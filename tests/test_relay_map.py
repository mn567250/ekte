"""The relay map (ekte/web/relay_map.py) and the knowledge-base version."""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest

from ekte import datadir, dbmigrate
from ekte.knowledge import store
from ekte.knowledge.relays import add_relay, kb_version
from ekte.web import analytics, history, relay_map

OPENAI = "https://api.openai.com/v1"
RELAY = "https://relay.example/v1"
SHARED = "https://shared.example/v1"
OTHER = "https://other.example/v1"
T0 = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("EKTE_KB_DIR", raising=False)
    monkeypatch.delenv("EKTE_NO_USER_KB", raising=False)
    return tmp_path


def _save(i: int, base_url: str | None, model: str | None = "model-a") -> int:
    report = {
        "tool_version": "0.34.0",
        "mode": "check",
        "started_at": (T0 + timedelta(minutes=i)).isoformat(),
        "generated_at": (T0 + timedelta(minutes=i + 1)).isoformat(),
        "suite": "standard",
        "target": {"base_url": base_url, "model": model, "claimed_model": model},
        "verdict": {"overall_score": 80.0, "risk_level": "clean", "rating": "B"},
        "dimensions": [],
        "detectors": [],
    }
    rid = history.save(report)
    assert rid > 0
    return rid


def _sql_groups() -> dict[int, dict]:
    """Each run's relay group and grouping keys, as SQL gives them."""
    keys = ", ".join(f"{sql} AS g_{name}" for name, sql in relay_map.GROUP_KEY_SQL.items())
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        relay_map.ensure_relay_map(conn)
        rows = conn.execute(
            f"SELECT h.id, rm.relay_key, rm.label, rm.kind, rm.in_kb, {keys}"
            " FROM history h JOIN history_metrics m ON m.history_id = h.id "
            + relay_map.JOIN_SQL
        ).fetchall()
    return {int(r["id"]): dict(r) for r in rows}


def _assert_matches_resolver() -> None:
    runs = history.analytics_runs()
    sql = _sql_groups()
    assert set(sql) == {int(r["id"]) for r in runs}  # every run joins exactly once
    resolver = analytics.RelayResolver()
    for run in runs:
        g, row = resolver.resolve(run), sql[int(run["id"])]
        assert (row["relay_key"], row["label"], row["kind"], bool(row["in_kb"])) == (
            g.key, g.label, g.kind, g.in_kb), run["base_url"]
        run["_group"] = g
        for name in relay_map.GROUP_KEY_SQL:
            assert row[f"g_{name}"] == analytics._group_of(name)(run)[0], (name, run["base_url"])


def test_map_groups_runs_exactly_as_the_resolver(data):
    add_relay("Cheap GPT", RELAY)
    # one URL listed by several entries: a saved relay wins over providers,
    # and among providers the smallest key wins
    store.upsert("provider", "zz-saved", {"display_name": "ZZ Saved", "base_url_hints": [OPENAI]},
                 origin="relay")
    store.upsert("provider", "bbb", {"display_name": "B", "base_url_hints": [SHARED]})
    store.upsert("provider", "aaa", {"display_name": "A", "base_url_hints": [SHARED]})
    for i, url in enumerate([
        OPENAI + "/chat/completions", RELAY + "/", RELAY, SHARED, OTHER, OTHER,
        "https://api.anthropic.com/v1", None, "", "  not a url ", "it's",
    ]):
        _save(i, url, model=None if i == 4 else "" if i == 5 else f"m{i % 3}")
    _assert_matches_resolver()
    by_key = {r["relay_key"]: r for r in _sql_groups().values()}
    assert by_key["zz-saved"]["kind"] == "relay"
    assert "aaa" in by_key and "bbb" not in by_key
    assert by_key[analytics.UNKNOWN_RELAY]["in_kb"] == 0
    assert "not a url" in by_key and "it's" in by_key
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        n = conn.execute("SELECT COUNT(*) FROM relay_map").fetchone()[0]
    assert n == 8  # one row per distinct URL, plus the no-URL row


def test_kb_version_changes_and_map_follows(data, tmp_path, monkeypatch):
    _save(0, RELAY)
    _save(1, OTHER)
    v0 = kb_version()
    assert kb_version() == v0  # stable
    _assert_matches_resolver()

    add_relay("Cheap GPT", RELAY)  # add
    v1 = kb_version()
    assert v1 != v0
    assert _sql_groups()[1]["label"] == "Cheap GPT"

    entry = store.find("provider", "cheap-gpt")  # rename
    store.upsert("provider", "cheap-gpt", {**entry["body"], "display_name": "Budget GPT"},
                 origin="relay")
    v2 = kb_version()
    assert v2 not in (v0, v1)
    assert _sql_groups()[1]["label"] == "Budget GPT"

    # a file edited outside any ekte process
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    monkeypatch.setenv("EKTE_KB_DIR", str(kb_dir))
    (kb_dir / "acme.yaml").write_text(
        f"provider: acme\ndisplay_name: Acme\nbase_url_hints: ['{OTHER}']\n", encoding="utf-8")
    v3 = kb_version()
    assert v3 != v2
    assert _sql_groups()[2]["relay_key"] == "acme"
    (kb_dir / "acme.yaml").write_text(
        f"provider: acme\ndisplay_name: Acme Two\nbase_url_hints: ['{OTHER}']\n", encoding="utf-8")
    assert kb_version() not in (v2, v3)
    assert _sql_groups()[2]["label"] == "Acme Two"
    _assert_matches_resolver()

    # a run with a new URL, saved by any process, marks the map stale; a known one does not
    def stale() -> int:
        with datadir.connect("history.db", history.MIGRATIONS) as conn:
            return conn.execute("SELECT stale FROM relay_map_meta").fetchone()[0]

    _save(3, RELAY + "/")
    assert stale() == 0
    rid = _save(2, "https://new.example/v1")
    assert stale() == 1
    assert _sql_groups()[rid]["relay_key"] == "https://new.example/v1"
    assert stale() == 0


def test_ensure_is_a_no_op_when_current_and_joins_an_open_transaction(data):
    _save(0, RELAY)
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        version = relay_map.ensure_relay_map(conn)
        assert version == kb_version()
        assert not conn.in_transaction
        conn.execute("UPDATE relay_map SET label = 'sentinel'")
        conn.commit()
        assert relay_map.ensure_relay_map(conn) == version  # current: nothing rewritten
        assert conn.execute("SELECT COUNT(*) FROM relay_map WHERE label = 'sentinel'").fetchone()[0] == 2
        conn.execute("UPDATE relay_map_meta SET kb_version = 'old'")  # opens a transaction
        assert relay_map.ensure_relay_map(conn) == version
        assert conn.in_transaction  # left to the caller
        conn.rollback()
        assert conn.execute("SELECT kb_version FROM relay_map_meta").fetchone()[0] == version


def test_rebuild_of_1000_urls_is_fast(data):
    history.init()
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        conn.executemany("INSERT INTO history (id, base_url) VALUES (?, ?)",
                         [(i, f"https://r{i}.example/v1") for i in range(1, 1001)])
        conn.executemany("INSERT INTO history_metrics (history_id, base_url_norm) VALUES (?, ?)",
                         [(i, f"https://r{i}.example/v1") for i in range(1, 1001)])
        conn.commit()
        relay_map.ensure_relay_map(conn)  # warms the knowledge-base cache
        best = float("inf")
        for _ in range(3):
            conn.execute("DELETE FROM relay_map_meta")
            conn.commit()
            t = time.perf_counter()
            relay_map.ensure_relay_map(conn)
            best = min(best, time.perf_counter() - t)
        assert conn.execute("SELECT COUNT(*) FROM relay_map").fetchone()[0] == 1001
    assert best < 0.05, best


def test_step_seven_adds_the_map_to_an_existing_database(data):
    _save(0, RELAY)
    db = datadir.db_path("history.db")
    with sqlite3.connect(db) as c:
        for name in ("relay_map_stale_insert", "relay_map_stale_update"):
            c.execute(f"DROP TRIGGER {name}")
        c.execute("DROP TABLE relay_map")
        c.execute("DROP TABLE relay_map_meta")
        c.execute("PRAGMA user_version = 6")
    history.init()
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == dbmigrate.latest(history.MIGRATIONS)
        assert c.execute("SELECT COUNT(*) FROM relay_map").fetchone()[0] == 0  # filled on first use
    assert _sql_groups()[1]["relay_key"] == RELAY


def _relay_ids() -> dict[int, str | None]:
    """Each run's relay key through its stored relay id (None: no id)."""
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        rows = conn.execute(
            "SELECT m.history_id, rg.relay_key FROM history_metrics m"
            " LEFT JOIN relay_group rg ON rg.id = m.relay_id").fetchall()
    return {int(r[0]): r[1] for r in rows}


def _assert_ids_match_the_map() -> None:
    expected = {rid: row["relay_key"] for rid, row in _sql_groups().items()}  # ensures the map
    assert _relay_ids() == expected
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        assert conn.execute("SELECT COUNT(*) FROM relay_map WHERE relay_id IS NULL").fetchone()[0] == 0
        # one group per key of the map
        keys = [k[0] for k in conn.execute("SELECT relay_key FROM relay_group ORDER BY 1")]
        mapped = [k[0] for k in conn.execute("SELECT DISTINCT relay_key FROM relay_map ORDER BY 1")]
    assert keys == mapped and set(expected.values()) <= set(keys)


def test_runs_carry_their_relay_id(data):
    _save(0, RELAY)
    _save(1, OTHER)
    _assert_ids_match_the_map()
    # a run with a known URL gets its id when saved; one with a new URL once the map catches up
    known = _save(2, OTHER + "/")
    assert _relay_ids()[known] == OTHER
    new = _save(3, "https://new.example/v1")
    assert _relay_ids()[new] is None
    _assert_ids_match_the_map()
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        old_id = conn.execute("SELECT id FROM relay_group WHERE relay_key = ?", (OTHER,)).fetchone()[0]
    # the knowledge base changes: runs move to their new relay, kept keys keep their id
    add_relay("Cheap GPT", RELAY)
    _assert_ids_match_the_map()
    assert _relay_ids()[1] == "cheap-gpt"
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        assert conn.execute("SELECT id FROM relay_group WHERE relay_key = ?",
                            (OTHER,)).fetchone()[0] == old_id
        # a run's normalised URL rewritten: its id follows at once
        conn.execute("UPDATE history_metrics SET base_url_norm = ? WHERE history_id = ?", (RELAY, known))
        conn.commit()
    assert _relay_ids()[known] == "cheap-gpt"
    _assert_ids_match_the_map()


def test_step_eleven_gives_existing_runs_their_relay_ids(data):
    _save(0, RELAY)
    _save(1, None)
    _sql_groups()  # the map is current
    db = datadir.db_path("history.db")
    with sqlite3.connect(db) as c:
        for name in ("relay_id_insert", "relay_id_update"):
            c.execute(f"DROP TRIGGER {name}")
        c.execute("DROP INDEX idx_history_metrics_no_relay")
        c.execute("DROP TABLE relay_group")
        c.execute("ALTER TABLE history_metrics DROP COLUMN relay_id")
        c.execute("ALTER TABLE relay_map DROP COLUMN relay_id")
        c.execute("PRAGMA user_version = 10")
    history.init()
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == dbmigrate.latest(history.MIGRATIONS)
        assert c.execute("SELECT stale FROM relay_map_meta").fetchone()[0] == 1
    assert set(_relay_ids().values()) == {None}
    _assert_ids_match_the_map()
    assert _relay_ids() == {1: RELAY, 2: analytics.UNKNOWN_RELAY}
