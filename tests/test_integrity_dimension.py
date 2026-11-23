"""The ``integrity`` dimension (#260): response tampering, an injected system
prompt, a response cache and prefix caching are scored apart from transport
security, on every surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ekte.config import stored_dimensions
from ekte.detectors import REGISTRY
from ekte.models import (
    AuditReport,
    DetectorResult,
    Dimension,
    Finding,
    RiskLevel,
    Severity,
    Status,
)
from ekte.report import dimensions as report_dimensions
from ekte.report.render import render_html, render_markdown
from ekte.scoring import (
    DIMENSION_NAMES,
    DIMENSION_WEIGHTS,
    SURFACE_WEIGHTS,
    build_dimensions,
    build_verdict,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _by_dimension(dimension: Dimension) -> set[str]:
    return {i for i, cls in REGISTRY.items() if cls.dimension == dimension}


def test_detectors_are_filed_under_the_dimension_they_check():
    assert _by_dimension(Dimension.INTEGRITY) == {
        "integrity", "injected_prompt", "determinism", "prompt_cache",
        "embed.determinism", "rerank.determinism",
    }
    # transport security keeps TLS, key echo and headers only
    assert _by_dimension(Dimension.SECURITY) == {"security"}
    assert "determinism" not in _by_dimension(Dimension.PROTOCOL)
    # reliability is the chat burst alone
    assert _by_dimension(Dimension.RELIABILITY) == {"reliability"}


def test_weights():
    assert sum(DIMENSION_WEIGHTS.values()) == 100.0
    assert DIMENSION_WEIGHTS[Dimension.INTEGRITY] == 6.0
    assert DIMENSION_WEIGHTS[Dimension.SECURITY] == 4.0
    assert DIMENSION_WEIGHTS[Dimension.PERFORMANCE] == 4.0
    # embedding and rerank: integrity takes reliability's place and weight
    assert SURFACE_WEIGHTS["embedding"][Dimension.INTEGRITY] == 15.0
    assert SURFACE_WEIGHTS["rerank"][Dimension.INTEGRITY] == 10.0
    for surface in ("embedding", "rerank"):
        assert Dimension.RELIABILITY not in SURFACE_WEIGHTS[surface]
        assert sum(SURFACE_WEIGHTS[surface].values()) == 100.0


def test_every_surface_dimension_has_a_detector():
    for surface, weights in SURFACE_WEIGHTS.items():
        have = {cls.dimension for cls in REGISTRY.values() if cls.surface == surface}
        assert have == set(weights), surface


def test_names():
    assert DIMENSION_NAMES[Dimension.INTEGRITY] == "Response integrity"
    assert DIMENSION_NAMES[Dimension.SECURITY] == "Transport security"
    assert set(DIMENSION_NAMES) == set(Dimension)
    # the protocol detector also runs against Anthropic Messages and Responses targets
    assert REGISTRY["protocol"].name == "Wire-protocol conformance"


def _core() -> list[DetectorResult]:
    return [
        DetectorResult(id=d.value, name=d.value, dimension=d, score=95.0, status=Status.PASS)
        for d in (Dimension.MODEL_IDENTITY, Dimension.CONTEXT_WINDOW, Dimension.CAPABILITY)
    ]


def _verdict(severity: Severity):
    finding = Finding(id="integrity.verdict", title="Response tampered", status=Status.FAIL,
                      severity=severity)
    detectors = [*_core(), DetectorResult(id="integrity", name="i", dimension=Dimension.INTEGRITY,
                                          score=10.0, status=Status.FAIL, findings=[finding])]
    dims = build_dimensions(detectors, None)
    return build_verdict(detectors, dims, profile_matched=True, used_judge=False, used_baseline=False)


@pytest.mark.parametrize(("severity", "risk"), [
    # not a core dimension: one HIGH finding is medium risk, as in any other
    # dimension outside the core; its severity alone sets the risk
    (Severity.MEDIUM, RiskLevel.LOW),
    (Severity.HIGH, RiskLevel.MEDIUM),
    (Severity.CRITICAL, RiskLevel.HIGH),
])
def test_integrity_findings_set_the_risk_by_severity(severity, risk):
    verdict = _verdict(severity)
    assert verdict.risk_level == risk
    assert verdict.drivers == [Dimension.INTEGRITY]


def test_headline_names_response_integrity_not_transport_security():
    headline = _verdict(Severity.CRITICAL).headline
    assert "Response integrity" in headline and "Transport security" not in headline


# --------------------------------------------------------------------------- #
# reports and selections saved before the dimension existed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["web_report.json", "history_report.json"])
def test_a_report_without_the_integrity_dimension_loads_and_renders(name):
    raw = json.loads((FIXTURES / name).read_text("utf-8"))
    assert "integrity" not in {d["dimension"] for d in raw["dimensions"]}
    report = AuditReport.model_validate(raw)
    listed = report_dimensions.all_dimensions(report)
    # what it recorded is kept as recorded; the new dimension is listed as not run
    assert [d.dimension for d in listed[:len(report.dimensions)]] == [d.dimension for d in report.dimensions]
    added = next(d for d in listed if d.dimension == Dimension.INTEGRITY)
    assert added.status == Status.NOT_RUN and added.score is None
    assert added.reason == "Not recorded in this report."
    assert report.verdict.overall_score == raw["verdict"]["overall_score"]
    md = render_markdown(report)
    assert "integrity — — (not_run)" in md and "| integrity | — |" in md
    page = render_html(report)
    assert page.count('<details class="dim">') == len(Dimension)


def test_an_old_report_with_security_filed_integrity_detectors_loads():
    # before #260 the tampering detector reported under ``security``
    raw = json.loads((FIXTURES / "web_report.json").read_text("utf-8"))
    raw["detectors"].append({
        "id": "integrity", "name": "Response integrity / tampering", "dimension": "security",
        "status": "pass", "score": 100.0,
        "findings": [{"id": "integrity.verdict", "title": "Canaries intact", "status": "pass",
                      "severity": "info"}],
    })
    report = AuditReport.model_validate(raw)
    det = next(d for d in report.detectors if d.id == "integrity")
    assert det.dimension == Dimension.SECURITY
    assert "Response integrity / tampering" in render_markdown(report)
    assert "Response integrity / tampering" in render_html(report)


def test_an_old_embedding_report_keeps_its_reliability_dimension():
    raw = json.loads((FIXTURES / "web_report.json").read_text("utf-8"))
    raw["surface"] = "embedding"
    raw["dimensions"] = [
        {"dimension": "connectivity", "score": 100.0, "weight": 10.0, "status": "pass"},
        {"dimension": "reliability", "score": 100.0, "weight": 15.0, "status": "pass"},
    ]
    raw["detectors"] = [{"id": "embed.determinism", "name": "Embedding determinism",
                         "dimension": "reliability", "status": "pass", "score": 100.0}]
    report = AuditReport.model_validate(raw)
    listed = [d.dimension for d in report_dimensions.all_dimensions(report)]
    assert listed[:2] == [Dimension.CONNECTIVITY, Dimension.RELIABILITY]
    assert Dimension.INTEGRITY in listed
    assert "### ✅ reliability — 100" in render_markdown(report)
    assert render_html(report)


def test_saved_selections_read_reliability_as_integrity_off_chat():
    assert stored_dimensions("embedding", ["reliability", "capability"]) == ["integrity", "capability"]
    assert stored_dimensions("rerank", ["reliability", "integrity"]) == ["integrity"]
    # chat still has a reliability dimension
    assert stored_dimensions("chat", ["reliability"]) == ["reliability"]
    assert stored_dimensions(None, ["reliability"]) == ["reliability"]
    assert stored_dimensions("embedding", None) == []


def test_a_saved_embedding_monitor_and_run_select_integrity(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ekte.web import history, watches
    from ekte.web.server import create_app

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    client = TestClient(create_app(), base_url="http://localhost")
    # a monitor saved by an earlier version
    r = client.post("/api/watches", json={
        "name": "e", "base_url": "http://127.0.0.1:9099/v1", "model": "text-embedding-3-small",
        "suite": "custom", "dimensions": ["integrity"], "surface": "embedding", "interval_sec": 3600,
    })
    assert r.status_code in (200, 201), r.text
    wid = r.json()["id"]
    with watches._connect() as conn:
        conn.execute("UPDATE watches SET dimensions = ? WHERE id = ?", ('["reliability"]', wid))
    assert watches.get(wid)["dimensions"] == ["integrity"]
    # a run saved by an earlier version, scheduled from History
    report = json.loads((FIXTURES / "web_report.json").read_text("utf-8"))
    report.update(surface="embedding", suite="custom", dimensions_selected=["reliability"])
    rid = history.save(report)
    r = client.post(f"/api/watches/from-history/{rid}")
    assert r.status_code == 201, r.text
    assert watches.get(r.json()["id"])["dimensions"] == ["integrity"]
    # reliability itself is no longer an embedding dimension
    r = client.post("/api/watches", json={
        "name": "e2", "base_url": "http://127.0.0.1:9099/v1", "model": "text-embedding-3-small",
        "suite": "custom", "dimensions": ["reliability"], "surface": "embedding", "interval_sec": 3600,
    })
    assert r.status_code == 400
