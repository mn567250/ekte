"""History's run row has one shape (issue 232); these rules keep it:

- the run's details are one sans line (.c-meta), never mono;
- the row's columns are shared with the column header through --cols, with
  no negative offsets;
- a monitor's run is never offered a disabled "schedule" button: it links to
  its monitor;
- a run's details are built in one place (metaHTML) and their separators are
  drawn by CSS, so a wrapped line never starts or ends with one.

tests/a11y/test_history_rows.py measures the rows in the browser.
"""

from __future__ import annotations

import re
from pathlib import Path

HISTORY = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static" / "v2" / "history.html"


def _css() -> str:
    text = HISTORY.read_text(encoding="utf-8")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_details_are_sans():
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _css()):
        if ".c-meta" in m.group(1) or ".rmain" in m.group(1) or ".c-date" in m.group(1):
            assert "--mono" not in m.group(2), m.group(1).strip()


def test_no_negative_offsets_in_the_rows():
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _css()):
        sel = m.group(1)
        if re.search(r"\.(?:colhead|sortb|rmain|rline|c-\w+|row)\b", sel):
            assert not re.search(r"margin(?:-left|-right)?\s*:[^;]*-\d{2,}px", m.group(2)), sel.strip()


def test_a_monitor_run_links_to_its_monitor():
    js = HISTORY.read_text(encoding="utf-8")
    assert 'class="rsched bymon" disabled' not in js
    assert '<a class="rsched bymon" href="/watches#w-' in js


def test_details_come_from_one_place():
    text = HISTORY.read_text(encoding="utf-8")
    assert text.count('class="c-meta"') == 1 and "function metaHTML" in text
    assert "c-mode" not in text and "\\u00a0·\\u00a0" not in text
