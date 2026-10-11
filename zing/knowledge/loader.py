"""Load provider YAML profiles into a :class:`KnowledgeBase`.

Profiles ship inside the package under ``data/``. Users can drop additional or
override YAML files via ``--kb-dir`` (or the ``ZING_KB_DIR`` env var) without
forking the project, and add their own models in the web UI (stored in
``kb.db`` in the data directory, see :mod:`zing.knowledge.store`).

Layers, later ones winning:

1. packaged ``data/*.yaml``;
2. ``--kb-dir`` directories, then ``ZING_KB_DIR`` — a file for an existing
   ``provider:`` replaces that whole provider (unchanged behaviour);
3. the user's ``kb.db`` entries, merged per model and per fingerprint id (see
   :mod:`zing.knowledge.store`). Left out with ``include_user=False``, or
   ``ZING_NO_USER_KB=1``;
4. packaged / ``ZING_KB_DIR`` providers and models the user switched off in
   ``kb.db`` are removed (a provider with all its models). Also left out with
   ``include_user=False``. ``full=True`` skips this step and applies disabled
   entries too: the complete set, for listing it with on/off switches.

An edit (or a new kb.db entry) applies to the next call without a restart.
Merged results are cached, keyed on everything they are built from: the
``--kb-dir`` / ``ZING_KB_DIR`` files (path and content digest), the user-KB switch,
the kb.db location, the kb.db entries and switched-off items themselves (two
small queries per call),
so an import, edit, toggle or delete is picked up immediately. The packaged
profiles are immutable package data and parsed once per process. Every call
returns a deep copy, so callers may modify what they get.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from zing.knowledge.schema import (
    FingerprintProbe,
    KnowledgeBase,
    ModelProfile,
    ProviderProfile,
)
from zing.utils import yamlio

_DATA_PACKAGE = "zing.knowledge.data"


def _parse_provider(text: str, source: str) -> ProviderProfile:
    data = yamlio.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Knowledge profile {source} is not a YAML mapping")
    try:
        return ProviderProfile(**data)
    except Exception as exc:  # pragma: no cover - surfaced to the user
        raise ValueError(f"Invalid knowledge profile {source}: {exc}") from exc


@lru_cache(maxsize=1)
def _load_packaged() -> dict[str, tuple[ProviderProfile, str]]:
    """The packaged profiles, parsed once per process; copy the dict before changing it."""
    providers: dict[str, tuple[ProviderProfile, str]] = {}
    root = resources.files(_DATA_PACKAGE)
    for entry in root.iterdir():
        name = entry.name
        if not name.endswith((".yaml", ".yml")):
            continue
        text = entry.read_text(encoding="utf-8")
        profile = _parse_provider(text, name)
        providers[profile.provider] = (profile, f"packaged:{name}")
    return providers


def _load_dir(directory: Path) -> dict[str, tuple[ProviderProfile, str]]:
    providers: dict[str, tuple[ProviderProfile, str]] = {}
    if not directory.is_dir():
        return providers
    for path in sorted(directory.glob("*.y*ml")):
        profile = _parse_provider(path.read_text(encoding="utf-8"), str(path))
        providers[profile.provider] = (profile, f"kb_dir:{path}")
    return providers


def user_kb_enabled(include_user: bool | None = None) -> bool:
    """Whether kb.db entries apply: an explicit choice, else not ``ZING_NO_USER_KB``."""
    if include_user is not None:
        return include_user
    return (os.environ.get("ZING_NO_USER_KB") or "").strip().lower() not in ("1", "true", "yes", "on")


def entry_source(entry: dict[str, Any]) -> str:
    return f"kb.db:entry/{entry['id']}"


def entry_ref(entry: dict[str, Any]) -> dict[str, Any]:
    """The public, report-safe description of a kb.db entry."""
    return {
        "id": entry["id"],
        "kind": entry["kind"],
        "provider": entry["provider"],
        "model_id": entry.get("model_id"),
        "updated_ts": entry.get("updated_ts"),
        "origin": entry.get("origin"),
    }


def merge_fingerprints(
    base: list[FingerprintProbe], extra: list[FingerprintProbe]
) -> list[FingerprintProbe]:
    """Append ``extra`` by id: a new id is appended, a known id is replaced in place."""
    out = list(base)
    index = {fp.id: i for i, fp in enumerate(out)}
    for fp in extra:
        if fp.id in index:
            out[index[fp.id]] = fp
        else:
            index[fp.id] = len(out)
            out.append(fp)
    return out


def _union(base: list[str], extra: list[str]) -> list[str]:
    out = list(base)
    for item in extra:
        if item not in out:
            out.append(item)
    return out


def _entry_label(entry: dict[str, Any]) -> str:
    if entry["kind"] == "model":
        return f"kb.db entry {entry['id']} (model {entry['provider']}/{entry.get('model_id')})"
    return f"kb.db entry {entry['id']} (provider {entry['provider']})"


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return " ".join(line.strip() for line in text[:3])[:300]


def apply_user_entries(kb: KnowledgeBase, entries: list[dict[str, Any]]) -> None:
    """Merge enabled kb.db entries into ``kb`` in place (providers first, then models)."""
    for entry in entries:
        if not entry.get("enabled", True) or entry["kind"] != "provider":
            continue
        name = entry["provider"]
        body = entry.get("body")
        try:
            if not isinstance(body, dict):
                raise ValueError("stored body is not a JSON object")
            if name in kb.providers:
                existing = kb.providers[name]
                fps = [FingerprintProbe(**f) for f in body.get("fingerprints") or []]
                kb.providers[name] = existing.model_copy(update={
                    "fingerprints": merge_fingerprints(existing.fingerprints, fps),
                    "base_url_hints": _union(existing.base_url_hints, [str(h) for h in body.get("base_url_hints") or []]),
                    "relay_red_flags": _union(existing.relay_red_flags, [str(h) for h in body.get("relay_red_flags") or []]),
                })
            else:
                fields = {k: v for k, v in body.items() if k not in ("provider", "models")}
                kb.providers[name] = ProviderProfile(provider=name, models=[], **fields)
                kb.provider_sources[name] = entry_source(entry)
        except Exception as exc:
            kb.warnings.append(f"{_entry_label(entry)} skipped: {_short_error(exc)}")
            continue
        kb.entries[f"provider:{name}"] = entry_ref(entry)

    for entry in entries:
        if not entry.get("enabled", True) or entry["kind"] != "model":
            continue
        name, mid = entry["provider"], entry.get("model_id")
        body = entry.get("body")
        provider = kb.providers.get(name)
        if provider is None:
            kb.warnings.append(f"{_entry_label(entry)} skipped: provider {name!r} is not in the knowledge base")
            continue
        try:
            if not isinstance(body, dict):
                raise ValueError("stored body is not a JSON object")
            model = ModelProfile(**{**body, "id": mid})
        except Exception as exc:
            kb.warnings.append(f"{_entry_label(entry)} skipped: {_short_error(exc)}")
            continue
        key = f"{name}/{mid}"
        models = list(provider.models)
        for i, m in enumerate(models):
            if m.id == mid:
                kb.shadowed[key] = kb.model_sources.get(key) or kb.provider_sources.get(name, "")
                models[i] = model
                break
        else:
            models.append(model)
        kb.providers[name] = provider.model_copy(update={"models": models})
        kb.model_sources[key] = entry_source(entry)
        kb.entries[f"model:{key}"] = entry_ref(entry)


def apply_disabled(kb: KnowledgeBase, items: list[tuple[str, str, str]]) -> None:
    """Remove switched-off packaged / ``ZING_KB_DIR`` items from ``kb`` in place.

    The user's own entries are switched off by their ``enabled`` column, so an
    item whose source is a kb.db entry is left alone here.
    """
    for kind, name, mid in items:
        if kind == "provider":
            if name not in kb.providers or kb.provider_sources.get(name, "").startswith("kb.db:"):
                continue
            del kb.providers[name]
            kb.provider_sources.pop(name, None)
            prefix = f"{name}/"
            for mapping in (kb.model_sources, kb.shadowed):
                for key in [k for k in mapping if k.startswith(prefix)]:
                    del mapping[key]
            for key in [k for k in kb.entries if k == f"provider:{name}" or k.startswith(f"model:{prefix}")]:
                del kb.entries[key]
            kb.disabled.append(f"provider:{name}")
            continue
        provider = kb.providers.get(name)
        key = f"{name}/{mid}"
        if provider is None or kb.model_sources.get(key, "").startswith("kb.db:"):
            continue
        models = [m for m in provider.models if m.id != mid]
        if len(models) == len(provider.models):
            continue
        kb.providers[name] = provider.model_copy(update={"models": models})
        kb.model_sources.pop(key, None)
        kb.disabled.append(f"model:{key}")


_CACHE_SIZE = 8
_cache: OrderedDict[tuple[Any, ...], KnowledgeBase] = OrderedDict()
_cache_lock = threading.Lock()


def _dirs_key(dirs: list[Path]) -> tuple[Any, ...]:
    """The YAML files of ``dirs`` as they are now: path as given plus a content digest.

    Hashing the (small) files is far cheaper than parsing them, and unlike
    mtimes it cannot miss an edit.
    """
    out: list[Any] = []
    for directory in dirs:
        files: list[Any] = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.y*ml")):
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError as exc:
                    digest = f"unreadable:{exc.errno}"
                files.append((path.name, digest))
        out.append((str(directory), tuple(files)))
    return tuple(out)


def _entries_key(entries: list[dict[str, Any]]) -> str:
    return json.dumps(entries, sort_keys=True, ensure_ascii=False, default=str)


def load_knowledge_base(
    extra_dirs: list[Path] | None = None,
    *,
    include_user: bool | None = None,
    user_entries: list[dict[str, Any]] | None = None,
    full: bool = False,
) -> KnowledgeBase:
    """Build the knowledge base from packaged profiles plus overrides.

    Later sources win, so a user-supplied profile for ``provider: openai``
    overrides the packaged one. ``user_entries`` replaces reading kb.db (used
    to preview an import before it is saved; such loads are not cached).
    ``full=True`` returns the complete set instead of what audits use: disabled
    kb.db entries applied as if enabled, switched-off items kept.
    The result is the caller's own copy.
    """
    dirs: list[Path] = list(extra_dirs or [])
    env_dir = os.environ.get("ZING_KB_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    use_user = user_kb_enabled(include_user)

    if user_entries is not None:
        return _build(dirs, use_user, user_entries, [], []).model_copy(deep=True)

    entries: list[dict[str, Any]] = []
    disabled: list[tuple[str, str, str]] = []
    warnings: list[str] = []
    cacheable = True
    db_location = ""
    if use_user:
        from zing import datadir
        from zing.knowledge import store

        try:
            db_location = str(datadir.db_path(store.DB_NAME).resolve())
            if full:
                entries = [{**e, "enabled": True} for e in store.list_entries()]
            else:
                entries = store.list_entries(enabled_only=True)
                disabled = store.disabled_items()
        except Exception as exc:  # an unreadable kb.db must not break audits
            warnings.append(f"kb.db could not be read: {_short_error(exc)}")
            cacheable = False

    if not cacheable:
        return _build(dirs, use_user, entries, warnings, disabled).model_copy(deep=True)
    key = (_dirs_key(dirs), use_user, db_location, full, _entries_key(entries), tuple(disabled))
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
    if cached is None:
        cached = _build(dirs, use_user, entries, warnings, disabled)
        with _cache_lock:
            _cache[key] = cached
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_SIZE:
                _cache.popitem(last=False)
    return cached.model_copy(deep=True)


def _build(
    dirs: list[Path],
    use_user: bool,
    user_entries: list[dict[str, Any]],
    warnings: list[str],
    disabled: list[tuple[str, str, str]],
) -> KnowledgeBase:
    layered = dict(_load_packaged())
    for directory in dirs:
        layered.update(_load_dir(directory))

    kb = KnowledgeBase(
        providers={name: prof for name, (prof, _src) in layered.items()},
        provider_sources={name: src for name, (_prof, src) in layered.items()},
    )
    for name, prof in kb.providers.items():
        for m in prof.models:
            kb.model_sources[f"{name}/{m.id}"] = kb.provider_sources[name]

    if not use_user:
        kb.user_kb = False
        return kb
    kb.warnings.extend(warnings)
    apply_user_entries(kb, user_entries)
    apply_disabled(kb, disabled)
    return kb
