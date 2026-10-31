"""Record every API call an audit makes, for the performance section.

A :class:`RequestRecorder` is attached to the target (and baseline) client by the
runner. The client hands it each call's :class:`~ekte.models.CompletionOutcome`
together with the request and a :class:`NetTrace` of the httpx transport events;
the recorder turns that into a :class:`~ekte.models.RequestRecord`.

Attribution needs no detector changes: the runner sets the current detector id
in a context variable (:func:`detector_scope`) and the performance probe marks
its own calls with :func:`phase_scope`. Context variables are copied into tasks
spawned by ``asyncio.gather``, so concurrent calls keep their attribution.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

from ekte.models import CompletionOutcome, RequestRecord, RequestSpec
from ekte.utils.stats import mean, percentile, stdev
from ekte.utils.tokenize import estimate_messages_tokens, estimate_tokens

_DETECTOR: ContextVar[str | None] = ContextVar("ekte_perf_detector", default=None)
_PHASE: ContextVar[str] = ContextVar("ekte_perf_phase", default="passive")
_NET: ContextVar[NetTrace | None] = ContextVar("ekte_perf_net", default=None)
_LAST: ContextVar[RequestRecord | None] = ContextVar("ekte_perf_last", default=None)

# Headers in which relays / upstreams report their own processing time (ms).
_PROCESSING_HEADERS = ("openai-processing-ms", "x-envoy-upstream-service-time")


@contextmanager
def detector_scope(detector_id: str | None) -> Iterator[None]:
    """Attribute every call made inside the block to ``detector_id``."""
    token = _DETECTOR.set(detector_id)
    try:
        yield
    finally:
        _DETECTOR.reset(token)


@contextmanager
def phase_scope(phase: str) -> Iterator[None]:
    """Mark every call made inside the block with ``phase`` (e.g. ``probe``)."""
    token = _PHASE.set(phase)
    try:
        yield
    finally:
        _PHASE.reset(token)


def last_record() -> RequestRecord | None:
    """The record of the most recent call made by the current task."""
    return _LAST.get()


def current_net_trace() -> NetTrace | None:
    """The transport trace collecting events for the call in flight, if any."""
    return _NET.get()


class NetTrace:
    """Collects httpx/httpcore trace events for one call.

    Installed as ``request.extensions["trace"]`` by the client's request hook.
    Each event name keeps its latest timestamp, so behind an HTTPS proxy the
    tunnel's own request is superseded by the real one.
    """

    def __init__(self) -> None:
        self.marks: dict[str, float] = {}

    async def trace(self, event_name: str, info: dict[str, Any]) -> None:
        self.marks[event_name] = time.perf_counter()

    def _mark(self, suffix: str) -> float | None:
        for prefix in ("http11.", "http2.", "connection."):
            at = self.marks.get(prefix + suffix)
            if at is not None:
                return at
        return None

    def _span(self, name: str) -> float | None:
        start = self._mark(f"{name}.started")
        end = self._mark(f"{name}.complete")
        if start is None or end is None or end < start:
            return None
        return (end - start) * 1000

    def sent_ms(self, started: float) -> float | None:
        """When the request was fully sent, in ms from ``started``."""
        sent = self._mark("send_request_body.complete") or self._mark(
            "send_request_headers.complete"
        )
        return (sent - started) * 1000 if sent is not None else None

    def breakdown(self, started: float) -> dict[str, float | None]:
        """connect/TLS time, time to response headers, and the server's share
        (request fully sent -> response headers), in ms."""
        sent = self.sent_ms(started)
        at = self._mark("receive_response_headers.complete")
        headers = (at - started) * 1000 if at is not None else None
        return {
            "connect_ms": self._span("connect_tcp"),
            "tls_ms": self._span("start_tls"),
            "headers_ms": headers,
            "server_ms": (
                headers - sent
                if headers is not None and sent is not None and headers >= sent
                else None
            ),
        }


@contextmanager
def net_trace_scope() -> Iterator[NetTrace]:
    """Collect transport events for the calls made inside the block."""
    net = NetTrace()
    token = _NET.set(net)
    try:
        yield net
    finally:
        _NET.reset(token)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _nested_int(usage: dict[str, Any], outer: str, inner: str) -> int | None:
    block = usage.get(outer)
    return _int(block.get(inner)) if isinstance(block, dict) else None


def usage_tokens(usage: dict[str, Any] | None) -> dict[str, int | None]:
    """Reported input/output/reasoning/cached tokens across OpenAI, Responses,
    Anthropic and DeepSeek usage shapes."""
    if not isinstance(usage, dict):
        return {"input": None, "output": None, "reasoning": None, "cached": None}
    inp = _int(usage.get("prompt_tokens"))
    if inp is None:
        inp = _int(usage.get("input_tokens"))
    out = _int(usage.get("completion_tokens"))
    if out is None:
        out = _int(usage.get("output_tokens"))
    reasoning = _nested_int(usage, "completion_tokens_details", "reasoning_tokens")
    if reasoning is None:
        reasoning = _nested_int(usage, "output_tokens_details", "reasoning_tokens")
    cached = _nested_int(usage, "prompt_tokens_details", "cached_tokens")
    if cached is None:
        cached = _nested_int(usage, "input_tokens_details", "cached_tokens")
    if cached is None:
        cached = _int(usage.get("cache_read_input_tokens"))
    if cached is None:
        cached = _int(usage.get("prompt_cache_hit_tokens"))
    return {"input": inp, "output": out, "reasoning": reasoning, "cached": cached}


# Share of the prompt that must come from a cache before a request counts as
# served from it. Local servers (Ollama, llama.cpp, LM Studio) reuse the KV cache
# of the previous prompt and report the shared prefix as cached; for a short
# unique prompt that prefix is only the chat template (system prompt, role
# markers), which says nothing about stored answers.
CACHE_HIT_SHARE = 0.5


def is_cache_hit(cached: int | None, prompt: int | None) -> bool:
    """True if the reported cached tokens cover most of the prompt (any cached
    tokens when the prompt size is unknown)."""
    if not cached:
        return False
    if not prompt:
        return True
    return cached >= CACHE_HIT_SHARE * prompt


def _relay_processing_ms(headers: dict[str, str]) -> float | None:
    for name in _PROCESSING_HEADERS:
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(str(raw).strip().removesuffix("ms"))
        except ValueError:
            continue
        if value >= 0:
            return value
    return None


def _decode_tps(tokens: int | None, duration: float | None, ttft: float | None) -> float | None:
    """Tokens after the first one over the time after the first one."""
    if tokens is None or tokens < 2 or duration is None or ttft is None:
        return None
    span = duration - ttft
    if span < 1.0:
        return None
    return (tokens - 1) / (span / 1000)


def _e2e_tps(tokens: int | None, duration: float | None) -> float | None:
    if tokens is None or tokens < 1 or not duration or duration <= 0:
        return None
    return tokens / (duration / 1000)


def _output_text(outcome: CompletionOutcome) -> str:
    parts = [outcome.content or ""]
    for call in outcome.tool_calls:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
            parts.append(fn["arguments"])
    return "".join(parts)


class RequestRecorder:
    """Accumulates :class:`RequestRecord` rows for one audit."""

    def __init__(
        self,
        tokenizer: str | None = None,
        *,
        on_record: Callable[[RequestRecord], None] | None = None,
    ) -> None:
        self.t0 = time.perf_counter()
        # Wall-clock time of ``t0``: record ``start_ms`` offsets count from here.
        self.started_at = datetime.now(UTC)
        self.tokenizer = tokenizer
        self.records: list[RequestRecord] = []
        self.on_record = on_record

    def now(self) -> datetime:
        """The current time on the recorder's clock: ``started_at`` plus the
        monotonic time since ``t0``.

        Record offsets count on the same clock, so a report stamped with this
        never ends before its last request. ``datetime.now()`` can lag behind
        it by its own resolution (about 16 ms on Windows).
        """
        return self.started_at + timedelta(seconds=time.perf_counter() - self.t0)

    def _base(
        self, endpoint: str, op: str, stream: bool, started: float, outcome: CompletionOutcome
    ) -> RequestRecord:
        error_type = outcome.error_type
        return RequestRecord(
            seq=len(self.records),
            endpoint=endpoint,
            detector=_DETECTOR.get(),
            phase=_PHASE.get(),
            op=op,
            stream=stream,
            start_ms=round((started - self.t0) * 1000, 1),
            ok=outcome.ok,
            status_code=outcome.status_code,
            error_type=error_type,
            timeout=bool(error_type and "timeout" in error_type.lower()),
            rate_limited=outcome.status_code == 429,
            duration_ms=outcome.duration_ms,
            relay_processing_ms=_relay_processing_ms(outcome.headers),
        )

    def _add(self, record: RequestRecord, net: NetTrace | None, started: float) -> RequestRecord:
        if net is not None:
            for key, value in net.breakdown(started).items():
                setattr(record, key, value)
            # A stream sends its headers before any output, so for streams the
            # server's share runs from the request being sent to the first token.
            sent = net.sent_ms(started)
            if record.stream:
                record.server_ms = (
                    record.ttft_ms - sent
                    if record.ttft_ms is not None and sent is not None and record.ttft_ms >= sent
                    else None
                )
        self.records.append(record)
        _LAST.set(record)
        if self.on_record is not None:
            with suppress(Exception):  # a progress sink must never break the audit
                self.on_record(record)
        return record

    def record_completion(
        self,
        endpoint: str,
        spec: RequestSpec,
        outcome: CompletionOutcome,
        started: float,
        net: NetTrace | None = None,
    ) -> RequestRecord:
        rec = self._base(endpoint, "complete", spec.stream, started, outcome)
        rec.ttft_ms = outcome.ttft_ms if spec.stream else None
        rec.chunk_count = outcome.chunk_count

        gaps = [
            b - a
            for a, b in zip(outcome.chunk_timings_ms, outcome.chunk_timings_ms[1:], strict=False)
        ]
        if gaps:
            rec.itl_mean_ms = mean(gaps)
            rec.itl_p50_ms = percentile(gaps, 50)
            rec.itl_p95_ms = percentile(gaps, 95)
            rec.itl_jitter_ms = stdev(gaps)

        reported = usage_tokens(outcome.usage)
        rec.input_tokens_reported = reported["input"]
        rec.output_tokens_reported = reported["output"]
        rec.reasoning_tokens = reported["reasoning"]
        rec.cached_input_tokens = reported["cached"]
        rec.cached = is_cache_hit(reported["cached"], reported["input"])
        try:
            rec.input_tokens_local = estimate_messages_tokens(spec.messages, self.tokenizer)
        except Exception:
            rec.input_tokens_local = None
        if outcome.ok:
            rec.output_tokens_local = estimate_tokens(_output_text(outcome), self.tokenizer)

            ttft = rec.ttft_ms
            dur = outcome.duration_ms
            rec.decode_tps_reported = _decode_tps(rec.output_tokens_reported, dur, ttft)
            rec.decode_tps_local = _decode_tps(rec.output_tokens_local, dur, ttft)
            rec.e2e_tps_reported = _e2e_tps(rec.output_tokens_reported, dur)
            rec.e2e_tps_local = _e2e_tps(rec.output_tokens_local, dur)
        return self._add(rec, net, started)

    def record_embedding(
        self,
        endpoint: str,
        inputs: list[str],
        outcome: CompletionOutcome,
        started: float,
        net: NetTrace | None = None,
    ) -> RequestRecord:
        """One ``POST /embeddings`` call: latency and input tokens, no output."""
        rec = self._base(endpoint, "embed", False, started, outcome)
        reported = usage_tokens(outcome.usage)
        rec.input_tokens_reported = reported["input"]
        try:
            rec.input_tokens_local = sum(estimate_tokens(text, self.tokenizer) for text in inputs)
        except Exception:
            rec.input_tokens_local = None
        return self._add(rec, net, started)

    def record_rerank(
        self,
        endpoint: str,
        query: str,
        documents: list[str],
        outcome: CompletionOutcome,
        started: float,
        net: NetTrace | None = None,
    ) -> RequestRecord:
        """One ``POST /rerank`` call: latency and input tokens, no output."""
        rec = self._base(endpoint, "rerank", False, started, outcome)
        reported = usage_tokens(outcome.usage)
        rec.input_tokens_reported = reported["input"]
        try:
            rec.input_tokens_local = sum(
                estimate_tokens(text, self.tokenizer) for text in (query, *documents))
        except Exception:
            rec.input_tokens_local = None
        return self._add(rec, net, started)

    def record_models(
        self,
        endpoint: str,
        outcome: CompletionOutcome,
        started: float,
        net: NetTrace | None = None,
    ) -> RequestRecord:
        rec = self._base(endpoint, "list_models", False, started, outcome)
        return self._add(rec, net, started)
