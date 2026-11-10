"""Shared building blocks of the Analytics and History widgets.

The widgets themselves are :mod:`ekte.web.analytics_widgets` (Analytics) and
:mod:`ekte.web.history_api` (History), both on the query core
:mod:`ekte.web.query`, which filters, groups and aggregates in SQL. This
module keeps what they share and what has no SQL of its own:

* the constants of the URL schema (groupings, buckets, blocks, folds, limits)
  and :class:`AnalyticsError` (a parameter answered with 400);
* :func:`metric`: a public metric id (``dim:<key>`` included) to its
  :class:`~ekte.web.metrics.Metric` of the registry (:mod:`ekte.web.metrics`);
* :class:`RelayResolver`: a run's base URL to its knowledge-base provider or
  relay entry (the source of the materialised ``relay_map``,
  :mod:`ekte.web.relay_map`);
* :func:`percentile` (Hyndman & Fan type 7, as the SQL fallback aggregates)
  and :func:`_bucket` (a UTC time's bucket in the viewer's time zone: the
  keys the SQL buckets reproduce, and the annotations' buckets).

* **Relays** are grouped by knowledge-base entry: a run's normalized base URL
  that is one of the base URLs of a provider or of a relay the user saved
  belongs to that entry (key = the provider key, label = its display name,
  ``in_kb`` true), so renaming or adding a relay re-groups the whole history
  at once. Any other URL is a group of its own, keyed and labelled by the URL,
  ``in_kb`` false. Models are grouped by ``claimed_model``.
* **Buckets** follow the viewer's time zone: ``hour``, ``day``, ``week`` (ISO
  weeks, starting Monday) and ``dow_hour`` (weekday x time of day; with
  ``block`` = 2, 3, 4 or 6 the day is cut into blocks of that many hours).
  With ``fold`` the weekday grid repeats per week of a longer cycle:
  ``4weeks`` (weeks 1-4 of a 4-week cycle counted from Monday 1970-01-05) or
  ``month_week`` (days 1-7, 8-14, 15-21, 22-28 and 29-31 of the month); a fold
  needs the runs to cover :data:`FOLD_MIN_DAYS` calendar days.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

from ekte.config import SURFACES
from ekte.knowledge.relays import normalize_url
from ekte.web.metrics import DIM_KEY
from ekte.web.metrics import DIM_PREFIX as DIM_PREFIX
from ekte.web.metrics import METRICS as METRICS
from ekte.web.metrics import MIN_RUNS as MIN_RUNS
from ekte.web.metrics import Metric as Metric

# Series per chart.
MAX_KEYS = 4
# Longest accepted filter value (relay keys are URLs).
MAX_PARAM = 500

GROUPS = ("relay", "model", "relay_model", "all")
BUCKETS = ("hour", "day", "week", "dow_hour")
# hours per row of the dow_hour grid: the divisors of 24, so blocks are equal
BLOCKS = (1, 2, 3, 4, 6)
# how the dow_hour grid folds the period: one week, a 4-week cycle, the weeks
# of a month; the longer folds need runs on this many calendar days
FOLDS = ("week", "4weeks", "month_week")
FOLD_MIN_DAYS = {"4weeks": 90, "month_week": 180}
# week 1 of every 4-week cycle starts on a multiple of 4 weeks after this Monday
CYCLE_EPOCH = date(1970, 1, 5)
# Group key of runs without a usable base URL (a provider key or URL never
# contains parentheses).
UNKNOWN_RELAY = "(unknown)"
# The one series key of group=all (every run that matches the filters).
ALL_KEY = "(all)"


class AnalyticsError(ValueError):
    """A request parameter that cannot be used (answered with 400)."""


def metric(mid: str, surface: str | None = None) -> Metric:
    """The :class:`Metric` of a public id (``dim:<key>`` included); with
    ``surface`` it must apply to that surface."""
    mid = (mid or "").strip()
    if mid in METRICS:
        m = METRICS[mid]
        if surface is not None and not m.applies(surface):
            raise AnalyticsError(f"metric {mid!r} does not apply to the {surface} surface")
        return m
    if mid.startswith(DIM_PREFIX) and DIM_KEY.match(mid[len(DIM_PREFIX):]):
        return Metric(mid, "", "score", True)
    raise AnalyticsError(f"unknown metric {mid[:80]!r}; one of {', '.join(METRICS)} or dim:<dimension>")


def metrics_for(surface: str) -> list[Metric]:
    """The metrics that apply to ``surface``, in whitelist order."""
    return [m for m in METRICS.values() if m.applies(surface)]


def percentile(ordered: list[float], q: float) -> float | None:
    """The ``q`` quantile (0..1) of sorted values, linear interpolation between
    closest ranks (Hyndman & Fan type 7). None for no values."""
    if not ordered:
        return None
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    in_kb: bool
    kind: str  # relay (saved by the user, or a provider without models) | provider | url

    def public(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "in_kb": self.in_kb, "kind": self.kind}


class RelayResolver:
    """Maps a run's base URL to its knowledge-base provider or relay entry.

    Built once per request from the current knowledge base (the complete set,
    so a switched-off entry still names its runs); never cached across
    requests, so a renamed or newly saved relay applies at once. A URL listed
    by several entries goes to a relay the user saved first, then to the
    provider with the smallest key.
    """

    def __init__(self, knowledge: Any | None = None) -> None:
        from ekte.knowledge.relays import load_for_grouping, relay_entries

        if knowledge is None:
            knowledge = load_for_grouping()
        self._by_url: dict[str, Group] = {}
        self._cache: dict[str | None, Group] = {}
        for entry in relay_entries(knowledge):
            group = Group(entry.key, entry.label, True, entry.kind)
            for url in entry.urls:
                self._by_url.setdefault(url, group)

    def resolve(self, run: Mapping[str, Any]) -> Group:
        url = run.get("base_url_norm")
        if not url:
            raw = run.get("base_url")
            url = (normalize_url(raw) or raw.strip() or None) if isinstance(raw, str) else None
        group = self._cache.get(url)
        if group is None:
            if url is None:
                group = Group(UNKNOWN_RELAY, UNKNOWN_RELAY, False, "url")
            else:
                group = self._by_url.get(url) or Group(url, url, False, "url")
            self._cache[url] = group
        return group


def _most_common(counts: Mapping[str, int]) -> str:
    """The surface with the most runs (ties: in :data:`SURFACES` order; chat
    when there are none)."""
    ranked = sorted((s for s in counts if counts[s]), key=lambda s: (
        -counts[s], SURFACES.index(s) if s in SURFACES else len(SURFACES), s))
    return ranked[0] if ranked else "chat"


# Run times outside this range cannot be shifted into every time zone (a
# damaged report's year 1 or 9999): such runs count as undated.
_T_MIN = datetime(1970, 1, 1, tzinfo=UTC)
_T_MAX = datetime(9999, 1, 1, tzinfo=UTC)


def _fold_week(day: date, fold: str) -> int:
    """Week (0-based) of the fold a local day falls in: 0 for ``week``."""
    if fold == "4weeks":
        return (day - CYCLE_EPOCH).days // 7 % 4
    if fold == "month_week":
        return min(4, (day.day - 1) // 7)
    return 0


def _bucket(dt: datetime, zone: tzinfo, size: str, block: int = 1,
            fold: str = "week") -> tuple[float, str, dict[str, Any]]:
    """Sort position, key and extra fields of the bucket a UTC time falls in
    (``block``: hours per ``dow_hour`` row; ``hour`` is the block's start;
    ``fold``: see :data:`FOLDS`)."""
    local = dt.astimezone(zone)
    if size == "dow_hour":
        dow, hour = local.isoweekday(), local.hour - local.hour % block
        extra: dict[str, Any] = {"dow": dow, "hour": hour}
        if block > 1:
            extra["hours"] = block
        if fold == "week":
            return float(dow * 24 + hour), f"{dow}-{hour:02d}", extra
        week = _fold_week(local.date(), fold)
        extra["week"] = week + 1
        return float(week * 168 + dow * 24 + hour), f"{week + 1}.{dow}-{hour:02d}", extra
    if size == "hour":
        # fold tells the two 01:00-01:59 hours of a DST fall-back apart
        start = datetime(local.year, local.month, local.day, local.hour, tzinfo=zone, fold=local.fold)
    else:
        day = local.date()
        if size == "week":
            day -= timedelta(days=day.weekday())
        start = datetime(day.year, day.month, day.day, tzinfo=zone)
    iso = start.isoformat()
    return start.timestamp(), iso, {}


# Breakdown metrics per request (/api/analytics/breakdown).
MAX_METRICS = 8

# Detectors whose status says whether the relay serves the model it claims,
# whole and with its features (columns of the matrix, in this order).
INTEGRITY_CHECKS = (
    "model_identity", "capability", "vision", "streaming", "protocol_request",
    "protocol_response", "integrity", "injected_prompt", "connectivity",
    # the embedding surface
    "embed.identity", "embed.drift", "embed.determinism", "embed.distinctness",
    "embed.connectivity",
    # the rerank surface
    "rerank.connectivity", "rerank.known_answer", "rerank.identity", "rerank.determinism",
    "rerank.drift", "performance.rerank",
)
JUDGED = ("pass", "warn", "fail")
