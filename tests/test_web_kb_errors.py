"""A knowledge base that fails to load: the client gets a generic 400, the log the traceback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web import server  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "web_report.json"
_URL = "http://127.0.0.1:9099/v1"
_MESSAGE = "knowledge base could not be loaded (ValueError); see the ekte serve log for details."


@pytest.fixture
def broken_kb(monkeypatch, tmp_path):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    def broken(*_a, **_kw):
        raise ValueError("internal detail /srv/kb/broken.yaml")

    monkeypatch.setattr(server, "_watch_knowledge", broken)
    return TestClient(server.create_app(), base_url="http://localhost")


def _assert_generic(r, caplog) -> None:
    assert r.status_code == 400
    assert r.json() == {"error": _MESSAGE}
    assert "internal detail" not in r.text
    rec = next(x for x in caplog.records if x.getMessage() == "knowledge base could not be loaded")
    assert rec.exc_info and "internal detail" in str(rec.exc_info[1])


def test_creating_a_watch_with_a_broken_kb(broken_kb, caplog):
    with caplog.at_level("ERROR", logger="ekte.web"):
        r = broken_kb.post("/api/watches", json={"base_url": _URL, "model": "gpt-4o"})
    _assert_generic(r, caplog)


def test_scheduling_a_history_run_with_a_broken_kb(broken_kb, caplog):
    from ekte.web import history

    rid = history.save(json.loads(_FIXTURE.read_text("utf-8")))
    with caplog.at_level("ERROR", logger="ekte.web"):
        r = broken_kb.post(f"/api/watches/from-history/{rid}", json={})
    _assert_generic(r, caplog)
