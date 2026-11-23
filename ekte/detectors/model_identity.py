"""Model identity & downgrade fingerprinting — the core 货不对板 detector.

A relay can claim to serve an expensive model while quietly routing to a cheaper
substitute. This detector checks a direct self-id prompt against the genuine
brand words (and rival brands that betray a swap), the knowledge base's
pure-code behavioral fingerprints (the model's own first: only they can tell it
from a sibling of the same vendor), the self-reported knowledge cutoff against
the profile's, and the ``model`` field the relay echoes back. In compare mode
every fingerprint and the cutoff probe also go to the baseline. Divergence
between the claim and what the model actually behaves like is the signal.

Scoring follows the published ``SCALE`` (method "deductions"): the score starts
at 100, each diverging fingerprint deducts its weight share of 100 points (at
most 25), and a rival-brand contradiction caps the score at 20. When no check
produced a usable answer the detector is inconclusive and unscored.
"""

from __future__ import annotations

import re

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors import advice
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import (
    contains_all,
    contains_any,
    contains_term_any,
    contains_word,
    contains_word_any,
)
from ekte.detectors.scale import DeductionScale, evidence_seqs, outcome
from ekte.knowledge.identity import AMBIGUOUS_BRAND_WORDS, VENDOR_BRANDS, own_brand_words
from ekte.knowledge.model_ids import compare_echoed_model
from ekte.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    Finding,
    RequestSpec,
    Severity,
    Status,
)

# Known LLM vendor/brand words (incl. Chinese). A model that self-identifies with
# any of these — OTHER than its own brand — betrays a substitution, even when the KB
# profile's identity_forbidden didn't list it (e.g. a Doubao/ByteDance model resold
# as DeepSeek). Matched whole-word; the model's own brand words are removed.
# Words in AMBIGUOUS_BRAND_WORDS ("step", "meta", ...) only count in the self-id
# answer and only written as a name; see _brand_hits.
_RIVAL_BRANDS = tuple(word for vendor in VENDOR_BRANDS for word in vendor)

_SELF_ID_PROMPT = prompts.text("model_identity.self_id")

# A single fingerprint can take at most this many points; a rival-brand
# contradiction caps the whole score at _CONTRADICTION_CAP.
_MAX_FP_DEDUCTION = 25.0
_CONTRADICTION_CAP = 20.0
_NO_RESPONSE = "No usable response to judge by."  # same sentence as protocol's scale
# An ambiguous brand word as a name (see _named): what may sit before it at the
# start of a sentence or list item, what ends a sentence, and the version or
# model-letter suffix that makes it a model name in any case ("grok-2", "Yi-34B",
# "Command R").
_LEAD = " \t\"'*_(`#>•·-"
_LIST_NUMBER = re.compile(r"(?:^|\n)[ \t]*\d+[.)]$")
_SENTENCE_END = ".!?\n。！？"
_VERSION = re.compile(r"-?\d|\s[A-Z](?![A-Za-z])")


def _named(text: str, word: str) -> bool:
    """Whole-word match of ``word`` written as a name, not the everyday word:
    with a version attached in any case ("grok-2", "Step-2", "Command R"), or
    capitalised ("Meta") or in capitals ("META") inside a sentence. At the start
    of a sentence or list item a capital proves nothing ("Step by step ..."), nor
    does a compound with a lower-case word ("Meta-analysis")."""
    w = word.strip().lower()
    if not w:
        return False
    text = text or ""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])(?!-[a-z])"
    for m in re.finditer(pattern, text, re.IGNORECASE):
        if _VERSION.match(text, m.end()):
            return True
        if m.group(0) not in (w.capitalize(), w.upper()):
            continue
        before = text[: m.start()].rstrip(_LEAD)
        if before and before[-1] not in _SENTENCE_END and not _LIST_NUMBER.search(before):
            return True
    return False


def _brand_hits(text: str, words: list[str], *, ambiguous: bool) -> list[str]:
    """The ``words`` present in ``text`` as whole words. An ambiguous brand word
    (AMBIGUOUS_BRAND_WORDS, also everyday English) counts only with
    ``ambiguous`` and only written as a name; without it, it never counts."""
    hits: list[str] = []
    for word in words or []:
        if word.strip().lower() in AMBIGUOUS_BRAND_WORDS:
            if ambiguous and _named(text, word):
                hits.append(word)
        elif contains_word(text, word):
            hits.append(word)
    return hits


SCALE = DeductionScale(
    outcome("model_identity.self_id", "consistent", None, Status.PASS,
            label="The self-description named the genuine brand."),
    outcome("model_identity.self_id", "rival_brand", None, Status.FAIL, Severity.HIGH,
            cap=_CONTRADICTION_CAP,
            label="The self-description named a rival brand and not the genuine one."),
    outcome("model_identity.self_id", "both_brands", None, Status.WARN, Severity.LOW,
            label="The self-description named the genuine brand and a rival (usually a benign contrast)."),
    outcome("model_identity.self_id", "evasive", None, Status.WARN, Severity.LOW,
            label="The self-description named neither the genuine brand nor a rival."),
    outcome("model_identity.self_id", "unavailable", None, Status.INCONCLUSIVE,
            label=_NO_RESPONSE),
    outcome("model_identity.fp", "consistent", None, Status.PASS,
            label="The answer matched the claimed model's native behavior."),
    outcome("model_identity.fp", "diverged", None, Status.WARN, Severity.LOW,
            max_deduction=_MAX_FP_DEDUCTION,
            label="The answer diverged from native behavior: deducts the probe's weight share of 100 points."),
    outcome("model_identity.fp", "corroborated", None, Status.WARN, Severity.MEDIUM,
            max_deduction=_MAX_FP_DEDUCTION,
            label="The answer diverged from native behavior while the baseline's matched it: "
                  "deducts the probe's weight share of 100 points."),
    outcome("model_identity.fp", "baseline_also_diverged", None, Status.INFO,
            label="The answer diverged, but so did the baseline's: a knowledge-base problem, "
                  "not relay evidence; no deduction."),
    outcome("model_identity.fp", "rival_brand", None, Status.FAIL, Severity.HIGH,
            max_deduction=_MAX_FP_DEDUCTION, cap=_CONTRADICTION_CAP,
            label="The answer named a rival brand and not the genuine one: deducts the probe's weight share."),
    outcome("model_identity.fp", "inconclusive", None, Status.INCONCLUSIVE,
            label=_NO_RESPONSE),
    outcome("model_identity.fp", "skipped_output_cap", None, Status.INFO,
            label="The probe needs more output than the 512-token identity cap; not run."),
    outcome("model_identity.cutoff", "consistent", None, Status.PASS,
            label="The reported knowledge cutoff is within 6 months of the claimed model's."),
    outcome("model_identity.cutoff", "earlier", None, Status.WARN, Severity.LOW,
            max_deduction=_MAX_FP_DEDUCTION,
            label="The reported knowledge cutoff is more than 12 months earlier than the claimed "
                  "model's: deducts its weight share of 100 points like a fingerprint."),
    outcome("model_identity.cutoff", "corroborated", None, Status.WARN, Severity.MEDIUM,
            max_deduction=_MAX_FP_DEDUCTION,
            label="The reported knowledge cutoff is more than 12 months earlier while the "
                  "baseline's is consistent: deducts its weight share of 100 points."),
    outcome("model_identity.cutoff", "baseline_also_diverged", None, Status.INFO,
            label="The reported knowledge cutoff is more than 12 months earlier, but so is the "
                  "baseline's: a knowledge-base problem, not relay evidence; no deduction."),
    outcome("model_identity.cutoff", "differs", None, Status.INFO,
            label="The reported knowledge cutoff is off by more than 6 months, but not more than "
                  "12 months earlier: recorded, not judged."),
    outcome("model_identity.cutoff", "inconclusive", None, Status.INCONCLUSIVE,
            label="No answer in the CUTOFF=YYYY-MM format to judge by."),
    outcome("model_identity.fp_aggregate", "diverged", None, Status.WARN, Severity.MEDIUM,
            label="Two or more behavioral fingerprints diverged."),
    outcome("model_identity.model_field", "consistent", None, Status.PASS,
            label="The echoed model field matched the requested model."),
    outcome("model_identity.model_field", "diverges", None, Status.WARN, Severity.MEDIUM,
            label="The echoed model field names a different or smaller model."),
    outcome("model_identity.model_field", "unknown", None, Status.INFO,
            label="The echoed model field names a different id that ekte cannot place: recorded, not judged."),
    outcome("model_identity.model_field", "unavailable", None, Status.INCONCLUSIVE,
            label="The response had no usable model field."),
    outcome("model_identity.model_specific", "vendor_only", None, Status.INFO,
            label="No check could tell the claimed model from other models of its vendor and no "
                  "baseline or judge was used: the vendor is consistent, the specific model was "
                  "not verified."),
    outcome("model_identity.no_evidence", "none", None, Status.INCONCLUSIVE,
            label="No self-identification or fingerprint answer was usable and the model "
                  "field did not diverge: not scored."),
    titles={"model_identity.fp": "Behavioral fingerprints"},
)

# The self-reported knowledge cutoff (prompt model_identity.cutoff): within
# _CUTOFF_TOLERANCE months of the profile's it is consistent; more than
# _CUTOFF_EARLIER months earlier it diverges. Self-reported cutoffs are soft
# evidence, so the check weighs like one fingerprint and is never HIGH.
_CUTOFF_PROMPT = prompts.text("model_identity.cutoff")
_CUTOFF_ANSWER = re.compile(r"CUTOFF\s*[=:]\s*(\d{4})\s*[-/.]\s*(\d{1,2})(?!\d)", re.IGNORECASE)
_CUTOFF_TOLERANCE = 6
_CUTOFF_EARLIER = 12
_CUTOFF_WEIGHT = 1.0
_CUTOFF_SIGNAL = "self-reported knowledge cutoff"
_CUTOFF_MAX_TOKENS = 64


def parse_cutoff(text: str | None) -> tuple[int, int] | None:
    """The (year, month) of a ``CUTOFF=YYYY-MM`` answer, or None."""
    m = _CUTOFF_ANSWER.search(text or "")
    if not m or not 1 <= int(m[2]) <= 12:
        return None
    return int(m[1]), int(m[2])


def _months(ym: tuple[int, int]) -> int:
    return ym[0] * 12 + ym[1] - 1


def _ym(ym: tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def _cutoff_verdict(answer: tuple[int, int] | None, claimed: tuple[int, int]) -> str:
    """``consistent`` / ``earlier`` / ``differs`` / ``inconclusive``."""
    if answer is None:
        return "inconclusive"
    delta = _months(answer) - _months(claimed)
    if abs(delta) <= _CUTOFF_TOLERANCE:
        return "consistent"
    if delta < -_CUTOFF_EARLIER:
        return "earlier"
    return "differs"


class _Tally:
    """What the fingerprint and cutoff checks add up to across probes."""

    def __init__(self, total_weight: float) -> None:
        self.total_weight = total_weight
        self.violated = 0
        self.soft_violations: list[str] = []
        self.diverged_calls: list[CompletionOutcome] = []
        self.high = False
        self.medium = False

    def deduction(self, weight: float) -> float:
        """A diverging probe's weight share of 100 points, capped so one
        fragile fingerprint can't tank the identity score on its own."""
        if self.total_weight <= 0:
            return 0.0
        return min((max(weight, 0.0) / self.total_weight) * 100.0, _MAX_FP_DEDUCTION)


@register
class ModelIdentityDetector(Detector):
    id = "model_identity"
    name = "Model identity & downgrade fingerprinting"
    dimension = Dimension.MODEL_IDENTITY
    min_suite = "standard"
    cost_hint = 10

    # Cap on fingerprint probes actually issued (cost control, ~8-call budget).
    MAX_FINGERPRINTS = 6
    # Hard ceiling on output tokens per fingerprint probe. Identity fingerprints
    # only need a short answer; without this a KB probe declaring max_tokens=40000
    # (e.g. a max-output check) would bill tens of thousands of tokens per audit
    # for zero identity signal. The real max-output test lives in capability.py.
    MAX_FINGERPRINT_OUTPUT = 512

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result()

        if ctx.profile is None:
            result.findings.append(
                Finding(
                    evidence_seqs=evidence_seqs([]),
                    id="model_identity.no_profile",
                    title="Claimed model not in knowledge base",
                    status=Status.INCONCLUSIVE,
                    severity=Severity.INFO,
                    summary=(
                        "Claimed model not found in knowledge base; "
                        "pass --declared-provider or add a KB profile."
                    ),
                    evidence={"claimed_model": ctx.target.claimed, "requested_model": ctx.target.model},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
            return result

        result.scoring = SCALE.scoring()
        model = ctx.profile.model
        has_high = False
        has_medium = False

        # 1) Direct self-identification + brand check. -------------------- #
        forbidden_hit = await self._check_self_id(ctx, model, result)
        if forbidden_hit:
            has_high = True

        # 2) Pure-code behavioral fingerprints. -------------------------- #
        # The model's own probes go first, so the slice below never drops the
        # only ones that can tell it from a sibling of the same vendor.
        own = ctx.profile.model.fingerprints
        probes = [
            fp for fp in (*own, *ctx.profile.provider.fingerprints) if fp.pure_code_checkable
        ]
        # A probe whose expected answer needs more output than the cap (e.g. a
        # count-to-4000 max-output check) would diverge on every genuine model.
        # Skip it before the slice so another probe takes its slot; it counts
        # toward neither the weights, the violations nor the aggregate.
        skipped = [fp for fp in probes if fp.max_tokens > self.MAX_FINGERPRINT_OUTPUT]
        probes = [fp for fp in probes if fp.max_tokens <= self.MAX_FINGERPRINT_OUTPUT]
        probes = probes[: self.MAX_FINGERPRINTS]
        for fp in skipped:
            result.findings.append(
                SCALE.finding(
                    "model_identity.fp",
                    "skipped_output_cap",
                    recommendation=advice.BY_DESIGN,
                    calls=[],
                    id=f"model_identity.fp.{fp.id}",
                    title=f"Fingerprint skipped: {fp.signal}",
                    summary=(
                        f"Probe '{fp.signal}' needs up to {fp.max_tokens} output tokens, more "
                        f"than the {self.MAX_FINGERPRINT_OUTPUT}-token identity cap; not run."
                    ),
                    evidence={
                        "probe": fp.id,
                        "max_tokens": fp.max_tokens,
                        "output_cap": self.MAX_FINGERPRINT_OUTPUT,
                    },
                )
            )
        # The knowledge-cutoff probe runs when the profile names a cutoff month
        # and weighs like one fingerprint.
        claimed_cutoff = model.cutoff_month()
        total_weight = sum(max(fp.weight, 0.0) for fp in probes)
        if claimed_cutoff is not None:
            total_weight += _CUTOFF_WEIGHT
        # Non-identity (behavioral) fingerprint divergences are individually noisy,
        # so a single one stays LOW and does not escalate overall risk; two or more
        # together raise a MEDIUM aggregate, and a baseline that answers natively
        # where the target diverges raises the divergence itself to MEDIUM.
        tally = _Tally(total_weight)
        own_ids = {id(fp) for fp in own}
        model_specific = 0
        for fp in probes:
            got_answer = await self._run_fingerprint(ctx, fp, model, result, tally)
            if got_answer and id(fp) in own_ids:
                model_specific += 1
        if claimed_cutoff is not None:
            await self._check_cutoff(ctx, claimed_cutoff, result, tally)
        if tally.high:
            has_high = True
        if tally.medium:
            has_medium = True

        # Two or more behavioral divergences together justify a MEDIUM aggregate.
        soft_violations = tally.soft_violations
        if len(soft_violations) >= 2:
            has_medium = True
            result.findings.append(
                SCALE.finding(
                    "model_identity.fp_aggregate",
                    "diverged",
                    calls=tally.diverged_calls,
                    title="Multiple behavioral fingerprints diverged",
                    summary=(
                        f"{len(soft_violations)} pure-code fingerprints diverged from native "
                        f"{model.id} behavior ({', '.join(soft_violations)}); investigate "
                        f"possible substitution."
                    ),
                    evidence={"diverged": soft_violations},
                    recommendation="Run `ekte compare` against a trusted baseline to corroborate.",
                )
            )

        # 3) Echoed model field on a plain call. ------------------------- #
        field_diverges = await self._check_model_field(ctx, result)
        if field_diverges:
            has_medium = True

        # Score & status. ----------------------------------------------- #
        # No usable answer to judge identity by (errors, empty answers, skipped
        # probes): the detector must not read as a clean 100. A matching echoed
        # model field alone is no evidence, since a relay can echo any requested
        # name; a diverging one is. Partial evidence still scores normally.
        answered = [
            f for f in result.findings
            if f.id != "model_identity.model_field"
            and f.status not in (Status.INCONCLUSIVE, Status.INFO)
        ]
        if not answered and not field_diverges:
            result.findings.append(
                SCALE.finding(
                    "model_identity.no_evidence",
                    "none",
                    recommendation=advice.NO_IDENTITY_EVIDENCE,
                    title="No usable identity evidence",
                    summary=(
                        "Neither the self-identification nor any fingerprint probe returned a "
                        "usable answer, and the echoed model field shows no divergence; "
                        "identity could not be judged."
                    ),
                    # The identity questions asked: self-id, each fingerprint
                    # run and the cutoff probe.
                    evidence={"checks": 1 + len(probes) + int(claimed_cutoff is not None)},
                )
            )
            result.score = None
            result.status = Status.INCONCLUSIVE
        else:
            if not has_high and model_specific == 0 and not ctx.has_baseline and not ctx.has_judge:
                # Honest wording: every check that ran holds for any model of
                # the vendor, so a same-vendor substitute would pass them too.
                vendor = ctx.profile.provider.display_name or ctx.profile.provider.provider
                result.findings.append(
                    SCALE.finding(
                        "model_identity.model_specific",
                        "vendor_only",
                        recommendation=advice.VERIFY_SPECIFIC_MODEL,
                        calls=[],
                        title="Specific model not verified",
                        summary=(
                            f"The answers are consistent with the vendor ({vendor}), but no check "
                            f"can tell {model.id} from the vendor's other models and no baseline "
                            "or judge was used: the specific model was not verified."
                        ),
                        evidence={"model_specific_checks": 0, "vendor": vendor, "model": model.id},
                    )
                )
            result.score = SCALE.total(result.findings)
            if has_high:
                result.status = Status.FAIL
            elif has_medium or soft_violations:
                result.status = Status.WARN
            else:
                result.status = Status.PASS

        result.evidence["fingerprints_run"] = len(probes)
        # Languages of the fingerprint prompts actually sent (see prompt_lang in
        # the knowledge base); the runner records them on the report.
        result.evidence["fingerprint_prompt_langs"] = sorted({fp.prompt_lang for fp in probes})
        result.evidence["fingerprints_violated"] = tally.violated
        result.evidence["fingerprints_skipped"] = [fp.id for fp in skipped]
        # Answered probes that can tell the claimed model from a same-vendor
        # sibling (its own fingerprints; see model_specific_fingerprints).
        result.evidence["model_specific_checks"] = model_specific
        result.evidence["cutoff_checked"] = claimed_cutoff is not None
        # Whether a usable baseline answer was compared (not merely configured).
        result.evidence["baseline_compared"] = result.baseline_compared
        result.evidence["match_confidence"] = ctx.profile.match_confidence
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    async def _baseline(ctx: AuditContext, spec: RequestSpec) -> CompletionOutcome | None:
        """The same request on the baseline, in compare mode; else None."""
        if not (ctx.has_baseline and ctx.baseline_client is not None):
            return None
        return await ctx.baseline_client.complete(spec)

    def _violation(self, ctx: AuditContext, fp, model, text: str) -> tuple[bool, list[str]]:
        """(violated, forbidden brand hits that contradict identity) for one
        fingerprint answer."""
        provider = ctx.profile.provider if ctx.profile is not None else None
        # Ambiguous brand words ("step by step", "a meta question") never count
        # here: a fingerprint answer is free prose, not a self-description.
        forbidden_hits = _brand_hits(text, self._forbidden_brands(model, provider), ambiguous=False)
        # A rival brand only contradicts identity when the GENUINE brand is
        # absent; an honest model contrasting itself ("not Claude") is benign —
        # same gating as the direct self-id check. Own brand words match in
        # any form: the genuine brand is never ambiguous to its own model.
        genuine_present = contains_word_any(text, own_brand_words(provider, model))
        contradiction = forbidden_hits if forbidden_hits and not genuine_present else []
        return self._fingerprint_violated(fp, text) or bool(contradiction), contradiction

    async def _run_fingerprint(
        self, ctx: AuditContext, fp, model, result: DetectorResult, tally: _Tally
    ) -> bool:
        """Send one fingerprint probe (and, in compare mode, the same probe to
        the baseline); append its finding. Returns True when the target answered."""
        spec = RequestSpec(
            messages=[{"role": "user", "content": fp.prompt}],
            temperature=fp.temperature,
            max_tokens=min(fp.max_tokens, self.MAX_FINGERPRINT_OUTPUT),
        )
        outcome = await ctx.client.complete(spec)
        base = await self._baseline(ctx, spec)
        calls = [outcome] if base is None else [outcome, base]
        if not (outcome.ok and outcome.has_content()):
            # A relay that errors or stays silent on a probe is not evidence of
            # a downgrade by itself — record it but do not penalize the score.
            result.findings.append(
                SCALE.finding(
                    "model_identity.fp",
                    "inconclusive",
                    recommendation=advice.failure_advice(outcome),
                    calls=calls,
                    id=f"model_identity.fp.{fp.id}",
                    title=f"Fingerprint inconclusive: {fp.signal}",
                    summary=outcome.error_message or f"No usable response (HTTP {outcome.status_code}).",
                    evidence={"probe": fp.id, "status_code": outcome.status_code},
                )
            )
            return False

        text = outcome.content
        is_violation, forbidden_hits = self._violation(ctx, fp, model, text)
        # The baseline's verdict on the same probe: True (it diverged too),
        # False (it answered natively) or None (no baseline / no usable answer).
        base_text = base.content if base is not None and base.ok and base.has_content() else None
        base_violated = None if base_text is None else self._violation(ctx, fp, model, base_text)[0]
        evidence: dict = {"probe": fp.id}
        if fp.separates_from:
            evidence["separates_from"] = fp.separates_from
            evidence["verified"] = fp.verified
        if base_text is not None:
            result.baseline_compared = True
            evidence["baseline_observed"] = base_text[:400 if is_violation else 200]
            evidence["baseline_diverged"] = base_violated

        if not is_violation:
            result.findings.append(
                SCALE.finding(
                    "model_identity.fp",
                    "consistent",
                    calls=calls,
                    id=f"model_identity.fp.{fp.id}",
                    title=f"Fingerprint consistent: {fp.signal}",
                    summary=f"Behavior consistent with {model.id}.",
                    evidence={**evidence, "observed": text[:200]},
                )
            )
            return True

        tally.violated += 1
        evidence.update({
            "signal": fp.signal,
            "native_expected": fp.native_expected,
            "downgrade_signal": fp.downgrade_signal,
            "observed": text[:400],
            "weight": fp.weight,
        })
        expected = fp.native_expected or self._expectation_text(fp)
        if forbidden_hits:
            # A rival brand is evidence of its own, whatever the baseline says.
            tally.high = True
            key = "rival_brand"
            summary = (
                f"Probe '{fp.signal}' surfaced a forbidden brand ({forbidden_hits[0]}); "
                f"expected behavior consistent with {model.id}."
            )
        elif base_violated:
            # The trusted baseline misses the expectation too: the probe, not
            # the relay, is wrong. Recorded for the knowledge base, not scored.
            result.findings.append(
                SCALE.finding(
                    "model_identity.fp",
                    "baseline_also_diverged",
                    recommendation=advice.KB_PROBE_DIVERGES_ON_BASELINE,
                    calls=calls,
                    id=f"model_identity.fp.{fp.id}",
                    title=f"Fingerprint diverged on the baseline too: {fp.signal}",
                    summary=(
                        f"Probe '{fp.signal}' diverged on the target and on the baseline "
                        f"(expected: {expected}); a knowledge-base problem, not relay evidence."
                    ),
                    evidence={**evidence, "baseline_also_diverged": True},
                )
            )
            return True
        else:
            tally.soft_violations.append(fp.signal)
            tally.diverged_calls.append(outcome)
            if base_violated is False:
                tally.medium = True
                key = "corroborated"
                summary = (
                    f"Probe '{fp.signal}' diverged from native behavior while the baseline "
                    f"answered natively. Expected: {expected}."
                )
            else:
                key = "diverged"
                summary = f"Probe '{fp.signal}' diverged from native behavior. Expected: {expected}."
        result.findings.append(
            SCALE.finding(
                "model_identity.fp",
                key,
                calls=calls,
                id=f"model_identity.fp.{fp.id}",
                deduction=tally.deduction(fp.weight),
                title=f"Fingerprint divergence: {fp.signal}",
                summary=summary,
                evidence=evidence,
            )
        )
        return True

    async def _check_cutoff(
        self, ctx: AuditContext, claimed: tuple[int, int], result: DetectorResult, tally: _Tally
    ) -> None:
        """Ask for the knowledge cutoff (``CUTOFF=YYYY-MM``) and compare it with
        the profile's; in compare mode the baseline answers too."""
        spec = RequestSpec(
            messages=[{"role": "user", "content": _CUTOFF_PROMPT}],
            temperature=0.0,
            max_tokens=_CUTOFF_MAX_TOKENS,
        )
        outcome = await ctx.client.complete(spec)
        base = await self._baseline(ctx, spec)
        calls = [outcome] if base is None else [outcome, base]
        usable = outcome.ok and outcome.has_content()
        answer = parse_cutoff(outcome.content) if usable else None
        key = _cutoff_verdict(answer, claimed)
        evidence: dict = {
            "claimed_cutoff": _ym(claimed),
            "reported_cutoff": _ym(answer) if answer else None,
            "observed": (outcome.content or "")[:200] if usable else None,
        }
        if answer is not None:
            evidence["months_off"] = _months(answer) - _months(claimed)
        base_key = None
        if base is not None and base.ok and base.has_content():
            base_answer = parse_cutoff(base.content)
            base_key = _cutoff_verdict(base_answer, claimed)
            evidence["baseline_cutoff"] = _ym(base_answer) if base_answer else None
            if answer is not None and base_answer is not None:
                result.baseline_compared = True

        if key == "inconclusive":
            result.findings.append(
                SCALE.finding(
                    "model_identity.cutoff",
                    "inconclusive",
                    recommendation=None if usable else advice.failure_advice(outcome),
                    calls=calls,
                    title="Knowledge cutoff not reported",
                    summary=(
                        outcome.error_message
                        or "The answer named no cutoff in the CUTOFF=YYYY-MM format; not judged."
                    ),
                    evidence={**evidence, "status_code": outcome.status_code},
                )
            )
            return
        assert answer is not None
        reported, claimed_text = _ym(answer), _ym(claimed)
        if key == "consistent":
            result.findings.append(
                SCALE.finding(
                    "model_identity.cutoff",
                    "consistent",
                    calls=calls,
                    title="Knowledge cutoff consistent",
                    summary=(
                        f"Reported knowledge cutoff {reported} is within {_CUTOFF_TOLERANCE} months "
                        f"of the claimed model's ({claimed_text})."
                    ),
                    evidence=evidence,
                )
            )
            return
        if key == "differs":
            result.findings.append(
                SCALE.finding(
                    "model_identity.cutoff",
                    "differs",
                    calls=calls,
                    title="Knowledge cutoff differs from the claimed model's",
                    summary=(
                        f"Reported knowledge cutoff {reported} differs from the claimed model's "
                        f"({claimed_text}) by more than {_CUTOFF_TOLERANCE} months, but is not more "
                        f"than {_CUTOFF_EARLIER} months earlier; recorded, not judged."
                    ),
                    evidence=evidence,
                )
            )
            return

        # More than a year earlier than the claimed model's cutoff.
        if base_key == "earlier":
            result.findings.append(
                SCALE.finding(
                    "model_identity.cutoff",
                    "baseline_also_diverged",
                    recommendation=advice.KB_PROBE_DIVERGES_ON_BASELINE,
                    calls=calls,
                    title="Knowledge cutoff earlier on the baseline too",
                    summary=(
                        f"Target and baseline both report a knowledge cutoff more than "
                        f"{_CUTOFF_EARLIER} months before the claimed model's ({claimed_text}); "
                        "a knowledge-base problem, not relay evidence."
                    ),
                    evidence={**evidence, "baseline_also_diverged": True},
                )
            )
            return
        tally.violated += 1
        tally.soft_violations.append(_CUTOFF_SIGNAL)
        tally.diverged_calls.append(outcome)
        corroborated = base_key == "consistent"
        if corroborated:
            tally.medium = True
        result.findings.append(
            SCALE.finding(
                "model_identity.cutoff",
                "corroborated" if corroborated else "earlier",
                calls=calls,
                deduction=tally.deduction(_CUTOFF_WEIGHT),
                title=(
                    "Knowledge cutoff earlier than the claimed model's, baseline consistent"
                    if corroborated
                    else "Knowledge cutoff earlier than the claimed model's"
                ),
                summary=(
                    f"Reported knowledge cutoff {reported} is more than {_CUTOFF_EARLIER} months "
                    f"before the claimed model's ({claimed_text}), as an older model of the "
                    "vendor would answer."
                    + (" The baseline's answer is consistent." if corroborated else "")
                ),
                evidence={**evidence, "signal": _CUTOFF_SIGNAL, "weight": _CUTOFF_WEIGHT},
            )
        )

    async def _check_self_id(
        self, ctx: AuditContext, model, result: DetectorResult
    ) -> bool:
        """Run the direct self-id prompt; append a finding. Returns True on a
        forbidden-brand (substitution) hit."""
        outcome = await ctx.client.complete(
            RequestSpec(
                messages=[{"role": "user", "content": _SELF_ID_PROMPT}],
                temperature=0.0,
                max_tokens=64,
            )
        )
        evidence: dict = {"prompt": "self-id"}
        calls = [outcome]

        # Optional baseline corroboration (informational only).
        if ctx.has_baseline and ctx.baseline_client is not None:
            base = await ctx.baseline_client.complete(
                RequestSpec(
                    messages=[{"role": "user", "content": _SELF_ID_PROMPT}],
                    temperature=0.0,
                    max_tokens=64,
                )
            )
            calls.append(base)
            evidence["baseline_answer"] = (
                base.content[:300] if (base.ok and base.has_content()) else None
            )

        if not (outcome.ok and outcome.has_content()):
            result.findings.append(
                SCALE.finding(
                    "model_identity.self_id",
                    "unavailable",
                    recommendation=advice.failure_advice(outcome),
                    calls=calls,
                    title="Self-identification unavailable",
                    summary=outcome.error_message or f"No usable response (HTTP {outcome.status_code}).",
                    evidence={**evidence, "status_code": outcome.status_code},
                )
            )
            return False

        text = outcome.content
        evidence["target_answer"] = text[:300]
        # Whole-word matching so a brand inside a longer token ("meta" in "metadata",
        # "gpt" in "ChatGPT") doesn't fire, and only treat a rival brand as a swap
        # when the GENUINE brand is ABSENT — an honest model contrasting itself
        # ("I am Claude, not GPT or Gemini") names rivals without being a substitute.
        # Own brand words: identity_keywords plus the provider and model names, so
        # a profile with empty identity_keywords never calls its own brand a rival.
        provider = ctx.profile.provider if ctx.profile is not None else None
        # An ambiguous brand word ("step", "meta", ...) counts only written as a
        # name ("Meta", "Command R"), never as the everyday word.
        forbidden_hits = _brand_hits(text, self._forbidden_brands(model, provider), ambiguous=True)
        keyword_present = contains_word_any(text, own_brand_words(provider, model))

        if forbidden_hits and not keyword_present:
            hit = forbidden_hits[0]
            result.findings.append(
                SCALE.finding(
                    "model_identity.self_id",
                    "rival_brand",
                    calls=calls,
                    title="Self-identifies as a rival brand",
                    summary=(
                        f"Self-identifies as a rival brand ({hit}) under the claimed "
                        f"model id {ctx.target.claimed}, without naming the genuine brand."
                    ),
                    evidence={**evidence, "forbidden_hits": forbidden_hits},
                    recommendation="A response naming a different vendor strongly suggests model substitution.",
                )
            )
            return True

        if forbidden_hits and keyword_present:
            result.findings.append(
                SCALE.finding(
                    "model_identity.self_id",
                    "both_brands",
                    calls=calls,
                    title="Self-id names both the genuine and a rival brand",
                    summary=(
                        f"Self-id mentions genuine brand words for {model.id} but also a rival "
                        f"brand ({', '.join(forbidden_hits)}); commonly a benign contrast "
                        "rather than a swap. Corroborate before treating as substitution."
                    ),
                    evidence={**evidence, "forbidden_hits": forbidden_hits},
                    recommendation="Run `ekte compare` against a trusted baseline to disambiguate.",
                )
            )
            return False

        if not keyword_present:
            result.findings.append(
                SCALE.finding(
                    "model_identity.self_id",
                    "evasive",
                    calls=calls,
                    title="Evasive self-identification",
                    summary=(
                        "Self-id response names neither the genuine brand nor a rival; "
                        "treat as weak/evasive evidence."
                    ),
                    evidence=evidence,
                )
            )
            return False

        result.findings.append(
            SCALE.finding(
                "model_identity.self_id",
                "consistent",
                calls=calls,
                title="Self-identification consistent",
                summary=f"Self-id mentions genuine brand words for {model.id}.",
                evidence=evidence,
            )
        )
        return False

    async def _check_model_field(self, ctx: AuditContext, result: DetectorResult) -> bool:
        """Compare the echoed ``model`` field to the claimed and requested ids
        (see :func:`ekte.knowledge.model_ids.compare_echoed_model`). Returns True
        if it clearly names a different/cheaper model."""
        outcome = await ctx.client.complete(
            RequestSpec(
                messages=[{"role": "user", "content": prompts.text("model_identity.ping")}],
                temperature=0.0,
                max_tokens=8,
            )
        )
        requested = ctx.target.model
        claimed = ctx.target.claimed
        returned = (outcome.model_returned or "").strip()
        if not (outcome.ok) or not returned:
            result.findings.append(
                SCALE.finding(
                    "model_identity.model_field",
                    "unavailable",
                    recommendation=advice.failure_advice(outcome) if not outcome.ok else advice.NO_MODEL_FIELD,
                    calls=[outcome],
                    title="No usable echoed model field",
                    summary=(
                        outcome.error_message
                        or "Response omitted a 'model' field; cannot compare."
                    ),
                    evidence={"requested": requested, "returned": returned or None},
                )
            )
            return False

        # Compared with the claimed model and the id sent (a deployment alias
        # may differ from the claim), through the knowledge base first.
        cmp = compare_echoed_model(ctx.kb, returned, claimed, requested, claimed_profile=ctx.profile)
        evidence = {"requested": requested, "claimed": claimed, "returned": returned, **cmp.evidence()}
        if cmp.verdict == "diverges":
            result.findings.append(
                SCALE.finding(
                    "model_identity.model_field",
                    "diverges",
                    calls=[outcome],
                    title="Echoed model field differs from requested",
                    summary=(
                        f"Response 'model' field ({returned}) differs from requested "
                        f"({requested})."
                    ),
                    evidence=evidence,
                    recommendation="A smaller-tier or different-family model id in the response suggests routing to a substitute.",
                )
            )
            return True

        if cmp.verdict == "unknown":
            result.findings.append(
                SCALE.finding(
                    "model_identity.model_field",
                    "unknown",
                    calls=[outcome],
                    title="Echoed model field not recognized",
                    summary=(
                        f"Response 'model' field ({returned}) is a different id from requested "
                        f"({requested}) that the knowledge base cannot place; not judged."
                    ),
                    evidence=evidence,
                    recommendation="Ask the relay what the echoed id names, or add it to the knowledge base as an alias.",
                )
            )
            return False

        result.findings.append(
            SCALE.finding(
                "model_identity.model_field",
                "consistent",
                calls=[outcome],
                title="Echoed model field consistent",
                summary=f"Response 'model' field ({returned}) matches requested.",
                evidence=evidence,
            )
        )
        return False

    # ------------------------------------------------------------------ #
    @staticmethod
    def _forbidden_brands(model, provider) -> list[str]:
        """Brands that would betray a substitution for this model: the global rival
        set plus the profile's explicit list, minus the model's own brand words
        (identity_keywords, provider and model names; see own_brand_words)."""
        own = set(own_brand_words(provider, model))
        seen: set[str] = set()
        out: list[str] = []
        for brand in (*(model.identity_forbidden or []), *_RIVAL_BRANDS):
            bl = brand.lower()
            if bl in own or bl in seen:
                continue
            seen.add(bl)
            out.append(brand)
        return out

    @staticmethod
    def _fingerprint_violated(fp, text: str) -> bool:
        """Apply the probe's deterministic expectations to the response text."""
        if fp.expect_contains and not contains_all(text, fp.expect_contains):
            return True
        if fp.expect_contains_any and not contains_any(text, fp.expect_contains_any):
            return True
        # Forbidden terms match whole words ("meta" is not in "metadata");
        # the expected ones stay substrings, the safe direction (#262).
        if fp.expect_not_contains and contains_term_any(text, fp.expect_not_contains):
            return True
        if fp.expect_regex:
            try:
                if not re.search(fp.expect_regex, text, re.IGNORECASE):
                    return True
            except re.error:
                # A malformed KB regex is a KB bug, not relay evidence — skip it.
                return False
        return False

    @staticmethod
    def _expectation_text(fp) -> str:
        if fp.expect_contains:
            return f"contains all of {fp.expect_contains}"
        if fp.expect_contains_any:
            return f"contains any of {fp.expect_contains_any}"
        if fp.expect_not_contains:
            return f"does not contain {fp.expect_not_contains}"
        if fp.expect_regex:
            return f"matches /{fp.expect_regex}/"
        return "native behavior"
