"""Which a11y pages a change affects: ``python -m tests.a11y.affected``.

Prints ``{"pages": [...], "full": bool, "reason": "..."}`` for the files
changed between two commits (``--base A --head B``: ``git diff A...B``, i.e.
since their merge base), for files given on the command line (``--files``),
or one per line on stdin (``--files -``). ``--full REASON`` skips the diff and
selects every page (CI: pushes, nightly and manual runs).

``pages`` is empty when no changed file can affect web UI v2; ``full`` means
every page (the complete suite). The mapping is in tests/a11y/pages.py. When
the diff cannot be computed the result is a full run, never an empty one.

``--github-output`` also writes ``pages`` (comma list), ``full``, ``reason``,
``run`` (any page selected) and ``matrix`` (JSON for a job matrix, see
:func:`tests.a11y.pages.matrix`) to ``$GITHUB_OUTPUT``.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from tests.a11y.pages import Scope, affected, full_scope, matrix


def changed_files(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def scope_from_args(args: argparse.Namespace) -> Scope:
    if args.full:
        return full_scope(args.full)
    if args.files is not None:
        files = sys.stdin.read().splitlines() if args.files == ["-"] else args.files
        return affected(files)
    if not (args.base and args.head):
        return full_scope("no --base/--head or --files given")
    try:
        return affected(changed_files(args.base, args.head))
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        return full_scope(f"git diff {args.base}...{args.head} failed ({detail.strip()[:200]}); running everything")


def github_output(scope: Scope, path: str) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"pages={','.join(scope.pages)}\n")
        fh.write(f"full={'true' if scope.full else 'false'}\n")
        fh.write(f"run={'true' if scope.pages else 'false'}\n")
        fh.write(f"reason={' '.join(scope.reason.split())}\n")
        fh.write(f"matrix={json.dumps({'include': matrix(scope)})}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.a11y.affected", description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="base commit (e.g. the PR's base sha)")
    ap.add_argument("--head", help="head commit (e.g. the PR's head sha)")
    ap.add_argument("--files", nargs="+", help="changed paths instead of a git diff; '-' reads them from stdin")
    ap.add_argument("--full", metavar="REASON", help="select every page, for this reason")
    ap.add_argument("--github-output", action="store_true", help="also write the outputs to $GITHUB_OUTPUT")
    args = ap.parse_args(argv)
    scope = scope_from_args(args)
    print(json.dumps(scope.as_dict()))
    if args.github_output:
        target = os.environ.get("GITHUB_OUTPUT")
        if not target:
            ap.error("--github-output needs $GITHUB_OUTPUT")
        github_output(scope, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
