"""Analytics' sortable tables (#207): every table of the page is drawn by one
helper (dataTable) whose column headers are sort buttons. A click sorts by
that column (largest or A–Z first), a second click flips the direction, a
third one goes back to the table's own order; the sort lives in the URL query
string, one key per table, and redraws only that table (no request), keeping
the focus on the button and announcing the new order (BITV 9.1.3.1,
9.4.1.2, 9.4.1.3).

The page runs against the a11y server's seeded history (seed.py).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, Route

from tests.a11y.harness import assert_no_issues, settle
from tests.a11y.test_analytics_view import _open

# id, query that shows the table, caption id, URL key, a sortable numeric column
TABLES = [
    ("lb", "?os=lb", "lbcap", "lb.sort", "runs"),
    ("cmpt", "?tab=trends&table.trend=1", "tcap", "cmpt.sort", "value"),
    ("heatt", "?tab=trends&ts=heat&table.heat=1", "htcap", "heatt.sort", "value"),
    ("errt", "?tab=reliability&table.errors=1", "etcap", "errt.sort", "calls"),
    ("errg", "?tab=reliability", "eg-cap", "errg.sort", "calls"),
    ("ovh", "?tab=reliability&rs=ovh", "ovh-cap", "ovh.sort", "relay_overhead"),
    ("int", "?tab=integrity", "int-cap", "int.sort", "runs"),
    ("billt", "?tab=billing&table.bill=1", "btcap", "billt.sort", "value"),
    ("bills", "?tab=billing", "bs-cap", "bills.sort", "runs"),
]

NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# the rows (their text) and, per row, the text of the cell under a header button
ROWS_JS = """([cap, ref]) => {
  const table = document.getElementById(cap).closest("table");
  const th = table.querySelector(`[data-sort="${CSS.escape(ref)}"]`).closest("th");
  const at = Array.prototype.indexOf.call(th.parentNode.cells, th);
  return Array.from(table.tBodies[0].rows).map((tr) => ({
    text: tr.textContent, cell: tr.cells[at].textContent, fc: tr.classList.contains("fcrow") }));
}"""
SORTED_JS = """(cap) => Array.from(document.getElementById(cap).closest("table").querySelectorAll("th[aria-sort]"))
  .map((th) => [th.querySelector("[data-sort]").dataset.sort, th.getAttribute("aria-sort")])"""


def _number(text: str) -> float | None:
    m = NUMBER.search(text)
    return float(m.group(0).replace(",", "")) if m else None


def _rows(page: Page, cap: str, ref: str) -> list[dict[str, Any]]:
    return list(page.evaluate(ROWS_JS, [cap, ref]))


def _order_issues(rows: list[dict[str, Any]], desc: bool, what: str) -> list[str]:
    """The numbers of the column in order (rows without one last)."""
    vals = [_number(r["cell"]) for r in rows if not r["fc"]]
    have = [v for v in vals if v is not None]
    issues = []
    if vals[: len(have)] != have:
        issues.append(f"{what}: rows without a value are not last: {vals}")
    if have != sorted(have, reverse=desc):
        issues.append(f"{what}: not sorted {'descending' if desc else 'ascending'}: {vals}")
    return issues


def _query(page: Page) -> dict[str, list[str]]:
    return parse_qs(urlparse(page.url).query, keep_blank_values=True)


@pytest.mark.bitv("9.1.3.1", "9.4.1.2", "9.4.1.3")
@pytest.mark.parametrize(("tid", "query", "cap", "key", "col"), TABLES, ids=[t[0] for t in TABLES])
def test_table_sorts_by_its_columns(open_page, tid: str, query: str, cap: str, key: str, col: str) -> None:
    """A header button sorts its column: largest first, then smallest first,
    then the table's own order; aria-sort, the focus, the announcement and
    the URL follow, and no data is fetched again. A link with the sort opens
    the table sorted."""
    page, calls = _open(open_page, query)
    ref = f"{tid}:{col}"
    issues: list[str] = []
    table = page.locator(f"table:has(#{cap})")
    if not table.count():
        pytest.fail(f"{tid}: no table with caption #{cap}")
    own = _rows(page, cap, ref)
    if len(own) < 2:
        pytest.fail(f"{tid}: the seeded history gives fewer than two rows")
    plain = table.locator("thead th:not(:has([data-sort]))").all_inner_texts()
    if any(t.strip().lower() not in ("note", "p25–p75") for t in plain):
        issues.append(f"{tid}: columns without a sort button: {plain}")
    if page.evaluate(SORTED_JS, cap):
        issues.append(f"{tid}: a column is marked sorted before any sort")
    button = table.locator(f'[data-sort="{ref}"]')
    status = page.locator(f"#{cap}").locator("xpath=ancestor::section[contains(@class,'panel')][1]").locator(".sortst")
    calls.clear()
    steps = [("desc", "descending", f"{col}.desc"), ("asc", "ascending", f"{col}.asc"), (None, None, None)]
    for dir_, aria, url in steps:
        button.click()
        settle(page)
        what = f"{tid} after the click to {dir_ or 'its own order'}"
        sorted_now = page.evaluate(SORTED_JS, cap)
        if sorted_now != ([[ref, aria]] if aria else []):
            issues.append(f"{what}: aria-sort is {sorted_now}")
        if page.evaluate("document.activeElement && document.activeElement.dataset.sort") != ref:
            issues.append(f"{what}: the focus left the sort button")
        if _query(page).get(key) != ([url] if url else None):
            issues.append(f"{what}: the URL holds {_query(page).get(key)}")
        said = status.inner_text().strip()
        rows = _rows(page, cap, ref)
        if dir_:
            issues += _order_issues(rows, dir_ == "desc", what)
            if not said.startswith("Sorted by ") or not said.endswith("descending" if dir_ == "desc" else "ascending"):
                issues.append(f"{what}: announced {said!r}")
        else:
            if [r["text"] for r in rows] != [r["text"] for r in own]:
                issues.append(f"{what}: not back in the table's own order")
            if said != "Default order":
                issues.append(f"{what}: announced {said!r}")
    if calls:
        issues.append(f"{tid}: sorting fetched {calls}")
    page.close()
    page, _ = _open(open_page, f"{query}&{key}={col}.asc")
    if page.evaluate(SORTED_JS, cap) != [[ref, "ascending"]]:
        issues.append(f"{tid}: a link with {key}={col}.asc does not open the table sorted")
    issues += _order_issues(_rows(page, cap, ref), False, f"{tid} opened from a link")
    assert_no_issues(issues, "analytics [en]", f"sort-{tid}")


@pytest.mark.bitv("9.4.1.2")
def test_leaderboard_sort_survives_another_grouping(open_page) -> None:
    """Names sort A–Z first; the sort stays when the leaderboard ranks
    another grouping, whose table has the same column."""
    page, _ = _open(open_page, "?os=lb")
    issues: list[str] = []
    page.locator('[data-sort="lb:label"]').click()
    settle(page)
    if _query(page).get("lb.sort") != ["label.asc"]:
        issues.append(f"the first click on the name column is not A–Z: {_query(page).get('lb.sort')}")
    page.locator('#lb-ctl [data-lb="model"]').click()
    settle(page)
    names = [r["cell"] for r in _rows(page, "lbcap", "lb:label")]
    if page.evaluate(SORTED_JS, "lbcap") != [["lb:label", "ascending"]] or _query(page).get("lb.sort") != ["label.asc"]:
        issues.append("ranking by model dropped the sort by name")
    if names != sorted(names, key=str.casefold):
        issues.append(f"the models are not sorted A–Z: {names}")
    assert_no_issues(issues, "analytics [en]", "sort-grouping")


def _integrity_verdicts(route: Route) -> None:
    """The first check column: passed, warnings, failed, no verdict (in that
    row order), whatever the seeded runs found."""
    resp = route.fetch()
    data = resp.json()
    check = data["checks"][0]
    cells = [{"n": 4, "pass": 4, "warn": 0, "fail": 0}, {"n": 4, "pass": 3, "warn": 1, "fail": 0},
             {"n": 4, "pass": 2, "warn": 0, "fail": 2}, {"n": 0, "pass": 0, "warn": 0, "fail": 0, "other": 1}]
    for row, cell in zip(data["rows"], cells, strict=False):
        row["checks"][check] = cell
    route.fulfill(response=resp, json=data)


@pytest.mark.bitv("9.4.1.2")
def test_check_columns_sort_worst_first(open_page) -> None:
    """A check column sorts by its verdict: failed, warnings, passed, and
    the rows without a verdict last, in either direction."""
    page, _ = _open(open_page, "?tab=integrity", route=("**/api/analytics/integrity*", _integrity_verdicts))
    issues: list[str] = []
    ref = page.locator("#int-cap").locator("xpath=..").locator("[data-sort^='int:check:']").first.get_attribute("data-sort")
    names = [r["text"] for r in _rows(page, "int-cap", str(ref))]
    if len(names) < 4:
        pytest.fail(f"the seeded history gives {len(names)} relay × model rows, the check needs 4")
    passed, warned, failed, none = names[:4]
    button = page.locator(f'[data-sort="{ref}"]')
    button.click()
    settle(page)
    got = [r["text"] for r in _rows(page, "int-cap", str(ref))]
    if got[:3] != [failed, warned, passed] or got[-1] != none:
        issues.append(f"worst first: {got}")
    button.click()
    settle(page)
    got = [r["text"] for r in _rows(page, "int-cap", str(ref))]
    if got[:3] != [passed, warned, failed] or got[-1] != none:
        issues.append(f"best first: {got}")
    assert_no_issues(issues, "analytics [en]", "sort-checks")


def _with_forecast(route: Route) -> None:
    """A forecast for the first series, larger than every measured value."""
    resp = route.fetch()
    data = resp.json()
    x = data["series"][0]
    last = x["points"][-1]["bucket"]
    x["forecast"] = {"status": "ok", "start": {"bucket": last, "value": 1, "p25": 1, "p75": 1},
                     "points": [{"bucket": "2099-01-01T00:00:00Z", "value": 999, "p25": 990, "p75": 1000}]}
    route.fulfill(response=resp, json=data)


@pytest.mark.bitv("9.4.1.2")
def test_forecast_rows_stay_after_the_measured_rows(open_page) -> None:
    """Forecast rows (estimates) follow the measured rows whatever the sort."""
    page, _ = _open(open_page, "?tab=trends&table.trend=1", route=("**/api/analytics/series*", _with_forecast))
    issues: list[str] = []
    if not any(r["fc"] for r in _rows(page, "tcap", "cmpt:value")):
        pytest.fail("the injected forecast shows no forecast row")
    button = page.locator('[data-sort="cmpt:value"]')
    for dir_ in ("descending", "ascending"):
        button.click()
        settle(page)
        fc = [r["fc"] for r in _rows(page, "tcap", "cmpt:value")]
        if fc != sorted(fc):
            issues.append(f"sorted {dir_}, a forecast row is among the measured rows: {fc}")
    assert_no_issues(issues, "analytics [en]", "sort-forecast")


FIT_JS = """(id) => {
  const box = document.querySelector(`#dtw-${id} .tscroll`);
  const first = box.querySelector("tbody tr > :first-child");
  const x0 = first.getBoundingClientRect().left;
  const over = box.scrollWidth - box.clientWidth;
  box.scrollLeft = 400;
  const x1 = first.getBoundingClientRect().left;
  box.scrollLeft = 0;
  return { over, still: Math.abs(x1 - x0) < 1 };
}"""


@pytest.mark.bitv("9.1.3.2", "9.1.4.10")
@pytest.mark.parametrize(("tid", "query", "cap", "key", "col"), TABLES, ids=[t[0] for t in TABLES])
def test_wide_tables_fit_and_keep_their_first_column(open_page, tid: str, query: str, cap: str, key: str, col: str) -> None:
    """#220: at 1280 px every table shows its default columns without
    scrolling sideways; on a narrow screen the row names stay in view while
    the rest of the table scrolls."""
    issues: list[str] = []
    page, _ = _open(open_page, query)
    settle(page)
    fit = page.evaluate(FIT_JS, tid)
    if fit["over"] > 0:
        issues.append(f"{tid}: {fit['over']} px of columns hidden to the right at 1280 px")
    narrow, _ = _open(open_page, query, viewport={"width": 390, "height": 844})
    settle(narrow)
    fit = narrow.evaluate(FIT_JS, tid)
    if fit["over"] > 0 and not fit["still"]:
        issues.append(f"{tid}: the first column scrolls away at 390 px")
    assert_no_issues(issues, "analytics [en]", f"table-fit-{tid}")


@pytest.mark.bitv("9.1.3.1", "9.4.1.2", "9.4.1.3")
def test_more_columns_chips_show_and_hide_a_column(open_page) -> None:
    """#220: the leaderboard's other metrics are "More columns" chips; a chip
    adds its column (and removes it again), keeps the focus, writes the URL
    (no request) and announces the change."""
    issues: list[str] = []
    page, calls = _open(open_page, "?os=lb")
    settle(page)

    def heads() -> list[str]:
        return [(t or "").strip() for t in page.locator("#lbcap").locator("xpath=..").locator("thead th").all_text_contents()]

    before = heads()
    chip = page.locator("#dtw-lb [data-cols]").first
    ref, label = chip.get_attribute("data-cols") or "", (chip.inner_text() or "").strip()
    n = len(calls)
    chip.click()
    if label not in heads():
        issues.append(f"the {label} column was not added: {heads()}")
    again = page.locator(f'[data-cols="{ref}"]')
    if again.get_attribute("aria-pressed") != "true":
        issues.append("the chip is not pressed")
    if page.evaluate("document.activeElement && document.activeElement.dataset.cols") != ref:
        issues.append("the focus left the chip")
    if _query(page).get("lb.cols") != [ref.split(":", 1)[1]]:
        issues.append(f"lb.cols in the URL: {_query(page).get('lb.cols')}")
    if "shown" not in (page.locator("#panel-board .sortst, .panel:not([hidden]) .sortst").first.text_content() or ""):
        issues.append("the new column is not announced")
    if len(calls) != n:
        issues.append(f"showing a column made requests: {calls[n:]}")
    again.click()
    if heads() != before:
        issues.append(f"the column did not go away again: {heads()}")
    if "lb.cols" in _query(page):
        issues.append("lb.cols stays in the URL with no extra column")
    assert_no_issues(issues, "analytics [en]", "more-columns")


def test_billing_tiles_come_before_the_metric_picker(open_page) -> None:
    """#217: the Metric select drives the chart, not the key figures, so it
    sits between the tiles and the chart, with room above it."""
    page, _ = _open(open_page, "?tab=billing")
    settle(page)
    box = page.evaluate("""() => {
      const r = (s) => document.querySelector(s).getBoundingClientRect();
      return { tiles: r("#bill-head .kpis").bottom, select: r("#bill-ctl select").top, chart: r("#bill-chart").top };
    }""")
    issues = []
    if not box["tiles"] + 12 <= box["select"] < box["chart"]:
        issues.append(f"order or spacing of tiles, Metric and chart: {box}")
    assert_no_issues(issues, "analytics [en]", "billing-order")
