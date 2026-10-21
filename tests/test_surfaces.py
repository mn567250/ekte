"""The surface axis: chat (default) vs embedding audits.

Covers the option / report field, detector selection by surface and the
per-surface scoring tables. Chat behaviour is pinned by the rest of the suite.
"""

from __future__ import annotations

import pytest

import zing.detectors  # noqa: F401  -- populate the registry
from zing.config import AuditOptions, ConfigError, validate_surface
from zing.detectors import base
from zing.models import (
    AuditReport,
    DetectorResult,
    Dimension,
    Finding,
    RiskLevel,
    Severity,
    Status,
)
from zing.scoring import (
    DIMENSION_WEIGHTS,
    SURFACE_WEIGHTS,
    build_dimensions,
    build_verdict,
    weights_for,
)


def _result(dimension: Dimension, score: float, *, severity: Severity = Severity.INFO) -> DetectorResult:
    status = Status.FAIL if severity in (Severity.HIGH, Severity.CRITICAL) else Status.PASS
    return DetectorResult(
        id=f"{dimension.value}.embed",
        name=dimension.value,
        dimension=dimension,
        score=score,
        status=status,
        findings=[Finding(id=f"{dimension.value}.x", title="x", status=status, severity=severity)],
    )


def _verdict(results: list[DetectorResult], surface: str = "embedding"):
    dims = build_dimensions(results, None, surface=surface)
    return dims, build_verdict(
        results, dims, profile_matched=True, used_judge=False, used_baseline=False, surface=surface
    )


# --------------------------------------------------------------------------- #
# Options and report
# --------------------------------------------------------------------------- #
def test_surface_defaults_to_chat():
    assert AuditOptions().surface == "chat"
    assert validate_surface(None) == "chat"
    assert validate_surface("embedding") == "embedding"
    with pytest.raises(ConfigError):
        validate_surface("video")


def test_saved_report_without_surface_loads_as_chat():
    import json
    from pathlib import Path

    raw = json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
    raw.pop("surface", None)
    assert AuditReport.model_validate(raw).surface == "chat"


# --------------------------------------------------------------------------- #
# Detector selection
# --------------------------------------------------------------------------- #
def _ids(surface: str | None = None, suite: str = "full") -> list[str]:
    kwargs = {} if surface is None else {"surface": surface}
    return [
        d.id for d in base.select_detectors(
            suite, has_judge=True, has_baseline=True, enabled=lambda _id: True, **kwargs
        )
    ]


def test_select_detectors_filters_by_surface(monkeypatch):
    class _Embed(base.Detector):
        id = "zz.embed_probe"
        name = "Embed probe"
        dimension = Dimension.MODEL_IDENTITY
        surface = "embedding"

        async def run(self, ctx):  # pragma: no cover - never run here
            raise NotImplementedError

    chat = _ids()
    monkeypatch.setitem(base.REGISTRY, _Embed.id, _Embed)
    assert _ids() == chat == _ids("chat")
    assert "zz.embed_probe" not in chat
    assert _ids("embedding") == ["zz.embed_probe"]
    assert all(base.REGISTRY[i].surface == "chat" for i in chat)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def test_chat_tables_are_unchanged():
    assert weights_for(None) is weights_for("chat") is DIMENSION_WEIGHTS
    assert DIMENSION_WEIGHTS[Dimension.MODEL_IDENTITY] == 21.0


def test_embedding_weights():
    weights = SURFACE_WEIGHTS["embedding"]
    assert sum(weights.values()) == 100.0
    assert set(weights) == {
        Dimension.CONNECTIVITY, Dimension.MODEL_IDENTITY, Dimension.RELIABILITY,
        Dimension.CAPABILITY, Dimension.PERFORMANCE,
    }
    assert max(weights, key=weights.__getitem__) == Dimension.MODEL_IDENTITY


def test_embedding_scores_only_its_dimensions():
    results = [
        _result(Dimension.CONNECTIVITY, 100.0),
        _result(Dimension.MODEL_IDENTITY, 90.0),
        _result(Dimension.RELIABILITY, 80.0),
        _result(Dimension.CAPABILITY, 70.0),
        _result(Dimension.PERFORMANCE, 60.0),
    ]
    dims, verdict = _verdict(results)
    assert [d.dimension for d in dims] == list(SURFACE_WEIGHTS["embedding"])
    assert verdict.overall_score == 80.5  # (10*100 + 40*90 + 15*80 + 15*70 + 20*60) / 100
    assert verdict.rating == "B"
    assert verdict.risk_level == RiskLevel.CLEAN


def test_embedding_dimension_mismatch_is_high_risk():
    results = [
        _result(Dimension.CONNECTIVITY, 100.0),
        _result(Dimension.MODEL_IDENTITY, 20.0, severity=Severity.HIGH),
        _result(Dimension.CAPABILITY, 100.0),
    ]
    assert _verdict(results)[1].risk_level == RiskLevel.HIGH


def test_embedding_capability_high_alone_is_not_core():
    results = [
        _result(Dimension.MODEL_IDENTITY, 100.0),
        _result(Dimension.CAPABILITY, 20.0, severity=Severity.HIGH),
    ]
    # CAPABILITY is core for chat but not for embeddings.
    assert _verdict(results)[1].risk_level == RiskLevel.MEDIUM


def test_embedding_connectivity_high_does_not_escalate():
    results = [
        _result(Dimension.CONNECTIVITY, 0.0, severity=Severity.HIGH),
        _result(Dimension.MODEL_IDENTITY, 100.0),
    ]
    assert _verdict(results)[1].risk_level == RiskLevel.CLEAN


# --------------------------------------------------------------------------- #
# Recorder and performance summary
# --------------------------------------------------------------------------- #
async def test_client_records_embedding_calls():
    from tests.test_embed import EmbedMock, _target
    from zing.clients import OpenAICompatibleClient
    from zing.perf.recorder import RequestRecorder

    recorder = RequestRecorder()
    async with OpenAICompatibleClient(_target(), transport=EmbedMock(dim=8).transport) as c:
        c.recorder = recorder
        outcome, vectors = await c.embeddings(["alpha", "beta gamma"])
    assert outcome.ok and len(vectors) == 2
    (rec,) = recorder.records
    assert (rec.op, rec.endpoint, rec.stream, rec.ok) == ("embed", "target", False, True)
    assert rec.input_tokens_reported == 10
    assert rec.input_tokens_local and rec.input_tokens_local > 0
    assert rec.duration_ms is not None and rec.output_tokens_reported is None


def test_summary_op_parameter():
    from zing.models import RequestRecord
    from zing.perf.summary import build_performance, stats_pool, summarize_endpoint

    records = [
        RequestRecord(seq=i, op="embed", phase="probe", ok=True, duration_ms=10.0 * (i + 1))
        for i in range(3)
    ]
    # Chat summaries (the default) ignore embedding requests.
    assert build_performance(records) is None
    assert stats_pool(records) == []
    embed = summarize_endpoint(records, op="embed")
    assert (embed.source, embed.requests, embed.latency_ms.p50) == ("probe", 3, 20.0)
    report = build_performance(records, op="embed")
    assert report is not None and report.probe_requests == 3
    assert report.probe_cost is not None and report.probe_cost.requests == 3
