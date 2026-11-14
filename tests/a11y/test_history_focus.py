"""A link to one run outside History's filters (#157): the server says the
run is outside them (``focus.outside``, ``by_range_only``, ``excluded_by``);
when only the range leaves it out, the page widens the range to the run's
day and says so once in the page notice (a status region, BITV 9.4.1.3);
otherwise the notice offers "Show it", which clears the filters that leave
it out, keeps the focus and moves keyboard focus to the run (9.2.4.3).

The data is history_views.py's server (2,000 runs over a year); its query
clock is ekte_proc.FIXED_TS, so the default range, the last 30 days, leaves
a run 40 days old out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from playwright.sync_api import Page

from tests.a11y.ekte_proc import FIXED_TS
from tests.a11y.harness import assert_no_issues, settle
from tests.a11y.history_views import open_history

NOW = datetime.fromtimestamp(FIXED_TS, UTC)
# every text the page notice shows, in order (a repeat of the same text is no change)
WATCH_NOTE = (
    "document.addEventListener('DOMContentLoaded', function () {"
    " var el = document.getElementById('note'); window.__notes = [];"
    " new MutationObserver(function () { var t = el.hidden ? '' : el.textContent;"
    "  if (window.__notes[window.__notes.length - 1] !== t) window.__notes.push(t); })"
    " .observe(el, { childList: true, subtree: true, characterData: true, attributes: true }); });"
)


def _runs(base: str, **params: str) -> list[dict]:
    """The newest runs (one page of the first group) under ``params``."""
    g = httpx.get(base + "/api/history/groups", params={"trend.metrics": "score", **params}, timeout=10).json()
    assert g["groups"], params
    return httpx.get(base + "/api/history/runs",
                     params={"group.key": g["groups"][0]["key"], "runs.limit": 50, **params}, timeout=10).json()["rows"]


def _query(page: Page) -> dict[str, list[str]]:
    return parse_qs(urlsplit(page.url).query, keep_blank_values=True)


def _announced(page: Page, text: str) -> int:
    """How often the page notice started to show ``text``."""
    return sum(1 for t in page.evaluate("() => window.__notes || []") if text in t)


@pytest.mark.bitv("9.4.1.3")
def test_link_to_an_old_run_widens_the_range(open_page, history_server) -> None:
    """runs.focus of a run 40 days old: the range becomes a custom range from
    the run's day, the run is shown and focused in the URL, and the notice
    "Range widened to show run #n" is announced once (not again on a repaint)."""
    old = _runs(history_server, **{"from": (NOW - timedelta(days=45)).isoformat(),
                                   "to": (NOW - timedelta(days=35)).isoformat()})[0]
    rid = str(old["id"])
    page = open_history(open_page, history_server, f"runs.focus={rid}", storage=WATCH_NOTE)
    issues: list[str] = []
    q = _query(page)
    if q.get("range") != [""] or not q.get("from") or "to" in q:
        issues.append(f"the range is not a custom range from the run's day: {q}")
    elif q["from"][0][:10] != datetime.fromisoformat(old["started_at"]).astimezone().date().isoformat():
        issues.append(f"from {q['from'][0]} is not the day of the run started {old['started_at']}")
    if q.get("runs.focus") != [rid]:
        issues.append(f"the focus is gone: {q}")
    if not page.locator(f"#r-{rid}").is_visible():
        issues.append(f"run {rid} is not shown")
    text = f"Range widened to show run #{rid}"
    note = page.locator("#note")
    if text not in (note.text_content() or "") or note.get_attribute("role") != "status":
        issues.append(f"no status notice {text!r}: {note.text_content()!r}")
    page.evaluate("() => window.dispatchEvent(new Event('ekte:lang'))")  # a repaint
    settle(page)
    if _announced(page, text) != 1:
        issues.append(f"the notice was announced {_announced(page, text)} times: {page.evaluate('() => window.__notes')}")
    if page.locator("#filters select[data-f=range]").input_value() != "custom":
        issues.append("the range select does not show the custom range")
    stored = page.evaluate("() => localStorage.getItem('ekte.v2.filters.history')")
    if stored and "from=" in stored:
        issues.append(f"the widened range is remembered as the viewer's filters: {stored!r}")
    assert_no_issues(issues, "history [en]", "focus-widened")


@pytest.mark.bitv("9.4.1.3", "9.2.4.3")
def test_run_outside_another_filter_shows_it(open_page, history_server) -> None:
    """runs.focus of a run another suite leaves out: the notice "Run #n
    doesn't match the current filters" with "Show it"; Enter on it clears
    suite, keeps the focus, shows the run and moves keyboard focus to it."""
    rows = _runs(history_server, range="30d")
    run = rows[0]
    other = next(r["suite"] for r in rows if r["suite"] and r["suite"] != run["suite"])
    rid = str(run["id"])
    page = open_history(open_page, history_server, f"suite={other}&runs.focus={rid}", storage=WATCH_NOTE)
    issues: list[str] = []
    text = f"Run #{rid} doesn't match the current filters"
    if text not in (page.locator("#note").text_content() or ""):
        issues.append(f"no notice {text!r}: {page.locator('#note').text_content()!r}")
    if page.locator(f"#r-{rid}").count():
        issues.append(f"run {rid} is shown under suite={other}")
    show = page.locator("#note [data-note-act=showfocus]")
    if show.count() != 1 or show.text_content() != "Show it":
        assert_no_issues(issues + ["no Show it button"], "history [en]", "focus-outside")
    show.focus()
    page.keyboard.press("Enter")
    settle(page)
    q = _query(page)
    if "suite" in q or q.get("runs.focus") != [rid]:
        issues.append(f"Show it did not clear suite and keep the focus: {q}")
    if not page.locator(f"#r-{rid}").is_visible():
        issues.append(f"run {rid} is not shown after Show it")
    if page.evaluate("() => document.activeElement && document.activeElement.id") != f"r-{rid}":
        issues.append("keyboard focus did not move to the run")
    if text in (page.locator("#note").text_content() or ""):
        issues.append("the notice stays after Show it")
    if _announced(page, text) != 1:
        issues.append(f"the notice was announced {_announced(page, text)} times")
    assert_no_issues(issues, "history [en]", "focus-outside")
