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
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from ekte import errorclass
from ekte.web import analytics_store, history, query
from ekte.web import metrics as _metrics
from ekte.web.analytics import (
    _T_MAX,
    _T_MIN,
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
    ``family`` and ``grade`` (:func:`ekte.web.metrics.present`)."""
    shown = _metrics.present(m, cell.get("value"))
    return {**cell, "family": shown["family"], "grade": shown["grade"]}


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
    groups = query.aggregate(conn, q, wanted, "all")
    sel = query.select_runs(q).with_relay()
    runs, relays, models = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT rm.relay_key), COUNT(DISTINCT NULLIF(h.claimed_model, ''))"
        f" {sel.sql}", sel.args).fetchone()
    full = 1.0 if runs else None
    cells = {"runs": query.Cell(float(runs), int(runs), full, False),
             "relays": query.Cell(float(relays), int(runs), full, False),
             "models": query.Cell(float(models), int(runs), full, False)}
    found = groups[0].metrics if groups else {}
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


def _counts_sql(alias: str = "o") -> list[str]:
    """``SUM(n)`` of each outcome class over joined ``history_outcomes`` rows."""
    return [f"SUM(CASE WHEN {alias}.outcome = '{c}' THEN {alias}.n ELSE 0 END)" for c in ERROR_CLASSES]


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


_DATED_SQL = (f"+m.started_at >= '{analytics_store.format_ts(_T_MIN)}'"
              f" AND +m.started_at < '{analytics_store.format_ts(_T_MAX)}'")


def _local_buckets(size: str, local: str, offset: str, block: int) -> list[str]:
    """SQL partitioning runs by the buckets of :func:`_bucket` (``local``: the
    run's local wall time; ``offset``: its UTC offset, which parts a DST fold)."""
    if size == "hour":
        return [f"strftime('%Y-%m-%dT%H', {local})", offset]
    if size == "day":
        return [f"date({local})"]
    if size == "week":
        return [f"date({local}, '-6 days', 'weekday 1')"]
    return [f"strftime('%w', {local})", f"CAST(strftime('%H', {local}) AS INTEGER) / {block}"]


def _error_buckets(conn: Any, sel: query.RunSelection, zone: tzinfo, size: str,
                   block: int) -> list[dict[str, Any]]:
    """Outcome counts of the selected runs per time bucket of the run's start
    (viewer's zone), in time order; buckets without runs are left out."""
    sel = sel.and_where(_DATED_SQL)
    lo, hi = conn.execute(f"SELECT MIN(m.started_at), MAX(m.started_at) {sel.sql}", sel.args).fetchone()
    first, last = analytics_store.parse_ts(lo), analytics_store.parse_ts(hi)
    if first is None or last is None:
        return []
    points: list[datetime] = []
    p = first.replace(microsecond=0)
    while p <= last:
        points.append(p)
        p += timedelta(days=7)
    off = query.offset_sql(zone, [*points, last + timedelta(seconds=1)])
    local = f"datetime(m.started_at, {off} || ' seconds')"
    buckets = _local_buckets(size, local, off, block)
    nb = len(buckets)
    cols = [*(f"{b} AS b{i}" for i, b in enumerate(buckets)), "MIN(m.started_at)",
            "COUNT(DISTINCT h.id)", "COUNT(DISTINCT o.history_id)", *_counts_sql()]
    rows = conn.execute(
        f"SELECT {', '.join(cols)} {sel.from_sql}"
        f" LEFT JOIN history_outcomes o ON o.history_id = h.id{sel.where_sql}"
        f" GROUP BY {', '.join(f'b{i}' for i in range(nb))}", sel.args).fetchall()
    out = []
    for row in rows:
        t = analytics_store.parse_ts(row[nb])
        assert t is not None
        pos, key, extra = _bucket(t, zone, size, block)
        runs, covered = int(row[nb + 1]), int(row[nb + 2])
        counts = dict(zip(ERROR_CLASSES, row[nb + 3:], strict=True))
        out.append((pos, {"bucket": key, **extra, "runs": runs, "covered": covered,
                          "low_n": covered < MIN_RUNS, **outcome_shares(counts)}))
    return [b for _, b in sorted(out, key=lambda item: item[0])]


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

    groups = query.aggregate(conn, q, ["impaired_rate"])
    sel = query.select_runs(q)
    if q.group in ("relay", "relay_model"):
        sel = sel.with_relay()
    counted = {
        str(row[0]): dict(zip(ERROR_CLASSES, row[1:], strict=True))
        for row in conn.execute(
            f"SELECT {GROUP_KEY_SQL[q.group]}, {', '.join(_counts_sql())} {sel.from_sql}"
            f" JOIN history_outcomes o ON o.history_id = h.id{sel.where_sql} GROUP BY 1", sel.args)
    }
    totals = dict.fromkeys(ERROR_CLASSES, 0)
    out_groups = []
    for g in groups:
        counts = counted.get(g.key, {})
        for k, v in counts.items():
            totals[k] += int(v or 0)
        covered = g.metrics["impaired_rate"].n
        out_groups.append({**g.describe(), "runs": g.runs, "covered": covered,
                           "coverage": covered / g.runs if g.runs else None,
                           "low_n": covered < MIN_RUNS, **outcome_shares(counts)})
    out_groups.sort(key=lambda g: (-g["requests"], -g["runs"], g["label"].lower(), g["key"]))
    runs = sum(g.runs for g in groups)
    covered = sum(g["covered"] for g in out_groups)
    out: dict[str, Any] = {
        **_head(q), "group": q.group, "bucket": size, "block": block, "tz": zone_name,
        "classes": list(ERROR_CLASSES), "runs": runs, "covered": covered,
        "coverage": covered / runs if runs else None,
        "totals": outcome_shares(totals), "groups": out_groups,
        "buckets": _error_buckets(conn, query.select_runs(q), zone, size, block),
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
# run's value (as the URL spells it), the Query field the key sets, and that
# field's "not set" value.
_FACETS: dict[str, tuple[str, str, Any]] = {
    "surface": ("COALESCE(h.surface, 'chat')", "surface", None),
    "model": (GROUP_KEY_SQL["model"], "models", ()),
    "suite": ("COALESCE(NULLIF(h.suite, ''), '-')", "suite", None),
    "mode": ("COALESCE(NULLIF(h.mode, ''), '-')", "mode", None),
    "api": ("COALESCE(NULLIF(h.api, ''), '-')", "api", None),
    "stream": ("COALESCE(NULLIF(h.stream_mode, ''), '-')", "stream", None),
    "detect": ("CASE h.api_auto WHEN 1 THEN 'auto' WHEN 0 THEN 'manual' ELSE '-' END", "detect", None),
    "risk": ("COALESCE(NULLIF(h.risk_level, ''), 'inconclusive')", "risk", None),
    "exec": ("CASE WHEN h.watch_id IS NULL THEN 'manual' ELSE 'monitor' END", "exec", None),
}
OPTION_KEYS = ("surface", "relay", "model", "suite", "mode", "api", "stream", "detect", "risk", "exec")


def filter_options(params: Any) -> dict[str, Any]:
    """``GET /api/filters/options``: the values present for every filter key
    of the URL schema (:data:`OPTION_KEYS`), each with its run count, under
    the current filters except the key itself (a selected value never
    disappears). ``relay`` values carry their relay-map label; ``span`` is the
    first and last run time under every filter but ``from`` / ``to``. Unlike
    the widgets no surface is defaulted: ``surface_default`` names the one
    they would use."""
    q = query.parse_query(params)
    conn = history.query_connection()
    out: dict[str, Any] = {"filters": q.canonical(), "runs": query.count_runs(conn, q),
                           "surface_default": query.default_surface(conn, q), "keys": list(OPTION_KEYS)}
    for key, (expr, field_name, unset) in _FACETS.items():
        sel = query.select_runs(q.replace(**{field_name: unset}))
        rows = conn.execute(f"SELECT {expr}, COUNT(*) {sel.sql} GROUP BY 1", sel.args).fetchall()
        out[key] = sorted(({"value": str(v), "runs": int(n)} for v, n in rows),
                          key=lambda o: (-o["runs"], o["value"]))
    sel = query.select_runs(q.replace(relays=())).with_relay()
    out["relay"] = sorted(
        ({"value": str(k), "label": str(lb), "kind": str(kd), "in_kb": bool(ik), "runs": int(n)}
         for k, lb, kd, ik, n in conn.execute(
             "SELECT rm.relay_key, MAX(rm.label), MAX(rm.kind), MAX(rm.in_kb), COUNT(*)"
             f" {sel.sql} GROUP BY 1", sel.args)),
        key=lambda o: (-o["runs"], o["label"].lower(), o["value"]))
    sel = query.select_runs(q.replace(start=None, end=None))
    first, last = conn.execute(f"SELECT MIN(m.started_at), MAX(m.started_at) {sel.sql}", sel.args).fetchone()
    out["span"] = {"first": first, "last": last}
    sel = query.select_runs(q)
    out["dimensions"] = [str(r[0]) for r in conn.execute(
        f"SELECT DISTINCT d.key {sel.from_sql} JOIN history_dimensions d ON d.history_id = h.id"
        f" AND d.kind = 'dimension'{sel.where_sql} ORDER BY 1", sel.args)]
    return out
