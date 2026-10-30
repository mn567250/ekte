"""Embedding performance probe — latency and throughput of ``POST /embeddings``.

The embedding counterpart of the chat probe (:mod:`ekte.detectors.performance`),
sharing its gating and phase loop (:mod:`ekte.detectors.perf_probe`): pings, a
warm-up (reported as cold start), N probe rounds, and on deep/full a burst at the
reliability concurrency. Each round sends one single-input request and one
batch of 16 inputs — the second axis, in place of the chat probe's streaming
mode: a batch whose per-input latency is about that of a single request
suggests a relay that splits or serialises batches.

Every input is unique (a random request id opens it), so no response can come
from a cache; a response whose vector repeats one seen for another input is
flagged as cached and left out of the stats. Embeddings do not stream.

There is no knowledge-base speed reference for embedding models: the probe
scores consistency, failures, behaviour under load and batch scaling, and with
a trusted baseline compares latency with it. Findings are at most LOW severity.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from typing import Any

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors import perf_probe
from ekte.detectors.base import Detector, register
from ekte.detectors.perf_probe import (
    Endpoint,
    burst_size,
    consistency_outcomes,
    error_outcomes,
    fmt,
    load_outcomes,
    planned_probe_requests,
    r,
    signed,
)
from ekte.detectors.scale import Scale, outcome
from ekte.models import (
    DetectorResult,
    Dimension,
    EndpointPerformance,
    RequestRecord,
    Severity,
    Status,
)
from ekte.perf import phase_scope, summarize_endpoint
from ekte.perf.recorder import last_record
from ekte.utils.stats import percentile

OP = "embed"
# Inputs per batch request, and the phase its records carry (kept out of the
# single-input latency statistics).
BATCH = 16
BATCH_PHASE = "probe_batch"
# Per-input latency of a batch / single-request latency at or above this: the
# batch costs about as much per input as single requests (linear scaling).
_LINEAR_SCALING = 0.6
_MIN_BATCH_SAMPLES = 5

SCALE = Scale(
    outcome("performance.summary", "measured", None, Status.INFO,
            label="Embedding latency and throughput were measured."),
    outcome("performance.summary", "no_success", None, Status.INCONCLUSIVE,
            label="None of the probe requests succeeded."),
    *consistency_outcomes("performance.latency_consistency", "Latency"),
    *consistency_outcomes("performance.throughput_consistency", "Throughput"),
    *error_outcomes(),
    *load_outcomes(),
    outcome("performance.batch_scaling", "parallel", 100, Status.PASS,
            label="A batch of 16 inputs costs far less per input than single requests."),
    outcome("performance.batch_scaling", "linear", 60, Status.WARN, Severity.LOW,
            label="A batch of 16 inputs costs about as much per input as single requests "
            "(consistent with a relay that splits or serialises batches)."),
    outcome("performance.batch_scaling", "few_samples", None, Status.INFO,
            label="Too few batch samples to judge how latency scales with batch size."),
    outcome("performance.cache_hit", "cached", 60, Status.WARN, Severity.LOW,
            label="Unique probe inputs came back with repeated vectors (left out of the statistics)."),
    outcome("performance.cache_hit", "baseline_cached", None, Status.INFO,
            label="The baseline returned repeated vectors for unique probe inputs (not scored)."),
    outcome("performance.relay_overhead", "compared", None, Status.INFO,
            label="Latency compared with the trusted baseline (informational)."),
    outcome("performance.skipped", "disabled", None, Status.INFO,
            label="The performance probe was disabled."),
)


def _per_s(count: float | None, duration_ms: float | None) -> float | None:
    if not count or not duration_ms or duration_ms <= 0:
        return None
    return count * 1000.0 / duration_ms


@register
class EmbedPerformanceDetector(Detector):
    id = "performance.embed"
    name = "Embedding performance probe"
    dimension = Dimension.PERFORMANCE
    surface = "embedding"
    min_suite = "standard"
    # pings + warm-up + 100 rounds of (single, batch) + the burst
    cost_hint = 220

    @classmethod
    def applies(cls, suite: str, *, has_baseline: bool) -> bool:
        return perf_probe.probe_applies(suite, has_baseline=has_baseline)

    def __init__(self) -> None:
        self._counter = 0
        # seq of each recorded request -> inputs it carried
        self._inputs: dict[int, int] = {}

    def _input(self) -> str:
        topics: list[str] = prompts.get("performance.topics")
        topic = topics[self._counter % len(topics)]
        self._counter += 1
        return prompts.text("embed.perf_input", nonce=secrets.token_hex(8), topic=topic)

    async def _call(self, ep: Endpoint, size: int) -> RequestRecord | None:
        inputs = [self._input() for _ in range(size)]
        if size > 1:
            with phase_scope(BATCH_PHASE):
                result, vectors = await ep.client.embeddings(inputs)
        else:
            result, vectors = await ep.client.embeddings(inputs)
        record = last_record()
        if record is None:
            return None
        self._inputs[record.seq] = size
        # A vector repeated for a different (unique) input is a cache hit.
        if result.ok:
            for vector in vectors:
                digest = hashlib.sha256(repr(vector).encode("utf-8")).hexdigest()
                if digest in ep.seen:
                    record.cached = True
                ep.seen.add(digest)
        return record

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

        endpoints = perf_probe.endpoints_of(ctx)
        recorder, attached = perf_probe.attach_recorder(ctx, endpoints)
        first = len(recorder.records)
        conc = max(1, opts.reliability_concurrency)
        burst = burst_size(opts, n)

        async def call(ep: Endpoint, size: int) -> None:
            await self._call(ep, size)

        try:
            await perf_probe.run_phases(
                endpoints, call, n=n, modes=[1, BATCH], burst=burst, conc=conc, burst_modes=[1]
            )
        finally:
            for client in attached:
                client.recorder = None

        records = recorder.records[first:]
        summaries = {
            ep.label: summarize_endpoint(records, ep.label, concurrency=conc, op=OP)
            for ep in endpoints
        }
        result.evidence["performance_probe"] = {
            "requests_per_endpoint": n,
            "batch": BATCH,
            "burst": burst,
            "modes": ["single", "batch"],
            "concurrency": conc,
        }
        self._findings(result, records, summaries)
        result.score = Scale.mean(result.findings)
        result.status = (
            Scale.roll_up(result.findings) if summaries["target"].successes else Status.INCONCLUSIVE
        )
        return result

    # -- findings ----------------------------------------------------------- #
    def _good(self, records: Sequence[RequestRecord], label: str, phase: str) -> list[RequestRecord]:
        return [
            rec for rec in records
            if rec.endpoint == label and rec.phase == phase and rec.op == OP
            and rec.ok and not rec.cached and rec.duration_ms
        ]

    def _metrics(
        self, records: Sequence[RequestRecord], label: str, ep: EndpointPerformance
    ) -> dict[str, Any]:
        single = self._good(records, label, "probe")
        batch = self._good(records, label, BATCH_PHASE)
        inputs_s = [_per_s(self._inputs.get(rec.seq, BATCH), rec.duration_ms) for rec in batch]
        tokens_s = [_per_s(rec.input_tokens_local, rec.duration_ms) for rec in single + batch]
        return {
            "requests": ep.requests,
            "successes": ep.successes,
            "latency_p50_ms": r(ep.latency_ms.p50),
            "latency_p95_ms": r(ep.latency_ms.p95),
            "cold_start_ms": r(ep.cold_start_ms),
            "batch_latency_p50_ms": r(percentile([rec.duration_ms for rec in batch if rec.duration_ms is not None], 50)),
            "inputs_per_s_p50": r(percentile([v for v in inputs_s if v], 50)),
            "input_tokens_per_s_p50": r(percentile([v for v in tokens_s if v], 50)),
            "network_rtt_p50_ms": r(ep.network_rtt_ms.p50),
        }

    def _findings(
        self,
        result: DetectorResult,
        records: Sequence[RequestRecord],
        summaries: dict[str, EndpointPerformance],
    ) -> None:
        target = summaries["target"]
        head = self._metrics(records, "target", target)
        if target.successes:
            summary = (
                f"{target.successes} of {target.requests} embedding probe requests succeeded; "
                f"p50 latency {fmt(target.latency_ms.p50, 'ms')}, batch of {BATCH} "
                f"{fmt(head['batch_latency_p50_ms'], 'ms')}, "
                f"{fmt(head['inputs_per_s_p50'], 'inputs/s')} in batches."
            )
        else:
            summary = f"None of the {target.requests} probe requests succeeded."
        result.findings.append(
            SCALE.finding(
                "performance.summary",
                "measured" if target.successes else "no_success",
                title="Embedding probe results",
                summary=summary,
                evidence=head,
            )
        )

        single = self._good(records, "target", "probe")
        batch = self._good(records, "target", BATCH_PHASE)
        perf_probe.consistency_finding(
            SCALE, result, "performance.latency_consistency", "Latency", "ms",
            [rec.duration_ms for rec in single if rec.duration_ms is not None], False,
        )
        perf_probe.consistency_finding(
            SCALE, result, "performance.throughput_consistency", "Embedding throughput", "inputs/s",
            [v for v in (_per_s(self._inputs.get(rec.seq, BATCH), rec.duration_ms) for rec in batch) if v],
            True,
        )
        perf_probe.error_finding(SCALE, result, target)
        perf_probe.load_finding(SCALE, result, target)
        self._batch_finding(result, single, batch)

        for label in summaries:
            cached = [
                rec for rec in records
                if rec.endpoint == label and rec.op == OP and rec.cached
                and rec.phase in ("probe", BATCH_PHASE, "probe_concurrent")
            ]
            if cached:
                result.findings.append(
                    SCALE.finding(
                        "performance.cache_hit",
                        "cached" if label == "target" else "baseline_cached",
                        title="Unique probe inputs returned repeated vectors",
                        summary=f"{len(cached)} {label} probe request(s) returned a vector already "
                        "seen for another input, although every input was unique. They were "
                        "left out of the statistics.",
                        evidence={"endpoint": label, "cached": len(cached)},
                        recommendation="A relay that returns the same vector for different "
                        "inputs may be serving stored results; compare with a trusted baseline.",
                    )
                )

        baseline = summaries.get("baseline")
        if baseline is not None:
            self._overhead_finding(result, records, target, baseline, head)

    def _batch_finding(
        self, result: DetectorResult, single: list[RequestRecord], batch: list[RequestRecord]
    ) -> None:
        one = percentile([rec.duration_ms for rec in single if rec.duration_ms is not None], 50)
        many = percentile([rec.duration_ms for rec in batch if rec.duration_ms is not None], 50)
        evidence = {
            "batch": BATCH,
            "single_samples": len(single),
            "batch_samples": len(batch),
            "single_latency_p50_ms": r(one),
            "batch_latency_p50_ms": r(many),
        }
        if len(single) < _MIN_BATCH_SAMPLES or len(batch) < _MIN_BATCH_SAMPLES or not one or not many:
            result.findings.append(
                SCALE.finding(
                    "performance.batch_scaling", "few_samples",
                    title="Batch latency scaling",
                    summary=f"{len(single)} single and {len(batch)} batch samples; at least "
                    f"{_MIN_BATCH_SAMPLES} of each are needed.",
                    evidence=evidence,
                )
            )
            return
        ratio = many / BATCH / one
        evidence["per_input_ratio"] = round(ratio, 3)
        key = "linear" if ratio >= _LINEAR_SCALING else "parallel"
        result.findings.append(
            SCALE.finding(
                "performance.batch_scaling", key,
                title="Batch latency scaling" if key == "parallel"
                else "Batch latency grows linearly with batch size",
                summary=f"A batch of {BATCH} inputs takes {fmt(many, 'ms')} vs "
                f"{fmt(one, 'ms')} for one input: {ratio:.2f}x the single-request latency "
                "per input.",
                evidence=evidence,
            )
        )

    def _overhead_finding(
        self,
        result: DetectorResult,
        records: Sequence[RequestRecord],
        target: EndpointPerformance,
        baseline: EndpointPerformance,
        head: dict[str, Any],
    ) -> None:
        lat_t, lat_b = target.latency_ms.p50, baseline.latency_ms.p50
        if lat_t is None or lat_b is None:
            return
        result.findings.append(
            SCALE.finding(
                "performance.relay_overhead",
                "compared",
                title="Latency versus the baseline",
                summary=f"Target p50 latency {fmt(lat_t, 'ms')} vs baseline "
                f"{fmt(lat_b, 'ms')} ({signed(lat_t - lat_b)} ms).",
                evidence={
                    "target_latency_p50_ms": r(lat_t),
                    "baseline_latency_p50_ms": r(lat_b),
                    "latency_p50_delta_ms": r(lat_t - lat_b),
                    "target": head,
                    "baseline": self._metrics(records, "baseline", baseline),
                },
            )
        )
