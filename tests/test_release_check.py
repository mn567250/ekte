"""Tests for scripts/release_check.py (the release workflow's pre-publish checks)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "release_check.py"
_spec = importlib.util.spec_from_file_location("release_check", _PATH)
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- upcoming thing

## [0.31.0] - 2026-11-01

### Fixed

- fix A

## [0.30.0] - 2026-10-01

- old
"""


def _pyproject(tmp_path, version):
    p = tmp_path / "pyproject.toml"
    p.write_text(f'[project]\nname = "ekte"\nversion = "{version}"\n')
    return p


@pytest.mark.parametrize("tag,ver", [("v0.31.0", "0.31.0"), ("refs/tags/v1.0.0rc2", "1.0.0rc2")])
def test_parse_tag_ok(tag, ver):
    assert rc.parse_tag(tag) == ver


@pytest.mark.parametrize("tag", ["0.31.0", "v1.0", "v1.0.0-rc1", "v1.0.0.dev1", "vx"])
def test_parse_tag_rejects(tag):
    with pytest.raises(rc.ReleaseCheckError):
        rc.parse_tag(tag)


def test_prerelease():
    assert rc.is_prerelease("1.0.0rc1")
    assert not rc.is_prerelease("1.0.0")


def test_version_match(tmp_path):
    assert rc.check_version("v0.31.0", _pyproject(tmp_path, "0.31.0")) == "0.31.0"


def test_version_mismatch(tmp_path):
    with pytest.raises(rc.ReleaseCheckError, match="does not match"):
        rc.check_version("v0.31.1", _pyproject(tmp_path, "0.31.0"))


def test_rc_tag_must_match_exactly(tmp_path):
    with pytest.raises(rc.ReleaseCheckError):
        rc.check_version("v0.31.0rc1", _pyproject(tmp_path, "0.31.0"))


def test_extract_section():
    assert rc.extract_section(CHANGELOG, "0.31.0") == "### Fixed\n\n- fix A"
    assert rc.extract_section(CHANGELOG, "0.30.0") == "- old"


def test_missing_section():
    with pytest.raises(rc.ReleaseCheckError, match="no section"):
        rc.extract_section(CHANGELOG, "0.32.0")


def test_prerelease_falls_back_to_base_then_unreleased():
    assert "fix A" in rc.extract_section(CHANGELOG, "0.31.0rc1")
    assert "upcoming thing" in rc.extract_section(CHANGELOG, "0.32.0rc1")


def test_empty_section():
    with pytest.raises(rc.ReleaseCheckError, match="empty"):
        rc.extract_section("## [1.0.0]\n\n## [0.9.0]\n- x\n", "1.0.0")


def _runs(*pairs, status="completed"):
    return {
        "check_runs": [
            {"id": i, "name": n, "status": status, "conclusion": c} for i, (n, c) in enumerate(pairs)
        ]
    }


GREEN = [("test (py3.10)", "success"), ("test (py3.13)", "success"), ("build distribution", "success")]


def test_ci_green():
    rc.check_ci(_runs(*GREEN, ("accessibility 1 (informational)", "failure")))


def test_ci_failure():
    with pytest.raises(rc.ReleaseCheckError, match="failure"):
        rc.check_ci(_runs(*GREEN[:2], ("build distribution", "failure")))


def test_ci_missing():
    with pytest.raises(rc.CIPendingError, match="no check run"):
        rc.check_ci(_runs(("test (py3.10)", "success")))


def test_ci_pending():
    with pytest.raises(rc.CIPendingError, match="not finished"):
        rc.check_ci(_runs(*GREEN, status="in_progress"))


def test_ci_latest_rerun_wins():
    data = _runs(("test (py3.10)", "failure"), ("test (py3.10)", "success"), ("build distribution", "success"))
    rc.check_ci(data)


def test_cli(tmp_path, capsys):
    py = _pyproject(tmp_path, "0.31.0")
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text(CHANGELOG)
    out = tmp_path / "notes.md"
    assert rc.main(["version", "v0.31.0", "--pyproject", str(py)]) == 0
    assert rc.main(["notes", "v0.31.0", "--changelog", str(cl), "--output", str(out)]) == 0
    assert out.read_text() == "### Fixed\n\n- fix A\n"
    assert rc.main(["changelog", "v0.40.0", "--changelog", str(cl)]) == 1
    assert rc.main(["prerelease", "v1.0.0rc1"]) == 0
    assert capsys.readouterr().out.strip().endswith("true")
    runs = tmp_path / "r.json"
    runs.write_text(json.dumps(_runs(*GREEN)))
    assert rc.main(["ci", str(runs)]) == 0
    runs.write_text(json.dumps(_runs(*GREEN, status="queued")))
    assert rc.main(["ci", str(runs)]) == 2
    runs.write_text(json.dumps(_runs(("test (py3.10)", "failure"), ("build distribution", "success"))))
    assert rc.main(["ci", str(runs)]) == 1
