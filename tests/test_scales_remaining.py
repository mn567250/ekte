"""Published scales of the remaining detectors: capability, vision, context
window, streaming, reliability, performance, security (+ injected prompt,
integrity, prompt cache) and the LLM judge.

Every scale-backed detector must build its findings from its scale and derive
its score from it; these tests check that invariant against the mock relay and
pin the scores of the scenarios whose arithmetic is least obvious.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import zing.detectors as detectors_pkg
from zing import i18n
from zing.config import AuditOptions
from zing.context import AuditContext
from zing.detectors import REGISTRY
from zing.detectors.capability import CapabilityDetector
from zing.detectors.context_window import SCALE as CW_SCALE
from zing.detectors.context_window import ContextWindowDetector, _window_deduction
from zing.detectors.quality_judge import SCALE as JUDGE_SCALE
from zing.detectors.quality_judge import QualityJudgeDetector, _suspicious_outcome
from zing.detectors.reliability import ReliabilityDetector, _latency_deduction
from zing.detectors.scale import DeductionScale, Scale
from zing.detectors.security import SecurityDetector
from zing.detectors.streaming import StreamingDetector
from zing.models import CompletionOutcome, DetectorResult, Severity, Status, TargetConfig


def _scales() -> dict[str, Scale]:
    out = {}
    for m in pkgutil.iter_modules(detectors_pkg.__path__):
        mod = importlib.import_module(f"zing.detectors.{m.name}")
        for name, value in vars(mod).items():
            if name.endswith("SCALE") and isinstance(value, Scale):
                out[f"{m.name}.{name}"] = value
    return out


def _scale_of(det_id: str) -> Scale | None:
    mod = importlib.import_module(REGISTRY[det_id].__module__)
    scale = getattr(mod, "SCALE", None)
    return scale if isinstance(scale, Scale) else None


def _check(result: DetectorResult, scale: Scale) -> None:
    """Findings come from the scale; the score is what the scale computes."""
    assert result.scoring is not None and result.scoring.method == scale.method
    assert len(result.scoring.outcomes) == len(scale.outcomes)
    for f in result.findings:
        o = scale.get(f.scale_check, f.outcome or "")
        assert (f.status, f.severity, f.score, f.cap) == (o.status, o.severity, o.score, o.cap), f.id
        if o.max_deduction is not None:
            assert f.deduction is not None and 0.0 <= f.deduction <= o.max_deduction, f.id
        else:
            assert f.deduction == o.deduction, f.id
    if result.score is not None:
        expected = (
            DeductionScale.total(result.findings)
            if isinstance(scale, DeductionScale)
            else Scale.mean(result.findings)
        )
        assert result.score == expected


def test_every_detector_publishes_a_scale():
    missing = [d for d in REGISTRY if not d.startswith("protocol_") and _scale_of(d) is None]
    assert missing == []


def test_every_scale_label_is_translated():
    langs = i18n._load()
    for where, scale in _scales().items():
        texts = [o.label for o in scale.outcomes] + list(scale.titles.values())
        assert all(texts), where
        for code in ("zh", "de", "fr", "es", "pt", "it"):
            strings = langs[code]["strings"]
            assert [t for t in texts if t not in strings] == [], (where, code)


@pytest.mark.parametrize("det_id", sorted(d for d in REGISTRY if d != "quality_judge"))
async def test_honest_relay_findings_match_their_scale(audit_context, det_id):
    scale = _scale_of(det_id)
    if scale is None:
        pytest.skip("scored by its own module-level scales")
    result = await REGISTRY[det_id]().run(audit_context)
    _check(result, scale)


# --------------------------------------------------------------------------- #
# capability
# --------------------------------------------------------------------------- #
async def test_capability_failed_probes_are_not_counted(audit_context, mock_server):
    # Every probe errors: inconclusive checks no longer count 50 — nothing is scored.
    mock_server.chat_status = 500
    result = await CapabilityDetector().run(audit_context)
    _check(result, _scale_of("capability"))
    assert {f.outcome for f in result.findings} == {"failed"}
    assert result.score is None


async def test_capability_unclaimed_json_mode_is_not_counted(audit_context, mock_server):
    # No profile, plain prose back: no claim to verify, so neither the tool nor
    # the JSON-mode observation moves the score (and no JSON is not a warning).
    audit_context.profile = None
    mock_server.reply_text = "Sure, here you go: status ok, value 7429."
    result = await CapabilityDetector().run(audit_context)
    _check(result, _scale_of("capability"))
    by_check = {f.scale_check: f for f in result.findings}
    json_mode = by_check["capability.json_mode"]
    assert (json_mode.outcome, json_mode.status, json_mode.score) == ("no_json", Status.INFO, None)
    assert by_check["capability.tools"].score is None
    counted = [f for f in result.findings if f.score is not None]
    assert [f.scale_check for f in counted] == ["capability.max_output"]
    assert result.score == counted[0].score
    assert result.status == counted[0].status  # the short reply stops early


@pytest.mark.parametrize(
    ("reply", "expected"),
    [('{"name": "Ada", "age": 36}', "over_delivered"), ("Ada is 36.", "absent_as_claimed")],
)
async def test_capability_unclaimed_json_schema_is_not_counted(
    audit_context, mock_server, reply, expected
):
    # The profile says strict schemas are unsupported: whatever comes back is
    # informational and never costs (or earns) the model points.
    model = audit_context.profile.model.model_copy(update={"supports_json_schema": False})
    audit_context.profile = audit_context.profile.model_copy(update={"model": model})
    mock_server.reply_text = reply
    result = await CapabilityDetector().run(audit_context)
    _check(result, _scale_of("capability"))
    schema = next(f for f in result.findings if f.scale_check == "capability.json_schema")
    assert (schema.outcome, schema.status, schema.score) == (expected, Status.INFO, None)


# --------------------------------------------------------------------------- #
# streaming: buffering signals deduct 40, then 20, then nothing
# --------------------------------------------------------------------------- #
async def test_streaming_honest_is_100(audit_context, mock_server):
    result = await StreamingDetector().run(audit_context)
    assert result.score == 100.0 and result.status == Status.PASS


async def test_streaming_buffered_signals_deduct_40_then_20(audit_context, mock_server):
    mock_server.fake_stream = True
    mock_server.reply_text = "word " * 120  # enough text to expect many chunks
    result = await StreamingDetector().run(audit_context)
    _check(result, _scale_of("streaming"))
    deductions = [f.deduction for f in result.findings if f.outcome == "buffered"]
    assert deductions and deductions[:2] == [40.0, 20.0][: len(deductions)]
    assert result.score == (60.0 if len(deductions) == 1 else 40.0)
    assert result.status == Status.WARN


async def test_streaming_missing_usage_alone_deducts_15(audit_context, mock_server):
    mock_server.usage_in_stream = False
    result = await StreamingDetector().run(audit_context)
    f = next(f for f in result.findings if f.id == "streaming.no_usage")
    assert (f.outcome, f.deduction) == ("missing", 15.0)
    assert result.score == 85.0 and result.status == Status.WARN


async def test_streaming_failure_caps_at_0(audit_context, mock_server):
    mock_server.chat_status = 500
    result = await StreamingDetector().run(audit_context)
    assert result.score == 0.0 and result.status == Status.FAIL


# --------------------------------------------------------------------------- #
# security: the lowest cap wins
# --------------------------------------------------------------------------- #
async def test_security_plain_http_caps_at_40(audit_context):
    result = await SecurityDetector().run(audit_context)  # the mock relay is http://
    tls = next(f for f in result.findings if f.id == "security.tls")
    assert (tls.outcome, tls.cap) == ("plain_http", 40.0)
    assert result.score == 40.0 and result.status == Status.FAIL


async def test_security_key_echo_over_http_caps_at_30(audit_context, mock_server):
    # Before the scale, http + key echo scored 40 (http's value) although https +
    # key echo scored 30; with "the lowest cap wins" the echo dominates.
    mock_server.reply_text = f"Your key is {audit_context.target.api_key}"
    result = await SecurityDetector().run(audit_context)
    echo = next(f for f in result.findings if f.id == "security.key_echo")
    assert (echo.outcome, echo.cap) == ("echoed", 30.0)
    assert result.score == 30.0 and result.status == Status.FAIL


# --------------------------------------------------------------------------- #
# reliability: failed share, then 15% of the rest for a slow tail
# --------------------------------------------------------------------------- #
async def test_reliability_all_failing_scores_0(audit_context, mock_server):
    mock_server.chat_status = 500
    result = await ReliabilityDetector().run(audit_context)
    _check(result, _scale_of("reliability"))
    f = next(f for f in result.findings if f.id == "reliability.success_rate")
    assert (f.outcome, f.deduction) == ("many_failed", 100.0)
    assert result.score == 0.0 and result.status == Status.FAIL


def test_reliability_latency_deduction_matches_the_old_formula():
    for rate in (1.0, 0.95, 0.9, 0.37, 0.0):
        base = round(rate * 100, 1)
        old = round(base * 0.85, 1)
        assert round(base - _latency_deduction(rate), 1) == old


# --------------------------------------------------------------------------- #
# context window: the unrecalled share of the claim, and 15 for the middle
# --------------------------------------------------------------------------- #
def test_context_window_deduction_matches_the_old_formula():
    for ratio in (1.3, 1.0, 0.93, 0.61, 0.3333, 0.0):
        for lost in (False, True):
            old = round(min(1.0, ratio) * 100, 1)
            if lost:
                old = round(max(0.0, old - 15.0), 1)
            findings = [CW_SCALE.finding("context_window.window", "consistent", id="w",
                                         title="w", deduction=_window_deduction(ratio))]
            if lost:
                findings.append(CW_SCALE.finding("context_window.lost_in_middle", "lost", title="m"))
            assert DeductionScale.total(findings) == old, (ratio, lost)


async def test_context_window_truncation_scores_the_recalled_share(audit_context, mock_server):
    mock_server.truncate_above_tokens = 6000
    result = await ContextWindowDetector().run(audit_context)
    _check(result, CW_SCALE)
    verdict = next(f for f in result.findings if f.check == "context_window.window")
    assert verdict.outcome in ("truncated", "no_recall")
    assert result.score == round(100.0 - verdict.deduction, 1)


# --------------------------------------------------------------------------- #
# LLM judge: score by confidence, severity by confidence + corroboration
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("confidence", "corroborated", "key", "score", "status"),
    [
        ("high", True, "confident_corroborated", 25.0, Status.FAIL),
        ("high", False, "confident", 25.0, Status.WARN),
        ("medium", True, "suspicious", 50.0, Status.WARN),
        ("medium", False, "suspicious", 50.0, Status.WARN),
        ("low", True, "suspicious", 50.0, Status.WARN),
        # a missing / unrecognized confidence counts as low — never HIGH
        ("", True, "suspicious", 50.0, Status.WARN),
        ("", False, "suspicious", 50.0, Status.WARN),
        ("very sure", True, "suspicious", 50.0, Status.WARN),
        # the judge's phrasing of "high" still counts as high
        ("High.", True, "confident_corroborated", 25.0, Status.FAIL),
        ("very high", False, "confident", 25.0, Status.WARN),
    ],
)
def test_judge_suspicious_rows(confidence, corroborated, key, score, status):
    assert _suspicious_outcome(confidence, corroborated) == key
    o = JUDGE_SCALE.get("quality_judge.verdict", key)
    assert (o.score, o.status) == (score, status)


class _JudgeStub:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls: list[tuple[str, str]] = []

    async def evaluate_json(self, system, user, **_):
        self.calls.append((system, user))
        return dict(self.verdict)


class _AnswerStub:
    """Answers every probe with ``text``, or fails (HTTP 500) when it is None."""

    def __init__(self, text):
        self.text = text

    async def complete(self, spec):
        if self.text is None:
            return CompletionOutcome(ok=False, status_code=500, error_message="down")
        return CompletionOutcome(ok=True, status_code=200, content=self.text, finish_reason="stop")


async def _run_judge(confidence, *, baseline=None, claimed=None):
    target = TargetConfig(base_url="https://r.test/v1", model="served-id", claimed_model=claimed)
    judge = _JudgeStub({"verdict": "suspicious", "confidence": confidence})
    ctx = AuditContext(
        target=target, client=_AnswerStub("an answer"), options=AuditOptions(suite="deep"),
        kb=None, profile=None, baseline=target if baseline is not None else None,  # type: ignore[arg-type]
        baseline_client=baseline, judge=judge,
    )
    result = await QualityJudgeDetector().run(ctx)
    _check(result, JUDGE_SCALE)
    return result, judge


@pytest.mark.parametrize("confidence", ["", "low", "medium", "unsure"])
async def test_judge_without_high_confidence_never_reaches_high(confidence):
    result, _ = await _run_judge(confidence, baseline=_AnswerStub("baseline answer"))
    (f,) = result.findings
    assert (f.outcome, f.severity, result.status) == ("suspicious", Severity.MEDIUM, Status.WARN)


async def test_judge_high_confidence_with_failed_baseline_is_not_corroborated():
    result, judge = await _run_judge("high", baseline=_AnswerStub(None))
    (f,) = result.findings
    assert (f.outcome, f.severity) == ("confident", Severity.MEDIUM)
    assert f.evidence["baseline_corroborated"] is False
    assert result.evidence["baseline_compared"] is True
    assert result.evidence["baseline_usable"] is False
    # the unusable baseline is not shown to the judge either
    _, user = judge.calls[0]
    assert "baseline answer" not in user and "TRUSTED BASELINE" not in user


async def test_judge_high_confidence_with_working_baseline_is_high():
    result, _ = await _run_judge("high", baseline=_AnswerStub("baseline answer"))
    (f,) = result.findings
    assert (f.outcome, f.severity, result.status) == ("confident_corroborated", Severity.HIGH, Status.FAIL)
    assert f.evidence["baseline_corroborated"] is True


async def test_judge_is_told_the_claimed_model():
    result, judge = await _run_judge("high", claimed="claimed-id")
    system, user = judge.calls[0]
    assert "claimed-id" in system and "claimed-id" in user
    assert "served-id" not in system and "served-id" not in user
    assert result.evidence["claimed_model"] == "claimed-id"
