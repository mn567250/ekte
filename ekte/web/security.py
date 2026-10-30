"""Local-only hardening for `zing serve`.

The web UI has no authentication on purpose: it is a single-user tool that
only ever listens on the loopback interface. "Only reachable from this machine"
is not enough on its own, though — any website open in the same browser can
still aim requests at ``http://localhost:<port>``. This module closes those
paths:

* **Bind address** (:func:`resolve_bind`): loopback only. The one exception is
  a container, where the server must listen on the container's interfaces for
  a published port to reach it; that needs an explicit opt-in
  (``ZING_CONTAINER=1``) *and* a detected container runtime, and the port is
  expected to be published to the host's loopback (``-p 127.0.0.1:8000:8000``).
* **Host header allowlist** (DNS rebinding): a hostile page can point its own
  domain at 127.0.0.1 and then read and write the local API as same-origin.
  Only ``localhost``, ``127.0.0.1`` and ``[::1]`` (plus ``ZING_ALLOWED_HOSTS``)
  are served; the port is not checked, so any published host port works.
* **Origin check** (CSRF): state-changing requests carrying a foreign
  ``Origin`` — or ``Sec-Fetch-Site: cross-site`` — are refused.
* **JSON only**: a state-changing request with a body must be
  ``application/json``. Browsers can send ``text/plain`` cross-site without a
  CORS preflight; requiring JSON forces that preflight, which zing never
  answers (it sends no CORS headers).
* **Response headers**: no framing (clickjacking), no MIME sniffing, no
  referrer leaks.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
]


class BindError(ValueError):
    """The requested bind address is not allowed."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def in_container() -> bool:
    """Best-effort detection of a Docker / Podman / Kubernetes container."""
    return (
        Path("/.dockerenv").exists()
        or Path("/run/.containerenv").exists()
        or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
    )


def resolve_bind(host: str | None, port: int | None) -> tuple[str, int]:
    """The (host, port) `zing serve` may bind.

    ``--host``/``--port`` win, then ``ZING_HOST``/``ZING_PORT``, then
    ``127.0.0.1:8000``. A non-loopback host is refused unless
    ``ZING_CONTAINER=1`` is set and a container runtime is detected.
    """
    chosen = (host or os.environ.get("ZING_HOST") or "127.0.0.1").strip()
    raw_port = port if port is not None else os.environ.get("ZING_PORT") or 8000
    try:
        chosen_port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise BindError(f"invalid port: {raw_port!r}") from exc
    if not 0 < chosen_port < 65536:
        raise BindError(f"invalid port: {chosen_port}")
    if chosen.strip("[]") in LOOPBACK_HOSTS:
        return chosen.strip("[]"), chosen_port
    if not _truthy(os.environ.get("ZING_CONTAINER")):
        raise BindError(
            f"refusing to bind {chosen}: zing serve listens on loopback only "
            "(127.0.0.1, ::1, localhost). Inside a container, set ZING_CONTAINER=1 "
            "and publish the port to the host's loopback, e.g. -p 127.0.0.1:8000:8000."
        )
    if not in_container():
        raise BindError(
            f"refusing to bind {chosen}: ZING_CONTAINER=1 is set but no container "
            "runtime was detected (/.dockerenv, /run/.containerenv or Kubernetes)."
        )
    return chosen, chosen_port


def allowed_hosts() -> frozenset[str]:
    extra = {
        h.strip().lower().strip("[]")
        for h in (os.environ.get("ZING_ALLOWED_HOSTS") or "").split(",")
        if h.strip()
    }
    return LOOPBACK_HOSTS | extra


def _hostname(netloc: str) -> str | None:
    """Hostname of a ``host[:port]`` value, lower-cased, IPv6 brackets removed."""
    try:
        name = urlsplit("//" + netloc).hostname
    except ValueError:
        return None
    return name.lower() if name else None


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class LocalOnlyMiddleware:
    """Pure ASGI middleware (streaming-safe) enforcing the rules above."""

    def __init__(self, app: ASGIApp, hosts: frozenset[str] | None = None) -> None:
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        problem = self._check(scope.get("method", "GET").upper(), headers)
        if problem is not None:
            status, message = problem
            await _reject(send, status, message)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers") or []}
                extra = [(k, v) for k, v in _SECURITY_HEADERS if k not in existing]
                message["headers"] = list(message.get("headers") or []) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _check(self, method: str, headers: dict[str, str]) -> tuple[int, str] | None:
        hosts = self.hosts if self.hosts is not None else allowed_hosts()
        host_header = headers.get("host", "")
        if _hostname(host_header) not in hosts:
            return 421, "unknown host: zing serve only answers to localhost"
        if method not in _UNSAFE_METHODS:
            return None
        if headers.get("sec-fetch-site", "").lower() in ("cross-site", "same-site"):
            return 403, "cross-site request refused"
        origin = headers.get("origin")
        if origin is not None:
            parts = urlsplit(origin) if origin != "null" else None
            if parts is None or parts.scheme not in ("http", "https") or (
                parts.netloc.lower() != host_header.lower()
            ):
                return 403, "cross-origin request refused"
        has_body = headers.get("transfer-encoding") or (headers.get("content-length") or "0") != "0"
        if has_body:
            ctype = headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return 415, "request body must be application/json"
        return None


async def _reject(send: Send, status: int, message: str) -> None:
    body = ('{"error": "' + message.replace('"', "'") + '"}').encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                    *_SECURITY_HEADERS],
    })
    await send({"type": "http.response.body", "body": body})
