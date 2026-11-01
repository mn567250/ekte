#!/usr/bin/env python3
"""Write (or with --check, verify) docs/reference/cli.md, generated from the CLI's own help."""

from __future__ import annotations

import sys
from pathlib import Path

from ekte import clidocs

DOC = Path(__file__).resolve().parent.parent / "docs" / "reference" / "cli.md"


def main(argv: list[str]) -> int:
    text = clidocs.render()
    if "--check" in argv:
        if not DOC.exists() or DOC.read_text("utf-8") != text:
            print("docs/reference/cli.md is stale: run scripts/generate_cli_docs.py")
            return 1
        return 0
    DOC.write_text(text, encoding="utf-8")
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
