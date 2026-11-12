"""What an HTTP proxy answered when it refused to open a tunnel to the relay.

Behind an HTTPS proxy every relay request starts with ``CONNECT host:443``.
When the proxy answers that with anything but 2xx, httpcore raises
``httpx.ProxyError("<status> <reason>")``, closes the connection without
reading the proxy's error page, and no httpx response hook ever runs: the
reply is not part of any response ekte sees. Yet it is the only evidence of
what went wrong, and it says *whose* problem it is — a ``407``/``403`` is the
proxy refusing, a ``502``/``503``/``504`` (typically after the proxy's own
connect timeout) is the proxy reporting that it could not reach the relay
host. Squid's ``X-Squid-Error`` header and error page even name the errno and
the address it tried.

Two observers keep it, both scoped to the call in flight
(:class:`ekte.perf.recorder.NetTrace`):

* :func:`observe` — httpcore's ``trace`` extension. The CONNECT request
  carries the real request's extensions, so its events reach the call's
  trace: its status, reason, headers and when they arrived. Public API, so
  this part works whatever httpcore's internals look like.
* :func:`install` — a thin tee on the network backend of each proxy transport
  of an ``httpx.AsyncClient``. It copies the bytes the proxy sends after a
  ``CONNECT`` (up to :data:`MAX_BODY_BYTES`) and, when the connection is
  closed on an error reply whose body has not fully arrived, reads the rest
  for at most :data:`BODY_GRACE_SEC`. That gives the error page's body. It
  relies on two private attributes (``AsyncClient._mounts`` and
  ``AsyncConnectionPool._network_backend``); where they are missing it does
  nothing and only the body is lost.

Nothing here changes what is sent or received: the tee hands every byte on
unchanged and only reads more on a connection httpcore is closing anyway.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ekte.perf.recorder import NetTrace

# The proxy's error body is kept up to this size (the rest is counted only).
MAX_BODY_BYTES = 64 * 1024
# How long a closing tunnel connection waits for the rest of an error body.
BODY_GRACE_SEC = 1.0
_HEAD_END = b"\r\n\r\n"
# Headers beyond this size are not a proxy reply ekte can parse.
_MAX_HEAD_BYTES = 64 * 1024


@dataclass
class ProxyReply:
    """The proxy's answer to one CONNECT."""

    target: str  # "host:port" the tunnel was asked for
    sent_at: float  # perf_counter when the CONNECT went out
    status: int | None = None
    reason: str | None = None
    http_version: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    at: float | None = None  # perf_counter when its headers arrived
    # The body as received (Transfer-Encoding undone), up to MAX_BODY_BYTES.
    body: bytes | None = None
    body_total: int = 0
    body_complete: bool = False

    @property
    def wait_ms(self) -> float | None:
        """How long the proxy took to answer the CONNECT, in ms."""
        if self.at is None or self.at < self.sent_at:
            return None
        return (self.at - self.sent_at) * 1000

    @property
    def refused_tunnel(self) -> bool:
        """True when the proxy answered with anything but 2xx."""
        return self.status is not None and not 200 <= self.status <= 299


# --------------------------------------------------------------------------- #
# Trace observer
# --------------------------------------------------------------------------- #
def observe(net: NetTrace, event_name: str, info: dict[str, Any]) -> None:
    """Keep the CONNECT reply from httpcore's trace events for ``net``."""
    _, _, event = event_name.partition(".")
    if event == "send_request_headers.started":
        request = info.get("request")
        method = getattr(request, "method", None)
        if method == b"CONNECT":
            net.proxy_reply = ProxyReply(target=_target(request), sent_at=time.perf_counter())
            net.awaiting_connect = True
        else:
            net.awaiting_connect = False
    elif event == "receive_response_headers.complete" and net.awaiting_connect:
        net.awaiting_connect = False
        reply = net.proxy_reply
        value = info.get("return_value")
        if reply is None or not isinstance(value, tuple) or len(value) < 4:
            return
        http_version, status, reason, headers = value[:4]
        reply.at = time.perf_counter()
        reply.status = status if isinstance(status, int) else None
        reply.reason = _text(reason)
        reply.http_version = _text(http_version)
        reply.headers = {(_text(k) or "").lower(): _text(v) or "" for k, v in headers or []}
        if reply.refused_tunnel and net.captures:
            # the call's own exchange (the request the tunnel was for) gets it
            net.captures[-1].proxy = reply
        _apply_wire(net)


def _target(request: Any) -> str:
    url = getattr(request, "url", None)
    target = getattr(url, "target", b"") if url is not None else b""
    return _text(target) or "?"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


# --------------------------------------------------------------------------- #
# Body tee on proxy connections
# --------------------------------------------------------------------------- #
class _Wire:
    """The bytes a proxy sent in answer to one CONNECT, as they arrived."""

    def __init__(self) -> None:
        self.raw = bytearray()
        self.total = 0
        self.closed_by_peer = False

    def feed(self, data: bytes) -> None:
        self.total += len(data)
        room = _MAX_HEAD_BYTES + MAX_BODY_BYTES - len(self.raw)
        if room > 0:
            self.raw += data[:room]

    def head_and_body(self) -> tuple[bytes, bytes] | None:
        cut = self.raw.find(_HEAD_END)
        if cut < 0:
            return None
        return bytes(self.raw[:cut]), bytes(self.raw[cut + len(_HEAD_END):])

    def status(self) -> int | None:
        parts = self.head_and_body()
        if parts is None:
            return None
        line = parts[0].split(b"\r\n", 1)[0].split(b" ", 2)
        try:
            return int(line[1])
        except (IndexError, ValueError):
            return None

    def _headers(self) -> dict[str, str]:
        parts = self.head_and_body()
        out: dict[str, str] = {}
        if parts is None:
            return out
        for raw_line in parts[0].split(b"\r\n")[1:]:
            name, sep, value = raw_line.partition(b":")
            if sep:
                out[name.strip().decode("latin-1").lower()] = value.strip().decode("latin-1")
        return out

    def body(self) -> tuple[bytes, int, bool]:
        """The body (chunked encoding undone), its full size as far as known,
        and whether all of it arrived."""
        parts = self.head_and_body()
        if parts is None:
            return b"", 0, False
        head_len = len(parts[0]) + len(_HEAD_END)
        raw = parts[1]
        headers = self._headers()
        if "chunked" in headers.get("transfer-encoding", "").lower():
            return _dechunk(raw)
        length = _int(headers.get("content-length"))
        received = self.total - head_len
        if length is not None:
            return raw[:length][:MAX_BODY_BYTES], length, received >= length
        # no length: the body ends when the proxy closes the connection
        return raw[:MAX_BODY_BYTES], received, self.closed_by_peer

    def body_missing(self) -> bool:
        """True when an error reply's body has not fully arrived yet."""
        status = self.status()
        if status is None or 200 <= status <= 299 or self.closed_by_peer:
            return False
        if len(self.raw) >= _MAX_HEAD_BYTES + MAX_BODY_BYTES:
            return False
        _, _, complete = self.body()
        return not complete


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _dechunk(raw: bytes) -> tuple[bytes, int, bool]:
    out = bytearray()
    pos = 0
    while True:
        eol = raw.find(b"\r\n", pos)
        if eol < 0:
            return bytes(out[:MAX_BODY_BYTES]), len(out), False
        size = _int_hex(raw[pos:eol].split(b";", 1)[0])
        if size is None:
            return bytes(out[:MAX_BODY_BYTES]), len(out), False
        if size == 0:
            return bytes(out[:MAX_BODY_BYTES]), len(out), True
        start = eol + 2
        chunk = raw[start:start + size]
        out += chunk
        if len(chunk) < size:
            return bytes(out[:MAX_BODY_BYTES]), len(out), False
        pos = start + size + 2


def _int_hex(value: bytes) -> int | None:
    try:
        return int(value.strip(), 16)
    except ValueError:
        return None


def _apply_wire(net: NetTrace) -> None:
    """Put the tee's body on the call's CONNECT reply (once both exist)."""
    reply, wire = net.proxy_reply, net.proxy_wire
    if reply is None or wire is None or not reply.refused_tunnel:
        return
    body, total, complete = wire.body()
    reply.body, reply.body_total, reply.body_complete = body, total, complete


class _TeeStream:
    """A network stream to a proxy that copies the reply to a CONNECT."""

    def __init__(self, inner: Any, net: NetTrace) -> None:
        self._inner = inner
        self._net = net
        self._wire: _Wire | None = None
        self._done = False  # the tunnel is up (or the stream is TLS to the relay)

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        data = await self._inner.read(max_bytes, timeout)
        wire = self._wire
        if wire is not None and not self._done:
            if data:
                wire.feed(data)
            else:
                wire.closed_by_peer = True
        return data

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        if not self._done and buffer.startswith(b"CONNECT "):
            self._wire = _Wire()
            self._net.proxy_wire = self._wire
        await self._inner.write(buffer, timeout)

    async def aclose(self) -> None:
        wire = self._wire
        if wire is not None and not self._done:
            # httpcore closes the connection right after an error reply's
            # headers: read what is left of its body first, briefly.
            deadline = time.perf_counter() + BODY_GRACE_SEC
            try:
                while wire.body_missing():
                    left = deadline - time.perf_counter()
                    if left <= 0:
                        break
                    data = await self._inner.read(MAX_BODY_BYTES, left)
                    if not data:
                        wire.closed_by_peer = True
                        break
                    wire.feed(data)
            except Exception:  # a reset or timeout ends the body: keep what came
                pass
            _apply_wire(self._net)
        await self._inner.aclose()

    async def start_tls(self, ssl_context: Any, server_hostname: str | None = None,
                        timeout: float | None = None) -> Any:
        stream = await self._inner.start_tls(ssl_context, server_hostname, timeout)
        if self._wire is not None:
            # TLS after a CONNECT: the tunnel is up, the rest is the relay's
            self._done = True
            return stream
        # TLS to an https:// proxy: the CONNECT goes inside it
        tee = _TeeStream(stream, self._net)
        return tee

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)


class _TeeBackend:
    """A network backend whose connections to the proxy copy CONNECT replies."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None,
                          socket_options: Any = None) -> Any:
        stream = await self._inner.connect_tcp(
            host, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )
        from ekte.perf.recorder import current_net_trace

        net = current_net_trace()
        return stream if net is None else _TeeStream(stream, net)

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Any = None) -> Any:
        return await self._inner.connect_unix_socket(path, timeout=timeout,
                                                     socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def install(client: Any) -> int:
    """Tee the network backend of every HTTP(S)-proxy transport of an
    ``httpx.AsyncClient``; returns how many it tees (0 without a proxy, or
    when httpx/httpcore no longer have the attributes it uses)."""
    try:
        import httpcore
        import httpx
    except ImportError:  # pragma: no cover - httpx is a dependency
        return 0
    mounts = getattr(client, "_mounts", None)
    if not isinstance(mounts, dict):
        return 0
    teed = 0
    for transport in mounts.values():
        if not isinstance(transport, httpx.AsyncHTTPTransport):
            continue
        pool = getattr(transport, "_pool", None)
        if not isinstance(pool, httpcore.AsyncHTTPProxy):
            continue
        backend = getattr(pool, "_network_backend", None)
        if backend is None or isinstance(backend, _TeeBackend):
            continue
        pool._network_backend = _TeeBackend(backend)
        teed += 1
    return teed
