"""Model identity & downgrade fingerprinting — the core 货不对板 detector.

A relay can claim to serve an expensive model while quietly routing to a cheaper
substitute. This detector triangulates identity three ways: a direct self-id
prompt checked against the genuine brand words (and rival brands that betray a
swap), the knowledge base's pure-code behavioral fingerprints (knowledge cutoff,
tokenizer quirks, etc.), and the ``model`` field the relay echoes back. Divergence
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
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import contains_all, contains_any, contains_word, contains_word_any
from ekte.detectors.scale import DeductionScale, outcome
from ekte.knowledge.identity import AMBIGUOUS_BRAND_WORDS, VENDOR_BRANDS, own_brand_words
from ekte.models import DetectorResult, Dimension, Finding, RequestSpec, Severity, Status

# Substrings that name a cheaper/smaller tier of a family. If the returned model
# field carries one of these and the requested id does not, that is a downgrade.
_DOWNGRADE_HINTS = ("mini", "nano", "flash", "lite", "small", "tiny", "8b", "7b", "3b", "1b")

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
    outcome("model_identity.fp", "rival_brand", None, Status.FAIL, Severity.HIGH,
            max_deduction=_MAX_FP_DEDUCTION, cap=_CONTRADICTION_CAP,
            label="The answer named a rival brand and not the genuine one: deducts the probe's weight share."),
    outcome("model_identity.fp", "inconclusive", None, Status.INCONCLUSIVE,
            label=_NO_RESPONSE),
    outcome("model_identity.fp", "skipped_output_cap", None, Status.INFO,
            label="The probe needs more output than the 512-token identity cap; not run."),
    outcome("model_identity.fp_aggregate", "diverged", None, Status.WARN, Severity.MEDIUM,
            label="Two or more behavioral fingerprints diverged."),
    outcome("model_identity.model_field", "consistent", None, Status.PASS,
            label="The echoed model field matched the requested model."),
    outcome("model_identity.model_field", "diverges", None, Status.WARN, Severity.MEDIUM,
            label="The echoed model field names a different or smaller model."),
    outcome("model_identity.model_field", "unavailable", None, Status.INCONCLUSIVE,
            label="The response had no usable model field."),
    outcome("model_identity.no_evidence", "none", None, Status.INCONCLUSIVE,
            label="No self-identification or fingerprint answer was usable and the model "
                  "field did not diverge: not scored."),
    titles={"model_identity.fp": "Behavioral fingerprints"},
)


@register
class ModelIdentityDetector(Detector):
    id = "model_identity"
    name = "Model identity & downgrade fingerprinting"
    dimension = Dimension.MODEL_IDENTITY
    min_suite = "standard"
    cost_hint = 9

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
        probes = [fp for fp in ctx.profile.all_fingerprints() if fp.pure_code_checkable]
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
        total_weight = sum(max(fp.weight, 0.0) for fp in probes)
        violated = 0
        # Non-identity (behavioral) fingerprint divergences are individually noisy,
        # so a single one stays LOW and does not escalate overall risk; two or more
        # together raise a MEDIUM aggregate.
        soft_violations: list[str] = []
        for fp in probes:
            outcome = await ctx.client.complete(
                RequestSpec(
                    messages=[{"role": "user", "content": fp.prompt}],
                    temperature=fp.temperature,
                    max_tokens=min(fp.max_tokens, self.MAX_FINGERPRINT_OUTPUT),
                )
            )
            if not (outcome.ok and outcome.has_content()):
                # A relay that errors or stays silent on a probe is not evidence of
                # a downgrade by itself — record it but do not penalize the score.
                result.findings.append(
                    SCALE.finding(
                        "model_identity.fp",
                        "inconclusive",
                        id=f"model_identity.fp.{fp.id}",
                        title=f"Fingerprint inconclusive: {fp.signal}",
                        summary=outcome.error_message or f"No usable response (HTTP {outcome.status_code}).",
                        evidence={"probe": fp.id, "status_code": outcome.status_code},
                    )
                )
                continue

            text = outcome.content
            # Ambiguous brand words ("step by step", "a meta question") never count
            # here: a fingerprint answer is free prose, not a self-description.
            forbidden_hits = _brand_hits(
                text, self._forbidden_brands(model, ctx.profile.provider), ambiguous=False
            )
            # A rival brand only contradicts identity when the GENUINE brand is
            # absent; an honest model contrasting itself ("not Claude") is benign —
            # same gating as the direct self-id check. Own brand words match in
            # any form: the genuine brand is never ambiguous to its own model.
            genuine_present = contains_word_any(text, own_brand_words(ctx.profile.provider, model))
            forbidden_contradiction = bool(forbidden_hits) and not genuine_present
            is_violation = self._fingerprint_violated(fp, text) or forbidden_contradiction
            if is_violation:
                violated += 1
                # Cap a single probe's penalty so one fragile fingerprint can't
                # tank the identity score on its own.
                deduction = (
                    min((max(fp.weight, 0.0) / total_weight) * 100.0, _MAX_FP_DEDUCTION)
                    if total_weight > 0
                    else 0.0
                )
                if forbidden_contradiction:
                    has_high = True
                    hit = forbidden_hits[0]
                    summary = (
                        f"Probe '{fp.signal}' surfaced a forbidden brand ({hit}); "
                        f"expected behavior consistent with {model.id}."
                    )
                    key = "rival_brand"
                else:
                    soft_violations.append(fp.signal)
                    summary = (
                        f"Probe '{fp.signal}' diverged from native behavior. "
                        f"Expected: {fp.native_expected or self._expectation_text(fp)}."
                    )
                    key = "diverged"
                result.findings.append(
                    SCALE.finding(
                        "model_identity.fp",
                        key,
                        id=f"model_identity.fp.{fp.id}",
                        deduction=deduction,
                        title=f"Fingerprint divergence: {fp.signal}",
                        summary=summary,
                        evidence={
                            "probe": fp.id,
                            "signal": fp.signal,
                            "native_expected": fp.native_expected,
                            "downgrade_signal": fp.downgrade_signal,
                            "observed": text[:400],
                            "weight": fp.weight,
                        },
                    )
                )
            else:
                result.findings.append(
                    SCALE.finding(
                        "model_identity.fp",
                        "consistent",
                        id=f"model_identity.fp.{fp.id}",
                        title=f"Fingerprint consistent: {fp.signal}",
                        summary=f"Behavior consistent with {model.id}.",
                        evidence={"probe": fp.id, "observed": text[:200]},
                    )
                )

        # Two or more behavioral divergences together justify a MEDIUM aggregate.
        if len(soft_violations) >= 2:
            has_medium = True
            result.findings.append(
                SCALE.finding(
                    "model_identity.fp_aggregate",
                    "diverged",
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
                    title="No usable identity evidence",
                    summary=(
                        "Neither the self-identification nor any fingerprint probe returned a "
                        "usable answer, and the echoed model field shows no divergence; "
                        "identity could not be judged."
                    ),
                    # The identity questions asked: self-id plus each fingerprint run.
                    evidence={"checks": 1 + len(probes)},
                )
            )
            result.score = None
            result.status = Status.INCONCLUSIVE
        else:
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
        result.evidence["fingerprints_violated"] = violated
        result.evidence["fingerprints_skipped"] = [fp.id for fp in skipped]
        result.evidence["match_confidence"] = ctx.profile.match_confidence
        return result

    # ------------------------------------------------------------------ #
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

        # Optional baseline corroboration (informational only).
        if ctx.has_baseline and ctx.baseline_client is not None:
            base = await ctx.baseline_client.complete(
                RequestSpec(
                    messages=[{"role": "user", "content": _SELF_ID_PROMPT}],
                    temperature=0.0,
                    max_tokens=64,
                )
            )
            evidence["baseline_answer"] = (
                base.content[:300] if (base.ok and base.has_content()) else None
            )

        if not (outcome.ok and outcome.has_content()):
            result.findings.append(
                SCALE.finding(
                    "model_identity.self_id",
                    "unavailable",
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
                title="Self-identification consistent",
                summary=f"Self-id mentions genuine brand words for {model.id}.",
                evidence=evidence,
            )
        )
        return False

    async def _check_model_field(self, ctx: AuditContext, result: DetectorResult) -> bool:
        """Compare the echoed ``model`` field to the requested id. Returns True if
        it clearly names a different/cheaper model."""
        outcome = await ctx.client.complete(
            RequestSpec(
                messages=[{"role": "user", "content": prompts.text("model_identity.ping")}],
                temperature=0.0,
                max_tokens=8,
            )
        )
        requested = ctx.target.model
        returned = (outcome.model_returned or "").strip()
        if not (outcome.ok) or not returned:
            result.findings.append(
                SCALE.finding(
                    "model_identity.model_field",
                    "unavailable",
                    title="No usable echoed model field",
                    summary=(
                        outcome.error_message
                        or "Response omitted a 'model' field; cannot compare."
                    ),
                    evidence={"requested": requested, "returned": returned or None},
                )
            )
            return False

        if self._model_field_diverges(requested, returned):
            result.findings.append(
                SCALE.finding(
                    "model_identity.model_field",
                    "diverges",
                    title="Echoed model field differs from requested",
                    summary=(
                        f"Response 'model' field ({returned}) differs from requested "
                        f"({requested})."
                    ),
                    evidence={"requested": requested, "returned": returned},
                    recommendation="A smaller-tier or different-family model id in the response suggests routing to a substitute.",
                )
            )
            return True

        result.findings.append(
            SCALE.finding(
                "model_identity.model_field",
                "consistent",
                title="Echoed model field consistent",
                summary=f"Response 'model' field ({returned}) matches requested.",
                evidence={"requested": requested, "returned": returned},
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
        if fp.expect_not_contains and contains_any(text, fp.expect_not_contains):
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

    @staticmethod
    def _model_field_diverges(requested: str, returned: str) -> bool:
        """Lenient comparison: ignore snapshot suffixes/aliases, flag a clear
        downgrade-tier word or a different family."""
        req = requested.lower()
        ret = returned.lower()
        if req == ret:
            return False

        # A downgrade-tier word present in the returned id but not the requested one.
        # Checked BEFORE the snapshot/alias substring tolerance below, otherwise the
        # most common substitution — gpt-4o -> gpt-4o-mini, where the requested id is
        # a substring of the returned one — would be waved through as an "alias".
        for hint in _DOWNGRADE_HINTS:
            if hint in ret and hint not in req:
                return True

        def norm(name: str) -> str:
            return "".join(ch for ch in name if ch.isalnum())

        nreq, nret = norm(req), norm(ret)
        # Snapshot/alias tolerance: one being a prefix/substring of the other
        # (e.g. "gpt-4o" vs "gpt-4o-2024-08-06") is not a divergence.
        if nreq and nret and (nreq in nret or nret in nreq):
            return False

        # Different leading family token (e.g. "gpt" vs "qwen", "claude" vs "llama").
        req_family = re.split(r"[-_/:.\s]", req, maxsplit=1)[0]
        ret_family = re.split(r"[-_/:.\s]", ret, maxsplit=1)[0]
        return bool(req_family and ret_family and req_family != ret_family)
