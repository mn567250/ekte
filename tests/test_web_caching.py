"""Compression and browser caching of the web UI (ekte/web/caching.py)."""

from __future__ import annotations

import gzip
import os
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402
from starlette.responses import PlainTextResponse, StreamingResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from ekte.web import caching  # noqa: E402
from ekte.web.server import create_app  # noqa: E402

IMMUTABLE = "public, max-age=31536000, immutable"
_REF = re.compile(r'(?:src|href)="(/[^"]+)"')


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def _versioned(html: str) -> list[str]:
    return [u for u in _REF.findall(html) if "?v=" in u]


@pytest.mark.parametrize(
    "path", ["/", "/history", "/watches", "/kb", "/analytics", "/accessibility"]
)
def test_v2_pages_version_their_assets_and_are_revalidated(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-type"].startswith("text/html")
    urls = _versioned(r.text)
    assert any(u.startswith("/static/ekte.css?v=") for u in urls)
    assert any(u.startswith("/i18n.js?v=") for u in urls)
    # every local script / stylesheet is versioned; the generated /locales.js is not
    assets = [u for u in _REF.findall(r.text) if re.search(r"\.(?:js|css)(?:\?|$)", u)]
    assert set(assets) - set(urls) <= {"/locales.js"}
    # conditional request -> 304 with the same caching policy
    again = client.get(path, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"
    assert again.headers["x-frame-options"] == "DENY"


def test_old_addresses_and_spa_fallback_are_versioned_too(client):
    # /v2/history redirects to /history (followed here)
    for path in ("/", "/history", "/v2/history", "/v2/some/deep/link", "/some/deep/link"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"
        assert _versioned(r.text), path


def test_versioned_assets_are_immutable_and_unversioned_ones_revalidate(client):
    urls = _versioned(client.get("/").text)
    assert len(urls) >= 8
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["cache-control"] == IMMUTABLE, url
        not_modified = client.get(url, headers={"If-None-Match": r.headers["etag"]})
        assert not_modified.status_code == 304, url
        assert not_modified.headers["cache-control"] == IMMUTABLE
        bare = client.get(url.split("?")[0])
        assert bare.headers["cache-control"] == "no-cache", url
        # a stale (or forged) version must not be pinned for a year
        stale = client.get(url.split("?")[0] + "?v=000000000000")
        assert stale.headers["cache-control"] == "no-cache", url


def test_root_scripts_keep_their_type_and_answer_304(client):
    for name in caching.ROOT_ASSETS:
        r = client.get(f"/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/javascript")
        assert client.get(f"/{name}", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_missing_static_file_is_still_a_plain_404(client):
    r = client.get("/static/nope.js?v=abc")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/plain")


def test_responses_are_gzipped_when_large_enough(client):
    page = client.get("/")
    assert page.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in page.headers["vary"].lower()
    assert client.get("/locales.js").headers["content-encoding"] == "gzip"
    assert client.get("/api/kb").headers["content-encoding"] == "gzip"
    # tiny responses are left alone
    assert "content-encoding" not in client.get("/api/health").headers
    # and nothing is compressed for a client that does not ask for it
    plain = client.get("/", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers


def test_security_checks_still_run_first(client):
    r = client.get("/", headers={"Host": "evil.example"})
    assert r.status_code == 421
    assert "content-encoding" not in r.headers


def _events() -> StreamingResponse:
    async def gen():
        for i in range(3):
            yield f"data: {'x' * 2000} {i}\n\n"

    # text/plain on purpose: the path alone must keep SSE uncompressed, whatever
    # the installed Starlette's content-type exclusions are.
    return StreamingResponse(gen(), media_type="text/plain")


def _big(_request) -> PlainTextResponse:
    return PlainTextResponse("y" * 5000)


def test_sse_paths_are_never_compressed():
    app = Starlette(routes=[
        Route("/api/jobs/{job_id}/events", lambda _r: _events()),
        Route("/api/audit/stream", lambda _r: _events(), methods=["POST"]),
        Route("/api/other", _big),
    ])
    c = TestClient(caching.CompressionMiddleware(app))
    for method, path in (("GET", "/api/jobs/abc/events"), ("POST", "/api/audit/stream")):
        r = c.request(method, path)
        assert "content-encoding" not in r.headers, path
        assert r.text.count("data: ") == 3
    assert c.get("/api/other").headers["content-encoding"] == "gzip"


def test_edited_files_get_a_new_version_without_restart(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "v2").mkdir(parents=True)
    asset = static / "v2" / "a.css"
    asset.write_text("body{}")
    page = static / "v2" / "p.html"
    page.write_text('<link rel="stylesheet" href="/static/a.css"><a href="/">x</a>')
    monkeypatch.setattr(caching, "_STATIC", static)
    monkeypatch.setattr(caching, "_V2", static / "v2")

    first = caching.html_page(page).body.decode()
    v1 = re.search(r"a\.css\?v=(\w+)", first)
    assert v1 and 'href="/"' in first
    assert caching.html_page(page).body.decode() == first  # cached

    asset.write_text("body{color:red}")
    st = asset.stat()
    os.utime(asset, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    second = caching.html_page(page).body.decode()
    v2 = re.search(r"a\.css\?v=(\w+)", second)
    assert v2 and v2[1] != v1[1]

    page.write_text('<script src="/static/a.css"></script>')
    st = page.stat()
    os.utime(page, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert "<script" in caching.html_page(page).body.decode()


def test_asset_file_stays_inside_the_static_dirs():
    assert caching.asset_file("/static/../../server.py") is None
    assert caching.asset_file("/static/") is None
    assert caching.asset_file("/locales.js") is None
    assert caching.asset_file("/i18n.js") == Path(caching._STATIC) / "i18n.js"


def _vary(r) -> set[str]:
    return {v.strip().lower() for v in r.headers.get("vary", "").split(",") if v.strip()}


def _raw_get(client, path: str, **headers: str):
    """GET without decoding the body, so its real Content-Encoding shows."""
    with client.stream("GET", path, headers=headers) as r:
        return r, b"".join(r.iter_raw())


@pytest.mark.parametrize(
    "path", ["/", "/", "/console", "/locales.js", "/locales.js?lang=de"]
)
def test_precompressed_bodies_decompress_to_the_identity_bytes(client, path):
    plain, identity = _raw_get(client, path, **{"Accept-Encoding": "identity"})
    assert plain.status_code == 200 and "content-encoding" not in plain.headers
    zipped, raw = _raw_get(client, path, **{"Accept-Encoding": "gzip, deflate"})
    assert zipped.headers["content-encoding"] == "gzip"
    # compressed once, not again by the middleware
    assert gzip.decompress(raw) == identity
    assert zipped.headers["content-length"] == str(len(raw))
    # one ETag per encoding; both responses vary on Accept-Encoding
    assert zipped.headers["etag"] == plain.headers["etag"][:-1] + '-gz"'
    assert "accept-encoding" in _vary(plain) and "accept-encoding" in _vary(zipped)
    assert (path == "/locales.js") == ("cookie" in _vary(zipped))
    # 304 with either ETag for a gzip client, echoing the one that matched; a
    # client refusing gzip must not be told to reuse the gzipped bytes
    cases = [
        ("gzip", plain.headers["etag"], 304),
        ("gzip", zipped.headers["etag"], 304),
        ("identity", plain.headers["etag"], 304),
        ("identity", zipped.headers["etag"], 200),
    ]
    for enc, tag, status in cases:
        r = client.get(path, headers={"Accept-Encoding": enc, "If-None-Match": f'"x", {tag}'})
        assert r.status_code == status, (enc, tag)
        assert "accept-encoding" in _vary(r)
        if status == 304:
            assert r.content == b"" and r.headers["etag"] == tag
            assert "content-encoding" not in r.headers


def test_refusing_gzip_is_honoured_by_the_middleware_too(client):
    for path in ("/locales.js", "/api/kb"):
        r, _ = _raw_get(client, path, **{"Accept-Encoding": "gzip;q=0, br"})
        assert r.status_code == 200 and "content-encoding" not in r.headers, path


def test_precompressed_bodies_are_built_once(client, monkeypatch):
    client.get("/")
    client.get("/locales.js")
    calls = []
    real = gzip.compress
    monkeypatch.setattr(gzip, "compress", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(3):
        assert client.get("/").headers["content-encoding"] == "gzip"
        assert client.get("/locales.js").headers["content-encoding"] == "gzip"
    assert not calls


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("gzip", True),
        ("GZip;q=0.5, br", True),
        ("x-gzip", True),
        ("*", True),
        ("", False),
        ("identity", False),
        ("br, deflate", False),
        ("gzip;q=0", False),
        ("gzip;q=0, *", False),
        ("*;q=0", False),
        ("gzip;q=bad", False),
        ("gzip;q=nan", False),
        ("gzip;q=inf", False),
    ],
)
def test_accepts_gzip(value, expected):
    assert caching.accepts_gzip(Headers({"accept-encoding": value})) is expected


def test_small_bodies_are_not_precompressed():
    assert caching.precompressed(b"x" * (caching.GZIP_MINIMUM_SIZE - 1)) is None
    r = caching.encoded_response(
        {"type": "http", "headers": [(b"accept-encoding", b"gzip")]},
        b"tiny", '"t"', None, media_type="text/plain",
    )
    assert r.body == b"tiny" and "content-encoding" not in r.headers and "vary" not in r.headers

