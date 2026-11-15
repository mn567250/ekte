"""The web UI's KPI tile component (ekte/web/static/v2/kpi.js, #208), evaluated under node."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests._helpers import run_subprocess

_V2 = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"

_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;  // no DOM: html() and fromServer() only
require(path.join(process.argv[1], "kpi.js"));
const K = window.EkteKpi;
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const [name, c] of Object.entries(cases)) {
  if (c.server) {
    const ctx = Object.assign({
      label: (k) => "L(" + k + ")",
      fmt: (v, f) => (v == null ? "—" : f + ":" + v),
      fmtDelta: (d, f) => "d" + d,
    }, c.ctx || {});
    out[name] = c.server.map((t) => K.fromServer(t, ctx));
  } else {
    out[name] = K.html(c.tiles, c.opts || {});
  }
}
console.log(JSON.stringify(out));
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")


def _run(cases: dict) -> dict:
    return json.loads(run_subprocess(["node", "-e", _JS, str(_V2), json.dumps(cases)],
                                     capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def _server_tile(**over) -> dict:
    t = {"id": "success_rate", "applies": True, "value": 0.97, "format": "percent", "label_key": "metric.success_rate",
         "hint_key": "metric.success_rate.agg_hint", "delta": 0.01, "direction": "better", "trend_key": "trend.rising",
         "n": 5, "group": 0, "family": "good"}
    t.update(over)
    return t


@needs_node
def test_grid_tiles_value_delta_hint_and_na():
    out = _run({
        "grid": {"opts": {"label": "Key figures", "cols": 4, "idp": "k"}, "tiles": [
            {"id": "a", "label": "Runs", "text": "47", "value": 47},
            {"id": "b", "label": "Error <rate>", "text": "2.2%", "hint": "Pooled.",
             "delta": {"text": "+0.4 pp", "sign": 1, "dir": "worse", "sr": "rising"}, "caption": "Data from 3 of 5 runs"},
            {"id": "c", "label": "TTFT", "na": True},
            {"id": "d", "label": "Impaired", "text": "0%", "group": 1, "note": "No data in the previous period"},
        ]},
    })
    html = out["grid"]
    assert html.startswith('<ul class="kpis cols" style="--kpi-cols:4" aria-label="Key figures">')
    assert '<li class="kpi" data-id="a">' in html
    # the figure counts up hidden; the screen reader reads the final value
    assert '<span aria-hidden="true" data-kv="a">47</span><span class="sr-only">47</span>' in html
    assert "Error &lt;rate&gt;" in html and "<rate>" not in html
    assert '<button type="button" class="khint" aria-describedby="k-b" aria-label="About: Error &lt;rate&gt;">' in html
    assert '<span class="ktip" role="tooltip" id="k-b">Pooled.</span>' in html
    assert '<span class="kd bad"><span aria-hidden="true">▲ </span><span class="sr-only">rising </span>+0.4 pp · worse</span>' in html
    assert '<span class="kc">Data from 3 of 5 runs</span>' in html
    assert '<li class="kpi na" data-id="c">' in html and ">n/a</span>" in html and "Not measured on this surface" in html
    # a new group: a divider before it
    assert '<li class="kpi sep" data-id="d">' in html and '<span class="kd few">No data in the previous period</span>' in html


@needs_node
def test_compact_tiles_with_a_slot_unit_and_family():
    html = _run({"c": {"opts": {"variant": "compact", "align": "end"}, "tiles": [
        {"id": "latency_p50", "label": "Latency", "text": "812", "unit": "ms", "family": "warn", "slot": "<svg></svg>"},
        {"id": "score", "label": "Score", "text": ""},
    ]}})["c"]
    assert html.startswith('<ul class="kpis compact end">')
    assert '<li class="kpi f-warn slotted" data-id="latency_p50"><span class="kslot"><svg></svg></span>' in html
    assert ">812<small>ms</small></span><span class=\"sr-only\">812 ms</span>" in html
    assert '<span class="kv none"><span aria-hidden="true" data-kv="score">—</span><span class="sr-only">no data</span>' in html


@needs_node
def test_server_tiles_map_to_tiles():
    out = _run({
        "prev": {"server": [_server_tile(), _server_tile(id="error_rate", delta=None, hint_key=None),
                            _server_tile(id="ttft_p50", applies=False),
                            _server_tile(id="score", direction="none", n=2)],
                 "ctx": {"previous": True, "runs": 5, "fewId": "few"}},
        "noprev": {"server": [_server_tile(n=0)], "ctx": {"previous": False, "runs": 5}},
    })
    ok, nodelta, na, faded = out["prev"]
    assert ok["text"] == "percent:0.97" and ok["value"] == 0.97 and ok["label"] == "L(metric.success_rate)"
    assert ok["delta"] == {"text": "d0.01", "sign": 1, "dir": "better", "sr": "L(trend.rising)"}
    assert ok["hint"].startswith("L(metric.success_rate.agg_hint). Relay failures only")
    assert ok["caption"] == "" and "faded" not in ok
    assert nodelta["note"] == "No data in the previous period" and "hint" not in nodelta
    assert na == {"id": "ttft_p50", "label": "L(metric.success_rate)", "group": 0, "kind": "percent", "na": True}
    assert faded["faded"] == "few" and faded["caption"] == "Data from 2 of 5 runs"
    (none,) = out["noprev"]
    assert "delta" not in none and "note" not in none and none["caption"] == "Not measured in these runs"
