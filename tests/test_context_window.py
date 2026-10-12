"""Context-window detector tests — truncation vs. parameter-rejection.

A real context-length rejection is a truncation signal; a max_tokens parameter
rejection (reasoning models) must NOT be misread as a shrunken context window.
"""

from __future__ import annotations

import re

from zing.detectors.context_window import ContextWindowDetector
from zing.models import CompletionOutcome, Status


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
        audit_context, 4_000, tokenizer=None, reasoning=False
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
        audit_context, 16_000, tokenizer=None, reasoning=False
    )
    assert (recalled, rejected, status, n) == (False, False, "front_truncated", 3)
    assert len(calls) == 3
    # Start, end, start again: the re-probe's needle is not the first one.
    assert len(set(seen)) == 3
