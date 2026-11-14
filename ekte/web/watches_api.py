"""The Monitors page's API: the filtered list of monitors and its filter options.

``GET /api/watches?<keys>`` (:func:`list_watches`) and
``GET /api/watches/options?<keys>`` (:func:`options`), both cached by
:func:`ekte.web.cache.cached_endpoint` (``ETag`` / ``304``) with
:func:`resolve_params` as ``prepare``.

URL keys
========

The monitor keys of the shared URL schema (:mod:`ekte.web.query`):

=====================================  ==========================================================
Key                                    A monitor matches when
=====================================  ==========================================================
``q``                                  the text is a substring (case-insensitive for ASCII) of
                                       its name, base URL, relay label, claimed model, model or
                                       suite
``surface``                            its surface is the value
``relay``                              its ``relay_key`` (the relay its runs are grouped under,
                                       :class:`ekte.web.analytics.RelayResolver`) is one of the
                                       values; repeatable
``model``                              its claimed model (else its model; ``(unknown)``
                                       without either) is one of the values; repeatable
``suite``, ``api``, ``stream``         its suite / protocol (``api_resolved``) / probe request
                                       mode (``stream_mode``) is the value, ``-`` for none
``state``                              ``active`` (enabled and set up), ``paused`` (set up but
                                       disabled), ``draft`` (scheduled from History, no interval
                                       yet: it needs setup before it runs on its own)
``alerting``                           ``yes``: its last run's risk is at or above its
                                       ``alert_on`` threshold (:func:`ekte.web.watches.risk_meets`,
                                       as the scheduler alerts); ``no`` otherwise
=====================================  ==========================================================

The shared keys are validated by :func:`ekte.web.query.parse_query` (same
values, same errors). Every other key, the run-only keys of History and
Analytics (``range``, ``risk``, …) included, is refused with
``unknown parameter`` (:class:`~ekte.web.query.QueryError`, answered 400).
Filtering runs in Python over the monitor rows: it is bounded by the number
of monitors, not runs.

Rows carry no live run state (running, queued, progress): that is
``GET /api/jobs`` (``id = monitor-<id>``). They never contain an API key
(:func:`ekte.web.watches.list_all`).

Cache key
=========

:func:`ekte.web.cache.cache_key` holds the history data version (the relay
labels are History's, :func:`ekte.web.history_api.relay_labels`) and the
knowledge-base relay version (``relay_key`` and the relay labels).
:func:`resolve_params` adds one more parameter, :data:`TOKEN`, a hash of
everything else the rows depend on: the watches data version
(:func:`ekte.web.watches.data_version`: a monitor created, edited, deleted
or run), the master key held and the keys held in memory (``key_status``),
the knowledge base audits use (``kb_changed``), the phase of every run window
(``in_window``, ``next_window_ts``) and this process (memory-held keys do
not survive a restart).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ekte.web import query
from ekte.web.analytics import UNKNOWN_RELAY
from ekte.web.query import UNKNOWN, QueryError

__all__ = ["KEYS", "OPTION_KEYS", "TOKEN", "WatchQuery", "list_watches", "options", "parse",
           "resolve_params", "rows"]

# the shared keys a monitor has, then the monitor-only ones
SHARED_KEYS = ("q", "surface", "relay", "model", "suite", "api", "stream")
OWN_KEYS = ("state", "alerting")
KEYS = (*SHARED_KEYS, *OWN_KEYS)
OPTION_KEYS = ("surface", "relay", "model", "suite", "api", "stream", "state", "alerting")
STATES = ("active", "paused", "draft")
ALERTING = ("yes", "no")
# resolve_params(): the cache-key token, or the error of parameters that do not parse
TOKEN = ":monitors"
_ERROR = ":error"

_BOOT = secrets.token_hex(8)


@dataclass(frozen=True)
class WatchQuery:
    """Parsed monitor filters: the shared ones as a :class:`ekte.web.query.Query`."""

    base: query.Query
    state: str | None = None
    alerting: str | None = None

    def canonical(self) -> dict[str, Any]:
        """The filters in canonical form (URL keys, sorted, only those set)."""
        out = {k: v for k, v in self.base.canonical().items() if k in SHARED_KEYS}
        out.update({k: v for k, v in (("state", self.state), ("alerting", self.alerting)) if v})
        return dict(sorted(out.items()))

    def params(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for key, value in self.canonical().items():
            pairs.extend((key, v) for v in (value if isinstance(value, list) else [value]))
        return pairs


def parse(params: query.Params) -> WatchQuery:
    """Validate request parameters into a :class:`WatchQuery` (raises
    :class:`~ekte.web.query.QueryError` naming the key)."""
    shared: list[tuple[str, str]] = []
    own: dict[str, str] = {}
    for key, value in query._pairs(params):
        if key in SHARED_KEYS:
            shared.append((key, value))
        elif key in OWN_KEYS:
            if len(value) > query.MAX_PARAM:
                raise QueryError(f"{key} is longer than {query.MAX_PARAM} characters")
            if key in own:
                raise QueryError(f"{key} given more than once")
            own[key] = value
        else:
            raise QueryError(f"unknown parameter {key[:64]!r}")
    return WatchQuery(
        base=query.parse_query(shared),
        state=query._choice("state", own.get("state"), STATES),
        alerting=query._choice("alerting", own.get("alerting"), ALERTING),
    )


# --------------------------------------------------------------------------- #
# Cache key
# --------------------------------------------------------------------------- #
_kb_lock = threading.Lock()
_kb_seen: list[Any] = [None, 0]  # [the last audit knowledge base seen, how many seen]


def _audit_kb() -> tuple[Any, int | str]:
    """The audit knowledge base (read-only; ``None`` when it cannot be
    loaded) and its version token (for ``kb_changed``). The loader shares
    one instance per content, so a new instance is a new version; while
    ``kb.db`` cannot be read the loader builds a fresh copy on every call
    (the packaged profiles only), which has one fixed token instead."""
    from ekte.knowledge import load_knowledge_base

    try:
        kb = load_knowledge_base(copy=False)
    except Exception:
        return None, "unloadable"
    degraded = [w for w in kb.warnings if w.startswith("kb.db could not be read")]
    if degraded:
        return kb, "kb.db unreadable"
    with _kb_lock:
        if kb is not _kb_seen[0]:
            _kb_seen[0] = kb
            _kb_seen[1] += 1
        return kb, int(_kb_seen[1])


def token(now: float | None = None) -> str:
    """The :data:`TOKEN` value (see the module docstring): changes whenever
    the rows may."""
    from ekte import runwindow
    from ekte.web import watches

    now = time.time() if now is None else now
    state = watches.listing_state()
    # one phase per distinct window (monitors often share one)
    windows = [(w.to_dict(), runwindow.in_window(w, now), runwindow.next_window_start(w, now))
               for w in dict.fromkeys(watches.run_windows(state[0]))]
    raw = json.dumps([_BOOT, state, _audit_kb()[1], windows], separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def resolve_params(params: query.Params) -> list[tuple[str, str]]:
    """The ``prepare`` of both endpoints: the filters in canonical form plus
    :data:`TOKEN`; parameters that do not parse come back as their error,
    for the endpoint to answer 400 with."""
    try:
        q = parse(params)
    except QueryError as exc:
        return [(_ERROR, str(exc))]
    return [*q.params(), (TOKEN, token())]


def _prepared(params: query.Params) -> WatchQuery:
    """The query of parameters :func:`resolve_params` prepared (raises its error)."""
    pairs = query._pairs(params)
    for key, value in pairs:
        if key == _ERROR:
            raise QueryError(value)
    return parse([(k, v) for k, v in pairs if k != TOKEN])


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #
def _relay_labels(groups: Iterable[Any]) -> dict[str, str]:
    """What each relay is called, as History names it
    (:func:`ekte.web.history_api.relay_labels`): a knowledge-base entry by its
    label, a URL by its host (host and path when several share it). A relay
    no run has yet is named among the monitors' own URLs."""
    from ekte.web import history
    from ekte.web.history_api import relay_labels, url_labels

    groups = list(groups)
    try:
        known = relay_labels(history.query_connection())
    except Exception:  # an unreadable history: the monitors' own URLs only
        known = {}
    labels = url_labels(g.key for g in groups if not g.in_kb and g.key != UNKNOWN_RELAY)
    labels.update({g.key: known[g.key] for g in groups if g.key in known})
    for g in groups:
        if g.in_kb or g.key == UNKNOWN_RELAY:
            labels[g.key] = g.label
    return labels


_FAILED = object()  # a profile that could not be resolved


# The profile hash each (claimed model, model, provider) resolves to in the
# audit knowledge base, for kb_changed: resolving one costs milliseconds (it
# normalizes every model of the knowledge base), so it is remembered for the
# knowledge base's version (_audit_kb) and forgotten when another one is
# current.
_profiles_lock = threading.Lock()
_profiles: tuple[Any, dict[tuple[Any, ...], Any]] = (None, {})
_PROFILES_MAX = 4096


def _profile_hash(kb: Any, version: Any, claimed: Any, model: Any, provider: Any) -> Any:
    """The profile hash a monitor's model resolves to in ``kb`` of
    ``version`` (``_FAILED`` when it cannot be resolved)."""
    from ekte.web import server

    global _profiles
    key = (claimed, model, provider)
    with _profiles_lock:
        if _profiles[0] != version:
            _profiles = (version, {})
        memo = _profiles[1]
        if key in memo:
            return memo[key]
    try:
        value = server._watch_knowledge(
            {"claimed_model": claimed, "model": model, "declared_provider": provider}, kb
        ).get("profile_hash")
    except Exception:
        value = _FAILED
    with _profiles_lock:
        if _profiles[0] == version:
            if len(memo) >= _PROFILES_MAX:
                memo.clear()
            memo[key] = value
    return value


def _memo(fn: Callable[..., Any]) -> Callable[..., Any]:
    """``fn`` remembered by its arguments for one request (many monitors share them)."""
    seen: dict[Any, Any] = {}

    def call(*args: Any) -> Any:
        if args not in seen:
            seen[args] = fn(*args)
        return seen[args]

    return call


def rows(now: float | None = None) -> list[dict[str, Any]]:
    """Every stored monitor (newest first, no API key) with what the page
    shows of it: its schedule floor, run window phase, protocol,
    knowledge-base drift, ``relay_key`` / ``relay_label``, ``state`` and
    ``alerting``. Relays and profiles are resolved once per request.
    Blocking (SQLite + knowledge base): call it off the loop."""
    from ekte import runwindow
    from ekte.web import server, watches
    from ekte.web.analytics import RelayResolver

    out = watches.list_all()
    if not out:
        return out
    now = time.time() if now is None else now
    resolver = RelayResolver()
    groups = [resolver.resolve(row) for row in out]
    labels = _relay_labels(groups)
    kb, kb_version = _audit_kb()  # read-only

    @_memo
    def protocol(base_url: Any, model: Any, api: Any, surface: Any, suite: Any, streaming: Any) -> Any:
        return server._watch_protocol({"base_url": base_url, "model": model, "api": api, "surface": surface,
                                       "suite": suite, "performance_streaming": streaming})

    def profile_hash(claimed: Any, model: Any, provider: Any) -> Any:
        return _profile_hash(kb, kb_version, claimed, model, provider)

    @_memo
    def phase(raw: Any) -> tuple[bool, float | None]:
        win = runwindow.parse(raw)
        return runwindow.in_window(win, now), runwindow.next_window_start(win, now)

    for row, group in zip(out, groups, strict=True):
        row["relay_key"] = group.key
        row["relay_label"] = labels.get(group.key) or group.label
        row["min_interval_sec"] = server._min_interval_sec(row.get("run_duration_sec"))
        window = row.get("run_window")  # a dict (list_all), or None
        row["in_window"], row["next_window_ts"] = phase(
            json.dumps(window, sort_keys=True) if window else None)
        row.update(protocol(row.get("base_url"), row.get("model"), row.get("api"), row.get("surface"),
                            row.get("suite"), row.get("performance_streaming")))
        row["kb_current_hash"] = None
        row["kb_changed"] = False
        if kb is not None:
            current = profile_hash(row.get("claimed_model"), row.get("model"), row.get("declared_provider"))
            if current is not _FAILED:
                row["kb_current_hash"] = current
                pinned_hash = (row.get("kb") or {}).get("profile_hash")
                row["kb_changed"] = bool(pinned_hash and pinned_hash != current)
        row["state"] = state_of(row)
        row["alerting"] = watches.risk_meets(row.get("last_risk"), row.get("alert_on"))
    return out


def state_of(row: Mapping[str, Any]) -> str:
    """``draft`` (no interval yet: scheduled from History, it needs setup;
    the API key stays optional, as for any monitor), else ``active`` when
    enabled, ``paused`` when not."""
    if row.get("interval_sec") is None:
        return "draft"
    return "active" if row.get("enabled") else "paused"


def _values(row: Mapping[str, Any]) -> dict[str, str]:
    """The value of each single-valued filter key for one row."""
    return {
        "surface": str(row.get("surface") or "chat"),
        "relay": str(row.get("relay_key") or UNKNOWN_RELAY),
        # "(unknown)": the model key of a run without one, as relay_map writes it
        "model": str(row.get("claimed_model") or row.get("model") or UNKNOWN_RELAY),
        "suite": str(row.get("suite") or UNKNOWN),
        "api": str(row.get("api_resolved") or UNKNOWN),
        "stream": str(row.get("stream_mode") or UNKNOWN),
        "state": str(row.get("state")),
        "alerting": "yes" if row.get("alerting") else "no",
    }


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _text(row: Mapping[str, Any]) -> str:
    """What ``q`` searches, lowercased for ASCII only (as SQL ``LIKE``)."""
    parts = (row.get("name"), row.get("base_url"), row.get("relay_label"), row.get("claimed_model"),
             row.get("model"), row.get("suite"))
    return "\n".join(str(p) for p in parts if p).translate(_ASCII_LOWER)


def _is(key: str, want: str) -> Callable[[Mapping[str, str], str], bool]:
    return lambda values, _text: values[key] == want


def _among(key: str, want: frozenset[str]) -> Callable[[Mapping[str, str], str], bool]:
    return lambda values, _text: values[key] in want


def _contains(want: str) -> Callable[[Mapping[str, str], str], bool]:
    return lambda _values, text: want in text


def _tests(q: WatchQuery) -> dict[str, Callable[[Mapping[str, str], str], bool]]:
    """One test per given filter key: ``(values, text) -> matches``."""
    b = q.base
    single = {"surface": b.surface, "suite": b.suite, "api": b.api, "stream": b.stream,
              "state": q.state, "alerting": q.alerting}
    tests = {key: _is(key, want) for key, want in single.items() if want is not None}
    if b.relays:
        tests["relay"] = _among("relay", frozenset(b.relays))
    if b.models:
        tests["model"] = _among("model", frozenset(b.models))
    if b.text is not None:
        tests["q"] = _contains(b.text.translate(_ASCII_LOWER))
    return tests


def _match(q: WatchQuery, items: list[tuple[dict[str, Any], dict[str, str], str]],
           skip: str | None = None) -> list[tuple[dict[str, Any], dict[str, str], str]]:
    tests = [t for k, t in _tests(q).items() if k != skip]
    return [it for it in items if all(t(it[1], it[2]) for t in tests)]


def _items(all_rows: list[dict[str, Any]], q: WatchQuery) -> list[tuple[dict[str, Any], dict[str, str], str]]:
    needs_text = q.base.text is not None
    return [(r, _values(r), _text(r) if needs_text else "") for r in all_rows]


def list_watches(params: query.Params) -> list[dict[str, Any]]:
    """``GET /api/watches``: the monitors matching the filters, newest first."""
    q = _prepared(params)
    return [r for r, _, _ in _match(q, _items(rows(), q))]


def options(params: query.Params) -> dict[str, Any]:
    """``GET /api/watches/options``: for every key of :data:`OPTION_KEYS`
    the values present as ``[{value, monitors, label?}]``, counted in
    monitors matching every filter but the key's own (as
    ``/api/filters/options`` counts runs: a selected value and its siblings
    never disappear), most monitors first. ``relay`` values carry their
    ``label`` (as History names the relay); ``monitors`` is how many match
    every filter."""
    q = _prepared(params)
    all_rows = rows()
    items = _items(all_rows, q)
    labels = {str(r.get("relay_key") or UNKNOWN_RELAY): str(r.get("relay_label") or "") for r in all_rows}
    out: dict[str, Any] = {"filters": q.canonical(), "keys": list(OPTION_KEYS),
                           "monitors": len(_match(q, items))}
    for key in OPTION_KEYS:
        counts: dict[str, int] = {}
        for _, values, _t in _match(q, items, skip=key):
            counts[values[key]] = counts.get(values[key], 0) + 1
        entries: list[dict[str, Any]] = []
        for value, n in counts.items():
            if key == "relay":
                entries.append({"value": value, "label": labels.get(value) or value, "monitors": n})
            else:
                entries.append({"value": value, "monitors": n})
        entries.sort(key=lambda o: (-o["monitors"], str(o.get("label", o["value"])).lower(), o["value"]))
        out[key] = entries
    return out
