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
Writes go through it. Reads that run often (the web UI's widget endpoints)
use :func:`read_connection` instead: one reused read-only connection per
thread, with the schema checked only on the first open in the process.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from ekte import dbmigrate, legacy

_DIR_MODE = 0o700
_FILE_MODE = 0o600


_migration_checked: set[Path] = set()
# Database files whose schema read_connection() has checked in this process,
# with the (device, inode) they had then.
_schema_ready: dict[Path, tuple[int, int]] = {}
_schema_lock = threading.Lock()
# Per thread: path -> (connection, (device, inode) of the file it opened,
# _reader_gen when it was opened).
_readers = threading.local()
# Bumped by close_read_connections(): older connections are closed.
_reader_gen = 0
# Every read connection, so close_read_connections() can close them all.
_all_readers: list[sqlite3.Connection] = []
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


def _file_id(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_dev, st.st_ino


def read_connection(
    name: str,
    migrations: Sequence[dbmigrate.Migration] = (),
    on_migrated: Callable[[sqlite3.Connection], None] | None = None,
) -> sqlite3.Connection:
    """This thread's read-only connection to ``<data dir>/<name>``, reused
    across calls (never close it; :func:`close_read_connections` does).

    Opened with a ``mode=ro`` URI and ``PRAGMA query_only``, so it can never
    write; rows come back as :class:`sqlite3.Row`. The database is in WAL mode
    (set by :func:`connect`), so its reads run next to writers, and each
    statement outside a transaction sees the latest committed data, whatever
    process wrote it.

    The first call in the process for a file brings its schema up to date
    through :func:`connect` (``migrations`` / ``on_migrated`` as there); later
    calls skip that check. A file that was replaced or deleted since (another
    inode) is opened and checked afresh.
    """
    path = db_path(name)
    cache: dict[Path, tuple[sqlite3.Connection, tuple[int, int], int]] = getattr(
        _readers, "conns", None) or {}
    _readers.conns = cache
    fid = _file_id(path)
    held = cache.get(path)
    if held is not None and held[1] == fid and held[2] == _reader_gen:
        return held[0]
    if held is not None:
        cache.pop(path)
        _close(held[0])
    if fid is None or _schema_ready.get(path) != fid:
        with connect(name, migrations, on_migrated):
            pass
        fid = _file_id(path)
        if fid is None:  # pragma: no cover - deleted while opening
            raise sqlite3.OperationalError(f"cannot open {path}")
        with _schema_lock:
            _schema_ready[path] = fid
    gen = _reader_gen
    conn = sqlite3.connect(
        path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5.0, check_same_thread=False
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA query_only=ON")
    except BaseException:
        conn.close()
        raise
    _restrict(path)  # the -shm file a reader may have created
    cache[path] = (conn, fid, gen)
    with _schema_lock:
        _all_readers.append(conn)
    return conn


def _close(conn: sqlite3.Connection) -> None:
    with _schema_lock, contextlib.suppress(ValueError):
        _all_readers.remove(conn)
    with contextlib.suppress(sqlite3.Error):
        conn.close()


def close_read_connections() -> None:
    """Close every thread's read connection and forget which schemas were
    checked (for tests, and before a data directory goes away). A thread
    whose connection was closed opens a new one on its next call."""
    global _reader_gen
    with _schema_lock:
        _reader_gen += 1
        conns = list(_all_readers)
        _all_readers.clear()
        _schema_ready.clear()
    for conn in conns:
        with contextlib.suppress(sqlite3.Error):
            conn.close()
