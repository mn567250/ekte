"""Audit version vs scoring version of a re-scored run: Analytics, History,
the report view and the exports (#168 part B)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from ekte import dbmigrate, replay
from ekte.models import AuditReport
from ekte.report import render_pdf
from ekte.report.render import compact_dict, render_html, render_markdown
from ekte.web import analytics_store

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_report.json"
AUDIT, SCORING = "0.33.1", "0.35.0"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(data):
    from ekte.web.server import create_app

    return TestClient(create_app(), base_url="http://localhost")


def _report(version: str = AUDIT) -> dict:
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    report["tool_version"] = version
    report.pop("rescored_from", None)
    return report


def _rescored(report: dict, rid: int | None = None) -> dict:
    """``report`` re-scored by ekte SCORING: a stricter verdict, the old one kept."""
    v = report["verdict"]
    return {
        **report, "tool_version": SCORING, "generated_at": "2026-11-20T10:00:00+00:00",
        "verdict": {**v, "risk_level": "high", "overall_score": 41.5, "rating": "F"},
        "rescored_from": {
            "run_id": "run-1", "evidence_sha256": "0" * 64, "tool_version": AUDIT,
            "generated_at": report["generated_at"], "report_id": rid,
            "rescored_at": "2026-11-20T10:00:00+00:00",
            "previous_verdict": {"risk_level": v["risk_level"], "overall_score": v["overall_score"],
                                 "rating": v["rating"]},
        },
    }


def _saved_and_rescored() -> tuple[int, dict, dict]:
    from ekte.web import history

    before = _report()
    rid = history.save(before)
    after = _rescored(before, rid)
    assert history.replace(rid, after)
    return rid, before, after


def _metrics(rid: int) -> dict:
    from ekte.web import history

    with sqlite3.connect(history._db_path()) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute("SELECT * FROM history_metrics WHERE history_id = ?", (rid,)).fetchone())


# --------------------------------------------------------------------------- #
# Extraction and the analytics store
# --------------------------------------------------------------------------- #
def test_extract_reads_the_audit_version_and_the_previous_verdict():
    plain = analytics_store.extract_metrics(_report())[0]
    assert (plain["tool_version"], plain["audit_tool_version"]) == (AUDIT, AUDIT)
    assert plain["rescored_at"] is None and plain["previous_verdict"] is None
    m = analytics_store.extract_metrics(_rescored(_report()))[0]
    assert (m["tool_version"], m["audit_tool_version"]) == (SCORING, AUDIT)
    assert m["rescored_at"] == "2026-11-20T10:00:00+00:00"
    prev = json.loads(m["previous_verdict"])
    assert set(prev) == {"risk_level", "overall_score", "rating"}
    assert m["extract_version"] == analytics_store.EXTRACT_VERSION >= 5


def test_save_and_replace_keep_the_audit_version(data):
    from ekte.web import history

    rid = history.save(_report())
    assert _metrics(rid)["audit_tool_version"] == AUDIT
    history.replace(rid, _rescored(history.get(rid), rid))
    m = _metrics(rid)
    assert (m["tool_version"], m["audit_tool_version"]) == (SCORING, AUDIT)
    assert m["version_id"] != m["audit_version_id"]  # marked as re-scored by another version


# --------------------------------------------------------------------------- #
# Migration step 18
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 35), reason="needs ALTER TABLE DROP COLUMN")
def test_history_step_18_adds_the_audit_version_and_the_backfill_fills_it(data):
    from ekte.web import history, run_row

    db = data / "history.db"
    old = _rescored(_report())
    with sqlite3.connect(db) as c:
        for m in history.MIGRATIONS[:17]:
            m.apply(c)
        # history_metrics as schema 17 had it: no audit version, triggers and
        # run-row index without it
        for name in run_row._trigger_sql():
            c.execute(f"DROP TRIGGER {name}")
        c.execute("DROP INDEX idx_run_row")
        for col in ("audit_version_id", "audit_tool_version", "rescored_at", "previous_verdict"):
            c.execute(f"ALTER TABLE history_metrics DROP COLUMN {col}")
        c.execute("INSERT INTO history (ts, base_url, claimed_model, report_json, requests_split) "
                  "VALUES ('2026-01-01T00:00:00Z', 'https://x/v1', 'm', ?, 0)", (json.dumps(old),))
        c.execute("INSERT INTO history_metrics (history_id, tool_version, extract_version) VALUES (1, ?, 4)",
                  (SCORING,))
        c.execute("PRAGMA user_version = 17")
    history.init()
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == dbmigrate.latest(history.MIGRATIONS) >= 18
        cols = {r[1] for r in c.execute("PRAGMA table_info(history_metrics)")}
        assert {"audit_tool_version", "rescored_at", "previous_verdict", "audit_version_id"} <= cols
    m = _metrics(1)
    assert (m["tool_version"], m["audit_tool_version"]) == (SCORING, AUDIT)
    assert m["extract_version"] == analytics_store.EXTRACT_VERSION
    assert m["version_id"] is not None and m["version_id"] != m["audit_version_id"]
    assert history.get(1) == old  # the old record reads back unchanged


def test_history_step_18_from_a_database_before_the_run_row(data):
    """A database from before the run-row steps (11) gets the audit version too:
    the run-row triggers read it, so the steps that make them add it first."""
    from ekte.web import history

    db = data / "history.db"
    with sqlite3.connect(db) as c:
        for m in history.MIGRATIONS[:10]:
            m.apply(c)
        # history_metrics as schema 10 made it: without the columns of later steps
        c.execute("DROP TABLE history_metrics")
        cols = ", ".join(f"{k} {t}" for k, t in analytics_store.METRIC_COLS.items()
                         if k not in ("audit_tool_version", "rescored_at", "previous_verdict"))
        c.execute(f"CREATE TABLE history_metrics (history_id INTEGER PRIMARY KEY, {cols})")
        analytics_store.ensure_tables(c)  # its indexes
        c.execute("INSERT INTO history (ts, base_url, claimed_model, report_json, requests_split) "
                  "VALUES ('2026-01-01T00:00:00Z', 'https://x/v1', 'm', ?, NULL)", (json.dumps(_report()),))
        c.execute("PRAGMA user_version = 10")
    history.init()
    assert _metrics(1)["audit_tool_version"] == AUDIT


# --------------------------------------------------------------------------- #
# Analytics: filters, breakdown, marks
# --------------------------------------------------------------------------- #
def _get(client, path, params):
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, params) -> list[dict]:
    """History's run rows under ``params`` (one group of every run)."""
    out = _get(client, "/api/history/runs", {**params, "group": "all", "group.key": "(all)",
                                               "runs.limit": "200"})
    return out["rows"]


def test_audit_and_scoring_versions_differ(data, client):
    """After a re-score, Analytics returns the new score at the original time,
    and the audit and scoring versions differ (filters, breakdown, options)."""
    rid, before, after = _saved_and_rescored()
    from ekte.web import history

    plain = history.save(_report(SCORING))
    base = {"range": "", "surface": "chat"}
    # the new score, at the time of the audit
    board = _get(client, "/api/analytics/leaderboard", {**base, "board.by": "audit_version"})
    rows = {r["key"]: r for r in board["rows"]}
    assert set(rows) == {AUDIT, SCORING}
    assert rows[AUDIT]["metrics"]["score"]["value"] == 41.5
    assert rows[AUDIT]["first_run"] == _metrics(rid)["started_at"]
    assert rows[AUDIT]["rescored"] == 1 and rows[SCORING]["rescored"] == 0
    assert rows[AUDIT]["kind"] == "audit_version"
    # by scoring version both runs are one group, one of them re-scored
    board = _get(client, "/api/analytics/leaderboard", {**base, "board.by": "scoring_version"})
    assert [(r["key"], r["runs"], r["rescored"]) for r in board["rows"]] == [(SCORING, 2, 1)]
    # the filters
    for key, value, ids in (("scoring_version", SCORING, {rid, plain}), ("scoring_version", AUDIT, set()),
                            ("audit_version", AUDIT, {rid}), ("audit_version", SCORING, {plain}),
                            ("audit_version", "-", set())):
        out = _get(client, "/api/analytics/summary", {**base, key: value})
        assert out["filters"][key] == value
        assert {r["id"] for r in _runs(client, {**base, key: value})} == ids, (key, value)
    # the breakdown by version
    out = _get(client, "/api/analytics/breakdown", {**base, "breakdown.metric": "score",
                                                     "breakdown.by": "audit_version"})
    assert out["group"] == "audit_version" and {r["key"] for r in out["rows"]} == {AUDIT, SCORING}
    # the options of both filters
    opts = _get(client, "/api/filters/options", base)
    assert {o["value"]: o["runs"] for o in opts["scoring_version"]} == {SCORING: 2}
    assert {o["value"]: o["runs"] for o in opts["audit_version"]} == {AUDIT: 1, SCORING: 1}
    opts = _get(client, "/api/filters/options", {**base, "audit_version": AUDIT})
    assert {o["value"]: o["runs"] for o in opts["scoring_version"]} == {SCORING: 1}
    assert {o["value"] for o in opts["audit_version"]} == {AUDIT, SCORING}  # its own list stays whole


def test_version_filters_are_validated_and_canonical():
    from ekte.web import query

    q = query.parse_query({"audit_version": AUDIT, "scoring_version": "-"})
    assert q.canonical()["audit_version"] == AUDIT and q.canonical()["scoring_version"] == "-"
    assert query.parse_query(q.params()) == q
    with pytest.raises(query.QueryError):
        query.parse_query([("audit_version", "a"), ("audit_version", "b")])
    with pytest.raises(query.QueryError):  # not a grouping of the shared filters
        query.parse_query({"group": "audit_version"})


def test_runs_without_a_version_are_one_unknown_group(data, client):
    from ekte.web import history

    history.save({**_report(), "tool_version": None})
    history.save(_report())
    board = _get(client, "/api/analytics/leaderboard", {"range": "", "board.by": "scoring_version"})
    assert {r["key"]: r["runs"] for r in board["rows"]} == {"(unknown)": 1, AUDIT: 1}
    assert len(_runs(client, {"range": "", "scoring_version": "-"})) == 1


# --------------------------------------------------------------------------- #
# History list
# --------------------------------------------------------------------------- #
def _history_row(client, rid: int) -> dict:
    return next(r for r in _runs(client, {"range": ""}) if r["id"] == rid)


def test_history_rows_carry_both_versions_and_the_previous_verdict(data, client):
    from ekte.web import history

    rid, before, _ = _saved_and_rescored()
    plain = history.save(_report())
    row = _history_row(client, rid)
    assert (row["audit_version"], row["scoring_version"], row["rescored"]) == (AUDIT, SCORING, True)
    assert row["rescored_at"] == "2026-11-20T10:00:00+00:00"
    v = before["verdict"]
    assert row["previous_verdict"]["risk_level"] == v["risk_level"]
    assert row["previous_verdict"]["score"] == v["overall_score"]
    assert row["previous_verdict"]["grade"] == v["rating"]
    assert row["previous_verdict"]["family"]
    assert row["rescore_refusal"] is None
    other = _history_row(client, plain)
    assert (other["audit_version"], other["scoring_version"], other["rescored"]) == (AUDIT, AUDIT, False)
    assert other["previous_verdict"] is None and other["rescored_at"] is None


def test_history_rows_show_why_a_run_cannot_be_rescored(data, client):
    from ekte.web import history

    rid = history.save(_report())
    assert _history_row(client, rid)["rescore_refusal"] is None
    history.record_refusal(rid, SCORING, replay.NO_EVIDENCE)
    assert _history_row(client, rid)["rescore_refusal"] == {"reason": replay.NO_EVIDENCE, "version": SCORING}
    # a successful re-score drops the recorded reason
    history.replace(rid, _rescored(history.get(rid), rid))
    assert _history_row(client, rid)["rescore_refusal"] is None


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #
def test_exports_state_both_versions_the_time_and_the_previous_verdict():
    report = AuditReport.model_validate(_rescored(_report()))
    v = _report()["verdict"]
    line = f"Audit ran with ekte v{AUDIT}; re-scored with ekte v{SCORING} on 2026-11-20T10:00:00+00:00"
    md = render_markdown(report)
    assert line.replace(".", "\\.").replace("-", "\\-").replace("+", "\\+") in md or line in md
    assert "Before the re" in md and f"grade {v['rating']}" in md
    html = render_html(report)
    assert line in html and f"risk {v['risk_level']}" in html
    from tests.test_report_export import _text

    pdf = _text(render_pdf(report))
    assert f"re-scored with ekte v{SCORING}" in pdf and f"Audit ran with ekte v{AUDIT}" in pdf
    compact = compact_dict(report)
    assert compact["rescored"] == {
        "audit_version": AUDIT, "scoring_version": SCORING, "rescored_at": "2026-11-20T10:00:00+00:00",
        "previous_verdict": {"risk": v["risk_level"], "score": v["overall_score"], "rating": v["rating"]}}
    # a report never re-scored: no line, no key
    plain = AuditReport.model_validate(_report())
    assert "re-scored" not in render_html(plain) and "rescored" not in compact_dict(plain)


# --------------------------------------------------------------------------- #
# The report view (report.js) and History's "Re-score" action
# --------------------------------------------------------------------------- #
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")


@needs_node
@pytest.mark.parametrize("lang", ["en", "de", "zh"])
def test_report_view_states_both_versions(tmp_path, lang):
    from tests.test_web_v2_report_js import _render
    from tests.test_web_v2_report_js import _text as text_of

    out = _render(tmp_path, lang, _rescored(_report()))
    text = " ".join(text_of(out["html"]).split())
    assert f"v{AUDIT}" in text and f"v{SCORING}" in text
    if lang == "en":
        assert f"ekte v{AUDIT} · re-scored with v{SCORING}" in text
        assert "Verdict before the re-score" in text and "Re-scored on" in text
    if lang == "de":
        assert f"ekte v{AUDIT} · neu bewertet mit v{SCORING}" in text
    plain = " ".join(text_of(_render(tmp_path, lang, _report())["html"]).split())
    assert f"ekte v{AUDIT}" in plain and "re-scored with" not in plain


@needs_node
def test_report_view_explains_a_missing_action(tmp_path):
    from tests.test_web_v2_report_js import _render

    note = "Cannot be re-scored: this report kept no evidence: there is nothing to replay"
    out = _render(tmp_path, "en", _report(), {"note": note})
    assert '<p class="hint">' + note + "</p>" in out["html"]
    assert '<p class="hint">' not in _render(tmp_path, "en", _report())["html"]


def test_history_page_knows_the_no_evidence_text():
    """History explains the missing action with replay's own text (translated
    through the locales like the server's other texts)."""
    from ekte import i18n

    page = (Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2" / "history.html")
    assert json.dumps(replay.NO_EVIDENCE) in page.read_text(encoding="utf-8")
    strings = i18n._load()
    for reason in (replay.NO_EVIDENCE, replay.HASH_DIFFERS, replay.NO_OPTIONS, replay.NO_TARGET,
                   replay.UNREADABLE):
        for lang, d in strings.items():
            assert reason in d.get("strings", {}), (lang, reason)
