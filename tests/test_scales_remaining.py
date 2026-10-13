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
from zing.detectors import REGISTRY
from zing.detectors.capability import CapabilityDetector
from zing.detectors.context_window import SCALE as CW_SCALE
from zing.detectors.context_window import ContextWindowDetector, _window_deduction
from zing.detectors.quality_judge import SCALE as JUDGE_SCALE
from zing.detectors.quality_judge import _suspicious_outcome
from zing.detectors.reliability import ReliabilityDetector, _latency_deduction
from zing.detectors.scale import DeductionScale, Scale
from zing.detectors.security import SecurityDetector
from zing.detectors.streaming import StreamingDetector
from zing.models import DetectorResult, Status


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


async def _burst(n: int, failures: int) -> DetectorResult:
    """The reliability detector over a fake client whose first ``failures`` of
    ``n`` requests return HTTP 500."""
    from types import SimpleNamespace

    calls = []

    async def complete(spec):
        calls.append(spec)
        ok = len(calls) > failures
        return SimpleNamespace(ok=ok, duration_ms=120.0 if ok else None,
                               error_type=None if ok else "server_error",
                               status_code=200 if ok else 500)

    ctx = SimpleNamespace(client=SimpleNamespace(complete=complete),
                          options=SimpleNamespace(reliability_requests=n, reliability_concurrency=4))
    return await ReliabilityDetector().run(ctx)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("n", "failures", "outcome", "status"),
    [
        (8, 0, "all_succeeded", Status.PASS),
        (8, 1, "some_failed", Status.WARN),   # one transient failure of the default 8
        (8, 2, "many_failed", Status.FAIL),
        (4, 1, "many_failed", Status.FAIL),   # 75% success is below the 80% floor
        (20, 2, "some_failed", Status.WARN),  # 10%
        (20, 3, "many_failed", Status.FAIL),
    ],
)
async def test_reliability_tolerates_one_failure_and_status_follows_findings(n, failures, outcome, status):
    result = await _burst(n, failures)
    _check(result, _scale_of("reliability"))
    f = next(f for f in result.findings if f.id == "reliability.success_rate")
    assert f.outcome == outcome
    assert result.score == round(100.0 * (n - failures) / n, 1)
    # The detector status is the worst of its findings — never PASS over a FAIL.
    assert result.status == status == Scale.roll_up(result.findings)


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
    ("confidence", "high_sev", "key", "score", "status"),
    [
        ("high", True, "confident_corroborated", 25.0, Status.FAIL),
        ("high", False, "confident", 25.0, Status.WARN),
        ("medium", False, "suspicious", 50.0, Status.WARN),
        ("low", False, "suspicious", 50.0, Status.WARN),
        ("", True, "unrated_corroborated", 50.0, Status.FAIL),
        ("", False, "suspicious", 50.0, Status.WARN),
    ],
)
def test_judge_suspicious_rows(confidence, high_sev, key, score, status):
    assert _suspicious_outcome(confidence, high_sev) == key
    o = JUDGE_SCALE.get("quality_judge.verdict", key)
    assert (o.score, o.status) == (score, status)
