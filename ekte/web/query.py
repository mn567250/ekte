"""The query core of the web UI: URL parameters → runs → groups → values → page.

One filter parser and one URL schema for History, Analytics and every widget
(:func:`parse_query`), one SQL ``WHERE`` over the runs' numeric run rows
(``history_metrics m``, :mod:`ekte.web.run_row`; ``history h`` and the
run's relay ``rm`` are joined only for free-text search) for every filter
(:func:`select_runs`), and the aggregations on top of it, computed in SQLite:
per group (:func:`aggregate`), per group and time bucket (:func:`series`),
and run rows a page at a time (:func:`page_runs`). Python never filters
runs and never loads one run per row to aggregate it.

Callers pass a connection to ``history.db`` that is ready for queries:
:func:`ekte.web.history.query_connection` (this thread's read connection,
analytics tables backfilled, ``relay_map`` current).

URL schema
==========

Every key is optional. A key given twice is an error, except ``relay`` and
``model``, which may repeat (any of the values matches). Empty values count as
not given. ``-`` stands for "(unknown)": the run has no value.

============================  ==============================================================
Key                           Values
============================  ==============================================================
``from``, ``to``              ISO 8601 (naive = UTC), compared with the run's
                              ``started_at``; ``from`` inclusive, ``to`` exclusive
``range``                     ``24h``, ``7d``, ``30d``, ``90d``, ``365d``: resolved at parse
                              time to ``to`` = now rounded up to the next whole minute
                              and ``from`` = ``to`` − range; not with ``from`` / ``to``
``surface``                   ``chat``, ``embedding``, ``rerank`` (a NULL surface reads as
                              chat); empty: every surface
``relay``                     a relay key (``relay_map.relay_key``; ``(unknown)`` for runs
                              without a URL); repeatable
``model``                     a claimed model (``(unknown)`` for runs without one);
                              repeatable
``suite``, ``mode``, ``api``  the exact stored value, or ``-`` for none
``stream``                    the exact ``stream_mode`` (``stream``, ``non_stream``,
                              ``both``), or ``-`` for none
``detect``                    ``auto``, ``manual`` (the protocol was detected / given), ``-``
``risk``                      ``clean``, ``low``, ``medium``, ``high``, ``inconclusive``
                              (a run without a risk level is inconclusive)
``min_score``                 0–100: runs scoring at least this (runs without a score are
                              left out)
``exec``                      ``manual`` (started by hand), ``monitor`` (by a monitor)
``q``                         free text, matched as a substring, case-insensitively for
                              ASCII (SQL ``LIKE``; ``%``, ``_`` and ``\\`` are literal),
                              against base URL, relay label, claimed model, model, suite,
                              mode and api
``group``                     ``relay`` (default), ``model``, ``relay_model``, ``all``
============================  ==============================================================

Keys with a dot are a widget's own (``<widget>.<key>``, e.g. ``trend.metric``,
``runs.sort``, ``runs.after``) and are ignored here; any other key is an
error (:class:`QueryError`, answered with 400) that names it.
:meth:`Query.canonical` is the parsed query in one form (sorted keys, the
range resolved, defaults applied), for cache keys and links;
:func:`resolve_params` turns request parameters into that form for
:func:`ekte.web.cache.cached_endpoint` (``prepare``).

Aggregation
===========

How runs combine is the metric's ``agg`` (:class:`ekte.web.analytics.Metric`):

* ``median`` — values per run (score, latencies, speeds, billing ratios,
  ``dim:<key>`` dimension scores): the median (SQLite ``median()``), with
  ``p25`` / ``p75`` (``percentile()``), linear interpolation (Hyndman & Fan
  type 7, as :func:`ekte.web.analytics.percentile`).
* ``pooled`` — outcome rates: Σ outcome counts (``history_outcomes``) ÷ Σ
  base (``requests_judged``, or ``requests_total`` for ``impaired_rate``)
  over the runs whose base is > 0; ``numerator`` and ``denominator`` are the
  sums. So ``success + error + rate_limited == 1`` for any group with a
  judged request.
* ``share`` — yes/no per run (high risk, model mismatch): the share of runs
  with "yes".

Each value comes with ``n`` (runs with a value), ``coverage`` (``n`` ÷ runs
of the group) and ``low_n`` (``n`` < :data:`MIN_RUNS`). A group of one run
returns exactly that run's stored value, for every metric.

SQLite builds without ``median()`` / ``percentile()`` get Python aggregates
with the same semantics (:func:`sql_functions`), so results are identical.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import sqlite3
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from ekte.config import SURFACES
from ekte.models import RiskLevel
from ekte.scoring import GRADE_SCALE
from ekte.web import analytics, analytics_store, run_row
from ekte.web.analytics import ALL_KEY, GROUPS, MIN_RUNS, AnalyticsError, Metric
from ekte.web.relay_map import GROUP_JOIN_SQL

__all__ = [
    "Cell", "GroupResult", "Page", "Point", "Query", "QueryError", "RunSelection",
    "Series", "SeriesResult", "aggregate", "count_runs", "default_surface", "page_runs",
    "parse_query", "resolve_params", "select_runs", "series", "sql_functions",
]

# "(unknown)" in the URL: the run has no value.
UNKNOWN = "-"
# Relative ranges (range=...).
RANGES: dict[str, timedelta] = {
    "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30),
    "90d": timedelta(days=90), "365d": timedelta(days=365),
}
DETECTS = ("auto", "manual")
EXECS = ("manual", "monitor")
RISKS = tuple(r.value for r in RiskLevel)
# Longest accepted value (relay keys are URLs), as the Analytics parser.
MAX_PARAM = analytics.MAX_PARAM
# Keys that take one value, and the ones that may repeat.
SINGLE_KEYS = ("from", "to", "range", "surface", "suite", "mode", "api", "stream", "detect",
               "risk", "min_score", "exec", "q", "group")
MULTI_KEYS = ("relay", "model")
# page_runs()
SORTS = ("time", "score", "risk", "grade")
PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 200
# series(): series per chart, as Analytics.
MAX_KEYS = analytics.MAX_KEYS


class QueryError(AnalyticsError):
    """A query parameter that cannot be used (answered with 400). An
    :class:`~ekte.web.analytics.AnalyticsError`, so handlers that catch that
    catch this too."""


# --------------------------------------------------------------------------- #
# The parsed query
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Query:
    """Parsed, validated filters (see the module docstring for each key).

    ``suite``, ``mode``, ``api`` and ``stream`` hold :data:`UNKNOWN` for "no
    value"; ``relays`` / ``models`` are sorted and unique. Build one with
    :func:`parse_query`, change one with :meth:`replace`.
    """

    start: datetime | None = None
    end: datetime | None = None
    surface: str | None = None
    relays: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    suite: str | None = None
    mode: str | None = None
    api: str | None = None
    stream: str | None = None
    detect: str | None = None
    risk: str | None = None
    min_score: float | None = None
    exec: str | None = None
    text: str | None = None
    group: str = "relay"

    def replace(self, **changes: Any) -> Query:
        """A copy with some fields changed (e.g. ``start`` / ``end`` of a
        previous period, or the ``surface`` an endpoint defaulted to)."""
        return replace(self, **changes)

    def canonical(self) -> dict[str, Any]:
        """The query in canonical form: URL keys, sorted, only those set
        (``group`` always), the range as absolute ``from`` / ``to``
        (:func:`ekte.web.analytics_store.format_ts`), repeated keys as sorted
        lists. Equal queries give equal dicts; ``parse_query(q.params())``
        gives ``q`` back."""
        out: dict[str, Any] = {
            "from": analytics_store.format_ts(self.start) if self.start else None,
            "to": analytics_store.format_ts(self.end) if self.end else None,
            "surface": self.surface,
            "relay": list(self.relays) or None,
            "model": list(self.models) or None,
            "suite": self.suite, "mode": self.mode, "api": self.api, "stream": self.stream,
            "detect": self.detect, "risk": self.risk,
            "min_score": _num_text(self.min_score) if self.min_score is not None else None,
            "exec": self.exec, "q": self.text, "group": self.group,
        }
        return {k: out[k] for k in sorted(out) if out[k] is not None}

    def params(self) -> list[tuple[str, str]]:
        """:meth:`canonical` as URL ``(key, value)`` pairs."""
        pairs: list[tuple[str, str]] = []
        for key, value in self.canonical().items():
            pairs.extend((key, v) for v in (value if isinstance(value, list) else [value]))
        return pairs


def _num_text(x: float) -> str:
    return str(int(x)) if x.is_integer() else repr(x)


Params = Mapping[str, Any] | Iterable[tuple[str, Any]]


def _pairs(params: Params) -> list[tuple[str, str]]:
    """``(key, value)`` pairs of a Starlette ``QueryParams``, a mapping
    (values may be lists) or pairs; values stripped, empty ones dropped."""
    multi = getattr(params, "multi_items", None)
    if callable(multi):
        items: Iterable[tuple[str, Any]] = multi()
    elif isinstance(params, Mapping):
        items = params.items()
    else:
        items = params
    out = []
    for key, value in items:
        for v in value if isinstance(value, (list, tuple)) else [value]:
            if v is None:
                continue
            if not isinstance(v, str):
                raise QueryError(f"{str(key)[:64]} must be a string")
            v = v.strip()
            if v:
                out.append((str(key), v))
    return out


def _choice(key: str, value: str | None, allowed: Sequence[str]) -> str | None:
    if value is not None and value not in allowed:
        raise QueryError(f"{key} must be one of {', '.join(allowed)}")
    return value


def _time(key: str, value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = analytics_store.parse_ts(value)
    if dt is None:
        raise QueryError(f"{key} must be an ISO 8601 timestamp (naive ones are UTC)")
    return dt


def _ceil_minute(now: datetime) -> datetime:
    floor = now.replace(second=0, microsecond=0)
    return floor if floor == now else floor + timedelta(minutes=1)


def parse_query(params: Params, *, now: datetime | None = None) -> Query:
    """Validate request parameters into a :class:`Query` (raises
    :class:`QueryError` naming the key); ``now`` (default: the clock)
    resolves ``range``. Keys with a dot are ignored."""
    single: dict[str, str] = {}
    multi: dict[str, set[str]] = {k: set() for k in MULTI_KEYS}
    for key, value in _pairs(params):
        if "." in key:
            continue
        if len(value) > MAX_PARAM:
            raise QueryError(f"{key} is longer than {MAX_PARAM} characters")
        if key in MULTI_KEYS:
            multi[key].add(value)
        elif key in SINGLE_KEYS:
            if key in single:
                raise QueryError(f"{key} given more than once")
            single[key] = value
        else:
            raise QueryError(f"unknown parameter {key[:64]!r}")

    start, end = _time("from", single.get("from")), _time("to", single.get("to"))
    rng = _choice("range", single.get("range"), tuple(RANGES))
    if rng is not None:
        if start is not None or end is not None:
            raise QueryError("range cannot be combined with from / to")
        end = _ceil_minute((now or datetime.now(UTC)).astimezone(UTC))
        start = end - RANGES[rng]
    if start is not None and end is not None and start >= end:
        raise QueryError("from must be before to")

    min_score = None
    if "min_score" in single:
        try:
            min_score = float(single["min_score"])
        except ValueError:
            min_score = math.nan
        if not 0 <= min_score <= 100:  # NaN fails too
            raise QueryError("min_score must be a number from 0 to 100")

    return Query(
        start=start, end=end,
        surface=_choice("surface", single.get("surface"), SURFACES),
        relays=tuple(sorted(multi["relay"])),
        models=tuple(sorted(multi["model"])),
        suite=single.get("suite"), mode=single.get("mode"), api=single.get("api"),
        stream=single.get("stream"),
        detect=_choice("detect", single.get("detect"), (*DETECTS, UNKNOWN)),
        risk=_choice("risk", single.get("risk"), RISKS),
        min_score=min_score,
        exec=_choice("exec", single.get("exec"), EXECS),
        text=single.get("q"),
        group=_choice("group", single.get("group"), GROUPS) or "relay",
    )


def resolve_params(params: Params, *, now: datetime | None = None) -> list[tuple[str, str]]:
    """Request parameters with the shared ones in canonical form (``range``
    resolved) and the widget keys (with a dot) as given: the ``prepare`` of
    :func:`ekte.web.cache.cached_endpoint`, so an answer is cached under its
    absolute range. Invalid parameters are returned unchanged, for the
    endpoint's own :func:`parse_query` to reject."""
    pairs = _pairs(params)
    try:
        q = parse_query(pairs, now=now)
    except QueryError:
        return pairs
    return [*q.params(), *((k, v) for k, v in pairs if "." in k)]


# --------------------------------------------------------------------------- #
# SQL: median / percentile
# --------------------------------------------------------------------------- #
class _Percentile:
    """``percentile(Y, P)`` as SQLite's (P in 0..100; NULLs ignored)."""

    def __init__(self) -> None:
        self.values: list[float] = []
        self.p = 50.0

    def step(self, value: Any, p: Any = 50.0) -> None:
        if isinstance(value, (int, float)) and math.isfinite(value):
            self.values.append(float(value))
            self.p = float(p)

    def finalize(self) -> float | None:
        self.values.sort()
        return analytics.percentile(self.values, self.p / 100.0)


class _Median(_Percentile):
    def step(self, value: Any, p: Any = 50.0) -> None:
        super().step(value, 50.0)


_native: bool | None = None


def _has_native() -> bool:
    global _native
    if _native is None:
        probe = sqlite3.connect(":memory:")
        try:
            probe.execute("SELECT median(1), percentile(1, 50)").fetchone()
            _native = True
        except sqlite3.OperationalError:
            _native = False
        finally:
            probe.close()
    return _native


def sql_functions(conn: sqlite3.Connection) -> tuple[str, str]:
    """The names of the median and percentile aggregates to use on ``conn``:
    SQLite's own ``median`` / ``percentile`` when the build has them (probed
    once per process), else Python ones registered on ``conn`` as
    ``ekte_median`` / ``ekte_percentile`` (same semantics)."""
    if _has_native():
        return "median", "percentile"
    conn.create_aggregate("ekte_median", 1, _Median)  # type: ignore[arg-type]
    conn.create_aggregate("ekte_percentile", 2, _Percentile)  # type: ignore[arg-type]
    return "ekte_median", "ekte_percentile"


# --------------------------------------------------------------------------- #
# SQL: run selection
# --------------------------------------------------------------------------- #
RUNS_SQL = "FROM history_metrics m"
"""The runs, as ``m``: every value a selection, grouping or aggregate reads
is on the run's own ``history_metrics`` row (:data:`ekte.web.run_row.RUN_COLUMNS`)."""
TEXT_SQL = (f"{RUNS_SQL} JOIN history h INDEXED BY idx_history_query ON h.id = m.history_id"
            f" {GROUP_JOIN_SQL}")
"""The runs with their ``history`` row (``h``, read through its covering index
``history.QUERY_INDEX_COLS``, never through the row, whose report_json would
be read along) and relay (``rm``: ``rm.relay_key``, ``rm.label``, ``rm.kind``,
``rm.in_kb``): what free-text search (``q``) needs, and only it."""

_SEARCH_SQL = " || char(10) || ".join(
    f"COALESCE({c}, '')" for c in
    ("h.base_url", "rm.label", "h.claimed_model", "h.model", "h.suite", "h.mode", "h.api")
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US = timedelta(microseconds=1)


def us_of(dt: datetime) -> int:
    """``dt`` in Unix microseconds (as ``started_us`` holds a run's start)."""
    return (dt - _EPOCH) // _US


def us_dt(us: Any) -> datetime:
    """A ``started_us`` value (or an aggregate of them) as an aware UTC datetime."""
    return _EPOCH + int(us) * _US


def us_text(us: Any) -> str | None:
    """A ``started_us`` value as the ``started_at`` text it was made from
    (None stays None)."""
    return None if us is None else analytics_store.format_ts(us_dt(us))


def time_sql(op: str, dt: datetime, run: str = "m") -> str:
    """``started_at {op} dt`` as SQL on the integer ``started_us`` of the run
    row ``run`` (exactly: both have microseconds)."""
    return f"{run}.started_us {op} {us_of(dt)}"


# Run times that can be shifted into every time zone (others count as undated).
# (Unary + keeps SQLite from walking a started_us index for this nearly
# unbounded range: a table scan is faster.)
_DATED_SQL = f"+{time_sql('>=', analytics._T_MIN)} AND +{time_sql('<', analytics._T_MAX)}"


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@dataclass(frozen=True)
class RunSelection:
    """The runs of a :class:`Query` as SQL: ``FROM`` + ``WHERE`` (``sql``)
    with its ``?`` arguments (``args``): ``f"SELECT m.history_id {sel.sql}"``.
    Columns of ``m`` can always be used; ``h`` (the run's ``history`` row,
    through its covering index) and ``rm`` (its relay) only when ``text`` is
    set (``q`` needs them), as joining them costs two lookups per run and
    never changes which runs are selected. :meth:`and_where` adds conditions."""

    where: tuple[str, ...]
    args: tuple[Any, ...]
    text: bool = False

    @property
    def where_sql(self) -> str:
        """`` WHERE ...`` (empty without conditions)."""
        return " WHERE " + " AND ".join(self.where) if self.where else ""

    @property
    def from_sql(self) -> str:
        return TEXT_SQL if self.text else RUNS_SQL

    @property
    def sql(self) -> str:
        return self.from_sql + self.where_sql

    def and_where(self, condition: str, *args: Any) -> RunSelection:
        """Also require ``condition`` (over ``m``; ``h`` and ``rm`` only with ``text``)."""
        return RunSelection((*self.where, condition), (*self.args, *args), self.text)


_SURFACE_ID_SQL = "(SELECT id FROM run_surface WHERE surface = ?)"


def _in_table(column: str, table: str, key: str, values: Sequence[Any]) -> tuple[Any, ...]:
    """The runs whose id ``column`` names one of ``values`` of ``key`` in the
    small table ``table`` (its ids are looked up once, not per run)."""
    return (f"{column} IN (SELECT id FROM {table} WHERE {key} IN ({', '.join('?' * len(values))}))",
            *values)


def select_runs(q: Query) -> RunSelection:
    """One ``WHERE`` over the runs' ``history_metrics`` rows covering every
    filter of ``q`` (``group`` is not a filter): the time on ``started_us``,
    relays and models by their ids, the few-valued keys by the run's facet
    combination (one lookup of the matching ``facet_combo`` ids), the score
    on ``m.score``; only ``q`` (text) reads ``history``."""
    where: list[str] = []
    args: list[Any] = []

    def add(cond: str, *a: Any) -> None:
        where.append(cond)
        args.extend(a)

    if q.start is not None:
        add(time_sql(">=", q.start))
    if q.end is not None:
        add(time_sql("<", q.end))
    if q.surface is not None:
        # (unary +: never a search of idx_run_row, which would read the rows in its order)
        add(f"+m.surface_id = {_SURFACE_ID_SQL}", q.surface)
    facet = {k: v for k, v in (("suite", q.suite), ("mode", q.mode), ("api", q.api),
                               ("stream", q.stream), ("detect", q.detect), ("risk", q.risk),
                               ("exec", q.exec)) if v is not None}
    if facet:
        same = " AND ".join(f"{run_row.COLUMNS[k]} = ?" for k in facet)
        add(f"m.facet_id IN (SELECT id FROM facet_combo WHERE {same})", *facet.values())
    if q.relays:
        add(*_in_table("m.relay_id", "relay_group", "relay_key", q.relays))
    if q.models:
        add(*_in_table("m.model_id", "model_group", "model_key", q.models))
    if q.min_score is not None:
        add("m.score >= ?", q.min_score)
    if q.text is not None:
        add(f"({_SEARCH_SQL}) LIKE ? ESCAPE '\\'", _like(q.text))
    return RunSelection(tuple(where), tuple(args), q.text is not None)


def count_runs(conn: sqlite3.Connection, q: Query) -> int:
    """How many runs ``q`` selects."""
    sel = select_runs(q)
    return int(conn.execute(f"SELECT COUNT(*) {sel.sql}", sel.args).fetchone()[0])


def default_surface(conn: sqlite3.Connection, q: Query | None = None) -> str:
    """The surface with the most runs among ``q``'s runs with any surface
    (the whole history without ``q``); ties in :data:`ekte.config.SURFACES`
    order, chat when there are none. For endpoints that need one surface."""
    sel = select_runs((q or Query()).replace(surface=None))
    # the known surfaces counted in one pass (no GROUP BY: no sort of the runs)
    known = ", ".join(f"COALESCE(SUM(m.surface_id = {_SURFACE_ID_SQL}), 0)" for _ in SURFACES)
    total, *counts = conn.execute(f"SELECT COUNT(*), {known} {sel.sql}",
                                  (*SURFACES, *sel.args)).fetchone()
    if int(total) == sum(int(c) for c in counts):
        return analytics._most_common(dict(zip(SURFACES, (int(c) for c in counts), strict=True)))
    rows = conn.execute(
        f"SELECT su.surface, s.n FROM (SELECT m.surface_id AS sid, COUNT(*) AS n {sel.sql}"
        " GROUP BY 1) s JOIN run_surface su ON su.id = s.sid", sel.args
    ).fetchall()
    return analytics._most_common({str(r[0]): int(r[1]) for r in rows})


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
class Cell(NamedTuple):
    """One metric over a group of runs. ``median`` / ``p25`` / ``p75`` for
    ``median`` metrics, ``numerator`` / ``denominator`` for ``pooled`` ones
    (None otherwise). Immutable; a named tuple, as a board holds thousands."""

    value: float | None
    n: int
    coverage: float | None
    low_n: bool
    median: float | None = None
    p25: float | None = None
    p75: float | None = None
    numerator: int | None = None
    denominator: int | None = None

    def public(self) -> dict[str, Any]:
        return {"value": self.value, "n": self.n, "coverage": self.coverage, "low_n": self.low_n,
                "median": self.median, "p25": self.p25, "p75": self.p75,
                "numerator": self.numerator, "denominator": self.denominator}


@dataclass(frozen=True)
class GroupResult:
    """A group (series key) and its metric cells. ``key`` / ``label`` /
    ``kind`` / ``in_kb`` describe it (:class:`ekte.web.analytics.Group` for a
    relay; ``relay`` / ``model`` are set for ``relay_model``); ``first_run`` /
    ``last_run`` are the extreme ``started_at``."""

    key: str
    label: str
    kind: str
    in_kb: bool
    runs: int
    metrics: dict[str, Cell]
    first_run: str | None = None
    last_run: str | None = None
    relay: str | None = None
    model: str | None = None

    @property
    def low_n(self) -> bool:
        return self.runs < MIN_RUNS

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {"key": self.key, "label": self.label, "in_kb": self.in_kb,
                               "kind": self.kind}
        if self.kind == "relay_model":
            out.update(relay=self.relay, model=self.model)
        return out

    def public(self) -> dict[str, Any]:
        return {**self.describe(), "runs": self.runs, "low_n": self.low_n,
                "first_run": self.first_run, "last_run": self.last_run,
                "metrics": {mid: c.public() for mid, c in self.metrics.items()}}


@dataclass(frozen=True)
class _Spec:
    """How one metric is aggregated over the runs of a group (``aggs``: SQL
    aggregates over per-run expressions; ``join`` / ``args``: a table it reads)."""

    metric: Metric
    aggs: tuple[str, ...]
    join: str = ""
    args: tuple[Any, ...] = ()


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _column(name: str) -> str:
    """A metric's per-run column on the run's row ``m``."""
    if name not in analytics_store.METRIC_COLS and name not in run_row.RUN_COLUMNS:
        raise ValueError(f"no run column {name!r}")
    return f"m.{name}"


def _spec(m: Metric, i: int, med: str, pct: str, quantiles: bool) -> _Spec:
    if m.agg == "pooled":
        # The run's count of m.outcomes: its rate is that count ÷ base (both from
        # the run's history_outcomes rows), so rate × base gives the integer back
        # exactly, without reading history_outcomes (tested equal).
        base, rate = f"m.{m.base}", f"m.{m.column}"
        has = f"{base} > 0 AND {rate} IS NOT NULL"
        return _Spec(m, (f"SUM(CASE WHEN {has} THEN ROUND({rate} * {base}) END)",
                         f"SUM(CASE WHEN {has} THEN {base} END)",
                         f"COUNT(CASE WHEN {has} THEN 1 END)"))
    join = ""
    args: tuple[Any, ...] = ()
    if m.id.startswith(analytics.DIM_PREFIX):
        join = (f" LEFT JOIN history_dimensions dm{i} ON dm{i}.history_id = m.history_id"
                f" AND dm{i}.kind = 'dimension' AND dm{i}.key = ?")
        args = (m.id[len(analytics.DIM_PREFIX):],)
        v = f"dm{i}.score"
    elif m.id == "risk_high_share":
        high = run_row.RISK_ORDER.index("high")
        v = f"CASE WHEN m.risk_value IS NULL THEN NULL WHEN m.risk_value = {high} THEN 1.0 ELSE 0.0 END"
    elif m.id == "grade":
        v = "m.grade_value"
    elif m.agg == "share":
        col = _column(m.column)
        v = f"CASE WHEN {col} IS NULL THEN NULL WHEN {col} != 0 THEN 1.0 ELSE 0.0 END"
    else:
        # the columns hold numbers or NULL (written from floats; median()
        # rejects text)
        v = _column(m.column)
    if m.agg == "share":
        return _Spec(m, (f"AVG({v})", f"COUNT({v})"), join, args)
    quartiles = (f"{pct}({v}, 25)", f"{pct}({v}, 75)") if quantiles else ("NULL", "NULL")
    return _Spec(m, (f"{med}({v})", *quartiles, f"COUNT({v})"), join, args)


def _cell(spec: _Spec, values: Sequence[Any], runs: int) -> Cell:
    if spec.metric.agg == "pooled":
        num, den, n = values
        n = int(n or 0)
        num = int(num) if n else None
        den = int(den) if n else None
        value = num / den if num is not None and den else None
        return Cell(value, n, _ratio(n, runs), n < MIN_RUNS, numerator=num, denominator=den)
    if spec.metric.agg == "share":
        value, n = values
        n = int(n or 0)
        return Cell(_float(value), n, _ratio(n, runs), n < MIN_RUNS)
    med, p25, p75, n = values
    n = int(n or 0)
    return Cell(_float(med), n, _ratio(n, runs), n < MIN_RUNS, _float(med), _float(p25), _float(p75))


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _ratio(n: int, runs: int) -> float | None:
    return n / runs if runs else None


def _metrics(metrics: Iterable[str | Metric], surface: str | None) -> list[Metric]:
    out: list[Metric] = []
    for item in metrics:
        m = item if isinstance(item, Metric) else analytics.metric(item, surface)
        if m not in out:
            out.append(m)
    return out


def _group(group: str | None, q: Query) -> str:
    group = group or q.group
    if group not in GROUPS:
        raise QueryError(f"group must be one of {', '.join(GROUPS)}")
    return group


def _grouped(
    conn: sqlite3.Connection, sel: RunSelection, group: str, metrics: list[Metric], *,
    buckets: Sequence[str] = (), extra: Sequence[str] = (), keys: Sequence[str] | None = None,
    quantiles: bool = False,
) -> tuple[list[_Spec], list[dict[str, Any]]]:
    """One SQL query: per group (key ``g``, id ``gid``) and bucket expressions
    ``b0, b1, ...``, ``runs``, ``t_min`` / ``t_max`` (Unix microseconds), the description columns
    of the group kind (:func:`ekte.web.run_row.label_sql`), the ``extra``
    aggregates (``x<i>``) and each
    metric's aggregates (``a<i>``).

    Runs are grouped by the integer that identifies their group on their own
    rows (:data:`ekte.web.run_row.GROUP_ID_SQL`), never by a value looked up
    per run: the few groups are named afterwards."""
    med, pct = sql_functions(conn)
    specs = [_spec(m, i, med, pct, quantiles) for i, m in enumerate(metrics)]
    if keys is not None:
        sel = sel.and_where(*_keys_sql(conn, group, keys))
    cols = [f"{run_row.GROUP_ID_SQL[group]} AS gid", *(f"{b} AS b{i}" for i, b in enumerate(buckets)),
            "COUNT(*) AS runs", "MIN(m.started_us) AS t_min", "MAX(m.started_us) AS t_max"]
    if group == "model":
        cols.append("MAX(m.model_in_kb) AS mkb")
    cols += [f"{e} AS x{i}" for i, e in enumerate(extra)]
    cols += [f"{a} AS a{i}" for i, a in enumerate(a for s in specs for a in s.aggs)]
    joins = "".join(s.join for s in specs)
    join_args = tuple(a for s in specs for a in s.args)
    # group=all needs no GROUP BY (SQLite would sort every run by the constant)
    group_by = ", ".join(p for p in (run_row.GROUP_BY_SQL[group],
                                     *(f"b{i}" for i in range(len(buckets)))) if p)
    sql = (f"SELECT {', '.join(cols)} {sel.from_sql}{joins}{sel.where_sql}"
           + (f" GROUP BY {group_by}" if group_by else ""))
    cur = conn.execute(run_row.label_sql(group, sql), (*join_args, *sel.args))
    names = [d[0] for d in cur.description]
    first = len(names) - sum(len(s.aggs) for s in specs)  # the metrics' aggregates come last
    rows = []
    for row in map(tuple, cur.fetchall()):
        r = dict(zip(names, row, strict=True))
        if not r["runs"]:  # without GROUP BY an empty selection still gives one row
            continue
        r["_aggs"] = row[first:]
        rows.append(r)
    return specs, rows


def group_ids(conn: sqlite3.Connection, group: str, keys: Iterable[str]) -> list[int]:
    """The group ids (:data:`ekte.web.run_row.GROUP_ID_SQL`) of the group keys
    ``keys`` of ``group`` (keys no run has are left out): a lookup in the
    small ``relay_group`` / ``model_group`` tables."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return []
    if group == "all":
        return [0] if ALL_KEY in keys else []

    def lookup(table: str, column: str, values: Sequence[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in range(0, len(values), 500):
            part = values[i:i + 500]
            out.update((str(k), int(v)) for k, v in conn.execute(
                f"SELECT {column}, id FROM {table} WHERE {column} IN ({', '.join('?' * len(part))})",
                part))
        return out

    if group == "relay":
        return sorted(lookup("relay_group", "relay_key", keys).values())
    if group == "model":
        return sorted(lookup("model_group", "model_key", keys).values())
    # key = relay_key || '|' || model: every (relay, model) split that spells a key
    pairs: list[tuple[int, str]] = []
    for rid, relay in conn.execute("SELECT id, relay_key FROM relay_group"):
        pairs += [(int(rid), key[len(relay) + 1:]) for key in keys if key.startswith(f"{relay}|")]
    models = lookup("model_group", "model_key", sorted({m for _, m in pairs}))
    return sorted({rid << run_row.MODEL_BITS | models[m] for rid, m in pairs if m in models})


def _keys_sql(conn: sqlite3.Connection, group: str, keys: Sequence[str]) -> tuple[Any, ...]:
    """The condition (and its arguments) that selects the runs of the group
    keys ``keys`` of ``group``, on their group ids."""
    ids = group_ids(conn, group, keys)
    if not ids:
        return ("0",)
    if group == "all":
        return ("1",)
    return (f"{run_row.GROUP_ID_SQL[group]} IN ({', '.join('?' * len(ids))})", *ids)


def _cells(specs: list[_Spec], row: Mapping[str, Any]) -> dict[str, Cell]:
    out, i = {}, 0
    runs = int(row["runs"])
    aggs = row["_aggs"]  # the metrics' aggregates, in spec order (see _grouped)
    for s in specs:
        k = len(s.aggs)
        out[s.metric.id] = _cell(s, aggs[i:i + k], runs)
        i += k
    return out


def _result(group: str, row: Mapping[str, Any], cells: dict[str, Cell]) -> GroupResult:
    runs, first, last = int(row["runs"]), us_text(row["t_min"]), us_text(row["t_max"])
    if group == "relay":
        return GroupResult(str(row["g"]), str(row["rl"]), str(row["rkind"]), bool(row["rin"]),
                           runs, cells, first, last)
    if group == "model":
        return GroupResult(str(row["g"]), str(row["g"]), "model", bool(row["mkb"]), runs, cells,
                           first, last)
    if group == "relay_model":
        return GroupResult(str(row["g"]), f"{row['rl']} · {row['mk']}", "relay_model",
                           bool(row["rin"]), runs, cells, first, last, str(row["rk"]),
                           str(row["mk"]))
    return GroupResult(ALL_KEY, ALL_KEY, "all", False, runs, cells, first, last)


def _rank(g: GroupResult) -> tuple[Any, ...]:
    return (-g.runs, g.label.lower(), g.key)


def aggregate(
    conn: sqlite3.Connection, q: Query, metrics: Iterable[str | Metric], group: str | None = None,
    *, quantiles: bool = False,
) -> list[GroupResult]:
    """Each metric (ids, ``dim:<key>`` included, or :class:`Metric`) over the
    runs of ``q``, per group (``group``, default ``q.group``), busiest group
    first. One SQL query; ``quantiles`` adds ``p25`` / ``p75`` to median
    cells (two more aggregates each). A metric that does not apply to
    ``q.surface`` raises :class:`QueryError` (via
    :func:`ekte.web.analytics.metric`)."""
    group = _group(group, q)
    wanted = _metrics(metrics, q.surface)
    specs, rows = _grouped(conn, select_runs(q), group, wanted, quantiles=quantiles)
    return sorted((_result(group, r, _cells(specs, r)) for r in rows), key=_rank)


# --------------------------------------------------------------------------- #
# Time series
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Point:
    """One time bucket of a series: its key (as
    :func:`ekte.web.analytics._bucket`), ``extra`` (``dow`` / ``hour`` /
    ``hours`` / ``week`` of a ``dow_hour`` grid), runs in it, and the cell."""

    bucket: str
    pos: float
    extra: dict[str, Any]
    runs: int
    cell: Cell

    def public(self) -> dict[str, Any]:
        return {"bucket": self.bucket, **self.extra, "runs": self.runs, **self.cell.public()}


@dataclass(frozen=True)
class Series:
    """One group over time: the group (``runs``: its dated runs; no metric
    cells), ``n`` (of them with a value), the non-empty buckets in time order,
    where the ekte version or knowledge-base profile changes
    (``annotations``), and whether suite / stream mode / api vary (``mixed``)."""

    group: GroupResult
    n: int
    points: list[Point]
    annotations: list[dict[str, Any]] = field(default_factory=list)
    mixed: dict[str, bool] = field(default_factory=dict)

    @property
    def coverage(self) -> float | None:
        return _ratio(self.n, self.group.runs)

    def public(self) -> dict[str, Any]:
        return {**self.group.describe(), "runs": self.group.runs, "n": self.n,
                "coverage": self.coverage, "points": [p.public() for p in self.points],
                "annotations": self.annotations, "mixed": self.mixed}


@dataclass(frozen=True)
class SeriesResult:
    metric: Metric
    group: str
    bucket: str
    block: int
    fold: str
    fold_requested: str
    span_days: int
    tz: str
    series: list[Series]

    def public(self) -> dict[str, Any]:
        return {"metric": self.metric.public(), "group": self.group, "bucket": self.bucket,
                "block": self.block, "fold": self.fold, "fold_requested": self.fold_requested,
                "fold_min_days": analytics.FOLD_MIN_DAYS, "span_days": self.span_days,
                "tz": self.tz, "min_runs": MIN_RUNS,
                "series": [s.public() for s in self.series]}


def _zone(tz: tzinfo | str) -> tuple[tzinfo, str]:
    if isinstance(tz, str):
        try:
            return ZoneInfo(tz), tz
        except Exception:
            raise QueryError(f"unknown time zone {tz[:64]!r}") from None
    if isinstance(tz, ZoneInfo):
        return tz, tz.key
    if isinstance(tz, timezone):
        offset = tz.utcoffset(None)
        return tz, "UTC" if not offset else str(tz)
    return tz, str(tz)


def _offset(zone: tzinfo, dt: datetime) -> int:
    off = dt.astimezone(zone).utcoffset()
    return int(off.total_seconds()) if off is not None else 0


# offset_sql() steps through a range this often (a time zone changes its
# offset at most once in that time), for ranges up to _STEP_SPAN.
_STEP = timedelta(days=7)
_STEP_SPAN = timedelta(days=366 * 20)


def offset_sql(zone: tzinfo, points: Iterable[datetime], run: str = "m") -> str:
    """SQL for the UTC offset (seconds) of ``zone`` at the start of the run
    row ``run`` (its ``started_us``, see :func:`time_sql`):
    a constant, or a ``CASE`` over the zone's transitions. ``points`` are UTC
    instants, sorted, with at most one transition between two neighbours that
    are less than :data:`_STEP` apart; a transition between neighbours further
    apart is put at the later one (no run may lie between them). Exact for
    runs within the points' span."""
    steps: list[tuple[datetime, int]] = []
    prev: tuple[datetime, int] | None = None
    base = None
    for p in points:
        off = _offset(zone, p)
        if prev is None:
            base = off
        elif off != prev[1]:
            at = p
            if p - prev[0] <= _STEP:  # the first second with the new offset
                lo, hi = 0, max(1, math.ceil((p - prev[0]).total_seconds()))
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if _offset(zone, prev[0] + timedelta(seconds=mid)) == prev[1]:
                        lo = mid
                    else:
                        hi = mid
                at = prev[0] + timedelta(seconds=hi)
            steps.append((at, off))
        prev = (p, off)
    if base is None:
        return "0"
    branches = []
    for at, off in steps:
        branches.append(f"WHEN {time_sql('<', at, run)} THEN {base}")
        base = off
    return f"(CASE {' '.join(branches)} ELSE {base} END)" if branches else str(base)


def _offset_points(conn: sqlite3.Connection, sel: RunSelection, first: datetime,
                   last: datetime) -> list[datetime]:
    """The :func:`offset_sql` points for runs from ``first`` to ``last``: every
    :data:`_STEP` across the span, or (a span longer than :data:`_STEP_SPAN`,
    e.g. a damaged run date) the start and end of each UTC day with runs."""
    first = first.replace(microsecond=0)
    if last - first <= _STEP_SPAN:
        points = []
        p = first
        while p <= last:
            points.append(p)
            p += _STEP
        return [*points, last + timedelta(seconds=1)]
    days = conn.execute(f"SELECT DISTINCT substr(m.started_at, 1, 10) {sel.sql} ORDER BY 1",
                        sel.args).fetchall()
    out = []
    for (day,) in days:
        start = datetime.fromisoformat(day).replace(tzinfo=UTC)
        out += [start, start + timedelta(days=1) - timedelta(seconds=1)]
    return out


# Days added to a run's local time in _bucket_sql, so that its integer
# divisions floor (SQLite's truncate toward zero) for any local time from
# 1970 on: a multiple of 28, so weekdays and 4-week cycles keep their place.
_SHIFT_DAYS = 28 * 10_000
_CYCLE_DAY = (analytics.CYCLE_EPOCH - date(1970, 1, 1)).days


def _bucket_sql(size: str, offset: str, block: int, fold: str) -> list[str]:
    """SQL expressions that partition runs exactly as
    :func:`ekte.web.analytics._bucket` (``offset``: the zone's UTC offset in
    seconds at the run's time). Integer arithmetic on the run's local time in
    seconds (from ``started_us``): the values only tell buckets apart; Python
    names them from a run in each."""
    local = f"(m.started_us / 1000000 + {offset} + {_SHIFT_DAYS * 86400})"
    day = f"({local} / 86400)"  # 1970-01-01 (+ the shift) is a Thursday
    if size == "hour":
        return [f"{local} / 3600", offset]  # the offset parts a DST fold
    if size == "day":
        return [day]
    if size == "week":
        return [f"({day} + 3) / 7"]  # weeks start on Monday
    out = [f"({day} + 4) % 7", f"{local} % 86400 / 3600 / {block}"]  # %w, hour block
    if fold == "4weeks":
        out.append(f"({day} - {_CYCLE_DAY}) / 7 % 4")
    elif fold == "month_week":
        out.append(f"MIN(4, (CAST(strftime('%d', {local} - {_SHIFT_DAYS * 86400}, 'unixepoch')"
                   " AS INTEGER) - 1) / 7)")
    return out


def _check(name: str, value: Any, allowed: Sequence[Any]) -> None:
    if value not in allowed:
        raise QueryError(f"{name} must be one of {', '.join(str(a) for a in allowed)}")


# Whether these vary in a series (Series.mixed), from their ids on the run row
_MIXED = tuple(run_row.VARYING)


def _data_bounds(conn: sqlite3.Connection) -> tuple[datetime, datetime] | None:
    """The first and last dated run time of the whole history (two index
    lookups in the started_at index)."""
    lo, hi = (analytics_store.format_ts(t) for t in (analytics._T_MIN, analytics._T_MAX))
    row = conn.execute(
        "SELECT (SELECT started_at FROM history_metrics WHERE started_at >= ?1 AND started_at < ?2"
        " ORDER BY started_at LIMIT 1), (SELECT started_at FROM history_metrics"
        " WHERE started_at >= ?1 AND started_at < ?2 ORDER BY started_at DESC LIMIT 1)",
        (lo, hi)).fetchone()
    first, last = (analytics_store.parse_ts(v) for v in row)
    return (first, last) if first is not None and last is not None else None


def series(
    conn: sqlite3.Connection, q: Query, metric: str | Metric, group: str | None = None,
    bucket: str = "day", tz: tzinfo | str = UTC, *, keys: Iterable[str] = (), block: int = 1,
    fold: str = "week", max_keys: int = MAX_KEYS, quantiles: bool = False,
) -> SeriesResult:
    """One metric per group over time, in the viewer's time zone ``tz``
    (``bucket``: hour, day, week or dow_hour with ``block`` hours per row and
    ``fold`` week / 4weeks / month_week, as :func:`ekte.web.analytics._bucket`;
    a fold needs :data:`ekte.web.analytics.FOLD_MIN_DAYS` calendar days of
    runs, else it falls back to ``week``). ``keys``: up to ``max_keys`` series
    keys, default the busiest groups. Undated runs are left out; ``quantiles``
    adds ``p25`` / ``p75`` to the points of a median metric.

    SQLite buckets the runs (the zone's offset is a ``CASE`` over its
    transitions, :func:`offset_sql`) and Python only names the buckets: one
    query for the buckets, one grouped query for the annotations (plus small
    reads of the runs where values change, :func:`_annotations`), and one more for the
    run counts per group when the busiest groups must be found (no ``keys``)
    or a fold needs the span first."""
    group = _group(group, q)
    _check("bucket", bucket, analytics.BUCKETS)
    _check("block", block, analytics.BLOCKS)
    _check("fold", fold, analytics.FOLDS)
    zone, zone_name = _zone(tz)
    m = _metrics([metric], q.surface)[0]
    wanted: list[str] = []
    for key in keys:
        key = (key or "").strip()
        if key and key not in wanted:
            wanted.append(key)
    if len(wanted) > max_keys:
        raise QueryError(f"at most {max_keys} keys")

    sel = select_runs(q).and_where(_DATED_SQL)

    def span(rows: Iterable[Mapping[str, Any]]) -> int:
        times = sorted(t for r in rows for t in (r["t_min"], r["t_max"]) if t is not None)
        if not times:
            return 0
        a, b = us_dt(times[0]), us_dt(times[-1])
        return (b.astimezone(zone).date() - a.astimezone(zone).date()).days + 1

    used_fold = "week"
    if not wanted or (bucket == "dow_hour" and fold != "week"):
        _, counted = _grouped(conn, sel, group, [], keys=wanted or None)
        if not wanted:
            ranked = sorted((_result(group, r, {}) for r in counted), key=_rank)
            wanted = [g.key for g in ranked[:max_keys]]
        shown = [r for r in counted if str(r["g"]) in wanted]
        if bucket == "dow_hour" and span(shown) >= analytics.FOLD_MIN_DAYS.get(fold, 0):
            used_fold = fold

    bounds = _data_bounds(conn) if wanted else None
    rows: list[dict[str, Any]] = []
    specs: list[_Spec] = []
    if bounds is not None:
        off = offset_sql(zone, _offset_points(conn, sel, *bounds))
        extra = [f"{f}(m.{c}_id)" for c in _MIXED for f in ("MIN", "MAX")]
        specs, rows = _grouped(conn, sel, group, [m], keys=wanted, quantiles=quantiles,
                               extra=extra, buckets=_bucket_sql(bucket, off, block, used_fold))
    by_key: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault(str(r["g"]), []).append(r)
    ids = {int(r["gid"]): str(r["g"]) for r in rows}
    annotations = ({} if bucket == "dow_hour" or not by_key
                   else _annotations(conn, sel, group, ids, zone, bucket))

    out = []
    for key in wanted:
        members = by_key.get(key, [])
        if not members:
            out.append(Series(GroupResult(key, key, group, False, 0, {}), 0, [], [],
                              dict.fromkeys(_MIXED, False)))
            continue
        points, n = [], 0
        for r in members:
            t = us_dt(r["t_min"])
            pos, bkey, bextra = analytics._bucket(t, zone, bucket, block, used_fold)
            cell = _cells(specs, r)[m.id]
            n += cell.n
            if cell.n:
                points.append(Point(bkey, pos, bextra, int(r["runs"]), cell))
        whole = {**members[0], "runs": sum(int(r["runs"]) for r in members),
                 "t_min": min(r["t_min"] for r in members),
                 "t_max": max(r["t_max"] for r in members)}
        if group == "model":  # in the knowledge base through any of its runs
            whole["mkb"] = max(r["mkb"] for r in members)
        mixed = {}
        for i, c in enumerate(_MIXED):
            lows = [r[f"x{2 * i}"] for r in members if r[f"x{2 * i}"] is not None]
            highs = [r[f"x{2 * i + 1}"] for r in members if r[f"x{2 * i + 1}"] is not None]
            mixed[c] = bool(lows) and min(lows) != max(highs)
        out.append(Series(_result(group, whole, {}), n, sorted(points, key=lambda p: p.pos),
                          annotations.get(key, []), mixed))
    span_days = span(r for key in wanted for r in by_key.get(key, []))
    return SeriesResult(m, group, bucket, block, used_fold, fold, span_days, zone_name, out)


# The run values whose changes are annotated: (kind, their id on the run row, lookup).
_CHANGES = tuple((kind, f"m.{column}", lookup) for kind, (column, lookup) in run_row.CHANGES.items())
# at most this many time ranges in one query (more are read as one), and
# start times in one IN list
_MAX_RANGES = 64
_MAX_TIMES = 500


def _segments(spans: Mapping[Any, list[str]]) -> list[tuple[str, str, Any]]:
    """A key's runs of one kind in time order, from each value's ``[first,
    last]`` run time: ``("one", t, v)`` runs of value ``v`` alone, from its
    first run at ``t``; ``("read", t0, t1)`` runs from ``t0`` to ``t1``
    (inclusive) where values overlap, to compare one by one; ``("after", t,
    v)`` runs of ``v`` alone after ``t``. Values whose times overlap (or
    touch) form one cluster: before its second value starts only the first
    one runs, after the second-to-last value ends only the last one."""
    clusters: list[list[tuple[Any, str, str]]] = []
    end = ""
    for value, (first, last) in sorted(spans.items(), key=lambda kv: kv[1]):
        if clusters and first <= end:
            clusters[-1].append((value, first, last))
            end = max(end, last)
        else:
            clusters.append([(value, first, last)])
            end = last
    out: list[tuple[str, str, Any]] = []
    for c in clusters:
        v1, t0, _ = c[0]
        if len(c) == 1:
            out.append(("one", t0, v1))
            continue
        start = min(first for _, first, _ in c[1:])
        lasts = sorted(c, key=lambda x: x[2])
        stop, (vmax, _, tmax) = lasts[-2][2], lasts[-1]
        if t0 < start:
            out.append(("one", t0, v1))
        out.append(("read", start, stop))
        if tmax > stop:
            out.append(("after", stop, vmax))
    return out


def _annotations(conn: sqlite3.Connection, sel: RunSelection, group: str, ids: Mapping[int, str],
                 zone: tzinfo, size: str) -> dict[str, list[dict[str, Any]]]:
    """Per series key: where the ekte version or knowledge-base profile
    changes from one run to the next in time order (unknown values skipped).

    One grouped query gives each value's first and last run time per key
    (:func:`_segments`): where values follow each other, a value changes at
    the first run of the next one, found by its time; only the runs where
    values overlap in time (a rollback, two versions in use) are read and
    compared one by one. Equal to comparing every run with the previous run
    that has a value. ``ids``: group id -> key of the series."""
    gid = run_row.GROUP_ID_SQL[group]
    ident, n = [gid], 1

    def key_of(parts: Sequence[Any]) -> str | None:
        return ids.get(int(parts[0]))

    def of(gids: Iterable[int]) -> RunSelection:
        gids = sorted(gids)
        return sel if group == "all" else sel.and_where(f"{gid} IN ({', '.join('?' * len(gids))})", *gids)

    keyed = of(ids)
    values = [v for _, v, _ in _CHANGES]
    # the values (by their ids on the run row) as text, and back
    names: list[dict[int, str]] = []
    for _, _, lookup in _CHANGES:
        names.append({int(i): str(v) for i, v in conn.execute(f"SELECT id, value FROM {lookup.table}")})
    numbers = [{v: i for i, v in by_id.items()} for by_id in names]

    def texts(row: Sequence[Any]) -> list[str | None]:
        return [None if v is None else names[i][int(v)] for i, v in enumerate(row)]

    # key -> per kind: value -> [first, last] run time (from the grouped run-row
    # ids, in the order of the values' text)
    grouped: list[tuple[Any, ...]] = []
    by = ", ".join(c for c in (run_row.GROUP_BY_SQL[group], *values) if c)
    for row in conn.execute(f"SELECT {', '.join([*ident, *values])}, MIN(m.started_us),"
                            f" MAX(m.started_us) {keyed.sql} GROUP BY {by}", keyed.args):
        key = key_of(row[:n])
        if key is not None:
            grouped.append((key, *texts(row[n:n + len(values)]), us_text(row[-2]), us_text(row[-1])))
    grouped.sort(key=lambda r: tuple((v is not None, v) for v in r[:1 + len(values)]))
    spans: dict[str, list[dict[Any, list[str]]]] = {}
    for key, *row in grouped:
        per = spans.setdefault(key, [{} for _ in _CHANGES])
        first, last = row[-2], row[-1]
        for i, value in enumerate(row[:len(values)]):
            if value is not None:
                s = per[i].setdefault(value, [first, last])
                s[0], s[1] = min(s[0], first), max(s[1], last)
    segments = {key: [_segments(s) for s in per] for key, per in spans.items()}
    every = [seg for per in segments.values() for segs in per for seg in segs]
    starts = sorted({t for what, t, _ in every if what == "one"})
    mixed = sorted((t0, t1) for what, t0, t1 in every if what == "read")

    cols = ", ".join([*ident, "m.history_id", "m.started_at", *values])
    # the first run of each one-value cluster: the smallest id at its start time
    firsts: dict[tuple[str, int, str, Any], int] = {}
    for i in range(0, len(starts), _MAX_TIMES):
        part = starts[i:i + _MAX_TIMES]
        at = keyed.and_where(f"m.started_at IN ({', '.join('?' * len(part))})", *part)
        for row in conn.execute(f"SELECT {cols} {at.sql}", at.args):
            key, rid, t = key_of(row[:n]), int(row[n]), row[n + 1]
            if key is None:
                continue
            for k, value in enumerate(texts(row[n + 2:])):
                if value is not None:
                    f = (key, k, t, value)
                    firsts[f] = min(firsts.get(f, rid), rid)
    # the runs where values overlap, in time order
    runs: dict[str, list[tuple[str, int, Sequence[Any]]]] = {}
    if mixed:
        merged: list[list[str]] = []
        for a, b in mixed:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        if len(merged) > _MAX_RANGES:
            merged = [[merged[0][0], max(s[1] for s in merged)]]
        cond = " OR ".join(["m.started_at BETWEEN ? AND ?"] * len(merged))
        part_sel = keyed.and_where(f"({cond})", *(t for s in merged for t in s))
        for row in conn.execute(f"SELECT {cols} {part_sel.sql} ORDER BY m.started_at,"
                                " m.history_id", part_sel.args):
            key = key_of(row[:n])
            if key is not None:
                runs.setdefault(key, []).append((row[n + 1], int(row[n]), texts(row[n + 2:])))

    out: dict[str, list[dict[str, Any]]] = {}

    def change(key: str, kind: str, a: Any, b: Any, rid: int, t: str) -> None:
        dt = analytics_store.parse_ts(t)
        assert dt is not None
        out.setdefault(key, []).append({
            "bucket": analytics._bucket(dt, zone, size)[1], "kind": kind, "from": a, "to": b,
            "run_id": rid, "started_at": t,
        })

    def first_after(key: str, i: int, t: str, value: Any) -> tuple[int, str]:
        """The first run of ``key`` with ``value`` (kind ``i``) after ``t``."""
        after = of(g for g, k in ids.items() if k == key).and_where(
            f"m.started_at > ? AND {values[i]} = ?", t, numbers[i][value])
        row = conn.execute(f"SELECT m.history_id, m.started_at {after.sql}"
                           " ORDER BY m.started_at, m.history_id LIMIT 1", after.args).fetchone()
        return int(row[0]), str(row[1])

    for key, by_kind in segments.items():
        mine = runs.get(key, [])
        times = [r[0] for r in mine]
        for i, segs in enumerate(by_kind):
            kind, prev = _CHANGES[i][0], None
            for what, t, v in segs:
                if what == "read":
                    for rt, rid, row_values in mine[bisect_left(times, t):bisect_right(times, v)]:
                        value = row_values[i]
                        if value is None:
                            continue
                        if prev is not None and value != prev:
                            change(key, kind, prev, value, rid, rt)
                        prev = value
                    continue
                if prev is not None and v != prev:
                    rid, rt = ((firsts[(key, i, t, v)], t) if what == "one"
                               else first_after(key, i, t, v))
                    change(key, kind, prev, v, rid, rt)
                prev = v
    for items in out.values():
        items.sort(key=lambda a: (a["started_at"], a["kind"], a["run_id"]))
    return out


# --------------------------------------------------------------------------- #
# Keyset paging
# --------------------------------------------------------------------------- #
def _rank_sql(column: str, codes: Mapping[Any, int]) -> str:
    """A run-row code (``column``) as a rank: ``codes`` maps code -> rank, others 0."""
    return f"CASE {column} {' '.join(f'WHEN {c} THEN {r}' for c, r in codes.items())} ELSE 0 END"


# The page order's ranks, from the run row's risk_value / grade_value
_RISK_RANK = _rank_sql("m.risk_value", {run_row.RISK_ORDER.index(r): i + 1 for i, r in
                                        enumerate(("clean", "low", "medium", "high"))})
_GRADE_RANK = _rank_sql("m.grade_value", {GRADE_SCALE.index(g) + 1: i + 1 for i, g in
                                          enumerate(("F", "D", "C", "B", "A"))})
# The sort value of each sort key. NULL (a run without a start time or a
# score) sorts first ascending and last descending; ties go by id.
SORT_SQL: dict[str, str] = {
    "time": "m.started_at",  # walks idx_history_metrics_started
    "score": "m.score",
    "risk": _RISK_RANK,  # inconclusive / none < clean < low < medium < high
    "grade": _GRADE_RANK,  # none < F < D < C < B < A
}
PAGE_COLUMNS: tuple[str, ...] = (
    *(f"h.{c}" for c in (
        "id", "ts", "base_url", "claimed_model", "model", "mode", "suite", "risk_level", "score",
        "rating", "kb_match", "watch_id", "api", "api_auto", "stream_mode")),
    "COALESCE(h.surface, 'chat') AS surface", "m.started_at", "m.started_at_estimated",
    "rm.relay_key", "rm.label AS relay_label", "rm.kind AS relay_kind", "rm.in_kb AS relay_in_kb",
    "m.latency_p50_ms", "m.ttft_p50_ms", "m.decode_tps_p50", "m.success_rate", "m.error_rate",
)
"""The columns of a :func:`page_runs` row (``AS`` names where given): the
History list's, the run's relay, and its headline values."""


@dataclass(frozen=True)
class Page:
    """Run rows (dicts of :data:`PAGE_COLUMNS`) and the cursor of the next
    page (``after``; None on the last page)."""

    rows: list[dict[str, Any]]
    after: str | None
    sort: str

    def public(self) -> dict[str, Any]:
        return {"rows": self.rows, "after": self.after, "sort": self.sort}


def _parse_sort(sort: str) -> tuple[str, bool]:
    key, desc = (sort[1:], True) if sort.startswith("-") else (sort, False)
    if key not in SORT_SQL:
        raise QueryError(f"sort must be one of {', '.join(SORTS)}, optionally with - (descending)")
    return key, desc


def _cursor(sort: str, value: Any, rid: int) -> str:
    raw = json.dumps([sort, value, rid], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _uncursor(after: str, sort: str) -> tuple[Any, int]:
    try:
        raw = base64.urlsafe_b64decode(after + "=" * (-len(after) % 4))
        s, value, rid = json.loads(raw)
    except (ValueError, TypeError, binascii.Error):
        raise QueryError("after is not a valid cursor") from None
    if s != sort or isinstance(rid, bool) or not isinstance(rid, int) or isinstance(value, bool) \
            or not (value is None or isinstance(value, (str, int, float))):
        raise QueryError("after is not a cursor of this sort")
    return value, rid


def _after_sql(expr: str, desc: bool, value: Any, rid: int) -> tuple[str, tuple[Any, ...]]:
    """The keyset condition "after (value, rid)" in the order of ``expr``
    (NULLs first ascending, last descending), then ``m.history_id``."""
    ident = "m.history_id"
    if value is None:
        if desc:
            return f"({expr} IS NULL AND {ident} < ?)", (rid,)
        return f"({expr} IS NOT NULL OR {ident} > ?)", (rid,)
    op = "<" if desc else ">"
    cond = f"({expr}, {ident}) {op} (?, ?)"
    return (f"({cond} OR {expr} IS NULL)" if desc else cond), (value, rid)


def page_runs(
    conn: sqlite3.Connection, q: Query, sort: str = "-time", after: str | None = None,
    limit: int | None = PAGE_LIMIT,
) -> Page:
    """One page of ``q``'s runs, ordered by ``sort`` (``time``, ``score``,
    ``risk``, ``grade``; ``-`` in front for descending), then id in the same
    direction. ``after`` is the previous page's cursor (opaque: the last
    row's sort value and id), ``limit`` 1 to :data:`MAX_PAGE_LIMIT` (default
    :data:`PAGE_LIMIT`). Keyset paging: a run saved meanwhile never shifts
    the pages. The page is chosen on ``(sort value, id)`` alone, then its
    rows' columns are read."""
    key, desc = _parse_sort(sort)
    if limit is None:
        limit = PAGE_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_LIMIT:
        raise QueryError(f"limit must be from 1 to {MAX_PAGE_LIMIT}")
    expr = SORT_SQL[key]
    sel = select_runs(q)
    if after:
        cond, args = _after_sql(expr, desc, *_uncursor(after, sort))
        sel = sel.and_where(cond, *args)
    direction = "DESC" if desc else "ASC"
    order = f"ORDER BY {{s}} {direction}, {{i}} {direction}"
    cur = conn.execute(
        f"WITH p AS MATERIALIZED (SELECT m.history_id AS id, {expr} AS s {sel.sql}"
        f" {order.format(s=expr, i='m.history_id')} LIMIT ?)"
        f" SELECT {', '.join(PAGE_COLUMNS)}, p.s AS _sort FROM p"
        f" JOIN history h ON h.id = p.id JOIN history_metrics m ON m.history_id = p.id {GROUP_JOIN_SQL}"
        f" {order.format(s='p.s', i='p.id')}", (*sel.args, limit + 1))
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        nxt = _cursor(sort, rows[-1]["_sort"], int(rows[-1]["id"]))
    for row in rows:
        row.pop("_sort")
    return Page(rows, nxt, sort)
