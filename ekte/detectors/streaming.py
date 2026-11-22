"""Streaming authenticity detector.

Checks whether the relay actually streams tokens or merely buffers the full
response and replays it as one or two chunks (``stream.fake-streaming``). True
token streaming shows many chunks, an early first token, and spread-out
inter-chunk gaps; a buffered fake collapses all of that into a single dump.

Four buffering signals, judged once at least ``_MIN_BUFFERED_CHARS`` came back
(issue #259): few chunks, a late first token, a first token that only comes
after the time the same prompt takes without streaming (one extra, non-streamed
call: a buffered answer replayed with a "typing" delay passes the other three),
and a burst (most gaps between chunks under 2 ms; check id
``streaming.uniform_gaps``, kept for stored reports).

Scoring follows the published ``SCALE`` (method "deductions"): the score starts
at 100; the first buffering signal deducts 40 points and a second one 20 more
(the score never drops below 40 for buffering alone); a missing usage chunk
deducts 15 only when nothing is buffered.

A failed stream request is repeated once (issue #255). A relay that refuses to
stream for this model (a 4xx naming streaming, or any other 4xx while the same
prompt without streaming succeeds) is ``streaming.unsupported`` and caps the
score at 0; any other failure (5xx, timeout, a rate limit) is a transport
failure, ``streaming.failed``, inconclusive and not scored. Both are advisories
(``ekte.scoring.ADVISORY_CHECKS``): they say how the relay is reached, not which
model it serves, so they never raise the substitution risk.

A reasoning model (``ekte.detectors.helpers.is_reasoning``: claimed by the
knowledge base, learned by the client, or reporting reasoning tokens) may think
for seconds before its first visible token and then write the answer quickly.
When that thinking is streamed (reasoning deltas), the first token of either
kind decides: a genuine stream starts reasoning early, a buffered one replays it
at the end. When the thinking is hidden, a late first visible token is noted,
not counted as buffering, and the non-streamed comparison is skipped. A stream
that succeeds but delivers no content cannot be judged at all and is
inconclusive (no score).
"""

from __future__ import annotations

from typing import Any

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import is_reasoning
from ekte.detectors.scale import DeductionScale, outcome
from ekte.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    RequestSpec,
    Severity,
    Status,
)
from ekte.perf.recorder import usage_tokens

# Buffered-streaming signals (few chunks / late first token) only make sense once
# enough text was produced that genuine streaming would have spanned many chunks.
# Below this, a fast small model finishing a short reply looks the same as a buffer.
_MIN_BUFFERED_CHARS = 220

# Late first token: above this share of the stream's duration; above the lower
# one when the non-streamed comparison confirms the buffering (#259).
_LATE_TTFT = 0.9
_LATE_TTFT_CONFIRMED = 0.75
# The streamed first token at or after this share of the non-streamed total: the
# answer was complete before the first chunk left.
_TTFT_VS_TOTAL = 0.8
# Below this non-streamed duration, two separate calls' timings are dominated by
# network and queueing noise (a very fast model): not compared.
_MIN_NON_STREAM_MS = 1000.0
# Burst: at least this many chunks with this share of the gaps below this.
_BURST_MIN_CHUNKS = 4
_BURST_SHARE = 0.8
_BURST_GAP_MS = 2.0

# Deductions of the 1st and 2nd buffering signal; any further one deducts nothing.
_SIGNAL_DEDUCTIONS = (40.0, 20.0)
_NO_USAGE_DEDUCTION = 15.0
_BUFFERED = (
    "Buffering signal: the first deducts 40 points, a second 20, any further one nothing."
)

SCALE = DeductionScale(
    outcome("streaming.healthy", "authentic", None, Status.PASS,
            label="Many chunks, an early first token and spread-out gaps: genuine streaming."),
    outcome("streaming.few_chunks", "buffered", None, Status.WARN, Severity.MEDIUM,
            max_deduction=_SIGNAL_DEDUCTIONS[0], label=_BUFFERED),
    outcome("streaming.late_ttft", "buffered", None, Status.WARN, Severity.MEDIUM,
            max_deduction=_SIGNAL_DEDUCTIONS[0], label=_BUFFERED),
    outcome("streaming.reasoning_ttft", "reasoning", None, Status.INFO,
            label="Late first token from a reasoning model (it thinks before answering): "
            "informational, not counted as buffering."),
    outcome("streaming.ttft_vs_total", "buffered", None, Status.WARN, Severity.MEDIUM,
            max_deduction=_SIGNAL_DEDUCTIONS[0], label=_BUFFERED),
    outcome("streaming.uniform_gaps", "buffered", None, Status.WARN, Severity.MEDIUM,
            max_deduction=_SIGNAL_DEDUCTIONS[0], label=_BUFFERED),
    outcome("streaming.no_usage", "missing", None, Status.WARN, Severity.LOW,
            max_deduction=_NO_USAGE_DEDUCTION,
            label="No usage chunk in the stream: deducts 15 points when nothing is buffered."),
    outcome("streaming.no_content", "no_content", None, Status.INCONCLUSIVE, Severity.LOW,
            label="The stream succeeded but delivered no content to judge by; not scored."),
    outcome("streaming.unsupported", "unsupported", None, Status.FAIL, Severity.MEDIUM, cap=0.0,
            label="The relay does not stream for this model."),
    outcome("streaming.failed", "failed", None, Status.INCONCLUSIVE, Severity.LOW,
            label="The streaming request failed twice (5xx, timeout or another transport "
            "failure); not scored."),
)

# 4xx statuses that are transient, not a refusal to stream: a timeout or a rate limit.
_TRANSIENT_4XX = frozenset({408, 429})


def _refuses_streaming(out: CompletionOutcome) -> bool | None:
    """True when a failed stream is a 4xx naming streaming, False when it is no
    4xx refusal at all (5xx, timeout, rate limit), None for another 4xx (decided
    by whether the same prompt succeeds without streaming)."""
    code = out.status_code
    if code is None or not 400 <= code < 500 or code in _TRANSIENT_4XX:
        return False
    return True if "stream" in (out.error_message or "").lower() else None


def _signal_deduction(signals: list[str]) -> float:
    """The deduction of the buffering signal just added to ``signals``."""
    i = len(signals) - 1
    return _SIGNAL_DEDUCTIONS[i] if i < len(_SIGNAL_DEDUCTIONS) else 0.0


def _first_ms(out: CompletionOutcome) -> float | None:
    """Time to the first streamed token of either kind (reasoning or content)."""
    return min((t for t in (out.ttft_ms, out.first_reasoning_ms) if t is not None), default=None)


async def _baseline_timing(ctx: AuditContext, spec: RequestSpec) -> dict[str, Any] | None:
    """Compare mode: the baseline's streamed first token and non-streamed total
    for the same prompt, recorded as evidence only (not scored)."""
    client = getattr(ctx, "baseline_client", None)
    if client is None:
        return None
    streamed = await client.complete(spec)
    plain = await client.complete(spec.model_copy(update={"stream": False}))
    first = _first_ms(streamed) if streamed.ok else None
    total = plain.duration_ms if plain.ok else None
    return {
        "ttft_ms": round(first, 1) if first is not None else None,
        "non_stream_ms": round(total, 1) if total is not None else None,
        "ttft_vs_total": round(first / total, 3) if first is not None and total else None,
    }


@register
class StreamingDetector(Detector):
    id = "streaming"
    name = "Streaming authenticity"
    dimension = Dimension.STREAMING
    min_suite = "standard"
    # The streamed request and the same prompt without streaming (#259).
    cost_hint = 2

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())

        spec = RequestSpec(
            messages=[
                {
                    "role": "user",
                    "content": prompts.text("streaming.sentences"),
                }
            ],
            temperature=0.0,
            max_tokens=256,
            stream=True,
        )
        out = await ctx.client.complete(spec)
        # One failed request is no evidence about streaming: repeat it once.
        calls = [out]
        if not out.ok:
            out = await ctx.client.complete(spec)
            calls.append(out)

        if not out.ok:
            refuses = _refuses_streaming(out)
            plain_ok: bool | None = None
            if refuses is None:
                # Another 4xx: a refusal to stream only if the same prompt works without it.
                unstreamed = await ctx.client.complete(spec.model_copy(update={"stream": False}))
                calls.append(unstreamed)
                plain_ok = unstreamed.ok
                refuses = unstreamed.ok
            evidence = {
                "status_code": out.status_code,
                "error_type": out.error_type,
                "attempts": 2,
                "non_stream_ok": plain_ok,
            }
            if refuses:
                result.findings.append(
                    SCALE.finding(
                        "streaming.unsupported",
                        "unsupported",
                        calls=calls,
                        title="Relay does not stream for this model",
                        summary=(
                            f"The streaming request was refused twice (HTTP {out.status_code})"
                            + (", while the same prompt without streaming succeeded"
                               if plain_ok else "")
                            + ": " + (out.error_message or "no error message") + "."
                        ),
                        evidence=evidence,
                        recommendation="Verify the relay supports stream=true for this model.",
                    )
                )
                result.status = Status.FAIL
                result.score = SCALE.total(result.findings)
            else:
                result.findings.append(
                    SCALE.finding(
                        "streaming.failed",
                        "failed",
                        calls=calls,
                        title="Streaming request failed",
                        summary=(
                            "The streaming request failed twice ("
                            + (out.error_message or f"HTTP {out.status_code}")
                            + "); streaming could not be assessed."
                        ),
                        evidence=evidence,
                        recommendation="Re-run the audit; if it keeps failing, check the "
                        "relay's status for this model.",
                    )
                )
                result.status = Status.INCONCLUSIVE
                result.score = None
            return result

        # A successful stream without any content: nothing to judge streaming by.
        if not out.has_content():
            result.findings.append(
                SCALE.finding(
                    "streaming.no_content",
                    "no_content",
                    calls=[out],
                    title="Stream delivered no content",
                    summary=(
                        f"The streaming request succeeded but delivered no content "
                        f"({out.chunk_count} chunk(s)); streaming could not be assessed."
                    ),
                    evidence={"chunk_count": out.chunk_count, "usage_present": out.usage is not None},
                    recommendation="Verify the relay streams content deltas for this model.",
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
            result.evidence.update(
                {"chunk_count": out.chunk_count, "content_chars": 0, "buffered_signals": []}
            )
            return result

        content_len = len(out.content or "")
        buffered_signals: list[str] = []
        # Reasoning models think before the first visible token. Streamed thinking
        # is itself a token stream, so the first token of either kind is timed;
        # only hidden thinking excuses a late first token.
        reasoning_tokens = usage_tokens(out.usage)["reasoning"] or 0
        reasoning = is_reasoning(ctx, out)
        first_ms = _first_ms(out)
        hidden_reasoning = reasoning and out.first_reasoning_ms is None
        judged = content_len >= _MIN_BUFFERED_CHARS

        # Signal 1: substantial content delivered in <=2 chunks.
        if judged and out.chunk_count <= 2:
            buffered_signals.append("few_chunks")
            result.findings.append(
                SCALE.finding(
                    "streaming.few_chunks",
                    "buffered",
                    calls=[out],
                    deduction=_signal_deduction(buffered_signals),
                    title="Response delivered in <=2 chunks",
                    summary=(
                        f"{content_len} chars arrived in {out.chunk_count} chunk(s) "
                        "(buffered-then-chunked, not true token streaming)."
                    ),
                    evidence={"content_chars": content_len, "chunk_count": out.chunk_count},
                )
            )

        # Signal 3, measured before signal 2 (whose bar depends on it): the same
        # prompt without streaming. A streamed first token that only comes after
        # most of the non-streamed total means the answer was complete before the
        # first chunk left: buffered, then replayed (e.g. with a "typing" delay).
        plain: CompletionOutcome | None = None
        vs_total: dict[str, Any] | None = None
        if judged and first_ms is not None and not hidden_reasoning:
            plain = await ctx.client.complete(spec.model_copy(update={"stream": False}))
            reasoning = is_reasoning(ctx, out, plain)
            hidden_reasoning = reasoning and out.first_reasoning_ms is None
            if (
                plain.ok
                and plain.has_content()
                and plain.duration_ms is not None
                and plain.duration_ms >= _MIN_NON_STREAM_MS
                and not hidden_reasoning
            ):
                vs_total = {
                    "ttft_ms": round(first_ms, 1),
                    "non_stream_ms": round(plain.duration_ms, 1),
                    "ttft_vs_total": round(first_ms / plain.duration_ms, 3),
                }
        vs_total_fires = vs_total is not None and vs_total["ttft_vs_total"] >= _TTFT_VS_TOTAL
        baseline = await _baseline_timing(ctx, spec) if plain is not None else None

        # Signal 2: first token arrives near the very end (response withheld). Only
        # meaningful when enough text was produced to expect multi-chunk streaming.
        # The bar drops from 90% to 75% when signal 3 confirms the buffering.
        late_bar = _LATE_TTFT_CONFIRMED if vs_total_fires else _LATE_TTFT
        if judged and first_ms is not None and out.duration_ms and out.duration_ms > 0:
            ttft_ratio = first_ms / out.duration_ms
            pct = round(ttft_ratio * 100)
            if ttft_ratio > _LATE_TTFT and hidden_reasoning:
                result.findings.append(
                    SCALE.finding(
                        "streaming.reasoning_ttft",
                        "reasoning",
                        calls=[out],
                        title="Late first token from a reasoning model",
                        summary=(
                            f"First visible token arrived at ~{pct}% of total time; the "
                            "model reasons before answering, so this is not counted as "
                            "buffering."
                        ),
                        evidence={
                            "ttft_ms": round(first_ms, 1),
                            "duration_ms": round(out.duration_ms, 1),
                            "ttft_ratio": round(ttft_ratio, 3),
                            "reasoning_tokens": reasoning_tokens or None,
                        },
                    )
                )
            elif ttft_ratio > late_bar and not hidden_reasoning:
                buffered_signals.append("late_ttft")
                result.findings.append(
                    SCALE.finding(
                        "streaming.late_ttft",
                        "buffered",
                        calls=[out],
                        deduction=_signal_deduction(buffered_signals),
                        title="First token arrived late in the stream",
                        summary=f"First token arrived at ~{pct}% of total time (buffered).",
                        evidence={
                            "ttft_ms": round(first_ms, 1),
                            "reasoning_streamed": out.first_reasoning_ms is not None,
                            "duration_ms": round(out.duration_ms, 1),
                            "ttft_ratio": round(ttft_ratio, 3),
                            "threshold": late_bar,
                        },
                    )
                )

        if vs_total_fires and plain is not None and vs_total is not None:
            buffered_signals.append("ttft_vs_total")
            result.findings.append(
                SCALE.finding(
                    "streaming.ttft_vs_total",
                    "buffered",
                    calls=[out, plain],
                    deduction=_signal_deduction(buffered_signals),
                    title="First token only after a whole non-streamed answer's time",
                    summary=(
                        f"The first streamed token came after {vs_total['ttft_ms']:.0f} ms, "
                        f"~{round(vs_total['ttft_vs_total'] * 100)}% of the "
                        f"{vs_total['non_stream_ms']:.0f} ms the same prompt takes without "
                        "streaming: the answer was complete before the first chunk was sent."
                    ),
                    evidence={**vs_total, **({"baseline": baseline} if baseline else {})},
                )
            )

        # Signal 4: many chunks dumped together in a burst (most gaps under 2 ms).
        # The check keeps its id ``streaming.uniform_gaps``, which stored reports
        # and translations carry (#259).
        deltas = [
            out.chunk_timings_ms[i] - out.chunk_timings_ms[i - 1]
            for i in range(1, len(out.chunk_timings_ms))
        ]
        if judged and out.chunk_count >= _BURST_MIN_CHUNKS and deltas:
            burst_gaps = sum(1 for d in deltas if d < _BURST_GAP_MS)
            burst_share = burst_gaps / len(deltas)
            if burst_share >= _BURST_SHARE:
                buffered_signals.append("uniform_gaps")
                result.findings.append(
                    SCALE.finding(
                        "streaming.uniform_gaps",
                        "buffered",
                        calls=[out],
                        deduction=_signal_deduction(buffered_signals),
                        title="Chunks arrived in a burst",
                        summary=(
                            f"{burst_gaps} of {len(deltas)} gaps between {out.chunk_count} "
                            f"chunks are under {_BURST_GAP_MS:g} ms: the chunks were "
                            "dumped together."
                        ),
                        evidence={
                            "chunk_count": out.chunk_count,
                            "burst_gaps": burst_gaps,
                            "gaps": len(deltas),
                            "burst_share": round(burst_share, 3),
                            "mean_delta_ms": round(sum(deltas) / len(deltas), 3),
                        },
                    )
                )

        # Usage chunk: only flag when usage is expected (or KB profile unknown).
        expects_usage = ctx.profile is None or ctx.profile.model.usage_in_stream
        missing_usage = out.usage is None and expects_usage
        if missing_usage:
            result.findings.append(
                SCALE.finding(
                    "streaming.no_usage",
                    "missing",
                    calls=[out],
                    deduction=0.0 if buffered_signals else _NO_USAGE_DEDUCTION,
                    title="No usage chunk in stream",
                    summary="stream_options.include_usage produced no usage data in the stream.",
                    evidence={"usage_present": False},
                )
            )

        # Healthy streaming evidence.
        if not buffered_signals:
            result.findings.append(
                SCALE.finding(
                    "streaming.healthy",
                    "authentic",
                    calls=[out] + ([plain] if plain is not None else []),
                    title="Streaming looks authentic",
                    summary=(
                        f"{out.chunk_count} chunks over {out.duration_ms:.0f} ms"
                        + (f", first token at {out.ttft_ms:.0f} ms" if out.ttft_ms is not None else "")
                        + "."
                    ),
                    evidence={
                        "chunk_count": out.chunk_count,
                        "duration_ms": round(out.duration_ms, 1) if out.duration_ms else None,
                        "ttft_ms": round(out.ttft_ms, 1) if out.ttft_ms is not None else None,
                    },
                )
            )

        # Score & status from collected signals.
        result.score = SCALE.total(result.findings)
        result.status = Status.WARN if buffered_signals or missing_usage else Status.PASS

        result.evidence.update(
            {
                "chunk_count": out.chunk_count,
                "content_chars": content_len,
                "duration_ms": round(out.duration_ms, 1) if out.duration_ms else None,
                "ttft_ms": round(out.ttft_ms, 1) if out.ttft_ms is not None else None,
                "first_reasoning_ms": (
                    round(out.first_reasoning_ms, 1) if out.first_reasoning_ms is not None else None
                ),
                "usage_present": out.usage is not None,
                "buffered_signals": buffered_signals,
                "reasoning": reasoning,
                "non_stream_ms": vs_total["non_stream_ms"] if vs_total else None,
                "ttft_vs_total": vs_total["ttft_vs_total"] if vs_total else None,
            }
        )
        if baseline is not None:
            result.evidence["baseline"] = baseline
        return result
