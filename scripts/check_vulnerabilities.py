#!/usr/bin/env python3
"""Fail when a locked dependency has a known vulnerability.

Exports uv.lock to requirements, audits it with pip-audit and filters the result
through .github/vulnerability-ignores.yml (id + reason + expiry). Expired or
malformed ignores fail the check. Usage: python scripts/check_vulnerabilities.py
[--audit-json FILE] (the JSON option skips the export/audit and reads a saved
`pip-audit --format json` report, which is what the tests use).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
IGNORE_FILE = ROOT / ".github" / "vulnerability-ignores.yml"


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def load_ignores(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    entries = (data or {}).get("ignores") or []
    for e in entries:
        if not isinstance(e, dict) or not all(e.get(k) for k in ("id", "reason", "expires")):
            raise ValueError(f"ignore entry needs id, reason and expires: {e!r}")
        e["expires"] = _as_date(e["expires"])
    return entries


def evaluate(
    report: dict[str, Any], ignores: list[dict[str, Any]], today: dt.date
) -> tuple[list[str], list[str]]:
    """Return (problems, accepted). Problems make the check fail."""
    by_id = {e["id"]: e for e in ignores}
    problems: list[str] = []
    accepted: list[str] = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            ids = [vuln["id"], *vuln.get("aliases", [])]
            entry = next((by_id[i] for i in ids if i in by_id), None)
            label = f"{dep['name']} {dep['version']}: {vuln['id']}"
            fix = ", ".join(vuln.get("fix_versions") or []) or "no fix released"
            if entry is None:
                problems.append(f"{label} (fix: {fix})")
            elif entry["expires"] < today:
                problems.append(f"{label} ignore expired on {entry['expires']} ({entry['reason']})")
            else:
                accepted.append(f"{label} ignored until {entry['expires']}: {entry['reason']}")
    return problems, accepted


def run_audit() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        export = ["uv", "export", "--frozen", "--all-extras", "--no-emit-project", "--no-hashes"]
        req.write_text(
            subprocess.run(export, check=True, capture_output=True, text=True, cwd=ROOT).stdout
        )
        # pip-audit exits 1 when it finds vulnerabilities; the report is still printed
        proc = subprocess.run(
            ["pip-audit", "-r", str(req), "--no-deps", "--disable-pip", "-f", "json"],
            capture_output=True,
            text=True,
        )
        if not proc.stdout.strip():
            raise RuntimeError(f"pip-audit failed: {proc.stderr}")
        return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-json", type=Path, help="read a saved pip-audit JSON report")
    ap.add_argument("--ignores", type=Path, default=IGNORE_FILE)
    args = ap.parse_args(argv)
    report = json.loads(args.audit_json.read_text()) if args.audit_json else run_audit()
    problems, accepted = evaluate(report, load_ignores(args.ignores), dt.date.today())
    for line in accepted:
        print(f"ignored: {line}")
    for line in problems:
        print(f"VULNERABLE: {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
