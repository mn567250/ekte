"""Relays and providers as endpoints: base URLs, and relays saved by the user.

The web UI's relay configuration starts from a list of endpoints: the providers
of the knowledge base (with the base URLs from their ``base_url_hints``) and the
relays the user saved. A saved relay is an ordinary kb.db provider entry — a
``display_name`` and one ``base_url_hints`` URL, no models, ``origin =
"relay"`` — so it needs no schema change and older zing versions read it too.

``base_url_hints`` are written for the reader (they also hold bare hosts, path
fragments, URL templates and full endpoint URLs); :func:`base_urls` keeps only
the ones a relay client can use as its ``base_url``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from zing.knowledge import store
from zing.knowledge.loader import load_knowledge_base
from zing.knowledge.schema import ProviderProfile

RELAY_ORIGIN = "relay"
MAX_NAME = 64
MAX_URL = 500

# Endpoint paths a client appends to its base URL; a hint that ends in one is
# reduced to the base URL in front of it.
_ENDPOINT_SUFFIXES = ("/chat/completions", "/completions", "/messages", "/responses", "/embeddings", "/rerank")
_URL_RE = re.compile(r"^https?://[^\s/?#]+[^\s]*$", re.IGNORECASE)


class RelayError(ValueError):
    """A relay that cannot be saved; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def normalize_url(url: str) -> str | None:
    """``url`` as a base URL (endpoint suffix and trailing slashes removed), or
    None when it is not an absolute http(s) URL or still holds a placeholder."""
    url = (url or "").strip()
    if not _URL_RE.match(url) or "{" in url or "REGION" in url:
        return None
    url = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    for suffix in _ENDPOINT_SUFFIXES:
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    return url if _URL_RE.match(url) else None


def base_urls(provider: ProviderProfile) -> list[str]:
    """The provider's usable base URLs, in hint order, without duplicates."""
    out: list[str] = []
    for hint in provider.base_url_hints:
        url = normalize_url(hint)
        if url and url not in out:
            out.append(url)
    return out


def is_relay(provider: ProviderProfile, entry: dict[str, Any] | None = None) -> bool:
    """A relay saved by the user, or any provider without models of its own."""
    return bool(entry and entry.get("origin") == RELAY_ORIGIN) or not provider.models


def slug(name: str) -> str:
    """A provider key for ``name``: lower-case ``[a-z0-9._-]``, or ``relay-<hash>``
    when nothing of the name is left (e.g. a name in Chinese)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    key = re.sub(r"[^a-z0-9._-]+", "-", ascii_name.lower()).strip("-._")[:64].rstrip("-._")
    if not key:
        key = "relay-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return key


def add_relay(name: str, base_url: str) -> dict[str, Any]:
    """Save a relay under ``name`` in kb.db; returns what the UI shows.

    Raises :class:`RelayError` (400 for bad input, 409 when the name is taken).
    """
    name = " ".join(str(name or "").split())
    if not name or len(name) > MAX_NAME:
        raise RelayError(400, f"name must be 1-{MAX_NAME} characters")
    url = normalize_url(str(base_url or "")[:MAX_URL])
    if not url:
        raise RelayError(400, "base_url must be an http:// or https:// URL")
    key = slug(name)
    # the complete set: a switched-off provider still owns its key and URLs
    knowledge = load_knowledge_base(full=True)
    taken = knowledge.providers.get(key)
    if taken is not None or store.find("provider", key) is not None:
        label = taken.display_name if taken is not None and taken.display_name else key
        raise RelayError(409, f"the name {name!r} is already used by {label!r}; choose another name")
    for prov in knowledge.providers.values():
        if url in base_urls(prov):
            raise RelayError(409, f"{url} is already in the knowledge base as {prov.display_name or prov.provider!r}")
    body = {"display_name": name, "base_url_hints": [url]}
    entry_id = store.upsert("provider", key, body, origin=RELAY_ORIGIN)
    return {"provider": key, "display_name": name, "base_url": url, "entry_id": entry_id}
