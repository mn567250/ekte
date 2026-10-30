"""The user's own knowledge-base entries — ``kb.db`` in the data directory.

Profiles added in the web UI (or imported from YAML) are stored here, so a user
without an editable install — or with only the UI — can add models and use
them for runs. :func:`zing.knowledge.load_knowledge_base` layers these entries
on top of the packaged YAML and ``ZING_KB_DIR`` for every command, so
``zing check`` and ``zing serve`` resolve exactly the same profiles.

One table, one row per entry:

* ``kind = 'model'``: a full :class:`~zing.knowledge.schema.ModelProfile` for
  ``provider``/``model_id``. It adds a model to that provider, or — the user's
  entries have the highest priority — replaces a packaged or ``ZING_KB_DIR``
  model with the same id (reported as *shadowing* it).
* ``kind = 'provider'``: provider-level data. For a provider that does not
  exist otherwise it is the whole provider (display name, hints, shared
  fingerprints, …). For an existing provider only its lists are used and merged
  in by id — ``fingerprints`` by ``id``, ``base_url_hints`` and
  ``relay_red_flags`` as a set union; single-value fields of a packaged
  provider are never overridden.

Bodies are stored as JSON and validated again on every load; an entry that no
longer validates (e.g. after an upgrade changed the schema) is skipped with a
warning rather than breaking every audit.

A second table, ``kb_disabled``, switches off items that are *not* the user's
own entries (packaged or ``ZING_KB_DIR`` providers and models): one row per
switched-off ``(kind, provider, model_id)``. The user's own entries keep using
their ``enabled`` column. Older zing versions ignore the table.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from zing import datadir

DB_NAME = "kb.db"
KINDS = ("provider", "model")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    with datadir.connect(DB_NAME) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                kind        TEXT NOT NULL CHECK (kind IN ('provider', 'model')),
                provider    TEXT NOT NULL,
                model_id    TEXT NOT NULL DEFAULT '',
                body_json   TEXT NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 1,
                origin      TEXT,
                created_ts  REAL,
                updated_ts  REAL,
                UNIQUE (kind, provider, model_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_disabled (
                kind        TEXT NOT NULL CHECK (kind IN ('provider', 'model')),
                provider    TEXT NOT NULL,
                model_id    TEXT NOT NULL DEFAULT '',
                ts          REAL,
                PRIMARY KEY (kind, provider, model_id)
            )
            """
        )
        yield conn


def exists() -> bool:
    """Whether a kb.db exists at all (loading never creates one)."""
    return datadir.db_path(DB_NAME).is_file()


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        d["body"] = json.loads(d.pop("body_json") or "{}")
    except (TypeError, ValueError):
        d["body"] = None  # surfaced as an invalid entry by the loader
    d["enabled"] = bool(d.get("enabled"))
    if d.get("kind") == "provider":
        d["model_id"] = None
    return d


def list_entries(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    """All entries in insertion order (``body`` decoded). Empty without a kb.db."""
    if not exists():
        return []
    sql = "SELECT * FROM kb_entries"
    if enabled_only:
        sql += " WHERE enabled = 1"
    with _connect() as conn:
        rows = conn.execute(sql + " ORDER BY id").fetchall()
    return [_row(r) for r in rows]


def get(entry_id: int) -> dict[str, Any] | None:
    if not exists():
        return None
    with _connect() as conn:
        r = conn.execute("SELECT * FROM kb_entries WHERE id = ?", (int(entry_id),)).fetchone()
    return _row(r) if r else None


def find(kind: str, provider: str, model_id: str | None = None) -> dict[str, Any] | None:
    if not exists():
        return None
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM kb_entries WHERE kind = ? AND provider = ? AND model_id = ?",
            (kind, provider, model_id or ""),
        ).fetchone()
    return _row(r) if r else None


def upsert(
    kind: str,
    provider: str,
    body: dict[str, Any],
    *,
    model_id: str | None = None,
    origin: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Insert or replace the entry for (kind, provider, model_id); return its id.

    Callers validate ``body`` first (see :mod:`zing.knowledge.importer`); the
    store only persists it. Replacing keeps the id and ``created_ts``.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown entry kind: {kind!r}")
    if kind == "model" and not model_id:
        raise ValueError("a model entry needs a model_id")
    key = model_id if kind == "model" else ""
    now = time.time()
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True)

    def _do(c: sqlite3.Connection) -> int:
        c.execute(
            """INSERT INTO kb_entries
                   (kind, provider, model_id, body_json, enabled, origin, created_ts, updated_ts)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)
               ON CONFLICT (kind, provider, model_id) DO UPDATE SET
                   body_json = excluded.body_json,
                   origin = excluded.origin,
                   updated_ts = excluded.updated_ts""",
            (kind, provider, key, payload, origin, now, now),
        )
        row = c.execute(
            "SELECT id FROM kb_entries WHERE kind = ? AND provider = ? AND model_id = ?",
            (kind, provider, key),
        ).fetchone()
        return int(row["id"])

    if conn is not None:
        return _do(conn)
    with _connect() as c:
        return _do(c)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """One connection for several upserts, committed together (or not at all)."""
    with _connect() as conn:
        yield conn


def set_enabled(entry_id: int, enabled: bool) -> bool:
    """Enable/disable an entry; False if it doesn't exist."""
    if not exists():
        return False
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE kb_entries SET enabled = ?, updated_ts = ? WHERE id = ?",
            (1 if enabled else 0, time.time(), int(entry_id)),
        )
        return cur.rowcount > 0


def delete(entry_id: int) -> bool:
    """Remove an entry; False if it doesn't exist."""
    if not exists():
        return False
    with _connect() as conn:
        cur = conn.execute("DELETE FROM kb_entries WHERE id = ?", (int(entry_id),))
        return cur.rowcount > 0


def disabled_items() -> list[tuple[str, str, str]]:
    """Switched-off packaged / ``ZING_KB_DIR`` items as ``(kind, provider, model_id)``,
    sorted (``model_id`` is ``""`` for a provider). Empty without a kb.db."""
    if not exists():
        return []
    with _connect() as conn:
        rows = conn.execute("SELECT kind, provider, model_id FROM kb_disabled ORDER BY kind, provider, model_id").fetchall()
    return [(r["kind"], r["provider"], r["model_id"]) for r in rows]


def set_item_enabled(kind: str, provider: str, model_id: str | None, enabled: bool) -> None:
    """Switch a packaged / ``ZING_KB_DIR`` item on or off (see ``kb_disabled``)."""
    if kind not in KINDS:
        raise ValueError(f"unknown item kind: {kind!r}")
    if kind == "model" and not model_id:
        raise ValueError("a model item needs a model_id")
    key = model_id if kind == "model" else ""
    with _connect() as conn:
        if enabled:
            conn.execute(
                "DELETE FROM kb_disabled WHERE kind = ? AND provider = ? AND model_id = ?", (kind, provider, key)
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO kb_disabled (kind, provider, model_id, ts) VALUES (?, ?, ?, ?)",
                (kind, provider, key, time.time()),
            )
