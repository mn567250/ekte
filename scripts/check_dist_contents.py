#!/usr/bin/env python3
"""Check that the wheel and sdist ship no excluded third-party files.

Usage: python scripts/check_dist_contents.py [DIST_DIR]   (default: build with `uv build`)

Fails when an archive contains a file matching EXCLUDED, or a file that NOTICE
lists as not distributed, or when the wheel's long description (README.md, the
PyPI page) still has a link PyPI cannot resolve (scripts/hatch_readme.py).
"""
from __future__ import annotations

import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Vendored third-party files that must never be shipped (see pyproject.toml).
EXCLUDED = ("tests/a11y/vendor/*.js",)
_PATH_RE = re.compile(r"\b((?:tests|ekte|docs)/[\w./-]*\w\.\w+)")


def notice_undistributed(notice: str) -> list[str]:
    """Paths NOTICE names in a paragraph that says they are not distributed."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", notice):
        flat = " ".join(para.split())
        if re.search(r"\bnot (?:part of the distributed package|distributed)", flat):
            out += _PATH_RE.findall(flat)
    return out


def archive_members(path: Path) -> list[str]:
    """Member paths of a wheel or sdist (the sdist's top-level directory removed)."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as z:
            return z.namelist()
    with tarfile.open(path) as t:
        return [n.split("/", 1)[1] for n in t.getnames() if "/" in n]


def violations(members: list[str], notice: str) -> list[str]:
    patterns = list(EXCLUDED) + notice_undistributed(notice)
    return sorted({m for m in members if any(fnmatch(m, p) for p in patterns)})


def wheel_description(path: Path) -> str:
    """The long description (the body of METADATA) of a wheel."""
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        text = z.read(name).decode("utf-8")
    return text.split("\n\n", 1)[1] if "\n\n" in text else ""


def unresolvable_links(description: str) -> list[str]:
    """Relative links and in-page anchors in the PyPI description."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from hatch_readme import relative_links
    finally:
        sys.path.pop(0)
    return relative_links(description)


def main(argv: list[str]) -> int:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        dist = Path(argv[1]) if len(argv) > 1 else Path(tmp)
        if len(argv) <= 1:
            subprocess.run(["uv", "build", "--out-dir", str(dist)], cwd=ROOT, check=True)
        archives = sorted([*dist.glob("*.whl"), *dist.glob("*.tar.gz")])
        if len(archives) < 2:
            print(f"expected a wheel and an sdist in {dist}", file=sys.stderr)
            return 2
        bad = 0
        for a in archives:
            for m in violations(archive_members(a), notice):
                print(f"{a.name}: must not contain {m}", file=sys.stderr)
                bad += 1
            if a.suffix == ".whl":
                for link in unresolvable_links(wheel_description(a)):
                    print(f"{a.name}: description link {link} does not work on PyPI", file=sys.stderr)
                    bad += 1
    print("dist contents OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
