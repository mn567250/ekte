"""The wire protocol (and whether it was auto-detected) and the performance
probe's request mode are recorded in every report, history row and monitor."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ekte.config import AuditOptions
from ekte.detectors.performance import stream_mode
from ekte.models import AuditReport, TargetConfig
from ekte.report.render import compact_dict, render_html, render_markdown
from ekte.runner import _redact

_FIXTURE = Path(__file__).parent / "fixtures" / "web_report.json"


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ekte.web.server import create_app

    return TestClient(create_app(), base_url="http://localhost")


def _fixture(**overrides) -> dict:
    report = json.loads(_FIXTURE.read_text("utf-8"))
    report.update(overrides)
    return report


def _with_protocol(api="anthropic", api_auto=False, mode="non_stream", **overrides) -> dict:
    report = _fixture(stream_mode=mode, **overrides)
    report["target"] = {**report["target"], "api": api, "api_auto": api_auto}
    return report


@pytest.mark.parametrize(
    ("suite", "streaming", "expected"),
    [("standard", True, "stream"), ("deep", False, "non_stream"), ("full", False, "both"), ("full", True, "both")],
)
def test_stream_mode_follows_the_probe_modes(suite, streaming, expected):
    assert stream_mode(AuditOptions(suite=suite, performance_streaming=streaming)) == expected


def test_redacted_target_records_the_resolved_protocol():
    auto = _redact(TargetConfig(base_url="https://api.anthropic.com/v1", model="x"))
    assert (auto.api, auto.api_auto) == ("anthropic", True)
    forced = _redact(TargetConfig(base_url="https://relay.test/v1", model="claude-x", api="openai"))
    assert (forced.api, forced.api_auto) == ("openai", False)


def test_renderers_show_protocol_and_request_mode():
    report = AuditReport.model_validate(_with_protocol())
    md = render_markdown(report)
    assert "protocol `anthropic` (set manually)" in md and "requests `non-streaming`" in md
    html = render_html(report)
    assert "protocol <code>anthropic</code> (set manually)" in html
    assert "requests <code>non-streaming</code>" in html
    compact = compact_dict(report)
    assert compact["target"]["api"] == "anthropic" and compact["target"]["api_auto"] is False
    assert compact["stream_mode"] == "non_stream"

    auto = AuditReport.model_validate(_with_protocol(api="openai", api_auto=True, mode="both"))
    md = render_markdown(auto)
    assert "protocol `openai` (auto-detected)" in md and "requests `streaming + non-streaming`" in md


def test_renderers_skip_the_fields_for_older_reports():
    report = AuditReport.model_validate(_fixture())
    assert report.target.api is None and report.stream_mode is None
    md = render_markdown(report)
    assert "protocol `" not in md and "requests `" not in md
    assert compact_dict(report)["stream_mode"] is None


def test_pdf_renders_the_protocol():
    pytest.importorskip("reportlab")
    from ekte.report.pdf import render_pdf

    assert render_pdf(AuditReport.model_validate(_with_protocol()))[:4] == b"%PDF"


def test_history_rows_carry_protocol_and_mode(tmp_path, monkeypatch, client):
    from ekte.web import history

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    new = history.save(_with_protocol())
    old = history.save(_fixture())
    rows = {r["id"]: r for r in client.get("/api/history").json()}
    assert (rows[new]["api"], rows[new]["api_auto"], rows[new]["stream_mode"]) == ("anthropic", 0, "non_stream")
    assert (rows[old]["api"], rows[old]["api_auto"], rows[old]["stream_mode"]) == (None, None, None)


def test_history_db_from_before_is_migrated(tmp_path, monkeypatch):
    import sqlite3

    from ekte.web import history

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    conn = sqlite3.connect(tmp_path / "history.db")
    conn.execute(
        "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, base_url TEXT,"
        " claimed_model TEXT, model TEXT, mode TEXT, suite TEXT, risk_level TEXT, score REAL,"
        " rating TEXT, report_json TEXT)"
    )
    conn.execute("INSERT INTO history (ts, base_url, report_json) VALUES ('t', 'u', '{}')")
    conn.commit()
    conn.close()
    [row] = history.recent()
    assert row["api"] is None and row["stream_mode"] is None


def test_schedule_keeps_a_forced_protocol_and_the_request_mode(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import history

    forced = history.save(_with_protocol(api="anthropic", api_auto=False, mode="non_stream"))
    detected = history.save(_with_protocol(api="anthropic", api_auto=True, mode="stream"))
    old = history.save(_fixture())
    ids = {}
    for rid in (forced, detected, old):
        r = client.post(f"/api/watches/from-history/{rid}")
        assert r.status_code == 201
        ids[rid] = r.json()["id"]
    watches = {w["id"]: w for w in client.get("/api/watches").json()}

    w = watches[ids[forced]]
    assert (w["api"], w["api_auto"], w["api_resolved"]) == ("anthropic", False, "anthropic")
    assert w["performance_streaming"] is False and w["stream_mode"] == "non_stream"
    w = watches[ids[detected]]
    assert (w["api"], w["api_auto"]) == ("auto", True) and w["stream_mode"] == "stream"
    w = watches[ids[old]]
    assert (w["api"], w["api_auto"], w["api_resolved"]) == ("auto", True, "openai")
    assert w["performance_streaming"] is True


async def test_monitor_runs_with_its_request_mode(tmp_path, monkeypatch):
    from ekte.web import history, server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    seen: list[AuditOptions] = []
    report = AuditReport.model_validate(_with_protocol())

    async def fake_run_audit(_target, options, **_k):
        seen.append(options)
        return report

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "gpt-4o",
                          "performance_streaming": False})
    await server._run_one_watch(watches.get(wid))
    assert seen[0].performance_streaming is False
    [row] = history.recent()
    assert row["watch_id"] == wid and row["stream_mode"] == "non_stream" and row["api"] == "anthropic"


def test_audit_job_summary_names_protocol_and_mode(tmp_path, monkeypatch, client):
    from ekte.web import jobs

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    captured = {}

    class _Job:
        def info(self):
            return {}

    def fake_submit(summary, _urls, _run):
        captured.update(summary)
        return _Job()

    monkeypatch.setattr(jobs.manager, "submit", fake_submit)
    client.post("/api/jobs", json={"base_url": "https://api.anthropic.com/v1", "model": "claude-x",
                                   "suite": "standard", "performance_streaming": False})
    assert captured["api"] == "anthropic" and captured["api_auto"] is True
    assert captured["stream_mode"] == "non_stream"


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")


@needs_node
@pytest.mark.parametrize("lang", ["en", "de"])
def test_v2_report_meta_shows_protocol_and_mode(tmp_path, lang):
    from test_web_v2_report_js import _render

    report = _with_protocol(api="openai", api_auto=True, mode="both")
    report["baseline"] = {**report["target"], "name": "b", "kind": "baseline", "api": "anthropic", "api_auto": False}
    html = _render(tmp_path, lang, report)["html"]
    if lang == "en":
        assert "<dt>Protocol</dt><dd><code>openai</code> · auto-detected</dd>" in html
        assert "<code>anthropic</code> · set manually</dd>" in html
        assert "<dt>Performance probe requests</dt><dd>Streaming + non-streaming</dd>" in html
    else:
        assert "<dt>Protokoll</dt><dd><code>openai</code> · automatisch erkannt</dd>" in html
        assert "manuell festgelegt" in html and "Streaming + ohne Streaming" in html

    old = _render(tmp_path, "en", _fixture())["html"]
    assert "<dt>Protocol</dt>" not in old and "<dt>Performance probe requests</dt>" not in old
