"""The rerank performance probe: through the runner against an in-process mock
/rerank endpoint, and its classification on fixed request timings."""

from __future__ import annotations

import json

import httpx
import pytest

from ekte.config import AuditOptions
from ekte.detectors.base import select_detectors
from ekte.detectors.rerank_performance import (
    DOCS_PHASE,
    FEW,
    MANY,
    RerankPerformanceDetector,
    _fine,
)
from ekte.models import DetectorResult, Dimension, RequestRecord, Status, TargetConfig
from ekte.runner import run_audit

BASE = "https://relay.rerank.test/v1"
MODEL = "rerank-test"


class RerankServer:
    """Scores each document by word overlap with the query; ``fixed`` answers
    every request with the same fine-grained scores (a stub or a cache)."""

    def __init__(self, *, fixed: bool = False, partial: bool = False) -> None:
        self.fixed, self.partial = fixed, partial
        self.sizes: list[int] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        body = json.loads(request.content or b"{}")
        docs = body.get("documents") or []
        self.sizes.append(len(docs))
        words = set(str(body.get("query", "")).lower().split())
        results = [
            {"index": i, "relevance_score": 0.123456 * (i + 1) if self.fixed
             else float(len(words & set(d.lower().split())))}
            for i, d in enumerate(docs)
        ]
        return httpx.Response(200, json={"model": MODEL, "results": results[:1] if self.partial
                                         else results})


@pytest.fixture
def serve(monkeypatch):
    def install(server: RerankServer) -> RerankServer:
        from ekte.clients import make_client as real

        monkeypatch.setattr(
            "ekte.runner.make_client", lambda config, **_: real(config, transport=server.transport)
        )
        return server

    return install


def _target() -> TargetConfig:
    return TargetConfig(name="r", kind="target", base_url=BASE, api_key="sk-x", model=MODEL)


def _finding(report, fid):
    return next(f for d in report.detectors for f in d.findings if f.id == fid)


def test_rerank_probe_is_selected_on_the_rerank_surface_only():
    def ids(suite: str, surface: str, base: bool = False) -> set[str]:
        return {d.id for d in select_detectors(suite, has_judge=False, has_baseline=base,
                                               enabled=lambda _: True, surface=surface)}

    assert "performance.rerank" in ids("deep", "rerank")
    assert "performance.rerank" not in ids("smoke", "rerank")
    assert "performance.rerank" not in ids("full", "chat") | ids("full", "embedding")
    det = RerankPerformanceDetector
    assert det.dimension == Dimension.PERFORMANCE and det.surface == "rerank"


def test_rerank_probe_gating_matches_the_chat_probe():
    from ekte.detectors.performance import PerformanceDetector

    for suite in ("smoke", "standard", "deep", "full", "custom"):
        for base in (False, True):
            assert RerankPerformanceDetector.applies(suite, has_baseline=base) == (
                PerformanceDetector.applies(suite, has_baseline=base))


async def test_rerank_probe_measures_latency_and_document_scaling(serve):
    server = serve(RerankServer())
    events: list[dict] = []
    report = await run_audit(
        _target(),
        AuditOptions(surface="rerank", suite="deep", performance_requests=12,
                     reliability_concurrency=2),
        on_event=events.append,
    )
    det = next(d for d in report.detectors if d.id == "performance.rerank")
    assert det.status != Status.ERROR, det.error
    assert {FEW, MANY} <= set(server.sizes)
    ids = {f.id for f in det.findings}
    assert {"performance.summary", "performance.latency_consistency",
            "performance.throughput_consistency", "performance.errors",
            "performance.document_scaling", "performance.load_stability"} <= ids
    # integer overlap scores repeat legitimately: no cache hit
    assert "performance.cache_hit" not in ids
    head = _finding(report, "performance.summary").evidence
    assert head["latency_p50_ms"] and head["cold_start_ms"] and head["documents_per_s_p50"]
    assert head["input_tokens_per_s_p50"]
    # only that it was measured: the classification is tested on given timings
    assert _finding(report, "performance.document_scaling").evidence["per_document_ratio"] > 0
    perf = report.performance
    assert perf is not None and perf.source == "probe" and perf.probe_requests == 12
    assert perf.target.latency_ms.count > 0 and perf.target.cold_start_ms is not None
    probe = [e for e in events if e["type"] == "request_done"
             and e["record"]["detector"] == "performance.rerank"]
    assert {e["record"]["phase"] for e in probe} >= {"ping", "warmup", "probe", DOCS_PHASE,
                                                    "probe_concurrent"}
    assert {e["record"]["op"] for e in probe} == {"list_models", "rerank"}
    # the dry-run estimate matches the calls actually made
    opts = AuditOptions(surface="rerank", suite="deep", performance_requests=12,
                        reliability_concurrency=2)
    assert RerankPerformanceDetector.estimated_calls(opts, has_baseline=False) == len(probe)
    assert RerankPerformanceDetector.estimated_calls(opts, has_baseline=True) == 2 * len(probe)
    start = next(e for e in events if e["type"] == "start")
    assert start["probe_requests"] == 24


async def test_rerank_probe_detects_repeated_scores(serve):
    serve(RerankServer(fixed=True))
    report = await run_audit(_target(), AuditOptions(surface="rerank", suite="deep",
                                                     performance_requests=6))
    hit = _finding(report, "performance.cache_hit")
    assert hit.outcome == "cached" and hit.evidence["cached"] > 0


async def test_rerank_probe_counts_an_incomplete_ranking_as_a_failure(serve):
    serve(RerankServer(partial=True))
    report = await run_audit(_target(), AuditOptions(surface="rerank", suite="deep",
                                                     performance_requests=6))
    det = next(d for d in report.detectors if d.id == "performance.rerank")
    assert det.status == Status.INCONCLUSIVE
    assert _finding(report, "performance.summary").outcome == "no_success"
    assert _finding(report, "performance.errors").outcome == "failed"


async def test_rerank_probe_disabled(serve):
    server = serve(RerankServer())
    report = await run_audit(_target(), AuditOptions(surface="rerank", suite="deep",
                                                     performance_requests=0))
    det = next(d for d in report.detectors if d.id == "performance.rerank")
    assert det.status == Status.NOT_RUN and det.findings[0].outcome == "disabled"
    assert MANY not in server.sizes


def test_fine_grained_scores():
    assert _fine(0.73519) and _fine(-2.0001)
    assert not _fine(3.0) and not _fine(0.125) and not _fine(None) and not _fine(1)


# --------------------------------------------------------------------------- #
# Classification on fixed timings (wall-clock time on a busy runner is noise)
# --------------------------------------------------------------------------- #
def _recs(ms: list[float], phase: str, start: int = 0) -> list[RequestRecord]:
    return [RequestRecord(seq=start + i, endpoint="target", op="rerank", phase=phase, ok=True,
                          duration_ms=v) for i, v in enumerate(ms)]


def _result() -> DetectorResult:
    return DetectorResult(id="performance.rerank", name="x", dimension=Dimension.PERFORMANCE)


def _scaling(few_ms: float, many_ms: float, n: int = 6):
    result = _result()
    RerankPerformanceDetector()._scaling_finding(
        result, _recs([few_ms] * n, "probe"), _recs([many_ms] * n, DOCS_PHASE, 100))
    [finding] = result.findings
    return finding


def test_document_scaling_classification_on_given_timings():
    # 8x the documents for 1.3x the time: scored in parallel
    parallel = _scaling(100.0, 130.0)
    assert parallel.outcome == "parallel" and parallel.evidence["per_document_ratio"] < 0.6
    # 8x the documents for 8x the time: split or serialised per document
    linear = _scaling(100.0, 800.0)
    assert linear.outcome == "linear" and linear.evidence["per_document_ratio"] == 1.0
    assert _scaling(100.0, 800.0, n=2).outcome == "few_samples"


def _findings(records: list[RequestRecord], docs: dict[int, int] | None = None):
    from ekte.perf import summarize_endpoint

    det = RerankPerformanceDetector()
    det._docs = docs or {}
    result = _result()
    summaries = {"target": summarize_endpoint(records, "target", concurrency=2, op="rerank")}
    det._findings(result, records, summaries)
    return {f.id: f for f in result.findings}


def test_findings_on_given_timings():
    few = _recs([100.0] * 12, "probe")
    many = _recs([200.0] * 12, DOCS_PHASE, 100)
    burst = _recs([110.0] * 8, "probe_concurrent", 200)
    failed = [RequestRecord(seq=300, endpoint="target", op="rerank", phase="probe", ok=False)]
    records = few + many + burst + failed
    found = _findings(records, {rec.seq: MANY for rec in many})
    assert found["performance.summary"].outcome == "measured"
    head = found["performance.summary"].evidence
    assert head["many_latency_p50_ms"] == 200.0 and head["documents_per_s_p50"] == 160.0
    assert found["performance.latency_consistency"].outcome == "steady"
    assert found["performance.throughput_consistency"].outcome == "steady"
    assert found["performance.throughput_consistency"].evidence["unit"] == "documents/s"
    assert found["performance.load_stability"].outcome == "stable"
    assert found["performance.errors"].evidence["errors"] == 1
    assert found["performance.document_scaling"].outcome == "parallel"
    assert "performance.cache_hit" not in found


def test_erratic_latency_and_cached_requests_on_given_timings():
    few = _recs([100.0] * 9 + [400.0] * 3, "probe")
    cached = _recs([5.0] * 3, "probe", 50)
    for rec in cached:
        rec.cached = True
    found = _findings(few + cached)
    # the cached requests are left out of the latency statistics
    assert found["performance.latency_consistency"].evidence["samples"] == 12
    assert found["performance.latency_consistency"].outcome == "erratic"
    assert found["performance.cache_hit"].outcome == "cached"
    assert found["performance.cache_hit"].evidence["cached"] == 3
    assert found["performance.document_scaling"].outcome == "few_samples"
    assert found["performance.throughput_consistency"].outcome == "few_samples"


def test_no_success_on_given_timings():
    records = [RequestRecord(seq=i, endpoint="target", op="rerank", phase="probe", ok=False)
               for i in range(3)]
    found = _findings(records)
    assert found["performance.summary"].outcome == "no_success"
    assert found["performance.errors"].outcome == "failed"
