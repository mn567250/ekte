"""The History page's widgets, computed on the server: groups, their runs, trends.

Built on the query core (:mod:`ekte.web.query`: one filter schema, one SQL
``WHERE``) and the metric registry (:mod:`ekte.web.metrics`: grades, colour
families, trend text keys), so the page only draws. Served by
``GET /api/history/groups`` (:func:`groups`) and ``GET /api/history/runs``
(:func:`runs`) through the response cache; ``GET /api/history/{rid}?trend=1``
adds :func:`run_trends`.

Order (``groups.sort`` / ``runs.sort``)
=======================================

``time``, ``risk``, ``score`` or ``grade``, descending with a leading ``-``
(default ``-time``), as the History list always sorted:

* the sort value: the run's start time; its risk (clean < inconclusive <
  low < medium < high; a run without a risk level is inconclusive); its
  score; its grade (F < E < D < C < B < A);
* runs without a value come last in either direction;
* ties: the most recently saved run first (the higher id; runs are saved in
  the order the list once sorted ties by, their save time).

Runs are ordered in their group by that order, and the groups by their first
run under it (the group holding the best match comes first). Both page with a
keyset cursor over that order (``after``): a run saved meanwhile never shifts
a page.

Relay labels
============

A saved relay or provider is called by its name. An unsaved URL is called by
its host with port (two servers on one host stay apart); when several unsaved
URLs share host and port, by host, port and path (trailing slashes dropped).
Worked out once per ``relay_map`` content (:func:`relay_labels`), over every
URL the map holds.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import sqlite3
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ekte.web import metrics, query
from ekte.web.analytics import ALL_KEY, UNKNOWN_RELAY
from ekte.web.analytics_store import METRIC_COLS
from ekte.web.metrics import HISTORY_TRENDS, MAX_TRENDS, MIN_RUNS, Metric
from ekte.web.query import Query, QueryError, RunSelection
from ekte.web.relay_map import GROUP_KEY_SQL, JOIN_SQL

__all__ = [
    "DEFAULT_GROUP", "POINTS", "RISK_FAMILY", "SORTS", "groups", "host_of", "parse_widget",
    "relay_labels", "resolve_params", "run_trends", "runs", "url_labels", "url_place",
]

DEFAULT_GROUP = "relay_model"
SORTS = ("time", "risk", "score", "grade")
DEFAULT_SORT = "-time"
PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 200
# Per-run trend points: the newest runs of a group.
POINTS = 50
# The colour family of each risk level (as the History badges).
RISK_FAMILY = {"clean": "good", "low": "sky", "medium": "warn", "high": "bad",
               "inconclusive": "grey"}
# Each endpoint's widget keys: the namespaced keys it reads (others with a dot
# belong to other widgets and are ignored).
WIDGET_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "groups": {"groups": ("sort", "after", "limit", "focus"), "trend": ("metrics",)},
    "runs": {"group": ("key",), "runs": ("sort", "after", "limit", "focus")},
}

_RISK_VALUE = ("CASE COALESCE(NULLIF(h.risk_level, ''), 'inconclusive') WHEN 'clean' THEN 0"
               " WHEN 'inconclusive' THEN 1 WHEN 'low' THEN 2 WHEN 'medium' THEN 3"
               " WHEN 'high' THEN 4 END")
_SORT_VALUE = {
    "time": "m.started_at",  # fixed-width ISO text: sorts as time
    "risk": _RISK_VALUE,
    # a score is a number or NULL (written from floats)
    "score": "h.score",
    "grade": metrics.grade_value_sql("h.rating"),
}
_NEWEST = "m.started_at IS NULL, m.started_at DESC, m.history_id DESC"


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
def resolve_params(params: Any) -> list[tuple[str, str]]:
    """The ``prepare`` of both endpoints: ``group`` defaults to
    :data:`DEFAULT_GROUP` (not the query core's ``relay``), then
    :func:`ekte.web.query.resolve_params` (the range made absolute)."""
    pairs = query._pairs(params)
    if not any(k == "group" for k, _ in pairs):
        pairs.append(("group", DEFAULT_GROUP))
    return query.resolve_params(pairs)


def parse_widget(endpoint: str, params: Any) -> tuple[Query, dict[str, list[str]]]:
    """The shared filters (:func:`ekte.web.query.parse_query`, ``group``
    defaulting to :data:`DEFAULT_GROUP`) and the endpoint's own widget keys
    (``{"groups.sort": [...], ...}``). An unknown key of the endpoint's
    namespaces raises :class:`~ekte.web.query.QueryError`."""
    pairs = query._pairs(params)
    if not any(k == "group" for k, _ in pairs):
        pairs.append(("group", DEFAULT_GROUP))
    q = query.parse_query(pairs)
    own = WIDGET_KEYS[endpoint]
    out: dict[str, list[str]] = {}
    for key, value in pairs:
        ns, dot, name = key.partition(".")
        if not dot or ns not in own:
            continue
        if name not in own[ns]:
            raise QueryError(f"unknown parameter {key[:64]!r}")
        out.setdefault(key, []).append(value)
    return q, out


def _one(widget: Mapping[str, list[str]], key: str) -> str | None:
    values = widget.get(key)
    if not values:
        return None
    if len(values) > 1:
        raise QueryError(f"{key} given more than once")
    return values[0]


def _sort(value: str | None, key: str) -> tuple[str, str, bool]:
    sort = value or DEFAULT_SORT
    name, desc = (sort[1:], True) if sort.startswith("-") else (sort, False)
    if name not in SORTS:
        raise QueryError(f"{key} must be one of {', '.join(SORTS)}, optionally with - (descending)")
    return sort, name, desc


def _limit(value: str | None, key: str) -> int:
    if value is None:
        return PAGE_LIMIT
    try:
        limit = int(value)
    except ValueError:
        limit = 0
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise QueryError(f"{key} must be from 1 to {MAX_PAGE_LIMIT}")
    return limit


def _focus(value: str | None, key: str) -> int | None:
    if value is None:
        return None
    try:
        rid = int(value)
    except ValueError:
        rid = -1
    if rid < 1:
        raise QueryError(f"{key} must be a run id")
    return rid


def trend_metrics(values: Sequence[str] | None) -> list[Metric]:
    """``trend.metrics`` (repeated or comma-separated ids): 1 to
    :data:`~ekte.web.metrics.MAX_TRENDS` distinct ids of
    :data:`~ekte.web.metrics.HISTORY_TRENDS`, returned in that (button) order."""
    ids = [part.strip() for v in values or () for part in v.split(",") if part.strip()]
    allowed = ", ".join(HISTORY_TRENDS)
    if not 1 <= len(ids) <= MAX_TRENDS:
        raise QueryError(f"trend.metrics must name 1 to {MAX_TRENDS} of {allowed}")
    for mid in ids:
        if mid not in HISTORY_TRENDS:
            raise QueryError(f"trend.metrics: {mid[:64]!r} is not one of {allowed}")
    if len(set(ids)) != len(ids):
        raise QueryError("trend.metrics names a metric twice")
    return [metrics.METRICS[mid] for mid in HISTORY_TRENDS if mid in ids]


# --------------------------------------------------------------------------- #
# Cursors
# --------------------------------------------------------------------------- #
def _cursor(kind: str, sort: str, key: Any) -> str:
    raw = json.dumps([kind, sort, key], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _uncursor(after: str, kind: str, sort: str, name: str) -> Any:
    try:
        raw = base64.urlsafe_b64decode(after + "=" * (-len(after) % 4))
        k, s, key = json.loads(raw)
    except (ValueError, TypeError, binascii.Error):
        raise QueryError(f"{name} is not a valid cursor") from None
    text = sort.lstrip("-") == "time"
    if (k, s) != (kind, sort) or isinstance(key, bool) or not isinstance(
            key, str if text else (int, float)) or (isinstance(key, float) and not math.isfinite(key)):
        raise QueryError(f"{name} is not a cursor of this sort")
    return key


# --------------------------------------------------------------------------- #
# SQL pieces
# --------------------------------------------------------------------------- #
# A run's sort key folds its id in, so the order is total: ids stay below
# _ID_SPAN, and value steps (scores in thousandths) are _ID_SPAN apart, exact
# in a double up to 2**53.
_ID_SPAN = 10**9
_SCALE = {"score": 1000, "risk": 1, "grade": 1}
_NO_VALUE = {False: 10**6, True: -1}  # past every value: ascending, descending


@dataclass(frozen=True)
class _Order:
    """A sort (see the module docstring) as one key per run, ``k``: its
    value (no value past the end), then the most recently saved run (the
    higher id) first. A number (``value · 10⁹ ± id``) for risk, score and
    grade; the fixed-width start time and the id as text for time."""

    name: str
    desc: bool

    def key(self) -> str:
        v = _SORT_VALUE[self.name]
        if self.name == "time":
            if self.desc:
                return "COALESCE(m.started_at, '') || printf('%010d', m.history_id)"
            return f"COALESCE(m.started_at, '~') || printf('%010d', {_ID_SPAN * 10 - 1} - m.history_id)"
        scaled = f"ROUND(({v}) * {_SCALE[self.name]})"
        sign = "+" if self.desc else "-"
        return (f"(CASE WHEN ({v}) IS NULL THEN {_NO_VALUE[self.desc]} ELSE {scaled} END)"
                f" * {_ID_SPAN} {sign} m.history_id")

    @property
    def agg(self) -> str:
        """The aggregate that picks a group's first run."""
        return "MAX" if self.desc else "MIN"

    @property
    def by(self) -> str:
        return "k DESC" if self.desc else "k"

    def beyond(self, key: Any, before: bool = False) -> tuple[str, tuple[Any, ...]]:
        """SQL for "after ``key`` in this order" (``before``: before it)."""
        return f"k {'<' if self.desc != before else '>'} ?", (key,)

    def after(self, a: Any, b: Any) -> bool:
        """Whether key ``a`` comes after key ``b`` in this order."""
        return bool(a < b if self.desc else a > b)


def _selection(q: Query) -> tuple[RunSelection, str]:
    sel = query.select_runs(q)
    if q.group in ("relay", "relay_model"):
        sel = sel.with_relay()
    return sel, GROUP_KEY_SQL[q.group]


def _run_value_sql(m: Metric) -> str:
    """A run's own stored value of a History trend metric (what one run
    aggregates to: n = 1)."""
    if m.id == "grade":
        return metrics.grade_value_sql(f"h.{m.column}")
    if m.agg == "pooled":
        return f"CASE WHEN m.{m.base} > 0 THEN m.{m.column} END"
    return f"m.{m.column}" if m.column in METRIC_COLS else f"h.{m.column}"


ROW_COLUMNS: tuple[str, ...] = (
    *(f"h.{c}" for c in (
        "id", "ts", "base_url", "claimed_model", "model", "mode", "suite", "risk_level", "score",
        "rating", "kb_match", "watch_id", "api", "api_auto", "stream_mode")),
    "COALESCE(h.surface, 'chat') AS surface", "m.started_at", "m.started_at_estimated",
    "rm.relay_key", "rm.kind AS relay_kind", "rm.in_kb AS relay_in_kb", "m.latency_p50_ms", "m.ttft_p50_ms", "m.decode_tps_p50", "m.error_rate",
)


def _row(d: Mapping[str, Any]) -> dict[str, Any]:
    """A run's summary row as the list shows it, display decisions made."""
    risk = d["risk_level"] or "inconclusive"
    score = d["score"] if isinstance(d["score"], (int, float)) else None
    grade = d["rating"] or None
    auto = d["api_auto"]
    return {
        "id": int(d["id"]), "ts": d["ts"], "started_at": d["started_at"],
        "started_at_estimated": bool(d["started_at_estimated"]),
        "base_url": d["base_url"], "relay_key": d["relay_key"],
        "_relay": (d["relay_key"], d["relay_kind"], d["relay_in_kb"]),
        "claimed_model": d["claimed_model"] or None, "model": d["model"] or None,
        "mode": d["mode"] or "check", "suite": d["suite"] or None, "surface": d["surface"],
        "api": d["api"] or None, "api_auto": None if auto is None else bool(auto),
        "detect": None if auto is None else "auto" if auto else "manual",
        "stream_mode": d["stream_mode"] or None,
        "risk_level": risk, "score": score, "grade": grade, "kb_match": d["kb_match"],
        "family": {
            "risk": RISK_FAMILY.get(risk, "grey"),
            "score": metrics.family(metrics.METRICS["score"], score),
            "grade": metrics.family(metrics.METRICS["grade"], metrics.grade_value(grade)),
        },
        "watch_id": d["watch_id"], "exec": "manual" if d["watch_id"] is None else "monitor",
        "latency_p50_ms": d["latency_p50_ms"], "ttft_p50_ms": d["ttft_p50_ms"],
        "decode_tps_p50": d["decode_tps_p50"], "error_rate": d["error_rate"],
    }


def _rows(conn: sqlite3.Connection, ids: Sequence[int],
          keep_relay: bool = False) -> dict[int, dict[str, Any]]:
    """The summary rows of some runs, by id (``keep_relay``: with
    ``_relay``, the relay's key, kind and in_kb)."""
    if not ids:
        return {}
    cur = conn.execute(
        f"SELECT {', '.join(ROW_COLUMNS)} FROM history h"
        f" JOIN history_metrics m ON m.history_id = h.id {JOIN_SQL}"
        f" WHERE h.id IN ({', '.join('?' * len(ids))})", tuple(ids))
    names = [c[0] for c in cur.description]
    out = {int(r[0]): _row(dict(zip(names, r, strict=True))) for r in cur.fetchall()}
    if not keep_relay:
        for row in out.values():
            del row["_relay"]
    return out


# --------------------------------------------------------------------------- #
# Relay labels
# --------------------------------------------------------------------------- #
_DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443", "ftp": "21"}
_SPECIAL = {"http", "https", "ws", "wss", "ftp", "file"}


def _split(url: str) -> tuple[str, str] | None:
    """``(host with port, path)`` as the browser's ``URL`` gives ``host`` and
    ``pathname`` (lower-case host, default port dropped); None where ``URL``
    throws (no scheme)."""
    try:
        s = urlsplit(url.strip())
    except ValueError:
        return None
    if not s.scheme:
        return None
    scheme = s.scheme.lower()
    netloc = s.netloc.rpartition("@")[2]
    host, port = netloc, ""
    if netloc.startswith("["):
        end = netloc.find("]")
        host, rest = netloc[:end + 1], netloc[end + 1:]
        port = rest[1:] if rest.startswith(":") else ""
    elif ":" in netloc:
        host, _, port = netloc.rpartition(":")
    host = host.lower()
    if port and port.isdigit():
        port = str(int(port))
    if port == _DEFAULT_PORTS.get(scheme):
        port = ""
    path = s.path or ("/" if scheme in _SPECIAL and host else "")
    return (f"{host}:{port}" if port and host else host), path


def host_of(url: str) -> str:
    """A URL's host with port (``hostOf`` of the History page): the URL
    itself when it has no host."""
    parts = _split(url)
    return (parts[0] if parts else "") or str(url or "")


def url_place(url: str) -> str:
    """Host, port and path of a URL without scheme or trailing slashes
    (``urlPlace`` of the History page); the URL itself when it has no scheme."""
    parts = _split(url)
    if parts is None:
        return str(url or "")
    return (parts[0] + parts[1]).rstrip("/")


def url_labels(urls: Iterable[str]) -> dict[str, str]:
    """The names of unsaved relay URLs: the host with port, or (several URLs
    share it) host, port and path."""
    hosts = {u: host_of(u) for u in dict.fromkeys(u for u in urls if u)}
    count: dict[str, int] = {}
    for h in hosts.values():
        count[h] = count.get(h, 0) + 1
    return {u: url_place(u) if count[h] > 1 else h for u, h in hosts.items()}


_labels_lock = threading.Lock()
_labels_memo: dict[tuple[Any, ...], dict[str, str]] = {}


def relay_labels(conn: sqlite3.Connection) -> dict[str, str]:
    """Every relay key of ``relay_map`` and what it is called (see the
    module docstring); computed once per map content (its knowledge-base
    version and size)."""
    sig = tuple(conn.execute(
        "SELECT (SELECT kb_version FROM relay_map_meta WHERE id = 1),"
        " (SELECT COUNT(*) FROM relay_map), (SELECT MAX(rowid) FROM relay_map)").fetchone())
    with _labels_lock:
        hit = _labels_memo.get(sig)
    if hit is not None:
        return hit
    named: dict[str, str] = {}
    urls: list[str] = []
    for key, label, kind in conn.execute("SELECT DISTINCT relay_key, label, kind FROM relay_map"):
        if kind == "url":
            urls.append(str(key))
        else:
            named[str(key)] = str(label)
    out = {**url_labels(urls), **named}
    with _labels_lock:
        _labels_memo.clear()
        _labels_memo[sig] = out
    return out


def _relay(rk: Any, kind: Any, in_kb: Any, labels: Mapping[str, str]) -> dict[str, Any] | None:
    if rk is None:
        return None
    key = str(rk)
    return {"key": key, "label": labels.get(key) or host_of(key), "kind": str(kind),
            "in_kb": bool(in_kb)}


# --------------------------------------------------------------------------- #
# Trends
# --------------------------------------------------------------------------- #
def _trend(m: Metric, points: list[float], surface: str | None) -> dict[str, Any]:
    first = points[0] if points else None
    last = points[-1] if points else None
    return {"metric": m.id, "points": points, "first": first, "n": len(points),
            "last": metrics.present(m, last, first, n=len(points), surface=surface)}


def run_trends(conn: sqlite3.Connection, rid: int) -> dict[str, Any] | None:
    """Every History trend metric of one run, as a group of that run alone
    shows its last value (:func:`ekte.web.metrics.present`); None when the
    run is not in the analytics tables."""
    specs = [metrics.METRICS[mid] for mid in HISTORY_TRENDS]
    row = conn.execute(
        f"SELECT COALESCE(h.surface, 'chat'), {', '.join(_run_value_sql(m) for m in specs)}"
        " FROM history h JOIN history_metrics m ON m.history_id = h.id WHERE h.id = ?",
        (int(rid),)).fetchone()
    if row is None:
        return None
    surface = str(row[0])
    return {m.id: _trend(m, [] if v is None else [float(v)], surface)["last"]
            for m, v in zip(specs, row[1:], strict=True)}


# --------------------------------------------------------------------------- #
# GET /api/history/groups
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Head:
    key: str
    runs: int
    sort_key: Any


def _heads(conn: sqlite3.Connection, sel: RunSelection, gk: str, order: _Order) -> list[_Head]:
    """Each group's first run under the sort (its key), the groups in that
    order: one aggregate pass."""
    cur = conn.execute(f"SELECT {gk} AS g, COUNT(*), {order.agg}({order.key()}) AS k {sel.sql}"
                       f" GROUP BY g ORDER BY {order.by}", sel.args)
    return [_Head(str(r[0]), int(r[1]), r[2]) for r in cur.fetchall()]


def groups(conn: sqlite3.Connection, params: Any) -> dict[str, Any]:
    """``GET /api/history/groups``: one page of groups (see
    ``docs/dev/web-server.md`` for the shape)."""
    q, widget = parse_widget("groups", params)
    sort, name, desc = _sort(_one(widget, "groups.sort"), "groups.sort")
    limit = _limit(_one(widget, "groups.limit"), "groups.limit")
    focus = _focus(_one(widget, "groups.focus"), "groups.focus")
    after = _one(widget, "groups.after")
    wanted = trend_metrics(widget.get("trend.metrics"))
    sel, gk = _selection(q)
    order = _Order(name, desc)
    heads = _heads(conn, sel, gk, order)

    start = 0
    if after:
        cut = _uncursor(after, "groups", sort, "groups.after")
        start = next((i for i, h in enumerate(heads) if order.after(h.sort_key, cut)), len(heads))
    end = min(len(heads), start + limit)
    focus_out = None
    if focus is not None:
        fsel = sel.and_where("m.history_id = ?", focus)
        row = conn.execute(f"SELECT {gk} {fsel.sql}", fsel.args).fetchone()
        if row is not None:
            fkey = str(row[0])
            at = next(i for i, h in enumerate(heads) if h.key == fkey)
            if at >= end:  # the page grows to the page that holds it
                end = min(len(heads), start + math.ceil((at - start + 1) / limit) * limit)
            focus_out = {"id": focus, "key": fkey}
    page = heads[start:end]
    nxt = _cursor("groups", sort, page[-1].sort_key) if page and end < len(heads) else None

    return {
        "group": q.group, "sort": sort, "limit": limit,
        "trend_metrics": [m.id for m in wanted], "points_max": POINTS, "min_runs": MIN_RUNS,
        "total_groups": len(heads), "total_runs": sum(h.runs for h in heads),
        "groups": _describe(conn, q, sel, gk, page, wanted), "after": nxt, "focus": focus_out,
    }


def _describe(conn: sqlite3.Connection, q: Query, sel: RunSelection, gk: str,
              page: list[_Head], wanted: list[Metric]) -> list[dict[str, Any]]:
    if not page:
        return []
    keys = [h.key for h in page]
    sel = sel.and_where(f"{gk} IN ({', '.join('?' * len(keys))})", *keys)
    vals = ", ".join(f"{_run_value_sql(m)} AS v{i}" for i, m in enumerate(wanted))
    cur = conn.execute(
        f"SELECT g, id, {', '.join(f'v{i}' for i in range(len(wanted)))} FROM ("
        f"SELECT {gk} AS g, m.history_id AS id, {vals},"
        f" ROW_NUMBER() OVER (PARTITION BY {gk} ORDER BY {_NEWEST}) AS rn {sel.sql})"
        f" WHERE rn <= {POINTS} ORDER BY g, rn DESC", sel.args)
    points: dict[str, list[list[float]]] = {k: [[] for _ in wanted] for k in keys}
    latest: dict[str, int] = {}
    for g, rid, *values in cur.fetchall():
        g = str(g)
        latest[g] = int(rid)  # rn descending: the newest comes last
        for i, v in enumerate(values):
            if v is not None:
                points[g][i].append(float(v))
    urls: dict[str, list[str]] = {k: [] for k in keys}
    usel = sel.and_where("NULLIF(h.base_url, '') IS NOT NULL")
    for g, url in conn.execute(
            f"SELECT {gk} AS g, h.base_url {usel.sql}"
            " GROUP BY g, h.base_url ORDER BY g, MAX(m.started_at) DESC, h.base_url", usel.args):
        urls[str(g)].append(str(url))
    rows = _rows(conn, list(latest.values()), keep_relay=True)
    by_relay = q.group in ("relay", "relay_model")
    labels = relay_labels(conn) if by_relay else {}
    out = []
    for h in page:
        row = rows.get(latest.get(h.key, -1))
        rel = row.pop("_relay") if row else None
        relay = _relay(*rel, labels) if rel and by_relay else None
        model = row["claimed_model"] if row and q.group in ("model", "relay_model") else None
        out.append({
            "key": h.key, "kind": q.group, "relay": relay, "claimed_model": model,
            "label": (relay["label"] if relay else None) if q.group == "relay"
            else (model or UNKNOWN_RELAY) if q.group == "model" else ALL_KEY if q.group == "all"
            else f"{relay['label'] if relay else UNKNOWN_RELAY} · {model or UNKNOWN_RELAY}",
            "base_urls": urls[h.key], "runs": h.runs, "low_n": h.runs < MIN_RUNS,
            "latest": row,
            "trends": {m.id: _trend(m, points[h.key][i], q.surface)
                       for i, m in enumerate(wanted)},
        })
    return out


# --------------------------------------------------------------------------- #
# GET /api/history/runs
# --------------------------------------------------------------------------- #
def runs(conn: sqlite3.Connection, params: Any) -> dict[str, Any]:
    """``GET /api/history/runs``: one page of one group's runs (see
    ``docs/dev/web-server.md`` for the shape)."""
    q, widget = parse_widget("runs", params)
    gkey = _one(widget, "group.key")
    if gkey is None:
        raise QueryError("group.key is required")
    sort, name, desc = _sort(_one(widget, "runs.sort"), "runs.sort")
    limit = _limit(_one(widget, "runs.limit"), "runs.limit")
    focus = _focus(_one(widget, "runs.focus"), "runs.focus")
    after = _one(widget, "runs.after")
    sel, gk = _selection(q)
    sel = sel.and_where(f"{gk} = ?", gkey)
    order = _Order(name, desc)
    base = f"SELECT m.history_id AS id, {order.key()} AS k {sel.sql}"
    cut = _uncursor(after, "runs", sort, "runs.after") if after else None
    later, cut_args = order.beyond(cut) if cut is not None else ("1", ())
    total = int(conn.execute(f"SELECT COUNT(*) {sel.sql}", sel.args).fetchone()[0])

    focus_out = None
    if focus is not None:
        fsel = sel.and_where("m.history_id = ?", focus)
        row = conn.execute(f"SELECT {order.key()} {fsel.sql}", fsel.args).fetchone()
        hit = row is not None and (cut is None or order.after(row[0], cut))
        if hit:  # the page grows to the page that holds it
            ahead, ahead_args = order.beyond(row[0], before=True)
            before = int(conn.execute(f"SELECT COUNT(*) FROM ({base}) WHERE {later} AND {ahead}",
                                      (*sel.args, *cut_args, *ahead_args)).fetchone()[0])
            limit = max(limit, math.ceil((before + 1) / limit) * limit)
        focus_out = {"id": focus, "found": hit}

    found = conn.execute(f"SELECT id, k FROM ({base}) WHERE {later} ORDER BY {order.by} LIMIT ?",
                         (*sel.args, *cut_args, limit + 1)).fetchall()
    nxt = _cursor("runs", sort, found[limit - 1][1]) if len(found) > limit else None
    ids = [int(r[0]) for r in found[:limit]]
    rows = _rows(conn, ids)
    return {"group": q.group, "key": gkey, "sort": sort, "limit": limit, "total": total,
            "rows": [rows[i] for i in ids if i in rows], "after": nxt, "focus": focus_out}
