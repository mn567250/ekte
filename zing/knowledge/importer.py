"""Scan, check and import knowledge-base YAML into the user's kb.db.

The intended flow (web UI: Knowledge base page, CLI: ``zing kb prompt``):

1. the user copies a research prompt (:mod:`zing.knowledge.research`) into an
   external AI assistant, which answers with a provider YAML document;
2. the user uploads/pastes that YAML;
3. :func:`scan` checks it — nothing is written — and reports errors (which
   block the import) and warnings (which don't);
4. :func:`import_yaml` stores a clean scan in kb.db, where the next audit
   picks it up.

The YAML comes from an AI and is treated as untrusted input:

* size-limited, parsed with PyYAML's safe loader (libyaml's C parser when
  available, :mod:`zing.utils.yamlio`) and refused when it uses
  anchors/aliases (no "billion laughs" expansion), nests more than
  ``MAX_NESTING`` levels or uses a tag outside the safe subset;
* validated against the same pydantic schema as the packaged profiles (unknown
  fields are errors, non-English probes need a ``language_bound`` reason);
* bounded: counts, prompt lengths, ``max_tokens``, ``temperature``, ``weight``;
* ``expect_regex`` must compile, be short, and not nest quantifiers — it runs
  on the server against relay output, so a catastrophic-backtracking pattern
  would stall audits;
* a model without ``identity_keywords`` gets its own brand words filled in
  (provider and model names, :mod:`zing.knowledge.identity`) with a warning;
* every fingerprint prompt (text zing will send to audited endpoints) is
  listed back so the user can review it before saving;
* resolution changes are reported: an id or alias that would make an existing
  model id resolve to a different profile, and user models that shadow a
  packaged or ``ZING_KB_DIR`` model.

Merge semantics match the loader: a new provider is stored whole; for an
existing (packaged / ``ZING_KB_DIR``) provider only its lists are added —
fingerprints by id, hints and red flags as a union — and single-value fields
are ignored with a warning; models are stored one entry each.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from zing.knowledge import store
from zing.knowledge.identity import own_brand_words
from zing.knowledge.loader import load_knowledge_base
from zing.knowledge.schema import FingerprintProbe, KnowledgeBase, ProviderProfile
from zing.utils import yamlio

MAX_YAML_BYTES = 512 * 1024
MAX_MODELS = 200
MAX_FINGERPRINTS = 100
MAX_PROMPT_CHARS = 20_000
MAX_REGEX_CHARS = 500
MAX_TOKENS = 32_768
# Valid profiles nest about six levels deep. The limit keeps the loaders off
# deeply nested input: libyaml's composer recurses in C once per level (tens
# of thousands of levels overflow the C stack), the Python code past it hits
# RecursionError after several hundred.
MAX_NESTING = 32

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_MODEL_ID_RE = re.compile(r"^[^\s\x00-\x1f\x7f]{1,200}$")
# A group that itself contains a quantifier, followed by another quantifier:
# (a+)+, (\w*)*, (x|y+){2,} — the classic catastrophic-backtracking shapes.
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d*,)")
_PROVIDER_LISTS = ("fingerprints", "base_url_hints", "relay_red_flags")


@dataclass
class ScanResult:
    ok: bool = False
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    providers: list[dict[str, Any]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(default_factory=list)
    # Every prompt zing would send to audited endpoints: review before saving.
    probes: list[dict[str, str]] = field(default_factory=list)
    resolution_changes: list[dict[str, str | None]] = field(default_factory=list)
    # What import_yaml would write: (kind, provider, model_id, body).
    entries: list[tuple[str, str, str | None, dict[str, Any]]] = field(default_factory=list)

    def error(self, path: str, message: str) -> None:
        self.errors.append({"path": path, "message": message})

    def warn(self, path: str, message: str) -> None:
        self.warnings.append({"path": path, "message": message})

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "providers": self.providers,
            "models": self.models,
            "probes": self.probes,
            "resolution_changes": self.resolution_changes,
        }


def _loc(prefix: str, loc: tuple[Any, ...]) -> str:
    out = prefix
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _pydantic_errors(result: ScanResult, prefix: str, exc: ValidationError) -> None:
    for err in exc.errors()[:50]:
        msg = err.get("msg", "invalid")
        if err.get("type") == "extra_forbidden":
            msg = "unknown field (not part of the zing profile schema)"
        result.error(_loc(prefix, tuple(err.get("loc") or ())), msg)


def _structure_problem(text: str, loader: Any = None) -> str | None:
    """Why ``text`` is refused before it is loaded (anchors, nesting), from its parser events."""
    depth = 0
    for event in yamlio.parse(text, loader):
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            return "YAML anchors/aliases (& and *) are not allowed"
        if isinstance(event, yaml.CollectionStartEvent):
            depth += 1
            if depth > MAX_NESTING:
                return f"nested more than {MAX_NESTING} levels deep"
        elif isinstance(event, yaml.CollectionEndEvent):
            depth -= 1
    return None


def _load_documents(text: str) -> list[Any] | str:
    """The non-empty documents in ``text``, or why it is refused."""
    problem = _structure_problem(text)
    if problem is not None:
        return problem
    return [d for d in yamlio.safe_load_all(text) if d is not None]


def _check_strings(result: ScanResult, path: str, value: Any) -> None:
    if isinstance(value, str):
        if "\x00" in value:
            result.error(path, "contains a NUL character")
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_strings(result, f"{path}.{k}" if path else str(k), v)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_strings(result, f"{path}[{i}]", v)


def _check_fingerprints(
    result: ScanResult, path: str, fps: list[FingerprintProbe], owner: str
) -> None:
    # Imported here: the knowledge layer otherwise does not load the detectors.
    from zing.detectors.model_identity import ModelIdentityDetector

    # The identity check skips pure-code probes that need more output than this.
    identity_cap = ModelIdentityDetector.MAX_FINGERPRINT_OUTPUT
    if len(fps) > MAX_FINGERPRINTS:
        result.error(path, f"too many fingerprints ({len(fps)} > {MAX_FINGERPRINTS})")
    seen: set[str] = set()
    for i, fp in enumerate(fps):
        p = f"{path}[{i}]"
        if fp.id in seen:
            result.error(f"{p}.id", f"duplicate fingerprint id {fp.id!r}")
        seen.add(fp.id)
        if not fp.prompt.strip():
            result.error(f"{p}.prompt", "empty prompt")
        if len(fp.prompt) > MAX_PROMPT_CHARS:
            result.error(f"{p}.prompt", f"prompt longer than {MAX_PROMPT_CHARS} characters")
        if not 1 <= fp.max_tokens <= MAX_TOKENS:
            result.error(f"{p}.max_tokens", f"must be between 1 and {MAX_TOKENS}")
        if not 0.0 <= fp.temperature <= 2.0:
            result.error(f"{p}.temperature", "must be between 0 and 2")
        if not 0.0 <= fp.weight <= 10.0:
            result.error(f"{p}.weight", "must be between 0 and 10")
        if fp.expect_regex is not None:
            rx = fp.expect_regex
            if len(rx) > MAX_REGEX_CHARS:
                result.error(f"{p}.expect_regex", f"longer than {MAX_REGEX_CHARS} characters")
            elif _NESTED_QUANTIFIER.search(rx):
                result.error(f"{p}.expect_regex", "nested quantifiers (catastrophic backtracking risk)")
            else:
                try:
                    re.compile(rx, re.IGNORECASE)
                except re.error as exc:
                    result.error(f"{p}.expect_regex", f"invalid regular expression: {exc}")
        if fp.pure_code_checkable and not (
            fp.expect_contains or fp.expect_contains_any or fp.expect_not_contains or fp.expect_regex
        ):
            result.warn(p, "pure_code_checkable without any expect_* check: it can never fail")
        if fp.pure_code_checkable and fp.max_tokens > identity_cap:
            result.warn(f"{p}.max_tokens",
                        f"more than {identity_cap} tokens: the identity check skips this probe")
        result.probes.append({"path": p, "owner": owner, "id": fp.id, "prompt": fp.prompt,
                              "prompt_lang": fp.prompt_lang})


def _resolution_map(kb: KnowledgeBase, names: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for n in names:
        r = kb.resolve(n)
        out[n] = f"{r.provider.provider}/{r.model.id}" if r else None
    return out


def scan(text: str, *, base: KnowledgeBase | None = None) -> ScanResult:
    """Check YAML without writing anything. ``base`` defaults to the current KB."""
    result = ScanResult()
    raw = text.encode("utf-8", errors="replace") if isinstance(text, str) else b""
    if not raw.strip():
        result.error("", "empty document")
        return result
    if len(raw) > MAX_YAML_BYTES:
        result.error("", f"larger than {MAX_YAML_BYTES // 1024} KB")
        return result
    try:
        loaded = _load_documents(text)
    except yaml.YAMLError as c_exc:
        # Syntax errors are raised by the parser, so re-parsing is enough for the detail.
        exc = yamlio.detailed_error(c_exc, lambda loader: _structure_problem(text, loader))
        problem = getattr(exc, "problem", None) or (str(exc).splitlines() or ["syntax error"])[0]
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark is not None else ""
        result.error("", f"not valid YAML: {problem}{where}")
        return result
    if isinstance(loaded, str):
        result.error("", loaded)
        return result
    docs = loaded
    if not docs:
        result.error("", "no YAML document found")
        return result

    # both are only read: the shared cached instances, no copies
    current = base if base is not None else load_knowledge_base(copy=False)
    underlying = load_knowledge_base(include_user=False, copy=False)
    user_entries = store.list_entries()
    user_keys = {(e["kind"], e["provider"], e.get("model_id") or "") for e in user_entries}
    seen_models: set[tuple[str, str]] = set()

    for d_index, doc in enumerate(docs):
        prefix = f"document[{d_index}]" if len(docs) > 1 else ""
        if not isinstance(doc, dict):
            result.error(prefix, "a document must be a mapping with `provider:` and `models:`")
            continue
        _check_strings(result, prefix, doc)
        name = doc.get("provider")
        if not isinstance(name, str) or not _PROVIDER_RE.match(name):
            result.error(_loc(prefix, ("provider",)),
                         "provider key must be lower-case letters, digits, . _ - (max 64)")
            continue
        models_raw = doc.get("models") or []
        if not isinstance(models_raw, list):
            result.error(_loc(prefix, ("models",)), "must be a list")
            continue
        if len(models_raw) > MAX_MODELS:
            result.error(_loc(prefix, ("models",)), f"too many models ({len(models_raw)} > {MAX_MODELS})")
            continue
        try:
            profile = ProviderProfile(**doc)
        except ValidationError as exc:
            _pydantic_errors(result, prefix, exc)
            continue
        except TypeError as exc:
            result.error(prefix, str(exc))
            continue

        _check_fingerprints(result, _loc(prefix, ("fingerprints",)), profile.fingerprints, f"provider {name}")
        for h_index, hint in enumerate(profile.base_url_hints):
            if not re.match(r"^https?://", hint):
                result.error(_loc(prefix, ("base_url_hints", h_index)), "must start with http:// or https://")

        # Provider-level entry.
        existing = underlying.providers.get(name)
        prov_info: dict[str, Any] = {"provider": name, "new": existing is None and name not in current.providers,
                                     "ignored_fields": []}
        if existing is not None:
            body = {k: getattr(profile, k) for k in _PROVIDER_LISTS if getattr(profile, k)}
            body = ProviderProfile(provider=name, **body).model_dump(mode="json", include=set(body))
            for fname in ProviderProfile.model_fields:
                if fname in ("provider", "models", *_PROVIDER_LISTS) or fname not in doc:
                    continue
                if getattr(profile, fname) != getattr(existing, fname):
                    prov_info["ignored_fields"].append(fname)
                    result.warn(_loc(prefix, (fname,)),
                                f"ignored: {name!r} is a {underlying.provider_sources.get(name, 'packaged')} "
                                "provider; only models, fingerprints, base_url_hints and relay_red_flags can be added")
            if body:
                result.entries.append(("provider", name, None, body))
        else:
            body = profile.model_dump(mode="json", exclude={"provider", "models"})
            result.entries.append(("provider", name, None, body))
            if ("provider", name, "") in user_keys:
                prov_info["replaces_your_entry"] = True
        result.providers.append(prov_info)

        # Model entries.
        for m_index, model in enumerate(profile.models):
            mpath = _loc(prefix, ("models", m_index))
            if not _MODEL_ID_RE.match(model.id):
                result.error(f"{mpath}.id", "model id must be 1-200 characters without spaces")
                continue
            if (name, model.id) in seen_models:
                result.error(f"{mpath}.id", f"duplicate model {name}/{model.id}")
                continue
            seen_models.add((name, model.id))
            for a_index, alias in enumerate(model.aliases):
                if not alias.strip():
                    result.error(f"{mpath}.aliases[{a_index}]", "empty alias")
            _check_fingerprints(result, f"{mpath}.fingerprints", model.fingerprints, f"model {name}/{model.id}")
            key = f"{name}/{model.id}"
            info: dict[str, Any] = {"provider": name, "id": model.id, "action": "add", "shadows": None}
            if ("model", name, model.id) in user_keys:
                info["action"] = "update"
            if existing is not None and any(m.id == model.id for m in existing.models):
                info["shadows"] = underlying.model_sources.get(key)
                if info["action"] == "add":
                    info["action"] = "shadow"
                result.warn(f"{mpath}.id", f"replaces {key} from {info['shadows']} (your entries take priority)")
            # An id/alias that is already a different model's id or alias.
            for n in [model.id, *model.aliases]:
                hit = current.resolve(n)
                if hit and hit.match_confidence in ("exact", "alias") and (
                    hit.provider.provider, hit.model.id) != (name, model.id):
                    result.warn(f"{mpath}", f"{n!r} is already {hit.provider.provider}/{hit.model.id}")
            result.models.append(info)
            body = model.model_dump(mode="json")
            if not model.identity_keywords:
                # Without own brand words the identity check has nothing to confirm
                # the genuine brand with; derive them from the names. A packaged
                # provider keeps its display_name; a provider document without
                # one falls back to the stored one.
                brand_source = existing if existing is not None else (
                    profile if profile.display_name else current.providers.get(name, profile))
                # Stored unwidened: the detector adds the vendor's other names itself.
                words = own_brand_words(brand_source, model, widen=False)
                if words:
                    body["identity_keywords"] = words
                    result.warn(f"{mpath}.identity_keywords",
                                f"was empty; filled with [{', '.join(words)}] — check and edit if wrong")
            result.entries.append(("model", name, model.id, body))

    if not result.errors and result.entries:
        _resolution_changes(result, current, user_entries)
    if not result.entries and not result.errors:
        result.error("", "nothing to import (no models or provider data)")
    result.ok = not result.errors
    return result


def _merge_preview(user_entries: list[dict[str, Any]],
                   new: list[tuple[str, str, str | None, dict[str, Any]]]) -> list[dict[str, Any]]:
    """kb.db entries as they would be after importing ``new`` (for a preview load)."""
    by_key = {(e["kind"], e["provider"], e.get("model_id") or ""): dict(e) for e in user_entries}
    next_id = max([e["id"] for e in user_entries] + [0]) + 1
    for kind, provider, model_id, body in new:
        k = (kind, provider, model_id or "")
        if k in by_key:
            by_key[k] = {**by_key[k], "body": body, "enabled": True}
        else:
            by_key[k] = {"id": next_id, "kind": kind, "provider": provider, "model_id": model_id,
                         "body": body, "enabled": True, "updated_ts": None, "origin": "preview"}
            next_id += 1
    return sorted(by_key.values(), key=lambda e: e["id"])


def _resolution_changes(result: ScanResult, current: KnowledgeBase, user_entries: list[dict[str, Any]]) -> None:
    after = load_knowledge_base(user_entries=[e for e in _merge_preview(user_entries, result.entries)
                                              if e.get("enabled", True)])
    imported = {(p, m) for kind, p, m, _ in result.entries if kind == "model"}
    names: list[str] = []
    for prov, model in current.all_models():
        if (prov.provider, model.id) in imported:
            continue
        names.extend([model.id, *model.aliases])
    before_map = _resolution_map(current, names)
    after_map = _resolution_map(after, names)
    for n in names:
        if before_map[n] != after_map[n] and not any(
            c["id"] == n for c in result.resolution_changes
        ):
            result.resolution_changes.append({"id": n, "before": before_map[n], "after": after_map[n]})
            result.warn("", f"{n!r} would resolve to {after_map[n]} instead of {before_map[n]}")
    for w in after.warnings:
        result.warn("", w)


def import_yaml(text: str, *, origin: str | None = None) -> tuple[ScanResult, list[int]]:
    """Scan ``text`` and, when clean, store it in kb.db. Returns (scan, entry ids)."""
    result = scan(text)
    if not result.ok:
        return result, []
    ids: list[int] = []
    with store.transaction() as conn:
        for kind, provider, model_id, body in result.entries:
            ids.append(store.upsert(kind, provider, body, model_id=model_id, origin=origin, conn=conn))
    return result, ids


def export_yaml(provider: str | None = None) -> str:
    """The user's kb.db entries as provider YAML documents (importable again)."""
    groups: dict[str, dict[str, Any]] = {}
    for e in store.list_entries():
        if provider and e["provider"] != provider:
            continue
        doc = groups.setdefault(e["provider"], {"provider": e["provider"]})
        if not isinstance(e.get("body"), dict):
            continue
        if e["kind"] == "provider":
            for k, v in e["body"].items():
                if k not in ("provider", "models"):
                    doc[k] = v
        else:
            doc.setdefault("models", []).append({**e["body"], "id": e["model_id"]})
    docs = []
    for name in sorted(groups):
        doc = groups[name]
        ordered = {"provider": doc.pop("provider"), **{k: v for k, v in doc.items() if k != "models"}}
        if "models" in doc:
            ordered["models"] = doc["models"]
        docs.append(yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, width=100))
    return "---\n".join(docs)
