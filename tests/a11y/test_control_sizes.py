"""Control heights (issue 213): every text field, select and button of the web
UI is one of three heights, the --h-sm / --h-md / --h-lg tokens of ekte.css
(32, 40 and 48 px). The static lint (tests/test_web_design_tokens.py) keeps
literal values out of the stylesheets; this test measures what the browser
draws, so a padding or font change that makes a control 36 px tall fails
here.

The page runs against the a11y server's seeded history (seed.py).
"""

from __future__ import annotations

import pytest

from tests.a11y.harness import PAGES, assert_no_issues, expand_all

HEIGHTS = (32, 40, 48)

# the controls: fields, selects, buttons, segmented controls, chips, the
# filter dropdowns and the header switches; textareas grow with their text
SIZES_JS = """(heights) => {
  const sel = 'input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=range]):not(.sr-only), ' +
    'select, .btn, .cta, .seg button, .seg.radio label, .chips button, .ekf-ms-btn, .znav .a11y';
  const off = [];
  document.querySelectorAll(sel).forEach((el) => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest("[hidden]") || getComputedStyle(el).visibility === "hidden") return;
    const h = Math.round(r.height);
    if (!heights.includes(h)) {
      const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("name") || el.id || "").trim().slice(0, 30);
      off.push(`${el.tagName.toLowerCase()}.${String(el.className).trim().split(/\\s+/).slice(0, 2).join(".")} "${name}": ${h} px`);
    }
  });
  return off;
}"""


@pytest.mark.parametrize("page_id", list(PAGES))
def test_controls_are_one_of_three_heights(open_page, page_id: str) -> None:
    page = open_page(PAGES[page_id], "en")
    expand_all(page)
    off = page.evaluate(SIZES_JS, list(HEIGHTS))
    assert_no_issues([f"not {'/'.join(map(str, HEIGHTS))} px: {o}" for o in off], f"{page_id} [en]", "control-sizes")
