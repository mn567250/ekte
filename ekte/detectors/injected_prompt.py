"""Injected-system-prompt detector.

A relay can silently prepend its own hidden system/developer prompt to every
request — to steer behavior, watermark, or simply pad billable input. Two
independent tells are combined so an honest relay is not falsely accused:

1. A *fixed input overhead*. With no system message, the reported ``prompt_tokens``
   should sit just above an independent estimate (a small, roughly-constant chat
   template overhead). A hidden prepended prompt shows up as a LARGE overhead that
   stays constant as the user message grows — distinguishing it from proportional
   billing inflation.
2. A *leak* response when asked to repeat any preceding instructions.

Only when both point the same way does this rise to a (still cautious) WARN; a
single tell stays low and never escalates overall risk on its own.
"""

from __future__ import annotations

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.helpers import usage_field
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, RequestSpec, Severity, Status
from zing.utils.tokenize import estimate_messages_tokens

# Overhead (reported prompt_tokens − estimate) above this, holding roughly constant
# across message sizes, reads as a hidden prepended prompt rather than template noise.
_OVERHEAD_TOKENS = 30
# The two probes' overheads must agree within this to count as a *fixed* prefix.
_OVERHEAD_CONSISTENCY = 16


# The detector score is its one verdict's points (the published scale).
SCALE = Scale(
    outcome("injected_prompt.verdict", "clean", 100.0, Status.PASS,
            label="Input-token overhead is small and no hidden instructions leaked."),
    outcome("injected_prompt.verdict", "leak", 85.0, Status.INFO, Severity.LOW,
            label="Instruction-like text leaked when asked (weak on its own)."),
    outcome("injected_prompt.verdict", "overhead", 75.0, Status.WARN, Severity.LOW,
            label="A large fixed input-token overhead, constant across message sizes."),
    outcome("injected_prompt.verdict", "suspected", 55.0, Status.WARN, Severity.MEDIUM,
            label="A fixed input-token overhead and a leaked preamble together."),
    outcome("injected_prompt.verdict", "inconclusive", None, Status.INCONCLUSIVE,
            label="No usable prompt token counts to measure the overhead."),
    titles={"injected_prompt.verdict": "Injected system prompt"},
)


@register
class InjectedPromptDetector(Detector):
    id = "injected_prompt"
    name = "Injected system-prompt detection"
    dimension = Dimension.SECURITY
    min_suite = "deep"
    cost_hint = 3

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        tok = ctx.tokenizer_hint()

        overhead = await self._measure_overhead(ctx, tok)
        leaked = await self._leak_probe(ctx)

        result.evidence.update({"overhead": overhead, "leak_detected": leaked})

        fixed_prefix = (
            overhead is not None
            and overhead["min"] >= _OVERHEAD_TOKENS
            and overhead["spread"] <= _OVERHEAD_CONSISTENCY
        )

        if fixed_prefix and leaked:
            assert overhead is not None  # fixed_prefix implies a measured overhead
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "suspected",
                    id="injected_prompt.suspected",
                    title="Hidden system prompt likely injected",
                    summary=(
                        f"Reported prompt tokens carry a large fixed overhead "
                        f"(~{overhead['min']} tokens beyond estimate, constant across "
                        f"message sizes) AND the model leaked instruction-like content "
                        f"when asked. A hidden prepended system prompt is suspected."
                    ),
                    evidence={"overhead": overhead, "leak_detected": True},
                    recommendation="Compare prompt_tokens against a trusted baseline for the same input.",
                )
            )
            result.status = Status.WARN
            result.score = Scale.mean(result.findings)
        elif fixed_prefix:
            assert overhead is not None
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "overhead",
                    id="injected_prompt.overhead",
                    title="Unexpected fixed input-token overhead",
                    summary=(
                        f"Prompt tokens sit ~{overhead['min']} above estimate and stay "
                        f"constant as the message grows — consistent with a hidden "
                        f"prepended prompt, but a single signal. Corroborate."
                    ),
                    evidence={"overhead": overhead},
                )
            )
            result.status = Status.WARN
            result.score = Scale.mean(result.findings)
        elif leaked:
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "leak",
                    id="injected_prompt.leak",
                    title="Model surfaced instruction-like preamble (weak)",
                    summary=(
                        "When asked to repeat preceding instructions the model returned "
                        "instruction-like text rather than NONE. Models confabulate, so "
                        "this is weak on its own."
                    ),
                    evidence={"leak_detected": True},
                )
            )
            result.status = Status.INFO
            result.score = Scale.mean(result.findings)
        elif overhead is None:
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "inconclusive",
                    id="injected_prompt.inconclusive",
                    title="Could not measure input-token overhead",
                    summary="No usable prompt_tokens in the responses; overhead check skipped.",
                    evidence={},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = Scale.mean(result.findings)
        else:
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "clean",
                    id="injected_prompt.clean",
                    title="No sign of an injected system prompt",
                    summary="Input-token overhead is small/template-sized and no preamble leaked.",
                    evidence={"overhead": overhead},
                )
            )
            result.status = Status.PASS
            result.score = Scale.mean(result.findings)
        return result

    # ------------------------------------------------------------------ #
    async def _measure_overhead(self, ctx: AuditContext, tok: str | None) -> dict | None:
        """Reported prompt_tokens minus an independent estimate, for two sizes."""
        overheads: list[int] = []
        for content in (prompts.text("injected_prompt.small"), prompts.text("injected_prompt.large")):
            messages = [{"role": "user", "content": content}]
            outcome = await ctx.client.complete(
                # only the prompt token count is read, never the answer
                RequestSpec(messages=messages, temperature=0.0, max_tokens=8, reasoning_retry=False)
            )
            if not outcome.ok:
                continue
            reported = usage_field(outcome.usage, "prompt_tokens", "input_tokens")
            if reported is None:
                continue
            estimate = estimate_messages_tokens(messages, tok)
            overheads.append(reported - estimate)
        if len(overheads) < 2:
            return None
        return {
            "values": overheads,
            "min": min(overheads),
            "spread": max(overheads) - min(overheads),
        }

    async def _leak_probe(self, ctx: AuditContext) -> bool:
        outcome = await ctx.client.complete(
            RequestSpec(
                messages=[{"role": "user", "content": prompts.text("injected_prompt.leak")}],
                temperature=0.0,
                max_tokens=200,
            )
        )
        if not (outcome.ok and outcome.has_content()):
            return False
        text = outcome.content.strip()
        # Compliant "NONE" (allowing minor punctuation) => no leak.
        if text.upper().strip(" .\"'") == "NONE":
            return False
        # Substantial, instruction-flavored content => a (weak) leak signal.
        lowered = text.lower()
        instruction_markers = ("you are", "system", "assistant", "instruction", "do not", "always", "must")
        return len(text) > 60 and any(m in lowered for m in instruction_markers)
