"""The BITV conformance report: per-step results plugin and generator.

Pure Python (no browser): tests/a11y/results.py and tests/a11y/conformance.py.
"""

from __future__ import annotations

import datetime as dt
import json

from tests.a11y import conformance, results
from tests.a11y.bitv_map import CRITERIA, catalogue, criterion_of

CAT = catalogue()


def test_catalogue_is_the_wcag_21_a_aa_scope():
    steps = CAT["steps"]
    assert len(steps) == 50
    levels: dict[str, set[str]] = {}
    for s in steps:
        levels.setdefault(s["automation"], set()).add(s["wcag"])
        assert s["step"] == "9." + s["wcag"]
        assert s["title"] and s["how"] and s["level"] in ("A", "AA")
    assert levels["n/a"] == {"1.2.1", "1.2.2", "1.2.3", "1.2.4", "1.2.5", "1.4.2"}
    assert len(levels["auto"]) == 27 and len(levels["partial"]) == 17
    # bitv_map keeps its API and reads its titles from the catalogue
    assert CRITERIA["1.4.3"] == "Contrast (Minimum)" and criterion_of("wcag1410") == "1.4.10"


def _rule(rid, outcome, tags, help_="h"):
    return {"id": rid, "tags": tags, "outcome": outcome, "impact": "serious" if outcome == "violation" else None,
            "help": help_, "nodes": 1, "targets": ["#x"] if outcome == "violation" else []}


def test_axe_failure_fails_only_the_steps_of_the_violated_rule():
    axe = results._merge_axe([[
        _rule("color-contrast", "violation", ["wcag2aa", "wcag143"], "Contrast"),
        _rule("image-alt", "pass", ["wcag2a", "wcag111"]),
        _rule("meta-refresh", "inapplicable", ["wcag2a", "wcag221"]),
    ]])
    rec = {"steps": ["9.1.4.3", "9.1.1.1", "9.2.2.1"], "outcome": "failed", "when": "call", "axe": axe,
           "message": "1 accessibility rule(s) violated on kb [en, light] as loaded:"}
    out = results.step_outcomes(rec)
    assert out["9.1.4.3"]["outcome"] == "failed" and "color-contrast" in out["9.1.4.3"]["message"]
    assert out["9.1.1.1"]["outcome"] == "passed"
    assert out["9.2.2.1"]["outcome"] == "skipped"  # nothing was checked


def test_passing_axe_test_does_not_pass_steps_it_could_not_check():
    axe = results._merge_axe([[_rule("meta-refresh", "inapplicable", ["wcag2a", "wcag221"]),
                               _rule("image-alt", "pass", ["wcag2a", "wcag111"])]])
    out = results.step_outcomes({"steps": ["9.2.2.1", "9.1.1.1"], "outcome": "passed", "axe": axe})
    assert out["9.2.2.1"]["outcome"] == "skipped" and out["9.1.1.1"]["outcome"] == "passed"


def test_axe_only_test_without_axe_run_decides_nothing():
    # e.g. "every tab panel" on a page without tabs: no axe run, no verdict
    out = results.step_outcomes({"steps": ["9.1.4.3"], "outcome": "passed", "axe": None, "axe_only": True})
    assert out["9.1.4.3"]["outcome"] == "skipped"
    axe = results._merge_axe([[_rule("color-contrast", "pass", ["wcag2aa", "wcag143"])]])
    out = results.step_outcomes({"steps": ["9.1.4.3", "9.4.1.2"], "outcome": "passed", "axe": axe, "axe_only": True})
    assert out["9.1.4.3"]["outcome"] == "passed" and out["9.4.1.2"]["outcome"] == "skipped"


def test_non_axe_failure_fails_every_marked_step():
    rec = {"steps": ["9.2.1.1", "9.2.1.2"], "outcome": "failed", "when": "call", "axe": None,
           "message": "1 keyboard issue(s) on kb [en]:\n  not reachable with Tab: <button>"}
    out = results.step_outcomes(rec)
    assert {o["outcome"] for o in out.values()} == {"failed"}


def test_best_practice_rules_map_to_steps():
    assert "9.1.3.1" in results.rule_steps("heading-order", ["cat.semantics", "best-practice"])
    assert results.rule_steps("color-contrast", ["wcag2aa", "wcag143"]) == ["9.1.4.3"]
    assert results.rule_steps("color-contrast-enhanced", ["wcag2aaa", "wcag146"]) == []  # AAA: out of scope


def _results():
    tests = {
        "tests/a11y/test_axe.py::test_wcag[kb-en]": {"steps": ["9.1.4.3", "9.1.1.1"], "outcome": "passed", "axe": None},
        "tests/a11y/test_visual.py::test_reflow[de-kb]": {"steps": ["9.1.4.10"], "outcome": "failed", "when": "call",
                                                          "message": "page scrolls horizontally", "axe": None},
        "tests/a11y/test_visual.py::test_forced[kb]": {"steps": ["11.7"], "outcome": "passed", "axe": None},
    }
    meta = {"langs": ["en", "de"], "themes": ["light"], "pages": {"kb": "/kb"}, "axe_version": "4.13.0"}
    return results.build_results(tests, meta)


def test_report_statuses_totals_and_review_notes():
    llm = {"model": "x", "steps": {"1.1.1": {"verdict": "ok", "notes": ["alt texts fit"]}}}
    rep = conformance.build_report(_results(), llm, now=dt.datetime(2026, 10, 4, tzinfo=dt.UTC), commit="abc")
    by = {s["step"]: s for s in rep["steps"]}
    assert by["9.1.4.3"]["status"] == "pass"                      # auto, passed
    assert by["9.1.1.1"]["status"] == "manual review pending"     # partial, automated part passed
    assert by["9.1.4.10"]["status"] == "fail"
    assert by["9.1.4.10"]["failures"] == ["test_reflow[de-kb]: page scrolls horizontally"]
    assert by["9.2.1.1"]["status"] == "not tested"
    assert by["9.1.2.1"]["status"] == "n/a"
    assert by["9.1.1.1"]["review"]["notes"] == "alt texts fit"
    assert rep["review"] == {"model": "x"}
    assert rep["beyond"][0]["step"] == "11.7" and rep["beyond"][0]["status"] == "pass"
    t = rep["totals"]
    assert t["applicable"] == 44 and t["automation"]["auto"]["count"] == 27
    assert t["automation"]["auto"]["percent"] == 61.4
    assert t["status"]["fail"]["count"] == 1
    assert t["tests"] == {"run": 3, "passed": 2, "failed": 1, "skipped": 0}
    assert rep["conformance"]["status"] == "partially conformant"
    assert rep["commit"] == "abc" and rep["axe_version"] == "4.13.0" and rep["tested"]["languages"] == ["en", "de"]
    json.dumps(rep)


def test_report_without_results_is_honest():
    rep = conformance.build_report(None)
    assert {s["status"] for s in rep["steps"]} == {"not tested", "n/a"}


def test_cli_writes_the_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no a11y-llm-review.json picked up
    res = tmp_path / "res.json"
    res.write_text(json.dumps(_results()), encoding="utf-8")
    out = tmp_path / "bitv-report.json"
    assert conformance.main(["--results", str(res), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["totals"]["steps"] == 50


def test_shard_results_merge_into_the_results_of_one_run(tmp_path, monkeypatch):
    """CI runs the suite as parallel shards (EKTE_A11Y_SHARD); merging their
    results must give exactly what one run over every test writes."""
    monkeypatch.chdir(tmp_path)  # no a11y-llm-review.json picked up
    axe = results._merge_axe([[_rule("color-contrast", "pass", ["wcag2aa", "wcag143"])]])
    axe2 = results._merge_axe([[_rule("color-contrast", "violation", ["wcag2aa", "wcag143"]),
                                _rule("image-alt", "pass", ["wcag2a", "wcag111"])]])
    tests = {
        "tests/a11y/test_axe.py::test_wcag[kb-en]": {"steps": ["9.1.4.3"], "outcome": "passed", "axe": axe},
        "tests/a11y/test_axe.py::test_wcag[kb-de]": {
            "steps": ["9.1.4.3", "9.1.1.1"], "outcome": "failed", "when": "call", "axe": axe2,
            "message": "1 accessibility rule(s) violated on kb [de, light] as loaded:"},
        "tests/a11y/test_visual.py::test_reflow[de-kb]": {"steps": ["9.1.4.10"], "outcome": "failed", "when": "call",
                                                          "message": "page scrolls horizontally", "axe": None},
        "tests/a11y/test_visual.py::test_forced[kb]": {"steps": ["11.7", "9.1.4.3"], "outcome": "passed", "axe": None},
    }
    meta = {"langs": ["en", "de"], "themes": ["light"], "pages": {"kb": "/kb"}, "axe_version": "4.13.0"}
    names = sorted(tests)
    # dealt like the conftest does: shard k of n takes every n-th test
    parts = [results.build_results({t: tests[t] for t in names[k::2]}, meta) for k in range(2)]
    whole = results.build_results(tests, meta)
    merged = conformance.merge_results(parts)
    for d in (whole, merged):
        d.pop("generated_at")
    assert merged == whole

    # and through the CLI, from one file per shard
    files = []
    for k, part in enumerate(parts):
        f = tmp_path / f"a11y-results-{k}.json"
        f.write_text(json.dumps(part), encoding="utf-8")
        files.append(str(f))
    out = tmp_path / "bitv-report.json"
    assert conformance.main(["--results", *files, "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    one = conformance.build_report(results.build_results(tests, meta), None, commit=rep["commit"])
    for r in (rep, one):
        r.pop("generated_at"), r.pop("tests_run_at")
    assert rep == one


def test_docs_table_lists_every_step_and_marked_tests():
    marked = conformance.marked_tests()
    # the axe tests are marked through the AXE_WCAG_STEPS tuple
    assert "test_wcag_rules_as_loaded" in marked["9.1.4.3"]
    assert "test_reflow_at_320_css_px" in marked["9.1.4.10"]
    table = conformance.docs_table()
    assert all(f"| {s['step']} |" in table for s in CAT["steps"])


# --------------------------------------------------------------------------- #
# a review of the texts written by tests/a11y/llm_review.py
# --------------------------------------------------------------------------- #
def _llm_review(status="ok", verdicts=None, pages=("kb",), langs=("en", "de")):
    verdicts = verdicts or {}
    finding = {"page": "kb", "lang": "de", "element": 'link "Mehr"', "problem": "unclear", "suggestion": "Name it"}
    steps = {
        s: {"title": s, "verdict": verdicts.get(s, "ok"), "findings": [finding] if verdicts.get(s) == "issues" else []}
        for s in ("9.1.1.1", "9.1.3.3", "9.2.4.4", "9.2.4.6", "9.3.3.2", "9.3.3.3", "translation")
    }
    return {"generated_at": "2026-10-13T00:00:00+00:00", "model": "claude-opus-5-5", "advisory": True,
            "status": status, "pages_reviewed": list(pages), "langs": list(langs),
            "endpoint": {"base_url": "http://localhost:11434/v1", "api": "openai", "source": "cli"},
            "pages": [], "steps": steps}


def _by(rep):
    return {s["step"]: s for s in rep["steps"]}


def test_llm_review_counts_as_the_manual_part():
    rep = conformance.build_report(_results(), _llm_review(verdicts={"9.2.4.4": "issues", "translation": "issues"}))
    by = _by(rep)
    assert by["9.1.1.1"]["status"] == "pass"                     # partial, tests passed, review ok
    assert by["9.1.1.1"]["review"] == {"verdict": "ok", "notes": "", "by": "claude-opus-5-5", "counted": True}
    assert by["9.2.4.4"]["status"] == "fail"                     # review found an issue
    assert by["9.2.4.4"]["review"]["notes"] == 'kb [de] link "Mehr": unclear → Name it'
    assert by["9.3.3.3"]["status"] == "not tested"               # no automated test ran: review alone decides nothing
    assert by["9.1.4.10"]["status"] == "fail" and "review" not in by["9.1.4.10"]
    # the LLM review counts for its steps but is not a manual review by a person
    assert rep["conformance"]["llm_review"] is True and rep["conformance"]["manual_review"] is False
    assert rep["review"]["method"] == "llm" and rep["review"]["model"] == "claude-opus-5-5" and rep["review"]["counted"]
    assert rep["review"]["translation"]["verdict"] == "issues"
    assert "localhost" not in json.dumps(rep)                    # the endpoint stays out of the published report


def test_failed_tests_are_not_overridden_by_the_review():
    res = _results()
    res["steps"]["9.1.1.1"][0]["outcome"] = "failed"
    assert _by(conformance.build_report(res, _llm_review()))["9.1.1.1"]["status"] == "fail"


def test_incomplete_llm_review_changes_no_status():
    plain = _by(conformance.build_report(_results(), None))
    # a step only partly reviewed
    rep = conformance.build_report(_results(), _llm_review(verdicts={"9.1.1.1": "partial"}))
    assert _by(rep)["9.1.1.1"]["status"] == plain["9.1.1.1"]["status"] == "manual review pending"
    assert _by(rep)["9.1.1.1"]["review"]["counted"] is False
    # a review of fewer languages than were tested
    rep = conformance.build_report(_results(), _llm_review(langs=("en",)))
    assert _by(rep)["9.1.1.1"]["status"] == "manual review pending"
    assert rep["review"]["counted"] is False and rep["conformance"]["llm_review"] is False


def test_skipped_or_failed_llm_review_is_ignored():
    plain = conformance.build_report(_results(), None, commit="c", now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    for status in ("skipped: no API key", "error", "dry-run", "skipped: browser harness unavailable"):
        rep = conformance.build_report(_results(), _llm_review(status=status), commit="c",
                                       now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        assert rep == plain, status


def test_cli_picks_up_the_llm_review_in_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = tmp_path / "res.json"
    res.write_text(json.dumps(_results()), encoding="utf-8")
    out = tmp_path / "bitv-report.json"
    assert conformance.main(["--results", str(res), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["review"] is None    # no file: as before
    (tmp_path / "a11y-llm-review.json").write_text(json.dumps(_llm_review()), encoding="utf-8")
    assert conformance.main(["--results", str(res), "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert _by(rep)["9.1.1.1"]["status"] == "pass" and rep["conformance"]["llm_review"] is True
    assert conformance.main(["--results", str(res), "--out", str(out), "--no-llm"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["review"] is None


def test_a_review_applied_to_a_built_report_equals_building_with_it():
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    llm = _llm_review(verdicts={"9.2.4.4": "issues"})
    built = conformance.build_report(_results(), llm, now=now, commit="c")
    applied = conformance.apply_review(conformance.build_report(_results(), None, now=now, commit="c"), llm)
    assert applied == built


def test_a_newer_review_replaces_the_older_one():
    base = conformance.build_report(_results(), None)
    first = conformance.apply_review(base, _llm_review(verdicts={"9.1.1.1": "issues"}))
    assert _by(first)["9.1.1.1"]["status"] == "fail" and _by(first)["9.1.1.1"]["status_tests"] == "manual review pending"
    second = conformance.apply_review(first, _llm_review())
    assert second == conformance.apply_review(base, _llm_review())
    assert _by(second)["9.1.1.1"]["status"] == "pass"
    # an unusable review, or none, goes back to the tests alone
    for llm in (None, _llm_review(status="error")):
        back = conformance.apply_review(first, llm)
        assert back == base
    assert base["totals"]["status"]["fail"]["count"] == 1     # 9.1.4.10 only


def test_long_review_notes_are_cut_at_a_line_and_counted():
    many = [{"page": "kb", "lang": "de", "element": f'link "{i}"', "problem": "p" * 80} for i in range(200)]
    llm = _llm_review(verdicts={"9.2.4.4": "issues"})
    llm["steps"]["9.2.4.4"]["findings"] = many
    r = _by(conformance.build_report(_results(), llm))["9.2.4.4"]["review"]
    assert r["count"] == 200 and r["notes"].endswith("\n…") and len(r["notes"]) <= conformance.MAX_NOTES + 2
    assert all(line.startswith("kb [de]") for line in r["notes"].split("\n")[:-1])


def test_cli_update_reapplies_the_review_to_an_existing_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rep = tmp_path / "bitv-report.json"
    rep.write_text(json.dumps(conformance.build_report(_results(), None)), encoding="utf-8")
    review = tmp_path / "review.json"
    review.write_text(json.dumps(_llm_review(verdicts={"9.2.4.4": "issues"})), encoding="utf-8")
    assert conformance.main(["--update", str(rep), "--llm", str(review)]) == 0
    out = json.loads(rep.read_text(encoding="utf-8"))
    assert _by(out)["9.2.4.4"]["status"] == "fail" and out["review"]["model"] == "claude-opus-5-5"
    # a report committed before status_tests existed works too
    old = conformance.build_report(_results(), None)
    for s in old["steps"]:
        s.pop("status_tests")
    rep.write_text(json.dumps(old), encoding="utf-8")
    assert conformance.main(["--update", str(rep), "--llm", str(review)]) == 0
    assert _by(json.loads(rep.read_text(encoding="utf-8")))["9.1.1.1"]["status"] == "pass"
