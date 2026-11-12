"""The trend forecast (ekte/web/forecast.py): a weighted line on bucket medians."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ekte.web import analytics, forecast
from ekte.web.analytics import metric
from ekte.web.query import Cell, Point

BERLIN = ZoneInfo("Europe/Berlin")
LAT = metric("latency_p50")
SCORE = metric("score")


def _series(values, *, n=10, spread=10.0, start=datetime(2026, 10, 1, tzinfo=UTC),
            bucket="day", zone=BERLIN, low=(), widths=None):
    """Points for the given medians, one bucket apart (None: an empty bucket)."""
    out, t = [], start
    for i, v in enumerate(values):
        pos, key, _ = analytics._bucket(t, zone, bucket)
        if v is not None:
            lo, hi = widths[i] if widths else (spread, spread)
            runs = 2 if i in low else n
            out.append(Point(key, pos, {}, runs, Cell(v, runs, 1.0, runs < 3, v, v - lo, v + hi)))
        t = datetime.fromtimestamp(forecast._next(pos, bucket, zone)[0], UTC)
    return out


def _fc(points, ahead=7, annotations=(), bucket="day", m=LAT, zone=BERLIN):
    return forecast.forecast(points, annotations, bucket, zone, ahead, m)


def test_exact_line_gives_its_slope_and_a_clear_trend():
    fc = _fc(_series([100 + 5 * i for i in range(10)]))
    assert fc["status"] == "ok"
    assert fc["slope"] == pytest.approx(5)
    assert fc["clear"] is True and fc["direction"] == "worse"  # latency rising
    assert fc["dropped"] == 0 and fc["step"] is None
    assert [p["value"] for p in fc["points"]] == pytest.approx([145 + 5 * d for d in range(1, 8)])
    assert len(fc["points"]) == 7


def test_constant_series_has_no_clear_trend():
    fc = _fc(_series([200.0] * 10))
    assert fc["status"] == "ok" and fc["clear"] is False and fc["direction"] == "none"
    assert fc["slope"] == pytest.approx(0)


def test_noisy_flat_series_has_no_clear_trend():
    noise = [3, -2, 4, -5, 1, -1, 2, -3, 5, -4, 0, 2]
    fc = _fc(_series([300 + e for e in noise]))
    assert fc["clear"] is False


def test_step_is_found_and_the_fit_starts_after_it():
    pts = _series([100.0, 101, 99, 100, 102, 98, 300, 301, 299, 300, 302, 298, 300, 301])
    fc = _fc(pts)
    assert fc["step"] == pts[6].bucket
    assert fc["since"] == pts[6].bucket
    assert fc["buckets_used"] == 8
    assert fc["points"][0]["value"] == pytest.approx(301, abs=3)


def test_steady_drift_is_not_a_step():
    noise = [1, -1, 2, -2, 0, 1, -1, 2, -2, 0, 1, -1, 2, -2]
    fc = _fc(_series([100 + 10 * i + e for i, e in enumerate(noise)]))
    assert fc["step"] is None
    assert fc["buckets_used"] == 14
    assert fc["slope"] == pytest.approx(10, abs=0.5)


def test_annotation_cuts_the_fit():
    pts = _series([500.0] * 4 + [100 + 2 * i for i in range(8)])
    fc = _fc(pts, annotations=[{"bucket": pts[4].bucket, "kind": "tool_version"}])
    assert fc["since"] == pts[4].bucket
    assert fc["buckets_used"] == 8
    assert fc["slope"] == pytest.approx(2)


def test_too_few_buckets():
    fc = _fc(_series([100.0, 110, 120, 130, 140]))
    assert fc == {"status": "few_buckets", "ahead": 7, "buckets_used": 5, "buckets_needed": 6}


def test_annotation_leaves_too_few_buckets():
    pts = _series([100.0 + i for i in range(10)])
    fc = _fc(pts, annotations=[{"bucket": pts[6].bucket, "kind": "kb_profile"}])
    assert fc["status"] == "few_buckets" and fc["buckets_used"] == 4


def test_low_n_buckets_are_ignored():
    vals = [100 + 5 * i for i in range(10)]
    vals[3] = 900
    pts = _series(vals, low={3})
    fc = _fc(pts)
    assert fc["buckets_used"] == 9 and fc["dropped"] == 0
    assert fc["slope"] == pytest.approx(5)


def test_only_low_n_buckets_is_too_few():
    fc = _fc(_series([100.0] * 8, n=2))
    assert fc["status"] == "few_buckets" and fc["buckets_used"] == 0


def test_one_wild_bucket_is_dropped():
    vals = [100 + 5 * i for i in range(10)]
    vals[4] = 900
    fc = _fc(_series(vals))
    assert fc["dropped"] == 1
    assert fc["buckets_used"] == 9
    assert fc["slope"] == pytest.approx(5)


def test_pooled_metric_is_not_forecast():
    fc = _fc(_series([0.9] * 10), m=metric("success_rate"))
    assert fc == {"status": "not_median", "ahead": 7, "buckets_used": 0, "buckets_needed": 6}


def test_start_is_the_last_bucket():
    widths = [(10.0, 20.0)] * 9 + [(12.0, 18.0)]
    pts = _series([100 + 3 * i for i in range(10)], widths=widths)
    fc = _fc(pts)
    last = pts[-1].cell
    assert fc["start"] == {"bucket": pts[-1].bucket, "value": last.value, "p25": last.p25, "p75": last.p75}


def test_band_widens_with_the_horizon():
    noise = [3, -2, 4, -5, 1, -1, 2, -3, 5, -4]
    fc = _fc(_series([200 + 4 * i + e for i, e in enumerate(noise)]))
    start = fc["start"]["p75"] - fc["start"]["p25"]
    widths = [p["p75"] - p["p25"] for p in fc["points"]]
    assert widths[0] > start
    assert all(b > a for a, b in zip(widths, widths[1:], strict=False))


def test_thin_last_bucket_gets_a_quarter_of_the_median_width():
    widths = [(40.0, 40.0)] * 9 + [(1.0, 2.0)]
    pts = _series([100.0 + i for i in range(10)], widths=widths)
    fc = _fc(pts)
    assert fc["start"]["value"] - fc["start"]["p25"] == pytest.approx(10)
    assert fc["start"]["p75"] - fc["start"]["value"] == pytest.approx(10)


def test_score_stays_within_0_to_100():
    fc = _fc(_series([60 + 5 * i for i in range(8)], spread=3), m=SCORE)
    assert all(p["p75"] <= 100 and p["value"] <= 100 for p in fc["points"])
    assert fc["direction"] == "better"  # a rising score


def test_latency_is_not_forecast_below_zero():
    fc = _fc(_series([100 - 12 * i for i in range(8)], spread=3))
    assert all(p["p25"] >= 0 and p["value"] >= 0 for p in fc["points"])


def test_empty_buckets_keep_their_gap():
    pts = _series([100.0, 105, None, 115, 120, None, None, 135, 140])
    fc = _fc(pts, ahead=3)
    assert fc["slope"] == pytest.approx(5)
    assert fc["points"][0]["value"] == pytest.approx(145)


def test_day_keys_cross_the_dst_change():
    # Europe/Berlin leaves summer time on Sunday 25 October 2026
    pts = _series([100.0 + i for i in range(8)], start=datetime(2026, 10, 15, 12, tzinfo=UTC))
    fc = _fc(pts, ahead=7)
    keys = [p["bucket"] for p in fc["points"]]
    assert keys[0] == "2026-10-23T00:00:00+02:00"
    assert "2026-10-25T00:00:00+02:00" in keys
    assert "2026-10-26T00:00:00+01:00" in keys
    assert [datetime.fromisoformat(k).hour for k in keys] == [0] * 7
    assert fc["points"][-1]["value"] == pytest.approx(114)


def test_hour_keys_cross_the_dst_change():
    start = datetime(2026, 10, 24, 18, tzinfo=UTC)
    pts = _series([10.0 + i for i in range(6)], bucket="hour", start=start)
    fc = _fc(pts, ahead=12, bucket="hour")
    keys = [p["bucket"] for p in fc["points"]]
    assert len(set(keys)) == 12
    # the two 02:00 hours of the fall-back are two buckets
    assert "2026-10-25T02:00:00+02:00" in keys and "2026-10-25T02:00:00+01:00" in keys
    stamps = [datetime.fromisoformat(k) for k in keys]
    assert all(b - a == timedelta(hours=1) for a, b in zip(stamps, stamps[1:], strict=False))


def test_week_keys_are_mondays():
    pts = _series([100.0 + i for i in range(6)], bucket="week", start=datetime(2026, 9, 7, tzinfo=UTC))
    fc = _fc(pts, ahead=4, bucket="week")
    keys = [datetime.fromisoformat(p["bucket"]) for p in fc["points"]]
    assert [k.weekday() for k in keys] == [0] * 4
    assert [k.hour for k in keys] == [0] * 4
    assert keys[0].date().isoformat() == "2026-10-19"
    assert keys[1].utcoffset() == timedelta(hours=1)
