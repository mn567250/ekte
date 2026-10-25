"""Completeness of the web UI translations and of the downloaded report.

Evaluates the UI's plain-browser JS (zing/web/static) under node, so it is
skipped when node isn't installed. Adding a language to LANG_LIST in lang.js
without a full zing/i18n/locales/<code>.json fails here, and so does a
downloaded report that changes the JSON schema or leaves text untranslated.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_LOCALE_CHECK_JS = r"""
const path = require("path");
const dir = process.argv[1];
global.window = {};
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => null, setItem() {} };
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
require(path.join(dir, "i18n.js"));
const L = window.ZING_LOCALES, zh = window.ZING_I18N.FINDINGS;
const ph = s => (String(s).match(/\{\w+(?:\|\w+)?\}/g) || []).sort().join(",");
const tags = s => (String(s).match(/<\/?[a-z]+/gi) || []).sort().join(",");
const problems = [];
const codes = window.ZING_LANG.langs().map(l => l.code).filter(c => c !== "en" && c !== "zh");
for (const c of codes) {
  const s = L.strings[c], f = L.findings[c];
  if (!s || !f) { problems.push(c + ": no zing/i18n/locales/" + c + ".json"); continue; }
  for (const k of L.keys.strings) {
    if (!(k in s)) problems.push(c + ": missing string " + JSON.stringify(k));
    else if (ph(k) !== ph(s[k]) || tags(k) !== tags(s[k]))
      problems.push(c + ": placeholder/markup mismatch in " + JSON.stringify(k));
  }
  for (const id of L.keys.findings) {
    const e = f[id], src = id === "model_identity.fp.*" ? "{probe}" : (zh[id] || {}).tpl;
    if (!e || !e.title || !e.tpl) problems.push(c + ": missing finding " + id);
    else if (ph(src) !== ph(e.tpl)) problems.push(c + ": placeholder mismatch in finding " + id);
  }
}
for (const id of Object.keys(zh)) if (!L.keys.findings.includes(id)) problems.push("finding not translatable: " + id);
// Branch/generic summary templates are English keys every language, CN
// included, must translate (CN has no other use for the dictionary).
for (const t of window.ZING_I18N.TEMPLATES)
  for (const c of codes.concat(["zh"])) {
    const d = L.strings[c] || {};
    if (!(t in d)) problems.push(c + ": missing template " + JSON.stringify(t));
    else if (ph(t) !== ph(d[t])) problems.push(c + ": placeholder mismatch in template " + JSON.stringify(t));
  }
console.log(JSON.stringify({ codes, problems }));
"""


def _ui_js(tmp_path: Path) -> Path:
    """The UI's i18n scripts as the browser gets them (/locales.js carries the
    JSON data from zing/i18n/locales/ in front of the lookup logic)."""
    from zing.i18n import locales_script

    static = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
    (tmp_path / "locales.js").write_text(locales_script(), encoding="utf-8")
    for name in ("lang.js", "i18n.js"):
        shutil.copy(static / name, tmp_path / name)
    return tmp_path


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_every_ui_language_is_complete(tmp_path):
    # Every language in lang.js's LANG_LIST (besides EN, the key language, and
    # CN, the original markup) must translate every UI string and finding,
    # keeping placeholders and inline markup intact.
    out = subprocess.run(
        ["node", "-e", _LOCALE_CHECK_JS, str(_ui_js(tmp_path))],
        capture_output=True, text=True, check=True,
    ).stdout
    result = json.loads(out)
    assert {"fr", "es", "pt", "it", "de"} <= set(result["codes"])
    assert result["problems"] == []


_EXPORT_JS = r"""
const path = require("path"), fs = require("fs");
const dir = process.argv[1], report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
// Extra findings for detector branches the fixture run didn't hit.
const f = (id, status, evidence, title, summary) => ({ id, title, status, severity: "low", summary, evidence, recommendation: null });
report.detectors[0].findings.push(
  f("model_identity.self_id", "pass", { prompt: "self-id", target_answer: "I am GPT-4o." }, "Self-identification consistent", "Self-id mentions genuine brand words for gpt-4o."),
  f("model_identity.self_id", "warn", { prompt: "self-id", target_answer: "I am GPT, not Claude.", forbidden_hits: ["claude"] }, "Self-id names both the genuine and a rival brand", "Self-id mentions genuine brand words for gpt-4o but also a rival brand (claude)."),
  f("model_identity.self_id", "warn", { prompt: "self-id", target_answer: "I am an assistant." }, "Evasive self-identification", "Self-id response names neither the genuine brand nor a rival; treat as weak/evasive evidence."),
  f("security.headers", "pass", { header_count: 7 }, "No revealing headers", "Inspected 7 response headers; none expose upstream identity."),
  f("connectivity.chat", "fail", { status_code: 502, error_type: "upstream_error" }, "Basic chat failed", "Bad gateway."),
  f("embed.dimension", "info", { returned: 1536, claimed: 0 }, "Claimed dimension unknown", "No KB dimension for the claimed model; observed 1536-d."));
// A published scoring scale: its outcome labels are fixed backend sentences.
report.detectors[0].scoring = { method: "mean_of_checks", outcomes: [
  { check: "protocol.stop", outcome: "ignored", score: 60, status: "warn", severity: "low",
    label: "Text after the stop sequence was returned." },
  { check: "protocol.stop", outcome: "no_content", score: null, status: "inconclusive", severity: "low",
    label: "No usable response to judge by." }] };
// The performance section's notes are fixed backend sentences.
report.performance = { source: "passive", notes: [
  "Local token counts are estimates (about ±15-20%) from a built-in heuristic; zing never downloads a tokenizer.",
  "Some requests were served fully or partly from a cache and are left out of the statistics."] };
const TEXT = /^(verdict\.(headline|summary|key_findings\.\d+)|dimensions\.\d+\.reason|(performance\.)?notes\.\d+|(baseline_)?detectors\.\d+\.(name|findings\.\d+\.(title|summary|recommendation)|scoring\.(outcomes\.\d+\.label|titles\..+)))$/;
const CJK = /[\u3400-\u9fff]/;
const flat = (o, p, out) => { if (o && typeof o === "object") for (const k of Object.keys(o)) flat(o[k], p ? p + "." + k : k, out); else out[p] = o; return out; };
const result = {};
for (const lang of ["en", "zh", "fr", "es", "pt", "it", "de"]) {
  for (const m of ["locales.js", "lang.js", "i18n.js"]) delete require.cache[require.resolve(path.join(dir, m))];
  global.window = {};
  global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete", querySelectorAll: () => [], addEventListener() {} };
  global.localStorage = { getItem: () => lang, setItem() {} };
  for (const m of ["locales.js", "lang.js", "i18n.js"]) require(path.join(dir, m));
  const ex = window.ZING_I18N.exportReport(report), a = flat(report, "", {}), b = flat(ex, "", {});
  const problems = [];
  const ka = Object.keys(a).sort().join("\n"), kb = Object.keys(b).sort().join("\n");
  if (ka !== kb) problems.push("JSON keys differ");
  for (const k of Object.keys(a)) {
    if (!TEXT.test(k)) { if (a[k] !== b[k]) problems.push("non-text value changed: " + k); continue; }
    if (typeof a[k] !== "string" || !a[k]) continue;
    if (lang !== "en" && a[k] === b[k]) problems.push("untranslated: " + k + " = " + a[k]);
    if (lang === "zh" && !CJK.test(b[k])) problems.push("no Chinese in: " + k + " = " + b[k]);
    if (lang !== "zh" && CJK.test(b[k])) problems.push("Chinese left in: " + k + " = " + b[k]);
  }
  result[lang] = { problems, report: ex };
}
console.log(JSON.stringify(result));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_downloaded_report_is_translated_with_english_keys(tmp_path):
    # The web UI's "Download report (JSON)" exports this: same keys, enums,
    # ids and evidence as the server's report; human-readable values in the
    # selected language; and still a valid zing AuditReport.
    from zing.models import AuditReport

    here = Path(__file__).resolve().parent
    out = subprocess.run(
        ["node", "-e", _EXPORT_JS, str(_ui_js(tmp_path)), str(here / "fixtures" / "web_report.json")],
        capture_output=True, text=True, check=True,
    ).stdout
    result = json.loads(out)
    assert set(result) == {"en", "zh", "fr", "es", "pt", "it", "de"}
    for lang, res in result.items():
        assert res["problems"] == [], lang
        AuditReport.model_validate(res["report"])


def test_locale_fragments_extend_every_language(tmp_path, monkeypatch):
    # zing/i18n/locales/fragments/<feature>/<code>.json adds strings to a
    # language; an en fragment extends the canonical key list.
    import zing.i18n as i18n

    base = Path(i18n.__file__).resolve().parent / "locales"
    for f in base.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    frag = tmp_path / "fragments" / "demo"
    frag.mkdir(parents=True)
    (frag / "en.json").write_text(json.dumps({"strings": {"Hello v2": "Hello v2"}}), encoding="utf-8")
    (frag / "de.json").write_text(json.dumps({"strings": {"Hello v2": "Hallo v2"}}), encoding="utf-8")
    monkeypatch.setattr(i18n, "_DIR", tmp_path)
    i18n._load.cache_clear()
    try:
        assert i18n.ui("de", "Hello v2") == "Hallo v2"
        assert "Hello v2" in i18n.bundle()["locales"]["en"]["strings"]
        assert i18n.ui("de", "History") == i18n._load()["de"]["strings"]["History"]  # base kept
        (frag / "xx.json").write_text("{}", encoding="utf-8")
        i18n._load.cache_clear()
        with pytest.raises(ValueError):
            i18n._load()
    finally:
        i18n._load.cache_clear()


def _backend_sentences() -> list[str]:
    """Fixed English sentences the backend puts in a report: detector names,
    recommendations, scoring-scale labels, verdict headlines, report notes and
    performance notes."""
    root = Path(__file__).resolve().parent.parent / "zing"
    out: list[str] = []

    def lit(node: ast.AST) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            # recommendation="…" wherever a finding is built; label="…" of a
            # scoring-scale outcome
            if isinstance(node, ast.keyword) and node.arg in ("recommendation", "label"):
                # a literal, or either literal branch of `"…" if cond else None`
                values = [node.value.body, node.value.orelse] if isinstance(node.value, ast.IfExp) else [node.value]
                out += [s for s in map(lit, values) if s]
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                continue
            target = node.targets[0].id
            if rel.startswith("detectors/") and target == "name" and lit(node.value):
                out.append(lit(node.value))  # a detector's display name
            if rel.startswith("detectors/") and target == "_NO_RESPONSE" and lit(node.value):
                out.append(lit(node.value))  # a shared scoring-scale label
            if rel == "perf/summary.py" and target.startswith("NOTE_") and lit(node.value):
                out.append(lit(node.value))  # performance notes
            if rel == "runner.py" and target == "notes" and isinstance(node.value, ast.List):
                out += [s for s in map(lit, node.value.elts) if s]  # report notes
            if rel == "scoring.py" and target == "table" and isinstance(node.value, ast.Dict):
                out += [s for s in map(lit, node.value.values) if s]  # verdict headlines
    return sorted(set(out))


def test_zh_translates_every_backend_sentence():
    # The UI shows backend text translated in CN too (ZING_LANG.server), so
    # zh.json must carry every fixed backend sentence.
    from zing import i18n

    sentences = _backend_sentences()
    assert len(sentences) > 40
    assert [s for s in sentences if i18n.backend("zh", s) == s] == []


_SERVER_ZH_JS = r"""
const path = require("path"), fs = require("fs");
const dir = process.argv[1], report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
global.window = {};
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => "zh", setItem() {} };
for (const m of ["locales.js", "lang.js"]) require(path.join(dir, m));
const texts = [report.verdict.headline, report.verdict.summary].concat(JSON.parse(process.argv[3]));
for (const k of ["detectors", "baseline_detectors"])
  for (const d of report[k] || []) {
    texts.push(d.name);
    for (const f of d.findings || []) if (f.recommendation) texts.push(f.recommendation);
  }
console.log(JSON.stringify(texts.map(t => [t, window.ZING_LANG.server(t)])));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_server_text_is_chinese_in_zh(tmp_path):
    # Recommendations, detector names and the verdict headline/summary come
    # from the backend in English; in CN the UI must show them in Chinese.
    here = Path(__file__).resolve().parent
    fixture = here / "fixtures" / "web_report.json"
    extra = _backend_sentences()
    out = subprocess.run(
        ["node", "-e", _SERVER_ZH_JS, str(_ui_js(tmp_path)), str(fixture), json.dumps(extra)],
        capture_output=True, text=True, check=True,
    ).stdout
    pairs = json.loads(out)
    cjk = re.compile(r"[㐀-鿿]")
    assert [en for en, zh in pairs if not cjk.search(zh or "")] == []
    summary = dict(pairs)[json.loads(fixture.read_text(encoding="utf-8"))["verdict"]["summary"]]
    # Chinese sentences are joined without spaces; no English sentence is left.
    assert "。 " not in summary and "Findings" not in summary and "health score" not in summary


def test_language_labels_are_endonyms():
    # The switcher names languages, not countries (no flags).
    from zing import i18n

    labels = {m["code"]: m["label"] for m in i18n.languages()}
    assert labels == {
        "en": "English", "zh": "中文", "fr": "Français", "es": "Español",
        "pt": "Português", "it": "Italiano", "de": "Deutsch",
    }
    assert i18n.codes()[:2] == ["en", "zh"]


_VISIBILITY_JS = r"""
const path = require("path");
const dir = process.argv[1];
const run = (lang, fire) => {
  delete require.cache[require.resolve(path.join(dir, "lang.js"))];
  const timers = [], handlers = {}, dcl = [];
  global.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  global.clearTimeout = id => { if (timers[id - 1]) timers[id - 1].fn = null; };
  global.window = {
    ZING_LOCALES: { languages: [{ code: "en", label: "English", html: "en", locale: "en-US" },
                                { code: "zh", label: "中文", html: "zh-CN", locale: "zh-CN" },
                                { code: "fr", label: "Français", html: "fr", locale: "fr-FR" }] },
    addEventListener(t, fn) { handlers[t] = fn; },
    removeEventListener(t, fn) { if (handlers[t] === fn) delete handlers[t]; },
  };
  // The document is still "loading"; lang.js's own boot (the last
  // DOMContentLoaded listener) is never called, as if it had failed.
  global.document = { documentElement: { style: {}, lang: "" }, readyState: "loading",
                      querySelectorAll: () => [], addEventListener(t, fn) { if (t === "DOMContentLoaded") dcl.push(fn); } };
  global.localStorage = { getItem: () => lang, setItem() {} };
  require(path.join(dir, "lang.js"));
  const st = document.documentElement.style, before = st.visibility || "";
  const fireTimers = () => timers.slice().forEach(t => t.fn && t.fn());
  if (fire === "cap") fireTimers();
  if (fire === "parsed") { document.readyState = "interactive"; dcl.slice(0, -1).forEach(f => f()); }
  const mid = st.visibility || "";
  if (fire === "parsed") fireTimers();
  if (fire === "error-loading") handlers.error({});
  if (fire === "error-parsed") { document.readyState = "interactive"; handlers.error({}); }
  return { before, mid, after: st.visibility || "", delays: timers.map(t => t.ms) };
};
const r = {};
for (const f of ["cap", "parsed", "error-loading", "error-parsed"]) r[f] = run("fr", f);
r.zh = run("zh", "none");
console.log(JSON.stringify(r));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_hidden_page_is_revealed_if_boot_never_runs(tmp_path):
    # lang.js hides the page until the markup is translated; if boot never
    # runs (e.g. a later script throws), a timer or the first error reveals it.
    static = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
    shutil.copy(static / "lang.js", tmp_path / "lang.js")
    out = subprocess.run(
        ["node", "-e", _VISIBILITY_JS, str(tmp_path)], capture_output=True, text=True, check=True,
    ).stdout
    r = json.loads(out)
    for case in ("cap", "parsed", "error-loading", "error-parsed"):
        assert r[case]["before"] == "hidden", case
    # A cap reveals the page even if DOMContentLoaded never fires …
    assert r["cap"]["after"] == "" and max(r["cap"]["delays"]) <= 10000
    # … and ~1.5 s after the HTML is parsed if boot didn't reveal it.
    assert r["parsed"]["mid"] == "hidden" and r["parsed"]["after"] == ""
    assert 1000 <= min(r["parsed"]["delays"]) <= 2000
    # A script error reveals it at once, but not while the HTML is still
    # loading (boot is still to come; revealing would flash the Chinese).
    assert r["error-loading"]["after"] == "hidden"
    assert r["error-parsed"]["after"] == ""
    assert r["zh"]["before"] == "" and r["zh"]["delays"] == []  # CN is the markup itself


# --------------------------------------------------------------------------- #
# Strings used in page source must be translatable
# --------------------------------------------------------------------------- #
_STATIC = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
_T_CALL = re.compile(r'\bTf?\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"')
_DATA_EN = re.compile(r'data-en(?:-[a-z-]+)?="([^"]*)"')
# A ["中文", "English"] pair handed to a helper that calls T/Tf later, e.g.
# kb.html's counts(["1 个模型", "1 model"], …) — invisible to _T_CALL.
_ZH_EN_PAIR = re.compile(r'\[\s*"((?:[^"\\]|\\.)*[㐀-鿿](?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\]')


def _source_strings(path: Path) -> set[str]:
    """English texts a page hands to T(zh, en) / Tf(zh, en, …), a ["zh", "en"]
    pair, or a data-en / data-en-<attr> attribute."""
    import html

    src = path.read_text(encoding="utf-8")
    pairs = _T_CALL.findall(src) + _ZH_EN_PAIR.findall(src)
    found = {json.loads(f'"{en}"') for _zh, en in pairs}
    found |= {html.unescape(en) for en in _DATA_EN.findall(src)}
    return found


@pytest.mark.parametrize(
    "page",
    ["v2/masterkey.js", "v2/watches.html", "watches.html", "v2/relaycfg.js", "v2/index.html", "v2/kb.html",
     "v2/kbsection.js", "v2/kbview.js", "v2/tabs.js", "v2/jobs.js", "v2/history.html", "v2/analytics.html", "v2/filterpanel.js",
     "v2/charts.js"],
)
def test_page_strings_are_translatable(page):
    # Every English text these pages show must be a key of the merged `en`
    # strings; test_every_ui_language_is_complete then requires all languages
    # to translate it, so a new string cannot silently stay English.
    from zing import i18n

    keys = set(i18n._load()["en"].get("strings", {}))
    missing = sorted(_source_strings(_STATIC / page) - keys)
    assert not missing, f"{page}: add to zing/i18n/locales (fragments): {missing}"


# --------------------------------------------------------------------------- #
# Per-language /locales.js
# --------------------------------------------------------------------------- #
def test_one_language_bundle_carries_only_that_language():
    from zing import i18n

    full = i18n.bundle()
    for code in i18n.codes():
        b = i18n.lang_bundle(code)
        assert b["lang"] == code and b["languages"] == full["languages"]
        assert set(b["locales"]) == (set() if code == "en" else {code})
        # ZING_LOCALES.keys, without shipping the identity map en.json
        assert b["keys"]["strings"] == list(full["locales"]["en"]["strings"])
        assert b["keys"]["findings"] == list(full["locales"]["zh"]["findings"])
        assert len(i18n.locales_script(code)) < len(i18n.locales_script()) / 3
    # built once per variant; unknown codes get the full bundle
    assert i18n.locales_bundle("de") is i18n.locales_bundle("DE")
    assert i18n.locales_script("xx") == i18n.locales_script(None) == i18n.locales_script()
    assert i18n.locales_bundle("de")[1] != i18n.locales_bundle("fr")[1]


def test_bundles_are_precompressed_once_and_rebuilt_with_the_data():
    import gzip

    from zing import i18n

    for lang in (None, "de"):
        body, etag, gz = i18n.locales_encoded(lang)
        assert body == i18n.locales_script(lang).encode("utf-8")
        assert etag == i18n.locales_bundle(lang)[1]
        assert gzip.decompress(gz) == body
        assert i18n.locales_encoded(lang) is i18n.locales_encoded(lang)
    before = i18n.locales_encoded("de")
    i18n._load.cache_clear()  # a reload rebuilds the compressed bytes too
    after = i18n.locales_encoded("de")
    assert after is not before and after == before


def test_locales_route_picks_the_language_and_revalidates():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from zing.web.server import create_app

    def vary(r) -> set[str]:
        # gzip (zing/web/caching.py) adds Accept-Encoding; only Cookie is ours
        return {v.strip().lower() for v in r.headers.get("vary", "").split(",") if v.strip()}

    client = TestClient(create_app(), base_url="http://localhost")
    full = client.get("/locales.js")
    assert full.status_code == 200 and '"code":"de"' in full.text
    assert full.headers["cache-control"] == "no-cache" and "cookie" in vary(full)
    assert '"lang":' not in full.text.split(";\n", 1)[0]  # every language

    de = client.get("/locales.js?lang=de")
    assert de.status_code == 200 and '"lang":"de"' in de.text
    assert "application/javascript" in de.headers["content-type"]
    assert de.headers["etag"] != full.headers["etag"]
    assert "cookie" not in vary(de)  # the query decides, not the cookie
    assert len(de.content) < len(full.content) / 3

    client.cookies.set("zing_lang", "fr")
    fr = client.get("/locales.js")
    assert '"lang":"fr"' in fr.text and "cookie" in vary(fr)
    assert '"lang":"de"' in client.get("/locales.js?lang=de").text  # query wins
    client.cookies.clear()

    etag = de.headers["etag"]
    for inm in (etag, f"W/{etag}", f'"nope", {etag}'):
        r = client.get("/locales.js?lang=de", headers={"If-None-Match": inm})
        assert r.status_code == 304 and r.content == b"" and r.headers["etag"] == etag
    assert client.get("/locales.js?lang=fr", headers={"If-None-Match": etag}).status_code == 200


_SWITCH_JS = r"""
const path = require("path"), fs = require("fs");
const dir = process.argv[1];
const file = l => path.join(dir, l ? "locales-" + l + ".js" : "locales.js");
const run = (o, steps) => {
  for (const k of Object.keys(require.cache)) delete require.cache[k];
  const out = { reloads: 0, events: [], errors: [] };
  const appended = [], session = Object.assign({}, o.session || {});
  const sel = { value: "", innerHTML: "", appendChild() {}, addEventListener() {} };
  global.CustomEvent = function (t, init) { this.type = t; this.detail = init.detail; };
  const timers = [];
  global.setTimeout = fn => timers.push(fn); global.clearTimeout = id => { timers[id - 1] = null; };
  global.window = { addEventListener() {}, removeEventListener() {},
                    dispatchEvent(e) { out.events.push(e.detail.lang); } };
  global.document = {
    documentElement: { style: {}, lang: "" }, readyState: "complete", cookie: o.cookie || "",
    querySelectorAll: s => (s === "select.lang-sel" ? [sel] : []), addEventListener() {},
    createElement: () => ({}), head: { appendChild(s) { s.parentNode = { removeChild() {} }; appended.push(s); } },
  };
  let stored = o.stored || null;
  global.localStorage = o.noStorage ? { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } }
    : { getItem: () => stored, setItem: (k, v) => { stored = v; } };
  global.sessionStorage = { getItem: k => (k in session ? session[k] : null),
                            setItem: (k, v) => { session[k] = String(v); }, removeItem: k => { delete session[k]; } };
  global.location = { reload() { out.reloads++; } };
  require(file(o.bundle));
  require(path.join(dir, "lang.js"));
  require(path.join(dir, "i18n.js"));
  // Serve (or fail) the bundles lang.js asked for.
  const serve = fail => appended.splice(0).forEach(s => {
    out.requested = (out.requested || []).concat(s.src);
    if (fail) return s.onerror();
    require(file(/lang=(\w+)/.exec(s.src)[1]));
    s.onload();
  });
  const snap = () => ({ lang: window.ZING_LANG.get(), html: document.documentElement.lang,
    hidden: document.documentElement.style.visibility === "hidden", select: sel.value,
    history: window.ZING_LANG.tr("History"), stored, cookie: /zing_lang=(\w+)/.exec(document.cookie)?.[1] || null,
    session: Object.assign({}, session), pending: appended.length, zhFindings: Object.keys(window.ZING_I18N.FINDINGS).length });
  out.boot = snap();
  for (const st of steps || []) {
    try {
      if (st.set) { sel.value = st.set; window.ZING_LANG.set(st.set); }
      if (st.serve) serve(st.serve === "fail");
      if (st.timers) timers.splice(0).forEach(fn => fn && fn());
      if (st.report) out.report = window.ZING_LOCALES.strings;
    } catch (e) { out.errors.push(String(e)); }
    (out.after = out.after || []).push(snap());
  }
  out.locales = window.ZING_LOCALES;
  return out;
};
const pick = r => ({ ...r, locales: undefined });
const r = {
  same: pick(run({ bundle: "de", stored: "de", cookie: "zing_lang=de", session: { "zing.lang.reload": "de" } })),
  stale: pick(run({ bundle: "de", stored: "fr", cookie: "zing_lang=de" })),
  again: pick(run({ bundle: "de", stored: "fr", cookie: "zing_lang=de", session: { "zing.lang.reload": "fr" } }, [{ serve: "ok" }])),
  noReload: pick(run({ bundle: "de", stored: "fr", cookie: "zing_lang=de" }, [{ timers: true }, { serve: "ok" }])),
  noStorage: pick(run({ bundle: "de", noStorage: true, cookie: "zing_lang=de" })),
  common: pick(run({ bundle: "de", stored: "de", cookie: "zing_lang=de" }, [{ report: true }])),
  againFail: pick(run({ bundle: "de", stored: "fr", cookie: "zing_lang=de", session: { "zing.lang.reload": "fr" } }, [{ serve: "fail" }])),
  full: pick(run({ bundle: null, stored: "it" })),
  toZh: pick(run({ bundle: "en", stored: "en", cookie: "zing_lang=en" }, [{ set: "zh" }, { serve: "ok" }, { set: "en" }, { set: "zh" }])),
  fail: pick(run({ bundle: "en", stored: "en", cookie: "zing_lang=en" }, [{ set: "de" }, { serve: "fail" }])),
  superseded: pick(run({ bundle: "en", stored: "en", cookie: "zing_lang=en" }, [{ set: "de" }, { set: "fr" }, { serve: "ok" }])),
};
// Every one-language bundle merged together is the full bundle.
const m = run({ bundle: "en", stored: "en" }).locales;
for (const c of m.languages.map(l => l.code)) if (c !== "en") require(file(c));
const f = run({ bundle: null }).locales;
const same = k => JSON.stringify(m[k]) === JSON.stringify(f[k]);
r.merged = { strings: same("strings"), findings: same("findings"), keys: same("keys"), languages: same("languages") };
console.log(JSON.stringify(r));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_lang_js_loads_the_missing_language_bundle(tmp_path):
    from zing import i18n

    _ui_js(tmp_path)
    for code in i18n.codes():
        (tmp_path / f"locales-{code}.js").write_text(i18n.locales_script(code), encoding="utf-8")
    r = json.loads(subprocess.run(
        ["node", "-e", _SWITCH_JS, str(tmp_path)], capture_output=True, text=True, check=True,
    ).stdout)
    de_history = i18n.ui("de", "History")
    fr_history = i18n.ui("fr", "History")

    # The bundle has the stored language: no reload, the guard is cleared.
    b = r["same"]["boot"]
    assert (b["lang"], b["html"], b["history"], b["hidden"]) == ("de", "de", de_history, False)
    assert r["same"]["reloads"] == 0 and b["session"] == {} and b["pending"] == 0
    # Stale cookie: fix it and reload once, the page still hidden.
    b = r["stale"]["boot"]
    assert r["stale"]["reloads"] == 1 and b["cookie"] == "fr" and b["hidden"]
    assert b["session"] == {"zing.lang.reload": "fr"} and b["stored"] == "fr"
    # Already reloaded once: no loop; English at once, then the bundle loads.
    a = r["again"]
    assert a["reloads"] == 0 and a["boot"]["lang"] == "en" and not a["boot"]["hidden"]
    assert a["requested"] == ["/locales.js?lang=fr"]
    assert a["after"][0]["lang"] == "fr" and a["after"][0]["history"] == fr_history
    assert a["events"] == ["fr"] and a["after"][0]["html"] == "fr"
    a = r["againFail"]
    assert a["after"][0]["lang"] == "en" and a["after"][0]["select"] == "en"
    assert a["after"][0]["stored"] == "fr" and a["errors"] == [] and not a["after"][0]["hidden"]
    # The reload doesn't come: the reveal timer shows English and loads fr.
    n = r["noReload"]
    assert n["reloads"] == 1 and n["boot"]["hidden"]
    assert not n["after"][0]["hidden"] and n["after"][0]["pending"] == 1
    assert n["after"][1]["lang"] == "fr" and n["events"] == ["fr"]
    # No localStorage: the cookie keeps the choice.
    b = r["noStorage"]["boot"]
    assert (b["lang"], b["cookie"], r["noStorage"]["reloads"]) == ("de", "de", 0)
    # Other languages carry the strings report.js needs for all of them.
    fr = r["common"]["report"]["fr"]
    assert fr["Overall health score {1}/100."] == i18n.ui("fr", "Overall health score {1}/100.")
    assert len(fr) == 2 and len(r["common"]["report"]["de"]) > 100
    # The full bundle (no cookie yet) has every language; the cookie is set.
    b = r["full"]["boot"]
    assert (b["lang"], b["cookie"], r["full"]["reloads"], b["pending"]) == ("it", "it", 0, 0)

    # set() to a language not loaded: fetch, merge, then switch.
    z = r["toZh"]
    assert z["boot"]["zhFindings"] == 0
    assert z["after"][0]["lang"] == "en" and z["after"][0]["pending"] == 1
    assert z["after"][1]["lang"] == "zh" and z["after"][1]["html"] == "zh-CN"
    # i18n.js's catalog reference sees the merged zh findings
    assert z["after"][1]["zhFindings"] == len(i18n._load()["zh"]["findings"])
    assert (z["after"][1]["stored"], z["after"][1]["cookie"]) == ("zh", "zh")
    assert z["after"][3]["lang"] == "zh" and z["after"][3]["pending"] == 0  # cached now
    assert z["events"] == ["zh", "en", "zh"] and z["errors"] == []
    # A failed load keeps the language and puts the switcher back.
    f = r["fail"]["after"][-1]
    assert (f["lang"], f["select"], f["stored"], f["cookie"]) == ("en", "en", "en", "en")
    assert r["fail"]["events"] == [] and r["fail"]["errors"] == []
    # Only the latest choice applies.
    s = r["superseded"]
    assert s["after"][-1]["lang"] == "fr" and s["events"] == ["fr"]

    assert r["merged"] == {"strings": True, "findings": True, "keys": True, "languages": True}


_INTL_JS = r"""
const path = require("path");
const dir = process.argv[1];
const made = {};
for (const name of ["DateTimeFormat", "NumberFormat", "DisplayNames"]) {
  const Orig = Intl[name];
  made[name] = 0;
  Intl[name] = function (loc, opts) { made[name]++; return new Orig(loc, opts); };
}
global.window = { addEventListener() {}, dispatchEvent() {} };
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => "en", setItem() {} };
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
const L = window.ZING_LANG;
const d = new Date(Date.UTC(2026, 9, 6, 12, 34)), opts = { dateStyle: "medium", timeStyle: "short" };
const snap = () => ({
  locale: L.locale(),
  date: L.dateFmt(opts).format(d), wantDate: d.toLocaleString(L.locale(), opts),
  num: L.numFmt({ maximumFractionDigits: 1 }).format(12345.67),
  wantNum: (12345.67).toLocaleString(L.locale(), { maximumFractionDigits: 1 }),
  plain: L.numFmt().format(1234), wantPlain: (1234).toLocaleString(L.locale()),
  lang: L.intl(Intl.DisplayNames, { type: "language" }, [L.locale() || "en"]).of("de"),
});
const out = { en: snap(), en2: snap() };
const afterEn = Object.assign({}, made);
L.set("de"); out.de = snap();
L.set("en"); out.back = snap();
const afterBack = Object.assign({}, made);
const err = (f) => { try { f(); return "ok"; } catch (e) { return e.name; } };
out.errors = {
  locale: err(() => L.intl(Intl.NumberFormat, {}, "not a locale!")),
  options: err(() => L.dateFmt({ dateStyle: "nope" })),
  ctor: err(() => L.intl(undefined, {})),
  joined: err(() => { L.intl(Intl.NumberFormat, {}, ["en-US", "fr-FR"]); L.intl(Intl.NumberFormat, {}, "en-US,fr-FR"); }),
};
out.browserDefault = L.intl(Intl.NumberFormat, {}, undefined).format(1234) === (1234).toLocaleString();
out.same = L.numFmt() === L.numFmt() && L.numFmt() !== L.intl(Intl.NumberFormat, undefined, undefined);
console.log(JSON.stringify({ out, afterEn, afterBack }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_shared_intl_formatters_are_cached_per_locale(tmp_path):
    from zing.i18n import locales_script

    (tmp_path / "locales.js").write_text(locales_script(), encoding="utf-8")
    shutil.copy(_STATIC / "lang.js", tmp_path / "lang.js")
    res = json.loads(subprocess.run(
        ["node", "-e", _INTL_JS, str(tmp_path)], capture_output=True, text=True, check=True,
    ).stdout)
    out = res["out"]
    # same text as toLocaleString, in the language shown (also after set())
    for key in ("en", "de", "back"):
        o = out[key]
        assert o["date"] == o["wantDate"] and o["num"] == o["wantNum"] and o["plain"] == o["wantPlain"], key
    assert out["en"]["locale"] == "en-US" and out["de"]["locale"] == "de-DE"
    assert out["de"]["num"] != out["en"]["num"] and out["de"]["lang"] == "Deutsch"
    assert out["en"] == out["en2"] == out["back"]
    # one formatter per (constructor, locale, options); switching back reuses them
    assert res["afterEn"] == {"DateTimeFormat": 1, "NumberFormat": 2, "DisplayNames": 1}
    assert res["afterBack"] == {"DateTimeFormat": 2, "NumberFormat": 4, "DisplayNames": 2}
    # bad input still throws, so the callers' fallbacks run as before
    assert out["errors"] == {
        "locale": "RangeError", "options": "RangeError", "ctor": "TypeError", "joined": "RangeError",
    }
    assert out["browserDefault"] and out["same"]


# --------------------------------------------------------------------------- #
# Fingerprint findings: one title per KB signal, in every language
# --------------------------------------------------------------------------- #
def _kb_signals() -> set[str]:
    """Every ``fingerprints[].signal`` in the packaged KB (zing/knowledge/data)."""
    import yaml

    out: set[str] = set()

    def walk(o: object) -> None:
        if isinstance(o, dict):
            out.update(f["signal"] for f in o.get("fingerprints") or [] if isinstance(f, dict) and f.get("signal"))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    data = Path(__file__).resolve().parent.parent / "zing" / "knowledge" / "data"
    for path in sorted(data.glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            walk(doc)
    return out


def test_every_fingerprint_signal_is_translated():
    # A divergence finding's title names its signal ("Fingerprint divergence:
    # <signal>"); the localized title shows it translated (i18n.js {signal|server}),
    # so every KB signal needs a translation in every language but EN.
    from zing import i18n

    signals = _kb_signals()
    assert len(signals) > 20
    data = i18n._load()
    for code in i18n.codes():
        if code == "en":
            continue
        strings = data[code].get("strings", {})
        assert sorted(s for s in signals if not strings.get(s) or strings[s] == s) == [], code
        title, _tpl, generic = data[code]["findings"]["model_identity.fp.*"]
        assert "{signal|server}" in title and "{" not in generic, code


_FP_TITLES_JS = r"""
const path = require("path");
const dir = process.argv[1], signals = JSON.parse(process.argv[2]);
const out = {};
for (const lang of ["en", "zh", "fr", "es", "pt", "it", "de"]) {
  for (const m of ["locales.js", "lang.js", "i18n.js"]) delete require.cache[require.resolve(path.join(dir, m))];
  global.window = {};
  global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete", querySelectorAll: () => [], addEventListener() {} };
  global.localStorage = { getItem: () => lang, setItem() {} };
  for (const m of ["locales.js", "lang.js", "i18n.js"]) require(path.join(dir, m));
  const I = window.ZING_I18N;
  const findings = signals.map((s, i) => ({ id: "model_identity.fp.p" + i, title: "Fingerprint divergence: " + s,
    status: "warn", severity: "low", summary: "x", evidence: { probe: "p" + i, signal: s }, recommendation: null }));
  const report = { detectors: [{ name: "x", findings }], verdict: { key_findings: findings.map(f => f.title) } };
  const ex = I.exportReport(report);
  out[lang] = {
    titles: findings.map(f => I.localizeFinding(f.id, f.summary, f.evidence, f.title, f.status).title),
    exported: ex.detectors[0].findings.map(f => f.title), key_findings: ex.verdict.key_findings,
    old: I.localizeFinding("model_identity.fp.p", "x", { probe: "p" }, "Fingerprint divergence: self-identification", "warn").title,
    unknown: I.localizeFinding("model_identity.fp.p", "x", { probe: "p" }, "Fingerprint went sideways", "warn").title,
    signal: signals.map(s => window.ZING_LANG.server(s)),
  };
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_fingerprint_findings_get_distinct_localized_titles(tmp_path):
    from zing import i18n

    signals = sorted(_kb_signals())
    out = json.loads(subprocess.run(
        ["node", "-e", _FP_TITLES_JS, str(_ui_js(tmp_path)), json.dumps(signals)],
        capture_output=True, text=True, check=True,
    ).stdout)
    assert out["en"]["titles"] == ["Fingerprint divergence: " + s for s in signals]
    for lang, r in out.items():
        assert len(set(r["titles"])) == len(signals), lang  # one title per signal
        assert r["exported"] == r["key_findings"] == r["titles"], lang  # the download matches the UI
        if lang == "en":
            continue
        fp = i18n._load()[lang]["findings"]["model_identity.fp.*"]
        assert r["titles"] == [fp[0].replace("{signal|server}", s) for s in r["signal"]], lang
        assert all(t != s for t, s in zip(r["signal"], signals, strict=True)), lang  # signals translated
        # no signal recorded (older report): the result title still names it
        assert r["old"] == fp[0].replace("{signal|server}", i18n.ui(lang, "self-identification")), lang
        assert r["unknown"] == fp[2], lang  # an unknown title and no signal: the generic title
    # the webhook alerts' titles (zing.notify) agree
    assert i18n.finding_title("de", "model_identity.fp.self-id", "x", {"signal": "self-identification"}) == (
        "Fingerprint-Abweichung: Selbstidentifikation"
    )
    assert i18n.finding_title("de", "model_identity.fp.self-id", "x", {"probe": "self-id"}) == (
        "Verhaltens-Fingerprint-Prüfung"
    )


# --------------------------------------------------------------------------- #
# Result titles: the backend's per-outcome English title, in every language
# --------------------------------------------------------------------------- #
def _result_titles() -> tuple[set[str], set[str]]:
    """Every finding title the backend can emit: ``(fixed titles, templates)``.

    A title is the ``title=`` of a finding built in zing/detectors (or the title
    argument of the embed/media audits' ``_finding``): a literal, either branch
    of a conditional, a module-level ``{…: title}`` dict looked up, or an
    f-string around one subject (a template, its subject as ``{1}``). Any other
    form fails, so a new dynamic title cannot slip past the translations.
    """
    root = Path(__file__).resolve().parent.parent / "zing"
    fixed: set[str] = set()
    templates: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        dicts = {
            n.targets[0].id: n.value
            for n in tree.body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Dict)
        }

        def add(v: ast.AST, rel: str = rel, dicts: dict = dicts) -> None:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                fixed.add(v.value)
            elif isinstance(v, ast.IfExp):
                add(v.body)
                add(v.orelse)
            elif isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name) and v.value.id in dicts:
                for x in dicts[v.value.id].values:
                    add(x)
            elif isinstance(v, ast.JoinedStr):
                parts = ["{1}" if isinstance(x, ast.FormattedValue) else x.value for x in v.values]
                assert parts.count("{1}") == 1, f"{rel}:{v.lineno}: a title template takes one subject"
                templates.add("".join(parts))
            else:
                raise AssertionError(f"{rel}:{v.lineno}: untranslatable finding title {ast.unparse(v)}")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = ast.unparse(node.func)
            # (scale.py's Finding only passes a detector's title through)
            if rel != "detectors/scale.py" and (rel.startswith("detectors/") or fn == "Finding"):
                for k in node.keywords:
                    if k.arg == "title":
                        add(k.value)
            if fn == "_finding" and len(node.args) > 1:
                add(node.args[1])
    return fixed, templates


def test_every_result_title_is_translated():
    # The UI, the download and the webhook alerts show a finding's result
    # title ("Endpoint is not HTTPS"), not just its check's, so every title the
    # backend can emit needs a translation in every language but EN.
    from zing import i18n

    fixed, templates = _result_titles()
    assert len(fixed) > 150 and "Endpoint is not HTTPS" in fixed
    assert templates == set(i18n.RESULT_TITLE_PATTERNS)
    data = i18n._load()
    for code in i18n.codes():
        if code == "en":
            continue
        strings = data[code]["strings"]
        assert sorted(t for t in fixed | templates if not strings.get(t)) == [], code
        assert sorted(t for t in templates if strings[t].count("{1}") != 1) == [], code
        assert sorted(t for t in fixed if i18n.result_title(code, t) is None) == [], code
    assert i18n.result_title("de", "Fingerprint consistent: self-identification") == (
        "Fingerprint stimmig: Selbstidentifikation"
    )
    assert i18n.result_title("fr", "Response attribute choices[0].logprobs") == (
        "Attribut de réponse choices[0].logprobs"
    )
    assert i18n.result_title("de", "Some new title") is None


# (id, passing English title, failing English title, evidence) of one check.
_PASS_FAIL = [
    ("security.tls", "Endpoint uses HTTPS", "Endpoint is not HTTPS", {}),
    ("model_identity.self_id", "Self-identification consistent", "Self-identifies as a rival brand", {}),
    ("model_identity.fp.self-id", "Fingerprint consistent: self-identification",
     "Fingerprint divergence: self-identification", {"probe": "self-id"}),
]

_PASS_FAIL_JS = r"""
const path = require("path");
const dir = process.argv[1], cases = JSON.parse(process.argv[2]);
const out = {};
for (const lang of ["en", "zh", "fr", "es", "pt", "it", "de"]) {
  for (const m of ["locales.js", "lang.js", "i18n.js"]) delete require.cache[require.resolve(path.join(dir, m))];
  global.window = {};
  global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete", querySelectorAll: () => [], addEventListener() {} };
  global.localStorage = { getItem: () => lang, setItem() {} };
  for (const m of ["locales.js", "lang.js", "i18n.js"]) require(path.join(dir, m));
  const I = window.ZING_I18N;
  const f = (id, title, status, evidence) => ({ id, title, status, severity: "info", summary: "x", evidence, recommendation: null });
  const findings = [];
  for (const [id, pass, fail, ev] of cases) findings.push(f(id, pass, "pass", ev), f(id, fail, "fail", ev));
  const ex = I.exportReport({ detectors: [{ name: "x", findings }], verdict: { key_findings: [] } });
  out[lang] = {
    ui: findings.map(x => I.localizeFinding(x.id, x.summary, x.evidence, x.title, x.status).title),
    exported: ex.detectors[0].findings.map(x => x.title),
    // a title this version does not know (an older or newer backend): the check's title
    unknown: I.localizeFinding("security.tls", "x", {}, "Some retired title", "fail").title,
  };
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_pass_and_fail_of_one_check_get_different_localized_titles(tmp_path):
    from zing import i18n

    out = json.loads(subprocess.run(
        ["node", "-e", _PASS_FAIL_JS, str(_ui_js(tmp_path)), json.dumps(_PASS_FAIL)],
        capture_output=True, text=True, check=True,
    ).stdout)
    english = [t for _id, p, f, _ev in _PASS_FAIL for t in (p, f)]
    assert out["en"]["ui"] == out["en"]["exported"] == english
    for lang, r in out.items():
        assert r["exported"] == r["ui"], lang  # the download matches the UI
        if lang == "en":
            continue
        for i, (fid, passed, failed, ev) in enumerate(_PASS_FAIL):
            p, f = r["ui"][2 * i], r["ui"][2 * i + 1]
            assert p != f, (lang, fid)
            assert (p, f) == (i18n.result_title(lang, passed), i18n.result_title(lang, failed)), (lang, fid)
            # the webhook alerts' titles agree
            assert i18n.finding_title(lang, fid, passed, ev) == p, (lang, fid)
            assert i18n.finding_title(lang, fid, failed, ev) == f, (lang, fid)
        check_title = i18n._load()[lang]["findings"]["security.tls"][0]
        assert r["unknown"] == check_title, lang
        assert i18n.finding_title(lang, "security.tls", "Some retired title") == check_title, lang
