"""Analytics' view controls: the shared filter panel, the tabs that load only
the panels they show, and "Copy link to this view" with the view in the URL
fragment (BITV 9.2.1.1, 9.4.1.2, 9.4.1.3, 9.1.4.10).

The page runs against the a11y server's seeded history (seed.py): runs of two
relays and models over the last week, manual and by a monitor.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.a11y.filter_panel import filter_panel_issues
from tests.a11y.harness import assert_no_issues, settle, track_network

PATH = "/v2/analytics"


def _open(open_page: Any, fragment: str = "", init: str = "", clipboard: bool = False,
          viewport: dict[str, int] | None = None,
          route: tuple[str, Callable[..., Any]] | None = None) -> tuple[Page, list[str]]:
    """The page in a fresh English context; returns it and the analytics API
    paths it requested (in order). route: (glob, handler) for the context,
    e.g. to change an API answer."""
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
    if route:
        ctx.route(*route)  # the later route wins
    calls: list[str] = []
    ctx.on("request", lambda r: calls.append(r.url.removeprefix(base).split("?")[0]) if "/api/analytics/" in r.url else None)
    page = ctx.new_page()
    page.goto(base + PATH + fragment, wait_until="load")
    settle(page)
    return page, calls


def _tab(page: Page) -> str:
    return str(page.locator("#atabs [role=tab][aria-selected=true]").get_attribute("id"))


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.4.1.3")
def test_analytics_filter_panel_disclosure(open_page) -> None:
    """The filter panel History has (filterpanel.js), on Analytics; there the
    closed panel names the period, suite and probe mode as well."""
    page, _ = _open(open_page)
    issues = filter_panel_issues(page, "[data-range='7']", ("[data-f=source]", "monitor"), "Source: Monitor")
    assert_no_issues(issues, "analytics [en]", "filter-panel")


@pytest.mark.bitv("9.4.1.2")
def test_tabs_load_only_their_panels(open_page) -> None:
    """Only the shown tab's panels load (of a tab with sub-tabs, the shown
    sub-tab's); a filter change reloads the shown panels and leaves the others
    stale until shown; nothing is busy once loaded."""
    page, calls = _open(open_page)
    issues: list[str] = []
    if _tab(page) != "tab-overview":
        issues.append(f"the page does not open on Overview: {_tab(page)}")
    if sorted(set(calls)) != ["/api/analytics/options", "/api/analytics/summary"]:
        issues.append(f"Overview loaded more than its shown panel: {calls}")
    if page.locator("#panel-kpi[aria-busy=true]").count():
        issues.append("the Overview panel is still marked busy after loading")
    calls.clear()
    page.locator("#tab-lb").click()
    settle(page)
    if sorted(set(calls)) != ["/api/analytics/leaderboard"] or not page.locator("#panel-lb").is_visible():
        issues.append(f"the Leaderboard sub-tab loaded {calls}")
    if page.locator("#panel-kpi").is_visible() or "os=lb" not in page.url:
        issues.append(f"the Leaderboard sub-tab does not replace the Overview panel: {page.url}")
    page.locator("#tab-kpi").click()
    settle(page)
    calls.clear()
    page.locator("#tab-reliability").click()
    settle(page)
    if sorted(set(calls)) != ["/api/analytics/errors"]:
        issues.append(f"Reliability loaded {calls}")
    calls.clear()
    page.locator("#ftog").click()
    page.locator("[data-f=source]").select_option("manual")
    settle(page)
    if sorted(set(calls)) != ["/api/analytics/errors"]:
        issues.append(f"a filter change on Reliability loaded {calls}")
    if page.locator("#panel-reliability [aria-busy=true]").count():
        issues.append("a Reliability panel is still marked busy after loading")
    calls.clear()
    page.locator("#tab-overview").click()
    settle(page)
    if sorted(set(calls)) != ["/api/analytics/summary"]:
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
    sub, _ = _open(open_page, "#tab=trends&ts=heat&range=30")
    if not sub.locator("#panel-heat").is_visible() or sub.locator("#panel-cmp").is_visible():
        issues.append("a link to the Peak hours sub-tab does not show it")
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


def _tip_gap(page: Page, chart: str, mark: str, at: tuple[float, float]) -> tuple[float, dict[str, Any]]:
    """Moves the pointer onto a mark of a chart (at: where on it, as fractions
    of its box); returns the distance from the pointer to the shown tooltip's
    box (0: touching) and that box."""
    page.locator(f"{chart} {mark}").scroll_into_view_if_needed()
    box = page.locator(f"{chart} {mark}").bounding_box()
    assert box, f"no {mark} in {chart}"
    x, y = box["x"] + box["width"] * at[0], box["y"] + box["height"] * at[1]
    page.mouse.move(x, y)
    page.mouse.move(x + 1, y + 1)
    tip = page.locator(f"{chart} .ctip")
    t = tip.bounding_box() if tip.is_visible() else None
    if not t:
        return float("inf"), {}
    dx = max(t["x"] - x, 0, x - t["x"] - t["width"])
    dy = max(t["y"] - y, 0, y - t["y"] - t["height"])
    return max(dx, dy), t


def test_chart_tooltips_follow_the_pointer(open_page) -> None:
    """Every chart's tooltip shows next to the pointer, wherever on the chart
    it is (a cell at the bottom of the peak-hours grid, a bucket of the
    comparison chart), and stays inside the chart's box."""
    issues: list[str] = []
    page, _ = _open(open_page, "#tab=trends&ts=heat&range=90&hb=1")
    cells = page.locator("#heat-chart rect[data-k]")
    if not cells.count():
        issues.append("no peak-hours cells to hover")
    else:
        # the lowest cell (the day starts at the bottom): far from the grid's top
        k = page.evaluate(
            "() => [...document.querySelectorAll('#heat-chart rect[data-k]')]"
            ".sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0].getAttribute('data-k')"
        )
        gap, t = _tip_gap(page, "#heat-chart", f"rect[data-k='{k}']", (0.5, 0.5))
        if gap > 30:
            issues.append(f"peak hours: the tooltip is {gap:.0f}px from the pointer ({t})")
        host = page.locator("#heat-chart").bounding_box()
        if t and host and (t["x"] < host["x"] - 1 or t["x"] + t["width"] > host["x"] + host["width"] + 1):
            issues.append(f"peak hours: the tooltip leaves the chart's box: {t} {host}")
    page, _ = _open(open_page, "#tab=trends&range=90")
    gap, t = _tip_gap(page, "#cmp-chart", "rect.hit >> nth=-1", (0.5, 0.9))
    if gap > 30:
        issues.append(f"comparison: the tooltip is {gap:.0f}px from the pointer ({t})")
    assert_no_issues(issues, "analytics [en]", "chart-tooltip")


def test_changing_a_panel_option_keeps_the_scroll_position(open_page) -> None:
    """A panel's option reloads only that panel, and the page stays where it
    was scrolled to. While a chart is redrawn the page must not get shorter
    than the scrolled-to view: browsers without scroll anchoring (Safari)
    would clamp the scroll position and jump up to the panel's heading."""
    page, _ = _open(open_page, "#tab=trends&ts=heat&range=90&hb=1", viewport={"width": 1280, "height": 700})
    # the scroll position at the moment each chart is drawn: Chromium restores
    # a clamped one afterwards (scroll anchoring), Safari keeps it
    page.evaluate(
        "() => { window.__at = []; const C = window.ZingCharts, draw = C.heatmap;"
        " C.heatmap = function (host, cfg) { window.__at.push(scrollY); return draw(host, cfg); }; }"
    )
    issues: list[str] = []
    for metric in ("latency_p50", "decode_tps"):
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        settle(page)
        page.evaluate("window.__at = []")
        before = page.evaluate("scrollY")
        page.locator("[data-v=hm]").select_option(metric)
        settle(page)
        after, at = page.evaluate("[scrollY, window.__at]")
        if not at:
            issues.append(f"choosing {metric} did not redraw the grid")
        for y in at + [after]:
            if abs(y - before) > 2:
                issues.append(f"choosing {metric} moved the page from {before} to {y}")
                break
    assert_no_issues(issues, "analytics [en]", "scroll")


def _folded(route: Any) -> None:
    """The peak-hours answer as if the runs covered 120 days and the server
    had folded them into 4-week cycles (the seeded history spans one week)."""
    res = route.fetch()
    body = res.json()
    body.update(fold="4weeks", fold_requested="4weeks", span_days=120)
    for ser in body["series"]:
        points = []
        for week in range(1, 5):
            points += [{**p, "week": week, "bucket": f"{week}.{p['bucket']}"} for p in ser["points"]]
        ser["points"] = points
    route.fulfill(response=res, json=body)


@pytest.mark.bitv("9.4.1.2")
def test_peak_hours_aggregation(open_page) -> None:
    """The Aggregation option: the longer folds are offered once the runs cover
    enough days (disabled before, with the reason); a link asking for one too
    early shows the grid by weekday and says why, and keeps the wish in the
    URL; a 4-week fold draws the weekdays once per week of the cycle."""
    issues: list[str] = []
    page, _ = _open(open_page, "#tab=trends&ts=heat&range=90&ha=4weeks")
    sel = page.locator("[data-v=ha]")
    if sel.input_value() != "week":
        issues.append(f"one week of runs is not shown by weekday: {sel.input_value()!r}")
    for value, days in (("4weeks", 90), ("month_week", 180)):
        opt = sel.locator(f"option[value='{value}']")
        if not opt.evaluate("o => o.disabled") or f"(needs {days} days of runs)" not in opt.inner_text():
            issues.append(f"the {value} option is not disabled with its reason: {opt.inner_text()!r}")
    note = page.locator("#heat-body .notes").inner_text() if page.locator("#heat-body .notes").count() else ""
    if "needs runs spread over at least 90 days" not in note:
        issues.append(f"the fallback to weekdays is not explained: {note!r}")
    if "ha=4weeks" not in page.url:
        issues.append(f"the link's aggregation was dropped from the URL: {page.url}")

    page, _ = _open(open_page, "#tab=trends&ts=heat&range=90&hb=4&ha=4weeks",
                    route=("**/api/analytics/series?*fold=4weeks*", _folded))
    groups = page.locator("#heat-chart svg.hmap text.hg").all_text_contents()
    if groups != ["Week 1", "Week 2", "Week 3", "Week 4"]:
        issues.append(f"the 4-week grid does not label its weeks: {groups}")
    n = page.locator("#heat-chart svg.hmap .cells rect:not(.hatch)").count()
    if n != 4 * 7 * 6:
        issues.append(f"the 4-week grid of 4-hour blocks has {n} cells, not 168")
    if page.locator("[data-v=ha]").input_value() != "4weeks":
        issues.append("the Aggregation option does not show the 4-week fold")
    if "Weeks 1–4 repeat every 4 weeks" not in page.locator("#heat-body .notes").inner_text():
        issues.append("the 4-week grid does not say how its cycle is counted")
    head = page.locator("#heat-body table thead").inner_text()
    if "Week" not in head.split("\n")[0] and "Week" not in head:
        issues.append(f"the table has no week column: {head!r}")
    k = page.locator("#heat-chart rect[data-k^='3.']").first
    k.hover()
    tip = page.locator("#heat-chart .ctip .when").inner_text()
    if not tip.startswith("Week 3 · "):
        issues.append(f"a cell's tooltip does not name its week: {tip!r}")
    assert_no_issues(issues, "analytics [en]", "peak-hours-fold")
