#!/usr/bin/env python3
"""Render the performance budget results as a Markdown table.

The budget tests (``@pytest.mark.slow``, ``EKTE_BENCH=1``) write every case's
p50 / p95 and budget to the JSON file of ``EKTE_BENCH_REPORT``
(``tests/bench_report.py``). This script prints that file as a table (case,
p50, p95, budget, ✅ / ❌), or appends it to ``--out``; the "performance
budget" CI job passes ``--out "$GITHUB_STEP_SUMMARY"``. Standard library only::

    EKTE_BENCH=1 EKTE_BENCH_REPORT=bench.json pytest -m slow -p no:xdist tests
    python scripts/bench_report.py bench.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TITLE = "### Performance budget"


def _ms(value: float) -> str:
    return f"{value:.1f} ms"


def render(cases: list[dict[str, Any]], note: str = "") -> str:
    """The Markdown for ``cases`` (the report file's ``cases`` list)."""
    lines = [TITLE, ""]
    if note:
        lines += [note, ""]
    if not cases:
        lines.append("No results: the budget tests did not run or failed before reporting "
                     "(see the test step's log).")
        return "\n".join(lines) + "\n"
    over = [c for c in cases if not c.get("ok")]
    lines.append(f"**{len(over)} of {len(cases)} cases over budget.**" if over
                 else f"All {len(cases)} cases within budget (p95 below the budget).")
    lines += ["", "| suite | case | p50 | p95 | budget | |", "|---|---|--:|--:|--:|:-:|"]
    for c in cases:
        name = str(c.get("case", "")).replace("|", "\\|")
        lines.append(f"| {c.get('suite', '')} | {name} | {_ms(c['p50_ms'])} | {_ms(c['p95_ms'])} "
                     f"| {_ms(c['budget_ms'])} | {'✅' if c.get('ok') else '❌'} |")
    return "\n".join(lines) + "\n"


def load(path: Path) -> list[dict[str, Any]]:
    """The cases of the report file at ``path`` (none if it is missing or unreadable)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cases = data.get("cases") if isinstance(data, dict) else None
    return [c for c in cases if isinstance(c, dict)] if isinstance(cases, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("report", type=Path, help="the JSON file of EKTE_BENCH_REPORT")
    parser.add_argument("--out", type=Path, help="append the Markdown to this file (default: print it)")
    parser.add_argument("--note", default="", help="a line under the heading (e.g. which budget applies)")
    args = parser.parse_args(argv)
    text = render(load(args.report), args.note)
    if args.out:
        with args.out.open("a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
