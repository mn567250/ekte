"""The streaming detector's buffering signals against synthetic timings (#259).

Before #259 a buffered answer replayed in a burst was caught by the late first
token alone (the "uniform gaps" signal asked for a coefficient of variation
below 0.1, which jittery burst gaps never have), and an answer buffered whole
and replayed with a typing delay passed as genuine streaming.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from ekte.detectors.streaming import SCALE, StreamingDetector
from ekte.models import CompletionOutcome, DetectorResult, Status

_USAGE = {"prompt_tokens": 20, "completion_tokens": 100, "total_tokens": 120}


def _timed(gaps: list[float], *, start: float = 3000.0, content: str = "x" * 400,
           **extra) -> CompletionOutcome:
    ts = [start]
    for g in gaps:
        ts.append(ts[-1] + g)
    return CompletionOutcome(ok=True, status_code=200, content=content, chunk_count=len(ts),
                             ttft_ms=ts[0], duration_ms=ts[-1] + 1, chunk_timings_ms=ts,
                             usage=dict(_USAGE), **extra)


def _plain(duration: float | None = 3000.0, *, ok: bool = True, usage: dict | None = None):
    return CompletionOutcome(ok=ok, status_code=200 if ok else 503, content="x" * 400 if ok else "",
                             duration_ms=duration, usage=usage or dict(_USAGE))


def _burst() -> CompletionOutcome:
    rng = random.Random(259)
    return _timed([0.05 + rng.uniform(0, 0.4) for _ in range(39)])


def _paced() -> CompletionOutcome:
    rng = random.Random(259)
    return _timed([30 + rng.uniform(0, 10) for _ in range(39)])


def _honest() -> CompletionOutcome:
    # First token at 300 ms, then spread-out gaps up to ~3 s.
    rng = random.Random(259)
    return _timed([55 + rng.uniform(0, 30) for _ in range(39)], start=300.0)


async def _run(streamed: CompletionOutcome, plain: CompletionOutcome | None = None, *,
               reasoning: bool = False, reasoning_room: bool = False,
               baseline: tuple[CompletionOutcome, CompletionOutcome] | None = None):
    seen: list[bool] = []

    async def complete(spec):
        seen.append(bool(spec.stream))
        return streamed if spec.stream else (plain or _plain())

    base_seen: list[bool] = []

    async def base_complete(spec):
        base_seen.append(bool(spec.stream))
        assert baseline is not None
        return baseline[0] if spec.stream else baseline[1]

    model = SimpleNamespace(reasoning=reasoning, usage_in_stream=True)
    ctx = SimpleNamespace(
        client=SimpleNamespace(complete=complete, reasoning_room=reasoning_room),
        profile=SimpleNamespace(model=model),
        baseline_client=SimpleNamespace(complete=base_complete) if baseline else None,
    )
    result: DetectorResult = await StreamingDetector().run(ctx)  # type: ignore[arg-type]
    for f in result.findings:  # every finding comes from the published scale
        o = SCALE.get(f.scale_check, f.outcome or "")
        assert (f.status, f.severity) == (o.status, o.severity), f.id
    return result, seen, base_seen


def _ids(result: DetectorResult) -> set[str]:
    return {f.id for f in result.findings}


async def test_a_burst_after_a_wait_fires_late_ttft_and_the_burst_signal():
    # Scenario (a); no usable non-streamed comparison, so exactly two signals.
    result, _, _ = await _run(_burst(), _plain(ok=False))
    assert {"streaming.late_ttft", "streaming.uniform_gaps"} <= _ids(result)
    assert "streaming.ttft_vs_total" not in _ids(result)
    assert result.score == 40.0 and result.status == Status.WARN
    burst = next(f for f in result.findings if f.id == "streaming.uniform_gaps")
    assert burst.title == "Chunks arrived in a burst"
    assert burst.evidence["burst_share"] == 1.0 and burst.evidence["gaps"] == 39


async def test_a_burst_with_the_non_streamed_comparison_still_scores_40():
    result, _, _ = await _run(_burst(), _plain(3000.0))
    assert result.evidence["buffered_signals"] == ["late_ttft", "ttft_vs_total", "uniform_gaps"]
    assert [f.deduction for f in result.findings if f.outcome == "buffered"] == [40.0, 20.0, 0.0]
    assert result.score == 40.0


async def test_a_paced_replay_fires_ttft_vs_total():
    # Scenario (b): buffered whole, then replayed with ~35 ms per chunk.
    result, seen, _ = await _run(_paced(), _plain(3000.0))
    assert seen == [True, False]
    ids = _ids(result)
    assert "streaming.ttft_vs_total" in ids
    assert "streaming.late_ttft" not in ids and "streaming.uniform_gaps" not in ids
    assert "streaming.healthy" not in ids
    assert result.score == 60.0 and result.status == Status.WARN
    f = next(f for f in result.findings if f.id == "streaming.ttft_vs_total")
    assert (f.outcome, f.deduction) == ("buffered", 40.0)
    assert f.evidence["non_stream_ms"] == 3000.0 and f.evidence["ttft_vs_total"] == 1.0


async def test_late_ttft_drops_to_75_percent_only_with_ttft_vs_total():
    # First token at ~80% of the stream: below 90%, above 75%.
    streamed = _timed([25.0] * 30, start=3000.0)  # ends at ~3751 ms
    alone, _, _ = await _run(streamed, _plain(6000.0))
    assert alone.score == 100.0 and "streaming.late_ttft" not in _ids(alone)
    both, _, _ = await _run(streamed, _plain(3000.0))
    late = next(f for f in both.findings if f.id == "streaming.late_ttft")
    assert late.evidence["threshold"] == 0.75
    assert {"streaming.late_ttft", "streaming.ttft_vs_total"} <= _ids(both)
    assert both.score == 40.0


async def test_an_honest_stream_stays_healthy():
    result, seen, _ = await _run(_honest(), _plain(3000.0))
    assert seen == [True, False]
    assert "streaming.healthy" in _ids(result) and result.evidence["buffered_signals"] == []
    assert result.evidence["ttft_vs_total"] == 0.1
    assert result.score == 100.0 and result.status == Status.PASS


async def test_a_short_answer_is_not_judged_and_costs_no_extra_call():
    result, seen, _ = await _run(_burst().model_copy(update={"content": "x" * 200}))
    assert seen == [True]
    assert result.evidence["buffered_signals"] == [] and result.score == 100.0


@pytest.mark.parametrize("how", ["profile", "learned", "usage"])
async def test_hidden_reasoning_is_not_flagged(how):
    usage = {**_USAGE, "completion_tokens_details": {"reasoning_tokens": 300}}
    streamed = _paced().model_copy(update={"usage": usage} if how == "usage" else {})
    result, seen, _ = await _run(streamed, _plain(3000.0), reasoning=how == "profile",
                                 reasoning_room=how == "learned")
    assert seen == [True]  # no non-streamed comparison for hidden thinking
    assert result.evidence["buffered_signals"] == [] and result.evidence["reasoning"] is True
    assert result.score == 100.0


async def test_reasoning_reported_only_by_the_non_streamed_call_is_not_flagged():
    result, seen, _ = await _run(
        _paced(), _plain(3000.0, usage={**_USAGE, "completion_tokens_details": {"reasoning_tokens": 300}}))
    assert seen == [True, False]
    assert "streaming.ttft_vs_total" not in _ids(result) and result.score == 100.0


async def test_a_fast_non_streamed_answer_is_not_compared():
    # Under a second the two calls' timings are mostly network noise.
    result, _, _ = await _run(_paced(), _plain(900.0))
    assert "streaming.ttft_vs_total" not in _ids(result)
    assert result.evidence["ttft_vs_total"] is None and result.score == 100.0


async def test_compare_mode_records_the_baselines_numbers_without_scoring():
    base_stream = _honest()
    result, _, base_seen = await _run(_paced(), _plain(3000.0),
                                      baseline=(base_stream, _plain(3000.0)))
    assert base_seen == [True, False]
    expected = {"ttft_ms": 300.0, "non_stream_ms": 3000.0, "ttft_vs_total": 0.1}
    assert result.evidence["baseline"] == expected
    f = next(f for f in result.findings if f.id == "streaming.ttft_vs_total")
    assert f.evidence["baseline"] == expected
    assert result.score == 60.0  # the baseline changes nothing


async def test_jitter_free_near_zero_gaps_still_count_as_a_burst():
    result, _, _ = await _run(_timed([0.1] * 39, start=100.0), _plain(ok=False))
    assert "streaming.uniform_gaps" in _ids(result) and result.status == Status.WARN


def test_the_burst_row_keeps_its_stored_check_id():
    checks = [o.check for o in SCALE.outcomes]
    assert "streaming.uniform_gaps" in checks and "streaming.ttft_vs_total" in checks
