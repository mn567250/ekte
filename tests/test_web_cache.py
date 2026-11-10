"""Data version, response cache (LRU, single-flight, ETag / 304) and the
reused read-only connections (ekte.web.cache, ekte.datadir.read_connection)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams
from starlette.requests import Request

from ekte import datadir, dbmigrate
from ekte.web import analytics_store, analytics_widgets, cache, history

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


def _report(i: int = 0) -> dict:
    return {"generated_at": f"2026-03-0{1 + i % 9}T12:00:00+00:00",
            "target": {"base_url": "https://relay.example/v1", "claimed_model": "m", "model": "m"},
            "verdict": {"risk_level": "clean", "overall_score": 80.0 + i}}


def _raw_bump(db: Path) -> None:
    """A write the server module does not see: another connection, as a CLI
    process would make it."""
    with sqlite3.connect(db) as c:
        c.execute(history._BUMP_SQL)


# --------------------------------------------------------------------------- #
# Data version
# --------------------------------------------------------------------------- #
def test_data_version_moves_with_every_write(data):
    history.init()
    v0 = history.data_version()
    rid = history.save(_report())
    v1 = history.data_version()
    assert rid > 0 and v1 > v0
    history.delete(rid)
    v2 = history.data_version()
    assert v2 > v1
    history.delete(rid)  # nothing deleted: nothing changed
    assert history.data_version() == v2
    history.save(_report(1))
    v3 = history.data_version()
    history.clear()
    assert history.data_version() > v3 > v2


def test_data_version_is_bumped_by_the_backfill(data):
    history.save(_report())
    db = data / "history.db"
    with sqlite3.connect(db) as c:  # as an older ekte would leave the row
        c.execute("UPDATE history SET requests_split = NULL")
        c.execute("DELETE FROM history_metrics")
    v = history.data_version()
    history.backfill_analytics()
    assert history.data_version() > v
    # nothing left to do: no write, no bump
    v = history.data_version()
    history.backfill_analytics()
    history.recent(perf=True)
    assert history.data_version() == v


def test_meta_migration_adds_the_counter_to_an_older_database(data):
    db = data / "history.db"
    with sqlite3.connect(db) as c:
        for m in history.MIGRATIONS[:7]:
            m.apply(c)
        c.execute("PRAGMA user_version = 7")
    history.init()
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == history._SCHEMA_VERSION
    assert history.data_version() == 0
    # idempotent: a meta table made by another step (with typed values) is reused
    with sqlite3.connect(db) as c:
        history._v8(c)
        c.execute(history._BUMP_SQL)
    assert history.data_version() == 1


def test_a_write_from_another_process_changes_the_version(data):
    history.init()
    v = history.data_version()
    code = ("import sys; from ekte.web import history; "
            "sys.exit(0 if history.save({'target': {'base_url': 'https://x/v1'}}) > 0 else 1)")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=_ROOT,
                   env={**os.environ, "EKTE_DATA_DIR": str(data)}, timeout=120)
    assert history.data_version() > v


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #
def test_canonical_params():
    q = QueryParams([("to", " b "), ("keys", "x"), ("from", ""), ("keys", "a"), ("api", "  ")])
    assert cache.canonical_params(q) == [("keys", "x"), ("keys", "a"), ("to", "b")]
    assert cache.canonical_params({"b": "1", "a": ["2", None, ""]}) == [("a", "2"), ("b", "1")]


def test_the_key_has_no_time_component(data, monkeypatch):
    history.init()
    key = cache.cache_key("e", [("a", "1")])
    assert json.loads(key) == ["e", [["a", "1"]], history.data_version(), cache.kb_version(),
                               analytics_store.EXTRACT_VERSION, str(history._db_path())]
    monkeypatch.setattr(time, "time", lambda: 4e9)
    assert cache.cache_key("e", [("a", "1")]) == key
    _raw_bump(data / "history.db")
    assert cache.cache_key("e", [("a", "1")]) != key


def test_etag_matching():
    tag = cache.etag_of("k")
    assert tag.startswith('"') and tag != cache.etag_of("k2")
    assert cache.etag_matches(tag, tag) and cache.etag_matches(f'"x", W/{tag}', tag)
    assert cache.etag_matches("*", tag)
    assert not cache.etag_matches(None, tag) and not cache.etag_matches('"x"', tag)


# --------------------------------------------------------------------------- #
# ResponseCache
# --------------------------------------------------------------------------- #
def test_lru_evicts_the_least_recently_used():
    c = cache.ResponseCache(maxsize=2)
    c.get_or_compute("a", lambda: 1)
    c.get_or_compute("b", lambda: 2)
    assert c.get_or_compute("a", lambda: 0) == 1  # a is now the most recent
    c.get_or_compute("c", lambda: 3)
    assert len(c) == 2
    assert c.get_or_compute("b", lambda: 20) == 20  # b was dropped
    with pytest.raises(ValueError):
        cache.ResponseCache(maxsize=0)


def test_errors_are_not_cached():
    c = cache.ResponseCache()
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("no")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            c.get_or_compute("k", boom)
    assert len(calls) == 2 and len(c) == 0
    assert c.get_or_compute("k", lambda: 5) == 5


def test_single_flight_shares_one_computation_and_its_error():
    c = cache.ResponseCache()
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow():
        calls.append(1)
        started.set()
        release.wait(10)
        raise KeyError("shared")

    errors = []

    def call():
        try:
            c.get_or_compute("k", slow)
        except KeyError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(5)]
    threads[0].start()
    assert started.wait(10)
    for t in threads[1:]:
        t.start()
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(10)
    assert len(calls) == 1 and len(errors) == 5


# --------------------------------------------------------------------------- #
# cached_endpoint
# --------------------------------------------------------------------------- #
def _request(query: str = "", etag: str | None = None) -> Request:
    headers = [(b"if-none-match", etag.encode())] if etag else []
    return Request({"type": "http", "method": "GET", "path": "/x", "query_string": query.encode(),
                    "headers": headers})


def test_ten_concurrent_identical_requests_compute_once(data):
    history.init()
    calls = []
    gate = threading.Barrier(10)

    @cache.cached_endpoint("test.concurrent", cache=cache.ResponseCache())
    def handler(params):
        calls.append(dict(params))
        time.sleep(0.2)  # every other request arrives while this one computes
        return {"n": params.get("n")}

    out = []

    def call():
        gate.wait(10)
        out.append(handler(_request("n=1")))

    threads = [threading.Thread(target=call) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert len(calls) == 1 and len(out) == 10
    assert {r.body for r in out} == {b'{"n":"1"}'} and len({r.headers["etag"] for r in out}) == 1


def test_handler_errors_answer_400_uncached(data):
    history.init()
    calls = []

    @cache.cached_endpoint("test.errors", cache=cache.ResponseCache(), errors=(ValueError,))
    def handler(params):
        calls.append(1)
        raise ValueError("bad n")

    for _ in range(2):
        r = handler(_request("n=x"))
        assert r.status_code == 400 and json.loads(r.body) == {"error": "bad n"}
        assert "etag" not in r.headers
    assert len(calls) == 2


def test_prepare_resolves_before_keying(data):
    history.init()
    seen = []

    @cache.cached_endpoint("test.prepare", cache=cache.ResponseCache(),
                           prepare=lambda p: [*p.multi_items(), ("to", "fixed")])
    def handler(params):
        seen.append(params.get("to"))
        return {}

    handler(_request("from=a"))
    handler(_request("from=a"))
    assert seen == ["fixed"]


# --------------------------------------------------------------------------- #
# Analytics over HTTP
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(data):
    from ekte.web.server import create_app

    cache.default_cache.clear()
    history.save(_report())
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture
def counted(monkeypatch):
    calls: list[dict] = []
    real = analytics_widgets.filter_options

    def options(params):
        calls.append(dict(params))
        return real(params)

    monkeypatch.setattr(analytics_widgets, "filter_options", options)
    return calls


def test_a_write_by_another_connection_misses_the_cache(client, counted, data):
    first = client.get("/api/filters/options")
    again = client.get("/api/filters/options")
    assert first.status_code == again.status_code == 200 and len(counted) == 1
    assert first.json()["runs"] == 1
    # a run saved outside this process's history module
    with sqlite3.connect(data / "history.db") as c:
        c.execute("DELETE FROM history_metrics")
        c.execute("DELETE FROM history")
        c.execute(history._BUMP_SQL)
    after = client.get("/api/filters/options")
    assert len(counted) == 2 and after.json()["runs"] == 0
    assert after.headers["etag"] != first.headers["etag"]


def test_if_none_match_answers_304_until_a_write(client, counted):
    r = client.get("/api/filters/options")
    etag = r.headers["etag"]
    assert r.headers["cache-control"] == "no-cache"
    counted.clear()
    cache.default_cache.clear()  # 304 must not even need the cached answer
    r = client.get("/api/filters/options", headers={"If-None-Match": etag})
    assert r.status_code == 304 and r.headers["etag"] == etag and not r.content
    assert counted == []
    history.save(_report(1))
    r = client.get("/api/filters/options", headers={"If-None-Match": etag})
    assert r.status_code == 200 and r.headers["etag"] != etag and r.json()["runs"] == 2
    assert len(counted) == 1


def test_parameters_are_keyed_canonically(client, counted):
    client.get("/api/filters/options", params=[("surface", "chat"), ("from", "")])
    client.get("/api/filters/options", params=[("surface", " chat ")])
    assert len(counted) == 1
    client.get("/api/filters/options", params=[("surface", "embedding")])
    assert len(counted) == 2


def test_summary_from_alone_is_resolved_to_an_absolute_range(client, monkeypatch):
    seen = []
    real = analytics_widgets.widget_summary
    monkeypatch.setattr(analytics_widgets, "widget_summary", lambda p: seen.append(dict(p)) or real(p))
    r = client.get("/api/analytics/summary", params={"from": "2026-01-01T00:00:00+00:00"})
    assert r.status_code == 200 and seen[0]["to"] == r.json()["to"]
    assert analytics_store.parse_ts(seen[0]["to"]) is not None


# --------------------------------------------------------------------------- #
# Read connections
# --------------------------------------------------------------------------- #
def test_read_connection_is_reused_per_thread_and_read_only(data):
    a = datadir.read_connection("history.db", history.MIGRATIONS)
    assert datadir.read_connection("history.db", history.MIGRATIONS) is a
    other: list[sqlite3.Connection] = []
    t = threading.Thread(target=lambda: other.append(
        datadir.read_connection("history.db", history.MIGRATIONS)))
    t.start()
    t.join(10)
    assert other and other[0] is not a
    assert a.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        a.execute("DELETE FROM history")
    assert a.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    # sees what another connection commits
    history.save(_report())
    assert a.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1


def test_read_connection_checks_the_schema_once(data, monkeypatch):
    calls = []
    real = dbmigrate.migrate
    monkeypatch.setattr(dbmigrate, "migrate", lambda *a: calls.append(1) or real(*a))
    datadir.read_connection("history.db", history.MIGRATIONS)
    datadir.read_connection("history.db", history.MIGRATIONS)
    t = threading.Thread(target=lambda: datadir.read_connection("history.db", history.MIGRATIONS))
    t.start()
    t.join(10)
    assert len(calls) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot delete or replace a file that a "
                    "connection holds open, so a replaced file cannot occur there")
def test_read_connection_reopens_a_replaced_file(data):
    history.save(_report())
    conn = datadir.read_connection("history.db", history.MIGRATIONS)
    assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1
    for suffix in ("", "-wal", "-shm"):
        (data / f"history.db{suffix}").unlink(missing_ok=True)
    fresh = datadir.read_connection("history.db", history.MIGRATIONS)  # migrated afresh
    assert fresh is not conn and fresh.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0


def test_close_read_connections(data):
    conn = datadir.read_connection("history.db", history.MIGRATIONS)
    datadir.close_read_connections()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    assert datadir.read_connection("history.db", history.MIGRATIONS).execute("SELECT 1")


def test_a_knowledge_base_change_changes_the_key(data, monkeypatch):
    from ekte.knowledge import relays

    history.init()
    assert cache.kb_version() == relays.kb_version()
    key = cache.cache_key("e", [])
    monkeypatch.setattr(relays, "kb_version", lambda: "other")
    assert cache.cache_key("e", []) != key
    monkeypatch.setattr(relays, "kb_version", lambda: 1 / 0)
    assert cache.kb_version() == ""
