"""Contract tests for the public HTTP API under /api/v1/ (docs/STABILITY.md#surface-http-api).

They pin paths, status codes, the error format, the response fields and the
``X-Ekte-API`` header, plus the local-only protections on the public paths.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.models import AuditReport, RedactedTarget, Verdict  # noqa: E402
from ekte.web.server import create_app  # noqa: E402

JOB_FIELDS = {
    "id", "kind", "base_url", "model", "claimed_model", "suite", "surface", "dimensions",
    "baseline_url", "api", "api_auto", "stream_mode", "status", "created", "started", "finished",
    "progress", "done", "total", "current", "waiting_for", "report_id", "error",
}


@pytest.fixture
def api():
    # as a context manager: one event loop, so a queued job outlives its request
    with TestClient(create_app(), base_url="http://localhost") as client:
        yield client


@pytest.fixture
def fake_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    async def fake_run_audit(target, options, *, on_event=None, **_):
        on_event({"type": "start", "total": 1, "probe_requests": 0})
        return AuditReport(
            tool_version="0", mode="check", suite="standard",
            target=RedactedTarget(name="t", kind="target", base_url=target.base_url, model="m"),
            verdict=Verdict(),
        )

    monkeypatch.setattr("ekte.web.server.run_audit", fake_run_audit)


def test_public_responses_carry_the_v1_header(api):
    assert api.get("/api/v1/history").headers["x-ekte-api"] == "v1"
    assert api.get("/api/v1/jobs/nope").headers["x-ekte-api"] == "v1"


def test_every_other_api_path_is_internal(api):
    for path in ("/api/health", "/api/jobs", "/api/history", "/api/kb", "/api/watches", "/api/nope"):
        assert api.get(path).headers["x-ekte-api"] == "internal", path
    assert "x-ekte-api" not in api.get("/v2/").headers


def test_bad_job_request_is_400_with_the_error_format(api):
    r = api.post("/api/v1/jobs", json={"base_url": "", "model": ""})
    assert r.status_code == 400
    assert set(r.json()) == {"error"} and isinstance(r.json()["error"], str)
    r = api.post("/api/v1/jobs", json={"base_url": "https://x.example/v1", "model": "m", "suite": "bogus"})
    assert r.status_code == 400 and "suite" in r.json()["error"]


def test_unknown_job_is_404_with_the_error_format(api):
    for path in ("/api/v1/jobs/nope", "/api/v1/jobs/nope/events"):
        r = api.get(path)
        assert r.status_code == 404 and r.json() == {"error": "not found"}


def test_queue_get_and_follow_a_job(api, fake_audit):
    r = api.post("/api/v1/jobs", json={"base_url": "https://x.example/v1", "model": "m", "api_key": "sk-secret"})
    assert r.status_code == 200
    job = r.json()
    assert set(job) == JOB_FIELDS and job["kind"] == "audit" and job["surface"] == "chat"
    assert job["status"] in ("queued", "running", "done")
    assert "sk-secret" not in r.text
    got = api.get(f"/api/v1/jobs/{job['id']}")
    assert got.status_code == 200 and set(got.json()) == JOB_FIELDS and got.json()["id"] == job["id"]
    ev = api.get(f"/api/v1/jobs/{job['id']}/events")
    assert ev.status_code == 200 and ev.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[5:]) for line in ev.text.splitlines() if line.startswith("data:")]
    types = [e["type"] for e in events]
    assert "report" in types and types[-1] == "done"
    report = next(e for e in events if e["type"] == "report")
    assert set(report) == {"type", "report", "report_id"}
    assert "sk-secret" not in ev.text
    assert api.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "done"


def test_history_list_and_item(api, tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    assert api.get("/api/v1/history").json() == []
    from ekte.web import history

    rid = history.save({
        "generated_at": "t", "target": {"base_url": "https://x/v1", "claimed_model": "m", "model": "m"},
        "mode": "check", "suite": "smoke", "verdict": {"risk_level": "clean", "overall_score": 95.0, "rating": "A"},
    })
    listed = api.get("/api/v1/history", params={"limit": 5}).json()
    assert len(listed) == 1
    assert {"id", "ts", "base_url", "claimed_model", "model", "mode", "suite", "risk_level", "score"} <= set(listed[0])
    assert listed[0]["id"] == rid
    assert "latency_p50_ms" not in listed[0]
    assert "latency_p50_ms" in api.get("/api/v1/history", params={"perf": "true"}).json()[0]
    item = api.get(f"/api/v1/history/{rid}")
    assert item.status_code == 200 and item.json()["verdict"]["overall_score"] == 95.0
    missing = api.get("/api/v1/history/999999")
    assert missing.status_code == 404 and missing.json() == {"error": "not found"}


def test_removed_endpoints_are_gone(api):
    for method, path in (
        ("post", "/api/audit/stream"), ("post", "/api/embed"), ("post", "/api/rerank"),
        ("get", "/api/history/trend"),
    ):
        kwargs = {"json": {}} if method == "post" else {}
        r = getattr(api, method)(path, **kwargs)
        assert r.status_code in (404, 405, 422), path
    assert not hasattr(__import__("ekte.web.history", fromlist=["x"]), "trend")


# ----- local-only protections apply to /api/v1/ as to every endpoint -------- #
V1_REQUESTS = (
    ("get", "/api/v1/history"),
    ("get", "/api/v1/history/1"),
    ("get", "/api/v1/jobs/x"),
    ("get", "/api/v1/jobs/x/events"),
    ("post", "/api/v1/jobs"),
)


@pytest.mark.parametrize(("method", "path"), V1_REQUESTS)
def test_v1_refuses_foreign_hosts(method, path):
    client = TestClient(create_app(), base_url="http://evil.example")
    r = getattr(client, method)(path)
    assert r.status_code == 421 and "error" in r.json()
    assert r.headers["x-ekte-api"] == "v1"


def test_v1_refuses_cross_site_and_cross_origin_writes(api):
    body = {"base_url": "https://x.example/v1", "model": "m"}
    r = api.post("/api/v1/jobs", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = api.post("/api/v1/jobs", json=body, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = api.post("/api/v1/jobs", content="x=1", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert r.headers["x-ekte-api"] == "v1"
