"""Token/usage billing audit.

Sends the same bounded summarization probe at three prompt sizes (about 150, 600
and 2,400 tokens, built from fixed paragraphs in ``ekte/prompts/en.json``) and
compares the relay's reported ``usage`` against an independent token estimate.

* **Slope and intercept.** Reported prompt tokens are fitted against the
  estimate: the slope is the proportional factor (inflation), the intercept a
  fixed overhead (a chat template, or a hidden system prompt the
  ``injected_prompt`` check examines). One prompt size cannot tell the two apart.
* **Baseline.** In compare mode, with a baseline on the same protocol, the same
  three prompts go to the baseline, whose ``prompt_tokens`` are exact for the
  same tokenizer; that direct comparison replaces the heuristic slope verdict.
* The estimate is always heuristic (ekte ships no tokenizer and downloads none).
  It under-counts real tokenizers by a systematic 12-15 %, so the slope bounds
  allow for that plus a dense tokenizer.

Missing accounting, a total without the split and inconsistent totals are
flagged as before. When only one of the three calls returns usable prompt
counts, the single-request check (2.5x and 50 tokens over the estimate) stands
in, with a note that the slope could not be measured.

Scoring follows the published ``SCALE`` (method "deductions"): the score starts
at 100 and each problem caps it (inflated tokens at 55, no usage at 75, ...);
the lowest cap wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ekte import prompts
from ekte.clients import Client, detect_api
from ekte.context import AuditContext
from ekte.detectors import advice
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import is_reasoning, usage_field
from ekte.detectors.scale import DeductionScale, outcome
from ekte.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    RequestSpec,
    Severity,
    Status,
)
from ekte.utils.tokenize import estimate_messages_tokens, estimate_tokens

# Prompt-token slope (reported / estimated, fitted over the three sizes). Up to
# SLOPE_PASS allows for the heuristic's under-count plus a dense tokenizer.
SLOPE_PASS = 1.35
SLOPE_FAIL = 1.6
# A fixed overhead (the fit's intercept) at or above this is more than a chat
# template adds: worth the injected_prompt check's look, not inflation.
FIXED_OVERHEAD_TOKENS = 30
# Compare mode: target prompt tokens may exceed the baseline's by this share or
# this many tokens, whichever is larger.
BASELINE_TOLERANCE_SHARE = 0.03
BASELINE_TOLERANCE_TOKENS = 5
# Single-request fallback (one usable size only): today's wide margin.
SINGLE_RATIO = 2.5
SINGLE_MARGIN = 50

# The three probe sizes: the known paragraph alone, all five paragraphs, and the
# five paragraphs four times over (about 150, 600 and 2,400 estimated tokens).
_SIZES = (("small", 1, 1), ("medium", 5, 1), ("large", 5, 4))

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
    outcome("billing.prompt-vs-baseline", "matches", None, Status.PASS,
            label="Reported prompt tokens match the baseline's for the same prompts."),
    outcome("billing.prompt-vs-baseline", "inflated", None, Status.FAIL, Severity.HIGH, cap=55.0,
            label="Reported prompt tokens exceed the baseline's for the same prompts."),
    outcome("billing.prompt-vs-baseline", "below", None, Status.INFO,
            label="Reported prompt tokens are below the baseline's (not buyer-harmful)."),
    outcome("billing.prompt-slope", "proportional", None, Status.PASS,
            label="Reported prompt tokens grow in proportion to the estimate (slope up to 1.35)."),
    outcome("billing.prompt-slope", "elevated", None, Status.WARN, Severity.MEDIUM, cap=70.0,
            label="Reported prompt tokens grow 1.35 to 1.6 times as fast as the estimate."),
    outcome("billing.prompt-slope", "inflated", None, Status.FAIL, Severity.HIGH, cap=55.0,
            label="Reported prompt tokens grow more than 1.6 times as fast as the estimate."),
    outcome("billing.prompt-slope", "unmeasured", None, Status.INFO,
            label="Only one prompt size returned usable counts; the slope could not be measured."),
    outcome("billing.fixed-overhead", "small", None, Status.INFO,
            label="A small fixed prompt-token overhead (under 30 tokens), as chat templates add."),
    outcome("billing.fixed-overhead", "large", None, Status.WARN, Severity.LOW, cap=90.0,
            label="A fixed prompt-token overhead of 30 tokens or more on every request."),
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


@dataclass
class _Call:
    """One probe size sent to the target (and, in compare mode, the baseline)."""

    size: str
    spec: RequestSpec
    est_prompt: int
    outcome: CompletionOutcome

    @property
    def usable(self) -> bool:
        # A reasoning model can return valid usage with EMPTY visible content
        # (budget spent thinking): that still counts.
        return self.outcome.ok and (self.outcome.has_content() or self.outcome.usage is not None)

    @property
    def prompt(self) -> int | None:
        return usage_field(self.outcome.usage, "prompt_tokens", "input_tokens")

    @property
    def completion(self) -> int | None:
        return usage_field(self.outcome.usage, "completion_tokens", "output_tokens")

    @property
    def total(self) -> int | None:
        return usage_field(self.outcome.usage, "total_tokens")

    @property
    def est_completion(self) -> int:
        return estimate_tokens(self.outcome.content, None)


def _probe_specs() -> list[tuple[str, RequestSpec]]:
    paragraphs = [prompts.get("billing.known_paragraph"), *prompts.get("billing.more_paragraphs")]
    out = []
    for size, count, repeat in _SIZES:
        text = "\n\n".join(paragraphs[:count] * repeat)
        spec = RequestSpec(
            messages=[{"role": "user", "content": prompts.text("billing.summarize", paragraph=text)}],
            temperature=0.0,
            max_tokens=120,
        )
        out.append((size, spec))
    return out


def fit_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least-squares ``(slope, intercept)`` of ``y`` against ``x``; None with
    fewer than two distinct ``x``."""
    if len(points) < 2:
        return None
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    var = sum((x - mx) ** 2 for x, _ in points)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / var
    return slope, my - slope * mx


def _ratio(num: int | None, den: int) -> float | None:
    return round(num / den, 3) if num is not None and den > 0 else None


@register
class BillingDetector(Detector):
    id = "billing"
    name = "Token/usage billing audit"
    dimension = Dimension.BILLING
    min_suite = "standard"
    # Three prompt sizes; compare mode sends them to the baseline too.
    cost_hint = 3

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        tok = ctx.tokenizer_hint()

        specs = _probe_specs()
        calls: list[_Call] = []
        for size, spec in specs:
            out = await ctx.client.complete(spec)
            calls.append(_Call(size, spec, estimate_messages_tokens(spec.messages, tok), out))
        usable = [c for c in calls if c.usable]

        # Bail only when there's truly nothing to assess.
        if not usable:
            first = calls[0].outcome
            result.findings.append(
                SCALE.finding(
                    "billing.request-failed",
                    "no_response",
                    recommendation=advice.failure_advice(first),
                    calls=[c.outcome for c in calls],
                    title="Billing probe request failed",
                    summary=first.error_message or f"HTTP {first.status_code}",
                    evidence={"status_code": first.status_code, "error_type": first.error_type},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None  # nothing measured: not scored
            return result

        outs = [c.outcome for c in usable]
        with_prompt = [c for c in usable if c.prompt is not None]
        with_completion = [c for c in usable if c.completion is not None]
        prompt_sum = sum(c.prompt or 0 for c in with_prompt) if with_prompt else None
        est_prompt_sum = sum(c.est_prompt for c in with_prompt) if with_prompt else sum(
            c.est_prompt for c in usable
        )
        completion_sum = sum(c.completion or 0 for c in with_completion) if with_completion else None
        est_completion_sum = sum(c.est_completion for c in (with_completion or usable))

        fit = fit_line([(float(c.est_prompt), float(c.prompt or 0)) for c in with_prompt])
        result.evidence = {
            "sizes": [
                {
                    "size": c.size,
                    "ok": c.usable,
                    "estimated_prompt": c.est_prompt,
                    "reported_prompt": c.prompt if c.usable else None,
                    "reported_completion": c.completion if c.usable else None,
                    "reported_total": c.total if c.usable else None,
                }
                for c in calls
            ],
            "reported": {"prompt": prompt_sum, "completion": completion_sum},
            "estimated": {"prompt": est_prompt_sum, "completion": est_completion_sum},
            "ratio_prompt": _ratio(prompt_sum, est_prompt_sum),
            "ratio_completion": _ratio(completion_sum, est_completion_sum),
            "slope": round(fit[0], 3) if fit else None,
            "intercept": round(fit[1], 1) if fit else None,
            "tokenizer": tok,
            "estimate_note": (
                "Token counts are heuristic estimates (no tokenizer is used); "
                "treat them as ~±25%."
            ),
        }

        # No usage block at all — billing cannot be independently verified.
        if not any(
            c.prompt is not None or c.completion is not None or c.total is not None for c in usable
        ):
            result.findings.append(
                SCALE.finding(
                    "billing.missing-usage",
                    "missing",
                    calls=outs,
                    title="No usage accounting returned",
                    summary="Response omitted token usage; billing is unverifiable.",
                    evidence={"usage_present": any(c.outcome.usage is not None for c in usable)},
                    recommendation="Confirm with the provider how usage is metered if billing is per-token.",
                )
            )
            result.status = Status.WARN
            result.score = SCALE.total(result.findings)
            return result

        worst = Status.PASS

        def worsen(status: Status) -> None:
            nonlocal worst
            rank = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}
            if rank.get(status, 0) > rank[worst]:
                worst = status

        # Prompt tokens (the buyer-harmful direction): the baseline's exact counts
        # when compare mode has them, else the slope over the three sizes, else
        # (one usable size) the single-request margin.
        baseline = await self._baseline_counts(ctx, with_prompt)
        if baseline:
            result.baseline_compared = True
            worsen(self._baseline_verdict(result, with_prompt, baseline))
        elif fit is not None:
            worsen(self._slope_verdict(result, with_prompt, fit))
        elif with_prompt:
            worsen(self._single_verdict(result, with_prompt[0]))

        # Completion-token inflation — the trickiest. For a REASONING model the
        # reported completion legitimately includes hidden reasoning/thinking tokens
        # that our visible-text estimate cannot see, so a higher count is EXPECTED,
        # not inflation. Reasoning = the profile says so, the client learned that
        # the endpoint reasons, or a response reports reasoning tokens
        # (helpers.is_reasoning). The completion estimate is heuristic and short outputs
        # make it noisy, so only a gross divergence is flagged, and only as a soft WARN.
        reasoning = is_reasoning(ctx, *(c.outcome for c in usable))
        if completion_sum is not None and est_completion_sum > 0:
            comp_ratio = completion_sum / est_completion_sum
            n = len(with_completion)
            if reasoning:
                if comp_ratio > 1.5:
                    result.findings.append(
                        SCALE.finding(
                            "billing.reasoning-tokens",
                            "hidden_reasoning",
                            calls=outs,
                            title="Completion tokens exceed visible text (reasoning model)",
                            summary=(
                                f"Reported completion tokens ({completion_sum}) exceed the visible-text "
                                f"estimate (~{est_completion_sum}); expected for a reasoning model whose "
                                "completion count includes hidden reasoning tokens. Not treated as inflation."
                            ),
                            evidence={"reported_completion": completion_sum, "visible_estimate": est_completion_sum, "ratio": round(comp_ratio, 2)},
                        )
                    )
            elif comp_ratio > 3.0 and completion_sum > est_completion_sum + 80 * n:
                # Non-reasoning: the estimate is approximate, so a gross divergence
                # is only a soft signal worth a second look.
                result.findings.append(
                    SCALE.finding(
                        "billing.usage-inflation-completion",
                        "above_heuristic",
                        calls=outs,
                        title="Reported completion tokens well above heuristic estimate",
                        summary=(
                            f"Reported completion tokens ({completion_sum}) are far above the "
                            f"heuristic estimate (~{est_completion_sum}); the estimate is approximate, "
                            "so corroborate before concluding overbilling."
                        ),
                        evidence={"reported_completion": completion_sum, "estimated_completion": est_completion_sum, "ratio": round(comp_ratio, 2), "exact_tokenizer": False},
                        recommendation="Compare token accounting against a trusted baseline of the same model.",
                    )
                )
                worsen(Status.WARN)

        # Severe under-count: cheaper for the buyer, so only an informational note.
        for label, reported, estimated in (
            ("prompt", prompt_sum, est_prompt_sum),
            ("completion", completion_sum, est_completion_sum),
        ):
            if reported is not None and estimated > 0 and reported < 0.5 * estimated:
                result.findings.append(
                    SCALE.finding(
                        f"billing.usage-undercount-{label}",
                        "below_estimate",
                        calls=outs,
                        title=_UNDERCOUNT_TITLE[label],
                        summary=(
                            f"Reported {label} tokens ({reported}) are far below the "
                            f"estimate (~{estimated}); not buyer-harmful but unusual."
                        ),
                        evidence={f"reported_{label}": reported, f"estimated_{label}": estimated},
                    )
                )

        # Internal consistency of the reported total, per request.
        mismatch = next(
            (
                c for c in usable
                if c.total is not None and c.prompt is not None and c.completion is not None
                and abs(c.total - (c.prompt + c.completion)) > 2
            ),
            None,
        )
        if mismatch is not None:
            result.findings.append(
                SCALE.finding(
                    "billing.total-mismatch",
                    "mismatch",
                    calls=[mismatch.outcome],
                    title="Usage total != prompt + completion",
                    summary=(
                        f"Reported total ({mismatch.total}) does not equal prompt "
                        f"({mismatch.prompt}) + completion ({mismatch.completion})."
                    ),
                    evidence={"total": mismatch.total, "prompt": mismatch.prompt, "completion": mismatch.completion, "size": mismatch.size},
                )
            )
            worsen(Status.WARN)

        # Within tolerance and accounted for — but only if the per-direction
        # breakdown is actually present. A response that reports only total_tokens
        # (prompt/completion missing) cannot be confirmed "consistent": the split
        # billing depends on was never validated.
        if worst == Status.PASS:
            partial = next((c for c in usable if c.prompt is None or c.completion is None), None)
            if partial is not None:
                result.findings.append(
                    SCALE.finding(
                        "billing.partial-usage",
                        "partial",
                        calls=[partial.outcome],
                        title="Incomplete usage breakdown",
                        summary=(
                            f"Usage reports only total={partial.total} (prompt={partial.prompt}, "
                            f"completion={partial.completion}); the per-direction split that "
                            "per-token billing depends on is missing and unverifiable."
                        ),
                        evidence={"reported_prompt": partial.prompt, "reported_completion": partial.completion, "reported_total": partial.total},
                        recommendation="Confirm with the provider how prompt/completion tokens are metered.",
                    )
                )
                worst = Status.WARN
            else:
                ratio_prompt = result.evidence["ratio_prompt"]
                ratio_completion = result.evidence["ratio_completion"]
                result.findings.append(
                    SCALE.finding(
                        "billing.usage-consistent",
                        "consistent",
                        calls=outs,
                        title="Usage consistent with independent estimate",
                        summary=(
                            f"Reported prompt={prompt_sum}, completion={completion_sum} within "
                            f"tolerance of estimate (~{est_prompt_sum}/~{est_completion_sum})."
                        ),
                        evidence={"ratio_prompt": ratio_prompt, "ratio_completion": ratio_completion},
                    )
                )

        result.status = worst
        result.score = SCALE.total(result.findings)
        return result

    # -- prompt-token verdicts ---------------------------------------------- #
    @staticmethod
    async def _baseline_counts(ctx: AuditContext, calls: list[_Call]) -> dict[str, tuple[int, CompletionOutcome]]:
        """The baseline's ``prompt_tokens`` per size for the same prompts, when
        compare mode has a baseline of the same model on the target's protocol
        (another model may count with another tokenizer)."""
        client: Client | None = ctx.baseline_client
        if client is None or ctx.baseline is None or not calls:
            return {}
        if detect_api(ctx.baseline) != detect_api(ctx.target) or ctx.baseline.claimed != ctx.target.claimed:
            return {}
        out: dict[str, tuple[int, CompletionOutcome]] = {}
        for c in calls:
            base = await client.complete(c.spec)
            prompt = usage_field(base.usage, "prompt_tokens", "input_tokens") if base.ok else None
            if prompt is not None:
                out[c.size] = (prompt, base)
        return out

    @staticmethod
    def _baseline_verdict(
        result: DetectorResult, calls: list[_Call], baseline: dict[str, tuple[int, CompletionOutcome]]
    ) -> Status:
        pairs = [(c, *baseline[c.size]) for c in calls if c.size in baseline]
        rows: list[dict[str, Any]] = []
        worst: tuple[float, _Call, int] | None = None
        for c, base_prompt, _ in pairs:
            target_prompt = c.prompt or 0
            allowed = max(BASELINE_TOLERANCE_SHARE * base_prompt, BASELINE_TOLERANCE_TOKENS)
            excess = target_prompt - base_prompt
            rows.append({"size": c.size, "target_prompt": target_prompt, "baseline_prompt": base_prompt, "excess": excess})
            over = excess - allowed
            if worst is None or over > worst[0]:
                worst = (over, c, base_prompt)
        assert worst is not None
        over, c, base_prompt = worst
        target_prompt = c.prompt or 0
        evidence = {
            "target_prompt": target_prompt,
            "baseline_prompt": base_prompt,
            "excess_pct": round(100 * (target_prompt - base_prompt) / base_prompt, 1) if base_prompt else None,
            "size": c.size,
            "sizes": rows,
            "tolerance": f"{round(BASELINE_TOLERANCE_SHARE * 100)}% or {BASELINE_TOLERANCE_TOKENS} tokens",
        }
        out_calls = [c.outcome for c, _, _ in pairs] + [b for _, _, b in pairs]
        if over > 0:
            result.findings.append(
                SCALE.finding(
                    "billing.prompt-vs-baseline",
                    "inflated",
                    calls=out_calls,
                    title="Reported prompt tokens exceed the baseline",
                    summary=(
                        f"For the same prompt the target reported {target_prompt} prompt tokens, "
                        f"the baseline {base_prompt} (more than 3% or 5 tokens over)."
                    ),
                    evidence=evidence,
                    recommendation="Compare billed prompt tokens with the baseline's; the relay over-reports input tokens.",
                )
            )
            return Status.FAIL
        below = all((c.prompt or 0) < b - max(BASELINE_TOLERANCE_SHARE * b, BASELINE_TOLERANCE_TOKENS)
                    for c, b, _ in pairs)
        result.findings.append(
            SCALE.finding(
                "billing.prompt-vs-baseline",
                "below" if below else "matches",
                calls=out_calls,
                title=(
                    "Reported prompt tokens below the baseline" if below
                    else "Reported prompt tokens match the baseline"
                ),
                summary=(
                    f"For the same prompt the target reported {target_prompt} prompt tokens, "
                    f"the baseline {base_prompt}."
                ),
                evidence=evidence,
            )
        )
        return Status.PASS

    @staticmethod
    def _slope_verdict(result: DetectorResult, calls: list[_Call], fit: tuple[float, float]) -> Status:
        slope, intercept = round(fit[0], 3), round(fit[1], 1)
        evidence = {
            "slope": slope,
            "intercept": intercept,
            "sizes": len(calls),
            "points": [{"size": c.size, "estimated_prompt": c.est_prompt, "reported_prompt": c.prompt} for c in calls],
            "exact_tokenizer": False,
        }
        outs = [c.outcome for c in calls]
        if slope > SLOPE_PASS:
            fail = slope > SLOPE_FAIL
            result.findings.append(
                SCALE.finding(
                    "billing.prompt-slope",
                    "inflated" if fail else "elevated",
                    calls=outs,
                    title=(
                        "Reported prompt tokens grow far faster than the estimate" if fail
                        else "Reported prompt tokens grow faster than the estimate"
                    ),
                    summary=(
                        f"Across {len(calls)} prompt sizes the reported prompt tokens grow {slope}x "
                        f"as fast as the independent estimate (expected up to {SLOPE_PASS}x)."
                    ),
                    evidence=evidence,
                    recommendation="Cross-check billing against a known-size prompt; possible per-token overbilling.",
                )
            )
            return Status.FAIL if fail else Status.WARN
        result.findings.append(
            SCALE.finding(
                "billing.prompt-slope",
                "proportional",
                calls=outs,
                title="Reported prompt tokens proportional to the estimate",
                summary=(
                    f"Across {len(calls)} prompt sizes the reported prompt tokens grow {slope}x "
                    "as fast as the independent estimate."
                ),
                evidence=evidence,
            )
        )
        # A fixed overhead with a normal slope is not inflation.
        large = intercept >= FIXED_OVERHEAD_TOKENS
        result.findings.append(
            SCALE.finding(
                "billing.fixed-overhead",
                "large" if large else "small",
                calls=outs,
                title=(
                    "Large fixed prompt-token overhead" if large
                    else "Small fixed prompt-token overhead"
                ),
                summary=(
                    f"Every request carries about {intercept} prompt tokens more than the estimate, "
                    "whatever its size."
                ),
                evidence={"intercept": intercept, "slope": slope},
                recommendation=(
                    "A fixed overhead this large suggests a hidden system prompt; "
                    "run the injected_prompt check (deep suite) to examine it."
                    if large else None
                ),
            )
        )
        return Status.WARN if large else Status.PASS

    @staticmethod
    def _single_verdict(result: DetectorResult, call: _Call) -> Status:
        prompt, est = call.prompt or 0, call.est_prompt
        result.findings.append(
            SCALE.finding(
                "billing.prompt-slope",
                "unmeasured",
                id="billing.prompt-slope-unmeasured",
                calls=[call.outcome],
                title="Prompt-token slope not measured",
                summary=(
                    "Only one of the prompt sizes returned usable token counts, so a fixed "
                    "overhead cannot be told from proportional inflation; the single-request "
                    "margin applies."
                ),
                evidence={"size": call.size, "reported_prompt": prompt, "estimated_prompt": est},
            )
        )
        if prompt > SINGLE_RATIO * est and prompt > est + SINGLE_MARGIN:
            result.findings.append(
                SCALE.finding(
                    "billing.usage-inflation",
                    "inflated",
                    calls=[call.outcome],
                    title="Reported prompt tokens far exceed estimate",
                    summary=(
                        f"Reported prompt tokens ({prompt}) far exceed independent "
                        f"estimate (~{est})."
                    ),
                    evidence={"reported_prompt": prompt, "estimated_prompt": est, "ratio": _ratio(prompt, est), "exact_tokenizer": False},
                    recommendation="Cross-check billing against a known-size prompt; possible per-token overbilling.",
                )
            )
            return Status.FAIL
        return Status.PASS
