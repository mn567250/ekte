"""Analytics queries over the run history: summary KPIs, time series, leaderboards.

The read side of the analytics tables :mod:`zing.web.analytics_store` defines;
``zing serve`` answers ``/api/analytics/*`` with the functions at the bottom
(:func:`options`, :func:`summary`, :func:`series`, :func:`leaderboard`,
:func:`breakdown`, :func:`errors`, :func:`integrity`). Python over
:func:`zing.web.history.analytics_runs`: no SQL is built from request input,
no ``report_json`` is parsed, and every statistic is computed here — except
the request counts of :func:`errors`, which SQLite sums per run, minute and
outcome class (:func:`zing.web.history.analytics_request_classes`), so no
request row is loaded.

* **Relays** are grouped by knowledge-base entry, resolved when the query runs
  (:class:`RelayResolver`): a run's normalized base URL that is one of the base
  URLs of a provider or of a relay the user saved belongs to that entry (key =
  the provider key, label = its display name, ``in_kb`` true), so renaming or
  adding a relay re-groups the whole history at once. Any other URL is a group
  of its own, keyed and labelled by the URL, ``in_kb`` false. Models are
  grouped by ``claimed_model``.
* **Run time** is ``started_at`` (estimated for older reports, see
  :mod:`zing.web.analytics_store`). ``from`` is inclusive, ``to`` exclusive.
* **Missing values** stay missing: a run that did not measure a metric does not
  count towards it (never as 0); ``n`` says how many runs had a value and
  ``coverage`` = ``n`` / runs.
* **Percentiles** (``median``, ``p25``, ``p75``) use linear interpolation
  between closest ranks (:func:`percentile`; Hyndman & Fan type 7, the default
  of numpy and spreadsheets). Metrics with ``agg = "share"`` are yes/no per run
  (``risk_high_share``, ``model_mismatch_rate``): their ``value`` is the share
  of runs with "yes", and they have no percentiles.
* **Buckets** follow the viewer's time zone (``tz``: IANA name, else
  ``tz_offset``: minutes east of UTC, else UTC): ``hour``, ``day``, ``week``
  (ISO weeks, starting Monday) and ``dow_hour`` (weekday x hour of day, a 7 x 24
  heatmap). Only buckets with data are returned. A bucket with fewer than
  :data:`MIN_RUNS` runs is flagged ``low_n``: a single audit can be an outlier.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from zing.knowledge.relays import normalize_url
from zing.web import analytics_store, history

# A bucket (or leaderboard cell) with fewer runs than this is flagged low_n.
MIN_RUNS = 3
# Series per chart.
MAX_KEYS = 4
# Longest accepted filter value (relay keys are URLs).
MAX_PARAM = 500

GROUPS = ("relay", "model", "relay_model", "all")
BUCKETS = ("hour", "day", "week", "dow_hour")
SOURCES = ("all", "manual", "monitor")
# Group key of runs without a usable base URL (a provider key or URL never
# contains parentheses).
UNKNOWN_RELAY = "(unknown)"
# The one series key of group=all (every run that matches the filters).
ALL_KEY = "(all)"


class AnalyticsError(ValueError):
    """A request parameter that cannot be used (answered with 400)."""


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Metric:
    """A public metric id and where its per-run value comes from."""

    id: str
    column: str  # history / history_metrics column ("" for derived values)
    unit: str  # score | ratio | ms | tok/s | tokens | count | s
    higher_is_better: bool | None  # None: neither (e.g. billing ratio, ideal 1.0)
    agg: str = "median"  # median | share

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "unit": self.unit, "higher_is_better": self.higher_is_better, "agg": self.agg}


def _m(mid: str, column: str, unit: str, better: bool | None, agg: str = "median") -> Metric:
    return Metric(mid, column, unit, better, agg)


# The whitelist: public id -> column. Rates and shares are 0..1 ("ratio").
METRICS: dict[str, Metric] = {m.id: m for m in (
    _m("score", "score", "score", True),
    _m("risk_high_share", "risk_level", "ratio", False, "share"),
    _m("success_rate", "success_rate", "ratio", True),
    _m("error_rate", "error_rate", "ratio", False),
    _m("timeout_rate", "timeout_rate", "ratio", False),
    _m("rate_limited_rate", "rate_limited_rate", "ratio", False),
    _m("latency_p50", "latency_p50_ms", "ms", False),
    _m("latency_p95", "latency_p95_ms", "ms", False),
    _m("ttft_p50", "ttft_p50_ms", "ms", False),
    _m("ttft_p95", "ttft_p95_ms", "ms", False),
    _m("decode_tps", "decode_tps_p50", "tok/s", True),
    _m("itl_jitter", "itl_jitter_p50_ms", "ms", False),
    _m("relay_overhead", "relay_processing_p50_ms", "ms", False),
    _m("network_rtt", "network_rtt_p50_ms", "ms", False),
    _m("cold_start", "cold_start_ms", "ms", False),
    _m("concurrency_tps", "concurrency_tps", "tok/s", True),
    _m("billing_ratio_prompt", "billing_ratio_prompt", "ratio", None),
    _m("billing_ratio_completion", "billing_ratio_completion", "ratio", None),
    _m("reasoning_share", "reasoning_share", "ratio", None),
    _m("cached_input_share", "cached_input_share", "ratio", None),
    _m("model_mismatch_rate", "model_mismatch", "ratio", False, "share"),
    _m("context_claimed", "context_claimed_tokens", "tokens", None),
    _m("context_effective", "context_effective_tokens", "tokens", True),
    _m("findings_high", "findings_high", "count", False),
    _m("findings_medium", "findings_medium", "count", False),
    _m("findings_low", "findings_low", "count", False),
    _m("duration", "duration_sec", "s", None),
)}
# Per-dimension scores: ``dim:<dimension>`` (history_dimensions, kind 'dimension').
DIM_PREFIX = "dim:"
_DIM_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

# The headline KPIs of /summary (besides the counts runs / relays / models).
SUMMARY_KPIS = (
    "score", "risk_high_share", "success_rate", "ttft_p50", "decode_tps",
    "billing_ratio_prompt", "billing_ratio_completion",
)
# The metrics of each leaderboard row.
LEADERBOARD_METRICS = (
    "score", "ttft_p50", "decode_tps", "success_rate", "billing_ratio_prompt",
    "billing_ratio_completion", "model_mismatch_rate", "risk_high_share",
)


def metric(mid: str) -> Metric:
    """The :class:`Metric` of a public id (``dim:<key>`` included)."""
    mid = (mid or "").strip()
    if mid in METRICS:
        return METRICS[mid]
    if mid.startswith(DIM_PREFIX) and _DIM_KEY.match(mid[len(DIM_PREFIX):]):
        return Metric(mid, "", "score", True)
    raise AnalyticsError(f"unknown metric {mid[:80]!r}; one of {', '.join(METRICS)} or dim:<dimension>")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def run_value(m: Metric, run: Mapping[str, Any]) -> float | None:
    """One run's value of a metric, None when the run did not measure it."""
    if m.id.startswith(DIM_PREFIX):
        return _number((run.get("_dims") or {}).get(m.id[len(DIM_PREFIX):]))
    if m.id == "risk_high_share":
        level = run.get("risk_level")
        return None if not level else 1.0 if level == "high" else 0.0
    value = _number(run.get(m.column))
    if m.agg == "share" and value is not None:
        return 1.0 if value else 0.0
    return value


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def percentile(ordered: list[float], q: float) -> float | None:
    """The ``q`` quantile (0..1) of sorted values, linear interpolation between
    closest ranks (Hyndman & Fan type 7). None for no values."""
    if not ordered:
        return None
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def aggregate(m: Metric, values: Iterable[float | None]) -> dict[str, Any]:
    """``value`` (the median, or the share for yes/no metrics), ``median``,
    ``p25``, ``p75`` and ``n`` (values present) of one metric's run values."""
    ordered = sorted(v for v in values if v is not None)
    n = len(ordered)
    if m.agg == "share":
        share = sum(ordered) / n if n else None
        return {"value": share, "median": None, "p25": None, "p75": None, "n": n}
    median = percentile(ordered, 0.5)
    return {
        "value": median, "median": median,
        "p25": percentile(ordered, 0.25), "p75": percentile(ordered, 0.75), "n": n,
    }


def _coverage(n: int, runs: int) -> float | None:
    return n / runs if runs else None


# --------------------------------------------------------------------------- #
# Relay grouping by knowledge-base entry
# --------------------------------------------------------------------------- #
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
        from zing.knowledge.relays import base_urls, is_relay

        if knowledge is None:
            try:
                from zing.knowledge import load_knowledge_base

                knowledge = load_knowledge_base(full=True, copy=False)  # only read
            except Exception:
                knowledge = None  # an unreadable knowledge base: URLs only
        self._by_url: dict[str, Group] = {}
        self._cache: dict[str | None, Group] = {}
        if knowledge is None:
            return
        ranked = []
        for key, prov in knowledge.providers.items():
            entry = knowledge.entries.get(f"provider:{key}")
            saved = bool(entry and entry.get("origin") == "relay")
            kind = "relay" if is_relay(prov, entry) else "provider"
            group = Group(key, prov.display_name or key, True, kind)
            ranked.append((not saved, key, prov, group))
        for _, _, prov, group in sorted(ranked, key=lambda r: (r[0], r[1])):
            for url in base_urls(prov):
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


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
@dataclass
class Filters:
    start: datetime | None = None
    end: datetime | None = None
    suite: str | None = None
    stream_mode: str | None = None
    api: str | None = None
    source: str = "all"
    relay: str | None = None
    model: str | None = None

    def range(self) -> dict[str, str | None]:
        return {
            "from": analytics_store.format_ts(self.start) if self.start else None,
            "to": analytics_store.format_ts(self.end) if self.end else None,
        }


def _text(params: Mapping[str, Any], name: str) -> str | None:
    value = params.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AnalyticsError(f"{name} must be a string")
    value = value.strip()
    if len(value) > MAX_PARAM:
        raise AnalyticsError(f"{name} is longer than {MAX_PARAM} characters")
    return value or None


def _choice(params: Mapping[str, Any], name: str, allowed: tuple[str, ...], default: str) -> str:
    value = _text(params, name) or default
    if value not in allowed:
        raise AnalyticsError(f"{name} must be one of {', '.join(allowed)}")
    return value


def _time(params: Mapping[str, Any], name: str) -> datetime | None:
    value = _text(params, name)
    if value is None:
        return None
    dt = analytics_store.parse_ts(value)
    if dt is None:
        raise AnalyticsError(f"{name} must be an ISO 8601 timestamp (naive ones are UTC)")
    return dt


def parse_filters(params: Mapping[str, Any]) -> Filters:
    """The filters every endpoint takes: from, to, suite, stream_mode, api,
    source (all|manual|monitor), relay (a group key), model (claimed model)."""
    f = Filters(
        start=_time(params, "from"),
        end=_time(params, "to"),
        suite=_text(params, "suite"),
        stream_mode=_text(params, "stream_mode"),
        api=_text(params, "api"),
        source=_choice(params, "source", SOURCES, "all"),
        relay=_text(params, "relay"),
        model=_text(params, "model"),
    )
    if f.start and f.end and f.start >= f.end:
        raise AnalyticsError("from must be before to")
    return f


def parse_tz(params: Mapping[str, Any]) -> tuple[tzinfo, str]:
    """The viewer's time zone and its name: ``tz`` (an IANA name), else
    ``tz_offset`` (minutes east of UTC, i.e. JavaScript's
    ``-Date.prototype.getTimezoneOffset()``), else UTC."""
    name = _text(params, "tz")
    offset = _text(params, "tz_offset")
    if name is not None:
        try:
            if len(name) > 64:
                raise ValueError(name)
            return ZoneInfo(name), name
        except Exception:
            if offset is None:
                raise AnalyticsError(f"unknown time zone {name[:64]!r}") from None
    if offset is not None:
        try:
            minutes = int(offset)
        except ValueError:
            raise AnalyticsError("tz_offset must be whole minutes east of UTC") from None
        if not -840 <= minutes <= 840:
            raise AnalyticsError("tz_offset must be between -840 and 840 minutes")
        zone = timezone(timedelta(minutes=minutes))
        return zone, "UTC" if minutes == 0 else str(zone)
    return timezone.utc, "UTC"


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
# Run times outside this range cannot be shifted into every time zone (a
# damaged report's year 1 or 9999): such runs count as undated.
_T_MIN = datetime(1970, 1, 1, tzinfo=timezone.utc)
_T_MAX = datetime(9999, 1, 1, tzinfo=timezone.utc)


def _prepare(runs: list[dict[str, Any]], resolver: RelayResolver) -> list[dict[str, Any]]:
    for run in runs:
        t = analytics_store.parse_ts(run.get("started_at"))
        run["_t"] = t if t is not None and _T_MIN <= t < _T_MAX else None
        run["_group"] = resolver.resolve(run)
    return runs


def _matches(run: Mapping[str, Any], f: Filters) -> bool:
    if f.source == "manual" and run.get("watch_id") is not None:
        return False
    if f.source == "monitor" and run.get("watch_id") is None:
        return False
    return (
        (f.suite is None or run.get("suite") == f.suite)
        and (f.stream_mode is None or run.get("stream_mode") == f.stream_mode)
        and (f.api is None or run.get("api") == f.api)
        and (f.model is None or run.get("claimed_model") == f.model)
        and (f.relay is None or run["_group"].key == f.relay)
    )


def _load(
    f: Filters, start: datetime | None = None, resolver: RelayResolver | None = None
) -> list[dict[str, Any]]:
    """The runs from ``start`` (default: the filter's ``from``) to ``to``,
    filtered, with their relay group (``_group``) and start time (``_t``)."""
    start = start or f.start
    runs = history.analytics_runs(
        analytics_store.format_ts(start) if start else None,
        analytics_store.format_ts(f.end) if f.end else None,
    )
    return [r for r in _prepare(runs, resolver or RelayResolver()) if _matches(r, f)]


def _attach_dims(runs: list[dict[str, Any]]) -> None:
    by_run: dict[int, dict[str, Any]] = {}
    for row in history.analytics_dimensions([r["id"] for r in runs], kind="dimension"):
        by_run.setdefault(int(row["history_id"]), {})[row["key"]] = row["score"]
    for run in runs:
        run["_dims"] = by_run.get(int(run["id"]), {})


def _group_of(group: str) -> Callable[[Mapping[str, Any]], tuple[str, dict[str, Any]]]:
    """The series key and its public description for a run, by ``group``."""
    def relay(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        g: Group = run["_group"]
        return g.key, g.public()

    def model(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        name = run.get("claimed_model") or UNKNOWN_RELAY
        return name, {"key": name, "label": name, "in_kb": run.get("kb_model_id") is not None,
                      "kind": "model"}

    def both(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        g: Group = run["_group"]
        name = run.get("claimed_model") or UNKNOWN_RELAY
        key = f"{g.key}|{name}"
        return key, {"key": key, "label": f"{g.label} · {name}", "in_kb": g.in_kb,
                     "kind": "relay_model", "relay": g.key, "model": name}

    def everything(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        return ALL_KEY, {"key": ALL_KEY, "label": ALL_KEY, "in_kb": False, "kind": "all"}

    return {"relay": relay, "model": model, "relay_model": both, "all": everything}[group]


def _grouped(
    runs: list[dict[str, Any]], group: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Runs by series key (in run order) and each key's public description."""
    key_of = _group_of(group)
    by_key: dict[str, list[dict[str, Any]]] = {}
    info: dict[str, dict[str, Any]] = {}
    for run in runs:
        key, desc = key_of(run)
        by_key.setdefault(key, []).append(run)
        if key not in info:
            info[key] = desc
        elif group == "model" and desc["in_kb"]:
            info[key]["in_kb"] = True  # resolved in the knowledge base by any of its runs
    return by_key, info


def _metric_cell(m: Metric, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """``value`` and ``n`` of one metric over some runs (leaderboard / summary)."""
    agg = aggregate(m, (run_value(m, r) for r in runs))
    return {"value": agg["value"], "n": agg["n"], "coverage": _coverage(agg["n"], len(runs))}


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
def options(params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The filter values present in the data (optionally within from / to)."""
    params = params or {}
    f = Filters(start=_time(params, "from"), end=_time(params, "to"))
    if f.start and f.end and f.start >= f.end:
        raise AnalyticsError("from must be before to")
    runs = _load(f)
    relays: dict[str, dict[str, Any]] = {}
    pairs: dict[str, dict[str, Any]] = {}
    pair_of = _group_of("relay_model")
    for run in runs:
        g: Group = run["_group"]
        relays.setdefault(g.key, {**g.public(), "runs": 0})["runs"] += 1
        key, desc = pair_of(run)
        pairs.setdefault(key, {**desc, "runs": 0})["runs"] += 1

    def counted(column: str) -> list[dict[str, Any]]:
        counts = Counter(r.get(column) for r in runs if r.get(column))
        return [{"value": v, "runs": n} for v, n in sorted(counts.items(), key=lambda i: (-i[1], i[0]))]

    times = [r["started_at"] for r in runs if r.get("started_at")]
    dims = sorted({row["key"] for row in history.analytics_dimensions([r["id"] for r in runs], "dimension")})
    monitor = sum(1 for r in runs if r.get("watch_id") is not None)
    return {
        "runs": len(runs),
        "manual": len(runs) - monitor,
        "monitor": monitor,
        "first": min(times) if times else None,
        "last": max(times) if times else None,
        "relays": sorted(relays.values(), key=lambda g: (-g["runs"], g["label"].lower(), g["key"])),
        "models": [{"key": item["value"], "runs": item["runs"]} for item in counted("claimed_model")],
        # the series keys of group=relay_model that have runs (for a series picker)
        "relay_models": sorted(pairs.values(), key=lambda p: (-p["runs"], p["label"].lower(), p["key"])),
        "suites": counted("suite"),
        "stream_modes": counted("stream_mode"),
        "apis": counted("api"),
        "metrics": [m.public() for m in METRICS.values()],
        "dimensions": dims,
        "min_runs": MIN_RUNS,
    }


def _kpis(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    n = len(runs)
    full = {"n": n, "coverage": 1.0 if n else None}
    out: dict[str, dict[str, Any]] = {
        "runs": {"value": n, **full, "unit": "count", "higher_is_better": None},
        "relays": {"value": len({r["_group"].key for r in runs}), **full, "unit": "count",
                   "higher_is_better": None},
        "models": {"value": len({r.get("claimed_model") for r in runs if r.get("claimed_model")}),
                   **full, "unit": "count", "higher_is_better": None},
    }
    for mid in SUMMARY_KPIS:
        m = METRICS[mid]
        out[mid] = {**_metric_cell(m, runs), "unit": m.unit, "higher_is_better": m.higher_is_better}
    return out


def summary(params: Mapping[str, Any]) -> dict[str, Any]:
    """KPIs for the range and for the previous range of the same length.

    Without ``from`` the whole history is summarized and there is no previous
    range; ``from`` without ``to`` runs up to now.
    """
    f = parse_filters(params)
    previous: tuple[datetime, datetime] | None = None
    if f.start is not None:
        if f.end is None:
            f.end = datetime.now(timezone.utc)
            if f.start >= f.end:
                raise AnalyticsError("from must be before to")
        try:
            previous = (f.start - (f.end - f.start), f.start)
        except OverflowError:
            previous = None
    runs = _load(f, previous[0] if previous else None)
    # started_at is stored fixed-width, so the strings compare like times
    split = analytics_store.format_ts(f.start) if f.start else None
    current = [r for r in runs if split is None or (r.get("started_at") or "") >= split]
    before = [r for r in runs if split is not None and (r.get("started_at") or "") < split]
    now, then = _kpis(current), _kpis(before) if previous else None
    for key, cell in now.items():
        prev = then[key]["value"] if then else None
        cell["previous"] = prev
        cell["previous_n"] = then[key]["n"] if then else None
        cell["delta"] = cell["value"] - prev if cell["value"] is not None and prev is not None else None
    return {
        **f.range(),
        "previous": (
            {"from": analytics_store.format_ts(previous[0]), "to": analytics_store.format_ts(previous[1])}
            if previous else None
        ),
        "runs": len(current),
        "kpis": now,
        "min_runs": MIN_RUNS,
    }


def _bucket(dt: datetime, zone: tzinfo, size: str) -> tuple[float, str, dict[str, Any]]:
    """Sort position, key and extra fields of the bucket a UTC time falls in."""
    local = dt.astimezone(zone)
    if size == "dow_hour":
        dow = local.isoweekday()
        return float(dow * 24 + local.hour), f"{dow}-{local.hour:02d}", {"dow": dow, "hour": local.hour}
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


def series(params: Mapping[str, Any], keys: Iterable[str] = ()) -> dict[str, Any]:
    """One metric over time per group (``keys``: up to :data:`MAX_KEYS` series
    keys; default the groups with the most runs)."""
    f = parse_filters(params)
    m = metric(_text(params, "metric") or "score")
    group = _choice(params, "group", GROUPS, "relay")
    size = _choice(params, "bucket", BUCKETS, "day")
    zone, zone_name = parse_tz(params)
    wanted = []
    for key in keys:
        key = (key or "").strip()
        if len(key) > MAX_PARAM:
            raise AnalyticsError(f"keys must be at most {MAX_PARAM} characters each")
        if key and key not in wanted:
            wanted.append(key)
    if len(wanted) > MAX_KEYS:
        raise AnalyticsError(f"at most {MAX_KEYS} keys")

    runs = [r for r in _load(f) if r["_t"] is not None]
    if m.id.startswith(DIM_PREFIX):
        _attach_dims(runs)
    by_key, info = _grouped(runs, group)
    if not wanted:
        wanted = sorted(by_key, key=lambda k: (-len(by_key[k]), info[k]["label"].lower(), k))[:MAX_KEYS]

    out = []
    for key in wanted:
        members = by_key.get(key, [])
        buckets: dict[str, tuple[float, dict[str, Any], list[float | None]]] = {}
        for run in members:
            pos, bkey, extra = _bucket(run["_t"], zone, size)
            buckets.setdefault(bkey, (pos, extra, []))[2].append(run_value(m, run))
        points = []
        for bkey, (_, extra, values) in sorted(buckets.items(), key=lambda i: i[1][0]):
            agg = aggregate(m, values)
            if not agg["n"]:
                continue
            points.append({"bucket": bkey, **extra, "runs": len(values), **agg,
                           "low_n": agg["n"] < MIN_RUNS})
        n = sum(1 for r in members if run_value(m, r) is not None)
        out.append({
            **(info.get(key) or {"key": key, "label": key, "in_kb": False, "kind": group}),
            "runs": len(members),
            "n": n,
            "coverage": _coverage(n, len(members)),
            "points": points,
            "annotations": [] if size == "dow_hour" else _annotations(members, zone, size),
            "mixed": {
                col: len({r.get(col) for r in members if r.get(col)}) > 1
                for col in ("suite", "stream_mode", "api")
            },
        })
    return {
        **f.range(),
        "metric": m.public(),
        "group": group,
        "bucket": size,
        "tz": zone_name,
        "min_runs": MIN_RUNS,
        "series": out,
    }


def _annotations(runs: list[dict[str, Any]], zone: tzinfo, size: str) -> list[dict[str, Any]]:
    """Where the zing version or the knowledge-base profile changes, run by run
    (unknown values are skipped, not counted as a change)."""
    out = []
    for kind, column in (("tool_version", "tool_version"), ("kb_profile", "kb_profile_hash")):
        last = None
        for run in runs:
            value = run.get(column)
            if not value:
                continue
            if last is not None and value != last:
                out.append({
                    "bucket": _bucket(run["_t"], zone, size)[1], "kind": kind,
                    "from": last, "to": value, "run_id": run["id"], "started_at": run["started_at"],
                })
            last = value
    out.sort(key=lambda a: (a["started_at"], a["kind"]))
    return out


def leaderboard(params: Mapping[str, Any]) -> dict[str, Any]:
    """One row per relay for a ``model``, or one row per model for a ``relay``."""
    f = parse_filters(params)
    if (f.model is None) == (f.relay is None):
        raise AnalyticsError("give either model or relay")
    by = "relay" if f.model is not None else "model"
    groups, info = _grouped(_load(f), by)
    rows = []
    for key, members in groups.items():
        times = [r["started_at"] for r in members if r.get("started_at")]
        rows.append({
            **info[key],
            "runs": len(members),
            "low_n": len(members) < MIN_RUNS,
            "last_run": max(times) if times else None,
            "metrics": {mid: _metric_cell(METRICS[mid], members) for mid in LEADERBOARD_METRICS},
        })

    def rank(row: dict[str, Any]) -> tuple[Any, ...]:
        score = row["metrics"]["score"]["value"]
        return (score is None, -(score or 0.0), -row["runs"], row["label"].lower(), row["key"])

    rows.sort(key=rank)
    return {
        **f.range(),
        "by": by,
        "model": f.model,
        "relay": f.relay,
        "metrics": [METRICS[mid].public() for mid in LEADERBOARD_METRICS],
        "min_runs": MIN_RUNS,
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# Per-group breakdown (billing, relay overhead)
# --------------------------------------------------------------------------- #
# Metrics per breakdown request.
MAX_METRICS = 8


def breakdown(params: Mapping[str, Any], metrics: Iterable[str]) -> dict[str, Any]:
    """Some metrics (``metrics``: 1 to :data:`MAX_METRICS` ids) over the whole
    range, one row per group (``group``: relay, model, relay_model or all),
    busiest group first."""
    f = parse_filters(params)
    group = _choice(params, "group", GROUPS, "relay")
    wanted: list[Metric] = []
    for mid in metrics:
        if not (mid or "").strip():
            continue
        m = metric(mid)
        if m not in wanted:
            wanted.append(m)
    if not wanted:
        raise AnalyticsError("give at least one metric")
    if len(wanted) > MAX_METRICS:
        raise AnalyticsError(f"at most {MAX_METRICS} metrics")
    runs = _load(f)
    if any(m.id.startswith(DIM_PREFIX) for m in wanted):
        _attach_dims(runs)
    by_key, info = _grouped(runs, group)
    rows = []
    for key, members in by_key.items():
        cells = {}
        for m in wanted:
            agg = aggregate(m, (run_value(m, r) for r in members))
            cells[m.id] = {**agg, "coverage": _coverage(agg["n"], len(members)), "low_n": agg["n"] < MIN_RUNS}
        rows.append({**info[key], "runs": len(members), "low_n": len(members) < MIN_RUNS, "metrics": cells})
    rows.sort(key=lambda r: (-r["runs"], r["label"].lower(), r["key"]))
    return {
        **f.range(),
        "group": group,
        "metrics": [m.public() for m in wanted],
        "runs": len(runs),
        "min_runs": MIN_RUNS,
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# Errors and reliability (request records)
# --------------------------------------------------------------------------- #
REQUEST_CLASSES = history.REQUEST_CLASSES
ERROR_GROUPS = ("relay", "model")


def _class_counts() -> dict[str, int]:
    return dict.fromkeys(REQUEST_CLASSES, 0)


def _request_shares(counts: Mapping[str, int]) -> dict[str, Any]:
    """Requests, failed ones, and the shares of all requests (pooled over the
    calls, not a median of runs) that failed, hit a rate limit or timed out."""
    total = sum(counts.values())
    errors = total - counts["success"]

    def share(n: int) -> float | None:
        return n / total if total else None

    return {
        "requests": total,
        "errors": errors,
        "error_share": share(errors),
        "rate_limited_share": share(counts["rate_limited"]),
        "timeout_share": share(counts["timeout"]),
        "server_share": share(counts["server_5xx"]),
    }


def errors(params: Mapping[str, Any]) -> dict[str, Any]:
    """Outcomes of the target's completion calls by class: per group
    (``group``: relay or model) and per time bucket (``bucket``, in the
    viewer's time zone; a call's time is its run's start plus its offset, to
    the minute). Counted in SQL; runs without stored request records (older
    history) add nothing and show in ``covered`` < ``runs``."""
    f = parse_filters(params)
    group = _choice(params, "group", ERROR_GROUPS, "relay")
    size = _choice(params, "bucket", BUCKETS, "day")
    zone, zone_name = parse_tz(params)
    runs = _load(f)
    by_id = {int(r["id"]): r for r in runs}
    key_of = _group_of(group)

    groups: dict[str, dict[str, Any]] = {}
    for run in runs:
        key, desc = key_of(run)
        g = groups.setdefault(key, {**desc, "runs": 0, "_covered": set(), "counts": _class_counts()})
        g["runs"] += 1
        if group == "model" and desc["in_kb"]:
            g["in_kb"] = True
    totals = _class_counts()
    covered: set[int] = set()
    buckets: dict[str, dict[str, Any]] = {}
    for row in history.analytics_request_classes(by_id):
        rid, cls, n = int(row["history_id"]), row["cls"], int(row["n"])
        found = by_id.get(rid)
        if found is None or cls not in totals:
            continue
        run = found
        covered.add(rid)
        totals[cls] += n
        g = groups[key_of(run)[0]]
        g["_covered"].add(rid)
        g["counts"][cls] += n
        if run["_t"] is None:
            continue  # counted, but not placed in time
        try:
            t = run["_t"] + timedelta(minutes=int(row["minute"] or 0))
        except OverflowError:
            continue
        if not _T_MIN <= t < _T_MAX:
            continue
        pos, bkey, extra = _bucket(t, zone, size)
        b = buckets.setdefault(bkey, {"_pos": pos, "bucket": bkey, **extra, "_runs": set(),
                                      "counts": _class_counts()})
        b["_runs"].add(rid)
        b["counts"][cls] += n

    out_groups = []
    for g in groups.values():
        cov = g.pop("_covered")
        out_groups.append({**g, "covered": len(cov), "coverage": _coverage(len(cov), g["runs"]),
                           "low_n": len(cov) < MIN_RUNS, **_request_shares(g["counts"])})
    out_groups.sort(key=lambda g: (-g["requests"], -g["runs"], g["label"].lower(), g["key"]))
    out_buckets = []
    for b in sorted(buckets.values(), key=lambda b: b["_pos"]):
        ids = b.pop("_runs")
        b.pop("_pos")
        out_buckets.append({**b, "runs": len(ids), "low_n": len(ids) < MIN_RUNS, **_request_shares(b["counts"])})
    return {
        **f.range(),
        "group": group,
        "bucket": size,
        "tz": zone_name,
        "min_runs": MIN_RUNS,
        "classes": list(REQUEST_CLASSES),
        "runs": len(runs),
        "covered": len(covered),
        "coverage": _coverage(len(covered), len(runs)),
        "totals": {"counts": totals, **_request_shares(totals)},
        "groups": out_groups,
        "buckets": out_buckets,
    }


# --------------------------------------------------------------------------- #
# Model integrity (identity, context window, capability detectors)
# --------------------------------------------------------------------------- #
# Detectors whose status says whether the relay serves the model it claims,
# whole and with its features (columns of the matrix, in this order).
INTEGRITY_CHECKS = (
    "model_identity", "capability", "vision", "streaming", "protocol_request",
    "protocol_response", "integrity", "injected_prompt", "connectivity",
)
JUDGED = ("pass", "warn", "fail")


def integrity(params: Mapping[str, Any]) -> dict[str, Any]:
    """One row per relay x model: the status counts of each integrity check
    (pass / warn / fail; ``other`` = inconclusive, not run, error, info, which
    do not count towards ``n`` or ``pass_rate``), the model-mismatch share and
    the effective context window as a share of the declared one (median over
    the runs that measured both)."""
    f = parse_filters(params)
    runs = _load(f)
    statuses: dict[int, dict[str, str | None]] = {}
    for row in history.analytics_dimensions([r["id"] for r in runs], kind="detector"):
        if row["key"] in INTEGRITY_CHECKS:
            statuses.setdefault(int(row["history_id"]), {})[row["key"]] = row["status"]
    present = {k for checks in statuses.values() for k in checks}
    checks = [c for c in INTEGRITY_CHECKS if c in present]
    by_key, info = _grouped(runs, "relay_model")
    ratio_metric = Metric("context_ratio", "", "ratio", True)
    rows = []
    for key, members in by_key.items():
        cells: dict[str, dict[str, Any]] = {}
        for check in checks:
            counts = {"pass": 0, "warn": 0, "fail": 0, "other": 0}
            for run in members:
                found = statuses.get(int(run["id"]), {})
                if check in found:  # a run without this detector does not count
                    status = found[check]
                    counts[status if status in JUDGED else "other"] += 1
            n = counts["pass"] + counts["warn"] + counts["fail"]
            cells[check] = {**counts, "n": n, "pass_rate": counts["pass"] / n if n else None,
                            "low_n": n < MIN_RUNS}
        ratios = []
        for run in members:
            claimed = _number(run.get("context_claimed_tokens"))
            effective = _number(run.get("context_effective_tokens"))
            ratios.append(effective / claimed if claimed and claimed > 0 and effective is not None else None)
        context = aggregate(ratio_metric, ratios)
        context["coverage"] = _coverage(context["n"], len(members))
        context["low_n"] = context["n"] < MIN_RUNS
        context["claimed"] = aggregate(METRICS["context_claimed"],
                                       (run_value(METRICS["context_claimed"], r) for r in members))["value"]
        context["effective"] = aggregate(METRICS["context_effective"],
                                         (run_value(METRICS["context_effective"], r) for r in members))["value"]
        mismatch = _metric_cell(METRICS["model_mismatch_rate"], members)
        mismatch["low_n"] = mismatch["n"] < MIN_RUNS
        rows.append({**info[key], "runs": len(members), "low_n": len(members) < MIN_RUNS,
                     "checks": cells, "model_mismatch": mismatch, "context": context})
    rows.sort(key=lambda r: (-r["runs"], r["label"].lower(), r["key"]))
    return {**f.range(), "min_runs": MIN_RUNS, "runs": len(runs), "checks": checks, "rows": rows}
