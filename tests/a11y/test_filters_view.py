"""The shared filter component (ekte/web/static/v2/filters.js) in a browser
(#125): the URL query string holds the view, "Copy link to this view" gives a
link that reproduces it in a fresh browser (empty storage), the last filters
are the fallback for a URL without filter keys, every field is labelled and
changes are announced (BITV 9.1.3.1, 9.4.1.2, 9.4.1.3, 9.3.2.4); and the
monitors' "Open in history" link uses the shared keys.

History and Analytics move onto the component in #126 / #127; until then it
runs on a test page served at FIXTURE_PATH (routed, never the server's) with
the scripts and styles of the real server, and /api/filters/options stubbed
with its documented shape.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from playwright.sync_api import BrowserContext, Page, Route

from tests.a11y.harness import (
    assert_no_issues,
    assert_no_violations,
    run_axe,
    settle,
    track_network,
)

FIXTURE_PATH = "/__filters-fixture"
FIELDS = ["q", "range", "surface", "relay", "model", "suite", "mode", "api", "stream", "detect", "risk",
          "min_score", "exec", "group"]
OPTIONS = {
    "relay": [{"value": "example", "label": "Example Relay", "runs": 9},
              {"value": "http://127.0.0.1:9099/v1", "label": "http://127.0.0.1:9099/v1", "runs": 3},
              {"value": "-", "runs": 1}],
    "model": [{"value": "gpt-4o", "runs": 10}, {"value": "claude-3", "runs": 3}],
    "suite": [{"value": "standard", "runs": 12}, {"value": "-", "runs": 1}],
    "mode": [{"value": "check", "runs": 13}],
    "api": [{"value": "openai", "runs": 13}],
}

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ekte — filters</title>
<script src="/locales.js"></script><script src="/lang.js"></script><script src="/static/theme.js"></script>
<link rel="stylesheet" href="/static/tokens.css" /><link rel="stylesheet" href="/static/ekte.css" />
<link rel="stylesheet" href="/static/filterpanel.css" />
</head><body><main id="main"><h1>Filters</h1>
<p class="sr-only" id="live" role="status"></p>
<section class="card filters" id="filters" hidden></section>
</main>
<script src="/i18n.js"></script><script src="/icons.js"></script>
<script src="/static/filterpanel.js"></script><script src="/static/filters.js"></script>
<script>
  window.__changes = [];
  window.__f = EkteFilters.create({
    section: document.getElementById("filters"), page: "fixture",
    fields: %(fields)s, defaults: { range: "30d", "trend.metric": "score", tab: "overview" },
    foot: '<span id="fcount">Showing all runs</span>',
    onChange: function (s, changed) { window.__changes.push({ changed: changed, trend: EkteFilters.widgetParams("trend") }); },
  });
</script></body></html>
"""


def _context(open_page: Any, clipboard: bool = False) -> BrowserContext:
    base = open_page.base_url
    ctx = open_page.browser.new_context(viewport={"width": 1280, "height": 900})
    open_page.contexts.append(ctx)
    track_network(ctx)
    if clipboard:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    ctx.add_init_script("try { localStorage.setItem('ekte.lang', 'en'); localStorage.setItem('ekte.v2.theme', 'light'); } catch (e) {}")
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    page_html = _PAGE % {"fields": json.dumps(FIELDS)}
    ctx.route(f"{base}{FIXTURE_PATH}*", lambda route: route.fulfill(status=200, content_type="text/html", body=page_html))
    ctx.options_calls = []  # type: ignore[attr-defined]

    def options(route: Route) -> None:
        ctx.options_calls.append(route.request.url.removeprefix(base))  # type: ignore[attr-defined]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(OPTIONS))

    ctx.route(f"{base}/api/filters/options*", options)
    return ctx


def _open(ctx: BrowserContext, base: str, query: str = "") -> Page:
    page = ctx.new_page()
    page.goto(base + FIXTURE_PATH + query, wait_until="load")
    settle(page)
    return page


def _query(page: Page) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(page.url).query, keep_blank_values=True)


def _open_panel(page: Page) -> None:
    if page.locator("#ftog").get_attribute("aria-expanded") != "true":
        page.locator("#ftog").click()
        settle(page)


@pytest.mark.bitv("9.1.3.1", "9.4.1.2", "9.3.2.4")
def test_fields_are_labelled_and_the_panel_passes_axe(open_page) -> None:
    ctx = _context(open_page)
    page = _open(ctx, open_page.base_url)
    _open_panel(page)
    issues: list[str] = []
    if page.locator("#filters").get_attribute("aria-label") != "Filters":
        issues.append("the section is not named Filters")
    unnamed = page.evaluate("""() => [...document.querySelectorAll('#fbody input, #fbody select')]
      .filter((el) => !(el.labels && el.labels.length && el.labels[0].textContent.trim())).map((el) => el.outerHTML)""")
    if unnamed:
        issues.append(f"fields without a label: {unnamed}")
    legends = page.locator("#fbody fieldset legend").all_text_contents()
    if legends != ["Relay / provider", "Claimed model"]:
        issues.append(f"the relay / model groups are not named by their legend: {legends}")
    # the options endpoint was asked with the shared filters, and its values are offered
    if ctx.options_calls != ["/api/filters/options?range=30d&group=relay"]:  # type: ignore[attr-defined]
        issues.append(f"options requested as {ctx.options_calls}")  # type: ignore[attr-defined]
    if "Example Relay (9)" not in page.locator("#fbody fieldset").first.inner_text():
        issues.append("the relay options from /api/filters/options are not shown")
    if not page.locator("#fshare").is_visible():
        issues.append("no 'Copy link to this view' button")
    assert_no_issues(issues, "filters fixture [en]", "filter-fields")
    assert_no_violations(run_axe(page, ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]), "filters fixture [en]")


@pytest.mark.bitv("9.4.1.3")
def test_changes_go_to_the_url_and_are_announced(open_page) -> None:
    ctx = _context(open_page)
    page = _open(ctx, open_page.base_url, "?tab=trends&trend.metric=latency_p50&days=7")
    _open_panel(page)
    issues: list[str] = []
    entries = page.evaluate("history.length")
    if _query(page) != [("tab", "trends"), ("trend.metric", "latency_p50")]:
        issues.append(f"on load the URL keeps an unknown key or loses a widget key: {page.url}")
    page.locator("[data-f=risk]").select_option("high")
    page.locator("#fbody input[data-m=relay][value=example]").check()
    page.locator("#fbody input[data-m=relay][value='-']").check()
    page.locator("[data-f=range]").select_option("")  # All time, over the 30d default
    page.locator("[data-f=q]").fill("gpt")
    page.wait_for_timeout(450)
    settle(page)
    want = [("q", "gpt"), ("range", ""), ("relay", "example"), ("relay", "-"), ("risk", "high"),
            ("tab", "trends"), ("trend.metric", "latency_p50")]
    if _query(page) != want:
        issues.append(f"the URL is {_query(page)}, not {want}")
    if page.evaluate("history.length") != entries:
        issues.append("a filter change added a history entry")
    last = page.evaluate("window.__changes[window.__changes.length - 1]")
    if last != {"changed": ["q"], "trend": "q=gpt&relay=example&relay=-&risk=high&group=relay&trend.metric=latency_p50"}:
        issues.append(f"the widget's parameters are {last}")
    live = page.locator("#live").inner_text()
    if live != "Filters updated: 4 active":
        issues.append(f"the change was not announced in the live region: {live!r}")
    if "4 active" not in page.locator("#ftog").inner_text():
        issues.append("the toggle does not count the active filters")
    # focus stays on the field that changed (the panel re-renders)
    page.locator("[data-f=range]").focus()  # as a person changing it
    page.locator("[data-f=range]").select_option("custom")
    settle(page)
    if not page.locator("[data-f=from]").is_visible() or page.evaluate("document.activeElement.dataset.f") != "range":
        issues.append("Custom range does not show the dates, or focus left the period field")
    page.locator("[data-f=from]").fill("2026-01-01")
    page.locator("[data-f=to]").fill("2026-01-31")  # inclusive on screen, exclusive in the URL
    page.locator("[data-f=to]").dispatch_event("change")
    settle(page)
    q = dict(_query(page))
    if (q.get("from"), q.get("to"), q.get("range")) != ("2026-01-01", "2026-02-01", ""):
        issues.append(f"the custom range is from={q.get('from')} to={q.get('to')} range={q.get('range')!r}")
    page.locator("#freset").click()
    settle(page)
    if _query(page) != [("tab", "trends"), ("trend.metric", "latency_p50")]:
        issues.append(f"Reset left filters in the URL: {_query(page)}")
    assert_no_issues(issues, "filters fixture [en]", "filter-url")


@pytest.mark.bitv("9.4.1.3")
def test_a_copied_link_reproduces_the_view_in_a_fresh_browser(open_page) -> None:
    base = open_page.base_url
    page = _open(_context(open_page, clipboard=True), base)
    _open_panel(page)
    page.locator("[data-f=surface]").select_option("embedding")
    page.locator("#fbody input[data-m=model][value='claude-3']").check()
    page.locator("[data-f=exec]").select_option("monitor")
    page.locator("[data-f=suite]").select_option("-")
    page.locator("[data-f=group]").select_option("model")
    page.locator("[data-f=min_score]").fill("60")
    page.wait_for_timeout(450)
    page.evaluate("window.__f.set({ 'trend.metric': 'error_rate' })")
    settle(page)
    page.locator("#fshare").click()
    settle(page)
    issues: list[str] = []
    link = page.evaluate("navigator.clipboard.readText()")
    if page.locator("#fsharest").inner_text() != "Link copied":
        issues.append(f"no 'Link copied' status: {page.locator('#fsharest').inner_text()!r}")
    if link != page.url.split("#")[0]:
        issues.append(f"the copied link {link} is not this view {page.url}")
    before = page.evaluate("EkteFilters.state()")
    summary = page.locator("#ftog").inner_text()
    # a fresh browser: a new context, empty storage
    fresh = _open(_context(open_page), base, "?" + urlsplit(link).query)
    if fresh.evaluate("EkteFilters.state()") != before:
        issues.append(f"the link opens {fresh.evaluate('EkteFilters.state()')}, not {before}")
    if fresh.locator("#ftog").get_attribute("aria-expanded") != "true":
        issues.append("a link that carries filters does not open the panel")
    if fresh.locator("#ftog").inner_text() != summary:
        issues.append("the link's panel does not count the same filters")
    for sel, value in (("[data-f=surface]", "embedding"), ("[data-f=exec]", "monitor"), ("[data-f=suite]", "-"),
                       ("[data-f=group]", "model"), ("[data-f=min_score]", "60")):
        if fresh.locator(sel).input_value() != value:
            issues.append(f"{sel} is {fresh.locator(sel).input_value()!r}, not {value!r}")
    if not fresh.locator("#fbody input[data-m=model][value='claude-3']").is_checked():
        issues.append("the model is not selected")
    assert_no_issues(issues, "filters fixture [en]", "filter-link")


def test_storage_is_only_a_fallback(open_page) -> None:
    base = open_page.base_url
    ctx = _context(open_page)
    page = _open(ctx, base)
    _open_panel(page)
    page.locator("[data-f=risk]").select_option("medium")
    settle(page)
    issues: list[str] = []
    # the same browser, a URL without filter keys: the last filters, shown in the URL
    again = _open(ctx, base, "?tab=runs")
    if _query(again) != [("risk", "medium"), ("tab", "runs")]:
        issues.append(f"the remembered filters were not applied to a bare URL: {again.url}")
    # a URL with a filter key: that alone
    linked = _open(ctx, base, "?api=openai")
    if _query(linked) != [("api", "openai")] or linked.locator("[data-f=risk]").input_value() != "":
        issues.append(f"remembered filters mixed into a link's: {linked.url}")
    # storage that throws: the page still works from the URL and the defaults
    broken = _context(open_page)
    broken.add_init_script("""Object.defineProperty(window, 'localStorage', { get() { throw new Error('denied'); } });""")
    p = _open(broken, base, "?relay=example")
    if p.evaluate("EkteFilters.widgetParams()") != "range=30d&relay=example&group=relay":
        issues.append(f"without storage the state is {p.evaluate('EkteFilters.state()')}")
    assert_no_issues(issues, "filters fixture [en]", "filter-storage")


def test_monitor_open_in_history_uses_the_shared_keys(open_page) -> None:
    """The monitor's links to History name its relay by the relay key (not the
    old base_url=) and open History filtered to its runs."""
    page = open_page("/watches")
    hrefs = page.evaluate("() => [...document.querySelectorAll('a[href^=\"/history?\"]')].map((a) => a.getAttribute('href'))")
    issues: list[str] = []
    if not hrefs:
        issues.append("no link to History on the monitors page")
    for href in hrefs:
        query = dict(parse_qsl(urlsplit(href).query))
        if set(query) - {"surface", "relay", "model", "suite"} or "relay" not in query:
            issues.append(f"{href}: not the shared keys")
    if hrefs:
        query = dict(parse_qsl(urlsplit(hrefs[0]).query))
        run = urlsplit(hrefs[0]).fragment
        page.goto(open_page.base_url + hrefs[0], wait_until="load")
        settle(page)
        checked = page.evaluate("() => [...document.querySelectorAll('input[data-m=relay]:checked')].map((b) => b.value)")
        if checked != [query["relay"]]:
            issues.append(f"History's relay filter is {checked!r}")
        if not page.locator("#" + run).count():
            issues.append(f"the monitor's run {run} is not in the filtered list")
    assert_no_issues(issues, "monitors -> history [en]", "monitor-link")
