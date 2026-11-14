"""Remembered filters across pages (#154): by default the filters chosen on
History follow the viewer to Analytics through the navigation; with "Keep
filters across pages" turned off in the filter panel's foot, each page keeps
its own. The checkbox is named, keyboard-operable and never part of the URL
(BITV 9.4.1.2, 9.3.2.4).

Runs against the a11y server's seeded history (seed.py): runs of two relays.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from playwright.sync_api import Page

from tests.a11y.harness import assert_no_issues, settle, track_network

KEEP = "Keep filters across pages"


def _context(open_page: Any) -> Any:
    base = open_page.base_url
    ctx = open_page.browser.new_context(viewport={"width": 1280, "height": 900})
    open_page.contexts.append(ctx)
    track_network(ctx)
    ctx.add_init_script("try { localStorage.setItem('ekte.lang', 'en'); localStorage.setItem('ekte.v2.theme', 'light'); } catch (e) {}")
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    return ctx


def _open_panel(page: Page) -> None:
    if page.locator("#ftog").get_attribute("aria-expanded") != "true":
        page.locator("#ftog").click()
        settle(page)


def _nav(page: Page, href: str) -> None:
    page.locator(f'.znav a[href="{href}"]').first.click()
    page.wait_for_load_state("load")
    settle(page)


def _state(page: Page) -> dict[str, Any]:
    return dict(page.evaluate("EkteFilters.state()"))


def _query(page: Page) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(page.url).query, keep_blank_values=True)


@pytest.mark.bitv("9.4.1.2", "9.3.2.4")
def test_filters_follow_the_navigation_unless_kept_per_page(open_page) -> None:
    base = open_page.base_url
    page = _context(open_page).new_page()
    page.goto(base + "/history", wait_until="load")
    settle(page)
    issues: list[str] = []

    _open_panel(page)
    keep = page.get_by_role("checkbox", name=KEEP)
    if keep.count() != 1 or not keep.is_checked():
        issues.append("History: no checked 'Keep filters across pages' checkbox in the filter panel")
    relays = page.locator("input[data-m=relay]")
    values = [str(relays.nth(i).get_attribute("value")) for i in range(relays.count())]
    values = [v for v in values if v != "-"]
    assert len(values) >= 2, f"the seeded history should offer two relays, got {values}"
    first, second = values[0], values[1]
    page.locator(f'input[data-m=relay][value="{first}"]').check()
    settle(page)

    # shared (default): Analytics, opened from the nav, applies History's relay
    _nav(page, "/analytics")
    if _state(page).get("relay") != [first]:
        issues.append(f"shared mode: Analytics did not take History's relay: {_state(page).get('relay')}")
    if ("relay", first) not in _query(page):
        issues.append(f"shared mode: the remembered relay is not written into the URL: {page.url}")

    # per page: turned off on Analytics with the keyboard, the view stays
    _open_panel(page)
    keep = page.get_by_role("checkbox", name=KEEP)
    keep.focus()
    page.keyboard.press(" ")
    settle(page)
    if keep.is_checked():
        issues.append("Space did not turn 'Keep filters across pages' off")
    if _state(page).get("relay") != [first]:
        issues.append("turning the toggle off changed the current view")
    if any(k in ("scope", "keep") for k, _ in _query(page)):
        issues.append(f"the preference leaked into the URL: {page.url}")
    page.locator("[data-f=stream]").select_option("stream")
    settle(page)

    # History changes its relay; Analytics keeps its own filters
    _nav(page, "/history")
    _open_panel(page)
    if page.get_by_role("checkbox", name=KEEP).is_checked():
        issues.append("the per-page preference is not the same on History")
    page.locator(f'input[data-m=relay][value="{first}"]').uncheck()
    page.locator(f'input[data-m=relay][value="{second}"]').check()
    settle(page)
    _nav(page, "/analytics")
    st = _state(page)
    if st.get("relay") != [first] or st.get("stream") != "stream":
        issues.append(f"per-page mode: Analytics did not keep its own filters: relay={st.get('relay')} stream={st.get('stream')}")

    # back on: the current view becomes the shared memory, unchanged
    _open_panel(page)
    page.get_by_role("checkbox", name=KEEP).check()
    settle(page)
    if _state(page).get("relay") != [first]:
        issues.append("turning the toggle on changed the current view")
    _nav(page, "/history")
    if _state(page).get("relay") != [first]:
        issues.append(f"turning sharing on did not share Analytics' relay with History: {_state(page).get('relay')}")
    assert_no_issues(issues, "history / analytics [en]", "filter-memory")
