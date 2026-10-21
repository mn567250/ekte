"""The embedding surface through the runner: detectors, vector drift and the
embedding performance probe, against an in-process mock /embeddings endpoint."""

from __future__ import annotations

import hashlib
import json
import math
import time

import httpx
import pytest

from zing.config import AuditOptions
from zing.detectors.base import select_detectors
from zing.detectors.embed_drift import drift_sample, previous_drift
from zing.detectors.embed_identity import echoes_model
from zing.models import Dimension, RiskLevel, Status, TargetConfig
from zing.runner import run_audit

BASE = "https://relay.embed.test/v1"
MODEL = "text-embedding-3-large"


def _vector(dim: int, text: str, salt: str = "") -> list[float]:
    key = int(hashlib.sha256((salt + text).encode()).hexdigest(), 16)
    v = [0.001 * math.sin(key % 997 + i) for i in range(dim)]
    v[key % dim] += 10.0
    return v


class EmbedServer:
    def __init__(self, *, dim: int = 3072, served: str = MODEL, collapse: bool = False,
                 salt: str = "", per_input_ms: float = 0.0, per_request_ms: float = 0.0):
        self.dim, self.served, self.collapse, self.salt = dim, served, collapse, salt
        self.per_input_ms, self.per_request_ms = per_input_ms, per_request_ms
        self.batches: list[int] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        body = json.loads(request.content or b"{}")
        inputs = body.get("input") or []
        self.batches.append(len(inputs))
        delay = self.per_request_ms + self.per_input_ms * len(inputs)
        if delay:
            time.sleep(delay / 1000)
        data = [
            {"index": i, "embedding": _vector(self.dim, "x" if self.collapse else t, self.salt)}
            for i, t in enumerate(inputs)
        ]
        return httpx.Response(200, json={"model": self.served, "data": data,
                                         "usage": {"prompt_tokens": 8 * len(inputs)}})


@pytest.fixture
def serve(monkeypatch):
    def install(server: EmbedServer) -> EmbedServer:
        from zing.clients import make_client as real

        monkeypatch.setattr(
            "zing.runner.make_client", lambda config, **_: real(config, transport=server.transport)
        )
        return server

    return install


def _target() -> TargetConfig:
    return TargetConfig(name="e", kind="target", base_url=BASE, api_key="sk-x", model=MODEL)


def _opts(**kw) -> AuditOptions:
    return AuditOptions(surface="embedding", embedding_dimensions=3072, **kw)


def _finding(report, fid):
    return next(f for d in report.detectors for f in d.findings if f.id == fid)


def test_surfaces_select_their_own_detectors():
    def ids(surface):
        return {d.id for d in select_detectors("full", has_judge=True, has_baseline=True,
                                               enabled=lambda _: True, surface=surface)}

    emb = ids("embedding")
    assert emb == {"embed.connectivity", "embed.identity", "embed.drift", "embed.determinism",
                   "embed.distinctness", "performance.embed"}
    assert not emb & ids("chat")
    assert {d.id for d in select_detectors("smoke", has_judge=False, has_baseline=False,
                                           enabled=lambda _: True, surface="embedding")} == emb - {
        "performance.embed"}


async def test_clean_embedding_audit(serve):
    serve(EmbedServer())
    report = await run_audit(_target(), _opts(suite="standard"))
    assert report.surface == "embedding" and report.stream_mode == "non_stream"
    assert report.verdict.risk_level == RiskLevel.CLEAN
    assert {d.dimension for d in report.detectors} == {
        Dimension.CONNECTIVITY, Dimension.MODEL_IDENTITY, Dimension.RELIABILITY, Dimension.CAPABILITY}
    assert all(d.status in (Status.PASS, Status.INFO) for d in report.detectors), [
        (d.id, d.status, d.error) for d in report.detectors]
    assert _finding(report, "embed.dimension").outcome == "match"
    assert _finding(report, "embed.model_field").outcome == "matches"
    drift = _finding(report, "embed.drift")
    assert drift.outcome == "baseline" and len(drift.evidence["sample"]) == 64
    # no probe on standard without a baseline; the passive calls are summarised
    assert not any(d.id == "performance.embed" for d in report.detectors)
    assert report.performance is not None and report.performance.target.latency_ms.count > 0


async def test_dimension_mismatch_is_high_risk(serve):
    serve(EmbedServer(dim=1536))
    report = await run_audit(_target(), _opts(suite="smoke"))
    dim = _finding(report, "embed.dimension")
    assert dim.outcome == "mismatch" and dim.evidence == {"returned": 1536, "claimed": 3072}
    assert report.verdict.risk_level == RiskLevel.HIGH


async def test_dimension_comes_from_the_kb_without_override(serve):
    serve(EmbedServer(dim=1024))
    report = await run_audit(
        TargetConfig(name="e", kind="target", base_url=BASE, model="unknown-embed-xyz"),
        AuditOptions(surface="embedding", suite="smoke"),
    )
    assert _finding(report, "embed.dimension").outcome == "unknown"


async def test_collapsed_vectors_and_echoed_model(serve):
    serve(EmbedServer(collapse=True, served="other-embedding-model"))
    report = await run_audit(_target(), _opts(suite="smoke"))
    assert _finding(report, "embed.distinctness").outcome == "collapsed"
    assert _finding(report, "embed.model_field").outcome == "differs"


def test_echoed_model_matching():
    assert echoes_model("text-embedding-3-large-2024", "text-embedding-3-large")
    assert echoes_model("openai/Text-Embedding-3-Large", "text-embedding-3-large")
    assert not echoes_model("bge-m3", "text-embedding-3-large", None)


async def test_vector_drift_against_the_previous_run(serve):
    serve(EmbedServer())
    first = await run_audit(_target(), _opts(suite="smoke"))
    saved = json.loads(first.model_dump_json())  # as history stores it
    assert previous_drift(saved)["dimension"] == 3072

    same = await run_audit(_target(), _opts(suite="smoke"), previous_report=saved)
    assert _finding(same, "embed.drift").outcome == "stable"

    serve(EmbedServer(salt="another model"))
    swapped = await run_audit(_target(), _opts(suite="smoke"), previous_report=saved)
    drift = _finding(swapped, "embed.drift")
    assert drift.outcome == "swapped" and drift.severity.value == "high"
    assert swapped.verdict.risk_level == RiskLevel.HIGH

    serve(EmbedServer(dim=1024))
    shorter = await run_audit(_target(), AuditOptions(surface="embedding", suite="smoke"),
                              previous_report=saved)
    assert _finding(shorter, "embed.drift").outcome == "swapped"


def test_drift_sample_is_small_and_unit_scaled():
    sample = drift_sample([3.0, 4.0] + [0.0] * 100)
    assert sample[:2] == [0.6, 0.8] and len(sample) == 64
    assert previous_drift({"detectors": [{"id": "x"}]}) is None
    assert previous_drift(None) is None


async def test_embedding_probe_measures_latency_and_batch_scaling(serve):
    server = serve(EmbedServer(per_input_ms=1.0))
    events: list[dict] = []
    report = await run_audit(_target(), _opts(suite="deep", performance_requests=12,
                                              reliability_concurrency=2), on_event=events.append)
    det = next(d for d in report.detectors if d.id == "performance.embed")
    assert det.dimension == Dimension.PERFORMANCE and det.status != Status.ERROR, det.error
    assert 16 in server.batches
    ids = {f.id for f in det.findings}
    assert {"performance.summary", "performance.latency_consistency",
            "performance.throughput_consistency", "performance.errors",
            "performance.batch_scaling", "performance.load_stability"} <= ids
    head = _finding(report, "performance.summary").evidence
    assert head["latency_p50_ms"] and head["cold_start_ms"] and head["inputs_per_s_p50"]
    assert head["input_tokens_per_s_p50"]
    # per-input latency is constant: a batch costs as much per input as single calls
    assert _finding(report, "performance.batch_scaling").outcome == "linear"
    perf = report.performance
    assert perf is not None and perf.source == "probe" and perf.probe_requests == 12
    assert perf.target.cold_start_ms is not None
    start = next(e for e in events if e["type"] == "start")
    assert start["probe_requests"] == 24
    probe = [e for e in events if e["type"] == "request_done"
             and e["record"]["detector"] == "performance.embed"]
    assert {e["record"]["phase"] for e in probe} >= {"ping", "warmup", "probe", "probe_batch",
                                                    "probe_concurrent"}


async def test_embedding_probe_parallel_batches_and_cache(serve):
    serve(EmbedServer(per_request_ms=3.0))
    report = await run_audit(_target(), _opts(suite="deep", performance_requests=6))
    assert _finding(report, "performance.batch_scaling").outcome == "parallel"

    serve(EmbedServer(collapse=True))
    cached = await run_audit(_target(), _opts(suite="deep", performance_requests=6))
    hit = _finding(cached, "performance.cache_hit")
    assert hit.outcome == "cached" and hit.evidence["cached"] > 0


async def test_embedding_probe_gating():
    from zing.detectors.embed_performance import EmbedPerformanceDetector
    from zing.detectors.performance import PerformanceDetector

    for suite in ("smoke", "standard", "deep", "full", "custom"):
        for base in (False, True):
            assert EmbedPerformanceDetector.applies(suite, has_baseline=base) == (
                PerformanceDetector.applies(suite, has_baseline=base))
