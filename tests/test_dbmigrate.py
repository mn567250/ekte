"""The shared schema-migration mechanism and its use by every ekte database."""

from __future__ import annotations

import sqlite3
import sys
import threading

import pytest

from ekte import datadir, dbmigrate
from ekte.knowledge import store as kb_store
from ekte.web import history, watches

ALL = {
    "history.db": history.MIGRATIONS,
    "watches.db": watches.MIGRATIONS,
    "kb.db": kb_store.MIGRATIONS,
}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


def _version(path) -> int:
    with sqlite3.connect(path) as c:
        return c.execute("PRAGMA user_version").fetchone()[0]


def _tables(path) -> set[str]:
    with sqlite3.connect(path) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(path, table) -> set[str]:
    with sqlite3.connect(path) as c:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def test_migrations_are_numbered_in_order():
    for migrations in ALL.values():
        dbmigrate.validate(migrations)


@pytest.mark.parametrize("name", list(ALL))
def test_fresh_database_gets_latest_version_and_no_backup(data, name):
    with datadir.connect(name, ALL[name]):
        pass
    assert _version(data / name) == dbmigrate.latest(ALL[name])
    assert dbmigrate.backups(data / name) == []


def test_fresh_schemas_have_expected_tables(data):
    history.init()
    watches.init()
    with kb_store._connect():
        pass
    assert {"history", "history_metrics", "history_requests", "kb_snapshots"} <= _tables(data / "history.db")
    assert {"watches", "secret_meta", "kb_snapshots"} <= _tables(data / "watches.db")
    assert {"kb_entries", "kb_disabled"} <= _tables(data / "kb.db")


# --- every upgrade step, history.db ------------------------------------------ #
_HISTORY_V0 = """
CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, base_url TEXT,
    claimed_model TEXT, model TEXT, mode TEXT, suite TEXT, risk_level TEXT,
    score REAL, rating TEXT, report_json TEXT);
INSERT INTO history (ts, base_url, claimed_model, model, mode, suite, risk_level, score,
    rating, report_json) VALUES ('2026-01-01T00:00:00Z', 'https://x/v1', 'm', 'm', 'x',
    'quick', 'low', 90.0, 'ok', '{"generated_at": "2026-01-01T00:00:00Z"}');
"""


@pytest.mark.parametrize("start", [0, 1, 2, 3])
def test_history_upgrades_from_every_step(data, start):
    db = data / "history.db"
    # Build the schema as of version `start` by running the real steps.
    with sqlite3.connect(db) as c:
        if start == 0:
            c.executescript(_HISTORY_V0)
        else:
            c.executescript(_HISTORY_V0.split("INSERT")[0])
            for m in history.MIGRATIONS[:start]:
                m.apply(c)
            c.execute(
                "INSERT INTO history (ts, base_url, claimed_model, report_json) "
                "VALUES ('t', 'https://x/v1', 'm', '{}')"
            )
            c.execute(f"PRAGMA user_version = {start}")
    history.init()
    assert _version(db) == dbmigrate.latest(history.MIGRATIONS)
    assert {"surface", "requests_split", "watch_id", "api"} <= _cols(db, "history")
    assert {"decode_tps_p5", "decode_tps_p95"} <= _cols(db, "history_metrics")
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM history").fetchone()[0] == 1  # no loss
    backups = dbmigrate.backups(db)
    assert len(backups) == 1
    assert f".v{start}." in backups[0].name
    assert _version(backups[0]) == start


_WATCHES_030 = """
CREATE TABLE watches (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, base_url TEXT,
    api_key TEXT, model TEXT, claimed_model TEXT, api TEXT, declared_provider TEXT,
    suite TEXT, interval_sec INTEGER, alert_on TEXT, webhooks TEXT,
    enabled INTEGER DEFAULT 1, created_ts REAL, last_run_ts REAL, last_risk TEXT,
    last_score REAL, last_report_id INTEGER);
INSERT INTO watches (name, base_url, api_key, interval_sec) VALUES ('w', 'https://x', 'mem:', 60);
"""


def test_watches_unversioned_030_shape_upgrades_without_loss(data):
    db = data / "watches.db"
    with sqlite3.connect(db) as c:
        c.executescript(_WATCHES_030)
    assert _version(db) == 0
    watches.init()
    assert _version(db) == 2
    assert {"language", "surface", "embedding_dimensions", "kb_snapshot_id"} <= _cols(db, "watches")
    assert "secret_meta" in _tables(db)
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT name, interval_sec FROM watches").fetchall() == [("w", 60)]


def test_watches_step_two_only(data):
    db = data / "watches.db"
    with sqlite3.connect(db) as c:
        watches.MIGRATIONS[0].apply(c)
        c.execute("PRAGMA user_version = 1")
    watches.init()
    assert _version(db) == 2
    assert "kb_snapshots" in _tables(db)
    assert len(dbmigrate.backups(db)) == 1


def test_kb_unversioned_database_is_adopted(data):
    db = data / "kb.db"
    with sqlite3.connect(db) as c:
        c.execute(
            "CREATE TABLE kb_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL "
            "CHECK (kind IN ('provider','model')), provider TEXT NOT NULL, model_id TEXT NOT NULL "
            "DEFAULT '', body_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, origin TEXT, "
            "created_ts REAL, updated_ts REAL, UNIQUE (kind, provider, model_id))"
        )
        c.execute("INSERT INTO kb_entries (kind, provider, body_json) VALUES ('provider','p','{}')")
    with kb_store._connect() as conn:
        assert conn.execute("SELECT count(*) FROM kb_entries").fetchone()[0] == 1
    assert _version(db) == 1


# --- mechanism --------------------------------------------------------------- #
def _steps(log):
    def one(conn):
        conn.execute("CREATE TABLE a (x)")
        log.append(1)

    def two(conn):
        conn.execute("CREATE TABLE b (x)")
        log.append(2)

    def three(conn):
        conn.execute("ALTER TABLE a ADD COLUMN y")
        log.append(3)

    return [dbmigrate.Migration(1, one), dbmigrate.Migration(2, two), dbmigrate.Migration(3, three)]


def test_interrupted_migration_leaves_previous_version(data):
    log: list[int] = []
    steps = _steps(log)

    def broken(conn):
        conn.execute("CREATE TABLE c (x)")  # must be rolled back with the step
        raise RuntimeError("interrupted")

    steps[2] = dbmigrate.Migration(3, broken)
    with pytest.raises(RuntimeError, match="interrupted"), datadir.connect("t.db", steps):
        pass
    assert _version(data / "t.db") == 2  # steps 1 and 2 committed, 3 rolled back
    assert _tables(data / "t.db") == {"a", "b"}

    # A later, fixed release resumes from version 2 and backs up first.
    steps = _steps(log)
    with datadir.connect("t.db", steps):
        pass
    assert _version(data / "t.db") == 3
    assert log == [1, 2, 1 + 2][:2] + [3]
    assert [".v2." in b.name for b in dbmigrate.backups(data / "t.db")] == [True]


def test_newer_database_is_refused_and_untouched(data):
    db = data / "t.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE a (x)")
        c.execute("PRAGMA user_version = 9")
    before = db.read_bytes()
    with pytest.raises(dbmigrate.DatabaseTooNewError) as err, datadir.connect("t.db", _steps([])):
        pass
    msg = str(err.value)
    assert "version 9" in msg and "up to version 3" in msg
    assert "Upgrade ekte" in msg
    assert db.read_bytes() == before
    assert not list(data.glob("t.db-wal"))
    assert dbmigrate.backups(db) == []


def test_every_store_refuses_a_newer_database(data):
    for name, migrations in ALL.items():
        with sqlite3.connect(data / name) as c:
            c.execute("PRAGMA user_version = 99")
        with pytest.raises(dbmigrate.DatabaseTooNewError), datadir.connect(name, migrations):
            pass


def test_backup_is_a_consistent_copy_named_with_version_and_pruned(data):
    db = data / "t.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE keep (x)")
        c.execute("INSERT INTO keep VALUES (42)")
    created = []
    for _ in range(dbmigrate.BACKUP_KEEP + 2):
        with sqlite3.connect(db) as c:
            c.execute("PRAGMA user_version = 0")
        steps = [dbmigrate.Migration(1, lambda conn: None)]
        with datadir.connect("t.db", steps):
            pass
        created.append(sorted(p.name for p in data.glob("t.db.v0.*.bak")))
    kept = dbmigrate.backups(db)
    assert len(kept) == dbmigrate.BACKUP_KEEP
    assert all(p.name.startswith("t.db.v0.") and p.name.endswith(".bak") for p in kept)
    with sqlite3.connect(kept[0]) as c:
        assert c.execute("SELECT x FROM keep").fetchone()[0] == 42
    if sys.platform != "win32":  # POSIX file modes have no effect on Windows
        assert (kept[0].stat().st_mode & 0o777) == 0o600
    # The newest backups are the ones kept.
    assert [p.name for p in kept] == sorted(created[-1], reverse=True)


def test_concurrent_openers_run_each_step_once(data):
    log: list[int] = []
    lock = threading.Lock()

    def slow(conn):
        import time

        time.sleep(0.2)
        conn.execute("CREATE TABLE a (x)")
        with lock:
            log.append(1)

    steps = [dbmigrate.Migration(1, slow)]
    errors: list[BaseException] = []

    def go():
        try:
            with datadir.connect("t.db", steps):
                pass
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert log == [1]
    assert _version(data / "t.db") == 1


def test_connect_uses_wal(data):
    with datadir.connect("t.db", [dbmigrate.Migration(1, lambda c: None)]) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_wal_switch_waits_for_a_held_lock(data, tmp_path):
    # SQLite refuses a journal-mode change at once while another connection
    # holds a lock; _set_wal retries until the lock is released.
    path = tmp_path / "w.db"
    holder = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    holder.execute("CREATE TABLE t (x)")
    holder.execute("BEGIN EXCLUSIVE")
    threading.Timer(0.3, lambda: holder.execute("COMMIT")).start()
    conn = sqlite3.connect(str(path), timeout=0.01, check_same_thread=False)
    try:
        datadir._set_wal(conn, timeout=5.0)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
        holder.close()
