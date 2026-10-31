"""Choosing and finding the data directory: --data-dir and `ekte data-dir`."""

from __future__ import annotations

import os
import stat

from typer.testing import CliRunner

from ekte import datadir
from ekte.cli import app


def test_default_is_home_dot_ekte(monkeypatch, tmp_path):
    monkeypatch.delenv("EKTE_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["data-dir"])
    assert result.exit_code == 0
    assert result.output.strip() == str(tmp_path / ".ekte")


def test_global_option_sets_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("EKTE_DATA_DIR", "/unused")
    result = CliRunner().invoke(app, ["--data-dir", str(tmp_path), "data-dir"])
    assert result.exit_code == 0
    assert result.output.strip() == str(tmp_path.resolve())


def test_relative_path_is_made_absolute(monkeypatch, tmp_path):
    monkeypatch.setenv("EKTE_DATA_DIR", "/unused")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["--data-dir", ".", "data-dir"])
    assert result.exit_code == 0
    assert os.path.isabs(os.environ["EKTE_DATA_DIR"])
    assert result.output.strip() == str(tmp_path.resolve())


def test_existing_folder_keeps_its_mode(monkeypatch, tmp_path):
    tmp_path.chmod(0o755)
    monkeypatch.setenv("EKTE_DATA_DIR", "/unused")
    CliRunner().invoke(app, ["--data-dir", str(tmp_path), "data-dir"])
    with datadir.connect("history.db") as conn:
        conn.execute("CREATE TABLE t (x)")
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    db = tmp_path / "history.db"
    assert db.is_file()
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
