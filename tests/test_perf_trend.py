"""Running medians for the performance chart's trend line (zing/perf/trend.py)."""

from __future__ import annotations

from zing.perf.trend import RunningMedian, attach_trends


def _rec(seq: int, ms: float, *, endpoint: str = "target", ok: bool = True, cached: bool = False) -> dict:
    return {"seq": seq, "op": "complete", "endpoint": endpoint, "ok": ok, "cached": cached,
            "duration_ms": ms, "ttft_ms": ms / 4, "decode_tps_local": None, "decode_tps_reported": 50.0,
            "itl_mean_ms": None}


def test_median_of_the_last_five_per_endpoint():
    recs = [_rec(i, v) for i, v in enumerate([100, 300, 200, 400, 500, 900], 1)]
    recs.insert(2, _rec(99, 5000, endpoint="baseline"))
    attach_trends(recs)
    target = [r["trend"]["latency"] for r in recs if r["endpoint"] == "target"]
    assert target == [100, 200, 200, 250, 300, 400]  # the 6th drops the 1st (window of 5)
    assert recs[2]["trend"]["latency"] == 5000  # the baseline has its own window
    assert recs[0]["trend"]["tps"] == 50.0  # decode speed falls back to the reported value
    assert "itl" not in recs[0]["trend"]  # no value, no median


def test_band_is_p25_to_p75_of_the_same_window():
    recs = [_rec(i, v) for i, v in enumerate([100, 300, 200, 400, 500, 900], 1)]
    attach_trends(recs)
    bands = [r["trend_band"]["latency"] for r in recs]
    assert bands[0] == [100, 100]  # one value: no spread
    assert bands[1] == [150, 250]  # interpolated between the two
    assert bands[4] == [200, 400]  # 5 values: the 2nd and 4th smallest
    assert bands[5] == [300, 500]  # [300, 200, 400, 500, 900] after the 1st drops out
    assert set(recs[0]["trend_band"]) == set(recs[0]["trend"])


def test_failed_cached_and_other_calls_neither_feed_nor_get_a_trend():
    tagger = RunningMedian()
    tagger.tag(_rec(1, 100))
    failed = tagger.tag(_rec(2, 9000, ok=False))
    cached = tagger.tag(_rec(3, 1, cached=True))
    models = tagger.tag({"op": "list_models", "ok": True, "duration_ms": 5})
    last = tagger.tag(_rec(4, 300))
    assert "trend" not in failed and "trend" not in cached and "trend" not in models
    assert "trend_band" not in failed and "trend_band" not in cached
    assert last["trend"]["latency"] == 200
