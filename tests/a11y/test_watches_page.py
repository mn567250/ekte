"""The Monitors page in the shared pattern (#160): the shared filter panel
with the filters in the URL query string, the list from the server
(``GET /api/watches?<filters>``), live progress from the job event streams
(no polling), and the links between Monitors, History and Analytics.

- Choosing a relay writes it to the URL and to the ``/api/watches`` request,
  the list shows only that relay's monitors, and a reload keeps the filter.
- A running monitor's progress comes from ``/api/jobs/monitor-<id>/events``;
  ``/api/watches`` is fetched when a run starts and ends, not on a timer.
- Every link opens its target with the right filters; "From run #n" finds a
  run 40 days old (History widens its range, #157).
- Shared filter memory: a relay set on History is the Monitors page's and
  back; ``state`` / ``alerting`` stay on the Monitors page.

Each test group has a server and data directory of its own (ekte_proc.py,
seed.py ``seed_monitors_page``): monitors in the shared session data would
change other pages' tests.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.a11y.ekte_proc import EkteProc
from tests.a11y.fake_relay import MODEL, FakeRelay
from tests.a11y.harness import DESKTOP, settle, track_network

# the change signal's poll interval (10 s) plus the time a refresh takes
WITHIN_MS = 15000


@pytest.fixture(scope="module")
def monitors_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[EkteProc]:
    with EkteProc(tmp_path_factory.mktemp("ekte-monitors"), seed="seed_monitors_page") as z:
        yield z


def _context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(viewport=DESKTOP)
    track_network(ctx)
    ctx.add_init_script(
        "try { if (!localStorage.getItem('a11y.init')) {"
        " localStorage.clear(); localStorage.setItem('a11y.init', '1'); localStorage.setItem('ekte.lang', 'en'); } } catch (e) {}")
    return ctx


def _open(ctx: BrowserContext, url: str) -> Page:
    page = ctx.new_page()
    page.goto(url, wait_until="load")
    settle(page)
    return page


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def _rows(base: str) -> dict[str, dict[str, Any]]:
    return {w["name"]: w for w in httpx.get(base + "/api/watches", timeout=10).json()}


def _names(page: Page) -> list[str]:
    return sorted(page.locator(".mon .mon-name").all_inner_texts())


def _open_panel(page: Page) -> None:
    if page.locator("#ftog").get_attribute("aria-expanded") != "true":
        page.locator("#ftog").click()


# --------------------------------------------------------------------------- #
# filters in the URL, filtered on the server
# --------------------------------------------------------------------------- #
def test_relay_filter_is_in_the_url_and_the_request(browser: Browser, monitors_server: EkteProc) -> None:
    base = monitors_server.url
    beta = _rows(base)["Beta"]
    ctx = _context(browser)
    requests: list[str] = []
    ctx.on("request", lambda r: requests.append(r.url) if urlsplit(r.url).path == "/api/watches" else None)
    try:
        page = _open(ctx, base + "/watches")
        assert _names(page) == ["Alpha", "Beta", "Gamma"]
        _open_panel(page)
        requests.clear()
        page.locator(f'input[data-m=relay][value="{beta["relay_key"]}"]').check()
        page.wait_for_function("() => document.querySelectorAll('.mon').length === 1")
        settle(page)
        assert _query(page.url).get("relay") == [beta["relay_key"]]
        assert requests and _query(requests[-1]).get("relay") == [beta["relay_key"]], requests
        assert "tz" in _query(requests[-1])  # every widget request carries the viewer's zone
        assert _names(page) == ["Beta"]
        assert "1 monitor matches these filters." in page.locator("#fcount").inner_text()
        # the options count monitors
        label = page.locator(f'input[data-m=relay][value="{beta["relay_key"]}"] + span').inner_text()
        assert label.endswith("(1)"), label
        page.reload(wait_until="load")
        settle(page)
        assert _names(page) == ["Beta"]
        assert _query(page.url).get("relay") == [beta["relay_key"]]
        # state / alerting: the server's values
        page.goto(base + "/watches?state=draft", wait_until="load")
        settle(page)
        assert _names(page) == ["Alpha"]
        page.goto(base + "/watches?alerting=yes", wait_until="load")
        settle(page)
        assert _names(page) == ["Beta"]
    finally:
        ctx.close()


def test_empty_states_tell_no_match_from_none(browser: Browser, monitors_server: EkteProc) -> None:
    ctx = _context(browser)
    try:
        page = _open(ctx, monitors_server.url + "/watches?state=paused&alerting=yes&q=gamma")
        empty = page.locator("#list .nomatch")
        assert "No monitors match these filters." in empty.inner_text()
        page.get_by_role("button", name="Clear filters").click()
        page.wait_for_function("() => document.querySelectorAll('.mon').length === 3")
        assert _query(page.url) == {}
    finally:
        ctx.close()


def test_deep_link_to_a_filtered_out_monitor_shows_it(browser: Browser, monitors_server: EkteProc) -> None:
    gamma = _rows(monitors_server.url)["Gamma"]
    ctx = _context(browser)
    try:
        page = _open(ctx, monitors_server.url + f"/watches?state=draft#w-{gamma['id']}")
        page.locator(f"#w-{gamma['id']}").wait_for()
        # cleared for this view only: nothing remembered
        assert page.evaluate("() => localStorage.getItem('ekte.v2.filters.watches')") in (None, "")
    finally:
        ctx.close()


# --------------------------------------------------------------------------- #
# links to and from the Monitors page
# --------------------------------------------------------------------------- #
def test_monitor_links_open_their_targets(browser: Browser, monitors_server: EkteProc) -> None:
    base = monitors_server.url
    rows = _rows(base)
    alpha, beta = rows["Alpha"], rows["Beta"]
    ctx = _context(browser)
    try:
        page = _open(ctx, base + "/watches")
        # accessible names: unique per card
        names = page.evaluate("() => [...document.querySelectorAll('.mon-last a')].map(a => a.getAttribute('aria-label'))")
        assert len(names) == len(set(names)), names
        # "From run #n": the run Alpha was made from, 40 days old
        src = page.locator(f"#w-{alpha['id']} a.ml-source")
        assert src.inner_text().startswith(f"From run #{alpha['source_report_id']}")
        href = src.get_attribute("href") or ""
        q = _query(href)
        assert q["runs.focus"] == [str(alpha["source_report_id"])] and q["relay"] == [alpha["relay_key"]]
        assert "watch" not in q  # the source run is not one of the monitor's runs
        page.goto(base + href, wait_until="load")
        settle(page)
        assert page.locator(f"#r-{alpha['source_report_id']}").is_visible(), "the 40-day-old run is not shown"
        assert "Range widened" in (page.locator("#note").text_content() or "")
        # "Open in History": the last run, among the monitor's own runs
        page.goto(base + "/watches", wait_until="load")
        settle(page)
        href = page.locator(f"#w-{beta['id']} a.ml-last").get_attribute("href") or ""
        q = _query(href)
        assert q["watch"] == [str(beta["id"])] and q["runs.focus"] == [str(beta["last_report_id"])]
        assert q["model"] == ["claude-x"] and q["relay"] == [beta["relay_key"]]
        page.goto(base + href, wait_until="load")
        settle(page)
        assert page.locator(f"#r-{beta['last_report_id']}").is_visible()
        st = page.evaluate("() => EkteFilters.state()")
        assert st["watch"] == str(beta["id"]) and st["relay"] == [beta["relay_key"]]
        # "Open in Analytics"
        page.goto(base + "/watches", wait_until="load")
        settle(page)
        href = page.locator(f"#w-{beta['id']} a.ml-analytics").get_attribute("href") or ""
        q = _query(href)
        assert q["exec"] == ["monitor"] and q["tab"] == ["overview"] and q["watch"] == [str(beta["id"])]
        page.goto(base + href, wait_until="load")
        settle(page)
        st = page.evaluate("() => EkteFilters.state()")
        assert (st["watch"], st["exec"], st["relay"], st["model"]) == (
            str(beta["id"]), "monitor", [beta["relay_key"]], ["claude-x"])
        # Analytics -> Monitors: offered once a relay or model is set
        mon = page.locator("#fmon a")
        mon.wait_for()
        assert mon.inner_text().startswith("Monitors for these filters")
        page.goto(base + (mon.get_attribute("href") or ""), wait_until="load")
        settle(page)
        assert _names(page) == ["Beta"]
        assert "watch" not in _query(page.url) and "exec" not in _query(page.url)
        page.goto(base + "/analytics?range=", wait_until="load")
        settle(page)
        assert page.locator("#fmon a").count() == 0
    finally:
        ctx.close()


def test_history_group_links_to_its_monitors(browser: Browser, monitors_server: EkteProc) -> None:
    base = monitors_server.url
    beta = _rows(base)["Beta"]
    ctx = _context(browser)
    try:
        page = _open(ctx, base + "/history?range=")
        links = page.locator('a.glink[href^="/watches"]')
        names = [links.nth(i).get_attribute("aria-label") for i in range(links.count())]
        assert names and len(names) == len(set(names)), names
        hit = page.locator('a.glink[href^="/watches"][href*="model=claude-x"]').first
        assert (hit.get_attribute("aria-label") or "").startswith("Monitors for this relay and model: ")
        href = hit.get_attribute("href") or ""
        q = _query(href)
        assert q["relay"] == [beta["relay_key"]] and q["model"] == ["claude-x"]
        assert not {"range", "watch", "exec", "state", "alerting"} & set(q)
        page.goto(base + href, wait_until="load")
        settle(page)
        assert _names(page) == ["Beta"]
    finally:
        ctx.close()


# --------------------------------------------------------------------------- #
# shared filter memory
# --------------------------------------------------------------------------- #
def test_shared_memory_carries_relay_not_state(browser: Browser, monitors_server: EkteProc) -> None:
    base = monitors_server.url
    rows = _rows(base)
    a, b = rows["Gamma"]["relay_key"], rows["Beta"]["relay_key"]
    ctx = _context(browser)
    try:
        hist = _open(ctx, base + "/history?range=")
        _open_panel(hist)
        hist.locator(f'input[data-m=relay][value="{b}"]').check()
        settle(hist)
        mon = _open(ctx, base + "/watches")
        assert mon.evaluate("() => EkteFilters.state().relay") == [b]
        assert _names(mon) == ["Beta"]
        _open_panel(mon)
        mon.locator(f'input[data-m=relay][value="{b}"]').uncheck()
        settle(mon)
        mon.locator(f'input[data-m=relay][value="{a}"]').check()
        settle(mon)
        mon.locator("select[data-f=state]").select_option("paused")
        settle(mon)
        assert _names(mon) == ["Gamma"]
        shared = json.loads(mon.evaluate("() => localStorage.getItem('ekte.v2.filters.shared')"))
        assert shared["relay"] == [a] and not {"state", "alerting"} & set(shared), shared
        again = _open(ctx, base + "/history")
        assert again.evaluate("() => EkteFilters.state().relay") == [a]
        assert not {"state", "alerting"} & set(_query(again.url))
        # the Monitors page keeps its own state
        back = _open(ctx, base + "/watches")
        assert back.evaluate("() => EkteFilters.state().state") == "paused"
    finally:
        ctx.close()


# --------------------------------------------------------------------------- #
# live progress from the job event stream
# --------------------------------------------------------------------------- #
PROGRESS_LOG_JS = """
() => {
  window.__a11yPct = [];
  const note = () => {
    const bar = document.querySelector('.mon-prog [role="progressbar"]');
    const v = bar && bar.getAttribute('aria-valuenow');
    if (v != null && window.__a11yPct[window.__a11yPct.length - 1] !== v) window.__a11yPct.push(v);
  };
  new MutationObserver(note).observe(document.getElementById('list'),
    { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-valuenow'] });
}
"""


@pytest.fixture
def relay() -> Iterator[FakeRelay]:
    # every POST held a moment: the run lasts long enough to watch it
    with FakeRelay(delay=1.0) as r:
        yield r


def test_running_monitor_follows_its_event_stream(browser: Browser, tmp_path: Path, relay: FakeRelay) -> None:
    with EkteProc(tmp_path / "data") as z:
        base = z.url
        with httpx.Client(base_url=base, headers={"Origin": base}, timeout=30) as c:
            r = c.post("/api/watches", json={"name": "Live", "base_url": relay.url, "api_key": "sk-test",
                                               "model": MODEL, "suite": "standard", "interval_sec": 3600,
                                               "enabled": False})
            assert r.status_code in (200, 201), r.text
            wid = r.json()["id"]
        ctx = _context(browser)
        lists: list[float] = []
        streams: list[str] = []

        def on_request(req: Any) -> None:
            path = urlsplit(req.url).path
            if path == "/api/watches":
                lists.append(1)
            elif path == f"/api/jobs/monitor-{wid}/events":
                streams.append(req.url)

        ctx.on("request", on_request)
        try:
            page = _open(ctx, base + "/watches")
            page.wait_for_function("() => window.EkteLive && window.EkteLive.tokens() !== null")
            page.evaluate(PROGRESS_LOG_JS)
            before = len(lists)
            # another client starts the run (as the scheduler would): the page learns it from the change signal
            done: dict[str, Any] = {}

            def run() -> None:
                with httpx.Client(base_url=base, headers={"Origin": base}, timeout=300) as c:
                    done["r"] = c.post(f"/api/watches/{wid}/run")

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            page.locator(".mon-prog").wait_for(timeout=WITHIN_MS)
            thread.join(timeout=240)
            assert done["r"].status_code == 200, done["r"].text
            page.wait_for_function("() => !document.querySelector('.mon-prog')", timeout=WITHIN_MS)
            page.locator(f"#w-{wid} a.ml-last").wait_for(timeout=WITHIN_MS)
            pct = page.evaluate("() => window.__a11yPct")
            assert streams, "no event stream was opened for the running monitor"
            assert len({int(p) for p in pct}) >= 3 and any(int(p) > 0 for p in pct), f"progress did not follow the stream: {pct}"
            # the list: once when the run started, once when it ended (and a
            # change signal between them at most), never on a timer
            assert len(lists) - before <= 3, f"/api/watches was requested {len(lists) - before} times during the run"
            # nothing after it ended either
            n = len(lists)
            page.wait_for_timeout(11000)
            assert len(lists) == n
            assert page.locator(f"#w-{wid}").get_by_text("Score").count() >= 1
        finally:
            ctx.close()
