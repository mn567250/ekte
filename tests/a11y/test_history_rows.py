"""History's run rows as the browser draws them (issue 232):

- at desktop width every run row has the same height (two lines: time, risk,
  score and grade, then one muted details line), whatever its details;
- each row action (re-run, schedule or the link to its monitor, delete) is
  centred on the first line, at every width;
- a monitor's run links to that monitor instead of showing a disabled bell;
- with a mouse, a row's actions show only while the row is hovered or holds
  the focus; Tab reaches them and shows them;
- on phones the group header keeps its trends in one row under the title.

tests/test_web_history_rows.py keeps the details out of mono and the row
free of offsets.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.a11y.harness import assert_no_issues, settle
from tests.a11y.history_views import open_history

ROWS_JS = """() => {
  const out = [], heights = {};
  document.querySelectorAll("#hist .row").forEach((row) => {
    const id = row.dataset.id, rm = row.querySelector(".rmain").getBoundingClientRect();
    heights[Math.round(rm.height)] = (heights[Math.round(rm.height)] || []).concat(id);
    const d = row.querySelector(".c-date").getBoundingClientRect(), mid = d.top + d.height / 2;
    row.querySelectorAll(".rline > :not(.rmain)").forEach((a) => {
      const r = a.getBoundingClientRect(), c = r.top + r.height / 2;
      if (Math.abs(c - mid) > 1.5) out.push(`run ${id}: ${a.className} is ${Math.round(c - mid)}px off the first line`);
    });
    const bell = row.querySelector(".rsched");
    if (bell && bell.disabled) out.push(`run ${id}: a disabled schedule button`);
    if (row.querySelector(".c-meta[data-monitor]") && !(bell && bell.tagName === "A" && /^\\/watches#w-\\d+$/.test(bell.getAttribute("href")))) {
      out.push(`run ${id}: a monitor's run does not link to its monitor`);
    }
  });
  return { out, heights: Object.keys(heights).map(Number), rows: document.querySelectorAll("#hist .row").length };
}"""


@pytest.mark.bitv("9.1.3.2", "9.1.4.10")
@pytest.mark.parametrize("width", [1280, 390])
def test_rows_have_one_shape(open_page: Any, width: int) -> None:
    page = open_history(open_page, open_page.base_url, viewport={"width": width, "height": 900})
    got = page.evaluate(ROWS_JS)
    issues = list(got["out"])
    if got["rows"] < 10:
        issues.append(f"only {got['rows']} rows seeded")
    if width == 1280 and len(got["heights"]) != 1:
        issues.append(f"run rows of {len(got['heights'])} heights: {sorted(got['heights'])}")
    if width == 390:
        # the trends follow the title in one row
        tops = page.evaluate("() => [...document.querySelectorAll('#hist .group')].map(g =>"
                             " [...g.querySelectorAll('.trend .kpi')].map(k => Math.round(k.getBoundingClientRect().top)))")
        issues += [f"group {i}: trends on {len(set(t))} rows" for i, t in enumerate(tops) if len(set(t)) > 1]
    assert_no_issues(issues, f"history [en, {width}px]", "run-rows")


def test_row_actions_show_on_hover_and_focus(open_page: Any) -> None:
    page = open_history(open_page, open_page.base_url)
    row = page.locator("#hist .row").nth(2)
    act = row.locator(".rrerun")
    op = lambda: float(act.evaluate("el => getComputedStyle(el).opacity"))  # noqa: E731
    issues: list[str] = []
    page.mouse.move(0, 0)
    settle(page)
    if op() != 0:
        issues.append(f"actions show on a row that is not hovered (opacity {op()})")
    row.locator(".rmain").hover()
    page.wait_for_timeout(300)
    if op() != 1:
        issues.append("actions do not show on hover")
    page.mouse.move(0, 0)
    row.locator(".rmain").focus()
    page.keyboard.press("Tab")
    page.wait_for_timeout(300)
    focused = page.evaluate("() => document.activeElement.className")
    if "rrerun" not in focused or op() != 1:
        issues.append(f"Tab from the row does not reach and show its actions ({focused!r}, opacity {op()})")
    assert_no_issues(issues, "history [en]", "run-row-actions")
