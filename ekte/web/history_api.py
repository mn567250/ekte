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
* ties: the newer run first (start time, then id, both descending).

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
_TIME_VALUE = "julianday(m.started_at)"
_SORT_VALUE = {
    "time": _TIME_VALUE,
    "risk": _RISK_VALUE,
    # a score is a number or NULL (written from floats)
    "score": "h.score",
    "grade": metrics.grade_value_sql("h.rating"),
}
_ORDER = "k0, k1, k2, k3, k4"
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
def _cursor(kind: str, sort: str, keys: Sequence[Any]) -> str:
    raw = json.dumps([kind, sort, list(keys)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _uncursor(after: str, kind: str, sort: str, key: str) -> tuple[Any, ...]:
    try:
        raw = base64.urlsafe_b64decode(after + "=" * (-len(after) % 4))
        k, s, keys = json.loads(raw)
    except (ValueError, TypeError, binascii.Error):
        raise QueryError(f"{key} is not a valid cursor") from None
    if (k, s) != (kind, sort) or not isinstance(keys, list) or len(keys) != 5 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in keys):
        raise QueryError(f"{key} is not a cursor of this sort")
    return tuple(keys)


# --------------------------------------------------------------------------- #
# SQL pieces
# --------------------------------------------------------------------------- #
def _keys_sql(name: str, desc: bool) -> str:
    """The sort as five ascending keys ``k0`` … ``k4`` (see the module
    docstring): no value last, the value, then newest first."""
    v = _SORT_VALUE[name]
    sign = "-" if desc else ""
    return (f"({v}) IS NULL AS k0, {sign}COALESCE({v}, 0) AS k1,"
            f" {_TIME_VALUE} IS NULL AS k2, -COALESCE({_TIME_VALUE}, 0) AS k3,"
            " -m.history_id AS k4")


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
    "rm.relay_key", "m.latency_p50_ms", "m.ttft_p50_ms", "m.decode_tps_p50", "m.error_rate",
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


def _rows(conn: sqlite3.Connection, ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    """The summary rows of some runs, by id."""
    if not ids:
        return {}
    cur = conn.execute(
        f"SELECT {', '.join(ROW_COLUMNS)} FROM history h"
        f" JOIN history_metrics m ON m.history_id = h.id {JOIN_SQL}"
        f" WHERE h.id IN ({', '.join('?' * len(ids))})", tuple(ids))
    names = [c[0] for c in cur.description]
    return {int(r[0]): _row(dict(zip(names, r, strict=True))) for r in cur.fetchall()}


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
    rid: int
    runs: int
    keys: tuple[Any, ...]


def _heads(conn: sqlite3.Connection, sel: RunSelection, gk: str, name: str,
           desc: bool) -> list[_Head]:
    """Each group's first run under the sort, the groups in that order."""
    cur = conn.execute(
        f"WITH r AS MATERIALIZED (SELECT {gk} AS g, m.history_id AS id, {_keys_sql(name, desc)}"
        f" {sel.sql}),"
        f" b AS (SELECT g, id, {_ORDER}, ROW_NUMBER() OVER w AS rn, COUNT(*) OVER (PARTITION BY g)"
        f" AS runs FROM r WINDOW w AS (PARTITION BY g ORDER BY {_ORDER}))"
        f" SELECT g, id, runs, {_ORDER} FROM b WHERE rn = 1 ORDER BY {_ORDER}", sel.args)
    return [_Head(str(r[0]), int(r[1]), int(r[2]), tuple(r[3:])) for r in cur.fetchall()]


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
    heads = _heads(conn, sel, gk, name, desc)

    start = 0
    if after:
        cut = _uncursor(after, "groups", sort, "groups.after")
        start = next((i for i, h in enumerate(heads) if h.keys > cut), len(heads))
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
    nxt = _cursor("groups", sort, page[-1].keys) if page and end < len(heads) else None

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
    rows = _rows(conn, list(latest.values()))
    labels = relay_labels(conn) if q.group in ("relay", "relay_model") else {}
    rm = {}
    if labels:
        rm = {int(r[0]): r[1:] for r in conn.execute(
            f"SELECT h.id, rm.relay_key, rm.kind, rm.in_kb FROM history h"
            f" JOIN history_metrics m ON m.history_id = h.id {JOIN_SQL}"
            f" WHERE h.id IN ({', '.join('?' * len(latest))})", tuple(latest.values()))}
    out = []
    for h in page:
        row = rows.get(latest.get(h.key, -1))
        relay = _relay(*rm[row["id"]], labels) if row and row["id"] in rm else None
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
    base = f"SELECT m.history_id AS id, {_keys_sql(name, desc)} {sel.sql}"
    cut = _uncursor(after, "runs", sort, "runs.after") if after else None
    later = f" WHERE ({_ORDER}) > (?, ?, ?, ?, ?)" if cut else ""
    cut_args = tuple(cut or ())
    total = int(conn.execute(f"SELECT COUNT(*) {sel.sql}", sel.args).fetchone()[0])

    focus_out = None
    if focus is not None:
        fk = conn.execute(f"SELECT {_ORDER} FROM ({base}) WHERE id = ?",
                          (*sel.args, focus)).fetchone()
        if fk is not None:
            fk = tuple(fk)
            if cut is None or fk > cut:
                before = int(conn.execute(
                    f"SELECT COUNT(*) FROM ({base}){later or ' WHERE 1'} AND ({_ORDER}) < (?, ?, ?, ?, ?)",
                    (*sel.args, *cut_args, *fk)).fetchone()[0])
                limit = max(limit, math.ceil((before + 1) / limit) * limit)
                focus_out = {"id": focus, "found": True}
        if focus_out is None:
            focus_out = {"id": focus, "found": False}

    found = conn.execute(f"SELECT id, {_ORDER} FROM ({base}){later} ORDER BY {_ORDER} LIMIT ?",
                         (*sel.args, *cut_args, limit + 1)).fetchall()
    nxt = _cursor("runs", sort, tuple(found[limit - 1][1:])) if len(found) > limit else None
    ids = [int(r[0]) for r in found[:limit]]
    rows = _rows(conn, ids)
    return {"group": q.group, "key": gkey, "sort": sort, "limit": limit, "total": total,
            "rows": [rows[i] for i in ids if i in rows], "after": nxt, "focus": focus_out}
