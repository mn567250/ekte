"""The command line contract (docs/reference/stability.md#surface-cli, #surface-exit-codes).

Pins the documented exit codes, runs every command's --help, checks that every
option has a help text, that docs/reference/cli.md matches the code, that --json writes only
JSON to stdout, and that renamed options keep working with a deprecation warning.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ekte import cli, clidocs

runner = CliRunner()
ROOT = Path(__file__).resolve().parent.parent
COMMANDS = [p for p, _ in clidocs.commands()]


def _invoke(*args: str):
    return runner.invoke(cli.app, list(args))


# --------------------------------------------------------------------------- help
@pytest.mark.parametrize("path", COMMANDS, ids=[" ".join(p) for p in COMMANDS])
def test_every_command_help_runs(path):
    res = _invoke(*path, "--help")
    assert res.exit_code == 0, res.output
    assert "Usage" in res.output


def test_top_level_help_and_version():
    assert _invoke("--help").exit_code == 0
    res = _invoke("--version")
    assert res.exit_code == 0 and res.output.startswith("ekte ")


def test_every_command_and_option_has_help_text():
    for path, cmd in clidocs.commands():
        assert (cmd.help or "").strip(), f"ekte {' '.join(path)} has no help text"
        for p in cmd.params:
            if p.name == "help":
                continue
            text = getattr(p, "help", None)
            assert (text or "").strip(), f"ekte {' '.join(path)}: {p.name} has no help text"


def test_option_names_are_lowercase_hyphenated_and_short_options_are_established():
    allowed_short = {"-c", "-H", "-D", "-p"}
    for path, cmd in clidocs.commands():
        for p in cmd.params:
            if p.param_type_name != "option":
                continue
            for name in [*p.opts, *p.secondary_opts]:
                if name.startswith("--"):
                    assert re.fullmatch(r"--[a-z0-9]+(-[a-z0-9]+)*", name), (path, name)
                else:
                    assert name in allowed_short, (path, name)


def test_cli_reference_is_current():
    doc = ROOT / "docs" / "reference" / "cli.md"
    assert doc.read_text("utf-8") == clidocs.render(), (
        "docs/reference/cli.md is stale: run `uv run python scripts/generate_cli_docs.py`"
    )


def test_same_option_means_the_same_everywhere():
    seen: dict[str, set[str]] = {}
    for _path, cmd in clidocs.commands():
        for p in cmd.params:
            if p.param_type_name == "option" and p.name in {"as_json", "fail_on_risk", "claimed_model"}:
                seen.setdefault(p.name, set()).add(p.opts[0])
    assert seen == {
        "as_json": {"--json"}, "fail_on_risk": {"--fail-on-risk"}, "claimed_model": {"--claimed-model"},
    }
    # --format is only ever the report file format: the audio one is --audio-format.
    for path, cmd in clidocs.commands():
        visible = [o for p in cmd.params if not getattr(p, "hidden", False) for o in p.opts]
        assert not ({"--format"} & set(visible)) or path[0] in {"check", "compare"}, path


# --------------------------------------------------------------------------- exit codes
def test_exit_code_table_is_documented():
    text = (ROOT / "docs" / "reference" / "stability.md").read_text("utf-8")
    section = text[text.index('id="surface-exit-codes"'):text.index('id="surface-config"')]
    assert set(cli.EXIT_CODES) == {0, 1, 2, 3, 4}
    for code in cli.EXIT_CODES:
        assert re.search(rf"\|\s*{code}\s*\|", section), f"exit code {code} missing from stability.md"
    assert "cli.md" in section


def test_exit_0_success():
    assert _invoke("data-dir").exit_code == cli.EXIT_OK


def test_exit_1_gate_or_check_failed(tmp_path):
    f = tmp_path / "ekte.yaml"
    f.write_text("target:\n  base_url: https://x.test/v1\n", encoding="utf-8")  # format 1: outdated
    assert _invoke("config", "migrate", str(f), "--check").exit_code == cli.EXIT_GATE
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: [a, provider", encoding="utf-8")
    assert _invoke("kb-import", str(bad), "--check").exit_code == cli.EXIT_GATE


def test_exit_1_for_risk_and_score_gates():
    from ekte.models import RiskLevel

    class V:
        overall_score = 40.0
        risk_level = RiskLevel.HIGH

    class R:
        verdict = V()

    assert cli._exit_code(R(), 50.0, None) == cli.EXIT_GATE  # type: ignore[arg-type]
    assert cli._exit_code(R(), None, "medium") == cli.EXIT_GATE  # type: ignore[arg-type]
    assert cli._exit_code(R(), 30.0, None) == cli.EXIT_OK  # type: ignore[arg-type]
    assert cli._embed_exit_code({"risk_level": "high"}, "low") == cli.EXIT_GATE
    assert cli._embed_exit_code({"risk_level": "clean"}, "low") == cli.EXIT_OK


def test_exit_2_usage_and_configuration_errors(tmp_path):
    assert _invoke("check", "--no-such-option").exit_code == cli.EXIT_USAGE
    assert _invoke(
        "check", "--base-url", "https://x.test/v1", "--model", "m", "--fail-on-risk", "nope", "--dry-run"
    ).exit_code == cli.EXIT_USAGE
    existing = tmp_path / "ekte.yaml"
    existing.write_text("x", encoding="utf-8")
    assert _invoke("init", "--path", str(existing)).exit_code == cli.EXIT_USAGE
    assert _invoke("config", "migrate", str(tmp_path / "missing.yaml")).exit_code == cli.EXIT_USAGE


def test_exit_3_endpoint_failure():
    res = _invoke("models", "--base-url", "http://127.0.0.1:9/v1")
    assert res.exit_code == cli.EXIT_ENDPOINT
    res = _invoke("models", "--base-url", "http://127.0.0.1:9/v1", "--json")
    assert res.exit_code == cli.EXIT_ENDPOINT
    assert json.loads(res.stdout)["ok"] is False


def test_exit_4_unexpected_error(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(SystemExit) as exc:
        cli.run()
    assert exc.value.code == cli.EXIT_INTERNAL
    assert "Internal error" in capsys.readouterr().err


def test_python_dash_m_ekte_runs():
    res = subprocess.run([sys.executable, "-m", "ekte", "data-dir"], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0 and res.stdout.strip()


# --------------------------------------------------------------------------- JSON mode
def test_json_mode_writes_only_json_to_stdout(tmp_path):
    cfg = tmp_path / "ekte.yaml"
    cfg.write_text("target:\n  base_url: https://x.test/v1\n", encoding="utf-8")
    nope = str(tmp_path / "nope.yaml")
    target = ["--base-url", "https://x.test/v1", "--model", "m"]
    cases = [
        (["data-dir", "--json"], 0),
        (["kb", "--json"], 0),
        (["secret", "status", "--json"], 0),
        (["config", "migrate", str(cfg), "--check", "--json"], 1),
        (["config", "migrate", str(cfg), "--json"], 0),
        (["config", "migrate", str(cfg), "--json"], 0),  # now current
        (["config", "migrate", nope, "--json"], 2),
        (["models", "--base-url", "http://127.0.0.1:9/v1", "--json"], 3),
        (["check", *target, "--dry-run", "--json"], 0),
        (["check", *target, "--dry-run", "--compact"], 0),
        (["check", "--json"], 2),
        (["compare", "--json"], 2),
        (["embed", *target, "--dry-run", "--json"], 0),
        (["rerank", *target, "--dry-run", "--json"], 0),
        (["embed", "--json"], 2),
        (["image", "--json"], 2),
        (["audio", "--json"], 2),
        (["watch", "--json"], 2),
        (["kb-import", nope, "--json"], 2),
        (["kb-import", nope, "--check", "--json"], 2),
    ]
    for args, code in cases:
        res = _invoke(*args)
        assert res.exit_code == code, (args, res.output)
        json.loads(res.stdout)


def test_kb_import_check_json(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: [a, provider", encoding="utf-8")
    res = _invoke("kb-import", str(bad), "--check", "--json")
    assert res.exit_code == cli.EXIT_GATE
    assert json.loads(res.stdout)["ok"] is False


def test_watch_json_cycle_goes_to_stdout_and_progress_to_stderr(monkeypatch):
    from ekte.models import AuditReport, RedactedTarget
    from ekte.scoring import build_dimensions, build_verdict

    async def fake_run_audit(target, options, **kw):
        dims = build_dimensions([], None)
        verdict = build_verdict([], dims, profile_matched=True, used_judge=False, used_baseline=False)
        return AuditReport(
            tool_version="0", mode="check", generated_at="t", suite="smoke",
            target=RedactedTarget(name="t", kind="target", base_url=target.base_url, model=target.model),
            verdict=verdict, dimensions=dims, detectors=[],
        )

    monkeypatch.setattr("ekte.runner.run_audit", fake_run_audit)
    res = _invoke("watch", "--base-url", "https://x.test/v1", "--model", "m", "--once", "--json")
    assert res.exit_code == 0, res.output
    lines = [json.loads(line) for line in res.stdout.splitlines()]
    assert len(lines) == 1 and lines[0]["event"] == "cycle"
    assert lines[0]["base_url"] == "https://x.test/v1"
    assert "ekte watch" in res.stderr


# --------------------------------------------------------------------------- deprecations
def test_deprecated_save_keeps_working_and_warns(monkeypatch, tmp_path):
    async def fake_audit_image(target, *, size, claimed_sizes):
        return {"risk_level": "clean"}

    monkeypatch.setattr("ekte.media_audit.audit_image", fake_audit_image)
    res = _invoke(
        "image", "--base-url", "https://x.test/v1", "--model", "m",
        "--save", str(tmp_path / "i.png"), "--json",
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout) == {"risk_level": "clean"}
    assert "--save" in res.stderr and "--save-to" in res.stderr and cli._DEPRECATED_REMOVAL in res.stderr


def test_deprecated_audio_format_keeps_working_and_warns(monkeypatch):
    seen = {}

    async def fake_audit_audio(target, *, voice, fmt):
        seen["fmt"] = fmt
        return {"risk_level": "clean"}

    monkeypatch.setattr("ekte.media_audit.audit_audio", fake_audit_audio)
    base = ["audio", "--base-url", "https://x.test/v1", "--model", "m", "--json"]
    res = _invoke(*base, "--format", "mp3")
    assert res.exit_code == 0, res.output
    assert seen["fmt"] == "mp3"
    assert "--format" in res.stderr and "--audio-format" in res.stderr and cli._DEPRECATED_REMOVAL in res.stderr
    res = _invoke(*base, "--audio-format", "flac")
    assert seen["fmt"] == "flac" and "Deprecated" not in res.stderr
    assert _invoke(*base).exit_code == 0 and seen["fmt"] == "wav"
