"""Performance section: stats floors, request recording, the report block."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ekte.clients import OpenAICompatibleClient
from ekte.config import AuditOptions
from ekte.models import CompletionOutcome, RequestRecord, RequestSpec, TargetConfig
from ekte.perf import RequestRecorder, build_performance, detector_scope, phase_scope
from ekte.perf.recorder import NetTrace, usage_tokens
from ekte.perf.summary import NOTE_PASSIVE, NOTE_REASONING, hidden_reasoning, summarize_endpoint
from ekte.runner import run_audit
from ekte.utils.stats import describe
from tests._helpers import BASE_URL, DEFAULT_MODEL


def _spec(stream: bool = False) -> RequestSpec:
    return RequestSpec(messages=[{"role": "user", "content": "hello there"}], stream=stream)


def _recorded_client(mock_server, recorder, kind: str = "target") -> OpenAICompatibleClient:
    cfg = TargetConfig(name=kind, kind=kind, base_url=BASE_URL, api_key="sk-x", model=DEFAULT_MODEL)
    client = OpenAICompatibleClient(cfg, transport=mock_server.transport)
    client.recorder = recorder
    return client


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def test_describe_hides_percentiles_below_their_sample_floor():
    few = describe([float(i) for i in range(9)])
    assert few["count"] == 9 and few["p50"] == 4.0 and few["p75"] is not None
    assert few["p90"] is None and few["p95"] is None and few["p99"] is None

    twenty = describe([float(i) for i in range(20)])
    assert twenty["p90"] is not None and twenty["p95"] is not None and twenty["p99"] is None

    hundred = describe([float(i) for i in range(100)])
    assert hundred["p99"] == pytest.approx(98.01)
    assert hundred["min"] == 0.0 and hundred["max"] == 99.0

    empty = describe([])
    assert empty["count"] == 0 and empty["p50"] is None and empty["mean"] is None


# --------------------------------------------------------------------------- #
# usage parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (
            {"prompt_tokens": 10, "completion_tokens": 50,
             "prompt_tokens_details": {"cached_tokens": 8},
             "completion_tokens_details": {"reasoning_tokens": 30}},
            {"input": 10, "output": 50, "reasoning": 30, "cached": 8},
        ),
        (
            {"input_tokens": 12, "output_tokens": 7,
             "input_tokens_details": {"cached_tokens": 0},
             "output_tokens_details": {"reasoning_tokens": 3}},
            {"input": 12, "output": 7, "reasoning": 3, "cached": 0},
        ),
        (
            {"input_tokens": 5, "output_tokens": 9, "cache_read_input_tokens": 4},
            {"input": 5, "output": 9, "reasoning": None, "cached": 4},
        ),
        (
            {"prompt_tokens": 5, "completion_tokens": 9, "prompt_cache_hit_tokens": 2},
            {"input": 5, "output": 9, "reasoning": None, "cached": 2},
        ),
        (None, {"input": None, "output": None, "reasoning": None, "cached": None}),
    ],
)
def test_usage_tokens_across_protocols(usage, expected):
    assert usage_tokens(usage) == expected


def test_anthropic_usage_keeps_cache_fields():
    from ekte.clients.anthropic import AnthropicClient

    usage = AnthropicClient._usage(
        {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 2}
    )
    assert usage is not None and usage["cache_read_input_tokens"] == 2


# --------------------------------------------------------------------------- #
# recorder
# --------------------------------------------------------------------------- #
async def test_recorder_logs_calls_with_attribution(mock_server):
    mock_server.reply_text = "one two three four five six seven eight nine ten"
    mock_server.stream_chunk_words = 1
    rec = RequestRecorder()
    client = _recorded_client(mock_server, rec)

    with detector_scope("streaming"):
        await client.complete(_spec(stream=True))
    with detector_scope("performance"), phase_scope("probe"):
        await client.complete(_spec())
    await client.list_models(no_cache=True)

    assert [r.seq for r in rec.records] == [0, 1, 2]
    s, n, m = rec.records
    assert (s.detector, s.phase, s.stream, s.op) == ("streaming", "passive", True, "complete")
    assert (n.detector, n.phase, n.stream) == ("performance", "probe", False)
    assert (m.op, m.detector) == ("list_models", None)
    assert s.ok and s.ttft_ms is not None and s.chunk_count == 10
    assert s.itl_mean_ms is not None and s.itl_p50_ms is not None
    assert s.output_tokens_reported == 10 and s.output_tokens_local == 10
    assert s.input_tokens_local and s.input_tokens_reported
    assert s.e2e_tps_local is not None
    assert n.ttft_ms is None  # only streamed calls have a TTFT
    assert all(r.endpoint == "target" for r in rec.records)
    assert all(r.start_ms >= 0 for r in rec.records)


async def test_no_cache_header_is_sent_on_ping(mock_server):
    seen: list[str | None] = []
    base = mock_server.handler

    def handler(request):
        if request.method == "GET":
            seen.append(request.headers.get("cache-control"))
        return base(request)

    cfg = TargetConfig(base_url=BASE_URL, model=DEFAULT_MODEL)
    client = OpenAICompatibleClient(cfg, transport=httpx.MockTransport(handler))
    await client.list_models(no_cache=True)
    await client.list_models()
    assert seen == ["no-cache", None]


async def test_attribution_survives_concurrent_gather(mock_server):
    rec = RequestRecorder()
    client = _recorded_client(mock_server, rec)

    async def one(det: str):
        with detector_scope(det):
            await client.complete(_spec())

    await asyncio.gather(one("a"), one("b"), one("c"))
    assert sorted(r.detector or "" for r in rec.records) == ["a", "b", "c"]


async def test_recorder_flags_failures_and_cache(mock_server):
    rec = RequestRecorder()
    client = _recorded_client(mock_server, rec)
    mock_server.chat_status = 429
    await client.complete(_spec())
    assert rec.records[-1].rate_limited and not rec.records[-1].ok

    rec.record_completion(
        "target",
        _spec(),
        CompletionOutcome(ok=True, duration_ms=100.0, content="hi",
                          usage={"prompt_tokens": 5, "completion_tokens": 1,
                                 "prompt_tokens_details": {"cached_tokens": 5}}),
        rec.t0,
    )
    assert rec.records[-1].cached

    rec.record_completion(
        "target", _spec(), CompletionOutcome(ok=False, error_type="ReadTimeout"), rec.t0
    )
    assert rec.records[-1].timeout


async def test_on_record_errors_never_break_the_call(mock_server):
    def boom(_):
        raise RuntimeError("sink down")

    client = _recorded_client(mock_server, RequestRecorder(on_record=boom))
    out = await client.complete(_spec())
    assert out.ok


async def test_net_trace_breakdown():
    net = NetTrace()
    for name in (
        "connection.connect_tcp.started",
        "connection.connect_tcp.complete",
        "connection.start_tls.started",
        "connection.start_tls.complete",
        "http11.send_request_headers.started",
        "http11.send_request_body.complete",
        "http11.receive_response_headers.complete",
    ):
        await net.trace(name, {})
    started = net.marks["connection.connect_tcp.started"]
    br = net.breakdown(started)
    assert br["connect_ms"] is not None and br["connect_ms"] >= 0
    assert br["tls_ms"] is not None and br["server_ms"] is not None
    assert br["headers_ms"] is not None and br["headers_ms"] >= br["server_ms"]
    # A reused connection has no connect/TLS events.
    assert NetTrace().breakdown(started)["connect_ms"] is None


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def _rec(seq: int, **kw) -> RequestRecord:
    base: dict = {
        "seq": seq, "ok": True, "duration_ms": 1000.0, "stream": True, "ttft_ms": 200.0,
        "output_tokens_reported": 100, "output_tokens_local": 100,
        "decode_tps_reported": 120.0, "decode_tps_local": 120.0,
        "e2e_tps_reported": 100.0, "e2e_tps_local": 100.0, "input_tokens_local": 50,
    }
    base.update(kw)
    return RequestRecord(**base)


def test_summary_prefers_probe_and_excludes_cached_and_warmup():
    recs = [
        _rec(0, phase="passive", duration_ms=9000.0),
        _rec(1, phase="warmup", duration_ms=5000.0),
        _rec(2, phase="probe", duration_ms=1000.0),
        _rec(3, phase="probe", duration_ms=1200.0),
        _rec(4, phase="probe", duration_ms=10.0, cached=True),
        _rec(5, phase="probe", ok=False, status_code=500, error_type="http_error"),
        _rec(6, phase="probe", ok=False, status_code=429, rate_limited=True),
        _rec(7, op="list_models", phase="ping", duration_ms=40.0, stream=False),
    ]
    ep = summarize_endpoint(recs)
    assert ep.source == "probe"
    # Reliability covers every call: passive + warm-up + 5 probe requests.
    assert ep.requests == 7 and ep.successes == 5
    assert ep.errors == 1 and ep.rate_limited == 1 and ep.cached_excluded == 1
    assert ep.error_rate == pytest.approx(1 / 7)
    assert ep.latency_ms.count == 2 and ep.latency_ms.max == 1200.0
    assert ep.cold_start_ms == 5000.0
    assert ep.network_rtt_ms.count == 1 and ep.network_rtt_ms.p50 == 40.0


def test_error_rate_counts_failed_audit_requests_when_probe_succeeds():
    recs = [_rec(i, phase="probe") for i in range(4)]
    recs += [
        _rec(10, phase="passive", ok=False, status_code=502, error_type="http_error"),
        _rec(11, phase="passive", ok=False, timeout=True, error_type="timeout"),
    ]
    ep = summarize_endpoint(recs)
    assert ep.source == "probe" and ep.latency_ms.count == 4
    assert ep.requests == 6 and ep.successes == 4
    assert ep.errors == 2 and ep.timeouts == 1
    assert ep.error_rate == pytest.approx(2 / 6)


def test_summary_falls_back_to_passive():
    recs = [_rec(i, phase="passive", detector="x") for i in range(3)]
    report = build_performance(recs)
    assert report is not None
    assert report.source == "passive" and report.target.latency_ms.count == 3
    assert NOTE_PASSIVE in report.notes
    assert report.probe_requests == 0 and report.probe_cost is None


def test_build_performance_none_without_calls():
    assert build_performance([]) is None


def test_compare_rows_and_concurrency():
    recs = [_rec(i, phase="probe", endpoint="target", decode_tps_reported=200.0) for i in range(5)]
    recs += [_rec(10 + i, phase="probe", endpoint="baseline", decode_tps_reported=80.0) for i in range(5)]
    recs += [
        _rec(20 + i, phase="probe_concurrent", endpoint="target", start_ms=float(i * 10))
        for i in range(3)
    ]
    report = build_performance(recs, has_baseline=True, concurrency=3, probe_max_tokens=128)
    assert report is not None and report.baseline is not None
    rows = {r.metric: r for r in report.comparison}
    assert rows["decode_tps_reported_p50"].ratio == pytest.approx(2.5)
    assert rows["latency_p50"].delta == 0
    conc = report.target.concurrency
    assert conc is not None and conc.requests == 3 and conc.concurrency == 3
    assert conc.aggregate_tps_local == pytest.approx(300 / 1.02)
    assert report.probe_cost is not None and report.probe_cost.requests == 13
    assert report.probe_max_tokens == 128


def test_hidden_reasoning_detection():
    plain = [_rec(i) for i in range(4)]
    assert not hidden_reasoning(plain)
    itemized = [_rec(0, reasoning_tokens=40)]
    assert hidden_reasoning(itemized)
    inflated = [_rec(i, output_tokens_reported=300, output_tokens_local=100) for i in range(4)]
    assert hidden_reasoning(inflated)
    report = build_performance(inflated)
    assert report is not None and NOTE_REASONING in report.notes


def test_input_size_buckets():
    recs = [_rec(0, input_tokens_local=100), _rec(1, input_tokens_local=5000, ttft_ms=900.0)]
    buckets = summarize_endpoint(recs).ttft_by_input
    assert [b.label for b in buckets] == ["<1K", "1K-8K"]
    assert buckets[1].ttft_p50_ms == 900.0


# --------------------------------------------------------------------------- #
# runner integration
# --------------------------------------------------------------------------- #
@pytest.fixture
def patched_make_client(monkeypatch, mock_server):
    from ekte.clients import make_client as real

    def factory(config, **_):
        return real(config, transport=mock_server.transport)

    monkeypatch.setattr("ekte.runner.make_client", factory)
    return mock_server


async def test_audit_report_has_passive_performance(patched_make_client, target_config):
    events: list[dict] = []
    report = await run_audit(
        target_config, AuditOptions(suite="standard"), on_event=events.append
    )
    perf = report.performance
    assert perf is not None and perf.source == "passive"
    assert perf.requests and perf.target.latency_ms.count > 0
    detectors = {r.detector for r in perf.requests}
    assert {"reliability", "streaming"} <= detectors
    assert perf.baseline is None and perf.comparison == []
    live = [e for e in events if e["type"] == "request_done"]
    assert len(live) == len(perf.requests)
    assert "content" not in live[0]["record"]
    # The JSON export carries the section.
    assert '"performance"' in report.model_dump_json()
    # started_at is the instant start_ms counts from: every request falls
    # between it and generated_at.
    assert report.started_at is not None and report.generated_at is not None
    started = datetime.fromisoformat(report.started_at)
    generated = datetime.fromisoformat(report.generated_at)
    assert started.utcoffset() == timedelta(0)
    last = max(r.start_ms + (r.duration_ms or 0) for r in perf.requests)
    assert started + timedelta(milliseconds=last) <= generated


def test_recorder_start_time_is_its_t0():
    before = datetime.now(UTC)
    rec = RequestRecorder()
    assert before <= rec.started_at <= datetime.now(UTC)


async def test_stream_server_time_runs_to_first_token():
    # A stream's headers arrive before any output, so its server share is
    # measured from the request being sent to the first token.
    rec = RequestRecorder()
    net = NetTrace()
    started = 100.0
    net.marks = {
        "http11.send_request_body.complete": started + 0.010,
        "http11.receive_response_headers.complete": started + 0.012,
    }
    outcome = CompletionOutcome(ok=True, duration_ms=900.0, ttft_ms=310.0, content="a b c")
    r = rec.record_completion("target", _spec(stream=True), outcome, started, net)
    assert r.headers_ms == pytest.approx(12.0)
    assert r.server_ms == pytest.approx(300.0)
    plain = rec.record_completion("target", _spec(), outcome, started, net)
    assert plain.server_ms == pytest.approx(2.0)
