"""History's paging: the "Show more" buttons of a group's rows and of the
group list (BITV 9.2.1.1, 9.2.4.3, 9.2.4.7, 9.4.1.3, 9.1.4.3, 9.1.4.10), and
that every run is reachable (#127).

The server sends the first page of each group's rows (20) and of the groups
(20); "Show more" asks for the next page with the cursor and appends it. The
data is history_views.py's server: one group of 45 runs (``model=model-p``)
and 2,000 runs over 32 groups. The buttons must work with Enter and Space,
keep or move focus sensibly, announce what they added in a live region, keep
the focus ring and contrast in both themes and reflow at 320 CSS px.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from playwright.sync_api import Page

from tests.a11y.harness import (
    THEMES,
    WCAG_TAGS,
    assert_no_issues,
    assert_no_violations,
    run_axe,
    settle,
)
from tests.a11y.history_views import open_history

ROWS = 45  # one group: pages of 20, 20 and 5
PAGE_SIZE = 20
PAGED = "model=model-p"


def _paged_history(open_page: Any, base: str, theme: str = "light", viewport: dict[str, int] | None = None) -> Page:
    page = open_history(open_page, base, PAGED, theme, viewport)
    # a link with filters opens the filter panel; closed, the group is in view
    if page.locator("#ftog").get_attribute("aria-expanded") == "true":
        page.locator("#ftog").click()
        settle(page)
    return page


def _rows(page: Page) -> int:
    return int(page.evaluate("() => document.querySelectorAll('#hist .row').length"))


@pytest.mark.bitv("9.2.1.1", "9.2.4.3", "9.4.1.3")
def test_show_more_by_keyboard(open_page, history_server) -> None:
    """Enter/Space append the next page in place, focus stays on the button
    while rows remain and then moves to the first added row; a status region
    says how many rows are shown; a re-render keeps the expansion."""
    page = _paged_history(open_page, history_server)
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
    scores = page.evaluate("() => [...document.querySelectorAll('#hist .c-score')].map(c => c.lastChild.textContent)")
    if scores != [str(90 - i) for i in range(2 * PAGE_SIZE)]:
        issues.append(f"the pages are not in order, without gaps: {scores}")

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
    # the link to this view reaches as far (the last row shown is its focus run)
    fresh = open_history(open_page, history_server, page.url.split("?", 1)[1])
    if _rows(fresh) != ROWS:
        issues.append(f"the link to this view shows {_rows(fresh)} rows, not {ROWS}")
    assert_no_issues(issues, "history [en]", "show-more")


@pytest.mark.bitv("9.2.1.1", "9.2.4.3", "9.4.1.3")
def test_show_more_groups(open_page, history_server) -> None:
    """The group list is paged too: Show more groups appends the next page,
    focus then moves to the first added group's toggle, and a status message
    says how many groups are shown."""
    page = open_history(open_page, history_server)
    issues: list[str] = []
    data = httpx.get(history_server + "/api/history/groups?trend.metrics=score", timeout=10).json()
    total = data["total_groups"]
    if page.locator("#hist .group").count() != PAGE_SIZE or total <= PAGE_SIZE:
        issues.append(f"expected {PAGE_SIZE} of {total} groups at first, got {page.locator('#hist .group').count()}")
    more = page.locator("[data-gmore]")
    if str(total - PAGE_SIZE) not in more.inner_text():
        issues.append(f"button does not say how many groups remain: {more.inner_text()!r}")
    more.focus()
    page.keyboard.press("Enter")
    settle(page)
    shown = page.locator("#hist .group").count()
    if shown != min(total, 2 * PAGE_SIZE):
        issues.append(f"expected {min(total, 2 * PAGE_SIZE)} groups, got {shown}")
    if total <= 2 * PAGE_SIZE:
        if more.count():
            issues.append("Show more groups stays after every group is shown")
        active = page.evaluate("() => document.activeElement && document.activeElement.className")
        if "gtog" not in str(active):
            issues.append(f"focus is on {active!r}, not on the first added group")
    live = page.evaluate("() => { const s = document.getElementById('hmore'); return s ? s.textContent : null; }")
    if not live or f"{shown} of {total} groups" not in live:
        issues.append(f"no status message announces the added groups: {live!r}")
    assert_no_issues(issues, "history [en]", "show-more-groups")


def test_oldest_of_2000_runs_is_reachable(open_page, history_server) -> None:
    """With 2,000 runs, the oldest one is reached by filtering for its relay
    and model and paging with Show more, and directly by a link to it."""
    oldest_group = httpx.get(history_server + "/api/history/groups",
                             params={"trend.metrics": "score", "groups.sort": "time", "groups.limit": 1}, timeout=10).json()
    assert oldest_group["total_runs"] >= 2000
    g = oldest_group["groups"][0]
    oldest = httpx.get(history_server + "/api/history/runs",
                       params={"group.key": g["key"], "runs.sort": "time", "runs.limit": 1}, timeout=10).json()["rows"][0]
    rid = str(oldest["id"])
    issues: list[str] = []
    # all time (range=): the oldest run is older than the default range, the last 30 days (#152)
    page = open_history(open_page, history_server, f"range=&relay={g['relay']['key']}&model={g['claimed_model']}")
    if page.locator("#hist .group").count() != 1:
        issues.append(f"the filters leave {page.locator('#hist .group').count()} groups")
    clicks = 0
    while not page.locator(f"#r-{rid}").count() and page.locator("[data-more]").count() and clicks < 50:
        page.locator("[data-more]").click()
        settle(page)
        clicks += 1
    if not page.locator(f"#r-{rid}").count():
        issues.append(f"paging never reached the oldest run {rid} ({_rows(page)} rows)")
    if _rows(page) != g["runs"]:
        issues.append(f"{_rows(page)} rows shown of the group's {g['runs']}")
    # a link to it widens the default range to its day (#157)
    linked = open_history(open_page, history_server, f"runs.focus={rid}")
    if not linked.locator(f"#r-{rid}").is_visible():
        issues.append(f"a link to the oldest run {rid} does not show it")
    assert_no_issues(issues, "history [en]", "reach-oldest")


@pytest.mark.bitv("9.2.4.7")
@pytest.mark.parametrize("theme", THEMES)
def test_show_more_focus_visible(open_page, history_server, theme: str) -> None:
    """The button shows a focus indicator in both themes."""
    page = _paged_history(open_page, history_server, theme)
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
def test_paged_history_wcag_rules(open_page, history_server, theme: str) -> None:
    """axe (contrast, names, roles) on a paged list, before and after Show more."""
    page = _paged_history(open_page, history_server, theme)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"paged history [en, {theme}]")
    page.locator("[data-more]").click()
    settle(page)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"paged history after Show more [en, {theme}]")


@pytest.mark.bitv("9.1.4.10")
def test_paged_history_reflows_at_320_css_px(open_page, history_server) -> None:
    """At 320 CSS px (400 % of 1280) the button fits and nothing scrolls sideways."""
    page = _paged_history(open_page, history_server, viewport={"width": 320, "height": 640})
    issues: list[str] = []
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if over > 0:
        issues.append(f"page scrolls sideways by {over}px")
    box = page.locator("[data-more]").bounding_box()
    if not box or box["x"] < 0 or box["x"] + box["width"] > 320:
        issues.append(f"Show more does not fit the viewport: {box}")
    assert_no_issues(issues, "history [en, 320px]", "reflow")
