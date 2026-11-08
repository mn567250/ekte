"""Per-run columns kept by triggers (history schema 12): the outcome counts
(analytics_store.OUTCOME_COLS) and the facet combination (ekte/web/facets.py)."""

from __future__ import annotations

import sqlite3

from ekte.web import analytics_store, facets, history
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


def _facets_ok(conn: sqlite3.Connection) -> None:
    """Every run points at the combination of its own values."""
    exprs = ", ".join(facets.FACETS.values())
    cols = ", ".join(f"fc.{c}" for c in facets.COLUMNS.values())
    rows = conn.execute(f"SELECT m.facet_id, {exprs}, {cols} FROM history h JOIN history_metrics m"
                        " ON m.history_id = h.id LEFT JOIN facet_combo fc ON fc.id = m.facet_id").fetchall()
    assert rows
    n = len(facets.FACETS)
    for row in rows:
        assert row[0] is not None and tuple(row[1:1 + n]) == tuple(row[1 + n:]), tuple(row)


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
        _facets_ok(conn)


def test_facet_ids_follow_the_runs(data):  # noqa: F811
    for i in range(6):  # runs 2 and 4 share a combination
        report = _fixture()
        report["suite"] = ("quick", "deep")[i % 2]
        history.save(report, watch_id=i if i % 3 else None)
    with _db(data) as conn:
        _facets_ok(conn)
        # a re-extraction (INSERT OR REPLACE) must not re-number combinations in use
        rid = int(conn.execute("SELECT MIN(id) FROM history").fetchone()[0])
        analytics_store.put_metrics(conn, rid, *analytics_store.extract_metrics(history.get(rid)))
        _facets_ok(conn)
        conn.execute("UPDATE history SET watch_id = NULL, risk_level = 'high' WHERE id = ?", (rid,))
        _facets_ok(conn)


def test_a_v11_database_gets_the_run_columns(data):  # noqa: F811
    rids = [history.save(_fixture()) for _ in range(3)]
    with _db(data) as conn:  # as schema 11 left it
        for trigger in ("outcome_cols_insert", "outcome_cols_delete", "outcome_cols_update",
                        "outcome_cols_metrics", "facet_id_insert", "facet_id_update"):
            conn.execute(f"DROP TRIGGER {trigger}")
        for col in [*_COLS, "facet_id"]:
            conn.execute(f"ALTER TABLE history_metrics DROP COLUMN {col}")
        conn.execute("DROP TABLE facet_combo")
        conn.execute("PRAGMA user_version = 11")
    history.init()
    with _db(data) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == history._SCHEMA_VERSION
        for rid in rids:
            assert _columns(conn, rid) == _pivot(conn, rid) is not None
        _facets_ok(conn)
