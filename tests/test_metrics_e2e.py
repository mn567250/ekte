"""End-to-end checks of the umbrella #117 (Definition of done), on the final code.

One set of saved runs, read through every surface that shows a rate: the
report as stored, ``GET /api/history/{id}?trend=1``, ``GET /api/history/runs``,
``GET /api/history/groups`` (n = 1 groups), ``GET /api/analytics/summary``
(a single-run range), ``/api/analytics/breakdown`` and
``/api/analytics/errors``. The success, error and rate-limited rates agree
everywhere and add up to 1; over several runs they are pooled. A save from
another process (as the CLI's) drops the cached answers. The pages do no
metric maths, grading or classification of their own.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from ekte import scoring
from ekte.perf.outcomes import from_counts
from ekte.web import history
from tests.test_analytics import T0, _report

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web.server import create_app  # noqa: E402

RATES = ("success_rate", "error_rate", "rate_limited_rate")
# One run per relay (each its own n = 1 group), with different outcome mixes:
# relay errors of every kind, 429s, network / ekte failures (impaired, outside
# the relay's rates), awkward fractions.
MIXES = [
    {"success": 7, "relay_5xx": 2, "rate_limited": 1, "network": 1},
    {"success": 1, "relay_timeout": 1, "relay_4xx": 1, "local": 2},
    {"success": 12},
    {"success": 2, "rate_limited": 5, "relay_other": 1, "relay_5xx": 1},
    {"success": 10, "relay_4xx": 3, "rate_limited": 3, "network": 4, "local": 1},
]
STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


def _run_report(i: int, counts: dict[str, int]) -> dict:
    report = _report(T0 + timedelta(days=i), base_url=f"https://relay-{i}.example/v1",
                     score=60.0 + 7 * i)
    report["outcomes"] = from_counts({"complete": counts}).model_dump()
    return report


@pytest.fixture
def runs(data):
    """The saved runs: id -> the outcomes block of its report."""
    out = {}
    for i, counts in enumerate(MIXES):
        report = _run_report(i, counts)
        rid = history.save(report)
        assert rid > 0
        out[rid] = report["outcomes"]
    return out


@pytest.fixture
def client(data):
    return TestClient(create_app(), base_url="http://localhost")


def _day(i: int) -> dict[str, str]:
    """A range holding run ``i`` alone."""
    start = (T0 + timedelta(days=i)).replace(hour=0, minute=0)
    return {"from": start.isoformat(), "to": (start + timedelta(days=1)).isoformat()}


def _tiles(body: dict) -> dict[str, dict]:
    return {t["id"]: t for t in body["tiles"]}


def test_rates_agree_between_report_history_and_analytics_and_add_up(runs, client):
    for i, (rid, stored) in enumerate(runs.items()):
        assert stored["requests_judged"] > 0
        want = {k: stored[k] for k in RATES}
        assert sum(want.values()) == pytest.approx(1.0, abs=1e-12)

        # the report as stored and as History opens it
        report = client.get(f"/api/history/{rid}", params={"trend": 1}).json()
        assert {k: report["outcomes"][k] for k in RATES} == want
        assert report["history_trends"]["error_rate"]["value"] == want["error_rate"]

        # History: the group of this run alone, its trend and its row
        groups = client.get("/api/history/groups", params={
            "trend.metrics": "score,error_rate", "group": "relay", "relay": report["target"]["base_url"],
        }).json()["groups"]
        (g,) = groups
        assert g["runs"] == 1 and g["latest"]["id"] == rid
        assert g["latest"]["error_rate"] == want["error_rate"]
        assert g["trends"]["error_rate"]["points"] == [want["error_rate"]]
        assert g["trends"]["error_rate"]["last"]["value"] == want["error_rate"]
        (row,) = client.get("/api/history/runs", params={"group": "relay", "group.key": g["key"]}).json()["rows"]
        assert row["id"] == rid and row["error_rate"] == want["error_rate"]

        # Analytics: the KPI tiles of a range holding this run alone
        tiles = _tiles(client.get("/api/analytics/summary", params=_day(i)).json())
        assert tiles["runs"]["value"] == 1
        for k in ("success_rate", "error_rate"):
            assert tiles[k]["value"] == want[k], (rid, k)
            assert (tiles[k]["numerator"], tiles[k]["denominator"]) == (
                round(want[k] * stored["requests_judged"]), stored["requests_judged"])

        # Analytics: the breakdown table and the request outcomes of that range
        (brow,) = client.get("/api/analytics/breakdown", params=[
            *_day(i).items(), *(("breakdown.metric", k) for k in RATES)]).json()["rows"]
        assert {k: brow["metrics"][k]["value"] for k in RATES} == want
        totals = client.get("/api/analytics/errors", params=_day(i)).json()["totals"]
        assert totals["judged"] == stored["requests_judged"]
        assert totals["requests"] == stored["requests_total"]
        assert (totals["success_rate"], totals["relay_error_rate"], totals["rate_limited_rate"]) == (
            want["success_rate"], want["error_rate"], want["rate_limited_rate"])
        assert totals["impaired_rate"] == stored["impaired_rate"]
        assert totals["success_rate"] + totals["relay_error_rate"] + totals["rate_limited_rate"] == \
            pytest.approx(1.0, abs=1e-12)


def test_rates_over_several_runs_are_pooled_and_add_up(runs, client):
    judged = sum(o["requests_judged"] for o in runs.values())
    pooled = {
        "success_rate": sum(o["counts"]["success"] for o in runs.values()) / judged,
        "rate_limited_rate": sum(o["counts"]["rate_limited"] for o in runs.values()) / judged,
    }
    pooled["error_rate"] = sum(
        o["counts"][k] for o in runs.values()
        for k in ("relay_timeout", "relay_5xx", "relay_4xx", "relay_other")) / judged
    median_of_runs = sorted(o["error_rate"] for o in runs.values())[len(runs) // 2]
    assert pooled["error_rate"] != pytest.approx(median_of_runs)  # the data tells them apart

    tiles = _tiles(client.get("/api/analytics/summary").json())
    assert tiles["success_rate"]["value"] == pytest.approx(pooled["success_rate"], abs=1e-12)
    assert tiles["error_rate"]["value"] == pytest.approx(pooled["error_rate"], abs=1e-12)
    (row,) = client.get("/api/analytics/breakdown", params=[
        ("group", "all"), *(("breakdown.metric", k) for k in RATES)]).json()["rows"]
    got = {k: row["metrics"][k]["value"] for k in RATES}
    assert got == pytest.approx(pooled, abs=1e-12)
    assert sum(got.values()) == pytest.approx(1.0, abs=1e-12)
    totals = client.get("/api/analytics/errors").json()["totals"]
    assert totals["relay_error_rate"] == pytest.approx(pooled["error_rate"], abs=1e-12)
    (g,) = client.get("/api/history/groups", params={"group": "all", "trend.metrics": "error_rate"}).json()["groups"]
    assert g["runs"] == len(runs)
    # the trend's points are the runs' own stored rates, oldest first
    assert g["trends"]["error_rate"]["points"] == [o["error_rate"] for o in runs.values()]


def test_every_aggregation_of_one_run_is_its_stored_value(runs, client):
    """n = 1: medians, shares and pooled rates of one run equal the run's
    stored values on every widget (tests/test_query.py checks every metric
    of the registry against the stored row)."""
    rid = next(iter(runs))
    report = client.get(f"/api/history/{rid}").json()
    tiles = _tiles(client.get("/api/analytics/summary", params=_day(0)).json())
    assert tiles["score"]["value"] == report["verdict"]["overall_score"]
    assert tiles["score"]["grade"] == scoring.rating(report["verdict"]["overall_score"])
    assert tiles["ttft_p50"]["value"] == report["performance"]["target"]["ttft_ms"]["p50"]
    assert tiles["decode_tps"]["value"] == report["performance"]["target"]["decode_tps_local"]["p50"]
    assert tiles["risk_high_share"]["value"] == 0.0
    trends = client.get(f"/api/history/{rid}", params={"trend": 1}).json()["history_trends"]
    (g,) = client.get("/api/history/groups", params={
        "trend.metrics": "score,decode_tps", "group": "relay", "relay": report["target"]["base_url"],
    }).json()["groups"]
    assert g["trends"]["score"]["points"] == [trends["score"]["value"]] == [report["verdict"]["overall_score"]]
    assert g["trends"]["decode_tps"]["points"] == [trends["decode_tps"]["value"]]
    assert trends["score"]["grade"] == g["trends"]["score"]["last"]["grade"] == tiles["score"]["grade"]


def test_a_save_from_another_process_drops_the_cached_answers(runs, client, data):
    """The CLI saves audits in its own process (``ekte audit``, ``ekte rescore
    --save``): the server's cached answers and ETags must not survive it."""
    paths = [("/api/analytics/summary", {}), ("/api/history/groups", {"trend.metrics": "score"}),
             ("/api/filters/options", {})]
    before = {}
    for path, params in paths:
        r = client.get(path, params=params)
        assert r.status_code == 200
        before[path] = r.headers["etag"]
        assert client.get(path, params=params, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    report = _run_report(len(MIXES), {"success": 3, "relay_5xx": 1})
    code = ("import json, sys; from ekte.web import history; "
            "sys.exit(0 if history.save(json.loads(sys.stdin.read())) > 0 else 1)")
    env = {**os.environ, "EKTE_DATA_DIR": str(data)}
    subprocess.run([sys.executable, "-c", code], input=json.dumps(report), text=True, env=env,
                   check=True, timeout=120)
    for path, params in paths:
        r = client.get(path, params=params, headers={"If-None-Match": before[path]})
        assert r.status_code == 200 and r.headers["etag"] != before[path], path
    assert _tiles(client.get("/api/analytics/summary").json())["runs"]["value"] == len(MIXES) + 1
    groups = client.get("/api/history/groups", params={"trend.metrics": "score"}).json()
    assert groups["total_runs"] == len(MIXES) + 1


# --------------------------------------------------------------------------- #
# No business rules in the browser
# --------------------------------------------------------------------------- #
PAGES = ("history.html", "analytics.html", "filters.js", "trendpick.js", "charts.js")


def _script(name: str) -> str:
    text = (STATIC / name).read_text(encoding="utf-8")
    if name.endswith(".html"):
        text = "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script\s*>", text, flags=re.S | re.I))
    # comments and string literals say nothing about what the code computes
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)//.*$", "", text)
    return re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", '""', text)


@pytest.mark.parametrize("name", PAGES)
def test_pages_do_no_metric_maths_grading_or_classification(name):
    code = _script(name)
    assert code.strip(), name
    # grading: no score thresholds (the server sends grade and colour family)
    for minimum, _letter in scoring.GRADE_THRESHOLDS:
        assert not re.search(rf"[<>]=?\s*{int(minimum)}\b(?!\s*[*/%])", code), (name, minimum)
    # classification: no HTTP status rules (the server sends outcome classes)
    assert not re.search(r"\b(?:status|status_code)\b\s*(?:[<>]=?|===?)\s*\d", code), name
    assert not re.search(r"(?:===?|[<>]=?)\s*(?:429|4\d\d|5\d\d)\b", code), name
    # aggregation: no medians, percentiles or pooled rates of its own
    assert not re.search(r"\bfunction\s+(?:median|percentile|quantile|pool\w*|grade\w*|rating)\b", code), name
    assert not re.search(r"\.(?:numerator|denominator)\s*[/+]", code), name
