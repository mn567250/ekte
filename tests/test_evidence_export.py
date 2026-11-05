"""Findings name the requests they rest on; evidence exports (HAR, curl, JSON)."""

from __future__ import annotations

import asyncio
import json
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

from ekte import evidence
from ekte.clients import OpenAICompatibleClient
from ekte.models import RequestSpec, TargetConfig
from tests._helpers import BASE_URL, DEFAULT_MODEL, MockServer, run_subprocess
from tests.test_evidence import KEY, _audit, _chunked, _patch_clients


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A standard audit of the mock relay that kept its evidence."""
    _patch_clients(monkeypatch, _chunked(MockServer()))
    path = tmp_path / "e.jsonl.zst"
    return _audit(path, suite="standard"), path


# --------------------------------------------------------------------------- #
# Findings name their requests
# --------------------------------------------------------------------------- #
def test_findings_name_requests_of_their_own_detector(run):
    report, path = run
    records = {r.seq: r for r in report.performance.requests}
    in_file = {x["seq"] for x in evidence.exchanges(path)}
    named = 0
    for det in report.detectors:
        for f in det.findings:
            if f.evidence_seqs is None:
                continue
            named += 1
            for seq in f.evidence_seqs:
                assert seq in in_file, (f.id, seq)
                assert records[seq].detector == det.id, (f.id, seq)
    assert named > 10  # most findings of a standard run say which requests


def test_a_finding_from_configuration_names_no_request(run):
    report, _ = run
    tls = next(f for d in report.detectors for f in d.findings if f.id == "security.tls")
    assert tls.evidence_seqs == []


def test_a_finding_from_one_call_names_exactly_that_call(run):
    report, path = run
    det = next(d for d in report.detectors if d.id == "streaming")
    seqs = {s for f in det.findings for s in (f.evidence_seqs or [])}
    assert len(seqs) == 1
    (line,) = evidence.exchanges(path, seq=seqs.pop())
    assert line["request"]["method"] == "POST" and '"stream":true' in line["request"]["body"]["text"]


def test_an_outcome_lists_every_attempt_of_a_repeated_request(tmp_path):
    from ekte.perf.recorder import RequestRecorder

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {
                "message": "Unsupported parameter: 'temperature' is not supported with this model.",
                "param": "temperature"}})
        return MockServer().handler(request)

    async def go():
        c = OpenAICompatibleClient(
            TargetConfig(name="t", kind="target", base_url=BASE_URL, api_key=KEY, model=DEFAULT_MODEL),
            transport=httpx.MockTransport(handler),
        )
        async with c:
            c.recorder = RequestRecorder()
            return await c.complete(RequestSpec(messages=[{"role": "user", "content": "hi"}], temperature=0.5))

    out = asyncio.run(go())
    assert out.ok and calls["n"] == 2 and out.seqs == [0, 1]


def test_evidence_seqs_accepts_outcomes_numbers_and_lists():
    from ekte.detectors.scale import evidence_seqs
    from ekte.models import CompletionOutcome

    a, b = CompletionOutcome(seqs=[3, 1]), CompletionOutcome(seqs=[1])
    assert evidence_seqs(None) is None
    assert evidence_seqs([]) == []
    assert evidence_seqs([a, [b, 7], None, True]) == [1, 3, 7]


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #
def test_har_has_one_entry_per_exchange(run):
    report, path = run
    har = evidence.export_har(path)
    entries = har["log"]["entries"]
    assert har["log"]["version"] == "1.2" and len(entries) == report.evidence.exchanges
    e = next(x for x in entries if x["request"]["method"] == "POST")
    assert e["request"]["postData"]["text"].startswith("{")
    assert e["response"]["status"] == 200 and e["response"]["content"]["text"]
    assert e["startedDateTime"].startswith(report.started_at[:10])
    assert e["timings"]["wait"] >= 0 and e["_ekte"]["seq"] is not None
    only = evidence.export_har(path, [e["_ekte"]["seq"]])["log"]["entries"]
    assert [x["_ekte"]["seq"] for x in only] == [e["_ekte"]["seq"]]


def test_curl_script_resends_without_the_key(run):
    _, path = run
    script = evidence.export_curl(path)
    assert KEY not in script and 'authorization: Bearer ${EKTE_API_KEY}' in script
    assert script.count("curl -sS -X") == len(evidence.exchanges(path))
    assert "content-length" not in script and "--data-binary @- <<'EKTE_BODY'" in script
    if shutil.which("sh"):
        run_subprocess(["sh", "-n"], input=script, text=True, check=True)


def test_curl_picks_a_delimiter_the_body_does_not_contain(tmp_path):
    import time

    from tests.test_evidence import _capture, _header

    path = tmp_path / "x.jsonl.zst"
    w = evidence.EvidenceWriter(path, _header(), t0=time.perf_counter())
    cap = _capture(0)
    cap.request_body = b"line\nEKTE_BODY\nmore"
    w.add([cap], seq=0, endpoint="target", detector="d", op="complete")
    w.close()
    script = evidence.export_curl(path)
    assert "<<'EKTE_BODY_'" in script and script.rstrip().endswith("echo")


def test_json_export_is_the_file_as_one_document(run):
    report, path = run
    doc = evidence.export_json(path)
    assert doc["header"]["run_id"] == report.evidence.run_id
    assert len(doc["exchanges"]) == report.evidence.exchanges


def test_cli_exports_a_file_or_a_saved_run(run, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from ekte.cli import app
    from ekte.web import history

    report, path = run
    res = CliRunner().invoke(app, ["evidence-export", str(path), "--as", "json"])
    assert res.exit_code == 0 and json.loads(res.output)["header"]["run_id"] == report.evidence.run_id

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path / "data"))
    saved = evidence.data_dir_path(report.evidence.run_id)
    shutil.copy(path, saved)
    rid = history.save(json.loads(report.model_dump_json()) | {"evidence": {**report.evidence.model_dump(), "file": saved.name}})
    out = tmp_path / "again.sh"
    res = CliRunner().invoke(app, ["evidence-export", str(rid), "--as", "curl", "--seq", "0", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert out.read_text().count("curl -sS -X") == 1

    assert CliRunner().invoke(app, ["evidence-export", str(path), "--as", "xml"]).exit_code == 2
    assert CliRunner().invoke(app, ["evidence-export", str(tmp_path / "nope.jsonl.zst")]).exit_code == 2
    assert CliRunner().invoke(app, ["evidence-export", "4242"]).exit_code == 2


def test_api_exports(tmp_path, monkeypatch):
    from ekte.web import history
    from ekte.web.server import create_app

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    _patch_clients(monkeypatch, _chunked(MockServer()))
    path = evidence.data_dir_path(evidence.new_run_id())
    report = _audit(path, suite="smoke")
    rid = history.save(json.loads(report.model_dump_json()))
    with TestClient(create_app(), base_url="http://localhost") as client:
        base = f"/api/v1/history/{rid}/evidence/export"
        har = client.get(base)
        assert har.status_code == 200 and har.json()["log"]["entries"]
        assert f'ekte-evidence-{rid}.har' in har.headers["content-disposition"]
        sh = client.get(base, params={"format": "curl", "seq": [0, 1]})
        assert sh.status_code == 200 and sh.text.count("curl -sS -X") == 2
        assert "seq0-1.sh" in sh.headers["content-disposition"]
        assert client.get(base, params={"format": "json"}).json()["exchanges"]
        assert client.get(base, params={"format": "xml"}).status_code == 400
        assert client.get("/api/v1/history/999/evidence/export").status_code == 404


def test_the_probe_failure_finding_names_the_failed_requests(tmp_path, monkeypatch):
    import itertools

    from ekte.perf.recorder import current_detector

    server, n = MockServer(), itertools.count()

    def handler(request: httpx.Request) -> httpx.Response:
        if current_detector() == "performance" and next(n) % 5 == 2:
            if next(n) % 2:
                return httpx.Response(502, text="<html><h1>502 Bad Gateway</h1></html>")
            raise httpx.ProxyError("502 Bad Gateway from the proxy", request=request)
        return server.handler(request)

    _patch_clients(monkeypatch, httpx.MockTransport(handler))
    report = _audit(tmp_path / "e.jsonl.zst", suite="deep")
    perf = next(d for d in report.detectors if d.id == "performance")
    errors = next(f for f in perf.findings if f.id == "performance.errors")
    records = {r.seq: r for r in report.performance.requests}
    # exactly the failures the finding counts: failed probe completions (not
    # the round-trip pings or the burst, which it does not count)
    assert errors.evidence["errors"] == len(errors.evidence_seqs) > 0
    for seq in errors.evidence_seqs:
        rec = records[seq]
        assert rec.detector == "performance" and rec.op == "complete" and not rec.ok
    assert any(records[s].status_code == 502 for s in errors.evidence_seqs)
    # a refused proxy tunnel never reached the relay: repeated, then (if it
    # failed again) counted apart, never as the relay's error
    proxy = [r for r in records.values() if r.error_type == "ProxyError"]
    assert proxy and all(r.error_class == "network" for r in proxy)
    assert not any(records[s].error_type == "ProxyError" for s in errors.evidence_seqs)
