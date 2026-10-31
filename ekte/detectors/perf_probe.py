"""Surface-neutral parts of the performance probes.

The chat probe (:mod:`ekte.detectors.performance`), the embedding probe
(:mod:`ekte.detectors.embed_performance`) and the rerank probe
(:mod:`ekte.detectors.rerank_performance`) share their gating, the phase loop
(ping → warm-up → N probes → burst, target and baseline alternating), and the
consistency, error and load findings. Each probe brings its own request, its own
scoring scale and its surface-specific findings.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from ekte.clients import Client
from ekte.config import AuditOptions
from ekte.context import AuditContext
from ekte.detectors.base import CUSTOM_SUITE, SUITE_ORDER
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, EndpointPerformance, Severity, Status
from ekte.perf import RequestRecorder, phase_scope
from ekte.utils.stats import percentile

PINGS = 3
# Probe size on the standard suite, where it only runs in compare mode.
STANDARD_COMPARE_REQUESTS = 5
# Burst size: a few rounds at the configured concurrency.
_BURST_ROUNDS = 4
_MIN_BURST = 8
# Consistency is judged by the tail ratio: p90 / p50 for latency and TTFT (slow
# outliers), p50 / p10 for throughput (slow outliers). A percentile ratio is
# robust to the odd stray request, unlike a standard deviation.
MIN_CONSISTENCY_SAMPLES = 10
_TAIL_STEADY = 1.3
_TAIL_STABLE = 1.75
_TAIL_VARIABLE = 2.5
# The consistency findings' titles per metric, spelled out so the locales can
# translate each one.
CONSISTENCY_TITLE = {
    "Latency": "Latency consistency",
    "Time to first token": "Time to first token consistency",
    "Decode throughput": "Decode throughput consistency",
    "End-to-end throughput": "End-to-end throughput consistency",
    "Embedding throughput": "Embedding throughput consistency",
    "Rerank throughput": "Rerank throughput consistency",
}
# Share of probe requests that failed (rate limits excluded).
_ERROR_RATE_OK = 0.02
_ERROR_RATE_WARN = 0.1
# Burst p50 latency / sequential p50 latency.
_LOAD_STABLE = 1.5
_LOAD_SLOWER = 3.0
_MIN_BURST_SAMPLES = 5


# -- gating ----------------------------------------------------------------- #
def deep(suite: str) -> bool:
    """Deep or deeper — the custom suite probes like deep."""
    if suite == CUSTOM_SUITE:
        return True
    return suite in SUITE_ORDER and SUITE_ORDER.index(suite) >= SUITE_ORDER.index("deep")


def probe_applies(suite: str, *, has_baseline: bool) -> bool:
    """A probe runs on deep/full/custom, and on standard in compare mode."""
    return deep(suite) or (suite == "standard" and has_baseline)


def planned_probe_requests(options: AuditOptions, *, has_baseline: bool) -> int:
    """Probe requests per endpoint for this run (0 = the probe does not run)."""
    n = options.performance_requests
    if n <= 0:
        return 0
    if deep(options.suite):
        return n
    if options.suite == "standard" and has_baseline:
        return min(STANDARD_COMPARE_REQUESTS, n)
    return 0


def burst_size(options: AuditOptions, probe_requests: int) -> int:
    """Requests in the concurrency burst (deep/full only)."""
    if not deep(options.suite) or probe_requests <= 0:
        return 0
    conc = max(1, options.reliability_concurrency)
    return min(probe_requests, max(conc * _BURST_ROUNDS, _MIN_BURST))


# -- the phase loop ----------------------------------------------------------- #
class Endpoint:
    """One side of the probe and its per-endpoint state."""

    def __init__(self, label: str, client: Client) -> None:
        self.label = label
        self.client = client
        self.seen: set[str] = set()


def endpoints_of(ctx: AuditContext) -> list[Endpoint]:
    endpoints = [Endpoint("target", ctx.client)]
    if ctx.baseline_client is not None:
        endpoints.append(Endpoint("baseline", ctx.baseline_client))
    return endpoints


def attach_recorder(ctx: AuditContext, endpoints: list[Endpoint]) -> tuple[RequestRecorder, list[Client]]:
    """The run's recorder; standalone use (no runner) records into a private
    one attached to the clients, which the caller detaches afterwards."""
    recorder = ctx.recorder
    attached: list[Client] = []
    if recorder is None:
        recorder = RequestRecorder(ctx.tokenizer_hint())
        for ep in endpoints:
            if ep.client.recorder is None:
                ep.client.recorder, ep.client.endpoint = recorder, ep.label
                attached.append(ep.client)
    return recorder, attached


async def run_phases(
    endpoints: list[Endpoint],
    call: Callable[[Endpoint, Any], Awaitable[Any]],
    *,
    n: int,
    modes: Sequence[Any],
    burst: int,
    conc: int,
    burst_modes: Sequence[Any] | None = None,
) -> None:
    """Ping, warm up (``modes[0]``), N probe rounds over ``modes``, then a burst
    per ``burst_modes`` (default ``modes``). ``call(endpoint, mode)`` sends one
    request; target and baseline alternate who goes first."""
    with phase_scope("ping"):
        for _ in range(PINGS):
            for ep in endpoints:
                await ep.client.list_models(no_cache=True)
    with phase_scope("warmup"):
        for ep in endpoints:
            await call(ep, modes[0])
    with phase_scope("probe"):
        for i in range(n):
            for mode in modes:
                # Alternate who goes first so neither side always follows the other.
                for ep in endpoints if i % 2 == 0 else endpoints[::-1]:
                    await call(ep, mode)
    if burst:
        with phase_scope("probe_concurrent"):
            for mode in modes if burst_modes is None else burst_modes:
                for ep in endpoints:
                    sem = asyncio.Semaphore(conc)

                    async def one(ep: Endpoint = ep, mode: Any = mode, sem: asyncio.Semaphore = sem) -> None:
                        async with sem:
                            await call(ep, mode)

                    await asyncio.gather(*(one() for _ in range(burst)))


# -- scale outcomes ------------------------------------------------------------ #
def consistency_outcomes(check: str, what: str) -> tuple:
    return (
        outcome(check, "steady", 100, Status.PASS, label=f"{what} is steady (tail ratio at most 1.3)."),
        outcome(check, "stable", 85, Status.PASS, label=f"{what} is stable (tail ratio at most 1.75)."),
        outcome(check, "variable", 65, Status.WARN, Severity.LOW,
                label=f"{what} varies noticeably (tail ratio at most 2.5)."),
        outcome(check, "erratic", 40, Status.FAIL, Severity.LOW,
                label=f"{what} is erratic (tail ratio above 2.5)."),
        outcome(check, "few_samples", None, Status.INFO,
                label=f"Too few samples to judge how consistent {what.lower()} is."),
    )


def error_outcomes() -> tuple:
    return (
        outcome("performance.errors", "ok", 100, Status.PASS,
                label="At most 2% of the probe requests failed."),
        outcome("performance.errors", "some", 80, Status.WARN, Severity.LOW,
                label="Up to 10% of the probe requests failed or timed out."),
        outcome("performance.errors", "failed", 50, Status.FAIL, Severity.LOW,
                label="Many probe requests failed or timed out."),
    )


def load_outcomes() -> tuple:
    return (
        outcome("performance.load_stability", "stable", 100, Status.PASS,
                label="Latency holds up under concurrent load (at most 1.5x)."),
        outcome("performance.load_stability", "slower", 80, Status.WARN, Severity.LOW,
                label="Latency rises under concurrent load (up to 3x)."),
        outcome("performance.load_stability", "degraded", 55, Status.FAIL, Severity.LOW,
                label="Latency degrades sharply under concurrent load (above 3x)."),
    )


# -- findings ---------------------------------------------------------------- #
def tail_key(ratio: float) -> str:
    if ratio <= _TAIL_STEADY:
        return "steady"
    if ratio <= _TAIL_STABLE:
        return "stable"
    if ratio <= _TAIL_VARIABLE:
        return "variable"
    return "erratic"


def tail_ratio(values: Sequence[float], *, higher_is_better: bool) -> float | None:
    """How far the slow tail sits from the median (>= 1; 1 = perfectly even)."""
    if len(values) < MIN_CONSISTENCY_SAMPLES:
        return None
    p50 = percentile(values, 50)
    tail = percentile(values, 10 if higher_is_better else 90)
    if not p50 or not tail:
        return None
    return p50 / tail if higher_is_better else tail / p50


def consistency_finding(
    scale: Scale,
    result: DetectorResult,
    check: str,
    what: str,
    unit: str,
    values: list[float],
    higher: bool,
) -> None:
    """One tail-ratio consistency finding (or "few samples") for ``values``;
    ``what`` names the metric (a :data:`CONSISTENCY_TITLE` key)."""
    ratio = tail_ratio(values, higher_is_better=higher)
    tail = "p10" if higher else "p90"
    p50 = r(percentile(values, 50))
    tail_value = r(percentile(values, 10 if higher else 90))
    evidence: dict[str, float | int | str | None] = {
        "samples": len(values),
        "p50": p50,
        tail: tail_value,
        "tail_ratio": round(ratio, 2) if ratio is not None else None,
        "unit": unit,
    }
    if ratio is None:
        result.findings.append(
            scale.finding(
                check, "few_samples",
                title=CONSISTENCY_TITLE[what],
                summary=f"{len(values)} clean samples; at least "
                f"{MIN_CONSISTENCY_SAMPLES} are needed to judge consistency.",
                evidence=evidence,
            )
        )
        return
    spread = f"{tail} / p50" if not higher else f"p50 / {tail}"
    result.findings.append(
        scale.finding(
            check, tail_key(ratio),
            title=CONSISTENCY_TITLE[what],
            summary=f"{what}: p50 {fmt(p50, unit)}, {tail} "
            f"{fmt(tail_value, unit)} — tail ratio ({spread}) {ratio:.2f} over "
            f"{len(values)} requests.",
            evidence=evidence,
        )
    )


def error_finding(scale: Scale, result: DetectorResult, target: EndpointPerformance) -> None:
    if target.error_rate is None:
        return
    rate = target.error_rate
    key = "ok" if rate <= _ERROR_RATE_OK else "some" if rate <= _ERROR_RATE_WARN else "failed"
    result.findings.append(
        scale.finding(
            "performance.errors",
            key,
            title="Probe request failures",
            summary=f"{target.errors} of {target.requests} target probe requests failed "
            f"({target.timeouts} timed out; {target.rate_limited} rate-limited, not counted).",
            evidence={
                "endpoint": "target",
                "requests": target.requests,
                "errors": target.errors,
                "timeouts": target.timeouts,
                "rate_limited": target.rate_limited,
                "error_rate": round(rate, 3),
            },
        )
    )


def load_finding(scale: Scale, result: DetectorResult, target: EndpointPerformance) -> None:
    conc = target.concurrency
    seq = target.latency_ms.p50
    if conc is None or conc.latency_ms.count < _MIN_BURST_SAMPLES or not seq:
        return
    burst = conc.latency_ms.p50
    if burst is None:
        return
    ratio = burst / seq
    key = "stable" if ratio <= _LOAD_STABLE else "slower" if ratio <= _LOAD_SLOWER else "degraded"
    result.findings.append(
        scale.finding(
            "performance.load_stability",
            key,
            title="Latency under concurrent load",
            summary=f"p50 latency {fmt(burst, 'ms')} at concurrency {conc.concurrency} vs "
            f"{fmt(seq, 'ms')} one at a time ({ratio:.2f}x).",
            evidence={
                "concurrency": conc.concurrency,
                "burst_latency_p50_ms": r(burst),
                "sequential_latency_p50_ms": r(seq),
                "ratio": round(ratio, 2),
            },
        )
    )


def r(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def fmt(value: float | None, unit: str) -> str:
    return "n/a" if value is None else f"{value:.0f} {unit}"


def signed(value: float) -> str:
    return f"{value:+.0f}"
