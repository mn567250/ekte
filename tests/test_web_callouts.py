"""Messages in the web UI come in two shapes (issue 226):

- the Callout, ekte.css's .znote: the page notice (notice.js show) or, inline
  in a card or form, notice.js callout(); tones info, success, warning,
  critical, neutral; for a message that needs attention or action;
- the Note, ekte.css's .note: one muted line with an icon, no box.

These rules keep pages from growing a message box of their own again:

- the old boxes (.errbox, .infobox, .okbox, .rw-note) are gone everywhere;
- no stylesheet but ekte.css draws a box in a status tone (a status tint
  background with a status border): that is the Callout's job;
- no page restyles .note.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static"
V2 = STATIC / "v2"
EKTE_CSS = V2 / "ekte.css"

_TONES = r"(?:info|success|warning|danger|fair)"


def _files(*suffixes: str) -> list[Path]:
    return [p for p in sorted(STATIC.rglob("*")) if p.suffix in suffixes and "vendor" not in p.parts]


def _css(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_the_old_boxes_are_gone():
    old = re.compile(r"""\b(?:errbox|infobox|okbox|rw-note)\b""")
    hits = [f"{p.relative_to(STATIC).as_posix()}: {m.group(0)}" for p in _files(".html", ".js", ".css")
            for m in old.finditer(p.read_text(encoding="utf-8"))]
    assert not hits, "use the Callout (EkteNotice.callout / .znote) or the Note (.note):\n" + "\n".join(hits)


def test_only_the_callout_draws_a_box_in_a_status_tone():
    tint = re.compile(rf"background(?:-color)?\s*:\s*var\(--{_TONES}-tint\)")
    border = re.compile(rf"border(?:-color)?\s*:[^;]*var\(--{_TONES}\)")
    hits = []
    for path in _files(".css", ".html"):
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _css(path)):
            sel, body = m.group(1).strip(), m.group(2)
            if not (tint.search(body) and border.search(body)):
                continue
            if path == EKTE_CSS and (sel.startswith(".znote") or ":hover" in sel):
                continue
            if ":hover" in sel:  # a button's hover wash, not a message box
                continue
            hits.append(f"{path.relative_to(STATIC).as_posix()}: {sel[:70]}")
    assert not hits, "a message box is the Callout (.znote, notice.js callout):\n" + "\n".join(hits)


def test_only_ekte_css_styles_the_note():
    sel = re.compile(r"(?:^|[\s,>+~])\.note(?![\w-])")
    hits = []
    for path in _files(".css", ".html"):
        if path == EKTE_CSS:
            continue
        for m in re.finditer(r"([^{}]+)\{", _css(path)):
            s = m.group(1)
            # a rule for something inside a note (.note .fcv) is the page's own content
            if any(sel.search(" " + part.strip()) and re.search(r"\.note(?![\w-])\s*$", part.strip())
                   for part in s.split(",")):
                hits.append(f"{path.relative_to(STATIC).as_posix()}: {s.strip()[:70]}")
    assert not hits, "the Note (.note) is ekte.css's:\n" + "\n".join(hits)


def test_the_callout_helper_exists():
    js = (V2 / "notice.js").read_text(encoding="utf-8")
    assert "callout: callout" in js and 'class="znote inline ' in js
