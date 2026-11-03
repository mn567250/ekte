"""The v2 charts (ekte/web/static/v2/charts.js), evaluated under node: bars,
points and annotation lines stay inside the plot even when a bucket starts
before or ends after the caller's domain (#84)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")

STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"

# a minimal DOM: the charts only set host.innerHTML and wire listeners
_JS = r"""
const path = require("path");
const stub = () => ({ addEventListener() {}, setAttribute() {}, querySelector: stub });
global.document = { addEventListener() {}, removeEventListener() {} };
global.window = {};
require(path.join(process.argv[1], "charts.js"));
const C = window.EkteCharts;
const [kind, cfg] = JSON.parse(process.argv[2]);
const host = { clientWidth: 640, innerHTML: "", querySelector: stub };
cfg.xTick = (t) => String(t);
cfg.tipTime = (t) => String(t);
cfg.totalText = () => "";
C[kind](host, cfg);
console.log(host.innerHTML);
"""

DAY = 86_400_000
WEEK = 7 * DAY
MON_SEP_29 = 1_759_096_800_000  # 2025-09-29 00:00 Europe/Berlin (a Monday)
SUN_OCT_5 = MON_SEP_29 + 6 * DAY
WED_OCT_29 = MON_SEP_29 + 30 * DAY  # a range ending mid-week


def render(kind: str, cfg: dict) -> str:
    return subprocess.run(
        ["node", "-e", _JS, str(STATIC), json.dumps([kind, cfg])],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout


def plot_x(svg: str) -> tuple[float, float]:
    """The plot's left and right edge: the x axis line."""
    m = re.search(r'<g class="xaxis"><line x1="([\d.]+)" x2="([\d.]+)"', svg)
    assert m, svg
    return float(m.group(1)), float(m.group(2))


def weeks(n: int) -> list[int]:
    return [MON_SEP_29 + i * WEEK for i in range(n)]


def test_stack_bars_stay_inside_the_plot():
    # range Sun Oct 5 .. Wed Oct 29: the first week starts 6 days before it,
    # the last (Mon Oct 27) ends 5 days after it
    bars = [{"t": t, "total": 10, "counts": {"e": 2}, "runs": 1, "low": False} for t in weeks(5)]
    svg = render("stackBars", {
        "id": "c", "title": "t", "desc": "d", "bucketMs": WEEK, "domain": [SUN_OCT_5, WED_OCT_29],
        "lowHint": "", "cats": [{"id": "e", "label": "E", "cls": "k-a"}], "bars": bars,
    })
    left, right = plot_x(svg)
    segs = re.findall(r'<rect class="seg [^"]*" x="([\d.-]+)" y="[\d.-]+" width="([\d.]+)"', svg)
    assert len(segs) == 5
    for x, w in segs:
        assert float(x) >= left - 0.05 and float(x) + float(w) <= right + 0.05, (x, w, left, right)


def test_stack_bars_keep_a_domain_wider_than_the_data():
    # the domain still sets the range when it covers every bucket
    bars = [{"t": SUN_OCT_5 + DAY, "total": 10, "counts": {"e": 2}, "runs": 1, "low": False}]
    svg = render("stackBars", {
        "id": "c", "title": "t", "desc": "d", "bucketMs": DAY, "domain": [SUN_OCT_5, SUN_OCT_5 + 10 * DAY],
        "lowHint": "", "cats": [{"id": "e", "label": "E", "cls": "k-a"}], "bars": bars,
    })
    left, right = plot_x(svg)
    x, w = map(float, re.search(r'<rect class="seg [^"]*" x="([\d.-]+)" y="[\d.-]+" width="([\d.]+)"', svg).groups())
    centre = (x + w / 2 - left) / (right - left)
    assert centre == pytest.approx(0.15, abs=0.005)  # day 1.5 of 10


def test_time_chart_points_and_marks_stay_inside_the_plot():
    pts = [{"t": t, "v": 0.5, "n": 3, "runs": 3} for t in weeks(5)]
    svg = render("timeChart", {
        "id": "c", "title": "t", "desc": "d", "unit": "ratio", "bucketMs": WEEK,
        "domain": [SUN_OCT_5, WED_OCT_29], "lowHint": "",
        "series": [{"label": "A", "cls": "s0", "points": pts}],
        "marks": [
            {"t": MON_SEP_29, "kind": "tool_version", "text": "v1 -> v2"},
            {"t": MON_SEP_29 - 4 * WEEK, "kind": "kb_profile", "text": "before the plot"},
        ],
    })
    left, right = plot_x(svg)
    # every marker path starts with "M<x>,<y>"; the shapes reach 4 px around the point
    xs = [float(x) for x in re.findall(r'<path class="pt[^"]*" d="M([\d.-]+),', svg)]
    assert len(xs) == 5
    assert all(left - 5 <= x <= right + 5 for x in xs), (xs, left, right)
    # the line through them too
    line = re.search(r'<path class="line" d="M([^"]+)"', svg).group(1)
    for x in (float(p.split(",")[0]) for p in line.split("L")):
        assert left <= x <= right
    # one annotation line (the mark in the first week); the one weeks before
    # the data is left out
    marks = re.search(r'<g class="marks">(.*?)</g>', svg).group(1)
    mx = [float(x) for x in re.findall(r'<line x1="([\d.-]+)"', marks)]
    assert len(mx) == 1 and left <= mx[0] <= right
