"""Streaming authenticity detector.

Checks whether the relay actually streams tokens or merely buffers the full
response and replays it as one or two chunks (``stream.fake-streaming``). True
token streaming shows many chunks, an early first token, and spread-out
inter-chunk gaps; a buffered fake collapses all of that into a single dump.

Scoring follows the published ``SCALE`` (method "deductions"): the score starts
at 100; the first buffering signal deducts 40 points and a second one 20 more
(the score never drops below 40 for buffering alone); a missing usage chunk
deducts 15 only when nothing is buffered; a failed stream caps the score at 0.

A reasoning model (claimed by the knowledge base, or reporting reasoning tokens
in its usage) may think for seconds before its first visible token and then
write the answer quickly, so for it a late first token is noted, not counted as
buffering. A stream that succeeds but delivers no content cannot be judged at
all and is inconclusive (no score).
"""

from __future__ import annotations

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.scale import DeductionScale, outcome
from zing.models import DetectorResult, Dimension, RequestSpec, Severity, Status
from zing.perf.recorder import usage_tokens
from zing.utils import stats

# Buffered-streaming signals (few chunks / late first token) only make sense once
# enough text was produced that genuine streaming would have spanned many chunks.
# Below this, a fast small model finishing a short reply looks the same as a buffer.
_MIN_BUFFERED_CHARS = 220

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
    outcome("streaming.uniform_gaps", "buffered", None, Status.WARN, Severity.MEDIUM,
            max_deduction=_SIGNAL_DEDUCTIONS[0], label=_BUFFERED),
    outcome("streaming.no_usage", "missing", None, Status.WARN, Severity.LOW,
            max_deduction=_NO_USAGE_DEDUCTION,
            label="No usage chunk in the stream: deducts 15 points when nothing is buffered."),
    outcome("streaming.no_content", "no_content", None, Status.INCONCLUSIVE, Severity.LOW,
            label="The stream succeeded but delivered no content to judge by; not scored."),
    outcome("streaming.failed", "failed", None, Status.FAIL, Severity.HIGH, cap=0.0,
            label="The streaming request failed."),
)


def _signal_deduction(signals: list[str]) -> float:
    """The deduction of the buffering signal just added to ``signals``."""
    i = len(signals) - 1
    return _SIGNAL_DEDUCTIONS[i] if i < len(_SIGNAL_DEDUCTIONS) else 0.0


@register
class StreamingDetector(Detector):
    id = "streaming"
    name = "Streaming authenticity"
    dimension = Dimension.STREAMING
    min_suite = "standard"
    cost_hint = 1

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

        # Total failure — can't assess streaming at all.
        if not out.ok:
            result.findings.append(
                SCALE.finding(
                    "streaming.failed",
                    "failed",
                    title="Streaming request failed",
                    summary=out.error_message or f"HTTP {out.status_code}",
                    evidence={"status_code": out.status_code, "error_type": out.error_type},
                    recommendation="Verify the relay supports stream=true for this model.",
                )
            )
            result.status = Status.FAIL
            result.score = SCALE.total(result.findings)
            return result

        # A successful stream without any content: nothing to judge streaming by.
        if not out.has_content():
            result.findings.append(
                SCALE.finding(
                    "streaming.no_content",
                    "no_content",
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
        # Reasoning models think (silently or as reasoning deltas) before the
        # first visible token, so a late first token is no buffering signal there.
        reasoning_tokens = usage_tokens(out.usage)["reasoning"] or 0
        reasoning = bool(ctx.profile and ctx.profile.model.reasoning) or reasoning_tokens > 0

        # Signal 1: substantial content delivered in <=2 chunks.
        if content_len >= _MIN_BUFFERED_CHARS and out.chunk_count <= 2:
            buffered_signals.append("few_chunks")
            result.findings.append(
                SCALE.finding(
                    "streaming.few_chunks",
                    "buffered",
                    deduction=_signal_deduction(buffered_signals),
                    title="Response delivered in <=2 chunks",
                    summary=(
                        f"{content_len} chars arrived in {out.chunk_count} chunk(s) "
                        "(buffered-then-chunked, not true token streaming)."
                    ),
                    evidence={"content_chars": content_len, "chunk_count": out.chunk_count},
                )
            )

        # Signal 2: first token arrives near the very end (response withheld). Only
        # meaningful when enough text was produced to expect multi-chunk streaming.
        if (
            content_len >= _MIN_BUFFERED_CHARS
            and out.ttft_ms is not None
            and out.duration_ms
            and out.duration_ms > 0
        ):
            ttft_ratio = out.ttft_ms / out.duration_ms
            pct = round(ttft_ratio * 100)
            if ttft_ratio > 0.9 and reasoning:
                result.findings.append(
                    SCALE.finding(
                        "streaming.reasoning_ttft",
                        "reasoning",
                        title="Late first token from a reasoning model",
                        summary=(
                            f"First visible token arrived at ~{pct}% of total time; the "
                            "model reasons before answering, so this is not counted as "
                            "buffering."
                        ),
                        evidence={
                            "ttft_ms": round(out.ttft_ms, 1),
                            "duration_ms": round(out.duration_ms, 1),
                            "ttft_ratio": round(ttft_ratio, 3),
                            "reasoning_tokens": reasoning_tokens or None,
                        },
                    )
                )
            elif ttft_ratio > 0.9:
                buffered_signals.append("late_ttft")
                result.findings.append(
                    SCALE.finding(
                        "streaming.late_ttft",
                        "buffered",
                        deduction=_signal_deduction(buffered_signals),
                        title="First token arrived late in the stream",
                        summary=f"First token arrived at ~{pct}% of total time (buffered).",
                        evidence={
                            "ttft_ms": round(out.ttft_ms, 1),
                            "duration_ms": round(out.duration_ms, 1),
                            "ttft_ratio": round(ttft_ratio, 3),
                        },
                    )
                )

        # Signal 3: many chunks but all dumped together (near-zero, uniform gaps).
        deltas = [
            out.chunk_timings_ms[i] - out.chunk_timings_ms[i - 1]
            for i in range(1, len(out.chunk_timings_ms))
        ]
        if out.chunk_count >= 4 and deltas:
            cv = stats.coefficient_of_variation(deltas)
            mean_delta = stats.mean(deltas)
            if cv is not None and mean_delta is not None and cv < 0.1 and mean_delta < 2.0:
                buffered_signals.append("uniform_gaps")
                result.findings.append(
                    SCALE.finding(
                        "streaming.uniform_gaps",
                        "buffered",
                        deduction=_signal_deduction(buffered_signals),
                        title="Inter-chunk gaps are uniform and near-zero",
                        summary=(
                            f"{out.chunk_count} chunks with ~{mean_delta:.2f} ms mean gap "
                            f"and CV {cv:.3f} — chunks appear dumped together."
                        ),
                        evidence={
                            "chunk_count": out.chunk_count,
                            "mean_delta_ms": round(mean_delta, 3),
                            "delta_cv": round(cv, 3),
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
                "usage_present": out.usage is not None,
                "buffered_signals": buffered_signals,
                "reasoning": reasoning,
            }
        )
        return result
