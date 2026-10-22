"""Rerank performance probe — latency and throughput of ``POST /rerank``.

The rerank counterpart of the embedding probe (:mod:`zing.detectors.embed_performance`),
sharing the chat probe's gating and phase loop (:mod:`zing.detectors.perf_probe`):
pings, a warm-up (reported as cold start), N probe rounds, and on deep/full a
burst at the reliability concurrency. Each round sends one query over 4
documents and one over 32 — the second axis: a 32-document request whose
per-document latency is about that of a 4-document one suggests a relay that
splits or serialises the documents.

Every query and document is unique (a random request id marks each), so no
response can come from a cache. The documents' topics rotate, so a request's
*arrangement* (which topics, how many) recurs every few rounds: a response
whose scores repeat, exactly, those seen for another arrangement ignored the
documents (a stub or a stored answer) and is flagged as cached and left out of
the stats. A deterministic scorer may repeat its scores for the same
arrangement, so that is never flagged. Only fine-grained scores count (a value
that is not a round number to 3 decimals): coarse scores, as from a lexical
scorer, can repeat legitimately. A 200 that does not score every
document counts as a failed request. Rerank does not stream.

There is no knowledge-base speed reference for rerank models: the probe scores
consistency, failures, behaviour under load and document-count scaling, and with
a trusted baseline compares latency with it. Findings are at most LOW severity.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from typing import Any

from zing import prompts
from zing.config import AuditOptions
from zing.context import AuditContext
from zing.detectors import perf_probe
from zing.detectors.base import Detector, register
from zing.detectors.perf_probe import (
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
from zing.detectors.scale import Scale, outcome
from zing.models import (
    DetectorResult,
    Dimension,
    EndpointPerformance,
    RequestRecord,
    Severity,
    Status,
)
from zing.perf import phase_scope, summarize_endpoint
from zing.perf.recorder import last_record
from zing.utils.stats import percentile

OP = "rerank"
# Documents per query on the two axes, and the phase the larger requests carry
# (kept out of the small-request latency statistics).
FEW = 4
MANY = 32
DOCS_PHASE = "probe_docs"
# Per-document latency of a 32-document request / that of a 4-document one at
# or above this: the documents cost about the same each (linear scaling).
_LINEAR_SCALING = 0.6
_MIN_DOCS_SAMPLES = 5

SCALE = Scale(
    outcome("performance.summary", "measured", None, Status.INFO,
            label="Rerank latency and throughput were measured."),
    outcome("performance.summary", "no_success", None, Status.INCONCLUSIVE,
            label="None of the probe requests succeeded."),
    *consistency_outcomes("performance.latency_consistency", "Latency"),
    *consistency_outcomes("performance.throughput_consistency", "Throughput"),
    *error_outcomes(),
    *load_outcomes(),
    outcome("performance.document_scaling", "parallel", 100, Status.PASS,
            label="A query over 32 documents costs far less per document than one over 4."),
    outcome("performance.document_scaling", "linear", 60, Status.WARN, Severity.LOW,
            label="A query over 32 documents costs about as much per document as one over 4 "
            "(consistent with a relay that splits or serialises the documents)."),
    outcome("performance.document_scaling", "few_samples", None, Status.INFO,
            label="Too few samples to judge how latency scales with the number of documents."),
    outcome("performance.cache_hit", "cached", 60, Status.WARN, Severity.LOW,
            label="Unique probe queries came back with repeated scores (left out of the statistics)."),
    outcome("performance.cache_hit", "baseline_cached", None, Status.INFO,
            label="The baseline returned repeated scores for unique probe queries (not scored)."),
    outcome("performance.relay_overhead", "compared", None, Status.INFO,
            label="Latency compared with the trusted baseline (informational)."),
    outcome("performance.skipped", "disabled", None, Status.INFO,
            label="The performance probe was disabled."),
)


def _per_s(count: float | None, duration_ms: float | None) -> float | None:
    if not count or not duration_ms or duration_ms <= 0:
        return None
    return count * 1000.0 / duration_ms


def _fine(score: Any) -> bool:
    """A score precise enough that an exact repeat for another query is no
    coincidence (not a round number to 3 decimals)."""
    return isinstance(score, float) and abs(score - round(score, 3)) > 1e-9


@register
class RerankPerformanceDetector(Detector):
    id = "performance.rerank"
    name = "Rerank performance probe"
    dimension = Dimension.PERFORMANCE
    surface = "rerank"
    min_suite = "standard"
    # pings + warm-up + 100 rounds of (4, 32 documents) + the burst
    cost_hint = 220

    @classmethod
    def applies(cls, suite: str, *, has_baseline: bool) -> bool:
        return perf_probe.probe_applies(suite, has_baseline=has_baseline)

    @classmethod
    def estimated_calls(cls, options: AuditOptions, *, has_baseline: bool) -> int:
        """API calls the probe makes across all endpoints — for ``--dry-run``:
        pings, a warm-up, two requests per round and the burst (4 documents)."""
        n = planned_probe_requests(options, has_baseline=has_baseline)
        if n == 0:
            return 0
        per_endpoint = perf_probe.PINGS + 1 + n * 2 + burst_size(options, n)
        return per_endpoint * (2 if has_baseline else 1)

    def __init__(self) -> None:
        self._counter = 0
        self._topics: list[str] = prompts.get("performance.topics")
        # seq of each recorded request -> documents it carried
        self._docs: dict[int, int] = {}
        # (endpoint, scores digest) -> the arrangement first answered with them
        self._answered: dict[tuple[str, str], tuple[int, int]] = {}

    def _request(self, size: int) -> tuple[str, list[str], tuple[int, int]]:
        topics = self._topics
        start = self._counter
        self._counter += 1
        nonce = secrets.token_hex(8)
        query = prompts.text("rerank.perf_query", nonce=nonce, topic=topics[start % len(topics)])
        documents = [
            prompts.text("rerank.perf_document", n=i + 1, nonce=nonce,
                         topic=topics[(start + i) % len(topics)])
            for i in range(size)
        ]
        return query, documents, (start % len(topics), size)

    async def _call(self, ep: Endpoint, size: int) -> RequestRecord | None:
        query, documents, arrangement = self._request(size)
        if size > FEW:
            with phase_scope(DOCS_PHASE):
                result, ranked = await ep.client.rerank(query, documents)
        else:
            result, ranked = await ep.client.rerank(query, documents)
        record = last_record()
        if record is None:
            return None
        self._docs[record.seq] = size
        # A 200 that leaves documents unscored did not do the work it is timed for.
        if record.ok and len({item.get("index") for item in ranked}) != size:
            record.ok = False
            record.error_type = "IncompleteRanking"
        # The same fine-grained scores for other documents: a cache hit.
        if record.ok and any(_fine(item.get("relevance_score")) for item in ranked):
            scores = [(item.get("index"), item.get("relevance_score")) for item in ranked]
            digest = hashlib.sha256(repr(scores).encode("utf-8")).hexdigest()
            first = self._answered.setdefault((ep.label, digest), arrangement)
            if first != arrangement:
                record.cached = True
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
                endpoints, call, n=n, modes=[FEW, MANY], burst=burst, conc=conc, burst_modes=[FEW]
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
            "documents": [FEW, MANY],
            "burst": burst,
            "modes": ["few", "many"],
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

    def _docs_per_s(self, records: Sequence[RequestRecord]) -> list[float]:
        return [v for v in (_per_s(self._docs.get(rec.seq, MANY), rec.duration_ms) for rec in records) if v]

    def _metrics(
        self, records: Sequence[RequestRecord], label: str, ep: EndpointPerformance
    ) -> dict[str, Any]:
        few = self._good(records, label, "probe")
        many = self._good(records, label, DOCS_PHASE)
        tokens_s = [_per_s(rec.input_tokens_local, rec.duration_ms) for rec in few + many]
        return {
            "requests": ep.requests,
            "successes": ep.successes,
            "latency_p50_ms": r(ep.latency_ms.p50),
            "latency_p95_ms": r(ep.latency_ms.p95),
            "cold_start_ms": r(ep.cold_start_ms),
            "many_latency_p50_ms": r(percentile([rec.duration_ms for rec in many if rec.duration_ms is not None], 50)),
            "documents_per_s_p50": r(percentile(self._docs_per_s(many), 50)),
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
                f"{target.successes} of {target.requests} rerank probe requests succeeded; "
                f"p50 latency {fmt(target.latency_ms.p50, 'ms')} over {FEW} documents, "
                f"{fmt(head['many_latency_p50_ms'], 'ms')} over {MANY}, "
                f"{fmt(head['documents_per_s_p50'], 'documents/s')} at {MANY}."
            )
        else:
            summary = f"None of the {target.requests} probe requests succeeded."
        result.findings.append(
            SCALE.finding(
                "performance.summary",
                "measured" if target.successes else "no_success",
                title="Rerank probe results",
                summary=summary,
                evidence=head,
            )
        )

        few = self._good(records, "target", "probe")
        many = self._good(records, "target", DOCS_PHASE)
        perf_probe.consistency_finding(
            SCALE, result, "performance.latency_consistency", "Latency", "ms",
            [rec.duration_ms for rec in few if rec.duration_ms is not None], False,
        )
        perf_probe.consistency_finding(
            SCALE, result, "performance.throughput_consistency", "Rerank throughput", "documents/s",
            self._docs_per_s(many), True,
        )
        perf_probe.error_finding(SCALE, result, target)
        perf_probe.load_finding(SCALE, result, target)
        self._scaling_finding(result, few, many)

        for label in summaries:
            cached = [
                rec for rec in records
                if rec.endpoint == label and rec.op == OP and rec.cached
                and rec.phase in ("probe", DOCS_PHASE, "probe_concurrent")
            ]
            if cached:
                result.findings.append(
                    SCALE.finding(
                        "performance.cache_hit",
                        "cached" if label == "target" else "baseline_cached",
                        title="Unique probe queries returned repeated scores",
                        summary=f"{len(cached)} {label} probe request(s) returned the exact "
                        "scores already seen for another query, although every query was "
                        "unique. They were left out of the statistics.",
                        evidence={"endpoint": label, "cached": len(cached)},
                        recommendation="A relay that returns the same scores for different "
                        "queries may be serving stored results; compare with a trusted baseline.",
                    )
                )

        baseline = summaries.get("baseline")
        if baseline is not None:
            self._overhead_finding(result, records, target, baseline, head)

    def _scaling_finding(
        self, result: DetectorResult, few: list[RequestRecord], many: list[RequestRecord]
    ) -> None:
        one = percentile([rec.duration_ms for rec in few if rec.duration_ms is not None], 50)
        lots = percentile([rec.duration_ms for rec in many if rec.duration_ms is not None], 50)
        evidence = {
            "documents": [FEW, MANY],
            "few_samples": len(few),
            "many_samples": len(many),
            "few_latency_p50_ms": r(one),
            "many_latency_p50_ms": r(lots),
        }
        if len(few) < _MIN_DOCS_SAMPLES or len(many) < _MIN_DOCS_SAMPLES or not one or not lots:
            result.findings.append(
                SCALE.finding(
                    "performance.document_scaling", "few_samples",
                    title="Document-count latency scaling",
                    summary=f"{len(few)} samples over {FEW} and {len(many)} over {MANY} "
                    f"documents; at least {_MIN_DOCS_SAMPLES} of each are needed.",
                    evidence=evidence,
                )
            )
            return
        ratio = (lots / MANY) / (one / FEW)
        evidence["per_document_ratio"] = round(ratio, 3)
        key = "linear" if ratio >= _LINEAR_SCALING else "parallel"
        result.findings.append(
            SCALE.finding(
                "performance.document_scaling", key,
                title="Document-count latency scaling" if key == "parallel"
                else "Rerank latency grows linearly with the number of documents",
                summary=f"A query over {MANY} documents takes {fmt(lots, 'ms')} vs "
                f"{fmt(one, 'ms')} over {FEW}: {ratio:.2f}x the per-document latency.",
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
