"""Scheduled watch store — saved re-audit targets for the web monitor, stdlib only.

`ekte serve` can keep a list of *watches*: a target plus a cadence (interval),
suite, an alert threshold, and a set of webhooks. A background scheduler in the
web server runs each due watch on its interval and POSTs an alert when the risk
crosses the threshold or regresses versus the previous run. This module is the
persistence layer for those watch definitions — a tiny SQLite store, no new
dependency beyond ``sqlite3``.

Storage lives alongside the audit history in ``$EKTE_DATA_DIR`` (default
``~/.ekte``) as ``watches.db``. Like :mod:`ekte.web.history`, every function
opens a fresh short-lived connection so the module is safe to call from
FastAPI's threadpool, lazily creates its table, and is best-effort: a malformed
row must never crash the scheduler loop.

Secret handling: the scheduler needs a watch's ``api_key`` to run the audit.
Where it keeps it is the user's choice (:func:`get_key_storage`, a
``secret_meta`` row):

``memory`` (the default)  the key is never stored. The ``api_key`` column holds
                          only the marker ``mem:`` and the key itself stays in
                          this process's memory (:data:`_memory_keys`) until
                          ``ekte serve`` stops; then it has to be entered again.
``encrypted``             the key is kept in the DB, encrypted with
                          :mod:`ekte.secretbox` (``enc:v1:…``).

``env:``/``file:`` references hold no secret and are kept as they are in both
modes. The master key itself is never stored here, only its check value
(``secret_meta``), which :func:`adopt_key` rewrites in the same transaction as
the keys it re-encrypts. :func:`list_all` (the listing the browser sees) NEVER
returns the key, only whether one is held and can be used; :func:`get` and
:func:`due`, used server-side by the scheduler, return it in clear. A key that
cannot be used comes back as ``None`` with ``key_error`` set, never as a guess;
``key_locked`` when that is only because the master key is not entered yet,
``key_missing`` when a key that is not stored was lost with a restart.

Pinned knowledge-base profile: when a watch is created, the profile its
claimed model resolves to is snapshotted into this database (``kb_snapshots``,
linked by ``kb_snapshot_id``; how it matched and where it came from in
``kb_usage``). Every scheduled run audits against that fixed snapshot, so a
later knowledge-base edit cannot silently change what a monitor measures;
:func:`pin` re-pins it to the current knowledge base on request. A watch whose
model matched no profile at creation resolves the live knowledge base per run.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ekte import datadir, dbmigrate, i18n, secretbox
from ekte.config import SURFACES
from ekte.knowledge import snapshot as kb_snapshot

# Full column set, in table order. ``api_key`` lives here for the scheduler, but
# is filtered out of the public listing (see _LIST_COLS).
_ALL_COLS = (
    "id",
    "name",
    "base_url",
    "api_key",
    "model",
    "claimed_model",
    "api",
    "declared_provider",
    "suite",
    "interval_sec",
    "alert_on",
    "webhooks",
    "enabled",
    "created_ts",
    "last_run_ts",
    "last_risk",
    "last_score",
    "last_report_id",
    "language",
    "kb_snapshot_id",
    "kb_usage",
    "kb_pinned_ts",
    "dimensions",
    "source_report_id",
    "run_duration_sec",
    "performance_streaming",
    "surface",
    "embedding_dimensions",
)

# Columns safe to return to the browser — everything except the API key.
_LIST_COLS = tuple(c for c in _ALL_COLS if c != "api_key")


_DB_NAME = "watches.db"

_log = logging.getLogger(__name__)


def _db_path() -> Path:
    return datadir.db_path(_DB_NAME)


def _v1(conn: sqlite3.Connection) -> None:
    """The watches table as of 0.30.0 (idempotent: also adopts unversioned databases)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watches (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT,
            base_url          TEXT,
            api_key           TEXT,
            model             TEXT,
            claimed_model     TEXT,
            api               TEXT,
            declared_provider TEXT,
            suite             TEXT,
            interval_sec      INTEGER,
            alert_on          TEXT,
            webhooks          TEXT,
            enabled           INTEGER DEFAULT 1,
            created_ts        REAL,
            last_run_ts       REAL,
            last_risk         TEXT,
            last_score        REAL,
            last_report_id    INTEGER,
            language          TEXT
        )
        """
    )
    # Columns older databases lack. language: alert language (NULL = English,
    # see ekte.i18n.normalize); dimensions: the custom suite's dimensions (JSON
    # list); source_report_id: the history run a watch was scheduled from;
    # run_duration_sec: seconds the last run took (no monitor runs more often);
    # performance_streaming: 0 non-streaming, 1 or NULL streaming; surface:
    # "chat", "embedding" or "rerank" (NULL reads as chat); embedding_dimensions:
    # an embedding watch's claimed vector length (NULL or 0 takes the KB's).
    kb_snapshot.add_link_columns(
        conn,
        "watches",
        {
            "language": "TEXT",
            "dimensions": "TEXT",
            "source_report_id": "INTEGER",
            "run_duration_sec": "REAL",
            "performance_streaming": "INTEGER",
            "surface": "TEXT",
            "embedding_dimensions": "INTEGER",
        },
    )
    # The master key's check value (see ekte.secretbox.make_canary).
    conn.execute("CREATE TABLE IF NOT EXISTS secret_meta (name TEXT PRIMARY KEY, value TEXT)")


def _v2(conn: sqlite3.Connection) -> None:
    """Knowledge-base snapshots and the links from a watch to them."""
    kb_snapshot.ensure_table(conn)
    kb_snapshot.add_link_columns(
        conn, "watches", {"kb_snapshot_id": "INTEGER", "kb_usage": "TEXT", "kb_pinned_ts": "REAL"}
    )


MIGRATIONS = (dbmigrate.Migration(1, _v1), dbmigrate.Migration(2, _v2))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection with rows as dicts; commit + close on exit."""
    with datadir.connect(_DB_NAME, MIGRATIONS) as conn:
        yield conn


def init() -> None:
    """Create the tables. Idempotent; safe to call often."""
    with _connect():
        pass


def get_canary() -> str | None:
    """The stored check value of the master key, or None before there is one."""
    with _connect() as conn:
        row = conn.execute("SELECT value FROM secret_meta WHERE name = 'canary'").fetchone()
    return row["value"] if row else None


def _set_canary(conn: sqlite3.Connection, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM secret_meta WHERE name = 'canary'")
    else:
        conn.execute(
            "INSERT OR REPLACE INTO secret_meta (name, value) VALUES ('canary', ?)", (value,)
        )


_SECRET_ROWS = (
    "SELECT id, api_key FROM watches WHERE COALESCE(api_key, '') != ''"
    " AND api_key NOT LIKE 'env:%' AND api_key NOT LIKE 'file:%' AND api_key NOT LIKE 'mem:%'"
)

# ----- where the API keys are kept (see the module docstring) --------------- #
STORAGE_MEMORY = "memory"
STORAGE_ENCRYPTED = "encrypted"
STORAGE_MODES = (STORAGE_MEMORY, STORAGE_ENCRYPTED)

# The keys of ``memory`` mode, by watch id. Never written anywhere.
_memory_keys: dict[int, str] = {}
_memory_lock = threading.Lock()


def _remember(wid: int, key: str | None) -> None:
    with _memory_lock:
        if key:
            _memory_keys[int(wid)] = key
        else:
            _memory_keys.pop(int(wid), None)


def _held(wid: Any) -> str | None:
    try:
        wid = int(wid)
    except (TypeError, ValueError):
        return None
    with _memory_lock:
        return _memory_keys.get(wid)


def forget_memory_keys() -> None:
    """Drop every key held in memory (as when ``ekte serve`` stops)."""
    with _memory_lock:
        _memory_keys.clear()


def _stored_storage(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM secret_meta WHERE name = 'key_storage'").fetchone()
    return row["value"] if row and row["value"] in STORAGE_MODES else None


def _default_storage(conn: sqlite3.Connection) -> str:
    """No choice made yet: keep what an older version set up, else store nothing.

    A store that already holds encrypted keys or a master key check value, and
    a setup that provides a master key (``EKTE_SECRET_KEY``, a legacy
    ``secret.key``), keep encrypting; everything else stores no key.
    """
    has_encrypted = conn.execute(
        "SELECT 1 FROM secret_meta WHERE name = 'canary'"
        " UNION ALL SELECT 1 FROM watches WHERE api_key LIKE 'enc:%' LIMIT 1"
    ).fetchone()
    if has_encrypted or os.environ.get(secretbox.ENV, "").strip():
        return STORAGE_ENCRYPTED
    with contextlib.suppress(OSError):
        if secretbox.legacy_key_file().exists():
            return STORAGE_ENCRYPTED
    return STORAGE_MEMORY


def _set_storage(conn: sqlite3.Connection, mode: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO secret_meta (name, value) VALUES ('key_storage', ?)", (mode,)
    )


def get_key_storage() -> str:
    """``memory`` (API keys are never stored) or ``encrypted``."""
    with _connect() as conn:
        return _stored_storage(conn) or _default_storage(conn)


def settle_key_storage() -> str:
    """Record the default choice once (at startup), so it does not change later
    with the environment; returns the mode in effect."""
    with _connect() as conn:
        mode = _stored_storage(conn)
        if mode is None:
            mode = _default_storage(conn)
            _set_storage(conn, mode)
        return mode


def keys_to_memory(box: secretbox.SecretBox | None) -> int:
    """Stop storing API keys: move every stored key into memory, in one transaction.

    Encrypted keys are opened with ``box`` (raises SecretLocked without one
    when there are any, before anything is written); one it cannot open is
    dropped and has to be entered again, as it could not be used anyway. The
    check value goes too, and the freed pages are scrubbed. Returns how many
    keys now live in memory.
    """
    with _connect() as conn:
        held: dict[int, str] = {}
        rows = conn.execute(_SECRET_ROWS).fetchall()
        for r in rows:
            stored = r["api_key"]
            if not secretbox.is_sealed(stored):
                held[int(r["id"])] = stored
                continue
            if box is None:
                raise secretbox.SecretLocked("enter the master key to move the stored keys")
            try:
                held[int(r["id"])] = box.open(stored)
            except secretbox.SecretError as exc:
                _log.warning("watch %s: %s; enter its key again", r["id"], exc)
        conn.executemany(
            "UPDATE watches SET api_key = ? WHERE id = ?",
            [(secretbox.MEMORY, r["id"]) for r in rows],
        )
        _set_canary(conn, None)
        _set_storage(conn, STORAGE_MEMORY)
    with _memory_lock:
        _memory_keys.update(held)
    _status_cache.clear()
    _scrub()
    return len(held)


def keys_to_store(box: secretbox.SecretBox) -> int:
    """Store API keys encrypted: seal every key held in memory into the DB.

    A watch whose key was lost with a restart keeps waiting for it. Returns
    how many keys were written.
    """
    with _connect() as conn:
        ids = [
            int(r["id"])
            for r in conn.execute("SELECT id FROM watches WHERE api_key LIKE 'mem:%'").fetchall()
        ]
        with _memory_lock:
            updates = [(box.seal(_memory_keys[i]), i) for i in ids if i in _memory_keys]
        conn.executemany("UPDATE watches SET api_key = ? WHERE id = ?", updates)
        _set_storage(conn, STORAGE_ENCRYPTED)
    with _memory_lock:
        for _, i in updates:
            _memory_keys.pop(i, None)
    return len(updates)


def migrate_keys(box: secretbox.SecretBox) -> int:
    """Encrypt every ``api_key`` still stored in plain text; return the count.

    The old plain text is then scrubbed from SQLite's free pages and WAL.
    """
    with _connect() as conn:
        rows = [r for r in conn.execute(_SECRET_ROWS).fetchall() if secretbox.needs_seal(r["api_key"])]
        if not rows:
            return 0
        conn.executemany(
            "UPDATE watches SET api_key = ? WHERE id = ?",
            [(box.seal(r["api_key"]), r["id"]) for r in rows],
        )
    _scrub()
    return len(rows)


def adopt_key(box: secretbox.SecretBox, opener: secretbox.SecretBox | None = None) -> int:
    """Make ``box`` the master key of this store, in one transaction.

    Every stored key is re-encrypted with ``box``'s first key (plain-text ones
    are encrypted) and the check value is rewritten. ``opener`` decrypts the
    stored keys (rotation; ``box`` itself when it holds the old keys too) and
    then the change is all-or-nothing: a key it cannot open aborts before
    anything is written. Without an opener (no previous key) values sealed
    with an unknown key are left as they are: they stay unreadable until the
    user enters them again. Returns how many keys were written.
    """
    with _connect() as conn:
        updates = []
        for r in conn.execute(_SECRET_ROWS).fetchall():
            stored = r["api_key"]
            if secretbox.is_sealed(stored):
                if opener is None:
                    continue
                updates.append((box.seal(opener.open(stored)), r["id"]))
            else:
                updates.append((box.seal(stored), r["id"]))
        conn.executemany("UPDATE watches SET api_key = ? WHERE id = ?", updates)
        _set_canary(conn, secretbox.make_canary(box))
    _status_cache.clear()
    _scrub()
    return len(updates)


def forget_keys() -> int:
    """Drop every encrypted key and the check value (the master key is lost).

    The watches stay, paused, until their keys are entered again. Returns how
    many keys were dropped.
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE watches SET api_key = '', enabled = 0 WHERE api_key LIKE 'enc:%'"
        )
        _set_canary(conn, None)
        n = cur.rowcount
    _status_cache.clear()
    _scrub()
    return n


def _scrub() -> None:
    """Overwrite freed pages and truncate the WAL so replaced keys don't linger."""
    with datadir.connect(_DB_NAME, MIGRATIONS) as conn:
        conn.execute("PRAGMA secure_delete=ON")
        conn.commit()
        conn.isolation_level = None  # VACUUM cannot run inside a transaction
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def key_counts(box: secretbox.SecretBox | None = None) -> dict[str, int]:
    """How many keys are encrypted, references, plain, locked, unreadable,
    held in memory only, or lost with a restart (missing)."""
    counts = {
        "encrypted": 0, "reference": 0, "plain": 0, "locked": 0, "unreadable": 0,
        "memory": 0, "missing": 0,
    }
    box = box or secretbox.current()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, api_key FROM watches WHERE COALESCE(api_key, '') != ''"
        ).fetchall()
    for r in rows:
        status = _key_status(r["api_key"], box, r["id"])
        counts[status] = counts.get(status, 0) + 1
    return counts


# Whether a box opens a sealed value, memoized: the monitors page polls the
# listing every few seconds and each check is a decryption. Keyed by the
# ciphertext itself (not secret, and already held in memory by the caller) and
# the box's key list, so a new key never sees old answers.
_status_cache: dict[tuple[str, str], bool] = {}
_STATUS_CACHE_MAX = 2048


def _can_open(box: secretbox.SecretBox, stored: str) -> bool:
    key = (stored, box.cache_id())
    ok = _status_cache.get(key)
    if ok is None:
        if len(_status_cache) >= _STATUS_CACHE_MAX:
            _status_cache.clear()
        ok = _status_cache[key] = box.can_open(stored)
    return ok


def _key_status(stored: str | None, box: secretbox.SecretBox | None, wid: Any = None) -> str:
    """none | encrypted | reference | plain | locked | unreadable | memory |
    missing — never the key."""
    if not stored:
        return "none"
    if secretbox.is_reference(stored):
        return "reference"
    if secretbox.is_memory(stored):
        return "memory" if _held(wid) is not None else "missing"
    if not secretbox.is_sealed(stored):
        return "plain"
    if box is None:
        return "locked"
    return "encrypted" if _can_open(box, stored) else "unreadable"


def _open_key(d: dict[str, Any]) -> None:
    """Decrypt ``d["api_key"]`` in place; on failure set ``key_error`` instead.

    ``key_locked`` says the failure is only a master key not entered yet,
    ``key_missing`` that the key is not stored and was lost with a restart.
    """
    d["key_error"] = None
    d["key_locked"] = False
    d["key_missing"] = False
    stored = d.get("api_key")
    if secretbox.is_memory(stored):
        d["api_key"] = _held(d.get("id"))
        if d["api_key"] is None:
            d["key_error"] = "the API key is not stored and ekte serve restarted: enter it again"
            d["key_missing"] = True
        return
    if not secretbox.is_sealed(stored):
        d["api_key"] = stored or ""
        return
    try:
        d["api_key"] = secretbox.default().open(stored)
    except secretbox.SecretLocked as exc:
        d["api_key"] = None
        d["key_error"] = str(exc)
        d["key_locked"] = True
    except secretbox.SecretError as exc:
        _log.warning("watch %s: %s", d.get("id"), exc)
        d["api_key"] = None
        d["key_error"] = str(exc)


def _store_key(value: str | None, storage: str | None = None) -> tuple[str, str | None]:
    """What to write to the ``api_key`` column, and what to hold in memory.

    Keyless watches and references are stored as they are. A real secret is
    held in memory (``memory`` mode) or encrypted (``encrypted`` mode; raises
    SecretLocked without a master key). ``storage`` overrides the mode
    (``memory``: a request that asks for its key not to be stored).
    """
    value = str(value or "")
    if not value or secretbox.is_reference(value):
        return value, None
    if (storage or get_key_storage()) == STORAGE_MEMORY:
        return secretbox.MEMORY, value
    if secretbox.needs_seal(value) or secretbox.is_memory(value):
        return secretbox.default().seal(value), None
    return value, None


def _row_to_dict(row: sqlite3.Row, *, include_key: bool) -> dict[str, Any]:
    """Convert a row to a plain dict, decoding webhooks JSON and the enabled flag.

    When ``include_key`` is False the ``api_key`` column is omitted entirely so it
    can never leak to a caller that only asked for a listing.
    """
    d = dict(row)
    if not include_key:
        d.pop("api_key", None)
    else:
        _open_key(d)
    # webhooks is stored as a JSON list; decode defensively.
    raw = d.get("webhooks")
    try:
        d["webhooks"] = json.loads(raw) if isinstance(raw, str) and raw else []
    except (ValueError, TypeError):
        d["webhooks"] = []
    if not isinstance(d["webhooks"], list):
        d["webhooks"] = []
    d["enabled"] = bool(d.get("enabled"))
    # NULL (watches from before the setting existed) probes with streaming.
    d["performance_streaming"] = d.get("performance_streaming") != 0
    # NULL (watches from before surfaces existed) audits a chat endpoint.
    d["surface"] = d.get("surface") or "chat"
    d["embedding_dimensions"] = _dims(d.get("embedding_dimensions"))
    d["language"] = i18n.normalize(d.get("language"))
    raw_dims = d.get("dimensions")
    try:
        dims = json.loads(raw_dims) if isinstance(raw_dims, str) and raw_dims else []
    except (ValueError, TypeError):
        dims = []
    d["dimensions"] = [str(x) for x in dims] if isinstance(dims, list) else []
    # kb_usage: the pinned profile's match/sources (the profile itself stays
    # in kb_snapshots); exposed as `kb`, None when nothing is pinned.
    raw_kb = d.pop("kb_usage", None)
    try:
        kb = json.loads(raw_kb) if isinstance(raw_kb, str) and raw_kb else None
    except (ValueError, TypeError):
        kb = None
    d["kb"] = kb if isinstance(kb, dict) and d.get("kb_snapshot_id") is not None else None
    if d["kb"] is not None:
        d["kb"]["pinned_at"] = d.get("kb_pinned_ts")
    return d


def _pin(conn: sqlite3.Connection, wid: int, knowledge: dict[str, Any] | None) -> None:
    snap = (knowledge or {}).get("profile")
    if isinstance(snap, dict):
        sid: int | None = kb_snapshot.put(conn, snap)
        usage = json.dumps({**(knowledge or {}), "profile": None}, ensure_ascii=False, default=str)
        ts: float | None = time.time()
    else:
        sid, usage, ts = None, None, None
    conn.execute(
        "UPDATE watches SET kb_snapshot_id = ?, kb_usage = ?, kb_pinned_ts = ? WHERE id = ?",
        (sid, usage, ts, int(wid)),
    )
    kb_snapshot.prune(conn, "watches")


def pin(wid: int, knowledge: dict[str, Any] | None) -> None:
    """Pin (or re-pin) a watch to a knowledge-base profile.

    ``knowledge`` is a :class:`~ekte.models.KnowledgeUsage` dict with its
    ``profile`` snapshot; without one the watch resolves the live KB per run.
    """
    with _connect() as conn:
        _pin(conn, wid, knowledge)


def pinned_knowledge(wid: int) -> dict[str, Any] | None:
    """The pinned KnowledgeUsage dict (profile snapshot included), or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT kb_snapshot_id, kb_usage, kb_pinned_ts FROM watches WHERE id = ?", (int(wid),)
        ).fetchone()
        if not row or row["kb_snapshot_id"] is None or not row["kb_usage"]:
            return None
        snap = kb_snapshot.get(conn, row["kb_snapshot_id"])
    try:
        usage = json.loads(row["kb_usage"])
    except (ValueError, TypeError):
        return None
    if snap is None or not isinstance(usage, dict):
        return None
    return {**usage, "profile": snap, "pinned_at": row["kb_pinned_ts"]}


def _duration(raw: Any) -> float | None:
    """A positive run duration in seconds, else None."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        return None
    return round(float(raw), 1)


def _dims(raw: Any) -> int:
    """A claimed embedding vector length: a positive int, else 0 (from the KB)."""
    if isinstance(raw, bool):
        return 0
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def create(
    cfg: dict[str, Any],
    knowledge: dict[str, Any] | None = None,
    *,
    draft: bool = False,
    key_storage: str | None = None,
) -> int:
    """Insert a new watch from a config dict; return its new id.

    Expected keys: name, base_url, api_key, model, claimed_model, api,
    declared_provider, suite, dimensions (list; the custom suite's), interval_sec,
    alert_on, webhooks (list), language (alert language code; unknown/missing ->
    English), performance_streaming (False: the probe sends non-streaming
    requests), surface ("chat", "embedding" or "rerank"; missing or unknown -> chat),
    embedding_dimensions (an embedding watch's claimed vector length; 0 or
    missing -> the knowledge base's). Unknown keys are ignored;
    missing keys fall back to sensible defaults. ``knowledge`` (a
    KnowledgeUsage dict with its profile) pins the watch's profile.

    ``draft=True`` stores a watch scheduled from a history run: paused and with
    no interval (NULL) until the user sets one, linked to ``source_report_id``.
    ``key_storage`` overrides where the key is kept (see :func:`_store_key`).
    """
    cfg = cfg or {}
    webhooks = cfg.get("webhooks") or []
    if not isinstance(webhooks, list):
        webhooks = [webhooks]
    webhooks = [str(w).strip() for w in webhooks if str(w).strip()]
    surface = cfg.get("surface") if cfg.get("surface") in SURFACES else "chat"
    interval: int | None
    if draft:
        interval = None
    else:
        try:
            interval = max(30, int(cfg.get("interval_sec") or 3600))
        except (TypeError, ValueError):
            interval = 3600
    stored_key, held = _store_key(cfg.get("api_key"), key_storage)
    row = (
        cfg.get("name") or "watch",
        cfg.get("base_url"),
        stored_key,
        cfg.get("model"),
        cfg.get("claimed_model") or None,
        cfg.get("api") or "auto",
        cfg.get("declared_provider") or None,
        cfg.get("suite") or "standard",
        interval,
        cfg.get("alert_on") or "medium",
        json.dumps(webhooks, ensure_ascii=False),
        0 if draft or not cfg.get("enabled", True) else 1,
        time.time(),
        i18n.normalize(cfg.get("language")),
        json.dumps(list(cfg.get("dimensions") or [])) if cfg.get("dimensions") else None,
        cfg.get("source_report_id") if draft else None,
        _duration(cfg.get("run_duration_sec")),
        0 if cfg.get("performance_streaming") is False else 1,
        surface,
        # a claimed vector length means something only to an embedding watch
        (_dims(cfg.get("embedding_dimensions")) or None) if surface == "embedding" else None,
    )
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO watches
               (name, base_url, api_key, model, claimed_model, api,
                declared_provider, suite, interval_sec, alert_on, webhooks,
                enabled, created_ts, language, dimensions, source_report_id,
                run_duration_sec, performance_streaming, surface,
                embedding_dimensions)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
        wid = int(cur.lastrowid or -1)
        if knowledge is not None:
            _pin(conn, wid, knowledge)
    _remember(wid, held)
    return wid


def list_all() -> list[dict[str, Any]]:
    """All watches, newest first, WITHOUT api_key (safe for the browser).

    ``has_key`` says whether a key is set and ``key_status`` how (see
    :func:`_key_status`; ``locked`` waits for the master key, ``unreadable``
    and ``missing`` must be re-entered), without revealing it.
    """
    cols = ", ".join(_LIST_COLS)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {cols}, api_key AS _stored_key FROM watches ORDER BY id DESC"
        ).fetchall()
    box = secretbox.current()
    out = []
    for r in rows:
        d = _row_to_dict(r, include_key=False)
        stored = d.pop("_stored_key", None)
        d["has_key"] = bool(stored)
        d["key_status"] = _key_status(stored, box, d.get("id"))
        out.append(d)
    return out


def get(wid: int) -> dict[str, Any] | None:
    """One full watch row INCLUDING api_key, or ``None`` if missing.

    Server-side use only (the scheduler / run-now). Never hand this to a client
    response without stripping the key first.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM watches WHERE id = ?", (int(wid),)
        ).fetchone()
    return _row_to_dict(row, include_key=True) if row else None


def set_enabled(wid: int, enabled: bool) -> None:
    """Enable or disable a watch. No-op if it doesn't exist."""
    with _connect() as conn:
        conn.execute(
            "UPDATE watches SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, int(wid)),
        )


def set_language(wid: int, language: str | None) -> None:
    """Set a watch's alert language (unknown codes become English)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE watches SET language = ? WHERE id = ?",
            (i18n.normalize(language), int(wid)),
        )


def update(
    wid: int,
    *,
    interval_sec: int | None = None,
    api_key: str | None = None,
    alert_on: str | None = None,
    webhooks: list[str] | None = None,
    embedding_dimensions: int | None = None,
    key_storage: str | None = None,
) -> None:
    """Change a watch's schedule, key or alert settings; ``None`` leaves a field as is.

    Callers validate the values (see the PATCH endpoint); this only stores them.
    ``key_storage`` overrides where a new key is kept (see :func:`_store_key`).
    """
    held: str | None = None
    sets: list[str] = []
    vals: list[Any] = []
    if interval_sec is not None:
        sets.append("interval_sec = ?")
        vals.append(int(interval_sec))
    if api_key is not None:
        stored_key, held = _store_key(api_key, key_storage)
        sets.append("api_key = ?")
        vals.append(stored_key)
    if alert_on is not None:
        sets.append("alert_on = ?")
        vals.append(alert_on)
    if webhooks is not None:
        sets.append("webhooks = ?")
        vals.append(json.dumps(list(webhooks), ensure_ascii=False))
    if embedding_dimensions is not None:
        sets.append("embedding_dimensions = ?")
        vals.append(_dims(embedding_dimensions) or None)
    if not sets:
        return
    with _connect() as conn:
        conn.execute(f"UPDATE watches SET {', '.join(sets)} WHERE id = ?", (*vals, int(wid)))
    if api_key is not None:
        _remember(wid, held)


def delete(wid: int) -> None:
    """Remove one watch by id. No-op if it doesn't exist."""
    with _connect() as conn:
        conn.execute("DELETE FROM watches WHERE id = ?", (int(wid),))
        kb_snapshot.prune(conn, "watches")
    _remember(wid, None)


def mark_run(
    wid: int,
    risk: str | None,
    score: float | None,
    report_id: int | None,
    ts: float,
    *,
    duration_sec: float | None = None,
) -> None:
    """Record the outcome of a run: last risk/score/report id and run timestamp.

    ``duration_sec`` (a completed audit's execution time) replaces the stored
    one; a run that failed before finishing leaves it as it was.
    """
    with _connect() as conn:
        conn.execute(
            """UPDATE watches
               SET last_run_ts = ?, last_risk = ?, last_score = ?, last_report_id = ?,
                   run_duration_sec = COALESCE(?, run_duration_sec)
               WHERE id = ?""",
            (
                float(ts),
                risk,
                float(score) if isinstance(score, (int, float)) else None,
                int(report_id) if report_id is not None else None,
                _duration(duration_sec),
                int(wid),
            ),
        )


def mark_attempt(wid: int, ts: float) -> None:
    """Record a run that was cancelled: only its time, the last result stays."""
    with _connect() as conn:
        conn.execute("UPDATE watches SET last_run_ts = ? WHERE id = ?", (float(ts), int(wid)))


def due(now_ts: float) -> list[dict[str, Any]]:
    """Enabled watches whose interval has elapsed — full rows incl. api_key.

    A watch is due when it has never run, or when ``now - last_run >= interval``.
    A draft (no interval yet) is never due. Used by the scheduler, so the
    api_key is included to actually run the audit.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watches WHERE enabled = 1 AND interval_sec IS NOT NULL"
            " AND (last_run_ts IS NULL OR ? - last_run_ts >= interval_sec)",
            (float(now_ts),),
        ).fetchall()
    # Only the due rows are decrypted.
    return [_row_to_dict(r, include_key=True) for r in rows]
