"""Where a failed request failed (ekte.errorclass): only relay failures blame
the relay, local and network failures are repeated and counted apart."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl

import httpx
import pytest

from ekte import errorclass
from ekte.clients import make_client
from ekte.detectors.impaired import NOTE, neutralize
from ekte.detectors.scale import Scale, outcome
from ekte.models import (
    DetectorResult,
    Dimension,
    RequestRecord,
    RequestSpec,
    Severity,
    Status,
)
from ekte.perf import RequestRecorder
from ekte.perf.summary import failed_seqs, summarize_endpoint
from ekte.runner import impaired_warning
from tests._helpers import BASE_URL, MockServer
from tests.test_evidence import _target

REQ = httpx.Request("POST", f"{BASE_URL}/chat/completions")


# -- classification ------------------------------------------------------------ #
@pytest.mark.parametrize(
    "exc, cls",
    [
        (httpx.ProxyError("502 from the proxy", request=REQ), "network"),
        (httpx.ConnectError("refused", request=REQ), "network"),
        (httpx.ConnectTimeout("slow connect", request=REQ), "network"),
        (socket.gaierror("no such host"), "network"),
        (ssl.SSLError("handshake"), "network"),
        (httpx.ReadTimeout("slow answer", request=REQ), "relay"),
        (httpx.RemoteProtocolError("peer closed", request=REQ), "relay"),
        (httpx.ReadError("reset", request=REQ), "relay"),
        (httpx.DecodingError("bad gzip", request=REQ), "relay"),
        (json.JSONDecodeError("Expecting value", "<html>", 0), "relay"),
        (httpx.PoolTimeout("pool full", request=REQ), "local"),
        (httpx.LocalProtocolError("bad header", request=REQ), "local"),
        (TypeError("'NoneType' object is not subscriptable"), "local"),
        (KeyError("choices"), "local"),
    ],
)
def test_exceptions_are_classified_by_where_they_failed(exc, cls):
    assert errorclass.classify_exception(exc) == cls
    # a record that kept only the name gets the same class (except the
    # ambiguous ValueError family, which only a live exception can tell)
    assert errorclass.classify_name(type(exc).__name__) == cls


def test_names_of_older_records():
    assert errorclass.classify_name("http_error", 502) == "relay"
    assert errorclass.classify_name(None, 500) == "relay"
    assert errorclass.classify_name("DeadlineTimeout") == "relay"
    assert errorclass.classify_name("IncompleteRanking") == "relay"
    assert errorclass.classify_name("Unsupported") == "local"
    assert errorclass.classify_name("SomethingNew") == "relay"  # unknown: as before
    old = {"ok": False, "error_type": "ProxyError", "status_code": None}
    assert errorclass.record_class(old) == "network" and errorclass.is_impaired(old)
    assert errorclass.record_class({"ok": True}) is None
    records = [dict(old), {"ok": False, "status_code": 502, "error_type": "http_error"}, {"ok": True}]
    errorclass.attach_classes(records)
    assert [r.get("error_class") for r in records] == ["network", "relay", None]


@pytest.mark.parametrize(
    "raw, want", [(None, 1), ("", 1), ("0", 0), ("3", 3), (" 2 ", 2), ("-1", 0), ("99", 10), ("x", 1)]
)
def test_retries_come_from_the_environment(monkeypatch, raw, want):
    monkeypatch.delenv("EKTE_NON_RELAY_RETRIES", raising=False)
    if raw is not None:
        monkeypatch.setenv("EKTE_NON_RELAY_RETRIES", raw)
    assert errorclass.non_relay_retries() == want


# -- the client repeats local and network failures, never relay ones ----------- #
def _client(handler):
    client = make_client(_target(), transport=httpx.MockTransport(handler))
    client.recorder, client.endpoint = RequestRecorder(), "target"
    return client


def _complete(client):
    async def go():
        async with client:
            return await client.complete(RequestSpec(messages=[{"role": "user", "content": "hi"}]))

    return asyncio.run(go())


def _flaky(fail, times=1):
    """The mock relay, failing its first ``times`` requests with ``fail``."""
    server, calls = MockServer(), []

    def handler(request):
        calls.append(request)
        if len(calls) <= times:
            return fail(request)
        return server.handler(request)

    return handler, calls


def _raise(exc_type):
    def fail(request):
        raise exc_type("boom", request=request)

    return fail


def test_a_network_failure_is_repeated_once(monkeypatch):
    monkeypatch.delenv("EKTE_NON_RELAY_RETRIES", raising=False)
    handler, calls = _flaky(_raise(httpx.ProxyError))
    client = _client(handler)
    out = _complete(client)
    assert out.ok and len(calls) == 2
    first, second = client.recorder.records
    assert (first.ok, first.error_class, first.retried) == (False, "network", True)
    assert (second.ok, second.retried) == (True, False)
    assert out.seqs == [first.seq, second.seq]


def test_a_persistent_network_failure_is_not_the_relays(monkeypatch):
    monkeypatch.setenv("EKTE_NON_RELAY_RETRIES", "2")
    handler, calls = _flaky(_raise(httpx.ConnectError), times=99)
    client = _client(handler)
    out = _complete(client)
    assert not out.ok and out.error_class == "network" and len(calls) == 3
    recs = client.recorder.records
    assert [r.retried for r in recs] == [True, True, False]
    perf = summarize_endpoint(recs)
    assert (perf.errors, perf.network_errors, perf.retried, perf.error_rate) == (0, 1, 2, None)
    assert failed_seqs(recs) == []


def test_retries_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("EKTE_NON_RELAY_RETRIES", "0")
    handler, calls = _flaky(_raise(httpx.ProxyError))
    out = _complete(_client(handler))
    assert not out.ok and len(calls) == 1


def test_a_relay_failure_is_never_repeated(monkeypatch):
    monkeypatch.setenv("EKTE_NON_RELAY_RETRIES", "3")
    handler, calls = _flaky(lambda request: httpx.Response(502, text="bad gateway"))
    client = _client(handler)
    out = _complete(client)
    assert not out.ok and out.error_class == "relay" and len(calls) == 1
    perf = summarize_endpoint(client.recorder.records)
    assert (perf.errors, perf.network_errors, perf.error_rate) == (1, 0, 1.0)


def test_a_bug_in_ekte_does_not_crash_and_is_not_the_relays(monkeypatch, caplog):
    monkeypatch.delenv("EKTE_NON_RELAY_RETRIES", raising=False)

    def bug(request):
        raise TypeError("'NoneType' object is not subscriptable")

    handler, calls = _flaky(bug, times=99)
    client = _client(handler)
    with caplog.at_level("WARNING", logger="ekte.clients.base"):
        out = _complete(client)
    assert not out.ok and out.error_class == "local" and len(calls) == 2
    assert "ekte failed on a request (TypeError)" in caplog.text
    perf = summarize_endpoint(client.recorder.records)
    assert (perf.errors, perf.local_errors) == (0, 1)


def test_embeddings_and_models_are_repeated_too(monkeypatch):
    monkeypatch.delenv("EKTE_NON_RELAY_RETRIES", raising=False)
    handler, calls = _flaky(_raise(httpx.ProxyError))
    client = _client(handler)

    async def go():
        async with client:
            return await client.list_models()

    out, ids = asyncio.run(go())
    assert out.ok and ids and len(calls) == 2 and len(out.seqs) == 2


# -- findings that rest only on lost requests ----------------------------------- #
SCALE = Scale(
    outcome("x.check", "ok", 100, Status.PASS, label="fine"),
    outcome("x.check", "bad", 0, Status.FAIL, Severity.HIGH, label="bad"),
)


def _rec(seq, ok=False, **kw):
    return RequestRecord(seq=seq, detector="x", ok=ok, **kw)


def _result(*findings):
    result = DetectorResult(id="x", name="X", dimension=Dimension.CAPABILITY, findings=list(findings),
                            scoring=SCALE.scoring())
    result.score, result.status = Scale.mean(result.findings), Scale.roll_up(result.findings)
    return result


def test_a_check_resting_on_lost_requests_is_inconclusive():
    lost = SCALE.finding("x.check", "bad", title="Lost", id="x.lost", calls=[1])
    good = SCALE.finding("x.check", "ok", title="Fine", id="x.fine", calls=[0])
    result = _result(lost, good)
    assert (result.score, result.status) == (50.0, Status.FAIL)
    records = [_rec(0, ok=True), _rec(1, error_type="ProxyError", error_class="network")]
    assert neutralize(result, records) == 1
    assert (lost.status, lost.severity, lost.score) == (Status.INCONCLUSIVE, Severity.INFO, None)
    assert lost.summary.startswith(NOTE) and lost.evidence["impaired_requests"] == [1]
    # the lost check no longer counts; the detector reads inconclusive, as with
    # any check it could not judge
    assert (result.score, result.status) == (100.0, Status.INCONCLUSIVE)
    warning = impaired_warning(records, [result])
    assert warning and "1 on the network path" in warning and "1 check(s)" in warning


def test_a_relay_failure_or_answer_keeps_the_verdict():
    mixed = SCALE.finding("x.check", "bad", title="Mixed", id="x.mixed", calls=[1, 2])
    answered = SCALE.finding("x.check", "bad", title="Answered", id="x.answered", calls=[0, 1])
    repeated = SCALE.finding("x.check", "bad", title="Repeated", id="x.repeated", calls=[3, 4])
    result = _result(mixed, answered, repeated)
    records = [
        _rec(0, ok=True),
        _rec(1, error_type="ProxyError", error_class="network"),
        _rec(2, status_code=502, error_type="http_error", error_class="relay"),
        # lost once, then failed at the relay on its repeat
        _rec(3, error_type="ConnectError", error_class="network", retried=True),
        _rec(4, status_code=500, error_type="http_error", error_class="relay"),
    ]
    assert neutralize(result, records) == 0
    assert all(f.status == Status.FAIL for f in result.findings)
    assert impaired_warning([_rec(0, ok=True), records[4]], [result]) is None
