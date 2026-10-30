"""Small statistics helpers used by latency / timing analysis.

Kept dependency-free (no numpy) so zing stays lightweight.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolated percentile (pct in [0, 100]). None if no data."""
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[int(rank)])
    frac = rank - low
    return float(ordered[low] * (1 - frac) + ordered[high] * frac)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def stdev(values: Sequence[float]) -> float | None:
    """Population standard deviation. None for fewer than 2 samples."""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def coefficient_of_variation(values: Sequence[float]) -> float | None:
    """stdev / mean — scale-free spread, handy for inter-chunk timing analysis."""
    avg = mean(values)
    sd = stdev(values)
    if avg is None or sd is None or avg == 0:
        return None
    return sd / avg


def summarize(values: Sequence[float]) -> dict[str, float | None]:
    """Compact latency summary: count, min, mean, p50, p95, p99, max, stdev."""
    if not values:
        return {
            "count": 0, "min": None, "mean": None, "p50": None,
            "p95": None, "p99": None, "max": None, "stdev": None,
        }
    return {
        "count": len(values),
        "min": float(min(values)),
        "mean": mean(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": float(max(values)),
        "stdev": stdev(values),
    }


# A percentile below this many samples is noise, so ``describe`` leaves it out.
PERCENTILE_MIN_SAMPLES: dict[str, int] = {
    "p50": 1,
    "p75": 4,
    "p90": 10,
    "p95": 20,
    "p99": 100,
}


def describe(values: Sequence[float]) -> dict[str, float | int | None]:
    """Full distribution for the performance report.

    count, min, mean, p50, p75, p90, p95, p99, max, stdev — each percentile is
    None until there are enough samples for it (``PERCENTILE_MIN_SAMPLES``).
    """
    n = len(values)
    out: dict[str, float | int | None] = {
        "count": n,
        "min": float(min(values)) if values else None,
        "mean": mean(values),
    }
    for key, floor in PERCENTILE_MIN_SAMPLES.items():
        out[key] = percentile(values, float(key[1:])) if n >= floor else None
    out["max"] = float(max(values)) if values else None
    out["stdev"] = stdev(values)
    return out
