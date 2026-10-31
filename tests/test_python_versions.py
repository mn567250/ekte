"""The supported Python versions agree across metadata, classifiers and CI."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tuple(v: str) -> tuple[int, int]:
    major, minor = v.split(".")[:2]
    return int(major), int(minor)


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _classifier_versions() -> list[str]:
    return sorted(
        (
            c.rsplit(" ", 1)[1]
            for c in _project()["project"]["classifiers"]
            if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
        ),
        key=_tuple,
    )


def test_requires_python_is_lowest_classifier() -> None:
    spec = _project()["project"]["requires-python"]
    assert spec == f">={_classifier_versions()[0]}"


def test_ci_matrix_matches_classifiers() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    m = re.search(r"python-version: \[([^\]]+)\]", ci)
    assert m, "no python-version matrix in ci.yml"
    matrix = sorted(re.findall(r"\d+\.\d+", m.group(1)), key=_tuple)
    assert matrix == _classifier_versions()


def test_lint_and_type_targets_follow_minimum() -> None:
    low = _classifier_versions()[0]
    tool = _project()["tool"]
    assert tool["mypy"]["python_version"] == low
    assert tool["ruff"]["target-version"] == "py" + low.replace(".", "")
