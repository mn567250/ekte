"""LLM-judged quality / downgrade assessment — the flagship code+LLM hybrid.

Poses a small battery of tier-discriminating prompts (multi-step reasoning, a
precise coding task, nuanced instruction-following) to the target, optionally
mirrors them against a trusted baseline, then asks a *separate trusted judge*
whether the target's answers read like the model it claims to be or like a
cheaper / quantized / substituted stand-in. The judge never sees credentials —
only the model answers.
"""

from __future__ import annotations

import re
from typing import Any

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.scale import Scale, outcome
from zing.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    RequestSpec,
    Severity,
    Status,
)

# Discriminating prompts: each separates capable models from cheaper ones along a
# different axis. Kept short and deterministic so answers are comparable.
_PROBES: tuple[tuple[str, str], ...] = tuple(
    (label, prompt) for label, prompt in prompts.get("quality_judge.probes")
)

_ANSWER_CLIP = 2000  # cap each answer fed to the judge, keeping the prompt bounded


# The detector score is its one verdict's points (the published scale).
SCALE = Scale(
    outcome("quality_judge.verdict", "consistent", 95.0, Status.PASS,
            label="The judge found the answers consistent with the claimed model."),
    outcome("quality_judge.verdict", "suspicious", 50.0, Status.WARN, Severity.MEDIUM,
            label="The judge found the answers unlike the claimed model (low, medium or no stated confidence)."),
    outcome("quality_judge.verdict", "confident", 25.0, Status.WARN, Severity.MEDIUM,
            label="The judge is confident the answers are unlike the claimed model (no usable baseline)."),
    outcome("quality_judge.verdict", "confident_corroborated", 25.0, Status.FAIL, Severity.HIGH,
            label="The judge is confident, and a trusted baseline corroborated the difference."),
    outcome("quality_judge.verdict", "inconclusive", None, Status.INCONCLUSIVE, Severity.LOW,
            label="The judge could not commit to a verdict."),
    outcome("quality_judge.verdict", "unavailable", None, Status.INCONCLUSIVE, Severity.LOW,
            label="No target answers to judge."),
    titles={"quality_judge.verdict": "LLM judge verdict"},
)


def _suspicious_outcome(confidence: str, corroborated: bool) -> str:
    """Which "suspicious" row of the scale applies.

    Only an explicit ``high`` confidence counts as confident; a low, medium,
    missing or unrecognized confidence is the low-confidence row (MEDIUM, never
    HIGH). A confident verdict reaches HIGH only when a usable baseline
    corroborated it (see :func:`_baseline_usable`)."""
    if _is_high(confidence):
        return "confident_corroborated" if corroborated else "confident"
    return "suspicious"


def _is_high(confidence: str) -> bool:
    """``high`` as the judge may phrase it ("High.", "very high", "high
    confidence"); anything else — including no value — is not high."""
    return re.match(r"^(very\s+)?high\b", confidence.strip().lower()) is not None


def _baseline_usable(
    target_answers: list[dict[str, Any]], baseline_answers: list[dict[str, Any]]
) -> bool:
    """A baseline corroborates only when it produced a usable (non-empty)
    answer for every probe the target answered — otherwise the judge compared
    the target against gaps, not against the claimed model."""
    if not baseline_answers:
        return False
    answered = {b["label"] for b in baseline_answers if b["answer"]}
    wanted = {t["label"] for t in target_answers if t["answer"]}
    return bool(wanted) and wanted <= answered

@register
class QualityJudgeDetector(Detector):
    id = "quality_judge"
    name = "LLM-judged quality / downgrade assessment"
    dimension = Dimension.MODEL_IDENTITY
    min_suite = "deep"
    requires_judge = True
    cost_hint = 5

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        result.used_judge = True
        # The judge weighs the answers against the model the relay CLAIMS to
        # serve (family / cutoff below come from that claimed profile too).
        claimed = ctx.target.claimed

        # 1) Gather target (and optional baseline) answers to the probe battery.
        target_answers: list[dict[str, Any]] = []
        baseline_answers: list[dict[str, Any]] = []
        target_failures = 0

        for label, prompt in _PROBES:
            outcome = await self._ask(ctx.client, prompt)
            answer = self._extract(outcome)
            if answer is None:
                target_failures += 1
            target_answers.append({"label": label, "prompt": prompt, "answer": answer or ""})

            if ctx.has_baseline and ctx.baseline_client is not None:
                b_outcome = await self._ask(ctx.baseline_client, prompt)
                baseline_answers.append(
                    {"label": label, "answer": self._extract(b_outcome) or ""}
                )

        # If the target could not answer any probe, there is nothing to judge.
        if target_failures == len(_PROBES):
            result.findings.append(
                SCALE.finding(
                    "quality_judge.verdict",
                    "unavailable",
                    id="quality_judge.unavailable",
                    title="No target answers to judge",
                    summary="Target returned no usable content for any discriminating probe.",
                    evidence={"probes": len(_PROBES), "failed": target_failures},
                    recommendation="Re-run once the endpoint reliably returns completions.",
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
            return result

        # A baseline corroborates — and is shown to the judge — only when it
        # answered every probe the target answered; otherwise the judge would be
        # comparing the target against "(no answer)" gaps.
        corroborated = _baseline_usable(target_answers, baseline_answers)

        # 2) Build the judge prompt from model answers only (no keys / no base_url).
        system = prompts.text("quality_judge.system", claimed=claimed)
        user = self._build_user_prompt(
            claimed, target_answers, baseline_answers if corroborated else [], ctx
        )

        assert ctx.judge is not None  # requires_judge=True guarantees a judge here
        verdict = await ctx.judge.evaluate_json(system, user, max_tokens=700)

        # 3) Interpret the verdict robustly — any malformed/error shape is inconclusive.
        kind = str(verdict.get("verdict", "")).strip().lower()
        confidence = str(verdict.get("confidence", "")).strip().lower()
        likely_tier = verdict.get("likely_actual_tier")
        reasoning = verdict.get("reasoning")
        judge_errored = "_error" in verdict

        evidence: dict[str, Any] = {
            "claimed_model": claimed,
            "probe_labels": [p["label"] for p in target_answers],
            "target_probe_failures": target_failures,
            "baseline_compared": bool(baseline_answers),
            "baseline_usable": corroborated,
            "judge_verdict": kind or None,
            "judge_confidence": confidence or None,
            "likely_actual_tier": likely_tier,
            "judge_reasoning": reasoning,
        }
        if judge_errored:
            evidence["judge_error"] = verdict.get("_error")
        result.evidence.update(evidence)

        if kind == "suspicious":
            # A lone judge opinion is a single fuzzy signal from one trusted model and
            # must not, by itself, reach the strongest "does not deliver the claimed
            # model" verdict (RiskLevel.HIGH). Only escalate to HIGH severity when a
            # trusted BASELINE that actually answered corroborated the side-by-side
            # AND the judge stated high confidence; a missing/unknown confidence
            # counts as low. Otherwise cap at MEDIUM so it needs a second core
            # signal to drive HIGH.
            key = _suspicious_outcome(confidence, corroborated)
            high_sev = key == "confident_corroborated"
            if corroborated:
                note = ""
            elif any(b["answer"] for b in baseline_answers):
                note = (" The trusted baseline did not answer every probe, so it does "
                        "not corroborate this — re-run `zing compare` once it responds.")
            elif baseline_answers:
                note = (" The trusted baseline returned no usable answer to any probe, so "
                        "it does not corroborate this — re-run `zing compare` once it responds.")
            else:
                note = (" No trusted baseline was compared, so this stays a "
                        "corroboration-required signal — run `zing compare`.")
            result.findings.append(
                SCALE.finding(
                    "quality_judge.verdict",
                    key,
                    id="quality_judge.suspicious",
                    title=(
                        "LLM judge: behavior inconsistent with claimed model "
                        "(possible downgrade/substitution/quantization)"
                    ),
                    summary=(
                        f"Judge ({confidence or 'unspecified'} confidence) found the answers "
                        f"unlike '{claimed}'"
                        + (f"; likely closer to: {likely_tier}." if likely_tier else ".")
                        + note
                    ),
                    evidence={
                        "judge_confidence": confidence or None,
                        "likely_actual_tier": likely_tier,
                        "reasoning": reasoning,
                        "baseline_corroborated": corroborated,
                    },
                    recommendation=(
                        "Treat as a divergence signal, not proof; corroborate with "
                        "fingerprint and identity detectors before acting."
                    ),
                )
            )
            result.status = Status.FAIL if high_sev else Status.WARN
            result.score = Scale.mean(result.findings)
        elif kind == "consistent":
            result.findings.append(
                SCALE.finding(
                    "quality_judge.verdict",
                    "consistent",
                    id="quality_judge.consistent",
                    title="LLM judge: behavior consistent with claimed model",
                    summary=(
                        f"Judge ({confidence or 'unspecified'} confidence) found the answers "
                        f"consistent with '{claimed}'."
                    ),
                    evidence={"judge_confidence": confidence or None, "reasoning": reasoning},
                )
            )
            result.status = Status.PASS
            result.score = Scale.mean(result.findings)
        else:
            # "inconclusive", an unrecognized verdict, or a judge error.
            result.findings.append(
                SCALE.finding(
                    "quality_judge.verdict",
                    "inconclusive",
                    id="quality_judge.inconclusive",
                    title="LLM judge: assessment inconclusive",
                    summary=(
                        verdict.get("_error")
                        or f"Judge could not commit to a verdict for '{claimed}'."
                    ),
                    evidence={"judge_confidence": confidence or None, "reasoning": reasoning},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None

        return result

    # -- internals --------------------------------------------------------- #
    async def _ask(self, client, prompt: str) -> CompletionOutcome:
        """Issue one probe at temp 0; never raise on a misbehaving relay."""
        spec = RequestSpec(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=400,
        )
        try:
            return await client.complete(spec)
        except Exception as exc:  # defensive: client should not raise, but a relay may surprise us
            return CompletionOutcome(ok=False, error_message=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _extract(outcome: CompletionOutcome) -> str | None:
        if outcome.ok and outcome.has_content():
            return outcome.content.strip()[:_ANSWER_CLIP]
        return None

    @staticmethod
    def _build_user_prompt(
        claimed: str,
        target_answers: list[dict[str, Any]],
        baseline_answers: list[dict[str, Any]],
        ctx: AuditContext,
    ) -> str:
        lines: list[str] = []
        family = ctx.profile.model.family if ctx.profile else None
        cutoff = ctx.profile.model.knowledge_cutoff if ctx.profile else None
        ctx_bits = [prompts.text("quality_judge.user.claimed", claimed=claimed)]
        if family:
            ctx_bits.append(prompts.text("quality_judge.user.family", family=family))
        if cutoff:
            ctx_bits.append(prompts.text("quality_judge.user.cutoff", cutoff=cutoff))
        lines.append(prompts.text("quality_judge.user.context", bits="; ".join(ctx_bits)))
        lines.append("")
        lines.append(
            prompts.text(
                "quality_judge.user.intro",
                with_baseline=prompts.text("quality_judge.user.with_baseline") if baseline_answers else "",
            )
        )

        baseline_by_label = {b["label"]: b["answer"] for b in baseline_answers}
        for i, item in enumerate(target_answers, start=1):
            lines.append("")
            no_answer = prompts.text("quality_judge.user.no_answer")
            lines.append(prompts.text("quality_judge.user.prompt_heading", n=i, label=item["label"]))
            lines.append(item["prompt"])
            lines.append("")
            lines.append(prompts.text("quality_judge.user.target_heading"))
            lines.append(item["answer"] or no_answer)
            if item["label"] in baseline_by_label:
                lines.append("")
                lines.append(prompts.text("quality_judge.user.baseline_heading"))
                lines.append(baseline_by_label[item["label"]] or no_answer)

        lines.append("")
        lines.append(prompts.text("quality_judge.user.instructions"))
        return "\n".join(lines)
