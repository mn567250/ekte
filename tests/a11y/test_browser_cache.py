"""The browser's HTTP cache holds every component's answer (#153).

History and Analytics load their components through ``EkteFilters.fetchWidget``,
a plain ``fetch`` on the server's ``ETag`` + ``Cache-Control: no-cache``.
Reloading a page with unchanged data must therefore send a conditional request
for every component, and the server must answer each one with ``304``: counted
here by a hook in the test server (an ASGI wrapper around the real app), since
the page itself sees a 304 as a 200 with the stored body.

No ``context.route()`` here: Playwright's request interception turns the
browser's HTTP cache off. A fixed absolute range keeps the cache keys the same
between loads (a relative range resolves "now").
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page

from tests.a11y.harness import DESKTOP, _free_port, settle, track_network

# the component endpoints of the two pages (all cached with an ETag)
COMPONENTS = ("/api/history/", "/api/analytics/", "/api/filters/", "/api/metrics")
RANGE = "range=&from=2020-01-01T00:00:00Z&to=2100-01-01T00:00:00Z"


class _Log:
    """The status of every component GET the server answered."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.entries: list[tuple[str, int, bool]] = []  # (path?query, status, conditional)

    def take(self) -> list[tuple[str, int, bool]]:
        with self.lock:
            out, self.entries = self.entries, []
        return out


def _recording(app: Any, log: _Log) -> Any:
    async def wrapped(scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") != "GET" or not path.startswith(COMPONENTS):
            await app(scope, receive, send)
            return
        query = scope.get("query_string", b"").decode()
        conditional = any(k.lower() == b"if-none-match" for k, _ in scope.get("headers", []))

        async def sending(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                with log.lock:
                    log.entries.append((path + ("?" + query if query else ""), message["status"], conditional))
            await send(message)

        await app(scope, receive, sending)

    return wrapped


@pytest.fixture(scope="module")
def cache_server(base_url: str) -> Iterator[tuple[str, _Log]]:
    """A second server over the session server's data (base_url seeds it),
    with the request log."""
    import httpx
    import uvicorn

    from ekte.web.server import create_app

    log = _Log()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(_recording(create_app(), log), host="127.0.0.1", port=port,
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
    yield url, log
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def context(browser: Any) -> Iterator[BrowserContext]:
    ctx = browser.new_context(viewport=DESKTOP)
    track_network(ctx)
    ctx.add_init_script("try { localStorage.setItem('ekte.lang', 'en'); } catch (e) {}")
    yield ctx
    ctx.close()


def _assert_all_revalidated(first: list[tuple[str, int, bool]], again: list[tuple[str, int, bool]]) -> None:
    assert first, "the page requested no component"
    assert {u for u, _, _ in again} == {u for u, _, _ in first}, "the reload asked for other components"
    fresh = [(u, s, c) for u, s, c in again if s != 304 or not c]
    assert not fresh, f"not answered 304 from a conditional request: {fresh}"


def _open_report(page: Page) -> str:
    """Open the first run's report on History; its id."""
    button = page.locator(".row .rmain").first
    rid = str(button.get_attribute("id")).removeprefix("r-")
    button.click()
    page.locator(f"#p-{rid} .state.loading").wait_for(state="detached")
    settle(page)
    return rid


def test_history_reload_revalidates_every_component(cache_server: tuple[str, _Log],
                                                     context: BrowserContext) -> None:
    url, log = cache_server
    page = context.new_page()
    page.goto(f"{url}/history?{RANGE}", wait_until="load")
    settle(page)
    rid = _open_report(page)  # puts runs.focus into the URL
    # the view as it now stands, loaded once (so every answer is stored) ...
    log.take()
    page.goto(page.url, wait_until="load")
    settle(page)
    assert _open_report(page) == rid
    first = log.take()
    paths = {u.split("?")[0] for u, _, _ in first}
    assert {"/api/history/status", "/api/history/groups", "/api/history/runs",
            f"/api/history/{rid}"} <= paths, paths
    # ... and reloaded: the status, the groups, the runs, the filter options
    # and the report detail (?trend=1) are all revalidated
    page.reload(wait_until="load")
    settle(page)
    assert _open_report(page) == rid
    _assert_all_revalidated(first, log.take())


def test_analytics_reload_revalidates_every_component(cache_server: tuple[str, _Log],
                                                       context: BrowserContext) -> None:
    url, log = cache_server
    page = context.new_page()
    page.goto(f"{url}/analytics?{RANGE}", wait_until="load")
    settle(page)
    first = log.take()
    paths = {u.split("?")[0] for u, _, _ in first}
    assert {"/api/history/status", "/api/analytics/summary"} <= paths, paths
    page.reload(wait_until="load")
    settle(page)
    _assert_all_revalidated(first, log.take())
    # and from another page: the browser's copy survives the change of page
    page.goto(f"{url}/history?{RANGE}", wait_until="load")
    settle(page)
    log.take()
    page.goto(f"{url}/analytics?{RANGE}", wait_until="load")
    settle(page)
    _assert_all_revalidated(first, log.take())
