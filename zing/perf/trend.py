"""Running medians for the performance chart's trend line.

Every successful, uncached request gets ``trend``: per chart metric, the
median of its endpoint's last :data:`TREND_WINDOW` such values, taken in the
order the requests were recorded. Failed and cached requests neither feed nor
get one, so a failure never pulls the line down. The live stream tags each
record as it is emitted (:class:`RunningMedian`); a finished or stored report
gets the same values from :func:`attach_trends`, so the browser only draws.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Iterable
from statistics import median
from typing import Any

TREND_WINDOW = 5


def _decode_tps(rec: dict[str, Any]) -> Any:
    local = rec.get("decode_tps_local")
    return local if local is not None else rec.get("decode_tps_reported")


# the live chart's metric tabs (perf.js METRICS) and the value each plots
METRICS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "latency": lambda r: r.get("duration_ms"),
    "ttft": lambda r: r.get("ttft_ms"),
    "tps": _decode_tps,
    "itl": lambda r: r.get("itl_mean_ms"),
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


class RunningMedian:
    """Tags request record dicts with their running medians, in order."""

    def __init__(self, window: int = TREND_WINDOW) -> None:
        self.window = window
        self._values: dict[tuple[str, str], deque[float]] = {}

    def tag(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Add ``trend`` to ``rec`` (in place) and return it."""
        if rec.get("op", "complete") != "complete" or not rec.get("ok") or rec.get("cached"):
            return rec
        endpoint = "baseline" if rec.get("endpoint") == "baseline" else "target"
        trend: dict[str, float] = {}
        for mid, get in METRICS.items():
            value = _number(get(rec))
            if value is None:
                continue
            window = self._values.setdefault((endpoint, mid), deque(maxlen=self.window))
            window.append(value)
            trend[mid] = median(window)
        if trend:
            rec["trend"] = trend
        return rec


def attach_trends(records: Iterable[dict[str, Any]]) -> None:
    """Tag a whole list of record dicts, as the live stream did."""
    tagger = RunningMedian()
    for rec in records:
        if isinstance(rec, dict):
            tagger.tag(rec)
