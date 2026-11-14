"""The change signal ``GET /api/version`` ({data, live}) and the persisted
watches data version (ekte.web.server.version_tokens, ekte.web.watches.data_version,
ekte.web.jobs.live_version)."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte import datadir  # noqa: E402
from ekte.web import history, jobs, server, watches  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(data):
    return TestClient(server.create_app(), base_url="http://localhost")


def _tokens(client) -> dict:
    r = client.get("/api/version")
    assert r.status_code == 200
    return r.json()


def _watch(**extra) -> int:
    return watches.create({"base_url": "https://relay.test/v1", "api_key": "env:EKTE_TEST_KEY",
                           "model": "gpt-4o", **extra})


# --------------------------------------------------------------------------- #
# The endpoint
# --------------------------------------------------------------------------- #
def test_answers_two_opaque_tokens_with_an_etag(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"data", "live"}
    assert all(isinstance(v, str) and v for v in body.values())
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["etag"].startswith('"')
    # unchanged state: the same answer
    again = client.get("/api/version")
    assert again.json() == body and again.headers["etag"] == r.headers["etag"]


def test_a_matching_if_none_match_gets_304_until_something_changes(client):
    r = client.get("/api/version")
    etag = r.headers["etag"]
    not_modified = client.get("/api/version", headers={"If-None-Match": etag})
    assert not_modified.status_code == 304 and not_modified.content == b""
    assert not_modified.headers["etag"] == etag
    assert not_modified.headers["cache-control"] == "no-cache"
    assert client.get("/api/version", headers={"If-None-Match": f'W/{etag}'}).status_code == 304
    assert client.get("/api/version", headers={"If-None-Match": '"other"'}).status_code == 200
    history.save({"target": {"base_url": "https://x/v1"}})
    changed = client.get("/api/version", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag


def test_the_endpoint_is_listed_in_the_server_docstring_and_the_docs():
    assert "GET  /api/version" in (server.__doc__ or "")
    assert "/api/version" in (_ROOT / "docs" / "dev" / "web-server.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def test_a_run_saved_by_another_process_changes_data_only(client, data):
    history.init()
    before = _tokens(client)
    code = ("import sys; from ekte.web import history; "
            "sys.exit(0 if history.save({'target': {'base_url': 'https://x/v1'}}) > 0 else 1)")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=_ROOT,
                   env={**os.environ, "EKTE_DATA_DIR": str(data)}, timeout=120)
    after = _tokens(client)
    assert after["data"] != before["data"]
    assert after["live"] == before["live"]


def test_data_follows_the_widget_cache_key_inputs(client, monkeypatch):
    from ekte.web import analytics_store, cache

    before = _tokens(client)
    monkeypatch.setattr(cache, "kb_version", lambda: "another knowledge base")
    kb = _tokens(client)
    assert kb["data"] != before["data"] and kb["live"] == before["live"]
    monkeypatch.setattr(analytics_store, "EXTRACT_VERSION", analytics_store.EXTRACT_VERSION + 1)
    assert _tokens(client)["data"] != kb["data"]


# --------------------------------------------------------------------------- #
# live: monitor settings
# --------------------------------------------------------------------------- #
def test_creating_editing_enabling_disabling_and_deleting_a_monitor_change_live(client):
    seen = [_tokens(client)["live"]]

    def changed() -> None:
        now = _tokens(client)["live"]
        assert now not in seen
        seen.append(now)

    r = client.post("/api/watches", json={"name": "m", "base_url": "https://relay.test/v1",
                                          "api_key": "env:EKTE_TEST_KEY", "model": "gpt-4o",
                                          "interval_sec": 3600})
    assert r.status_code == 201
    wid = r.json()["id"]
    changed()
    assert client.patch(f"/api/watches/{wid}", json={"interval_sec": 7200}).status_code == 200
    changed()
    assert client.patch(f"/api/watches/{wid}", json={"enabled": False}).status_code == 200
    changed()
    assert client.patch(f"/api/watches/{wid}", json={"enabled": True}).status_code == 200
    changed()
    assert client.delete(f"/api/watches/{wid}").status_code == 200
    changed()
    # reading changes nothing
    client.get("/api/watches")
    assert _tokens(client)["live"] == seen[-1]


def test_every_store_write_bumps_the_watches_data_version(data):
    seen = [watches.data_version()]

    def bumped() -> None:
        now = watches.data_version()
        assert now > seen[-1]
        seen.append(now)

    wid = _watch()
    bumped()
    watches.update(wid, alert_on="high")
    bumped()
    watches.update(wid)  # nothing to change: no write
    assert watches.data_version() == seen[-1]
    watches.set_enabled(wid, False)
    bumped()
    watches.set_language(wid, "zh")
    bumped()
    watches.pin(wid, None)
    bumped()
    watches.mark_run(wid, "low", 90.0, 1, 1.0)
    bumped()
    watches.mark_attempt(wid, 2.0)
    bumped()
    watches.delete(wid)
    bumped()
    # reads do not bump
    watches.list_all()
    watches.get(wid)
    watches.due(0)
    assert watches.data_version() == seen[-1]


def test_key_storage_changes_bump_the_watches_data_version(data):
    from ekte import secretbox

    box = secretbox.SecretBox([secretbox.generate_key()], "test")
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-plain",
                          "model": "gpt-4o"}, key_storage=watches.STORAGE_MEMORY)
    v = watches.data_version()
    assert watches.keys_to_store(box) == 1
    assert watches.data_version() > v
    v = watches.data_version()
    watches.adopt_key(box, opener=box)
    assert watches.data_version() > v
    v = watches.data_version()
    watches.keys_to_memory(box)
    assert watches.data_version() > v
    # a plain-text key from an older version, encrypted
    with sqlite3.connect(datadir.db_path("watches.db")) as c:
        c.execute("UPDATE watches SET api_key = 'sk-plain' WHERE id = ?", (wid,))
    v = watches.data_version()
    assert watches.migrate_keys(box) == 1
    assert watches.data_version() > v
    v = watches.data_version()
    watches.forget_keys()
    assert watches.data_version() > v


def test_the_watches_data_version_sees_writes_from_another_process(data):
    watches.init()
    v = watches.data_version()
    code = ("from ekte.web import watches; "
            "watches.create({'base_url': 'https://relay.test/v1', 'model': 'm'})")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=_ROOT,
                   env={**os.environ, "EKTE_DATA_DIR": str(data)}, timeout=120)
    assert watches.data_version() > v


def test_the_meta_migration_adds_the_counter_to_an_older_store(data):
    db = data / "watches.db"
    with sqlite3.connect(db) as c:
        for m in watches.MIGRATIONS[:4]:
            m.apply(c)
        c.execute("PRAGMA user_version = 4")
        c.execute("INSERT INTO watches (name) VALUES ('old')")
    assert watches.data_version() == 0
    assert [w["name"] for w in watches.list_all()] == ["old"]
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == len(watches.MIGRATIONS)
        watches._v5(c)  # idempotent
    _watch()
    assert watches.data_version() == 1


# --------------------------------------------------------------------------- #
# live: jobs and monitor runs
# --------------------------------------------------------------------------- #
def _live() -> str:
    return server.version_tokens()[1]


async def _until(cond, timeout: float = 30.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not cond():
        assert loop.time() < deadline, "condition not met in time"
        await asyncio.sleep(0.005)


async def test_a_monitor_run_changes_live_when_it_starts_and_when_it_ends(data, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def audit(target, *_a, **_k):
        from tests.test_watches import _audit_report

        started.set()
        await release.wait()
        return _audit_report(target)

    monkeypatch.setattr(server, "run_audit", audit)
    monkeypatch.setattr(history, "save", lambda *_a, **_k: 7)
    wid = _watch()
    before = _live()
    run = asyncio.create_task(server._run_one_watch(watches.get(wid)))
    await started.wait()
    running = _live()
    assert running != before
    release.set()
    await run
    ended = _live()
    assert ended not in (before, running)
    assert watches.get(wid)["last_report_id"] == 7


async def test_a_cancelled_and_a_failed_monitor_run_change_live(data, monkeypatch):
    started = asyncio.Event()
    fail = False

    async def audit(*_a, **_k):
        started.set()
        if fail:
            raise RuntimeError("boom")
        await asyncio.sleep(60)

    monkeypatch.setattr(server, "run_audit", audit)
    wid = _watch()
    before = _live()
    run = asyncio.create_task(server._run_one_watch(watches.get(wid)))
    await started.wait()
    running = _live()
    assert running != before
    assert server._cancel_watch(wid) is True
    with pytest.raises(server.WatchCancelled):
        await run
    cancelled = _live()
    assert cancelled not in (before, running)

    # the live counter alone moves on start and end (the watches data version
    # moves only when the run is recorded)
    fail = True
    started.clear()
    n = jobs.live_version()
    with pytest.raises(RuntimeError):
        await server._run_one_watch(watches.get(wid))
    assert jobs.live_version() >= n + 2
    assert _live() != cancelled


async def test_an_audit_job_changes_live_when_queued_started_and_ended(data):
    release = asyncio.Event()

    async def run(emit):
        await release.wait()
        raise RuntimeError("the audit failed")

    manager = jobs.JobManager(jobs.RelayGate())
    v0 = jobs.live_version()
    job = manager.submit({"base_url": "https://relay.test/v1"}, ["https://relay.test/v1"], run)
    assert jobs.live_version() > v0  # queued
    await _until(lambda: job.status == "running")
    v1 = jobs.live_version()
    assert v1 > v0 + 1  # running
    release.set()
    await _until(lambda: job.finished is not None)
    assert job.status == "error" and jobs.live_version() > v1

    # a cancelled job ends with a change too
    blocked = asyncio.Event()

    async def wait_forever(emit):
        await blocked.wait()
        return {}

    job = manager.submit({}, ["https://relay.test/v1"], wait_forever)
    await _until(lambda: job.status == "running")
    v2 = jobs.live_version()
    assert manager.cancel(job.id)
    await _until(lambda: job.finished is not None)
    assert job.status == "cancelled" and jobs.live_version() > v2


def test_the_live_token_differs_between_server_processes(data, monkeypatch):
    live = _live()
    monkeypatch.setattr(server, "_BOOT_ID", "another process")
    assert _live() != live


def test_locking_the_master_key_changes_live(client, monkeypatch):
    from ekte.web import masterkey

    before = _tokens(client)["live"]
    monkeypatch.setattr(masterkey.vault, "lock", lambda: {"state": "locked"})
    assert client.post("/api/secret/lock").status_code == 200
    assert _tokens(client)["live"] != before


# --------------------------------------------------------------------------- #
# Cheap: no table scanned
# --------------------------------------------------------------------------- #
def _plan(conn: sqlite3.Connection, sql: str) -> str:
    return "\n".join(str(r[3]) for r in conn.execute("EXPLAIN QUERY PLAN " + sql))


def test_the_version_reads_scan_no_table(data):
    history.init()
    watches.init()
    traced: dict[str, list[str]] = {"history.db": [], "watches.db": []}
    for name, migrations in (("history.db", history.MIGRATIONS), ("watches.db", watches.MIGRATIONS)):
        datadir.read_connection(name, migrations).set_trace_callback(traced[name].append)
    server.version_tokens()
    for name in traced:
        assert traced[name], f"no statement on {name}"
        with sqlite3.connect(datadir.db_path(name)) as c:
            for sql in traced[name]:
                plan = _plan(c, sql)
                assert "SCAN" not in plan, (name, sql, plan)
                assert "SEARCH meta USING INDEX" in plan, (name, sql, plan)


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_benchmark_version_under_budget(bench_data):
    """``/api/version``'s work (the handler's ``version_tokens``, its ETag and
    JSON body) answers in under 5 ms p95 on the 20k-run fixture with its 200
    monitors. Opt-in (EKTE_BENCH=1); EKTE_BENCH_VERSION_BUDGET_MS overrides 5,
    EKTE_BENCH_REPORT collects the timings (tests/bench_report.py)."""
    import json

    from ekte.web import cache
    from tests import bench_report

    budget = bench_report.budget(5, "EKTE_BENCH_VERSION_BUDGET_MS")
    assert len(watches.list_all()) >= 200

    def answer() -> None:
        data_token, live_token = server.version_tokens()
        cache.etag_of(f"{data_token}:{live_token}")
        json.dumps({"data": data_token, "live": live_token})

    cases = {
        "version": answer,
        "version: data": lambda: (history.data_version(), cache.kb_version()),
        "version: live": watches.data_version,
    }
    results = {name: bench_report.measure(fn) for name, fn in cases.items()}
    bench_report.record("web_version", results, budget)
    slow = {name: round(p95, 2) for name, (_, p95) in results.items() if p95 >= budget}
    assert not slow, f"p95 over {budget} ms: {slow}"
