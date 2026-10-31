"""The v2 report view (ekte/web/static/v2/report.js), evaluated under node."""

from __future__ import annotations

import copy
import html as htmllib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = r"""
const path = require("path");
const [dir, lang, reportJson] = process.argv.slice(1);
global.window = { addEventListener() {} };
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => lang, setItem() {} };
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
require(path.join(dir, "i18n.js"));
require(path.join(dir, "icons.js"));
require(path.join(dir, "v2", "report.js"));
const el = { querySelectorAll: () => [], querySelector: () => null };
let clicked = null;
window.EkteReport.render(el, JSON.parse(reportJson), { actions: [
  { zh: "再测一个", en: "Test another" },
  { zh: "下载报告 (JSON)", en: "Download report (JSON)", primary: true, onClick: r => { clicked = r.mode; } },
], download: { name: "ekte-report" } });
console.log(JSON.stringify({ html: el.innerHTML, globals: Object.keys(window), icons: window.EKTE_ICONS }));
"""

_STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_report.json"


def _render(tmp_path: Path, lang: str, report: dict) -> dict:
    from ekte.i18n import locales_script

    (tmp_path / "locales.js").write_text(locales_script(), encoding="utf-8")
    for name in ("lang.js", "i18n.js", "icons.js"):
        shutil.copy(_STATIC / name, tmp_path / name)
    (tmp_path / "v2").mkdir(exist_ok=True)
    shutil.copy(_STATIC / "v2" / "report.js", tmp_path / "v2" / "report.js")
    out = subprocess.run(
        ["node", "-e", _JS, str(tmp_path), lang, json.dumps(report)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    return json.loads(out)


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")


@needs_node
def test_report_severity_dots_meters_and_summary(tmp_path):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    out = _render(tmp_path, "en", report)
    html = out["html"]
    # findings: dot colour and glyph come from the severity: no amber dot with a red cross
    glyph_for = {"bad": "x", "warn": "warning", "sky": "info"}
    findings = html[html.index("<h3>Findings"):]
    dots = re.findall(r'<span class="dot (\w+)" aria-hidden="true">(.*?)</span>', findings)
    assert {c for c, _ in dots} == {"bad", "warn"}
    for colour, glyph in dots:
        assert glyph == out["icons"][glyph_for[colour]], colour
    assert "Severity: High." in html and "Severity: Medium." in html
    # dimensions: meters for those that ran; every dimension listed and
    # expandable, the fixture's missing performance one included as not run
    assert html.count('role="meter"') == 8
    assert 'aria-valuenow="93"' in html or 'aria-valuenow="92"' in html
    assert "8 of 10 dimensions run" in html and "findings" in html
    assert html.count('class="dtog"') == 10 and html.count('<div class="zr-dimw off">') == 2
    assert "Context window" in html and "Performance" in html
    # the risk pill uses the shared vocabulary; the summary drops score + disclaimer
    assert "Bait-and-switch" in html
    summary = re.search(r'<p class="sum">(.*?)</p>', html).group(1)
    assert "Overall health score" not in summary and "black-box" not in summary
    assert "Findings: 4 high, 5 medium." in summary
    # evidence toggles are accessible, actions sit in the card footer
    assert 'aria-expanded="false" aria-controls="zr-ev-' in html
    foot = html[html.index('<footer class="zr-foot">'):]
    assert 'data-action="1"' in foot and "Download report (JSON)" in foot
    # every report format can be downloaded from the footer
    assert re.findall(r'data-dl="(\w+)">([^<]+)<', foot) == [
        ("json", "JSON"), ("md", "Markdown"), ("html", "HTML"), ("pdf", "PDF")]
    assert 'role="group" aria-label="Download report"' in foot and 'class="dl-msg" role="status"' in foot
    assert [g for g in out["globals"] if g.startswith("Ekte")] == ["EkteReport"]


@needs_node
@pytest.mark.parametrize("lang", ["zh", "fr", "es", "pt", "it", "de", "nb"])
def test_report_is_translated(tmp_path, lang):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    html = _render(tmp_path, lang, report)["html"]
    text = _text(html)
    for en in ("Per-dimension checks", "Severity:", "Show evidence", "Bait-and-switch",
               "Overall health score", "Claimed model", "Test another", "Download report"):
        assert en not in text, (lang, en)
    summary = re.search(r'<p class="sum">(.*?)</p>', html).group(1)
    assert "52" not in summary  # no repeated score line
    assert not re.search(r"\b(HIGH|MEDIUM|FAIL|PASS)\b", text)


@needs_node
def test_report_clean_and_translated_summary(tmp_path):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    clean = copy.deepcopy(report)
    clean["verdict"].update(risk_level="clean", rating="A", overall_score=96.0)
    for det in clean["detectors"]:
        det["findings"] = []
    # a summary already translated by exportReport (e.g. re-imported in French)
    clean["verdict"]["summary"] = (
        "Score de santé global 96/100. Aucun écart significatif constaté. "
        "ekte rapporte des preuves boîte noire d'écart et de risque, pas une preuve de fraude."
    )
    html = _render(tmp_path, "en", clean)["html"]
    summary = re.search(r'<p class="sum">(.*?)</p>', html).group(1)
    assert "Score de santé" not in summary and "boîte noire" not in summary
    assert "No warnings or failures" in html
    assert "Consistent (likely genuine)" in html



def _headline(html: str) -> str:
    return htmllib.unescape(re.search(r'<h2 id="zr-h-\d+">(.*?)</h2>', html).group(1))


@needs_node
@pytest.mark.parametrize(("lang", "want"), [
    ("en", "It does not deliver what it advertises: Context window, Billing & usage"),
    ("de", "Es liefert nicht, was es bewirbt: Kontextfenster, Abrechnung & Verbrauch"),
    ("zh", "它没有兑现所宣传的内容：上下文窗口、计费用量"),
])
def test_headline_names_the_dimensions_that_drove_the_risk(tmp_path, lang, want):
    # Model identity passed; the risk comes from the context window and billing.
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    report["verdict"].update(drivers=["context_window", "billing"],
                             checked=["context_window", "model_identity", "billing"])
    assert _headline(_render(tmp_path, lang, report)["html"]) == want


@needs_node
def test_headline_by_drivers_and_checked_dimensions(tmp_path):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    report["verdict"].update(drivers=["model_identity"], checked=["model_identity"])
    assert _headline(_render(tmp_path, "en", report)["html"]) == "It is not serving the model it claims"
    report["verdict"].update(risk_level="clean", drivers=[], checked=["streaming"])
    assert _headline(_render(tmp_path, "en", report)["html"]) == (
        "No problems in the checked dimensions (model identity not verified)")
    # a report from before drivers were recorded does not name the model
    del report["verdict"]["drivers"], report["verdict"]["checked"]
    report["verdict"]["risk_level"] = "high"
    assert _headline(_render(tmp_path, "en", report)["html"]) == "It does not deliver what it advertises"


_DOWNLOAD_JS = r"""
const path = require("path");
const [dir, reportJson] = process.argv.slice(1);
global.window = { addEventListener() {} };
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {},
                    body: { appendChild() {} },
                    createElement: () => ({ click() { saved.push(this.download); }, remove() {} }) };
global.localStorage = { getItem: () => "de", setItem() {} };
global.URL = { createObjectURL: () => "blob:x", revokeObjectURL() {} };
global.Blob = class { constructor(parts, o) { this.text = parts.join(""); this.type = o.type; } };
const saved = [], posted = [];
global.fetch = (url, init) => {
  posted.push({ url, method: init.method, type: init.headers["Content-Type"], body: JSON.parse(init.body) });
  if (url.endsWith("pdf")) return Promise.resolve({ ok: false, status: 500,
    json: () => Promise.resolve({ error: "PDF rendering failed: boom" }) });
  return Promise.resolve({ ok: true, blob: () => Promise.resolve(new Blob(["x"], { type: "t" })) });
};
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
require(path.join(dir, "i18n.js"));
require(path.join(dir, "icons.js"));
require(path.join(dir, "v2", "report.js"));
const rep = JSON.parse(reportJson), D = window.EkteReport.download;
(async () => {
  await D(rep, "json", "ekte-report-7");
  await D(rep, "md", "ekte-report-7");
  let err = null;
  try { await D(rep, "pdf", "ekte-report-7"); } catch (e) { err = e.message; }
  console.log(JSON.stringify({ saved, posted: posted.map(p => ({ ...p, title: p.body.detectors[0].findings[0].title })), err }));
})();
"""


@needs_node
def test_download_saves_every_format_in_the_ui_language(tmp_path):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    _render(tmp_path, "en", report)  # stage the scripts
    out = json.loads(subprocess.run(
        ["node", "-e", _DOWNLOAD_JS, str(tmp_path), json.dumps(report)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    # JSON is built in the browser; Markdown/HTML/PDF are rendered by the server
    assert out["saved"] == ["ekte-report-7.de.json", "ekte-report-7.de.md"]
    assert [(p["url"], p["method"], p["type"]) for p in out["posted"]] == [
        ("/api/report/export?format=md", "POST", "application/json"),
        ("/api/report/export?format=pdf", "POST", "application/json"),
    ]
    # the server gets the report exported in the UI language, same schema
    body = out["posted"][0]["body"]
    assert body.keys() == report.keys()
    assert out["posted"][0]["title"] != report["detectors"][0]["findings"][0]["title"]
    # a server refusal (no PDF support) comes back as the error message
    assert out["err"] == "PDF rendering failed: boom"


async def _scored_report() -> dict:
    # the transparency tests' report: protocol (published scale, one check not
    # counted, one medium finding) + determinism (no scale) in one dimension
    from tests.test_scoring_transparency import _report

    return json.loads((await _report()).model_dump_json())


def _panel(html: str) -> str:
    # the details panel of the first dimension that ran (rows of dimensions
    # that did not run are listed too, as "zr-dimw off")
    start = html.index('<div class="zr-dd"', html.index('<div class="zr-dimw">'))
    end = html.find('<div class="zr-dimw', start)
    return html[start:end if end >= 0 else None]


@needs_node
async def test_dimension_rows_expand_into_scoring_details(tmp_path):
    report = await _scored_report()
    html = _render(tmp_path, "en", report)["html"]
    # one disclosure per dimension (run or not), collapsed, controlling its panel
    toggles = re.findall(r'<button type="button" class="dtog" aria-expanded="false" aria-controls="(zr-dd-\d+)">', html)
    assert len(toggles) == 10 and all(f'id="{t}" role="region"' in html for t in toggles)
    assert html.count('role="meter"') == 1
    panel = _text(_panel(html))
    assert "Score: mean of 2 detectors, equal weight." in panel
    assert "Status: the worst status its detectors concluded." in panel
    assert "Score 77.5" in panel and "Score 100" in panel
    assert "Detector score: mean of the counted checks' points." in panel
    # every check, positive and negative, with the outcome and its points
    assert "Multi-turn conversation memory 55 pts" in " ".join(panel.split())
    assert "Not counted" in panel and "Result: Pass." in panel
    assert "Output varies at temperature=1.0" in panel  # a detector without a scale
    dots = set(re.findall(r'<span class="dot (\w+)"', _panel(html)))
    assert {"good", "warn", "grey"} <= dots
    # the published scale sits in one info tip per check (no appended block),
    # every outcome the check could have had, this run's marked
    assert "zr-scale" not in html and "Show scoring scale" not in html
    tips = re.findall(r'<span class="zr-tip"><button type="button" class="tipb" aria-expanded="false" '
                      r'aria-describedby="(zr-tip-\d+)" aria-label="Scoring scale">', html)
    assert len(tips) == 3
    assert f'<span class="bubble" role="tooltip" id="{tips[0]}">' in html
    assert "The invalid request was accepted (2xx)." in panel
    assert re.search(r'<span class="row hit"><span class="p">100 pts</span><span>Rejected with a 4xx and an OpenAI-style', html)
    # the outcome is no longer repeated as its own line under the title
    assert '<div class="oc">' not in html
    assert html.count("This run") == 3  # one hit per check, the not-counted one included


@needs_node
async def test_dimension_details_explain_a_status_override(tmp_path):
    report = await _scored_report()
    dim = next(d for d in report["dimensions"] if d["dimension"] == "protocol")
    dim["status"] = "warn"
    dim["breakdown"]["detector_status"] = "pass"
    dim["breakdown"]["status_override"] = {"from_status": "pass", "to_status": "warn",
                                           "severity": "medium", "findings": ["protocol.multi_turn"]}
    panel = _text(_panel(_render(tmp_path, "en", report)["html"]))
    assert ("Status raised from Pass to Warning by findings of severity Medium: "
            "Multi-turn conversation memory.") in " ".join(panel.split())


@needs_node
@pytest.mark.parametrize(("lang", "points"), [("zh", "55 分"), ("de", "55 Pkt."), ("fr", "55 pts")])
async def test_dimension_details_are_translated(tmp_path, lang, points):
    html = _render(tmp_path, lang, await _scored_report())["html"]
    panel = _text(_panel(html))
    for en in ("Score: mean of", "Not counted", "Scoring scale", "This run",
               "The invalid request was accepted", "Detector score", "Result:"):
        assert en not in panel, (lang, en)
    assert f'<span class="pts">{points}</span>' in html


@needs_node
def test_old_reports_still_expand(tmp_path):
    # reports from before the breakdown/scale existed: detectors and findings
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    html = _render(tmp_path, "en", report)["html"]
    assert html.count('class="dtog"') == 10
    assert "Score: mean of" in html or "Score from one detector." in html
    assert "Status: the worst status" not in html  # needs the breakdown
    assert not re.search(r"\d pts\b", _text(html))  # no points without a published scale


async def _attr_report() -> dict:
    # the response-attribute detector: 12 attribute findings, two parametrized checks
    from tests.test_scoring_transparency import _attr_report as build

    return json.loads((await build()).model_dump_json())


@needs_node
async def test_parametrized_checks_fold_into_one_row_each(tmp_path):
    html = _render(tmp_path, "en", await _attr_report())["html"]
    panel = _panel(html)
    text = " ".join(_text(panel).split())
    # one row per check, not per attribute; one scale tip each
    assert panel.count('class="zr-find zr-chk zr-grp"') == 2
    assert panel.count('aria-label="Scoring scale"') == 2
    assert "Core response attributes avg 90 pts" in text and "7 of 8 OK" in text
    assert "Minor response attributes avg 90 pts" in text and "3 of 4 OK" in text
    # problems listed inline, with their outcome and points
    sub = re.findall(r'<ul class="zr-sub">(.*?)</ul>', panel)
    assert len(sub) == 2 and "usage.completion_tokens" in sub[0] and "id" in sub[1]
    assert "Present but zero or empty (e.g. completion_tokens: 0). 20 pts" in " ".join(_text(sub[0]).split())
    # every attribute in a table behind a disclosure; the scale marks repeated hits
    toggles = re.findall(r'<button type="button" class="linkbtn more" aria-expanded="false" '
                         r'aria-controls="(zr-ga-\d+)" data-l0="Show all (\d+)" data-l1="Show fewer">', panel)
    assert [n for _, n in toggles] == ["8", "4"]
    assert all(f'<div class="zr-at" id="{i}" hidden>' in panel for i, _ in toggles)
    assert panel.count("<tr><td>") == 12
    assert "This run ×7" in panel and "This run ×3" in panel
    # the findings list shows only the two problems
    findings = html[html.index("<h3>Findings"):]
    assert findings.count('class="zr-find"') == 2


@needs_node
@pytest.mark.parametrize(("lang", "words"), [
    ("de", ["Zentrale Antwortattribute", "7 von 8 in Ordnung", "Alle 8 anzeigen", "Attribut", "Dieser Lauf ×7"]),
    ("zh", ["核心响应属性", "7/8 项正常", "显示全部 8 项", "属性", "本次结果 ×7"]),
])
async def test_parametrized_checks_are_translated(tmp_path, lang, words):
    panel = _panel(_render(tmp_path, lang, await _attr_report())["html"])
    for w in words:
        assert w in panel, (lang, w)
    for en in ("Core response attributes", "Show all", "of 8 OK", "Present with a valid value"):
        assert en not in panel, (lang, en)


def _deductions_report() -> dict:
    # billing with an inflated prompt (cap 55) and model identity with one
    # diverging fingerprint (-12.5) — detectors on "deductions" scales
    from ekte.detectors import billing, model_identity
    from ekte.detectors.scale import DeductionScale
    from ekte.models import AuditReport, DetectorResult, Dimension, RedactedTarget, Status, Verdict
    from ekte.scoring import build_dimensions

    b = billing.SCALE
    bill = DetectorResult(id="billing", name="Token/usage billing audit", dimension=Dimension.BILLING,
                          status=Status.FAIL, scoring=b.scoring(), findings=[
                              b.finding("billing.usage-inflation", "inflated",
                                        title="Reported prompt tokens far exceed estimate",
                                        summary="Reported prompt tokens (900) far exceed independent estimate (~135)."),
                          ])
    m = model_identity.SCALE
    ident = DetectorResult(id="model_identity", name="Model identity & downgrade fingerprinting",
                           dimension=Dimension.MODEL_IDENTITY, status=Status.WARN, scoring=m.scoring(),
                           findings=[
                               m.finding("model_identity.self_id", "consistent", title="Self-identification consistent",
                                         summary="Self-id mentions genuine brand words for gpt-4o."),
                               m.finding("model_identity.fp", "diverged", id="model_identity.fp.cutoff",
                                         deduction=12.5, title="Fingerprint divergence: cutoff",
                                         summary="Probe 'cutoff' diverged from native behavior."),
                           ])
    for det in (bill, ident):
        det.score = DeductionScale.total(det.findings)
    report = AuditReport(
        tool_version="t", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="http://relay.test/v1", model="gpt-4o"),
        verdict=Verdict(), dimensions=build_dimensions([bill, ident], None), detectors=[bill, ident],
    )
    return json.loads(report.model_dump_json())


@needs_node
def test_deduction_scales_show_deductions_and_caps(tmp_path):
    report = _deductions_report()
    assert [d["score"] for d in report["detectors"]] == [55.0, 87.5]
    html = _render(tmp_path, "en", report)["html"]
    text = " ".join(_text(html).split())
    assert text.count("Detector score: starts at 100; findings deduct points or cap it") == 2
    # what each finding did to the score, next to it
    assert '<span class="pts">cap 55</span>' in html
    assert '<span class="pts">−12.5 pts</span>' in html
    assert '<span class="pts">No deduction</span>' in html
    # and the scale tip lists every outcome's effect
    assert '<span class="p">up to −25 pts · cap 20</span>' in html
    assert '<span class="p">cap 55</span>' in html  # a check's tip lists its own outcomes


@needs_node
def test_deduction_scales_are_translated(tmp_path):
    html = _render(tmp_path, "de", _deductions_report())["html"]
    assert '<span class="pts">Obergrenze 55</span>' in html and '<span class="pts">Kein Abzug</span>' in html
    assert "starts at 100" not in html and "The answer diverged" not in html


def _timed_report() -> dict:
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for i, det in enumerate(report["detectors"]):
        det["duration_ms"] = 250.0 * (i + 1)
    report["detectors"][2]["duration_ms"] = 12_345.0  # the slowest
    report["detectors"][1]["error"] = "ReadTimeout"
    report["target"]["declared_provider"] = "openai"
    return report


def _exec(html: str) -> str:
    start = html.index('<section class="sect zr-exec">')
    return html[start:html.index("</section>", start)]


@needs_node
def test_execution_log_lists_every_detector_with_its_time(tmp_path):
    report = _timed_report()
    dets = report["detectors"]
    html = _render(tmp_path, "en", report)["html"]
    ex = _exec(html)
    # collapsed behind one toggle, rows in run order
    tog = re.search(r'<button type="button" class="linkbtn xtog" aria-expanded="false" aria-controls="(zr-ex-\d+)" '
                    r'data-l0="Show all (\d+)" data-l1="Show fewer">', ex)
    assert tog and tog.group(2) == str(len(dets))
    assert f'<ol class="zr-xl" id="{tog.group(1)}" hidden>' in ex
    assert ex.count('<li class="zr-xr') == len(dets)
    names = [htmllib.unescape(n) for n in re.findall(r'<span class="xn">([^<]+)<small>', ex)]
    assert names == [d["name"] for d in dets]
    # time per detector, the total and the slowest one called out
    total = sum(d["duration_ms"] for d in dets)
    text = htmllib.unescape(" ".join(_text(ex).split()))
    assert f"{len(dets)} checks · {round(total / 1000)} s in total" in text
    assert f"the slowest was {dets[2]['name']} (12 s)" in text
    assert ex.count('class="zr-xr slow"') == 1
    assert '<span class="xt">250 ms</span>' in ex and '<span class="xt">1.3 s</span>' in ex
    assert "Error: ReadTimeout" in text
    # the declared provider joins the meta strip
    assert "<dt>Declared provider</dt><dd><code>openai</code></dd>" in html


@needs_node
def test_execution_log_is_translated_and_skipped_without_timings(tmp_path):
    html = _render(tmp_path, "de", _timed_report())["html"]
    text = _text(_exec(html))
    assert "Ausführungsprotokoll" in text and "insgesamt" in text and "Alle " in text
    assert "Execution log" not in text and "in total" not in text
    untimed = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for det in untimed["detectors"]:
        det["duration_ms"] = None
    assert "zr-exec" not in _render(tmp_path, "en", untimed)["html"]


_DETAIL_JS = r"""
const path = require("path");
const [dir, findingJson] = process.argv.slice(1);
global.window = { addEventListener() {} };
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => "en", setItem() {} };
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
require(path.join(dir, "i18n.js"));
require(path.join(dir, "icons.js"));
require(path.join(dir, "v2", "report.js"));
const R = window.EkteReport;
console.log(JSON.stringify({ html: R.findingDetail(JSON.parse(findingJson)),
  d: [R.duration(0), R.duration(999.6), R.duration(1234), R.duration(73210), R.duration(null)] }));
"""


@needs_node
def test_finding_detail_shows_all_evidence(tmp_path):
    _render(tmp_path, "en", json.loads(_FIXTURE.read_text(encoding="utf-8")))  # stage the scripts
    finding = {"id": "x.y", "title": "Usage looks inflated", "status": "fail", "severity": "high",
               "summary": "Reported 900 prompt tokens.", "recommendation": "Check billing.",
               "evidence": {f"k{i}": i for i in range(15)}}
    out = json.loads(subprocess.run(
        ["node", "-e", _DETAIL_JS, str(tmp_path), json.dumps(finding)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    html = out["html"]
    assert '<span class="dot sm bad"' in html and '<span class="tag bad">High</span>' in html
    assert "Usage looks inflated" in html and "Reported 900 prompt tokens." in html
    assert "Recommendation: Check billing." in html
    ev = re.search(r'<pre class="ev">(.*?)</pre>', html, re.S).group(1).split("\n")
    assert ev[0] == "k0: 0" and len(ev) == 12  # up to 12 evidence fields
    assert out["d"] == ["0 ms", "1,000 ms", "1.2 s", "73 s", "—"]


_PERF_JS = r"""
const path = require("path");
const [dir, reportJson] = process.argv.slice(1);
global.window = { addEventListener() {} };
global.document = undefined;  // perf.js skips its style injection without a DOM
require(path.join(dir, "perf.js"));
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => "en", setItem() {} };
for (const m of ["locales.js", "lang.js", "i18n.js", "icons.js"]) require(path.join(dir, m));
require(path.join(dir, "v2", "report.js"));
const el = { querySelectorAll: () => [], querySelector: () => null };
window.EkteReport.render(el, JSON.parse(reportJson), {});
console.log(JSON.stringify({ html: el.innerHTML }));
"""


@needs_node
def test_performance_measurements_sit_in_the_performance_dimension(tmp_path):
    from ekte.models import RequestRecord
    from ekte.perf import build_performance

    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    recs = [RequestRecord(seq=i, endpoint="target", phase="probe", ok=True, stream=True,
                          start_ms=i * 1000.0, duration_ms=900.0, ttft_ms=250.0,
                          decode_tps_local=100.0) for i in range(4)]
    report["performance"] = json.loads(build_performance(recs, has_baseline=False, probe_max_tokens=64)
                                       .model_dump_json())
    _render(tmp_path, "en", report)  # stage the scripts
    shutil.copy(_STATIC / "perf.js", tmp_path / "perf.js")
    html = json.loads(subprocess.run(
        ["node", "-e", _PERF_JS, str(tmp_path), json.dumps(report)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)["html"]
    # no separate performance section: the measurements are an extra of the
    # performance dimension's details (listed although the fixture never ran it)
    assert "perf-sect" not in html and html.count('class="zp-section"') == 1
    rows = html.split('<div class="zr-dimw')
    perf_row = next(r for r in rows if "Is its speed consistent?" in r)
    assert perf_row.startswith(' off">')
    assert '<div class="zr-extra" data-extra="performance">' in perf_row
    assert "Performance measurements" in perf_row and 'class="zp-section"' in perf_row


_JS_INTL = r"""
const path = require("path");
const [dir, lang, reportJson] = process.argv.slice(1);
// count how many Intl formatters the report builds
const made = {};
for (const name of ["DateTimeFormat", "NumberFormat", "DisplayNames"]) {
  const Orig = Intl[name];
  made[name] = 0;
  Intl[name] = function (loc, opts) { made[name]++; return new Orig(loc, opts); };
}
global.window = { addEventListener() {} };
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => lang, setItem() {} };
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
require(path.join(dir, "i18n.js"));
require(path.join(dir, "icons.js"));
require(path.join(dir, "v2", "report.js"));
const report = JSON.parse(reportJson);
const render = () => {
  const el = { querySelectorAll: () => [], querySelector: () => null };
  window.EkteReport.render(el, report, {});
  return el.innerHTML;
};
const first = render();
const after1 = Object.assign({}, made);
const second = render();
const after2 = Object.assign({}, made);
const loc = window.EKTE_LANG.locale();
console.log(JSON.stringify({
  first, second, after1, after2, locale: loc,
  time: new Date(report.generated_at).toLocaleString(loc, { dateStyle: "medium", timeStyle: "short" }),
  lang: new Intl.DisplayNames([loc || "en"], { type: "language" }).of("de"),
}));
"""


@needs_node
@pytest.mark.parametrize("lang", ["en", "de", "zh"])
def test_intl_formatters_are_cached_and_output_unchanged(tmp_path, lang):
    from ekte.i18n import locales_script

    (tmp_path / "locales.js").write_text(locales_script(), encoding="utf-8")
    for name in ("lang.js", "i18n.js", "icons.js"):
        shutil.copy(_STATIC / name, tmp_path / name)
    (tmp_path / "v2").mkdir()
    shutil.copy(_STATIC / "v2" / "report.js", tmp_path / "v2" / "report.js")
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    report["prompt_languages"] = ["de", "en"]
    out = json.loads(subprocess.run(
        ["node", "-e", _JS_INTL, str(tmp_path), lang, json.dumps(report)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    # same text as Date#toLocaleString / Intl.DisplayNames built per call
    assert out["locale"]
    assert htmllib.escape(out["time"], quote=False) in out["first"]
    assert htmllib.escape(out["lang"], quote=False) in out["first"]
    def ids(h: str) -> str:  # each render numbers its element ids anew
        return re.sub(r"(zr-[a-z-]*?)\d+", r"\1N", h)

    assert ids(out["second"]) == ids(out["first"])
    # each (locale, options) formatter is built once and reused on re-render
    assert out["after1"]["DateTimeFormat"] == 1 and out["after1"]["DisplayNames"] == 1
    assert out["after1"]["NumberFormat"] >= 1
    assert out["after2"] == out["after1"]


@needs_node
def test_report_evidence_durations_are_readable(tmp_path):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for det in report["detectors"]:
        for f in det["findings"]:
            if f["id"] == "billing.usage-inflation":
                f["evidence"] = {"ttft_ms": 5457.0, "duration_ms": 6097.3,
                                 "slow_ms": 65432.0, "short_duration_s": 0.00085}
    html = _render(tmp_path, "en", report)["html"]
    assert "ttft_ms: 5 s 457 ms" in html and "duration_ms: 6 s 97 ms" in html
    assert "slow_ms: 1 min 5 s" in html and "short_duration_s: 850 µs" in html
