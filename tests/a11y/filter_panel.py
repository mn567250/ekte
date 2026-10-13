"""The collapsible filter panel (zing/web/static/v2/filterpanel.js), checked
the same way on every page that has it: History (test_history_controls.py)
and Analytics (test_analytics_view.py)."""

from __future__ import annotations

from playwright.sync_api import Page

from tests.a11y.harness import settle


def _active(page: Page) -> str:
    return str(page.evaluate("() => { const a = document.activeElement; return a ? (a.id || a.tagName) : ''; }"))


def filter_panel_issues(page: Page, field: str, flt: tuple[str, str], named: str) -> list[str]:
    """Closed by default; Enter/Space open and close it in place, focus stays
    on the toggle; the toggle counts active filters and, closed, a line under
    it names them (``named``; also the toggle's description); the page's note
    and Reset stay visible while it is closed; Reset with the panel closed
    leaves focus on the toggle; the open state survives a reload.

    ``field`` is a field inside the panel, ``flt`` a (select, value) that sets
    one filter."""
    fsel, fval = flt
    issues: list[str] = []
    tog = page.locator("#ftog")
    if tog.get_attribute("aria-expanded") != "false" or page.locator("#fbody").is_visible():
        issues.append("filter panel is not closed by default")
    if tog.get_attribute("aria-controls") != "fbody":
        issues.append("toggle does not name the panel it controls")
    if not page.locator("#fcount").is_visible():
        issues.append("the 'Showing X of N' count is hidden with the panel")
    tog.focus()
    page.keyboard.press("Enter")
    settle(page)
    if tog.get_attribute("aria-expanded") != "true" or not page.locator(field).is_visible():
        issues.append("Enter did not open the panel")
    if _active(page) != "ftog":
        issues.append(f"focus moved to {_active(page)!r} instead of staying on the toggle")
    if page.locator("#fsum").is_visible():
        issues.append("the filter summary shows while the panel is open")
    page.locator(fsel).select_option(fval)
    settle(page)
    name = tog.inner_text()
    if "1 active" not in name:
        issues.append(f"toggle does not count the active filter: {name!r}")
    tog.focus()
    page.keyboard.press(" ")
    settle(page)
    if tog.get_attribute("aria-expanded") != "false" or page.locator("#fbody").is_visible():
        issues.append("Space did not close the panel")
    if not page.locator("#freset").is_visible():
        issues.append("Reset filters is hidden with the panel while a filter is active")
    fsum = page.locator("#fsum")
    if not fsum.is_visible() or named not in fsum.inner_text():
        issues.append(f"the closed panel does not name the active filter: {fsum.inner_text()!r}")
    if tog.get_attribute("aria-describedby") != "fsum":
        issues.append("the closed panel's toggle is not described by the filter summary")
    page.locator("#freset").click()
    settle(page)
    if _active(page) != "ftog":
        issues.append(f"reset with the panel closed left focus on {_active(page)!r}")
    if page.locator("#factive").is_visible():
        issues.append("active-filter badge stays after reset")
    tog.click()
    page.reload(wait_until="networkidle")
    settle(page)
    if page.locator("#ftog").get_attribute("aria-expanded") != "true":
        issues.append("open state is not remembered across a reload")
    return issues
