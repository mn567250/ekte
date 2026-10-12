"""Analytics queries (zing/web/analytics.py) and the /api/analytics endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from zing.knowledge import store
from zing.knowledge.relays import add_relay
from zing.web import analytics, history
from zing.web.analytics import AnalyticsError

OPENAI = "https://api.openai.com/v1"
RELAY = "https://relay.example/v1"
OTHER = "https://other.example/v1"
T0 = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)  # a Monday


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
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
    tool_version: str = "0.20.0",
    kb_hash: str | None = "kb1",
    ttft: float | None = 300.0,
    tps: float | None = 50.0,
    billing: tuple[float, float] | None = (1.0, 1.0),
    protocol: float | None = 90.0,
    old: bool = False,
) -> dict:
    """A report as save() gets it; ``old`` drops what older zing versions lacked."""
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
    m = analytics.METRICS["ttft_p50"]
    agg = analytics.aggregate(m, [None, 4.0, 1.0, None, 3.0, 2.0])
    assert agg == {"value": 2.5, "median": 2.5, "p25": 1.75, "p75": 3.25, "n": 4}
    share = analytics.aggregate(analytics.METRICS["risk_high_share"], [1.0, 0.0, 0.0, None, 1.0])
    assert share == {"value": 0.5, "median": None, "p25": None, "p75": None, "n": 4}
    assert analytics.aggregate(m, [None, None])["value"] is None


def test_metric_whitelist():
    assert analytics.metric("ttft_p50").column == "ttft_p50_ms"
    assert analytics.metric("dim:protocol").unit == "score"
    for bad in ("", "ttft_p50_ms", "score; DROP TABLE history", "dim:", "dim:a b", "dim:" + "x" * 65):
        with pytest.raises(AnalyticsError):
            analytics.metric(bad)
    run = {"risk_level": "high", "model_mismatch": 0, "score": 70.0, "ttft_p50_ms": None}
    assert analytics.run_value(analytics.METRICS["risk_high_share"], run) == 1.0
    assert analytics.run_value(analytics.METRICS["model_mismatch_rate"], run) == 0.0
    assert analytics.run_value(analytics.METRICS["ttft_p50"], run) is None  # never 0
    assert analytics.run_value(analytics.METRICS["risk_high_share"], {"risk_level": None}) is None


# --------------------------------------------------------------------------- #
# Relay grouping
# --------------------------------------------------------------------------- #
def test_relays_grouped_by_knowledge_base_entry_at_query_time(data):
    add_relay("Cheap GPT", RELAY)
    _save(T0, base_url=OPENAI + "/chat/completions")
    _save(T0 + timedelta(hours=1), base_url=RELAY + "/")
    _save(T0 + timedelta(hours=2), base_url=RELAY)
    _save(T0 + timedelta(hours=3), base_url=OTHER)
    relays = {r["key"]: r for r in analytics.options()["relays"]}
    assert relays["openai"] == {"key": "openai", "label": "OpenAI", "in_kb": True,
                                "kind": "provider", "runs": 1}
    assert relays["cheap-gpt"] == {"key": "cheap-gpt", "label": "Cheap GPT", "in_kb": True,
                                   "kind": "relay", "runs": 2}
    assert relays[OTHER] == {"key": OTHER, "label": OTHER, "in_kb": False, "kind": "url", "runs": 1}
    assert [r["key"] for r in analytics.options()["relays"]][0] == "cheap-gpt"  # most runs first

    # Renaming the relay relabels its history; saving one re-groups old runs.
    entry = store.find("provider", "cheap-gpt")
    store.upsert("provider", "cheap-gpt", {**entry["body"], "display_name": "Budget GPT"}, origin="relay")
    add_relay("Other Relay", OTHER)
    relays = {r["key"]: r for r in analytics.options()["relays"]}
    assert relays["cheap-gpt"]["label"] == "Budget GPT"
    assert relays["other-relay"]["in_kb"] and relays["other-relay"]["runs"] == 1
    assert OTHER not in relays
    out = analytics.series({"group": "relay", "relay": "other-relay"})
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
                  score=70.0 + i, tool_version="0.19.2" if day < 2 else "0.20.0",
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


def test_options(seeded):
    opt = analytics.options()
    assert opt["runs"] == 17 and opt["monitor"] == 2 and opt["manual"] == 15
    assert opt["first"].startswith("2026-03-02T12:00:00") and opt["last"].startswith("2026-03-05")
    assert opt["models"] == [{"key": "model-a", "runs": 15}, {"key": "model-b", "runs": 2}]
    assert opt["suites"][0] == {"value": "standard", "runs": 16}
    assert {s["value"] for s in opt["stream_modes"]} == {"stream", "non_stream"}
    assert {a["value"] for a in opt["apis"]} == {"openai", "anthropic"}
    assert opt["dimensions"] == ["protocol"] and opt["min_runs"] == analytics.MIN_RUNS
    assert {m["id"] for m in opt["metrics"]} >= {"score", "ttft_p50", "billing_ratio_prompt"}
    assert analytics.options({"from": _iso(T0 + timedelta(days=3))})["runs"] == 3


def test_filters(seeded):
    def runs(**params):
        return analytics.summary(params)["runs"]

    assert runs() == 17
    assert runs(source="monitor") == 2 and runs(source="manual") == 15
    assert runs(suite="quick") == 1 and runs(stream_mode="non_stream") == 1
    assert runs(api="anthropic") == 1 and runs(model="model-b") == 2
    assert runs(relay="cheap-gpt") == 14 and runs(relay=OTHER) == 1 and runs(relay="nope") == 0
    assert runs(**{"from": _iso(T0 + timedelta(days=1)), "to": _iso(T0 + timedelta(days=2))}) == 5
    assert runs(**{"from": "2026-03-03T12:00:00Z", "to": "2026-03-04T12:00:00Z"}) == 5


def test_series_daily_with_coverage_low_n_mixed_and_annotations(seeded):
    out = analytics.series({"metric": "ttft_p50", "group": "relay", "bucket": "day"})
    assert out["metric"] == {"id": "ttft_p50", "unit": "ms", "higher_is_better": False, "agg": "median"}
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
        ("tool_version", "0.19.2", "0.20.0", "2026-03-04T00:00:00+00:00"),
        ("kb_profile", "kb1", "kb2", "2026-03-05T00:00:00+00:00"),
    ]
    openai = out["series"][1]
    assert openai["mixed"] == {"suite": True, "stream_mode": True, "api": False}
    assert all(p["low_n"] for p in openai["points"]) and openai["points"][0]["n"] == 1


def test_series_keys_groups_and_share_metric(seeded):
    out = analytics.series({"metric": "risk_high_share", "group": "model", "bucket": "week"},
                           ["model-b", "missing"])
    b, missing = out["series"]
    assert b["key"] == "model-b" and b["in_kb"] is True
    assert b["points"] == [{"bucket": "2026-03-02T00:00:00+00:00", "runs": 2, "value": 0.5,
                            "median": None, "p25": None, "p75": None, "n": 2, "low_n": True}]
    assert missing["runs"] == 0 and missing["points"] == [] and missing["coverage"] is None
    both = analytics.series({"group": "relay_model"})
    assert both["series"][0]["key"] == "cheap-gpt|model-a"
    assert both["series"][0]["label"] == "Cheap GPT · model-a"
    dim = analytics.series({"metric": "dim:protocol", "relay": "cheap-gpt", "bucket": "week"})
    assert dim["series"][0]["points"][0]["median"] == 90.0
    assert dim["series"][0]["n"] == 12  # the old reports carry no dimensions here


def test_series_score_keeps_old_runs(seeded):
    """Old-shaped runs still contribute what they have (their score)."""
    out = analytics.series({"metric": "score", "relay": "cheap-gpt"})
    relay = out["series"][0]
    assert relay["n"] == 13 and relay["runs"] == 14  # one old run has no score
    assert relay["points"][2]["n"] == 4


# --------------------------------------------------------------------------- #
# Time zones
# --------------------------------------------------------------------------- #
def test_buckets_in_viewer_time_zone_across_dst_and_midnight(data):
    utc = timezone.utc
    times = [
        datetime(2026, 3, 28, 22, 30, tzinfo=utc),  # Sat 23:30 CET
        datetime(2026, 3, 28, 23, 30, tzinfo=utc),  # Sun 00:30 CET
        datetime(2026, 3, 29, 22, 30, tzinfo=utc),  # Mon 00:30 CEST (after spring forward)
        datetime(2026, 10, 25, 0, 30, tzinfo=utc),  # 02:30 CEST
        datetime(2026, 10, 25, 1, 30, tzinfo=utc),  # 02:30 CET (after fall back)
    ]
    for t in times:
        _save(t)

    def buckets(**params):
        out = analytics.series({"metric": "score", **params})
        return [p["bucket"] for p in out["series"][0]["points"]]

    assert buckets(bucket="day", tz="Europe/Berlin") == [
        "2026-03-28T00:00:00+01:00", "2026-03-29T00:00:00+01:00",
        "2026-03-30T00:00:00+02:00", "2026-10-25T00:00:00+02:00",
    ]
    assert buckets(bucket="day") == [
        "2026-03-28T00:00:00+00:00", "2026-03-29T00:00:00+00:00", "2026-10-25T00:00:00+00:00",
    ]
    hours = buckets(bucket="hour", tz="Europe/Berlin")
    assert hours[-2:] == ["2026-10-25T02:00:00+02:00", "2026-10-25T02:00:00+01:00"]
    assert buckets(bucket="week", tz="Europe/Berlin")[:2] == [
        "2026-03-23T00:00:00+01:00", "2026-03-30T00:00:00+02:00",
    ]
    assert buckets(bucket="day", tz_offset="-300")[0] == "2026-03-28T00:00:00-05:00"
    # An unknown zone falls back to the offset when one is given.
    assert buckets(bucket="day", tz="Mars/Olympus", tz_offset="60")[0] == "2026-03-28T00:00:00+01:00"
    heat = analytics.series({"metric": "score", "bucket": "dow_hour", "tz": "Europe/Berlin"})
    cells = {p["bucket"]: p for p in heat["series"][0]["points"]}
    assert set(cells) == {"6-23", "7-00", "1-00", "7-02"}
    assert cells["7-02"]["n"] == 2 and (cells["7-02"]["dow"], cells["7-02"]["hour"]) == (7, 2)
    assert heat["series"][0]["annotations"] == []


# --------------------------------------------------------------------------- #
# Summary and leaderboard
# --------------------------------------------------------------------------- #
def test_summary_against_previous_range(data):
    for i in range(4):  # previous week
        _save(T0 + timedelta(days=i), score=60.0 + i, ttft=400.0)
    for i in range(3):  # this week
        _save(T0 + timedelta(days=7 + i), score=80.0 + i, ttft=None if i else 200.0,
              base_url=OTHER if i == 2 else RELAY, risk="high" if i == 0 else "clean")
    out = analytics.summary({"from": _iso(T0 + timedelta(days=7)), "to": _iso(T0 + timedelta(days=14))})
    assert out["previous"] == {"from": "2026-03-02T12:00:00.000000+00:00",
                               "to": "2026-03-09T12:00:00.000000+00:00"}
    k = out["kpis"]
    assert out["runs"] == 3 and k["runs"]["value"] == 3 and k["runs"]["previous"] == 4
    assert k["runs"]["delta"] == -1
    assert k["relays"]["value"] == 2 and k["models"]["value"] == 1
    assert k["score"]["value"] == 81.0 and k["score"]["previous"] == 61.5
    assert k["score"]["delta"] == pytest.approx(19.5)
    assert k["ttft_p50"]["value"] == 200.0 and k["ttft_p50"]["n"] == 1
    assert k["ttft_p50"]["coverage"] == pytest.approx(1 / 3) and k["ttft_p50"]["previous"] == 400.0
    assert k["risk_high_share"]["value"] == pytest.approx(1 / 3)
    assert k["risk_high_share"]["previous"] == 0.0
    assert k["billing_ratio_prompt"]["value"] == 1.0 and k["success_rate"]["value"] == 0.9
    assert k["decode_tps"]["unit"] == "tok/s"

    whole = analytics.summary({})
    assert whole["previous"] is None and whole["runs"] == 7
    assert whole["kpis"]["score"]["previous"] is None and whole["kpis"]["score"]["delta"] is None


def test_leaderboard(seeded):
    by_relay = analytics.leaderboard({"model": "model-a"})
    assert by_relay["by"] == "relay"
    rows = by_relay["rows"]
    assert [r["key"] for r in rows] == ["cheap-gpt", OTHER]  # best median score first
    top = rows[0]
    assert top["runs"] == 14 and top["low_n"] is False and top["last_run"].startswith("2026-03-05")
    assert top["metrics"]["score"] == {"value": 71.0, "n": 13, "coverage": pytest.approx(13 / 14)}
    assert top["metrics"]["ttft_p50"]["n"] == 12
    assert rows[1]["low_n"] is True and rows[1]["metrics"]["risk_high_share"]["value"] == 1.0
    assert rows[1]["metrics"]["model_mismatch_rate"] == {"value": None, "n": 0, "coverage": 0.0}

    by_model = analytics.leaderboard({"relay": "openai"})
    assert by_model["by"] == "model" and [r["key"] for r in by_model["rows"]] == ["model-b"]
    for bad in ({}, {"model": "model-a", "relay": "openai"}):
        with pytest.raises(AnalyticsError):
            analytics.leaderboard(bad)


def test_empty_history(data):
    assert analytics.options()["runs"] == 0 and analytics.options()["first"] is None
    out = analytics.summary({"from": "2026-01-01T00:00:00Z"})
    assert out["runs"] == 0 and out["kpis"]["score"]["value"] is None
    assert out["kpis"]["runs"]["coverage"] is None
    assert analytics.series({})["series"] == []
    assert analytics.leaderboard({"model": "x"})["rows"] == []


def test_single_run_all_null_metrics(data):
    _save(T0, score=None, risk=None, ttft=None, tps=None, billing=None, protocol=None)
    out = analytics.series({"metric": "ttft_p50"})
    assert out["series"][0]["points"] == [] and out["series"][0]["coverage"] == 0.0
    k = analytics.summary({})["kpis"]
    assert k["runs"]["value"] == 1
    assert all(k[m]["value"] is None and k[m]["n"] == 0 for m in analytics.SUMMARY_KPIS)


@pytest.mark.parametrize(
    "params",
    [
        {"metric": "nope"},
        {"group": "provider"},
        {"bucket": "month"},
        {"source": "cron"},
        {"from": "yesterday"},
        {"from": "2026-03-02T00:00:00Z", "to": "2026-03-01T00:00:00Z"},
        {"tz": "Mars/Olympus"},
        {"tz": "../../etc/passwd"},
        {"tz_offset": "abc"},
        {"tz_offset": "900"},
        {"suite": "x" * (analytics.MAX_PARAM + 1)},
    ],
)
def test_bad_parameters(data, params):
    with pytest.raises(AnalyticsError):
        analytics.series(params)


def test_too_many_keys(data):
    with pytest.raises(AnalyticsError):
        analytics.series({}, ["a", "b", "c", "d", "e"])
    assert len(analytics.series({}, ["a", "b", "a", "c", "d"])["series"]) == 4  # duplicates once


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(seeded):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from zing.web.server import create_app

    return TestClient(create_app(), base_url="http://localhost")


def test_http_endpoints(client):
    r = client.get("/api/analytics/options")
    assert r.status_code == 200 and r.json()["runs"] == 17
    assert r.headers["cache-control"] == "no-store"
    r = client.get("/api/analytics/summary", params={"from": "2026-03-03T12:00:00+00:00"})
    assert r.status_code == 200 and r.json()["previous"]["from"].startswith("2026-03-")
    r = client.get("/api/analytics/series", params=[
        ("metric", "ttft_p50"), ("bucket", "day"), ("tz", "Europe/Berlin"),
        ("keys", "cheap-gpt"), ("keys", OTHER),
    ])
    body = r.json()
    assert r.status_code == 200 and [s["key"] for s in body["series"]] == ["cheap-gpt", OTHER]
    assert body["series"][0]["points"][0]["bucket"] == "2026-03-02T00:00:00+01:00"
    r = client.get("/api/analytics/leaderboard", params={"model": "model-a"})
    assert r.status_code == 200 and r.json()["rows"][0]["key"] == "cheap-gpt"


@pytest.mark.parametrize(
    ("path", "params", "message"),
    [
        ("/api/analytics/series", {"metric": "x'; DROP TABLE history; --"}, "unknown metric"),
        ("/api/analytics/series", {"bucket": "year"}, "bucket must be one of"),
        ("/api/analytics/summary", {"from": "2026-13-01"}, "ISO 8601"),
        ("/api/analytics/options", {"from": "x"}, "ISO 8601"),
        ("/api/analytics/leaderboard", {}, "either model or relay"),
        ("/api/analytics/series", [("keys", k) for k in "abcde"], "at most 4 keys"),
    ],
)
def test_http_bad_parameters(client, path, params, message):
    r = client.get(path, params=params)
    assert r.status_code == 400 and message in r.json()["error"]
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/analytics/options").json()["runs"] == 17  # nothing dropped
