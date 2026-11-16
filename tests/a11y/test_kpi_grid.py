"""KPI tiles as the browser draws them (issue 233), on every Analytics tab
with tiles, at desktop and phone width, in both themes:

- the values of one row of tiles share a baseline (their first lines' tops
  are equal), whatever the labels above them wrap to;
- a label takes at most two lines and is never cut off;
- a change is coloured by whether it is good or bad for its metric: better
  in the success colour, worse in the danger colour, no verdict muted;
- no tile is drawn in a border style of its own (a new group is a tag).

tests/test_web_kpi_grid.py keeps the grid in kpi.css and pages from setting
column counts.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.a11y.harness import THEMES, assert_no_issues
from tests.a11y.test_analytics_view import _open

TABS = ("overview", "reliability", "integrity", "billing")

GRID_JS = """() => {
  const tok = (name) => {
    const el = document.createElement("i");
    el.style.color = `var(${name})`;
    document.body.appendChild(el);
    const c = getComputedStyle(el).color;
    el.remove();
    return c;
  };
  const good = tok("--success"), bad = tok("--danger"), muted = tok("--ink-muted");
  const out = [], lists = [];
  document.querySelectorAll(".kpis:not(.compact)").forEach((l) => {
    const r = l.getBoundingClientRect();
    if (!r.width || l.closest("[hidden]")) return;
    const rows = {};
    l.querySelectorAll(":scope > .kpi").forEach((k) => {
      const id = k.dataset.id, kr = k.getBoundingClientRect();
      (rows[Math.round(kr.top)] ||= []).push([id, k.querySelector(".kv").getBoundingClientRect().top]);
      const kl = k.querySelector(".kl"), lh = parseFloat(getComputedStyle(kl).lineHeight);
      if (kl.scrollHeight > kl.clientHeight + 1) out.push(`${id}: the label "${kl.textContent}" is cut off`);
      if (Math.round(kl.clientHeight / lh) > 2) out.push(`${id}: the label takes ${Math.round(kl.clientHeight / lh)} lines`);
      if (getComputedStyle(k).borderTopStyle !== "solid") out.push(`${id}: a ${getComputedStyle(k).borderTopStyle} tile`);
      const kd = k.querySelector(".kd");
      if (kd) {
        const c = getComputedStyle(kd).color;
        const want = kd.classList.contains("good") ? good : kd.classList.contains("bad") ? bad : muted;
        if (c !== want) out.push(`${id}: change "${kd.textContent}" is ${c}, not ${want}`);
      }
    });
    Object.values(rows).forEach((row) => {
      const tops = row.map((x) => x[1]);
      if (Math.max(...tops) - Math.min(...tops) > 1) {
        out.push("values off one baseline: " + row.map((x) => `${x[0]}@${Math.round(x[1])}`).join(" "));
      }
    });
    lists.push(l.children.length);
  });
  return { out, lists };
}"""


@pytest.mark.bitv("9.1.4.10")
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", [1280, 390])
def test_tiles_share_baselines_and_short_labels(open_page: Any, width: int, theme: str) -> None:
    issues: list[str] = []
    for tab in TABS:
        page, _ = _open(open_page, f"?tab={tab}", viewport={"width": width, "height": 900}, theme=theme)
        r = page.evaluate(GRID_JS)
        if not r["lists"]:
            issues.append(f"{tab}: no KPI tiles shown")
        issues += [f"{tab}: {x}" for x in r["out"]]
        page.context.close()
    assert_no_issues(issues, f"analytics [en, {width}px, {theme}]", "kpi-grid")
