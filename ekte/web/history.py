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
backfill), from whichever process writes. :func:`data_version`
reads it; the web response cache (:mod:`ekte.web.cache`) keys on it.

Relay map (schema version 7): ``relay_map`` maps each distinct run URL to
its knowledge-base relay so SQL can group and filter runs by relay; it is
rebuilt from the knowledge base on demand (see :mod:`ekte.web.relay_map`).

Query index (schema version 10): ``idx_history_query`` covers the columns
:mod:`ekte.web.query` reads from ``history``, so filtering and grouping never
read a run's report.

Relay ids (schema version 11): ``history_metrics.relay_id`` holds each run's
``relay_group`` id, kept current by triggers and the relay map, so grouping
and filtering by relay use an integer of the run's row (see
:mod:`ekte.web.relay_map`).

Outcome columns (schema version 12): ``history_metrics.outcome_<outcome>``
holds the run's ``history_outcomes`` counts summed over its ops, kept equal
by triggers, so pooling outcomes over many runs reads no second table (see
:data:`ekte.web.analytics_store.OUTCOME_COLS`); ``history_metrics.facet_id``
the run's combination of few-valued filter values in ``facet_combo`` (see
:mod:`ekte.web.run_row`).

Performance headline (schema version 13): the list's p50 latency / TTFT /
decode speed are read from ``history_metrics`` (one store per value); the
duplicate ``history`` columns of earlier versions (``latency_p50_ms``,
``ttft_p50_ms``, ``decode_tps_p50``, ``perf_done``) are dropped.

Run row (schema version 14): every value the query core selects, groups or
sorts runs by is a number on the run's ``history_metrics`` row (start time
in Unix seconds, score, grade, risk, model / URL / facet ids; kept by
triggers, see :mod:`ekte.web.run_row`), so aggregations never read
``history``.

``PRAGMA user_version`` records the schema version; the numbered steps are in
``MIGRATIONS`` and are applied by :mod:`ekte.dbmigrate`.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Iterator
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

# 1: the row's request records are in history_requests; 0: inline (or none);
# NULL: not looked at yet.
_SPLIT = "requests_split"

_DB_NAME = "history.db"

# Rows per analytics backfill transaction: each one parses a whole report, so
# few, to keep the write lock short.
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


def _v11(conn: sqlite3.Connection) -> None:
    """Each run's relay id (``history_metrics.relay_id``, ``relay_group``;
    :func:`ekte.web.relay_map.ensure_relay_ids`); filled in for the runs
    already saved by the next ``relay_map.ensure_relay_map``."""
    from ekte.web import relay_map

    relay_map.ensure_relay_ids(conn)


def _v12(conn: sqlite3.Connection) -> None:
    """Per-run columns kept by triggers, filled in for the runs already
    saved: each run's outcome counts
    (:data:`ekte.web.analytics_store.OUTCOME_COLS`) and its combination of
    few-valued filter values (``facet_id``), with the other run-row columns
    (:func:`ekte.web.run_row.ensure_run_columns`; step 14 finds them current)."""
    from ekte.web import run_row

    analytics_store.ensure_outcome_columns(conn)
    run_row.ensure_run_columns(conn)


# The performance headline columns of ``history`` before version 13: the same
# values as history_metrics' (two stores for one value), dropped.
_DROPPED_PERF_COLS = ("latency_p50_ms", "ttft_p50_ms", "decode_tps_p50", "perf_done")


def _v13(conn: sqlite3.Connection) -> None:
    """Drop the duplicate performance headline columns of ``history`` (the
    list reads them from ``history_metrics``). ``ALTER TABLE ... DROP COLUMN``
    needs SQLite 3.35; an older SQLite keeps the columns, which nothing reads
    or writes any more."""
    if sqlite3.sqlite_version_info < (3, 35):
        return
    present = {r[1] for r in conn.execute("PRAGMA table_info(history)")}
    for col in _DROPPED_PERF_COLS:
        if col in present:
            conn.execute(f"ALTER TABLE history DROP COLUMN {col}")


def _v14(conn: sqlite3.Connection) -> None:
    """Each run's numeric run row (:data:`ekte.web.run_row.RUN_COLUMNS`:
    start time in Unix seconds, score, grade, risk, model, URL and facet ids,
    kept by triggers), filled in for the runs already saved, and its
    indexes."""
    from ekte.web import run_row

    run_row.ensure_run_columns(conn)


def _v15(conn: sqlite3.Connection) -> None:
    """What an HTTPS proxy answered when it refused the tunnel to the relay
    (``proxy_status``, ``proxy_wait_ms``, ekte.proxyreply); records saved
    before read back without them."""
    analytics_store.add_request_columns(
        conn, {"proxy_status": "int", "proxy_wait_ms": "float"}
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
    dbmigrate.Migration(11, _v11),
    dbmigrate.Migration(12, _v12),
    dbmigrate.Migration(13, _v13),
    dbmigrate.Migration(14, _v14),
    dbmigrate.Migration(15, _v15),
)
_SCHEMA_VERSION = dbmigrate.latest(MIGRATIONS)


def _after_migration(conn: sqlite3.Connection) -> None:
    """Fill the columns new steps added for existing rows.

    Runs after the schema transactions, so other threads already see the new
    schema and compute any row the backfill has not reached yet.
    """
    try:
        _backfill_analytics(conn)
    except Exception:
        # Best-effort: rows left over are picked up by backfill_analytics().
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
    if not pending:
        return
    began = time.monotonic()
    dbmigrate.notice(f"updating the metrics of {len(pending)} saved run(s) for this version...")
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
    dbmigrate.notice(f"metrics of {len(pending)} saved run(s) updated in"
                     f" {time.monotonic() - began:.1f} s")


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
        with _connect() as conn:
            snapshot_id = kb_snapshot.put(conn, snap) if isinstance(snap, dict) else None
            cur = conn.execute(
                """INSERT INTO history
                   (ts, base_url, claimed_model, model, mode, suite,
                    risk_level, score, rating, report_json, kb_snapshot_id, kb_match, watch_id,
                    api, api_auto, stream_mode, surface, requests_split, evidence_file)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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


# The performance headline of the list (GET /api/v1/history?perf=1), read
# from the run's extracted metrics.
PERF_HEADLINE = ("latency_p50_ms", "ttft_p50_ms", "decode_tps_p50")


def recent(limit: int = 50, perf: bool = False) -> list[dict[str, Any]]:
    """Most recent audits, newest first — summary columns only (no report).

    With ``perf`` each row also carries the target's performance headline
    (:data:`PERF_HEADLINE`, from ``history_metrics``; None where the run did
    not measure it). The public ``GET /api/v1/history``; the History page
    reads ``/api/history/groups`` and ``/api/history/runs`` instead.
    """
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 50
    cols = ", ".join((*(f"h.{c}" for c in _SUMMARY_COLS),
                      *((f"m.{c}" for c in PERF_HEADLINE) if perf else ())))
    join = " LEFT JOIN history_metrics m ON m.history_id = h.id" if perf else ""
    if perf:
        _ensure_extracted(_read())
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM history h{join} ORDER BY h.id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_with_surface(dict(r)) for r in rows]


def status() -> dict[str, Any]:
    """What the pages' notices say about the history as a whole: how many runs,
    since when, the newest one (summary columns), how many rows the analytics
    backfill has not processed yet (``pending``) and how many runs have an
    estimated start time (``estimated``).

    Reads on this thread's reused read-only connection (:func:`_read`; not
    :func:`query_connection`, which would run the backfill and hide
    ``pending``): its page cache stays warm between calls, where a fresh
    connection read every page of ``history`` again, and each statement still
    sees the latest committed data of any process."""
    conn = _read()
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
# Reads of the query core (ekte/web/query.py)
# --------------------------------------------------------------------------- #
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
