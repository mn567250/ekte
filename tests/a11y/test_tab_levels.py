"""Tabs, segmented controls and chips each show their selection in their own
way (issue 225), in both themes, as the browser draws them:

- a selected primary tab is a raised surface pill (the card colour), a
  selected secondary tab is underlined in the primary colour, a pressed
  segment or chip is a primary-tint wash with a primary border; none of them
  is a solid primary block (that is kept for a view's one main action);
- a primary bar of up to four tabs shares its width equally.

tests/test_web_tabs.py checks the markup and that only ekte.css styles tabs.
"""

from __future__ import annotations

import pytest

from tests.a11y.harness import PAGES, assert_no_issues

LEVELS_JS = """() => {
  const tok = (name) => {
    const el = document.createElement("i");
    el.style.color = `var(${name})`;
    document.body.appendChild(el);
    const c = getComputedStyle(el).color;
    el.remove();
    return c;
  };
  const primary = tok("--primary"), surface = tok("--surface"), tint = tok("--primary-tint");
  const shown = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.closest("[hidden]"); };
  const name = (el) => (el.textContent || "").trim().slice(0, 24);
  const out = [];
  document.querySelectorAll('[role="tablist"]').forEach((bar) => {
    if (!shown(bar)) return;
    const sub = bar.classList.contains("sub");
    const tabs = [...bar.querySelectorAll('[role="tab"]')].filter(shown);
    tabs.forEach((t) => {
      if (t.getAttribute("aria-selected") !== "true") return;
      const cs = getComputedStyle(t);
      if (cs.backgroundColor === primary) out.push(`selected tab "${name(t)}" is a solid primary block`);
      if (!sub && cs.backgroundColor !== surface) out.push(`selected primary tab "${name(t)}" is not the surface pill (${cs.backgroundColor})`);
      if (sub && cs.borderBottomColor !== primary) out.push(`selected secondary tab "${name(t)}" is not underlined in primary`);
    });
    if (!sub && tabs.length && tabs.length <= 4) {
      const w = tabs.map((t) => t.getBoundingClientRect().width);
      if (Math.max(...w) - Math.min(...w) > 1.5) out.push(`primary bar of ${tabs.length} tabs has unequal widths: ${w.map(Math.round).join("/")}`);
    }
  });
  document.querySelectorAll('.seg button[aria-pressed="true"], .chips button[aria-pressed="true"], .seg.radio input:checked + label').forEach((el) => {
    if (!shown(el)) return;
    const bg = getComputedStyle(el).backgroundColor;
    if (bg === primary) out.push(`pressed control "${name(el)}" is a solid primary block`);
    else if (bg !== tint) out.push(`pressed control "${name(el)}" is not the primary tint (${bg})`);
  });
  return out;
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("page_id", list(PAGES))
def test_selection_has_one_look_per_level(open_page, page_id: str, scheme: str) -> None:
    page = open_page(PAGES[page_id], "en")
    page.emulate_media(color_scheme=scheme)
    issues = page.evaluate(LEVELS_JS)
    assert_no_issues(issues, f"{page_id} [{scheme}]", "tab-levels")
