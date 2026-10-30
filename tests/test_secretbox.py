"""Encryption at rest for the monitors' stored API keys (ekte/secretbox.py).

Covers the box itself, where the master key comes from, the watch store's
encryption, legacy plain-text migration, an unreadable key in the scheduler and
the `ekte secret` commands. The key's life cycle (create, unlock, lock, rotate,
reset) is in test_masterkey.py.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

pytest.importorskip("cryptography")

from typer.testing import CliRunner  # noqa: E402

from ekte import secretbox  # noqa: E402
from ekte.cli import app  # noqa: E402
from ekte.web import watches  # noqa: E402
from ekte.web.masterkey import vault  # noqa: E402

SECRET = "sk-super-secret-123"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    # conftest holds a fresh master key in memory for every test.
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    # These tests are about encrypted storage (the opt-in key storage mode).
    watches.init()
    with watches._connect() as conn:
        watches._set_storage(conn, watches.STORAGE_ENCRYPTED)


def _restart():
    """What a server restart does to the key: memory is gone, startup reloads."""
    vault.reset_state()
    return vault.startup()


def _box(*keys: str) -> secretbox.SecretBox:
    return secretbox.SecretBox(list(keys) or [secretbox.generate_key()], "test")


def _raw_keys(path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT api_key FROM watches ORDER BY id")]


def _watch(**kw):
    from ekte.web import watches

    cfg = {"name": "w", "base_url": "https://relay.test/v1", "model": "gpt-4o",
           "api_key": SECRET, "interval_sec": 3600, **kw}
    return watches.create(cfg)


# --------------------------------------------------------------------------- #
# The box
# --------------------------------------------------------------------------- #
def test_seal_open_roundtrip():
    box = _box()
    sealed = box.seal(SECRET)
    assert sealed.startswith("enc:v1:") and SECRET not in sealed
    assert box.open(sealed) == SECRET
    assert box.seal(sealed) == sealed  # never double-sealed


@pytest.mark.parametrize("value", ["", None, "env:OPENAI_API_KEY", "file:/run/secrets/k"])
def test_references_and_empty_pass_through(value):
    box = _box()
    assert box.seal(value) == (value or "")
    assert box.open(value) == (value or "")


def test_wrong_key_and_tampering_raise():
    sealed = _box().seal(SECRET)
    with pytest.raises(secretbox.SecretError):
        _box().open(sealed)
    box = _box()
    good = box.seal(SECRET)
    with pytest.raises(secretbox.SecretError):
        box.open(good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB"))


def test_invalid_key_is_a_secret_error():
    with pytest.raises(secretbox.SecretError):
        secretbox.SecretBox(["not-a-fernet-key"], "test")


def test_older_keys_still_open_and_reseal_moves_to_first():
    old, new = secretbox.generate_key(), secretbox.generate_key()
    sealed_old = _box(old).seal(SECRET)
    both = _box(new, old)
    assert both.open(sealed_old) == SECRET
    assert _box(new).open(both.reseal(sealed_old)) == SECRET


# --------------------------------------------------------------------------- #
# Where the master key comes from
# --------------------------------------------------------------------------- #
def test_no_key_file_is_ever_created(tmp_path):
    vault.reset_state()
    assert vault.startup()["state"] == "uninitialized"
    with pytest.raises(secretbox.SecretLocked):
        secretbox.default()
    _watch(api_key="")  # a keyless watch needs no master key
    assert not (tmp_path / "secret.key").exists()
    assert not any(p.name.endswith(".key") for p in tmp_path.iterdir())


def test_env_key_literal_and_file_reference(tmp_path, monkeypatch):
    key = secretbox.generate_key()
    monkeypatch.setenv("EKTE_SECRET_KEY", key)
    st = _restart()
    assert st["state"] == "unlocked" and st["source"] == "EKTE_SECRET_KEY"
    assert secretbox.default().keys == [key]
    assert not (tmp_path / "secret.key").exists()

    other = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    other.write_text(key + "\n")
    monkeypatch.setenv("EKTE_SECRET_KEY", f"file:{other}")
    assert _restart()["state"] == "unlocked" and secretbox.default().keys == [key]


def test_env_key_inside_the_data_dir_is_flagged(tmp_path, monkeypatch):
    inside = tmp_path / "k"
    inside.write_text(secretbox.generate_key())
    monkeypatch.setenv("EKTE_SECRET_KEY", f"file:{inside}")
    assert "env_in_data_dir" in _restart()["warnings"]


def test_parse_key_trims_and_never_echoes():
    key = secretbox.generate_key()
    assert secretbox.parse_key(f"  {key[:20]}\n{key[20:]} ") == key
    with pytest.raises(secretbox.SecretError) as err:
        secretbox.parse_key("sk-not-a-master-key")
    assert "sk-not-a-master-key" not in str(err.value)


def test_canary_round_trip():
    box, other = _box(), _box()
    canary = secretbox.make_canary(box)
    assert secretbox.check_canary(box, canary)
    assert not secretbox.check_canary(other, canary)
    assert not secretbox.check_canary(box, None)


# --------------------------------------------------------------------------- #
# Watch store
# --------------------------------------------------------------------------- #
def test_store_encrypts_on_disk_and_decrypts_for_the_scheduler():
    from ekte.web import watches

    wid = _watch()
    [raw] = _raw_keys(watches._db_path())
    assert raw.startswith("enc:v1:")
    assert SECRET.encode() not in watches._db_path().read_bytes()
    assert watches.get(wid)["api_key"] == SECRET
    assert watches.due(time.time())[0]["api_key"] == SECRET
    [row] = watches.list_all()
    assert "api_key" not in row and row["has_key"] and row["key_status"] == "encrypted"

    watches.update(wid, api_key="sk-new")
    assert _raw_keys(watches._db_path())[0].startswith("enc:v1:")
    assert watches.get(wid)["api_key"] == "sk-new"


def test_references_are_stored_as_is():
    from ekte.web import watches

    wid = _watch(api_key="env:RELAY_KEY")
    assert _raw_keys(watches._db_path()) == ["env:RELAY_KEY"]
    assert watches.get(wid)["api_key"] == "env:RELAY_KEY"
    assert watches.list_all()[0]["key_status"] == "reference"


def test_due_only_returns_due_rows():
    from ekte.web import watches

    wid = _watch()
    watches.mark_run(wid, None, None, None, time.time())
    assert watches.due(time.time()) == []
    assert [d["id"] for d in watches.due(time.time() + 3600)] == [wid]


def test_init_migrates_legacy_plain_text_and_scrubs_it():
    from ekte.web import watches

    watches.init()
    vault.reset_state()  # an old install: no key yet, plain keys in the DB
    path = watches._db_path()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO watches (name, base_url, api_key, model, webhooks, interval_sec)"
            " VALUES ('old', 'https://x/v1', ?, 'm', '[]', 3600)", (SECRET,)
        )
        conn.execute(
            "INSERT INTO watches (name, base_url, api_key, model, webhooks, interval_sec)"
            " VALUES ('ref', 'https://x/v1', 'env:K', 'm', '[]', 3600)"
        )
    assert watches.list_all()[-1]["key_status"] == "plain"
    box = _box()
    assert watches.migrate_keys(box) == 1
    assert watches.migrate_keys(box) == 0  # idempotent
    secretbox.unlock(box)
    raw = _raw_keys(path)
    assert raw[0].startswith("enc:v1:") and raw[1] == "env:K"
    for p in (path, path.with_name(path.name + "-wal")):
        if p.exists():
            assert SECRET.encode() not in p.read_bytes()
    assert watches.get(1)["api_key"] == SECRET


def test_lost_master_key_is_reported_not_guessed(tmp_path):
    from ekte.web import watches

    wid = _watch()
    secretbox.unlock(_box())  # another key than the one the store used
    row = watches.get(wid)
    assert row["api_key"] is None and row["key_error"]
    assert watches.list_all()[0]["key_status"] == "unreadable"
    assert watches.key_counts()["unreadable"] == 1
    # Re-entering the key heals it.
    watches.update(wid, api_key=SECRET)
    assert watches.get(wid)["api_key"] == SECRET and watches.get(wid)["key_error"] is None


async def test_scheduler_skips_a_watch_whose_key_is_unreadable(tmp_path, monkeypatch):
    from ekte.web import server, watches

    wid = _watch()
    watches.mark_run(wid, "low", 90.0, None, 1.0)
    secretbox.unlock(_box())

    async def boom(*_a, **_k):  # the audit must never start
        raise AssertionError("audited without a key")

    monkeypatch.setattr(server, "run_audit", boom)
    with pytest.raises(server.WatchKeyUnreadable):
        await server._run_one_watch(watches.get(wid))
    row = watches.get(wid)
    assert row["last_run_ts"] > 1.0 and row["last_risk"] == "low"  # result kept


# --------------------------------------------------------------------------- #
# ekte secret
# --------------------------------------------------------------------------- #
def test_cli_status_never_prompts_and_reports_the_state():
    vault.reset_state()
    res = CliRunner().invoke(app, ["secret", "status"])
    assert res.exit_code == 0, res.output
    assert "uninitialized" in res.output


def test_cli_rotate_creates_prints_once_and_stores_nothing(tmp_path):
    from ekte.web import watches

    vault.reset_state()
    res = CliRunner().invoke(app, ["secret", "rotate"])
    assert res.exit_code == 0, res.output
    key = res.stdout.strip().splitlines()[-1]
    assert key not in "".join(p.read_text(errors="ignore") for p in tmp_path.iterdir() if p.is_file())
    assert secretbox.check_canary(_box(key), watches.get_canary())

    # Later: locked; status works, rotate asks for the current key.
    vault.reset_state()
    res = CliRunner().invoke(app, ["secret", "status"])
    assert "locked" in res.output and "1 encrypted" not in res.output
    res = CliRunner().invoke(app, ["secret", "rotate"], input="wrong-key\n")
    assert res.exit_code == 2
    vault.reset_state()
    res = CliRunner().invoke(app, ["secret", "rotate"], input=key + "\n")
    assert res.exit_code == 0, res.output
    new = res.stdout.strip().splitlines()[-1]
    assert new != key and secretbox.check_canary(_box(new), watches.get_canary())


def test_cli_rotate_moves_a_legacy_key_file_out(tmp_path):
    from ekte.web import watches

    old = secretbox.generate_key()
    secretbox.unlock(_box(old))
    wid = _watch()
    (tmp_path / "secret.key").write_text(old + "\n")
    vault.reset_state()
    res = CliRunner().invoke(app, ["secret", "export"])
    assert res.exit_code == 0 and old in res.stdout
    res = CliRunner().invoke(app, ["secret", "rotate"])
    assert res.exit_code == 0, res.output
    new = res.stdout.strip().splitlines()[-1]
    assert new != old and not (tmp_path / "secret.key").exists()
    assert watches.get(wid)["api_key"] == SECRET
    with pytest.raises(secretbox.SecretError):
        _box(old).open(_raw_keys(watches._db_path())[0])


def test_cli_rotate_env_key_in_two_steps(monkeypatch):
    from ekte.web import watches

    old = secretbox.generate_key()
    monkeypatch.setenv("EKTE_SECRET_KEY", old)
    _restart()
    wid = _watch()
    res = CliRunner().invoke(app, ["secret", "rotate"])
    assert res.exit_code == 0
    pair = res.stdout.strip().splitlines()[-1]
    new = pair.split(",")[0]
    assert pair == f"{new},{old}"
    monkeypatch.setenv("EKTE_SECRET_KEY", pair)
    vault.reset_state()
    res = CliRunner().invoke(app, ["secret", "rotate"])
    assert res.exit_code == 0, res.output
    monkeypatch.setenv("EKTE_SECRET_KEY", new)
    assert _restart()["state"] == "unlocked"
    assert watches.get(wid)["api_key"] == SECRET
