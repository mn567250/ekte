"""Per-step results of the accessibility suite (pytest plugin).

Every a11y test names the BITV 2.0 / EN 301 549 steps it decides with
``@pytest.mark.bitv("9.1.4.3", ...)`` (registered in pyproject.toml). With
``EKTE_A11Y_RESULTS=<path>`` set, this plugin writes, after the session, for
each step the tests that ran for it with their outcome and a short failure
summary. ``python -m tests.a11y.conformance --results <path>`` turns that into
the conformance report shown at ``/v2/accessibility``.

New test files need nothing beyond the marker: the plugin reads it from every
collected item, so tests added later are picked up automatically.

axe-core checks dozens of rules in one test, so a failing axe test must not
fail every step it covers. ``harness.run_axe`` notes each rule's outcome
(violation / pass / incomplete / inapplicable, by ``wcagXYZ`` tag) via
:func:`note_axe_run`; when a test failed *because of axe violations*, each of
its steps gets the outcome of the rules that map to it:

* a rule for the step reported a violation -> failed (with that rule's summary);
* rules for the step passed -> passed;
* rules for the step were only inapplicable/incomplete -> skipped (not decided).

A test that failed for any other reason fails every step it is marked with. A
passing test passes its steps, except steps whose axe rules were all
inapplicable or incomplete (nothing was checked) -> skipped. Tests marked
``bitv(..., axe=True)`` decide their steps through axe alone: a step without
a passing axe rule in that test (e.g. no tab panel to check) -> skipped. Works with and
without pytest-xdist (markers and rule outcomes travel in
``report.user_properties``).

This module must not import Playwright: it is loaded as a plugin even where
the browser tests are skipped.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from tests.a11y.bitv_map import criterion_of

RESULTS_ENV = "EKTE_A11Y_RESULTS"
SCHEMA = "ekte-a11y-results/1"

# axe best-practice rules carry no WCAG tag; these back a BITV step (the test
# using them is marked with that step). Unlisted best-practice rules count
# for no step.
BEST_PRACTICE_STEPS: dict[str, list[str]] = {
    "region": ["9.1.3.1", "9.2.4.1"],
    "skip-link": ["9.2.4.1"],
    "landmark-one-main": ["9.1.3.1", "9.2.4.1"],
    "landmark-no-duplicate-main": ["9.1.3.1"],
    "landmark-no-duplicate-banner": ["9.1.3.1"],
    "landmark-no-duplicate-contentinfo": ["9.1.3.1"],
    "landmark-main-is-top-level": ["9.1.3.1"],
    "landmark-banner-is-top-level": ["9.1.3.1"],
    "landmark-contentinfo-is-top-level": ["9.1.3.1"],
    "landmark-complementary-is-top-level": ["9.1.3.1"],
    "landmark-unique": ["9.1.3.1"],
    "heading-order": ["9.1.3.1"],
    "page-has-heading-one": ["9.1.3.1", "9.2.4.6"],
    "empty-heading": ["9.2.4.6"],
    "empty-table-header": ["9.1.3.1", "9.2.4.6"],
    "label-title-only": ["9.2.4.6"],
    "scope-attr-valid": ["9.1.3.1"],
    "table-duplicate-name": ["9.1.3.1"],
    "tabindex": ["9.2.4.3"],
}

_STEP = re.compile(r"^\d+(\.\d+)+$")
_AXE_FAILURE = "accessibility rule(s) violated on"
_RANK = {"violation": 3, "pass": 2, "incomplete": 1, "inapplicable": 0}

# rule outcomes of the axe runs of the test that is running (this process)
_AXE_RUNS: list[list[dict[str, Any]]] = []
_AXE_VERSION: list[str] = []


def note_axe_run(rules: list[dict[str, Any]], version: str | None = None) -> None:
    """Called by harness.run_axe with one entry per rule:
    {id, tags, outcome, impact, help, nodes, targets}."""
    _AXE_RUNS.append(rules)
    if version and not _AXE_VERSION:
        _AXE_VERSION.append(version)


def rule_steps(rule_id: str, tags: list[str]) -> list[str]:
    """BITV steps an axe rule decides: its wcagXYZ tags, or the best-practice map."""
    out = [f"9.{sc}" for sc in (criterion_of(t) for t in tags) if sc]
    for s in BEST_PRACTICE_STEPS.get(rule_id, []):
        if s not in out:
            out.append(s)
    return out


def steps_of(item: pytest.Item) -> list[str]:
    out: list[str] = []
    for m in item.iter_markers("bitv"):
        for s in m.args:
            s = str(s)
            if not _STEP.match(s):
                raise pytest.UsageError(f"{item.nodeid}: bitv marker needs step numbers like '9.1.4.3', got {s!r}")
            if s not in out:
                out.append(s)
    return out


def axe_only(item: pytest.Item) -> bool:
    """``@pytest.mark.bitv(..., axe=True)``: the test decides its steps only
    through axe rules (an axe-only test). A step then passes only when an axe
    rule for it passed; a run without axe (no tab panel to check, say) or
    without a rule for the step decides nothing."""
    return any(m.kwargs.get("axe") for m in item.iter_markers("bitv"))


def _merge_axe(runs: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """All axe runs of one test -> per rule: counts per outcome, worst outcome,
    help text and a few failing targets."""
    out: dict[str, Any] = {}
    for rules in runs:
        for r in rules:
            e = out.setdefault(
                r["id"],
                {"steps": rule_steps(r["id"], list(r.get("tags") or [])), "outcome": r["outcome"],
                 "counts": {}, "help": r.get("help") or "", "impact": r.get("impact"), "targets": []},
            )
            e["counts"][r["outcome"]] = e["counts"].get(r["outcome"], 0) + 1
            if _RANK[r["outcome"]] > _RANK[e["outcome"]]:
                e["outcome"] = r["outcome"]
            if r["outcome"] == "violation":
                e["impact"] = r.get("impact") or e["impact"]
                for t in r.get("targets") or []:
                    if t not in e["targets"] and len(e["targets"]) < 5:
                        e["targets"].append(t)
    return out


# --------------------------------------------------------------------------- #
# worker side: attach markers and axe outcomes to the reports
# --------------------------------------------------------------------------- #
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    if call.when == "setup":
        _AXE_RUNS.clear()
        steps = steps_of(item)
        if steps and not any(k == "bitv" for k, _ in item.user_properties):
            item.user_properties.append(("bitv", steps))
            if axe_only(item):
                item.user_properties.append(("bitv_axe_only", True))
    elif call.when == "call" and _AXE_RUNS:
        item.user_properties.append(("axe", _merge_axe(_AXE_RUNS)))
        if _AXE_VERSION:
            item.user_properties.append(("axe_version", _AXE_VERSION[0]))
        _AXE_RUNS.clear()
    yield


# --------------------------------------------------------------------------- #
# controller side: collect and write
# --------------------------------------------------------------------------- #
_TESTS: dict[str, dict[str, Any]] = {}
_META: dict[str, Any] = {}


def _message(report: pytest.TestReport) -> str:
    if report.skipped and isinstance(report.longrepr, tuple):
        return str(report.longrepr[2]).removeprefix("Skipped: ")
    crash = getattr(report.longrepr, "reprcrash", None)
    msg = getattr(crash, "message", None) or report.longreprtext or ""
    msg = re.sub(r"^\w*(Error|Exception): ", "", msg)
    msg = msg.split("\nassert ", 1)[0]
    return msg.strip()[:2000]


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not os.environ.get(RESULTS_ENV):
        return
    props = dict(report.user_properties)
    steps = props.get("bitv")
    if not steps:
        return
    rec = _TESTS.setdefault(
        report.nodeid,
        {"steps": list(steps), "outcome": None, "message": "", "axe": None, "axe_only": bool(props.get("bitv_axe_only"))},
    )
    if "axe" in props:
        rec["axe"] = props["axe"]
    if "axe_version" in props:
        _META.setdefault("axe_version", props["axe_version"])
    if report.failed:
        if rec["outcome"] != "failed":
            rec["outcome"] = "failed"
            rec["message"] = _message(report)
            rec["when"] = report.when
    elif report.skipped:
        if rec["outcome"] is None:
            rec["outcome"] = "skipped"
            rec["message"] = _message(report)
    elif report.when == "call" and rec["outcome"] is None:
        rec["outcome"] = "passed"


def _axe_message(rule_id: str, e: dict[str, Any]) -> str:
    n = e["counts"].get("violation", 0)
    where = ", ".join(e["targets"])
    return f"axe {rule_id} [{e.get('impact') or '?'}]: {e['help']} ({n} run(s) failing){': ' + where if where else ''}"


def step_outcomes(rec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One test record -> {step: {outcome, message}} (see the module docstring)."""
    outcome = rec["outcome"] or "skipped"
    axe = rec.get("axe") or {}
    axe_failure = outcome == "failed" and rec.get("when") == "call" and _AXE_FAILURE in (rec.get("message") or "")
    out: dict[str, dict[str, Any]] = {}
    for step in rec["steps"]:
        rules = {rid: e for rid, e in axe.items() if step in e["steps"]}
        if outcome == "skipped":
            out[step] = {"outcome": "skipped", "message": rec.get("message") or ""}
        elif outcome == "failed" and not axe_failure:
            out[step] = {"outcome": "failed", "message": rec.get("message") or ""}
        elif outcome == "failed" and axe_failure:
            bad = [rid for rid, e in rules.items() if e["outcome"] == "violation"]
            if bad:
                out[step] = {"outcome": "failed", "message": "\n".join(_axe_message(r, rules[r]) for r in sorted(bad))}
            elif any(e["outcome"] == "pass" for e in rules.values()):
                out[step] = {"outcome": "passed", "message": ""}
            else:
                out[step] = {"outcome": "skipped", "message": "no applicable axe rule for this step"}
        else:  # passed
            if rec.get("axe_only") and not any(e["outcome"] == "pass" for e in rules.values()):
                out[step] = {"outcome": "skipped", "message": "no axe rule for this step ran in this test"}
            elif rules and not any(e["outcome"] in ("pass", "violation") for e in rules.values()):
                out[step] = {"outcome": "skipped", "message": "no applicable axe rule for this step"}
            else:
                out[step] = {"outcome": "passed", "message": ""}
    return out


def build_results(tests: dict[str, dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    steps: dict[str, list[dict[str, Any]]] = {}
    rules: dict[str, dict[str, Any]] = {}
    for nodeid, rec in sorted(tests.items()):
        for step, res in step_outcomes(rec).items():
            steps.setdefault(step, []).append({"test": nodeid, **res})
        for rid, e in (rec.get("axe") or {}).items():
            g = rules.setdefault(rid, {"steps": e["steps"], "help": e["help"], "counts": {}})
            for k, v in e["counts"].items():
                g["counts"][k] = g["counts"].get(k, 0) + v
    return {
        "schema": SCHEMA,
        "generated_at": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        **meta,
        "tests": {nodeid: {"outcome": rec["outcome"] or "skipped", "steps": rec["steps"]} for nodeid, rec in sorted(tests.items())},
        "steps": dict(sorted(steps.items(), key=lambda kv: [int(x) for x in kv[0].split(".")])),
        "axe_rules": dict(sorted(rules.items())),
    }


def pytest_sessionfinish(session: pytest.Session) -> None:
    path = os.environ.get(RESULTS_ENV)
    if not path or hasattr(session.config, "workerinput") or not _TESTS:
        return
    meta = dict(_META)
    try:  # what was tested (harness needs playwright; without it nothing ran)
        from tests.a11y import harness

        meta.update(langs=list(harness.LANGS), themes=list(harness.THEMES), pages=dict(harness.PAGES))
    except BaseException:  # pytest.importorskip raises a BaseException
        pass
    data = build_results(_TESTS, meta)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
