"""A short-range forecast of one trend series from its time buckets.

What ``GET /api/analytics/series`` adds per series with ``trend.ahead``
(:func:`ekte.web.analytics_widgets.widget_series`; response shape:
docs/dev/web-server.md). Pure functions over the buckets
:func:`ekte.web.query.series` already returned: no I/O, no SQL, a few
microseconds per series. A forecast is an estimate, not a measurement, so it
is only made from enough well-filled buckets measured the same way.

The method, on the bucket medians of a ``median`` metric (``pooled`` and
``share`` metrics have no p25 / p75 and answer ``not_median``):

1. Buckets before the series' last annotation (ekte version or
   knowledge-base profile changed) are dropped, and so are buckets with fewer
   than :data:`~ekte.web.metrics.MIN_RUNS` runs (``low_n``).
2. A step (a backend or model change, often without a mark) is looked for over
   at least :data:`STEP_MIN_BUCKETS` buckets: the best split into two flat
   levels (at least :data:`STEP_MIN_SIDE` buckets each side) must cost less
   than :data:`STEP_GAIN` times a straight line (sums of absolute residuals),
   and the jump must exceed :data:`STEP_SIGMA` robust σ of the residuals
   around the two levels. Comparing against a line, not one level, keeps a
   steady drift from passing for a step. Buckets before a step are dropped.
3. With fewer than :data:`MIN_FIT_BUCKETS` buckets left: ``few_buckets``.
   Otherwise a weighted least-squares line of the medians on the bucket index
   (weight: the bucket's runs); buckets whose residual is further than
   :data:`ODD_SIGMA` robust σ from the residuals' median are dropped once and
   the line refitted (if enough remain).
4. The slope's standard error ``se`` and the wander of bucket medians around
   the line ``s_b`` (robust σ); the trend is ``clear`` when
   ``|slope| > Z · se``; a clear trend is judged ``better`` / ``worse``
   (``direction``, :func:`ekte.web.metrics.direction`). The widths below and above the median (median − p25,
   p75 − median) get a slope each, from buckets with at least
   :data:`MIN_WIDTH_RUNS` runs (at least :data:`MIN_WIDTH_BUCKETS` of them;
   else 0).
5. The forecast starts at the last fitted bucket (its median and widths, a
   width no less than a quarter of the median width), so it joins the history
   without a gap, and goes on ``slope`` per bucket. Its band is the projected
   p25–p75, widened by ``k = √(1 + (Z·σf / σ)²)`` with ``σ`` the run spread
   ((wl + wu) / 1.349) and ``σf = √((se·Δ)² + s_b²·Δ)``: ``k`` is 1 at the
   start and grows the further ahead it reaches.

Robust σ is 1.4826 × the median absolute deviation. A score stays within
0..100, and a metric whose history never went below 0 is not forecast below 0.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from ekte.web import analytics, metrics
from ekte.web.analytics import Metric
from ekte.web.query import Point

# buckets with >= MIN_RUNS runs needed after the cut
MIN_FIT_BUCKETS = 6
# a bucket's p25 / p75 is used for the width fit only from this many runs
MIN_WIDTH_RUNS = 5
# fewer such buckets: the widths stay constant (slope 0)
MIN_WIDTH_BUCKETS = 4
# a bucket further than this many robust σ off the line is dropped once
ODD_SIGMA = 3.0
# 80 %: the "clear trend" test and the widening
Z = 1.2816
# step detection needs this many buckets, this many on each side of a step
STEP_MIN_BUCKETS = 12
STEP_MIN_SIDE = 4
# two levels must cost less than this times the straight line
STEP_GAIN = 0.75
# the jump must exceed this many robust σ
STEP_SIGMA = 3.0
# a bucket's run spread (p25..p75) as σ of a normal distribution
_IQR_SIGMA = 1.349
_MAD_SIGMA = 1.4826

# Allowed forecast horizons (in buckets) per bucket size.
AHEAD: dict[str, tuple[int, ...]] = {"hour": (12, 24), "day": (3, 7), "week": (2, 4)}
_SECONDS = {"hour": 3600.0, "day": 86400.0, "week": 7 * 86400.0}


def _median(values: Sequence[float]) -> float:
    return analytics.percentile(sorted(values), 0.5) or 0.0 if values else 0.0


def _robust_sigma(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mid = _median(values)
    return _MAD_SIGMA * _median([abs(v - mid) for v in values])


def _wls(xs: Sequence[float], ys: Sequence[float], ws: Sequence[float]) -> tuple[float, float, float, float]:
    """Weighted least squares: (intercept, slope, weighted mean of x, Σw(x − x̄)²)."""
    sw = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs, strict=True)) / sw
    my = sum(w * y for w, y in zip(ws, ys, strict=True)) / sw
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs, strict=True))
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys, strict=True))
    slope = sxy / sxx if sxx > 0 else 0.0
    return my - slope * mx, slope, mx, sxx


class _B:
    """A fitted bucket: its point, index x, median y, runs n (the weight) and
    widths below / above the median (None without p25 / p75)."""

    __slots__ = ("lower", "n", "p", "upper", "x", "y")

    def __init__(self, p: Point, x: float) -> None:
        c = p.cell
        self.p, self.x = p, x
        self.y = y = float(c.value)  # type: ignore[arg-type]
        self.n = max(1, c.n)
        self.lower = None if c.p25 is None else max(0.0, y - c.p25)
        self.upper = None if c.p75 is None else max(0.0, c.p75 - y)


def _ts(key: str) -> float | None:
    try:
        return datetime.fromisoformat(key).timestamp()
    except (TypeError, ValueError):
        return None


def _prefix_l1(ys: Sequence[float]) -> list[tuple[float, float]]:
    """For each prefix ``ys[:i + 1]``: (Σ|y − median|, median), in O(n log n)
    with two heaps (the lower half a max-heap holding the extra value)."""
    low: list[float] = []  # negated
    high: list[float] = []
    s_low = s_high = 0.0
    out = []
    for y in ys:
        if low and y > -low[0]:
            heapq.heappush(high, y)
            s_high += y
        else:
            heapq.heappush(low, -y)
            s_low += y
        if len(low) > len(high) + 1:
            v = -heapq.heappop(low)
            s_low -= v
            heapq.heappush(high, v)
            s_high += v
        elif len(high) > len(low):
            v = heapq.heappop(high)
            s_high -= v
            heapq.heappush(low, -v)
            s_low += v
        m = -low[0]
        cost = (s_high - len(high) * m) + (len(low) * m - s_low)
        mid = m if len(low) > len(high) else (m + high[0]) / 2
        out.append((cost, mid))
    return out


def _step(bs: list[_B], eps: float) -> int | None:
    """Index of the first bucket after a step in the medians, or None."""
    n = len(bs)
    if n < STEP_MIN_BUCKETS:
        return None
    xs, ys = [b.x for b in bs], [b.y for b in bs]
    a, s, _, _ = _wls(xs, ys, [1.0] * n)
    line_cost = sum(abs(y - (a + s * x)) for x, y in zip(xs, ys, strict=True))
    left = _prefix_l1(ys)
    right = _prefix_l1(ys[::-1])[::-1]  # right[i]: of ys[i:]
    best: tuple[float, int] | None = None
    for k in range(STEP_MIN_SIDE, n - STEP_MIN_SIDE + 1):
        cost = left[k - 1][0] + right[k][0]
        if best is None or cost < best[0]:
            best = (cost, k)
    if best is None or not best[0] < STEP_GAIN * line_cost - eps:
        return None
    k = best[1]
    ml, mr = left[k - 1][1], right[k][1]
    resid = [y - ml for y in ys[:k]] + [y - mr for y in ys[k:]]
    return k if abs(mr - ml) > max(STEP_SIGMA * _robust_sigma(resid), eps) else None


def _next(t: float, bucket: str, zone: tzinfo) -> tuple[float, str]:
    """Position and key of the bucket after the one starting at ``t``, named
    as :func:`ekte.web.analytics._bucket` names them (calendar days and
    Mondays in the viewer's zone, so a DST change keeps midnight)."""
    dt = datetime.fromtimestamp(t, UTC)
    if bucket == "hour":
        nxt = dt + timedelta(hours=1)
    else:
        day = dt.astimezone(zone).date() + timedelta(days=7 if bucket == "week" else 1)
        nxt = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)
    pos, key, _ = analytics._bucket(nxt, zone, bucket)
    return pos, key


def _short(status: str, ahead: int, used: int = 0) -> dict[str, Any]:
    return {"status": status, "ahead": ahead, "buckets_used": used, "buckets_needed": MIN_FIT_BUCKETS}


def forecast(points: Sequence[Point], annotations: Iterable[Mapping[str, Any]], bucket: str,
             zone: tzinfo, ahead: int, metric: Metric) -> dict[str, Any]:
    """The forecast of one series ``ahead`` buckets past its last bucket (see
    the module docstring): ``status`` ok / few_buckets / not_median."""
    if metric.agg != "median":
        return _short("not_median", ahead)
    size = _SECONDS[bucket]
    pts = sorted(points, key=lambda p: p.pos)
    if not pts:
        return _short("few_buckets", ahead)
    last_pos = pts[-1].pos
    # 1. cut at the last mark
    marks = [t for a in annotations if (t := _ts(str(a.get("bucket")))) is not None]
    if marks:
        cut = max(marks)
        pts = [p for p in pts if p.pos >= cut]
    # 2. enough runs
    pts = [p for p in pts if not p.cell.low_n and p.cell.value is not None]
    if not pts:
        return _short("few_buckets", ahead)
    pos0 = pts[0].pos
    bs = [_B(p, round((p.pos - pos0) / size)) for p in pts]
    eps = 1e-9 * max(1.0, max(abs(b.y) for b in bs))
    # 3. cut at a step
    step_key = None
    k = _step(bs, eps)
    if k is not None:
        step_key = bs[k].p.bucket
        bs = bs[k:]
    # 4. too few
    if len(bs) < MIN_FIT_BUCKETS:
        return _short("few_buckets", ahead, len(bs))

    def fit(bs: list[_B]) -> tuple[float, float, float, float, list[float]]:
        a, s, mx, sxx = _wls([b.x for b in bs], [b.y for b in bs], [b.n for b in bs])
        return a, s, mx, sxx, [b.y - (a + s * b.x) for b in bs]

    # 5. median line; 6. drop odd buckets once
    a, slope, _mx, sxx, resid = fit(bs)
    # off the residuals' median: one wild bucket also shifts the line itself
    sigma, mid = _robust_sigma(resid), _median(resid)
    keep = [b for b, r in zip(bs, resid, strict=True)
            if not (abs(r - mid) > ODD_SIGMA * sigma and abs(r - mid) > eps)]
    dropped = 0
    if len(keep) < len(bs) and len(keep) >= MIN_FIT_BUCKETS:
        dropped = len(bs) - len(keep)
        bs = keep
        a, slope, _mx, sxx, resid = fit(bs)
    kf = len(bs)
    # 7. uncertainty
    s2 = sum(b.n * r * r for b, r in zip(bs, resid, strict=True)) / (kf - 2)
    se = math.sqrt(s2 / sxx) if sxx > 0 else 0.0
    s_b = _robust_sigma(resid)
    clear = abs(slope) > Z * se and abs(slope) > eps
    # 8. width slopes
    wide = [b for b in bs if b.n >= MIN_WIDTH_RUNS and b.lower is not None and b.upper is not None]
    l_slope = u_slope = 0.0
    if len(wide) >= MIN_WIDTH_BUCKETS:
        ws = [float(b.n) for b in wide]
        l_slope = _wls([b.x for b in wide], [b.lower or 0.0 for b in wide], ws)[1]
        u_slope = _wls([b.x for b in wide], [b.upper or 0.0 for b in wide], ws)[1]
    # 9. start at the last fitted bucket
    last = bs[-1]
    lows = [w for b in bs if (w := b.lower) is not None]
    highs = [w for b in bs if (w := b.upper) is not None]
    a_lo = max(last.lower or 0.0, 0.25 * _median(lows))
    a_hi = max(last.upper or 0.0, 0.25 * _median(highs))
    y0 = last.y
    floor = 0.0 if metric.unit == "score" or min(b.y for b in bs) >= 0 else -math.inf
    ceil = 100.0 if metric.unit == "score" else math.inf

    def clip(v: float) -> float:
        return min(ceil, max(floor, v))

    # 10. projection over 11. the next bucket keys
    out = []
    t = last_pos
    for _ in range(ahead):
        t, key = _next(t, bucket, zone)
        d = max(0, round((t - last.p.pos) / size))
        y = y0 + slope * d
        wl, wu = max(0.0, a_lo + l_slope * d), max(0.0, a_hi + u_slope * d)
        sig = (wl + wu) / _IQR_SIGMA
        sf = math.sqrt((se * d) ** 2 + s_b * s_b * d)
        if sig > 0:
            kw = math.sqrt(1 + (Z * sf / sig) ** 2)
            lo, hi = y - wl * kw, y + wu * kw
        else:
            lo, hi = y - Z * sf, y + Z * sf
        out.append({"bucket": key, "value": clip(y), "p25": clip(lo), "p75": clip(hi)})
    return {
        "status": "ok", "ahead": ahead, "buckets_used": kf, "buckets_needed": MIN_FIT_BUCKETS,
        "dropped": dropped, "since": bs[0].p.bucket, "step": step_key,
        "slope": slope, "slope_se": se, "clear": clear,
        # better / worse / neutral (no better side) for a clear trend; none otherwise
        "direction": metrics.direction(metric, slope) if clear else "none",
        "start": {"bucket": last.p.bucket, "value": y0, "p25": y0 - a_lo, "p75": y0 + a_hi},
        "points": out,
    }
