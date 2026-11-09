"""History store: the list's performance headline (from history_metrics), the
duplicate headline columns dropped by step 13, one-time schema check and
backfill."""

from __future__ import annotations

import json
import sqlite3

import pytest

from ekte.web import analytics_store, history

_TARGET = {"base_url": "https://x/v1", "claimed_model": "m", "model": "m"}

# Report shapes the headline must survive: none, full, reported-only decode,
# empty/odd performance blocks, integer and non-numeric p50 values.
_PERFS = [
    None,
    {"target": {"latency_ms": {"p50": 900.5}, "ttft_ms": {"p50": 310}, "decode_tps_local": {"p50": 60.25}}},
    {"target": {"latency_ms": {"p50": 800}, "decode_tps_reported": {"p50": 42.5}}},
    {"target": {"decode_tps_local": {"p50": None}, "decode_tps_reported": {"p50": 7}}},
    {"target": None},
    {"target": {"latency_ms": {"p50": "bad"}, "ttft_ms": {}, "decode_tps_local": 3}},
    {},
    "not a dict",
    {"target": {"latency_ms": {"p50": True}, "ttft_ms": {"p50": 1e-9}}},
]

_OLD_SCHEMA = (
    "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, base_url TEXT,"
    " claimed_model TEXT, model TEXT, mode TEXT, suite TEXT, risk_level TEXT, score REAL,"
    " rating TEXT, report_json TEXT, kb_snapshot_id INTEGER, kb_match TEXT, watch_id INTEGER,"
    " api TEXT, api_auto INTEGER, stream_mode TEXT)"
)
# The headline columns ekte 0.34 kept on history (dropped by step 13).
_DROPPED = ("latency_p50_ms", "ttft_p50_ms", "decode_tps_p50", "perf_done")
_V12_SCHEMA = _OLD_SCHEMA[:-1] + ", latency_p50_ms REAL, ttft_p50_ms REAL, decode_tps_p50 REAL, perf_done INTEGER)"


def _report(i: int, perf) -> dict:
    r = {"generated_at": f"t{i}", "target": dict(_TARGET),
         "verdict": {"risk_level": "clean", "overall_score": 90.0 + i}}
    if perf is not None:
        r["performance"] = perf
    return r


def _headline(report_json: str | None) -> dict:
    """The target's p50 latency / TTFT / decode speed of a saved report, as
    ekte computed it from report_json before step 13 (the oracle)."""
    out: dict = {"latency_p50_ms": None, "ttft_p50_ms": None, "decode_tps_p50": None}
    try:
        target = (json.loads(report_json or "{}").get("performance") or {}).get("target") or {}
    except (ValueError, TypeError, AttributeError):
        return out

    def p50(key):
        stats = target.get(key)
        value = stats.get("p50") if isinstance(stats, dict) else None
        # a boolean is no measurement (the old columns took True for 1.0)
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return float(value) if ok else None

    out["latency_p50_ms"] = p50("latency_ms")
    out["ttft_p50_ms"] = p50("ttft_ms")
    tps = p50("decode_tps_local")
    out["decode_tps_p50"] = tps if tps is not None else p50("decode_tps_reported")
    return out


def _old_recent(db, limit=500):
    """recent(perf=True) computed from report_json, as before step 13 (a row
    without a surface reads as chat)."""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    summary = tuple(c for c in history._SUMMARY_COLS if c != "surface")
    cols = ", ".join(summary + ("report_json",))
    rows = conn.execute(f"SELECT {cols} FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    out = [dict(r) for r in rows]
    for item in out:
        report_json = item.pop("report_json", None)
        item["surface"] = "chat"
        item.update(_headline(report_json))
    return out


def _user_version(db) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _columns(db) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(history)")}
    finally:
        conn.close()


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


def _seed_old_db(db, schema: str = _OLD_SCHEMA) -> None:
    """A database written by an older ekte (no analytics tables)."""
    conn = sqlite3.connect(db)
    conn.execute(schema)
    for i, perf in enumerate(_PERFS * 30):  # > one backfill batch
        conn.execute(
            "INSERT INTO history (ts, base_url, claimed_model, score, risk_level, report_json)"
            " VALUES (?,?,?,?,?,?)",
            (f"t{i}", "https://x/v1", "m", float(i), "clean", json.dumps(_report(i, perf))),
        )
    conn.execute("INSERT INTO history (ts, base_url, claimed_model, report_json)"
                 " VALUES ('broken', 'https://x/v1', 'm', '{not json')")
    conn.execute("INSERT INTO history (ts, base_url, claimed_model, report_json)"
                 " VALUES ('null', 'https://x/v1', 'm', NULL)")
    conn.commit()
    conn.close()


def _boom(*_a, **_k):
    raise AssertionError("report_json parsed again")


def test_saved_rows_read_like_the_old_report_json_path(data):
    for i, perf in enumerate(_PERFS):
        assert history.save(_report(i, perf)) > 0
    db = data / "history.db"
    assert _user_version(db) == history._SCHEMA_VERSION
    assert not _columns(db) & set(_DROPPED)  # one store per value: history_metrics
    new = history.recent(500, perf=True)
    assert new == _old_recent(db)
    assert [list(r) for r in new] == [list(r) for r in _old_recent(db)]  # same key order
    by_ts = {r["ts"]: r for r in new}
    assert (by_ts["t1"]["latency_p50_ms"], by_ts["t1"]["ttft_p50_ms"],
            by_ts["t1"]["decode_tps_p50"]) == (900.5, 310.0, 60.25)
    assert by_ts["t2"]["decode_tps_p50"] == 42.5  # reported decode when no local one
    assert by_ts["t0"]["latency_p50_ms"] is None
    assert "latency_p50_ms" not in history.recent(500)[0]  # only with perf


def test_old_database_is_backfilled_once_with_identical_values(data, monkeypatch):
    db = data / "history.db"
    _seed_old_db(db)
    expected_recent = _old_recent(db)

    assert history.recent(500, perf=True) == expected_recent
    assert _user_version(db) == history._SCHEMA_VERSION

    # Once migrated and extracted, reads never parse report_json again.
    monkeypatch.setattr(analytics_store, "extract_metrics", _boom)
    assert history.recent(500, perf=True) == expected_recent


def test_step_13_drops_the_duplicate_headline_columns(data):
    """A 0.34-era database (headline columns on history, filled) loses them;
    the list reads the same values from history_metrics."""
    db = data / "history.db"
    _seed_old_db(db, _V12_SCHEMA)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE history SET latency_p50_ms = -1, perf_done = 1")  # never read
    assert set(_DROPPED) <= _columns(db)
    expected = _old_recent(db)
    assert history.recent(500, perf=True) == expected
    assert _user_version(db) == history._SCHEMA_VERSION
    if sqlite3.sqlite_version_info >= (3, 35):
        assert not _columns(db) & set(_DROPPED)
    assert history.save(_report(999, _PERFS[1])) > 0  # writes without them


def test_step_13_keeps_the_columns_on_an_old_sqlite(data, monkeypatch):
    db = data / "history.db"
    _seed_old_db(db, _V12_SCHEMA)
    monkeypatch.setattr(history.sqlite3, "sqlite_version_info", (3, 34, 1))
    assert history.recent(500, perf=True) == _old_recent(db)
    assert set(_DROPPED) <= _columns(db)  # harmless: nothing reads or writes them
    assert history.save(_report(999, _PERFS[1])) > 0


def test_rows_written_by_an_older_ekte_are_extracted_on_read(data, monkeypatch):
    history.save(_report(0, _PERFS[1]))
    db = data / "history.db"
    conn = sqlite3.connect(db)  # an older ekte does not know the analytics tables
    for i, perf in enumerate(_PERFS[1:4], 1):
        conn.execute(
            "INSERT INTO history (ts, base_url, claimed_model, report_json) VALUES (?,?,?,?)",
            (f"old{i}", "https://x/v1", "m", json.dumps(_report(i, perf))),
        )
    conn.commit()
    conn.close()
    expected = _old_recent(db)
    assert history.recent(perf=True) == expected  # extracted on this read, then stored
    monkeypatch.setattr(analytics_store, "extract_metrics", _boom)
    assert history.recent(perf=True) == expected
    assert expected[1]["ts"] == "old2" and expected[1]["decode_tps_p50"] == 42.5


def test_schema_is_rebuilt_for_a_new_or_deleted_database(data, monkeypatch, tmp_path_factory):
    history.save(_report(0, _PERFS[1]))
    db = data / "history.db"
    for side in (db, db.with_name("history.db-wal"), db.with_name("history.db-shm")):
        side.unlink(missing_ok=True)
    history.datadir.close_read_connections()
    assert history.recent(perf=True) == []
    assert history.save(_report(1, _PERFS[2])) > 0

    other = tmp_path_factory.mktemp("other")
    monkeypatch.setenv("EKTE_DATA_DIR", str(other))
    assert history.recent() == []
    _seed = other / "history.db"
    assert _user_version(_seed) == history._SCHEMA_VERSION

    # An old-schema file put in place of a migrated one is migrated too.
    third = tmp_path_factory.mktemp("third")
    monkeypatch.setenv("EKTE_DATA_DIR", str(third))
    _seed_old_db(third / "history.db", _OLD_SCHEMA.split(", kb_snapshot_id")[0] + ")")
    got = history.recent(500, perf=True)
    assert len(got) == len(_PERFS) * 30 + 2
    assert got == _old_recent(third / "history.db")


def test_latest_for_finds_a_target_behind_many_newer_runs(data):
    profile = {"provider": {"provider": "acme"}, "model": {"id": "model-one"}}
    for i in range(2):
        report = _report(i, None)
        report["knowledge"] = {"profile": dict(profile), "match_confidence": "exact"}
        history.save(report)
    for i in range(60):  # more than the 50 rows the old lookup scanned
        other = _report(100 + i, None)
        other["target"] = {"base_url": f"https://other-{i}/v1", "claimed_model": "m", "model": "m"}
        history.save(other)

    found = history.latest_for(_TARGET["base_url"], _TARGET["claimed_model"])
    assert found is not None and found["generated_at"] == "t1"  # the newest of the two
    # The full report, with its profile snapshot put back as get() does.
    assert found["knowledge"]["profile"] == profile
    assert history.latest_for(_TARGET["base_url"], "other-model") is None
    assert history.latest_for("https://nowhere/v1", _TARGET["claimed_model"]) is None


def test_latest_for_is_one_lookup_on_the_target_index(data):
    history.save(_report(0, None))
    with sqlite3.connect(data / "history.db") as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + history._LATEST_FOR_SQL, ("https://x/v1", "m")
        ).fetchall()
    detail = " ".join(str(row[-1]) for row in plan)
    assert "idx_history_target" in detail and "TEMP B-TREE" not in detail


def test_status_sums_up_the_history_for_the_page_notices(data):
    s = history.status()
    assert (s["runs"], s["oldest"], s["latest"], s["pending"]) == (0, None, None, 0)
    reports = [_report(i, None) for i in range(3)]
    for r in reports:
        r["generated_at"] = "2026-10-01T10:00:00+00:00"
    ids = [history.save(r) for r in reports]
    s = history.status()
    assert s["runs"] == 3 and s["latest"]["id"] == ids[-1] and s["latest"]["score"] == 92.0
    assert s["latest"]["surface"] == "chat" and s["pending"] == 0
    # these reports carry no started_at: their start time is estimated
    assert s["estimated"] == 3
    # a row the analytics backfill has not reached yet counts as pending
    conn = sqlite3.connect(data / "history.db")
    conn.execute(f"UPDATE history SET {history._SPLIT} = NULL WHERE id = ?", (ids[0],))
    conn.commit()
    conn.close()
    assert history.status()["pending"] == 1


def test_status_endpoint_is_not_taken_for_a_report_id(data):
    from fastapi.testclient import TestClient

    from ekte.web.server import create_app

    history.save(_report(0, None))
    r = TestClient(create_app(), base_url="http://localhost").get("/api/history/status")
    assert r.status_code == 200 and r.json()["runs"] == 1
