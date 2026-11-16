"""One page template (issue 230), as drawn at 1280 px on every page:

- the blocks of <main> come in one order: hero, page notice, toolbar (the
  filters and the page's own actions), then the content (a tab card or the
  page's cards);
- one gap between the blocks (--s-5, 24 px);
- text in the column starts at two x positions only: the hero's (the
  column's edge) and the cards' content (one card padding in);
- an action row (.actions) holds buttons as wide as their labels, at most
  one primary, last; only the audit's Start audit (.cta) spans the width.

tests/test_web_template.py keeps the page markup and stylesheets to it.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.a11y.harness import PAGES, assert_no_issues

TEMPLATE_JS = """() => {
  const out = [], main = document.querySelector("main"), colL = main.getBoundingClientRect().left;
  const pad = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--pad")) || 24;
  const shown = (e) => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(e).visibility !== "hidden"; };
  const notice = (e) => e.classList.contains("znote") || (!e.classList.length && e.children.length === 1 && e.firstElementChild.classList.contains("znote"));
  const rank = (e) => e.classList.contains("hero") ? 0 : notice(e) ? 1
    : (e.classList.contains("toolbar") || e.classList.contains("filters")) ? 2 : 3;
  const blocks = [...main.children].filter((e) => shown(e) && !e.classList.contains("sr-only"));
  let last = -1, prev = null;
  blocks.forEach((b) => {
    const name = b.tagName.toLowerCase() + (b.id ? "#" + b.id : "") + "." + [...b.classList].join(".");
    const r = rank(b);
    if (r < last) out.push(`${name} comes after a later template block`);
    last = Math.max(last, r);
    if (prev) {
      const gap = Math.round(b.getBoundingClientRect().top - prev.getBoundingClientRect().bottom);
      if (Math.abs(gap - 24) > 1) out.push(`${gap}px between ${prev.className} and ${name}, not 24`);
    }
    prev = b;
    // the leftmost thing drawn in the block: a text line, an icon or a control
    let min = Infinity;
    const walk = document.createTreeWalker(b, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = walk.currentNode; n; n = walk.nextNode()) {
      if (n.nodeType === 3) {
        if (!n.data.trim() || !n.parentElement || !shown(n.parentElement) || n.parentElement.closest(".sr-only")) continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        for (const q of rg.getClientRects()) if (q.width > 0) min = Math.min(min, q.left);
      } else if (n.matches("svg, img, input, select, textarea") && shown(n) && !n.closest(".sr-only")) {
        min = Math.min(min, n.getBoundingClientRect().left);
      }
    }
    if (min === Infinity) return;
    const x = Math.round(min - colL), card = 1 + pad;
    if (Math.abs(x) > 2 && Math.abs(x - card) > 2) out.push(`${name}: content starts ${x}px into the column (not 0 or ${card})`);
  });
  document.querySelectorAll(".actions").forEach((row) => {
    if (!shown(row)) return;
    const btns = [...row.children].filter((e) => e.matches(".btn, button, a.btn") && shown(e));
    const pri = btns.filter((e) => e.classList.contains("pri"));
    if (pri.length > 1) out.push(`an action row with ${pri.length} primary buttons`);
    if (pri.length && btns[btns.length - 1] !== pri[0]) out.push(`the primary action "${pri[0].textContent.trim()}" is not last`);
    const w = row.getBoundingClientRect().width;
    btns.forEach((b) => { if (btns.length > 1 && b.getBoundingClientRect().width > w * 0.6) out.push(`"${b.textContent.trim()}" spans its row`); });
  });
  document.querySelectorAll(".cta").forEach((c) => { if (c.id !== "go") out.push(`a full-width .cta other than Start audit: ${c.textContent.trim()}`); });
  return out;
}"""


@pytest.mark.bitv("9.1.3.2")
@pytest.mark.parametrize("page_id", list(PAGES))
def test_pages_follow_one_template(open_page: Any, page_id: str) -> None:
    page = open_page(PAGES[page_id], "en")
    assert_no_issues(page.evaluate(TEMPLATE_JS), f"{page_id} [en]", "page-template")


# A monitor's setup form (Monitors, a draft): its parts span the form like its
# fields do, and every field label has the one label style.
SETUP_JS = """async () => {
  const out = [], form = document.querySelector(".setup");
  if (!form) return ["no draft monitor with a setup form"];
  form.querySelector("[data-act=win-preset][data-v=weekdays7]").click();
  await new Promise((r) => setTimeout(r, 300));
  const f = document.querySelector(".setup"), fr = f.getBoundingClientRect();
  const parts = [f.querySelector(".fields"), ...f.querySelectorAll(".setup-rw > *:not(.lab), .setup-rw .rw-times")];
  parts.forEach((p) => {
    if (!p) return;
    const r = p.getBoundingClientRect();
    if (r.width && (Math.abs(r.left - fr.left) > 1 || Math.abs(r.right - fr.right) > 1)) {
      out.push(`${p.className || p.tagName}: spans ${Math.round(r.left - fr.left)}..${Math.round(r.right - fr.left)} of 0..${Math.round(fr.width)}`);
    }
  });
  const style = (e) => { const c = getComputedStyle(e); return [c.fontSize, c.fontWeight, c.textTransform, c.letterSpacing].join(" "); };
  const ref = style(f.querySelector(".fields .lab"));
  f.querySelectorAll(".lab, label.sub, legend.sub").forEach((l) => {
    if (style(l) !== ref) out.push(`label "${l.textContent.trim()}" is styled ${style(l)}, not ${ref}`);
  });
  return out;
}"""


@pytest.mark.parametrize("width", [1280, 390])
def test_monitor_setup_spans_one_column(open_page: Any, width: int) -> None:
    page = open_page(PAGES["monitors"], "en", viewport={"width": width, "height": 900})
    assert_no_issues(page.evaluate(SETUP_JS), f"monitors [en, {width}px]", "setup-form")
