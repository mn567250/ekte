"""Published "deductions" scales of the model_identity and billing detectors.

Both start at 100: model identity deducts each diverging fingerprint's weight
share and caps the score at 20 on a rival-brand contradiction; billing caps the
score per problem (the lowest cap wins). Every finding records its outcome and
what it did to the score, and the scale travels with the result.
"""

from __future__ import annotations

import pytest

from ekte.detectors import billing, model_identity
from ekte.detectors.billing import BillingDetector
from ekte.detectors.model_identity import ModelIdentityDetector
from ekte.detectors.scale import DeductionScale
from ekte.models import DetectorResult, Finding, Status
from ekte.report.dimensions import _effect


def _matches_scale(result: DetectorResult, scale) -> None:
    assert result.scoring is not None and result.scoring.method == "deductions"
    assert len(result.scoring.outcomes) == len(scale.outcomes)
    for f in result.findings:
        o = scale.get(f.scale_check, f.outcome or "")
        assert (f.status, f.severity, f.cap) == (o.status, o.severity, o.cap), f.id
        if o.max_deduction is None:
            assert f.deduction == o.deduction, f.id
        else:
            assert f.deduction is not None and 0.0 <= f.deduction <= o.max_deduction, f.id


@pytest.mark.parametrize("scale", [model_identity.SCALE, billing.SCALE])
def test_every_outcome_has_a_label_and_no_mean_points(scale):
    assert all(o.label for o in scale.outcomes)
    assert all(o.score is None for o in scale.outcomes)  # deductions, not points


def test_deduction_total_subtracts_then_applies_the_lowest_cap():
    f = lambda d=None, c=None: Finding(id="x", title="x", status=Status.WARN, deduction=d, cap=c)  # noqa: E731
    assert DeductionScale.total([]) == 100.0
    assert DeductionScale.total([f(12.5), f(25.0)]) == 62.5
    assert DeductionScale.total([f(10.0), f(c=55.0), f(c=90.0)]) == 55.0
    assert DeductionScale.total([f(90.0), f(c=55.0)]) == 10.0  # already below the cap
    assert DeductionScale.total([f(80.0), f(80.0)]) == 0.0  # never negative


def test_effect_text():
    assert _effect("deductions", None, 12.5) == "−12.5"
    assert _effect("deductions", None, None, 55.0) == "cap 55"
    assert _effect("deductions", None, 25.0, 20.0) == "−25 · cap 20"
    assert _effect("deductions", None, None, None, 25.0) == "up to −25"
    assert _effect("deductions", None) == "no deduction"
    assert _effect("mean_of_checks", 80.0) == "80"


# --------------------------------------------------------------------------- #
# model_identity
# --------------------------------------------------------------------------- #
async def test_identity_honest_relay_has_no_deductions(audit_context, mock_server):
    result = await ModelIdentityDetector().run(audit_context)
    _matches_scale(result, model_identity.SCALE)
    by_id = {f.id: f for f in result.findings}
    assert by_id["model_identity.self_id"].outcome == "consistent"
    assert by_id["model_identity.model_field"].outcome == "consistent"
    fps = [f for f in result.findings if f.check == "model_identity.fp"]
    assert fps and all(f.id.startswith("model_identity.fp.") for f in fps)
    # the score is exactly what the findings say
    assert result.score == DeductionScale.total(result.findings)


async def test_identity_rival_brand_caps_the_score(audit_context, mock_server):
    mock_server.self_identity = "I am Claude, an AI assistant made by Anthropic."
    result = await ModelIdentityDetector().run(audit_context)
    _matches_scale(result, model_identity.SCALE)
    f = next(f for f in result.findings if f.id == "model_identity.self_id")
    assert (f.outcome, f.cap, f.status) == ("rival_brand", 20.0, Status.FAIL)
    assert result.score is not None and result.score <= 20.0
    assert result.score == DeductionScale.total(result.findings)


async def test_identity_downgraded_model_field_warns_without_deduction(audit_context, mock_server):
    mock_server.served_model = "gpt-4o-mini"
    result = await ModelIdentityDetector().run(audit_context)
    f = next(f for f in result.findings if f.id == "model_identity.model_field")
    assert (f.outcome, f.deduction, f.cap) == ("diverges", None, None)
    assert result.status == Status.WARN


def test_identity_diverging_fingerprint_deducts_its_weight_share():
    o = model_identity.SCALE.get("model_identity.fp", "diverged")
    assert o.max_deduction == 25.0 and o.cap is None
    f = model_identity.SCALE.finding("model_identity.fp", "diverged", id="model_identity.fp.cutoff",
                                     title="Fingerprint divergence: cutoff", deduction=12.5)
    assert (f.id, f.check, f.subject, f.deduction) == (
        "model_identity.fp.cutoff", "model_identity.fp", None, 12.5,
    )
    assert f.scale_check == "model_identity.fp"


# --------------------------------------------------------------------------- #
# billing
# --------------------------------------------------------------------------- #
async def test_billing_honest_usage_is_consistent(audit_context, mock_server):
    mock_server.inflate_usage_factor = 1.0
    result = await BillingDetector().run(audit_context)
    _matches_scale(result, billing.SCALE)
    assert [f.outcome for f in result.findings] == ["consistent"]
    assert result.score == 100.0


async def test_billing_inflation_caps_at_55(audit_context, mock_server):
    mock_server.inflate_usage_factor = 6.0
    result = await BillingDetector().run(audit_context)
    _matches_scale(result, billing.SCALE)
    inflated = next(f for f in result.findings if f.id == "billing.usage-inflation")
    assert (inflated.outcome, inflated.cap) == ("inflated", 55.0)
    assert result.score == 55.0 and result.status == Status.FAIL


async def test_billing_missing_usage_caps_at_75(audit_context, mock_server):
    mock_server.emit_usage = False
    result = await BillingDetector().run(audit_context)
    _matches_scale(result, billing.SCALE)
    assert [(f.outcome, f.cap) for f in result.findings] == [("missing", 75.0)]
    assert result.score == 75.0 and result.status == Status.WARN
