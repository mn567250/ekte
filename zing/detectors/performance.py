"""Performance probe — controlled latency / TTFT / throughput measurement.

The audit's own requests mix prompt and output sizes, so their timings describe
nothing in particular. This probe sends N uniform streaming requests per
endpoint instead, and every one is uncacheable: a random request id opens the
prompt (prompt caches key on the prefix, response caches on the whole request),
the topic rotates, no cache controls are sent, and the prompt stays far below
the 1024-token automatic-caching minimum. A response that still comes back
cached, or repeats an earlier one verbatim, is flagged and left out of the stats.

Order of work, per endpoint (target and baseline alternate in compare mode so
network drift during the run hits both equally):

1. three ``GET /models`` pings (``Cache-Control: no-cache``) — network round trip
2. one warm-up request — reported as cold start, excluded from the stats
3. N probe requests per request mode
4. (deep/full) a burst at the reliability concurrency — throughput under load

Requests stream by default; ``performance_streaming=False`` measures relays that
cannot stream. The full suite measures both modes, interleaved.

No reasoning-effort parameter is sent: the modes a relay accepts are unknown, so
a reasoning model thinks at its default effort (the report says so).

The probe scores the performance dimension, mostly on *consistency* — steady
latency, TTFT and throughput, few failures, little slowdown under load — so an
endpoint that is slow but steady (a local or self-hosted model) is not marked
down for not being a data centre. Speed itself is one check: compared with the
trusted baseline, or else with the knowledge base's published reference range,
where only a much faster target (consistent with a smaller model) counts
against it. Findings are at most LOW severity: they move the score, never the
risk verdict. Runs on deep/full/custom, and with 5 requests on the standard
suite in compare mode (too few samples for the consistency checks).
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Sequence

from zing import prompts
from zing.clients import Client
from zing.config import AuditOptions
from zing.context import AuditContext
from zing.detectors.base import CUSTOM_SUITE, SUITE_ORDER, Detector, register
from zing.detectors.scale import Scale, outcome
from zing.knowledge.schema import PerformanceReference
from zing.models import (
    DetectorResult,
    Dimension,
    EndpointPerformance,
    RequestRecord,
    RequestSpec,
    Severity,
    Status,
)
from zing.perf import RequestRecorder, phase_scope, summarize_endpoint
from zing.perf.recorder import last_record
from zing.perf.summary import hidden_reasoning
from zing.utils.stats import percentile

PINGS = 3
# Probe size on the standard suite, where it only runs in compare mode.
STANDARD_COMPARE_REQUESTS = 5
# Burst size: a few rounds at the configured concurrency.
_BURST_ROUNDS = 4
_MIN_BURST = 8
# Decode throughput this far above the reference suggests a smaller model.
_FAST_RATIO = 2.0
# Minimum clean samples per side before comparing throughput.
_MIN_COMPARE_SAMPLES = 5
# Consistency is judged by the tail ratio: p90 / p50 for latency and TTFT (slow
# outliers), p50 / p10 for throughput (slow outliers). A percentile ratio is
# robust to the odd stray request, unlike a standard deviation.
_MIN_CONSISTENCY_SAMPLES = 10
_TAIL_STEADY = 1.3
_TAIL_STABLE = 1.75
_TAIL_VARIABLE = 2.5
# The consistency findings' titles per metric, spelled out so the locales can
# translate each one.
_CONSISTENCY_TITLE = {
    "Latency": "Latency consistency",
    "Time to first token": "Time to first token consistency",
    "Decode throughput": "Decode throughput consistency",
    "End-to-end throughput": "End-to-end throughput consistency",
}
# Share of probe requests that failed (rate limits excluded).
_ERROR_RATE_OK = 0.02
_ERROR_RATE_WARN = 0.1
# Burst p50 latency / sequential p50 latency.
_LOAD_STABLE = 1.5
_LOAD_SLOWER = 3.0
_MIN_BURST_SAMPLES = 5


def _deep(suite: str) -> bool:
    """Deep or deeper — the custom suite probes like deep."""
    if suite == CUSTOM_SUITE:
        return True
    return suite in SUITE_ORDER and SUITE_ORDER.index(suite) >= SUITE_ORDER.index("deep")


def planned_probe_requests(options: AuditOptions, *, has_baseline: bool) -> int:
    """Probe requests per endpoint for this run (0 = the probe does not run)."""
    n = options.performance_requests
    if n <= 0:
        return 0
    if _deep(options.suite):
        return n
    if options.suite == "standard" and has_baseline:
        return min(STANDARD_COMPARE_REQUESTS, n)
    return 0


def probe_modes(options: AuditOptions) -> list[bool]:
    """Request modes to probe (True = streaming), headline mode first."""
    if options.suite == "full":
        return [True, False]
    return [options.performance_streaming]


def stream_mode(options: AuditOptions) -> str:
    """The configured probe request mode: "stream", "non_stream" or "both"."""
    modes = probe_modes(options)
    if len(modes) > 1:
        return "both"
    return "stream" if modes[0] else "non_stream"


def burst_size(options: AuditOptions, probe_requests: int) -> int:
    """Requests in the concurrency burst (deep/full only)."""
    if not _deep(options.suite) or probe_requests <= 0:
        return 0
    conc = max(1, options.reliability_concurrency)
    return min(probe_requests, max(conc * _BURST_ROUNDS, _MIN_BURST))


def estimated_calls(options: AuditOptions, *, has_baseline: bool) -> int:
    """API calls the probe makes across all endpoints — for ``--dry-run``."""
    n = planned_probe_requests(options, has_baseline=has_baseline)
    if n == 0:
        return 0
    per_endpoint = PINGS + 1 + (n + burst_size(options, n)) * len(probe_modes(options))
    return per_endpoint * (2 if has_baseline else 1)


class _Endpoint:
    """One side of the probe and its per-endpoint state."""

    def __init__(self, label: str, client: Client) -> None:
        self.label = label
        self.client = client
        self.seen: set[str] = set()


def _consistency(check: str, what: str) -> tuple:
    return (
        outcome(check, "steady", 100, Status.PASS, label=f"{what} is steady (tail ratio at most 1.3)."),
        outcome(check, "stable", 85, Status.PASS, label=f"{what} is stable (tail ratio at most 1.75)."),
        outcome(check, "variable", 65, Status.WARN, Severity.LOW,
                label=f"{what} varies noticeably (tail ratio at most 2.5)."),
        outcome(check, "erratic", 40, Status.FAIL, Severity.LOW,
                label=f"{what} is erratic (tail ratio above 2.5)."),
        outcome(check, "few_samples", None, Status.INFO,
                label=f"Too few samples to judge how consistent {what.lower()} is."),
    )


# Consistency first: an endpoint that is slow but steady scores well.
SCALE = Scale(
    outcome("performance.summary", "measured", None, Status.INFO,
            label="Latency, TTFT and throughput were measured."),
    outcome("performance.summary", "no_success", None, Status.INCONCLUSIVE,
            label="None of the probe requests succeeded."),
    *_consistency("performance.latency_consistency", "Latency"),
    *_consistency("performance.ttft_consistency", "Time to first token"),
    *_consistency("performance.throughput_consistency", "Throughput"),
    outcome("performance.errors", "ok", 100, Status.PASS,
            label="At most 2% of the probe requests failed."),
    outcome("performance.errors", "some", 80, Status.WARN, Severity.LOW,
            label="Up to 10% of the probe requests failed or timed out."),
    outcome("performance.errors", "failed", 50, Status.FAIL, Severity.LOW,
            label="Many probe requests failed or timed out."),
    outcome("performance.load_stability", "stable", 100, Status.PASS,
            label="Latency holds up under concurrent load (at most 1.5x)."),
    outcome("performance.load_stability", "slower", 80, Status.WARN, Severity.LOW,
            label="Latency rises under concurrent load (up to 3x)."),
    outcome("performance.load_stability", "degraded", 55, Status.FAIL, Severity.LOW,
            label="Latency degrades sharply under concurrent load (above 3x)."),
    outcome("performance.cache_hit", "cached", 60, Status.WARN, Severity.LOW,
            label="Unique probe prompts came back from a cache (left out of the statistics)."),
    outcome("performance.cache_hit", "baseline_cached", None, Status.INFO,
            label="The baseline served unique probe prompts from a cache (not scored)."),
    outcome("performance.reference", "matches", 100, Status.PASS,
            label="Throughput is in line with the reference for this model."),
    outcome("performance.reference", "slower", None, Status.INFO,
            label="Slower than the reference (e.g. local or smaller hardware); not a failure."),
    outcome("performance.reference", "faster", 60, Status.WARN, Severity.LOW,
            label="Much faster than the reference (consistent with a smaller model)."),
    outcome("performance.reasoning", "hidden_reasoning", None, Status.INFO,
            label="The model spends hidden reasoning tokens; TTFT includes thinking."),
    outcome("performance.relay_overhead", "compared", None, Status.INFO,
            label="Latency compared with the trusted baseline (informational)."),
    outcome("performance.skipped", "disabled", None, Status.INFO,
            label="The performance probe was disabled."),
)


def _tail_key(ratio: float) -> str:
    if ratio <= _TAIL_STEADY:
        return "steady"
    if ratio <= _TAIL_STABLE:
        return "stable"
    if ratio <= _TAIL_VARIABLE:
        return "variable"
    return "erratic"


def _tail_ratio(values: Sequence[float], *, higher_is_better: bool) -> float | None:
    """How far the slow tail sits from the median (>= 1; 1 = perfectly even)."""
    if len(values) < _MIN_CONSISTENCY_SAMPLES:
        return None
    p50 = percentile(values, 50)
    tail = percentile(values, 10 if higher_is_better else 90)
    if not p50 or not tail:
        return None
    return p50 / tail if higher_is_better else tail / p50


@register
class PerformanceDetector(Detector):
    id = "performance"
    name = "Performance probe"
    dimension = Dimension.PERFORMANCE
    min_suite = "standard"
    cost_hint = 120

    @classmethod
    def applies(cls, suite: str, *, has_baseline: bool) -> bool:
        return _deep(suite) or (suite == "standard" and has_baseline)

    def __init__(self) -> None:
        self._counter = 0

    # -- request building --------------------------------------------------- #
    def _spec(self, max_tokens: int, *, stream: bool) -> RequestSpec:
        topics: list[str] = prompts.get("performance.topics")
        topic = topics[self._counter % len(topics)]
        self._counter += 1
        content = prompts.text("performance.probe", nonce=secrets.token_hex(8), topic=topic)
        # The fixed output budget is part of the measurement: never repeated. A
        # model that wants max_completion_tokens gets it from the client, which
        # renames the limit (profile or first 4xx) and keeps the rejection out of
        # the stats as a ``param_retry`` record.
        return RequestSpec(
            messages=[{"role": "user", "content": content}],
            temperature=None,
            max_tokens=max_tokens,
            stream=stream,
            reasoning_retry=False,
        )

    async def _call(self, ep: _Endpoint, max_tokens: int, stream: bool) -> RequestRecord | None:
        outcome = await ep.client.complete(self._spec(max_tokens, stream=stream))
        record = last_record()
        if record is None:
            return None
        # A verbatim repeat of an earlier answer to a unique prompt is a cache hit.
        text = (outcome.content or "").strip()
        if outcome.ok and text:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest in ep.seen:
                record.cached = True
            ep.seen.add(digest)
        return record

    async def _burst(
        self, ep: _Endpoint, size: int, conc: int, max_tokens: int, stream: bool
    ) -> None:
        sem = asyncio.Semaphore(conc)

        async def one() -> None:
            async with sem:
                await self._call(ep, max_tokens, stream)

        await asyncio.gather(*(one() for _ in range(size)))

    # -- run ---------------------------------------------------------------- #
    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        result.score = None
        opts = ctx.options
        n = planned_probe_requests(opts, has_baseline=ctx.has_baseline)
        if n <= 0:
            result.status = Status.NOT_RUN
            result.findings.append(
                SCALE.finding(
                    "performance.skipped",
                    "disabled",
                    title="Performance probe disabled",
                    summary="performance_requests <= 0; no probe requests were sent.",
                    evidence={"performance_requests": opts.performance_requests},
                )
            )
            return result

        endpoints = [_Endpoint("target", ctx.client)]
        if ctx.baseline_client is not None:
            endpoints.append(_Endpoint("baseline", ctx.baseline_client))

        # Standalone use (no runner): record into a private recorder.
        recorder = ctx.recorder
        attached: list[Client] = []
        if recorder is None:
            recorder = RequestRecorder(ctx.tokenizer_hint())
            for ep in endpoints:
                if ep.client.recorder is None:
                    ep.client.recorder, ep.client.endpoint = recorder, ep.label
                    attached.append(ep.client)
        first = len(recorder.records)
        max_tokens = max(1, opts.performance_max_tokens)
        conc = max(1, opts.reliability_concurrency)
        burst = burst_size(opts, n)
        modes = probe_modes(opts)

        try:
            with phase_scope("ping"):
                for _ in range(PINGS):
                    for ep in endpoints:
                        await ep.client.list_models(no_cache=True)
            with phase_scope("warmup"):
                for ep in endpoints:
                    await self._call(ep, max_tokens, modes[0])
            with phase_scope("probe"):
                for i in range(n):
                    for stream in modes:
                        # Alternate who goes first so neither side always follows the other.
                        for ep in endpoints if i % 2 == 0 else endpoints[::-1]:
                            await self._call(ep, max_tokens, stream)
            if burst:
                with phase_scope("probe_concurrent"):
                    for stream in modes:
                        for ep in endpoints:
                            await self._burst(ep, burst, conc, max_tokens, stream)
        finally:
            for client in attached:
                client.recorder = None

        records = recorder.records[first:]
        # Findings describe the headline mode (streaming when it was probed).
        summaries = {
            ep.label: summarize_endpoint(records, ep.label, concurrency=conc, stream=modes[0])
            for ep in endpoints
        }
        result.evidence["performance_probe"] = {
            "requests_per_endpoint": n,
            "max_tokens": max_tokens,
            "burst": burst,
            "modes": ["stream" if m else "non_stream" for m in modes],
            "concurrency": conc,
            # The client renamed the limit for a model known (or found) to
            # refuse max_tokens.
            "max_completion_tokens": {
                ep.label: "max_tokens" in getattr(ep.client, "unsupported_params", ())
                for ep in endpoints
            },
        }
        self._findings(
            result, records, summaries, n, stream=modes[0], reference=ctx.performance_reference()
        )
        result.score = Scale.mean(result.findings)
        result.status = (
            Scale.roll_up(result.findings) if summaries["target"].successes else Status.INCONCLUSIVE
        )
        return result

    # -- findings ----------------------------------------------------------- #
    @staticmethod
    def _headline(ep: EndpointPerformance) -> dict[str, float | int | str | None]:
        return {
            "requests": ep.requests,
            "successes": ep.successes,
            "latency_p50_ms": _r(ep.latency_ms.p50),
            "latency_p95_ms": _r(ep.latency_ms.p95),
            "ttft_p50_ms": _r(ep.ttft_ms.p50),
            "decode_tps_p50": _r(ep.decode_tps_local.p50),
            "network_rtt_p50_ms": _r(ep.network_rtt_ms.p50),
        }

    def _findings(
        self,
        result: DetectorResult,
        records: Sequence[RequestRecord],
        summaries: dict[str, EndpointPerformance],
        n: int,
        *,
        stream: bool = True,
        reference: PerformanceReference | None = None,
    ) -> None:
        target = summaries["target"]
        baseline = summaries.get("baseline")
        head = self._headline(target)
        head["mode"] = "stream" if stream else "non_stream"
        if target.successes and stream:
            summary = (
                f"{target.successes} of {target.requests} probe requests succeeded; "
                f"p50 latency {_fmt(target.latency_ms.p50, 'ms')}, "
                f"p50 TTFT {_fmt(target.ttft_ms.p50, 'ms')}, "
                f"p50 decode {_fmt(target.decode_tps_local.p50, 'tok/s')}."
            )
        elif target.successes:
            summary = (
                f"{target.successes} of {target.requests} non-streaming probe requests "
                f"succeeded; p50 latency {_fmt(target.latency_ms.p50, 'ms')}, "
                f"p50 end-to-end {_fmt(target.e2e_tps_local.p50, 'tok/s')}."
            )
        else:
            summary = f"None of the {target.requests} probe requests succeeded."
        result.findings.append(
            SCALE.finding(
                "performance.summary",
                "measured" if target.successes else "no_success",
                title="Performance probe results",
                summary=summary,
                evidence=head,
            )
        )

        self._consistency_findings(result, records, stream=stream)
        self._error_finding(result, target)
        self._load_finding(result, target)

        for label in summaries:
            cached = [
                r for r in records
                if r.endpoint == label and r.phase in ("probe", "probe_concurrent") and r.cached
            ]
            if cached:
                result.findings.append(
                    SCALE.finding(
                        "performance.cache_hit",
                        "cached" if label == "target" else "baseline_cached",
                        title="Unique probe prompts were served from a cache",
                        summary=f"{len(cached)} {label} probe request(s) reported cached input "
                        "tokens or repeated an earlier answer verbatim, although every prompt "
                        "was unique. They were left out of the statistics.",
                        evidence={"endpoint": label, "cached": len(cached)},
                        recommendation="A relay that caches unique prompts may be serving "
                        "stored answers; compare with a trusted baseline.",
                    )
                )

        probe_records = [r for r in records if r.op == "complete"]
        if hidden_reasoning(probe_records):
            result.findings.append(
                SCALE.finding(
                    "performance.reasoning",
                    "hidden_reasoning",
                    title="Reasoning tokens in the probe",
                    summary="The model spends hidden reasoning tokens: TTFT is the time to the "
                    "first visible token and includes thinking. zing sets no reasoning "
                    "effort, so the model thinks at its default effort.",
                    evidence={
                        "reasoning_tokens": sum(r.reasoning_tokens or 0 for r in probe_records),
                    },
                )
            )

        if baseline is not None:
            self._overhead_finding(result, target, baseline, head)
            self._baseline_reference(result, target, baseline, stream=stream)
        elif reference is not None:
            self._kb_reference(result, target, reference, stream=stream)

    # -- consistency ---------------------------------------------------------- #
    @staticmethod
    def _consistency_findings(
        result: DetectorResult, records: Sequence[RequestRecord], *, stream: bool
    ) -> None:
        """Tail ratios of the target's sequential probe requests in the headline mode."""
        good = [
            r for r in records
            if r.endpoint == "target" and r.phase == "probe" and r.op == "complete"
            and r.ok and not r.cached and r.stream == stream
        ]
        metrics: list[tuple[str, str, str, list[float], bool]] = [
            ("performance.latency_consistency", "Latency", "ms",
             [r.duration_ms for r in good if r.duration_ms is not None], False),
        ]
        if stream:
            metrics.append(("performance.ttft_consistency", "Time to first token", "ms",
                            [r.ttft_ms for r in good if r.ttft_ms is not None], False))
            metrics.append(("performance.throughput_consistency", "Decode throughput", "tok/s",
                            [r.decode_tps_local for r in good if r.decode_tps_local], True))
        else:
            metrics.append(("performance.throughput_consistency", "End-to-end throughput",
                            "tok/s", [r.e2e_tps_local for r in good if r.e2e_tps_local], True))
        for check, what, unit, values, higher in metrics:
            ratio = _tail_ratio(values, higher_is_better=higher)
            tail = "p10" if higher else "p90"
            p50 = _r(percentile(values, 50))
            tail_value = _r(percentile(values, 10 if higher else 90))
            evidence: dict[str, float | int | str | None] = {
                "samples": len(values),
                "p50": p50,
                tail: tail_value,
                "tail_ratio": round(ratio, 2) if ratio is not None else None,
                "unit": unit,
            }
            if ratio is None:
                result.findings.append(
                    SCALE.finding(
                        check, "few_samples",
                        title=_CONSISTENCY_TITLE[what],
                        summary=f"{len(values)} clean samples; at least "
                        f"{_MIN_CONSISTENCY_SAMPLES} are needed to judge consistency.",
                        evidence=evidence,
                    )
                )
                continue
            spread = f"{tail} / p50" if not higher else f"p50 / {tail}"
            result.findings.append(
                SCALE.finding(
                    check, _tail_key(ratio),
                    title=_CONSISTENCY_TITLE[what],
                    summary=f"{what}: p50 {_fmt(p50, unit)}, {tail} "
                    f"{_fmt(tail_value, unit)} — tail ratio ({spread}) {ratio:.2f} over "
                    f"{len(values)} requests.",
                    evidence=evidence,
                )
            )

    @staticmethod
    def _error_finding(result: DetectorResult, target: EndpointPerformance) -> None:
        if target.error_rate is None:
            return
        rate = target.error_rate
        key = "ok" if rate <= _ERROR_RATE_OK else "some" if rate <= _ERROR_RATE_WARN else "failed"
        result.findings.append(
            SCALE.finding(
                "performance.errors",
                key,
                title="Probe request failures",
                summary=f"{target.errors} of {target.requests} target probe requests failed "
                f"({target.timeouts} timed out; {target.rate_limited} rate-limited, not counted).",
                evidence={
                    "endpoint": "target",
                    "requests": target.requests,
                    "errors": target.errors,
                    "timeouts": target.timeouts,
                    "rate_limited": target.rate_limited,
                    "error_rate": round(rate, 3),
                },
            )
        )

    @staticmethod
    def _load_finding(result: DetectorResult, target: EndpointPerformance) -> None:
        conc = target.concurrency
        seq = target.latency_ms.p50
        if conc is None or conc.latency_ms.count < _MIN_BURST_SAMPLES or not seq:
            return
        burst = conc.latency_ms.p50
        if burst is None:
            return
        ratio = burst / seq
        key = "stable" if ratio <= _LOAD_STABLE else "slower" if ratio <= _LOAD_SLOWER else "degraded"
        result.findings.append(
            SCALE.finding(
                "performance.load_stability",
                key,
                title="Latency under concurrent load",
                summary=f"p50 latency {_fmt(burst, 'ms')} at concurrency {conc.concurrency} vs "
                f"{_fmt(seq, 'ms')} one at a time ({ratio:.2f}x).",
                evidence={
                    "concurrency": conc.concurrency,
                    "burst_latency_p50_ms": _r(burst),
                    "sequential_latency_p50_ms": _r(seq),
                    "ratio": round(ratio, 2),
                },
            )
        )

    # -- reference speed ---------------------------------------------------- #
    @staticmethod
    def _overhead_finding(
        result: DetectorResult,
        target: EndpointPerformance,
        baseline: EndpointPerformance,
        head: dict,
    ) -> None:
        lat_t, lat_b = target.latency_ms.p50, baseline.latency_ms.p50
        ttft_t, ttft_b = target.ttft_ms.p50, baseline.ttft_ms.p50
        if lat_t is None or lat_b is None:
            return
        result.findings.append(
            SCALE.finding(
                "performance.relay_overhead",
                "compared",
                title="Latency versus the baseline",
                summary=f"Target p50 latency {_fmt(lat_t, 'ms')} vs baseline "
                f"{_fmt(lat_b, 'ms')} ({_signed(lat_t - lat_b)} ms)"
                + (
                    f"; p50 TTFT {_fmt(ttft_t, 'ms')} vs {_fmt(ttft_b, 'ms')} "
                    f"({_signed(ttft_t - ttft_b)} ms)."
                    if ttft_t is not None and ttft_b is not None
                    else "."
                ),
                evidence={
                    "target_latency_p50_ms": _r(lat_t),
                    "baseline_latency_p50_ms": _r(lat_b),
                    "latency_p50_delta_ms": _r(lat_t - lat_b),
                    "ttft_p50_delta_ms": _r(ttft_t - ttft_b)
                    if ttft_t is not None and ttft_b is not None
                    else None,
                    "target": head,
                    "baseline": PerformanceDetector._headline(baseline),
                },
            )
        )

    @staticmethod
    def _baseline_reference(
        result: DetectorResult,
        target: EndpointPerformance,
        baseline: EndpointPerformance,
        *,
        stream: bool,
    ) -> None:
        # Non-streamed calls have no first token: compare end-to-end speed.
        if stream:
            tps_t, tps_b = target.decode_tps_local, baseline.decode_tps_local
        else:
            tps_t, tps_b = target.e2e_tps_local, baseline.e2e_tps_local
        if (
            tps_t.count < _MIN_COMPARE_SAMPLES
            or tps_b.count < _MIN_COMPARE_SAMPLES
            or not tps_t.p50
            or not tps_b.p50
        ):
            return
        ratio = tps_t.p50 / tps_b.p50
        key = "faster" if ratio >= _FAST_RATIO else "slower" if ratio < 1 / _FAST_RATIO else "matches"
        summary = (
            f"Target decodes at {_fmt(tps_t.p50, 'tok/s')} vs baseline "
            f"{_fmt(tps_b.p50, 'tok/s')} ({ratio:.1f}x)."
        )
        if key == "faster":
            summary += (
                " The same model normally decodes at a similar speed; a much faster "
                "target is consistent with a smaller model."
            )
        result.findings.append(
            SCALE.finding(
                "performance.reference",
                key,
                title="Throughput versus the reference",
                summary=summary,
                evidence={
                    "reference": "baseline",
                    "target_tps_p50": _r(tps_t.p50),
                    "reference_range": f"{tps_b.p50:.0f}",
                    "ratio": round(ratio, 2),
                    "metric": "decode" if stream else "end_to_end",
                    "samples": min(tps_t.count, tps_b.count),
                },
                recommendation="Weigh this together with the model-identity findings; "
                "speed alone is not proof of substitution." if key == "faster" else None,
            )
        )

    @staticmethod
    def _kb_reference(
        result: DetectorResult,
        target: EndpointPerformance,
        reference: PerformanceReference,
        *,
        stream: bool,
    ) -> None:
        # The published figures are decode speeds: only a streamed probe compares.
        tps = target.decode_tps_local
        if not stream or reference.decode_tps is None or tps.count < _MIN_COMPARE_SAMPLES or not tps.p50:
            return
        low, high = reference.decode_tps
        key = "faster" if tps.p50 >= high * _FAST_RATIO else "slower" if tps.p50 < low else "matches"
        summary = (
            f"Target decodes at {_fmt(tps.p50, 'tok/s')}; the model's native API typically "
            f"runs at {low:.0f}–{high:.0f} tok/s."
        )
        if key == "faster":
            summary += " A much faster target is consistent with a smaller model."
        result.findings.append(
            SCALE.finding(
                "performance.reference",
                key,
                title="Throughput versus the reference",
                summary=summary,
                evidence={
                    "reference": "knowledge_base",
                    "target_tps_p50": _r(tps.p50),
                    "reference_range": f"{low:.0f}–{high:.0f}",
                    "ratio": round(tps.p50 / high, 2),
                    "metric": "decode",
                    "samples": tps.count,
                    "source": reference.source,
                    "measured": reference.measured,
                },
                recommendation="Weigh this together with the model-identity findings; "
                "speed alone is not proof of substitution." if key == "faster" else None,
            )
        )


def _r(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _fmt(value: float | None, unit: str) -> str:
    return "n/a" if value is None else f"{value:.0f} {unit}"


def _signed(value: float) -> str:
    return f"{value:+.0f}"
