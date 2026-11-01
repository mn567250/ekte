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
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from ekte import dbmigrate, legacy

_DIR_MODE = 0o700
_FILE_MODE = 0o600


_migration_checked: set[Path] = set()
_warned_unprotected: set[Path] = set()


def _modes_enforced() -> bool:
    """True where file modes restrict access to the owner (Linux, macOS)."""
    return os.name == "posix"


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
        _warn_unprotected(path)
    elif not legacy.getenv("EKTE_DATA_DIR"):
        with contextlib.suppress(OSError):
            path.chmod(_DIR_MODE)
    return path


def _warn_unprotected(path: Path) -> None:
    """On Windows the 0700/0600 modes have no effect: say so once, when the
    directory is created (see docs/reference/stability.md#os)."""
    if _modes_enforced() or path in _warned_unprotected:
        return
    _warned_unprotected.add(path)
    print(
        f"ekte: created {path}. On this system the directory is not restricted to "
        "your account by ekte (file modes have no effect on Windows); it inherits "
        "the permissions of its parent folder. Keep it inside your user profile.",
        file=sys.stderr,
    )


def _restrict(path: Path) -> None:
    """Create ``path`` owner-only if missing; tighten an existing file."""
    if not path.exists():
        with contextlib.suppress(OSError):
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, _FILE_MODE))
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if p.exists():
            with contextlib.suppress(OSError):
                p.chmod(_FILE_MODE)


def _set_wal(conn: sqlite3.Connection, timeout: float = 5.0) -> None:
    """Switch to WAL, waiting for other connections like ``busy_timeout`` does.

    SQLite answers a journal-mode change with "database is locked" at once,
    without calling the busy handler, while another connection holds a lock
    (e.g. a concurrent opener migrating a fresh database), so retry until the
    same deadline the busy timeout uses.
    """
    deadline = time.monotonic() + timeout
    delay = 0.01
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)


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
        _set_wal(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        if dbmigrate.migrate(conn, path, migrations) and on_migrated:
            on_migrated(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
        _restrict(path)
