"""History schema v2: request records stored once, extracted metrics, backfill."""

from __future__ import annotations

import copy
import json
import math
import sqlite3
import typing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zing.models import AuditReport, RequestRecord
from zing.web import analytics_store, history

FIXTURES = Path(__file__).parent / "fixtures"

# history.db as schema version 1 (zing 0.19) left it.
_V1_SCHEMA = (
    "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, base_url TEXT,"
    " claimed_model TEXT, model TEXT, mode TEXT, suite TEXT, risk_level TEXT, score REAL,"
    " rating TEXT, report_json TEXT, kb_snapshot_id INTEGER, kb_match TEXT, watch_id INTEGER,"
    " api TEXT, api_auto INTEGER, stream_mode TEXT, latency_p50_ms REAL, ttft_p50_ms REAL,"
    " decode_tps_p50 REAL, perf_done INTEGER)",
    "CREATE INDEX idx_history_target ON history (base_url, claimed_model, id)",
    "CREATE TABLE kb_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, content_hash TEXT NOT NULL"
    " UNIQUE, provider TEXT, model_id TEXT, profile_json TEXT NOT NULL, created_ts REAL)",
    "PRAGMA user_version = 1",
)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    return tmp_path


def _fixture() -> dict:
    """A real compare-mode report (fake relay), trimmed: 8 target and 4
    baseline request records, a knowledge-base profile snapshot."""
    return json.loads((FIXTURES / "history_report.json").read_text(encoding="utf-8"))


def _old_shaped(i: int = 0) -> dict:
    """A report as an older zing wrote it: no started_at, request records
    without the newer fields."""
    report = _fixture()
    report.pop("started_at")
    report["generated_at"] = f"2026-0{1 + i % 9}-1{i % 10}T10:00:00+00:00"
    report["tool_version"] = "0.15.0"
    for rec in report["performance"]["requests"]:
        for key in ("relay_processing_ms", "server_ms", "cached", "reasoning_tokens"):
            rec.pop(key, None)
    return report


def _db(data: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data / "history.db")
    conn.row_factory = sqlite3.Row
    return conn


def _count(data: Path, table: str, rid: int | None = None) -> int:
    with _db(data) as conn:
        if rid is None:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return conn.execute(
            f"SELECT count(*) FROM {table} WHERE history_id = ?", (rid,)
        ).fetchone()[0]


def _stored_json(data: Path, rid: int) -> dict:
    with _db(data) as conn:
        row = conn.execute("SELECT report_json FROM history WHERE id = ?", (rid,)).fetchone()
    return json.loads(row[0])


def _same(a: object, b: object) -> bool:
    """Identical as JSON: values, types (1 vs 1.0), key order, NaN."""
    return json.dumps(a) == json.dumps(b)


def _same_report(got: dict | None, saved: dict) -> None:
    assert got == saved
    # Byte-identical, except the profile snapshot, whose keys kb_snapshots
    # has always stored sorted.
    assert got is not None
    strip = [copy.deepcopy(r) for r in (got, saved)]
    for r in strip:
        if isinstance(r.get("knowledge"), dict):
            r["knowledge"].pop("profile", None)
    assert _same(*strip)


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #
def test_fixture_is_a_valid_current_report():
    report = AuditReport.model_validate(_fixture())
    assert report.started_at and report.performance is not None
    endpoints = [r.endpoint for r in report.performance.requests]
    assert endpoints.count("target") == 8 and endpoints.count("baseline") == 4


def test_request_columns_cover_every_request_record_field():
    kinds = {int: "int", float: "float", bool: "bool", str: "str"}
    hints = typing.get_type_hints(RequestRecord)
    assert list(analytics_store.REQUEST_FIELDS) == list(RequestRecord.model_fields)
    for name, kind in analytics_store.REQUEST_FIELDS.items():
        types = [t for t in typing.get_args(hints[name]) or (hints[name],) if t is not type(None)]
        assert [kinds[t] for t in types] == [kind], name


@pytest.mark.parametrize("shape", ["compare", "check", "no_performance", "no_requests"])
def test_saved_report_reads_back_identical(data, shape):
    report = _fixture()
    if shape == "check":
        report["mode"] = "check"
        report["baseline"] = None
        report["performance"]["baseline"] = None
        report["performance"]["requests"] = [
            r for r in report["performance"]["requests"] if r["endpoint"] == "target"
        ]
    elif shape == "no_performance":
        report["performance"] = None
    elif shape == "no_requests":
        report["performance"]["requests"] = []
    saved = copy.deepcopy(report)

    rid = history.save(report)
    assert rid > 0
    assert report == saved  # save() leaves its argument alone
    _same_report(history.get(rid), saved)
    claimed = saved["target"].get("claimed_model") or saved["target"]["model"]
    _same_report(history.latest_for(saved["target"]["base_url"], claimed), saved)

    n = len((saved["performance"] or {}).get("requests") or [])
    assert _count(data, "history_requests", rid) == n
    stored = _stored_json(data, rid)
    if saved["performance"] is not None:
        # Stored once: report_json keeps an empty list in their place.
        assert stored["performance"]["requests"] == []
    assert _count(data, "history_metrics", rid) == 1


def test_records_are_stored_once_in_their_own_table(data):
    report = _fixture()
    rid = history.save(report)
    with _db(data) as conn:
        rows = conn.execute(
            "SELECT * FROM history_requests WHERE history_id = ? ORDER BY ord", (rid,)
        ).fetchall()
        size = conn.execute("SELECT length(report_json) FROM history").fetchone()[0]
    records = report["performance"]["requests"]
    assert [r["seq"] for r in rows] == [r["seq"] for r in records]
    assert [r["endpoint"] for r in rows] == [r["endpoint"] for r in records]
    assert all(r["extra"] is None for r in rows)  # ordinary records need no extra
    assert size < len(json.dumps(report, ensure_ascii=False)) - len(json.dumps(records)) + 100
    assert history.analytics_requests([rid])[0]["duration_ms"] == records[0]["duration_ms"]
    assert len(history.analytics_requests([rid])) == 8
    assert len(history.analytics_requests([rid], endpoint=None)) == 12
    assert {r["endpoint"] for r in history.analytics_requests([rid], "baseline")} == {"baseline"}


def test_unusual_records_read_back_exactly(data):
    report = _fixture()
    records = report["performance"]["requests"]
    records[0]["future_field"] = {"nested": [1, 2.5, None]}  # unknown key
    del records[1]["relay_processing_ms"]  # an older record: field missing
    records[2]["start_ms"] = 5  # int where a float is expected (kept queryable)
    records[2]["duration_ms"] = 12.0
    records[3]["status_code"] = 200.0  # float where an int is expected
    records[3]["ok"] = 1  # int where a bool is expected
    records[4]["detector"] = 7  # wrong type entirely
    records[5]["chunk_count"] = 2**70  # beyond SQLite's integers
    records[6]["ttft_ms"] = -0.0
    records[7]["itl_mean_ms"] = float("nan")
    records[8] = dict(reversed(list(records[8].items())))  # another key order
    records[9]["phase"] = "pröbe ✓"
    records[10] = {}
    saved = copy.deepcopy(report)
    rid = history.save(report)
    assert rid > 0
    got = history.get(rid)
    assert got is not None
    assert _same(got["performance"]["requests"], saved["performance"]["requests"])
    assert _stored_json(data, rid)["performance"]["requests"] == []
    with _db(data) as conn:
        cols = conn.execute(
            "SELECT start_ms, status_code, ok, ttft_ms, itl_mean_ms, chunk_count, detector"
            " FROM history_requests ORDER BY ord"
        ).fetchall()
    assert cols[2]["start_ms"] == 5.0 and cols[3]["status_code"] == 200
    assert cols[3]["ok"] is None and cols[4]["detector"] is None
    assert cols[5]["chunk_count"] is None and cols[7]["itl_mean_ms"] is None
    assert str(cols[6]["ttft_ms"]) == "0.0"


def test_records_that_cannot_move_stay_inline(data):
    report = _fixture()
    report["performance"]["requests"].append("not a record")
    saved = copy.deepcopy(report)
    rid = history.save(report)
    _same_report(history.get(rid), saved)
    assert _count(data, "history_requests", rid) == 0
    assert len(_stored_json(data, rid)["performance"]["requests"]) == 13


def test_save_never_raises(data, monkeypatch):
    weird = [
        None,
        {},
        {"performance": "x"},
        {"performance": {"requests": "x"}},
        {"performance": {"requests": [None, 1, "a"]}},
        {"performance": {"target": [], "requests": [{"seq": "x", "start_ms": "y"}]}},
        {"detectors": "x", "dimensions": [None, {"dimension": 5}], "knowledge": "x"},
        {"detectors": [{"id": "billing", "evidence": "x", "findings": "x"}]},
        {"generated_at": 12, "started_at": ["x"], "target": {"base_url": 5}},
        {"generated_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "notes": {1, 2}},
    ]
    for report in weird:
        assert isinstance(history.save(report), int)  # type: ignore[arg-type]
    assert history.save({"target": "not a dict"}) == -1
    assert history.save("not a dict") == -1  # type: ignore[arg-type]

    # A failing extraction still saves the run, unprocessed (records inline),
    # and the backfill processes it later.
    def boom(_report):
        raise RuntimeError("extraction bug")

    with monkeypatch.context() as m:
        m.setattr(analytics_store, "extract_metrics", boom)
        rid = history.save(_fixture())
    assert rid > 0 and _count(data, "history_metrics", rid) == 0
    assert _count(data, "history_requests", rid) == 0
    _same_report(history.get(rid), _fixture())
    history.backfill_analytics()
    assert _count(data, "history_metrics", rid) == 1
    assert _count(data, "history_requests", rid) == 12
    _same_report(history.get(rid), _fixture())


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def test_extract_metrics_of_a_current_report():
    report = _fixture()
    metrics, dims = analytics_store.extract_metrics(report)
    assert set(metrics) == set(analytics_store.METRIC_COLS)
    start = datetime.fromisoformat(report["started_at"])
    assert metrics["started_at"] == start.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    assert metrics["started_at_estimated"] == 0
    assert metrics["tool_version"] == report["tool_version"]
    assert metrics["base_url_norm"] == "https://relay.example.com/v1"
    knowledge = report["knowledge"]
    assert (metrics["kb_profile_hash"], metrics["kb_provider"], metrics["kb_model_id"]) == (
        knowledge["profile_hash"], knowledge["provider"], knowledge["model_id"]
    )
    billing = next(d for d in report["detectors"] if d["id"] == "billing")["evidence"]
    assert metrics["billing_ratio_prompt"] == billing["ratio_prompt"]
    assert metrics["billing_ratio_completion"] == billing["ratio_completion"]
    side = report["performance"]["target"]
    assert metrics["success_rate"] == side["successes"] / side["requests"]
    assert metrics["error_rate"] == side["error_rate"]
    assert metrics["cold_start_ms"] == side["cold_start_ms"]
    assert metrics["network_rtt_p50_ms"] == side["network_rtt_ms"]["p50"]
    assert metrics["model_mismatch"] == 0
    assert metrics["identity_status"] == "warn"
    severities = [f["severity"] for d in report["detectors"] for f in d["findings"]]
    assert metrics["findings_high"] == severities.count("high") + severities.count("critical")
    assert metrics["findings_medium"] == severities.count("medium")
    assert metrics["findings_low"] == severities.count("low")
    assert metrics["extract_version"] == analytics_store.EXTRACT_VERSION
    # Not measured by this run: NULL, never 0.
    for key in ("ttft_p50_ms", "decode_tps_p50", "reasoning_share", "context_claimed_tokens",
                "relay_processing_p50_ms", "concurrency_tps"):
        assert metrics[key] is None, key

    by_key = {(d["kind"], d["key"]): d for d in dims}
    assert len(by_key) == len(report["dimensions"]) + len(report["detectors"])
    billing_dim = next(d for d in report["dimensions"] if d["dimension"] == "billing")
    assert by_key[("dimension", "billing")] == {
        "kind": "dimension", "key": "billing", "score": billing_dim["score"],
        "status": billing_dim["status"], "weight": billing_dim["weight"],
    }
    assert by_key[("detector", "model_identity")]["weight"] is None


def test_extract_metrics_reads_the_performance_headline():
    stats = {
        "requests": 10, "successes": 7, "error_rate": 0.2, "timeout_rate": 0.1,
        "rate_limited_rate": 0.1,
        "latency_ms": {"p50": 900.5, "p95": 1500}, "ttft_ms": {"p50": 300.0, "p95": None},
        "decode_tps_local": {"p50": None}, "decode_tps_reported": {"p50": 42.5},
        "itl_jitter_ms": {"p50": 3.5}, "relay_processing_ms": {"p50": 120},
        "network_rtt_ms": {"p50": 40.0}, "cold_start_ms": 2000.0,
        "concurrency": {"aggregate_tps_local": None, "aggregate_tps_reported": 88.0},
    }
    records = [
        {"endpoint": "target", "output_tokens_reported": 100, "reasoning_tokens": 60,
         "input_tokens_reported": 1000, "cached_input_tokens": 0},
        {"endpoint": "target", "output_tokens_reported": 100, "reasoning_tokens": None,
         "input_tokens_reported": 1000, "cached_input_tokens": 500},
        {"endpoint": "baseline", "output_tokens_reported": 100, "reasoning_tokens": 100,
         "input_tokens_reported": 1000, "cached_input_tokens": 1000},
        {"output_tokens_reported": 100, "reasoning_tokens": 20},  # endpoint defaults to target
    ]
    report = {"performance": {"target": stats, "requests": records}}
    metrics, dims = analytics_store.extract_metrics(report)
    assert dims == []
    assert metrics["success_rate"] == 0.7
    assert (metrics["error_rate"], metrics["timeout_rate"], metrics["rate_limited_rate"]) == (
        0.2, 0.1, 0.1)
    assert (metrics["latency_p50_ms"], metrics["latency_p95_ms"]) == (900.5, 1500.0)
    assert (metrics["ttft_p50_ms"], metrics["ttft_p95_ms"]) == (300.0, None)
    assert metrics["decode_tps_p50"] == 42.5  # the reported count when no local one
    assert metrics["itl_jitter_p50_ms"] == 3.5
    assert metrics["relay_processing_p50_ms"] == 120.0
    assert metrics["network_rtt_p50_ms"] == 40.0
    assert metrics["cold_start_ms"] == 2000.0
    assert metrics["concurrency_tps"] == 88.0
    assert metrics["reasoning_share"] == pytest.approx(80 / 200)
    assert metrics["cached_input_share"] == pytest.approx(500 / 2000)
    # No detectors: finding counts are unknown, not zero.
    assert metrics["findings_high"] is None


@pytest.mark.parametrize("report", [{}, None, "x", [], {"performance": None, "detectors": None}])
def test_extract_metrics_of_nothing_is_all_null(report):
    metrics, dims = analytics_store.extract_metrics(report)
    assert dims == []
    assert {k: v for k, v in metrics.items() if v is not None} == {
        "extract_version": analytics_store.EXTRACT_VERSION
    }


def test_extract_metrics_of_an_old_shaped_report():
    report = _old_shaped()
    for det in report["detectors"]:
        for f in det["findings"]:
            f.pop("outcome", None)  # before scoring outcomes were recorded
    report["knowledge"] = None
    report["performance"]["target"] = {"latency_ms": {"p50": 800}}
    metrics, _ = analytics_store.extract_metrics(report)
    assert metrics["started_at_estimated"] == 1
    assert metrics["tool_version"] == "0.15.0"
    assert metrics["kb_profile_hash"] is None and metrics["kb_provider"] is None
    assert metrics["latency_p50_ms"] == 800.0
    assert metrics["success_rate"] is None and metrics["error_rate"] is None
    assert metrics["model_mismatch"] == 0  # from the finding's status


@pytest.mark.parametrize(
    ("outcome", "status", "returned", "expected"),
    [
        ("diverges", "fail", "small-model", 1),
        ("consistent", "pass", "m", 0),
        ("unavailable", "inconclusive", None, None),
        (None, "fail", "small-model", 1),
        (None, "pass", "m", 0),
        (None, "inconclusive", None, None),
    ],
)
def test_model_mismatch(outcome, status, returned, expected):
    finding = {"id": "model_identity.model_field", "status": status, "outcome": outcome,
               "evidence": {"requested": "m", "returned": returned}}
    report = {"detectors": [{"id": "model_identity", "status": "warn", "findings": [finding]}]}
    metrics, _ = analytics_store.extract_metrics(report)
    assert metrics["model_mismatch"] == expected
    assert metrics["identity_status"] == "warn"
    assert analytics_store.extract_metrics({"detectors": []})[0]["model_mismatch"] is None


def test_extract_context_window():
    det = {"id": "context_window", "evidence": {"declared": 128000, "effective_window": 64000}}
    metrics, _ = analytics_store.extract_metrics({"detectors": [det]})
    assert (metrics["context_claimed_tokens"], metrics["context_effective_tokens"]) == (
        128000, 64000)


def test_started_at_is_estimated_for_older_reports():
    generated = "2026-03-01T12:00:10.500000+00:00"
    records = [
        {"start_ms": 100.0, "duration_ms": 900.0},
        {"start_ms": 2000.0, "duration_ms": 500.0},  # ends last: 2.5 s in
        {"start_ms": 2400.0, "duration_ms": None},
        {"start_ms": "x"},
        "junk",
    ]
    report = {"generated_at": generated, "performance": {"requests": records}}
    assert analytics_store.started_at(report) == ("2026-03-01T12:00:08.000000+00:00", 1)
    # Without request records: generated_at itself.
    assert analytics_store.started_at({"generated_at": generated}) == (
        "2026-03-01T12:00:10.500000+00:00", 1)
    # A recorded started_at wins, normalized to UTC.
    report["started_at"] = "2026-03-01T13:00:00+01:00"
    assert analytics_store.started_at(report) == ("2026-03-01T12:00:00.000000+00:00", 0)
    assert analytics_store.started_at({"started_at": "2026-03-01T12:00:00Z"})[0] == (
        "2026-03-01T12:00:00.000000+00:00")
    assert analytics_store.started_at({"started_at": "2026-03-01T12:00:00"})[0] == (
        "2026-03-01T12:00:00.000000+00:00")  # naive: taken as UTC
    assert analytics_store.started_at({"started_at": "garbage", "generated_at": "t1"}) == (
        None, None)
    assert analytics_store.started_at({}) == (None, None)


def test_started_at_estimate_matches_a_real_run():
    """The estimate for the fixture (as if it had no started_at) is a little
    after the real start: the report is put together after the last request."""
    report = _fixture()
    real = datetime.fromisoformat(report.pop("started_at"))
    est, flag = analytics_store.started_at(report)
    assert flag == 1 and est is not None
    delta = datetime.fromisoformat(est) - real
    assert timedelta(0) <= delta < timedelta(seconds=2)


# --------------------------------------------------------------------------- #
# Migration and backfill
# --------------------------------------------------------------------------- #
def _seed_v1(db: Path, reports: list) -> None:
    conn = sqlite3.connect(db)
    for stmt in _V1_SCHEMA:
        conn.execute(stmt)
    for report in reports:
        raw = report if isinstance(report, str) or report is None else json.dumps(report)
        conn.execute(
            "INSERT INTO history (ts, base_url, claimed_model, report_json, perf_done)"
            " VALUES (?, ?, ?, ?, 1)",
            ("t", "https://relay.example.com/v1", "gpt-4o-mini", raw),
        )
    conn.commit()
    conn.close()


def _v1_reports() -> list:
    no_perf = _old_shaped(1)
    no_perf.pop("performance")
    odd = _old_shaped(2)
    odd["performance"]["requests"][0]["legacy"] = True
    return [_old_shaped(i) for i in range(60)] + [no_perf, odd, "{not json", None]


def _tables(data: Path) -> dict:
    with _db(data) as conn:
        return {
            t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3")]
            for t in ("history", "history_metrics", "history_dimensions", "history_requests")
        }


def test_v1_database_is_migrated_and_backfilled(data):
    reports = _v1_reports()
    _seed_v1(data / "history.db", reports)

    for rid, report in enumerate(reports, 1):
        got = history.get(rid)
        if isinstance(report, dict):
            _same_report(got, report)
        else:
            assert got is None
    with _db(data) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == history._SCHEMA_VERSION
        split = [r[0] for r in conn.execute("SELECT requests_split FROM history ORDER BY id")]
        metrics = conn.execute(
            "SELECT started_at, started_at_estimated, extract_version FROM history_metrics"
            " ORDER BY history_id"
        ).fetchall()
    # Every row processed: records moved where there were any, metrics for all.
    assert split == [1] * 60 + [0, 1, 0, 0]
    assert len(metrics) == len(reports)
    assert all(m["extract_version"] == analytics_store.EXTRACT_VERSION for m in metrics)
    assert [m["started_at_estimated"] for m in metrics] == [1] * 62 + [None, None]
    assert metrics[0]["started_at"] == analytics_store.started_at(reports[0])[0]
    assert _stored_json(data, 1)["performance"]["requests"] == []
    assert _count(data, "history_requests") == 61 * 12

    # Once done, the backfill finds nothing and changes nothing.
    before = _tables(data)
    history.backfill_analytics()
    assert _tables(data) == before


def test_interrupted_backfill_resumes_without_damage(data, monkeypatch):
    reports = _v1_reports()
    _seed_v1(data / "history.db", reports)
    calls = []
    real_put = analytics_store.put_metrics

    def crash_in_second_batch(conn, rid, metrics, dims):
        calls.append(rid)
        if len(calls) > history._ANALYTICS_BATCH:
            raise sqlite3.OperationalError("disk I/O error")
        real_put(conn, rid, metrics, dims)

    with monkeypatch.context() as m:
        m.setattr(analytics_store, "put_metrics", crash_in_second_batch)
        history.init()  # migrates; the backfill fails part-way (best-effort)
    with _db(data) as conn:
        done = conn.execute("SELECT count(*) FROM history WHERE requests_split IS NOT NULL")
        assert done.fetchone()[0] == history._ANALYTICS_BATCH  # the first batch only
    assert _count(data, "history_metrics") == history._ANALYTICS_BATCH
    # Every row reads back right, migrated or not.
    for rid, report in enumerate(reports, 1):
        if isinstance(report, dict):
            _same_report(history.get(rid), report)

    history.backfill_analytics()
    assert _count(data, "history_metrics") == len(reports)
    for rid, report in enumerate(reports, 1):
        if isinstance(report, dict):
            _same_report(history.get(rid), report)


def test_rows_written_by_an_older_zing_are_picked_up(data):
    first = _fixture()
    history.save(first)
    old = _old_shaped(3)
    with _db(data) as conn:  # an older zing knows neither the column nor the tables
        conn.execute(
            "INSERT INTO history (ts, base_url, claimed_model, report_json) VALUES (?,?,?,?)",
            ("t", "https://relay.example.com/v1", "gpt-4o-mini", json.dumps(old)),
        )
    _same_report(history.get(2), old)  # inline records still read
    runs = history.analytics_runs()
    assert [r["id"] for r in runs] == [2, 1]  # oldest start first
    assert runs[0]["started_at_estimated"] == 1
    assert _count(data, "history_requests", 2) == 12
    _same_report(history.get(2), old)


def test_a_newer_extract_version_re_extracts(data, monkeypatch):
    rid = history.save(_fixture())
    with _db(data) as conn:
        conn.execute("UPDATE history_metrics SET reasoning_share = 0.99, extract_version = 0")
    history.backfill_analytics()
    with _db(data) as conn:
        row = conn.execute("SELECT * FROM history_metrics WHERE history_id = ?", (rid,)).fetchone()
    # Re-extracted from the full report (records put back from their table).
    assert row["reasoning_share"] is None
    assert row["extract_version"] == analytics_store.EXTRACT_VERSION

    gone = history.save(_fixture())
    with _db(data) as conn:  # deleted by an older zing: its analytics rows stay
        conn.execute("DELETE FROM history WHERE id = ?", (gone,))
    monkeypatch.setattr(analytics_store, "EXTRACT_VERSION", analytics_store.EXTRACT_VERSION + 1)
    history.backfill_analytics()
    tables = ("history_metrics", "history_dimensions", "history_requests")
    assert [_count(data, t, gone) for t in tables] == [0, 0, 0]  # cleaned up on the way
    with _db(data) as conn:
        version = conn.execute("SELECT extract_version FROM history_metrics").fetchone()[0]
    assert version == analytics_store.EXTRACT_VERSION
    _same_report(history.get(rid), _fixture())


def test_pending_rows_are_found_through_indexes(data):
    history.save(_fixture())
    with _db(data) as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + history._ANALYTICS_TODO,
            (analytics_store.EXTRACT_VERSION,),
        ).fetchall()
    detail = " ".join(str(row[-1]) for row in plan)
    assert "idx_history_pending" in detail and "idx_history_metrics_version" in detail
    assert "SCAN history " not in detail.replace("SCAN history USING INDEX", "") + " "


def test_fresh_database_has_the_v3_schema(data):
    history.init()
    with _db(data) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(history)")}
        metric_cols = {r[1] for r in conn.execute("PRAGMA table_info(history_metrics)")}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert {"history_metrics", "history_dimensions", "history_requests",
            "idx_history_metrics_started", "idx_history_model"} <= tables
    assert "requests_split" in cols
    assert {"decode_tps_p5", "decode_tps_p95"} <= metric_cols


def _with_decode(report: dict, speeds: list[float | None], *, stream: bool = True) -> dict:
    """The report with probe requests of these local decode speeds (tok/s)."""
    seq = max(r["seq"] for r in report["performance"]["requests"]) + 1
    report["performance"]["requests"] += [
        RequestRecord(seq=seq + i, phase="probe", stream=stream, ok=True, duration_ms=900.0,
                      ttft_ms=200.0, decode_tps_local=v, decode_tps_reported=50.0).model_dump()
        for i, v in enumerate(speeds)
    ]
    return report


def test_decode_speed_tails_come_from_the_requests_of_the_p50():
    speeds = [float(v) for v in range(10, 31)]  # 21 requests: 10 .. 30 tok/s
    metrics, _ = analytics_store.extract_metrics(_with_decode(_fixture(), speeds))
    assert metrics["decode_tps_p5"] == pytest.approx(11.0) and metrics["decode_tps_p95"] == pytest.approx(29.0)
    # a failed or cached request does not count, like for the p50
    report = _with_decode(_fixture(), speeds)
    report["performance"]["requests"][-1].update(ok=False)
    report["performance"]["requests"][-2].update(cached=True)
    assert analytics_store.extract_metrics(report)[0]["decode_tps_p5"] is None  # 19 < 20 requests
    # without local counts: the reported speed, as for the p50
    metrics, _ = analytics_store.extract_metrics(_with_decode(_fixture(), [None] * 20))
    assert (metrics["decode_tps_p5"], metrics["decode_tps_p95"]) == (50.0, 50.0)
    # only non-streaming requests: no decode speed
    metrics, _ = analytics_store.extract_metrics(_with_decode(_fixture(), speeds, stream=False))
    assert (metrics["decode_tps_p5"], metrics["decode_tps_p95"]) == (None, None)
    # fewer than 20 requests (the p95 floor), or records that do not parse
    assert analytics_store.extract_metrics(_fixture())[0]["decode_tps_p95"] is None
    report = _with_decode(_fixture(), speeds)
    report["performance"]["requests"].append({"seq": "x"})
    assert analytics_store.extract_metrics(report)[0]["decode_tps_p95"] == pytest.approx(29.0)


def test_a_v2_database_gets_the_decode_tails_of_its_older_runs(data):
    rid = history.save(_with_decode(_fixture(), [float(v) for v in range(10, 31)]))
    with _db(data) as conn:  # as zing with schema 2 left it
        conn.execute("ALTER TABLE history_metrics DROP COLUMN decode_tps_p5")
        conn.execute("ALTER TABLE history_metrics DROP COLUMN decode_tps_p95")
        conn.execute("UPDATE history_metrics SET extract_version = 1")
        conn.execute("PRAGMA user_version = 2")
    history.init()
    with _db(data) as conn:
        row = conn.execute("SELECT * FROM history_metrics WHERE history_id = ?", (rid,)).fetchone()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert row["decode_tps_p5"] == pytest.approx(11.0) and row["decode_tps_p95"] == pytest.approx(29.0)
    assert row["extract_version"] == analytics_store.EXTRACT_VERSION


# --------------------------------------------------------------------------- #
# Delete / clear, reads
# --------------------------------------------------------------------------- #
def test_delete_and_clear_remove_the_analytics_rows(data):
    ids = [history.save(_fixture()) for _ in range(3)]
    tables = ("history_metrics", "history_dimensions", "history_requests")
    assert all(_count(data, t, ids[0]) for t in tables)
    history.delete(ids[0])
    assert [_count(data, t, ids[0]) for t in tables] == [0, 0, 0]
    assert all(_count(data, t, ids[1]) for t in tables)
    history.clear()
    assert [_count(data, t) for t in tables] == [0, 0, 0]
    assert history.get(ids[1]) is None


def test_analytics_runs_filters_by_start_time(data):
    for day in (1, 2, 3):
        report = _fixture()
        report["started_at"] = f"2026-05-0{day}T23:30:00-02:00"  # = next day 01:30 UTC
        history.save(report, watch_id=7 if day == 2 else None)
    runs = history.analytics_runs()
    assert [r["started_at"][:10] for r in runs] == ["2026-05-02", "2026-05-03", "2026-05-04"]
    assert [r["watch_id"] for r in runs] == [None, 7, None]
    assert set(analytics_store.METRIC_COLS) <= set(runs[0])
    assert {"id", "base_url", "claimed_model", "suite", "stream_mode", "score"} <= set(runs[0])
    got = history.analytics_runs("2026-05-03T00:00:00Z", "2026-05-04T01:30:00+00:00")
    assert [r["started_at"][:10] for r in got] == ["2026-05-03"]
    with pytest.raises(ValueError):
        history.analytics_runs("yesterday")
    dims = history.analytics_dimensions([runs[0]["id"]], "dimension")
    assert {d["key"] for d in dims} == {d["dimension"] for d in _fixture()["dimensions"]}
    assert history.analytics_dimensions([]) == []


def test_nan_and_float_values_survive_in_metrics(data):
    report = _fixture()
    report["performance"]["target"]["latency_ms"]["p50"] = float("nan")
    report["performance"]["target"]["ttft_ms"]["p50"] = 0.1 + 0.2
    rid = history.save(report)
    with _db(data) as conn:
        row = conn.execute("SELECT latency_p50_ms, ttft_p50_ms FROM history_metrics").fetchone()
    assert row["latency_p50_ms"] is None  # not a measurement
    assert row["ttft_p50_ms"] == 0.1 + 0.2
    got = history.get(rid)
    assert got is not None and math.isnan(got["performance"]["target"]["latency_ms"]["p50"])
