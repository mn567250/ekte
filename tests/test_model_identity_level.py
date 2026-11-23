"""Model-level identity checks (issue #251).

A same-vendor downgrade (gpt-4o served by gpt-4o-mini) passes every brand
check, so the identity detector adds a self-reported knowledge-cutoff probe,
compares every fingerprint with a trusted baseline in compare mode, and says
so when nothing it ran could tell the claimed model from its siblings.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ekte.config import AuditOptions
from ekte.context import AuditContext
from ekte.detectors import model_identity
from ekte.detectors.model_identity import ModelIdentityDetector, _cutoff_verdict, parse_cutoff
from ekte.knowledge.schema import (
    FingerprintProbe,
    KnowledgeBase,
    ModelProfile,
    ProviderProfile,
    ResolvedProfile,
)
from ekte.models import CompletionOutcome, RequestSpec, Severity, Status, TargetConfig

SCALE = model_identity.SCALE
CUTOFF_PROMPT = model_identity._CUTOFF_PROMPT
FP_PROMPT = "What is 2+2? Answer with the number only."


class _Relay:
    """A stub client: the self-id names the brand, the cutoff probe answers
    ``cutoff``, the fingerprint probe ``fp_answer``, everything else "OK"."""

    def __init__(self, *, cutoff: str = "CUTOFF=2025-01", fp_answer: str = "4", brand: str = "Acme"):
        self.cutoff = cutoff
        self.fp_answer = fp_answer
        self.brand = brand
        self.prompts: list[str] = []

    async def complete(self, spec: RequestSpec) -> CompletionOutcome:
        prompt = spec.messages[0]["content"]
        self.prompts.append(prompt)
        if prompt == CUTOFF_PROMPT:
            text = self.cutoff
        elif prompt == FP_PROMPT:
            text = self.fp_answer
        elif "what model are you" in prompt.lower():
            text = f"I am {self.brand} One, built by {self.brand}."
        else:
            text = "OK"
        return CompletionOutcome(ok=True, status_code=200, content=text, model_returned="acme-1",
                                 finish_reason="stop")


def _profile(*, cutoff: str | None = "2025-01", own: list[FingerprintProbe] | None = None,
             shared: list[FingerprintProbe] | None = None) -> ResolvedProfile:
    return ResolvedProfile(
        provider=ProviderProfile(provider="acme", display_name="Acme", fingerprints=shared or []),
        model=ModelProfile(id="acme-1", identity_keywords=["acme"], knowledge_cutoff=cutoff,
                           fingerprints=own or []),
    )


def _fp(**kw) -> FingerprintProbe:
    return FingerprintProbe(id="arith", signal="arithmetic", prompt=FP_PROMPT,
                            pure_code_checkable=True, expect_contains=["4"], max_tokens=16, **kw)


async def _run(profile: ResolvedProfile, relay: _Relay, baseline: _Relay | None = None):
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model="acme-1")
    ctx = AuditContext(
        target=target, client=relay, options=AuditOptions(suite="standard"),  # type: ignore[arg-type]
        kb=KnowledgeBase(), profile=profile,
        baseline=target if baseline is not None else None,
        baseline_client=baseline,  # type: ignore[arg-type]
    )
    return await ModelIdentityDetector().run(ctx)


def _finding(result, fid):
    return next(f for f in result.findings if f.id == fid)


# --------------------------------------------------------------------------- #
# A. the knowledge-cutoff probe
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("CUTOFF=2024-06", (2024, 6)),
    ("cutoff = 2023-1", (2023, 1)),
    ("My training data goes up to CUTOFF=2025-10.", (2025, 10)),
    ("CUTOFF=2024-13", None),
    ("I was trained until early 2024.", None),
    ("", None),
])
def test_parse_cutoff(text, expected):
    assert parse_cutoff(text) == expected


@pytest.mark.parametrize("answer,verdict", [
    ((2025, 1), "consistent"),
    ((2024, 7), "consistent"),   # 6 months earlier
    ((2025, 7), "consistent"),   # 6 months later
    ((2024, 1), "differs"),      # exactly 12 months earlier: not "more than"
    ((2023, 12), "earlier"),     # 13 months earlier
    ((2026, 3), "differs"),      # later than the profile
    (None, "inconclusive"),
])
def test_cutoff_bands(answer, verdict):
    assert _cutoff_verdict(answer, (2025, 1)) == verdict


def test_profile_cutoff_month_only_for_a_named_month():
    assert ModelProfile(id="m", knowledge_cutoff="2024-06-01").cutoff_month() == (2024, 6)
    assert ModelProfile(id="m", knowledge_cutoff="2025-01").cutoff_month() == (2025, 1)
    for vague in ("2025", "~2024 (undisclosed)", "not officially published", None):
        assert ModelProfile(id="m", knowledge_cutoff=vague).cutoff_month() is None


async def test_older_same_vendor_model_warns_on_cutoff():
    # The relay answers like an older Acme model: right brand, cutoff 2023-06.
    relay = _Relay(cutoff="CUTOFF=2023-06")
    result = await _run(_profile(), relay)
    f = _finding(result, "model_identity.cutoff")
    assert (f.outcome, f.status, f.severity) == ("earlier", Status.WARN, Severity.LOW)
    assert f.deduction and f.deduction > 0
    assert f.evidence["claimed_cutoff"] == "2025-01" and f.evidence["reported_cutoff"] == "2023-06"
    assert f.evidence["months_off"] == -19
    assert _finding(result, "model_identity.self_id").outcome == "consistent"
    assert result.status == Status.WARN and result.score is not None and result.score < 100
    assert CUTOFF_PROMPT in relay.prompts


async def test_consistent_cutoff_passes_and_unparsed_one_is_inconclusive():
    ok = await _run(_profile(), _Relay(cutoff="CUTOFF=2024-10"))
    assert _finding(ok, "model_identity.cutoff").outcome == "consistent"
    assert ok.status == Status.PASS and ok.score == 100.0
    vague = await _run(_profile(), _Relay(cutoff="Sometime in 2024."))
    f = _finding(vague, "model_identity.cutoff")
    assert (f.outcome, f.status, f.deduction) == ("inconclusive", Status.INCONCLUSIVE, None)


async def test_no_cutoff_probe_without_a_profile_month():
    relay = _Relay()
    result = await _run(_profile(cutoff="~2025 (undisclosed)"), relay)
    assert CUTOFF_PROMPT not in relay.prompts
    assert not [f for f in result.findings if f.id == "model_identity.cutoff"]
    assert result.evidence["cutoff_checked"] is False


async def test_cutoff_divergence_counts_toward_the_aggregate():
    result = await _run(_profile(own=[_fp()]), _Relay(cutoff="CUTOFF=2022-01", fp_answer="five"))
    agg = _finding(result, "model_identity.fp_aggregate")
    assert model_identity._CUTOFF_SIGNAL in agg.evidence["diverged"]
    assert result.status == Status.WARN


# --------------------------------------------------------------------------- #
# B. baseline comparison of fingerprints and the cutoff probe
# --------------------------------------------------------------------------- #
async def test_compare_mode_corroborated_fingerprint_is_medium():
    baseline = _Relay(fp_answer="4")
    result = await _run(_profile(shared=[_fp()]), _Relay(fp_answer="five"), baseline)
    f = _finding(result, "model_identity.fp.arith")
    assert (f.outcome, f.status, f.severity) == ("corroborated", Status.WARN, Severity.MEDIUM)
    assert f.deduction and f.deduction > 0
    assert f.evidence["baseline_diverged"] is False
    assert FP_PROMPT in baseline.prompts and CUTOFF_PROMPT in baseline.prompts
    assert result.baseline_compared is True and result.evidence["baseline_compared"] is True


async def test_compare_mode_fingerprint_the_baseline_also_misses_is_info():
    result = await _run(_profile(shared=[_fp()]), _Relay(fp_answer="five"), _Relay(fp_answer="five"))
    f = _finding(result, "model_identity.fp.arith")
    assert (f.outcome, f.status, f.severity, f.deduction) == (
        "baseline_also_diverged", Status.INFO, Severity.INFO, None)
    assert f.evidence["baseline_also_diverged"] is True
    assert result.status == Status.PASS and result.score == 100.0


async def test_compare_mode_cutoff_corroborated_and_both_earlier():
    hit = await _run(_profile(), _Relay(cutoff="CUTOFF=2023-01"), _Relay(cutoff="CUTOFF=2024-12"))
    f = _finding(hit, "model_identity.cutoff")
    assert (f.outcome, f.severity) == ("corroborated", Severity.MEDIUM)
    both = await _run(_profile(), _Relay(cutoff="CUTOFF=2023-01"), _Relay(cutoff="CUTOFF=2023-03"))
    f = _finding(both, "model_identity.cutoff")
    assert (f.outcome, f.status, f.deduction) == ("baseline_also_diverged", Status.INFO, None)


async def test_baseline_without_usable_answer_keeps_the_low_divergence():
    class _Down(_Relay):
        async def complete(self, spec):
            return CompletionOutcome(ok=False, status_code=503, error_message="down")

    result = await _run(_profile(shared=[_fp()]), _Relay(fp_answer="five"), _Down())
    assert _finding(result, "model_identity.fp.arith").outcome == "diverged"
    # #257: a configured baseline that never answered is no comparison
    assert result.baseline_compared is False and result.evidence["baseline_compared"] is False


# --------------------------------------------------------------------------- #
# D. honest wording when only vendor-level evidence exists
# --------------------------------------------------------------------------- #
async def test_vendor_only_evidence_says_the_model_was_not_verified():
    result = await _run(_profile(shared=[_fp()]), _Relay())
    f = _finding(result, "model_identity.model_specific")
    assert (f.outcome, f.status, f.deduction) == ("vendor_only", Status.INFO, None)
    assert f.evidence["model_specific_checks"] == 0
    assert "specific model was not verified" in f.summary
    assert result.evidence["model_specific_checks"] == 0
    assert result.status == Status.PASS


async def test_a_model_specific_fingerprint_or_a_baseline_lifts_the_caveat():
    own = await _run(_profile(own=[_fp()]), _Relay())
    assert own.evidence["model_specific_checks"] == 1
    assert not [f for f in own.findings if f.id == "model_identity.model_specific"]
    compared = await _run(_profile(shared=[_fp()]), _Relay(), _Relay())
    assert not [f for f in compared.findings if f.id == "model_identity.model_specific"]


async def test_model_specific_probes_are_sent_before_the_vendor_ones():
    shared = [FingerprintProbe(id=f"s{i}", signal=f"s{i}", prompt=f"shared {i}", pure_code_checkable=True)
              for i in range(ModelIdentityDetector.MAX_FINGERPRINTS)]
    result = await _run(_profile(own=[_fp()], shared=shared), _Relay())
    assert result.evidence["model_specific_checks"] == 1
    assert result.evidence["fingerprints_run"] == ModelIdentityDetector.MAX_FINGERPRINTS


def test_every_finding_matches_the_published_scale():
    keys = {(o.check, o.outcome) for o in SCALE.outcomes}
    for check, key in [("model_identity.cutoff", k) for k in
                       ("consistent", "earlier", "corroborated", "baseline_also_diverged",
                        "differs", "inconclusive")] + [
                       ("model_identity.fp", "corroborated"), ("model_identity.fp", "baseline_also_diverged"),
                       ("model_identity.model_specific", "vendor_only")]:
        assert (check, key) in keys
    # Self-reported cutoffs are soft: never HIGH.
    assert all(o.severity in (Severity.INFO, Severity.LOW, Severity.MEDIUM)
               for o in SCALE.outcomes if o.check == "model_identity.cutoff")


# --------------------------------------------------------------------------- #
# Schema: provenance of a model-specific fingerprint
# --------------------------------------------------------------------------- #
def test_separates_from_needs_a_verification_date():
    with pytest.raises(ValidationError):
        FingerprintProbe(id="x", signal="x", prompt="x", separates_from=["acme-1-mini"])
    with pytest.raises(ValidationError):
        FingerprintProbe(id="x", signal="x", prompt="x", separates_from=["acme-1-mini"], verified="May 2026")
    fp = FingerprintProbe(id="x", signal="x", prompt="x", separates_from=["acme-1-mini"], verified="2026-05-01")
    assert fp.separates_from == ["acme-1-mini"]


async def test_separation_provenance_is_recorded_in_the_evidence():
    probe = _fp(separates_from=["acme-1-mini"], verified="2026-05-01")
    result = await _run(_profile(own=[probe]), _Relay())
    f = _finding(result, "model_identity.fp.arith")
    assert f.evidence["separates_from"] == ["acme-1-mini"] and f.evidence["verified"] == "2026-05-01"


# --------------------------------------------------------------------------- #
# D. the verdict and the identity dimension say so (ekte/scoring.py)
# --------------------------------------------------------------------------- #
def _verdict(result, *, used_baseline=False, used_judge=False):
    from ekte.models import Dimension
    from ekte.scoring import build_dimensions, build_verdict

    dims = build_dimensions([result], None)
    verdict = build_verdict([result], dims, profile_matched=True, used_judge=used_judge,
                            used_baseline=used_baseline)
    reason = next(d.reason for d in dims if d.dimension == Dimension.MODEL_IDENTITY)
    return verdict, reason


async def test_verdict_and_reason_say_the_specific_model_was_not_verified():
    from ekte.scoring import VENDOR_ONLY_NOTE

    verdict, reason = _verdict(await _run(_profile(shared=[_fp()]), _Relay()))
    assert VENDOR_ONLY_NOTE in verdict.summary
    assert reason == VENDOR_ONLY_NOTE  # instead of "All checks passed."
    # A warning keeps its title and gains the note.
    verdict, reason = _verdict(await _run(_profile(), _Relay(cutoff="CUTOFF=2022-01")))
    assert reason.startswith("Knowledge cutoff earlier") and reason.endswith(VENDOR_ONLY_NOTE)


async def test_verdict_has_no_vendor_only_note_with_model_specific_checks_or_a_baseline():
    from ekte.scoring import VENDOR_ONLY_NOTE

    verdict, reason = _verdict(await _run(_profile(own=[_fp()]), _Relay()))
    assert VENDOR_ONLY_NOTE not in verdict.summary and VENDOR_ONLY_NOTE not in reason
    verdict, reason = _verdict(await _run(_profile(shared=[_fp()]), _Relay(), _Relay()), used_baseline=True)
    assert VENDOR_ONLY_NOTE not in verdict.summary and VENDOR_ONLY_NOTE not in reason
