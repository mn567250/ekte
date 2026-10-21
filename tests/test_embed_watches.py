"""Embedding-surface monitors: the scheduler runs an embedding audit with the
drift reference, and "monitor this" schedules an embedding run as a monitor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from zing.web.server import create_app  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "web_report.json"
_URL = "http://127.0.0.1:9099/v1"


def _report(**overrides):
    report = json.loads(_FIXTURE.read_text("utf-8"))
    report.update(overrides)
    return report


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


async def test_scheduler_runs_an_embedding_watch_with_its_drift_reference(tmp_path, monkeypatch):
    from zing.models import AuditReport
    from zing.web import history, server, watches

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    # a chat run of the same target must be neither the drift nor the alert reference
    prev_id = history.save(_report(surface="embedding", generated_at="2026-01-01T00:00:00Z"))
    history.save(_report())
    seen: dict = {}

    async def fake_run_audit(target, options, **kw):
        seen["options"] = options
        seen["previous"] = kw.get("previous_report")
        seen["pinned"] = kw.get("pinned")
        return AuditReport.model_validate(_report(surface="embedding"))

    sent: list = []

    async def fake_send(url, report, *, previous=None, lang=None):
        sent.append((url, previous))
        return True

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    monkeypatch.setattr("zing.notify.send", fake_send)
    cfg = {
        "base_url": _URL, "api_key": "sk-x", "model": "gpt-4o", "suite": "deep",
        "surface": "embedding", "embedding_dimensions": 1024, "alert_on": "high",
        "webhooks": ["https://hooks.test/x"],
    }
    wid = watches.create(cfg, knowledge=server._watch_knowledge(cfg))
    await server._run_one_watch(watches.get(wid))

    opts = seen["options"]
    assert opts.surface == "embedding" and opts.suite == "deep"
    assert opts.embedding_dimensions == 1024
    assert seen["previous"] is not None and seen["previous"]["surface"] == "embedding"
    assert seen["pinned"] is not None  # the KB pin is still applied
    row = watches.get(wid)
    rid = row["last_report_id"]
    assert rid is not None and rid != prev_id and history.watch_of(rid) == wid
    assert history.get(rid)["surface"] == "embedding"
    # alerted (risk high >= threshold) with the previous embedding run as the delta
    [(url, previous)] = sent
    assert url == "https://hooks.test/x" and previous["surface"] == "embedding"


async def test_chat_watch_passes_no_drift_reference(tmp_path, monkeypatch):
    from zing.models import AuditReport
    from zing.web import history, server, watches

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    history.save(_report(surface="embedding"))
    seen: dict = {}

    async def fake_run_audit(target, options, **kw):
        seen["options"], seen["previous"] = options, kw.get("previous_report")
        return AuditReport.model_validate(_report())

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    wid = watches.create({"base_url": _URL, "api_key": "sk-x", "model": "gpt-4o"})
    await server._run_one_watch(watches.get(wid))
    assert seen["options"].surface == "chat" and seen["previous"] is None


def test_create_and_edit_an_embedding_watch(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    body = {"base_url": _URL, "model": "text-embedding-3-small", "surface": "embedding",
            "embedding_dimensions": 512, "performance_streaming": False}
    wid = client.post("/api/watches", json=body).json()["id"]
    [w] = client.get("/api/watches").json()
    assert w["surface"] == "embedding" and w["embedding_dimensions"] == 512
    assert w["stream_mode"] is None and w["performance_streaming"] is True
    assert client.patch(f"/api/watches/{wid}", json={"embedding_dimensions": 0}).status_code == 200
    assert client.get("/api/watches").json()[0]["embedding_dimensions"] == 0
    assert client.patch(f"/api/watches/{wid}", json={"surface": "chat"}).status_code == 400
    bad = client.post("/api/watches", json={**body, "surface": "image"})
    assert bad.status_code == 400

    chat = client.post("/api/watches", json={"base_url": _URL, "model": "gpt-4o"}).json()["id"]
    r = client.patch(f"/api/watches/{chat}", json={"embedding_dimensions": 8})
    assert r.status_code == 400


def test_monitor_this_from_an_embedding_run(tmp_path, monkeypatch, client):
    from zing.web import history

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    rid = history.save(_report(surface="embedding", suite="deep"))
    r = client.post(f"/api/watches/from-history/{rid}", json={"embedding_dimensions": 768})
    assert r.status_code == 201
    [w] = client.get("/api/watches").json()
    assert w["surface"] == "embedding" and w["suite"] == "deep"
    assert w["embedding_dimensions"] == 768 and w["source_report_id"] == rid
    assert w["enabled"] is False and w["interval_sec"] is None
