"""The local data directory and its SQLite stores, shared by the CLI and `ekte serve`.

Everything ekte persists locally — audit history, scheduled watches, the user's
own knowledge-base entries — lives in ``$EKTE_DATA_DIR`` (default ``~/.ekte``;
on the first run after the rename an existing ``~/.zing`` is copied there, see
:mod:`ekte.legacy`).
The watch store holds API keys (encrypted, see :mod:`ekte.secretbox`; the
master key itself is never stored here), so the directory is still created
owner-only (``0700``) and every database file (plus SQLite's
``-wal``/``-shm`` side files) is kept ``0600``.

:func:`connect` opens a fresh, short-lived connection per call, so callers are
safe on FastAPI's threadpool without sharing a connection across threads.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from ekte import dbmigrate, legacy

_DIR_MODE = 0o700
_FILE_MODE = 0o600


_migration_checked: set[Path] = set()


def data_dir() -> Path:
    explicit = legacy.getenv("EKTE_DATA_DIR")
    if explicit:
        return Path(explicit)
    path = Path.home() / ".ekte"
    if path not in _migration_checked:
        _migration_checked.add(path)
        legacy.migrate_data_dir(path, Path.home() / legacy.LEGACY_DIR_NAME)
    return path


def db_path(name: str) -> Path:
    return data_dir() / name


def ensure_data_dir() -> Path:
    """Create the data directory owner-only. A directory ekte did not create
    (e.g. a mounted volume passed as ``EKTE_DATA_DIR``) keeps its mode, except
    the default ``~/.ekte``, which is always tightened."""
    path = data_dir()
    if not path.is_dir():
        path.mkdir(parents=True, mode=_DIR_MODE, exist_ok=True)
        with contextlib.suppress(OSError):
            path.chmod(_DIR_MODE)
    elif not legacy.getenv("EKTE_DATA_DIR"):
        with contextlib.suppress(OSError):
            path.chmod(_DIR_MODE)
    return path


def _restrict(path: Path) -> None:
    """Create ``path`` owner-only if missing; tighten an existing file."""
    if not path.exists():
        with contextlib.suppress(OSError):
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, _FILE_MODE))
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if p.exists():
            with contextlib.suppress(OSError):
                p.chmod(_FILE_MODE)


@contextmanager
def connect(
    name: str,
    migrations: Sequence[dbmigrate.Migration],
    on_migrated: Callable[[sqlite3.Connection], None] | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection to ``<data dir>/<name>``; commit + close on exit.

    Rows come back as :class:`sqlite3.Row`. A short busy timeout lets
    concurrent local writers (the CLI and the server) retry instead of raising
    ``database is locked``.

    The schema is checked on every open and brought up to date with
    ``migrations`` (see :mod:`ekte.dbmigrate`); ``on_migrated`` is called once
    after a migration ran. A database from a newer ekte raises
    :class:`ekte.dbmigrate.DatabaseTooNewError` before anything is written.
    """
    ensure_data_dir()
    path = db_path(name)
    _restrict(path)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        # Refuse a newer database before any pragma can write to its file.
        if dbmigrate.user_version(conn) > dbmigrate.latest(migrations):
            dbmigrate.migrate(conn, path, migrations)  # raises
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        if dbmigrate.migrate(conn, path, migrations) and on_migrated:
            on_migrated(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
        _restrict(path)
