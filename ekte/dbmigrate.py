"""One versioned, safe schema-migration mechanism for every local SQLite database.

Each database declares an ordered list of :class:`Migration` steps (version
1, 2, 3, ...). The database records the last applied step in
``PRAGMA user_version``; :func:`migrate` is called by
:func:`ekte.datadir.connect` on every open and:

* costs one ``PRAGMA user_version`` read when the database is current;
* refuses a database whose version is **newer** than the last known step
  (:class:`DatabaseTooNewError`) without writing anything to it;
* otherwise copies the file to a backup next to it (once per run, only if it
  already holds data), then applies each missing step in its own
  ``BEGIN IMMEDIATE`` transaction together with the version bump, so an
  interrupted or failing step leaves the database at the previous version.

``BEGIN IMMEDIATE`` takes SQLite's write lock and the version is read again
after it, so two processes (CLI and server) never run the same step twice: the
second waits (``busy_timeout``), sees the new version and skips.

Backups are named ``<db>.v<from-version>.<UTC timestamp>.bak`` and the newest
``BACKUP_KEEP`` (3) per database are kept; older ones are deleted.

A database with no recorded version (``user_version`` 0) is either new or from
before versioning; step 1 of every database must therefore be idempotent
(``CREATE ... IF NOT EXISTS``, add a column only if missing).
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

BACKUP_KEEP = 3
_BACKUP_SUFFIX = ".bak"


@dataclass(frozen=True)
class Migration:
    """One schema step: ``apply(conn)`` brings a database from ``version - 1`` to ``version``.

    ``apply`` runs inside a transaction; it must not commit or roll back.
    """

    version: int
    apply: Callable[[sqlite3.Connection], None]


class DatabaseTooNewError(RuntimeError):
    """The database was written by a newer ekte than this one."""


def latest(migrations: Sequence[Migration]) -> int:
    """The newest version (0 for no migrations)."""
    return migrations[-1].version if migrations else 0


def validate(migrations: Sequence[Migration]) -> None:
    """Versions must be 1, 2, 3, ... in order (checked by the tests)."""
    if [m.version for m in migrations] != list(range(1, len(migrations) + 1)):
        raise ValueError("migrations must be numbered 1..N in order")


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection, path: Path, migrations: Sequence[Migration]) -> bool:
    """Bring ``conn``'s database (the file at ``path``) to the latest version.

    Returns True when at least one step ran. Raises :class:`DatabaseTooNewError`
    for a database from a newer ekte (nothing is modified).
    """
    target = latest(migrations)
    current = user_version(conn)
    if current == target:
        return False
    if current > target:
        raise _too_new(path, current, target)
    ran = False
    backed_up = False
    for step in migrations:
        if step.version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Another process may have migrated while we waited for the lock.
            now = user_version(conn)
            if now > target:
                raise _too_new(path, now, target)
            if now >= step.version:
                conn.rollback()
                continue
            if not backed_up:
                backed_up = True
                _backup(path, now)
            step.apply(conn)
            conn.execute(f"PRAGMA user_version = {step.version}")
            conn.commit()
            ran = True
        except BaseException:
            conn.rollback()
            raise
    return ran


def _too_new(path: Path, found: int, supported: int) -> DatabaseTooNewError:
    from ekte import __version__

    return DatabaseTooNewError(
        f"{path} has schema version {found}, but this ekte ({__version__}) only "
        f"understands up to version {supported}. It was written by a newer ekte "
        "and has not been modified. Upgrade ekte (pip install -U ekte), or point "
        "--data-dir / EKTE_DATA_DIR at a different directory. To go back to this "
        "ekte, restore a backup made before the upgrade (<db>.v<N>.<time>.bak "
        "next to the database) and keep the newer database elsewhere."
    )


def backups(path: Path) -> list[Path]:
    """The backups of ``path``, newest first."""
    found = [
        p
        for p in path.parent.glob(f"{path.name}.v*{_BACKUP_SUFFIX}")
        if p.is_file()
    ]
    # The UTC timestamp in the name sorts chronologically within one database.
    return sorted(found, key=lambda p: p.name[len(path.name) + 1 :].split(".", 1)[-1], reverse=True)


def _has_data(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)) as c:
        return c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 0


def _backup(path: Path, from_version: int) -> Path | None:
    """Copy the database to a backup next to it, then prune old ones.

    Skipped for a new, empty database. Uses SQLite's backup API from a second
    connection (a reader; the caller holds the write lock, so the copy is
    consistent), and keeps the copy owner-only like the database.
    """
    if not _has_data(path):
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = path.with_name(f"{path.name}.v{from_version}.{stamp}{_BACKUP_SUFFIX}")
    fd = os.open(dest, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    os.close(fd)
    with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)) as src, \
            contextlib.closing(sqlite3.connect(str(dest))) as dst:
        src.backup(dst)
    for old in backups(path)[BACKUP_KEEP:]:
        with contextlib.suppress(OSError):
            old.unlink()
    return dest
