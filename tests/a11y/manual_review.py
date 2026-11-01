"""Worksheet for the manual part of the BITV / EN 301 549 test steps.

    python -m tests.a11y.manual_review --prepare [--merge] [--report R] [--out F]
    python -m tests.a11y.manual_review --check [F] [--strict] [--report R]

The automated suite and the LLM review of the texts (tests/a11y/llm_review.py)
leave some partly automatic steps "manual review pending": a person still has
to judge the rest. ``--prepare`` reads the conformance report
(``ekte/web/static/v2/bitv-report.json``) and the questions per step
(``tests/a11y/manual-checks.json``) and writes a worksheet
(``a11y-manual-review.json``): one check per pending step, question, page and
session, with the tools, what to do and what to expect, and empty results.

The person fills in, once per session, who did it, when and with which versions
(``fill_in``), and per check:

- ``"result": true``: the expectation holds;
- ``"result": false``: it does not; ``issue`` links the follow-up issue;
- ``"result": null`` with a ``reason``: the check does not apply;
- ``"result": null`` without a reason: not done yet.

``--check`` validates a worksheet against ``tests/a11y/manual-review.schema.json``
and against the questions (a changed, added or removed question is an error, so
a step cannot pass on a weakened question); ``--strict`` also requires every
pending check to be answered. ``--prepare --merge`` regenerates the worksheet
and keeps the answers of the checks whose question did not change.

``python -m tests.a11y.conformance`` applies a worksheet to the report
(``--manual``, default ``./a11y-manual-review.json`` when it exists); see
:func:`summarize` for how checks decide a step.

Standard library only, except for the JSON Schema validation of ``--check``,
which needs ``jsonschema`` (in the dev extra).
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from tests.a11y.pages import PAGES

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECKS_FILE = HERE / "manual-checks.json"
SCHEMA_FILE = HERE / "manual-review.schema.json"
REPORT_FILE = ROOT / "ekte" / "web" / "static" / "v2" / "bitv-report.json"
DEFAULT_WORKSHEET = Path("a11y-manual-review.json")
SCHEMA_REF = "./tests/a11y/manual-review.schema.json"
SCHEMA_VERSION = "1.0"
BASE_URL = "http://127.0.0.1:8000"

PENDING = "manual review pending"
# fields --prepare writes and the person must not change
GENERATED = ("id", "step", "title", "page", "url", "session", "lang", "theme", "width", "zoom", "tools", "do", "expect")
ANSWERS = ("result", "reason", "issue", "notes")
CONDITIONS = ("lang", "theme", "width", "zoom")
FILL_IN = ("by", "date", "ekte_version", "at_version", "browser_version", "os_version")
# fill_in fields a session needs before its checks count (at_version only with an AT)
FILL_IN_REQUIRED = ("by", "date", "ekte_version", "browser_version")


def load_definitions(path: Path = CHECKS_FILE) -> dict[str, Any]:
    """The questions per step (tests/a11y/manual-checks.json)."""
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _session_setup(defn: dict[str, Any]) -> dict[str, Any]:
    keys = ("label", "assistive_technology", "browser", "os", "input", "language", "theme")
    return {k: defn.get(k) for k in keys}


def all_checks(defs: dict[str, Any], titles: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every check the questions define, for every step (pending or not), in
    worksheet order: by session, then step, question and page. ``titles``:
    step -> title (from the report or the catalogue)."""
    titles = titles or {}
    out: list[dict[str, Any]] = []
    steps = sorted(defs["steps"], key=lambda s: [int(x) for x in s.split(".")])
    for session in defs["sessions"]:
        for step in steps:
            for q in defs["steps"][step]["checks"]:
                if session not in q["sessions"]:
                    continue
                for page in q["pages"]:
                    c: dict[str, Any] = {
                        "id": f"{step}/{page}/{session}/{q['id']}",
                        "step": step,
                        "title": titles.get(step, ""),
                        "page": page,
                        "url": BASE_URL + PAGES[page],
                        "session": session,
                    }
                    for k in CONDITIONS:
                        if q.get(k):
                            c[k] = q[k]
                    c.update(tools=list(q["tools"]), do=q["do"], expect=q["expect"])
                    c.update(dict.fromkeys(ANSWERS))
                    out.append(c)
    return out


def pending_steps(report: dict[str, Any]) -> list[str]:
    """Steps the report leaves to a person: "manual review pending" from the
    tests and the LLM review alone (``status_machine``), so applying a
    worksheet to the report does not change what the worksheet covers."""
    return [s["step"] for s in report["steps"] if s.get("status_machine", s["status"]) == PENDING]


def _titles(report: dict[str, Any]) -> dict[str, str]:
    return {s["step"]: s.get("title", "") for s in report.get("steps", [])}


def build_worksheet(report: dict[str, Any], defs: dict[str, Any] | None = None) -> dict[str, Any]:
    """A worksheet with empty results for the report's pending steps."""
    defs = defs or load_definitions()
    pending = set(pending_steps(report))
    checks = [c for c in all_checks(defs, _titles(report)) if c["step"] in pending]
    used = [s for s in defs["sessions"] if any(c["session"] == s for c in checks)]
    return {
        "$schema": SCHEMA_REF,
        "schema_version": SCHEMA_VERSION,
        "about": "Manual review of web UI v2 (docs/dev/accessibility.md, Manual review). Fill in fill_in per session and"
                 " result per check: true = holds, false = fails (give issue), null + reason = not applicable,"
                 " null without reason = not done yet. Do not change the other fields.",
        "generated_from": {
            "commit": report.get("commit"),
            "ekte_version": report.get("ekte_version"),
            "tests_run_at": report.get("tests_run_at"),
        },
        "setup": defs["setup"],
        "sessions": {
            s: {"setup": _session_setup(defs["sessions"][s]), "fill_in": dict.fromkeys(FILL_IN)} for s in used
        },
        "checks": checks,
    }


def merge(old: dict[str, Any], new: dict[str, Any]) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """``new`` with the answers of ``old`` kept where the question did not
    change. Returns (worksheet, {"kept": ids, "reset": ids, "dropped": ids}):
    reset = the question changed, so its answer was dropped; dropped = the
    check no longer exists (its step passed, failed or its question was
    removed). Session fill_in is kept for sessions that still exist."""
    out = copy.deepcopy(new)
    before = {c.get("id"): c for c in old.get("checks", []) if isinstance(c, dict)}
    kept: list[str] = []
    reset: list[str] = []
    for c in out["checks"]:
        o = before.get(c["id"])
        if o is None or not _answered(o):
            continue
        if all(o.get(k) == c.get(k) for k in GENERATED if k != "title"):
            c.update({k: o.get(k) for k in ANSWERS})
            kept.append(c["id"])
        else:
            reset.append(c["id"])
    ids = {c["id"] for c in out["checks"]}
    dropped = [i for i, c in before.items() if i not in ids and _answered(c)]
    for s, sess in out["sessions"].items():
        old_fill = ((old.get("sessions") or {}).get(s) or {}).get("fill_in")
        if isinstance(old_fill, dict):
            sess["fill_in"].update({k: old_fill.get(k) for k in FILL_IN})
    return out, {"kept": kept, "reset": reset, "dropped": sorted(i for i in dropped if i)}


def _answered(c: dict[str, Any]) -> bool:
    return c.get("result") is not None or bool(c.get("reason"))


def session_complete(ws: dict[str, Any], session: str) -> bool:
    s = (ws.get("sessions") or {}).get(session) or {}
    fill = s.get("fill_in") or {}
    need = list(FILL_IN_REQUIRED) + (["at_version"] if (s.get("setup") or {}).get("assistive_technology") else [])
    return all(fill.get(k) for k in need)


def schema_errors(ws: Any) -> list[str]:
    """JSON Schema errors of a worksheet (needs jsonschema)."""
    import jsonschema

    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errs = sorted(validator.iter_errors(ws), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errs]


def validate(
    ws: Any,
    defs: dict[str, Any] | None = None,
    pending: list[str] | None = None,
    strict: bool = False,
    schema: bool = True,
) -> tuple[list[str], list[str]]:
    """(errors, warnings) of a worksheet.

    Errors: JSON Schema (when ``schema`` and jsonschema is installed); a check
    whose generated fields differ from its question, or that no question
    defines; a session setup that differs; an answered check of a session
    whose fill_in is incomplete; the answer rules (false needs an issue, a
    reason only with null). With ``pending`` (the report's pending steps):
    a pending check missing from the worksheet is a warning, or an error with
    ``strict``, which also makes a check not done yet an error."""
    defs = defs or load_definitions()
    errors: list[str] = []
    warnings: list[str] = []
    if schema:
        try:
            errors += schema_errors(ws)
        except ImportError:
            warnings.append("jsonschema is not installed: the JSON Schema was not checked (pip install -e '.[dev]')")
    if not isinstance(ws, dict) or not isinstance(ws.get("checks"), list) or not isinstance(ws.get("sessions"), dict):
        return errors or ["not a worksheet: needs 'sessions' (object) and 'checks' (list)"], warnings
    expected = {c["id"]: c for c in all_checks(defs)}
    seen: set[str] = set()
    for s, sess in ws["sessions"].items():
        if s not in defs["sessions"]:
            errors.append(f"sessions/{s}: no such session in {CHECKS_FILE.name}")
        elif not isinstance(sess, dict) or sess.get("setup") != _session_setup(defs["sessions"][s]):
            errors.append(f"sessions/{s}/setup: differs from {CHECKS_FILE.name}; do not edit it (run --prepare --merge)")
    for c in ws["checks"]:
        if not isinstance(c, dict):
            errors.append("checks: every entry must be an object")
            continue
        cid = str(c.get("id"))
        if cid in seen:
            errors.append(f"{cid}: listed twice")
        seen.add(cid)
        want = expected.get(cid)
        if want is None:
            errors.append(f"{cid}: no such check in {CHECKS_FILE.name} (run --prepare --merge)")
            continue
        changed = [k for k in GENERATED if k != "title" and c.get(k) != want.get(k)]
        if changed:
            errors.append(f"{cid}: {', '.join(changed)} changed; do not edit the questions (run --prepare --merge)")
        result, reason, issue = c.get("result"), c.get("reason"), c.get("issue")
        if result not in (True, False, None):
            errors.append(f"{cid}: result must be true, false or null")
        if result is False and not issue:
            errors.append(f"{cid}: a failed check needs the URL of its follow-up issue in 'issue'")
        if result is not None and reason:
            errors.append(f"{cid}: 'reason' is only for a check that does not apply (result null)")
        if _answered(c) and c.get("session") not in ws["sessions"]:
            errors.append(f"{cid}: session {c.get('session')!r} is missing from 'sessions'")
        elif _answered(c) and not session_complete(ws, str(c.get("session"))):
            errors.append(f"{cid}: fill in sessions/{c.get('session')}/fill_in (by, date, versions) first")
    if pending is not None:
        pend = set(pending)
        missing = [i for i, c in expected.items() if c["step"] in pend and i not in seen]
        if missing:
            msg = f"{len(missing)} pending check(s) missing from the worksheet, e.g. {missing[0]} (run --prepare --merge)"
            (errors if strict else warnings).append(msg)
        extra = sorted({c.get("step") for c in ws["checks"] if isinstance(c, dict) and c.get("step") not in pend})
        if extra:
            warnings.append(f"steps no longer pending in the report: {', '.join(str(s) for s in extra)}"
                            " (their checks change nothing; --prepare --merge removes them)")
    if strict:
        todo = [c.get("id") for c in ws["checks"] if isinstance(c, dict) and not _answered(c)]
        if todo:
            errors.append(f"{len(todo)} check(s) not done yet, e.g. {todo[0]}")
    return errors, warnings


def stale_sessions(ws: dict[str, Any], version: str | None) -> list[str]:
    """Sessions that tested another ekte version than ``version``."""
    out = []
    for s, sess in (ws.get("sessions") or {}).items():
        v = ((sess or {}).get("fill_in") or {}).get("ekte_version")
        if v and version and v != version:
            out.append(f"{s} (tested {v})")
    return out


def summarize(ws: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """step -> the manual result of the step from its checks.

    A check counts only when its session's fill_in is complete. Per step:
    any failed check -> "fail"; else any check not done -> "pending"; else
    "pass" when at least one check holds, "n/a" when none applies."""
    if not ws:
        return {}
    by_step: dict[str, list[dict[str, Any]]] = {}
    for c in ws.get("checks") or []:
        by_step.setdefault(str(c["step"]), []).append(c)
    out: dict[str, dict[str, Any]] = {}
    for step, checks in by_step.items():
        counts = {"total": len(checks), "pass": 0, "fail": 0, "n/a": 0, "open": 0}
        issues: list[str] = []
        failures: list[str] = []
        reasons: list[str] = []
        used: list[str] = []
        for c in checks:
            done = _answered(c) and session_complete(ws, c["session"])
            if not done:
                counts["open"] += 1
                continue
            if c["session"] not in used:
                used.append(c["session"])
            if c["result"] is True:
                counts["pass"] += 1
            elif c["result"] is False:
                counts["fail"] += 1
                if c.get("issue") and c["issue"] not in issues:
                    issues.append(c["issue"])
                failures.append(f"{c['page']} ({c['session']}): {c.get('notes') or c['expect']}")
            else:
                counts["n/a"] += 1
                reasons.append(f"{c['page']} ({c['session']}): {c['reason']}")
        if counts["fail"]:
            status = "fail"
        elif counts["open"]:
            status = "pending"
        else:
            status = "pass" if counts["pass"] else "n/a"
        out[step] = {
            "status": status,
            "counted": status != "pending",
            "checks": counts,
            "issues": issues,
            "failures": failures,
            "reasons": reasons,
            "sessions": used,
        }
    return out


def session_records(ws: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The sessions with at least one counted check: setup and fill_in."""
    if not ws:
        return {}
    used = {s for r in summarize(ws).values() for s in r["sessions"]}
    return {
        s: {**sess["setup"], **sess["fill_in"]}
        for s, sess in (ws.get("sessions") or {}).items()
        if s in used
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def docs_checks_table(defs: dict[str, Any] | None = None, pending: list[str] | None = None,
                      titles: dict[str, str] | None = None) -> str:
    """Markdown table of the questions per step (docs/dev/accessibility.md)."""
    defs = defs or load_definitions()
    pend = set(pending or [])
    titles = titles or {}
    rows = ["| Step | Now | Why a person | Check | Sessions | Pages | Do | Expect |",
            "|---|---|---|---|---|---|---|---|"]
    for step in sorted(defs["steps"], key=lambda s: [int(x) for x in s.split(".")]):
        d = defs["steps"][step]
        now = "pending" if step in pend else "decided without a person"
        for i, q in enumerate(d["checks"]):
            cond = ", ".join(f"{k} {q[k]}" for k in CONDITIONS if q.get(k))
            head = (f"{step} {titles.get(step, '')}".strip(), now, d["why"]) if i == 0 else ("", "", "")
            rows.append("| " + " | ".join(_cell(x) for x in (
                *head,
                f"`{q['id']}`" + (f" ({cond})" if cond else ""),
                ", ".join(q["sessions"]),
                ", ".join(q["pages"]),
                q["do"] + " Tools: " + "; ".join(q["tools"]) + ".",
                q["expect"],
            )) + " |")
    return "\n".join(rows)


def docs_results_table(ws: dict[str, Any] | None) -> str:
    """Markdown table of the recorded results per step and session."""
    rows = ["| Step | Result | Checks done | Sessions | By | Date |", "|---|---|---|---|---|---|"]
    summary = summarize(ws)
    sessions = (ws or {}).get("sessions") or {}
    done_any = False
    for step in sorted(summary, key=lambda s: [int(x) for x in s.split(".")]):
        r = summary[step]
        c = r["checks"]
        if c["open"] == c["total"]:
            continue
        done_any = True
        result = {"pass": "pass", "fail": "fail: " + ", ".join(r["issues"]), "n/a": "n/a: " + "; ".join(r["reasons"]),
                  "pending": "in progress"}[r["status"]]
        fills = [sessions[s]["fill_in"] for s in r["sessions"]]
        setups = [
            ", ".join(x for x in (
                f"{sessions[s]['setup']['assistive_technology']} {sessions[s]['fill_in']['at_version']}"
                if sessions[s]["setup"]["assistive_technology"] else "",
                f"{sessions[s]['setup']['browser'].split(' (')[0]} {sessions[s]['fill_in']['browser_version']}",
                f"{sessions[s]['fill_in']['os_version'] or sessions[s]['setup']['os']}",
            ) if x)
            for s in r["sessions"]
        ]
        rows.append("| " + " | ".join(_cell(x) for x in (
            step, result, f"{c['total'] - c['open']} of {c['total']}", "; ".join(setups),
            ", ".join(sorted({str(f["by"]) for f in fills})), ", ".join(sorted({str(f["date"]) for f in fills})),
        )) + " |")
    if not done_any:
        rows.append("| (no manual review recorded yet) | | | | | |")
    return "\n".join(rows)


def load(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def write(path: Path, ws: dict[str, Any]) -> None:
    path.write_text(json.dumps(ws, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _ekte_version() -> str | None:
    try:
        from ekte import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001 - only a hint
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.a11y.manual_review", description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="write the worksheet for the report's pending steps")
    mode.add_argument("--check", nargs="?", const=str(DEFAULT_WORKSHEET), metavar="WORKSHEET",
                      help=f"validate a worksheet (default: ./{DEFAULT_WORKSHEET})")
    ap.add_argument("--merge", action="store_true", help="with --prepare: keep the answers of an existing worksheet")
    ap.add_argument("--force", action="store_true", help="with --prepare: overwrite an existing worksheet")
    ap.add_argument("--strict", action="store_true", help="with --check: every pending check must be answered")
    ap.add_argument("--report", type=Path, default=REPORT_FILE,
                    help=f"conformance report (default: {REPORT_FILE.relative_to(ROOT)})")
    ap.add_argument("--out", type=Path, default=DEFAULT_WORKSHEET, help=f"worksheet to write (default: ./{DEFAULT_WORKSHEET})")
    args = ap.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    defs = load_definitions()
    if args.prepare:
        ws = build_worksheet(report, defs)
        if args.out.exists() and args.merge:
            ws, changes = merge(load(args.out), ws)
            for kind in ("reset", "dropped"):
                for cid in changes[kind]:
                    print(f"{kind}: {cid}", file=sys.stderr)
            print(f"kept {len(changes['kept'])} answer(s), reset {len(changes['reset'])}, dropped {len(changes['dropped'])}")
        elif args.out.exists() and not args.force:
            ap.error(f"{args.out} exists: --merge keeps its answers, --force overwrites it")
        write(args.out, ws)
        steps = sorted({c["step"] for c in ws["checks"]}, key=lambda s: [int(x) for x in s.split(".")])
        print(f"wrote {args.out}: {len(ws['checks'])} checks for {len(steps)} pending step(s) in {len(ws['sessions'])} session(s)")
        return 0
    path = Path(args.check)
    try:
        ws = load(path)
    except (OSError, ValueError) as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1
    errors, warnings = validate(ws, defs, pending_steps(report), strict=args.strict)
    stale = stale_sessions(ws, _ekte_version())
    if stale:
        warnings.append("sessions of another ekte version, repeat them if the UI changed: " + ", ".join(stale))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    s = summarize(ws)
    done = sum(r["checks"]["total"] - r["checks"]["open"] for r in s.values())
    total = sum(r["checks"]["total"] for r in s.values())
    decided = sorted(k for k, r in s.items() if r["counted"])
    print(f"{path}: {done} of {total} checks done; steps decided: {', '.join(decided) or 'none'}"
          + (f"; {len(errors)} error(s)" if errors else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
