"""Analytics' view controls: the shared filter panel, the tabs that load only
the panels they show, and "Copy link to this view" with the view in the URL
fragment (BITV 9.2.1.1, 9.4.1.2, 9.4.1.3, 9.1.4.10).

The page runs against the a11y server's seeded history (seed.py): runs of two
relays and models over the last week, manual and by a monitor.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.a11y.filter_panel import filter_panel_issues
from tests.a11y.harness import assert_no_issues, settle, track_network

PATH = "/v2/analytics"


def _open(open_page: Any, fragment: str = "", init: str = "", clipboard: bool = False,
          viewport: dict[str, int] | None = None) -> tuple[Page, list[str]]:
    """The page in a fresh English context; returns it and the analytics API
    paths it requested (in order)."""
    base = open_page.base_url
    ctx = open_page.browser.new_context(viewport=viewport or {"width": 1280, "height": 900})
    open_page.contexts.append(ctx)
    track_network(ctx)
    if clipboard:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    ctx.add_init_script(
        "try { localStorage.setItem('zing.lang', 'en'); localStorage.setItem('zing.v2.theme', 'light'); } catch (e) {}" + init
    )
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    calls: list[str] = []
    ctx.on("request", lambda r: calls.append(r.url.removeprefix(base).split("?")[0]) if "/api/analytics/" in r.url else None)
    page = ctx.new_page()
    page.goto(base + PATH + fragment, wait_until="load")
    settle(page)
    return page, calls


def _tab(page: Page) -> str:
    return str(page.locator("[role=tab][aria-selected=true]").get_attribute("id"))


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.4.1.3")
def test_analytics_filter_panel_disclosure(open_page) -> None:
    """The filter panel History has (filterpanel.js), on Analytics; there the
    closed panel names the period, suite and probe mode as well."""
    page, _ = _open(open_page)
    issues = filter_panel_issues(page, "[data-range='7']", ("[data-f=source]", "monitor"), "Source: Monitor")
    assert_no_issues(issues, "analytics [en]", "filter-panel")


@pytest.mark.bitv("9.4.1.2")
def test_tabs_load_only_their_panels(open_page) -> None:
    """Only the shown tab's panels load; a filter change reloads the shown
    tab and leaves the others stale until shown; nothing is busy once loaded."""
    page, calls = _open(open_page)
    issues: list[str] = []
    if _tab(page) != "tab-overview":
        issues.append(f"the page does not open on Overview: {_tab(page)}")
    if sorted(set(calls)) != ["/api/analytics/leaderboard", "/api/analytics/options", "/api/analytics/summary"]:
        issues.append(f"Overview loaded more than its panels: {calls}")
    if page.locator("#panel-overview [aria-busy=true]").count():
        issues.append("an Overview panel is still marked busy after loading")
    calls.clear()
    page.locator("#tab-reliability").click()
    settle(page)
    if sorted(set(calls)) != ["/api/analytics/breakdown", "/api/analytics/errors"]:
        issues.append(f"Reliability loaded {calls}")
    calls.clear()
    page.locator("#ftog").click()
    page.locator("[data-f=source]").select_option("manual")
    settle(page)
    if sorted(set(calls)) != ["/api/analytics/breakdown", "/api/analytics/errors"]:
        issues.append(f"a filter change on Reliability loaded {calls}")
    if page.locator("#panel-reliability [aria-busy=true]").count():
        issues.append("a Reliability panel is still marked busy after loading")
    calls.clear()
    page.locator("#tab-overview").click()
    settle(page)
    if sorted(set(calls)) != ["/api/analytics/leaderboard", "/api/analytics/summary"]:
        issues.append(f"Overview did not reload with the new filter: {calls}")
    calls.clear()
    page.locator("#tab-reliability").click()
    settle(page)
    if calls:
        issues.append(f"showing a tab that is up to date loaded {calls} again")
    assert_no_issues(issues, "analytics [en]", "tabs")


def test_link_restores_tab_filters_and_view(open_page) -> None:
    """A link carries the tab, the filters and the panels' options; an older
    link without a tab opens Overview; the URL follows every change."""
    page, calls = _open(open_page, "#tab=reliability&range=90&source=monitor&eb=dow_hour&et=1")
    issues: list[str] = []
    if _tab(page) != "tab-reliability" or not page.locator("#panel-err").is_visible():
        issues.append(f"the link's tab is not shown: {_tab(page)}")
    if "/api/analytics/summary" in calls:
        issues.append("a link to Reliability loaded the Overview panels")
    summary = page.locator("#fsum").inner_text()
    if "Last 90 days" not in summary or "Source: Monitor" not in summary:
        issues.append(f"the closed filter panel does not name the link's filters: {summary!r}")
    if page.locator("[data-v=eb]").input_value() != "dow_hour":
        issues.append("the errors panel does not use the link's weekday x hour buckets")
    if page.locator("#ettog").get_attribute("aria-expanded") != "true":
        issues.append("the errors table the link opened is closed")
    if "hmap" not in (page.locator("#err-chart svg[role=img]").get_attribute("class") or "").split():
        issues.append("weekday x hour errors are not drawn as a grid")
    page.locator("#tab-billing").click()
    settle(page)
    if "tab=billing" not in page.url or "source=monitor" not in page.url:
        issues.append(f"the URL does not follow the tab: {page.url}")
    old, _ = _open(open_page, "#range=7&metric=ttft_p50")
    if _tab(old) != "tab-overview" or "range=7" not in old.url:
        issues.append(f"a link without a tab does not open Overview with its filters: {_tab(old)} {old.url}")
    assert_no_issues(issues, "analytics [en]", "share-link")


@pytest.mark.bitv("9.4.1.3")
def test_copy_link_announces_it(open_page) -> None:
    """"Copy link to this view" puts the view's URL on the clipboard and says
    so in a status message."""
    page, _ = _open(open_page, "#tab=integrity&range=7", clipboard=True)
    issues: list[str] = []
    page.locator("#sharebtn").click()
    settle(page)
    st = page.locator("#sharest")
    if st.get_attribute("role") != "status" or st.inner_text() != "Link copied":
        issues.append(f"no 'Link copied' status: {st.get_attribute('role')!r} {st.inner_text()!r}")
    url = page.evaluate("navigator.clipboard.readText()")
    if not url.startswith(open_page.base_url + PATH + "#tab=integrity&range=7"):
        issues.append(f"the clipboard holds {url!r}")
    if page.locator("#sharefb").is_visible():
        issues.append("the fallback field shows although copying worked")
    assert_no_issues(issues, "analytics [en]", "share-link")


@pytest.mark.bitv("9.2.1.1", "9.4.1.3")
def test_copy_link_falls_back_to_a_selected_field(open_page) -> None:
    """Without a clipboard API the link shows in a labelled read-only field
    that gets focus with the text selected, and a status says to copy it."""
    page, _ = _open(open_page, "#tab=billing", init=" try { Object.defineProperty(navigator, 'clipboard', { value: undefined }); } catch (e) {}")
    issues: list[str] = []
    page.locator("#sharebtn").click()
    settle(page)
    field = page.locator("#shareurl")
    if not field.is_visible() or field.get_attribute("readonly") is None:
        issues.append("no read-only link field")
    state = page.evaluate(
        "() => { const e = document.activeElement; return { id: e.id, all: e.selectionStart === 0 && e.selectionEnd === e.value.length,"
        " name: e.labels && e.labels[0] ? e.labels[0].textContent.trim() : '' }; }"
    )
    if state["id"] != "shareurl" or not state["all"]:
        issues.append(f"the field is not focused with the link selected: {json.dumps(state)}")
    if state["name"] != "Link to this view":
        issues.append(f"the field's label: {state['name']!r}")
    if "#tab=billing" not in field.input_value():
        issues.append(f"the field holds {field.input_value()!r}")
    if "copy the link" not in page.locator("#sharest").inner_text():
        issues.append(f"no status pointing to the field: {page.locator('#sharest').inner_text()!r}")
    page.locator("#tab-trends").click()
    settle(page)
    if "#tab=trends" not in field.input_value():
        issues.append("the field does not follow the view")
    assert_no_issues(issues, "analytics [en]", "share-link")


@pytest.mark.bitv("9.1.4.10")
def test_view_controls_reflow_at_320_css_px(open_page) -> None:
    """At 320 CSS px, with long filters in the closed panel's summary, the
    tabs, the summary and Copy link fit; nothing scrolls sideways on any tab."""
    relay = "https%3A%2F%2Fgateway.a-very-long-relay-hostname.example.org%2Fopenai%2Fcompatible%2Fv1"
    page, _ = _open(open_page, f"#range=90&source=monitor&relay={relay}&model=model-a", viewport={"width": 320, "height": 640})
    issues: list[str] = []
    for tab in ("overview", "trends", "reliability", "integrity", "billing"):
        page.locator(f"#tab-{tab}").click()
        settle(page)
        over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if over > 0:
            issues.append(f"{tab}: the page scrolls sideways by {over}px")
    for sel in ("#fsum", "#sharebtn", "#ftog", "#tab-integrity"):
        box = page.locator(sel).bounding_box()
        if not box or box["x"] < 0 or box["x"] + box["width"] > 320:
            issues.append(f"{sel} does not fit the viewport: {box}")
    assert_no_issues(issues, "analytics [en, 320px]", "reflow")
