"""A re-score replaces the stored run in place; monitors follow it (#168)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from ekte import __version__, dbmigrate, evidence, replay
from ekte.schemas import WebhookPayload
from tests.test_replay import _record


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(evidence.ENV_OFF, raising=False)
    return tmp_path


def _saved(monkeypatch, *, watch_id=None, tool_version="0.1.0"):
    """A saved run with evidence, recorded "by" an older ekte."""
    from ekte.web import history

    path = evidence.data_dir_path(evidence.new_run_id())
    report = _record(monkeypatch, path, suite="smoke")
    report["tool_version"] = tool_version
    return history.save(report, watch_id=watch_id), path


def _metrics(rid):
    from ekte.web import history

    with sqlite3.connect(history._db_path()) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute("SELECT * FROM history_metrics WHERE history_id = ?", (rid,)).fetchone())


def _row(rid):
    from ekte.web import history

    with sqlite3.connect(history._db_path()) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute(
            "SELECT id, ts, watch_id, evidence_file, base_url, claimed_model, surface, risk_level,"
            " score, rating FROM history WHERE id = ?", (rid,)).fetchone())


def _count():
    from ekte.web import history

    with sqlite3.connect(history._db_path()) as c:
        return c.execute("SELECT COUNT(*) FROM history").fetchone()[0]


def _worse(report, risk="high", score=12.5, rating="F"):
    """``report`` with another verdict, as a stricter scoring would give it."""
    return {**report, "verdict": {**report["verdict"], "risk_level": risk,
                                  "overall_score": score, "rating": rating}}


# --------------------------------------------------------------------------- #
# history.replace and the replay's rescored_from
# --------------------------------------------------------------------------- #
def test_replace_keeps_the_run_and_takes_the_new_scoring(data, monkeypatch):
    from ekte.web import history, rescore

    rid, _ = _saved(monkeypatch, watch_id=None)
    before_row, before_metrics = _row(rid), _metrics(rid)
    n = _count()
    old, new = asyncio.run(rescore.rescore_run(rid))
    assert new["tool_version"] == __version__ and old["tool_version"] == "0.1.0"
    stricter = _worse(new)
    assert history.replace(rid, stricter)
    after = _row(rid)
    assert _count() == n
    for key in ("id", "ts", "watch_id", "evidence_file", "base_url", "claimed_model", "surface"):
        assert after[key] == before_row[key], key
    assert (after["risk_level"], after["score"], after["rating"]) == ("high", 12.5, "F")
    got = history.get(rid)
    assert got["verdict"]["overall_score"] == 12.5
    assert got["performance"]["requests"] == new["performance"]["requests"]  # request rows rewritten
    m = _metrics(rid)
    # the new scoring at the original time (Analytics)
    assert m["score"] == 12.5 and m["tool_version"] == __version__
    assert m["started_at"] == before_metrics["started_at"]
    assert before_metrics["tool_version"] == "0.1.0"
    assert history.replace(999, stricter) is False


def test_repeated_rescores_keep_the_recorded_version(data, monkeypatch):
    from ekte.web import history, rescore

    rid, _ = _saved(monkeypatch)
    original = history.get(rid)
    asyncio.run(rescore.rescore_run(rid))
    first = history.get(rid)["rescored_from"]
    assert first["tool_version"] == "0.1.0" and first["report_id"] == rid
    assert first["previous_verdict"]["risk_level"] == original["verdict"]["risk_level"]
    # a scoring of a third version: the recorded audit stays 0.1.0
    history.replace(rid, {**_worse(history.get(rid)), "tool_version": "0.2.0"})
    asyncio.run(rescore.rescore_run(rid))
    second = history.get(rid)["rescored_from"]
    assert second["tool_version"] == "0.1.0"
    assert second["generated_at"] == original["generated_at"]
    assert second["run_id"] == original["evidence"]["run_id"]
    assert second["report_id"] == rid
    assert second["previous_verdict"] == {"risk_level": "high", "overall_score": 12.5, "rating": "F"}
    assert second["rescored_at"] == history.get(rid)["generated_at"]


@pytest.mark.parametrize("url", ["/api/v1/history/{rid}/rescore?replace=true",
                                 "/api/history/{rid}/rescore"])
def test_the_api_job_replaces_the_run_and_reports_its_id(data, monkeypatch, url):
    from ekte.web import history
    from ekte.web.server import create_app

    rid, _ = _saved(monkeypatch)
    n = _count()
    with TestClient(create_app(), base_url="http://localhost") as client:
        created = client.post(url.format(rid=rid))
        assert "deprecation" not in created.headers
        job = created.json()
        r = client.get(f"/api/v1/jobs/{job['id']}/events")
        events = [json.loads(x[5:]) for x in r.text.splitlines() if x.startswith("data:")]
        ev = next(e for e in events if e["type"] == "report")
        assert ev["report_id"] == rid
        assert client.get(f"/api/v1/jobs/{job['id']}").json()["report_id"] == rid
    assert _count() == n
    assert history.get(rid)["tool_version"] == __version__


def test_cli_save_replaces_the_run(data, monkeypatch):
    from typer.testing import CliRunner

    from ekte.cli import app
    from ekte.web import history

    rid, _ = _saved(monkeypatch)
    n = _count()
    res = CliRunner().invoke(app, ["rescore", str(rid), "--replace"])
    assert res.exit_code == 0, res.output
    assert "replaced" in res.output and "Deprecated" not in res.output
    assert _count() == n and history.get(rid)["tool_version"] == __version__


# --------------------------------------------------------------------------- #
# Monitors
# --------------------------------------------------------------------------- #
@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    async def fake_send(url, report, *, previous=None, lang=None, rescored=False, **_):
        calls.append({"url": url, "report": report, "previous": previous, "rescored": rescored})
        return True

    monkeypatch.setattr("ekte.notify.send", fake_send)
    return calls


def _watch(alert_on="medium"):
    from ekte.web import watches

    return watches.create({"name": "w", "base_url": "http://relay/v1", "api_key": "", "model": "m",
                           "alert_on": alert_on, "webhooks": ["https://hooks.example/x"]})


def test_rescoring_a_monitors_latest_run_updates_its_card_and_alerts(data, monkeypatch, sent):
    from ekte.web import history, rescore, watches

    wid = _watch()
    rid, _ = _saved(monkeypatch, watch_id=wid)
    watches.mark_run(wid, "clean", 99.0, rid, 1000.0, duration_sec=5)
    old = history.get(rid)
    asyncio.run(rescore.store(rid, old, _worse(old)))
    w = watches.get_settings(wid)
    assert (w["last_risk"], w["last_score"], w["last_report_id"]) == ("high", 12.5, rid)
    assert w["last_run_ts"] == 1000.0 and w["run_duration_sec"] == 5
    assert len(sent) == 1 and sent[0]["rescored"] is True
    assert sent[0]["previous"]["verdict"] == old["verdict"]
    # the next monitor run's regression check compares with the re-scored verdict
    previous = history.latest_for(old["target"]["base_url"],
                                  old["target"].get("claimed_model") or old["target"]["model"])
    assert previous["verdict"]["risk_level"] == "high"
    from ekte.notify import regressed

    assert not regressed(_worse(old, risk="medium"), previous)


def test_a_better_rescore_below_the_threshold_sends_nothing(data, monkeypatch, sent):
    from ekte.web import history, rescore, watches

    wid = _watch(alert_on="high")
    rid, _ = _saved(monkeypatch, watch_id=wid)
    watches.mark_run(wid, "medium", 60.0, rid, 1000.0)
    old = _worse(history.get(rid), risk="medium", score=60.0, rating="D")
    history.replace(rid, old)
    asyncio.run(rescore.store(rid, old, _worse(old, risk="low", score=80.0, rating="B")))
    assert sent == []
    assert watches.get_settings(wid)["last_risk"] == "low"


def test_rescoring_an_older_run_of_a_monitor_sends_nothing(data, monkeypatch, sent):
    from ekte.web import history, rescore, watches

    wid = _watch()
    first, _ = _saved(monkeypatch, watch_id=wid)
    second, _ = _saved(monkeypatch, watch_id=wid)
    watches.mark_run(wid, "clean", 99.0, second, 2000.0)
    old = history.get(first)
    asyncio.run(rescore.store(first, old, _worse(old)))
    assert sent == []
    w = watches.get_settings(wid)
    assert (w["last_risk"], w["last_score"], w["last_report_id"]) == ("clean", 99.0, second)
    assert history.get(first)["verdict"]["risk_level"] == "high"


def test_webhook_payload_marks_a_rescore():
    from ekte import notify

    report = {"tool_version": "0.36.0", "verdict": {"risk_level": "high", "overall_score": 10},
              "target": {"base_url": "u", "model": "m"},
              "rescored_from": {"tool_version": "0.33.1"}}
    body = notify.format_generic(report, {"verdict": {"risk_level": "low"}}, rescored=True)
    assert body["schema_version"] == "1.1"
    assert body["rescored"] is True
    assert (body["audit_tool_version"], body["scoring_tool_version"]) == ("0.33.1", "0.36.0")
    assert "0.33.1" in body["text"] and "Before the re-score" in body["text"]
    WebhookPayload.model_validate(body)
    plain = notify.format_generic({**report, "rescored_from": None})
    assert plain["rescored"] is False and plain["audit_tool_version"] == "0.36.0"
    assert "Before the re-score" not in notify.build_text(report, {"verdict": {"risk_level": "low"}})


# --------------------------------------------------------------------------- #
# Bulk re-scores and the automatic one after an upgrade
# --------------------------------------------------------------------------- #
def test_bulk_rescore_skips_runs_without_evidence_and_records_why(data, monkeypatch):
    from ekte.web import history, rescore

    rid, _ = _saved(monkeypatch)
    plain = history.save({**history.get(rid), "evidence": None, "tool_version": "0.1.0"})
    current = history.save({**history.get(rid), "evidence": None, "tool_version": __version__})
    seen: dict[int, tuple] = {}

    def on_run(r, old, new, refusal):
        seen[r] = (new is not None, refusal)

    counts = asyncio.run(rescore.rescore_all(on_run))
    assert counts == {"rescored": 1, "skipped": 1, "failed": 0}
    assert seen == {rid: (True, None), plain: (False, replay.NO_EVIDENCE)}
    assert current not in seen  # already scored by this version
    assert history.get(plain)["tool_version"] == "0.1.0"  # keeps its verdict
    assert history.refusals()[plain]["refusal"] == replay.NO_EVIDENCE
    assert history.refusals()[plain]["version"] == __version__
    # nothing left for this version
    assert asyncio.run(rescore.rescore_all(on_run)) == {"rescored": 0, "skipped": 0, "failed": 0}


def test_cli_rescore_all_prints_before_and_after(data, monkeypatch):
    from typer.testing import CliRunner

    from ekte.cli import app
    from ekte.web import history

    rid, _ = _saved(monkeypatch)
    plain = history.save({**history.get(rid), "evidence": None})
    res = CliRunner().invoke(app, ["rescore", "--all"])
    assert res.exit_code == 0, res.output
    assert f"Run {rid}:" in res.output and "->" in res.output
    assert f"Run {plain}: skipped" in res.output
    assert "Re-scored 1 run(s)" in res.output
    assert CliRunner().invoke(app, ["rescore", "--all", str(rid)]).exit_code == 2
    assert CliRunner().invoke(app, ["rescore"]).exit_code == 2


def _wait(client, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        info = client.get("/api/rescore").json()
        if not info["active"] and info.get("finished"):
            return info
        time.sleep(0.1)
    raise AssertionError("the bulk re-score did not finish")


def test_upgrade_rescores_older_runs_once_and_alerts_on_the_latest(data, monkeypatch, sent):
    from ekte.web import history, rescore, watches
    from ekte.web.server import create_app

    wid = _watch()
    rid, _ = _saved(monkeypatch, watch_id=wid)
    ran = time.time()  # not due again while the server runs
    watches.mark_run(wid, "clean", 99.0, rid, ran)
    newer = history.save({**history.get(rid), "evidence": None, "tool_version": "99.0.0"})
    plain = history.save({**history.get(rid), "evidence": None})
    # this version's scoring is stricter than the one that recorded the run
    orig = rescore.store

    async def stricter(r, old, new):
        return await orig(r, old, _worse(new))

    monkeypatch.setattr(rescore, "store", stricter)
    monkeypatch.setenv("EKTE_AUTO_RESCORE", "1")
    with TestClient(create_app(), base_url="http://localhost") as client:
        info = _wait(client)
        assert info["trigger"] == "upgrade" and info["rescored"] == 1 and info["skipped"] == 1
    assert history.get(rid)["tool_version"] == __version__
    assert history.get(newer)["tool_version"] == "99.0.0"  # newer: left alone after an upgrade
    assert plain in history.refusals()
    assert history.get_meta(rescore.META_KEY) == __version__
    w = watches.get_settings(wid)
    assert (w["last_risk"], w["last_score"], w["last_run_ts"]) == ("high", 12.5, ran)
    assert len(sent) == 1 and sent[0]["rescored"] is True
    assert sent[0]["report"]["rescored_from"]["tool_version"] == "0.1.0"
    # once per version: the next start does nothing
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.get("/api/rescore").json()["started"] == info["started"]


def test_upgrade_rescore_resumes_after_a_restart(data, monkeypatch):
    from ekte.web import history, rescore

    rid, _ = _saved(monkeypatch)
    # a run the interrupted start re-scored already, and one it did not reach
    done, _ = _saved(monkeypatch, tool_version=__version__)
    assert rescore.upgrade_pending()
    ids = [r for r, _ in history.rescore_candidates(__version__)]
    assert rid in ids and done not in ids


def test_history_rescore_all_action(data, monkeypatch):
    from ekte.web import history
    from ekte.web.server import create_app

    rid, _ = _saved(monkeypatch)
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.get("/api/rescore").json()["active"] is False
        started = client.post("/api/rescore")
        assert started.status_code == 200 and started.json()["trigger"] == "manual"
        info = _wait(client)
        assert info["rescored"] == 1 and info["done"] == info["total"] == 1
    assert history.get(rid)["tool_version"] == __version__


def test_auto_rescore_can_be_turned_off(data, monkeypatch):
    from ekte.web import rescore

    monkeypatch.setenv("EKTE_AUTO_RESCORE", "0")
    assert not rescore.auto_enabled()
    monkeypatch.setenv("EKTE_AUTO_RESCORE", "1")
    assert rescore.auto_enabled()
    assert rescore.older("0.35.0", "0.36.0") and not rescore.older("0.36.1", "0.36.0")
    assert rescore.older(None, "0.36.0")


# --------------------------------------------------------------------------- #
# Migration step 17
# --------------------------------------------------------------------------- #
def test_history_step_17_adds_the_rescore_table_and_keeps_old_records(data):
    from ekte.web import history

    db = data / "history.db"
    with sqlite3.connect(db) as c:
        for m in history.MIGRATIONS[:16]:
            m.apply(c)
        c.execute("INSERT INTO history (ts, base_url, claimed_model, report_json, requests_split) "
                  "VALUES ('2026-01-01T00:00:00Z', 'https://x/v1', 'm', '{\"tool_version\": \"0.30.0\"}', 0)")
        c.execute("PRAGMA user_version = 16")
    history.init()
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == dbmigrate.latest(history.MIGRATIONS)
        assert c.execute("SELECT COUNT(*) FROM history_rescore").fetchone()[0] == 0
    assert history.get(1) == {"tool_version": "0.30.0"}
    history.record_refusal(1, "0.36.0", replay.NO_EVIDENCE)
    assert history.refusals([1])[1]["refusal"] == replay.NO_EVIDENCE
    history.delete(1)
    assert history.refusals() == {}
