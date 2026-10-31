"""The CI and release workflows stay hardened (offline checks).

The workflow linter (zizmor) runs in CI; these tests keep the core rules
enforced locally too: SHA-pinned actions, declared permissions, no credential
persistence, timeouts, and a publishing job that is isolated and minimal.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _uses(path: Path) -> list[str]:
    # line-based so the version comment is visible
    return [
        line.split("uses:", 1)[1].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*(-\s+)?uses:", line)
    ]


def test_workflows_exist() -> None:
    assert {p.name for p in WORKFLOWS} >= {"ci.yml", "release.yml"}


@pytest.mark.parametrize("path", [*WORKFLOWS, ROOT / "action.yml"], ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_full_sha_with_version_comment(path: Path) -> None:
    for ref in _uses(path):
        target, _, comment = ref.partition("#")
        target = target.strip()
        if target.startswith("./"):  # this repository's own action
            continue
        assert SHA_PIN.match(target), f"{path.name}: {target} is not pinned to a commit SHA"
        assert re.match(r"v?\d+(\.\d+)*", comment.strip()), f"{path.name}: {target} lacks a version comment"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_permissions_are_declared_and_minimal(path: Path) -> None:
    wf = _load(path)
    assert "permissions" in wf, "declare workflow-level permissions"
    top = wf["permissions"] or {}
    assert top in ({}, {"contents": "read"})
    for name, job in wf["jobs"].items():
        perms = job.get("permissions", top) or {}
        if "id-token" in perms:
            assert (path.name, name) == ("release.yml", "publish")
        writes = {k for k, v in perms.items() if v == "write" and k != "id-token"}
        allowed = {"contents"} if (path.name, name) == ("release.yml", "github-release") else set()
        assert writes <= allowed, f"{path.name}:{name} has write access to {writes - allowed}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_jobs_have_timeouts(path: Path) -> None:
    for name, job in _load(path)["jobs"].items():
        assert "timeout-minutes" in job, f"{path.name}:{name}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_checkout_does_not_persist_credentials(path: Path) -> None:
    for job in _load(path)["jobs"].values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step.get("with", {}).get("persist-credentials") is False


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_untrusted_expression_in_run_scripts(path: Path) -> None:
    allowed = re.compile(r"\$\{\{\s*(matrix|strategy|runner)\.[\w.-]+\s*\}\}")
    for name, job in _load(path)["jobs"].items():
        for step in job["steps"]:
            run = allowed.sub("", step.get("run", ""))
            assert "${{" not in run, f"{path.name}:{name}: move expressions into env:"


def test_action_yml_run_scripts_do_not_interpolate_inputs() -> None:
    action = _load(ROOT / "action.yml")
    for step in action["runs"]["steps"]:
        assert "${{" not in step.get("run", "")


def test_release_publishing_is_isolated() -> None:
    wf = _load(ROOT / ".github" / "workflows" / "release.yml")
    # PyYAML reads the key `on` as boolean True
    trigger = wf.get("on", wf.get(True))
    assert trigger == {"push": {"tags": ["v*"]}}
    for name, job in wf["jobs"].items():
        has_token = "id-token" in (job.get("permissions") or {})
        assert has_token == (name == "publish")
    publish = wf["jobs"]["publish"]
    assert publish["environment"]["name"] == "pypi"
    assert "mn567250/ekte" in publish["if"]


def test_ci_runs_on_integration_branches_generically() -> None:
    wf = _load(ROOT / ".github" / "workflows" / "ci.yml")
    on = wf.get("on", wf.get(True))
    for event in ("push", "pull_request"):
        assert "main" in on[event]["branches"]
        assert "*/integration" in on[event]["branches"]


def test_workflow_linter_runs_in_ci() -> None:
    assert "zizmor" in (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
