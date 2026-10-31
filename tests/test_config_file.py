"""The versioned, validated configuration file (docs/STABILITY.md#surface-config)."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ekte import configfile
from ekte.cli import app
from ekte.config import TEMPLATE, ConfigError, load_config_file
from ekte.models import Dimension

ROOT = Path(__file__).resolve().parents[1]
VALID = """\
version: 1
target:
  base_url: https://relay.example.com/v1
  model: gpt-4o
  timeout_sec: 30
run:
  suite: deep
  judge: true
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "ekte.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_file(tmp_path):
    cfg = load_config_file(_write(tmp_path, VALID))
    assert cfg["version"] == 1
    assert cfg["run"]["suite"] == "deep"


def test_template_and_example_are_valid(tmp_path):
    assert load_config_file(_write(tmp_path, TEMPLATE))["version"] == configfile.CURRENT_VERSION
    assert load_config_file(ROOT / "examples" / "ekte.yaml")["version"] == 1


def test_unknown_key_names_file_line_and_key(tmp_path, capsys):
    p = _write(tmp_path, VALID + "  suit: deep\n")
    cfg = load_config_file(p)
    msg = capsys.readouterr().err
    assert str(p) in msg and "line 9" in msg and "run.suit" in msg and "'suite'" in msg
    assert "ignored" in msg and "1.0.0 will reject it" in msg
    assert "suit" not in cfg["run"]


def test_unknown_section(tmp_path, capsys):
    cfg = load_config_file(_write(tmp_path, "runs:\n  suite: deep\n"))
    assert "line 1: runs: unknown key" in capsys.readouterr().err
    assert "runs" not in cfg


def test_wrong_type(tmp_path):
    with pytest.raises(ConfigError, match=r"line 5: target.timeout_sec: expected a number, got 'fast'"):
        load_config_file(_write(tmp_path, VALID.replace("timeout_sec: 30", "timeout_sec: fast")))


def test_invalid_value(tmp_path):
    with pytest.raises(ConfigError, match=r"run.suite: expected one of smoke"):
        load_config_file(_write(tmp_path, VALID.replace("deep", "huge")))


def test_unversioned_file_is_format_1(tmp_path):
    cfg = load_config_file(_write(tmp_path, VALID.replace("version: 1\n", "")))
    assert "version" not in cfg and cfg["run"]["suite"] == "deep"


def test_newer_format_is_refused(tmp_path):
    with pytest.raises(ConfigError, match=r"line 1: version: format 2 is newer"):
        load_config_file(_write(tmp_path, VALID.replace("version: 1", "version: 2")))


def test_deprecated_key_warns_and_works(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(configfile, "DEPRECATED", {"run.threads": "run.concurrency"})
    p = _write(tmp_path, VALID + "  threads: 5\n")
    cfg = load_config_file(p)
    assert cfg["run"]["concurrency"] == 5 and "threads" not in cfg["run"]
    err = capsys.readouterr().err
    assert "run.threads is deprecated; use run.concurrency" in err and "line 9" in err


def test_older_format_names_migrate_command(tmp_path, monkeypatch):
    monkeypatch.setattr(configfile, "CURRENT_VERSION", 2)
    with pytest.raises(ConfigError, match="outdated.*ekte config migrate"):
        load_config_file(_write(tmp_path, VALID))


def test_migrate_renames_keys_and_keeps_comments(monkeypatch):
    monkeypatch.setattr(configfile, "CURRENT_VERSION", 2)
    monkeypatch.setattr(configfile, "RENAMES_FROM", {1: {"run.threads": "run.concurrency"}})
    text = "# my config\nversion: 1\nrun:\n  threads: 5  # parallel\n"
    new, changes = configfile.migrate_text(text, "x")
    assert new == "# my config\nversion: 2\nrun:\n  concurrency: 5  # parallel\n"
    assert changes == ["renamed run.threads to run.concurrency", "set version to 2"]
    assert configfile.load(new, "x")["run"]["concurrency"] == 5


def test_migrate_adds_version_below_header():
    new, changes = configfile.migrate_text("# header\n\ntarget:\n  model: m\n", "x")
    assert new.startswith("# header\n\nversion: 1\n") and changes


def test_migrate_command(tmp_path):
    p = _write(tmp_path, "# c\ntarget:\n  model: m\n")
    runner = CliRunner()
    assert runner.invoke(app, ["config", "migrate", str(p), "--check"]).exit_code == 1
    assert runner.invoke(app, ["config", "migrate", str(p)]).exit_code == 0
    assert "version: 1" in p.read_text() and (tmp_path / "ekte.yaml.bak").exists()
    assert runner.invoke(app, ["config", "migrate", str(p), "--check"]).exit_code == 0


def test_init_writes_current_version(tmp_path):
    p = tmp_path / "c.yaml"
    assert CliRunner().invoke(app, ["init", "--path", str(p)]).exit_code == 0
    assert f"version: {configfile.CURRENT_VERSION}" in p.read_text()


def test_published_schema_is_current():
    path = ROOT / "docs" / "schemas" / "config.schema.json"
    assert path.read_text(encoding="utf-8") == configfile.schema_text(), (
        "regenerate with: uv run python -m ekte.configfile"
    )


def test_schema_choices_match_code():
    from ekte import config

    assert set(configfile.DIMENSIONS) == {d.value for d in Dimension}
    assert configfile.SUITES == config.SUITES and configfile.APIS == config.APIS
    assert configfile.FORMATS == config.FORMATS


def test_unknown_key_leniency_ends_at_1_0():
    # Unknown keys only warn until 1.0.0 (docs/STABILITY.md#surface-config).
    # When the package reaches 1.0, this fails until validate() rejects them.
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    major = int(version.split(".")[0])
    if major >= int(configfile.UNKNOWN_KEYS_REJECTED_IN.split(".")[0]):
        pytest.fail("ekte reached 1.0: make unknown config keys an error (configfile.validate)")
