"""The shared header (nav.js, ekte.css) on phones (issue 231):

- the display settings (theme, motion, language) sit in one panel after
  one disclosure button, so on phones they open from that button and reading
  and Tab order match what is shown;
- no page styles the header itself (.znav, .zset, the switches): it is the
  same on every page;
- a primary tab bar of five or more tabs is one row that scrolls sideways
  (never wrapping), with the fading edges of EkteScroll.

tests/a11y/test_phone_header.py measures the header and the bars at 390 px.
"""

from __future__ import annotations

import re
from pathlib import Path

V2 = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static" / "v2"


def test_settings_sit_behind_one_button():
    js = (V2 / "nav.js").read_text(encoding="utf-8")
    btn = js.index('class="zset" aria-expanded="false" aria-controls="zset"')
    panel = js.index('class="zset-panel" id="zset" role="group"')
    selects = [js.index(f'<select class="{c}', btn) for c in ("theme-sel", "motion-sel", "lang-sel")]
    close = js.index('"</div>"', max(selects))
    assert btn < panel < min(selects) and max(selects) < close < js.index('class="a11y"')
    assert "window.EkteScroll = { fade: fade }" in js


def test_no_page_styles_the_header():
    sel = re.compile(r"\.(?:znav|zset|zset-panel|theme-sel|motion-sel|lang-sel)\b")
    hits = []
    for path in sorted(V2.glob("*.*")):
        if path.name == "ekte.css" or path.suffix not in (".css", ".html"):
            continue
        text = path.read_text(encoding="utf-8")
        css = text if path.suffix == ".css" else "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        hits += [f"{path.name}: {m.group(1).strip()[:60]}" for m in re.finditer(r"([^{}]+)\{", css) if sel.search(m.group(1))]
    assert not hits, "the header is ekte.css's:\n" + "\n".join(hits)


def test_five_tabs_scroll_in_one_row():
    css = re.sub(r"/\*.*?\*/", "", (V2 / "ekte.css").read_text(encoding="utf-8"), flags=re.S)
    rule = re.search(r'\.tabs:has\(> \[role="tab"\]:nth-of-type\(5\)\)\s*\{([^}]*)\}', css)
    assert rule and "flex-wrap: nowrap" in rule.group(1) and "overflow-x: auto" in rule.group(1)
