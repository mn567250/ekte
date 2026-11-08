"""The Analytics widget endpoints on the query core: one function per widget.

What ``ekte serve`` answers under ``/api/analytics/*`` and
``/api/filters/options`` (request and response shapes: docs/dev/web-server.md).
Each function takes the request parameters: the shared URL schema of
:mod:`ekte.web.query` plus the widget's own namespaced keys (``kpi.*``,
``trend.*``, ``heat.*``, ``board.*``, ``breakdown.*``, ``errors.*``,
``integrity.*``); an unknown key, shared or of the widget, raises
:class:`~ekte.web.query.QueryError` (400). Runs are selected, grouped and
aggregated in SQLite (:func:`ekte.web.query.aggregate`,
:func:`~ekte.web.query.series`, and a few grouped queries here); Python only
shapes the answer and judges values with :func:`ekte.web.metrics.present`. No
function loads runs or request records into Python, and every answer's size
depends on the number of groups and buckets, never on the number of runs.

Without ``surface`` a widget uses the most common surface of the selection
(:func:`ekte.web.query.default_surface`), so runs of different surfaces never
mix; the answer names it (``surface``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from ekte import errorclass
from ekte.web import analytics_store, history, query
from ekte.web import metrics as _metrics
from ekte.web.analytics import (
    BLOCKS,
    BUCKETS,
    FOLDS,
    INTEGRITY_CHECKS,
    JUDGED,
    MAX_METRICS,
    MAX_PARAM,
    METRICS,
    MIN_RUNS,
    Metric,
    _bucket,
    _most_common,
    metric,
)
from ekte.web.relay_map import GROUP_KEY_SQL

# Metrics of each leaderboard row (the median score ranks them).
BOARD_METRICS = (
    "score", "success_rate", "error_rate", "latency_p50", "ttft_p50", "decode_tps",
    "billing_ratio_prompt", "billing_ratio_completion", "model_mismatch_rate", "risk_high_share",
)
BOARD_GROUPS = ("relay", "model", "relay_model")
TREND_BUCKETS = ("hour", "day", "week")
# The outcome classes of the errors widget.
ERROR_CLASSES = errorclass.OUTCOMES


def _widget(params: Any, ns: str, single: Iterable[str] = (),
            multi: Iterable[str] = ()) -> dict[str, Any]:
    """The widget's own keys (``<ns>.<key>``): single ones as a string, repeated
    ones as a list. An unknown key of this widget, or a single key given twice,
    raises :class:`~ekte.web.query.QueryError`; other widgets' keys are ignored."""
    single, multi = tuple(single), tuple(multi)
    out: dict[str, Any] = {k: [] for k in multi}
    prefix = ns + "."
    for key, value in query._pairs(params):
        if not key.startswith(prefix):
            continue
        name = key[len(prefix):]
        if len(value) > MAX_PARAM:
            raise query.QueryError(f"{key} is longer than {MAX_PARAM} characters")
        if name in multi:
            if value not in out[name]:
                out[name].append(value)
        elif name in single:
            if name in out:
                raise query.QueryError(f"{key} given more than once")
            out[name] = value
        else:
            raise query.QueryError(f"unknown parameter {key[:64]!r}")
    return out


def _setup(params: Any) -> tuple[Any, query.Query]:
    """This thread's query connection and the parsed shared filters, with the
    surface defaulted."""
    q = query.parse_query(params)
    conn = history.query_connection()
    if q.surface is None:
        q = q.replace(surface=query.default_surface(conn, q))
    return conn, q


def _range(q: query.Query) -> dict[str, str | None]:
    return {"from": analytics_store.format_ts(q.start) if q.start else None,
            "to": analytics_store.format_ts(q.end) if q.end else None}


def _head(q: query.Query) -> dict[str, Any]:
    """What every widget answer starts with: the range, the surface, the
    canonical filters and :data:`MIN_RUNS`."""
    return {**_range(q), "surface": q.surface, "filters": q.canonical(), "min_runs": MIN_RUNS}


def _int_choice(w: Mapping[str, Any], name: str, key: str, allowed: tuple[int, ...],
                default: int) -> int:
    raw = w.get(name)
    if raw is None:
        return default
    if raw not in {str(a) for a in allowed}:
        raise query.QueryError(f"{key} must be one of {', '.join(str(a) for a in allowed)}")
    return int(raw)


def _str_choice(w: Mapping[str, Any], name: str, key: str, allowed: tuple[str, ...],
                default: str) -> str:
    value = w.get(name) or default
    if value not in allowed:
        raise query.QueryError(f"{key} must be one of {', '.join(allowed)}")
    return str(value)


def _judged(m: Metric, cell: Mapping[str, Any]) -> dict[str, Any]:
    """A cell (``Cell.public()`` or a point) with the judgement of its value:
    ``family`` and ``grade``, as :func:`ekte.web.metrics.present` gives them
    (its other fields are not needed: thousands of cells per board)."""
    v = _metrics._number(cell.get("value"))
    return {**cell, "family": _metrics.family(m, v), "grade": _metrics._grade(m, v)}


def resolve_params(params: Any, *, now: datetime | None = None) -> list[tuple[str, str]]:
    """The ``prepare`` of the widget endpoints: :func:`ekte.web.query.resolve_params`
    (``range`` resolved), and ``from`` without ``to`` bounded at now (the next
    whole minute), so every
    answer is cached under an absolute range."""
    pairs = query.resolve_params(params, now=now)
    keys = {k for k, _ in pairs}
    if "from" in keys and "to" not in keys and "range" not in keys:
        # rounded up to the next whole minute, as range=: a minute's requests share an answer
        pairs.append(("to", analytics_store.format_ts(query._ceil_minute((now or datetime.now(UTC)).astimezone(UTC)))))
    return pairs


# --------------------------------------------------------------------------- #
# KPI grid
# --------------------------------------------------------------------------- #
def _kpi_cells(conn: Any, q: query.Query) -> dict[str, query.Cell]:
    """The KPI grid's cells over ``q``'s runs: the counts and every grid metric
    that applies to ``q.surface``."""
    wanted = [mid for mid in _metrics.KPI_GRID if mid in METRICS and METRICS[mid].applies(str(q.surface))]
    # one pass: the metrics and the distinct relays (their ids) and models
    specs, rows = query._grouped(
        conn, query.select_runs(q), "all", query._metrics(wanted, q.surface),
        extra=("COUNT(DISTINCT m.relay_id)", "COUNT(DISTINCT NULLIF(h.claimed_model, ''))"))
    row = rows[0] if rows else {"runs": 0, "x0": 0, "x1": 0}
    runs, relays, models = int(row["runs"]), int(row["x0"]), int(row["x1"])
    found = query._cells(specs, row) if rows else {}
    full = 1.0 if runs else None
    cells = {"runs": query.Cell(float(runs), int(runs), full, False),
             "relays": query.Cell(float(relays), int(runs), full, False),
             "models": query.Cell(float(models), int(runs), full, False)}
    for mid in wanted:
        cells[mid] = found.get(mid) or query.Cell(None, 0, None, True)
    return cells


def widget_summary(params: Any) -> dict[str, Any]:
    """``GET /api/analytics/summary``: the 12 tiles of
    :data:`ekte.web.metrics.KPI_GRID`, in order, over the range and over the
    previous range of the same length (none without ``from``)."""
    _widget(params, "kpi")
    conn, q = _setup(params)
    prev_q: query.Query | None = None
    start = q.start
    if start is not None:
        end = q.end or datetime.now(UTC)
        q = q.replace(end=end)
        try:
            prev_q = q.replace(start=start - (end - start), end=start)
        except OverflowError:
            prev_q = None
    now = _kpi_cells(conn, q)
    then = _kpi_cells(conn, prev_q) if prev_q is not None else {}
    tiles = []
    for mid in _metrics.KPI_GRID:
        m = _metrics.get(mid)
        cur, prev = now.get(mid), then.get(mid)
        shown = _metrics.present(m, cur.value if cur else None, prev.value if prev else None,
                                 cur.n if cur else None, prev.n if prev else None, surface=q.surface)
        applies = shown["applies"]
        tiles.append({
            "id": mid, **shown,
            "n": cur.n if cur and applies else None,
            "coverage": cur.coverage if cur and applies else None,
            "previous": prev.value if prev and applies else None,
            "previous_n": prev.n if prev and applies else None,
            "numerator": cur.numerator if cur else None,
            "denominator": cur.denominator if cur else None,
            "format": m.format, "label_key": m.kpi_label_key,
        })
    return {**_head(q), "previous": _range(prev_q) if prev_q else None,
            "runs": int(now["runs"].n), "tiles": tiles}


# --------------------------------------------------------------------------- #
# Trend chart and heatmap
# --------------------------------------------------------------------------- #
def _series_public(result: query.SeriesResult) -> dict[str, Any]:
    out = result.public()
    for s in out["series"]:
        s["points"] = [_judged(result.metric, p) for p in s["points"]]
    return out


def widget_series(params: Any) -> dict[str, Any]:
    """``GET /api/analytics/series``: one metric per group (``group``) over
    time buckets. ``trend.metric`` (default score), ``trend.bucket`` (hour,
    day, week), ``trend.tz`` (IANA, default UTC), ``trend.key`` (repeatable,
    up to :data:`MAX_KEYS` series keys; default the busiest groups)."""
    w = _widget(params, "trend", ("metric", "bucket", "tz"), ("key",))
    conn, q = _setup(params)
    bucket = _str_choice(w, "bucket", "trend.bucket", TREND_BUCKETS, "day")
    result = query.series(conn, q, w.get("metric") or "score", None, bucket, w.get("tz") or "UTC",
                          keys=w["key"], quantiles=True)
    return {**_head(q), **_series_public(result)}


def widget_heatmap(params: Any) -> dict[str, Any]:
    """``GET /api/analytics/heatmap``: one metric on the weekday x time-of-day
    grid (a series with bucket ``dow_hour``). ``heat.metric`` (default score),
    ``heat.block`` (hours per row: 1, 2, 3, 4, 6), ``heat.fold`` (week,
    4weeks, month_week), ``heat.tz``, ``heat.key`` (one series key of
    ``group``; default every selected run as one series, group ``all``)."""
    w = _widget(params, "heat", ("metric", "block", "fold", "tz", "key"))
    conn, q = _setup(params)
    block = _int_choice(w, "block", "heat.block", BLOCKS, 1)
    fold = _str_choice(w, "fold", "heat.fold", FOLDS, "week")
    key = w.get("key")
    result = query.series(conn, q, w.get("metric") or "score", None if key else "all", "dow_hour",
                          w.get("tz") or "UTC", keys=[key] if key else (), block=block, fold=fold,
                          max_keys=1)
    return {**_head(q), **_series_public(result)}


# --------------------------------------------------------------------------- #
# Leaderboard and breakdown
# --------------------------------------------------------------------------- #
def _rows(groups: list[query.GroupResult], wanted: list[Metric]) -> list[dict[str, Any]]:
    by_id = {m.id: m for m in wanted}
    out = []
    for g in groups:
        row = g.public()
        row["metrics"] = {mid: _judged(by_id[mid], c) for mid, c in row["metrics"].items()}
        out.append(row)
    return out


def widget_leaderboard(params: Any) -> dict[str, Any]:
    """``GET /api/analytics/leaderboard``: one row per ``board.by`` (relay,
    model, relay_model; default relay) with :data:`BOARD_METRICS`, best
    median score first (rows without a score last). Rank the relays of one
    model with ``model=<m>&board.by=relay``."""
    w = _widget(params, "board", ("by",))
    conn, q = _setup(params)
    by = _str_choice(w, "by", "board.by", BOARD_GROUPS, "relay")
    wanted = [METRICS[mid] for mid in BOARD_METRICS if METRICS[mid].applies(str(q.surface))]
    rows = _rows(query.aggregate(conn, q, wanted, by), wanted)

    def rank(row: dict[str, Any]) -> tuple[Any, ...]:
        score = row["metrics"]["score"]["value"]
        return (score is None, -(score or 0.0), -row["runs"], row["label"].lower(), row["key"])

    rows.sort(key=rank)
    return {**_head(q), "by": by, "metrics": [m.public() for m in wanted], "rows": rows}


def widget_breakdown(params: Any) -> dict[str, Any]:
    """``GET /api/analytics/breakdown``: some metrics (``breakdown.metric``,
    repeatable, 1 to :data:`MAX_METRICS`; ``dim:<key>`` included) per group
    (``group``) over the whole range, with quartiles, busiest group first."""
    w = _widget(params, "breakdown", (), ("metric",))
    conn, q = _setup(params)
    wanted: list[Metric] = []
    for mid in w["metric"]:
        m = metric(mid, q.surface)
        if m not in wanted:
            wanted.append(m)
    if not wanted:
        raise query.QueryError("give at least one breakdown.metric")
    if len(wanted) > MAX_METRICS:
        raise query.QueryError(f"at most {MAX_METRICS} breakdown.metric")
    groups = query.aggregate(conn, q, wanted, quantiles=True)
    return {**_head(q), "group": q.group, "metrics": [m.public() for m in wanted],
            "runs": sum(g.runs for g in groups), "rows": _rows(groups, wanted)}


# --------------------------------------------------------------------------- #
# Errors (request outcomes)
# --------------------------------------------------------------------------- #
def _sql_list(names: Iterable[str]) -> str:
    return "(" + ", ".join("'" + n.replace("'", "''") + "'" for n in sorted(names)) + ")"


_RECORD_CLASS_SQL = (
    f"CASE WHEN error_class IN {_sql_list(errorclass.ERROR_CLASSES)} THEN error_class"
    " WHEN status_code IS NOT NULL THEN 'relay'"
    f" WHEN error_type IN {_sql_list(errorclass._RELAY_TYPES)} THEN 'relay'"
    f" WHEN error_type IN {_sql_list(errorclass._LOCAL_TYPES | errorclass._LOCAL_NAMES)} THEN 'local'"
    f" WHEN error_type IN {_sql_list(errorclass._NETWORK_NAMES)} THEN 'network'"
    " ELSE 'relay' END"
)
OUTCOME_SQL = (
    "CASE WHEN COALESCE(retried, 0) != 0"
    f" OR COALESCE(phase, '') IN {_sql_list(errorclass._UNCOUNTED_PHASES)} THEN NULL"
    f" WHEN COALESCE(ok, 0) != 0 THEN '{errorclass.SUCCESS}'"
    f" WHEN ({_RECORD_CLASS_SQL}) IN {_sql_list(errorclass.IMPAIRED)} THEN ({_RECORD_CLASS_SQL})"
    f" WHEN COALESCE(rate_limited, 0) != 0 OR status_code = 429 THEN '{errorclass.RATE_LIMITED}'"
    f" WHEN COALESCE(timeout, 0) != 0 THEN '{errorclass.RELAY_TIMEOUT}'"
    f" WHEN status_code BETWEEN 500 AND 599 THEN '{errorclass.RELAY_5XX}'"
    f" WHEN status_code BETWEEN 400 AND 499 THEN '{errorclass.RELAY_4XX}'"
    f" ELSE '{errorclass.RELAY_OTHER}' END"
)
""":func:`ekte.errorclass.outcome` as SQL over a ``history_requests`` row
(NULL: a record that never counts). Tested equal to the Python rules."""


def outcome_shares(counts: Mapping[str, Any]) -> dict[str, Any]:
    """Pooled counts and rates of some requests: ``requests`` (all),
    ``judged`` (all − network − local), ``shares`` (each relay outcome over
    judged, network / local over all), ``success_rate``,
    ``rate_limited_rate``, ``relay_error_rate`` (they add up to 1 with a
    judged request) and ``timeout_rate`` over judged, and ``impaired_rate``
    over all."""
    c = {k: int(counts.get(k) or 0) for k in ERROR_CLASSES}
    total = sum(c.values())
    impaired = sum(c[k] for k in errorclass.IMPAIRED)
    judged = total - impaired

    def over(n: int, base: int) -> float | None:
        return n / base if base else None

    return {
        "counts": c, "requests": total, "judged": judged,
        "shares": {k: over(v, total if k in errorclass.IMPAIRED else judged) for k, v in c.items()},
        "success_rate": over(c[errorclass.SUCCESS], judged),
        "rate_limited_rate": over(c[errorclass.RATE_LIMITED], judged),
        "relay_error_rate": over(sum(c[k] for k in errorclass.RELAY_ERRORS), judged),
        "timeout_rate": over(c[errorclass.RELAY_TIMEOUT], judged),
        "impaired_rate": over(impaired, total),
    }


# Per group or bucket: the runs with outcome counts and the sum of each
# outcome (the run's pivoted history_outcomes, analytics_store.OUTCOME_COLS).
_OUTCOME_AGGS = (f"COUNT(m.{analytics_store.OUTCOME_COLS[ERROR_CLASSES[0]]})",
                 *(f"SUM(m.{analytics_store.OUTCOME_COLS[c]})" for c in ERROR_CLASSES))


def _outcome_rows(conn: Any, sel: query.RunSelection, group: str,
                  buckets: list[str] | None = None) -> list[dict[str, Any]]:
    """The errors widget's rows (:func:`ekte.web.query._grouped`: one pass
    over the selected runs' own rows, grouped by the relay id / model on
    them): per group, or per time bucket of the dated runs (``buckets``),
    ``runs``, ``covered`` (runs with outcome counts) and each outcome's sum."""
    if buckets is not None:
        sel = sel.and_where(query._DATED_SQL)
    _, rows = query._grouped(conn, sel, group, [], buckets=buckets or (), extra=_OUTCOME_AGGS)
    for r in rows:
        r["covered"] = int(r["x0"] or 0)
        r["counts"] = {c: int(r[f"x{i + 1}"] or 0) for i, c in enumerate(ERROR_CLASSES)}
    return rows


def run_timeline(conn: Any, rid: int) -> list[dict[str, Any]]:
    """One run's target requests per whole minute after its start, by outcome
    (:data:`OUTCOME_SQL` over its ``history_requests``, one indexed query)."""
    rows = conn.execute(
        "SELECT CAST(COALESCE(start_ms, 0) / 60000 AS INTEGER) AS minute,"
        f" {OUTCOME_SQL} AS outcome, COUNT(*) FROM history_requests"
        " WHERE history_id = ? AND COALESCE(endpoint, 'target') = 'target'"
        " GROUP BY minute, outcome ORDER BY minute", (int(rid),)).fetchall()
    by_minute: dict[int, dict[str, int]] = {}
    for minute, out, n in rows:
        if out is not None:
            by_minute.setdefault(int(minute), {})[str(out)] = int(n)
    return [{"minute": mnt, **outcome_shares(c)} for mnt, c in sorted(by_minute.items())]


def widget_errors(params: Any) -> dict[str, Any]:
    """``GET /api/analytics/errors``: the selected runs' target requests by
    outcome (:data:`ERROR_CLASSES`, from ``history_outcomes``), pooled per group
    (``group``), in total and per time bucket of the run's start
    (``errors.bucket``: hour, day, week, dow_hour; ``errors.block`` for
    dow_hour; ``errors.tz``). ``errors.run=<id>``: also that run's per-minute
    timeline (``run``), classified from its request records."""
    w = _widget(params, "errors", ("bucket", "block", "tz", "run"))
    conn, q = _setup(params)
    size = _str_choice(w, "bucket", "errors.bucket", BUCKETS, "day")
    block = _int_choice(w, "block", "errors.block", BLOCKS, 1)
    zone, zone_name = query._zone(w.get("tz") or "UTC")
    rid = None
    if w.get("run") is not None:
        if not w["run"].isdigit():
            raise query.QueryError("errors.run must be a run id")
        rid = int(w["run"])

    sel = query.select_runs(q)
    totals = dict.fromkeys(ERROR_CLASSES, 0)
    groups, buckets = [], []

    def cell(r: Mapping[str, Any]) -> dict[str, Any]:
        runs, covered = int(r["runs"]), r["covered"]
        return {"runs": runs, "covered": covered, "low_n": covered < MIN_RUNS,
                **outcome_shares(r["counts"])}

    for r in _outcome_rows(conn, sel, q.group):
        for k, v in r["counts"].items():
            totals[k] += v
        c = cell(r)
        groups.append({**query._result(q.group, r, {}).describe(), **c,
                       "coverage": c["covered"] / c["runs"] if c["runs"] else None})
    bounds = query._data_bounds(conn)
    if bounds is not None:
        offset = query.offset_sql(zone, query._offset_points(conn, sel, *bounds))
        for r in _outcome_rows(conn, sel, "all", query._bucket_sql(size, offset, block, "week")):
            start = analytics_store.parse_ts(r["t_min"])
            assert start is not None
            pos, bkey, extra = _bucket(start, zone, size, block)
            buckets.append((pos, {"bucket": bkey, **extra, **cell(r)}))
    groups.sort(key=lambda g: (-g["requests"], -g["runs"], g["label"].lower(), g["key"]))
    runs = sum(g["runs"] for g in groups)
    covered = sum(g["covered"] for g in groups)
    out: dict[str, Any] = {
        **_head(q), "group": q.group, "bucket": size, "block": block, "tz": zone_name,
        "classes": list(ERROR_CLASSES), "runs": runs, "covered": covered,
        "coverage": covered / runs if runs else None,
        "totals": outcome_shares(totals), "groups": groups,
        "buckets": [b for _, b in sorted(buckets, key=lambda item: item[0])],
    }
    if rid is not None:
        out["run"] = {"id": rid, "minutes": run_timeline(conn, rid)}
    return out


# --------------------------------------------------------------------------- #
# Model integrity
# --------------------------------------------------------------------------- #
def widget_integrity(params: Any) -> dict[str, Any]:
    """``GET /api/analytics/integrity``: one row per relay x model: the
    status counts of each integrity check (:data:`INTEGRITY_CHECKS`;
    ``other`` = not judged), the model-mismatch share, and the effective
    context window as a share of the declared one (median over the runs that
    measured both; chat only)."""
    _widget(params, "integrity")
    conn, q = _setup(params)
    chat = METRICS["context_claimed"].applies(str(q.surface))
    wanted = ["model_mismatch_rate", *(("context_claimed", "context_effective") if chat else ())]
    groups = query.aggregate(conn, q, wanted, "relay_model")
    gk = GROUP_KEY_SQL["relay_model"]
    sel = query.select_runs(q).with_relay()
    checks: dict[str, dict[str, dict[str, int]]] = {}
    for g, key, status, n in conn.execute(
        f"SELECT {gk}, d.key, CASE WHEN d.status IN {_sql_list(JUDGED)} THEN d.status ELSE 'other' END,"
        f" COUNT(*) {sel.from_sql} JOIN history_dimensions d ON d.history_id = h.id"
        f" AND d.kind = 'detector' AND d.key IN {_sql_list(INTEGRITY_CHECKS)}{sel.where_sql}"
        " GROUP BY 1, 2, 3", sel.args):
        cell = checks.setdefault(str(g), {}).setdefault(str(key), {"pass": 0, "warn": 0, "fail": 0, "other": 0})
        cell[str(status)] += int(n)
    ratios: dict[str, tuple[Any, ...]] = {}
    if chat:
        med, pct = query.sql_functions(conn)
        v = ("CASE WHEN m.context_claimed_tokens > 0 AND m.context_effective_tokens IS NOT NULL"
             " THEN CAST(m.context_effective_tokens AS REAL) / m.context_claimed_tokens END")
        ratios = {str(r[0]): tuple(r[1:]) for r in conn.execute(
            f"SELECT {gk}, {med}({v}), {pct}({v}, 25), {pct}({v}, 75), COUNT({v}) {sel.sql} GROUP BY 1",
            sel.args)}
    present = {k for per in checks.values() for k in per}
    shown = [c for c in INTEGRITY_CHECKS if c in present]
    rows = []
    for g in groups:
        cells = {}
        for check in shown:
            # all zero when no run of this row ran the check
            c = checks.get(g.key, {}).get(check) or {"pass": 0, "warn": 0, "fail": 0, "other": 0}
            n =c["pass"] + c["warn"] + c["fail"]
            cells[check] = {**c, "n": n, "pass_rate": c["pass"] / n if n else None, "low_n": n < MIN_RUNS}
        median, p25, p75, rn = ratios.get(g.key, (None, None, None, 0))
        rn = int(rn or 0)
        claimed, effective = g.metrics.get("context_claimed"), g.metrics.get("context_effective")
        context = {"value": median, "median": median, "p25": p25, "p75": p75, "n": rn,
                   "coverage": rn / g.runs if g.runs else None, "low_n": rn < MIN_RUNS,
                   "claimed": claimed.value if claimed else None,
                   "effective": effective.value if effective else None}
        rows.append({**g.describe(), "runs": g.runs, "low_n": g.low_n, "checks": cells,
                     "model_mismatch": g.metrics["model_mismatch_rate"].public(), "context": context})
    return {**_head(q), "runs": sum(g.runs for g in groups), "checks": shown,
            "has_context": any(r["context"]["n"] for r in rows), "rows": rows}


# --------------------------------------------------------------------------- #
# Filter options (History and Analytics)
# --------------------------------------------------------------------------- #
# The filter keys of the URL schema with values to choose from: the SQL of a
# run's value as the URL spells it (so "the key is set" is "the value is one
# of the given ones"), and the Query field the key sets.
_FACETS: dict[str, tuple[str, str]] = {
    "surface": ("COALESCE(h.surface, 'chat')", "surface"),
    "relay": ("rm.relay_key", "relays"),
    "model": (GROUP_KEY_SQL["model"], "models"),
    "suite": ("COALESCE(NULLIF(h.suite, ''), '-')", "suite"),
    "mode": ("COALESCE(NULLIF(h.mode, ''), '-')", "mode"),
    "api": ("COALESCE(NULLIF(h.api, ''), '-')", "api"),
    "stream": ("COALESCE(NULLIF(h.stream_mode, ''), '-')", "stream"),
    "detect": ("CASE h.api_auto WHEN 1 THEN 'auto' WHEN 0 THEN 'manual' ELSE '-' END", "detect"),
    "risk": ("COALESCE(NULLIF(h.risk_level, ''), 'inconclusive')", "risk"),
    "exec": ("CASE WHEN h.watch_id IS NULL THEN 'manual' ELSE 'monitor' END", "exec"),
}
OPTION_KEYS = tuple(_FACETS)
# the keys with many values (a list of their own over the runs; the others
# are folded from one grouping of all of them)
_MANY = ("relay", "model")


def filter_options(params: Any) -> dict[str, Any]:
    """``GET /api/filters/options``: the values present for every filter key
    of the URL schema (:data:`OPTION_KEYS`) as ``{"<key>": [{value, runs,
    label?}]}``, most runs first, each counted under the current filters
    except the key itself (a selected value and its siblings never
    disappear). ``relay`` values carry their relay-map ``label``, ``kind``
    and ``in_kb``; ``span`` is the first and last run time under every filter
    but ``from`` / ``to``; ``dimensions`` the dimension keys of the selected
    runs (for ``dim:<key>`` metrics). Unlike the widgets no surface is
    defaulted: ``surface_default`` names the one they would use.

    One statement, three passes over the selected runs: the runs matching
    the filters without a value list (``min_score``, ``q``) are read once
    with each key's value (``r``); ``relay`` (by the integer relay id) and
    ``model`` lists are a ``GROUP BY`` over them, and every other list, the
    span and the run count are folded from one ``GROUP BY`` over all the
    few-valued keys at once (``c``: a row per combination of their values
    and of whether the relay, model and time filters hold), so each list
    still counts under every filter but its own."""
    q = query.parse_query(params)
    conn = history.query_connection()
    base = query.select_runs(q.replace(
        start=None, end=None, **{f: () if f in ("relays", "models") else None for _, f in _FACETS.values()}))
    base = base.and_where("m.relay_id IS NOT NULL")  # the runs with a relay, as the join to it
    few = [k for k in _FACETS if k not in _MANY]
    cols = ", ".join(["h.id AS id", "m.started_at AS t", "m.relay_id AS rid",
                      *(f"{expr} AS f_{k}" for k, (expr, _) in _FACETS.items() if k != "relay")])

    def values(key: str) -> tuple[Any, ...]:
        value = getattr(q, _FACETS[key][1])
        return tuple(value) if isinstance(value, tuple) else () if value is None else (value,)

    def marks(n: int) -> str:
        return ", ".join("?" * n)

    # each filter on r and, folded into c, its condition there
    on_r: dict[str, tuple[str, tuple[Any, ...]]] = {}
    for key in _FACETS:
        if vs := values(key):
            on_r[key] = ((f"rid IN (SELECT id FROM relay_group WHERE relay_key IN ({marks(len(vs))}))"
                          if key == "relay" else f"f_{key} IN ({marks(len(vs))})"), vs)
    times = [(c, (analytics_store.format_ts(v),)) for c, v in (("t >= ?", q.start), ("t < ?", q.end))
             if v is not None]
    if times:
        on_r[":time"] = (" AND ".join(c for c, _ in times), tuple(a for _, args in times for a in args))
    flags = [k for k in on_r if k not in few]  # relay, model, time: a 0/1 column of c each
    on_c = {k: (f"k{flags.index(k)}", ()) if k in flags else c for k, c in on_r.items()}

    def where(conds: Mapping[str, tuple[str, tuple[Any, ...]]], *skip: str) -> tuple[str, list[Any]]:
        parts = [c for k, c in conds.items() if k not in skip]
        sql = " WHERE " + " AND ".join(f"({p})" for p, _ in parts) if parts else ""
        return sql, [a for _, args in parts for a in args]

    args: list[Any] = list(base.args)
    c_cols = [f"f_{k}" for k in few] + [f"({on_r[k][0]}) AS k{i}" for i, k in enumerate(flags)]
    for k in flags:
        args += on_r[k][1]
    ctes = (f"WITH r AS MATERIALIZED (SELECT {cols} {base.sql}),"
            f" c AS MATERIALIZED (SELECT {', '.join(c_cols)}, COUNT(*) AS n, MIN(t) AS t0, MAX(t) AS t1"
            f" FROM r GROUP BY {', '.join(str(i + 1) for i in range(len(c_cols)))}) ")
    branches: list[str] = []

    def branch(sql: str, conds: Mapping[str, tuple[str, tuple[Any, ...]]], *skip: str,
               tail: str = "") -> None:
        w_sql, w_args = where(conds, *skip)
        branches.append(sql.format(w=w_sql) + tail)
        args.extend(w_args)

    for key in few:
        branch(f"SELECT '{key}', f_{key}, NULL, NULL, NULL, SUM(n) FROM c{{w}} GROUP BY 2", on_c, key)
    branch("SELECT 'relay', g.relay_key, g.label, g.kind, g.in_kb, s.n"
           " FROM (SELECT rid, COUNT(*) AS n FROM r{w} GROUP BY rid) s JOIN relay_group g ON g.id = s.rid",
           on_r, "relay")
    branch("SELECT 'model', f_model, NULL, NULL, NULL, COUNT(*) FROM r{w} GROUP BY 2", on_r, "model")
    branch("SELECT ':span', MIN(t0), MAX(t1), NULL, NULL, 0 FROM c{w}", on_c, ":time")
    branch("SELECT ':runs', NULL, NULL, NULL, NULL, COALESCE(SUM(n), 0) FROM c{w}", on_c)
    branch("SELECT ':dim', d.key, NULL, NULL, NULL, COUNT(*) FROM history_dimensions d"
           " WHERE d.kind = 'dimension' AND d.history_id IN (SELECT id FROM r{w}) GROUP BY 2", on_r)
    rows = conn.execute(ctes + " UNION ALL ".join(branches), args).fetchall()

    out: dict[str, Any] = {"filters": q.canonical(), "keys": list(OPTION_KEYS)}
    lists: dict[str, list[dict[str, Any]]] = {k: [] for k in OPTION_KEYS}
    dims: list[str] = []
    for key, value, a, b, c, n in rows:
        if key == ":span":
            out["span"] = {"first": value, "last": a}
        elif key == ":runs":
            out["runs"] = int(n)
        elif key == ":dim":
            dims.append(str(value))
        elif key == "relay":
            lists[key].append({"value": str(value), "label": str(a), "kind": str(b), "in_kb": bool(c),
                               "runs": int(n)})
        else:
            lists[key].append({"value": str(value), "runs": int(n)})
    for key, items in lists.items():
        items.sort(key=lambda o: (-o["runs"], str(o.get("label", o["value"])).lower(), o["value"]))
        out[key] = items
    out["surface_default"] = _most_common({o["value"]: o["runs"] for o in lists["surface"]})
    out["dimensions"] = sorted(dims)
    return out
