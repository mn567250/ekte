"""The local data directory and its SQLite stores, shared by the CLI and `zing serve`.

Everything zing persists locally — audit history, scheduled watches, the user's
own knowledge-base entries — lives in ``$ZING_DATA_DIR`` (default ``~/.zing``).
The watch store holds API keys (encrypted, see :mod:`zing.secretbox`; the
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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_DIR_MODE = 0o700
_FILE_MODE = 0o600


def data_dir() -> Path:
    return Path(os.environ.get("ZING_DATA_DIR") or (Path.home() / ".zing"))


def db_path(name: str) -> Path:
    return data_dir() / name


def ensure_data_dir() -> Path:
    """Create the data directory owner-only. A directory zing did not create
    (e.g. a mounted volume passed as ``ZING_DATA_DIR``) keeps its mode, except
    the default ``~/.zing``, which is always tightened."""
    path = data_dir()
    if not path.is_dir():
        path.mkdir(parents=True, mode=_DIR_MODE, exist_ok=True)
        with contextlib.suppress(OSError):
            path.chmod(_DIR_MODE)
    elif not os.environ.get("ZING_DATA_DIR"):
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
def connect(name: str) -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection to ``<data dir>/<name>``; commit + close on exit.

    Rows come back as :class:`sqlite3.Row`. A short busy timeout lets
    concurrent local writers (the CLI and the server) retry instead of raising
    ``database is locked``.
    """
    ensure_data_dir()
    path = db_path(name)
    _restrict(path)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()
        _restrict(path)
