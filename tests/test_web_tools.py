"""Tests for the old Tools address and /api/models.

Skipped automatically when the optional web extra (fastapi) isn't installed.
No network is touched.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web.server import create_app  # noqa: E402

SECRET = "sk-tools-secret-key-abcdef123456"


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def test_embedding_and_rerank_audits_start_on_the_audit_page(client):
    # the Tools page is gone: its address opens the audit page's embedding surface
    r = client.get("/tools", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/v2/?surface=embedding"
    assert 'data-page="audit"' in client.get("/v2/?surface=rerank").text


# ----- /api/models: relay model listing for the picker's custom provider ----- #


def _mock_relay(monkeypatch, handler):
    """Route every client make_client builds through an httpx.MockTransport."""
    import httpx

    import ekte.clients as clients

    real = clients.make_client
    seen: list = []

    def recording(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        clients,
        "make_client",
        lambda cfg, **_: real(cfg, transport=httpx.MockTransport(recording)),
    )
    return seen


def test_models_endpoint_lists_relay_models_and_hides_secret(client, monkeypatch):
    import httpx

    seen = _mock_relay(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"data": [{"id": "gpt-4o"}, {"id": "deepseek-chat"}, {"id": "gpt-4o"}]}
        ),
    )
    r = client.post(
        "/api/models",
        json={"base_url": "https://relay.example.com/v1", "api_key": SECRET, "api": "openai"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["api"] == "openai"
    assert data["models"] == ["deepseek-chat", "gpt-4o"]
    assert SECRET not in r.text
    assert str(seen[0].url) == "https://relay.example.com/v1/models"
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"


def test_models_endpoint_works_without_api_key(client, monkeypatch):
    import httpx

    seen = _mock_relay(
        monkeypatch, lambda req: httpx.Response(200, json={"data": [{"id": "llama3.2"}]})
    )
    # Self-hosted relays (Ollama, LM Studio) need no key.
    r = client.post("/api/models", json={"base_url": "http://localhost:11434/v1"})
    assert r.status_code == 200
    assert r.json()["models"] == ["llama3.2"]
    assert "authorization" not in seen[0].headers


def test_models_endpoint_reports_relay_error_without_secret(client, monkeypatch):
    import httpx

    _mock_relay(
        monkeypatch,
        lambda req: httpx.Response(401, json={"error": {"message": f"bad key {SECRET}"}}),
    )
    r = client.post(
        "/api/models",
        json={"base_url": "https://relay.example.com/v1", "api_key": SECRET},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["status_code"] == 401
    assert "bad key" in data["error"]
    assert SECRET not in r.text


def test_models_endpoint_bad_base_url_is_400(client):
    r = client.post("/api/models", json={"base_url": "ftp://nope", "api_key": SECRET})
    assert r.status_code == 400
    assert "base_url" in r.json()["error"]


def test_relay_config_lists_the_relays_models(client):
    r = client.get("/v2/static/relaycfg.js")
    assert r.status_code == 200
    assert 'fetch("/api/models"' in r.text
