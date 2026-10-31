"""Analytics queries (ekte/web/analytics.py) and the /api/analytics endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ekte.knowledge import store
from ekte.knowledge.relays import add_relay
from ekte.web import analytics, history
from ekte.web.analytics import AnalyticsError

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


def test_options(seeded):
    opt = analytics.options()
    assert opt["runs"] == 17 and opt["monitor"] == 2 and opt["manual"] == 15
    assert opt["first"].startswith("2026-03-02T12:00:00") and opt["last"].startswith("2026-03-05")
    assert opt["models"] == [{"key": "model-a", "runs": 15}, {"key": "model-b", "runs": 2}]
    assert opt["suites"][0] == {"value": "standard", "runs": 16}
    assert {s["value"] for s in opt["stream_modes"]} == {"stream", "non_stream"}
    assert {a["value"] for a in opt["apis"]} == {"openai", "anthropic"}
    assert opt["dimensions"] == ["protocol"] and opt["min_runs"] == analytics.MIN_RUNS
    pairs = {p["key"]: p for p in opt["relay_models"]}
    assert sum(p["runs"] for p in pairs.values()) == 17
    assert all(p["key"] == f'{p["relay"]}|{p["model"]}' and p["kind"] == "relay_model" for p in pairs.values())
    assert opt["relay_models"][0]["runs"] == max(p["runs"] for p in pairs.values())
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
    assert out["metric"] == {"id": "ttft_p50", "unit": "ms", "higher_is_better": False, "agg": "median",
                             "surfaces": ["chat"]}
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
    assert dim["series"][0]["n"] == 14  # old-shaped reports have dimension scores too


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
    # 4-hour blocks: the 23:00, 00:00 and 02:00 runs fall into 20-24 and 00-04
    blocks = analytics.series({"metric": "score", "bucket": "dow_hour", "block": "4", "tz": "Europe/Berlin"})
    assert blocks["block"] == 4
    cells = {p["bucket"]: p for p in blocks["series"][0]["points"]}
    assert set(cells) == {"6-20", "7-00", "1-00"}
    assert cells["7-00"]["n"] == 3 and (cells["7-00"]["hour"], cells["7-00"]["hours"]) == (0, 4)
    assert "hours" not in heat["series"][0]["points"][0]
    with pytest.raises(analytics.AnalyticsError):
        analytics.series({"bucket": "dow_hour", "block": "5"})


def test_dow_hour_folds_into_4_week_cycles_and_weeks_of_the_month(data):
    utc = UTC

    def grid(fold):
        out = analytics.series({"metric": "score", "bucket": "dow_hour", "block": "4", "fold": fold, "tz": "UTC"})
        return out, {p["bucket"]: p for p in out["series"][0]["points"]}

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
    none = analytics.series({"bucket": "dow_hour", "fold": "4weeks", "group": "relay"}, ["nobody"])
    assert (none["fold"], none["span_days"]) == ("week", 0)
    with pytest.raises(analytics.AnalyticsError):
        analytics.series({"bucket": "dow_hour", "fold": "month"})


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
    assert k["success_rate"]["value"] == 0.9  # the one thing it measured
    assert all(k[m]["value"] is None and k[m]["n"] == 0
               for m in analytics.SUMMARY_KPIS if m != "success_rate")


def test_run_time_out_of_range_is_undated(data):
    _save(datetime(1, 1, 1, 0, 30, tzinfo=UTC))
    _save(T0)
    out = analytics.series({"metric": "score", "tz": "America/New_York", "bucket": "hour"})
    assert out["series"][0]["runs"] == 1  # the year-1 run cannot be bucketed
    assert analytics.summary({})["runs"] == 2
    assert analytics.summary({"from": "0001-01-01T00:00:00Z", "to": "2026-04-01T00:00:00Z"})["runs"] == 2


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

    from ekte.web.server import create_app

    return TestClient(create_app(), base_url="http://localhost")


def test_http_endpoints(client):
    r = client.get("/api/analytics/options")
    assert r.status_code == 200 and r.json()["runs"] == 17
    assert r.headers["cache-control"] == "no-store"
    r = client.get("/api/analytics/summary",
                   params={"from": "2026-03-03T12:00:00+00:00", "to": "2026-03-04T12:00:00+00:00"})
    assert r.status_code == 200 and r.json()["runs"] == 5
    assert r.json()["previous"]["from"] == "2026-03-02T12:00:00.000000+00:00"
    # from alone: up to now, against the range of the same length before it
    r = client.get("/api/analytics/summary", params={"from": "2026-03-03T12:00:00Z"})
    assert r.status_code == 200 and r.json()["to"] is not None and r.json()["runs"] == 13
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


# --------------------------------------------------------------------------- #
# Errors, integrity, breakdown (phase 4)
# --------------------------------------------------------------------------- #
def _rec(seq: int, start_ms: float, *, ok: bool = True, status: int | None = 200,
         error_type: str | None = None, endpoint: str = "target", op: str = "complete") -> dict:
    return {
        "seq": seq, "endpoint": endpoint, "op": op, "start_ms": start_ms, "ok": ok,
        "status_code": status, "error_type": error_type,
        "timeout": bool(error_type and "timeout" in error_type.lower()),
        "rate_limited": status == 429, "duration_ms": 500.0,
    }


def _with_requests(started, records, **kw) -> int:
    report = _report(started, **kw)
    report["performance"]["requests"] = records
    rid = history.save(report)
    assert rid > 0
    return rid


@pytest.fixture
def requests_seeded(data):
    add_relay("Cheap GPT", RELAY)
    # 10:59:50 Berlin (09:59:50 UTC): the second minute of calls lands in the next hour
    start = datetime(2026, 3, 2, 9, 59, 50, tzinfo=UTC)
    _with_requests(start, [
        _rec(0, 0), _rec(1, 1000), _rec(2, 2000, ok=False, status=429, error_type="http_error"),
        _rec(3, 61_000, ok=False, status=503, error_type="http_error"),
        _rec(4, 62_000, ok=False, status=None, error_type="ReadTimeout"),
        _rec(5, 63_000, ok=False, status=None, error_type="ConnectError"),
        _rec(6, 64_000, ok=False, status=400, error_type="http_error"),
        _rec(7, 65_000, ok=False, status=200, error_type=None),
        _rec(8, 66_000, op="list_models"),  # not a completion call
        _rec(9, 67_000, endpoint="baseline", ok=False, status=500, error_type="http_error"),
    ])
    _with_requests(T0 + timedelta(days=1), [_rec(0, 0), _rec(1, 10)], base_url=OTHER, model="model-b")
    # an old-shaped run (no request records) and one with an empty list
    _save(T0 + timedelta(days=1, hours=1), base_url=RELAY, old=True)
    _save(T0 + timedelta(days=1, hours=2), base_url=RELAY)
    return data


def test_errors_counts_by_class_group_and_coverage(requests_seeded):
    out = analytics.errors({"tz": "Europe/Berlin", "bucket": "hour"})
    assert out["classes"][0] == "success" and out["runs"] == 4 and out["covered"] == 2
    assert out["coverage"] == 0.5
    counts = out["totals"]["counts"]
    assert counts == {"success": 4, "client_4xx": 1, "rate_limited": 1, "server_5xx": 1,
                      "timeout": 1, "network": 1, "other": 1}
    assert out["totals"]["requests"] == 10 and out["totals"]["errors"] == 6
    assert out["totals"]["rate_limited_share"] == pytest.approx(0.1)
    assert out["totals"]["timeout_share"] == pytest.approx(0.1)
    relay = out["groups"][0]
    assert relay["key"] == "cheap-gpt" and relay["runs"] == 3 and relay["covered"] == 1
    assert relay["requests"] == 8 and relay["low_n"] is True
    assert relay["error_share"] == pytest.approx(6 / 8)
    # Berlin hours: 10:59:50 + 0 min -> 10:00; + 1 min -> 11:00
    buckets = {b["bucket"]: b for b in out["buckets"]}
    assert buckets["2026-03-02T10:00:00+01:00"]["counts"]["success"] == 2
    assert buckets["2026-03-02T10:00:00+01:00"]["counts"]["rate_limited"] == 1
    assert buckets["2026-03-02T11:00:00+01:00"]["errors"] == 5
    assert all(b["low_n"] and b["runs"] == 1 for b in out["buckets"])


def test_errors_group_model_dow_hour_and_filters(requests_seeded):
    out = analytics.errors({"group": "model", "bucket": "dow_hour", "tz_offset": "0"})
    assert [g["key"] for g in out["groups"]] == ["model-a", "model-b"]
    assert {(b["dow"], b["hour"]) for b in out["buckets"]} == {(1, 9), (1, 10), (2, 12)}
    six = analytics.errors({"group": "model", "bucket": "dow_hour", "block": "6", "tz_offset": "0"})
    assert {(b["dow"], b["hour"], b["hours"]) for b in six["buckets"]} == {(1, 6, 6), (2, 12, 6)}
    only = analytics.errors({"relay": OTHER})
    assert only["runs"] == 1 and only["totals"]["requests"] == 2 and only["totals"]["error_share"] == 0
    none = analytics.errors({"from": "2027-01-01T00:00:00Z", "to": "2027-02-01T00:00:00Z"})
    assert none["runs"] == 0 and none["coverage"] is None and none["totals"]["error_share"] is None
    assert none["groups"] == [] and none["buckets"] == []


def test_errors_never_loads_request_rows(requests_seeded, monkeypatch):
    monkeypatch.setattr(history, "analytics_requests", lambda *a, **k: pytest.fail("loaded rows"))
    assert analytics.errors({})["totals"]["requests"] == 10


@pytest.mark.parametrize("params", [{"group": "relay_model"}, {"bucket": "month"}, {"tz": "Nowhere/x"}])
def test_errors_bad_parameters(data, params):
    with pytest.raises(AnalyticsError):
        analytics.errors(params)


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


def test_integrity_matrix(data):
    add_relay("Cheap GPT", RELAY)
    plan = [
        ({"model_identity": "pass", "capability": "pass", "vision": "fail"}, (128_000, 64_000), "model-a"),
        ({"model_identity": "warn", "capability": "pass", "vision": "inconclusive"}, (128_000, 128_000), "other"),
        ({"model_identity": "pass", "capability": "fail"}, None, "model-a"),
    ]
    for i, (statuses, context, returned) in enumerate(plan):
        history.save(_detectors(_report(T0 + timedelta(hours=i)), statuses, context=context, returned=returned))
    history.save(_detectors(_report(T0, base_url=OTHER, model="model-b"), {"streaming": "pass"}))
    _save(T0 + timedelta(hours=5), old=True)  # no detectors at all

    out = analytics.integrity({})
    assert out["checks"] == ["model_identity", "capability", "vision", "streaming"]
    row = out["rows"][0]
    assert row["key"] == "cheap-gpt|model-a" and row["runs"] == 4
    ident = row["checks"]["model_identity"]
    assert (ident["pass"], ident["warn"], ident["fail"], ident["n"]) == (2, 1, 0, 3)
    assert ident["pass_rate"] == pytest.approx(2 / 3) and ident["low_n"] is False
    vision = row["checks"]["vision"]
    assert (vision["fail"], vision["other"], vision["n"], vision["low_n"]) == (1, 1, 1, True)
    assert row["checks"]["streaming"]["n"] == 0 and row["checks"]["streaming"]["pass_rate"] is None
    assert row["model_mismatch"]["value"] == pytest.approx(1 / 3) and row["model_mismatch"]["n"] == 3
    assert row["context"]["value"] == pytest.approx(0.75) and row["context"]["n"] == 2
    assert row["context"]["claimed"] == 128_000 and row["context"]["coverage"] == 0.5
    other = out["rows"][1]
    assert other["key"] == f"{OTHER}|model-b" and other["checks"]["streaming"]["pass"] == 1
    assert other["context"]["value"] is None and other["model_mismatch"]["value"] is None


def test_integrity_empty(data):
    assert analytics.integrity({}) == {"from": None, "to": None, "min_runs": 3, "runs": 0, "checks": [],
                                          "has_context": False, "rows": []}


def test_breakdown(seeded):
    out = analytics.breakdown({}, ["billing_ratio_prompt", "ttft_p50", "ttft_p50", ""])
    assert [m["id"] for m in out["metrics"]] == ["billing_ratio_prompt", "ttft_p50"]
    row = out["rows"][0]
    assert row["key"] == "cheap-gpt" and row["runs"] == 14
    ttft = row["metrics"]["ttft_p50"]
    assert ttft["n"] == 12 and ttft["median"] == 200.0 and ttft["coverage"] == pytest.approx(12 / 14)
    assert analytics.breakdown({"group": "all"}, ["score"])["rows"][0]["key"] == analytics.ALL_KEY
    assert [r["key"] for r in analytics.breakdown({"group": "model"}, ["dim:protocol"])["rows"]] == ["model-a", "model-b"]
    with pytest.raises(AnalyticsError):
        analytics.breakdown({}, [])
    with pytest.raises(AnalyticsError):
        analytics.breakdown({}, ["nope"])
    with pytest.raises(AnalyticsError):
        analytics.breakdown({}, list(analytics.METRICS)[:9])


def test_series_group_all(seeded):
    out = analytics.series({"group": "all", "metric": "score", "bucket": "dow_hour", "tz_offset": "0"})
    assert len(out["series"]) == 1 and out["series"][0]["key"] == analytics.ALL_KEY
    assert out["series"][0]["runs"] == 17 - 2 + 2  # every run (old ones dated by generated_at)


def test_http_phase4_endpoints(client):
    r = client.get("/api/analytics/breakdown", params=[("metrics", "relay_overhead"), ("metrics", "network_rtt")])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert [m["id"] for m in r.json()["metrics"]] == ["relay_overhead", "network_rtt"]
    r = client.get("/api/analytics/errors", params={"group": "model", "bucket": "dow_hour", "tz": "UTC"})
    assert r.status_code == 200 and r.json()["covered"] == 0 and r.json()["runs"] == 17
    r = client.get("/api/analytics/integrity", params={"model": "model-a"})
    assert r.status_code == 200 and all(row["model"] == "model-a" for row in r.json()["rows"])
    for path, params, message in [
        ("/api/analytics/breakdown", {}, "at least one metric"),
        ("/api/analytics/breakdown", {"metrics": "x'; DROP TABLE history; --"}, "unknown metric"),
        ("/api/analytics/errors", {"group": "relay_model"}, "group must be one of"),
        ("/api/analytics/integrity", {"source": "cron"}, "source must be one of"),
    ]:
        r = client.get(path, params=params)
        assert r.status_code == 400 and message in r.json()["error"], path


def test_http_answers_are_cached_until_the_history_changes(client):
    def runs() -> int:
        return client.get("/api/analytics/summary", params={"range": "all"}).json()["runs"]

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
    # the default is the most common surface; runs never mix
    assert analytics.default_surface() == "embedding"
    assert analytics.summary({})["runs"] == 4 and analytics.summary({})["surface"] == "embedding"
    assert analytics.summary({"surface": "chat"})["runs"] == 3
    with pytest.raises(AnalyticsError, match="surface"):
        analytics.parse_filters({"surface": "image"})

    opts = analytics.options()
    assert opts["surface"] == "embedding" and opts["runs"] == 4
    assert opts["surfaces"] == [{"value": "embedding", "runs": 4}, {"value": "chat", "runs": 3}]
    assert opts["stream_modes"] == [{"value": "non_stream", "runs": 4}]
    ids = {m["id"] for m in opts["metrics"]}
    assert "latency_p50" in ids and "ttft_p50" not in ids and "billing_ratio_prompt" not in ids
    assert "ttft_p50" in {m["id"] for m in analytics.options({"surface": "chat"})["metrics"]}

    kpis = analytics.summary({"surface": "embedding"})["kpis"]
    assert "ttft_p50" not in kpis and "billing_ratio_prompt" not in kpis and "score" in kpis
    assert "ttft_p50" in analytics.summary({"surface": "chat"})["kpis"]
    series = analytics.series({"surface": "embedding", "metric": "latency_p50", "group": "all"})
    assert series["series"][0]["runs"] == 4
    with pytest.raises(AnalyticsError, match="does not apply"):
        analytics.series({"surface": "embedding", "metric": "ttft_p50"})
    board = analytics.leaderboard({"surface": "embedding", "model": "emb-a"})
    assert [m["id"] for m in board["metrics"]] == [
        "score", "success_rate", "model_mismatch_rate", "risk_high_share"]
    assert board["rows"][0]["metrics"]["model_mismatch_rate"]["value"] == 0.25

    integ = analytics.integrity({"surface": "embedding"})
    assert integ["checks"] == ["embed.identity", "embed.drift"] and integ["has_context"] is False
    assert integ["rows"][0]["checks"]["embed.identity"]["pass"] == 4
    assert analytics.integrity({"surface": "chat"})["runs"] == 3


def test_null_surface_reads_as_chat(data):
    rid = _save(T0)
    with history._connect() as conn:
        conn.execute("UPDATE history SET surface = NULL WHERE id = ?", (rid,))
    assert history.surface_counts() == {"chat": 1}
    assert analytics.default_surface() == "chat"
    assert analytics.summary({"surface": "chat"})["runs"] == 1
    assert analytics.summary({"surface": "embedding"})["runs"] == 0


def test_embedding_errors_count_embed_calls(data):
    report = _embed_report(T0)
    report["performance"]["requests"] = [
        {"seq": i, "endpoint": "target", "op": "embed", "phase": "probe", "ok": i > 0,
         "status_code": 200 if i else 500, "start_ms": 10.0 * i} for i in range(3)
    ]
    history.save(report)
    out = analytics.errors({"surface": "embedding"})
    assert out["totals"]["counts"]["success"] == 2 and out["totals"]["counts"]["server_5xx"] == 1
    assert analytics.errors({"surface": "chat"})["covered"] == 0
