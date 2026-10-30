"""Prompt prefix-cache detector (timing).

Sends a long unique prefix twice and a different control prefix once, all
streamed, and compares time-to-first-token. A sharp TTFT collapse on the repeated
prefix — but not on the control — indicates the relay caches by prompt prefix.

This is reported as INFORMATION, never a failure: prefix caching is a legitimate
latency/cost optimization. ekte cannot prove *cross-user* cache sharing (the real
privacy risk) from a single key — that needs genuinely distinct accounts — so the
finding states that limitation explicitly rather than overclaiming.
"""

from __future__ import annotations

import asyncio

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import build_filler, stable_marker
from ekte.detectors.scale import Scale, outcome
from ekte.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    RequestSpec,
    Status,
)

# A warm prefix must be at least this much faster than both cold and control to
# count as caching, with a minimum absolute drop so sub-millisecond noise is ignored.
_WARM_RATIO = 0.5
_MIN_ABS_DROP_MS = 150.0
_PREFIX_TOKENS = 1200


# Informational: no outcome is counted, so the detector never has a score.
SCALE = Scale(
    outcome("prompt_cache.verdict", "detected", None, Status.INFO,
            label="A repeated prompt prefix came back much faster: prefix caching is active."),
    outcome("prompt_cache.verdict", "none", None, Status.INFO,
            label="A repeated prompt prefix was not distinctly faster."),
    outcome("prompt_cache.verdict", "inconclusive", None, Status.INCONCLUSIVE,
            label="One or more timing probes returned no usable timing."),
    titles={"prompt_cache.verdict": "Prompt-prefix caching"},
)


@register
class PromptCacheDetector(Detector):
    id = "prompt_cache"
    name = "Prompt prefix-cache (timing)"
    dimension = Dimension.SECURITY
    min_suite = "deep"
    cost_hint = 3

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        tok = ctx.tokenizer_hint()
        # CPU work: keep it off the event loop (it would skew concurrent timings).
        filler = await asyncio.to_thread(build_filler, _PREFIX_TOKENS, tok)
        prefix_a = f"{stable_marker('cache-a')}\n{filler}"
        prefix_b = f"{stable_marker('cache-b')}\n{filler}"

        cold = await self._timed(ctx, prefix_a)
        warm = await self._timed(ctx, prefix_a)
        control = await self._timed(ctx, prefix_b)

        times = {"cold_ms": cold, "warm_ms": warm, "control_ms": control}
        result.evidence.update(times)

        if cold is None or warm is None or control is None:
            result.findings.append(
                SCALE.finding(
                    "prompt_cache.verdict",
                    "inconclusive",
                    id="prompt_cache.inconclusive",
                    title="Prefix-cache timing unavailable",
                    summary="One or more streamed probes returned no usable timing.",
                    evidence=times,
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
            return result

        cached = (
            warm < _WARM_RATIO * cold
            and warm < _WARM_RATIO * control
            and (cold - warm) >= _MIN_ABS_DROP_MS
        )
        if cached:
            result.findings.append(
                SCALE.finding(
                    "prompt_cache.verdict",
                    "detected",
                    id="prompt_cache.detected",
                    title="Relay caches by prompt prefix",
                    summary=(
                        f"A repeated prefix returned far faster (~{warm:.0f} ms vs cold "
                        f"~{cold:.0f} ms, control ~{control:.0f} ms) — prompt-prefix "
                        "caching is active. This is a legitimate optimization; ekte "
                        "cannot prove cross-user cache sharing from a single key."
                    ),
                    evidence=times,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "prompt_cache.verdict",
                    "none",
                    id="prompt_cache.none",
                    title="No clear prompt-prefix caching",
                    summary=(
                        f"Repeated-prefix TTFT (~{warm:.0f} ms) was not distinctly faster "
                        f"than cold (~{cold:.0f} ms) / control (~{control:.0f} ms)."
                    ),
                    evidence=times,
                )
            )
        result.status = Status.INFO
        result.score = None  # informational — does not move the security score
        return result

    async def _timed(self, ctx: AuditContext, prefix: str) -> float | None:
        spec = RequestSpec(
            messages=[{"role": "user", "content": prompts.text("prompt_cache.request", prefix=prefix)}],
            temperature=0.0,
            max_tokens=8,
            stream=True,
            reasoning_retry=False,  # the timing is the measurement
        )
        outcome: CompletionOutcome = await ctx.client.complete(spec)
        if not outcome.ok:
            return None
        return outcome.ttft_ms if outcome.ttft_ms is not None else outcome.duration_ms
