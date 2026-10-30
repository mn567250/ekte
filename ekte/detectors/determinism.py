"""Determinism & cache-correctness detector.

A relay that secretly caches responses to cut inference cost will return the
same text for an identical prompt regardless of sampling parameters. The tell is
sampling at ``temperature=1.0``: a genuine model should vary; byte-identical
output is a caching signal. Identity at ``temperature=0`` is expected and not
penalized — deterministic decoding is correct behavior there.

To avoid falsely accusing honest models, the caching call only fires when at
least ``MIN_USABLE_SAMPLES`` (3) of the ``CACHING_SAMPLES`` (4) long
high-temperature samples came back usable and ALL usable samples are
byte-identical (fewer usable samples are inconclusive), and it is
suppressed for reasoning models, which legitimately ignore/clamp sampling
parameters (e.g. deepseek-reasoner ignores temperature) and can repeat output.

Checks score points from the published scale ``SCALE``. Only the temperature=1.0
check is counted; the temperature=0 check is informational, and an inconclusive
check is not counted.
"""

from __future__ import annotations

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import Detector, register
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, RequestSpec, Severity, Status

_NO_RESPONSE = "No usable response to judge by."  # same sentence as protocol's scale

SCALE = Scale(
    outcome("determinism.temp1_variability", "varies", 100.0, Status.PASS,
            label="Repeated samples at temperature=1.0 differed, as genuine sampling does."),
    outcome("determinism.temp1_variability", "identical_reasoning", 100.0, Status.INFO,
            label="Samples were identical, but reasoning models legitimately ignore temperature."),
    outcome("determinism.temp1_variability", "identical", 55.0, Status.WARN, Severity.MEDIUM,
            label="All usable samples (at least 3) at temperature=1.0 were byte-identical, "
            "suggesting response caching."),
    outcome("determinism.temp1_variability", "not_assessed", None, Status.INCONCLUSIVE,
            Severity.LOW, label="Fewer than 3 usable samples at temperature=1.0 to judge by."),
    outcome("determinism.temp0_stability", "stable", None, Status.INFO,
            label="Identical answers at temperature=0 (expected); informational, not scored."),
    outcome("determinism.temp0_stability", "drifts", None, Status.INFO,
            label="Answers differed at temperature=0; informational, not scored."),
    outcome("determinism.temp0_stability", "not_assessed", None, Status.INCONCLUSIVE,
            Severity.LOW, label=_NO_RESPONSE),
)


@register
class DeterminismDetector(Detector):
    id = "determinism"
    name = "Determinism & cache-correctness"
    dimension = Dimension.PROTOCOL
    min_suite = "deep"
    cost_hint = 6

    # Number of high-temperature samples that must ALL be byte-identical before a
    # caching finding fires. More than two so a chance collision on a short output
    # can't trip it.
    CACHING_SAMPLES = 4
    # Usable (ok, non-empty) samples needed to judge at all; with fewer, two
    # identical survivors would be too weak a caching signal.
    MIN_USABLE_SAMPLES = 3

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        # Reasoning models legitimately ignore/clamp temperature and may repeat
        # output, so a byte-identical run is NOT evidence of caching for them.
        reasoning = bool(ctx.profile and getattr(ctx.profile.model, "reasoning", False))

        # 1) High-temperature variability — the load-bearing caching probe. A longer
        # generation has far more entropy, so genuine sampling almost never repeats.
        creative = RequestSpec(
            messages=[
                {
                    "role": "user",
                    "content": prompts.text("determinism.creative"),
                }
            ],
            temperature=1.0,
            max_tokens=220,
        )
        outcomes = [await ctx.client.complete(creative) for _ in range(self.CACHING_SAMPLES)]
        usable = [o for o in outcomes if o.ok and o.has_content()]

        if len(usable) >= self.MIN_USABLE_SAMPLES:
            texts = [o.content.strip() for o in usable]
            all_identical = len(set(texts)) == 1
            previews = {f"output_{i}_preview": t[:160] for i, t in enumerate(texts[:3])}
            if all_identical and not reasoning:
                result.findings.append(
                    SCALE.finding(
                        "determinism.temp1_variability",
                        "identical",
                        title="Identical output at temperature=1.0 suggests response caching",
                        summary=(
                            f"{len(usable)} identical long creative prompts at "
                            "temperature=1.0 (no seed) returned byte-identical text. A "
                            "genuine sampling model should vary; this is consistent with a "
                            "relay serving cached responses."
                        ),
                        evidence={
                            "temperature": 1.0,
                            "samples": len(usable),
                            "identical": True,
                            "model_returned": usable[0].model_returned,
                            **previews,
                        },
                        recommendation=(
                            "Confirm with varied prompts; a cache that ignores sampling "
                            "parameters can mask the served model's true behavior."
                        ),
                    )
                )
            elif all_identical and reasoning:
                result.findings.append(
                    SCALE.finding(
                        "determinism.temp1_variability",
                        "identical_reasoning",
                        title="Identical output at temperature=1.0 (expected for a reasoning model)",
                        summary=(
                            f"{len(usable)} samples were byte-identical, but the claimed "
                            "model is a reasoning model that legitimately ignores sampling "
                            "parameters — not treated as a caching signal."
                        ),
                        evidence={"temperature": 1.0, "samples": len(usable), "reasoning": True},
                    )
                )
            else:
                result.findings.append(
                    SCALE.finding(
                        "determinism.temp1_variability",
                        "varies",
                        title="Output varies at temperature=1.0",
                        summary=(
                            f"{len(usable)} identical creative prompts at temperature=1.0 "
                            "produced differing text, as expected for genuine sampling."
                        ),
                        evidence={"temperature": 1.0, "samples": len(usable), "identical": False, **previews},
                    )
                )
        else:
            # A relay that errors or returns nothing cannot be judged for caching.
            # Report a real failure when there is one, else an empty answer.
            failed = next((o for o in outcomes if not o.ok), None) or next(
                (o for o in outcomes if not o.has_content()), outcomes[0]
            )
            if not failed.ok:
                reason = failed.error_message or (
                    f"HTTP {failed.status_code}" if failed.status_code is not None
                    else failed.error_type or "no response"
                )
            else:
                reason = "the response had no content"
            result.findings.append(
                SCALE.finding(
                    "determinism.temp1_variability",
                    "not_assessed",
                    title="Could not assess temperature=1.0 variability",
                    summary=(
                        f"Only {len(usable)} of {self.CACHING_SAMPLES} samples were usable "
                        f"(at least {self.MIN_USABLE_SAMPLES} needed): "
                        + reason
                    ),
                    evidence={
                        "usable_samples": len(usable),
                        "requested_samples": self.CACHING_SAMPLES,
                        "required_samples": self.MIN_USABLE_SAMPLES,
                        "status_code": failed.status_code,
                        "error_type": failed.error_type,
                    },
                )
            )

        # 2) Determinism sanity at temperature=0 — informational only.
        factual = RequestSpec(
            messages=[{"role": "user", "content": prompts.text("determinism.factual")}],
            temperature=0.0,
            max_tokens=16,
        )
        third = await ctx.client.complete(factual)
        fourth = await ctx.client.complete(factual)

        if third.ok and third.has_content() and fourth.ok and fourth.has_content():
            ans_a = third.content.strip()
            ans_b = fourth.content.strip()
            stable = ans_a == ans_b
            result.findings.append(
                SCALE.finding(
                    "determinism.temp0_stability",
                    "stable" if stable else "drifts",
                    title=(
                        "Stable answer at temperature=0"
                        if stable
                        else "Answer drifts at temperature=0"
                    ),
                    summary=(
                        "Repeated factual prompt at temperature=0 returned "
                        + ("identical text (expected)." if stable else "differing text.")
                    ),
                    evidence={
                        "temperature": 0.0,
                        "identical": stable,
                        "answer_a": ans_a[:120],
                        "answer_b": ans_b[:120],
                    },
                )
            )
        else:
            failed = third if not (third.ok and third.has_content()) else fourth
            result.findings.append(
                SCALE.finding(
                    "determinism.temp0_stability",
                    "not_assessed",
                    title="Could not assess temperature=0 stability",
                    summary=failed.error_message or f"HTTP {failed.status_code}",
                    evidence={
                        "third_ok": third.ok and third.has_content(),
                        "fourth_ok": fourth.ok and fourth.has_content(),
                        "status_code": failed.status_code,
                        "error_type": failed.error_type,
                    },
                )
            )

        # Verdict: caching signal at temp=1 is the only thing that lowers status.
        result.score = Scale.mean(result.findings)
        if result.score is not None:
            caching = any(f.id == "determinism.temp1_variability" and f.status == Status.WARN
                          for f in result.findings)
            result.status = Status.WARN if caching else Status.PASS
        else:
            result.status = Status.INCONCLUSIVE
        return result
