#!/usr/bin/env python3
"""Check the coverage floors (issue #32) against a coverage.py JSON report.

Run after ``pytest --cov=ekte --cov-report=json``; exits 1 when the whole
package or one of the named user-facing areas is below its floor. The floors
are set slightly under the values reached, so a drop is noticed without a
single refactor tripping the check; raise them when coverage improves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The whole package, in percent of statements.
PACKAGE_FLOOR = 93.0

# Area -> (files or directory prefixes, floor in percent).
AREAS: dict[str, tuple[tuple[str, ...], float]] = {
    "command line": (("ekte/cli.py", "ekte/clidocs.py", "ekte/__main__.py"), 90.0),
    "LLM judge": (("ekte/judge/",), 95.0),
    "media auditor (image, audio)": (("ekte/media_audit.py",), 95.0),
}


def _percent(files: dict[str, dict], prefixes: tuple[str, ...]) -> float | None:
    covered = statements = 0
    for name, data in files.items():
        if any(name.replace("\\", "/").startswith(p) for p in prefixes):
            summary = data["summary"]
            covered += summary["covered_lines"]
            statements += summary["num_statements"]
    return None if statements == 0 else 100.0 * covered / statements


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {path}: {exc}")
        return 2
    failed = False
    rows = [("whole package", data["totals"]["percent_covered"], PACKAGE_FLOOR)]
    for area, (prefixes, floor) in AREAS.items():
        percent = _percent(data["files"], prefixes)
        if percent is None:
            print(f"no coverage data for {area} ({', '.join(prefixes)})")
            failed = True
            continue
        rows.append((area, percent, floor))
    for area, percent, floor in rows:
        ok = percent >= floor
        failed = failed or not ok
        print(f"{'ok  ' if ok else 'FAIL'} {area}: {percent:.1f}% (floor {floor:.0f}%)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
