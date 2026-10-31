"""Compatibility with installs from before the rename zing -> ekte (ekte/legacy.py)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from ekte import datadir, legacy


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh home directory with no data directory set explicitly."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    monkeypatch.delenv("EKTE_DATA_DIR", raising=False)
    monkeypatch.delenv("ZING_DATA_DIR", raising=False)
    monkeypatch.setattr(datadir, "_migration_checked", set())
    monkeypatch.setattr(legacy, "_warned", set())
    return tmp_path


def _zing_dir(home: Path) -> tuple[Path, sqlite3.Connection]:
    """A ~/.zing as zing leaves it, with zing still running: its connection
    stays open, so the last rows are only in history.db-wal."""
    old = home / ".zing"
    old.mkdir(mode=0o700)
    con = sqlite3.connect(old / "history.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE runs (id INTEGER)")
    con.execute("INSERT INTO runs VALUES (1), (2)")
    con.commit()
    (old / "secret.key").write_text("legacy-key\n")
    (old / "secret.key").chmod(0o600)
    (old / "kb").mkdir()
    (old / "kb" / "mine.yaml").write_text("models: []\n")
    assert (old / "history.db-wal").stat().st_size > 0
    return old, con


# --------------------------------------------------------------------------- #
# environment variables
# --------------------------------------------------------------------------- #
def test_getenv_prefers_the_new_name(monkeypatch, capsys):
    monkeypatch.setattr(legacy, "_warned", set())
    monkeypatch.setenv("EKTE_PORT", "9000")
    monkeypatch.setenv("ZING_PORT", "8000")
    assert legacy.getenv("EKTE_PORT") == "9000"
    assert capsys.readouterr().err == ""


def test_getenv_falls_back_to_zing_with_one_notice(monkeypatch, capsys):
    monkeypatch.setattr(legacy, "_warned", set())
    monkeypatch.delenv("EKTE_PORT", raising=False)
    monkeypatch.setenv("ZING_PORT", "8000")
    assert legacy.getenv("EKTE_PORT") == "8000"
    assert legacy.getenv("EKTE_PORT") == "8000"
    err = capsys.readouterr().err
    assert err.count("ZING_PORT is deprecated and will stop working in ekte 1.0.0; use EKTE_PORT instead") == 1


def test_getenv_default_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("EKTE_PORT", raising=False)
    monkeypatch.delenv("ZING_PORT", raising=False)
    assert legacy.getenv("EKTE_PORT") is None
    assert legacy.getenv("EKTE_PORT", "8000") == "8000"


def test_legacy_secret_key_is_read(monkeypatch):
    from ekte import secretbox

    monkeypatch.delenv("EKTE_SECRET_KEY", raising=False)
    monkeypatch.setenv("ZING_SECRET_KEY", secretbox.generate_key())
    box = secretbox.env_box()
    assert box is not None and box.source == secretbox.ENV == "EKTE_SECRET_KEY"


def test_legacy_data_dir_variable_is_used_as_is(home, monkeypatch):
    _zing_dir(home)[1].close()
    custom = home / "custom"
    monkeypatch.setenv("ZING_DATA_DIR", str(custom))
    assert datadir.data_dir() == custom
    assert not (home / ".ekte").exists()  # an explicit directory is never migrated


# --------------------------------------------------------------------------- #
# ~/.zing -> ~/.ekte
# --------------------------------------------------------------------------- #
def test_zing_data_dir_is_copied_once_and_kept(home, capsys):
    old, zing = _zing_dir(home)
    before = sorted(p.relative_to(old) for p in old.rglob("*"))

    path = datadir.data_dir()

    new = home / ".ekte"
    assert path == new and new.is_dir()
    assert not (new / "history.db-wal").exists()  # side files are not copied ...
    rows = sqlite3.connect(new / "history.db").execute("SELECT id FROM runs ORDER BY id").fetchall()
    assert rows == [(1,), (2,)]  # ... their content is in the copy
    assert (new / "secret.key").read_text(encoding="utf-8") == "legacy-key\n"
    if sys.platform != "win32":  # POSIX file modes have no effect on Windows
        assert (new / "secret.key").stat().st_mode & 0o777 == 0o600
        assert new.stat().st_mode & 0o777 == 0o700
    assert (new / "kb" / "mine.yaml").read_text(encoding="utf-8") == "models: []\n"
    # ~/.zing is left exactly as it was, and zing keeps working on it
    assert sorted(p.relative_to(old) for p in old.rglob("*")) == before
    zing.execute("INSERT INTO runs VALUES (3)")
    zing.commit()
    zing.close()
    err = capsys.readouterr().err
    assert f"copied the zing data directory {old} to {new}" in err
    assert "delete it yourself" in err
    assert "removed in ekte 1.0.0" in err and "never deletes" in err

    # from now on ekte works from ~/.ekte: no second copy, no second notice
    (old / "later.txt").write_text("written by zing afterwards")
    datadir._migration_checked.clear()
    assert datadir.data_dir() == new
    assert not (new / "later.txt").exists()
    assert capsys.readouterr().err == ""


def test_existing_ekte_dir_is_not_overwritten(home, capsys):
    _zing_dir(home)[1].close()
    new = home / ".ekte"
    new.mkdir()
    assert datadir.data_dir() == new
    assert list(new.iterdir()) == []
    assert capsys.readouterr().err == ""


def test_no_zing_dir_means_nothing_to_migrate(home, capsys):
    assert datadir.data_dir() == home / ".ekte"
    assert not (home / ".ekte").exists()  # created on first write, as before
    assert capsys.readouterr().err == ""


def test_failed_copy_leaves_no_half_filled_dir(home, monkeypatch, capsys):
    _zing_dir(home)[1].close()

    def boom(src: Path, dst: Path) -> None:
        dst.mkdir()
        raise OSError("disk full")

    monkeypatch.setattr(legacy, "_copy_tree", boom)
    assert datadir.data_dir() == home / ".ekte"
    assert not (home / ".ekte").exists()
    assert not list(home.glob(".ekte.migrating-*"))
    assert "could not copy" in capsys.readouterr().err


def snapshot(root):
    """Every path under root, and the content of the plain files (SQLite's own
    side files change whenever a connection opens the database)."""
    return sorted((p.relative_to(root), p.read_bytes() if p.suffix in ("", ".key", ".yaml") and p.is_file() else None)
                  for p in root.rglob("*"))


def test_the_copy_never_deletes_the_old_directory(home, monkeypatch):
    """Neither a finished copy nor a failed one removes anything from ~/.zing,
    and nothing in the module can delete it (also not once the copy is removed)."""
    old, zing = _zing_dir(home)  # zing still runs on it (its connection stays open)
    before = snapshot(old)
    removed: list[object] = []
    real_rmtree = legacy.shutil.rmtree
    monkeypatch.setattr(legacy.shutil, "rmtree", lambda path, *a, **k: (removed.append(path), real_rmtree(path, *a, **k)))
    monkeypatch.setattr(legacy.os, "remove", lambda *a, **k: removed.append(a))
    monkeypatch.setattr(legacy.os, "unlink", lambda *a, **k: removed.append(a))
    # a failing copy: the temporary sibling is cleaned up, ~/.zing is not
    monkeypatch.setattr(legacy, "_copy_tree", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    assert legacy.migrate_data_dir(home / ".ekte", old) is False
    assert all(not str(r).startswith(str(old)) for r in removed)
    monkeypatch.undo()
    assert legacy.migrate_data_dir(home / ".ekte", old) is True
    assert old.is_dir()
    assert snapshot(old) == before
    zing.close()
