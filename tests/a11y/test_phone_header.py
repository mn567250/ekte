"""The shared header on phones (issue 231), on every page, as drawn:

- at 390 px the header is two rows (logo, version, the display settings
  button and the accessibility link; then the section links) and the hero
  starts within the first 140 px;
- the display settings (theme, motion, language) open from one button in a
  popover: Tab reaches them right after the button, Escape closes it and
  returns the focus to the button; on desktop the switches sit in the row and
  the button is hidden;
- a row that scrolls sideways (the section links, a primary tab bar of five
  or more tabs) stays one row and fades at the edge that hides more;
- a primary tab bar is one row at every width.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.a11y.harness import PAGES, assert_no_issues

PHONE = {"width": 390, "height": 800}

LAYOUT_JS = """() => {
  const out = [], vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const nav = document.querySelector(".znav");
  const tops = new Set([...nav.querySelectorAll(":scope > :not(.skip-link), .tail > *, .zset-panel > *")].filter(vis)
    .map((e) => Math.round(e.getBoundingClientRect().top / 8)));
  const hero = document.querySelector(".hero h1, main h1");
  const scroll = [...document.querySelectorAll(".znav .links, .tabs:not(.sub)[role=tablist]")].filter(vis).map((row) => {
    const tabs = [...row.querySelectorAll("a, [role=tab]")].filter(vis);
    return { name: row.className, rows: new Set(tabs.map((t) => Math.round(t.getBoundingClientRect().top))).size,
             over: row.scrollWidth - row.clientWidth, fade: row.classList.contains("fl") || row.classList.contains("fr") };
  });
  return { header: Math.round(nav.getBoundingClientRect().bottom), rows: tops.size,
           hero: hero ? Math.round(hero.getBoundingClientRect().top) : null, scroll,
           selects: [...nav.querySelectorAll("select")].filter(vis).length, button: vis(nav.querySelector(".zset")) };
}"""


@pytest.mark.bitv("9.1.4.10")
@pytest.mark.parametrize("page_id", list(PAGES))
def test_phone_header_is_two_rows(open_page: Any, page_id: str) -> None:
    page = open_page(PAGES[page_id], "en", viewport=PHONE)
    got = page.evaluate(LAYOUT_JS)
    issues = []
    if got["rows"] > 2:
        issues.append(f"the header takes {got['rows']} rows")
    if got["hero"] is not None and got["hero"] > 140:
        issues.append(f"the hero starts at {got['hero']}px (> 140)")
    if got["selects"] or not got["button"]:
        issues.append("the display settings are not behind the settings button")
    for row in got["scroll"]:
        if row["rows"] > 1:
            issues.append(f"{row['name']}: {row['rows']} rows")
        if row["over"] > 1 and not row["fade"]:
            issues.append(f"{row['name']}: scrolls sideways without a fading edge")
    assert_no_issues(issues, f"{page_id} [en, 390px]", "phone-header")


@pytest.mark.parametrize("page_id", list(PAGES))
def test_desktop_tab_bars_are_one_row(open_page: Any, page_id: str) -> None:
    page = open_page(PAGES[page_id], "en")
    got = page.evaluate(LAYOUT_JS)
    issues = [f"{r['name']}: {r['rows']} rows" for r in got["scroll"] if r["rows"] > 1]
    if got["selects"] != 3 or got["button"]:
        issues.append(f"desktop: {got['selects']} switches in the row, settings button shown: {got['button']}")
    assert_no_issues(issues, f"{page_id} [en]", "header")


@pytest.mark.bitv("9.2.1.1", "9.2.4.3", "9.4.1.2")
def test_settings_popover_keyboard(open_page: Any) -> None:
    page = open_page(PAGES["analytics"], "en", viewport=PHONE)
    btn = page.locator(".znav .zset")
    issues: list[str] = []
    btn.focus()
    page.keyboard.press("Enter")
    if btn.get_attribute("aria-expanded") != "true" or not page.locator(".zset-panel select").first.is_visible():
        issues.append("Enter does not open the display settings")
    page.keyboard.press("Tab")
    if "theme-sel" not in (page.evaluate("() => document.activeElement.className") or ""):
        issues.append("Tab from the button does not reach the theme switch")
    page.keyboard.press("Escape")
    if btn.get_attribute("aria-expanded") != "false" or page.locator(".zset-panel select").first.is_visible():
        issues.append("Escape does not close the display settings")
    if "zset" not in (page.evaluate("() => document.activeElement.className") or ""):
        issues.append("Escape does not return the focus to the settings button")
    btn.click()
    page.locator("main").click(position={"x": 5, "y": 5})
    if btn.get_attribute("aria-expanded") != "false":
        issues.append("a click outside does not close the display settings")
    assert_no_issues(issues, "analytics [en, 390px]", "settings-popover")
