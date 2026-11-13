"""Per-run columns kept by triggers: the outcome counts (history schema 12,
analytics_store.OUTCOME_COLS) and the numeric run row (schema 12 / 14,
ekte/web/run_row.py: facet combination, start time, score, grade, risk,
lookup ids)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from ekte.web import analytics_store, history, query, run_row
from tests.test_history_analytics import _db, _fixture, data  # noqa: F401  (fixture)

_COLS = list(analytics_store.OUTCOME_COLS.values())


def _pivot(conn: sqlite3.Connection, rid: int) -> list[int] | None:
    rows = conn.execute("SELECT outcome, SUM(n) FROM history_outcomes WHERE history_id = ?"
                        " GROUP BY outcome", (rid,)).fetchall()
    if not rows:
        return None
    sums = {o: int(n) for o, n in rows}
    return [sums.get(o, 0) for o in analytics_store.OUTCOME_COLS]


def _columns(conn: sqlite3.Connection, rid: int) -> list[int] | None:
    row = list(conn.execute(f"SELECT {', '.join(_COLS)} FROM history_metrics WHERE history_id = ?",
                            (rid,)).fetchone())
    return None if all(v is None for v in row) else row


def _run_row_ok(conn: sqlite3.Connection) -> None:
    """Every run's run-row columns hold what their definitions give for its
    current history / metrics rows (a lookup column: the id of the run's own
    values, NULL exactly when they are), and started_us spells started_at."""
    cols = list(run_row.RUN_COLUMNS)
    fresh = [run_row._value_sql(d) for _, d in run_row.RUN_COLUMNS.values()]
    known = [" AND ".join(f"({e}) IS NOT NULL" for e in d.columns.values())
             if isinstance(d, run_row.Lookup) else "NULL" for _, d in run_row.RUN_COLUMNS.values()]
    rows = conn.execute(
        f"SELECT m.history_id, m.started_at, {', '.join(f'm.{c}' for c in cols)}, {', '.join(fresh)},"
        f" {', '.join(known)} FROM history h JOIN history_metrics m ON m.history_id = h.id").fetchall()
    assert rows
    n = len(cols)
    for row in rows:
        rid, started, stored, want, has = row[0], row[1], row[2:2 + n], row[2 + n:2 + 2 * n], row[2 + 2 * n:]
        for col, s, w, h in zip(cols, stored, want, has, strict=True):
            assert s == w, (rid, col, s, w)
            if h is not None:  # a lookup: an id exactly for known values
                assert (s is not None) == bool(h), (rid, col)
        assert query.us_text(stored[cols.index("started_us")]) == started, rid


def test_outcome_columns_follow_history_outcomes(data):  # noqa: F811
    rids = [history.save(_fixture()) for _ in range(2)]
    with _db(data) as conn:
        for rid in rids:
            assert _columns(conn, rid) == _pivot(conn, rid) is not None
        # re-extracted (INSERT OR REPLACE of the metrics row, outcome rows rewritten)
        report = history.get(rids[0])
        analytics_store.put_metrics(conn, rids[0], *analytics_store.extract_metrics(report))
        assert _columns(conn, rids[0]) == _pivot(conn, rids[0])
        conn.execute("UPDATE history_outcomes SET n = n + 5 WHERE history_id = ? AND outcome = 'success'",
                     (rids[0],))
        assert _columns(conn, rids[0]) == _pivot(conn, rids[0])
        conn.execute("DELETE FROM history_outcomes WHERE history_id = ?", (rids[1],))
        assert _columns(conn, rids[1]) is None
        _run_row_ok(conn)


def test_run_row_follows_the_runs(data):  # noqa: F811
    for i in range(6):  # runs 2 and 4 share a facet combination
        report = _fixture()
        report["suite"] = ("quick", "deep")[i % 2]
        if i == 5:
            report["target"]["claimed_model"] = report["target"]["model"] = ""
            report["verdict"]["risk_level"] = None
        history.save(report, watch_id=i if i % 3 else None)
    with _db(data) as conn:
        _run_row_ok(conn)
        ids = [int(r[0]) for r in conn.execute("SELECT id FROM history ORDER BY id")]
        # a re-extraction (INSERT OR REPLACE) must not re-number the lookups
        before = {t.table: conn.execute(f"SELECT * FROM {t.table} ORDER BY id").fetchall()
                  for t in run_row.LOOKUPS}
        analytics_store.put_metrics(conn, ids[0], *analytics_store.extract_metrics(history.get(ids[0])))
        assert {t.table: conn.execute(f"SELECT * FROM {t.table} ORDER BY id").fetchall()
                for t in run_row.LOOKUPS} == before
        _run_row_ok(conn)
        # every history column a run-row column reads
        for col, value in (("watch_id", None), ("risk_level", "high"), ("risk_level", "weird"),
                           ("risk_level", ""), ("score", 12.5), ("rating", "E"), ("rating", None),
                           ("claimed_model", "other-model"), ("base_url", "https://x.example/v1"),
                           ("surface", "rerank"), ("suite", ""), ("stream_mode", "both"),
                           ("api", "responses"), ("api_auto", 0), ("mode", "deep")):
            conn.execute(f"UPDATE history SET {col} = ? WHERE id = ?", (value, ids[1]))
            _run_row_ok(conn)
        # and the metrics columns
        for col, value in (("started_at", "1969-12-31T23:59:59.250000+00:00"),
                           ("started_at", "2026-03-29T01:00:00.000001+00:00"), ("started_at", None),
                           ("tool_version", "9.9.9"), ("tool_version", ""), ("kb_profile_hash", "abc"),
                           ("kb_model_id", None)):
            conn.execute(f"UPDATE history_metrics SET {col} = ? WHERE history_id = ?", (value, ids[2]))
            _run_row_ok(conn)
        row = conn.execute("SELECT risk_value, grade_value, score, model_id FROM history_metrics"
                           " WHERE history_id = ?", (ids[1],)).fetchone()
        assert (row[0], row[1], row[2]) == (None, None, 12.5)
        assert conn.execute("SELECT model_key FROM model_group WHERE id = ?", (row[3],)).fetchone()[0] \
            == "other-model"
        (unknown,) = conn.execute("SELECT mg.model_key FROM history_metrics m JOIN model_group mg"
                                  " ON mg.id = m.model_id WHERE m.history_id = ?", (ids[5],)).fetchone()
        assert unknown == "(unknown)"


def test_risk_and_grade_codes(data):  # noqa: F811
    rid = history.save(_fixture())
    with _db(data) as conn:
        for level, code in (("clean", 0), ("inconclusive", 1), ("low", 2), ("medium", 3), ("high", 4),
                            ("weird", -1), ("", None), (None, None)):
            conn.execute("UPDATE history SET risk_level = ? WHERE id = ?", (level, rid))
            assert conn.execute("SELECT risk_value FROM history_metrics WHERE history_id = ?",
                                (rid,)).fetchone()[0] == code, level
        for i, letter in enumerate(("F", "E", "D", "C", "B", "A")):
            conn.execute("UPDATE history SET rating = ? WHERE id = ?", (letter, rid))
            assert conn.execute("SELECT grade_value FROM history_metrics WHERE history_id = ?",
                                (rid,)).fetchone()[0] == i + 1


def test_started_us_orders_and_compares_as_started_at(data):  # noqa: F811
    """time_sql() on the integer start compares exactly as on started_at,
    for times with and without microseconds, before and after 1970."""
    rid = history.save(_fixture())
    base = datetime(1969, 12, 31, 23, 59, 58, tzinfo=UTC)
    times = [base + timedelta(microseconds=k) for k in
             (0, 1, 499_999, 500_000, 999_999, 1_000_000, 1_500_000, 2_000_000, 2_000_001)]
    times += [datetime(2026, 7, 1, 12, 0, 0, us, tzinfo=UTC) for us in (0, 1, 999_999)]
    bounds = [*times, *(t + timedelta(microseconds=d) for t in times for d in (-1, 1))]
    with _db(data) as conn:
        for t in times:
            text = analytics_store.format_ts(t)
            conn.execute("UPDATE history_metrics SET started_at = ? WHERE history_id = ?", (text, rid))
            us = conn.execute("SELECT started_us FROM history_metrics WHERE history_id = ?",
                              (rid,)).fetchone()[0]
            assert us == query.us_of(t) and query.us_text(us) == text
            for b in bounds:
                for op in (">=", "<"):
                    got = conn.execute(f"SELECT {query.time_sql(op, b)} FROM history_metrics m"
                                       " WHERE m.history_id = ?", (rid,)).fetchone()[0]
                    assert bool(got) == (text >= analytics_store.format_ts(b) if op == ">="
                                         else text < analytics_store.format_ts(b)), (t, b, op)


def _strip_run_row(conn: sqlite3.Connection, *, outcomes: bool) -> None:
    """Take the run row (and, ``outcomes``, the outcome columns) away, as the
    schema before them had it."""
    for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND"
                                   " (name LIKE 'run_row_%' OR (? AND name LIKE 'outcome_cols_%'))",
                                   (outcomes,)).fetchall():
        conn.execute(f"DROP TRIGGER {trigger}")
    for name in run_row.INDEXES:
        conn.execute(f"DROP INDEX {name}")
    for col in [*(_COLS if outcomes else ()), *run_row.RUN_COLUMNS]:
        conn.execute(f"ALTER TABLE history_metrics DROP COLUMN {col}")
    for lookup in run_row.LOOKUPS:
        conn.execute(f"DROP TABLE {lookup.table}")


def test_a_v11_database_gets_the_run_columns(data):  # noqa: F811
    rids = [history.save(_fixture()) for _ in range(3)]
    with _db(data) as conn:  # as schema 11 left it
        _strip_run_row(conn, outcomes=True)
        conn.execute("PRAGMA user_version = 11")
    history.init()
    with _db(data) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == history._SCHEMA_VERSION
        for rid in rids:
            assert _columns(conn, rid) == _pivot(conn, rid) is not None
        _run_row_ok(conn)


def test_a_v13_database_gets_the_run_row(data):  # noqa: F811
    rids = [history.save(_fixture()) for _ in range(3)]
    with _db(data) as conn:  # as schema 13 left it: facet ids by their own triggers
        _strip_run_row(conn, outcomes=False)
        conn.execute(run_row.FACET_COMBOS.create_sql())
        conn.execute("ALTER TABLE history_metrics ADD COLUMN facet_id INTEGER")
        conn.execute("CREATE TRIGGER facet_id_insert AFTER INSERT ON history_metrics"
                     " BEGIN SELECT 1; END")
        conn.execute("PRAGMA user_version = 13")
    history.init()
    with _db(data) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == history._SCHEMA_VERSION
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'facet_id_insert'").fetchall()
        assert {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")} \
            >= set(run_row.INDEXES)
        _run_row_ok(conn)
        rids.append(history.save(_fixture()))
        _run_row_ok(conn)


def test_ensure_run_columns_is_cheap_once_done(data):  # noqa: F811
    history.save(_fixture())
    with _db(data) as conn:
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        run_row.ensure_run_columns(conn)
        assert not [s for s in statements if s.lstrip().upper().startswith(("UPDATE", "INSERT"))]


def test_a_v15_database_gets_the_monitor_on_the_run_row(data):  # noqa: F811
    """Schema 16: history.watch_id copied onto the run row (the watch filter),
    filled in for the runs already saved, kept by the triggers, and covered by
    idx_run_row (made again: CREATE INDEX IF NOT EXISTS would keep the old one)."""
    rids = [history.save(_fixture(), watch_id=w) for w in (3, None, 4)]
    with _db(data) as conn:  # as schema 15 left it
        for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'"
                                       " AND name LIKE 'run_row_%'").fetchall():
            conn.execute(f"DROP TRIGGER {trigger}")
        conn.execute("DROP INDEX idx_run_row")
        conn.execute("ALTER TABLE history_metrics DROP COLUMN watch_id")
        old = ", ".join(c for c in run_row.NUMBERS if c != "watch_id")
        conn.execute(f"CREATE INDEX idx_run_row ON history_metrics ({old})")
        conn.execute("PRAGMA user_version = 15")
    history.init()
    with _db(data) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == history._SCHEMA_VERSION
        got = dict(conn.execute("SELECT history_id, watch_id FROM history_metrics").fetchall())
        assert got == dict(zip(rids, (3, None, 4), strict=True))
        indexed = [r[2] for r in conn.execute("PRAGMA index_info(idx_run_row)")]
        assert indexed == list(run_row.NUMBERS) and "watch_id" in indexed
        sel = query.select_runs(query.parse_query({"watch": "3"}))
        plan = " ".join(r[3] for r in conn.execute(f"EXPLAIN QUERY PLAN SELECT COUNT(*) {sel.sql}", sel.args))
        assert "COVERING INDEX idx_run_row" in plan, plan
        # the triggers keep it: a run moved to another monitor, or by hand
        conn.execute("UPDATE history SET watch_id = 9 WHERE id = ?", (rids[1],))
        conn.execute("UPDATE history SET watch_id = NULL WHERE id = ?", (rids[0],))
        _run_row_ok(conn)
        assert dict(conn.execute("SELECT history_id, watch_id FROM history_metrics").fetchall()) == \
            dict(zip(rids, (None, 9, 4), strict=True))
