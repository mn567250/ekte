"""Validate the reusable GitHub composite action (action.yml).

These tests parse the YAML and assert the public contract — required inputs,
declared outputs, and a `composite` runs section — so the action stays in sync
with the CLI it wraps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ACTION_PATH = Path(__file__).resolve().parent.parent / "action.yml"


def _load() -> dict:
    with ACTION_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_action_file_exists() -> None:
    assert ACTION_PATH.is_file()


def test_required_inputs_present() -> None:
    action = _load()
    inputs = action["inputs"]
    for name in ("base-url", "api-key", "model"):
        assert inputs[name]["required"] is True, name
    # Optional inputs with sensible defaults.
    assert inputs["api"]["default"] == "auto"
    assert inputs["suite"]["default"] == "standard"
    assert inputs["fail-on-risk"]["default"] == "high"
    assert inputs["version"]["default"] == "ekte"


def test_outputs_present() -> None:
    action = _load()
    outputs = action["outputs"]
    for name in ("risk", "score", "rating"):
        assert name in outputs
        # Each output is wired to the audit step.
        assert "steps.audit.outputs." in outputs[name]["value"]


def test_runs_is_composite_with_steps() -> None:
    action = _load()
    runs = action["runs"]
    assert runs["using"] == "composite"
    steps = runs["steps"]
    assert isinstance(steps, list) and steps

    uses = [s.get("uses", "") for s in steps]
    assert any(u.startswith("actions/setup-python@") for u in uses)

    # The audit step is a bash step that gates on ekte's exit code.
    audit = next(s for s in steps if s.get("id") == "audit")
    assert audit["shell"] == "bash"
    assert "--compact" in audit["run"]
    assert "--fail-on-risk" in audit["run"]
    # Key is forwarded via env + env:VAR reference, never inlined.
    assert "env:EKTE_RELAY_API_KEY" in audit["run"]
    assert "EKTE_RELAY_API_KEY" in audit["env"]


def test_api_key_never_echoed() -> None:
    """The raw key value must not be interpolated onto the command line."""
    action = _load()
    audit = next(
        s for s in action["runs"]["steps"] if s.get("id") == "audit"
    )
    # The key only ever flows through the env var, not `inputs.api-key` directly.
    assert "inputs.api-key" not in audit["run"]


def test_evidence_is_opt_in_and_uploaded_even_when_the_gate_fails() -> None:
    action = _load()
    assert action["inputs"]["evidence"]["default"] == "false"
    assert "steps.audit.outputs.evidence-file" in action["outputs"]["evidence-file"]["value"]
    steps = action["runs"]["steps"]
    audit = next(s for s in steps if s.get("id") == "audit")
    assert "--evidence" in audit["run"] and "IN_EVIDENCE" in audit["env"]
    assert "inputs.evidence" not in audit["run"]  # through the environment only
    upload = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["if"].startswith("${{ always() && inputs.evidence == 'true'")
    assert upload["with"]["path"] == "${{ steps.audit.outputs.evidence-file }}"
