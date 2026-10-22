"""Tests for the web Tools page (embedding + rerank auditors).

Skipped automatically when the optional web extra (fastapi) isn't installed.
No network is touched: most tests monkeypatch the auditors to return canned
verdict dicts (the end-to-end ones run the runner against a mock transport), so
they exercise the HTTP plumbing — request parsing, the claimed
dimension (0 = the runner resolves it from the KB), ConfigError -> 400, secret
hygiene, and the served page/nav.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import zing.embed_audit as embed_audit  # noqa: E402
from zing.web.server import create_app  # noqa: E402

SECRET = "sk-tools-secret-key-abcdef123456"


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def _embed_verdict(target) -> dict:
    # Mirror the real audit_embeddings verdict shape, already redacted (api key is
    # a fingerprint, never the raw secret).
    return {
        "risk_level": "clean",
        "score": 100.0,
        "findings": [
            {
                "id": "embed.dimension",
                "title": "Vector dimension matches the claimed model",
                "status": "pass",
                "severity": "info",
                "summary": "Returned 3072-d vectors, as expected.",
                "evidence": {"returned": 3072, "claimed": 3072},
            }
        ],
        "target": {
            "name": target.name,
            "base_url": target.base_url,
            "model": target.model,
            "claimed_model": target.claimed_model,
            "declared_provider": target.declared_provider,
            "api_key_fingerprint": "sha256:deadbeef",
        },
    }


def _rerank_verdict(target) -> dict:
    return {
        "risk_level": "clean",
        "score": 100.0,
        "findings": [
            {
                "id": "rerank.known_answer",
                "title": "Reranker ranks the obvious answer first",
                "status": "pass",
                "severity": "info",
                "summary": "Document 2 ranked first.",
                "evidence": {"top_index": 2, "expected": 2, "ranking": [2, 0, 1, 3]},
            }
        ],
        "target": {
            "name": target.name,
            "base_url": target.base_url,
            "model": target.model,
            "claimed_model": target.claimed_model,
            "declared_provider": target.declared_provider,
            "api_key_fingerprint": "sha256:cafef00d",
        },
    }


def _fake_embed_audit(monkeypatch, captured: dict) -> None:
    """Stand in for the runner-backed audit: record what reached it and answer
    with a canned verdict (saved as history row 7)."""

    async def fake_run(target, *, claimed_dimensions=0, suite="standard", **_):
        captured.update(claimed_dimensions=claimed_dimensions, suite=suite, api_key=target.api_key)
        return target, 7

    def fake_verdict(report, report_id=None):
        return {**_embed_verdict(report), "report_id": report_id}

    monkeypatch.setattr(embed_audit, "run_embedding_audit", fake_run)
    monkeypatch.setattr(embed_audit, "tool_verdict", fake_verdict)


def test_embed_endpoint_returns_verdict_and_hides_secret(client, monkeypatch):
    captured = {}

    _fake_embed_audit(monkeypatch, captured)

    r = client.post(
        "/api/embed",
        json={
            "base_url": "https://relay.embed.test/v1",
            "api_key": SECRET,
            "model": "text-embedding-3-large",
            "claimed_dimensions": 3072,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] == "clean" and body["score"] == 100.0
    assert body["findings"][0]["id"] == "embed.dimension"
    assert "target" in body
    # The verdict reached the auditor with the resolved secret...
    assert captured["api_key"] == SECRET
    assert captured["claimed_dimensions"] == 3072 and captured["suite"] == "standard"
    assert body["report_id"] == 7
    # ...but the secret must never cross back to the browser.
    raw = r.text
    assert SECRET not in raw
    assert "api_key" not in body["target"]
    assert "api_key_fingerprint" in body["target"]


def test_embed_resolves_dimension_from_kb_when_not_given(client, monkeypatch):
    captured = {}

    _fake_embed_audit(monkeypatch, captured)
    # No claimed_dimensions in the request and an unknown model -> 0 (skip match),
    # exercising the KB-resolution branch without depending on KB contents.
    r = client.post(
        "/api/embed",
        json={
            "base_url": "https://relay.embed.test/v1",
            "api_key": SECRET,
            "model": "totally-unknown-embedding-xyz",
        },
    )
    assert r.status_code == 200
    assert captured["claimed_dimensions"] == 0


def test_embed_bad_target_is_400(client, monkeypatch):
    async def fake_run(target, **_):  # pragma: no cover - never called
        raise AssertionError("auditor must not run on a bad target")

    monkeypatch.setattr(embed_audit, "run_embedding_audit", fake_run)
    # Missing base_url -> ConfigError -> clean 400, not a 500 and no audit.
    r = client.post("/api/embed", json={"model": "m", "api_key": SECRET})
    assert r.status_code == 400
    assert "error" in r.json()
    assert SECRET not in r.text
    # an unknown suite is a 400 too
    r = client.post("/api/embed", json={"base_url": "https://relay.embed.test/v1", "model": "m",
                                        "suite": "bogus"})
    assert r.status_code == 400


def test_embed_endpoint_runs_the_runner_and_saves(client, monkeypatch):
    # End to end through the real runner against a mock /embeddings endpoint.
    import httpx

    from zing.clients import OpenAICompatibleClient
    from zing.web import history

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        inputs = _json.loads(request.content or b"{}").get("input") or []
        data = [{"index": i, "embedding": [float(len(t) % 7 == j) + 0.01 * j for j in range(8)]}
                for i, t in enumerate(inputs)]
        return httpx.Response(200, json={"model": "e-model", "data": data})

    monkeypatch.setattr(
        "zing.runner.make_client",
        lambda target, **_: OpenAICompatibleClient(target, transport=httpx.MockTransport(handler)),
    )
    r = client.post("/api/embed", json={"base_url": "https://relay.embed.test/v1",
                                        "api_key": SECRET, "model": "e-model",
                                        "claimed_dimensions": 8})
    assert r.status_code == 200
    body = r.json()
    assert body["surface"] == "embedding" and isinstance(body["report_id"], int)
    assert {f["id"] for f in body["findings"]} >= {"embed.connectivity", "embed.dimension",
                                                   "embed.drift", "embed.determinism"}
    assert SECRET not in r.text
    saved = history.get(body["report_id"])
    assert saved["surface"] == "embedding" and saved["target"]["model"] == "e-model"


def _fake_rerank_audit(monkeypatch, captured: dict) -> None:
    """Stand in for the runner-backed rerank audit (saved as history row 9)."""

    async def fake_run(target, *, suite="standard", **_):
        captured.update(suite=suite, api_key=target.api_key, model=target.model)
        return target, 9

    def fake_verdict(report, report_id=None):
        return {**_rerank_verdict(report), "report_id": report_id}

    monkeypatch.setattr(embed_audit, "run_rerank_audit", fake_run)
    monkeypatch.setattr(embed_audit, "tool_verdict", fake_verdict)


def test_rerank_endpoint_returns_verdict_and_hides_secret(client, monkeypatch):
    captured: dict = {}
    _fake_rerank_audit(monkeypatch, captured)
    r = client.post(
        "/api/rerank",
        json={"base_url": "https://relay.rerank.test/v1", "api_key": SECRET, "model": "r-model"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] == "clean" and body["report_id"] == 9
    assert body["findings"][0]["id"] == "rerank.known_answer"
    # The default suite, and the key reached the audit (but not the response).
    assert captured == {"suite": "standard", "api_key": SECRET, "model": "r-model"}
    assert SECRET not in r.text
    assert "api_key" not in body["target"]


def test_rerank_endpoint_passes_the_suite(client, monkeypatch):
    captured: dict = {}
    _fake_rerank_audit(monkeypatch, captured)
    r = client.post("/api/rerank", json={"base_url": "https://relay.rerank.test/v1",
                                         "model": "r-model", "suite": "deep"})
    assert r.status_code == 200
    assert captured["suite"] == "deep"


def test_rerank_bad_target_is_400(client, monkeypatch):
    async def fake_run(*a, **k):  # pragma: no cover - never called
        raise AssertionError("auditor must not run on a bad target")

    monkeypatch.setattr(embed_audit, "run_rerank_audit", fake_run)
    r = client.post("/api/rerank", json={"base_url": "", "model": "", "api_key": SECRET})
    assert r.status_code == 400
    assert "error" in r.json()
    assert SECRET not in r.text
    # an unknown suite is a 400 too
    r = client.post("/api/rerank", json={"base_url": "https://relay.rerank.test/v1", "model": "m",
                                         "suite": "bogus"})
    assert r.status_code == 400


def test_rerank_endpoint_runs_the_runner_and_saves(client, monkeypatch):
    # End to end through the real runner against a mock /rerank endpoint; holds
    # whichever rerank detectors are registered.
    import json as _json

    import httpx

    from zing.clients import OpenAICompatibleClient
    from zing.web import history

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json.loads(request.content or b"{}")
        words = set(str(body.get("query") or "").lower().split())
        docs = body.get("documents") or []
        results = [{"index": i, "relevance_score": len(words & set(str(d).lower().split())) / 10}
                   for i, d in enumerate(docs)]
        results.sort(key=lambda x: -x["relevance_score"])
        return httpx.Response(200, json={"model": "r-model", "results": results})

    monkeypatch.setattr(
        "zing.runner.make_client",
        lambda target, **_: OpenAICompatibleClient(target, transport=httpx.MockTransport(handler)),
    )
    r = client.post("/api/rerank", json={"base_url": "https://relay.rerank-e2e.test/v1",
                                         "api_key": SECRET, "model": "r-model", "suite": "smoke"})
    assert r.status_code == 200
    body = r.json()
    assert body["surface"] == "rerank" and body["suite"] == "smoke"
    assert isinstance(body["report_id"], int)
    assert {"risk_level", "score", "findings", "target", "rating", "headline"} <= set(body)
    assert all(f["id"].startswith(("rerank.", "performance.")) for f in body["findings"])
    assert SECRET not in r.text
    saved = history.get(body["report_id"])
    assert saved["surface"] == "rerank" and saved["target"]["model"] == "r-model"
    rows = client.get("/api/history").json()
    assert any(row.get("id") == body["report_id"] and row.get("surface") == "rerank" for row in rows)


def test_serves_tools_page_and_index_nav(client):
    r = client.get("/tools")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "工具箱" in r.text and "嵌入审计" in r.text and "重排审计" in r.text
    # The home page links to /tools in its nav.
    index = client.get("/").text
    assert 'href="/tools"' in index


# ----- /api/models: relay model listing for the picker's custom provider ----- #


def _mock_relay(monkeypatch, handler):
    """Route every client make_client builds through an httpx.MockTransport."""
    import httpx

    import zing.clients as clients

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


def test_modelpicker_offers_custom_relay_provider(client):
    r = client.get("/modelpicker.js")
    assert r.status_code == 200
    assert "/api/models" in r.text
    assert "Custom (from relay)" in r.text
