"""History's view controls: the collapsible filter panel (filterpanel.js,
shared with Analytics), the sort buttons in the column header, the per-group
collapse toggles and the trend picker (BITV 9.2.1.1, 9.4.1.2, 9.4.1.3,
9.2.4.3, 9.1.4.3, 9.1.4.10).

Each control is a native button that keeps focus where it was, says its state
in its name, aria-pressed or aria-expanded, and hides what it collapses with
``hidden`` (out of the tab order and the accessibility tree). The page draws
what the server sends (history_views.py: a server of its own); these tests
pick two relay groups of three runs each, with distinct times, scores and
risks, by their models.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page

from tests.a11y.filter_panel import filter_panel_issues
from tests.a11y.harness import (
    THEMES,
    WCAG_TAGS,
    assert_no_issues,
    assert_no_violations,
    run_axe,
    settle,
)
from tests.a11y.history_views import open_history

# the two groups of seed.HISTORY_CONTROLS
TWO = "model=model-a&model=model-b"


def _history(open_page: Any, base: str, theme: str = "light", viewport: dict[str, int] | None = None,
             query: str = TWO) -> Page:
    return open_history(open_page, base, query, theme, viewport)


def _scores(page: Page) -> list[list[str]]:
    """Score cell text per group, in page order."""
    return page.evaluate(
        """() => [...document.querySelectorAll('#hist .group')].map(g =>
             [...g.querySelectorAll('.c-score')].map(c => c.lastChild.textContent))"""
    )


def _open_filters(page: Page) -> None:
    """Open the filter panel (a link with filters opens it already)."""
    if page.locator("#ftog").get_attribute("aria-expanded") != "true":
        page.locator("#ftog").click()
    settle(page)


def _active(page: Page) -> str:
    return page.evaluate(
        "() => { const a = document.activeElement; return a ? (a.id || a.getAttribute('data-sort') || a.getAttribute('data-gkey')"
        " || a.getAttribute('data-trend') || a.tagName) : ''; }"
    )


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.4.1.3")
def test_filter_panel_disclosure(open_page, history_server) -> None:
    """Closed by default; Enter/Space open and close it in place, focus stays on
    the toggle; the toggle counts active filters and, closed, a line under it
    names them (also the toggle's description); the count and reset stay
    visible while it is closed; the state survives a reload. The same panel
    (filterpanel.js) is checked on Analytics in test_analytics_view.py."""
    page = _history(open_page, history_server, query="")
    issues = filter_panel_issues(page, "[data-f=q]", ("[data-f=risk]", "high"), "Risk: ")
    assert_no_issues(issues, "history [en]", "filter-panel")


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.4.1.3", "9.1.3.2")
def test_sort_buttons(open_page, history_server) -> None:
    """Sort buttons reorder rows within their groups and the groups by their
    first row (on the server); focus stays on the button, its name says the
    order, a status message announces it and the choice survives a reload
    (it is in the URL)."""
    page = _history(open_page, history_server)
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
    if parse_qs(urlparse(page.url).query).get("groups.sort") != ["-risk"]:
        issues.append(f"the sort is not in the URL: {page.url}")
    page.reload(wait_until="networkidle")
    settle(page)
    if "descending" not in (page.locator("[data-sort=risk]").get_attribute("aria-label") or ""):
        issues.append("sort is not remembered across a reload")
    assert_no_issues(issues, "history [en]", "sort")


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.2.4.3")
def test_group_collapse(open_page, history_server) -> None:
    """The group heading's button collapses its rows in place (heading and
    trend stay), focus stays; an open report closes with it; Collapse all /
    Expand all work; the state survives a reload."""
    page = _history(open_page, history_server)
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
    # a group first opened here loads its rows
    if page.locator(".group").first.locator(".row").count() != 3:
        issues.append("the group opened after a reload shows no rows")
    assert_no_issues(issues, "history [en]", "group-collapse")


def _trend_buttons(page: Page) -> dict[str, list[Any]]:
    return dict(page.evaluate(
        "() => [...document.querySelectorAll('[data-trend]')].map(b =>"
        " [b.dataset.trend, [b.getAttribute('aria-pressed'), b.disabled, b.getAttribute('aria-disabled')]])"
    ))


def _tiles(page: Page) -> list[str]:
    return page.evaluate("() => [...document.querySelector('#hist .group .trend').querySelectorAll('.tr')].map(t => t.dataset.m)")


@pytest.mark.bitv("9.2.1.1", "9.4.1.2", "9.4.1.3", "9.1.3.1")
def test_trend_picker(open_page, history_server) -> None:
    """Six trend options in one labelled group; one or two are on. With two on,
    the other buttons are disabled (and aria-disabled) and "2 / 2" shows next
    to the label (the group's description says it in words); the last one on
    cannot be turned off. The choice is in the URL, the tiles follow it and
    focus stays on the button."""
    page = _history(open_page, history_server)
    _open_filters(page)
    issues: list[str] = []
    order = ["score", "grade", "latency_p50", "ttft_p50", "decode_tps", "error_rate"]
    btns = _trend_buttons(page)
    if list(btns) != order:
        issues.append(f"trend options: {list(btns)}")
    on = [k for k, (p, _, _) in btns.items() if p == "true"]
    if on != ["score", "latency_p50"]:
        issues.append(f"default trends: {on}")
    off = [k for k, (p, d, a) in btns.items() if p == "false" and not (d and a == "true")]
    if off:
        issues.append(f"with two on, these are not disabled (aria-disabled): {off}")
    group = page.locator(".tsel")
    if group.get_attribute("role") != "group" or not group.get_attribute("aria-labelledby"):
        issues.append("the trend buttons are not a labelled group")
    hint = page.locator("#tselN")
    if "2 / 2" not in hint.inner_text() or group.get_attribute("aria-describedby") != "tselN":
        issues.append(f"no '2 / 2' hint describing the group: {hint.inner_text()!r}")
    if _tiles(page) != ["score", "latency_p50"]:
        issues.append(f"tiles: {_tiles(page)}")

    lat = page.locator("[data-trend=latency_p50]")
    lat.focus()
    page.keyboard.press("Enter")  # off: one left
    settle(page)
    btns = _trend_buttons(page)
    if list(btns["score"][:2]) != ["true", True] or any(d for k, (_, d, _) in btns.items() if k != "score"):
        issues.append(f"with one on, only that one should be disabled: {btns}")
    if "1 / 2" not in hint.inner_text():
        issues.append(f"hint after turning one off: {hint.inner_text()!r}")
    if _active(page) != "latency_p50":
        issues.append(f"focus moved to {_active(page)!r}")
    page.locator("[data-trend=score]").dispatch_event("click")  # a disabled button does nothing
    settle(page)
    if _trend_buttons(page)["score"][0] != "true":
        issues.append("the last trend could be turned off")

    err = page.locator("[data-trend=error_rate]")
    err.focus()
    page.keyboard.press(" ")
    settle(page)
    if _tiles(page) != ["score", "error_rate"]:
        issues.append(f"tiles after choosing error rate: {_tiles(page)}")
    if parse_qs(urlparse(page.url).query).get("trend.metrics") != ["score,error_rate"]:
        issues.append(f"the trends are not in the URL: {page.url}")
    if _active(page) != "error_rate":
        issues.append(f"focus moved to {_active(page)!r}")
    if not _trend_buttons(page)["grade"][1]:
        issues.append("a third trend is not disabled")
    label = page.locator("#hist .group .tr[data-m=error_rate] svg").first.get_attribute("aria-label") or ""
    if label != "Error rate trend across 3 audits: from 0% to 25%, rising.":
        issues.append(f"error rate sparkline has no description: {label!r}")
    assert_no_issues(issues, "history [en]", "trend-picker")


@pytest.mark.bitv("9.4.1.2")
def test_copied_link_reproduces_the_view(open_page, history_server) -> None:
    """The link to this view (filters, sort, trends and the focused run) opens
    the same view in a fresh browser (no stored state)."""
    page = _history(open_page, history_server)
    page.locator("[data-sort=score]").click()
    settle(page)
    _open_filters(page)
    page.locator("[data-trend=latency_p50]").click()
    page.locator("[data-trend=grade]").click()
    settle(page)
    page.locator(".group").nth(1).locator(".rmain").nth(2).click()  # model-b, score 60: the focus run
    settle(page)
    link = page.url  # what Copy link to this view copies (the query string is the view)
    rid = page.locator(".group").nth(1).locator(".row").nth(2).get_attribute("data-id")
    query = urlparse(link).query
    fresh = _history(open_page, history_server, query=query)
    issues: list[str] = []
    if _scores(fresh) != _scores(page):
        issues.append(f"rows differ: {_scores(fresh)} vs {_scores(page)}")
    if _tiles(fresh) != ["score", "grade"]:
        issues.append(f"trends differ: {_tiles(fresh)}")
    if "descending" not in (fresh.locator("[data-sort=score]").get_attribute("aria-label") or ""):
        issues.append("sort differs")
    if parse_qs(query).get("runs.focus") != [rid] or not fresh.locator(f"#r-{rid}").is_visible():
        issues.append(f"the focused run {rid} is not shown: {query}")
    assert_no_issues(issues, "history [en]", "link")


@pytest.mark.bitv("9.2.4.4", "9.4.1.2")
def test_group_opens_in_analytics(open_page, history_server) -> None:
    """Each group's "Open in Analytics" link (a unique name: the group's model
    and relay) opens Analytics with that relay and model plus the History
    filters Analytics shows (surface, range); History-only keys (q) stay
    behind (#159)."""
    page = _history(open_page, history_server, query=TWO + "&surface=chat&range=7d&q=model-")
    issues: list[str] = []
    links = page.locator("#hist .group .glink")
    names = [links.nth(i).get_attribute("aria-label") or "" for i in range(links.count())]
    if len(names) != 2 or len(set(names)) != 2:
        issues.append(f"the group links are not two with unique names: {names}")
    groups = page.evaluate(
        "() => fetch('/api/history/groups?' + window.EkteFilters.widgetParams(['groups', 'trend'])).then(r => r.json())"
        ".then(d => d.groups.map(g => ({ relay: g.relay && g.relay.key, label: g.relay && g.relay.label, model: g.claimed_model })))"
    )
    first = groups[0]
    if not all(s in names[0] for s in ("Open in Analytics", first["model"], first["label"])):
        issues.append(f"the first link's name {names[0]!r} does not name {first}")
    seen: list[dict[str, list[str]]] = []
    page.context.on("request", lambda r: seen.append(parse_qs(urlparse(r.url).query, keep_blank_values=True))
                    if urlparse(r.url).path == "/api/analytics/summary" else None)
    want = {"relay": [first["relay"]], "model": [first["model"]], "surface": ["chat"], "range": ["7d"]}
    link = parse_qs(urlparse(links.first.get_attribute("href") or "").query, keep_blank_values=True)
    if link != {**want, "tab": ["overview"]}:
        issues.append(f"the link is {link}, not {want} + tab=overview")
    links.first.click()
    page.wait_for_url("**/analytics?**")
    settle(page)
    # Analytics leaves its default tab (overview) out of its own URL
    got = parse_qs(urlparse(page.url).query, keep_blank_values=True)
    if got != want:
        issues.append(f"the Analytics URL is {page.url}, not {want}")
    st = page.evaluate("() => window.EkteFilters.state()")
    if {k: [st[k]] if isinstance(st[k], str) else st[k] for k in want} != want or st.get("tab") != "overview":
        issues.append(f"Analytics did not apply the group's filters on the overview: {st}")
    if not seen or any({k: q.get(k) for k in want} != want for q in seen):
        issues.append(f"the summary was not asked with the group's filters: {seen}")
    assert_no_issues(issues, "history [en]", "analytics-link")


def _groups_requests(open_page: Any, base: str, query: str) -> tuple[Page, list[dict[str, list[str]]]]:
    """History opened at ``query`` in a viewer zone of its own, and the query
    strings of its /api/history/groups requests."""
    from tests.a11y.harness import DESKTOP, track_network

    ctx = open_page.browser.new_context(viewport=DESKTOP, timezone_id="America/Los_Angeles")
    open_page.contexts.append(ctx)
    track_network(ctx)
    ctx.add_init_script("try { localStorage.clear(); localStorage.setItem('ekte.lang', 'en'); } catch (e) {}")
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    seen: list[dict[str, list[str]]] = []
    ctx.on("request", lambda r: seen.append(parse_qs(urlparse(r.url).query, keep_blank_values=True))
           if urlparse(r.url).path == "/api/history/groups" else None)
    page = ctx.new_page()
    page.goto(base + "/history" + ("?" + query if query else ""), wait_until="networkidle")
    settle(page)
    return page, seen


def test_history_defaults_to_the_last_30_days(open_page, history_server) -> None:
    """Without a range in the URL History asks for range=30d (the schema's
    default) in the viewer's zone and keeps the URL clean; range= (All time)
    asks for no range (#152)."""
    issues: list[str] = []
    page, seen = _groups_requests(open_page, history_server, "")
    if not seen or any(q.get("range") != ["30d"] or q.get("tz") != ["America/Los_Angeles"] for q in seen):
        issues.append(f"default requests: {seen}")
    if "range" in parse_qs(urlparse(page.url).query) or "tz" in page.url:
        issues.append(f"the default or the zone was written to the URL: {page.url}")
    _open_filters(page)
    if page.locator("[data-f=range]").input_value() != "30d":
        issues.append("the period field does not show the last 30 days")
    last30 = page.locator("#fcount").inner_text()
    page, seen = _groups_requests(open_page, history_server, "range=")
    if not seen or any("range" in q or "from" in q for q in seen) or any(q.get("tz") != ["America/Los_Angeles"] for q in seen):
        issues.append(f"all-time requests: {seen}")
    if parse_qs(urlparse(page.url).query, keep_blank_values=True).get("range") != [""]:
        issues.append(f"All time is not kept as range= in the URL: {page.url}")
    _open_filters(page)
    if page.locator("[data-f=range]").input_value() != "":
        issues.append("the period field does not show All time")
    every = page.locator("#fcount").inner_text()
    # the fixture has runs older than 30 days (the bulk spans a year)
    if last30 == every:
        issues.append(f"the last 30 days count as many runs as all time: {last30!r}")
    assert_no_issues(issues, "history [en]", "default-range")



@pytest.mark.bitv("9.1.4.3", "9.4.1.2", axe=True)
@pytest.mark.parametrize("theme", THEMES)
def test_controls_wcag_rules(open_page, history_server, theme: str) -> None:
    """axe on the page with the filter panel open, a sort applied and a group
    collapsed."""
    page = _history(open_page, history_server, theme)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"history controls [en, {theme}]")
    _open_filters(page)
    page.locator("[data-sort=score]").click()
    settle(page)
    page.locator(".gtog").first.click()
    settle(page)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"history controls changed [en, {theme}]")


@pytest.mark.bitv("9.1.4.10")
def test_controls_reflow_at_320_css_px(open_page, history_server) -> None:
    """At 320 CSS px the sort buttons, group toggles, filter toggle and trend
    picker fit and nothing scrolls sideways."""
    page = _history(open_page, history_server, viewport={"width": 320, "height": 640})
    _open_filters(page)
    issues: list[str] = []
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if over > 0:
        issues.append(f"page scrolls sideways by {over}px")
    for sel in ["[data-sort=time]", "[data-sort=grade]", "#gall", ".gtog >> nth=0", "#ftog", "#tselN",
                "[data-trend=ttft_p50]"]:
        box = page.locator(sel).bounding_box()
        if not box or box["x"] < 0 or box["x"] + box["width"] > 320:
            issues.append(f"{sel} does not fit the viewport: {box}")
    assert_no_issues(issues, "history [en, 320px]", "reflow")
