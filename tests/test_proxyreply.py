"""An HTTPS proxy that refuses the tunnel: its answer is kept (ekte.proxyreply).

A local asyncio server plays the proxy: it answers ``CONNECT`` with an error
status, headers and an HTML error page, the way Squid answers when it cannot
reach the target (``ERR_CONNECT_FAIL``). The real client goes through it via
``HTTPS_PROXY``.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from ekte import errorclass, evidence, proxyreply
from ekte.clients import OpenAICompatibleClient
from ekte.evidence import EvidenceHeader, EvidenceWriter
from ekte.models import RedactedTarget, RequestSpec, TargetConfig
from ekte.perf.recorder import RequestRecorder

SECRET = "sk-proxyreply-test-0123456789abcdef"
PAGE = (b"<html><body>ERR_CONNECT_FAIL (110) Connection timed out "
        b"while trying 203.0.113.7</body></html>")


class FakeProxy:
    """Answers every CONNECT with ``status``; the body in one or two writes."""

    def __init__(self, status: int = 503, reason: bytes = b"Service Unavailable", *,
                 body: bytes = PAGE, split: bool = False, chunked: bool = False,
                 no_length: bool = False, delay: float = 0.0) -> None:
        self.status, self.reason, self.body = status, reason, body
        self.split, self.chunked, self.no_length, self.delay = split, chunked, no_length, delay
        self.connects: list[bytes] = []
        self.server: asyncio.base_events.Server | None = None

    async def __aenter__(self) -> FakeProxy:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        self.connects.append(head)
        if self.delay:
            await asyncio.sleep(self.delay)
        lines = [b"HTTP/1.1 %d %s" % (self.status, self.reason), b"Server: squid",
                 b"X-Squid-Error: ERR_CONNECT_FAIL 110", b"Content-Type: text/html",
                 b"X-Echo-Key: " + SECRET.encode()]
        if self.chunked:
            lines.append(b"Transfer-Encoding: chunked")
            half = len(self.body) // 2
            payload = b"".join(b"%x\r\n%s\r\n" % (len(p), p) for p in (self.body[:half], self.body[half:]))
            payload += b"0\r\n\r\n"
        else:
            if not self.no_length:
                lines.append(b"Content-Length: %d" % len(self.body))
            payload = self.body
        head_bytes = b"\r\n".join(lines) + b"\r\n\r\n"
        try:
            if self.split:
                writer.write(head_bytes)
                await writer.drain()
                await asyncio.sleep(0.2)
                writer.write(payload)
            else:
                writer.write(head_bytes + payload)
            await writer.drain()
            if self.no_length:
                writer.close()
                return
            await asyncio.sleep(0.5)
        except ConnectionError:
            pass
        writer.close()


def _client(rec: RequestRecorder | None = None) -> OpenAICompatibleClient:
    client = OpenAICompatibleClient(TargetConfig(
        kind="target", name="t", base_url="https://relay.example/v1", api_key=SECRET,
        model="gpt-4o", timeout_sec=30,
    ))
    client.recorder = rec
    return client


def _spec() -> RequestSpec:
    return RequestSpec(messages=[{"role": "user", "content": "hi"}], max_tokens=8)


@pytest.fixture
def via_proxy(monkeypatch):
    def use(proxy: FakeProxy) -> None:
        for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("HTTPS_PROXY", proxy.url)
    return use


def _header() -> EvidenceHeader:
    return EvidenceHeader(
        tool_version="test", run_id="r1", started_at="2026-01-01T00:00:00Z", mode="check",
        target=RedactedTarget(name="t", kind="target", base_url="https://relay.example/v1", model="gpt-4o"),
    )


# -- the request record ------------------------------------------------------ #
async def test_a_refused_tunnel_keeps_the_proxys_status_and_wait(via_proxy):
    async with FakeProxy(503, delay=0.3) as proxy:
        via_proxy(proxy)
        rec = RequestRecorder()
        async with _client(rec) as client:
            out = await client.complete(_spec())
    assert not out.ok and out.error_type == "ProxyError" and out.error_class == errorclass.NETWORK
    assert out.proxy_status == 503
    assert out.proxy_wait_ms is not None and out.proxy_wait_ms >= 250
    assert "CONNECT relay.example:443" in (out.error_message or "")
    # repeated once (a network failure), as before; both attempts keep it
    assert [r.retried for r in rec.records] == [True, False]
    assert all(r.proxy_status == 503 and r.error_class == "network" for r in rec.records)
    assert len(proxy.connects) == 2


async def test_without_a_recorder_the_outcome_is_as_before(via_proxy):
    async with FakeProxy(407, b"Proxy Authentication Required") as proxy:
        via_proxy(proxy)
        async with _client() as client:
            out = await client.complete(_spec())
    assert out.error_type == "ProxyError" and out.error_class == errorclass.NETWORK
    assert out.proxy_status is None  # no trace without a recorder or evidence


async def test_a_successful_request_keeps_no_proxy_fields():
    from tests._helpers import MockServer

    server = MockServer()
    rec = RequestRecorder()
    client = OpenAICompatibleClient(TargetConfig(
        kind="target", name="t", base_url="https://relay.example/v1", api_key="k", model="gpt-4o",
    ), transport=server.transport)
    client.recorder = rec
    out = await client.complete(_spec())
    assert out.ok and out.proxy_status is None and rec.records[0].proxy_status is None


# -- the evidence file ------------------------------------------------------- #
@pytest.mark.parametrize("shape", [{}, {"split": True}, {"chunked": True}, {"no_length": True}])
async def test_the_evidence_keeps_the_proxys_reply_and_error_page(via_proxy, tmp_path, shape):
    path = tmp_path / "x.jsonl.zst"
    writer = EvidenceWriter(path, _header(), t0=time.perf_counter(), secrets=[SECRET])
    async with FakeProxy(503, **shape) as proxy:
        via_proxy(proxy)
        rec = RequestRecorder(evidence=writer)
        async with _client(rec) as client:
            await client.complete(_spec())
    writer.close()
    lines = evidence.exchanges(path)
    assert len(lines) == 2  # the attempt and its repeat
    for line in lines:
        assert line["response"] is None
        assert line["request"]["method"] == "POST"
        got = line["proxy"]
        assert got["target"] == "relay.example:443"
        assert got["status"] == 503 and got["reason"] == "Service Unavailable"
        assert got["headers"]["x-squid-error"] == "ERR_CONNECT_FAIL 110"
        assert got["body"]["text"] == PAGE.decode()
        assert got["read_to_end"] is True
        assert got["wait_ms"] is not None
        # the key the proxy echoed is scrubbed like any relay-controlled text
        assert SECRET not in str(line)
        assert SECRET not in got["headers"]["x-echo-key"]


async def test_a_huge_error_page_is_cut(via_proxy, tmp_path, monkeypatch):
    monkeypatch.setattr(proxyreply, "MAX_BODY_BYTES", 32)
    path = tmp_path / "x.jsonl.zst"
    writer = EvidenceWriter(path, _header(), t0=time.perf_counter())
    async with FakeProxy(502, b"Bad Gateway", body=b"x" * 500) as proxy:
        via_proxy(proxy)
        rec = RequestRecorder(evidence=writer)
        async with _client(rec) as client:
            await client.complete(_spec())
    writer.close()
    got = evidence.exchanges(path)[0]["proxy"]
    assert got["status"] == 502
    assert got["body"]["truncated"] and got["body"]["bytes"] == 500
    assert len(got["body"]["text"]) == 32


def test_lines_with_a_proxy_reply_match_the_published_schema(tmp_path):
    import jsonschema

    from ekte import schemas

    cap = evidence.Capture(method="POST", url="https://relay.example/v1/chat/completions",
                           request_headers={}, request_body=b"{}", started=time.perf_counter())
    cap.proxy = proxyreply.ProxyReply(
        target="relay.example:443", sent_at=cap.started, status=503, reason="Service Unavailable",
        http_version="HTTP/1.1", headers={"server": "squid"}, at=cap.started + 60,
        body=b"<html/>", body_total=7, body_complete=True,
    )
    path = tmp_path / "x.jsonl.zst"
    w = EvidenceWriter(path, _header(), t0=cap.started)
    w.add([cap], seq=0, endpoint="target", detector="d", op="complete", error="ProxyError: 503")
    w.close()
    schema = schemas.load("evidence")
    for line in evidence.exchanges(path):
        jsonschema.validate(line, schema)
        assert line["proxy"]["wait_ms"] == pytest.approx(60_000, rel=1e-3)


# -- the tee itself ------------------------------------------------------------ #
def test_install_without_a_proxy_tees_nothing(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    assert proxyreply.install(httpx.AsyncClient()) == 0
    assert proxyreply.install(object()) == 0  # no _mounts: nothing to tee


def test_install_tees_each_proxy_once(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    client = httpx.AsyncClient()
    assert proxyreply.install(client) == 1
    assert proxyreply.install(client) == 0


def test_wire_parsing():
    wire = proxyreply._Wire()
    wire.feed(b"HTTP/1.1 504 Gateway Timeout\r\nContent-Length: 5\r\n\r\nab")
    assert wire.status() == 504 and wire.body_missing()
    wire.feed(b"cde")
    assert wire.body() == (b"abcde", 5, True) and not wire.body_missing()
    ok = proxyreply._Wire()
    ok.feed(b"HTTP/1.1 200 Connection established\r\n\r\n")
    assert ok.status() == 200 and not ok.body_missing()


# -- what the proxy's answer says, and how it reads ---------------------------- #
@pytest.mark.parametrize("status, reason", [
    (407, errorclass.PROXY_REFUSED), (403, errorclass.PROXY_REFUSED),
    (502, errorclass.PROXY_UNREACHABLE), (503, errorclass.PROXY_UNREACHABLE),
    (504, errorclass.PROXY_UNREACHABLE), (500, errorclass.PROXY_OTHER),
    (None, None), (True, None),
])
def test_proxy_reason(status, reason):
    assert errorclass.proxy_reason(status) == reason


def test_a_proxy_failure_stays_a_network_failure():
    rec = {"ok": False, "error_type": "ProxyError", "error_class": "network", "proxy_status": 503}
    assert errorclass.record_class(rec) == errorclass.NETWORK
    assert errorclass.outcome(rec) == errorclass.NETWORK
    assert errorclass.is_impaired(rec) and not errorclass.is_relay_failure(rec)
    assert errorclass.record_proxy_reason(rec) == errorclass.PROXY_UNREACHABLE
    assert errorclass.record_proxy_reason({**rec, "ok": True}) is None


def _rec(**kw):
    from ekte.models import RequestRecord

    base = {"seq": 0, "endpoint": "target", "ok": False, "error_type": "ProxyError",
            "error_class": "network"}
    return RequestRecord(**{**base, **kw})


def test_fail_text_names_what_the_proxy_said():
    from ekte.report.performance import fail_text

    assert fail_text(_rec(retried=True, proxy_status=503)) == (
        "repeated (ProxyError 503 · relay host unreachable via the proxy · network)")
    assert fail_text(_rec(proxy_status=407)) == (
        "failed (ProxyError 407 · the proxy refused the tunnel · network)")
    # records saved before the proxy's answer was kept read as they did
    assert fail_text(_rec()) == "failed (ProxyError · network)"


def test_the_impaired_warning_points_past_the_proxy():
    from ekte.runner import impaired_warning

    recs = [_rec(seq=0, retried=True, proxy_status=503, proxy_wait_ms=60_100.0),
            _rec(seq=1, proxy_status=503, proxy_wait_ms=59_900.0)]
    text = impaired_warning(recs, []) or ""
    assert "1 were answered by the proxy with 503 after up to 60 s" in text
    assert "could not reach the relay host" in text and "evidence file" in text
    assert "Of the network failures" not in (impaired_warning([_rec()], []) or "")


def test_reliability_advice_by_proxy_answer():
    from ekte.detectors.reliability import _network_advice

    assert "could not reach the relay host" in _network_advice(3, 0)
    assert "refused the tunnel" in _network_advice(0, 2)
    assert _network_advice(0, 0) == _network_advice(1, 1)


# -- a re-scored run keeps it ------------------------------------------------- #
async def test_a_replayed_refusal_keeps_the_proxys_answer():
    from ekte.models import EvidenceRef
    from ekte.replay import Replay

    client = _client(RequestRecorder())
    body = client._build_body(_spec())
    import json

    line = {
        "type": "exchange", "id": 1, "seq": 0, "endpoint": "target", "op": "complete",
        "start_ms": 0.0,
        "request": {"method": "POST", "url": "https://relay.example/v1/chat/completions",
                    "headers": {}, "body": {"text": json.dumps(body)}},
        "response": None,
        "error": "ProxyError: 503 Service Unavailable",
        "proxy": {"target": "relay.example:443", "status": 503, "reason": "Service Unavailable",
                  "headers": {"server": "squid"}, "body": {"text": "<html/>", "bytes": 7},
                  "read_to_end": True, "wait_ms": 60_000.0},
    }
    replay = Replay([line], ref=EvidenceRef(run_id="r", file="r.jsonl.zst", sha256="0" * 64))
    rec = RequestRecorder()
    replayed = OpenAICompatibleClient(client.config, transport=replay.transport("target"))
    replayed.recorder = rec
    replayed.replay_retried = replay.was_retried
    out = await replayed.complete(_spec())
    assert out.error_type == "ProxyError" and out.error_class == errorclass.NETWORK
    assert out.proxy_status == 503 and out.proxy_wait_ms == pytest.approx(60_000, rel=1e-3)
    assert rec.records[0].proxy_status == 503
