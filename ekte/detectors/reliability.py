"""Reliability detector — concurrent success rate & latency under load.

Fires a burst of identical tiny requests with bounded concurrency and measures
how many succeed and how fast they return. A relay that flakes, rate-limits, or
crawls under modest parallelism is a reliability risk even when single calls
look fine. Aggregated into a :class:`ReliabilitySummary` the runner surfaces.

Scoring follows the published ``SCALE`` (method "deductions"): the score starts
at 100, failed requests deduct their share (100 - success rate x 100; HTTP 429
throttling is excluded), and a high tail latency deducts 15% of what is left.
A single failure in a small burst (or at most 10% of a larger one) is a WARN,
more is a FAIL; the detector status is the worst of its findings. These are
transport advisories (``zing.scoring.ADVISORY_CHECKS``): they lower this
dimension but never the substitution risk.
"""

from __future__ import annotations

import asyncio

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.scale import DeductionScale, outcome
from zing.models import (
    DetectorResult,
    Dimension,
    ReliabilitySummary,
    RequestSpec,
    Severity,
    Status,
)
from zing.utils.stats import summarize

# A p95 above this (ms) is slow enough to flag and dampen the score.
_SLOW_P95_MS = 30_000.0
_SLOW_FACTOR = 0.85  # a slow tail keeps 85% of the success-rate score
# Failures tolerated as a WARN: at most 10% of the attempted requests, or one
# request in a small burst (one of the default 8 is 12.5%) — but never below
# an 80% success rate.
_MINOR_MIN_SUCCESS = 0.80

SCALE = DeductionScale(
    outcome("reliability.success_rate", "all_succeeded", None, Status.PASS,
            label="Every attempted request in the burst succeeded."),
    outcome("reliability.success_rate", "some_failed", None, Status.WARN, Severity.LOW,
            max_deduction=20.0,
            label="One request, or at most 10% of the attempted ones, failed (80%+ succeeded); deducts the failed share."),
    outcome("reliability.success_rate", "many_failed", None, Status.FAIL, Severity.MEDIUM,
            max_deduction=100.0,
            label="More requests than that failed; deducts the failed share."),
    outcome("reliability.success_rate", "all_rate_limited", None, Status.INCONCLUSIVE,
            Severity.LOW, label="Every request was rate-limited (HTTP 429): not scored."),
    outcome("reliability.latency", "slow", None, Status.WARN, Severity.LOW, max_deduction=15.0,
            label="p95 latency above 30 s under load; deducts 15% of the remaining score."),
    outcome("reliability.rate_limited", "throttled", None, Status.INFO,
            label="Part of the burst was rate-limited: honest throttling, not counted."),
    outcome("reliability.skipped", "disabled", None, Status.INFO,
            label="The reliability probe was disabled."),
)


def _rate_score(success_rate: float) -> float:
    return round(success_rate * 100, 1)


def _minor_failures(failed: int, effective: int) -> bool:
    """Whether ``failed`` of ``effective`` attempted requests is a WARN, not a FAIL."""
    allowed = max(1, effective // 10)  # 10%, rounded down
    return 0 < failed <= allowed and (effective - failed) / effective >= _MINOR_MIN_SUCCESS


def _latency_deduction(success_rate: float) -> float:
    """What a slow tail takes off: 15% of the success-rate score (rounded like
    the score itself)."""
    base = _rate_score(success_rate)
    return round(base - round(base * _SLOW_FACTOR, 1), 1)


@register
class ReliabilityDetector(Detector):
    id = "reliability"
    name = "Concurrent reliability & latency"
    dimension = Dimension.RELIABILITY
    min_suite = "standard"
    cost_hint = 8

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())

        n = ctx.options.reliability_requests
        if n <= 0:
            result.status = Status.NOT_RUN
            result.score = None
            result.findings.append(
                SCALE.finding(
                    "reliability.skipped",
                    "disabled",
                    title="Reliability probe disabled",
                    summary="reliability_requests <= 0; no concurrent load was issued.",
                    evidence={"reliability_requests": n},
                )
            )
            return result

        conc = max(1, ctx.options.reliability_concurrency)
        spec = RequestSpec(
            messages=[{"role": "user", "content": prompts.text("reliability.ping")}],
            temperature=0.0,
            max_tokens=8,
            reasoning_retry=False,  # latency under load is the measurement
        )

        # Fire n identical requests, capping in-flight calls with a semaphore.
        sem = asyncio.Semaphore(conc)

        async def _one() -> tuple[bool, float | None, str | None, int | None]:
            async with sem:
                outcome = await ctx.client.complete(spec)
            return outcome.ok, outcome.duration_ms, outcome.error_type, outcome.status_code

        results = await asyncio.gather(*(_one() for _ in range(n)))

        successes = 0
        rate_limited = 0
        durations: list[float] = []
        errors: dict[str, int] = {}
        for ok, duration_ms, error_type, status_code in results:
            if ok:
                successes += 1
                if duration_ms is not None:
                    durations.append(duration_ms)
            elif status_code == 429:
                # The relay correctly throttling the burst is honest behavior, not
                # instability — keep it out of the success-rate denominator.
                rate_limited += 1
            else:
                key = error_type or "unknown"
                errors[key] = errors.get(key, 0) + 1

        # Success rate is over genuinely-attempted (non-throttled) requests.
        effective = n - rate_limited
        success_rate = successes / effective if effective > 0 else 1.0
        latency = summarize(durations)
        summary = ReliabilitySummary(
            requests=n,
            successes=successes,
            success_rate=success_rate,
            rate_limited=rate_limited,
            latency_ms=latency,
            errors=errors,
        )
        result.evidence["reliability"] = summary.model_dump()

        p95 = latency.get("p95")
        slow = p95 is not None and p95 > _SLOW_P95_MS
        failed = effective - successes

        # Headline finding: how the burst fared (over genuinely-attempted requests).
        if effective == 0:
            result.findings.append(
                SCALE.finding(
                    "reliability.success_rate",
                    "all_rate_limited",
                    title="All concurrent requests were rate-limited",
                    summary=f"All {n} requests returned HTTP 429 at concurrency {conc}; "
                    "reliability under load could not be assessed.",
                    evidence={"requests": n, "rate_limited": rate_limited, "concurrency": conc},
                    recommendation="Lower --concurrency or --reliability-requests and re-run.",
                )
            )
        elif successes == effective:
            result.findings.append(
                SCALE.finding(
                    "reliability.success_rate",
                    "all_succeeded",
                    title="All concurrent requests succeeded",
                    summary=f"{successes} of {effective} attempted requests succeeded at "
                    f"concurrency {conc}"
                    + (f" ({rate_limited} rate-limited)." if rate_limited else "."),
                    evidence={
                        "requests": n,
                        "successes": successes,
                        "rate_limited": rate_limited,
                        "concurrency": conc,
                        "success_rate": round(success_rate, 4),
                    },
                )
            )
        else:
            severe = not _minor_failures(failed, effective)
            result.findings.append(
                SCALE.finding(
                    "reliability.success_rate",
                    "many_failed" if severe else "some_failed",
                    deduction=round(100.0 - _rate_score(success_rate), 1),
                    title="Some concurrent requests failed",
                    summary=f"{failed} of {effective} attempted requests failed at "
                    f"concurrency {conc}"
                    + (f" ({rate_limited} rate-limited, excluded)." if rate_limited else "."),
                    evidence={
                        "requests": n,
                        "successes": successes,
                        "rate_limited": rate_limited,
                        "concurrency": conc,
                        "success_rate": round(success_rate, 4),
                        "errors": errors,
                    },
                    recommendation=(
                        "Check the relay's connection pool and upstream stability under "
                        "parallel load (HTTP 429 throttling is excluded from this rate)."
                    ),
                )
            )

        # Throttling is honest behavior — surface it, but only as information.
        if rate_limited and effective > 0:
            result.findings.append(
                SCALE.finding(
                    "reliability.rate_limited",
                    "throttled",
                    title="Relay rate-limited part of the burst",
                    summary=f"{rate_limited} of {n} requests returned HTTP 429 at concurrency "
                    f"{conc}; counted as throttling, not instability.",
                    evidence={"rate_limited": rate_limited, "requests": n, "concurrency": conc},
                )
            )

        # Latency finding: only when we have data and p95 is high.
        if slow:
            result.findings.append(
                SCALE.finding(
                    "reliability.latency",
                    "slow",
                    deduction=_latency_deduction(success_rate) if effective > 0 else 0.0,
                    title="High tail latency under load",
                    summary=f"p95 latency {p95:.0f} ms exceeds {_SLOW_P95_MS:.0f} ms.",
                    evidence={"latency_ms": latency, "concurrency": conc},
                )
            )

        if effective == 0:
            # Nothing but throttling — no reliability signal to score.
            result.score = None
            result.status = Status.INCONCLUSIVE
            return result

        result.score = SCALE.total(result.findings)
        # The status is the worst of the findings, so it never contradicts them
        # (a FAIL finding under a PASS detector).
        result.status = DeductionScale.roll_up(result.findings)
        return result
