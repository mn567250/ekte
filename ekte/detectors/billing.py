"""Token/usage billing audit.

Sends one bounded request with a fixed, known-size prompt and compares the
relay's reported ``usage`` against an independent token estimate. The estimate is
always heuristic (ekte ships no tokenizer and downloads none), so we tolerate wide
margins and flag only gross deviations — inflated counts that would overbill the
buyer, missing accounting that makes billing unverifiable, or internally
inconsistent totals.

Scoring follows the published ``SCALE`` (method "deductions"): the score starts
at 100 and each problem caps it (inflated tokens at 55, no usage at 75, ...);
the lowest cap wins.
"""

from __future__ import annotations

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import usage_field
from ekte.detectors.scale import DeductionScale, outcome
from ekte.models import DetectorResult, Dimension, RequestSpec, Severity, Status
from ekte.utils.tokenize import estimate_messages_tokens, estimate_tokens

# The probe summarizes a fixed paragraph (~110 words, "billing.known_paragraph" in
# ekte/prompts/en.json) so the prompt size is stable across runs.

# Finding titles spelled out (not built from the label), so every title the
# detector can emit is a fixed string the locales translate.
_UNDERCOUNT_TITLE = {
    "prompt": "Reported prompt tokens well below estimate",
    "completion": "Reported completion tokens well below estimate",
}

SCALE = DeductionScale(
    outcome("billing.request-failed", "no_response", None, Status.INCONCLUSIVE, Severity.LOW,
            label="No usable response to judge by."),
    outcome("billing.missing-usage", "missing", None, Status.WARN, Severity.MEDIUM, cap=75.0,
            label="The response carried no token usage at all."),
    outcome("billing.usage-inflation", "inflated", None, Status.FAIL, Severity.HIGH, cap=55.0,
            label="Reported prompt tokens far exceed the independent estimate."),
    outcome("billing.usage-inflation-completion", "above_heuristic", None, Status.WARN,
            Severity.MEDIUM, cap=70.0,
            label="Reported completion tokens are far above a heuristic estimate."),
    outcome("billing.reasoning-tokens", "hidden_reasoning", None, Status.INFO,
            label="Completion tokens exceed the visible text, as expected for a reasoning model."),
    outcome("billing.usage-undercount-prompt", "below_estimate", None, Status.INFO,
            label="Reported prompt tokens are well below the estimate (not buyer-harmful)."),
    outcome("billing.usage-undercount-completion", "below_estimate", None, Status.INFO,
            label="Reported completion tokens are well below the estimate (not buyer-harmful)."),
    outcome("billing.total-mismatch", "mismatch", None, Status.WARN, Severity.LOW, cap=90.0,
            label="The reported total does not equal prompt + completion tokens."),
    outcome("billing.partial-usage", "partial", None, Status.WARN, Severity.MEDIUM, cap=80.0,
            label="Usage reports a total without the prompt/completion split."),
    outcome("billing.usage-consistent", "consistent", None, Status.PASS,
            label="Reported usage is within tolerance of the independent estimate."),
)


@register
class BillingDetector(Detector):
    id = "billing"
    name = "Token/usage billing audit"
    dimension = Dimension.BILLING
    min_suite = "standard"
    cost_hint = 1

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        tok = ctx.tokenizer_hint()

        spec = RequestSpec(
            messages=[
                {
                    "role": "user",
                    "content": prompts.text(
                        "billing.summarize", paragraph=prompts.get("billing.known_paragraph")
                    ),
                }
            ],
            temperature=0.0,
            max_tokens=120,
        )
        outcome = await ctx.client.complete(spec)

        # Bail only when there's truly nothing to assess. A reasoning model can return
        # valid usage with EMPTY visible content (budget spent thinking) — keep going so
        # the prompt-token padding check still runs even then.
        if not outcome.ok or (not outcome.has_content() and outcome.usage is None):
            result.findings.append(
                SCALE.finding(
                    "billing.request-failed",
                    "no_response",
                    title="Billing probe request failed",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None  # nothing measured: not scored
            return result

        est_prompt = estimate_messages_tokens(spec.messages, tok)
        est_completion = estimate_tokens(outcome.content, tok)

        usage = outcome.usage
        prompt = usage_field(usage, "prompt_tokens", "input_tokens")
        completion = usage_field(usage, "completion_tokens", "output_tokens")
        total = usage_field(usage, "total_tokens")

        ratio_prompt = (prompt / est_prompt) if (prompt is not None and est_prompt > 0) else None
        ratio_completion = (
            (completion / est_completion) if (completion is not None and est_completion > 0) else None
        )

        result.evidence = {
            "reported": {"prompt": prompt, "completion": completion, "total": total},
            "estimated": {"prompt": est_prompt, "completion": est_completion},
            "ratio_prompt": round(ratio_prompt, 3) if ratio_prompt is not None else None,
            "ratio_completion": round(ratio_completion, 3) if ratio_completion is not None else None,
            "tokenizer": tok,
            "estimate_note": (
                "Token counts are heuristic estimates (no tokenizer is used); "
                "treat them as ~±25%."
            ),
        }

        # No usage block at all — billing cannot be independently verified.
        if prompt is None and completion is None and total is None:
            result.findings.append(
                SCALE.finding(
                    "billing.missing-usage",
                    "missing",
                    title="No usage accounting returned",
                    summary="Response omitted token usage; billing is unverifiable.",
                    evidence={"usage_present": usage is not None},
                    recommendation="Confirm with the provider how usage is metered if billing is per-token.",
                )
            )
            result.status = Status.WARN
            result.score = SCALE.total(result.findings)
            return result

        worst = Status.PASS
        reasoning = bool(ctx.profile and ctx.profile.model.reasoning)

        # Prompt-token inflation (the buyer-harmful direction). The prompt has no
        # hidden tokens, but the estimate is heuristic, so the margin is wide enough
        # that CJK / aggressive-split tokenizers aren't flagged.
        if (
            prompt is not None
            and prompt > 2.5 * est_prompt
            and prompt > est_prompt + 50
        ):
            result.findings.append(
                SCALE.finding(
                    "billing.usage-inflation",
                    "inflated",
                    title="Reported prompt tokens far exceed estimate",
                    summary=(
                        f"Reported prompt tokens ({prompt}) far exceed independent "
                        f"estimate (~{est_prompt})."
                    ),
                    evidence={"reported_prompt": prompt, "estimated_prompt": est_prompt, "ratio": ratio_prompt, "exact_tokenizer": False},
                    recommendation="Cross-check billing against a known-size prompt; possible per-token overbilling.",
                )
            )
            worst = Status.FAIL

        # Completion-token inflation — the trickiest. For a REASONING model the
        # reported completion legitimately includes hidden reasoning/thinking tokens
        # that our visible-text estimate cannot see, so a higher count is EXPECTED,
        # not inflation. The completion estimate is heuristic and short outputs make
        # it noisy, so only a gross divergence is flagged, and only as a soft WARN.
        if completion is not None and est_completion > 0:
            comp_ratio = completion / est_completion
            if reasoning:
                if comp_ratio > 1.5:
                    result.findings.append(
                        SCALE.finding(
                            "billing.reasoning-tokens",
                            "hidden_reasoning",
                            title="Completion tokens exceed visible text (reasoning model)",
                            summary=(
                                f"Reported completion tokens ({completion}) exceed the visible-text "
                                f"estimate (~{est_completion}); expected for a reasoning model whose "
                                "completion count includes hidden reasoning tokens. Not treated as inflation."
                            ),
                            evidence={"reported_completion": completion, "visible_estimate": est_completion, "ratio": round(comp_ratio, 2)},
                        )
                    )
            elif comp_ratio > 3.0 and completion > est_completion + 80:
                # Non-reasoning: the estimate is approximate, so a gross divergence
                # is only a soft signal worth a second look.
                result.findings.append(
                    SCALE.finding(
                        "billing.usage-inflation-completion",
                        "above_heuristic",
                        title="Reported completion tokens well above heuristic estimate",
                        summary=(
                            f"Reported completion tokens ({completion}) are far above the "
                            f"heuristic estimate (~{est_completion}); the estimate is approximate, "
                            "so corroborate before concluding overbilling."
                        ),
                        evidence={"reported_completion": completion, "estimated_completion": est_completion, "ratio": round(comp_ratio, 2), "exact_tokenizer": False},
                        recommendation="Compare token accounting against a trusted baseline of the same model.",
                    )
                )
                if worst == Status.PASS:
                    worst = Status.WARN

        # Severe under-count: cheaper for the buyer, so only an informational note.
        for label, reported, estimated in (
            ("prompt", prompt, est_prompt),
            ("completion", completion, est_completion),
        ):
            if reported is not None and estimated > 0 and reported < 0.5 * estimated:
                result.findings.append(
                    SCALE.finding(
                        f"billing.usage-undercount-{label}",
                        "below_estimate",
                        title=_UNDERCOUNT_TITLE[label],
                        summary=(
                            f"Reported {label} tokens ({reported}) are far below the "
                            f"estimate (~{estimated}); not buyer-harmful but unusual."
                        ),
                        evidence={f"reported_{label}": reported, f"estimated_{label}": estimated},
                    )
                )

        # Internal consistency of the reported total.
        if (
            total is not None
            and prompt is not None
            and completion is not None
            and abs(total - (prompt + completion)) > 2
        ):
            result.findings.append(
                SCALE.finding(
                    "billing.total-mismatch",
                    "mismatch",
                    title="Usage total != prompt + completion",
                    summary=(
                        f"Reported total ({total}) does not equal prompt "
                        f"({prompt}) + completion ({completion})."
                    ),
                    evidence={"total": total, "prompt": prompt, "completion": completion},
                )
            )
            if worst == Status.PASS:
                worst = Status.WARN

        # Within tolerance and accounted for — but only if the per-direction
        # breakdown is actually present. A response that reports only total_tokens
        # (prompt/completion missing) cannot be confirmed "consistent": the split
        # billing depends on was never validated.
        if worst == Status.PASS:
            if prompt is None or completion is None:
                result.findings.append(
                    SCALE.finding(
                        "billing.partial-usage",
                        "partial",
                        title="Incomplete usage breakdown",
                        summary=(
                            f"Usage reports only total={total} (prompt={prompt}, "
                            f"completion={completion}); the per-direction split that "
                            "per-token billing depends on is missing and unverifiable."
                        ),
                        evidence={"reported_prompt": prompt, "reported_completion": completion, "reported_total": total},
                        recommendation="Confirm with the provider how prompt/completion tokens are metered.",
                    )
                )
                worst = Status.WARN
            else:
                result.findings.append(
                    SCALE.finding(
                        "billing.usage-consistent",
                        "consistent",
                        title="Usage consistent with independent estimate",
                        summary=(
                            f"Reported prompt={prompt}, completion={completion} within "
                            f"tolerance of estimate (~{est_prompt}/~{est_completion})."
                        ),
                        evidence={"ratio_prompt": ratio_prompt, "ratio_completion": ratio_completion},
                    )
                )

        result.status = worst
        result.score = SCALE.total(result.findings)
        return result
