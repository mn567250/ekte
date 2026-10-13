"""Published scoring scales of the connectivity and determinism detectors.

Each finding's status, severity and points come from the detector's ``SCALE``,
the scale travels with the result, and the detector score is the mean of the
counted checks — the same pattern as the protocol pilot
(tests/test_scoring_transparency.py).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from zing.detectors import connectivity, determinism
from zing.detectors.connectivity import ConnectivityDetector
from zing.detectors.determinism import DeterminismDetector
from zing.models import CompletionOutcome, DetectorResult, Status


def _ok(text: str) -> CompletionOutcome:
    return CompletionOutcome(ok=True, status_code=200, content=text, duration_ms=120.0)


_DOWN = CompletionOutcome(ok=False, status_code=503, error_message="Service unavailable")


def _by_id(result: DetectorResult) -> dict:
    return {f.id: f for f in result.findings}


def _matches_scale(result: DetectorResult, scale) -> None:
    assert result.scoring is not None and result.scoring.method == "mean_of_checks"
    assert len(result.scoring.outcomes) == len(scale.outcomes)
    for f in result.findings:
        o = scale.get(f.id, f.outcome or "")
        assert (f.score, f.status, f.severity) == (o.score, o.status, o.severity), f.id


@pytest.mark.parametrize("scale", [connectivity.SCALE, determinism.SCALE])
def test_every_outcome_has_a_label(scale):
    assert all(o.label for o in scale.outcomes)


# --------------------------------------------------------------------------- #
# connectivity
# --------------------------------------------------------------------------- #
async def _connectivity(models_ok: bool, chat: CompletionOutcome | None) -> DetectorResult:
    listing = CompletionOutcome(ok=models_ok, status_code=200 if models_ok else 404)

    async def list_models():
        return listing, (["gpt-4o"] if models_ok else [])

    async def complete(spec):
        if chat is not None:
            return chat
        # echo the canary the prompt asks for
        return _ok(next(w for w in spec.messages[0]["content"].split() if w.startswith("ZING-")))

    ctx = SimpleNamespace(client=SimpleNamespace(list_models=list_models, complete=complete),
                          target=SimpleNamespace(model="gpt-4o"))
    return await ConnectivityDetector().run(ctx)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("models_ok", "chat", "outcomes", "score", "status"),
    [
        (True, None, ("listed", "canary_echoed"), 100.0, Status.PASS),
        (True, _ok("Hello there."), ("listed", "canary_missing"), 92.5, Status.PASS),
        (False, None, ("unavailable", "canary_echoed"), 80.0, Status.WARN),  # worst of the checks
        (True, _DOWN, ("listed", "failed"), 50.0, Status.FAIL),
        (False, _DOWN, ("unavailable", "failed"), 30.0, Status.FAIL),
    ],
)
async def test_connectivity_scores_from_its_scale(models_ok, chat, outcomes, score, status):
    result = await _connectivity(models_ok, chat)
    _matches_scale(result, connectivity.SCALE)
    by_id = _by_id(result)
    assert (by_id["connectivity.models"].outcome, by_id["connectivity.chat"].outcome) == outcomes
    assert result.score == score and result.status == status


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
async def _determinism(temp1: list[CompletionOutcome], temp0: list[CompletionOutcome],
                       reasoning: bool = False) -> DetectorResult:
    queue = list(temp1) + list(temp0)

    async def complete(_spec):
        return queue.pop(0)

    profile = SimpleNamespace(model=SimpleNamespace(reasoning=reasoning))
    ctx = SimpleNamespace(client=SimpleNamespace(complete=complete), profile=profile)
    return await DeterminismDetector().run(ctx)  # type: ignore[arg-type]


_N = DeterminismDetector.CACHING_SAMPLES
_VARIED = [_ok(f"A story, take {i}.") for i in range(_N)]
_SAME = [_ok("The very same story.") for _ in range(_N)]
_STABLE = [_ok("Paris"), _ok("Paris")]


async def test_determinism_varied_samples_pass_and_temp0_is_not_counted():
    result = await _determinism(_VARIED, [_ok("Paris"), _ok("Paris.")])
    _matches_scale(result, determinism.SCALE)
    by_id = _by_id(result)
    assert by_id["determinism.temp1_variability"].outcome == "varies"
    t0 = by_id["determinism.temp0_stability"]
    assert (t0.outcome, t0.status, t0.score) == ("drifts", Status.INFO, None)
    assert result.score == 100.0 and result.status == Status.PASS


async def test_determinism_identical_samples_warn():
    result = await _determinism(_SAME, _STABLE)
    _matches_scale(result, determinism.SCALE)
    f = _by_id(result)["determinism.temp1_variability"]
    assert (f.outcome, f.score, f.status) == ("identical", 55.0, Status.WARN)
    assert _by_id(result)["determinism.temp0_stability"].outcome == "stable"
    assert result.score == 55.0 and result.status == Status.WARN


async def test_determinism_identical_samples_of_a_reasoning_model_are_not_caching():
    result = await _determinism(_SAME, _STABLE, reasoning=True)
    f = _by_id(result)["determinism.temp1_variability"]
    assert (f.outcome, f.score, f.status) == ("identical_reasoning", 100.0, Status.INFO)
    assert result.score == 100.0 and result.status == Status.PASS


async def test_determinism_without_usable_samples_has_no_score():
    result = await _determinism([_DOWN] * _N, [_DOWN, _DOWN])
    _matches_scale(result, determinism.SCALE)
    by_id = _by_id(result)
    assert by_id["determinism.temp1_variability"].outcome == "not_assessed"
    assert by_id["determinism.temp0_stability"].outcome == "not_assessed"
    assert result.score is None and result.status == Status.INCONCLUSIVE


async def test_determinism_two_identical_survivors_are_inconclusive():
    # 2 failed + 2 identical samples: too few usable samples to call caching.
    result = await _determinism([_DOWN, _DOWN] + _SAME[:2], _STABLE)
    _matches_scale(result, determinism.SCALE)
    f = _by_id(result)["determinism.temp1_variability"]
    assert (f.outcome, f.status, f.score) == ("not_assessed", Status.INCONCLUSIVE, None)
    assert f.evidence["usable_samples"] == 2
    assert f.evidence["required_samples"] == DeterminismDetector.MIN_USABLE_SAMPLES == 3
    assert "Only 2 of 4 samples were usable" in f.summary
    assert result.score is None and result.status == Status.INCONCLUSIVE


async def test_determinism_empty_samples_are_not_reported_as_http_failures():
    result = await _determinism([_ok(""), _ok("")] + _SAME[:2], _STABLE)
    f = _by_id(result)["determinism.temp1_variability"]
    assert f.outcome == "not_assessed"
    assert f.summary.endswith("the response had no content") and "HTTP" not in f.summary


async def test_determinism_three_identical_usable_samples_warn():
    result = await _determinism([_DOWN] + _SAME[:3], _STABLE)
    f = _by_id(result)["determinism.temp1_variability"]
    assert (f.outcome, f.status, f.evidence["samples"]) == ("identical", Status.WARN, 3)
    assert result.score == 55.0 and result.status == Status.WARN
