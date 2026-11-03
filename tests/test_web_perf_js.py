"""The web UI's performance panel (ekte/web/static/perf.js), evaluated under node."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ekte.models import RequestRecord
from ekte.perf import build_performance

_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;  // no DOM: the style injection must be skipped
require(path.join(process.argv[1], "perf.js"));
const perf = JSON.parse(process.argv[2]);
const P = window.EktePerf;
console.log(JSON.stringify({
  section: P.section(perf),
  empty: P.section(null),
  tps: P.chart(perf.requests, "tps"),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_renders_section_and_chart():
    recs = [
        RequestRecord(seq=i, endpoint=ep, phase="probe", ok=True, stream=True,
                      start_ms=i * 1000.0, duration_ms=900.0, ttft_ms=250.0,
                      decode_tps_local=100.0 if ep == "target" else 50.0,
                      detector='<img src=x onerror=alert(1)>')
        for i, ep in enumerate(["target", "baseline"] * 3)
    ]
    recs.append(RequestRecord(seq=9, endpoint="target", phase="probe", ok=False, status_code=502))
    perf = build_performance(recs, has_baseline=True, probe_max_tokens=128)
    assert perf is not None
    static = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static"
    out = json.loads(subprocess.run(
        ["node", "-e", _JS, str(static), perf.model_dump_json()],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    section = out["section"]
    assert out["empty"] == ""
    # probe requests: small, translucent dots (class "probe")
    assert "<svg" in section and 'class="zp-pt t probe"' in section and 'class="zp-pt b probe"' in section
    assert 'class="zp-fail"' in section  # the failed request
    assert "Target vs baseline" in section and "Decode speed p50 (local)" in section
    assert "<img" not in section and "&lt;img" in section  # detector ids are escaped
    assert "zp-pt" in out["tps"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_colors_deltas_and_shows_both_modes():
    recs = []
    for _ in range(4):
        for stream in (True, False):
            for ep, lat in (("target", 800.0), ("baseline", 1200.0)):
                recs.append(RequestRecord(
                    seq=len(recs), endpoint=ep, phase="probe", ok=True, stream=stream,
                    start_ms=len(recs) * 100.0, duration_ms=lat,
                    ttft_ms=200.0 if stream else None,
                    decode_tps_local=(40.0 if ep == "target" else 80.0) if stream else None,
                    e2e_tps_local=100.0,
                ))
    perf = build_performance(recs, has_baseline=True)
    assert perf is not None and [m.mode for m in perf.modes] == ["non_stream"]
    static = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static"
    section = json.loads(subprocess.run(
        ["node", "-e", _JS, str(static), perf.model_dump_json()],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)["section"]
    # lower latency: better (green ✓); lower decode speed: worse (red ✗)
    assert 'class="r zp-better">✓ -400' in section
    assert 'class="r zp-worse">✗ -40.0' in section
    assert "Streaming" in section and "Non-streaming" in section
    assert 'zp-pt t hollow' in section and "non-streaming request (hollow)" in section
    assert "End-to-end speed p50" in section  # non-stream tiles


_STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static"


def _render(perf_json: str) -> dict:
    js = _JS.replace("tps: P.chart(perf.requests, \"tps\"),", "tps: P.chart(perf.requests, \"tps\"), css: P.CSS,")
    return json.loads(subprocess.run(
        ["node", "-e", js, str(_STATIC), perf_json], capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)


def _perf():
    recs = [
        RequestRecord(seq=i, endpoint=ep, phase="probe", ok=True, stream=True,
                      start_ms=i * 1000.0, duration_ms=900.0, ttft_ms=250.0, decode_tps_local=80.0)
        for i, ep in enumerate(["target", "baseline"] * 2)
    ]
    recs.append(RequestRecord(seq=7, endpoint="target", phase="probe", ok=False, status_code=502))
    perf = build_performance(recs, has_baseline=True, probe_max_tokens=128)
    assert perf is not None
    return perf


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_css_colours_only_through_variables():
    import re

    css = _render(_perf().model_dump_json())["css"]
    # All colour literals live in the :where() block of --zp-* defaults.
    defaults = re.match(r":where\(\.zp-section,\.zp-live,\.zp-tip\)\{([^}]*)\}", css)
    assert defaults
    decls = dict(d.split(":", 1) for d in defaults.group(1).split(";"))
    assert all(k.startswith("--zp-") for k in decls)
    assert decls["--zp-t"] == "#2a78d6" and decls["--zp-tile"] == "#f5f8f4"  # built-in defaults
    rest = css[defaults.end():]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|(?<![\w-])(white|black)(?![\w-])", rest)
    # v2 maps every property the injected CSS uses.
    v2 = (_STATIC / "v2" / "perf.css").read_text(encoding="utf-8")
    for prop in set(re.findall(r"var\((--zp-[\w-]+)", css)):
        assert prop + ":" in v2, prop


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_tabs_and_chart_are_accessible():
    section = _render(_perf().model_dump_json())["section"]
    assert 'role="tablist"' in section and section.count('role="tab"') == 4
    assert 'aria-selected="true"' in section and section.count('aria-selected="false"') == 3
    assert 'tabindex="0"' in section and section.count('tabindex="-1"') == 3
    assert 'aria-controls="zp1-panel"' in section and 'role="tabpanel" id="zp1-panel"' in section
    assert 'aria-labelledby="zp1-tab-latency"' in section
    assert 'role="img" aria-label="Latency (ms) over time: 5 requests; target median 900 ms; ' \
           'baseline median 900 ms; 1 failed"' in section
    # the tooltip contents are also in a data table
    assert '<details class="zp-data">' in section and "Show data table" in section
    assert "failed (502)" in section.split('class="zp-data"')[1]


def test_perf_fragment_translates_every_key():
    base = Path(__file__).resolve().parent.parent / "ekte" / "i18n" / "locales" / "fragments" / "v2-perf"
    en = json.loads((base / "en.json").read_text(encoding="utf-8"))["strings"]
    assert all(k == v for k, v in en.items())
    for code in ("fr", "es", "pt", "it", "de", "nb"):
        tr = json.loads((base / f"{code}.json").read_text(encoding="utf-8"))["strings"]
        assert set(tr) == set(en), code


_LIVE_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;
require(path.join(process.argv[1], "perf.js"));
global.document = { activeElement: null };  // after load: style injection stays skipped
const host = { innerHTML: "", contains: () => false, querySelector: () => null, querySelectorAll: () => [] };
const live = new window.EktePerf.Live(host);
live.records = JSON.parse(process.argv[2]);
live.render();
console.log(JSON.stringify({ html: host.innerHTML }));
"""


def _live(recs: list[RequestRecord]) -> str:
    payload = json.dumps([r.model_dump() for r in recs])
    return json.loads(subprocess.run(
        ["node", "-e", _LIVE_JS, str(_STATIC), payload], capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)["html"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_live_tiles_show_ttft_and_decode_speed_for_streamed_calls():
    html = _live([
        RequestRecord(seq=i, endpoint="target", phase="probe", op="complete", ok=True, stream=True,
                      start_ms=i * 100.0, duration_ms=900.0, ttft_ms=250.0, decode_tps_local=80.0)
        for i in range(3)
    ])
    assert "TTFT p50</div><div class=\"zp-tv\">250 ms" in html
    assert "Decode speed p50</div><div class=\"zp-tv\">80.0 tok/s" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_live_tiles_fall_back_to_end_to_end_speed_without_streamed_calls():
    html = _live([
        RequestRecord(seq=i, endpoint="target", phase="passive", op="complete", ok=True, stream=False,
                      start_ms=i * 100.0, duration_ms=1000.0, e2e_tps_local=42.0)
        for i in range(3)
    ])
    assert "TTFT p50</div><div class=\"zp-tv\">—<" in html  # no first token without streaming
    assert "End-to-end speed p50</div><div class=\"zp-tv\">42.0 tok/s" in html


_AXIS_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;
require(path.join(process.argv[1], "perf.js"));
const recs = JSON.parse(process.argv[2]);
console.log(JSON.stringify({chart: window.EktePerf.chart(recs, "ttft"), axis: window.EktePerf.niceAxis(510)}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_axes_fit_the_data():
    # An audit ending around 500 s with TTFT up to 350 ms: the live chart used
    # to stretch to 1000 s and 500 ms, leaving much of the plot empty. The
    # time axis now ends where the last request ended (not at a rounded-up
    # 600 s): its last dot sits at the right edge.
    recs = [{"seq": i, "op": "complete", "endpoint": "target", "phase": "probe", "ok": True,
             "stream": True, "start_ms": i * 50_000.0, "duration_ms": 900.0, "ttft_ms": 300.0 + i * 5}
            for i in range(11)]
    static = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static"
    out = json.loads(subprocess.run(
        ["node", "-e", _AXIS_JS, str(static), json.dumps(recs)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    assert out["axis"] == {"max": 600, "step": 100, "n": 6}
    chart = out["chart"]
    ticks = re.findall(r'<text class="zp-tick" x="([\d.]+)" y="216" text-anchor="(\w+)">([^<]+)</text>', chart)
    assert [t[2] for t in ticks] == ["0s", "100s", "200s", "300s", "400s"]  # 500s would not fit before the edge
    assert ticks[0][1] == "start" and {t[1] for t in ticks[1:]} == {"middle"}
    assert "600s" not in chart and "1,000s" not in chart
    last = max(float(c) for c in re.findall(r'<circle class="zp-pt[^"]*" cx="([\d.]+)"', chart))
    assert 720 - 12 - last < 2  # 500 s of 500.9 s: at the plot's right edge
    assert 'text-anchor="end">400</text>' in chart and ">500</text>" not in chart  # 350 x 1.05 -> 0..400


_FMT_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;
let made = 0;
const Real = Intl.NumberFormat;
Intl.NumberFormat = function (locale, opts) { made++; return new Real(locale, opts); };
require(path.join(process.argv[1], "perf.js"));
const P = window.EktePerf;
const recs = JSON.parse(process.argv[2]);
const out = {};
for (const locale of ["", "en-US", "de-DE", "zh-CN"]) {
  window.EKTE_LANG = locale ? { t: (zh, en) => en, locale: () => locale } : undefined;
  const loc = locale || undefined;
  const a = P.chart(recs, "latency"), b = P.chart(recs, "latency");
  // what the cached formatters must match: Number#toLocaleString
  const one = (v) => v.toLocaleString(loc, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  out[locale] = {
    stable: a === b,
    latency: a.includes("Latency: " + Math.round(1234.5).toLocaleString(loc) + " ms"),
    ttft: a.includes("TTFT: " + one(12.25) + " ms"),
    tick: a.includes(">" + (1000).toLocaleString(loc) + "</text>"),
    tps: P.chart(recs, "tps").includes("Decode speed: " + (0.5).toLocaleString(loc, {
      minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " tok/s"),
  };
}
console.log(JSON.stringify({ out, made }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_number_formatters_are_cached_with_the_same_output():
    recs = [{"seq": i, "op": "complete", "endpoint": "target", "phase": "probe", "ok": True,
             "stream": True, "start_ms": i * 1000.0, "duration_ms": 1234.5, "ttft_ms": 12.25,
             "decode_tps_local": 0.5}
            for i in range(40)]
    res = json.loads(subprocess.run(
        ["node", "-e", _FMT_JS, str(_STATIC), json.dumps(recs)], capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    for locale, o in res["out"].items():
        assert o == {"stable": True, "latency": True, "ttft": True, "tick": True, "tps": True}, locale
    # one formatter per locale and digit count, however many numbers are drawn
    # (4 locales x {integer, 1, 2 digits}), not one per number
    assert 0 < res["made"] <= 12


_LIVE_OPEN_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;
require(path.join(process.argv[1], "perf.js"));
global.document = { activeElement: null };
const out = {};
for (const open of [false, true]) {
  const host = { innerHTML: "", contains: () => false, querySelector: () => null, querySelectorAll: () => [] };
  const live = new window.EktePerf.Live(host);
  live.reset({ probeTotal: 10 });
  live.records = JSON.parse(process.argv[2]);
  live.open = open;
  live.render();
  out[open] = host.innerHTML;
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_live_builds_the_data_table_only_when_open():
    recs = [RequestRecord(seq=i, endpoint="target", phase="probe", op="complete", ok=i != 2, stream=True,
                          status_code=200 if i != 2 else 502, start_ms=i * 100.0, duration_ms=900.0)
            for i in range(4)]
    out = json.loads(subprocess.run(
        ["node", "-e", _LIVE_OPEN_JS, str(_STATIC), json.dumps([r.model_dump() for r in recs])],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    closed, opened = out["false"], out["true"]
    # the toggle is there either way (keyboard and screen readers reach it) ...
    for html in (closed, opened):
        assert '<summary>Show data table</summary><div class="zp-data-scroll" tabindex="0">' in html
        assert 'role="progressbar" aria-label="Performance probe" aria-valuemin="0" aria-valuemax="10" ' \
               'aria-valuenow="4"' in html
        assert re.search(r'role="tabpanel" id="(zpl\d+)-panel" aria-labelledby="\1-tab-latency"', html)
    # ... but only an open one carries its rows
    assert '<details class="zp-data"><summary>' in closed and "<table" not in closed
    assert '<details class="zp-data" open><summary>' in opened and opened.count("<tr>") == 5
    assert "failed (502)" in opened



@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_live_embedding_audit_offers_latency_only_with_its_trend():
    # an embedding audit's calls return no tokens and never stream: the live
    # panel shows the latency tab alone (as its report does), and the stream's
    # running median draws the line and band behind the dots
    from ekte.perf.trend import attach_trends
    recs = [RequestRecord(seq=i, endpoint="target", phase="probe", op="embed", ok=True, stream=False,
                          status_code=200, start_ms=i * 100.0, duration_ms=10.0 + i).model_dump()
            for i in range(6)]
    attach_trends(recs)
    html = json.loads(subprocess.run(
        ["node", "-e", _LIVE_OPEN_JS, str(_STATIC), json.dumps(recs)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)["false"]
    assert html.count('role="tab"') == 1 and 'data-metric="latency"' in html
    assert "TTFT" not in html and "Decode speed" not in html and "Inter-chunk" not in html
    assert '<g class="zp-band">' in html and '<g class="zp-trend">' in html

_REC_JS = """window.mk = (i, ok = true) => ({seq: i, endpoint: i % 2 ? 'baseline' : 'target', phase: 'probe',
  op: 'complete', stream: true, start_ms: i * 400, ok, status_code: ok ? 200 : 502,
  duration_ms: 800 + (i % 7) * 40, ttft_ms: 300 + i, decode_tps_local: 60, itl_mean_ms: 9});"""


def test_live_panel_updates_in_place_in_a_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("EKTE_A11Y_CHROMIUM") or None)
        except Exception as e:  # no browser installed
            pytest.skip(f"no Chromium: {e}")
        try:
            _drive_live_panel(browser.new_page())
        finally:
            browser.close()


def _drive_live_panel(page) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_content('<!doctype html><html lang="en"><head><title>t</title></head><body><div id="host"></div></body></html>')
    page.add_script_tag(content=(_STATIC / "perf.js").read_text(encoding="utf-8"))
    page.add_script_tag(content=_REC_JS)
    page.evaluate("""() => {
      window.L = new EktePerf.Live(document.getElementById('host'));
      L.reset({probeTotal: 50, hasBaseline: true});
      for (let i = 0; i < 20; i++) L.records.push(mk(i, i !== 5));
      L.render();
      window.firstTile = document.querySelector('.zp-tv');
      window.firstTab = document.querySelector('.zp-tabs [data-metric="ttft"]');
      window.firstSummary = document.querySelector('.zp-data summary');
    }""")
    # closed: the table is not built
    assert page.evaluate("document.querySelectorAll('.zp-data-scroll tr').length") == 0
    # streamed records while a metric tab has keyboard focus
    page.focus('.zp-tabs [data-metric="ttft"]')
    page.evaluate("() => { L.records.push(mk(20)); L.render(); }")
    state = page.evaluate("""() => ({
      sameTile: document.querySelector('.zp-tv') === firstTile,
      sameTab: document.querySelector('.zp-tabs [data-metric="ttft"]') === firstTab,
      focus: document.activeElement.getAttribute('data-metric'),
      requests: document.querySelector('.zp-tv').textContent,
      now: document.querySelector('.zp-bar').getAttribute('aria-valuenow'),
      width: document.querySelector('.zp-bar i').style.width,
      label: document.querySelector('.zp-chart').getAttribute('aria-label'),
    })""")
    assert state["sameTile"] and state["sameTab"] and state["focus"] == "ttft"
    assert state["requests"] == "21" and state["now"] == "11" and state["width"] == "22%"
    assert state["label"].startswith("Latency (ms) over time: 21 requests")
    # keyboard: the arrow key selects and focuses the next tab
    page.evaluate("() => { window.foc = []; document.addEventListener('focusin', e => foc.push(e.target.dataset.metric)); }")
    page.keyboard.press("ArrowRight")
    assert page.evaluate("foc") == ["tps"]  # straight to the new tab, not via the old one
    # the buttons stay; their markup is what a fresh render draws
    assert page.evaluate("document.querySelector('.zp-tabs [data-metric=\"ttft\"]') === firstTab")
    assert page.evaluate("""() => { const h = document.createElement('div'); document.body.appendChild(h);
      const M = new EktePerf.Live(h); M.pid = L.pid; M.records = L.records.slice(); M.metric = L.metric; M.render();
      const s = h.querySelector('.zp-tabs').outerHTML; h.remove();
      return s === document.querySelector('#host .zp-tabs').outerHTML; }""")
    tabs = page.evaluate("""() => [...document.querySelectorAll('.zp-tabs [role=tab]')].map(b =>
      [b.dataset.metric, b.getAttribute('aria-selected'), b.tabIndex, b === document.activeElement])""")
    assert ["tps", "true", 0, True] in tabs and ["ttft", "false", -1, False] in tabs
    assert page.get_attribute(".zp-plot", "aria-labelledby").endswith("-tab-tps")
    page.evaluate("() => { L.records.push(mk(21)); L.render(); }")
    assert page.evaluate("document.activeElement.dataset.metric") == "tps"
    # opening the toggle with the keyboard builds the table right away
    page.focus(".zp-data summary")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('.zp-data').open && L.open")
    assert page.evaluate("document.querySelectorAll('.zp-data-scroll tbody tr').length") == 22
    page.evaluate("() => { L.records.push(mk(22)); L.render(); }")
    assert page.evaluate("document.querySelector('.zp-data summary') === firstSummary")
    assert page.evaluate("document.activeElement === firstSummary")
    # new records are appended; the focused, scrolled table stays put
    page.evaluate("() => { for (let i = 23; i < 80; i++) L.records.push(mk(i)); L.render(); }")
    page.focus(".zp-data-scroll")
    page.evaluate("document.querySelector('.zp-data-scroll').scrollTop = 120")
    page.evaluate("() => { L.records.push(mk(80, false)); L.render(); }")
    box = page.evaluate("""() => { const b = document.querySelector('.zp-data-scroll');
      return {top: b.scrollTop, focused: b === document.activeElement, rows: b.querySelectorAll('tbody tr').length,
              last: b.querySelector('tbody tr:last-child').textContent}; }""")
    assert box["top"] == 120 and box["focused"] and box["rows"] == 81
    assert box["last"].startswith("80") and "failed (502)" in box["last"]
    # the appended table is the one a fresh render builds
    fresh = page.evaluate("""() => { const h = document.createElement('div'); document.body.appendChild(h);
      const M = new EktePerf.Live(h); M.records = L.records.slice(); M.metric = L.metric; M.open = true; M.render();
      const s = h.querySelector('.zp-data-scroll').innerHTML; h.remove(); return s; }""")
    assert fresh == page.evaluate("document.querySelector('#host .zp-data-scroll').innerHTML")
    # a metric switch rebuilds it for that metric
    page.evaluate("() => L.setMetric('latency')")
    assert "Latency" in page.evaluate("document.querySelector('#host .zp-data-scroll thead').textContent")
    # a language switch redraws the labels and keeps focus on the selected tab
    page.focus('.zp-tabs [data-metric="latency"]')
    page.evaluate("() => { window.EKTE_LANG = {t: (zh, en) => zh, locale: () => 'zh-CN'}; L.render(); }")
    zh = page.evaluate("""() => [document.activeElement.dataset.metric, document.activeElement.textContent,
      document.querySelector('#host .zp-data summary').textContent,
      document.querySelector('#host .zp-data-scroll thead').textContent.includes('延迟'),
      document.querySelectorAll('#host .zp-data-scroll tbody tr').length]""")
    assert zh == ["latency", "延迟", "查看数据表", True, 81]
    page.evaluate("() => { delete window.EKTE_LANG; L.render(); }")
    # tooltips work on marks drawn after the first render
    page.locator("#host .zp-pt").last.hover()
    tip = page.evaluate("() => { const t = document.querySelector('.zp-tip'); return [t.style.display, t.textContent]; }")
    assert tip[0] == "block" and tip[1].startswith("#")
    page.mouse.move(1, 1)
    assert page.evaluate("document.querySelector('.zp-tip').style.display") == "none"
    # once closed, later renders leave the table alone
    page.evaluate("() => { document.querySelector('.zp-data').open = false; }")
    page.wait_for_function("L.open === false")
    page.evaluate("() => { L.records.push(mk(81)); L.render(); }")
    assert page.evaluate("document.querySelectorAll('#host .zp-data-scroll tbody tr').length") == 81
    assert errors == []


_SCALE_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;
require(path.join(process.argv[1], "perf.js"));
global.document = { activeElement: null };
const P = window.EktePerf;
const recs = JSON.parse(process.argv[2]);
const live = (total, n, user) => {
  const host = { innerHTML: "", contains: () => false, querySelector: () => null, querySelectorAll: () => [] };
  const l = new P.Live(host);
  l.reset({ probeTotal: total });
  l.records = recs.slice(0, n);
  l.scale = user || null;
  l.render();
  return host.innerHTML;
};
const audit = recs.filter((r) => r.phase === "passive").length;
console.log(JSON.stringify({
  full: P.chart(recs, "latency"),
  focus: P.chart(recs, "latency", { scale: "probe" }),
  early: P.chart(recs.slice(0, audit + 2), "latency", { scale: "probe" }),
  later: P.chart(recs.slice(0, audit + 5).concat(recs.slice(-1)), "latency", { scale: "probe" }),
  running: live(20, audit + 8),
  finished: live(20, recs.length),
  chosen: live(20, audit + 8, "full"),
  auditOnly: live(0, audit),
  report: P.section({ target: {}, requests: recs }),
}));
"""


def _scale_records() -> list[dict]:
    from ekte.perf.trend import attach_trends

    recs: list[dict] = []
    for i, ms in enumerate([12_000, 58_000, 9_000, 101_000, 3_500, 74_000, 22_000, 98_000, 41_000, 7_500]):
        recs.append({"seq": len(recs) + 1, "op": "complete", "endpoint": "target", "phase": "passive", "ok": True,
                     "stream": True, "start_ms": i * 50_000.0, "duration_ms": float(ms)})
    # the first five probe requests: p25 1,550, p75 1,700 -> top max(2,150, 2,550) -> axis 0..3,000
    probe = [1500, 2600, 1700, 1550, 1650] + [1600] * 14 + [9000]
    for i, ms in enumerate(probe):
        recs.append({"seq": len(recs) + 1, "op": "complete", "endpoint": "target", "phase": "probe", "ok": True,
                     "stream": True, "start_ms": 600_000.0 + i * 2_000, "duration_ms": float(ms)})
    attach_trends(recs)
    return recs


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_probe_focus_fixes_the_range_from_the_first_probe_requests():
    out = json.loads(subprocess.run(
        ["node", "-e", _SCALE_JS, str(_STATIC), json.dumps(_scale_records())],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    full, focus = out["full"], out["focus"]
    # full range: everything on the plot, no triangles
    assert "zp-off" not in full and 'text-anchor="end">3,000</text>' not in full
    # probe focus: 0..3,000 from the first five probe requests; the ten audit
    # requests and the one slow probe request sit as triangles on the top edge
    assert 'text-anchor="end">3,000</text>' in focus
    assert focus.count('class="zp-off t"') == 11
    assert "y-axis focused on the probe: 0 to 3,000 ms, 11 requests above it" in focus
    # the range stays put however the probe goes on (here: a 9 s request) ...
    assert 'text-anchor="end">3,000</text>' in out["later"]
    # ... and is provisional before the fifth request (two: 1,500 and 2,600 -> 0..4,000)
    assert 'text-anchor="end">4,000</text>' in out["early"]
    # the running median sits in its p25–p75 band; probe dots are small
    assert '<g class="zp-band"><path class="t" d="M' in full and 'r="3"' in full


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_live_focuses_on_the_probe_while_it_runs_unless_the_user_chose():
    out = json.loads(subprocess.run(
        ["node", "-e", _SCALE_JS, str(_STATIC), json.dumps(_scale_records())],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    pressed = lambda html, s: f'data-scale="{s}" aria-pressed="true"' in html  # noqa: E731
    # "Full range" comes first, then "Probe focus"
    assert out["running"].index('data-scale="full"') < out["running"].index('data-scale="probe"')
    assert pressed(out["running"], "probe") and "automatic · range from the first 5 probe requests" in out["running"]
    assert "· ▲ 10 above 3,000 ms</span>" in out["running"]  # the ten audit requests
    assert pressed(out["finished"], "full") and "Back to automatic" not in out["finished"]
    assert pressed(out["chosen"], "full") and "set by you" in out["chosen"] and "Back to automatic" in out["chosen"]
    assert 'role="group" aria-label="Y-axis range"' in out["running"] and 'class="zp-sr" role="status"' in out["running"]
    assert "zp-scale" not in out["auditOnly"]  # no probe, no switch
    # a finished report starts on the full range
    assert pressed(out["report"], "full") and "zp-scale" in out["report"]


_PARITY_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;
require(path.join(process.argv[1], "perf.js"));
console.log(JSON.stringify({chart: window.EktePerf.chart(JSON.parse(process.argv[2]), "latency")}));
"""


def _points(d: str) -> list[tuple[float, float]]:
    return [(float(a), float(b)) for a, b in re.findall(r"(-?[\d.]+),(-?[\d.]+)", d)]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_web_and_export_charts_draw_the_same_trend_and_axes():
    # perf.js (live view and web report) and the exports (HTML here; the PDF
    # draws the same Timeline) plot the same running median, p25–p75 band and
    # time axis: compared in data units, as their canvases differ
    from ekte.perf.trend import attach_trends
    from ekte.report.performance import CHART_METRICS, Timeline, timeline_svg

    recs = [RequestRecord(seq=i, endpoint="baseline" if i % 3 == 2 else "target", phase="probe", ok=i != 4,
                          stream=True, status_code=200 if i != 4 else 502, start_ms=i * 700.0,
                          duration_ms=600.0 + (i * 37) % 250) for i in range(14)]
    dumped = [r.model_dump() for r in recs]
    attach_trends(dumped)  # as the web UI gets them
    web = json.loads(subprocess.run(
        ["node", "-e", _PARITY_JS, str(_STATIC), json.dumps(dumped)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)["chart"]
    export = timeline_svg(recs, CHART_METRICS[0])
    tl = Timeline(recs, CHART_METRICS[0])

    def unit(svg_pts, w, ml, mr, mt, ph):
        pw = w - ml - mr
        return [round((x - ml) / pw * tl.x_max, 1) for x, _ in svg_pts], \
            [round((mt + ph - y) / ph * tl.y_max, 0) for _, y in svg_pts]

    for side, ep in (("t", "target"), ("b", "baseline")):
        for g_web, g_exp in (("zp-trend", "trend"), ("zp-band", "band")):
            d_web = re.search(rf'<g class="{g_web}">.*?<path class="{side}" d="([^"]+)"', web).group(1)
            d_exp = re.search(rf'<g class="{g_exp}">.*?<path class="{ep}" d="([^"]+)"', export).group(1)
            xs_w, ys_w = unit(_points(d_web), 720, 52, 12, 10, 230 - 10 - 30)
            xs_e, ys_e = unit(_points(d_exp), 860, 56, 16, 12, 260 - 12 - 34)
            assert len(xs_w) == len(xs_e) > 2, (side, g_web)
            assert all(abs(a - b) <= 0.05 for a, b in zip(xs_w, xs_e, strict=True)), (side, g_web)
            assert all(abs(a - b) <= 5 for a, b in zip(ys_w, ys_e, strict=True)), (side, g_web)
    # the same time axis: both end at the last request, with the same ticks
    def ticks(svg):
        return [float(t.replace(",", "")) for t in re.findall(r">([\d.,]+)s</text>", svg)]

    assert ticks(web) == ticks(export) == [0, 2, 4, 6, 8]


_MOTION_REC_JS = """window.mk = (i, t) => ({seq: i, endpoint: 'target', phase: 'probe', op: 'complete', stream: true,
  start_ms: t, ok: true, status_code: 200, duration_ms: 500 + (i % 4) * 60, ttft_ms: 200 + i,
  trend: {latency: 560 + i}, trend_band: {latency: [520 + i, 600 + i]}});"""


def test_live_chart_motion_in_a_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("EKTE_A11Y_CHROMIUM") or None)
        except Exception as e:  # no browser installed
            pytest.skip(f"no Chromium: {e}")
        try:
            _drive_live_motion(browser.new_page())
            page = browser.new_page()
            page.emulate_media(reduced_motion="reduce")
            _drive_live_still(page, "reduced motion")
            page = browser.new_page()
            _drive_live_still(page, "motion switch")
        finally:
            browser.close()


def _live_page(page, motion_off: bool = False) -> None:
    page.set_content('<!doctype html><html lang="en"' + (' data-motion="off"' if motion_off else "") +
                     '><head><title>t</title></head><body style="width:760px"><div id="host"></div></body></html>')
    page.add_style_tag(content=(_STATIC / "v2" / "chartmotion.css").read_text(encoding="utf-8"))
    page.add_script_tag(content=(_STATIC / "perf.js").read_text(encoding="utf-8"))
    page.add_script_tag(content=(_STATIC / "v2" / "chartmotion.js").read_text(encoding="utf-8"))
    page.add_script_tag(content=_MOTION_REC_JS)


# the requests' x positions, the time ticks and the accessible name
_GEOM = """() => { const s = document.querySelector('#host svg.zp-chart');
  return {cx: [...s.querySelectorAll('circle.zp-pt')].map(c => +c.getAttribute('cx')),
          ticks: [...s.querySelectorAll('.zp-xt text')].map(t => t.textContent),
          line: s.querySelector('.zp-trend path').getAttribute('d'),
          name: s.getAttribute('aria-label')}; }"""


def _drive_live_motion(page) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _live_page(page)
    # an audit 6 s in: six requests, the last one ending ~now
    page.evaluate("""() => {
      window.L = new EktePerf.Live(document.getElementById('host'));
      L.reset({probeTotal: 50});
      const t = performance.now(), recs = [];
      for (let i = 0; i < 6; i++) recs.push(mk(i, i * 1000));
      L.add(recs);
    }""")
    page.wait_for_function("() => !!document.querySelector('#host svg.zp-chart')")
    # the first draw sweeps in like every line chart: the band grows out of
    # its median line (SMIL), it does not just fade
    sweep = page.evaluate("""() => { const b = document.querySelector('#host .zp-band path');
      return {grow: !!b.querySelector('animate'), fade: b.classList.contains('zm-fd'),
              svg: document.querySelector('#host svg.zp-chart').classList.contains('zm-in')}; }""")
    assert sweep == {"grow": True, "fade": False, "svg": True}
    page.wait_for_timeout(1300)  # the sweep is over: nothing of it is left in the DOM
    assert page.evaluate("document.querySelectorAll('#host svg animate, #host svg .zm-fd, #host svg [style]').length") == 0
    # between requests the time axis keeps up with the clock: the requests
    # move left, the chart's accessible name does not change
    a = page.evaluate(_GEOM)
    page.wait_for_timeout(600)
    b = page.evaluate(_GEOM)
    assert all(x1 < x0 for x0, x1 in zip(a["cx"][1:], b["cx"][1:], strict=True)) and b["cx"][0] == a["cx"][0]
    assert b["name"] == a["name"] and b["line"] != a["line"]
    # a new request: the line morphs out of its old end (no fade), the new dot pops in
    page.evaluate("() => L.add([mk(6, 6200)])")
    page.wait_for_function("() => document.querySelectorAll('#host circle.zp-pt').length === 7")
    st = page.evaluate("""() => { const s = document.querySelector('#host svg.zp-chart');
      return {morph: !!s.querySelector('.zp-trend path animate'), fade: !!s.querySelector('.zp-trend .zm-fd'),
              pop: s.querySelectorAll('.zm-fresh').length}; }""")
    assert st == {"morph": True, "fade": False, "pop": 1}
    # motion switched off mid-audit: nothing moves any more
    page.evaluate("() => document.documentElement.setAttribute('data-motion', 'off')")
    page.wait_for_timeout(100)
    c = page.evaluate(_GEOM)
    page.wait_for_timeout(500)
    assert page.evaluate(_GEOM) == c
    # the audit ends: the axis ends at the last request again (6.2 s + 0.62 s)
    page.evaluate("() => { document.documentElement.removeAttribute('data-motion'); L.stop(); }")
    page.wait_for_timeout(600)
    end = page.evaluate("""() => { const s = document.querySelector('#host svg.zp-chart');
      return [L.raf, Math.max(...[...s.querySelectorAll('circle.zp-pt')].map(c => +c.getAttribute('cx')))]; }""")
    assert end[0] == 0
    assert abs(end[1] - (52 + 6.2 / 6.82 * 656)) < 1
    assert errors == []


def _drive_live_still(page, how: str) -> None:
    # reduced motion or the motion switch: no sweep, no creep; the time axis
    # ends at the last request and changes only when one lands
    _live_page(page, motion_off=how == "motion switch")
    page.evaluate("""() => {
      window.L = new EktePerf.Live(document.getElementById('host'));
      L.reset({probeTotal: 50});
      L.add([0, 1, 2, 3].map(i => mk(i, i * 1000)));
    }""")
    page.wait_for_function("() => !!document.querySelector('#host svg.zp-chart')")
    a = page.evaluate(_GEOM)
    page.wait_for_timeout(500)
    assert page.evaluate(_GEOM) == a, how
    assert page.evaluate("""() => [L.raf, document.querySelectorAll('#host animate, #host .zm-fd, #host .zm-mv').length,
      document.querySelector('#host svg.zp-chart').getAttribute('class')]""") == [0, 0, "zp-chart"], how
    # the last request (3 s + 0.68 s) at the right edge
    assert abs(max(a["cx"]) - (52 + 3 / 3.68 * 656)) < 1, how
