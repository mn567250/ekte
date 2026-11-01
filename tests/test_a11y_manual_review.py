"""The manual review worksheet (tests/a11y/manual_review.py) and how the
conformance report applies it (tests/a11y/conformance.py).

Pure Python (no browser).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.a11y import conformance, manual_review, results
from tests.a11y.bitv_map import catalogue
from tests.a11y.pages import PAGES

ROOT = Path(__file__).resolve().parents[1]
DEFS = manual_review.load_definitions()
CAT = catalogue()
PARTIAL = {s["step"] for s in CAT["steps"] if s["automation"] in ("partial", "manual")}


def _results(pending: tuple[str, ...] = ("9.1.3.1", "9.4.1.3")) -> dict[str, Any]:
    """Suite results where ``pending`` (partial steps) pass their automated
    part, so the report leaves them to a person."""
    tests = {
        f"tests/a11y/test_x.py::test_{i}": {"steps": [step], "outcome": "passed", "axe": None}
        for i, step in enumerate(pending)
    }
    meta = {"langs": ["en"], "themes": ["light"], "pages": dict(PAGES), "axe_version": "4.13.0"}
    return results.build_results(tests, meta)


def _report(pending: tuple[str, ...] = ("9.1.3.1", "9.4.1.3")) -> dict[str, Any]:
    return conformance.build_report(_results(pending), None)


def _fill(ws: dict[str, Any], session: str) -> None:
    ws["sessions"][session]["fill_in"].update(
        by="tester", date="2026-11-05", ekte_version="0.1.0", at_version="2026.3",
        browser_version="140", os_version="Windows 11",
    )


def _answer(ws: dict[str, Any], step: str, result: bool | None, reason: str | None = None,
            issue: str | None = None, only: str | None = None) -> None:
    for c in ws["checks"]:
        if c["step"] == step and (only is None or c["id"] == only):
            c.update(result=result, reason=reason, issue=issue)


def _by(rep: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["step"]: s for s in rep["steps"]}


# ---- the questions ----------------------------------------------------------


def test_every_partly_automatic_step_has_questions():
    assert set(DEFS["steps"]) == PARTIAL
    for step, d in DEFS["steps"].items():
        assert d["why"] and d["checks"], step
        ids = [q["id"] for q in d["checks"]]
        assert len(ids) == len(set(ids)), step
        for q in d["checks"]:
            assert q["pages"] and set(q["pages"]) <= set(PAGES), (step, q["id"])
            assert len(q["pages"]) == len(set(q["pages"])), (step, q["id"])
            assert q["sessions"] and set(q["sessions"]) <= set(DEFS["sessions"]), (step, q["id"])
            assert q["tools"] and q["do"] and q["expect"], (step, q["id"])
            assert set(q) <= {"id", "sessions", "pages", "tools", "do", "expect", *manual_review.CONDITIONS}


def test_sessions_name_their_setup():
    for sid, s in DEFS["sessions"].items():
        assert set(s) == {"label", "assistive_technology", "browser", "os", "input", "language", "theme"}, sid
        assert s["label"] and s["browser"] and s["os"], sid


def test_questions_apply_only_to_the_pages_they_name():
    """Checks are only generated for the pages a question lists, not for all."""
    checks = manual_review.all_checks(DEFS)
    tables = [c for c in checks if c["id"].endswith("/table-headers")]
    assert {c["page"] for c in tables} == {"audit", "analytics", "accessibility"}
    assert {c["page"] for c in checks if c["id"].endswith("/dialog-focus")} == {"monitors"}


# ---- preparing the worksheet ------------------------------------------------


def test_worksheet_covers_only_the_pending_steps():
    rep = _report(("9.1.3.1", "9.4.1.3"))
    ws = manual_review.build_worksheet(rep, DEFS)
    assert {c["step"] for c in ws["checks"]} == {"9.1.3.1", "9.4.1.3"}
    assert set(ws["sessions"]) == {"nvda-firefox", "voiceover-safari"}
    assert all(c[k] is None for c in ws["checks"] for k in manual_review.ANSWERS)
    assert all(v is None for s in ws["sessions"].values() for v in s["fill_in"].values())
    c = next(c for c in ws["checks"] if c["id"] == "9.1.3.1/kb/nvda-firefox/headings-landmarks")
    assert c["url"] == "http://127.0.0.1:8000/kb" and c["title"] == "Info and Relationships"
    assert manual_review.schema_errors(ws) == []
    assert manual_review.validate(ws, DEFS, manual_review.pending_steps(rep)) == ([], [])


def test_steps_the_llm_review_decided_are_not_in_the_worksheet():
    rep = _report(("9.1.1.1", "9.1.3.1"))
    llm = {"model": "m", "advisory": True, "status": "ok", "pages_reviewed": list(PAGES), "langs": ["en"],
           "steps": {"9.1.1.1": {"verdict": "ok", "findings": []}}}
    rep = conformance.apply_review(rep, llm)
    assert _by(rep)["9.1.1.1"]["status"] == "pass"
    ws = manual_review.build_worksheet(rep, DEFS)
    assert {c["step"] for c in ws["checks"]} == {"9.1.3.1"}


def test_checks_carry_their_conditions():
    ws = manual_review.build_worksheet(_report(("9.3.3.1", "9.1.4.11")), DEFS)
    by_id = {c["id"]: c for c in ws["checks"]}
    assert by_id["9.3.3.1/audit/nvda-firefox/audit-errors-de"]["lang"] == "de"
    assert by_id["9.1.4.11/analytics/desktop-browser/graphics-contrast-dark"]["theme"] == "dark"
    assert "lang" not in by_id["9.3.3.1/audit/nvda-firefox/audit-errors"]


# ---- validation -------------------------------------------------------------


def _ws(pending: tuple[str, ...] = ("9.1.3.1", "9.4.1.3")) -> tuple[dict[str, Any], list[str]]:
    rep = _report(pending)
    return manual_review.build_worksheet(rep, DEFS), manual_review.pending_steps(rep)


def test_answers_follow_the_rules():
    ws, pending = _ws()
    first = ws["checks"][0]
    first["result"] = True                       # answered before the session is filled in
    errors, _ = manual_review.validate(ws, DEFS, pending)
    assert any("fill in sessions/nvda-firefox/fill_in" in e for e in errors)
    _fill(ws, "nvda-firefox")
    assert manual_review.validate(ws, DEFS, pending)[0] == []
    first.update(result=False)                  # a failure needs its issue
    errors, _ = manual_review.validate(ws, DEFS, pending)
    assert any("follow-up issue" in e for e in errors)
    assert any(e.startswith("checks/0") for e in manual_review.schema_errors(ws))
    first.update(issue="https://github.com/mn567250/ekte/issues/99")
    assert manual_review.validate(ws, DEFS, pending)[0] == []
    first.update(result=True, reason="no table here")     # a reason only with null
    assert any("only for a check that does not apply" in e for e in manual_review.validate(ws, DEFS, pending)[0])
    first.update(result=None)                            # null + reason: does not apply
    assert manual_review.validate(ws, DEFS, pending)[0] == []
    first.update(result="yes", reason=None)
    assert any("true, false or null" in e for e in manual_review.validate(ws, DEFS, pending)[0])


def test_editing_a_question_is_an_error():
    ws, pending = _ws()
    for field, value in (("expect", "Something easier."), ("pages", None), ("tools", []), ("page", "kb")):
        bad = copy.deepcopy(ws)
        if value is None:
            bad["checks"][0].pop("page")
        else:
            bad["checks"][0][field] = value
        errors, _ = manual_review.validate(bad, DEFS, pending, schema=False)
        assert errors, field
    bad = copy.deepcopy(ws)
    bad["checks"].pop()                          # a removed check is missing ...
    assert manual_review.validate(bad, DEFS, pending)[0] == []
    assert any("missing" in w for w in manual_review.validate(bad, DEFS, pending)[1])
    assert any("missing" in e for e in manual_review.validate(bad, DEFS, pending, strict=True)[0])
    bad = copy.deepcopy(ws)                      # ... an invented one an error
    bad["checks"].append({**ws["checks"][0], "id": "9.1.3.1/kb/nvda-firefox/easy"})
    assert any("no such check" in e for e in manual_review.validate(bad, DEFS, pending, schema=False)[0])
    bad = copy.deepcopy(ws)
    bad["sessions"]["nvda-firefox"]["setup"]["assistive_technology"] = "JAWS"
    assert any("setup: differs" in e for e in manual_review.validate(bad, DEFS, pending)[0])


def test_strict_needs_every_check_answered():
    ws, pending = _ws(("9.4.1.3",))
    assert any("not done yet" in e for e in manual_review.validate(ws, DEFS, pending, strict=True)[0])
    for s in ws["sessions"]:
        _fill(ws, s)
    _answer(ws, "9.4.1.3", True)
    assert manual_review.validate(ws, DEFS, pending, strict=True) == ([], [])


def test_schema_rejects_typos():
    ws, _ = _ws()
    ws["checks"][0]["resutl"] = True
    assert any("resutl" in e for e in manual_review.schema_errors(ws))


# ---- merging ----------------------------------------------------------------


def test_merge_keeps_answers_of_unchanged_questions():
    old, _ = _ws(("9.1.3.1", "9.4.1.3"))
    _fill(old, "nvda-firefox")
    _answer(old, "9.1.3.1", True)
    _answer(old, "9.4.1.3", True)
    defs = copy.deepcopy(DEFS)
    q = next(q for q in defs["steps"]["9.1.3.1"]["checks"] if q["id"] == "table-headers")
    q["expect"] = "A stricter expectation."
    # 9.4.1.3 is no longer pending, 9.2.4.3 is new
    new = manual_review.build_worksheet(_report(("9.1.3.1", "9.2.4.3")), defs)
    merged, changes = manual_review.merge(old, new)
    by_id = {c["id"]: c for c in merged["checks"]}
    assert by_id["9.1.3.1/kb/nvda-firefox/headings-landmarks"]["result"] is True
    assert by_id["9.1.3.1/audit/nvda-firefox/table-headers"]["result"] is None    # question changed
    assert "9.1.3.1/audit/nvda-firefox/table-headers" in changes["reset"]
    assert all(c["step"] != "9.4.1.3" for c in merged["checks"])
    assert any(i.startswith("9.4.1.3/") for i in changes["dropped"])
    assert merged["sessions"]["nvda-firefox"]["fill_in"]["by"] == "tester"
    assert all(c["result"] is None for c in merged["checks"] if c["step"] == "9.2.4.3")


def test_cli_prepare_check_and_merge(tmp_path, capsys):
    rep = tmp_path / "bitv-report.json"
    rep.write_text(json.dumps(_report()), encoding="utf-8")
    ws_path = tmp_path / "ws.json"
    assert manual_review.main(["--prepare", "--report", str(rep), "--out", str(ws_path)]) == 0
    with pytest.raises(SystemExit):                     # never overwritten by accident
        manual_review.main(["--prepare", "--report", str(rep), "--out", str(ws_path)])
    assert manual_review.main(["--check", str(ws_path), "--report", str(rep)]) == 0
    assert manual_review.main(["--check", str(ws_path), "--report", str(rep), "--strict"]) == 1
    ws = json.loads(ws_path.read_text(encoding="utf-8"))
    _fill(ws, "nvda-firefox")
    _answer(ws, "9.1.3.1", True, only=ws["checks"][0]["id"])
    ws_path.write_text(json.dumps(ws), encoding="utf-8")
    assert manual_review.main(["--prepare", "--merge", "--report", str(rep), "--out", str(ws_path)]) == 0
    again = json.loads(ws_path.read_text(encoding="utf-8"))
    assert again["checks"][0]["result"] is True and again["sessions"]["nvda-firefox"]["fill_in"]["by"] == "tester"
    capsys.readouterr()
    assert manual_review.main(["--check", str(ws_path), "--report", str(rep)]) == 0
    out = capsys.readouterr()
    assert "1 of " in out.out and "another ekte version" in out.err   # tested 0.1.0, not this version


# ---- from checks to step status ---------------------------------------------


def test_summary_per_step():
    ws, _ = _ws(("9.1.3.1",))
    for s in ws["sessions"]:
        _fill(ws, s)
    s = manual_review.summarize(ws)["9.1.3.1"]
    assert s["status"] == "pending" and not s["counted"] and s["checks"]["open"] == s["checks"]["total"]
    _answer(ws, "9.1.3.1", True)
    assert manual_review.summarize(ws)["9.1.3.1"]["status"] == "pass"
    table = [c["id"] for c in ws["checks"] if c["id"].endswith("table-headers")]
    for cid in table:
        _answer(ws, "9.1.3.1", None, reason="no data table on this page", only=cid)
    s = manual_review.summarize(ws)["9.1.3.1"]
    assert s["status"] == "pass" and s["checks"]["n/a"] == len(table) and len(s["reasons"]) == len(table)
    _answer(ws, "9.1.3.1", False, issue="https://github.com/mn567250/ekte/issues/7", only=table[0])
    s = manual_review.summarize(ws)["9.1.3.1"]
    assert s["status"] == "fail" and s["issues"] == ["https://github.com/mn567250/ekte/issues/7"]
    _answer(ws, "9.1.3.1", None, reason="nothing to check")
    assert manual_review.summarize(ws)["9.1.3.1"]["status"] == "n/a"


def test_checks_of_an_unfilled_session_do_not_count():
    ws, _ = _ws(("9.1.3.1",))
    _fill(ws, "nvda-firefox")                     # voiceover-safari not filled in
    _answer(ws, "9.1.3.1", True)
    s = manual_review.summarize(ws)["9.1.3.1"]
    assert s["status"] == "pending" and s["sessions"] == ["nvda-firefox"]


def test_report_with_a_manual_review():
    rep = _report(("9.1.3.1", "9.4.1.3"))
    ws = manual_review.build_worksheet(rep, DEFS)
    applied = conformance.apply_review(rep, None, manual=ws)       # nothing done yet
    assert [s["status"] for s in applied["steps"]] == [s["status"] for s in rep["steps"]]
    assert applied["conformance"]["manual_review"] is False and applied["conformance"]["level"] is None
    assert _by(applied)["9.1.3.1"]["manual"]["status"] == "pending"
    assert applied["manual_review"]["checks"]["done"] == 0
    for s in ws["sessions"]:
        _fill(ws, s)
    _answer(ws, "9.1.3.1", True)
    _answer(ws, "9.4.1.3", False, issue="https://github.com/mn567250/ekte/issues/8")
    applied = conformance.apply_review(rep, None, manual=ws)
    by = _by(applied)
    assert by["9.1.3.1"]["status"] == "pass" and by["9.1.3.1"]["status_machine"] == "manual review pending"
    assert by["9.4.1.3"]["status"] == "fail" and by["9.4.1.3"]["status_tests"] == "manual review pending"
    assert by["9.4.1.3"]["manual"]["issues"] == ["https://github.com/mn567250/ekte/issues/8"]
    c = applied["conformance"]
    assert c["manual_review"] is True and c["status"] == "partially conformant" and c["level"] is None
    assert set(applied["manual_review"]["sessions"]) == {"nvda-firefox", "voiceover-safari"}
    assert applied["manual_review"]["sessions"]["nvda-firefox"]["by"] == "tester"
    assert applied["manual_review"]["steps_decided"] == ["9.1.3.1", "9.4.1.3"]
    # re-applying without the worksheet goes back to the machine statuses
    assert [s["status"] for s in conformance.apply_review(applied, None)["steps"]] == [s["status"] for s in rep["steps"]]


def test_a_failing_automated_part_is_not_overridden_by_a_person():
    res = _results(("9.1.3.1",))
    res["steps"]["9.1.3.1"][0]["outcome"] = "failed"
    rep = conformance.build_report(res, None)
    ws = manual_review.build_worksheet(_report(("9.1.3.1",)), DEFS)
    for s in ws["sessions"]:
        _fill(ws, s)
    _answer(ws, "9.1.3.1", True)
    assert _by(conformance.apply_review(rep, None, manual=ws))["9.1.3.1"]["status"] == "fail"


def test_full_conformance_needs_a_persons_review():
    """Every applicable step passing makes the report fully conformant (level
    AA) only with a person's review; the LLM review alone is not enough."""
    every = tuple(s["step"] for s in CAT["steps"] if s["automation"] != "n/a")
    res = _results(every)
    rep = conformance.build_report(res, None)
    pend = manual_review.pending_steps(rep)
    assert set(pend) == PARTIAL
    llm = {"model": "m", "advisory": True, "status": "ok", "pages_reviewed": list(PAGES), "langs": ["en"],
           "steps": {s: {"verdict": "ok", "findings": []} for s in PARTIAL}}
    only_llm = conformance.apply_review(rep, llm)
    assert all(s["status"] in ("pass", "n/a") for s in only_llm["steps"])
    assert only_llm["conformance"] == {"status": "partially conformant", "level": None,
                                       "manual_review": False, "llm_review": True}
    ws = manual_review.build_worksheet(rep, DEFS)
    for s in ws["sessions"]:
        _fill(ws, s)
    for step in PARTIAL:
        _answer(ws, step, True)
    full = conformance.apply_review(rep, llm, manual=ws)
    assert full["conformance"]["status"] == "fully conformant" and full["conformance"]["level"] == "AA"
    # a level AA step failing a check leaves level A
    aa = next(s["step"] for s in CAT["steps"] if s["step"] in PARTIAL and s["level"] == "AA")
    _answer(ws, aa, False, issue="https://github.com/mn567250/ekte/issues/9", only=next(
        c["id"] for c in ws["checks"] if c["step"] == aa))
    part = conformance.apply_review(rep, llm, manual=ws)
    assert part["conformance"]["status"] == "partially conformant" and part["conformance"]["level"] == "A"


def test_cli_applies_the_worksheet_and_refuses_an_edited_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    res = tmp_path / "res.json"
    res.write_text(json.dumps(_results(("9.1.3.1",))), encoding="utf-8")
    out = tmp_path / "bitv-report.json"
    ws = manual_review.build_worksheet(_report(("9.1.3.1",)), DEFS)
    for s in ws["sessions"]:
        _fill(ws, s)
    _answer(ws, "9.1.3.1", True)
    (tmp_path / "a11y-manual-review.json").write_text(json.dumps(ws), encoding="utf-8")   # picked up by default
    assert conformance.main(["--results", str(res), "--out", str(out)]) == 0
    assert _by(json.loads(out.read_text(encoding="utf-8")))["9.1.3.1"]["status"] == "pass"
    assert conformance.main(["--results", str(res), "--out", str(out), "--no-manual"]) == 0
    assert _by(json.loads(out.read_text(encoding="utf-8")))["9.1.3.1"]["status"] == "manual review pending"
    assert conformance.main(["--update", str(out)]) == 0                       # --update applies it too
    assert _by(json.loads(out.read_text(encoding="utf-8")))["9.1.3.1"]["status"] == "pass"
    ws["checks"][0]["expect"] = "Anything goes."
    (tmp_path / "a11y-manual-review.json").write_text(json.dumps(ws), encoding="utf-8")
    capsys.readouterr()
    assert conformance.main(["--results", str(res), "--out", str(out)]) == 1
    assert "do not edit the questions" in capsys.readouterr().err


# ---- docs and the committed files -------------------------------------------


def test_docs_tables():
    table = manual_review.docs_checks_table(DEFS, pending=["9.1.3.1"], titles={"9.1.3.1": "Info and Relationships"})
    assert "| 9.1.3.1 Info and Relationships | pending |" in table
    assert "decided without a person" in table
    assert "(no manual review recorded yet)" in manual_review.docs_results_table(None)
    ws, _ = _ws(("9.1.3.1",))
    _fill(ws, "nvda-firefox")
    _answer(ws, "9.1.3.1", True, only=ws["checks"][0]["id"])
    row = manual_review.docs_results_table(ws).splitlines()[2]
    assert row.startswith("| 9.1.3.1 | in progress | 1 of ") and "NVDA 2026.3, Firefox 140, Windows 11" in row
    assert "tester" in row and "2026-11-05" in row


def test_committed_worksheet_is_valid_and_current():
    """a11y-manual-review.json is the worksheet for the committed report:
    valid, unchanged by --prepare --merge, and applied to the report."""
    if not (ROOT / ".git").exists() and not (ROOT / "a11y-manual-review.json").exists():
        pytest.skip("the review files at the repository root are not part of the sdist")
    report = json.loads(conformance.DEFAULT_OUT.read_text(encoding="utf-8"))
    ws = manual_review.load(ROOT / "a11y-manual-review.json")
    pending = manual_review.pending_steps(report)
    errors, warnings = manual_review.validate(ws, DEFS, pending)
    assert errors == [] and warnings == []
    fresh, changes = manual_review.merge(ws, manual_review.build_worksheet(report, DEFS))
    assert changes["reset"] == [] and changes["dropped"] == []
    strip = lambda w: {k: v for k, v in w.items() if k != "generated_from"}  # noqa: E731
    assert strip(fresh) == strip(ws), "run python -m tests.a11y.manual_review --prepare --merge"
    llm = json.loads((ROOT / "a11y-llm-review.json").read_text(encoding="utf-8"))
    again = conformance.apply_review(report, llm, manual=ws)
    hint = "apply the reviews: python -m tests.a11y.conformance --update ekte/web/static/v2/bitv-report.json"
    assert again["steps"] == report["steps"], hint
    assert again["manual_review"] == report["manual_review"] and again["conformance"] == report["conformance"], hint
    assert report["manual_review"]["checks"]["total"] == len(ws["checks"])


def test_docs_are_current(tmp_path):
    doc = tmp_path / "accessibility.md"
    doc.write_text(conformance.DOCS.read_text(encoding="utf-8"), encoding="utf-8")
    assert conformance.update_docs(doc) is False, "run python -m tests.a11y.conformance --docs"
