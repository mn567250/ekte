"""Re-scoring a recorded run from its evidence file (ekte.replay)."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from ekte import evidence, replay
from ekte.clients import make_client as real_make_client
from ekte.config import AuditOptions
from ekte.models import EvidenceRef, Status
from ekte.perf.recorder import REPLAY_MISS_SEQ
from tests._helpers import BASE_URL, MockServer, unwrapped
from tests.test_evidence import _chunked, _target

DISHONEST = {
    "served_model": "gpt-4o-mini", "self_identity": "I am GPT-4o mini, made by OpenAI.",
    "fake_stream": True, "inflate_usage_factor": 1.6, "truncate_above_tokens": 120_000,
}


def _record(monkeypatch, path, suite="standard", server=None, **kw):
    """Run an audit against the mock relay keeping its evidence; afterwards the
    clients are real again, so a replay can only answer from the file."""
    from ekte.runner import run_audit

    transport = _chunked(server or MockServer())
    monkeypatch.setattr(
        "ekte.runner.make_client", lambda config, **_: real_make_client(config, transport=transport)
    )
    report = asyncio.run(run_audit(_target(), AuditOptions(suite=suite), evidence=path, **kw))
    monkeypatch.setattr("ekte.runner.make_client", real_make_client)
    return json.loads(report.model_dump_json())


def _scores(report: dict) -> dict:
    return {d["id"]: (d["status"], d["score"]) for d in report["detectors"]}


@pytest.mark.parametrize("server", [MockServer(), MockServer(**DISHONEST)], ids=["honest", "dishonest"])
def test_a_replay_reproduces_the_verdict(tmp_path, monkeypatch, server):
    path = tmp_path / "e.jsonl.zst"
    before = _record(monkeypatch, path, suite="deep", server=server)
    after = json.loads(asyncio.run(replay.rescore(before, path, report_id=7)).model_dump_json())
    assert _scores(after) == _scores(before)
    assert after["verdict"]["risk_level"] == before["verdict"]["risk_level"]
    assert after["verdict"]["overall_score"] == before["verdict"]["overall_score"]
    r = after["rescored_from"]
    assert r["missing"] == {} and r["unused"] == 0 and r["replayed"] == before["evidence"]["exchanges"]
    assert r["report_id"] == 7 and r["run_id"] == before["evidence"]["run_id"]
    # as the original says: protocol auto-detected, profile not pinned by a monitor
    assert after["target"]["api_auto"] is before["target"]["api_auto"]
    assert after["knowledge"]["pinned"] is before["knowledge"]["pinned"]
    assert after["knowledge"]["profile_hash"] == before["knowledge"]["profile_hash"]
    # the same file is the evidence: records and findings keep the recorded seqs
    assert after["evidence"] == before["evidence"]
    assert sorted(x["seq"] for x in after["performance"]["requests"]) == sorted(
        x["seq"] for x in before["performance"]["requests"])
    in_file = {x["seq"] for x in evidence.exchanges(path)}
    for d in after["detectors"]:
        for f in d["findings"]:
            assert set(f.get("evidence_seqs") or []) <= in_file


def test_a_question_the_recorded_run_never_asked_is_inconclusive(tmp_path, monkeypatch):
    from ekte.runner import run_audit

    path = tmp_path / "e.jsonl.zst"
    before = _record(monkeypatch, path)
    lines = [x for x in evidence.exchanges(path) if x["detector"] != "billing"]
    rp = replay.Replay(lines, ref=EvidenceRef(**before["evidence"]))
    after = asyncio.run(run_audit(_target(), AuditOptions(suite="standard"), replay=rp))
    billing = next(d for d in after.detectors if d.id == "billing")
    assert billing.status == Status.INCONCLUSIVE and billing.score is None
    missing = next(f for f in billing.findings if f.id == replay.MISSING_ID)
    assert missing.evidence["missing_requests"] == 1 and missing.evidence_seqs == []
    assert after.rescored_from.missing == {"billing": 1}
    assert all(r.seq >= REPLAY_MISS_SEQ for r in after.performance.requests if r.detector == "billing")
    others = {k: v for k, v in _scores(json.loads(after.model_dump_json())).items() if k != "billing"}
    assert others == {k: v for k, v in _scores(before).items() if k != "billing"}


def test_the_relay_is_never_contacted(tmp_path, monkeypatch):
    path = tmp_path / "e.jsonl.zst"
    before = _record(monkeypatch, path, suite="smoke")

    def explode(request):  # what a network transport would be asked
        raise AssertionError(f"replay reached the network: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", explode)
    after = asyncio.run(replay.rescore(before, path))
    assert after.rescored_from.replayed == before["evidence"]["exchanges"]


def test_recorded_timing_is_replayed():
    line = {
        "endpoint": "target", "seq": 3,
        "request": {"method": "POST", "url": f"{BASE_URL}/x", "body": {"text": "{}"}},
        "response": {"status": 200, "headers": {"content-type": "text/plain"},
                     "body": {"text": "abcdef"}, "chunks": [[40.0, 3], [90.0, 6]]},
    }
    rp = replay.Replay([line], ref=EvidenceRef(run_id="r", file="f", sha256="0"))

    async def go():
        async with httpx.AsyncClient(transport=rp.transport("target")) as c:
            t0 = time.perf_counter()
            arrivals, body = [], b""
            async with c.stream("POST", f"{BASE_URL}/x", content=b"{}") as r:
                async for chunk in r.aiter_raw():
                    arrivals.append((time.perf_counter() - t0) * 1000)
                    body += chunk
            return arrivals, body

    arrivals, body = asyncio.run(go())
    assert body == b"abcdef" and len(arrivals) == 2
    assert arrivals[0] >= 35 and arrivals[1] >= 85


def test_matching_masks_probe_ids_and_key_order():
    a = replay.request_key("target", "post", "https://r/v1/chat", '{"b":1,"a":"id 0123456789abcdef"}')
    b = replay.request_key("target", "POST", "https://other/v1/chat?x=1", '{"a": "id fedcba9876543210", "b": 1}')
    assert a == b
    assert a != replay.request_key("baseline", "POST", "https://r/v1/chat", '{"b":1,"a":"id 0123456789abcdef"}')


def test_a_recorded_failure_fails_again():
    line = {"endpoint": "target", "seq": 0, "request": {"method": "GET", "url": f"{BASE_URL}/models", "body": {}},
            "response": None, "error": "ConnectError: refused"}
    rp = replay.Replay([line], ref=EvidenceRef(run_id="r", file="f", sha256="0"))

    async def go():
        async with httpx.AsyncClient(transport=rp.transport("target")) as c:
            await c.get(f"{BASE_URL}/models")

    with pytest.raises(httpx.ConnectError, match="refused"):
        asyncio.run(go())
    with pytest.raises(replay.ReplayMiss):
        asyncio.run(go())  # asked twice, recorded once


def test_only_the_named_file_is_replayed(tmp_path, monkeypatch):
    path = tmp_path / "e.jsonl.zst"
    report = _record(monkeypatch, path, suite="smoke")
    with pytest.raises(ValueError, match="kept no evidence"):
        replay.check({**report, "evidence": None}, path)
    with pytest.raises(ValueError, match="SHA-256"):
        replay.check({**report, "evidence": {**report["evidence"], "sha256": "0" * 64}}, path)


# --------------------------------------------------------------------------- #
# History, the API and the command line
# --------------------------------------------------------------------------- #
@pytest.fixture
def saved(tmp_path, monkeypatch):
    from ekte.web import history

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(evidence.ENV_OFF, raising=False)
    path = evidence.data_dir_path(evidence.new_run_id())
    report = _record(monkeypatch, path, suite="smoke")
    return history.save(report), path


def test_a_rescored_run_shares_its_original_file(saved):
    from ekte.web import history

    rid, path = saved
    report = history.get(rid)
    new = asyncio.run(replay.rescore(report, path, report_id=rid))
    rid2 = history.save(json.loads(new.model_dump_json()))
    assert history.evidence_path(rid2) == path
    history.delete(rid)
    assert path.exists()  # the re-score still names it
    history.delete(rid2)
    assert not path.exists()


def test_api_queues_a_rescore_as_a_job(saved):
    from ekte.web import history
    from ekte.web.server import create_app

    rid, _ = saved
    with TestClient(create_app(), base_url="http://localhost") as client:
        created = client.post(f"/api/v1/history/{rid}/rescore")
        assert created.status_code == 200, created.text
        job = created.json()
        assert job["rescore_of"] == rid
        r = client.get(f"/api/v1/jobs/{job['id']}/events")
        events = [json.loads(x[5:]) for x in r.text.splitlines() if x.startswith("data:")]
        ev = next(e for e in events if e["type"] == "report")
        assert ev["report"]["rescored_from"]["report_id"] == rid
        assert history.get(ev["report_id"])["rescored_from"]["missing"] == {}
        assert client.post("/api/v1/history/999/rescore").status_code == 404
        plain = history.save({**history.get(rid), "evidence": None})
        assert client.post(f"/api/v1/history/{plain}/rescore").status_code == 409


def test_cli_rescores_a_saved_run_or_a_report_file(saved, tmp_path):
    from typer.testing import CliRunner

    from ekte.cli import app
    from ekte.web import history

    rid, path = saved
    res = CliRunner().invoke(app, ["rescore", str(rid)])
    assert res.exit_code == 0, res.output
    out = unwrapped(res.output)  # one long line, wrapped by Rich
    assert "requests replayed" in out and "saved as run" in out
    assert history.recent(1)[0]["id"] != rid

    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(history.get(rid)), encoding="utf-8")
    res = CliRunner().invoke(app, ["rescore", str(report_file), "--evidence", str(path), "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["rescored_from"]["replayed"] > 0

    assert CliRunner().invoke(app, ["rescore", str(report_file)]).exit_code == 2  # no --evidence
    assert CliRunner().invoke(app, ["rescore", "4242"]).exit_code == 2


def test_api_errors_carry_fixed_texts_only(saved):
    # CodeQL py/stack-trace-exposure: no exception text in a response
    import zstandard

    from ekte.web import history
    from ekte.web.server import create_app

    rid, path = saved
    with TestClient(create_app(), base_url="http://localhost") as client:
        # a replay refused for a fixed reason (the file was changed)
        path.write_bytes(path.read_bytes() + zstandard.ZstdCompressor().compress(b""))
        r = client.post(f"/api/v1/history/{rid}/rescore")
        assert r.status_code == 409 and r.json() == {"error": replay.HASH_DIFFERS}
        # a file of a newer major schema version
        with open(path, "wb") as fh, zstandard.ZstdCompressor().stream_writer(fh) as z:
            z.write(b'{"type": "header", "schema_version": "9.0"}\n')
        for url in (f"/api/v1/history/{rid}/evidence/exchanges",
                    f"/api/v1/history/{rid}/evidence/export"):
            r = client.get(url)
            assert r.status_code == 409
            assert r.json() == {"error": evidence.EvidenceVersionError.PUBLIC}
            assert "9.0" not in r.text
        assert history.get(rid) is not None


class _FlakyProxy(MockServer):
    """The mock relay behind a proxy that refuses every ``every``-th tunnel."""

    def __init__(self, every: int = 7) -> None:
        super().__init__()
        self.every, self.n = every, 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.n += 1
        if self.n % self.every == 0:
            raise httpx.ProxyError("502 Bad Gateway from the proxy", request=request)
        return super().handler(request)


def test_a_repeated_network_failure_replays_with_its_repeat(tmp_path, monkeypatch):
    # the recorded run repeated each refused tunnel; the replay repeats exactly
    # those, so every repeat meets the recorded repeat's answer
    monkeypatch.delenv("EKTE_NON_RELAY_RETRIES", raising=False)
    path = tmp_path / "e.jsonl.zst"
    before = _record(monkeypatch, path, suite="deep", server=_FlakyProxy())
    recs = before["performance"]["requests"]
    lost = [r for r in recs if r["error_type"] == "ProxyError"]
    assert lost and all(r["error_class"] == "network" and r["retried"] for r in lost)
    assert before["performance"]["target"]["errors"] == 0
    after = json.loads(asyncio.run(replay.rescore(before, path)).model_dump_json())
    assert _scores(after) == _scores(before)
    r = after["rescored_from"]
    assert r["missing"] == {} and r["unused"] == 0
    assert [x["error_type"] for x in after["performance"]["requests"] if not x["ok"]] == [
        x["error_type"] for x in recs if not x["ok"]]


def test_a_recorded_failure_keeps_its_class():
    for error, exc, cls in [("ProxyError: refused tunnel", httpx.ProxyError, "network"),
                            ("ReadTimeout: slow", httpx.ReadTimeout, "relay"),
                            ("no response", httpx.ConnectError, "network")]:
        err = replay.recorded_error(error, httpx.Request("GET", f"{BASE_URL}/models"))
        assert type(err) is exc
        from ekte.errorclass import classify_exception

        assert classify_exception(err) == cls


def test_an_unrepeated_recorded_failure_is_not_repeated_in_the_replay(tmp_path, monkeypatch):
    # a run recorded before repeats existed (or with them off): the replay must
    # not ask again, or it would find no recorded answer
    monkeypatch.setenv("EKTE_NON_RELAY_RETRIES", "0")
    path = tmp_path / "e.jsonl.zst"
    before = _record(monkeypatch, path, suite="standard", server=_FlakyProxy(every=5))
    assert not any(r["retried"] for r in before["performance"]["requests"])
    monkeypatch.setenv("EKTE_NON_RELAY_RETRIES", "3")
    after = json.loads(asyncio.run(replay.rescore(before, path)).model_dump_json())
    assert after["rescored_from"]["missing"] == {} and _scores(after) == _scores(before)
