"""Upgrade guarantee: data written by released ekte versions opens without loss.

``tests/fixtures/upgrade/v<X>/`` holds a data directory written by release X
itself (scripts/make_upgrade_fixture.py: history, monitors with stored and
unstored keys, the user's own knowledge-base entries) and a manifest of what it
contains. Every fixture is opened with the current code; the migration must
succeed, keep every record readable and keep the main read paths of the web UI
and the command line working. A new minor release adds a fixture (see
docs/RELEASE_CHECKLIST.md).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ekte import dbmigrate, secretbox
from ekte.cli import app as cli_app
from ekte.knowledge import load_knowledge_base
from ekte.knowledge import store as kb_store
from ekte.web import history, watches
from ekte.web.server import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "upgrade"
DIRS = sorted(p for p in FIXTURES.glob("v*") if p.is_dir())
DBS = {"history.db": history.MIGRATIONS, "watches.db": watches.MIGRATIONS, "kb.db": kb_store.MIGRATIONS}


def test_a_fixture_exists_for_every_listed_release():
    names = {p.name for p in DIRS}
    assert "v0.30.0" in names


@pytest.fixture(params=DIRS, ids=lambda p: p.name)
def upgraded(request, tmp_path, monkeypatch):
    """The fixture copied to a scratch data directory, plus its manifest."""
    src: Path = request.param
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    for name in DBS:
        shutil.copy(src / name, tmp_path / name)
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EKTE_SECRET_KEY", manifest["master_key"])
    monkeypatch.delenv("EKTE_NO_USER_KB", raising=False)
    monkeypatch.delenv("EKTE_KB_DIR", raising=False)
    box = secretbox.env_box()
    secretbox.unlock(box)
    watches.forget_memory_keys()
    yield tmp_path, manifest, src
    secretbox.lock()
    watches.forget_memory_keys()


def _version(path: Path) -> int:
    with sqlite3.connect(path) as c:
        return int(c.execute("PRAGMA user_version").fetchone()[0])


def _open_all() -> None:
    history.init()
    watches.init()
    kb_store.list_entries()


def test_migration_succeeds_and_is_backed_up(upgraded):
    data, _manifest, src = upgraded
    before = {n: _version(data / n) for n in DBS}
    _open_all()
    for name, migrations in DBS.items():
        assert _version(data / name) == dbmigrate.latest(migrations), name
        if before[name] < dbmigrate.latest(migrations):
            kept = dbmigrate.backups(data / name)
            assert kept, f"{name} was migrated without a backup"
            # the backup is the database exactly as the old version wrote it
            with sqlite3.connect(kept[0]) as b, sqlite3.connect(src / name) as o:
                assert b.execute("PRAGMA user_version").fetchone() == o.execute("PRAGMA user_version").fetchone()
                assert list(b.iterdump()) == list(o.iterdump())
    # a second open runs no step and makes no further backup
    kept = {n: dbmigrate.backups(data / n) for n in DBS}
    _open_all()
    assert {n: dbmigrate.backups(data / n) for n in DBS} == kept


def test_history_is_complete_and_readable(upgraded):
    _data, manifest, _src = upgraded
    rows = {r["id"]: r for r in history.recent(500)}
    assert set(rows) == {r["id"] for r in manifest["history"]}
    for run in manifest["history"]:
        row = rows[run["id"]]
        assert row["score"] == run["score"]
        assert row["risk_level"] == run["risk_level"]
        report = history.get(run["id"])
        assert report is not None
        assert report["target"]["model"] == run["model"]
        assert report["target"]["base_url"] == run["base_url"]
        assert report["verdict"]["overall_score"] == run["score"]
        assert report["dimensions"] and report["detectors"]
    # still writable: a new run goes next to the migrated ones
    new_id = history.save(history.get(manifest["history"][0]["id"]) or {})
    assert new_id > max(rows)
    assert len(history.recent(500)) == len(manifest["history"]) + 1


def test_web_read_paths(upgraded):
    _data, manifest, _src = upgraded
    client = TestClient(create_app(), base_url="http://localhost")
    listed = client.get("/api/history").json()
    assert {r["id"] for r in listed} == {r["id"] for r in manifest["history"]}
    for run in manifest["history"]:
        for path in (f"/api/history/{run['id']}", f"/api/v1/history/{run['id']}"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert r.json()["verdict"]["overall_score"] == run["score"]
    assert client.get("/api/v1/history").status_code == 200
    ws = client.get("/api/watches").json()
    assert {w["name"] for w in ws} == {w["name"] for w in manifest["watches"]}
    assert all("api_key" not in w for w in ws)
    assert client.get("/api/kb/profiles").status_code == 200
    exported = client.get("/api/kb/export")
    assert exported.status_code == 200
    for entry in manifest["kb"]:
        assert entry["provider"] in exported.text


def test_monitors_keep_their_keys(upgraded):
    _data, manifest, _src = upgraded
    listed = {w["id"]: w for w in watches.list_all()}
    assert set(listed) == {w["id"] for w in manifest["watches"]}
    for w in manifest["watches"]:
        row = listed[w["id"]]
        assert row["name"] == w["name"]
        assert row["webhooks"] == ["https://hooks.example.com/ekte"]
        assert row["enabled"] is True and row["interval_sec"] == 3600
        full = watches.get(w["id"])
        assert full is not None
        if w["key"] == "stored":
            assert row["key_status"] == "encrypted"
            assert full["api_key"] == manifest["api_key"]
        elif w["key"] == "unstored":
            # never stored: still not stored, and reported as to be re-entered
            assert row["key_status"] == "missing"
            assert full["api_key"] is None and full["key_missing"] is True
        else:
            assert row["key_status"] == "reference"
            assert full["api_key"].startswith("env:")
    assert watches.get_key_storage() == watches.STORAGE_ENCRYPTED
    assert watches.get_canary()
    assert {w["id"] for w in watches.due(10**12)} >= {w["id"] for w in manifest["watches"]}


def test_user_knowledge_base_survives(upgraded):
    _data, manifest, _src = upgraded
    entries = {e["id"]: e for e in kb_store.list_entries()}
    assert set(entries) == {e["id"] for e in manifest["kb"]}
    for e in manifest["kb"]:
        got = entries[e["id"]]
        assert (got["kind"], got["provider"], got["model_id"]) == (e["kind"], e["provider"], e["model_id"])
        assert got["enabled"] is True and got["body"]
    kb = load_knowledge_base()
    assert kb.user_kb and not kb.warnings
    models = [e["model_id"] for e in manifest["kb"] if e["kind"] == "model"]
    for model_id in models:
        assert any(m.id == model_id for p in kb.providers.values() for m in p.models)


def test_cli_read_paths(upgraded):
    _data, manifest, _src = upgraded
    runner = CliRunner()
    provider = manifest["kb"][0]["provider"]
    result = runner.invoke(cli_app, ["kb", provider, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["user_kb"] and not data["warnings"]
    shown = {m.get("id") or m.get("model") for m in data["models"]}
    assert {e["model_id"] for e in manifest["kb"] if e["kind"] == "model"} <= shown
    out = runner.invoke(cli_app, ["kb-export"])
    assert out.exit_code == 0, out.output
    assert provider in out.output


@pytest.mark.parametrize("src", DIRS, ids=lambda p: p.name)
def test_fixtures_hold_no_real_secrets(src):
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    assert {p.name for p in src.iterdir()} == {*DBS, "manifest.json"}
    for name in DBS:
        raw = (src / name).read_bytes()
        assert manifest["api_key"].encode() not in raw, "an API key is stored in the clear"
        for marker in (b"sk-", b"Bearer ", b"BEGIN PRIVATE KEY"):
            assert marker not in raw, (name, marker)
    assert manifest["api_key"] == "fixture-api-key-not-real"
