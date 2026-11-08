"""The metric registry and its display semantics (ekte/web/metrics.py, #122)."""

from __future__ import annotations

import pytest

from ekte import scoring
from ekte.web import analytics, metrics
from ekte.web.analytics import AnalyticsError
from ekte.web.metrics import KPI_GRID, MIN_RUNS, present


@pytest.mark.parametrize(("mid", "value", "fam", "grade"), [
    ("score", 95, "good", "A"),
    ("score", 90, "good", "A"),
    ("score", 85, "good", "B"),
    ("score", 75, "sky", "C"),
    ("score", 65, "warn", "D"),
    ("score", 59.9, "bad", "F"),
    ("score", None, "grey", None),
    ("dim:protocol", 72, "sky", "C"),
    ("grade", 6, "good", "A"),
    ("grade", 5, "good", "B"),
    ("grade", 4, "sky", "C"),
    ("grade", 3, "warn", "D"),
    ("grade", 2, "bad", "E"),
    ("grade", 1, "bad", "F"),
    ("grade", 4.5, "good", "B"),  # a median between two grades: half up
    ("grade", 0, "bad", "F"),  # clamped to the scale
    ("latency_p50", 812, "lat", None),
    ("ttft_p95", 0, "lat", None),
    ("decode_tps", 41.5, "tps", None),
    ("success_rate", 0.99, "grey", None),
    ("billing_ratio_prompt", 1.02, "grey", None),
    ("runs", 12, "grey", None),
    ("latency_p50", None, "grey", None),
])
def test_family_and_grade(mid, value, fam, grade):
    out = present(mid, value)
    assert (out["family"], out["grade"]) == (fam, grade)
    assert out["family"] in metrics.FAMILIES


@pytest.mark.parametrize(("mid", "value", "previous", "previous_n", "direction", "trend"), [
    ("score", 80, 70, 5, "better", "trend.rising"),
    ("score", 70, 80, 5, "worse", "trend.falling"),
    ("score", 70, 70, 5, "neutral", "trend.unchanged"),
    ("latency_p50", 500, 800, 5, "better", "trend.falling"),
    ("latency_p50", 800, 500, None, "worse", "trend.rising"),
    ("error_rate", 0.02, 0.01, 5, "worse", "trend.rising"),
    ("success_rate", 0.99, 0.95, 5, "better", "trend.rising"),
    ("grade", 6, 4, 5, "better", "trend.rising"),
    ("billing_ratio_prompt", 1.2, 1.0, 5, "neutral", "trend.rising"),  # no better side
    # low previous n: indicative only, no verdict (the trend key stays)
    ("score", 80, 70, MIN_RUNS - 1, "none", "trend.rising"),
    ("score", 80, 70, MIN_RUNS, "better", "trend.rising"),
    # counts are exact: judged whatever the previous n (and have no better side)
    ("runs", 12, 9, 1, "neutral", "trend.rising"),
    ("findings_high", 3, 1, 1, "worse", "trend.rising"),
    # nothing to compare with
    ("score", 80, None, 5, "none", None),
    ("score", None, 70, 5, "none", None),
])
def test_direction_and_trend(mid, value, previous, previous_n, direction, trend):
    out = present(mid, value, previous, previous_n=previous_n)
    assert (out["direction"], out["trend_key"]) == (direction, trend)
    assert out["direction"] in metrics.DIRECTIONS
    if value is not None and previous is not None:
        assert out["delta"] == pytest.approx(value - previous)
    else:
        assert out["delta"] is None


@pytest.mark.parametrize(("mid", "n", "low"), [
    ("score", 1, True), ("score", MIN_RUNS - 1, True), ("score", MIN_RUNS, False), ("score", None, False),
    ("runs", 1, False),
])
def test_low_n(mid, n, low):
    assert present(mid, 50, n=n)["low_n"] is low


def test_applies_per_surface():
    out = present("ttft_p50", 300, 200, 5, 5, surface="embedding")
    assert out == {"value": None, "family": "grey", "grade": None, "delta": None, "direction": "none",
                   "trend_key": None, "low_n": False, "applies": False}
    assert present("ttft_p50", 300, surface="chat")["applies"] is True
    assert present("latency_p50", 300, surface="embedding")["applies"] is True


def test_present_ignores_non_numbers():
    assert present("score", "80")["value"] is None
    assert present("score", True)["value"] is None
    assert present("score", float("nan"))["family"] == "grey"


def test_grades_follow_the_scoring_thresholds(monkeypatch):
    assert present("score", 85)["grade"] == "B" and present("score", 85)["family"] == "good"
    assert present("score", 72)["family"] == "sky"
    monkeypatch.setattr(scoring, "GRADE_THRESHOLDS", ((95, "A"), (88, "B"), (75, "C"), (60, "D")))
    assert scoring.rating(85) == "C"
    assert present("score", 85)["grade"] == "C" and present("score", 85)["family"] == "sky"
    assert present("score", 72)["grade"] == "D" and present("score", 72)["family"] == "warn"
    assert present("dim:protocol", 90)["grade"] == "B"


def test_grade_scale():
    assert [metrics.grade_value(g) for g in "FEDCBA"] == [1, 2, 3, 4, 5, 6]
    assert metrics.grade_value(None) is None and metrics.grade_value("Z") is None
    assert [metrics.grade_letter(v) for v in (1, 1.49, 1.5, 6, 7)] == ["F", "F", "E", "A", "A"]
    assert analytics.run_value(metrics.METRICS["grade"], {"rating": "B"}) == 5.0
    assert analytics.run_value(metrics.METRICS["grade"], {"rating": None}) is None


def test_grade_sql_matches_python():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    for letter in (*scoring.GRADE_SCALE, None, "", "Z"):
        sql = metrics.grade_value_sql("?").replace("CASE ?", "CASE :g")
        got = conn.execute(f"SELECT {sql}", {"g": letter}).fetchone()[0]
        assert got == metrics.grade_value(letter), letter


def test_registry_shape():
    cat = metrics.catalogue()
    ids = [m["id"] for m in cat["metrics"]]
    assert len(ids) == len(set(ids))
    for mid in ("score", "grade", "risk_high_share", "success_rate", "error_rate", "rate_limited_rate",
                "timeout_rate", "impaired_rate", "latency_p50", "latency_p95", "ttft_p50", "ttft_p95",
                "decode_tps", "runs", "relays", "models"):
        assert mid in ids
    fields = {"id", "unit", "format", "agg", "surfaces", "higher_is_better", "label_key", "short_label_key",
              "kpi_label_key", "agg_hint_key"}
    for m in cat["metrics"]:
        assert set(m) == fields
        assert m["format"] in metrics.FORMATS and m["agg"] in metrics.AGGS
        assert m["label_key"] == f"metric.{m['id']}"
        assert m["agg_hint_key"] == f"metric.{m['id']}.agg_hint"
        assert m["higher_is_better"] in (True, False, None)
    by = {m["id"]: m for m in cat["metrics"]}
    assert by["decode_tps"]["format"] == "tok_s" and by["billing_ratio_prompt"]["format"] == "ratio_percent"
    assert by["success_rate"]["format"] == "percent" and by["grade"]["format"] == "grade"
    assert by["duration"]["format"] == "seconds" and by["context_claimed"]["format"] == "tokens"
    assert by["score"]["kpi_label_key"] == "metric.score.kpi"
    assert cat["kpi_grid"] == [
        "runs", "relays", "models", "score",
        "risk_high_share", "success_rate", "error_rate", "latency_p50",
        "ttft_p50", "decode_tps", "billing_ratio_prompt", "billing_ratio_completion",
    ]
    assert len(KPI_GRID) == 12 and set(KPI_GRID) <= set(ids)
    assert cat["history_trends"] == ["score", "grade", "latency_p50", "ttft_p50", "decode_tps", "error_rate"]
    assert cat["grades"] == ["F", "E", "D", "C", "B", "A"]
    assert cat["min_runs"] == MIN_RUNS
    # every key named has its English text
    assert cat["labels"]["metric.decode_tps"] == "Decode speed p50"
    assert cat["labels"]["metric.score.kpi"] == "Median score"
    assert cat["labels"]["trend.rising"] == "rising"
    for m in cat["metrics"]:
        for k in ("label_key", "short_label_key", "kpi_label_key", "agg_hint_key"):
            assert cat["labels"][m[k]] != m[k]


def test_counts_are_not_aggregatable():
    assert metrics.get("runs").agg == "count"
    with pytest.raises(AnalyticsError):
        analytics.metric("runs")
    with pytest.raises(KeyError):
        metrics.get("nope")
    assert analytics.metric("grade") is metrics.METRICS["grade"]
    assert analytics.METRICS is metrics.METRICS


def test_metrics_endpoint(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ekte.web.server import create_app

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    client = TestClient(create_app(), base_url="http://localhost")
    r = client.get("/api/metrics")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert r.json() == metrics.catalogue()
    again = client.get("/api/metrics", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
