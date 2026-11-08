"""Each run's combination of few-valued filter values, as one integer.

The filter keys of the URL schema (:mod:`ekte.web.query`) that take one of a
few values (:data:`FACETS`: surface, suite, mode, API, stream mode, detection,
risk, execution) are read from the run's ``history`` row. ``facet_combo``
holds every combination of their values that a run has (as the URL spells
them), and ``history_metrics.facet_id`` the run's combination, kept current
by triggers (a new run's metrics row, a changed ``history`` column). So the
filter options (:func:`ekte.web.analytics_widgets.filter_options`) count the
values of all these keys with one ``GROUP BY`` of an integer, then fold the
few combinations, instead of one ``GROUP BY`` of the runs per key.
"""

from __future__ import annotations

import sqlite3

FACETS: dict[str, str] = {
    "surface": "COALESCE(h.surface, 'chat')",
    "suite": "COALESCE(NULLIF(h.suite, ''), '-')",
    "mode": "COALESCE(NULLIF(h.mode, ''), '-')",
    "api": "COALESCE(NULLIF(h.api, ''), '-')",
    "stream": "COALESCE(NULLIF(h.stream_mode, ''), '-')",
    "detect": "CASE h.api_auto WHEN 1 THEN 'auto' WHEN 0 THEN 'manual' ELSE '-' END",
    "risk": "COALESCE(NULLIF(h.risk_level, ''), 'inconclusive')",
    "exec": "CASE WHEN h.watch_id IS NULL THEN 'manual' ELSE 'monitor' END",
}
"""Filter key -> SQL of a run's value as the URL spells it (over ``history h``)."""

COLUMNS: dict[str, str] = {k: f"f_{k}" for k in FACETS}
"""Filter key -> its ``facet_combo`` column."""

# the history columns FACETS reads (a change re-assigns the run's combination)
_SOURCE_COLS = ("surface", "suite", "mode", "api", "stream_mode", "api_auto", "risk_level", "watch_id")


def _set_sql(rid: str, where: str | None = None) -> str:
    """Add the combination of run ``rid`` and set its ``facet_id`` (on the
    run ``rid`` or the rows ``where`` selects)."""
    cols = ", ".join(COLUMNS.values())
    same = " AND ".join(f"fc.{c} = {FACETS[k]}" for k, c in COLUMNS.items())
    # NOT EXISTS, not INSERT OR IGNORE: in a trigger the conflict clause of
    # the statement that fired it wins, and INSERT OR REPLACE (how metrics
    # rows are written) would re-number a combination others point to
    return (f"INSERT INTO facet_combo ({cols})"
            f" SELECT DISTINCT {', '.join(FACETS.values())} FROM history h"
            f" WHERE {'h.id = ' + rid if where is None else 'TRUE'}"
            f" AND NOT EXISTS (SELECT 1 FROM facet_combo fc WHERE {same});"
            f" UPDATE history_metrics SET facet_id = (SELECT fc.id FROM history h"
            f" JOIN facet_combo fc ON {same} WHERE h.id = {rid})"
            f" WHERE {where or f'history_id = {rid}'};")


def ensure_facet_ids(conn: sqlite3.Connection) -> None:
    """Add ``facet_combo``, ``history_metrics.facet_id`` and the triggers that
    set a run's id, and fill them for the runs already saved (idempotent; a
    migration step)."""
    from ekte.knowledge.snapshot import add_link_columns

    cols = ", ".join(COLUMNS.values())
    conn.execute(f"CREATE TABLE IF NOT EXISTS facet_combo (id INTEGER PRIMARY KEY,"
                 f" {', '.join(f'{c} TEXT NOT NULL' for c in COLUMNS.values())}, UNIQUE ({cols}))")
    add_link_columns(conn, "history_metrics", {"facet_id": "INTEGER"})
    conn.execute("CREATE TRIGGER IF NOT EXISTS facet_id_insert AFTER INSERT ON history_metrics"
                 f" BEGIN {_set_sql('NEW.history_id')} END")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS facet_id_update AFTER UPDATE OF {', '.join(_SOURCE_COLS)}"
                 f" ON history BEGIN {_set_sql('NEW.id')} END")
    for statement in _set_sql("history_metrics.history_id", "TRUE").split("; "):
        conn.execute(statement)
