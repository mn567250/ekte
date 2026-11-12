"""The metric registry and its display semantics: the one catalogue of metric
ids, units, formats, label keys and directions, and the server-side judgement
of a value (colour family, grade, better / worse) the pages show.

* **Registry.** :data:`METRICS` holds every per-run metric the analytics and
  history queries aggregate (:mod:`ekte.web.query`, :mod:`ekte.web.analytics`
  re-exports it); :data:`COUNTS` the run / relay / model counts of the KPI
  grid, which are counted, not aggregated. :func:`catalogue` is what
  ``GET /api/metrics`` answers.
* **Labels are keys.** Each metric names i18n keys (``metric.<id>``,
  ``metric.<id>.short``, ``metric.<id>.kpi``, ``metric.<id>.agg_hint``; see
  :meth:`Metric.public`), translated in the browser from
  ``ekte/i18n/locales/fragments/metrics/``. A metric without a shorter or a KPI
  label of its own names its plain label there.
* **Judgement on the server.** :func:`present` turns a value (and the previous
  period's) into the colour family, grade letter, delta direction and trend key
  the pages render. Score families and grade letters come from the grade
  thresholds of :mod:`ekte.scoring`, read at call time: they are never copied.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ekte import errorclass, scoring
from ekte.config import SURFACES

# A value (or bucket, or leaderboard cell) resting on fewer runs than this is
# flagged low_n; a delta against fewer previous runs gets no verdict.
MIN_RUNS = 3

# Every surface, and the chat surface alone (metrics of chat completions only).
ALL_SURFACES = frozenset(SURFACES)
CHAT_ONLY = frozenset({"chat"})

# Per-dimension scores: ``dim:<dimension>`` (history_dimensions, kind 'dimension').
DIM_PREFIX = "dim:"
DIM_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

AGGS = ("median", "pooled", "share", "count")
FORMATS = ("score", "grade", "percent", "ms", "tok_s", "ratio_percent", "tokens", "count", "seconds")
# The display format of a unit, unless the metric names its own.
_UNIT_FORMAT = {"score": "score", "grade": "grade", "ratio": "percent", "ms": "ms", "tok/s": "tok_s",
                "tokens": "tokens", "count": "count", "s": "seconds"}
# Colour families: judged ones, and the neutral families of the latency and
# speed series (a value with no better or worse of its own).
FAMILIES = ("good", "sky", "warn", "bad", "grey", "lat", "tps")
_UNIT_FAMILY = {"ms": "lat", "tok/s": "tps"}
# The colour family of each grade letter (scoring.GRADE_SCALE).
GRADE_FAMILY = {"A": "good", "B": "good", "C": "sky", "D": "warn", "E": "bad", "F": "bad"}
DIRECTIONS = ("better", "worse", "neutral", "none")
TREND_KEYS = {1: "trend.rising", -1: "trend.falling", 0: "trend.unchanged"}


@dataclass(frozen=True)
class Metric:
    """A public metric id, where its per-run value comes from and how it shows.

    ``agg`` says how runs combine (:mod:`ekte.web.query`): ``median`` of the
    per-run values, ``share`` of the runs with "yes", or ``pooled``: the
    outcome counts ``outcomes`` (``history_outcomes``) summed over the runs,
    divided by the summed base ``base`` (a ``history_metrics`` column,
    ``requests_judged`` or ``requests_total``); the per-run ``column`` is
    then that run's own ratio. ``count`` (:data:`COUNTS` only) is counted over
    the runs, not aggregated.

    ``fmt`` overrides the display format of the unit (:data:`FORMATS`);
    ``short`` / ``kpi`` say the metric has a shorter label (narrow tiles) / a
    label of its own as an aggregate over runs ("Median score").
    """

    id: str
    column: str  # history / history_metrics column ("" for derived values)
    unit: str  # score | grade | ratio | ms | tok/s | tokens | count | s
    higher_is_better: bool | None  # None: neither (e.g. billing ratio, ideal 1.0)
    agg: str = "median"  # median | share | pooled | count
    surfaces: frozenset[str] = ALL_SURFACES  # the surfaces it is measured on
    outcomes: tuple[str, ...] = ()  # pooled: the outcomes counted (numerator)
    base: str = ""  # pooled: the history_metrics column of the denominator
    fmt: str = ""  # display format; "" = the unit's
    short: bool = False  # has metric.<id>.short
    kpi: bool = False  # has metric.<id>.kpi

    @property
    def format(self) -> str:
        return self.fmt or _UNIT_FORMAT[self.unit]

    @property
    def label_key(self) -> str:
        return f"metric.{self.id}"

    @property
    def short_label_key(self) -> str:
        return f"metric.{self.id}.short" if self.short else self.label_key

    @property
    def kpi_label_key(self) -> str:
        return f"metric.{self.id}.kpi" if self.kpi else self.label_key

    @property
    def agg_hint_key(self) -> str:
        return f"metric.{self.id}.agg_hint"

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "unit": self.unit, "format": self.format, "higher_is_better": self.higher_is_better,
                "agg": self.agg, "surfaces": [s for s in SURFACES if s in self.surfaces],
                "label_key": self.label_key, "short_label_key": self.short_label_key,
                "kpi_label_key": self.kpi_label_key, "agg_hint_key": self.agg_hint_key}

    def applies(self, surface: str) -> bool:
        return surface in self.surfaces


def _m(mid: str, column: str, unit: str, better: bool | None, agg: str = "median",
       surfaces: frozenset[str] = ALL_SURFACES, **display: Any) -> Metric:
    return Metric(mid, column, unit, better, agg, surfaces, **display)


def _pooled(mid: str, better: bool, outcomes: tuple[str, ...], base: str = "requests_judged",
            **display: Any) -> Metric:
    """An outcome rate (:mod:`ekte.perf.outcomes`): Σ outcome counts ÷ Σ base."""
    return Metric(mid, mid, "ratio", better, "pooled", ALL_SURFACES, outcomes, base, **display)


# The whitelist: public id -> column. Rates and shares are 0..1 ("ratio").
METRICS: dict[str, Metric] = {m.id: m for m in (
    _m("score", "score", "score", True, kpi=True),
    # the run's grade letter (history.rating) on the 1..6 scale: grade_value()
    _m("grade", "rating", "grade", True, kpi=True),
    _m("risk_high_share", "risk_level", "ratio", False, "share", short=True),
    _pooled("success_rate", True, (errorclass.SUCCESS,)),
    _pooled("error_rate", False, errorclass.RELAY_ERRORS),
    _pooled("timeout_rate", False, (errorclass.RELAY_TIMEOUT,)),
    _pooled("rate_limited_rate", False, (errorclass.RATE_LIMITED,), short=True),
    _pooled("impaired_rate", False, errorclass.IMPAIRED, "requests_total", short=True),
    _m("latency_p50", "latency_p50_ms", "ms", False),
    _m("latency_p95", "latency_p95_ms", "ms", False),
    _m("ttft_p50", "ttft_p50_ms", "ms", False, surfaces=CHAT_ONLY, short=True),
    _m("ttft_p95", "ttft_p95_ms", "ms", False, surfaces=CHAT_ONLY, short=True),
    _m("decode_tps", "decode_tps_p50", "tok/s", True, surfaces=CHAT_ONLY, short=True),
    _m("decode_tps_p5", "decode_tps_p5", "tok/s", True, surfaces=CHAT_ONLY, short=True),
    _m("decode_tps_p95", "decode_tps_p95", "tok/s", True, surfaces=CHAT_ONLY, short=True),
    _m("itl_jitter", "itl_jitter_p50_ms", "ms", False, surfaces=CHAT_ONLY),
    _m("relay_overhead", "relay_processing_p50_ms", "ms", False),
    _m("network_rtt", "network_rtt_p50_ms", "ms", False),
    _m("cold_start", "cold_start_ms", "ms", False),
    _m("concurrency_tps", "concurrency_tps", "tok/s", True, surfaces=CHAT_ONLY),
    _m("billing_ratio_prompt", "billing_ratio_prompt", "ratio", None, surfaces=CHAT_ONLY,
       fmt="ratio_percent", short=True),
    _m("billing_ratio_completion", "billing_ratio_completion", "ratio", None, surfaces=CHAT_ONLY,
       fmt="ratio_percent", short=True),
    _m("reasoning_share", "reasoning_share", "ratio", None, surfaces=CHAT_ONLY),
    _m("cached_input_share", "cached_input_share", "ratio", None, surfaces=CHAT_ONLY),
    _m("model_mismatch_rate", "model_mismatch", "ratio", False, "share"),
    _m("context_claimed", "context_claimed_tokens", "tokens", None, surfaces=CHAT_ONLY),
    _m("context_effective", "context_effective_tokens", "tokens", True, surfaces=CHAT_ONLY),
    _m("findings_high", "findings_high", "count", False),
    _m("findings_medium", "findings_medium", "count", False),
    _m("findings_low", "findings_low", "count", False),
    _m("duration", "duration_sec", "s", None),
)}
# The counts of the KPI grid: runs, distinct relays (knowledge-base entries)
# and distinct claimed models of the selection. Not aggregatable metrics.
COUNTS: dict[str, Metric] = {m.id: m for m in (
    _m("runs", "", "count", None, "count"),
    _m("relays", "", "count", None, "count"),
    _m("models", "", "count", None, "count"),
)}

# The Analytics KPI grid, 4 columns x 3 rows in reading order (#117). On a
# surface a tile's metric does not apply to, the tile keeps its slot ("n/a").
KPI_GRID: tuple[str, ...] = (
    "runs", "relays", "models", "score",
    "risk_high_share", "success_rate", "error_rate", "latency_p50",
    "ttft_p50", "decode_tps", "billing_ratio_prompt", "billing_ratio_completion",
)
# The History trend options, in button order (at most 2 shown at once).
HISTORY_TRENDS: tuple[str, ...] = ("score", "grade", "latency_p50", "ttft_p50", "decode_tps", "error_rate")
MAX_TRENDS = 2


def get(mid: str) -> Metric:
    """The :class:`Metric` of an id: a registry metric, a count of
    :data:`COUNTS` or ``dim:<dimension>`` (a 0..100 dimension score)."""
    if mid in METRICS:
        return METRICS[mid]
    if mid in COUNTS:
        return COUNTS[mid]
    if mid.startswith(DIM_PREFIX) and DIM_KEY.match(mid[len(DIM_PREFIX):]):
        return Metric(mid, "", "score", True)
    raise KeyError(mid)


def catalogue() -> dict[str, Any]:
    """The registry as ``GET /api/metrics`` answers it: every metric (registry
    order, then the counts) with its unit, format, aggregation, surfaces,
    direction and label keys, and the named lists the pages lay out.

    ``labels`` maps every key named here to its English text: the browser
    translates a key through ``EKTE_LOCALES`` and shows this text where it
    has none (English is the key language, so its keyed strings are not in
    the page's bundle)."""
    from ekte import i18n

    every = [m.public() for m in (*METRICS.values(), *COUNTS.values())]
    keys = [k for m in every for k in (m["label_key"], m["short_label_key"], m["kpi_label_key"],
                                       m["agg_hint_key"])]
    keys += [TREND_KEYS[k] for k in (1, -1, 0)]
    return {
        "metrics": every,
        "kpi_grid": list(KPI_GRID),
        "history_trends": list(HISTORY_TRENDS),
        "max_trends": MAX_TRENDS,
        "min_runs": MIN_RUNS,
        "grades": list(scoring.GRADE_SCALE),
        "families": list(FAMILIES),
        "directions": list(DIRECTIONS),
        "trend_keys": [TREND_KEYS[k] for k in (1, -1, 0)],
        "labels": {k: i18n.keyed(k, i18n.DEFAULT) for k in dict.fromkeys(keys)},
    }


# --------------------------------------------------------------------------- #
# Grades
# --------------------------------------------------------------------------- #
def grade_value(letter: Any) -> float | None:
    """A grade letter's place on the 1..6 scale (F = 1 … A = 6), None for none."""
    if isinstance(letter, str) and letter in scoring.GRADE_SCALE:
        return float(scoring.GRADE_SCALE.index(letter) + 1)
    return None


def grade_value_sql(column: str = "h.rating") -> str:
    """:func:`grade_value` as an SQL expression over a grade-letter column."""
    whens = " ".join(f"WHEN '{g}' THEN {i + 1}" for i, g in enumerate(scoring.GRADE_SCALE))
    return f"CASE {column} {whens} END"


def grade_letter(value: float | None) -> str | None:
    """The letter of a value on the 1..6 grade scale (an aggregate may fall
    between two grades: rounded half up)."""
    if value is None:
        return None
    scale = scoring.GRADE_SCALE
    return scale[min(max(int(value + 0.5), 1), len(scale)) - 1]


# --------------------------------------------------------------------------- #
# Display semantics
# --------------------------------------------------------------------------- #
def _grade(m: Metric, value: float | None) -> str | None:
    if value is None:
        return None
    if m.unit == "score":  # the overall score and dim:<dimension> scores
        return scoring.rating(value)
    if m.unit == "grade":
        return grade_letter(value)
    return None


def family(m: Metric, value: float | None) -> str:
    """The colour family of a value (:data:`FAMILIES`): a score or grade by its
    grade letter, latency / speed values their neutral series family, anything
    else (or no value) grey."""
    return judge(m, value)[0]


def judge(m: Metric, value: float | None) -> tuple[str, str | None]:
    """A value's colour family (:func:`family`) and grade letter (or None),
    worked out once."""
    if value is None:
        return "grey", None
    letter = _grade(m, value)
    if letter is not None:
        return GRADE_FAMILY.get(letter, "grey"), letter
    return _UNIT_FAMILY.get(m.unit, "grey"), None


def judge_of(m: Metric) -> Callable[[Any], tuple[str, str | None]]:
    """``judge(m, _number(value))`` as a function of the value, for the many
    cells of one metric: what depends only on ``m`` is worked out once (a
    metric of no grade has one family for every number)."""
    if m.unit in ("score", "grade"):
        return lambda value: judge(m, _number(value))
    grey: tuple[str, str | None] = ("grey", None)
    unit: tuple[str, str | None] = (_UNIT_FAMILY.get(m.unit, "grey"), None)
    return lambda value: grey if value is None or _number(value) is None else unit


def direction(m: Metric, delta: float | None, previous_n: int | None = None) -> str:
    """Whether a change is ``better``, ``worse`` or ``neutral`` (no change, or
    a metric without a better side); ``none`` without a delta or when the
    previous value rests on fewer than :data:`MIN_RUNS` runs (indicative only).
    Counts (unit ``count``) are exact and always judged."""
    if delta is None:
        return "none"
    if m.unit != "count" and previous_n is not None and previous_n < MIN_RUNS:
        return "none"
    if delta == 0 or m.higher_is_better is None:
        return "neutral"
    return "better" if (delta > 0) == m.higher_is_better else "worse"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def present(metric: str | Metric, value: Any, previous: Any = None, n: int | None = None,
            previous_n: int | None = None, *, surface: str | None = None) -> dict[str, Any]:
    """How a value of ``metric`` shows, decided here rather than in the page.

    ``previous`` is the value it is compared with (the previous period, or the
    first point of a trend), ``n`` / ``previous_n`` the runs each rests on, and
    ``surface`` the selected surface. Returns ``value``, ``family``
    (:data:`FAMILIES`), ``grade`` (a letter for scores and grades, else None),
    ``delta`` (value − previous), ``direction`` (:func:`direction`),
    ``trend_key`` (``trend.rising`` / ``trend.falling`` / ``trend.unchanged``,
    None without a delta), ``low_n`` (``n`` below :data:`MIN_RUNS`) and
    ``applies`` (False when the metric is not measured on ``surface``: the
    "n/a" tiles; the values are then dropped).
    """
    m = metric if isinstance(metric, Metric) else get(metric)
    applies = surface is None or m.applies(surface)
    v = _number(value) if applies else None
    p = _number(previous) if applies else None
    delta = v - p if v is not None and p is not None else None
    return {
        "value": v,
        "family": family(m, v),
        "grade": _grade(m, v),
        "delta": delta,
        "direction": direction(m, delta, previous_n),
        "trend_key": None if delta is None else TREND_KEYS[(delta > 0) - (delta < 0)],
        "low_n": applies and n is not None and m.agg != "count" and n < MIN_RUNS,
        "applies": applies,
    }

