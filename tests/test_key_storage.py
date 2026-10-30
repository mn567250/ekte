"""Where the monitors' API keys are kept: not at all (``memory``, the default)
or encrypted in watches.db (``encrypted``, opt-in), and switching between them.

The master key itself is covered in test_masterkey.py, the encryption in
test_secretbox.py.
"""

from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from fastapi.testclient import TestClient  # noqa: E402

from ekte import secretbox  # noqa: E402
from ekte.web import watches  # noqa: E402
from ekte.web.masterkey import vault  # noqa: E402
from ekte.web.server import create_app  # noqa: E402

SECRET = "sk-relay-secret-not-stored-42"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    _restart()  # a first start: nothing chosen yet


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def _restart():
    """What a server restart does: memory is gone, startup reloads."""
    vault.reset_state()
    st = vault.startup()
    vault.take_stored_keys()
    return st


def _watch(api_key=SECRET, **kw) -> int:
    cfg = {"base_url": "https://relay.test/v1", "model": "m", "api_key": api_key}
    return watches.create(cfg, **kw)


def _db_bytes(tmp_path) -> bytes:
    return b"".join(p.read_bytes() for p in tmp_path.glob("watches.db*"))


def _raw_keys():
    with sqlite3.connect(watches._db_path()) as conn:
        return [r[0] for r in conn.execute("SELECT api_key FROM watches ORDER BY id")]


def _store_mode(mode):
    with watches._connect() as conn:
        watches._set_storage(conn, mode)


def _setup(client) -> str:
    key = client.post("/api/secret/new").json()["key"]
    assert client.post("/api/secret/new/confirm", json={"key": key}).status_code == 200
    return key


# --------------------------------------------------------------------------- #
# The default: no key is stored
# --------------------------------------------------------------------------- #
def test_a_new_install_stores_no_key(client, tmp_path):
    assert client.get("/api/secret").json()["storage"] == "memory"
    vault.reset_state()  # nothing held: storing must not need a master key
    wid = _watch()
    ref = _watch(api_key="env:RELAY_KEY")
    assert _raw_keys() == ["mem:", "env:RELAY_KEY"]
    assert SECRET.encode() not in _db_bytes(tmp_path)
    assert watches.get(wid)["api_key"] == SECRET
    rows = {w["id"]: w for w in client.get("/api/watches").json()}
    assert rows[wid]["key_status"] == "memory" and rows[wid]["has_key"] is True
    assert rows[ref]["key_status"] == "reference"
    assert SECRET not in client.get("/api/watches").text


def test_a_restart_loses_the_key_and_the_monitor_waits(client):
    wid = _watch()
    watches.mark_run(wid, "low", 90.0, None, 1.0)
    _restart()
    row = watches.get(wid)
    assert row["api_key"] is None and row["key_missing"] is True and row["key_error"]
    assert client.get("/api/watches").json()[0]["key_status"] == "missing"
    assert client.get("/api/secret").json()["counts"]["missing"] == 1
    r = client.post(f"/api/watches/{wid}/run")
    assert r.status_code == 409 and r.json()["key_missing"] is True
    assert watches.get(wid)["last_run_ts"] == 1.0  # still due once the key is back

    assert client.patch(f"/api/watches/{wid}", json={"api_key": SECRET}).status_code == 200
    assert watches.get(wid)["api_key"] == SECRET and _raw_keys() == ["mem:"]


async def test_scheduler_waits_for_a_missing_key(client, monkeypatch):
    from ekte.web import server

    wid = _watch()
    _restart()
    with pytest.raises(server.WatchKeyMissing):
        await server._run_one_watch(watches.get(wid))
    assert watches.get(wid)["last_run_ts"] is None


def test_delete_forgets_the_key():
    wid = _watch()
    watches.delete(wid)
    assert watches._held(wid) is None


def test_plain_text_keys_of_an_old_version_leave_the_database(tmp_path):
    with sqlite3.connect(watches._db_path()) as conn:
        conn.execute("DELETE FROM secret_meta WHERE name = 'key_storage'")
    wid = _watch()
    with sqlite3.connect(watches._db_path()) as conn:
        conn.execute("UPDATE watches SET api_key = ? WHERE id = ?", (SECRET, wid))
    _restart()  # no canary, no enc: key -> memory; the plain key moves out
    assert _raw_keys() == ["mem:"]
    assert watches.get(wid)["api_key"] == SECRET
    assert SECRET.encode() not in _db_bytes(tmp_path)


# --------------------------------------------------------------------------- #
# Upgrades keep what is there
# --------------------------------------------------------------------------- #
def test_an_install_with_encrypted_keys_keeps_storing_them(client):
    with sqlite3.connect(watches._db_path()) as conn:
        conn.execute("DELETE FROM secret_meta WHERE name = 'key_storage'")
        conn.execute("INSERT INTO secret_meta (name, value) VALUES ('canary', 'enc:v1:x')")
    assert _restart()["storage"] == "encrypted"
    # the choice is recorded: it does not flip with the environment later
    with sqlite3.connect(watches._db_path()) as conn:
        conn.execute("DELETE FROM secret_meta WHERE name = 'canary'")
    assert watches.get_key_storage() == "encrypted"


def test_ekte_secret_key_selects_encrypted_storage(monkeypatch):
    with sqlite3.connect(watches._db_path()) as conn:
        conn.execute("DELETE FROM secret_meta WHERE name = 'key_storage'")
    monkeypatch.setenv("EKTE_SECRET_KEY", secretbox.generate_key())
    st = _restart()
    assert st["storage"] == "encrypted" and st["state"] == "unlocked"


# --------------------------------------------------------------------------- #
# Switching
# --------------------------------------------------------------------------- #
def test_switch_to_encrypted_needs_a_master_key_then_seals_the_held_keys(client):
    wid = _watch()
    lost = _watch(api_key="sk-other")
    watches._remember(lost, None)  # as if lost with a restart
    r = client.post("/api/secret/storage", json={"mode": "encrypted"})
    assert r.status_code == 423 and r.json()["state"] == "uninitialized"
    assert watches.get_key_storage() == "memory"

    _setup(client)
    r = client.post("/api/secret/storage", json={"mode": "encrypted"})
    assert r.status_code == 200, r.text
    assert r.json()["storage"] == "encrypted" and r.json()["moved"] == 1
    raw = _raw_keys()
    assert secretbox.is_sealed(raw[0]) and raw[1] == "mem:"
    assert watches.get(wid)["api_key"] == SECRET
    assert watches.get(lost)["key_missing"] is True
    _restart()  # survives a restart once the master key is entered again
    assert watches.get(wid)["key_locked"] is True


def test_switch_to_memory_moves_the_keys_and_erases_them(client, tmp_path):
    _store_mode("encrypted")
    key = _setup(client)
    wid = _watch()
    assert secretbox.is_sealed(_raw_keys()[0])
    _restart()  # locked: the keys cannot be opened yet, nothing changes
    r = client.post("/api/secret/storage", json={"mode": "memory"})
    assert r.status_code == 423 and watches.get_key_storage() == "encrypted"
    assert secretbox.is_sealed(_raw_keys()[0])

    assert client.post("/api/secret/unlock", json={"key": key}).status_code == 200
    r = client.post("/api/secret/storage", json={"mode": "memory"})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["storage"] == "memory" and st["moved"] == 1 and st["state"] == "uninitialized"
    assert _raw_keys() == ["mem:"] and watches.get_canary() is None
    assert watches.get(wid)["api_key"] == SECRET
    assert b"enc:v1:" not in _db_bytes(tmp_path)


def test_storage_route_validates_and_keeps_the_csrf_checks(client):
    assert client.post("/api/secret/storage", json={"mode": "disk"}).status_code == 400
    assert client.post("/api/secret/storage", json={"mode": "memory"}).json()["moved"] == 0
    r = client.post("/api/secret/storage", json={"mode": "encrypted"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/secret/storage", json={"mode": "memory"})
    assert r.headers["cache-control"] == "no-store"


# --------------------------------------------------------------------------- #
# The classic UI never stores a key
# --------------------------------------------------------------------------- #
def test_classic_ui_keys_stay_in_memory_even_when_storing_is_on(client):
    _store_mode("encrypted")
    _setup(client)
    body = {"base_url": "https://relay.test/v1", "model": "m", "api_key": SECRET,
            "key_storage": "memory"}
    r = client.post("/api/watches", json=body)
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert _raw_keys() == ["mem:"]
    r = client.patch(f"/api/watches/{wid}", json={"api_key": "sk-new", "key_storage": "memory"})
    assert r.status_code == 200 and _raw_keys() == ["mem:"]
    assert watches.get(wid)["api_key"] == "sk-new"
    # the override can only keep a key out of the database, never put one in
    _store_mode("memory")
    r = client.post("/api/watches", json={**body, "key_storage": "encrypted"})
    assert _raw_keys() == ["mem:", "mem:"]
