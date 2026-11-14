"""Live refresh (#156): one poller per tab (static/v2/live.js) asks
``GET /api/version`` every 10 s while the tab is visible; History and
Analytics react to a changed ``data`` token.

- A run saved by another process (the store, as the CLI saves one) while the
  page is open: Analytics updates its KPIs within 15 s, in place (no reload,
  no motion, no announcement) and the focus stays where it was; History shows
  "1 new run" with a Show button, announced once through ``#live``, keeps its
  list until the button is pressed, and counts a second run in place.
- A hidden tab sends no ``/api/version`` request; it asks once on becoming
  visible again (counted by a hook in a test server).

The saving tests get a server and data directory of their own (ekte_proc.py),
so the shared session data stays as it is. The hidden-tab test only reads.
Headless Chromium keeps every tab visible, so an init script stands in for
``document.visibilityState`` and fires ``visibilitychange``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.a11y.ekte_proc import REPORT_FIXTURE, ROOT, EkteProc
from tests.a11y.harness import DESKTOP, _free_port, settle, track_network

# the poll interval (10 s) plus the time a refresh takes, with some room
WITHIN_MS = 15000

VISIBILITY_INIT = """
(() => {
  let hidden = false;
  Object.defineProperty(Document.prototype, 'visibilityState', { configurable: true, get() { return hidden ? 'hidden' : 'visible'; } });
  Object.defineProperty(Document.prototype, 'hidden', { configurable: true, get() { return hidden; } });
  window.__a11ySetHidden = (h) => { hidden = !!h; document.dispatchEvent(new Event('visibilitychange')); };
})();
"""

# every text the page's live region (#live) is given, in order
LIVE_LOG_JS = """
() => {
  const live = document.getElementById('live');
  window.__a11yLive = [];
  new MutationObserver(() => { const t = live.textContent.trim(); if (t) window.__a11yLive.push(t); })
    .observe(live, { childList: true, characterData: true, subtree: true });
}
"""


def _save_run(data_dir: Path) -> None:
    """Save one run into ``data_dir`` from another process (as the CLI does)."""
    code = ("import json, sys; from ekte.web import history; history.init();"
            " history.save(json.loads(open(sys.argv[1], encoding='utf-8').read()))")
    env = dict(os.environ, EKTE_DATA_DIR=str(data_dir), PYTHONPATH=str(ROOT))
    subprocess.run([sys.executable, "-c", code, str(REPORT_FIXTURE)], cwd=str(ROOT), env=env, check=True, timeout=60)


@pytest.fixture
def own_server(tmp_path: Path) -> Iterator[EkteProc]:
    """A server of its own over one saved run."""
    with EkteProc(tmp_path / "data") as z:
        yield z


def _context(browser: Browser, base: str) -> BrowserContext:
    ctx = browser.new_context(viewport=DESKTOP)
    track_network(ctx)
    ctx.add_init_script("try { localStorage.clear(); localStorage.setItem('ekte.lang', 'en'); } catch (e) {}")
    ctx.add_init_script(VISIBILITY_INIT)
    return ctx


def _open(ctx: BrowserContext, url: str) -> Page:
    page = ctx.new_page()
    page.goto(url, wait_until="load")
    settle(page)
    # the poller has its baseline (the first answer dispatches nothing)
    page.wait_for_function("() => window.EkteLive && window.EkteLive.tokens() !== null")
    page.evaluate(LIVE_LOG_JS)
    page.evaluate("() => { window.__a11yNoReload = true; }")
    return page


def test_analytics_updates_in_place_and_keeps_focus(browser: Browser, own_server: EkteProc) -> None:
    ctx = _context(browser, own_server.url)
    try:
        page = _open(ctx, own_server.url + "/analytics")
        runs = page.locator('#kpi-body [data-kv="runs"]')
        assert runs.inner_text().strip() == "1"
        # focus inside the panel that is redrawn: a tile's hint button (else the reset link)
        target = page.locator("#kpi-body .khint, #kpi-body button").first
        target.focus()
        at = page.evaluate("() => [...document.querySelectorAll('#kpi-body button')].indexOf(document.activeElement)")
        assert at >= 0
        # count the motion the refresh would start (chartmotion.js)
        page.evaluate("""() => {
          window.__a11yMotion = 0;
          const M = window.EkteMotion;
          if (M) ['count', 'enter'].forEach(k => { const f = M[k]; M[k] = function () { window.__a11yMotion++; return f.apply(this, arguments); }; });
          window.scrollTo(0, 120);
        }""")
        scroll = page.evaluate("() => window.scrollY")
        _save_run(own_server.data_dir)
        page.wait_for_function("() => document.querySelector('#kpi-body [data-kv=\"runs\"]').textContent.trim() === '2'",
                               timeout=WITHIN_MS)
        settle(page)
        state = page.evaluate("""() => ({
          reloaded: !window.__a11yNoReload,
          focus: [...document.querySelectorAll('#kpi-body button')].indexOf(document.activeElement),
          motion: window.__a11yMotion, live: window.__a11yLive, scroll: window.scrollY,
          busy: document.getElementById('panel-kpi').getAttribute('aria-busy'),
          noteLive: document.getElementById('note').getAttribute('aria-live'),
        })""")
        assert not state["reloaded"]
        assert state["focus"] == at, "focus left the control it was on"
        assert state["motion"] == 0, "the refresh restarted the motion"
        assert state["live"] == [], f"the refresh was announced: {state['live']}"
        assert state["scroll"] == scroll
        assert state["busy"] == "false"
        assert state["noteLive"] == "off"  # the page notice changed without an announcement
        assert "2" in page.locator("#fcount").inner_text()  # the filter count follows
    finally:
        ctx.close()


def test_history_shows_new_runs_notice_once(browser: Browser, own_server: EkteProc) -> None:
    ctx = _context(browser, own_server.url)
    try:
        page = _open(ctx, own_server.url + "/history")
        rows = page.locator("#hist .row")
        assert rows.count() == 1
        fresh = page.locator("#fresh")
        assert fresh.is_hidden()
        _save_run(own_server.data_dir)
        fresh.wait_for(state="visible", timeout=WITHIN_MS)
        assert fresh.locator("b").inner_text() == "1 new run"
        assert fresh.get_attribute("role") is None  # #live announces it, not the notice itself
        button = fresh.get_by_role("button", name="Show")
        assert button.is_visible()
        page.wait_for_function("() => window.__a11yLive.length > 0")
        assert page.evaluate("() => window.__a11yLive") == ["1 new run. Use the Show button above the list."]
        # the list never reloads by itself
        assert rows.count() == 1 and page.evaluate("() => window.__a11yNoReload")
        # a second run while the notice is shown: N in place, no new announcement
        _save_run(own_server.data_dir)
        page.wait_for_function("() => document.querySelector('#fresh b').textContent === '2 new runs'", timeout=WITHIN_MS)
        settle(page)
        assert page.evaluate("() => window.__a11yLive") == ["1 new run. Use the Show button above the list."]
        assert rows.count() == 1
        # Show: the list loads again, the notice goes, focus moves to the newest run
        button.focus()
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.querySelectorAll('#hist .row').length === 3")
        settle(page)
        assert fresh.is_hidden()
        assert page.evaluate("() => !!document.activeElement.closest('#hist .row')")
        assert page.evaluate("() => window.__a11yNoReload")
        # the page's own list is current: the next polls show no notice
        page.wait_for_timeout(11000)
        assert fresh.is_hidden()
    finally:
        ctx.close()


def test_history_filter_change_removes_the_notice(browser: Browser, own_server: EkteProc) -> None:
    ctx = _context(browser, own_server.url)
    try:
        page = _open(ctx, own_server.url + "/history")
        _save_run(own_server.data_dir)
        fresh = page.locator("#fresh")
        fresh.wait_for(state="visible", timeout=WITHIN_MS)
        # a filter change loads the list anyway: the notice goes
        if page.locator("#ftog").get_attribute("aria-expanded") != "true":
            page.locator("#ftog").click()
        page.locator("[data-f=range]").select_option("")  # all time
        page.wait_for_function("() => document.querySelectorAll('#hist .row').length === 2")
        settle(page)
        assert fresh.is_hidden()
        assert page.evaluate("() => window.__a11yNoReload")
    finally:
        ctx.close()


# --------------------------------------------------------------------------- #
# a hidden tab does not poll
# --------------------------------------------------------------------------- #
class _Count:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.n = 0

    def take(self) -> int:
        with self.lock:
            n, self.n = self.n, 0
        return n


def _counting(app: Any, count: _Count) -> Any:
    async def wrapped(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") == "/api/version":
            with count.lock:
                count.n += 1
        await app(scope, receive, send)

    return wrapped


@pytest.fixture(scope="module")
def version_server(base_url: str) -> Iterator[tuple[str, _Count]]:
    """A second server over the session server's data (only read here),
    counting the ``/api/version`` requests."""
    import httpx
    import uvicorn

    from ekte.web.server import create_app

    count = _Count()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(_counting(create_app(), count), host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            if httpx.get(url + "/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    else:  # pragma: no cover
        raise RuntimeError("ekte web server did not start")
    yield url, count
    server.should_exit = True
    thread.join(timeout=10)


@pytest.mark.parametrize("path", ["/analytics", "/history"])
def test_hidden_tab_sends_no_version_requests(browser: Browser, version_server: tuple[str, _Count], path: str) -> None:
    url, count = version_server
    ctx = _context(browser, url)
    try:
        page = _open(ctx, url + path)
        page.evaluate("() => window.__a11ySetHidden(true)")
        count.take()
        page.wait_for_timeout(25000)  # two and a half poll intervals
        assert count.take() == 0, "a hidden tab polled /api/version"
        page.evaluate("() => window.__a11ySetHidden(false)")
        page.wait_for_timeout(1500)
        assert count.take() == 1, "becoming visible asks once"
        page.wait_for_timeout(10000)
        assert count.take() == 1, "a visible tab asks every 10 s"
        assert json.loads(page.evaluate("() => JSON.stringify(window.__a11yLive)")) == []
    finally:
        ctx.close()
