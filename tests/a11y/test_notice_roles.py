"""The page notice's role follows its importance (notice.js, #193; BITV
9.4.1.3 / WCAG 4.1.3 Status Messages): on every page with a notice, a
critical one (here: the page's status API answers 500) is role="alert", so
it is announced at once, and an informational one is role="status",
announced politely. Either way it is announced once: a repaint of the same
notice (as on every poll or a language event) changes nothing in it.
History's new-runs notice (no role: #live says it) is tested in
test_live_refresh.py.

Uses the shared session server; it only reads.
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, Route

from tests.a11y.harness import DESKTOP, assert_no_issues, settle, track_network
from tests.a11y.pages import PAGES

# each page with a notice -> the API whose failure makes the notice critical
FAILS: dict[str, str] = {
    "audit": "**/api/history/status*",
    "history": "**/api/history/status*",
    "analytics": "**/api/history/status*",
    "kb": "**/api/kb/profiles*",
    "monitors": "**/api/secret*",
}

# every change of the notice element (its text, children or attributes)
WATCH = (
    "document.addEventListener('DOMContentLoaded', function () {"
    " var el = document.getElementById('note'); window.__noteChanges = 0;"
    " if (el) new MutationObserver(function () { window.__noteChanges++; })"
    " .observe(el, { childList: true, subtree: true, characterData: true, attributes: true }); });"
)


def _open(open_page: Any, page_id: str, fail: bool) -> Page:
    base = open_page.base_url
    ctx = open_page.browser.new_context(viewport=DESKTOP)
    open_page.contexts.append(ctx)
    track_network(ctx)
    ctx.add_init_script("try { localStorage.setItem('ekte.lang', 'en'); } catch (e) {}" + WATCH)
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    if fail:
        def answer_500(route: Route) -> None:
            route.fulfill(status=500, content_type="application/json", body='{"error": "test"}')

        ctx.route(FAILS[page_id], answer_500)  # the later route wins
    page = ctx.new_page()
    page.goto(base + PAGES[page_id], wait_until="load")
    settle(page)
    return page


def _note(page: Page) -> dict[str, Any]:
    return page.evaluate("""() => { const el = document.getElementById('note');
      return { hidden: el.hidden, cls: el.className, role: el.getAttribute('role'),
               text: el.textContent }; }""")


def _repaint_changes(page: Page) -> int:
    """Changes to the notice when the page repaints it unchanged."""
    page.evaluate("() => { window.__noteChanges = 0; window.dispatchEvent(new Event('ekte:lang')); }")
    settle(page)
    return page.evaluate("() => window.__noteChanges")


@pytest.mark.bitv("9.4.1.3")
@pytest.mark.parametrize("page_id", list(FAILS))
def test_critical_notice_is_an_alert(open_page, page_id: str) -> None:
    page = _open(open_page, page_id, fail=True)
    page.wait_for_selector("#note.critical:not([hidden])")
    n = _note(page)
    issues: list[str] = []
    if n["role"] != "alert":
        issues.append(f"a critical notice is role={n['role']!r}, not alert: {n['text']!r}")
    if changes := _repaint_changes(page):
        issues.append(f"repainting the same critical notice changed it {changes} times (announced again)")
    assert_no_issues(issues, f"{page_id} [en]", "notice-role")


@pytest.mark.bitv("9.4.1.3")
@pytest.mark.parametrize("page_id", list(FAILS))
def test_other_notices_are_status(open_page, page_id: str) -> None:
    page = _open(open_page, page_id, fail=False)
    n = _note(page)
    issues: list[str] = []
    if n["hidden"]:
        pytest.skip(f"{page_id} shows no notice on the shared data")
    if "critical" in n["cls"].split():
        issues.append(f"the page shows a critical notice on the shared data: {n['text']!r}")
    elif n["role"] != "status":
        issues.append(f"a {n['cls']!r} notice is role={n['role']!r}, not status: {n['text']!r}")
    if changes := _repaint_changes(page):
        issues.append(f"repainting the same notice changed it {changes} times (announced again)")
    assert_no_issues(issues, f"{page_id} [en]", "notice-role")
