"""Rerank-surface monitors: the scheduler runs a rerank audit with the previous
rerank run as the drift reference, and "monitor this" schedules a rerank run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from zing.web.server import create_app  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "web_report.json"
_URL = "http://127.0.0.1:9099/v1"
_MODEL = "r-model"


def _report(**overrides):
    report = json.loads(_FIXTURE.read_text("utf-8"))
    report["target"] = {**report["target"], "model": _MODEL}
    report.update(overrides)
    return report


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


async def test_scheduler_runs_a_rerank_watch_with_the_previous_rerank_run(tmp_path, monkeypatch):
    from zing.models import AuditReport
    from zing.web import history, server, watches

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    # Newer chat and embedding runs of the same target must be neither the
    # drift nor the alert reference.
    prev_id = history.save(_report(surface="rerank", generated_at="2026-01-01T00:00:00Z"))
    history.save(_report(surface="embedding"))
    history.save(_report())
    seen: dict = {}

    async def fake_run_audit(target, options, **kw):
        seen["options"] = options
        seen["previous"] = kw.get("previous_report")
        return AuditReport.model_validate(_report(surface="rerank"))

    sent: list = []

    async def fake_send(url, report, *, previous=None, lang=None):
        sent.append((url, previous))
        return True

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    monkeypatch.setattr("zing.notify.send", fake_send)
    # A stray claimed vector length means nothing to a rerank watch.
    cfg = {
        "base_url": _URL, "api_key": "sk-x", "model": _MODEL, "suite": "deep",
        "surface": "rerank", "embedding_dimensions": 1024, "alert_on": "high",
        "webhooks": ["https://hooks.test/x"],
    }
    wid = watches.create(cfg, knowledge=server._watch_knowledge(cfg))
    assert watches.get(wid)["embedding_dimensions"] == 0
    await server._run_one_watch(watches.get(wid))

    opts = seen["options"]
    assert opts.surface == "rerank" and opts.suite == "deep"
    assert opts.embedding_dimensions == 0
    previous = seen["previous"]
    assert previous is not None and previous["surface"] == "rerank"
    assert previous["generated_at"].startswith("2026-01-01")
    rid = watches.get(wid)["last_report_id"]
    assert rid is not None and rid != prev_id and history.watch_of(rid) == wid
    assert history.get(rid)["surface"] == "rerank"
    # alerted (risk high >= threshold) with the previous rerank run as the delta
    [(url, alert_prev)] = sent
    assert url == "https://hooks.test/x" and alert_prev["surface"] == "rerank"


async def test_first_rerank_watch_run_has_no_drift_reference(tmp_path, monkeypatch):
    from zing.models import AuditReport
    from zing.web import history, server, watches

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    history.save(_report(surface="embedding"))
    history.save(_report())
    seen: dict = {}

    async def fake_run_audit(target, options, **kw):
        seen["options"], seen["previous"] = options, kw.get("previous_report")
        return AuditReport.model_validate(_report(surface="rerank"))

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    wid = watches.create({"base_url": _URL, "api_key": "sk-x", "model": _MODEL, "surface": "rerank"})
    await server._run_one_watch(watches.get(wid))
    assert seen["options"].surface == "rerank" and seen["previous"] is None


def test_create_and_edit_a_rerank_watch(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    body = {"base_url": _URL, "model": _MODEL, "surface": "rerank", "embedding_dimensions": 512,
            "performance_streaming": False}
    r = client.post("/api/watches", json=body)
    assert r.status_code == 201
    wid = r.json()["id"]
    [w] = client.get("/api/watches").json()
    assert w["surface"] == "rerank" and w["embedding_dimensions"] == 0
    # rerank requests never stream: no probe request mode
    assert w["stream_mode"] is None and w["performance_streaming"] is True
    r = client.patch(f"/api/watches/{wid}", json={"embedding_dimensions": 8})
    assert r.status_code == 400
    assert client.patch(f"/api/watches/{wid}", json={"surface": "embedding"}).status_code == 400
    assert client.patch(f"/api/watches/{wid}", json={"interval_sec": 600}).status_code == 200


def test_monitor_this_from_a_rerank_run(tmp_path, monkeypatch, client):
    from zing.web import history

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    rid = history.save(_report(surface="rerank", suite="deep", stream_mode="non_stream"))
    # a claimed vector length sent along is dropped: it is an embedding setting
    r = client.post(f"/api/watches/from-history/{rid}", json={"embedding_dimensions": 768})
    assert r.status_code == 201
    [w] = client.get("/api/watches").json()
    assert w["surface"] == "rerank" and w["suite"] == "deep"
    assert w["embedding_dimensions"] == 0 and w["source_report_id"] == rid
    assert w["performance_streaming"] is True and w["stream_mode"] is None
    assert w["enabled"] is False and w["interval_sec"] is None


def test_monitor_this_refuses_a_run_of_an_unknown_surface(tmp_path, monkeypatch, client):
    from zing.web import history

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    rid = history.save(_report(surface="hologram"))
    r = client.post(f"/api/watches/from-history/{rid}", json={})
    assert r.status_code == 400 and "surface" in r.json()["error"]
    assert client.get("/api/watches").json() == []
