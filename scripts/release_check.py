#!/usr/bin/env python3
"""Pre-release checks used by .github/workflows/release.yml (and runnable locally).

Subcommands (all exit non-zero with a message on stderr when a check fails;
`ci` exits 2 instead of 1 while CI is merely unfinished):

    release_check.py version  TAG [--pyproject pyproject.toml]
    release_check.py changelog TAG [--changelog CHANGELOG.md]
    release_check.py notes    TAG [--changelog CHANGELOG.md] [--output FILE]
    release_check.py prerelease TAG          # prints "true" / "false"
    release_check.py ci       CHECK_RUNS_JSON  # GitHub check-runs API response

Standard library only, so the workflow can run it before installing anything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# PEP 440 subset ekte uses: X.Y.Z with optional aN / bN / rcN pre-release.
_VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+\.\d+)(?P<pre>(?:a|b|rc)\d+)?$")

# Check-run names (prefixes) that must be green on the tagged commit.
REQUIRED_CHECKS = ("test (", "build distribution")


class ReleaseCheckError(Exception):
    """A release check failed; the message says why."""


class CIPendingError(ReleaseCheckError):
    """CI has not finished (or has not started) yet; retrying may help."""


def parse_tag(tag: str) -> str:
    """Return the PEP 440 version for a tag like ``v0.31.0rc1``."""
    version = tag.removeprefix("refs/tags/")
    if not version.startswith("v"):
        raise ReleaseCheckError(f"tag {tag!r} must start with 'v'")
    version = version[1:]
    if not _VERSION_RE.match(version):
        raise ReleaseCheckError(
            f"tag {tag!r} is not a valid version (expected vX.Y.Z, vX.Y.ZaN, vX.Y.ZbN or vX.Y.ZrcN)"
        )
    return version


def is_prerelease(version: str) -> bool:
    m = _VERSION_RE.match(version)
    return bool(m and m.group("pre"))


def package_version(pyproject: Path) -> str:
    # Regex instead of tomllib: CI also runs on Python 3.10, which lacks tomllib.
    text = pyproject.read_text(encoding="utf-8")
    project = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    m = project and re.search(r'^version\s*=\s*"([^"]+)"', project.group(1), re.MULTILINE)
    if not m:
        raise ReleaseCheckError(f"no [project] version found in {pyproject}")
    return m.group(1)


def check_version(tag: str, pyproject: Path) -> str:
    version = parse_tag(tag)
    actual = package_version(pyproject)
    if actual != version:
        raise ReleaseCheckError(
            f"tag {tag} does not match the package version {actual!r} in {pyproject}"
        )
    return version


_HEADING_RE = re.compile(r"^## \[(?P<name>[^\]]+)\][^\n]*$", re.MULTILINE)


def extract_section(changelog: str, version: str) -> str:
    """Return the body of the ``## [version]`` section (stripped), or raise.

    A pre-release (rcN) also accepts its final version's section, or
    ``[Unreleased]``, since the notes are written before the final release.
    """
    headings = list(_HEADING_RE.finditer(changelog))
    candidates = [version]
    m = _VERSION_RE.match(version)
    if m and m.group("pre"):
        candidates += [m.group("base"), "Unreleased"]
    for name in candidates:
        for i, h in enumerate(headings):
            if h.group("name").lower() != name.lower():
                continue
            end = headings[i + 1].start() if i + 1 < len(headings) else len(changelog)
            body = changelog[h.end():end].strip()
            if not body:
                raise ReleaseCheckError(f"CHANGELOG section [{name}] is empty")
            return body
    raise ReleaseCheckError(f"CHANGELOG.md has no section for version {version}")


def check_ci(check_runs: dict, required: tuple[str, ...] = REQUIRED_CHECKS) -> None:
    """Every required check must exist and have concluded ``success``.

    ``check_runs`` is the JSON of ``GET /repos/{o}/{r}/commits/{sha}/check-runs``.
    Where a check name appears more than once (re-runs), the latest run wins.
    """
    latest: dict[str, dict] = {}
    for run in check_runs.get("check_runs", []):
        prev = latest.get(run["name"])
        if prev is None or run.get("id", 0) > prev.get("id", 0):
            latest[run["name"]] = run
    failed: list[str] = []
    pending: list[str] = []
    for prefix in required:
        matching = {n: r for n, r in latest.items() if n.startswith(prefix)}
        if not matching:
            pending.append(f"no check run named '{prefix}*' found")
        for name, run in sorted(matching.items()):
            if run.get("status") != "completed":
                pending.append(f"'{name}' has not finished ({run.get('status')})")
            elif run.get("conclusion") != "success":
                failed.append(f"'{name}' concluded {run.get('conclusion')}")
    prefix_msg = "CI is not green for the tagged commit: "
    if failed:
        raise ReleaseCheckError(prefix_msg + "; ".join(failed + pending))
    if pending:
        raise CIPendingError(prefix_msg + "; ".join(pending))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("version")
    s.add_argument("tag")
    s.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    for name in ("changelog", "notes"):
        s = sub.add_parser(name)
        s.add_argument("tag")
        s.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
        if name == "notes":
            s.add_argument("--output", type=Path)
    s = sub.add_parser("prerelease")
    s.add_argument("tag")
    s = sub.add_parser("ci")
    s.add_argument("check_runs_json", type=Path)
    args = p.parse_args(argv)
    try:
        if args.cmd == "version":
            print(check_version(args.tag, args.pyproject))
        elif args.cmd in ("changelog", "notes"):
            version = parse_tag(args.tag)
            body = extract_section(args.changelog.read_text(encoding="utf-8"), version)
            if args.cmd == "notes":
                if args.output:
                    args.output.write_text(body + "\n", encoding="utf-8")
                else:
                    print(body)
        elif args.cmd == "prerelease":
            print("true" if is_prerelease(parse_tag(args.tag)) else "false")
        elif args.cmd == "ci":
            check_ci(json.loads(args.check_runs_json.read_text(encoding="utf-8")))
    except CIPendingError as exc:
        print(f"release check pending: {exc}", file=sys.stderr)
        return 2  # lets the workflow poll until CI finishes
    except (ReleaseCheckError, OSError, KeyError, ValueError) as exc:
        print(f"release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
