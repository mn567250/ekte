"""The CLI examples from the docs run offline (#34): ``init``, ``config migrate
--check`` and ``check --dry-run`` on the shipped example configuration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "ekte.yaml"


def _ekte(*args: str, cwd: Path, env_home: Path) -> subprocess.CompletedProcess[str]:
    import os

    # PYTHONIOENCODING: on Windows a child writing to a pipe uses the ANSI code
    # page; make it write UTF-8, which is how the output is read here.
    env = dict(os.environ, EKTE_DATA_DIR=str(env_home / "data"), HOME=str(env_home),
               USERPROFILE=str(env_home), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "ekte", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_init_writes_a_valid_config(tmp_path):
    res = _ekte("init", cwd=tmp_path, env_home=tmp_path)
    assert res.returncode == 0, res.stderr
    written = tmp_path / "ekte.yaml"
    assert written.is_file()
    check = _ekte("config", "migrate", "--check", str(written), cwd=tmp_path, env_home=tmp_path)
    assert check.returncode == 0, check.stderr


def test_example_config_is_current(tmp_path):
    res = _ekte("config", "migrate", "--check", str(EXAMPLE), cwd=tmp_path, env_home=tmp_path)
    assert res.returncode == 0, res.stderr


def test_example_config_dry_run(tmp_path):
    res = _ekte("check", "--config", str(EXAMPLE), "--dry-run", cwd=tmp_path, env_home=tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
