"""Evidence files: every raw request/response pair of a run (ekte.evidence)."""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
from pathlib import Path

import httpx
import jsonschema
import pytest
import zstandard
from fastapi.testclient import TestClient

from ekte import evidence, schemas
from ekte.clients import OpenAICompatibleClient
from ekte.clients import make_client as real_make_client
from ekte.config import AuditOptions
from ekte.evidence import EvidenceHeader, EvidenceLine, EvidenceWriter
from ekte.models import RedactedTarget, RequestSpec, TargetConfig
from ekte.utils.redact import REDACTED, REDACTED_KEY
from tests._helpers import BASE_URL, DEFAULT_MODEL, MockServer

KEY = "sk-test-secret-key-do-not-leak"
HEADER_SECRET = "hdr-secret-value-123456"


def _target(**kw) -> TargetConfig:
    return TargetConfig(
        name="target", kind="target", base_url=BASE_URL, api_key=KEY, model=DEFAULT_MODEL, **kw
    )


class _Chunked(httpx.AsyncByteStream):
    """A body that arrives in pieces, like a network stream."""

    def __init__(self, data: bytes, size: int = 64) -> None:
        self.data, self.size = data, size

    async def __aiter__(self):
        for i in range(0, len(self.data), self.size):
            await asyncio.sleep(0)
            yield self.data[i : i + self.size]


def _chunked(server: MockServer, *, gzip_json: bool = False, echo_key: bool = False) -> httpx.MockTransport:
    """The mock relay, its bodies streamed in chunks (optionally gzip-encoded,
    optionally echoing the key and setting a cookie)."""

    def handler(request: httpx.Request) -> httpx.Response:
        r = server.handler(request)
        headers = dict(r.headers)
        body = r.content
        if echo_key:
            headers["set-cookie"] = "session=abcdef123456; HttpOnly"
            for sep in (b'"content":"', b'"content": "'):
                body = body.replace(sep, sep + f"your key {KEY} ".encode())
        if gzip_json and "json" in headers.get("content-type", ""):
            body = gzip.compress(body)
            headers["content-encoding"] = "gzip"
        headers.pop("content-length", None)
        return httpx.Response(r.status_code, headers=headers, stream=_Chunked(body))

    return httpx.MockTransport(handler)


def _patch_clients(monkeypatch, transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(
        "ekte.runner.make_client", lambda config, **_: real_make_client(config, transport=transport)
    )


def _audit(path: Path | None, target: TargetConfig | None = None, suite: str = "standard", **kw):
    from ekte.runner import run_audit

    return asyncio.run(run_audit(target or _target(), AuditOptions(suite=suite), evidence=path, **kw))


def _plain(path: Path) -> str:
    with open(path, "rb") as fh:
        return zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True).read().decode()


# --------------------------------------------------------------------------- #
# The file a run writes
# --------------------------------------------------------------------------- #
def test_every_recorded_request_has_its_pair_under_its_seq(tmp_path, monkeypatch):
    server = MockServer()
    _patch_clients(monkeypatch, _chunked(server))
    path = tmp_path / "run.jsonl.zst"
    report = _audit(path, _target(headers={"X-Custom-Auth": HEADER_SECRET}))

    ref = report.evidence
    assert ref is not None and ref.file == "run.jsonl.zst" and ref.complete
    assert ref.sha256 == evidence.sha256_of(path) and ref.bytes == path.stat().st_size
    assert not path.with_name(path.name + ".part").exists()
    lines = list(evidence.iter_lines(path))
    head, rest = lines[0], lines[1:]
    assert head["type"] == "header" and head["run_id"] == ref.run_id
    assert head["started_at"] == report.started_at and head["target"]["api_key_fingerprint"]
    assert len(rest) == ref.exchanges == len(report.performance.requests)
    # (run, seq) finds the pair of every request record, attributed alike
    by_seq = {line["seq"]: line for line in rest}
    for rec in report.performance.requests:
        line = by_seq[rec.seq]
        assert (line["endpoint"], line["detector"], line["op"]) == (rec.endpoint, rec.detector, rec.op)
        assert line["response"]["status"] == rec.status_code
    # the request body is what was sent: the mock saw the same JSON
    sent = [json.loads(line["request"]["body"]["text"]) for line in rest if line["request"]["method"] == "POST"]
    assert sent == server.requests
    # ids are unique and in order
    assert [line["id"] for line in rest] == list(range(1, len(rest) + 1))


def test_no_secret_reaches_the_file(tmp_path, monkeypatch):
    _patch_clients(monkeypatch, _chunked(MockServer(), echo_key=True))
    path = tmp_path / "e.jsonl.zst"
    _audit(path, _target(headers={"X-Custom-Auth": HEADER_SECRET}), suite="smoke")
    text = _plain(path)
    assert KEY not in text and HEADER_SECRET not in text and "abcdef123456" not in text
    line = evidence.exchanges(path)[0]
    assert line["request"]["headers"]["authorization"] == REDACTED
    assert line["request"]["headers"]["x-custom-auth"] == REDACTED_KEY
    echoed = [x for x in evidence.exchanges(path) if REDACTED_KEY in (x["response"]["body"]["text"] or "")]
    assert echoed and all(x["response"]["headers"]["set-cookie"] == REDACTED for x in echoed)


def test_every_line_matches_the_published_schema(tmp_path, monkeypatch):
    _patch_clients(monkeypatch, _chunked(MockServer()))
    path = tmp_path / "e.jsonl.zst"
    _audit(path, suite="standard")
    schema = schemas.load("evidence")
    assert schema == schemas.evidence_schema()
    validator = jsonschema.Draft202012Validator(schema)
    for line in evidence.iter_lines(path):
        validator.validate(line)
        EvidenceLine.model_validate(line)  # and the producing models (extra forbidden)


def test_a_stream_keeps_its_chunk_timing(tmp_path, monkeypatch):
    _patch_clients(monkeypatch, _chunked(MockServer()))
    path = tmp_path / "e.jsonl.zst"
    report = _audit(path, suite="standard")
    streams = [
        x for x in evidence.exchanges(path)
        if "event-stream" in x["response"]["headers"].get("content-type", "")
    ]
    assert streams
    s = streams[0]
    chunks = s["response"]["chunks"]
    assert len(chunks) > 1
    offsets = [c[0] for c in chunks]
    received = [c[1] for c in chunks]
    assert offsets == sorted(offsets) and received == sorted(received)
    assert s["response"]["body"]["text"].startswith("data: ")
    assert "[DONE]" in s["response"]["body"]["text"]
    assert s["response"]["done_ms"] >= offsets[-1]
    # the line's start lies on the report's clock
    rec = next(r for r in report.performance.requests if r.seq == s["seq"])
    assert abs(s["start_ms"] - rec.start_ms) < 50


def test_an_encoded_body_is_stored_decoded(tmp_path, monkeypatch):
    _patch_clients(monkeypatch, _chunked(MockServer(), gzip_json=True))
    path = tmp_path / "e.jsonl.zst"
    _audit(path, suite="smoke")
    line = next(x for x in evidence.exchanges(path) if x["request"]["method"] == "POST")
    assert line["response"]["headers"]["content-encoding"] == "gzip"
    assert json.loads(line["response"]["body"]["text"])["object"] == "chat.completion"


def test_a_failed_call_keeps_its_error(tmp_path, monkeypatch):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_clients(monkeypatch, httpx.MockTransport(refuse))
    path = tmp_path / "e.jsonl.zst"
    _audit(path, suite="smoke")
    lines = evidence.exchanges(path)
    assert lines and all(x["response"] is None for x in lines)
    assert "ConnectError" in lines[0]["error"]


def test_no_evidence_means_no_file_and_no_capture(tmp_path, monkeypatch):
    _patch_clients(monkeypatch, _chunked(MockServer()))
    report = _audit(None, suite="smoke")
    assert report.evidence is None
    assert not list(tmp_path.iterdir())


def test_a_run_that_fails_leaves_no_file(tmp_path, monkeypatch):
    _patch_clients(monkeypatch, _chunked(MockServer()))

    async def boom(*a, **k):
        raise RuntimeError("detector blew up")

    monkeypatch.setattr("ekte.runner._assemble", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("ekte.runner.run_detector", boom)
    path = tmp_path / "e.jsonl.zst"
    with pytest.raises(RuntimeError):
        _audit(path, suite="smoke")
    assert not path.exists() and not path.with_name(path.name + ".part").exists()


# --------------------------------------------------------------------------- #
# Writer and reader
# --------------------------------------------------------------------------- #
def _header(run_id: str = "a" * 32) -> EvidenceHeader:
    return EvidenceHeader(
        tool_version="0", run_id=run_id, started_at="2026-01-01T00:00:00+00:00", mode="check",
        target=RedactedTarget(name="t", kind="target", base_url=BASE_URL, model="m"),
    )


def _capture(n: int, body: bytes = b'{"ok": true}') -> evidence.Capture:
    cap = evidence.Capture(
        method="POST", url=f"{BASE_URL}/chat/completions", request_headers={"content-type": "application/json"},
        request_body=json.dumps({"n": n}).encode(), started=time.perf_counter(),
    )
    cap.status, cap.complete, cap.done = 200, True, time.perf_counter()
    cap.raw += body
    cap.raw_total = len(body)
    return cap


def test_a_crashed_run_leaves_a_readable_partial_file(tmp_path):
    path = tmp_path / "x.jsonl.zst"
    w = EvidenceWriter(path, _header(), t0=time.perf_counter())
    for i in range(5):
        w.add([_capture(i)], seq=i, endpoint="target", detector="d", op="complete")
    # wait for the thread to write them, then "crash": no close()
    deadline = time.time() + 5
    while w._lines < 6 and time.time() < deadline:
        time.sleep(0.01)
    part = path.with_name(path.name + ".part")
    assert part.exists() and not path.exists()
    lines = list(evidence.iter_lines(part))
    assert [x.get("seq") for x in lines[1:]] == [0, 1, 2, 3, 4]
    w.abort()
    assert not part.exists()


def test_a_newer_major_schema_is_refused(tmp_path):
    path = tmp_path / "x.jsonl.zst"
    with open(path, "wb") as fh, zstandard.ZstdCompressor().stream_writer(fh) as z:
        z.write(b'{"type": "header", "schema_version": "2.0"}\n')
    with pytest.raises(ValueError, match="2.0"):
        list(evidence.iter_lines(path))


def test_binary_bodies_are_base64_and_huge_ones_are_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "MAX_BODY_BYTES", 16)
    path = tmp_path / "x.jsonl.zst"
    w = EvidenceWriter(path, _header(), t0=time.perf_counter())
    w.add([_capture(0, body=b"\xff\xd8\xff\xe0binary")], seq=None, endpoint="target", detector=None, op="image")
    w.add([_capture(1, body=b"x" * 40)], seq=1, endpoint="target", detector=None, op="complete")
    ref = w.close()
    assert ref.exchanges == 2
    first, second = evidence.exchanges(path)
    assert first["response"]["body"]["encoding"] == "base64" and first["seq"] is None
    assert second["response"]["body"]["truncated"] and len(second["response"]["body"]["text"]) == 16


def test_lookup_by_seq_and_id(tmp_path):
    path = tmp_path / "x.jsonl.zst"
    w = EvidenceWriter(path, _header(), t0=time.perf_counter())
    w.add([_capture(0), _capture(1)], seq=7, endpoint="target", detector="d", op="image")
    w.add([_capture(2)], seq=8, endpoint="baseline", detector="d", op="complete")
    w.close()
    assert [x["id"] for x in evidence.exchanges(path, seq=7)] == [1, 2]
    assert evidence.exchanges(path, line_id=3)[0]["endpoint"] == "baseline"
    assert evidence.exchanges(path, seq=99) == []
    rows = evidence.index(path)
    assert [r["seq"] for r in rows] == [7, 7, 8] and "request" not in rows[0]


def test_sweep_removes_only_stale_unclaimed_files(tmp_path):
    folder = tmp_path / evidence.DIR_NAME
    folder.mkdir()
    old = time.time() - evidence.STALE_SEC - 10
    names = {
        "kept.jsonl.zst": old, "orphan.jsonl.zst": old, "young.jsonl.zst": time.time(),
        "died.jsonl.zst.part": old, "other.txt": old,
    }
    for name, mtime in names.items():
        (folder / name).write_bytes(b"x")
        os.utime(folder / name, (mtime, mtime))
    assert evidence.sweep({"kept.jsonl.zst"}, base=tmp_path) == 2
    assert sorted(p.name for p in folder.iterdir()) == ["kept.jsonl.zst", "other.txt", "young.jsonl.zst"]


def test_stored_file_takes_bare_names_only(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    good = evidence.data_dir_path("b" * 32)
    good.write_bytes(b"x")
    assert evidence.stored_file(good.name) == good
    for bad in ("../x.jsonl.zst", "a/b.jsonl.zst", ".hidden.jsonl.zst", "x.txt", None, ""):
        assert evidence.stored_file(bad) is None


def test_the_switch_off(monkeypatch):
    monkeypatch.delenv(evidence.ENV_OFF, raising=False)
    assert evidence.default_on()
    for v in ("1", "true", "YES"):
        monkeypatch.setenv(evidence.ENV_OFF, v)
        assert not evidence.default_on()


# --------------------------------------------------------------------------- #
# Calls without a request record: the judge, the media auditor
# --------------------------------------------------------------------------- #
def test_unrecorded_calls_are_kept_without_a_seq(tmp_path):
    path = tmp_path / "x.jsonl.zst"

    async def go():
        w = EvidenceWriter(path, _header(), t0=time.perf_counter())
        async with OpenAICompatibleClient(_target(), transport=MockServer().transport) as c:
            c.endpoint, c.evidence = "judge", w
            out = await c.complete(RequestSpec(messages=[{"role": "user", "content": "hi"}], max_tokens=8))
        assert out.ok
        return await asyncio.to_thread(w.close)

    ref = asyncio.run(go())
    (line,) = evidence.exchanges(path)
    assert ref.exchanges == 1 and line["seq"] is None and line["endpoint"] == "judge"


def test_media_audit_writes_evidence(tmp_path, monkeypatch):
    import base64

    from ekte import media_audit

    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IHDR" + (64).to_bytes(4, "big") * 2).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": png}]})

    monkeypatch.setattr(
        media_audit, "make_client",
        lambda config, **_: real_make_client(config, transport=httpx.MockTransport(handler)),
    )
    path = tmp_path / "img.jsonl.zst"
    verdict = asyncio.run(media_audit.audit_image(_target(), size="64x64", claimed_sizes=[], evidence=path))
    assert verdict["evidence"]["exchanges"] == 2 and verdict["evidence"]["file"] == path.name
    lines = list(evidence.iter_lines(path))
    assert lines[0]["mode"] == "image" and {x["op"] for x in lines[1:]} == {"image"}
    assert KEY not in _plain(path)


# --------------------------------------------------------------------------- #
# History, the web API and the entry points
# --------------------------------------------------------------------------- #
@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(evidence.ENV_OFF, raising=False)
    _patch_clients(monkeypatch, _chunked(MockServer()))
    return tmp_path


def _saved_run(data: Path) -> tuple[int, Path]:
    from ekte.web import history

    path = evidence.data_dir_path(evidence.new_run_id())
    report = _audit(path, suite="smoke")
    rid = history.save(json.loads(report.model_dump_json()))
    return rid, path


def test_history_links_deletes_and_sweeps(data):
    from ekte.web import history

    rid, path = _saved_run(data)
    assert history.evidence_path(rid) == path
    other, path2 = _saved_run(data)
    history.delete(rid)
    assert not path.exists() and path2.exists()
    orphan = evidence.data_dir_path(evidence.new_run_id())
    orphan.write_bytes(b"x")
    old = time.time() - evidence.STALE_SEC - 1
    os.utime(orphan, (old, old))
    os.utime(path2, (old, old))
    assert history.sweep_evidence() == 1
    assert path2.exists() and not orphan.exists()
    history.clear()
    assert not path2.exists()


def test_a_report_naming_a_foreign_file_links_nothing(data, tmp_path_factory):
    from ekte.web import history

    elsewhere = tmp_path_factory.mktemp("cli") / "mine.jsonl.zst"
    report = _audit(elsewhere, suite="smoke")
    rid = history.save(json.loads(report.model_dump_json()))
    assert history.evidence_path(rid) is None
    history.delete(rid)
    assert elsewhere.exists()  # never touched: it is not the data directory's


def test_api_serves_the_file_the_listing_and_the_pairs(data):
    from ekte.web.server import create_app

    rid, path = _saved_run(data)
    with TestClient(create_app(), base_url="http://localhost") as client:
        f = client.get(f"/api/v1/history/{rid}/evidence")
        assert f.status_code == 200 and f.content == path.read_bytes()
        assert f.headers["content-type"] == "application/zstd"
        listing = client.get(f"/api/v1/history/{rid}/evidence/exchanges").json()
        assert listing["verified"] is True and listing["exchanges"]
        assert "request" not in listing["exchanges"][0]
        seq = listing["exchanges"][0]["seq"]
        pairs = client.get(f"/api/v1/history/{rid}/evidence/exchanges", params={"seq": seq}).json()
        assert pairs["exchanges"][0]["request"]["method"]
        one = client.get(f"/api/v1/history/{rid}/evidence/exchanges", params={"id": 1}).json()
        assert one["exchanges"][0]["id"] == 1
        det = listing["exchanges"][0]["detector"]
        only = client.get(f"/api/v1/history/{rid}/evidence/exchanges", params={"detector": det}).json()
        assert {x["detector"] for x in only["exchanges"]} == {det}
        assert client.get(f"/api/v1/history/{rid}/evidence/exchanges", params={"id": 999}).status_code == 404
        assert client.get("/api/v1/history/999/evidence").status_code == 404
        # tampered with: still served, flagged as not the file the report names
        path.write_bytes(path.read_bytes() + zstandard.ZstdCompressor().compress(b""))
        assert client.get(f"/api/v1/history/{rid}/evidence/exchanges").json()["verified"] is False


def test_api_says_when_a_run_kept_no_evidence(data):
    from ekte.web import history
    from ekte.web.server import create_app

    rid = history.save(json.loads(_audit(None, suite="smoke").model_dump_json()))
    with TestClient(create_app(), base_url="http://localhost") as client:
        r = client.get(f"/api/v1/history/{rid}/evidence")
        assert r.status_code == 404 and "no evidence" in r.json()["error"]


def _job_report(client, body) -> dict:
    created = client.post("/api/v1/jobs", json=body)
    assert created.status_code == 200, created.text
    r = client.get(f"/api/v1/jobs/{created.json()['id']}/events")
    events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
    return next(e for e in events if e["type"] == "report")


@pytest.mark.parametrize("keep", [True, False])
def test_web_audits_keep_evidence_unless_asked_not_to(data, keep):
    from ekte.web import history
    from ekte.web.server import create_app

    body = {"base_url": BASE_URL, "model": DEFAULT_MODEL, "api_key": KEY, "suite": "smoke"}
    if not keep:
        body["evidence"] = False
    with TestClient(create_app(), base_url="http://localhost") as client:
        ev = _job_report(client, body)
    assert (ev["report"].get("evidence") is not None) is keep
    assert (history.evidence_path(ev["report_id"]) is not None) is keep


def test_the_server_switch_turns_evidence_off(data, monkeypatch):
    from ekte.web.server import create_app

    monkeypatch.setenv(evidence.ENV_OFF, "1")
    with TestClient(create_app(), base_url="http://localhost") as client:
        ev = _job_report(client, {"base_url": BASE_URL, "model": DEFAULT_MODEL, "suite": "smoke"})
    assert ev["report"].get("evidence") is None


def test_monitors_store_and_patch_their_evidence_setting(data):
    from ekte.web import watches
    from ekte.web.server import create_app

    with TestClient(create_app(), base_url="http://localhost") as client:
        made = client.post("/api/watches", json={
            "base_url": BASE_URL, "model": DEFAULT_MODEL, "suite": "smoke", "evidence": False,
        })
        wid = made.json()["id"]
        assert watches.get(wid)["evidence"] is False
        assert client.patch(f"/api/watches/{wid}", json={"evidence": "yes"}).status_code == 400
        assert client.patch(f"/api/watches/{wid}", json={"evidence": True}).status_code == 200
        assert watches.get(wid)["evidence"] is True
        listed = next(w for w in client.get("/api/watches").json() if w["id"] == wid)
        assert listed["evidence"] is True


@pytest.mark.parametrize("keep", [True, False])
def test_a_monitor_run_follows_its_setting(data, keep):
    from ekte.web import history, server, watches

    wid = watches.create({"base_url": BASE_URL, "model": DEFAULT_MODEL, "suite": "smoke", "evidence": keep})
    asyncio.run(server._run_one_watch_inner(watches.get(wid)))
    rid = history.recent(1)[0]["id"]
    assert (history.evidence_path(rid) is not None) is keep


def test_cli_check_writes_evidence_into_a_directory(data, tmp_path_factory):
    from typer.testing import CliRunner

    from ekte.cli import app

    out = tmp_path_factory.mktemp("ev")
    res = CliRunner().invoke(app, [
        "check", "--base-url", BASE_URL, "--model", DEFAULT_MODEL, "--api-key", KEY,
        "--suite", "smoke", "--json", "--evidence", str(out),
    ])
    assert res.exit_code in (0, 1), res.output
    report = json.loads(res.output)
    (written,) = list(out.iterdir())
    assert written.name == report["evidence"]["file"] == f"{report['evidence']['run_id']}.jsonl.zst"
    assert report["evidence"]["sha256"] == evidence.sha256_of(written)


def test_cli_refuses_an_evidence_path_in_a_missing_directory(data, tmp_path):
    from typer.testing import CliRunner

    from ekte.cli import app

    res = CliRunner().invoke(app, [
        "check", "--base-url", BASE_URL, "--model", DEFAULT_MODEL, "--suite", "smoke",
        "--evidence", str(tmp_path / "nope" / "e.jsonl.zst"),
    ])
    assert res.exit_code == 2 and "does not" in res.output and "--evidence" in res.output


@pytest.mark.parametrize("flag", [[], ["--no-evidence"]])
def test_cli_watch_keeps_evidence_unless_told_not_to(data, flag):
    from typer.testing import CliRunner

    from ekte.cli import app
    from ekte.web import history

    res = CliRunner().invoke(app, [
        "watch", "--base-url", BASE_URL, "--model", DEFAULT_MODEL, "--suite", "smoke", "--once", *flag,
    ])
    assert res.exit_code == 0, res.output
    rid = history.recent(1)[0]["id"]
    assert (history.evidence_path(rid) is not None) is (not flag)


def test_embedding_and_rerank_runs_follow_the_history_rule(data, monkeypatch):
    from ekte.embed_audit import evidence_path

    mine = data / "mine.jsonl.zst"
    assert evidence_path(mine, save=False) == mine  # an explicit path always wins
    assert evidence_path(None, save=False) is None  # not saved: nothing kept
    assert evidence_path(False, save=True) is None  # --no-evidence
    kept = evidence_path(None, save=True)
    assert kept is not None and kept.parent.name == evidence.DIR_NAME
    monkeypatch.setenv(evidence.ENV_OFF, "1")
    assert evidence_path(None, save=True) is None
    assert evidence_path(True, save=True) is not None  # asked for explicitly
