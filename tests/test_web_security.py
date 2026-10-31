"""Local-only hardening of `ekte serve` (ekte/web/security.py) and the data dir.

Skipped automatically when the optional web extra (fastapi) isn't installed.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web import security  # noqa: E402
from ekte.web.server import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path / "data"))
    return TestClient(create_app(), base_url="http://localhost:8000")


# ----- bind address ------------------------------------------------------ #
@pytest.fixture
def no_env(monkeypatch):
    for var in ("EKTE_HOST", "EKTE_PORT", "EKTE_CONTAINER"):
        monkeypatch.delenv(var, raising=False)


def test_bind_defaults_to_loopback(no_env):
    assert security.resolve_bind(None, None) == ("127.0.0.1", 8000)
    assert security.resolve_bind("::1", 9000) == ("::1", 9000)
    assert security.resolve_bind("[::1]", None) == ("::1", 8000)
    assert security.resolve_bind("localhost", None) == ("localhost", 8000)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "example.com"])
def test_non_loopback_bind_is_refused(no_env, host):
    with pytest.raises(security.BindError, match="loopback only"):
        security.resolve_bind(host, None)


def test_env_host_and_port(no_env, monkeypatch):
    monkeypatch.setenv("EKTE_HOST", "localhost")
    monkeypatch.setenv("EKTE_PORT", "9123")
    assert security.resolve_bind(None, None) == ("localhost", 9123)
    assert security.resolve_bind("127.0.0.1", 8001) == ("127.0.0.1", 8001)  # flags win
    monkeypatch.setenv("EKTE_PORT", "nope")
    with pytest.raises(security.BindError):
        security.resolve_bind(None, None)


def test_container_bind_needs_opt_in_and_a_container(no_env, monkeypatch):
    monkeypatch.setenv("EKTE_HOST", "0.0.0.0")
    monkeypatch.setenv("EKTE_CONTAINER", "1")
    monkeypatch.setattr(security, "in_container", lambda: False)
    with pytest.raises(security.BindError, match="no container runtime"):
        security.resolve_bind(None, None)
    monkeypatch.setattr(security, "in_container", lambda: True)
    assert security.resolve_bind(None, None) == ("0.0.0.0", 8000)
    monkeypatch.delenv("EKTE_CONTAINER")
    with pytest.raises(security.BindError):
        security.resolve_bind(None, None)


def test_serve_command_refuses_all_interfaces(no_env, monkeypatch):
    pytest.importorskip("uvicorn")
    from typer.testing import CliRunner

    from ekte.cli import app

    called = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: called.append(k))
    res = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--no-open"])
    assert res.exit_code == 2 and not called


# ----- Host allowlist (DNS rebinding) ------------------------------------ #
@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:9999", "[::1]:8000", "LOCALHOST"])
def test_loopback_host_headers_are_served(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "192.168.1.5:8000", ""])
def test_foreign_host_headers_are_refused(client, host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 421
    assert client.get("/", headers={"Host": host}).status_code == 421


def test_allowed_hosts_env_adds_names(client, monkeypatch):
    monkeypatch.setenv("EKTE_ALLOWED_HOSTS", "ekte.internal, other.local")
    assert client.get("/api/health", headers={"Host": "ekte.internal:8000"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "nope.local"}).status_code == 421


# ----- Origin / Sec-Fetch-Site / JSON (CSRF) ------------------------------ #
def test_same_origin_and_originless_writes_pass(client):
    assert client.post("/api/watches", json={"base_url": "", "model": ""}).status_code == 400
    r = client.post("/api/watches", json={"base_url": "", "model": ""},
                    headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 400  # reached the handler (bad input), not refused


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:9999", "null", "file://"])
def test_cross_origin_writes_are_refused(client, origin):
    r = client.post("/api/watches", json={"base_url": "https://x/v1", "model": "m"},
                    headers={"Origin": origin})
    assert r.status_code == 403
    assert client.get("/api/watches").json() == []
    assert client.delete("/api/history", headers={"Origin": origin}).status_code == 403


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_cross_site_fetch_metadata_is_refused(client, site):
    r = client.post("/api/watches", json={"base_url": "https://x/v1", "model": "m"},
                    headers={"Sec-Fetch-Site": site})
    assert r.status_code == 403


def test_non_json_bodies_are_refused(client):
    body = '{"base_url": "https://x/v1", "model": "m"}'
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        r = client.post("/api/watches", content=body, headers={"Content-Type": ctype})
        assert r.status_code == 415, ctype
    assert client.get("/api/watches").json() == []
    # bodyless writes need no content type
    assert client.post("/api/watches/999/run").status_code == 404
    assert client.delete("/api/watches/999").status_code == 200


def test_security_headers_on_every_response(client):
    for path in ("/", "/", "/api/health", "/static/ekte.css"):
        h = client.get(path).headers
        assert h["x-frame-options"] == "DENY", path
        assert h["x-content-type-options"] == "nosniff", path
        assert h["referrer-policy"] == "no-referrer", path
        assert "frame-ancestors 'none'" in h["content-security-policy"], path
    assert "access-control-allow-origin" not in client.get("/api/health").headers


def test_streaming_events_pass_through_the_middleware(client):
    r = client.post("/api/jobs", json={"model": "", "base_url": ""})
    assert r.status_code == 400
    assert r.headers["x-frame-options"] == "DENY"


# ----- owner-only data directory ------------------------------------------ #
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_data_dir_and_databases_are_owner_only(tmp_path, monkeypatch):
    from ekte.web import history, watches

    data = tmp_path / "fresh"
    monkeypatch.setenv("EKTE_DATA_DIR", str(data))
    watches.create({"base_url": "https://x/v1", "model": "m", "api_key": "sk-secret"})
    history.save({"target": {"base_url": "https://x/v1", "model": "m"}, "verdict": {}})
    assert stat.S_IMODE(os.stat(data).st_mode) == 0o700
    for name in ("watches.db", "history.db"):
        assert stat.S_IMODE(os.stat(data / name).st_mode) == 0o600, name
        for side in ("-wal", "-shm"):
            p = data / (name + side)
            if p.exists():
                assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p.name


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_existing_database_files_are_tightened(tmp_path, monkeypatch):
    from ekte.web import watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    db = tmp_path / "watches.db"
    db.touch()
    db.chmod(0o644)
    watches.list_all()
    assert stat.S_IMODE(os.stat(db).st_mode) == 0o600
