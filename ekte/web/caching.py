"""HTTP compression and browser caching for the web UI's pages and assets.

* **Compression** (:class:`CompressionMiddleware`): gzip for every response of
  at least 1 KiB that the client accepts it for, except Server-Sent Events,
  which must reach the browser event by event.
* **Precompression** (:func:`encoded_response`): cached bodies (pages,
  ``/locales.js``) are gzipped once, when built, and served as such; the
  middleware leaves a response that already has a ``Content-Encoding`` alone.
* **Versioned asset URLs** (:func:`html_page`): pages are served with their
  local script / stylesheet references rewritten to ``…?v=<content hash>``.
  Hashes and rewritten pages are cached, keyed on file mtime and size, so an
  edited file shows up on the next page load without a restart.
* **Cache-Control** (:class:`CachedStaticFiles`): an asset requested with its
  current ``?v=`` hash is ``immutable`` for a year (a new version gets a new
  URL); without it (or with a stale one) it is ``no-cache``, i.e. revalidated
  with ETag / Last-Modified on every use. Pages themselves are ``no-cache``.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from starlette.datastructures import Headers, QueryParams
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

_STATIC = Path(__file__).parent / "static"
_V2 = _STATIC / "v2"

# Top-level scripts served by their own routes (see create_app). /locales.js is
# generated, not a file, and is left unversioned here.
ROOT_ASSETS = ("i18n.js", "lang.js", "icons.js", "perf.js", "secretfield.js")
_V2_PREFIX = "/v2/static/"

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

# Responses smaller than this are not worth compressing.
GZIP_MINIMUM_SIZE = 1024

# Server-Sent Events: never compressed (gzip would hold events back in its
# buffer). Newer Starlette also skips text/event-stream by itself; matching
# the paths keeps that true for every supported version.
_SSE_PATH = re.compile(r"^/api/(?:audit/stream|jobs/[^/]+/events)$")


class CompressionMiddleware:
    """Starlette's GZipMiddleware, bypassed for the SSE endpoints."""

    def __init__(self, app: ASGIApp, minimum_size: int = GZIP_MINIMUM_SIZE) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Clients refusing gzip (also `gzip;q=0`, which the middleware's substring
        # check would miss) skip it, as encoded_response does.
        if (
            scope["type"] == "http"
            and not _SSE_PATH.match(scope.get("path", ""))
            and accepts_gzip(Headers(scope=scope))
        ):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


# ----- precompressed bodies ----------------------------------------------- #
def precompressed(body: bytes) -> bytes | None:
    """``body`` gzipped (once, by a caller that caches it), or None when it is
    too small to be worth compressing."""
    if len(body) < GZIP_MINIMUM_SIZE:
        return None
    return gzip.compress(body, compresslevel=9, mtime=0)


def accepts_gzip(request_headers: Headers) -> bool:
    """Whether Accept-Encoding allows gzip (an explicit ``gzip;q=0`` refuses it,
    even next to ``*``)."""
    allowed = None
    for part in request_headers.get("accept-encoding", "").split(","):
        coding, _, params = part.partition(";")
        coding = coding.strip().lower()
        if coding not in ("gzip", "x-gzip", "*"):
            continue
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
                if not 0 <= q <= 1:  # also nan
                    q = 0.0
        if coding == "*":
            if allowed is None:
                allowed = q > 0
        else:
            return q > 0
    return bool(allowed)


def gzip_etag(etag: str) -> str:
    """The ETag of the gzipped representation: ``"tag"`` -> ``"tag-gz"``."""
    return etag[:-1] + '-gz"' if etag.endswith('"') else etag + "-gz"


def encoded_response(
    scope: Scope | None,
    body: bytes,
    etag: str,
    gz: bytes | None,
    *,
    media_type: str,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    """``body`` (or its precompressed ``gz``, when the client accepts gzip) with
    an ETag per encoding; a 304 when If-None-Match has the requested one, or,
    for a gzip request, the identity one (identity bytes suit any client; the
    gzip ones must not be revalidated for a client that refused gzip)."""
    out = dict(headers or {})
    req = Headers(scope=scope) if scope is not None else Headers()
    tags: tuple[str, ...] = (etag,)
    if gz is not None:
        vary = [v.strip() for v in out.get("Vary", "").split(",") if v.strip()]
        out["Vary"] = ", ".join([*vary, "Accept-Encoding"])
        if accepts_gzip(req):
            body, tags = gz, (gzip_etag(etag), etag)
            out["Content-Encoding"] = "gzip"
    out["ETag"] = tags[0]
    if scope is not None and status_code == 200:
        matched = next((t for t in tags if _etag_matches(req, t)), None)
        if matched is not None:
            out.pop("Content-Encoding", None)
            # "*" matches both; otherwise echo the representation the client has
            out["ETag"] = tags[0] if req.get("if-none-match", "").strip() == "*" else matched
            return Response(status_code=304, headers=out)
    return Response(body, status_code=status_code, media_type=media_type, headers=out)


# ----- content hashes ------------------------------------------------------ #
# (mtime_ns, ctime_ns, size, inode): ctime and inode also change on an edit or
# an atomic replace, which narrows the window of a same-size edit within one
# mtime tick going unnoticed.
_Stamp = tuple[int, int, int, int]
_hashes: dict[Path, tuple[_Stamp, str]] = {}


def _stamp(st: os.stat_result) -> _Stamp:
    return st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino


def content_hash(path: Path, st: os.stat_result | None = None) -> str:
    """Short hash of a file's content, recomputed only when the file changes."""
    stamp = _stamp(st if st is not None else path.stat())
    cached = _hashes.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    _hashes[path] = (stamp, digest)
    return digest


def asset_file(url_path: str) -> Path | None:
    """The local file behind a versionable asset URL, or None."""
    if url_path.startswith(_V2_PREFIX):
        rel = url_path[len(_V2_PREFIX):]
        if not rel or ".." in rel.split("/") or "\\" in rel:
            return None
        candidate = _V2 / rel
    elif url_path[1:] in ROOT_ASSETS:
        candidate = _STATIC / url_path[1:]
    else:
        return None
    return candidate if candidate.is_file() else None


# ----- pages ---------------------------------------------------------------- #
# src="/…" / href="/…" with no query or fragment yet.
_REF = re.compile(r"""(?P<pre>\b(?:src|href)=)(?P<q>["'])(?P<url>/[^"'?#\s<>]+)(?P=q)""")

# page -> (stamps of page + referenced assets, referenced asset paths, body, etag, gzipped body)
_Page = tuple[tuple[_Stamp, ...], tuple[Path, ...], bytes, str, bytes | None]
_pages: dict[Path, _Page] = {}


def _stamps(paths: tuple[Path, ...]) -> tuple[_Stamp, ...] | None:
    try:
        return tuple(_stamp(p.stat()) for p in paths)
    except OSError:
        return None


def _render(page: Path) -> _Page:
    st = page.stat()
    html = page.read_text(encoding="utf-8")
    deps: list[Path] = []
    stamps: list[_Stamp] = [_stamp(st)]

    def version(m: re.Match[str]) -> str:
        file = asset_file(m["url"])
        if file is None:
            return m[0]
        fst = file.stat()
        deps.append(file)
        stamps.append(_stamp(fst))
        return f"{m['pre']}{m['q']}{m['url']}?v={content_hash(file, fst)}{m['q']}"

    body = _REF.sub(version, html).encode("utf-8")
    etag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
    return tuple(stamps), tuple(deps), body, etag, precompressed(body)


def _etag_matches(request_headers: Headers, etag: str) -> bool:
    inm = request_headers.get("if-none-match")
    if not inm:
        return False
    if inm.strip() == "*":
        return True
    return etag in [t.strip().removeprefix("W/") for t in inm.split(",")]


def html_page(page: Path, scope: Scope | None = None, status_code: int = 200) -> Response:
    """An HTML page with versioned asset URLs; ``no-cache`` with an ETag."""
    cached = _pages.get(page)
    if cached is None or _stamps((page, *cached[1])) != cached[0]:
        cached = _render(page)
        _pages[page] = cached
    _, _, body, etag, gz = cached
    return encoded_response(
        scope, body, etag, gz, media_type="text/html", status_code=status_code,
        headers={"Cache-Control": NO_CACHE},
    )


# ----- assets --------------------------------------------------------------- #
def _requested_version(scope: Scope) -> str | None:
    return QueryParams(scope.get("query_string", b"")).get("v")


class CachedStaticFiles(StaticFiles):
    """StaticFiles (ETag / Last-Modified / 304) plus the Cache-Control policy above."""

    def file_response(
        self,
        full_path: Any,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        version = _requested_version(scope)
        current = content_hash(Path(full_path), stat_result) if version else None
        response.headers["Cache-Control"] = IMMUTABLE if version and version == current else NO_CACHE
        return response

    def asset(self, name: str, scope: Scope, media_type: str | None = None) -> Response:
        """A file directly in this directory (for routes outside a mount)."""
        full_path = Path(str(self.directory)) / name
        response = self.file_response(full_path, full_path.stat(), scope)
        if media_type is not None and response.status_code == 200:
            response.headers["content-type"] = media_type
        return response
