"""The claimed-model picker (ekte/web/static/modelpicker.js), evaluated under node.

A tiny fake DOM is enough: the picker only creates elements, sets styles,
classes and attributes, and listens for change/click events.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = r"""
const path = require("path");
const lang = process.argv[2];

class ClassList {
  constructor(el) { this.el = el; }
  _get() { return this.el.className ? this.el.className.split(/\s+/).filter(Boolean) : []; }
  contains(c) { return this._get().includes(c); }
  toggle(c, on) {
    const l = this._get().filter(x => x !== c);
    if (on === undefined ? !this.contains(c) : on) l.push(c);
    this.el.className = l.join(" ");
  }
}
class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null;
    this.style = {}; this.attrs = {}; this.className = ""; this.listeners = {};
    this.textContent = ""; this.title = ""; this.disabled = false; this._value = "";
    this.classList = new ClassList(this);
  }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); c.parentNode = null; }
  insertBefore(c, ref) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.children.splice(this.children.indexOf(ref), 0, c); return c;
  }
  set innerHTML(v) { this.children.forEach(c => (c.parentNode = null)); this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatchEvent(e) { (this.listeners[e.type] || []).forEach(f => f(e)); }
  focus() {}
  get options() {
    return this.children.flatMap(c => (c.tagName === "OPTGROUP" ? c.children : [c])).filter(c => c.tagName === "OPTION");
  }
  get selectedIndex() { return this.options.findIndex(o => o.value === this._value); }
  get value() {
    if (this.tagName !== "SELECT") return this._value;
    return this.selectedIndex >= 0 ? this._value : (this.options[0] ? this.options[0].value : "");
  }
  set value(v) {
    if (this.tagName !== "SELECT") { this._value = v; return; }
    this._value = this.options.some(o => o.value === v) ? v : (this.options[0] ? this.options[0].value : "");
  }
}
global.Event = class { constructor(type) { this.type = type; } };
global.document = { createElement: t => new El(t), querySelector: () => null };
global.window = { addEventListener() {} };
window.EKTE_LANG = {
  isZh: () => lang === "zh",
  t: (zh, en) => (lang === "zh" ? zh : en),
  stripCJK: s => String(s).replace(/[㐀-鿿]+/g, "").replace(/\(\s*\/\s*/g, "(").replace(/\s{2,}/g, " ").trim(),
};
const KB = { providers: [
  { provider: "deepseek", display_name: "DeepSeek (DeepSeek-AI / Hangzhou DeepSeek)",
    models: [{ id: "deepseek-chat", aliases: ["DeepSeek-V3"] }] },
  { provider: "moonshot", display_name: "Moonshot AI (月之暗面 / Kimi)", models: [{ id: "kimi-k2" }] },
  { provider: "alibaba", display_name: "Alibaba Cloud — Qwen / 通义千问, served via DashScope", models: [] },
]};
const RELAY = { ok: true, models: ["deepseek-chat", "deepseek-v9-preview"] };
global.fetch = (url) => Promise.resolve({ ok: true, json: () => Promise.resolve(url === "/api/models" ? RELAY : KB) });
require(path.join(process.argv[1], "modelpicker.js"));

function mount(unstyled) {
  const form = new El("form");
  const input = form.appendChild(new El("input"));
  const url = form.appendChild(new El("input"));
  window.EkteModelPicker.enhance({ claimedInput: input, urlInput: url, unstyled });
  return { form, input };
}
function describe(el) {
  return {
    tag: el.tagName, cls: el.className, style: el.style, attrs: el.attrs, title: el.title,
    text: el.tagName === "OPTION" ? el.textContent : undefined,
    children: el.tagName === "OPTION" ? [] : el.children.map(describe),
  };
}
const classic = mount(false), v2 = mount(true);
setTimeout(() => {
  const wrap = v2.form.children[0];
  const [sels, , toggle] = wrap.children;
  const [prov, , model] = sels.children;
  const snap = describe(wrap);
  const before = { prov: prov.className, model: model.className, title: prov.title, pressed: toggle.attrs["aria-pressed"] };
  prov.value = "deepseek"; prov.dispatchEvent(new Event("change"));
  model.value = "deepseek-chat"; model.dispatchEvent(new Event("change"));
  toggle.dispatchEvent(new Event("click"));
  console.log(JSON.stringify({
    classic: describe(classic.form.children[0]),
    v2: snap,
    before,
    after: { prov: prov.className, model: model.className, provTitle: prov.title, modelTitle: model.title,
             pressed: toggle.attrs["aria-pressed"], value: v2.input.value, toggleText: toggle.textContent },
  }));
}, 0);
"""

_STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static"


def _run(lang: str) -> dict:
    return json.loads(subprocess.run(
        ["node", "-e", _JS, str(_STATIC), lang], capture_output=True, text=True, check=True,
    ).stdout)


def _walk(node):
    yield node
    for c in node["children"]:
        yield from _walk(c)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_modelpicker_default_keeps_classic_inline_styles():
    classic = _run("en")["classic"]
    assert classic["cls"] == "zmp" and classic["style"]["gap"] == "8px"
    selects = [n for n in _walk(classic) if n["tag"] == "SELECT"]
    assert len(selects) == 2
    for s in selects:
        assert s["cls"] == "" and s["style"]["background"] == "#fbfdfa"
        assert s["style"]["border"] == "1.5px solid var(--line, #e7ece5)"
        assert "aria-label" not in s["attrs"]  # no label passed: unchanged classic DOM
    opts = [n["text"] for n in _walk(selects[0]) if n["tag"] == "OPTION"]
    # classic keeps the full (CJK-stripped) provider names
    assert "DeepSeek (DeepSeek-AI / Hangzhou DeepSeek)" in opts
    toggle = classic["children"][-1]
    assert toggle["tag"] == "BUTTON" and toggle["cls"] == "" and toggle["style"]["color"].startswith("var(--teal")
    assert "aria-pressed" not in toggle["attrs"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_modelpicker_unstyled_uses_class_hooks():
    out = _run("en")
    v2 = out["v2"]
    assert v2["cls"] == "zmp zmp-unstyled"
    for n in _walk(v2):
        # only the show/hide display toggles remain inline; no colours/borders/backgrounds
        assert set(n["style"]) <= {"display"}, (n["tag"], n["style"])
    provs = [n for n in _walk(v2) if n["tag"] == "SELECT"]
    assert [p["cls"] for p in provs] == ["in zmp-sel zmp-prov is-empty", "in zmp-sel zmp-model is-empty"]
    assert provs[0]["attrs"]["aria-label"] == "Provider" and provs[1]["attrs"]["aria-label"] == "Model"
    opts = {n["text"]: n["title"] for n in _walk(provs[0]) if n["tag"] == "OPTION"}
    # long provider names are shortened, the full name stays in the title
    assert opts["DeepSeek"] == "DeepSeek (DeepSeek-AI / Hangzhou DeepSeek)"
    assert opts["Moonshot AI"] == "Moonshot AI (Kimi)"
    assert "Alibaba Cloud" in opts
    fetch_row = v2["children"][0]["children"][1]
    assert fetch_row["cls"] == "zmp-fetch"
    assert fetch_row["children"][0]["cls"] == "btn sm zmp-fetch-btn"
    assert fetch_row["children"][1]["attrs"]["role"] == "status"
    toggle = v2["children"][-1]
    assert toggle["tag"] == "BUTTON" and toggle["cls"] == "linkbtn zmp-custom"
    assert out["before"]["pressed"] == "false"
    after = out["after"]
    assert after["prov"] == "in zmp-sel zmp-prov" and after["model"] == "in zmp-sel zmp-model"
    assert after["provTitle"] == "DeepSeek (DeepSeek-AI / Hangzhou DeepSeek)"
    assert after["modelTitle"] == "deepseek-chat · DeepSeek-V3"
    assert after["value"] == "deepseek-chat"
    assert after["pressed"] == "true" and after["toggleText"] == "← Pick a model"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_modelpicker_unstyled_labels_follow_the_language():
    out = _run("zh")
    provs = [n for n in _walk(out["v2"]) if n["tag"] == "SELECT"]
    assert provs[0]["attrs"]["aria-label"] == "供应商" and provs[1]["attrs"]["aria-label"] == "模型"
    opts = [n["text"] for n in _walk(provs[0]) if n["tag"] == "OPTION"]
    assert "Moonshot AI" in opts  # shortened in Chinese too; the title keeps 月之暗面


# A model newer than the knowledge base: "Fetch models" works for every
# provider, not only "Custom (from relay)", and adds the relay's unknown ids.
_FETCH_JS = _JS.split("function mount")[0] + r"""
const form = new El("form");
const model = form.appendChild(new El("input"));
const url = form.appendChild(new El("input"));
const prov = form.appendChild(new El("input"));
url.value = "https://relay.test/v1";
window.EkteModelPicker.enhance({ claimedInput: model, providerInput: prov, urlInput: url, unstyled: true });
const tick = () => new Promise(r => setTimeout(r, 0));
(async () => {
  await tick();
  const [sels] = form.children[0].children;
  const [provSel, fetchRow, modelSel] = sels.children;
  provSel.value = "deepseek"; provSel.dispatchEvent(new Event("change"));
  const shown = fetchRow.style.display, disabled = fetchRow.children[0].disabled;
  fetchRow.children[0].dispatchEvent(new Event("click"));
  await tick(); await tick(); await tick();
  const groups = modelSel.children.filter(c => c.tagName === "OPTGROUP");
  modelSel.value = "deepseek-v9-preview"; modelSel.dispatchEvent(new Event("change"));
  console.log(JSON.stringify({
    shown, disabled,
    texts: modelSel.options.map(o => o.textContent),
    group: groups.map(g => [g.label, g.children.map(o => o.value)]),
    status: fetchRow.children[1].textContent,
    value: model.value, provider: prov.value,
  }));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_modelpicker_fetches_relay_models_for_a_knowledge_base_provider():
    out = json.loads(subprocess.run(
        ["node", "-e", _FETCH_JS, str(_STATIC), "en"], capture_output=True, text=True, check=True,
    ).stdout)
    assert out["shown"] == "flex" and out["disabled"] is False
    # the KB model the relay lists is marked; the unknown one is still offered
    assert "deepseek-chat · DeepSeek-V3 ✓" in out["texts"]
    assert out["group"] == [["Relay only (not in knowledge base)", ["deepseek-v9-preview"]]]
    assert out["status"] == "✓ Models found: 2"
    assert out["value"] == "deepseek-v9-preview" and out["provider"] == "deepseek"
