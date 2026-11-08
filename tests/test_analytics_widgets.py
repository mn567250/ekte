"""The Analytics widget endpoints on the query core (ekte/web/analytics_widgets.py):
/api/analytics/* and /api/filters/options."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from ekte import errorclass
from ekte.knowledge.relays import add_relay
from ekte.web import analytics, analytics_widgets, cache, history, metrics
from ekte.web.analytics_widgets import (
    filter_options,
    widget_breakdown,
    widget_errors,
    widget_heatmap,
    widget_integrity,
    widget_leaderboard,
    widget_series,
    widget_summary,
)
from ekte.web.query import QueryError
from tests.test_analytics import OPENAI, OTHER, RELAY, T0, _detectors, _embed_report, _report
from tests.test_query import _save, data, seeded  # noqa: F401  (fixtures)

pytest.importorskip("fastapi")

# Every endpoint, with parameters that exercise it (also the benchmark's cases).
WIDGET_CASES = [
    ("filters/options", filter_options, {"surface": "chat"}),
    ("filters/options, filtered", filter_options, {"exec": "manual", "risk": "clean"}),
    ("summary, 30d", widget_summary, {"from": "2026-10-01T00:00:00Z", "to": "2026-10-31T00:00:00Z"}),
    ("summary, all", widget_summary, {}),
    ("series score, day", widget_series, {"trend.tz": "Europe/Berlin"}),
    ("series error_rate, week", widget_series, {"trend.metric": "error_rate", "trend.bucket": "week",
                                                "group": "model"}),
    ("heatmap latency", widget_heatmap, {"heat.metric": "latency_p50", "heat.block": "2",
                                         "heat.tz": "Asia/Shanghai"}),
    ("leaderboard, by relay", widget_leaderboard, {"surface": "chat"}),
    ("leaderboard, relay x model", widget_leaderboard, {"board.by": "relay_model"}),
    ("breakdown", widget_breakdown, {"breakdown.metric": ["relay_overhead", "network_rtt"]}),
    ("errors, day", widget_errors, {"errors.tz": "Europe/Berlin"}),
    ("errors, dow_hour by model", widget_errors, {"errors.bucket": "dow_hour", "group": "model"}),
    ("integrity", widget_integrity, {}),
]
PATHS = {
    filter_options: "/api/filters/options", widget_summary: "/api/analytics/summary",
    widget_series: "/api/analytics/series", widget_heatmap: "/api/analytics/heatmap",
    widget_leaderboard: "/api/analytics/leaderboard", widget_breakdown: "/api/analytics/breakdown",
    widget_errors: "/api/analytics/errors", widget_integrity: "/api/analytics/integrity",
}


@pytest.fixture
def client(data):  # noqa: F811
    from fastapi.testclient import TestClient

    from ekte.web.server import create_app

    cache.default_cache.clear()
    return TestClient(create_app(), base_url="http://localhost")


def _get(client, path, params=None, status=200):
    r = client.get(path, params=params or {})
    assert r.status_code == status, (path, r.text)
    return r.json()


# --------------------------------------------------------------------------- #
# Every endpoint
# --------------------------------------------------------------------------- #
def test_every_endpoint_answers_caches_and_revalidates(seeded, client):  # noqa: F811
    for name, fn, params in WIDGET_CASES:
        r = client.get(PATHS[fn], params=params)
        assert r.status_code == 200, (name, r.text)
        assert r.headers["cache-control"] == "no-cache" and r.headers["etag"]
        again = client.get(PATHS[fn], params=params, headers={"If-None-Match": r.headers["etag"]})
        assert again.status_code == 304 and not again.content, name


@pytest.mark.parametrize("path", sorted(PATHS.values()))
def test_every_endpoint_rejects_unknown_and_bad_keys(seeded, client, path):  # noqa: F811
    assert "unknown parameter 'bogus'" in _get(client, path, {"bogus": "1"}, 400)["error"]
    assert "surface must be one of" in _get(client, path, {"surface": "image"}, 400)["error"]
    assert "ISO 8601" in _get(client, path, {"from": "2026-13-01"}, 400)["error"]
    ns = {"/api/analytics/summary": "kpi", "/api/analytics/series": "trend",
          "/api/analytics/heatmap": "heat", "/api/analytics/leaderboard": "board",
          "/api/analytics/breakdown": "breakdown", "/api/analytics/errors": "errors",
          "/api/analytics/integrity": "integrity"}.get(path)
    if ns:
        assert f"unknown parameter '{ns}.bogus'" in _get(client, path, {f"{ns}.bogus": "1"}, 400)["error"]
        # another widget's keys are not this one's business
        other = "kpi" if ns != "kpi" else "trend"
        r = client.get(path, params={f"{other}.x": "1", **(
            {"breakdown.metric": "score"} if ns == "breakdown" else {})})
        assert r.status_code == 200


def test_no_endpoint_uses_the_python_path(seeded, monkeypatch):  # noqa: F811
    for name in ("_load", "_load_all", "_matches", "_prepare"):
        monkeypatch.setattr(analytics, name, lambda *a, _n=name, **k: pytest.fail(f"called {_n}"))
    monkeypatch.setattr(history, "analytics_runs", lambda *a, **k: pytest.fail("loaded runs"))
    monkeypatch.setattr(history, "analytics_requests", lambda *a, **k: pytest.fail("loaded requests"))
    for _, fn, params in WIDGET_CASES:
        fn(params)


@pytest.mark.parametrize(("fn", "params"), [(fn, p) for _, fn, p in WIDGET_CASES])
def test_every_endpoint_on_an_empty_history(data, fn, params):  # noqa: F811
    out = fn(params)
    assert out["surface"] == "chat" if fn is not filter_options else out["runs"] == 0


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def test_summary_tiles_in_grid_order_against_the_previous_range(seeded, client):  # noqa: F811
    params = {"from": (T0 + timedelta(days=100)).isoformat(), "to": (T0 + timedelta(days=200)).isoformat()}
    out = _get(client, "/api/analytics/summary", params)
    assert [t["id"] for t in out["tiles"]] == list(metrics.KPI_GRID) and len(out["tiles"]) == 12
    assert out["previous"] == {"from": T0.isoformat().replace("+00:00", ".000000+00:00"),
                               "to": params["from"].replace("+00:00", ".000000+00:00")}
    tiles = {t["id"]: t for t in out["tiles"]}
    runs = tiles["runs"]
    assert runs["value"] == out["runs"] == 30 and runs["previous"] == 30 and runs["direction"] == "neutral"
    for t in out["tiles"]:
        assert {"value", "n", "coverage", "applies", "previous", "previous_n", "family", "direction",
                "delta", "grade", "trend_key", "low_n"} <= set(t), t["id"]
        assert t["applies"] is True
    # pooled rates over the judged requests add up to 1
    rates = [tiles[k] for k in ("success_rate", "error_rate")]
    assert all(r["denominator"] == rates[0]["denominator"] > 0 for r in rates)
    (whole,) = analytics_widgets.query.aggregate(
        history.query_connection(), analytics_widgets.query.parse_query(params), ["rate_limited_rate"], "all")
    limited = whole.metrics["rate_limited_rate"]
    assert limited.denominator == rates[0]["denominator"]
    assert rates[0]["value"] + rates[1]["value"] + limited.value == pytest.approx(1)
    # the score tile is judged on the server
    score = tiles["score"]
    assert score["grade"] and score["family"] in metrics.FAMILIES
    assert score["delta"] == pytest.approx(score["value"] - score["previous"])
    # the counts
    assert tiles["relays"]["value"] == 4 and tiles["models"]["value"] == 2


def test_summary_without_from_has_no_previous_range_and_from_alone_ends_now(seeded, client):  # noqa: F811
    out = _get(client, "/api/analytics/summary")
    assert out["previous"] is None and out["runs"] == 60
    assert all(t["previous"] is None and t["direction"] == "none" for t in out["tiles"])
    out = _get(client, "/api/analytics/summary", {"from": (T0 + timedelta(days=150)).isoformat()})
    assert out["to"] is not None and out["to"].endswith(":00.000000+00:00") and out["previous"]
    out = _get(client, "/api/analytics/summary", {"range": "7d"})
    assert out["runs"] == 0 and out["previous"] is not None


def test_summary_one_run_is_its_stored_value(data):  # noqa: F811
    _save(T0, outcomes={"success": 7, "rate_limited": 1, "relay_5xx": 2, "network": 3})
    tiles = {t["id"]: t for t in widget_summary({})["tiles"]}
    row = history.query_connection().execute(
        "SELECT success_rate, error_rate, ttft_p50_ms FROM history_metrics").fetchone()
    assert tiles["success_rate"]["value"] == row[0] == pytest.approx(0.7)
    assert tiles["error_rate"]["value"] == row[1] == pytest.approx(0.2)
    assert tiles["ttft_p50"]["value"] == row[2]
    assert tiles["runs"]["value"] == 1 and tiles["score"]["low_n"] is True


def test_summary_on_a_non_chat_surface_keeps_the_slots(data, client):  # noqa: F811
    for i in range(4):
        history.save(_embed_report(T0 + timedelta(hours=i), latency=40.0 + i))
    _save(T0)  # chat: outnumbered
    out = _get(client, "/api/analytics/summary")
    assert out["surface"] == "embedding" and out["runs"] == 4
    tiles = {t["id"]: t for t in out["tiles"]}
    assert [t["id"] for t in out["tiles"]] == list(metrics.KPI_GRID)
    for mid in ("ttft_p50", "decode_tps", "billing_ratio_prompt", "billing_ratio_completion"):
        assert tiles[mid]["applies"] is False and tiles[mid]["value"] is None and tiles[mid]["n"] is None
    assert tiles["latency_p50"]["applies"] is True and tiles["latency_p50"]["value"] == 41.5
    assert _get(client, "/api/analytics/summary", {"surface": "chat"})["runs"] == 1


# --------------------------------------------------------------------------- #
# series and heatmap
# --------------------------------------------------------------------------- #
def test_series_keys_groups_buckets_and_families(seeded, client):  # noqa: F811
    out = _get(client, "/api/analytics/series", [("trend.metric", "score"), ("trend.tz", "Europe/Berlin"),
                                                 ("trend.key", "cheap-gpt"), ("trend.key", OTHER)])
    assert [s["key"] for s in out["series"]] == ["cheap-gpt", OTHER] and out["tz"] == "Europe/Berlin"
    point = out["series"][0]["points"][0]
    assert point["family"] in metrics.FAMILIES and point["grade"] and "p25" in point
    by_model = _get(client, "/api/analytics/series", {"group": "model", "trend.bucket": "week"})
    assert {s["key"] for s in by_model["series"]} == {"model-a", "model-b"}
    assert by_model["bucket"] == "week" and by_model["group"] == "model"
    only = _get(client, "/api/analytics/series", {"relay": OTHER, "trend.metric": "error_rate"})
    assert [s["key"] for s in only["series"]] == [OTHER]
    assert "trend.bucket must be one of" in _get(client, "/api/analytics/series",
                                                 {"trend.bucket": "dow_hour"}, 400)["error"]
    assert "unknown metric" in _get(client, "/api/analytics/series", {"trend.metric": "x'--"}, 400)["error"]
    assert "at most 4 keys" in _get(client, "/api/analytics/series",
                                    [("trend.key", k) for k in "abcde"], 400)["error"]
    empty = _get(client, "/api/analytics/series", {"from": "2030-01-01", "to": "2030-02-01"})
    assert empty["series"] == []


def test_series_on_a_non_chat_surface(data, client):  # noqa: F811
    history.save(_embed_report(T0))
    assert "does not apply" in _get(client, "/api/analytics/series", {"trend.metric": "ttft_p50"}, 400)["error"]
    out = _get(client, "/api/analytics/series", {"trend.metric": "latency_p50"})
    assert out["surface"] == "embedding" and out["series"][0]["points"][0]["value"] == 40.0


def test_heatmap(seeded, client):  # noqa: F811
    out = _get(client, "/api/analytics/heatmap", {"heat.block": "6", "heat.tz": "UTC"})
    assert out["bucket"] == "dow_hour" and out["group"] == "all" and len(out["series"]) == 1
    cells = out["series"][0]["points"]
    assert sum(c["runs"] for c in cells) == 60 and all(c["hours"] == 6 and c["family"] for c in cells)
    one = _get(client, "/api/analytics/heatmap", {"heat.key": "cheap-gpt", "heat.fold": "4weeks"})
    assert [s["key"] for s in one["series"]] == ["cheap-gpt"] and one["fold"] == "4weeks"
    assert "heat.block must be one of" in _get(client, "/api/analytics/heatmap", {"heat.block": "5"}, 400)["error"]
    assert "heat.fold must be one of" in _get(client, "/api/analytics/heatmap", {"heat.fold": "year"}, 400)["error"]


# --------------------------------------------------------------------------- #
# leaderboard and breakdown
# --------------------------------------------------------------------------- #
def test_leaderboard_ranks_by_score_with_judged_cells(seeded, client):  # noqa: F811
    out = _get(client, "/api/analytics/leaderboard", {"model": "model-a"})
    assert out["by"] == "relay" and len(out["rows"]) == 4
    scores = [r["metrics"]["score"]["value"] for r in out["rows"]]
    assert scores == sorted(scores, reverse=True)
    cell = out["rows"][0]["metrics"]["score"]
    assert cell["family"] in metrics.FAMILIES and cell["grade"] == metrics.present("score", cell["value"])["grade"]
    assert [m["id"] for m in out["metrics"]] == list(analytics_widgets.BOARD_METRICS)
    models = _get(client, "/api/analytics/leaderboard", {"relay": "cheap-gpt", "board.by": "model"})
    assert {r["key"] for r in models["rows"]} == {"model-a", "model-b"}
    assert _get(client, "/api/analytics/leaderboard", {"from": "2030-01-01", "to": "2030-02-01"})["rows"] == []
    assert "board.by must be one of" in _get(client, "/api/analytics/leaderboard", {"board.by": "all"}, 400)["error"]


def test_leaderboard_on_a_non_chat_surface(data, client):  # noqa: F811
    history.save(_embed_report(T0))
    ids = [m["id"] for m in _get(client, "/api/analytics/leaderboard")["metrics"]]
    assert "ttft_p50" not in ids and "billing_ratio_prompt" not in ids and "latency_p50" in ids


def test_breakdown(seeded, client):  # noqa: F811
    out = _get(client, "/api/analytics/breakdown", [("breakdown.metric", "ttft_p50"),
                                                    ("breakdown.metric", "dim:protocol"), ("group", "model")])
    assert [m["id"] for m in out["metrics"]] == ["ttft_p50", "dim:protocol"] and out["group"] == "model"
    assert [r["key"] for r in out["rows"]] == ["model-a", "model-b"] and out["runs"] == 60
    cell = out["rows"][0]["metrics"]["ttft_p50"]
    assert cell["p25"] <= cell["median"] <= cell["p75"] and cell["family"] == "lat"
    assert _get(client, "/api/analytics/breakdown", {"breakdown.metric": "score", "group": "all"})["rows"][0][
        "key"] == analytics.ALL_KEY
    assert "at least one" in _get(client, "/api/analytics/breakdown", {}, 400)["error"]
    assert "at most 8" in _get(client, "/api/analytics/breakdown",
                               [("breakdown.metric", m) for m in list(analytics.METRICS)[:9]], 400)["error"]
    history.save(_embed_report(T0))
    assert "does not apply" in _get(client, "/api/analytics/breakdown",
                                    {"surface": "embedding", "breakdown.metric": "ttft_p50"}, 400)["error"]


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
def _rec(seq, start_ms, *, ok=False, status=None, error_type=None, error_class=None, retried=False,
         phase="probe", timeout=False, rate_limited=False, endpoint="target", op="complete"):
    return {"seq": seq, "endpoint": endpoint, "op": op, "phase": phase, "start_ms": start_ms, "ok": ok,
            "status_code": status, "error_type": error_type, "error_class": error_class,
            "retried": retried, "timeout": timeout, "rate_limited": rate_limited, "duration_ms": 100.0}


# Records the former status-guessing SQL got wrong, and ordinary ones.
TRICKY = [
    _rec(0, 0, ok=True, status=200),
    _rec(1, 100, ok=True, status=200, op="list_models"),  # every op counts
    _rec(2, 200, error_type="PoolTimeout"),  # ekte's own pool, no status: local (was "network")
    _rec(3, 300, error_type="TypeError", error_class="local"),  # ekte bug: local
    _rec(4, 400, error_type="ConnectTimeout", timeout=True),  # never reached the relay: network (was "timeout")
    _rec(5, 500, error_type="ConnectError"),  # network
    _rec(6, 600, status=503, error_type="http_error", retried=True),  # superseded by its repeat (was counted)
    _rec(7, 700, status=503, error_type="http_error"),  # the repeat: relay_5xx
    _rec(8, 61_000, status=400, error_type="http_error", phase="param_retry"),  # ekte's own retry (was counted)
    _rec(9, 61_100, ok=True, status=200, phase="param_retry"),  # never counted either
    _rec(10, 61_200, status=429, error_type="http_error", rate_limited=True),
    _rec(11, 61_300, error_type="ReadTimeout", timeout=True),  # relay_timeout
    _rec(12, 61_400, status=404, error_type="http_error"),  # relay_4xx
    _rec(13, 61_500, status=200, error_type=None),  # failed with 200: relay_other
    _rec(14, 61_600, error_type="RemoteProtocolError"),  # relay broke off: relay_other
    _rec(15, 61_700, status=500, error_type="http_error", endpoint="baseline"),  # not the target
]
TRICKY_COUNTS = {"success": 2, "rate_limited": 1, "relay_timeout": 1, "relay_5xx": 1, "relay_4xx": 1,
                 "relay_other": 2, "network": 2, "local": 2}


def _save_records(started, records, **kw) -> int:
    report = _report(started, **kw)
    report.pop("outcomes")  # derived from the records
    report["performance"]["requests"] = records
    rid = history.save(report)
    assert rid > 0
    return rid


def test_errors_classify_like_the_outcome_model(data, client):  # noqa: F811
    """Regression: ekte failures without a status, connect timeouts, repeated
    attempts and param_retry records, which the former SQL misclassified."""
    add_relay("Cheap GPT", RELAY)
    rid = _save_records(T0, TRICKY)
    expected = dict.fromkeys(errorclass.OUTCOMES, 0)
    for rec in TRICKY:
        if rec["endpoint"] == "target" and (o := errorclass.outcome(rec)) is not None:
            expected[o] += 1
    assert expected == TRICKY_COUNTS
    out = _get(client, "/api/analytics/errors", {"errors.run": str(rid), "errors.tz": "Europe/Berlin"})
    assert out["classes"] == list(errorclass.OUTCOMES)
    totals = out["totals"]
    assert totals["counts"] == TRICKY_COUNTS and totals["requests"] == 12 and totals["judged"] == 8
    assert totals["success_rate"] == pytest.approx(2 / 8)
    assert totals["relay_error_rate"] == pytest.approx(5 / 8)  # 5xx, 4xx, timeout, 2 other
    assert totals["rate_limited_rate"] == pytest.approx(1 / 8)
    assert totals["success_rate"] + totals["relay_error_rate"] + totals["rate_limited_rate"] == pytest.approx(1)
    assert totals["impaired_rate"] == pytest.approx(4 / 12)
    assert totals["shares"]["network"] == pytest.approx(2 / 12) and totals["shares"]["relay_5xx"] == 1 / 8
    # the run's per-minute timeline classifies its records in SQL by the same rules
    minutes = out["run"]["minutes"]
    assert [m["minute"] for m in minutes] == [0, 1]
    summed = {o: sum(m["counts"][o] for m in minutes) for o in errorclass.OUTCOMES}
    assert summed == TRICKY_COUNTS
    assert minutes[0]["counts"]["local"] == 2 and minutes[1]["counts"]["relay_other"] == 2
    (bucket,) = out["buckets"]
    assert bucket["bucket"] == "2026-03-02T00:00:00+01:00" and bucket["counts"] == TRICKY_COUNTS


def test_outcome_sql_matches_the_python_rules(data):  # noqa: F811
    """Every combination of the fields outcome() reads, through OUTCOME_SQL."""
    import itertools

    records = []
    for i, (ok, status, etype, ecls, retried, phase, timeout, limited) in enumerate(itertools.product(
            (False, True), (None, 200, 404, 429, 503), (None, "http_error", "PoolTimeout", "ConnectError",
                                                        "ReadTimeout", "Unsupported", "Weird"),
            (None, "relay", "network", "local"), (False, True), ("probe", "param_retry", None),
            (False, True), (False, True))):
        records.append(_rec(i, float(i), ok=ok, status=status, error_type=etype, error_class=ecls,
                            retried=retried, phase=phase, timeout=timeout, rate_limited=limited))
    rid = _save_records(T0, records)
    got = {o: sum(m["counts"][o] for m in analytics_widgets.run_timeline(history.query_connection(), rid))
           for o in errorclass.OUTCOMES}
    want = dict.fromkeys(errorclass.OUTCOMES, 0)
    for rec in records:
        if (o := errorclass.outcome(rec)) is not None:
            want[o] += 1
    assert got == want and sum(want.values()) > 100


def test_errors_groups_buckets_filters_and_coverage(seeded, client):  # noqa: F811
    out = _get(client, "/api/analytics/errors", {"group": "model", "errors.bucket": "week"})
    assert [g["key"] for g in out["groups"]] == ["model-a", "model-b"]
    assert out["runs"] == out["covered"] == 60 and out["coverage"] == 1
    conn = history.query_connection()
    sums = dict(conn.execute("SELECT outcome, SUM(n) FROM history_outcomes GROUP BY outcome").fetchall())
    assert {k: v for k, v in out["totals"]["counts"].items() if v} == sums
    assert sum(g["requests"] for g in out["groups"]) == out["totals"]["requests"]
    assert sum(b["requests"] for b in out["buckets"]) == out["totals"]["requests"]
    assert sum(b["runs"] for b in out["buckets"]) == 60
    for g in out["groups"]:
        assert g["success_rate"] + g["relay_error_rate"] + g["rate_limited_rate"] == pytest.approx(1)
    # pooled: the group's rate is its summed counts over its summed base, as the KPI
    (kpi,) = analytics_widgets.query.aggregate(conn, analytics_widgets.query.parse_query({"model": "model-a"}),
                                               ["error_rate"], "all")
    assert out["groups"][0]["relay_error_rate"] == pytest.approx(kpi.metrics["error_rate"].value)
    grid = _get(client, "/api/analytics/errors", {"errors.bucket": "dow_hour", "errors.block": "6"})
    assert all(b["hours"] == 6 for b in grid["buckets"])
    only = _get(client, "/api/analytics/errors", {"relay": OTHER, "group": "relay_model"})
    assert all(g["relay"] == OTHER for g in only["groups"]) and only["runs"] == 15
    empty = _get(client, "/api/analytics/errors", {"from": "2030-01-01", "to": "2030-02-01"})
    assert empty["runs"] == 0 and empty["coverage"] is None and empty["groups"] == empty["buckets"] == []
    assert empty["totals"]["success_rate"] is None
    for params, message in [({"errors.bucket": "month"}, "errors.bucket must be one of"),
                            ({"errors.tz": "Nowhere/x"}, "unknown time zone"),
                            ({"errors.run": "x"}, "errors.run must be a run id")]:
        assert message in _get(client, "/api/analytics/errors", params, 400)["error"]


def test_errors_on_a_non_chat_surface(data, client):  # noqa: F811
    report = _embed_report(T0)
    report.pop("outcomes")
    report["performance"]["requests"] = [_rec(i, 10.0 * i, ok=i > 0, status=200 if i else 500, op="embed")
                                         for i in range(3)]
    history.save(report)
    out = _get(client, "/api/analytics/errors")
    assert out["surface"] == "embedding" and out["totals"]["counts"]["relay_5xx"] == 1
    assert out["totals"]["counts"]["success"] == 2
    assert _get(client, "/api/analytics/errors", {"surface": "chat"})["runs"] == 0


# --------------------------------------------------------------------------- #
# integrity
# --------------------------------------------------------------------------- #
def test_integrity_matrix(data, client):  # noqa: F811
    add_relay("Cheap GPT", RELAY)
    plan = [
        ({"model_identity": "pass", "capability": "pass", "vision": "fail"}, (128_000, 64_000), "model-a"),
        ({"model_identity": "warn", "capability": "pass", "vision": "inconclusive"}, (128_000, 128_000), "other"),
        ({"model_identity": "pass", "capability": "fail"}, None, "model-a"),
    ]
    for i, (statuses, context, returned) in enumerate(plan):
        history.save(_detectors(_report(T0 + timedelta(hours=i)), statuses, context=context, returned=returned))
    history.save(_detectors(_report(T0, base_url=OTHER, model="model-b"), {"streaming": "pass"}))
    out = _get(client, "/api/analytics/integrity")
    assert out["checks"] == ["model_identity", "capability", "vision", "streaming"] and out["runs"] == 4
    row = out["rows"][0]
    assert row["key"] == "cheap-gpt|model-a" and row["runs"] == 3
    ident = row["checks"]["model_identity"]
    assert (ident["pass"], ident["warn"], ident["fail"], ident["n"]) == (2, 1, 0, 3)
    assert ident["pass_rate"] == pytest.approx(2 / 3)
    vision = row["checks"]["vision"]
    assert (vision["fail"], vision["other"], vision["n"], vision["low_n"]) == (1, 1, 1, True)
    assert row["checks"]["streaming"]["n"] == 0 and row["checks"]["streaming"]["pass_rate"] is None
    assert row["model_mismatch"]["value"] == pytest.approx(1 / 3)
    assert row["context"]["value"] == pytest.approx(0.75) and row["context"]["n"] == 2
    assert row["context"]["claimed"] == 128_000 and out["has_context"] is True
    assert _get(client, "/api/analytics/integrity", {"model": "model-b"})["rows"][0]["key"] == f"{OTHER}|model-b"
    assert _get(client, "/api/analytics/integrity", {"from": "2030-01-01", "to": "2030-02-01"})["rows"] == []


def test_integrity_on_a_non_chat_surface(data, client):  # noqa: F811
    for i in range(2):
        history.save(_embed_report(T0 + timedelta(hours=i), echoed="differs" if i else "matches"))
    out = _get(client, "/api/analytics/integrity")
    assert out["surface"] == "embedding" and out["has_context"] is False
    assert out["checks"] == ["embed.identity", "embed.drift"]
    assert out["rows"][0]["model_mismatch"]["value"] == 0.5 and out["rows"][0]["context"]["claimed"] is None


# --------------------------------------------------------------------------- #
# filter options
# --------------------------------------------------------------------------- #
def test_filter_options_count_every_key_under_the_other_filters(seeded, client):  # noqa: F811
    out = _get(client, "/api/filters/options")
    assert out["runs"] == 60 and out["surface_default"] == "chat" and out["keys"] == list(
        analytics_widgets.OPTION_KEYS)
    for key in out["keys"]:
        assert sum(o["runs"] for o in out[key]) == 60, key
    relays = {o["value"]: o for o in out["relay"]}
    assert relays["cheap-gpt"]["label"] == "Cheap GPT" and relays["cheap-gpt"]["in_kb"] is True
    assert relays[OTHER]["in_kb"] is False and relays["openai"]["runs"] == 15
    assert {o["value"] for o in out["detect"]} == {"auto", "manual", "-"}
    assert {o["value"] for o in out["exec"]} == {"manual", "monitor"}
    assert "inconclusive" in {o["value"] for o in out["risk"]}
    assert out["span"]["first"] < out["span"]["last"] and out["dimensions"] == ["protocol"]

    # a selected value stays, with its siblings, while the other keys narrow
    sel = _get(client, "/api/filters/options", {"relay": "cheap-gpt", "exec": "monitor"})
    assert {o["value"] for o in sel["relay"]} == {o["value"] for o in out["relay"]}
    assert {o["value"] for o in sel["exec"]} == {"manual", "monitor"}
    monitor_runs = {o["value"]: o["runs"] for o in out["exec"]}["monitor"]
    assert sum(o["runs"] for o in sel["model"]) == sel["runs"] < monitor_runs
    # from / to narrow the counts but not the span
    window = _get(client, "/api/filters/options", {"from": (T0 + timedelta(days=50)).isoformat(),
                                                   "to": (T0 + timedelta(days=60)).isoformat()})
    assert window["runs"] < 60 and window["span"] == out["span"]
    empty = _get(client, "/api/filters/options", {"q": "no such relay"})
    assert empty["runs"] == 0 and empty["model"] == [] and empty["span"] == {"first": None, "last": None}


def test_filter_options_surfaces(data, client):  # noqa: F811
    history.save(_embed_report(T0))
    _save(T0, base_url=OPENAI)
    _save(T0 + timedelta(hours=1), base_url=OPENAI)
    out = _get(client, "/api/filters/options", {"surface": "embedding"})
    assert out["surface"] == [{"value": "chat", "runs": 2}, {"value": "embedding", "runs": 1}]
    assert out["runs"] == 1 and out["surface_default"] == "embedding"
    assert _get(client, "/api/filters/options")["surface_default"] == "chat"


# --------------------------------------------------------------------------- #
# Caching and the 20k-run budget
# --------------------------------------------------------------------------- #
def test_resolve_params_bounds_open_ranges():
    now = datetime(2026, 6, 1, 12, 0, 30, tzinfo=UTC)
    pairs = dict(analytics_widgets.resolve_params({"from": "2026-05-01", "trend.metric": "score"}, now=now))
    assert pairs["to"] == "2026-06-01T12:01:00.000000+00:00" and pairs["trend.metric"] == "score"
    assert dict(analytics_widgets.resolve_params({"range": "7d"}, now=now))["from"] == \
        "2026-05-25T12:01:00.000000+00:00"
    assert "to" not in dict(analytics_widgets.resolve_params({}, now=now))
    with pytest.raises(QueryError):
        analytics_widgets.widget_summary(analytics_widgets.resolve_params({"from": "x"}, now=now))


def test_a_saved_run_drops_the_cached_answers(seeded, client):  # noqa: F811
    first = client.get("/api/analytics/summary")
    _save(T0, base_url=RELAY)
    second = client.get("/api/analytics/summary")
    assert second.json()["runs"] == first.json()["runs"] + 1
    assert second.headers["etag"] != first.headers["etag"]


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_benchmark_20k_runs_under_budget(data):  # noqa: F811
    """Every widget answers within the budget (p95, cold cache: the functions
    are called directly) on the 20k-run fixture of #121. Opt-in
    (EKTE_BENCH=1); EKTE_BENCH_BUDGET_MS overrides the 50 ms budget."""
    if os.environ.get("EKTE_BENCH") != "1":
        pytest.skip("set EKTE_BENCH=1 to run the 20k-run benchmark")
    import time

    from tests.test_query import _bench_module

    budget = float(os.environ.get("EKTE_BENCH_BUDGET_MS", "50"))
    _bench_module().build()
    history.query_connection()
    slow = {}
    for name, fn, params in WIDGET_CASES:
        fn(params)
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            fn(params)
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        if times[18] >= budget:
            slow[name] = round(times[18], 1)
    assert not slow, f"p95 over {budget} ms: {slow}"
