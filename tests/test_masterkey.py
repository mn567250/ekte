"""The monitors' master key life cycle (zing/web/masterkey.py) and its API.

Create (shown once, typed back), unlock after a restart, lock, rotate, move a
legacy key file out, reset a lost key, ZING_SECRET_KEY, and that the key never
leaks into an error, a cache or the data directory.
"""

from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from fastapi.testclient import TestClient  # noqa: E402

from zing import secretbox  # noqa: E402
from zing.web import masterkey, watches  # noqa: E402
from zing.web.masterkey import Vault, VaultError, vault  # noqa: E402
from zing.web.server import create_app  # noqa: E402

SECRET = "sk-relay-secret-abc123"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    vault.reset_state()  # a first start: no key yet
    _store_encrypted()  # these tests are about the master key: keys are stored
    vault.startup()


def _store_encrypted():
    watches.init()
    with watches._connect() as conn:
        watches._set_storage(conn, watches.STORAGE_ENCRYPTED)


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def _restart():
    vault.reset_state()
    return vault.startup()


def _setup(client) -> str:
    r = client.post("/api/secret/new")
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    r = client.post("/api/secret/new/confirm", json={"key": key})
    assert r.status_code == 200, r.text
    return key


def _watch(api_key=SECRET) -> int:
    return watches.create({"base_url": "https://relay.test/v1", "model": "m", "api_key": api_key})


def _raw_keys():
    with sqlite3.connect(watches._db_path()) as conn:
        return [r[0] for r in conn.execute("SELECT api_key FROM watches ORDER BY id")]


# --------------------------------------------------------------------------- #
# States and allowed actions
# --------------------------------------------------------------------------- #
ACTIONS = {
    "uninitialized": {"new"},
    "locked": {"unlock", "reset"},
    "unlocked": {"new", "lock"},
}


def _to_state(client, state):
    if state == "uninitialized":
        return None
    key = _setup(client)
    if state == "locked":
        _restart()
    return key


@pytest.mark.parametrize("state", list(ACTIONS))
def test_every_state_allows_only_its_actions(client, state):
    _to_state(client, state)
    st = client.get("/api/secret").json()
    assert st["state"] == state and set(st["actions"]) == ACTIONS[state]
    calls = {
        "new": lambda: client.post("/api/secret/new"),
        "unlock": lambda: client.post("/api/secret/unlock", json={"key": secretbox.generate_key()}),
        "reset": lambda: client.post("/api/secret/reset", json={"confirm": "RESET"}),
    }
    for action, call in calls.items():
        if action not in ACTIONS[state]:
            assert call().status_code == 409, action


def test_status_never_carries_a_key(client):
    key = _setup(client)
    r = client.get("/api/secret")
    assert key not in r.text and r.json()["fingerprint"]
    assert r.headers["cache-control"] == "no-store"


# --------------------------------------------------------------------------- #
# First key
# --------------------------------------------------------------------------- #
def test_first_key_shown_once_confirmed_and_never_stored(client, tmp_path):
    assert client.get("/api/secret").json()["state"] == "uninitialized"
    # Monitors with a key wait for it: 423 tells the UI to set it up.
    r = client.post("/api/watches", json={"base_url": "https://relay.test/v1", "model": "m",
                                          "api_key": SECRET})
    assert r.status_code == 423 and r.json()["state"] == "uninitialized"
    assert SECRET not in r.text

    first = client.post("/api/secret/new")
    assert first.headers["cache-control"] == "no-store"
    key = first.json()["key"]
    assert client.post("/api/secret/new").json()["key"] == key  # same until confirmed
    assert client.get("/api/secret").json()["state"] == "uninitialized"  # nothing written yet

    wrong = secretbox.generate_key()
    r = client.post("/api/secret/new/confirm", json={"key": wrong})
    assert r.status_code == 400 and wrong not in r.text and key not in r.text
    r = client.post("/api/secret/new/confirm", json={"key": f"  {key}\n"})  # pasted
    assert r.status_code == 200 and r.json()["state"] == "unlocked" and r.json()["source"] == "ui"

    r = client.post("/api/watches", json={"base_url": "https://relay.test/v1", "model": "m",
                                          "api_key": SECRET})
    assert r.status_code == 201
    blob = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    assert key.encode() not in blob and SECRET.encode() not in blob


def test_pending_key_expires():
    now = [0.0]
    v = Vault(clock=lambda: now[0])
    key = v.begin_new()
    now[0] += masterkey.PENDING_TTL_SEC + 1
    with pytest.raises(VaultError) as err:
        v.confirm_new(key)
    assert err.value.status == 410
    assert v.begin_new() != key  # a fresh one


def test_key_errors_never_echo_the_input(client):
    for body in ({"key": "sk-not-a-key-123"}, {"nokey": 1}, None):
        r = client.post("/api/secret/new/confirm", json=body) if body is not None else \
            client.post("/api/secret/new/confirm", content=b"{broken",
                        headers={"content-type": "application/json"})
        assert r.status_code in (400, 410) and "sk-not-a-key-123" not in r.text


# --------------------------------------------------------------------------- #
# Restart, unlock, lock
# --------------------------------------------------------------------------- #
def test_restart_locks_and_monitors_wait(client):
    key = _setup(client)
    wid = _watch()
    watches.mark_run(wid, "low", 90.0, None, 1.0)
    _restart()

    st = client.get("/api/secret").json()
    assert st["state"] == "locked" and st["counts"]["locked"] == 1
    assert client.get("/api/watches").json()[0]["key_status"] == "locked"
    assert client.post(f"/api/watches/{wid}/run").status_code == 423
    assert client.patch(f"/api/watches/{wid}", json={"api_key": "sk-other"}).status_code == 423
    assert watches.get(wid)["last_run_ts"] == 1.0  # still due once unlocked

    r = client.post("/api/secret/unlock", json={"key": secretbox.generate_key()})
    assert r.status_code == 403
    r = client.post("/api/secret/unlock", json={"key": key})
    assert r.status_code == 200 and r.json()["state"] == "unlocked"
    assert watches.get(wid)["api_key"] == SECRET

    assert client.post("/api/secret/lock").json()["state"] == "locked"
    assert watches.get(wid)["key_locked"] is True


async def test_scheduler_waits_while_locked(client, monkeypatch):
    from zing.web import server

    _setup(client)
    wid = _watch()
    keyless = _watch(api_key="")
    _restart()
    ran = []

    async def fake_audit(target, *_a, **_k):
        ran.append(target.api_key)
        raise RuntimeError("stop here")  # the audit started: that is all we check

    monkeypatch.setattr(server, "run_audit", fake_audit)
    with pytest.raises(server.WatchLocked):
        await server._run_one_watch(watches.get(wid))
    assert watches.get(wid)["last_run_ts"] is None  # not marked: runs after unlock
    with pytest.raises(RuntimeError, match="stop here"):
        await server._run_one_watch(watches.get(keyless))  # needs no master key
    assert ran == [""]


def test_another_process_changing_the_key_locks_the_server(client):
    _setup(client)
    _watch()
    assert vault.verify()
    # e.g. `zing secret rotate` in another shell
    watches.adopt_key(secretbox.SecretBox([secretbox.generate_key()], "cli"),
                      opener=secretbox.default())
    assert vault.verify() is False
    assert client.get("/api/secret").json()["state"] == "locked"


# --------------------------------------------------------------------------- #
# Rotate, legacy, reset
# --------------------------------------------------------------------------- #
def test_rotate_reencrypts_and_retires_the_old_key(client):
    old = _setup(client)
    wid = _watch()
    new = _setup(client)  # "new" while unlocked is a rotation
    assert new != old
    assert watches.get(wid)["api_key"] == SECRET
    with pytest.raises(secretbox.SecretError):
        secretbox.SecretBox([old], "t").open(_raw_keys()[0])
    _restart()
    assert client.post("/api/secret/unlock", json={"key": old}).status_code == 403
    assert client.post("/api/secret/unlock", json={"key": new}).status_code == 200


def test_rotate_is_all_or_nothing():
    secretbox.unlock(secretbox.SecretBox([secretbox.generate_key()], "t"))
    wid = _watch()
    foreign = secretbox.SecretBox([secretbox.generate_key()], "x").seal("sk-foreign")
    with sqlite3.connect(watches._db_path()) as conn:
        conn.execute("UPDATE watches SET api_key = ? WHERE id = ?", (foreign, wid))
    _watch()
    before = _raw_keys()
    with pytest.raises(secretbox.SecretError):
        watches.adopt_key(secretbox.SecretBox([secretbox.generate_key()], "n"),
                          opener=secretbox.default())
    assert _raw_keys() == before


def test_legacy_key_file_keeps_working_then_moves_out_with_a_new_key(client, tmp_path):
    old = secretbox.generate_key()
    secretbox.unlock(secretbox.SecretBox([old], "legacy"))
    wid = _watch()
    with sqlite3.connect(watches._db_path()) as conn:  # an older version had no check value
        conn.execute("DELETE FROM secret_meta")
    (tmp_path / "secret.key").write_text(old + "\n")

    st = _restart()
    assert st["state"] == "unlocked" and st["source"] == "legacy"
    assert "legacy_key_file" in st["warnings"]
    assert watches.get(wid)["api_key"] == SECRET

    new = _setup(client)
    assert new != old and not (tmp_path / "secret.key").exists()
    st = client.get("/api/secret").json()
    assert st["source"] == "ui" and st["warnings"] == []
    _restart()
    assert client.post("/api/secret/unlock", json={"key": new}).status_code == 200
    assert watches.get(wid)["api_key"] == SECRET


def test_reset_forgets_keys_and_starts_over(client, monkeypatch):
    from zing.web import server

    _setup(client)
    wid = _watch()
    ref = _watch(api_key="env:RELAY_KEY")
    _restart()
    assert client.post("/api/secret/reset", json={"confirm": "yes"}).status_code == 400
    cancelled = []
    monkeypatch.setattr(server, "_running_watches", {wid: {}})
    monkeypatch.setattr(server, "_cancel_watch", lambda w: cancelled.append(w) or True)
    r = client.post("/api/secret/reset", json={"confirm": "RESET"})
    assert r.status_code == 200 and r.json()["dropped"] == 1
    assert r.json()["state"] == "uninitialized" and cancelled == [wid]
    w = watches.get(wid)
    assert w["api_key"] == "" and w["enabled"] is False
    assert watches.get(ref)["api_key"] == "env:RELAY_KEY"


# --------------------------------------------------------------------------- #
# ZING_SECRET_KEY
# --------------------------------------------------------------------------- #
def test_env_key_unlocks_by_itself_and_cannot_be_changed_from_the_ui(client, monkeypatch):
    key = secretbox.generate_key()
    monkeypatch.setenv("ZING_SECRET_KEY", key)
    st = _restart()
    assert st["state"] == "unlocked" and st["source"] == "ZING_SECRET_KEY" and st["actions"] == []
    wid = _watch()
    assert client.post("/api/secret/new").status_code == 409
    assert client.post("/api/secret/lock").status_code == 409
    _restart()
    assert watches.get(wid)["api_key"] == SECRET

    monkeypatch.setenv("ZING_SECRET_KEY", secretbox.generate_key())
    st = _restart()
    assert st["state"] == "env_mismatch" and st["actions"] == [] and st["error"]
    assert client.post(f"/api/watches/{wid}/run").status_code == 423


def test_secret_routes_keep_the_csrf_checks(client):
    r = client.post("/api/secret/new", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/secret/unlock", content=b'{"key": "x"}',
                    headers={"content-type": "text/plain"})
    assert r.status_code in (403, 415)

