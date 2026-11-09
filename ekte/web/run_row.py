"""Each run's row of numbers: the ``history_metrics`` columns aggregation reads.

A run's ``history`` row holds its report (tens of kB, mostly in overflow
pages), so the query core (:mod:`ekte.web.query`) never reads it to select,
group, sort or aggregate runs: everything it needs from ``history`` is
copied onto the run's ``history_metrics`` row (``m``) as a number,
:data:`RUN_COLUMNS`, the single definition of each value:

* ``started_us`` — ``started_at`` in Unix microseconds: it orders and
  compares exactly as ``started_at`` (:func:`ekte.web.query.time_sql`),
  gives the first and last run time back without text
  (:func:`ekte.web.query.us_text`), and buckets in integer arithmetic;
* ``score`` — the run's score; ``grade_value`` — its grade on the 1..6
  scale (:func:`ekte.web.metrics.grade_value_sql`); ``risk_value`` — its
  risk level in History's order (:data:`RISK_ORDER`: clean 0,
  inconclusive 1, low 2, medium 3, high 4; -1 for a level ekte does not
  know; NULL for none);
* ``model_id`` — its model key (as :data:`ekte.web.relay_map.GROUP_KEY_SQL`
  spells it) in ``model_group``; ``url_id`` — its raw base URL in
  ``run_url``; ``facet_id`` — its combination of few-valued filter values
  (:data:`FACETS`: surface, suite, mode, API, stream mode, detection, risk,
  execution, as the URL spells them) in ``facet_combo``; ``surface_id`` —
  its surface alone in ``run_surface`` (every widget filters by surface:
  one integer comparison per run instead of a lookup of its combination);
  ``suite_id``, ``stream_mode_id``, ``api_id`` — those values (NULL for
  none) in ``run_suite`` / ``run_stream_mode`` / ``run_api``, for whether
  they vary in a series (:data:`VARYING`); ``version_id``,
  ``kb_profile_id`` — the ekte version and knowledge-base profile (NULL for
  none) in ``run_version`` / ``run_kb_profile``, for where they change in a
  series (:data:`CHANGES`); ``model_in_kb`` — 1 when the run's model is in
  the knowledge base.
  These lookup tables (:class:`Lookup`) number each distinct value once;
  rows no run uses any more are harmless.

The relay id (``history_metrics.relay_id``) depends on the knowledge base
and is kept by :mod:`ekte.web.relay_map`; the outcome counts by
:func:`ekte.web.analytics_store.ensure_outcome_columns`.

Triggers keep the columns current (:func:`ensure_run_columns`): a new
metrics row (``INSERT OR REPLACE`` included), a changed ``history`` column
one of them reads, a changed ``started_at``. Which source columns fire them
is read off the SQL itself, so a column is defined in one place.

:data:`GROUP_ID_SQL` groups runs by an integer of their row (relay ×
model packed into one: ``relay_id << MODEL_BITS | model_id``);
:func:`label_sql` names the few resulting groups afterwards.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from ekte.web import analytics_store
from ekte.web.analytics import ALL_KEY
from ekte.web.metrics import grade_value_sql
from ekte.web.relay_map import GROUP_KEY_SQL

__all__ = [
    "COLUMNS", "FACETS", "FACET_COMBOS", "GROUP_BY_SQL", "GROUP_ID_SQL", "MODELS", "MODEL_BITS", "RISK_ORDER",
    "RUN_COLUMNS", "SURFACES", "URLS", "Lookup", "ensure_run_columns", "label_sql",
]

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


@dataclass(frozen=True)
class Lookup:
    """A table numbering each distinct combination of some text values of a
    run: ``id INTEGER PRIMARY KEY`` and one ``TEXT NOT NULL`` column per
    value (``columns``: column -> SQL over ``h`` and ``m``), unique together.
    A run whose values are NULL has no id."""

    table: str
    columns: Mapping[str, str]

    def id_sql(self) -> str:
        """The id of the run's combination (SQL over ``h`` and ``m``)."""
        same = " AND ".join(f"{c} = {e}" for c, e in self.columns.items())
        return f"(SELECT id FROM {self.table} WHERE {same})"

    def create_sql(self) -> str:
        cols = ", ".join(f"{c} TEXT NOT NULL" for c in self.columns)
        return (f"CREATE TABLE IF NOT EXISTS {self.table} (id INTEGER PRIMARY KEY, {cols},"
                f" UNIQUE ({', '.join(self.columns)}))")

    def add_sql(self, where: str) -> str:
        """Number the combinations of the runs ``where`` selects that are new.
        NOT EXISTS, not INSERT OR IGNORE: in a trigger the conflict clause of
        the statement that fired it wins, and INSERT OR REPLACE (how metrics
        rows are written) would re-number a combination others point to."""
        values = ", ".join(self.columns.values())
        same = " AND ".join(f"t.{c} = {e}" for c, e in self.columns.items())
        known = " AND ".join(f"{e} IS NOT NULL" for e in self.columns.values())
        return (f"INSERT INTO {self.table} ({', '.join(self.columns)}) SELECT DISTINCT {values}"
                f" {_RUN_SQL} WHERE {where} AND {known}"
                f" AND NOT EXISTS (SELECT 1 FROM {self.table} t WHERE {same})")


MODELS = Lookup("model_group", {"model_key": GROUP_KEY_SQL["model"]})
URLS = Lookup("run_url", {"base_url": "h.base_url"})
SURFACES = Lookup("run_surface", {"surface": FACETS["surface"]})
FACET_COMBOS = Lookup("facet_combo", {COLUMNS[k]: sql for k, sql in FACETS.items()})
# the values a series reports as varying (query.Series.mixed): none is NULL
VARYING = {name: Lookup(f"run_{name}", {"value": f"NULLIF(h.{name}, '')"})
           for name in ("suite", "stream_mode", "api")}
# the values whose changes a series annotates (annotation kind -> column, lookup): none is NULL
CHANGES = {"tool_version": ("version_id", Lookup("run_version", {"value": "NULLIF(m.tool_version, '')"})),
           "kb_profile": ("kb_profile_id",
                          Lookup("run_kb_profile", {"value": "NULLIF(m.kb_profile_hash, '')"}))}

RISK_ORDER = ("clean", "inconclusive", "low", "medium", "high")
"""Risk levels by ``risk_value`` (History's order; a run without one sorts
as inconclusive)."""
_RISK_SQL = ("CASE WHEN NULLIF(h.risk_level, '') IS NULL THEN NULL ELSE CASE h.risk_level "
             + " ".join(f"WHEN '{r}' THEN {i}" for i, r in enumerate(RISK_ORDER)) + " ELSE -1 END END")

RUN_COLUMNS: dict[str, tuple[str, str | Lookup]] = {
    # the whole UTC seconds of the fixed-width form (parsed without the fraction:
    # older SQLite truncates a fractional time before 1970 towards zero, newer
    # floors it) plus its microseconds
    "started_us": ("INTEGER", "CAST(strftime('%s', substr(m.started_at, 1, 19)) AS INTEGER) * 1000000"
                              " + CAST(substr(m.started_at, 21, 6) AS INTEGER)"),
    "model_in_kb": ("INTEGER", "m.kb_model_id IS NOT NULL"),
    "score": ("REAL", "h.score"),
    "grade_value": ("INTEGER", grade_value_sql("h.rating")),
    "risk_value": ("INTEGER", _RISK_SQL),
    "model_id": ("INTEGER", MODELS),
    "url_id": ("INTEGER", URLS),
    "surface_id": ("INTEGER", SURFACES),
    "facet_id": ("INTEGER", FACET_COMBOS),
    **{f"{name}_id": ("INTEGER", lookup) for name, lookup in VARYING.items()},
    **{column: ("INTEGER", lookup) for column, lookup in CHANGES.values()},
}
"""``history_metrics`` column -> (SQL type, the run's value: SQL over
``history h`` and ``history_metrics m``, or the :class:`Lookup` that numbers it)."""

LOOKUPS: tuple[Lookup, ...] = tuple(d for _, d in RUN_COLUMNS.values() if isinstance(d, Lookup))

NUMBERS: tuple[str, ...] = (
    "relay_id", "model_id", *(c for c in RUN_COLUMNS if c != "model_id"),
    *(c for c, t in analytics_store.METRIC_COLS.items()
      if t != "TEXT" and c not in ("started_at_estimated", "extract_version")),
    *analytics_store.OUTCOME_COLS.values(),
)
"""The narrow run row: every number of ``history_metrics`` aggregation reads
(the run's relay and model ids first)."""

INDEXES: dict[str, str] = {
    # the narrow run row as a covering index: aggregations read its entries
    # (a few hundred bytes) instead of the rows (text columns too), already
    # in relay x model order, so grouping by relay or relay x model needs no sort
    "idx_run_row": ", ".join(NUMBERS),
}
"""Index name -> its ``history_metrics`` columns."""

MODEL_BITS = 20
"""``relay_model`` groups pack ``relay_id << MODEL_BITS | model_id`` (model
ids stay below 2**20)."""
_MODEL_MASK = (1 << MODEL_BITS) - 1

GROUP_ID_SQL: dict[str, str] = {
    "relay": "m.relay_id",
    "model": "m.model_id",
    "relay_model": f"(m.relay_id << {MODEL_BITS} | m.model_id)",
    "all": "0",
}
"""Each grouping's integer group id on the run's row ``m`` (every run of a
group has the one id; ``all``: the constant 0)."""

GROUP_BY_SQL: dict[str, str] = {
    "relay": "m.relay_id", "model": "m.model_id", "relay_model": "m.relay_id, m.model_id", "all": "",
}
"""What to ``GROUP BY`` for each grouping's id: the columns themselves, in
``idx_run_row`` order, so relay and relay × model groups need no sort
(``all``: nothing; SQLite would sort every run by a constant)."""


def label_sql(group: str, inner: str) -> str:
    """``inner`` (a query with the group id as ``gid``, alias ``s``) with its
    groups named: ``g`` (the group key, as :data:`ekte.web.relay_map.GROUP_KEY_SQL`
    spells it), and for relay groups ``rk``, ``rl``, ``rkind``, ``rin`` (the
    relay's key, label, kind, in_kb), for model groups ``mk`` (the model)."""
    relay = "rg.relay_key AS rk, rg.label AS rl, rg.kind AS rkind, rg.in_kb AS rin"
    if group == "relay":
        return (f"SELECT rg.relay_key AS g, {relay}, s.* FROM ({inner}) s"
                " JOIN relay_group rg ON rg.id = s.gid")
    if group == "model":
        return (f"SELECT mg.model_key AS g, mg.model_key AS mk, s.* FROM ({inner}) s"
                " JOIN model_group mg ON mg.id = s.gid")
    if group == "relay_model":
        return (f"SELECT rg.relay_key || '|' || mg.model_key AS g, {relay}, mg.model_key AS mk,"
                f" s.* FROM ({inner}) s JOIN relay_group rg ON rg.id = s.gid >> {MODEL_BITS}"
                f" JOIN model_group mg ON mg.id = s.gid & {_MODEL_MASK}")
    return f"SELECT '{ALL_KEY}' AS g, s.* FROM ({inner}) s"


# --------------------------------------------------------------------------- #
# Triggers
# --------------------------------------------------------------------------- #
_RUN_SQL = "FROM history h JOIN history_metrics m ON m.history_id = h.id"


def _value_sql(definition: str | Lookup) -> str:
    return definition.id_sql() if isinstance(definition, Lookup) else definition


def _sources(alias: str) -> list[str]:
    """The columns of ``history`` (``h``) or ``history_metrics`` (``m``) the
    run columns read."""
    sql = " ".join(_value_sql(d) for _, d in RUN_COLUMNS.values())
    return sorted(set(re.findall(rf"\b{alias}\.(\w+)", sql)))


def _refresh_sql(rid: str, where: str | None = None) -> str:
    """Statements that add the lookup rows of run ``rid`` and set its
    :data:`RUN_COLUMNS` (on the run ``rid``, or the rows ``where`` selects)."""
    adds = [lookup.add_sql(f"h.id = {rid}" if where is None else "TRUE") for lookup in LOOKUPS]
    values = ", ".join(_value_sql(d) for _, d in RUN_COLUMNS.values())
    update = (f"UPDATE history_metrics SET ({', '.join(RUN_COLUMNS)}) = (SELECT {values} {_RUN_SQL}"
              f" WHERE h.id = {rid}) WHERE {where or f'history_id = {rid}'}")
    return "; ".join([*adds, update]) + ";"


def _trigger_sql() -> dict[str, str]:
    """Trigger name -> its CREATE statement."""
    fire = {
        "run_row_insert": ("INSERT ON history_metrics", "NEW.history_id"),
        "run_row_history": (f"UPDATE OF {', '.join(_sources('h'))} ON history", "NEW.id"),
        "run_row_metrics": (f"UPDATE OF {', '.join(_sources('m'))} ON history_metrics",
                            "NEW.history_id"),
    }
    return {name: f"CREATE TRIGGER {name} AFTER {event} BEGIN {_refresh_sql(rid)} END"
            for name, (event, rid) in fire.items()}


# triggers of earlier schema versions that set some of these columns
_OLD_TRIGGERS = ("facet_id_insert", "facet_id_update")


def ensure_run_columns(conn: sqlite3.Connection) -> None:
    """Add the lookup tables, :data:`RUN_COLUMNS` and the triggers that keep
    them current, and fill them for the runs already saved (a migration
    step). Idempotent and cheap once done: when every trigger is as defined
    here, the columns are current and nothing is rewritten. Creates
    :data:`INDEXES`."""
    from ekte.knowledge.snapshot import add_link_columns

    triggers = _trigger_sql()
    stored = dict(conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN"
        f" ({', '.join('?' * (len(triggers) + len(_OLD_TRIGGERS)))})",
        (*triggers, *_OLD_TRIGGERS)).fetchall())
    if stored != triggers:
        for name in (*triggers, *_OLD_TRIGGERS):
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        for lookup in LOOKUPS:
            conn.execute(lookup.create_sql())
        add_link_columns(conn, "history_metrics", {c: t for c, (t, _) in RUN_COLUMNS.items()})
        for sql in triggers.values():
            conn.execute(sql)
        for statement in _refresh_sql("history_metrics.history_id", "TRUE").rstrip(";").split("; "):
            conn.execute(statement)
    for name, cols in INDEXES.items():
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON history_metrics ({cols})")
