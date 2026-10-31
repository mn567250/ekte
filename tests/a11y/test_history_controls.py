"""History's view controls: the collapsible filter panel (filterpanel.js,
shared with Analytics), the sort buttons in the column header and the
per-group collapse toggles (BITV 9.2.1.1, 9.4.1.2, 9.4.1.3, 9.2.4.3, 9.1.4.3,
9.1.4.10).

Each control is a native button that keeps focus where it was, says its state
in its name or aria-expanded, and hides what it collapses with ``hidden`` (out
of the tab order and the accessibility tree). The list is served to the page:
two relay groups of three runs each, with distinct times, scores and risks.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.a11y.filter_panel import filter_panel_issues
from tests.a11y.harness import (
    DESKTOP,
    THEMES,
    WCAG_TAGS,
    assert_no_issues,
    assert_no_violations,
    run_axe,
    settle,
)

# (model, minutes ago, score, rating, risk); newest first like /api/history
RUNS = [
    ("model-a", 10, 70, "C", "medium"),
    ("model-b", 20, 95, "A", "clean"),
    ("model-a", 30, 40, "F", "high"),
    ("model-b", 40, 85, "B", "low"),
    ("model-a", 50, 90, "A", "clean"),
    ("model-b", 60, 60, "D", "medium"),
]


def _history(open_page: Any, theme: str = "light", viewport: dict[str, int] | None = None, storage: str = "") -> Page:
    import httpx

    base = open_page.base_url
    resp = httpx.get(base + "/api/history?limit=500&perf=1", timeout=10)
    resp.raise_for_status()
    real = resp.json()
    assert real, "the a11y data dir should hold one saved run"
    now = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC)
    rows = [
        {**real[0], "id": 910000 + i, "claimed_model": m, "score": s, "rating": g, "risk_level": r,
         "ts": (now - dt.timedelta(minutes=ago)).isoformat()}
        for i, (m, ago, s, g, r) in enumerate(RUNS)
    ]
    ctx = open_page.browser.new_context(
        viewport=viewport or DESKTOP, color_scheme="dark" if theme == "dark" else "light"
    )
    open_page.contexts.append(ctx)
    ctx.add_init_script(
        "try { if (!sessionStorage.getItem('a11y.init')) { sessionStorage.setItem('a11y.init', '1');"
        " localStorage.clear(); localStorage.setItem('ekte.lang', 'en');"
        f" localStorage.setItem('ekte.v2.theme', {json.dumps(theme)}); {storage} }} }} catch (e) {{}}"
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


def _scores(page: Page) -> list[list[str]]:
    """Score cell text per group, in page order."""
    return page.evaluate(
        """() => [...document.querySelectorAll('#hist .group')].map(g =>
             [...g.querySelectorAll('.c-score')].map(c => c.lastChild.textContent))"""
    )


def _active(page: Page) -> str:
    return page.evaluate(
        "() => { const a = document.activeElement; return a ? (a.id || a.getAttribute('data-sort') || a.getAttribute('data-gkey') || a.tagName) : ''; }"
    )


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.4.1.3")
def test_filter_panel_disclosure(open_page) -> None:
    """Closed by default; Enter/Space open and close it in place, focus stays on
    the toggle; the toggle counts active filters and, closed, a line under it
    names them (also the toggle's description); the count and reset stay
    visible while it is closed; the state survives a reload. The same panel
    (filterpanel.js) is checked on Analytics in test_analytics_view.py."""
    page = _history(open_page)
    issues = filter_panel_issues(page, "[data-f=q]", ("[data-f=risk]", "high"), "Risk: ")
    assert_no_issues(issues, "history [en]", "filter-panel")


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.4.1.3", "9.1.3.2")
def test_sort_buttons(open_page) -> None:
    """Sort buttons reorder rows within their groups and the groups by their
    first row; focus stays on the button, its name says the order, a status
    message announces it and the choice survives a reload."""
    page = _history(open_page)
    issues: list[str] = []
    if _scores(page) != [["70", "40", "90"], ["95", "85", "60"]]:
        issues.append(f"default order is not newest first: {_scores(page)}")
    if page.locator("#hist .colhead").get_attribute("aria-hidden"):
        issues.append("the column header is still hidden from assistive technology")
    score = page.locator("[data-sort=score]")
    score.focus()
    page.keyboard.press("Enter")
    settle(page)
    if _scores(page) != [["95", "85", "60"], ["90", "70", "40"]]:
        issues.append(f"score descending: {_scores(page)}")
    if _active(page) != "score":
        issues.append(f"focus moved to {_active(page)!r}")
    if "descending" not in (score.get_attribute("aria-label") or ""):
        issues.append(f"button name does not say the order: {score.get_attribute('aria-label')!r}")
    status = page.evaluate("() => { const s = document.getElementById('sortst'); return [s.getAttribute('role'), s.textContent]; }")
    if status[0] != "status" or "Score" not in status[1] or "descending" not in status[1]:
        issues.append(f"sort is not announced: {status!r}")
    page.keyboard.press(" ")
    settle(page)
    if _scores(page) != [["40", "70", "90"], ["60", "85", "95"]]:
        issues.append(f"score ascending: {_scores(page)}")
    page.locator("[data-sort=risk]").click()
    settle(page)
    if _scores(page) != [["40", "70", "90"], ["60", "85", "95"]]:
        issues.append(f"risk descending (most severe first): {_scores(page)}")
    if page.locator("[data-sort=score]").get_attribute("data-dir"):
        issues.append("the previous sort button still shows a direction")
    page.reload(wait_until="networkidle")
    settle(page)
    if "descending" not in (page.locator("[data-sort=risk]").get_attribute("aria-label") or ""):
        issues.append("sort is not remembered across a reload")
    assert_no_issues(issues, "history [en]", "sort")


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.2.4.3")
def test_group_collapse(open_page) -> None:
    """The group heading's button collapses its rows in place (heading and
    trend stay), focus stays; an open report closes with it; Collapse all /
    Expand all work; the state survives a reload."""
    page = _history(open_page)
    issues: list[str] = []
    tog = page.locator(".gtog").first
    if page.evaluate("() => document.querySelector('.gtog').parentElement.tagName") != "H2":
        issues.append("group toggle is not inside the group heading")
    page.locator(".rmain").first.click()
    settle(page)
    tog.focus()
    page.keyboard.press("Enter")
    settle(page)
    body = page.locator(".gbody").first
    if tog.get_attribute("aria-expanded") != "false" or body.is_visible():
        issues.append("Enter did not collapse the group")
    if not page.locator(".group").first.locator(".trend").is_visible():
        issues.append("collapsing hid the group's trend")
    if page.evaluate("() => document.activeElement && document.activeElement.classList.contains('gtog')") is not True:
        issues.append("focus left the group toggle")
    if page.locator(".panel:not([hidden])").count():
        issues.append("the open report stayed open in the collapsed group")
    if page.locator(".gbody").nth(1).is_hidden():
        issues.append("collapsing one group collapsed another")
    page.reload(wait_until="networkidle")
    settle(page)
    if page.locator(".gtog").first.get_attribute("aria-expanded") != "false":
        issues.append("collapsed group is not remembered across a reload")
    gall = page.locator("#gall")
    gall.click()
    settle(page)
    if page.locator(".gtog[aria-expanded=true]").count():
        issues.append("Collapse all left a group open")
    if "Expand all" not in gall.inner_text():
        issues.append(f"button does not switch to 'Expand all': {gall.inner_text()!r}")
    gall.click()
    settle(page)
    if page.locator(".gtog[aria-expanded=false]").count():
        issues.append("Expand all left a group closed")
    assert_no_issues(issues, "history [en]", "group-collapse")


@pytest.mark.bitv("9.1.4.3", "9.4.1.2", axe=True)
@pytest.mark.parametrize("theme", THEMES)
def test_controls_wcag_rules(open_page, theme: str) -> None:
    """axe on the page with the filter panel open, a sort applied and a group
    collapsed."""
    page = _history(open_page, theme)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"history controls [en, {theme}]")
    page.locator("#ftog").click()
    page.locator("[data-sort=score]").click()
    page.locator(".gtog").first.click()
    settle(page)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"history controls changed [en, {theme}]")


@pytest.mark.bitv("9.1.4.10")
def test_controls_reflow_at_320_css_px(open_page) -> None:
    """At 320 CSS px the sort buttons, group toggles and filter toggle fit and
    nothing scrolls sideways."""
    page = _history(open_page, viewport={"width": 320, "height": 640})
    page.locator("#ftog").click()
    settle(page)
    issues: list[str] = []
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if over > 0:
        issues.append(f"page scrolls sideways by {over}px")
    for sel in ["[data-sort=time]", "[data-sort=grade]", "#gall", ".gtog >> nth=0", "#ftog"]:
        box = page.locator(sel).bounding_box()
        if not box or box["x"] < 0 or box["x"] + box["width"] > 320:
            issues.append(f"{sel} does not fit the viewport: {box}")
    assert_no_issues(issues, "history [en, 320px]", "reflow")
