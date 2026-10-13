"""Context-window detector tests — truncation vs. parameter-rejection.

A real context-length rejection is a truncation signal; a max_tokens parameter
rejection (reasoning models) must NOT be misread as a shrunken context window.
"""

from __future__ import annotations

import re

import pytest

from zing.detectors.context_window import ContextWindowDetector, _build_haystack
from zing.models import CompletionOutcome, Status
from zing.utils.tokenize import estimate_tokens


def _outcome(status_code, message, *, needle="ZING-ABC", content="", ok=False):
    return CompletionOutcome(
        ok=ok,
        status_code=status_code,
        content=content,
        error_message=message,
        headers={"x-zing-needle": needle},
    )


def test_classify_context_length_error_is_size_rejection():
    o = _outcome(400, "This model's maximum context length is 8192 tokens; reduce the length of the messages")
    recalled, rejected, status = ContextWindowDetector._classify(o, 16000)
    assert recalled is False and rejected is True and status == "rejected"


def test_classify_max_tokens_param_error_is_not_size_rejection():
    o = _outcome(400, "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens'.")
    recalled, rejected, status = ContextWindowDetector._classify(o, 16000)
    assert rejected is False and status == "param_error"


def test_classify_recall_hit():
    o = _outcome(200, None, needle="ZING-ABC", content="the secret pass phrase is ZING-ABC", ok=True)
    recalled, rejected, status = ContextWindowDetector._classify(o, 4000)
    assert recalled is True and status == "recalled"


async def test_truncation_below_claim_is_flagged(audit_context, mock_server):
    # gpt-4o claims a 128K window, but the relay rejects anything past ~6000 chars.
    mock_server.truncate_above_tokens = 6000
    result = await ContextWindowDetector().run(audit_context)
    assert result.status == Status.FAIL
    assert any(
        f.id in ("context_window.truncation", "context_window.no_recall",
                 "context_window.rejected_below_claim")
        for f in result.findings
    )


def test_classify_timeout_is_its_own_status():
    o = CompletionOutcome(ok=False, error_type="ReadTimeout", headers={"x-zing-needle": "N"})
    assert ContextWindowDetector._classify(o, 16000) == (False, False, "timeout")


async def test_timeout_is_inconclusive_not_truncation(audit_context):
    # A slow endpoint: recalls small prompts, times out on large ones.
    real = audit_context.client.complete
    timed_out_sizes: list[int] = []

    async def slow_complete(spec):
        size = len(spec.messages[0]["content"])
        if size > 20_000:
            timed_out_sizes.append(size)
            return CompletionOutcome(ok=False, error_type="ReadTimeout", error_message="timed out")
        return await real(spec)

    audit_context.client.complete = slow_complete
    result = await ContextWindowDetector().run(audit_context)
    ids = {f.id for f in result.findings}
    assert result.status == Status.INCONCLUSIVE
    assert result.score is None
    assert "context_window.timed_out" in ids
    assert not ids & {"context_window.truncation", "context_window.short", "context_window.no_recall"}
    # The ladder stops at the first timeout instead of retrying the other edge.
    assert len(timed_out_sizes) == 1


# --------------------------------------------------------------------------- #
# Start edge first: a server that keeps only the END of a long prompt
# --------------------------------------------------------------------------- #
_NEEDLE = re.compile(r"pass phrase is (ZING-[0-9A-F]+)")


def _keep_tail_server(audit_context, *, keep_chars: int | None, miss_first: bool = False):
    """Answer each probe from the last ``keep_chars`` characters of the prompt
    (``None`` keeps it all), like a local runtime cutting a prompt to its context
    length. Records the prompt length of every call."""
    calls: list[int] = []
    missed: list[bool] = []

    async def complete(spec):
        prompt = spec.messages[0]["content"]
        calls.append(len(prompt))
        kept = prompt if keep_chars is None else prompt[-keep_chars:]
        found = _NEEDLE.search(kept)
        if miss_first and not missed:
            missed.append(True)
            found = None  # one benign miss: a paraphrase instead of the marker
        content = found.group(1) if found else "I could not find a pass phrase."
        return CompletionOutcome(ok=True, status_code=200, content=content)

    audit_context.client.complete = complete
    return calls


async def test_honest_server_measures_the_window_with_one_call_per_size(audit_context):
    calls = _keep_tail_server(audit_context, keep_chars=None)
    result = await ContextWindowDetector().run(audit_context)
    ladder = result.evidence["ladder"]
    assert all(row["recalled"] and row["status"] == "recalled" for row in ladder)
    assert result.evidence["effective_window"] == ladder[-1]["size"]
    assert result.evidence["front_truncated_at"] is None
    # One call per ladder size, plus the three lost-in-the-middle depths.
    assert len(calls) == result.evidence["calls"] == len(ladder) + 3
    assert "context_window.consistent" in {f.id for f in result.findings}


async def test_front_truncating_server_fails_at_its_kept_length(audit_context):
    keep = 40_000  # characters: well below the declared 128K-token window
    _keep_tail_server(audit_context, keep_chars=keep)
    result = await ContextWindowDetector().run(audit_context)
    ladder = [row for row in result.evidence["ladder"] if not row.get("refine")]
    failed = ladder[-1]
    assert failed["status"] == "front_truncated" and not failed["rejected"]
    assert all(row["recalled"] for row in ladder[:-1])
    window = result.evidence["effective_window"]
    assert window is not None and window < failed["size"]
    assert window < 0.5 * result.evidence["declared"]
    assert result.status == Status.FAIL
    verdict = next(f for f in result.findings if f.check == "context_window.window")
    assert verdict.id == "context_window.truncation"
    assert verdict.evidence["front_truncated"] is True
    assert verdict.evidence["front_truncated_at"] == result.evidence["front_truncated_at"]
    assert "front truncation" in verdict.summary


async def test_front_truncation_without_a_declared_window_is_reported(audit_context, monkeypatch):
    monkeypatch.setattr(audit_context, "declared_context_window", lambda: None)
    audit_context.options.max_context_probe_tokens = 64_000
    _keep_tail_server(audit_context, keep_chars=40_000)
    result = await ContextWindowDetector().run(audit_context)
    measured = next(f for f in result.findings if f.id == "context_window.measured")
    assert result.status == Status.INFO and result.score is None
    assert measured.evidence["effective_window"] < 64_000
    assert measured.evidence["front_truncated"] is True


async def test_a_single_start_miss_is_retried_with_a_fresh_needle(audit_context):
    calls = _keep_tail_server(audit_context, keep_chars=None, miss_first=True)
    result = await ContextWindowDetector().run(audit_context)
    ladder = result.evidence["ladder"]
    assert all(row["recalled"] for row in ladder)
    assert result.evidence["front_truncated_at"] is None
    # The first size took three calls (start miss, end, start again); the rest one.
    assert len(calls) == len(ladder) + 2 + 3
    assert calls[0] == calls[1] == calls[2] < calls[3]
    assert "context_window.consistent" in {f.id for f in result.findings}


async def test_a_miss_at_both_edges_fails_after_two_calls(audit_context):
    async def complete(spec):
        return CompletionOutcome(ok=True, status_code=200, content="no idea")

    audit_context.client.complete = complete
    recalled, rejected, status, n = await ContextWindowDetector()._probe_size(
        audit_context, 4_000, tokenizer=None
    )
    assert (recalled, rejected, status, n) == (False, False, "no_recall", 2)


async def test_front_truncated_size_takes_three_calls_with_a_fresh_start_needle(audit_context):
    seen: list[str] = []
    calls = _keep_tail_server(audit_context, keep_chars=10_000)
    keep_tail = audit_context.client.complete

    async def complete(spec):
        seen.append(_NEEDLE.search(spec.messages[0]["content"]).group(1))
        return await keep_tail(spec)

    audit_context.client.complete = complete
    recalled, rejected, status, n = await ContextWindowDetector()._probe_size(
        audit_context, 16_000, tokenizer=None
    )
    assert (recalled, rejected, status, n) == (False, False, "front_truncated", 3)
    assert len(calls) == 3
    # Start, end, start again: the re-probe's needle is not the first one.
    assert len(set(seen)) == 3


# --------------------------------------------------------------------------- #
# Ladder, margin, cap and error handling
# --------------------------------------------------------------------------- #
# Real tokenizers count the filler up to ~15% higher than zing's heuristic.
_REAL_PER_HEURISTIC = 1.15


def _window_server(audit_context, *, window: int | None, middle_misses: int = 0,
                   error: CompletionOutcome | None = None, error_above: int = 0):
    """An honest endpoint: recalls every needle, rejects a prompt only when its
    REAL token count (plus the 64-token answer) exceeds ``window``. The first
    ``middle_misses`` probes with the needle near the middle are answered without
    it; ``error`` answers every prompt longer than ``error_above`` characters."""
    calls: list[int] = []
    left = [middle_misses]

    async def complete(spec):
        prompt = spec.messages[0]["content"]
        calls.append(len(prompt))
        if error is not None and len(prompt) > error_above:
            return error
        if window and estimate_tokens(prompt) * _REAL_PER_HEURISTIC + 64 > window:
            return CompletionOutcome(
                ok=False, status_code=400,
                error_message=f"This model's maximum context length is {window} tokens",
            )
        found = _NEEDLE.search(prompt)
        at = found.start() / len(prompt) if found else 0.0
        if found and left[0] and 0.3 < at < 0.7:
            left[0] -= 1
            found = None
        content = found.group(1) if found else "I could not find a pass phrase."
        return CompletionOutcome(ok=True, status_code=200, content=content)

    audit_context.client.complete = complete
    return calls


def test_ladder_rungs_stay_below_the_window():
    for upper in (2_048, 8_192, 32_768, 128_000, 131_072, 200_000):
        sizes = ContextWindowDetector._ladder(1_000, upper)
        assert 3 <= len(sizes) <= 7, upper
        assert sizes == sorted(set(sizes))
        # The 90% rung is always the top one; no rung reaches the full window.
        assert sizes[-1] == int(upper * 0.9)
        assert all(s <= 0.9 * upper for s in sizes)
    # A window too small for any sensible rung gets no ladder.
    assert ContextWindowDetector._ladder(1_000, 200) == []


def test_haystack_real_tokens_stay_within_the_rung():
    for size in (460, 1_843, 7_372, 57_600, 115_200):
        prompt = _build_haystack(size, needle="ZING-0123456789", depth=0.5, tokenizer=None)
        assert "ZING-0123456789" in prompt
        assert estimate_tokens(prompt) * _REAL_PER_HEURISTIC <= size


@pytest.mark.parametrize("declared", [2_048, 8_192, 32_768, 131_072, 200_000])
async def test_honest_endpoint_passes_at_its_full_window(audit_context, monkeypatch, declared):
    monkeypatch.setattr(audit_context, "declared_context_window", lambda: declared)
    _window_server(audit_context, window=declared)
    result = await ContextWindowDetector().run(audit_context)
    assert result.status == Status.PASS and result.score == 100.0
    assert [f.id for f in result.findings] == ["context_window.consistent"]


async def test_window_above_the_cap_is_verified_to_the_cap(audit_context, monkeypatch):
    monkeypatch.setattr(audit_context, "declared_context_window", lambda: 1_048_576)
    audit_context.options.max_context_probe_tokens = 64_000
    _window_server(audit_context, window=1_048_576)
    result = await ContextWindowDetector().run(audit_context)
    verdict = next(f for f in result.findings if f.check == "context_window.window")
    assert verdict.id == "context_window.verified_to_cap" and verdict.status == Status.PASS
    assert result.status == Status.PASS and result.score == 100.0
    assert verdict.evidence["declared"] == 1_048_576
    assert verdict.evidence["upper"] == verdict.evidence["probe_cap"] == 64_000
    assert verdict.evidence["effective_window"] == int(64_000 * 0.9)


async def test_truncation_below_the_cap_still_fails(audit_context, monkeypatch):
    # Declared 1M, probed up to the 200K cap, but the endpoint holds only 60K.
    monkeypatch.setattr(audit_context, "declared_context_window", lambda: 1_000_000)
    _window_server(audit_context, window=60_000)
    result = await ContextWindowDetector().run(audit_context)
    verdict = next(f for f in result.findings if f.check == "context_window.window")
    assert verdict.id == "context_window.truncation" and result.status == Status.FAIL


async def test_truncating_endpoint_fails(audit_context):
    # The mock declares 128K; the endpoint holds only 60K.
    _window_server(audit_context, window=60_000)
    result = await ContextWindowDetector().run(audit_context)
    assert result.status == Status.FAIL
    verdict = next(f for f in result.findings if f.check == "context_window.window")
    assert verdict.id == "context_window.truncation"
    assert verdict.evidence["effective_window"] < 60_000


async def test_window_between_half_and_top_is_short(audit_context):
    # 80K of a declared 128K: the two refine steps land it in the WARN band (the
    # detector FAILs on the separate rejected_below_claim finding).
    _window_server(audit_context, window=80_000)
    result = await ContextWindowDetector().run(audit_context)
    verdict = next(f for f in result.findings if f.check == "context_window.window")
    assert verdict.id == "context_window.short" and result.status == Status.FAIL
    assert 0.5 <= verdict.evidence["ratio"] < 0.9


def test_classify_413_is_a_size_rejection():
    o = _outcome(413, "Request Entity Too Large")
    assert ContextWindowDetector._classify(o, 16000) == (False, True, "rejected")


async def test_parameter_rejection_is_inconclusive_not_no_recall(audit_context):
    rejected = CompletionOutcome(
        ok=False, status_code=400,
        error_message="Unsupported value: 'temperature' does not support 0 with this model.",
    )
    _window_server(audit_context, window=None, error=rejected)
    result = await ContextWindowDetector().run(audit_context)
    ids = {f.id for f in result.findings}
    assert result.status == Status.INCONCLUSIVE and result.score is None
    assert "context_window.probe_error" in ids
    assert not ids & {"context_window.no_recall", "context_window.truncation", "context_window.short"}
    finding = next(f for f in result.findings if f.id == "context_window.probe_error")
    assert finding.evidence["error_status"] == "param_error"
    assert finding.evidence["status_code"] == 400


async def test_server_error_above_a_size_stops_the_ladder_inconclusive(audit_context):
    _window_server(audit_context, window=None, error_above=60_000,
                   error=CompletionOutcome(ok=False, status_code=502, error_message="bad gateway"))
    result = await ContextWindowDetector().run(audit_context)
    assert result.status == Status.INCONCLUSIVE and result.score is None
    assert {f.id for f in result.findings} == {"context_window.probe_error"}
    assert result.evidence["effective_window"] is not None
    assert result.evidence["errored_at"] > result.evidence["effective_window"]


async def test_a_single_middle_miss_is_confirmed_with_a_fresh_needle(audit_context):
    _window_server(audit_context, window=None, middle_misses=1)
    result = await ContextWindowDetector().run(audit_context)
    assert result.evidence["depth_results"]["0.5"] is False
    assert result.evidence["depth_results"]["0.5_retry"] is True
    assert "context_window.lost_in_middle" not in {f.id for f in result.findings}
    assert result.status == Status.PASS


async def test_a_confirmed_middle_miss_is_lost_in_the_middle(audit_context):
    _window_server(audit_context, window=None, middle_misses=2)
    result = await ContextWindowDetector().run(audit_context)
    assert result.evidence["depth_results"]["0.5_retry"] is False
    lost = next(f for f in result.findings if f.id == "context_window.lost_in_middle")
    assert lost.status == Status.WARN and result.status == Status.WARN
    assert result.score == 85.0
