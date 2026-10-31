"""Compatibility with installs from before ekte was renamed from zing.

The whole compatibility layer is deprecated and removed in ekte 1.0.0
(docs/STABILITY.md, #26); every notice below names that version. ekte never
deletes an old ``~/.zing``, also not when the copy is removed.

* **Environment variables.** Every setting is read from ``EKTE_<NAME>``; when
  that is unset, the old ``ZING_<NAME>`` still works, with a one-time
  deprecation notice on stderr (:func:`getenv`).
* **Data directory.** The default is ``~/.ekte``. When it does not exist yet
  and the old ``~/.zing`` does, :func:`migrate_data_dir` copies ``~/.zing``
  to ``~/.ekte`` once, and from then on ekte works from ``~/.ekte`` only.
  ``~/.zing`` is left untouched (zing may still run next to ekte); the
  notice says so and leaves deleting it to the user. A data directory set
  explicitly (``EKTE_DATA_DIR`` / ``ZING_DATA_DIR`` / ``--data-dir``) is
  used as it is, nothing is copied.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import overload

PREFIX = "EKTE_"
LEGACY_PREFIX = "ZING_"
LEGACY_DIR_NAME = ".zing"
REMOVED_IN = "1.0.0"  # the release that removes this module

_warned: set[str] = set()


def _notice(text: str) -> None:
    print(f"ekte: {text}", file=sys.stderr)


@overload
def getenv(name: str) -> str | None: ...
@overload
def getenv(name: str, default: str) -> str: ...
def getenv(name: str, default: str | None = None) -> str | None:
    """``os.environ[name]`` for an ``EKTE_*`` name, else its ``ZING_*``
    predecessor (deprecated, noticed once per name), else ``default``."""
    value = os.environ.get(name)
    if value is not None or not name.startswith(PREFIX):
        return value if value is not None else default
    old = LEGACY_PREFIX + name[len(PREFIX):]
    value = os.environ.get(old)
    if value is None:
        return default
    if old not in _warned:
        _warned.add(old)
        _notice(f"{old} is deprecated and will stop working in ekte {REMOVED_IN}; use {name} instead.")
    return value


def _copy_db(src: Path, dst: Path) -> None:
    """A consistent copy of a SQLite database, even while zing writes to it
    (the backup API reads one snapshot, WAL content included)."""
    with contextlib.closing(sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)) as s, \
            contextlib.closing(sqlite3.connect(str(dst))) as d:
        s.backup(d)
    shutil.copymode(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(mode=0o700)
    shutil.copymode(src, dst)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_symlink():
            continue  # never follow links out of the data directory
        if entry.is_dir():
            _copy_tree(entry, target)
        elif entry.name.endswith(("-wal", "-shm", "-journal")):
            continue  # part of the database next to it, copied with it
        elif entry.suffix == ".db":
            _copy_db(entry, target)
        elif entry.is_file():
            shutil.copy2(entry, target)


def migrate_data_dir(new: Path, old: Path) -> bool:
    """Copy ``old`` to ``new`` when ``new`` does not exist and ``old`` is a
    directory; True when it copied. The copy goes to a temporary sibling that
    is renamed into place, so an interrupted copy is retried next time
    instead of leaving a half-filled ``new``. ``old`` is never changed."""
    if new.exists() or not old.is_dir() or old.is_symlink():
        return False
    tmp = new.with_name(f"{new.name}.migrating-{os.getpid()}")
    try:
        _copy_tree(old, tmp)
        tmp.rename(new)
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        if new.is_dir():  # another ekte process finished the copy first
            return False
        _notice(f"could not copy {old} to {new} ({exc}); starting with an empty {new}.")
        return False
    _notice(
        f"copied the zing data directory {old} to {new} (history, monitors, "
        f"knowledge base); ekte uses {new} from now on. {old} was left as it "
        "is for zing; delete it yourself once you no longer need it. "
        f"This copy is deprecated and is removed in ekte {REMOVED_IN}; ekte never deletes {old}."
    )
    return True
