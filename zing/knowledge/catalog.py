"""The knowledge base as the web UI's Knowledge page lists it: models, providers
and relays, each as a complete set with an on/off state.

Every item carries a ``key`` — ``model:<provider>/<id>``, ``provider:<provider>``
or ``entry:<id>`` (the user's additions to a provider that is not their own) —
its ``source`` (``packaged:…``, ``kb_dir:…`` or ``kb.db:entry/<id>``), whether it
is the user's own (``yours``) and whether audits use it (``enabled``).

The lists come from two loads: the complete set (``full=True``: disabled kb.db
entries applied, switched-off items kept) and what audits use. An item is
enabled when the audit load has it from the same source. A switched-off entry
of the user's that replaced a packaged model names the source audits use
instead (``effective_source``).

:func:`set_enabled` switches one item: the user's own entries by their
``enabled`` column, everything else with the ``kb_disabled`` table (see
:mod:`zing.knowledge.store`).
"""

from __future__ import annotations

from typing import Any

from zing.knowledge import store
from zing.knowledge.loader import load_knowledge_base
from zing.knowledge.relays import RELAY_ORIGIN, base_urls, is_relay
from zing.knowledge.schema import KnowledgeBase

_ENTRY_PREFIX = "kb.db:entry/"


def _entry_id(source: str | None) -> int | None:
    if source and source.startswith(_ENTRY_PREFIX):
        try:
            return int(source[len(_ENTRY_PREFIX):])
        except ValueError:
            return None
    return None


def build(full: KnowledgeBase, effective: KnowledgeBase, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The page's three lists from the two loads and the kb.db entries."""
    by_id = {e["id"]: e for e in entries}
    models: list[dict[str, Any]] = []
    providers: list[dict[str, Any]] = []
    relays: list[dict[str, Any]] = []

    for prov in sorted(full.providers.values(), key=lambda p: p.provider):
        name = prov.provider
        src = full.provider_sources.get(name, "")
        entry = by_id.get(_entry_id(src) or -1)
        eff = effective.providers.get(name)
        prov_on = eff is not None and effective.provider_sources.get(name) == src
        item = {
            "key": f"provider:{name}",
            "provider": name,
            "display_name": prov.display_name or name,
            "base_urls": base_urls(prov),
            "model_count": len(prov.models),
            "source": src,
            "yours": entry is not None,
            "entry_id": entry["id"] if entry else None,
            "enabled": prov_on,
        }
        # your own entries go by their origin (a provider you imported without
        # models stays a provider); anything else without models is a relay
        relay = entry.get("origin") == RELAY_ORIGIN if entry is not None else is_relay(prov)
        (relays if relay else providers).append(item)

        for m in prov.models:
            key = f"{name}/{m.id}"
            msrc = full.model_sources.get(key, "")
            eff_src = effective.model_sources.get(key) if prov_on else None
            on = eff_src == msrc and eff is not None and any(x.id == m.id for x in eff.models)
            models.append({
                "key": f"model:{key}",
                "provider": name,
                "provider_name": prov.display_name or name,
                "id": m.id,
                "aliases": list(m.aliases),
                "kind": "embedding" if m.embedding_dimensions else "chat",
                "context_window_tokens": m.context_window_tokens,
                "max_output_tokens": m.max_output_tokens,
                "source": msrc,
                "yours": msrc.startswith(_ENTRY_PREFIX),
                "entry_id": _entry_id(msrc),
                "enabled": on,
                "provider_enabled": prov_on,
                "shadows": full.shadowed.get(key),
                # set when audits use another source for this id (yours is off)
                "effective_source": eff_src if eff_src and eff_src != msrc else None,
            })

    # the user's additions to a provider that is not their own: their own rows
    for e in entries:
        if e["kind"] != "provider" or e.get("origin") == RELAY_ORIGIN:
            continue
        name = e["provider"]
        if _entry_id(full.provider_sources.get(name)) == e["id"] or name not in full.providers:
            continue
        raw = e.get("body")
        body: dict[str, Any] = raw if isinstance(raw, dict) else {}
        prov = full.providers[name]
        providers.append({
            "key": f"entry:{e['id']}",
            "provider": name,
            "display_name": prov.display_name or name,
            "addition": True,
            "base_urls": [str(h) for h in body.get("base_url_hints") or []],
            "fingerprint_count": len(body.get("fingerprints") or []),
            "model_count": None,
            "source": f"{_ENTRY_PREFIX}{e['id']}",
            "yours": True,
            "entry_id": e["id"],
            "enabled": bool(e.get("enabled")) and name in effective.providers,
        })

    return {
        "models": models,
        "providers": providers,
        "relays": relays,
        "user_kb": effective.user_kb,
        "warnings": effective.warnings,
        "disabled": len(effective.disabled),
        "entry_count": len(entries),
    }


def catalog() -> dict[str, Any]:
    """:func:`build` for the knowledge base as it is now."""
    effective = load_knowledge_base()
    full = load_knowledge_base(full=True)
    entries = store.list_entries() if effective.user_kb else []
    return build(full, effective, entries)


class ToggleError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def set_enabled(key: str, enabled: bool) -> None:
    """Switch the item ``key`` on or off; :class:`ToggleError` when that is not possible."""
    effective = load_knowledge_base()
    if not effective.user_kb:
        raise ToggleError(409, "your kb.db is ignored (ZING_NO_USER_KB); nothing can be switched")
    kind, _, rest = str(key or "").partition(":")
    if kind == "entry":
        try:
            target = int(rest)
        except ValueError:
            raise ToggleError(400, f"bad key {key!r}") from None
        if not store.set_enabled(target, enabled):
            raise ToggleError(404, "not found")
        return
    full = load_knowledge_base(full=True)
    if kind == "provider":
        if rest not in full.providers:
            raise ToggleError(404, "not found")
        source, provider, model_id = full.provider_sources.get(rest, ""), rest, ""
    elif kind == "model":
        provider, _, model_id = rest.partition("/")
        prov = full.providers.get(provider)
        if not model_id or prov is None or not any(m.id == model_id for m in prov.models):
            raise ToggleError(404, "not found")
        source = full.model_sources.get(rest, "")
    else:
        raise ToggleError(400, f"bad key {key!r}")
    entry_id = _entry_id(source)
    if entry_id is not None:
        store.set_enabled(entry_id, enabled)
    else:
        store.set_item_enabled(kind, provider, model_id, enabled)
