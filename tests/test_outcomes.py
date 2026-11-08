"""The outcome model (#118): one outcome per request, per-run counts and rates,
stored at save time and re-extracted for older runs."""

from __future__ import annotations

import json
import random
import shutil
import sqlite3
from pathlib import Path

import jsonschema
import pytest

from ekte import schemas
from ekte.config import AuditOptions
from ekte.errorclass import OUTCOMES, outcome
from ekte.models import RequestRecord, TargetConfig
from ekte.perf.outcomes import from_counts, run_outcomes
from ekte.runner import run_audit
from ekte.web import analytics_store, history
from tests._helpers import BASE_URL, DEFAULT_MODEL, MockServer

FIXTURES = Path(__file__).parent / "fixtures"
V0340 = FIXTURES / "upgrade" / "v0.34.0"


def _rec(seq: int = 0, **kw) -> RequestRecord:
    return RequestRecord(seq=seq, **kw)


# --------------------------------------------------------------------------- #
# outcome()
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        # 1. ok wins over everything else
        ({"ok": True, "status_code": 200, "rate_limited": True, "timeout": True}, "success"),
        # 2. / 3. failures before the relay answered
        ({"error_class": "network", "error_type": "ConnectError"}, "network"),
        ({"error_class": "network", "status_code": 429, "rate_limited": True}, "network"),
        ({"error_class": "local", "error_type": "PoolTimeout"}, "local"),
        ({"error_class": "local", "timeout": True}, "local"),
        # 4. rate-limited: the flag or HTTP 429, before a timeout or status range
        ({"error_class": "relay", "rate_limited": True, "status_code": 500}, "rate_limited"),
        ({"error_class": "relay", "status_code": 429, "timeout": True}, "rate_limited"),
        # 5. timeout, before a status range
        ({"error_class": "relay", "timeout": True, "status_code": 504}, "relay_timeout"),
        ({"error_class": "relay", "timeout": True, "error_type": "ReadTimeout"}, "relay_timeout"),
        # 6. / 7. status ranges
        ({"error_class": "relay", "status_code": 500}, "relay_5xx"),
        ({"error_class": "relay", "status_code": 599}, "relay_5xx"),
        ({"error_class": "relay", "status_code": 400}, "relay_4xx"),
        ({"error_class": "relay", "status_code": 499}, "relay_4xx"),
        # 8. anything else the relay did
        ({"error_class": "relay", "error_type": "JSONDecodeError"}, "relay_other"),
        ({"error_class": "relay", "status_code": 302}, "relay_other"),
        ({"error_class": "relay", "status_code": 200, "error_type": "IncompleteRanking"},
         "relay_other"),
    ],
)
def test_outcome_precedence(fields, expected):
    assert outcome(_rec(**fields)) == expected
    assert outcome(_rec(**fields).model_dump()) == expected  # the dict form too


@pytest.mark.parametrize(
    ("error_type", "status", "expected"),
    [
        ("PoolTimeout", None, "local"),
        ("ConnectTimeout", None, "network"),
        ("ProxyError", None, "network"),
        ("JSONDecodeError", None, "relay_other"),
        ("ReadTimeout", None, "relay_other"),  # no timeout flag: just a relay failure
        ("http_error", 503, "relay_5xx"),
        ("http_error", 404, "relay_4xx"),
        (None, None, "relay_other"),
    ],
)
def test_outcome_of_an_old_record_without_error_class(error_type, status, expected):
    old = {"seq": 1, "ok": False, "error_type": error_type, "status_code": status}
    assert outcome(old) == expected
    assert outcome({"seq": 1, "ok": True}) == "success"
    assert outcome({"seq": 1, "ok": False, "status_code": 429}) == "rate_limited"


def test_outcome_leaves_out_records_that_never_count():
    assert outcome(_rec(retried=True, error_class="network")) is None
    assert outcome({"retried": True, "ok": True}) is None
    assert outcome(_rec(phase="param_retry", status_code=400, error_class="relay")) is None
    assert outcome({"phase": "param_retry", "ok": True}) is None
    assert outcome(_rec(phase="probe", ok=True)) == "success"


def test_outcomes_constant():
    assert OUTCOMES == ("success", "rate_limited", "relay_timeout", "relay_5xx", "relay_4xx",
                        "relay_other", "network", "local")


# --------------------------------------------------------------------------- #
# run_outcomes()
# --------------------------------------------------------------------------- #
def test_run_outcomes_counts_every_target_request():
    records = [
        _rec(1, ok=True),
        _rec(2, ok=True, op="list_models", phase="ping"),
        _rec(3, ok=True, phase="probe", stream=True),
        _rec(4, ok=True, phase="warmup"),
        _rec(5, error_class="relay", rate_limited=True, status_code=429, phase="probe_concurrent"),
        _rec(6, error_class="relay", timeout=True),
        _rec(7, error_class="relay", status_code=502),
        _rec(8, error_class="network", retried=True),  # superseded by its repeat
        _rec(9, error_class="network"),
        _rec(10, error_class="local", op="embed"),
        _rec(11, error_class="relay", status_code=400, phase="param_retry"),
        _rec(12, ok=True, endpoint="baseline"),
        _rec(13, error_class="relay", status_code=500, endpoint="baseline"),
    ]
    out = run_outcomes(records)
    assert out.requests_total == 9
    assert out.requests_judged == 7
    assert out.counts == {
        "success": 4, "rate_limited": 1, "relay_timeout": 1, "relay_5xx": 1, "relay_4xx": 0,
        "relay_other": 0, "network": 1, "local": 1,
    }
    assert out.by_op == {
        "complete": {"success": 3, "rate_limited": 1, "relay_timeout": 1, "relay_5xx": 1,
                     "network": 1},
        "embed": {"local": 1},
        "list_models": {"success": 1},
    }
    assert out.success_rate == pytest.approx(4 / 7)
    assert out.error_rate == pytest.approx(2 / 7)
    assert out.rate_limited_rate == pytest.approx(1 / 7)
    assert out.timeout_rate == pytest.approx(1 / 7)
    assert out.impaired_rate == pytest.approx(2 / 9)
    # the dict form gives the same
    assert run_outcomes([r.model_dump() for r in records]) == out


def test_rates_are_none_when_their_base_is_zero():
    empty = run_outcomes([])
    assert (empty.requests_total, empty.requests_judged) == (0, 0)
    assert empty.counts == dict.fromkeys(OUTCOMES, 0) and empty.by_op == {}
    assert (empty.success_rate, empty.error_rate, empty.rate_limited_rate, empty.timeout_rate,
            empty.impaired_rate) == (None, None, None, None, None)
    impaired = run_outcomes([_rec(1, error_class="network"), _rec(2, error_class="local")])
    assert (impaired.requests_total, impaired.requests_judged) == (2, 0)
    assert impaired.success_rate is None and impaired.error_rate is None
    assert impaired.impaired_rate == 1.0


def test_from_counts_drops_zero_and_unknown_outcomes():
    out = from_counts({"complete": {"success": 2, "relay_4xx": 0, "bogus": 5}, "embed": {}})
    assert out.by_op == {"complete": {"success": 2}}
    assert out.requests_total == 2 and out.success_rate == 1.0


def _random_record(rng: random.Random, seq: int) -> dict:
    rec: dict = {"seq": seq, "ok": rng.random() < 0.5}
    if rng.random() < 0.8:
        rec["error_class"] = rng.choice(["relay", "relay", "network", "local", None])
    rec["status_code"] = rng.choice([None, 200, 302, 400, 404, 429, 500, 503])
    rec["error_type"] = rng.choice([None, "http_error", "PoolTimeout", "ConnectTimeout",
                                    "JSONDecodeError", "ReadTimeout"])
    rec["timeout"] = rng.random() < 0.2
    rec["rate_limited"] = rng.random() < 0.15
    rec["retried"] = rng.random() < 0.1
    rec["phase"] = rng.choice(["passive", "probe", "warmup", "ping", "param_retry"])
    rec["op"] = rng.choice(["complete", "embed", "list_models"])
    rec["endpoint"] = rng.choice(["target", "target", "baseline"])
    return rec


@pytest.mark.parametrize("seed", range(200))
def test_rates_add_up_to_one(seed):
    rng = random.Random(seed)
    records = [_random_record(rng, i) for i in range(rng.randint(0, 60))]
    out = run_outcomes(records)
    assert sum(out.counts.values()) == out.requests_total
    assert sum(n for c in out.by_op.values() for n in c.values()) == out.requests_total
    assert out.requests_judged == out.requests_total - out.counts["network"] - out.counts["local"]
    if out.requests_judged > 0:
        assert out.success_rate is not None
        assert out.error_rate is not None
        assert out.rate_limited_rate is not None
        total = out.success_rate + out.error_rate + out.rate_limited_rate
        assert total == pytest.approx(1.0, abs=1e-9)
    else:
        assert out.success_rate is None


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
async def test_finished_audit_reports_its_outcomes(monkeypatch):
    server = MockServer()
    from ekte.clients import make_client as real

    monkeypatch.setattr(
        "ekte.runner.make_client", lambda config, **_: real(config, transport=server.transport)
    )
    target = TargetConfig(name="t", kind="target", base_url=BASE_URL, model=DEFAULT_MODEL)
    report = await run_audit(target, AuditOptions(suite="quick"))
    assert report.outcomes is not None
    records = report.performance.requests if report.performance else []
    assert report.outcomes == run_outcomes(records)
    assert report.outcomes.requests_total > 0
    doc = json.loads(report.model_dump_json())
    jsonschema.validate(doc, schemas.load("report"))
    assert doc["outcomes"]["requests_total"] == report.outcomes.requests_total


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


def _report_with_records() -> dict:
    """A saved report (fixture) with records of every outcome, as an older ekte
    wrote them: no ``outcomes`` section, some records without ``error_class``."""
    report = json.loads((FIXTURES / "history_report.json").read_text(encoding="utf-8"))
    extra = [
        {"seq": 900, "endpoint": "target", "ok": False, "status_code": 429, "rate_limited": True},
        {"seq": 901, "endpoint": "target", "ok": False, "timeout": True, "error_type": "ReadTimeout"},
        {"seq": 902, "endpoint": "target", "ok": False, "status_code": 503,
         "error_type": "http_error"},
        {"seq": 903, "endpoint": "target", "ok": False, "error_type": "ConnectTimeout"},
        {"seq": 904, "endpoint": "target", "ok": False, "error_type": "PoolTimeout",
         "op": "embed"},
        {"seq": 905, "endpoint": "target", "ok": False, "error_type": "ConnectError",
         "retried": True},
        {"seq": 906, "endpoint": "target", "ok": False, "status_code": 400,
         "phase": "param_retry"},
    ]
    report["performance"]["requests"].extend(extra)
    report.pop("outcomes", None)
    return report


def _stored(db: Path, rid: int) -> tuple[dict, dict]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM history_metrics WHERE history_id = ?", (rid,)).fetchone()
        metrics = {k: row[k] for k in row.keys() if k != "history_id"} if row else {}
        rows = conn.execute(
            "SELECT op, outcome, n FROM history_outcomes WHERE history_id = ?", (rid,)
        ).fetchall()
    return metrics, {(r["op"], r["outcome"]): r["n"] for r in rows}


def test_save_writes_outcome_rows_that_add_up(data):
    report = _report_with_records()
    rid = history.save(report)
    assert rid > 0
    metrics, rows = _stored(data / "history.db", rid)
    assert metrics["requests_total"] == sum(rows.values()) > 0
    expected = run_outcomes(report["performance"]["requests"])
    assert rows == {(op, o): n for op, c in expected.by_op.items() for o, n in c.items()}
    for key in ("success_rate", "error_rate", "rate_limited_rate", "timeout_rate",
                "impaired_rate", "requests_total", "requests_judged"):
        assert metrics[key] == pytest.approx(getattr(expected, key)), key
    assert rows[("embed", "local")] == 1
    # Deleting the run deletes its outcomes.
    history.delete(rid)
    assert _stored(data / "history.db", rid) == ({}, {})


def test_save_prefers_the_reports_own_outcomes(data):
    report = _report_with_records()
    report["outcomes"] = from_counts({"complete": {"success": 3, "relay_5xx": 1}}).model_dump()
    rid = history.save(report)
    metrics, rows = _stored(data / "history.db", rid)
    assert rows == {("complete", "success"): 3, ("complete", "relay_5xx"): 1}
    assert (metrics["requests_total"], metrics["success_rate"]) == (4, 0.75)
    # a damaged section: counted from the records instead
    report["outcomes"] = {"requests_total": "many"}
    metrics, _ = _stored(data / "history.db", history.save(report))
    assert metrics["requests_total"] == run_outcomes(report["performance"]["requests"]).requests_total


def test_backfill_of_a_v0_34_0_database_matches_a_fresh_save(data, monkeypatch):
    for name in ("history.db", "watches.db", "kb.db"):
        shutil.copy(V0340 / name, data / name)
    old = _report_with_records()
    split = _report_with_records()
    split["generated_at"] = "2026-11-01T10:00:00+00:00"
    db = data / "history.db"
    # As 0.34.0 left them: one run with inline records (not processed yet),
    # one whose records moved to history_requests, both extracted by version 3.
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        cur = conn.execute(
            "INSERT INTO history (ts, base_url, claimed_model, report_json) VALUES (?,?,?,?)",
            ("t", "https://relay.example.com/v1", "gpt-4o-mini", json.dumps(old)),
        )
        inline_id = int(cur.lastrowid)
        stored, rows = analytics_store.split_requests(split)
        assert rows is not None
        cur = conn.execute(
            "INSERT INTO history (ts, base_url, claimed_model, report_json, requests_split)"
            " VALUES (?,?,?,?,1)",
            ("t", "https://relay.example.com/v1", "gpt-4o-mini", json.dumps(stored)),
        )
        split_id = int(cur.lastrowid)
        cols = ("history_id", "ord", *analytics_store.REQUEST_FIELDS, "extra")
        conn.executemany(
            f"INSERT INTO history_requests ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [(split_id, i, *row) for i, row in enumerate(rows)],
        )
        conn.execute(
            "INSERT INTO history_metrics (history_id, extract_version) VALUES (?, 3)", (split_id,)
        )
        old_ids = [r[0] for r in conn.execute("SELECT id FROM history WHERE id < ?", (inline_id,))]

    history.init()  # migrates and backfills
    history.backfill_analytics()
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        versions = {r[0] for r in conn.execute("SELECT extract_version FROM history_metrics")}
    assert versions == {analytics_store.EXTRACT_VERSION}

    backfilled = {rid: _stored(db, rid) for rid in (*old_ids, inline_id, split_id)}
    # The same reports saved fresh by this version.
    fresh = {rid: _stored(db, history.save(history.get(rid))) for rid in backfilled}
    for rid, (metrics, rows) in backfilled.items():
        fresh_metrics, fresh_rows = fresh[rid]
        assert rows == fresh_rows, rid
        for key in ("success_rate", "error_rate", "rate_limited_rate", "timeout_rate",
                    "impaired_rate", "requests_total", "requests_judged"):
            assert metrics[key] == fresh_metrics[key], (rid, key)
    for rid in (inline_id, split_id):
        metrics, rows = backfilled[rid]
        assert metrics["requests_total"] == sum(rows.values()) > 0
