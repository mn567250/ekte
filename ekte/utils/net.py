"""Host classification for relay URLs."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_LOOPBACK_NAMES = frozenset({"localhost", "0.0.0.0", "::1", "::", ""})
# Names that reach the machine running zing (or its LAN) from inside a container.
_LOCAL_NAMES = frozenset({"host.docker.internal", "host.containers.internal", "gateway.docker.internal"})


def url_host(base_url: str | None) -> str:
    """The lower-cased host name of a URL ('' when it has none or is unparsable)."""
    try:
        return (urlsplit(str(base_url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_loopback_host(host: str) -> bool:
    """True for this machine's own addresses (localhost, 127.x, ::1, *.localhost).

    A DNS name that merely starts with "127." (``127.example.com``) is a public
    host, not loopback: only a real IPv4 address in 127.0.0.0/8 counts."""
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_local_host(base_url: str | None) -> bool:
    """True when a relay URL points at this machine or a private network.

    Such endpoints are usually self-hosted models (llama.cpp, Ollama, vLLM, LM
    Studio) on modest hardware, so requests to them get more time.
    """
    host = url_host(base_url)
    if not host:
        return False
    if is_loopback_host(host) or host in _LOCAL_NAMES or host.endswith((".local", ".lan", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local
