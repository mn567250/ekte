"""Tests for the scheduled-watch store and its web endpoints.

Skipped automatically when the optional web extra (fastapi) isn't installed.
These never touch the network: they cover the SQLite store roundtrip and the
/api/watches CRUD endpoints, asserting that the api_key never leaks into a
listing, and drive the scheduler loop with fake audits.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web.server import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def test_watch_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import watches

    assert watches.list_all() == []

    wid = watches.create(
        {
            "name": "prod relay",
            "base_url": "https://relay.test/v1",
            "api_key": "sk-super-secret",
            "model": "gpt-4o",
            "claimed_model": "gpt-4o",
            "api": "openai",
            "suite": "standard",
            "interval_sec": 3600,
            "alert_on": "medium",
            "webhooks": ["https://hooks.slack.com/services/x"],
        }
    )
    assert isinstance(wid, int) and wid > 0

    # Listing must never expose the api_key, but should decode webhooks/enabled.
    rows = watches.list_all()
    assert len(rows) == 1
    row = rows[0]
    assert "api_key" not in row
    assert row["name"] == "prod relay"
    assert row["webhooks"] == ["https://hooks.slack.com/services/x"]
    assert row["enabled"] is True

    # get() is the server-side view and DOES carry the key for the scheduler.
    full = watches.get(wid)
    assert full is not None and full["api_key"] == "sk-super-secret"

    # A brand-new watch (never run) is due immediately.
    import time

    due = watches.due(time.time())
    assert len(due) == 1 and due[0]["id"] == wid

    # Record a run; risk/score/report id + run time persist.
    watches.mark_run(wid, "high", 21.0, 7, ts=time.time())
    after = watches.get(wid)
    assert after["last_risk"] == "high" and after["last_score"] == 21.0
    assert after["last_report_id"] == 7

    # With a fresh last_run and a long interval, it is no longer due.
    assert watches.due(time.time()) == []

    # Disable, then it is excluded from due() regardless of timing.
    watches.set_enabled(wid, False)
    assert watches.list_all()[0]["enabled"] is False
    assert watches.due(time.time() + 10_000) == []

    watches.delete(wid)
    assert watches.list_all() == []


def test_watches_endpoints_create_list_delete(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    assert client.get("/api/watches").json() == []

    r = client.post(
        "/api/watches",
        json={
            "name": "my watch",
            "base_url": "https://relay.test/v1",
            "api_key": "sk-do-not-leak",
            "model": "gpt-4o",
            "suite": "standard",
            "alert_on": "medium",
            "interval_sec": 7200,
            "webhooks": ["https://example.com/hook"],
        },
    )
    assert r.status_code == 201
    wid = r.json()["id"]
    assert isinstance(wid, int) and wid > 0

    listed = client.get("/api/watches").json()
    assert len(listed) == 1
    one = listed[0]
    assert one["id"] == wid and one["name"] == "my watch"
    # The endpoint listing must NOT include the api_key anywhere.
    assert "api_key" not in one
    assert "sk-do-not-leak" not in r.text
    assert "sk-do-not-leak" not in client.get("/api/watches").text

    # PATCH toggles enabled.
    assert client.patch(f"/api/watches/{wid}", json={"enabled": False}).status_code == 200
    assert client.get("/api/watches").json()[0]["enabled"] is False

    # DELETE removes it.
    assert client.delete(f"/api/watches/{wid}").status_code == 200
    assert client.get("/api/watches").json() == []


def test_watches_create_bad_target_is_clean_400(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    r = client.post("/api/watches", json={"base_url": "", "model": ""})
    assert r.status_code == 400 and "error" in r.json()
    # Nothing was persisted.
    assert client.get("/api/watches").json() == []


def test_watches_create_unknown_suite_is_400(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    r = client.post(
        "/api/watches",
        json={"base_url": "https://x/v1", "model": "gpt-4o", "suite": "bogus"},
    )
    assert r.status_code == 400


def test_watches_page_and_nav_link(client):
    r = client.get("/watches")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "监控" in r.text
    # The SPA exposes a nav link to /watches.
    assert 'href="/watches"' in client.get("/").text


def test_patch_and_run_missing_watch_404(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    assert client.patch("/api/watches/999999", json={"enabled": True}).status_code == 404
    assert client.post("/api/watches/999999/run").status_code == 404


def test_watch_alert_language_default_create_patch(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    base = {"base_url": "https://relay.test/v1", "model": "gpt-4o", "webhooks": []}

    # No language given -> English; a supported one is stored; junk -> English.
    a = client.post("/api/watches", json=base).json()["id"]
    b = client.post("/api/watches", json={**base, "language": "de"}).json()["id"]
    c = client.post("/api/watches", json={**base, "language": "klingon"}).json()["id"]
    langs = {w["id"]: w["language"] for w in client.get("/api/watches").json()}
    assert langs == {a: "en", b: "de", c: "en"}

    assert client.patch(f"/api/watches/{a}", json={"language": "zh"}).status_code == 200
    assert {w["id"]: w["language"] for w in client.get("/api/watches").json()}[a] == "zh"


def test_watch_db_from_before_alert_languages_is_migrated(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import watches

    # A watches table as created by earlier versions (no `language` column).
    path = watches._db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE watches (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, base_url TEXT,"
            " api_key TEXT, model TEXT, claimed_model TEXT, api TEXT, declared_provider TEXT,"
            " suite TEXT, interval_sec INTEGER, alert_on TEXT, webhooks TEXT, enabled INTEGER DEFAULT 1,"
            " created_ts REAL, last_run_ts REAL, last_risk TEXT, last_score REAL, last_report_id INTEGER)"
        )
        conn.execute("INSERT INTO watches (name, base_url, model, webhooks) VALUES ('old', 'https://x/v1', 'm', '[]')")

    [old] = watches.list_all()
    assert old["name"] == "old" and old["language"] == "en"
    assert old["source_report_id"] is None and old["has_key"] is False
    watches.set_language(old["id"], "fr")
    assert watches.get(old["id"])["language"] == "fr"


async def test_scheduled_watch_alerts_in_its_language(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from ekte import notify
    from ekte.models import AuditReport
    from ekte.web import server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    report = AuditReport.model_validate(
        json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
    )

    async def fake_run_audit(*_a, **_k):
        return report

    sent: list[dict] = []

    async def fake_send(url, report_dict, **kw):
        sent.append({"url": url, **kw})
        return True

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    monkeypatch.setattr(notify, "send", fake_send)
    wid = watches.create({
        "base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "gpt-4o",
        "alert_on": "medium", "webhooks": ["https://hooks.slack.com/services/x"], "language": "it",
    })
    await server._run_one_watch(watches.get(wid))
    assert [s["lang"] for s in sent] == ["it"]


# ----- scheduling a history run as a monitor ------------------------------ #


def _saved_report(**overrides):
    import json
    from pathlib import Path

    from ekte.web import history

    report = json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
    report.update(overrides)
    return history.save(report)


def test_schedule_history_run_creates_a_paused_draft(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    rid = _saved_report()
    r = client.post(f"/api/watches/from-history/{rid}", json={"language": "de"})
    assert r.status_code == 201
    wid = r.json()["id"]
    [w] = client.get("/api/watches").json()
    assert w["id"] == wid and w["source_report_id"] == rid
    # the run's configuration, but no schedule, no key, and switched off
    assert w["base_url"] == "http://127.0.0.1:9099/v1" and w["model"] == "gpt-4o"
    assert w["name"] == "gpt-4o" and w["suite"] == "standard" and w["api"] == "auto"
    assert w["interval_sec"] is None and w["enabled"] is False and w["has_key"] is False
    assert w["language"] == "de" and w["alert_on"] == "medium" and w["webhooks"] == []

    assert client.post("/api/watches/from-history/999999").status_code == 404


async def test_monitor_runs_are_tagged_and_cannot_be_rescheduled(tmp_path, monkeypatch, client):
    import json
    from pathlib import Path

    from ekte.models import AuditReport
    from ekte.web import history, server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    report = AuditReport.model_validate(
        json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
    )

    async def fake_run_audit(*_a, **_k):
        return report

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "gpt-4o"})
    await server._run_one_watch(watches.get(wid))
    manual = _saved_report()

    by_id = {r["id"]: r for r in client.get("/api/history").json()}
    mon = watches.get(wid)["last_report_id"]
    assert by_id[mon]["watch_id"] == wid and by_id[manual]["watch_id"] is None
    assert history.watch_of(mon) == wid and history.watch_of(manual) is None

    r = client.post(f"/api/watches/from-history/{mon}")
    assert r.status_code == 409 and "monitor" in r.json()["error"]
    assert client.post(f"/api/watches/from-history/{manual}").status_code == 201


def test_schedule_keeps_a_custom_suites_dimensions(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    rid = _saved_report(suite="custom", dimensions_selected=["security", "protocol"])
    client.post(f"/api/watches/from-history/{rid}")
    [w] = client.get("/api/watches").json()
    assert w["suite"] == "custom" and sorted(w["dimensions"]) == ["protocol", "security"]


def test_draft_needs_interval_but_not_a_key_before_it_runs(tmp_path, monkeypatch, client):
    import time

    from ekte.web import watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    wid = client.post(f"/api/watches/from-history/{_saved_report()}").json()["id"]

    # never picked up by the scheduler, even if switched on behind the API's back
    watches.set_enabled(wid, True)
    assert watches.due(time.time()) == []
    watches.set_enabled(wid, False)

    r = client.patch(f"/api/watches/{wid}", json={"enabled": True})
    assert r.status_code == 400 and "interval" in r.json()["error"]

    # the key is optional, as in the audit: a local relay needs none
    r = client.patch(f"/api/watches/{wid}", json={"enabled": True, "interval_sec": 600})
    assert r.status_code == 200
    [w] = client.get("/api/watches").json()
    assert w["enabled"] is True and w["interval_sec"] == 600 and w["has_key"] is False
    assert [d["id"] for d in watches.due(time.time())] == [wid]

    # a key can still be added later
    r = client.patch(f"/api/watches/{wid}", json={"api_key": "sk-draft-secret"})
    assert r.status_code == 200
    assert client.get("/api/watches").json()[0]["has_key"] is True
    assert "sk-draft-secret" not in client.get("/api/watches").text
    assert watches.get(wid)["api_key"] == "sk-draft-secret"


def test_patch_validates_schedule_and_alert_settings(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    wid = client.post(
        "/api/watches", json={"base_url": "https://relay.test/v1", "model": "gpt-4o", "api_key": "sk-a"}
    ).json()["id"]
    url = f"/api/watches/{wid}"
    for bad in ({"interval_sec": 10}, {"interval_sec": "600"}, {"interval_sec": True},
                {"alert_on": "extreme"}, {"webhooks": "https://x"}, {"webhooks": ["ftp://x"]}):
        assert client.patch(url, json=bad).status_code == 400, bad
    assert client.patch(url, json={
        "interval_sec": 900, "alert_on": "high", "webhooks": [" https://hooks.test/a ", ""], "api_key": "  ",
    }).status_code == 200
    [w] = client.get("/api/watches").json()
    assert w["interval_sec"] == 900 and w["alert_on"] == "high" and w["webhooks"] == ["https://hooks.test/a"]
    from ekte.web import watches

    assert watches.get(wid)["api_key"] == "sk-a"  # a blank key leaves the stored one alone
    # a form-created keyless watch (a relay without auth) can still be switched on
    keyless = client.post("/api/watches", json={"base_url": "https://open.test/v1", "model": "m", "enabled": False}).json()["id"]
    assert client.patch(f"/api/watches/{keyless}", json={"enabled": True}).status_code == 200


def test_running_watch_is_flagged_and_rejects_run_now(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import server, watches

    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "gpt-4o"})
    w = client.get("/api/watches").json()[0]
    assert w["running"] is False and w["progress"] is None
    server._running_watches[wid] = {"total": 4, "done": 1}
    try:
        w = client.get("/api/watches").json()[0]
        assert w["running"] is True and w["progress"] == 25
        assert client.post(f"/api/watches/{wid}/run").status_code == 409
    finally:
        server._running_watches.pop(wid, None)
    # nothing to cancel once it stopped
    assert client.post(f"/api/watches/{wid}/cancel").status_code == 409


def test_watch_progress_counts_detectors_and_probe_requests():
    from ekte.web import server

    state: dict = {}
    assert server._watch_progress(state) == 0
    server._track_progress(state, {"type": "start", "total": 4, "probe_requests": 10})
    server._track_progress(state, {"type": "detector_done", "index": 0})
    assert server._watch_progress(state) == 25
    server._track_progress(state, {"type": "detector_start", "id": "performance"})
    for _ in range(5):
        server._track_progress(
            state, {"type": "request_done", "record": {"detector": "performance", "endpoint": "target"}}
        )
    assert server._watch_progress(state) == 37  # 1.5 of 4 detectors
    for i in range(4):
        server._track_progress(state, {"type": "detector_done", "index": i})
    assert server._watch_progress(state) == 99  # never 100 while still running


async def test_cancel_stops_a_running_watch_and_keeps_its_last_result(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import server, watches

    started = asyncio.Event()

    async def slow_audit(*_a, **_k):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(server, "run_audit", slow_audit)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "gpt-4o"})
    watches.mark_run(wid, "low", 88.0, 3, ts=1.0, duration_sec=200)
    run = asyncio.create_task(server._run_one_watch(watches.get(wid)))
    await started.wait()
    assert server._cancel_watch(wid) is True
    with pytest.raises(server.WatchCancelled):
        await run
    assert wid not in server._running_watches and server._cancel_watch(wid) is False
    w = watches.get(wid)
    assert w["last_risk"] == "low" and w["last_report_id"] == 3 and w["run_duration_sec"] == 200
    assert w["last_run_ts"] > 1.0


def test_min_interval_rounds_the_run_time_up_to_a_step():
    from ekte.web.server import _min_interval_sec

    assert _min_interval_sec(None) == 300
    assert _min_interval_sec(210) == 300  # 3.5 min -> 5 min
    assert _min_interval_sec(301) == 600
    assert _min_interval_sec(21 * 60) == 30 * 60
    assert _min_interval_sec(61 * 60) == 120 * 60
    assert _min_interval_sec(30 * 3600) == 24 * 3600  # never less often than daily


def test_history_run_time_sets_the_monitors_shortest_interval(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    import json
    from pathlib import Path

    fixture = json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
    detectors = fixture["detectors"]
    for d in detectors:  # a run of 7.5 minutes in all
        d["duration_ms"] = 450_000 / len(detectors)
    rid = _saved_report(detectors=detectors)
    wid = client.post(f"/api/watches/from-history/{rid}").json()["id"]
    [w] = client.get("/api/watches").json()
    assert w["run_duration_sec"] == 450 and w["min_interval_sec"] == 600
    r = client.patch(f"/api/watches/{wid}", json={"interval_sec": 300})
    assert r.status_code == 400 and "at least 600" in r.json()["error"]
    assert client.patch(f"/api/watches/{wid}", json={"interval_sec": 86400 + 60}).status_code == 400
    assert client.patch(f"/api/watches/{wid}", json={"interval_sec": 600, "enabled": True}).status_code == 200


# ----- the scheduler loop ------------------------------------------------- #


def _audit_report(target):
    from ekte.models import AuditReport, RedactedTarget, Verdict

    return AuditReport(
        tool_version="0", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url=target.base_url, model=target.model),
        verdict=Verdict(),
    )


async def _until(cond, timeout: float = 5.0) -> None:
    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not cond():
        assert loop.time() < deadline, "condition not met in time"
        await asyncio.sleep(0.005)


class _GatedAudits:
    """A fake run_audit: records when each audit starts and ends, and holds it
    until its model's release event is set."""

    def __init__(self) -> None:
        import asyncio

        self.started: dict[str, float] = {}
        self.ended: dict[str, float] = {}
        self.calls: list[str] = []
        self.release: dict[str, asyncio.Event] = {}

    def event(self, model: str):
        import asyncio

        return self.release.setdefault(model, asyncio.Event())

    async def __call__(self, target, options, **_):
        import time

        self.calls.append(target.model)
        self.started[target.model] = time.monotonic()
        await self.event(target.model).wait()
        self.ended[target.model] = time.monotonic()
        return _audit_report(target)


async def _scheduler(monkeypatch):
    """Start the scheduler loop with a short tick; returns its task."""
    import asyncio

    from ekte.web import server

    # Many ticks per run: a watch stays due until its run is recorded.
    monkeypatch.setattr(server, "_SCHEDULER_TICK_SEC", 0.01)
    return asyncio.create_task(server._scheduler_loop())


async def _stop(loop_task) -> None:
    import asyncio

    from ekte.web import server

    loop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop_task
    await server._cancel_scheduled_watches()
    # Each task leaves the dict from its done callback, a loop step later.
    await _until(lambda: not server._scheduled_watch_tasks)
    assert not server._running_watches


async def test_due_watches_on_different_relays_run_at_the_same_time(tmp_path, monkeypatch):
    import asyncio

    from ekte.web import server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    audits = _GatedAudits()
    monkeypatch.setattr(server, "run_audit", audits)
    ids = [
        watches.create({"base_url": f"https://relay-{n}.test/v1", "api_key": "sk-x",
                        "model": n, "interval_sec": 3600})
        for n in ("a", "b")
    ]
    loop_task = await _scheduler(monkeypatch)
    try:
        await _until(lambda: len(audits.started) == 2)
        await asyncio.sleep(0.05)  # several more ticks while both are running
        assert sorted(audits.calls) == ["a", "b"]  # neither started twice
        audits.event("a").set()
        audits.event("b").set()
        await _until(lambda: all(watches.get(w)["last_report_id"] for w in ids))
        await _until(lambda: not server._scheduled_watch_tasks)
    finally:
        for ev in audits.release.values():
            ev.set()
        await _stop(loop_task)
    # Overlap: each audit started before the other one ended.
    assert audits.started["a"] < audits.ended["b"] and audits.started["b"] < audits.ended["a"]
    assert sorted(audits.calls) == ["a", "b"]  # recorded, so not due again


async def test_due_watches_on_the_same_relay_run_one_after_another(tmp_path, monkeypatch):
    import asyncio
    import time

    from ekte.web import server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    audits = _GatedAudits()
    monkeypatch.setattr(server, "run_audit", audits)
    ids = [
        watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x",
                        "model": n, "interval_sec": 3600})
        for n in ("a", "b")
    ]
    loop_task = await _scheduler(monkeypatch)
    try:
        await _until(lambda: len(audits.started) == 1)
        first = audits.calls[0]
        second = "b" if first == "a" else "a"
        # Both runs are in flight, the second waiting for the relay.
        await _until(lambda: len(server._running_watches) == 2)
        await asyncio.sleep(0.05)
        assert audits.calls == [first]
        released = time.time()
        audits.event(first).set()
        await _until(lambda: len(audits.started) == 2)
        audits.event(second).set()
        await _until(lambda: all(watches.get(w)["last_report_id"] for w in ids))
    finally:
        for ev in audits.release.values():
            ev.set()
        await _stop(loop_task)
    assert audits.ended[first] <= audits.started[second]
    # The queued run's time is when its audit started, not when it became due,
    # so it does not come due again right after it waited for the relay.
    by_model = {watches.get(w)["model"]: watches.get(w) for w in ids}
    assert by_model[second]["last_run_ts"] >= released
    assert audits.calls == [first, second]


async def test_a_failing_watch_does_not_stop_the_others(tmp_path, monkeypatch):
    from ekte.web import server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    audits = _GatedAudits()

    async def audit(target, options, **kw):
        if target.model == "bad":
            raise RuntimeError("relay down")
        return await audits(target, options, **kw)

    monkeypatch.setattr(server, "run_audit", audit)
    bad = watches.create({"base_url": "https://bad.test/v1", "api_key": "sk-x",
                          "model": "bad", "interval_sec": 3600})
    good = watches.create({"base_url": "https://good.test/v1", "api_key": "sk-x",
                           "model": "good", "interval_sec": 3600})
    audits.event("good").set()
    loop_task = await _scheduler(monkeypatch)
    try:
        await _until(lambda: watches.get(good)["last_report_id"] is not None)
        await _until(lambda: watches.get(bad)["last_run_ts"] is not None)
    finally:
        await _stop(loop_task)


async def test_shutdown_cancels_running_monitors(tmp_path, monkeypatch):
    from ekte.web import server, watches
    from ekte.web.server import create_app

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    audits = _GatedAudits()  # never released: the runs are still going at shutdown
    monkeypatch.setattr(server, "run_audit", audits)
    monkeypatch.setattr(server, "_SCHEDULER_TICK_SEC", 0.01)
    for n in ("a", "b"):
        watches.create({"base_url": f"https://relay-{n}.test/v1", "api_key": "sk-x",
                        "model": n, "interval_sec": 3600})
    async with server._lifespan(create_app()):
        await _until(lambda: len(audits.started) == 2)
        tasks = list(server._scheduled_watch_tasks.values())
        assert len(tasks) == 2
    assert all(t.done() for t in tasks)
    assert not server._running_watches
    await _until(lambda: not server._scheduled_watch_tasks)


async def test_alert_webhooks_are_sent_at_the_same_time(tmp_path, monkeypatch):
    import asyncio

    from ekte import notify
    from ekte.models import RiskLevel
    from ekte.web import server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    async def fake_run_audit(target, options, **_):
        report = _audit_report(target)
        report.verdict.risk_level = RiskLevel.HIGH
        return report

    hooks = [f"https://hooks.test/{i}" for i in range(3)]
    entered: list[str] = []
    all_in = asyncio.Event()

    async def fake_send(url, report_dict, **_):
        entered.append(url)
        if len(entered) == len(hooks):
            all_in.set()
        # Each send waits for all of them: only finishes if they run at once.
        await asyncio.wait_for(all_in.wait(), 2)
        if url.endswith("/1"):
            raise RuntimeError("must not escape")
        return True

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    monkeypatch.setattr(notify, "send", fake_send)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "m",
                          "alert_on": "medium", "webhooks": [*hooks, "  "]})
    await asyncio.wait_for(server._run_one_watch(watches.get(wid)), 5)
    assert sorted(entered) == hooks
    assert watches.get(wid)["last_report_id"] is not None


async def test_regression_check_sees_a_run_that_queued_ahead_on_the_relay(tmp_path, monkeypatch):
    from ekte import notify
    from ekte.models import RiskLevel
    from ekte.web import server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    runs: list[str] = []
    ids: list[int] = []

    async def audit(target, options, **_):
        runs.append(f"run-{len(runs)}")
        name = runs[-1]
        if name == "run-1":
            # A real audit takes minutes: the run ahead is saved meanwhile.
            await _until(lambda: any(watches.get(w)["last_report_id"] for w in ids))
        report = _audit_report(target)
        report.tool_version = name  # tells the two saved reports apart
        report.verdict.risk_level = RiskLevel.HIGH
        return report

    alerts: list[tuple[str, str | None]] = []

    async def fake_send(url, report_dict, *, previous=None, **_):
        alerts.append((report_dict["tool_version"], (previous or {}).get("tool_version")))
        return True

    monkeypatch.setattr(server, "run_audit", audit)
    monkeypatch.setattr(notify, "send", fake_send)
    # Two monitors of one target (say, two suites), due together.
    ids.extend(
        watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "m",
                        "suite": suite, "interval_sec": 3600, "webhooks": ["https://hooks.test/x"]})
        for suite in ("smoke", "standard")
    )
    loop_task = await _scheduler(monkeypatch)
    try:
        await _until(lambda: all(watches.get(w)["last_report_id"] for w in ids))
        await _until(lambda: len(alerts) == 2)
    finally:
        await _stop(loop_task)
    # The second run queued behind the first on the relay, and still compares
    # against it: the previous run is read once its own audit is done.
    assert alerts == [("run-0", None), ("run-1", "run-0")]


async def test_run_now_refuses_a_watch_the_scheduler_just_started(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from ekte.web import server, watches
    from ekte.web.server import create_app

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    audits = _GatedAudits()
    monkeypatch.setattr(server, "run_audit", audits)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "m",
                          "interval_sec": 3600})
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        # Started by the scheduler, but its task has not taken a step yet.
        server._start_scheduled_watch(watches.get(wid))
        assert wid not in server._running_watches
        task = server._scheduled_watch_tasks[wid]
        r = await ac.post(f"/api/watches/{wid}/run")
        assert r.status_code == 409
        audits.event("m").set()
        await asyncio.wait_for(task, 5)
    assert audits.calls == ["m"]
    assert watches.get(wid)["last_report_id"] is not None
