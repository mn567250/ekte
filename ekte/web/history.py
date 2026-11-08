"""Local audit history + trends — a tiny SQLite store, stdlib only.

`ekte serve` persists every finished AuditReport here so the web app can show a
history table and per-target score trends. No new dependency: just `sqlite3`.

Storage lives in ``$EKTE_DATA_DIR`` (default ``~/.ekte``) as ``history.db``.
Every public function opens a fresh, short-lived connection so the module is
safe to call from FastAPI's threadpool without sharing a connection across
threads. Writes are best-effort: a malformed report must never break the audit
stream, so :func:`save` swallows its own errors and returns ``-1`` on failure.

Knowledge-base snapshots: the full profile a run was audited against
(``report.knowledge.profile``) is stored once per distinct content in
``kb_snapshots`` and linked from the row (``kb_snapshot_id``); the saved
report JSON carries only the hash, and :func:`get` puts the profile back.
Snapshots no row points to any more are deleted with the rows.

Performance headline: the target's p50 latency / TTFT / decode speed (see
:func:`_perf_headline`) is stored in its own columns when a row is saved, so
the list and trend views never parse ``report_json``. ``perf_done`` marks a
row whose headline has been computed, which tells "no performance data" (all
three NULL) apart from "not computed yet". Rows saved before those columns
existed are backfilled once after the migration; any row still unmarked (a
failed backfill, or a row written by an older ekte) is computed when it is
first read and written back.

Analytics (schema version 2): every saved run also gets a row of extracted
metrics plus its dimension and detector scores (and, from schema version 9, its
outcome counts per op in ``history_outcomes``), and its ``performance.requests``
records move out of ``report_json`` into ``history_requests``, stored once and
put back by :func:`get` / :func:`latest_for`, so a report reads back identical
to the one saved (the tables are described in :mod:`ekte.web.analytics_store`).
``requests_split`` says where a row's records are: 1 in ``history_requests``,
0 inline (or none), NULL not looked at yet (a row from before version 2, or
one written by an older ekte). Such rows are processed by a batched backfill
(:func:`backfill_analytics`), which also re-extracts rows whose
``extract_version`` is behind ``analytics_store.EXTRACT_VERSION``.

Evidence (schema version 5): a run that kept its raw request/response pairs
names its file (``report.evidence.file``, see :mod:`ekte.evidence`) in the
``evidence_file`` column. The file lives in the data directory's ``evidence``
folder; deleting the last row that names it deletes it (a re-scored run,
:mod:`ekte.replay`, names its original's file), and :func:`sweep_evidence`
removes files no row names.

Data version (schema version 8): ``meta`` holds ``data_version``, a counter
bumped in the same transaction as every write that changes what the web
endpoints return (:func:`save`, :func:`delete`, :func:`clear`, the analytics
and perf backfills), from whichever process writes. :func:`data_version`
reads it; the web response cache (:mod:`ekte.web.cache`) keys on it.

Relay map (schema version 7): ``relay_map`` maps each distinct run URL to
its knowledge-base relay so SQL can group and filter runs by relay; it is
rebuilt from the knowledge base on demand (see :mod:`ekte.web.relay_map`).

Query index (schema version 10): ``idx_history_query`` covers the columns
:mod:`ekte.web.query` reads from ``history``, so filtering and grouping never
read a run's report.

``PRAGMA user_version`` records the schema version; the numbered steps are in
``MIGRATIONS`` and are applied by :mod:`ekte.dbmigrate`.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ekte import datadir, dbmigrate
from ekte import evidence as evidence_files
from ekte.knowledge import snapshot as kb_snapshot
from ekte.web import analytics_store

# Columns returned by the list view (everything except the heavy report_json).
_SUMMARY_COLS = (
    "id",
    "ts",
    "base_url",
    "claimed_model",
    "model",
    "mode",
    "suite",
    "risk_level",
    "score",
    "rating",
    "kb_match",
    "watch_id",
    "api",
    "api_auto",
    "stream_mode",
    "surface",
)

# Performance headline columns, in the order the API returns them.
_PERF_COLS = ("latency_p50_ms", "ttft_p50_ms", "decode_tps_p50")
# Set to 1 once a row's headline has been computed (its values may all be NULL).
_PERF_DONE = "perf_done"
# 1: the row's request records are in history_requests; 0: inline (or none);
# NULL: not looked at yet.
_SPLIT = "requests_split"

_DB_NAME = "history.db"

_BACKFILL_BATCH = 100
# Rows per analytics backfill transaction: each one parses a whole report, so
# fewer than the perf backfill, to keep the write lock short.
_ANALYTICS_BATCH = 25


def _db_path() -> Path:
    return datadir.db_path(_DB_NAME)


def _v1(conn: sqlite3.Connection) -> None:
    """The base schema (idempotent: also adopts databases from before versioning)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT,
            base_url      TEXT,
            claimed_model TEXT,
            model         TEXT,
            mode          TEXT,
            suite         TEXT,
            risk_level    TEXT,
            score         REAL,
            rating        TEXT,
            report_json   TEXT
        )
        """
    )
    # Speeds up lookups for a given target+model.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_target "
        "ON history (base_url, claimed_model, id)"
    )
    kb_snapshot.ensure_table(conn)
    # Databases from before knowledge snapshots lack the link columns.
    kb_snapshot.add_link_columns(conn, "history", {"kb_snapshot_id": "INTEGER", "kb_match": "TEXT"})
    # The monitor (watch) that produced a run; NULL for runs started by hand.
    kb_snapshot.add_link_columns(conn, "history", {"watch_id": "INTEGER"})
    # The run's wire protocol, whether it was auto-detected, and the probe's
    # request mode; NULL for runs saved before these were recorded.
    kb_snapshot.add_link_columns(
        conn, "history", {"api": "TEXT", "api_auto": "INTEGER", "stream_mode": "TEXT"}
    )
    # The performance headline, so list and trend views need not parse report_json.
    kb_snapshot.add_link_columns(
        conn, "history", {**dict.fromkeys(_PERF_COLS, "REAL"), _PERF_DONE: "INTEGER"}
    )
    # Groups runs by model across relays.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_model ON history (claimed_model)")


def _v2(conn: sqlite3.Connection) -> None:
    """Where a row's request records are, and the analytics tables."""
    kb_snapshot.add_link_columns(conn, "history", {_SPLIT: "INTEGER"})
    # The rows the analytics backfill has not processed yet.
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_history_pending ON history (id) WHERE {_SPLIT} IS NULL"
    )
    analytics_store.ensure_tables(conn)


def _v3(conn: sqlite3.Connection) -> None:
    """Decode speed p5 / p95 (filled by the analytics backfill, which
    re-extracts every row of an older EXTRACT_VERSION)."""
    kb_snapshot.add_link_columns(
        conn, "history_metrics", {"decode_tps_p5": "REAL", "decode_tps_p95": "REAL"}
    )


def _v4(conn: sqlite3.Connection) -> None:
    """The audited surface ("chat", "embedding" or "rerank"); NULL (rows saved
    before surfaces existed) reads as chat."""
    kb_snapshot.add_link_columns(conn, "history", {"surface": "TEXT"})


def _v5(conn: sqlite3.Connection) -> None:
    """The run's evidence file (its name in the data directory's ``evidence``
    folder); NULL when the run kept none."""
    kb_snapshot.add_link_columns(conn, "history", {"evidence_file": "TEXT"})


def _v6(conn: sqlite3.Connection) -> None:
    """Where a failed request failed (``error_class``) and whether it was
    repeated (``retried``); records saved before read back without them."""
    analytics_store.add_request_columns(
        conn, {"error_class": "str", "retried": "bool"}
    )


def _v7(conn: sqlite3.Connection) -> None:
    """The relay of each distinct run URL (:mod:`ekte.web.relay_map`); filled
    on first use by ``relay_map.ensure_relay_map``."""
    from ekte.web import relay_map  # it imports the analytics queries, which import this module

    relay_map.ensure_tables(conn)


def _v8(conn: sqlite3.Connection) -> None:
    """The ``meta`` key/value table and its ``data_version`` counter.

    Idempotent (another step may have created ``meta`` already); values are
    read with a CAST, so either column affinity works."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value)")
    conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('data_version', 0)")


def _v9(conn: sqlite3.Connection) -> None:
    """Outcome counts per run and op (``history_outcomes``) and the outcome
    rates' bases (filled by the analytics backfill, which re-extracts every
    row of an older EXTRACT_VERSION)."""
    analytics_store.ensure_tables(conn)
    kb_snapshot.add_link_columns(
        conn,
        "history_metrics",
        {"impaired_rate": "REAL", "requests_total": "INTEGER", "requests_judged": "INTEGER"},
    )


# The history columns the query core (ekte/web/query.py) filters, groups and
# sorts by, in a covering index: a run's row holds its report_json (tens of
# kB, in overflow pages) before most of them, so reading them from the table
# would read the whole report of every run.
QUERY_INDEX_COLS = (
    "id", "surface", "watch_id", "base_url", "claimed_model", "model", "mode", "suite",
    "risk_level", "score", "rating", "api", "api_auto", "stream_mode",
)


def _v10(conn: sqlite3.Connection) -> None:
    """The covering index of the query core (:data:`QUERY_INDEX_COLS`)."""
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_history_query ON history ({', '.join(QUERY_INDEX_COLS)})"
    )


MIGRATIONS = (
    dbmigrate.Migration(1, _v1),
    dbmigrate.Migration(2, _v2),
    dbmigrate.Migration(3, _v3),
    dbmigrate.Migration(4, _v4),
    dbmigrate.Migration(5, _v5),
    dbmigrate.Migration(6, _v6),
    dbmigrate.Migration(7, _v7),
    dbmigrate.Migration(8, _v8),
    dbmigrate.Migration(9, _v9),
    dbmigrate.Migration(10, _v10),
)
_SCHEMA_VERSION = dbmigrate.latest(MIGRATIONS)


def _after_migration(conn: sqlite3.Connection) -> None:
    """Fill the columns new steps added for existing rows.

    Runs after the schema transactions, so other threads already see the new
    schema and compute any row the backfill has not reached yet.
    """
    try:
        _backfill_perf(conn)
    except Exception:
        # Best-effort: rows left unmarked are computed on read instead.
        conn.rollback()
    try:
        _backfill_analytics(conn)
    except Exception:
        # Best-effort: rows left over are picked up by backfill_analytics().
        conn.rollback()


_SET_PERF = (
    f"UPDATE history SET {', '.join(f'{c} = ?' for c in _PERF_COLS)}, {_PERF_DONE} = 1 "
    "WHERE id = ?"
)


def _backfill_perf(conn: sqlite3.Connection) -> None:
    """Compute the perf headline of every row not marked ``perf_done``.

    Works in batches and commits after each one, so other writers are not
    locked out for long. Idempotent: a row computed twice gets the same values.
    """
    last = 0
    while True:
        rows = conn.execute(
            f"SELECT id, report_json FROM history WHERE id > ? AND {_PERF_DONE} IS NULL"
            " ORDER BY id LIMIT ?",
            (last, _BACKFILL_BATCH),
        ).fetchall()
        if not rows:
            return
        conn.executemany(
            _SET_PERF,
            [(*_perf_headline(r["report_json"]).values(), r["id"]) for r in rows],
        )
        _bump(conn)
        conn.commit()
        last = int(rows[-1]["id"])


def _fill_perf(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    """Pop ``perf_done`` from each item; compute the headline of items not yet
    marked from their report_json, and store it (best-effort)."""
    todo = {int(item["id"]): item for item in items if not item.pop(_PERF_DONE, None)}
    if not todo:
        return
    ids = list(todo)
    updates = []
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        rows = conn.execute(
            f"SELECT id, report_json FROM history WHERE id IN ({', '.join('?' * len(chunk))})",
            chunk,
        ).fetchall()
        for r in rows:
            headline = _perf_headline(r["report_json"])
            todo[int(r["id"])].update(headline)
            updates.append((*headline.values(), r["id"]))
    try:
        conn.executemany(_SET_PERF, updates)
        _bump(conn)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()


# Rows the analytics backfill has to process: not looked at yet (those have
# no metrics either: a row gets both in one transaction), or extracted by an
# older EXTRACT_VERSION. Both halves are index lookups, so a database with
# nothing left to do costs next to nothing, however large its reports.
_ANALYTICS_TODO = f"""SELECT id FROM history WHERE {_SPLIT} IS NULL
   UNION SELECT history_id FROM history_metrics INDEXED BY idx_history_metrics_version
   WHERE extract_version < ?"""


def _analytics_work(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[Any, ...] | None:
    """What the backfill writes for one row: ``(id, new report_json or None,
    encoded request records or None, metrics, dimensions, outcomes)``; None to
    skip it."""
    try:
        report = json.loads(row["report_json"]) if row["report_json"] is not None else None
    except (ValueError, TypeError):
        report = None
    report_json = None
    records = None
    if row[_SPLIT] == 1 and isinstance(report, dict):
        analytics_store.restore_requests(report, analytics_store.get_requests(conn, row["id"]))
    try:
        if row[_SPLIT] is None and isinstance(report, dict):
            stored, records = analytics_store.split_requests(report)
            if records is not None:
                report_json = json.dumps(stored, ensure_ascii=False)
        extracted = analytics_store.extract_metrics(report)
    except Exception:
        return None
    return row["id"], report_json, records, *extracted


def _backfill_analytics(conn: sqlite3.Connection) -> None:
    """Move inline request records out of ``report_json`` and extract metrics,
    for every row that needs it (see ``_ANALYTICS_TODO``).

    Reads and parses a batch first, then writes it in one short transaction: a
    row is either fully processed (report_json, its records and metrics) or
    untouched. Idempotent, and safe next to a second process doing the same:
    a row's records move only while it is still unmarked, and nothing is
    written for a row deleted in the meantime.
    """
    pending = sorted(
        int(r[0]) for r in conn.execute(_ANALYTICS_TODO, (analytics_store.EXTRACT_VERSION,))
    )
    for start in range(0, len(pending), _ANALYTICS_BATCH):
        ids = pending[start:start + _ANALYTICS_BATCH]
        rows = conn.execute(
            f"SELECT id, report_json, {_SPLIT} FROM history"
            f" WHERE id IN ({', '.join('?' * len(ids))}) ORDER BY id",
            ids,
        ).fetchall()
        work = [w for w in (_analytics_work(conn, r) for r in rows) if w is not None]
        split = {int(r["id"]): r[_SPLIT] for r in rows}
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Analytics rows of a run that is gone (deleted by an older ekte,
            # which does not know these tables): ids are never reused.
            for rid in ids:
                if rid not in split:
                    analytics_store.delete_for(conn, rid)
            for rid, report_json, records, *extracted in work:
                if split[rid] is None:
                    if records is not None:
                        cur = conn.execute(
                            f"UPDATE history SET report_json = ?, {_SPLIT} = 1"
                            f" WHERE id = ? AND {_SPLIT} IS NULL",
                            (report_json, rid),
                        )
                        if cur.rowcount:
                            analytics_store.put_requests(conn, rid, records)
                    else:
                        conn.execute(
                            f"UPDATE history SET {_SPLIT} = 0 WHERE id = ? AND {_SPLIT} IS NULL",
                            (rid,),
                        )
                analytics_store.put_metrics(conn, rid, *extracted)
            _bump(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def backfill_analytics() -> None:
    """Bring the analytics tables up to date with every saved run.

    Runs once after the schema migration; call it before reading the analytics
    tables to pick up rows written since by an older ekte, or extracted by an
    older ``EXTRACT_VERSION``. Costs one query when nothing is left.
    """
    with _connect() as conn:
        _backfill_analytics(conn)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection with rows as dicts; commit + close on exit."""
    with datadir.connect(_DB_NAME, MIGRATIONS, _after_migration) as conn:
        yield conn


def _read() -> sqlite3.Connection:
    """This thread's reused read-only connection (see :func:`ekte.datadir.read_connection`)."""
    return datadir.read_connection(_DB_NAME, MIGRATIONS, _after_migration)


_BUMP_SQL = (
    "INSERT INTO meta (key, value) VALUES ('data_version', 1)"
    " ON CONFLICT (key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
)


def _bump(conn: sqlite3.Connection) -> None:
    """Increment ``data_version``; call inside the write's own transaction."""
    conn.execute(_BUMP_SQL)


def data_version() -> int:
    """The database's write counter: changes with every committed write that
    changes what the web endpoints return, from any process. One primary-key
    lookup on this thread's read connection."""
    row = _read().execute(
        "SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'data_version'"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def init() -> None:
    """Create the tables if they don't exist. Idempotent; safe to call often."""
    with _connect():
        pass


def save(report: dict[str, Any], watch_id: int | None = None) -> int:
    """Persist one AuditReport dict; return the new row id (``-1`` on failure).

    ``watch_id`` marks a run produced by that monitor, so the UI does not offer
    to schedule it as a monitor again.

    Best-effort by contract: this is called from inside the SSE stream, so any
    extraction or DB error is swallowed rather than allowed to abort the audit.
    """
    try:
        # As plain JSON (what reading it back gives), so the request records
        # and metrics below see exactly what is stored.
        report = json.loads(json.dumps(dict(report or {}), ensure_ascii=False, default=str))
        target = report.get("target") or {}
        verdict = report.get("verdict") or {}
        score = verdict.get("overall_score")
        knowledge = report.get("knowledge")
        if not isinstance(knowledge, dict):
            knowledge = {}
        api_auto = target.get("api_auto")
        snap = knowledge.get("profile")
        if isinstance(snap, dict):
            # The profile lives in kb_snapshots; the row keeps only the hash.
            report["knowledge"] = {**knowledge, "profile": None}
        # The request records go to history_requests; report_json keeps an
        # empty list in their place (kept inline if they cannot be moved).
        metrics: tuple[Any, ...] | None = None
        stored, records, split = report, None, None
        try:
            metrics = analytics_store.extract_metrics(report)
            stored, records = analytics_store.split_requests(report)
            split = 1 if records is not None else 0
        except Exception:
            # Left unmarked with its records inline: the backfill retries it.
            metrics, stored, records, split = None, report, None, None
        report_json = json.dumps(stored, ensure_ascii=False)
        # Serialised the same way, so the stored headline is exactly what
        # reading report_json back would give.
        headline = _perf_headline(json.dumps({"performance": report.get("performance")}))
        with _connect() as conn:
            snapshot_id = kb_snapshot.put(conn, snap) if isinstance(snap, dict) else None
            cur = conn.execute(
                """INSERT INTO history
                   (ts, base_url, claimed_model, model, mode, suite,
                    risk_level, score, rating, report_json, kb_snapshot_id, kb_match, watch_id,
                    api, api_auto, stream_mode, surface,
                    latency_p50_ms, ttft_p50_ms, decode_tps_p50, perf_done, requests_split,
                    evidence_file)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                (
                    report.get("generated_at"),
                    target.get("base_url"),
                    # Fall back to the concrete model id when no claim was made, so the
                    # trend grouping key is always populated.
                    target.get("claimed_model") or target.get("model"),
                    target.get("model"),
                    report.get("mode"),
                    report.get("suite"),
                    verdict.get("risk_level"),
                    float(score) if isinstance(score, (int, float)) else None,
                    verdict.get("rating"),
                    report_json,
                    snapshot_id,
                    knowledge.get("match_confidence"),
                    int(watch_id) if watch_id is not None else None,
                    target.get("api"),
                    int(api_auto) if isinstance(api_auto, bool) else None,
                    report.get("stream_mode"),
                    report.get("surface") or "chat",
                    *(headline[c] for c in _PERF_COLS),
                    split,
                    _evidence_name(report),
                ),
            )
            rid = int(cur.lastrowid or -1)
            # The same transaction: the row is stored with its records, or not at all.
            if records is not None:
                analytics_store.put_requests(conn, rid, records)
            if metrics is not None:
                analytics_store.put_metrics(conn, rid, *metrics)
            _bump(conn)
            return rid
    except Exception:
        return -1


def recent(limit: int = 50, perf: bool = False) -> list[dict[str, Any]]:
    """Most recent audits, newest first — summary columns only (no report).

    With ``perf`` each row also carries the performance headline of its report
    (``latency_p50_ms`` / ``ttft_p50_ms`` / ``decode_tps_p50``, see
    :func:`_perf_headline`) so the UI can draw trends without one call per group.
    """
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 50
    cols = ", ".join(_SUMMARY_COLS + ((*_PERF_COLS, _PERF_DONE) if perf else ()))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = [_with_surface(dict(r)) for r in rows]
        if perf:
            _fill_perf(conn, out)
    return out


def status() -> dict[str, Any]:
    """What the pages' notices say about the history as a whole: how many runs,
    since when, the newest one (summary columns), how many rows the analytics
    backfill has not processed yet (``pending``) and how many runs have an
    estimated start time (``estimated``)."""
    with _connect() as conn:
        runs, oldest = conn.execute("SELECT COUNT(*), MIN(ts) FROM history").fetchone()
        row = conn.execute(
            f"SELECT {', '.join(_SUMMARY_COLS)} FROM history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        pending = conn.execute(
            f"SELECT COUNT(*) FROM ({_ANALYTICS_TODO})", (analytics_store.EXTRACT_VERSION,)
        ).fetchone()[0]
        estimated = conn.execute(
            "SELECT COUNT(*) FROM history_metrics WHERE started_at_estimated = 1"
        ).fetchone()[0]
    return {
        "runs": int(runs or 0),
        "oldest": oldest,
        "latest": _with_surface(dict(row)) if row else None,
        "pending": int(pending or 0),
        "estimated": int(estimated or 0),
    }


def _with_surface(row: dict[str, Any]) -> dict[str, Any]:
    """``row`` with a NULL ``surface`` (saved before surfaces existed) read as chat."""
    row["surface"] = row.get("surface") or "chat"
    return row


def get(rid: int) -> dict[str, Any] | None:
    """The full saved report for one row (profile snapshot included), or ``None``."""
    with _connect() as conn:
        row = conn.execute(
            f"SELECT id, report_json, kb_snapshot_id, {_SPLIT} FROM history WHERE id = ?",
            (int(rid),),
        ).fetchone()
        return _full_report(conn, row)


def latest_for(
    base_url: str, claimed_model: str, surface: str | None = None
) -> dict[str, Any] | None:
    """The newest saved report for one target+model (as :func:`get`), or ``None``.

    One lookup on ``idx_history_target``, however many runs of other targets
    were saved since — a monitor's regression check compares against this.
    ``surface`` limits it to runs of that surface (NULL reads as chat).
    """
    with _connect() as conn:
        if surface is None:
            row = conn.execute(_LATEST_FOR_SQL, (base_url, claimed_model)).fetchone()
        else:
            row = conn.execute(
                _LATEST_FOR_SURFACE_SQL, (base_url, claimed_model, surface)
            ).fetchone()
        return _full_report(conn, row)


_LATEST_FOR_SQL = f"""SELECT id, report_json, kb_snapshot_id, {_SPLIT} FROM history
   WHERE base_url = ? AND claimed_model = ?
   ORDER BY id DESC LIMIT 1"""
_LATEST_FOR_SURFACE_SQL = f"""SELECT id, report_json, kb_snapshot_id, {_SPLIT} FROM history
   WHERE base_url = ? AND claimed_model = ? AND COALESCE(surface, 'chat') = ?
   ORDER BY id DESC LIMIT 1"""


def _full_report(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Parse a row's ``report_json`` and put its profile snapshot and its
    request records back."""
    if not row or row["report_json"] is None:
        return None
    snap = kb_snapshot.get(conn, row["kb_snapshot_id"])
    try:
        report = json.loads(row["report_json"])
    except (ValueError, TypeError):
        return None
    if snap is not None and isinstance(report, dict) and isinstance(report.get("knowledge"), dict):
        report["knowledge"]["profile"] = snap
    if row[_SPLIT] == 1 and isinstance(report, dict):
        analytics_store.restore_requests(report, analytics_store.get_requests(conn, row["id"]))
    return report


def watch_of(rid: int) -> int | None:
    """The id of the monitor that produced a saved run (``None`` for manual runs)."""
    with _connect() as conn:
        row = conn.execute("SELECT watch_id FROM history WHERE id = ?", (int(rid),)).fetchone()
    return int(row["watch_id"]) if row and row["watch_id"] is not None else None


def run_duration_sec(report: dict[str, Any] | None) -> float | None:
    """How long a saved run took, in seconds: detectors run one after another,
    so their summed durations are the audit's execution time. None if unknown."""
    total = 0.0
    for det in (report or {}).get("detectors") or []:
        ms = det.get("duration_ms") if isinstance(det, dict) else None
        if isinstance(ms, (int, float)) and not isinstance(ms, bool):
            total += float(ms)
    return round(total / 1000, 1) if total > 0 else None


def snapshot_for(rid: int) -> dict[str, Any] | None:
    """The knowledge-base profile snapshot a saved run used, if any."""
    with _connect() as conn:
        row = conn.execute("SELECT kb_snapshot_id FROM history WHERE id = ?", (int(rid),)).fetchone()
        return kb_snapshot.get(conn, row["kb_snapshot_id"]) if row else None


def _perf_headline(report_json: str | None) -> dict[str, float | None]:
    """Target p50 latency / TTFT / decode speed of a saved report (None if absent)."""
    out: dict[str, float | None] = {"latency_p50_ms": None, "ttft_p50_ms": None, "decode_tps_p50": None}
    try:
        target = (json.loads(report_json or "{}").get("performance") or {}).get("target") or {}
    except (ValueError, TypeError, AttributeError):
        return out

    def p50(key: str) -> float | None:
        stats = target.get(key)
        value = stats.get("p50") if isinstance(stats, dict) else None
        return float(value) if isinstance(value, (int, float)) else None

    out["latency_p50_ms"] = p50("latency_ms")
    out["ttft_p50_ms"] = p50("ttft_ms")
    tps = p50("decode_tps_local")
    out["decode_tps_p50"] = tps if tps is not None else p50("decode_tps_reported")
    return out


def delete(rid: int) -> None:
    """Remove one row by id, with its analytics rows, its evidence file (and a
    snapshot nothing else uses). No-op if missing."""
    with _connect() as conn:
        row = conn.execute("SELECT evidence_file FROM history WHERE id = ?", (int(rid),)).fetchone()
        conn.execute("DELETE FROM history WHERE id = ?", (int(rid),))
        analytics_store.delete_for(conn, int(rid))
        kb_snapshot.prune(conn, "history")
        if row is not None:
            _bump(conn)
        # a re-scored run shares its original's file: keep it while a row names it
        shared = row is not None and row["evidence_file"] is not None and conn.execute(
            "SELECT 1 FROM history WHERE evidence_file = ? LIMIT 1", (row["evidence_file"],)
        ).fetchone() is not None
    if row is not None and not shared:
        evidence_files.remove(row["evidence_file"])


def clear() -> None:
    """Wipe all history, analytics rows, snapshots and evidence files included."""
    with _connect() as conn:
        names = [r["evidence_file"] for r in conn.execute(
            "SELECT evidence_file FROM history WHERE evidence_file IS NOT NULL")]
        conn.execute("DELETE FROM history")
        analytics_store.delete_for(conn)
        kb_snapshot.prune(conn, "history")
        _bump(conn)
    for name in names:
        evidence_files.remove(name)


# --------------------------------------------------------------------------- #
# Evidence files
# --------------------------------------------------------------------------- #
def _evidence_name(report: dict[str, Any]) -> str | None:
    """The data-directory evidence file a report names, if it is there."""
    ref = report.get("evidence")
    name = ref.get("file") if isinstance(ref, dict) else None
    return name if evidence_files.stored_file(name) is not None else None


def evidence_path(rid: int) -> Path | None:
    """The evidence file of a saved run (None: it kept none, or it is gone)."""
    with _connect() as conn:
        row = conn.execute("SELECT evidence_file FROM history WHERE id = ?", (int(rid),)).fetchone()
    return evidence_files.stored_file(row["evidence_file"]) if row is not None else None


def sweep_evidence() -> int:
    """Remove evidence files no row names (and partial files of runs that
    died), once they are older than a day; returns how many."""
    with _connect() as conn:
        keep = {r["evidence_file"] for r in conn.execute(
            "SELECT evidence_file FROM history WHERE evidence_file IS NOT NULL")}
    return evidence_files.sweep(keep)


# --------------------------------------------------------------------------- #
# Analytics reads (the query layer builds on these)
# --------------------------------------------------------------------------- #
_RUN_COLS = (
    *(f"h.{c}" for c in _SUMMARY_COLS),
    *(f"m.{c}" for c in analytics_store.METRIC_COLS),
)


def analytics_runs(start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    """Every run with its extracted metrics, oldest first by ``started_at``.

    Each row holds the list view's columns (``id``, ``base_url``,
    ``claimed_model``, ``suite``, ``watch_id``, ...) and every
    ``history_metrics`` column. ``start`` (inclusive) / ``end`` (exclusive) are
    ISO timestamps compared with ``started_at``; runs without a known start
    time are left out when either is given. Brings the analytics tables up to
    date first (:func:`backfill_analytics`).
    """
    where, args = [], []
    for op, value in ((">=", start), ("<", end)):
        if value is None:
            continue
        dt = analytics_store.parse_ts(value)
        if dt is None:
            raise ValueError(f"not an ISO timestamp: {value!r}")
        where.append(f"m.started_at {op} ?")
        args.append(analytics_store.format_ts(dt))
    sql = (
        f"SELECT {', '.join(_RUN_COLS)} FROM history h"
        " JOIN history_metrics m ON m.history_id = h.id"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY m.started_at, h.id"
    )
    conn = _read()
    _ensure_extracted(conn)
    return [_with_surface(dict(r)) for r in conn.execute(sql, args).fetchall()]


def _ensure_extracted(conn: sqlite3.Connection) -> None:
    """Run the analytics backfill when a row still needs it (one indexed
    ``EXISTS`` when none does)."""
    if conn.execute(
        f"SELECT EXISTS ({_ANALYTICS_TODO})", (analytics_store.EXTRACT_VERSION,)
    ).fetchone()[0]:
        with contextlib.suppress(sqlite3.Error):
            backfill_analytics()  # best-effort; a locked database can wait


def query_connection() -> sqlite3.Connection:
    """This thread's read-only connection, ready for :mod:`ekte.web.query`:
    the analytics tables are backfilled and ``relay_map`` reflects the current
    knowledge base (rebuilt through a short write connection only when it is
    out of date). Never close it."""
    from ekte.web import relay_map

    conn = _read()
    _ensure_extracted(conn)
    if not relay_map.is_current(conn):
        with _connect() as writer:
            relay_map.ensure_relay_map(writer)
    return conn


def surface_counts() -> dict[str, int]:
    """Runs per surface over the whole history (NULL reads as chat)."""
    rows = _read().execute(
        "SELECT COALESCE(surface, 'chat') AS s, COUNT(*) AS n FROM history GROUP BY s"
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _chunks(ids: Iterable[int]) -> Iterator[list[int]]:
    ids = [int(i) for i in ids]
    for start in range(0, len(ids), 500):
        yield ids[start:start + 500]


def analytics_dimensions(ids: Iterable[int], kind: str | None = None) -> list[dict[str, Any]]:
    """``history_dimensions`` rows (``history_id``, ``kind``, ``key``, ``score``,
    ``status``, ``weight``) of the given runs, optionally of one ``kind``
    (``dimension`` / ``detector``)."""
    out: list[dict[str, Any]] = []
    conn = _read()
    for chunk in _chunks(ids):
        sql = (
            "SELECT history_id, kind, key, score, status, weight FROM history_dimensions"
            f" WHERE history_id IN ({', '.join('?' * len(chunk))})"
        )
        args: list[Any] = list(chunk)
        if kind is not None:
            sql += " AND kind = ?"
            args.append(kind)
        out.extend(dict(r) for r in conn.execute(sql + " ORDER BY history_id, kind, key", args))
    return out


def analytics_requests(
    ids: Iterable[int], endpoint: str | None = "target"
) -> list[dict[str, Any]]:
    """Request records of the given runs as stored columns (``history_id``,
    ``ord`` and every RequestRecord field; booleans as 0/1, ``extra`` left out),
    in run and list order. ``endpoint`` None returns baseline records too.

    Rows whose records are still inline in ``report_json`` contribute nothing;
    :func:`analytics_runs` moves them out first.
    """
    cols = ", ".join(("history_id", "ord", *analytics_store.REQUEST_FIELDS))
    out: list[dict[str, Any]] = []
    conn = _read()
    for chunk in _chunks(ids):
        sql = (
            f"SELECT {cols} FROM history_requests"
            f" WHERE history_id IN ({', '.join('?' * len(chunk))})"
        )
        args: list[Any] = list(chunk)
        if endpoint is not None:
            sql += " AND endpoint = ?"
            args.append(endpoint)
        out.extend(dict(r) for r in conn.execute(sql + " ORDER BY history_id, ord", args))
    return out


# The outcome class of one request record (errors view). First match wins:
# a timeout is a timeout whatever its status code, a 429 is rate limiting.
# ``network`` is an exception without an HTTP status (connection refused,
# TLS, reset); ``other`` a failed call with a 1xx-3xx status or no detail.
REQUEST_CLASSES = ("success", "client_4xx", "rate_limited", "server_5xx", "timeout", "network", "other")
_CLASS_SQL = (
    "CASE WHEN ok = 1 THEN 'success'"
    " WHEN timeout = 1 THEN 'timeout'"
    " WHEN rate_limited = 1 OR status_code = 429 THEN 'rate_limited'"
    " WHEN status_code BETWEEN 500 AND 599 THEN 'server_5xx'"
    " WHEN status_code BETWEEN 400 AND 499 THEN 'client_4xx'"
    " WHEN status_code IS NULL AND error_type IS NOT NULL THEN 'network'"
    " ELSE 'other' END"
)


def analytics_request_classes(
    ids: Iterable[int], endpoint: str = "target", op: str = "complete"
) -> list[dict[str, Any]]:
    """Calls of the given runs (``op``: ``complete`` for completion calls,
    ``embed`` for embedding calls, ``rerank`` for rerank calls) counted in SQL by run, minute after
    the run's start (``minute``: whole minutes of ``start_ms``) and outcome
    class (``cls``, one of :data:`REQUEST_CLASSES`): rows ``history_id``,
    ``minute``, ``cls``, ``n``. Never loads the records themselves; a run
    without stored records has no rows."""
    out: list[dict[str, Any]] = []
    conn = _read()
    for chunk in _chunks(ids):
        sql = (
            "SELECT history_id, CAST(COALESCE(start_ms, 0) / 60000 AS INTEGER) AS minute,"
            f" {_CLASS_SQL} AS cls, COUNT(*) AS n FROM history_requests"
            f" WHERE history_id IN ({', '.join('?' * len(chunk))})"
            " AND COALESCE(endpoint, 'target') = ? AND COALESCE(op, 'complete') = ?"
            " GROUP BY history_id, minute, cls ORDER BY history_id, minute, cls"
        )
        out.extend(dict(r) for r in conn.execute(sql, [*chunk, endpoint, op]))
    return out
