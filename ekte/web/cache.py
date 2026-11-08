"""The response cache of the web UI's widget endpoints (JSON GET answers).

One caching layer for every widget endpoint (:func:`cached_endpoint`):

* **Key** (:func:`cache_key`): ``json([endpoint, canonical params, data
  version, knowledge-base version, EXTRACT_VERSION, database])``. The data
  version (:func:`ekte.web.history.data_version`) is a counter stored in the
  history database and bumped in the same transaction as every write, from any
  process (a CLI audit included), so a write drops every cached answer. There
  is no time slot: an endpoint whose answer depends on the clock (a relative
  range such as "the last 7 days", or "up to now") resolves it to absolute
  bounds before keying (``prepare``).
* **LRU + single-flight** (:class:`ResponseCache`): bounded, thread-safe (the
  endpoints run in the thread pool), and concurrent misses on one key wait for
  a single computation. Errors are never cached.
* **HTTP**: answers carry an ``ETag`` (a hash of the key and the ekte version)
  and ``Cache-Control: no-cache``, so the browser revalidates on every use; a
  request whose ``If-None-Match`` matches gets ``304 Not Modified`` without
  anything being computed.
"""

from __future__ import annotations

import collections
import hashlib
import json
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

DEFAULT_SIZE = 256
NO_CACHE = "no-cache"


def kb_version() -> str:
    """The knowledge-base fingerprint answers depend on (relay grouping).

    TODO(#119): return the relay map's knowledge-base version once it exists.
    """
    return ""


def canonical_params(params: QueryParams | Mapping[str, Any] | Iterable[tuple[str, Any]]) -> list[
        tuple[str, str]]:
    """The parameters as sorted ``(key, value)`` pairs: values stripped of
    surrounding whitespace, empty ones dropped; the values of a repeated key
    keep their order (it can matter, e.g. which series come first)."""
    if isinstance(params, QueryParams):
        items: Iterable[tuple[str, Any]] = params.multi_items()
    elif isinstance(params, Mapping):
        items = params.items()
    else:
        items = params
    pairs: list[tuple[str, str]] = []
    for key, value in items:
        values = value if isinstance(value, (list, tuple)) else [value]
        for v in values:
            text = "" if v is None else str(v).strip()
            if text:
                pairs.append((str(key), text))
    return sorted(pairs, key=lambda kv: kv[0])  # stable: repeated keys keep their order


def cache_key(endpoint: str, params: Iterable[tuple[str, str]]) -> str:
    """The cache key of one answer (see the module docstring)."""
    from ekte.web import analytics_store, history

    return json.dumps(
        [endpoint, [list(p) for p in params], history.data_version(), kb_version(),
         analytics_store.EXTRACT_VERSION, str(history._db_path())],
        ensure_ascii=False, separators=(",", ":"),
    )


def etag_of(key: str) -> str:
    """A strong ETag for a key; the ekte version is part of it, so an upgrade
    never revalidates an answer of the old code."""
    from ekte import __version__

    digest = hashlib.sha256(f"{__version__}\n{key}".encode()).hexdigest()[:32]
    return f'"{digest}"'


def etag_matches(header: str | None, etag: str) -> bool:
    """Whether an ``If-None-Match`` header names ``etag`` (weak comparison, as
    RFC 9110 asks for ``If-None-Match``; ``*`` matches anything)."""
    if not header:
        return False
    want = etag.removeprefix("W/")
    for tag in header.split(","):
        tag = tag.strip()
        if tag == "*" or tag.removeprefix("W/") == want:
            return True
    return False


@dataclass
class _Flight:
    done: threading.Event = field(default_factory=threading.Event)
    value: Any = None
    error: BaseException | None = None


class ResponseCache:
    """A thread-safe LRU of computed answers with single-flight misses."""

    def __init__(self, maxsize: int = DEFAULT_SIZE) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self.maxsize = maxsize
        self._entries: collections.OrderedDict[str, Any] = collections.OrderedDict()
        self._flights: dict[str, _Flight] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        """The cached value of ``key``, else ``compute()``'s, stored.

        While one thread computes a key, other callers of the same key wait
        for it and get its value (or its exception: errors are not stored, so
        the next caller after it computes again).
        """
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = self._flights[key] = _Flight()
        if not leader:
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            return flight.value
        try:
            flight.value = compute()
        except BaseException as exc:
            flight.error = exc
            raise
        else:
            with self._lock:
                self._entries[key] = flight.value
                self._entries.move_to_end(key)
                while len(self._entries) > self.maxsize:
                    self._entries.popitem(last=False)
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()
        return flight.value


# The cache cached_endpoint() uses unless given another one. Keys hold the
# database path, so apps over different data directories can share it.
default_cache = ResponseCache()


def cached_endpoint(
    endpoint: str,
    *,
    cache: ResponseCache | None = None,
    errors: tuple[type[Exception], ...] = (),
    prepare: Callable[[QueryParams], QueryParams | Iterable[tuple[str, str]]] | None = None,
) -> Callable[[Callable[[QueryParams], Any]], Callable[[Request], Response]]:
    """Turn ``fn(params) -> JSON-able`` into a cached GET handler ``(request) -> Response``.

    ``fn`` gets the request's query parameters in canonical form (a
    :class:`QueryParams`: ``dict(params)`` for single values,
    ``params.getlist(name)`` for repeated ones) and must depend only on them
    and on the history database. ``prepare`` runs first, to resolve anything
    clock-relative into absolute values. An exception in ``errors`` answers
    400 ``{"error": str(exc)}`` and is not cached. Use it on a plain ``def``
    route (it blocks on SQLite)::

        @app.get("/api/analytics/summary")
        @cached_endpoint("analytics.summary", errors=(AnalyticsError,))
        def analytics_summary(params): ...
    """

    def decorate(fn: Callable[[QueryParams], Any]) -> Callable[[Request], Response]:
        def handler(request: Request) -> Response:
            params = QueryParams(canonical_params(request.query_params))
            if prepare is not None:
                params = QueryParams(canonical_params(prepare(params)))
            pairs = params.multi_items()
            key = cache_key(endpoint, pairs)
            etag = etag_of(key)
            headers = {"ETag": etag, "Cache-Control": NO_CACHE}
            if etag_matches(request.headers.get("if-none-match"), etag):
                return Response(status_code=304, headers=headers)
            try:
                body = (cache if cache is not None else default_cache).get_or_compute(
                    key, lambda: JSONResponse(fn(params)).body)
            except errors as exc:
                return JSONResponse({"error": str(exc)}, status_code=400,
                                    headers={"Cache-Control": "no-store"})
            return Response(body, media_type="application/json", headers=headers)

        # Not functools.wraps: FastAPI must see (request), not fn's signature.
        handler.__name__ = fn.__name__
        handler.__qualname__ = fn.__qualname__
        handler.__doc__ = fn.__doc__
        handler.__module__ = fn.__module__
        return handler

    return decorate
