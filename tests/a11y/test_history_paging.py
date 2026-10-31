"""History's paged groups: the "Show more" button (BITV 9.2.1.1, 9.2.4.3,
9.2.4.7, 9.4.1.3, 9.1.4.3, 9.1.4.10).

History renders the first rows of each relay group and appends the rest page by
page. The suite's shared data dir holds one run, so these tests serve a longer
list (copies of that run) to the page: the button must work with Enter and
Space, keep or move focus sensibly, announce what it added in a live region,
keep the focus ring and contrast in both themes and reflow at 320 CSS px.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.a11y.harness import (
    DESKTOP,
    THEMES,
    WCAG_TAGS,
    assert_no_issues,
    assert_no_violations,
    run_axe,
    settle,
)

ROWS = 45  # one group: pages of 20, 20 and 5
PAGE_SIZE = 20


def _paged_history(open_page: Any, theme: str = "light", viewport: dict[str, int] | None = None) -> Page:
    """/history with ROWS runs of one relay + model (newest first)."""
    import httpx

    base = open_page.base_url
    resp = httpx.get(base + "/api/history?limit=500&perf=1", timeout=10)
    resp.raise_for_status()
    real = resp.json()
    assert real, "the a11y data dir should hold one saved run"
    rows = [{**real[0], "id": 900000 + i, "score": 90 - i} for i in range(ROWS)]
    ctx = open_page.browser.new_context(
        viewport=viewport or DESKTOP, color_scheme="dark" if theme == "dark" else "light"
    )
    open_page.contexts.append(ctx)
    ctx.add_init_script(
        "try { localStorage.setItem('ekte.lang', 'en');"
        f" localStorage.setItem('ekte.v2.theme', {json.dumps(theme)}); }} catch (e) {{}}"
    )
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    ctx.route(
        lambda u: "/api/history?" in u,
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(rows)),
    )
    page = ctx.new_page()
    page.goto(base + "/history", wait_until="networkidle")
    settle(page)
    return page


def _rows(page: Page) -> int:
    return int(page.evaluate("() => document.querySelectorAll('#hist .row').length"))


@pytest.mark.bitv("9.2.1.1", "9.2.4.3", "9.4.1.3")
def test_show_more_by_keyboard(open_page) -> None:
    """Enter/Space append the next page in place, focus stays on the button
    while rows remain and then moves to the first added row; a status region
    says how many rows are shown; a re-render keeps the expansion."""
    page = _paged_history(open_page)
    issues: list[str] = []
    more = page.locator("[data-more]")
    if _rows(page) != PAGE_SIZE:
        issues.append(f"expected {PAGE_SIZE} rows at first, got {_rows(page)}")
    if more.count() != 1:
        assert_no_issues(issues + ["no Show more button"], "history [en]", "show-more")
    if "25" not in more.inner_text():
        issues.append(f"button does not say how many rows remain: {more.inner_text()!r}")
    if page.evaluate("() => document.querySelector('[data-more]').tagName") != "BUTTON":
        issues.append("Show more is not a native button")
    page.evaluate("() => { document.querySelector('#hist .row').__a11yMark = 1; }")

    more.focus()
    page.keyboard.press("Enter")
    settle(page)
    if _rows(page) != 2 * PAGE_SIZE:
        issues.append(f"Enter: expected {2 * PAGE_SIZE} rows, got {_rows(page)}")
    if not page.evaluate("() => !!document.activeElement.hasAttribute('data-more')"):
        issues.append("Enter: focus left the Show more button although rows remain")
    if not page.evaluate("() => document.querySelector('#hist .row').__a11yMark === 1"):
        issues.append("Show more rebuilt the list instead of appending rows")
    live = page.evaluate(
        "() => { const s = document.getElementById('hmore');"
        " return s ? [s.getAttribute('role'), s.textContent] : null; }"
    )
    if not live or live[0] != "status" or "40" not in live[1] or "45" not in live[1]:
        issues.append(f"no status message announces the added rows: {live!r}")

    page.keyboard.press(" ")
    settle(page)
    if _rows(page) != ROWS:
        issues.append(f"Space: expected {ROWS} rows, got {_rows(page)}")
    if more.count():
        issues.append("Show more stays after every row is shown")
    focused = page.evaluate("() => document.activeElement && document.activeElement.id")
    first_new = page.evaluate(f"() => document.querySelectorAll('#hist .row')[{2 * PAGE_SIZE}].querySelector('.rmain').id")
    if focused != first_new:
        issues.append(f"after the last page focus is on {focused!r}, expected the first added row {first_new!r}")

    # a re-render (language switch) keeps the group expanded and the focus
    page.evaluate("() => window.dispatchEvent(new Event('ekte:lang'))")
    settle(page)
    if _rows(page) != ROWS:
        issues.append(f"re-render collapsed the group to {_rows(page)} rows")
    if page.evaluate("() => document.activeElement && document.activeElement.id") != first_new:
        issues.append("re-render lost the focus")
    assert_no_issues(issues, "history [en]", "show-more")


@pytest.mark.bitv("9.2.4.7")
@pytest.mark.parametrize("theme", THEMES)
def test_show_more_focus_visible(open_page, theme: str) -> None:
    """The button shows a focus indicator in both themes."""
    page = _paged_history(open_page, theme)
    more = page.locator("[data-more]")
    more.scroll_into_view_if_needed()
    box = more.bounding_box()
    assert box
    clip = {"x": max(box["x"] - 6, 0), "y": max(box["y"] - 6, 0), "width": box["width"] + 12, "height": box["height"] + 12}
    page.mouse.move(0, 0)
    plain = page.screenshot(clip=clip, animations="disabled", caret="hide")
    page.keyboard.press("Tab")  # put the page in keyboard modality
    more.focus()
    focused = page.screenshot(clip=clip, animations="disabled", caret="hide")
    issues = [] if focused != plain else ["Show more has no visible focus indicator"]
    assert_no_issues(issues, f"history [en, {theme}]", "focus-visible")


@pytest.mark.bitv("9.1.4.3", "9.4.1.2", axe=True)
@pytest.mark.parametrize("theme", THEMES)
def test_paged_history_wcag_rules(open_page, theme: str) -> None:
    """axe (contrast, names, roles) on a paged list, before and after Show more."""
    page = _paged_history(open_page, theme)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"paged history [en, {theme}]")
    page.locator("[data-more]").click()
    settle(page)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"paged history after Show more [en, {theme}]")


@pytest.mark.bitv("9.1.4.10")
def test_paged_history_reflows_at_320_css_px(open_page) -> None:
    """At 320 CSS px (400 % of 1280) the button fits and nothing scrolls sideways."""
    page = _paged_history(open_page, viewport={"width": 320, "height": 640})
    issues: list[str] = []
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if over > 0:
        issues.append(f"page scrolls sideways by {over}px")
    box = page.locator("[data-more]").bounding_box()
    if not box or box["x"] < 0 or box["x"] + box["width"] > 320:
        issues.append(f"Show more does not fit the viewport: {box}")
    assert_no_issues(issues, "history [en, 320px]", "reflow")
