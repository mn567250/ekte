"""Scheduled watch store — saved re-audit targets for the web monitor, stdlib only.

`zing serve` can keep a list of *watches*: a target plus a cadence (interval),
suite, an alert threshold, and a set of webhooks. A background scheduler in the
web server runs each due watch on its interval and POSTs an alert when the risk
crosses the threshold or regresses versus the previous run. This module is the
persistence layer for those watch definitions — a tiny SQLite store, no new
dependency beyond ``sqlite3``.

Storage lives alongside the audit history in ``$ZING_DATA_DIR`` (default
``~/.zing``) as ``watches.db``. Like :mod:`zing.web.history`, every function
opens a fresh short-lived connection so the module is safe to call from
FastAPI's threadpool, lazily creates its table, and is best-effort: a malformed
row must never crash the scheduler loop.

Secret handling: the stored ``api_key`` is what the scheduler needs to actually
run the audit, so it is kept in the DB — encrypted with :mod:`zing.secretbox`
(``enc:v1:…``); ``env:``/``file:`` references are kept as they are. The master
key itself is never stored here, only its check value (``secret_meta``), which
:func:`adopt_key` rewrites in the same transaction as the keys it re-encrypts.
:func:`list_all` (the listing the browser sees) NEVER returns the key, only
whether one is stored and can be decrypted; :func:`get` and :func:`due`, used
server-side by the scheduler, return it decrypted. A key that cannot be
decrypted comes back as ``None`` with ``key_error`` set, never as a guess, and
``key_locked`` when that is only because the master key is not entered yet.

Pinned knowledge-base profile: when a watch is created, the profile its
claimed model resolves to is snapshotted into this database (``kb_snapshots``,
linked by ``kb_snapshot_id``; how it matched and where it came from in
``kb_usage``). Every scheduled run audits against that fixed snapshot, so a
later knowledge-base edit cannot silently change what a monitor measures;
:func:`pin` re-pins it to the current knowledge base on request. A watch whose
model matched no profile at creation resolves the live knowledge base per run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from zing import datadir, i18n, secretbox
from zing.knowledge import snapshot as kb_snapshot

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
)

# Columns safe to return to the browser — everything except the API key.
_LIST_COLS = tuple(c for c in _ALL_COLS if c != "api_key")


_DB_NAME = "watches.db"

_log = logging.getLogger(__name__)


def _db_path() -> Path:
    return datadir.db_path(_DB_NAME)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection with rows as dicts; commit + close on exit."""
    with datadir.connect(_DB_NAME) as conn:
        _ensure_table(conn)
        yield conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Lazily create the watches table. Idempotent."""
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
    # Databases created before alerts were translatable lack `language`; add
    # it (NULL = English, see zing.i18n.normalize).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(watches)")}
    if "language" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN language TEXT")
    # The custom suite's dimensions (JSON list); NULL for the fixed suites.
    if "dimensions" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN dimensions TEXT")
    # The history run a watch was scheduled from (NULL for form-created ones).
    if "source_report_id" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN source_report_id INTEGER")
    # Seconds the last completed run took (from the history run for a draft);
    # no monitor is scheduled more often than that.
    if "run_duration_sec" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN run_duration_sec REAL")
    # The performance probe's request mode: 0 non-streaming, 1 or NULL streaming
    # (the full suite measures both either way).
    if "performance_streaming" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN performance_streaming INTEGER")
    # The audited surface ("chat" or "embedding"); NULL reads as chat.
    if "surface" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN surface TEXT")
    # The master key's check value (see zing.secretbox.make_canary).
    conn.execute("CREATE TABLE IF NOT EXISTS secret_meta (name TEXT PRIMARY KEY, value TEXT)")
    kb_snapshot.ensure_table(conn)
    kb_snapshot.add_link_columns(
        conn, "watches", {"kb_snapshot_id": "INTEGER", "kb_usage": "TEXT", "kb_pinned_ts": "REAL"}
    )


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
    " AND api_key NOT LIKE 'env:%' AND api_key NOT LIKE 'file:%'"
)


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
    with datadir.connect(_DB_NAME) as conn:
        conn.execute("PRAGMA secure_delete=ON")
        conn.commit()
        conn.isolation_level = None  # VACUUM cannot run inside a transaction
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def key_counts(box: secretbox.SecretBox | None = None) -> dict[str, int]:
    """How many stored keys are encrypted, references, plain, locked or unreadable."""
    counts = {"encrypted": 0, "reference": 0, "plain": 0, "locked": 0, "unreadable": 0}
    box = box or secretbox.current()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT api_key FROM watches WHERE COALESCE(api_key, '') != ''"
        ).fetchall()
    for r in rows:
        status = _key_status(r["api_key"], box)
        counts[status] = counts.get(status, 0) + 1
    return counts


# Whether a box opens a sealed value, memoized: the monitors page polls the
# listing every few seconds and each check is a decryption. Keyed by the
# ciphertext's hash and the box's key list, so a new key never sees old answers.
_status_cache: dict[tuple[str, str], bool] = {}
_STATUS_CACHE_MAX = 2048


def _can_open(box: secretbox.SecretBox, stored: str) -> bool:
    import hashlib

    key = (hashlib.sha256(stored.encode("utf-8")).hexdigest(), box.cache_id())
    ok = _status_cache.get(key)
    if ok is None:
        if len(_status_cache) >= _STATUS_CACHE_MAX:
            _status_cache.clear()
        ok = _status_cache[key] = box.can_open(stored)
    return ok


def _key_status(stored: str | None, box: secretbox.SecretBox | None) -> str:
    """none | encrypted | reference | plain | locked | unreadable — never the key."""
    if not stored:
        return "none"
    if secretbox.is_reference(stored):
        return "reference"
    if not secretbox.is_sealed(stored):
        return "plain"
    if box is None:
        return "locked"
    return "encrypted" if _can_open(box, stored) else "unreadable"


def _open_key(d: dict[str, Any]) -> None:
    """Decrypt ``d["api_key"]`` in place; on failure set ``key_error`` instead.

    ``key_locked`` says the failure is only a master key not entered yet.
    """
    d["key_error"] = None
    d["key_locked"] = False
    stored = d.get("api_key")
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


def _seal(value: str | None) -> str:
    """Encrypt a key for storage. Only a real secret needs the master key
    (raises SecretLocked without one); keyless watches and references don't."""
    if not secretbox.needs_seal(value):
        return str(value or "")
    return secretbox.default().seal(value)


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

    ``knowledge`` is a :class:`~zing.models.KnowledgeUsage` dict with its
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


def create(
    cfg: dict[str, Any], knowledge: dict[str, Any] | None = None, *, draft: bool = False
) -> int:
    """Insert a new watch from a config dict; return its new id.

    Expected keys: name, base_url, api_key, model, claimed_model, api,
    declared_provider, suite, dimensions (list; the custom suite's), interval_sec,
    alert_on, webhooks (list), language (alert language code; unknown/missing ->
    English), performance_streaming (False: the probe sends non-streaming
    requests), surface ("chat" or "embedding"; missing -> chat). Unknown keys are ignored;
    missing keys fall back to sensible defaults. ``knowledge`` (a
    KnowledgeUsage dict with its profile) pins the watch's profile.

    ``draft=True`` stores a watch scheduled from a history run: paused and with
    no interval (NULL) until the user sets one, linked to ``source_report_id``.
    """
    cfg = cfg or {}
    webhooks = cfg.get("webhooks") or []
    if not isinstance(webhooks, list):
        webhooks = [webhooks]
    webhooks = [str(w).strip() for w in webhooks if str(w).strip()]
    interval: int | None
    if draft:
        interval = None
    else:
        try:
            interval = max(30, int(cfg.get("interval_sec") or 3600))
        except (TypeError, ValueError):
            interval = 3600
    row = (
        cfg.get("name") or "watch",
        cfg.get("base_url"),
        _seal(cfg.get("api_key")),
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
        cfg.get("surface") or "chat",
    )
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO watches
               (name, base_url, api_key, model, claimed_model, api,
                declared_provider, suite, interval_sec, alert_on, webhooks,
                enabled, created_ts, language, dimensions, source_report_id,
                run_duration_sec, performance_streaming, surface)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
        wid = int(cur.lastrowid or -1)
        if knowledge is not None:
            _pin(conn, wid, knowledge)
        return wid


def list_all() -> list[dict[str, Any]]:
    """All watches, newest first, WITHOUT api_key (safe for the browser).

    ``has_key`` says whether a key is stored and ``key_status`` how (see
    :func:`_key_status`; ``locked`` waits for the master key, ``unreadable``
    must be re-entered), without
    revealing it.
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
        d["key_status"] = _key_status(stored, box)
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
) -> None:
    """Change a watch's schedule, key or alert settings; ``None`` leaves a field as is.

    Callers validate the values (see the PATCH endpoint); this only stores them.
    """
    sets: list[str] = []
    vals: list[Any] = []
    if interval_sec is not None:
        sets.append("interval_sec = ?")
        vals.append(int(interval_sec))
    if api_key is not None:
        sets.append("api_key = ?")
        vals.append(_seal(api_key))
    if alert_on is not None:
        sets.append("alert_on = ?")
        vals.append(alert_on)
    if webhooks is not None:
        sets.append("webhooks = ?")
        vals.append(json.dumps(list(webhooks), ensure_ascii=False))
    if not sets:
        return
    with _connect() as conn:
        conn.execute(f"UPDATE watches SET {', '.join(sets)} WHERE id = ?", (*vals, int(wid)))


def delete(wid: int) -> None:
    """Remove one watch by id. No-op if it doesn't exist."""
    with _connect() as conn:
        conn.execute("DELETE FROM watches WHERE id = ?", (int(wid),))
        kb_snapshot.prune(conn, "watches")


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
