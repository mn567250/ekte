"""The relay of every run as SQL-joinable data: the ``relay_map`` table of ``history.db``.

Which relay a run belongs to depends on the knowledge base, so it is not
stored with the run. Instead ``relay_map`` holds one row per distinct run URL
with the group :class:`ekte.web.analytics.RelayResolver` gives it (the single
source of the matching rules: a relay the user saved first, then the provider
with the smallest key, then the URL itself):

``relay_map(base_url_norm TEXT PRIMARY KEY, relay_key, label, kind, in_kb)``

* ``base_url_norm`` — a run's URL as :data:`RUN_URL_SQL` gives it:
  ``history_metrics.base_url_norm``, else the raw ``history.base_url``
  trimmed (a URL :func:`~ekte.knowledge.relays.normalize_url` rejects groups
  by itself, as the resolver does), else ``''`` for a run without a URL. The
  ``''`` row is always present and maps to ``UNKNOWN_RELAY``, so every run
  has exactly one row and an inner join keeps every run.
* ``relay_key``, ``label``, ``kind``, ``in_kb`` — the resolver's
  :class:`~ekte.web.analytics.Group` (``in_kb`` 0/1).

``relay_map_meta`` (one row) records the :func:`ekte.knowledge.relays.kb_version`
the map was built from, and ``stale``: set by a trigger on ``history_metrics``
when a run with a URL the map lacks is saved (by any process). Both are
checked by :func:`ensure_relay_map`, which must be called before grouping or
filtering by relay: it rebuilds the map when the knowledge base changed (in
any process: the version is computed from the knowledge base itself, not from
a change notice) and adds the missing URLs when ``stale`` is set. Up to date,
it costs a cached knowledge-base load and a one-row read. Rows of URLs no run
uses any more are harmless and dropped by the next rebuild.

Grouping keys for SQL, with ``history h``, ``history_metrics m`` and
:data:`JOIN_SQL` (alias ``rm``) in the query (:data:`GROUP_KEY_SQL`):

* ``relay`` = ``rm.relay_key``
* ``model`` = ``h.claimed_model``, or ``UNKNOWN_RELAY`` when missing or empty
* ``relay_model`` = ``relay || '|' || model``
* ``all`` = the constant ``ALL_KEY``

Every run has exactly one key per grouping, so groups partition the runs.

Relay ids (schema version 11): every distinct ``relay_key`` also has a row in
``relay_group(id INTEGER PRIMARY KEY, relay_key UNIQUE, label, kind, in_kb)``,
``relay_map.relay_id`` names it, and ``history_metrics.relay_id`` holds it
for each run, so SQL groups and filters runs on an integer the run's row
already carries instead of looking each run's URL up in ``relay_map``
(:data:`RELAY_ID_SQL`, :data:`GROUP_JOIN_SQL`). A trigger sets a new run's
id from ``relay_map``; a run whose URL the map lacks keeps a NULL id (and the
map is marked stale) until :func:`ensure_relay_map` adds the URL and fills
it, and a rebuild re-assigns the runs whose relay changed. A key keeps its id
while any URL maps to it. Once the map is current, every run has an id.
"""

from __future__ import annotations

import sqlite3

from ekte.knowledge.relays import kb_version, load_for_grouping
from ekte.web.analytics import ALL_KEY, UNKNOWN_RELAY, RelayResolver


def _url_sql(norm: str, raw: str) -> str:
    """The relay-map key from the SQL expressions of a run's normalised and
    raw URL (trimming the whitespace ``str.strip()`` removes from ASCII)."""
    return (f"COALESCE(NULLIF({norm}, ''), "
            f"NULLIF(TRIM({raw}, char(32, 9, 10, 11, 12, 13)), ''), '')")


RUN_URL_SQL = _url_sql("m.base_url_norm", "h.base_url")
"""A run's key into ``relay_map`` (needs ``history h`` and ``history_metrics m``)."""

JOIN_SQL = f"JOIN relay_map rm ON rm.base_url_norm = {RUN_URL_SQL}"
"""Joins each run to its relay as ``rm`` (an inner join keeps every run once
:func:`ensure_relay_map` ran)."""


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


_MODEL_SQL = f"COALESCE(NULLIF(h.claimed_model, ''), {_quote(UNKNOWN_RELAY)})"

GROUP_KEY_SQL: dict[str, str] = {
    "relay": "rm.relay_key",
    "model": _MODEL_SQL,
    "relay_model": f"rm.relay_key || '|' || {_MODEL_SQL}",
    "all": _quote(ALL_KEY),
}
"""The SQL expression of each grouping's series key (see the module docstring)."""

RELAY_ID_SQL = "m.relay_id"
"""A run's ``relay_group.id`` (needs ``history_metrics m``; set for every
run once :func:`ensure_relay_map` ran)."""

GROUP_JOIN_SQL = "JOIN relay_group rm ON rm.id = m.relay_id"
"""Joins each run to its relay as ``rm`` through its relay id: one integer
primary-key lookup, where :data:`JOIN_SQL` looks the run's URL up. ``rm`` has
the ``relay_key``, ``label``, ``kind`` and ``in_kb`` columns of
:data:`JOIN_SQL`'s (not ``base_url_norm``), and an inner join keeps every run
once :func:`ensure_relay_map` ran."""

_RUNS_SQL = "FROM history h JOIN history_metrics m ON m.history_id = h.id"
_NEW_URL_SQL = _url_sql("NEW.base_url_norm", "(SELECT base_url FROM history WHERE id = NEW.history_id)")


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create ``relay_map``, ``relay_map_meta`` and the trigger that marks the
    map stale (idempotent; a migration step)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS relay_map (
            base_url_norm TEXT PRIMARY KEY,
            relay_key     TEXT NOT NULL,
            label         TEXT NOT NULL,
            kind          TEXT NOT NULL,
            in_kb         INTEGER NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_relay_map_key ON relay_map (relay_key)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS relay_map_meta (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            kb_version TEXT NOT NULL,
            stale      INTEGER NOT NULL DEFAULT 0
        )"""
    )
    # INSERT OR REPLACE (how runs are extracted) fires the insert trigger.
    for name, event in (("insert", "INSERT"), ("update", "UPDATE OF base_url_norm")):
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS relay_map_stale_{name} AFTER {event} ON history_metrics"
            f" WHEN NOT EXISTS (SELECT 1 FROM relay_map WHERE base_url_norm = {_NEW_URL_SQL})"
            " BEGIN UPDATE relay_map_meta SET stale = 1 WHERE stale = 0; END"
        )


def _id_of(url: str) -> str:
    """The relay id ``relay_map`` gives the run URL ``url`` (SQL; NULL when missing)."""
    return f"(SELECT relay_id FROM relay_map WHERE base_url_norm = {url})"


def ensure_relay_ids(conn: sqlite3.Connection) -> None:
    """Add the relay ids: ``relay_group``, ``relay_map.relay_id``,
    ``history_metrics.relay_id`` and the triggers that set a new run's id
    (idempotent; a migration step). Marks the map stale, so the next
    :func:`ensure_relay_map` fills in the ids of the runs already saved."""
    from ekte.knowledge.snapshot import add_link_columns

    conn.execute(
        """CREATE TABLE IF NOT EXISTS relay_group (
            id        INTEGER PRIMARY KEY,
            relay_key TEXT NOT NULL UNIQUE,
            label     TEXT NOT NULL,
            kind      TEXT NOT NULL,
            in_kb     INTEGER NOT NULL
        )"""
    )
    add_link_columns(conn, "relay_map", {"relay_id": "INTEGER"})
    add_link_columns(conn, "history_metrics", {"relay_id": "INTEGER"})
    # the runs still to be given an id (none once the map is current)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_metrics_no_relay"
                 " ON history_metrics (history_id) WHERE relay_id IS NULL")
    set_id = (f"UPDATE history_metrics SET relay_id = {_id_of(_NEW_URL_SQL)}"
              " WHERE history_id = NEW.history_id;")
    # (INSERT OR REPLACE, how runs are extracted, fires the insert trigger)
    conn.execute("CREATE TRIGGER IF NOT EXISTS relay_id_insert AFTER INSERT ON history_metrics"
                 f" WHEN NEW.relay_id IS NULL BEGIN {set_id} END")
    conn.execute("CREATE TRIGGER IF NOT EXISTS relay_id_update"
                 f" AFTER UPDATE OF base_url_norm ON history_metrics BEGIN {set_id} END")
    conn.execute("UPDATE relay_map_meta SET stale = 1 WHERE stale = 0")


def _group_ids(conn: sqlite3.Connection, groups: dict[str, tuple[str, str, int]]) -> dict[str, int]:
    """Upsert the ``relay_group`` rows of ``groups`` (key -> label, kind,
    in_kb); returns key -> id."""
    conn.executemany(
        "INSERT INTO relay_group (relay_key, label, kind, in_kb) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (relay_key) DO UPDATE SET label = excluded.label, kind = excluded.kind,"
        " in_kb = excluded.in_kb",
        [(k, *v) for k, v in groups.items()],
    )
    ids: dict[str, int] = {}
    keys = list(groups)
    for i in range(0, len(keys), 500):
        part = keys[i:i + 500]
        ids.update((str(k), int(v)) for k, v in conn.execute(
            f"SELECT relay_key, id FROM relay_group WHERE relay_key IN ({', '.join('?' * len(part))})",
            part))
    return ids


# the relay_map key of history_metrics row t (as RUN_URL_SQL)
_URL_OF_T_SQL = _url_sql("t.base_url_norm", "(SELECT base_url FROM history WHERE id = t.history_id)")


def _state(conn: sqlite3.Connection) -> tuple[str | None, bool]:
    row = conn.execute("SELECT kb_version, stale FROM relay_map_meta WHERE id = 1").fetchone()
    return (None, True) if row is None else (str(row[0]), bool(row[1]))


def is_current(conn: sqlite3.Connection) -> bool:
    """Whether ``relay_map`` is up to date (any connection, read-only ones
    included): built from the current knowledge base and not marked stale."""
    return _state(conn) == (kb_version(load_for_grouping()), False)


def ensure_relay_map(conn: sqlite3.Connection) -> str:
    """Bring ``relay_map`` up to date with the knowledge base and the runs of
    ``conn`` (a writable ``history.db`` connection); returns the knowledge-base
    version the map now reflects.

    Rebuilds the whole map when :func:`~ekte.knowledge.relays.kb_version`
    differs from the stored one (and re-assigns the relay id of every run
    whose relay changed), else adds the run URLs it lacks when it is marked
    stale (and fills in the ids of the runs without one). Either is one
    Python pass over the URLs and one transaction (the caller's, when one is
    open; else its own, committed here).
    """
    knowledge = load_for_grouping()
    version = kb_version(knowledge)
    if _state(conn) == (version, False):
        return version
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")  # no run is saved until the map is consistent
    try:
        stored, _ = _state(conn)
        rebuild = stored != version
        if rebuild:
            urls = [str(r[0]) for r in conn.execute(f"SELECT DISTINCT {RUN_URL_SQL} {_RUNS_SQL}")]
            conn.execute("DELETE FROM relay_map")
        else:
            # the URLs the map lacks, and those without an id (mapped before step 11)
            urls = [str(r[0]) for r in conn.execute(
                f"SELECT DISTINCT {RUN_URL_SQL} AS u {_RUNS_SQL}"
                " WHERE NOT EXISTS (SELECT 1 FROM relay_map r WHERE r.base_url_norm = u)"
                " UNION SELECT base_url_norm FROM relay_map WHERE relay_id IS NULL")]
        resolver = RelayResolver(knowledge)
        resolved = {url: resolver.resolve({"base_url_norm": url or None})
                    for url in {*urls, ""}}  # the no-URL row is always there
        groups: dict[str, tuple[str, str, int]] = {}
        for g in resolved.values():
            # one description per key (they agree; else the largest, as MAX() in SQL)
            groups[g.key] = max(groups.get(g.key, ("", "", 0)), (g.label, g.kind, int(g.in_kb)))
        ids = _group_ids(conn, groups)
        conn.executemany(
            "INSERT OR REPLACE INTO relay_map (base_url_norm, relay_key, label, kind, in_kb,"
            " relay_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(url, g.key, g.label, g.kind, int(g.in_kb), ids[g.key]) for url, g in resolved.items()])
        if rebuild:
            # the runs whose relay changed, then the groups no URL maps to any more
            conn.execute(
                "UPDATE history_metrics AS t SET relay_id = x.rid FROM"
                f" (SELECT m.history_id AS hid, rm.relay_id AS rid {_RUNS_SQL} {JOIN_SQL}) AS x"
                " WHERE t.history_id = x.hid AND t.relay_id IS NOT x.rid")
            conn.execute("DELETE FROM relay_group WHERE id NOT IN (SELECT relay_id FROM relay_map)")
        else:
            conn.execute(f"UPDATE history_metrics AS t SET relay_id = {_id_of(_URL_OF_T_SQL)}"
                         " WHERE t.relay_id IS NULL")
        conn.execute(
            "INSERT INTO relay_map_meta (id, kb_version, stale) VALUES (1, ?, 0)"
            " ON CONFLICT (id) DO UPDATE SET kb_version = excluded.kb_version, stale = 0",
            (version,),
        )
        if own:
            conn.commit()
    except BaseException:
        if own:
            conn.rollback()
        raise
    return version
