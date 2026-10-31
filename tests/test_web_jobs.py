"""Background audit jobs: the relay gate, queuing, replay and the /api/jobs endpoints."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web import jobs  # noqa: E402
from ekte.web.server import create_app  # noqa: E402


async def _until(cond, timeout: float = 5.0) -> None:
    """Wait for ``cond()``: history and watch-store calls hop to a worker thread."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not cond():
        assert loop.time() < deadline, "condition not met in time"
        await asyncio.sleep(0.005)


def test_relay_key_is_the_host_and_folds_loopback():
    assert jobs.relay_key("https://Relay.Example.com:8443/v1") == "relay.example.com"
    assert jobs.relay_key("http://relay.example.com/v1") == "relay.example.com"
    # every local model server is one machine (usually one GPU)
    for url in ("http://localhost:11434/v1", "http://127.0.0.1:8080", "http://[::1]:1234/v1"):
        assert jobs.relay_key(url) == "localhost"
    assert jobs.relay_key("https://a.example/v1") != jobs.relay_key("https://b.example/v1")


async def test_gate_serializes_one_relay_and_parallelizes_others():
    gate = jobs.RelayGate(limit=4)
    log: list[str] = []

    async def audit(name: str, key: str, hold: asyncio.Event) -> None:
        async with gate.hold([key], label=name):
            log.append(f"+{name}")
            await hold.wait()
            log.append(f"-{name}")

    a, b, c = asyncio.Event(), asyncio.Event(), asyncio.Event()
    ta = asyncio.create_task(audit("a", "r1", a))
    tb = asyncio.create_task(audit("b", "r1", b))  # same relay: waits for a
    tc = asyncio.create_task(audit("c", "r2", c))  # other relay: runs now
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert log == ["+a", "+c"]
    assert gate.busy_with(["r1", "r3"]) == ["r1"]
    a.set()
    await ta
    await asyncio.sleep(0)
    assert log == ["+a", "+c", "-a", "+b"]
    b.set()
    c.set()
    await asyncio.gather(tb, tc)
    assert not gate.busy_with(["r1", "r2"])


async def test_gate_keeps_arrival_order_and_respects_the_limit():
    gate = jobs.RelayGate(limit=1)
    order: list[str] = []
    release = asyncio.Event()

    async def audit(name: str, key: str) -> None:
        async with gate.hold([key], label=name):
            order.append(name)
            if name == "first":
                await release.wait()

    tasks = [asyncio.create_task(audit("first", "r1"))]
    await asyncio.sleep(0)
    tasks += [asyncio.create_task(audit(n, k)) for n, k in (("second", "r2"), ("third", "r1"))]
    await asyncio.sleep(0)
    assert order == ["first"]  # limit 1: r2 waits for the slot too
    release.set()
    await asyncio.gather(*tasks)
    assert order == ["first", "second", "third"]


async def test_cancelling_a_waiter_frees_its_place():
    gate = jobs.RelayGate(limit=4)
    hold = asyncio.Event()

    async def audit(key: str) -> None:
        async with gate.hold([key]):
            await hold.wait()

    first = asyncio.create_task(audit("r1"))
    await asyncio.sleep(0)
    waiter = asyncio.create_task(audit("r1"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    hold.set()
    await first
    assert not gate.busy_with(["r1"]) and gate.would_wait(["r1"]) is False


async def test_jobs_queue_per_relay_and_replay_their_log(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    mgr = jobs.JobManager(jobs.RelayGate(limit=4))
    gates = {"a": asyncio.Event(), "b": asyncio.Event()}

    def runner(name: str):
        async def run(emit):
            emit({"type": "start", "total": 2, "probe_requests": 0})
            emit({"type": "detector_done", "id": "x", "index": 0})
            await gates[name].wait()
            return {"verdict": {}, "target": {"base_url": "https://r.example/v1"}, "name": name}

        return run

    a = mgr.submit({"base_url": "https://r.example/v1"}, ["https://r.example/v1"], runner("a"))
    b = mgr.submit({"base_url": "https://r.example/v2"}, ["https://r.example/v2"], runner("b"))
    await asyncio.sleep(0.01)
    assert a.status == "running" and a.info()["progress"] == 50
    assert b.status == "queued" and b.info()["waiting_for"] == ["r.example"]
    assert [e["type"] for e in b.events] == ["queued"]

    gates["a"].set()
    await _until(lambda: a.status == "done")
    assert a.report_id is not None
    await _until(lambda: b.status == "running")  # the relay is free once a is saved

    # a late subscriber gets the whole log, then the live tail
    chunks: list[str] = []

    async def follow() -> None:
        async for chunk in jobs.stream(b, 0.01):
            chunks.append(chunk)

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.01)
    gates["b"].set()
    await follower
    types = [json.loads(c[5:])["type"] for c in chunks]
    assert types == ["queued", "running", "start", "detector_done", "report", "done"]
    assert [j.id for j in mgr.list()] == [a.id, b.id]


async def test_cancel_stops_queued_and_running_jobs():
    mgr = jobs.JobManager(jobs.RelayGate(limit=4))
    forever = asyncio.Event()

    async def run(emit):
        await forever.wait()
        return {}

    a = mgr.submit({}, ["https://r.example"], run)
    b = mgr.submit({}, ["https://r.example"], run)
    await asyncio.sleep(0)
    assert mgr.cancel(b.id) and mgr.cancel(a.id)
    await asyncio.sleep(0.01)
    assert a.status == b.status == "cancelled"
    assert [e["type"] for e in a.events][-2:] == ["cancelled", "done"]
    assert not mgr.cancel(a.id)
    # nothing left holding the relay
    assert not mgr.gate.would_wait(["r.example"])


def _fake_report(target):
    from ekte.models import AuditReport, RedactedTarget, Verdict

    return AuditReport(
        tool_version="0", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url=target.base_url, model="m"),
        verdict=Verdict(),
    )


def test_jobs_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    async def fake_run_audit(target, options, *, on_event=None, **_):
        on_event({"type": "start", "total": 1, "probe_requests": 0})
        on_event({"type": "detector_done", "id": "x", "index": 0})
        return _fake_report(target)

    monkeypatch.setattr("ekte.web.server.run_audit", fake_run_audit)
    # One event loop for every request (as under uvicorn): the job runs on in
    # the background, its history save in a worker thread.
    with TestClient(create_app(), base_url="http://localhost") as client:
        bad = client.post("/api/jobs", json={"base_url": "", "model": ""})
        assert bad.status_code == 400 and bad.json()["error"]

        created = client.post(
            "/api/jobs",
            json={"base_url": "https://x.example/v1", "model": "m", "api_key": "sk-secret"},
        )
        assert created.status_code == 200
        job = created.json()
        assert job["base_url"] == "https://x.example/v1" and "sk-secret" not in created.text

        r = client.get(f"/api/jobs/{job['id']}/events")
        events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
        types = [e["type"] for e in events]
        assert types[-2:] == ["report", "done"] and "start" in types
        report_id = events[-2]["report_id"]
        assert client.get(f"/api/history/{report_id}").status_code == 200

        listed = client.get("/api/jobs").json()
        mine = [j for j in listed["jobs"] if j["id"] == job["id"]]
        assert mine and mine[0]["status"] == "done" and mine[0]["report_id"] == report_id
        assert listed["max_parallel"] >= 1
        assert "sk-secret" not in json.dumps(listed)

        assert client.get("/api/jobs/nope").status_code == 404
        assert client.get("/api/jobs/nope/events").status_code == 404
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


def test_running_monitors_are_listed_as_jobs():
    from ekte.web import server

    server._running_watches[4242] = {
        "base_url": "https://m.example/v1", "model": "m", "claimed_model": "m",
        "suite": "standard", "started": True, "total": 4, "done": 2, "since": 1.0,
    }
    try:
        client = TestClient(create_app(), base_url="http://localhost")
        rows = client.get("/api/jobs").json()["jobs"]
        mon = [r for r in rows if r["id"] == "monitor-4242"][0]
        assert mon["kind"] == "monitor" and mon["status"] == "running" and mon["progress"] == 50
    finally:
        server._running_watches.pop(4242, None)


async def test_a_monitor_waits_for_an_audit_of_its_relay(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import server, watches

    started = asyncio.Event()

    async def audit(*_a, **_k):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(server, "run_audit", audit)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "m"})
    release = asyncio.Event()

    async def other_audit() -> None:
        async with jobs.gate.hold(["relay.test"], label="job"):
            await release.wait()

    holder = asyncio.create_task(other_audit())
    await asyncio.sleep(0)
    run = asyncio.create_task(server._run_one_watch(watches.get(wid)))
    await _until(lambda: "waiting_for" in server._running_watches.get(wid, {}))
    state = server._running_watches[wid]
    assert not started.is_set() and not state.get("started")
    assert state["waiting_for"] == ["relay.test"]
    release.set()
    await holder
    await asyncio.wait_for(started.wait(), 1)
    assert state["started"]
    assert server._cancel_watch(wid)
    with pytest.raises(server.WatchCancelled):
        await run
    assert not jobs.gate.busy_with(["relay.test"])


def test_v2_pages_use_background_jobs():
    client = TestClient(create_app(), base_url="http://localhost")
    audit = client.get("/").text
    assert 'fetch("/api/jobs"' in audit and "/events" in audit and 'id="bg"' in audit
    assert "/api/audit/stream" not in audit  # the v2 audit outlives the page
    # the Running tab lists background audits (v2/jobs.js) and links back here
    assert 'id="tab-running"' in audit and 'class="jlist" id="jobs"' in audit and "/static/jobs.js" in audit
    shared = client.get("/static/jobs.js").text
    assert 'fetch("/api/jobs")' in shared and "/?job=" in shared


async def test_shutdown_stops_every_job():
    mgr = jobs.JobManager(jobs.RelayGate(limit=4))

    async def run(emit):
        await asyncio.sleep(60)
        return {}

    a = mgr.submit({}, ["https://r.example"], run)
    b = mgr.submit({}, ["https://r.example"], run)
    await asyncio.sleep(0)
    await mgr.shutdown()
    assert a.status == b.status == "cancelled"
    assert not mgr.gate.would_wait(["r.example"])


def test_detector_start_is_stamped_and_replayed_with_its_start_time():
    # a page re-attaching mid-check times the running check from "at"
    job = jobs.Job({}, frozenset())
    job.started = 1000.0
    job.emit({"type": "detector_start", "id": "x", "index": 0, "total": 1})
    job.emit({"type": "detector_done", "id": "x", "index": 0})
    at = job.events[0]["at"]
    assert isinstance(at, float) and at >= job.started
    assert "at" not in job.events[1]
    q = job.subscribe()
    assert q.get_nowait()["at"] == at
    # an explicit time is kept
    job.emit({"type": "detector_start", "id": "y", "at": 5.0})
    assert job.events[-1]["at"] == 5.0
