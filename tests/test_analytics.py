"""The shared Analytics building blocks (ekte/web/analytics.py), the time
series of the query core they feed, and the /api/analytics endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ekte.knowledge import store
from ekte.knowledge.relays import add_relay
from ekte.perf.outcomes import from_counts
from ekte.web import analytics, history, query
from ekte.web.analytics import AnalyticsError
from ekte.web.query import Query, QueryError

OPENAI = "https://api.openai.com/v1"
RELAY = "https://relay.example/v1"
OTHER = "https://other.example/v1"
T0 = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)  # a Monday


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


def _report(
    started: datetime | None,
    *,
    base_url: str = RELAY,
    model: str = "model-a",
    score: float | None = 80.0,
    risk: str | None = "clean",
    suite: str = "standard",
    stream_mode: str = "stream",
    api: str = "openai",
    tool_version: str = "0.11.0",
    kb_hash: str | None = "kb1",
    ttft: float | None = 300.0,
    tps: float | None = 50.0,
    billing: tuple[float, float] | None = (1.0, 1.0),
    protocol: float | None = 90.0,
    old: bool = False,
) -> dict:
    """A report as save() gets it; ``old`` drops what older ekte versions lacked."""
    generated = (started or T0) + timedelta(minutes=2)
    report: dict = {
        "tool_version": tool_version,
        "mode": "check",
        "generated_at": generated.isoformat(),
        "suite": suite,
        "stream_mode": stream_mode,
        "target": {"base_url": base_url, "model": model, "claimed_model": model, "api": api},
        "verdict": {"overall_score": score, "risk_level": risk, "rating": "B"},
        "dimensions": [] if protocol is None else [
            {"dimension": "protocol", "score": protocol, "weight": 8.0, "status": "pass"},
        ],
        "detectors": [],
        "knowledge": {"profile_hash": kb_hash, "model_id": model if kb_hash else None},
    }
    if started is not None and not old:
        report["started_at"] = started.isoformat()
    if not old:
        report["performance"] = {
            "target": {
                "requests": 10, "successes": 9,
                "ttft_ms": {"p50": ttft} if ttft is not None else None,
                "decode_tps_local": {"p50": tps} if tps is not None else None,
            },
            "requests": [],
        }
        report["outcomes"] = from_counts({"complete": {"success": 9, "relay_5xx": 1}}).model_dump()
        if billing is not None:
            report["detectors"].append({
                "id": "billing", "status": "pass", "findings": [], "duration_ms": 1000,
                "evidence": {"ratio_prompt": billing[0], "ratio_completion": billing[1]},
            })
    return report


def _save(started, watch_id=None, **kw) -> int:
    rid = history.save(_report(started, **kw), watch_id=watch_id)
    assert rid > 0
    return rid


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def test_percentile_linear_interpolation():
    assert analytics.percentile([], 0.5) is None
    assert analytics.percentile([7.0], 0.25) == 7.0
    vals = [1.0, 2.0, 3.0, 4.0]
    assert analytics.percentile(vals, 0.5) == 2.5
    assert analytics.percentile(vals, 0.25) == 1.75
    assert analytics.percentile(vals, 0.75) == 3.25
    assert analytics.percentile([1.0, 2.0, 10.0], 0.5) == 2.0


def test_metric_whitelist():
    assert analytics.metric("ttft_p50").column == "ttft_p50_ms"
    assert analytics.metric("dim:protocol").unit == "score"
    for bad in ("", "ttft_p50_ms", "score; DROP TABLE history", "dim:", "dim:a b", "dim:" + "x" * 65):
        with pytest.raises(AnalyticsError):
            analytics.metric(bad)


# --------------------------------------------------------------------------- #
# Relay grouping
# --------------------------------------------------------------------------- #
def _relays() -> dict[str, dict]:
    groups = query.aggregate(history.query_connection(), Query(surface="chat"), [], "relay")
    return {g.key: {**g.describe(), "runs": g.runs} for g in groups}


def test_relays_grouped_by_knowledge_base_entry_at_query_time(data):
    add_relay("Cheap GPT", RELAY)
    _save(T0, base_url=OPENAI + "/chat/completions")
    _save(T0 + timedelta(hours=1), base_url=RELAY + "/")
    _save(T0 + timedelta(hours=2), base_url=RELAY)
    _save(T0 + timedelta(hours=3), base_url=OTHER)
    relays = _relays()
    assert relays["openai"] == {"key": "openai", "label": "OpenAI", "in_kb": True,
                                "kind": "provider", "runs": 1}
    assert relays["cheap-gpt"] == {"key": "cheap-gpt", "label": "Cheap GPT", "in_kb": True,
                                   "kind": "relay", "runs": 2}
    assert relays[OTHER] == {"key": OTHER, "label": OTHER, "in_kb": False, "kind": "url", "runs": 1}
    assert next(iter(relays)) == "cheap-gpt"  # most runs first

    # Renaming the relay relabels its history; saving one re-groups old runs.
    entry = store.find("provider", "cheap-gpt")
    store.upsert("provider", "cheap-gpt", {**entry["body"], "display_name": "Budget GPT"}, origin="relay")
    add_relay("Other Relay", OTHER)
    relays = _relays()
    assert relays["cheap-gpt"]["label"] == "Budget GPT"
    assert relays["other-relay"]["in_kb"] and relays["other-relay"]["runs"] == 1
    assert OTHER not in relays
    out = _series(group="relay", relays=("other-relay",))
    assert [s["key"] for s in out["series"]] == ["other-relay"]


def test_resolver_without_base_url_and_unreadable_kb():
    resolver = analytics.RelayResolver(knowledge=None)
    assert resolver.resolve({"base_url": None}).key == analytics.UNKNOWN_RELAY
    assert resolver.resolve({"base_url": "not a url "}).key == "not a url"
    assert resolver.resolve({"base_url": "https://x.example/v1/"}).key == "https://x.example/v1"


# --------------------------------------------------------------------------- #
# Filters, coverage, low_n, mixed flags, annotations
# --------------------------------------------------------------------------- #
@pytest.fixture
def seeded(data):
    """Three relays, two models, suites / stream modes / monitor runs over a few
    days, plus old-shaped runs without started_at or performance data."""
    add_relay("Cheap GPT", RELAY)
    for day in range(4):
        for i in range(3):
            _save(T0 + timedelta(days=day, minutes=i), base_url=RELAY, ttft=100.0 * (i + 1),
                  score=70.0 + i, tool_version="0.10.0" if day < 2 else "0.11.0",
                  kb_hash="kb1" if day < 3 else "kb2")
    _save(T0, base_url=OPENAI, model="model-b", score=95.0, suite="quick", watch_id=7)
    _save(T0 + timedelta(days=1), base_url=OPENAI, model="model-b", score=91.0, watch_id=7,
          stream_mode="non_stream", risk="high")
    _save(T0 + timedelta(days=1), base_url=OTHER, model="model-a", score=40.0, risk="high",
          api="anthropic")
    # Older reports: no started_at (estimated from generated_at), no performance.
    _save(T0 + timedelta(days=2, hours=1), base_url=RELAY, old=True, score=60.0)
    _save(T0 + timedelta(days=2, hours=2), base_url=RELAY, old=True, score=None, risk=None)
    return data


def _series(metric: str = "score", group: str = "relay", bucket: str = "day", tz="UTC", *,
            keys=(), block: int = 1, fold: str = "week", **filters) -> dict:
    """The query core's time series (what /api/analytics/series and
    /api/analytics/heatmap draw) over the chat runs, with quartiles."""
    q = Query(surface=filters.pop("surface", "chat"), **filters)
    return query.series(history.query_connection(), q, metric, group, bucket, tz, keys=keys,
                        block=block, fold=fold, quantiles=True).public()


def _runs(**filters) -> int:
    return query.count_runs(history.query_connection(), Query(**filters))


def test_filters(seeded):
    assert _runs() == 17
    assert _runs(exec="monitor") == 2 and _runs(exec="manual") == 15
    assert _runs(suite="quick") == 1 and _runs(stream="non_stream") == 1
    assert _runs(api="anthropic") == 1 and _runs(models=("model-b",)) == 2
    assert _runs(relays=("cheap-gpt",)) == 14 and _runs(relays=(OTHER,)) == 1
    assert _runs(relays=("nope",)) == 0
    assert _runs(start=T0 + timedelta(days=1), end=T0 + timedelta(days=2)) == 5


def test_series_daily_with_coverage_low_n_mixed_and_annotations(seeded):
    out = _series("ttft_p50", "relay", "day")
    assert out["metric"] == {"id": "ttft_p50", "unit": "ms", "format": "ms", "higher_is_better": False,
                             "agg": "median", "surfaces": ["chat"], "label_key": "metric.ttft_p50",
                             "short_label_key": "metric.ttft_p50.short", "kpi_label_key": "metric.ttft_p50",
                             "agg_hint_key": "metric.ttft_p50.agg_hint"}
    assert out["tz"] == "UTC" and out["bucket"] == "day"
    keys = [s["key"] for s in out["series"]]
    assert keys == ["cheap-gpt", "openai", OTHER]  # by run count
    relay = out["series"][0]
    # 14 runs, the 2 old ones measured nothing: they count in runs, not in n.
    assert relay["runs"] == 14 and relay["n"] == 12 and relay["coverage"] == pytest.approx(12 / 14)
    assert [p["bucket"] for p in relay["points"]] == [
        f"2026-03-0{d}T00:00:00+00:00" for d in (2, 3, 4, 5)
    ]
    day3 = relay["points"][2]
    assert day3["runs"] == 5 and day3["n"] == 3 and day3["low_n"] is False
    assert (day3["median"], day3["p25"], day3["p75"]) == (200.0, 150.0, 250.0)
    assert day3["value"] == day3["median"]
    assert relay["mixed"] == {"suite": False, "stream_mode": False, "api": False}
    kinds = [(a["kind"], a["from"], a["to"], a["bucket"]) for a in relay["annotations"]]
    assert kinds == [
        ("tool_version", "0.10.0", "0.11.0", "2026-03-04T00:00:00+00:00"),
        ("kb_profile", "kb1", "kb2", "2026-03-05T00:00:00+00:00"),
    ]
    openai = out["series"][1]
    assert openai["mixed"] == {"suite": True, "stream_mode": True, "api": False}
    assert all(p["low_n"] for p in openai["points"]) and openai["points"][0]["n"] == 1


def test_series_keys_groups_and_share_metric(seeded):
    out = _series("risk_high_share", "model", "week", keys=["model-b", "missing"])
    b, missing = out["series"]
    assert b["key"] == "model-b" and b["in_kb"] is True
    (point,) = b["points"]
    assert {k: point[k] for k in ("bucket", "runs", "value", "n", "low_n")} == {
        "bucket": "2026-03-02T00:00:00+00:00", "runs": 2, "value": 0.5, "n": 2, "low_n": True}
    assert point.get("median") is None and point.get("p25") is None
    assert missing["runs"] == 0 and missing["points"] == [] and missing["coverage"] is None
    both = _series(group="relay_model")
    assert both["series"][0]["key"] == "cheap-gpt|model-a"
    assert both["series"][0]["label"] == "Cheap GPT · model-a"
    dim = _series("dim:protocol", bucket="week", relays=("cheap-gpt",))
    assert dim["series"][0]["points"][0]["median"] == 90.0
    assert dim["series"][0]["n"] == 14  # old-shaped reports have dimension scores too


def test_series_score_keeps_old_runs(seeded):
    """Old-shaped runs still contribute what they have (their score)."""
    relay = _series(relays=("cheap-gpt",))["series"][0]
    assert relay["n"] == 13 and relay["runs"] == 14  # one old run has no score
    assert relay["points"][2]["n"] == 4


def test_series_group_all(seeded):
    out = _series(group="all", bucket="dow_hour")
    assert len(out["series"]) == 1 and out["series"][0]["key"] == analytics.ALL_KEY
    assert out["series"][0]["runs"] == 17  # every run (old ones dated by generated_at)


# --------------------------------------------------------------------------- #
# Time zones
# --------------------------------------------------------------------------- #
def test_buckets_in_viewer_time_zone_across_dst_and_midnight(data):
    utc = UTC
    times = [
        datetime(2026, 3, 28, 22, 30, tzinfo=utc),  # Sat 23:30 CET
        datetime(2026, 3, 28, 23, 30, tzinfo=utc),  # Sun 00:30 CET
        datetime(2026, 3, 29, 22, 30, tzinfo=utc),  # Mon 00:30 CEST (after spring forward)
        datetime(2026, 10, 25, 0, 30, tzinfo=utc),  # 02:30 CEST
        datetime(2026, 10, 25, 1, 30, tzinfo=utc),  # 02:30 CET (after fall back)
    ]
    for t in times:
        _save(t)

    def buckets(bucket, tz="UTC"):
        return [p["bucket"] for p in _series(bucket=bucket, tz=tz)["series"][0]["points"]]

    assert buckets("day", "Europe/Berlin") == [
        "2026-03-28T00:00:00+01:00", "2026-03-29T00:00:00+01:00",
        "2026-03-30T00:00:00+02:00", "2026-10-25T00:00:00+02:00",
    ]
    assert buckets("day") == [
        "2026-03-28T00:00:00+00:00", "2026-03-29T00:00:00+00:00", "2026-10-25T00:00:00+00:00",
    ]
    hours = buckets("hour", "Europe/Berlin")
    assert hours[-2:] == ["2026-10-25T02:00:00+02:00", "2026-10-25T02:00:00+01:00"]
    assert buckets("week", "Europe/Berlin")[:2] == [
        "2026-03-23T00:00:00+01:00", "2026-03-30T00:00:00+02:00",
    ]
    assert buckets("day", timezone(timedelta(minutes=-300)))[0] == "2026-03-28T00:00:00-05:00"
    heat = _series(bucket="dow_hour", tz="Europe/Berlin")
    cells = {p["bucket"]: p for p in heat["series"][0]["points"]}
    assert set(cells) == {"6-23", "7-00", "1-00", "7-02"}
    assert cells["7-02"]["n"] == 2 and (cells["7-02"]["dow"], cells["7-02"]["hour"]) == (7, 2)
    assert heat["series"][0]["annotations"] == []
    # 4-hour blocks: the 23:00, 00:00 and 02:00 runs fall into 20-24 and 00-04
    blocks = _series(bucket="dow_hour", block=4, tz="Europe/Berlin")
    assert blocks["block"] == 4
    cells = {p["bucket"]: p for p in blocks["series"][0]["points"]}
    assert set(cells) == {"6-20", "7-00", "1-00"}
    assert cells["7-00"]["n"] == 3 and (cells["7-00"]["hour"], cells["7-00"]["hours"]) == (0, 4)
    assert "hours" not in heat["series"][0]["points"][0]
    with pytest.raises(QueryError):
        _series(bucket="dow_hour", block=5)


def test_dow_hour_folds_into_4_week_cycles_and_weeks_of_the_month(data):
    utc = UTC

    def grid(fold, keys=()):
        out = _series(bucket="dow_hour", block=4, fold=fold, keys=keys)
        return out, {p["bucket"]: p for p in out["series"][0]["points"]} if out["series"] else {}

    # Mondays 5 and 12 Jan and 2 Feb 2026, Thursday 30 Apr: 116 calendar days
    for t in (datetime(2026, 1, 5, 10, tzinfo=utc), datetime(2026, 1, 12, 10, tzinfo=utc),
              datetime(2026, 2, 2, 10, tzinfo=utc), datetime(2026, 4, 30, 10, tzinfo=utc)):
        _save(t)
    out, cells = grid("week")
    assert (out["fold"], out["fold_requested"], out["span_days"]) == ("week", "week", 116)
    assert out["fold_min_days"] == {"4weeks": 90, "month_week": 180}
    assert set(cells) == {"1-08", "4-08"} and "week" not in cells["1-08"]
    # weeks counted from Monday 1970-01-05: 5 Jan and 2 Feb (4 weeks later)
    # share week 3 of the cycle, 12 Jan is week 4, 30 Apr week 3 again
    out, cells = grid("4weeks")
    assert out["fold"] == "4weeks"
    assert set(cells) == {"3.1-08", "4.1-08", "3.4-08"}
    assert cells["3.1-08"]["n"] == 2 and (cells["3.1-08"]["week"], cells["3.1-08"]["dow"]) == (3, 1)
    # weeks of the month need 180 days: shown by weekday until then
    out, cells = grid("month_week")
    assert (out["fold"], out["fold_requested"]) == ("week", "month_week") and set(cells) == {"1-08", "4-08"}
    _save(datetime(2026, 7, 31, 10, tzinfo=utc))  # a Friday, 208 days after the first run
    out, cells = grid("month_week")
    assert (out["fold"], out["span_days"]) == ("month_week", 208)
    # days 1-7 (5 Jan, 2 Feb), 8-14 (12 Jan), 29-31 (30 Apr, 31 Jul)
    assert set(cells) == {"1.1-08", "2.1-08", "5.4-08", "5.5-08"} and cells["1.1-08"]["n"] == 2
    # the span counts only the runs shown (here: none for an unknown relay)
    none, _ = grid("4weeks", keys=["nobody"])
    assert (none["fold"], none["span_days"]) == ("week", 0)
    with pytest.raises(QueryError):
        _series(bucket="dow_hour", fold="month")


def test_empty_history(data):
    assert _series()["series"] == []
    assert _runs() == 0


def test_single_run_all_null_metrics(data):
    _save(T0, score=None, risk=None, ttft=None, tps=None, billing=None, protocol=None)
    out = _series("ttft_p50")
    assert out["series"][0]["points"] == [] and out["series"][0]["coverage"] == 0.0
    (g,) = query.aggregate(history.query_connection(), Query(surface="chat"),
                           ["score", "ttft_p50", "success_rate", "risk_high_share"], "all")
    assert g.metrics["success_rate"].value == 0.9  # the one thing it measured
    assert all(g.metrics[m].value is None and g.metrics[m].n == 0
               for m in ("score", "ttft_p50", "risk_high_share"))


def test_run_time_out_of_range_is_undated(data):
    _save(datetime(1, 1, 1, 0, 30, tzinfo=UTC))
    _save(T0)
    out = _series(bucket="hour", tz="America/New_York")
    assert out["series"][0]["runs"] == 1  # the year-1 run cannot be bucketed
    assert _runs() == 2


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"metric": "nope"}, "unknown metric"),
        ({"group": "provider"}, "group must be one of"),
        ({"bucket": "month"}, "bucket must be one of"),
        ({"tz": "Mars/Olympus"}, "unknown time zone"),
        ({"tz": "../../etc/passwd"}, "unknown time zone"),
        ({"keys": ["a", "b", "c", "d", "e"]}, "at most 4 keys"),
    ],
)
def test_bad_parameters(data, kw, message):
    with pytest.raises(AnalyticsError, match=message):
        _series(**kw)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(seeded):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ekte.web.server import create_app

    return TestClient(create_app(), base_url="http://localhost")


def test_http_endpoints(client):
    # the widget endpoints on the query core (#123; tests/test_analytics_widgets.py)
    r = client.get("/api/filters/options")
    assert r.status_code == 200 and r.json()["runs"] == 17
    assert r.headers["cache-control"] == "no-cache" and r.headers["etag"]
    r = client.get("/api/analytics/summary",
                   params={"from": "2026-03-03T12:00:00+00:00", "to": "2026-03-04T12:00:00+00:00"})
    assert r.status_code == 200 and r.json()["runs"] == 5
    assert r.json()["previous"]["from"] == "2026-03-02T12:00:00.000000+00:00"
    # from alone: up to now, against the range of the same length before it
    r = client.get("/api/analytics/summary", params={"from": "2026-03-03T12:00:00Z"})
    assert r.status_code == 200 and r.json()["to"] is not None and r.json()["runs"] == 13
    r = client.get("/api/analytics/series", params=[
        ("trend.metric", "ttft_p50"), ("trend.bucket", "day"), ("trend.tz", "Europe/Berlin"),
        ("trend.key", "cheap-gpt"), ("trend.key", OTHER),
    ])
    body = r.json()
    assert r.status_code == 200 and [s["key"] for s in body["series"]] == ["cheap-gpt", OTHER]
    assert body["series"][0]["points"][0]["bucket"] == "2026-03-02T00:00:00+01:00"
    r = client.get("/api/analytics/leaderboard", params={"model": "model-a"})
    assert r.status_code == 200 and r.json()["rows"][0]["key"] == "cheap-gpt"
    for old in ("/api/analytics/options",):
        assert client.get(old).status_code == 404  # replaced by /api/filters/options


@pytest.mark.parametrize(
    ("path", "params", "message"),
    [
        ("/api/analytics/series", {"trend.metric": "x'; DROP TABLE history; --"}, "unknown metric"),
        ("/api/analytics/series", {"trend.bucket": "year"}, "bucket must be one of"),
        ("/api/analytics/summary", {"from": "2026-13-01"}, "ISO 8601"),
        ("/api/filters/options", {"from": "x"}, "ISO 8601"),
        ("/api/analytics/leaderboard", {"board.by": "all"}, "board.by must be one of"),
        ("/api/analytics/series", [("trend.key", k) for k in "abcde"], "at most 4 keys"),
    ],
)
def test_http_bad_parameters(client, path, params, message):
    r = client.get(path, params=params)
    assert r.status_code == 400 and message in r.json()["error"]
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/filters/options").json()["runs"] == 17  # nothing dropped


# Detector helpers (tests/test_analytics_widgets.py)
def _detectors(report: dict, statuses: dict, *, context: tuple[int, int] | None = None,
               returned: str | None = None) -> dict:
    for det_id, status in statuses.items():
        det = {"id": det_id, "status": status, "findings": [], "duration_ms": 100, "evidence": {}}
        if det_id == "model_identity" and returned is not None:
            det["findings"] = [{"id": "model_identity.model_field", "status": "pass",
                                "outcome": "consistent" if returned == report["target"]["model"] else "diverges",
                                "evidence": {"returned": returned}}]
        report["detectors"].append(det)
    if context is not None:
        report["detectors"].append({"id": "context_window", "status": "pass", "findings": [],
                                    "evidence": {"declared": context[0], "effective_window": context[1]}})
    return report


def test_http_phase4_endpoints(client):
    r = client.get("/api/analytics/breakdown", params=[("breakdown.metric", "relay_overhead"),
                                                       ("breakdown.metric", "network_rtt")])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers["etag"]
    assert [m["id"] for m in r.json()["metrics"]] == ["relay_overhead", "network_rtt"]
    r = client.get("/api/analytics/errors", params={"group": "model", "errors.bucket": "dow_hour",
                                                    "errors.tz": "UTC"})
    # runs with outcome counts (history_outcomes): every run but the two old-shaped ones
    assert r.status_code == 200 and r.json()["covered"] == 15 and r.json()["runs"] == 17
    r = client.get("/api/analytics/integrity", params={"model": "model-a"})
    assert r.status_code == 200 and all(row["model"] == "model-a" for row in r.json()["rows"])
    for path, params, message in [
        ("/api/analytics/breakdown", {}, "at least one breakdown.metric"),
        ("/api/analytics/breakdown", {"breakdown.metric": "x'; DROP TABLE history; --"}, "unknown metric"),
        ("/api/analytics/errors", {"group": "relays"}, "group must be one of"),
        ("/api/analytics/integrity", {"exec": "cron"}, "exec must be one of"),
    ]:
        r = client.get(path, params=params)
        assert r.status_code == 400 and message in r.json()["error"], path


def test_http_answers_are_cached_until_the_history_changes(client):
    def runs() -> int:
        return client.get("/api/analytics/summary").json()["runs"]

    before = runs()
    assert runs() == before  # served from the cache
    _save(T0 + timedelta(hours=5), score=70.0)
    assert runs() == before + 1  # a saved run drops the cached answers

# --------------------------------------------------------------------------- #
# Surfaces
# --------------------------------------------------------------------------- #
def _embed_report(started: datetime, *, base_url: str = RELAY, model: str = "emb-a",
                  latency: float = 40.0, echoed: str = "matches") -> dict:
    report = _report(started, base_url=base_url, model=model, ttft=None, tps=None, billing=None,
                     protocol=None, stream_mode="non_stream")
    report["surface"] = "embedding"
    report["performance"]["target"]["latency_ms"] = {"p50": latency}
    report["detectors"] = [
        {"id": "embed.identity", "status": "pass", "dimension": "model_identity",
         "findings": [{"id": "embed.model_field", "check": "embed.model_field", "status": "pass",
                       "outcome": echoed, "severity": "info"}]},
        {"id": "embed.drift", "status": "pass", "dimension": "model_identity", "findings": []},
    ]
    return report


def test_metrics_declare_their_surfaces():
    chat_only = {"ttft_p50", "ttft_p95", "decode_tps", "decode_tps_p5", "decode_tps_p95", "itl_jitter",
                 "concurrency_tps", "billing_ratio_prompt", "billing_ratio_completion",
                 "reasoning_share", "cached_input_share", "context_claimed", "context_effective"}
    assert {m.id for m in analytics.METRICS.values() if m.surfaces == {"chat"}} == chat_only
    emb = {m.id for m in analytics.metrics_for("embedding")}
    assert emb == set(analytics.METRICS) - chat_only
    assert {"score", "latency_p50", "cold_start", "model_mismatch_rate", "findings_high"} <= emb
    assert analytics.METRICS["latency_p50"].public()["surfaces"] == ["chat", "embedding", "rerank"]
    with pytest.raises(AnalyticsError, match="does not apply"):
        analytics.metric("ttft_p50", "embedding")
    assert analytics.metric("dim:model_identity", "embedding").unit == "score"


def test_surface_is_a_mandatory_filter(data):
    for i in range(3):
        _save(T0 + timedelta(hours=i))  # chat
    for i in range(4):
        history.save(_embed_report(T0 + timedelta(hours=i), latency=40.0 + i,
                                   echoed="differs" if i == 0 else "matches"))
    c = history.query_connection()
    # the default is the most common surface; runs never mix
    assert query.default_surface(c) == "embedding"
    assert _runs(surface="embedding") == 4 and _runs(surface="chat") == 3
    with pytest.raises(QueryError, match="surface"):
        query.parse_query({"surface": "image"})
    series = _series("latency_p50", "all", surface="embedding")
    assert series["series"][0]["runs"] == 4
    with pytest.raises(AnalyticsError, match="does not apply"):
        _series("ttft_p50", surface="embedding")
    (g,) = query.aggregate(c, Query(surface="embedding"), ["model_mismatch_rate"], "all")
    assert g.metrics["model_mismatch_rate"].value == 0.25


def test_null_surface_reads_as_chat(data):
    rid = _save(T0)
    with history._connect() as conn:
        conn.execute("UPDATE history SET surface = NULL WHERE id = ?", (rid,))
    assert query.default_surface(history.query_connection()) == "chat"
    assert _runs(surface="chat") == 1 and _runs(surface="embedding") == 0
