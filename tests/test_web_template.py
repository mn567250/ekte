"""One page template (issue 230): what the page markup and stylesheets must
keep so every page follows it (tests/a11y/test_page_template.py measures it):

- <main>'s blocks come in one order: .hero, the page notice (.znote),
  the toolbar (.toolbar: the filter panel and the page's own actions in a
  .tool-row), then the content; the filter panel is the toolbar or sits in it;
- ekte.css spaces the blocks (one gap, no block margins) and pads every card
  by one --pad;
- no stylesheet stretches a button (.btn) to fill its row: actions sit in a
  .actions row at their labels' width; only .cta is full width;
- no inline margins on the page.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

V2 = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static" / "v2"
PAGES = ["index.html", "watches.html", "history.html", "analytics.html", "kb.html", "accessibility.html"]


class _Main(HTMLParser):
    """The direct children of <main>: (tag, classes, id)."""

    VOID = {"input", "br", "img", "meta", "link", "hr", "wbr", "source"}

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.in_main = 0
        self.kids: list[tuple[str, set[str], str]] = []
        self.live: list[bool] = []
        self.inside: list[set[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in self.VOID:
            return
        self.depth += 1
        if tag == "main":
            self.in_main = self.depth
        elif self.in_main and self.depth == self.in_main + 1:
            self.kids.append((tag, set((a.get("class") or "").split()), a.get("id") or ""))
            self.live.append("aria-live" in a or a.get("role") in ("status", "alert"))
        if self.in_main and self.depth > self.in_main + 1 and a.get("id") == "filters":
            self.inside.append(self.kids[-1][1])

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if tag == "main":
            self.in_main = 0
        self.depth -= 1


def _rank(cls: set[str], live: bool = False) -> int | None:
    if "sr-only" in cls:
        return None
    if live and not cls:  # a live region the page fills with a notice (e.g. #mk-bar)
        return 1
    if "hero" in cls:
        return 0
    if "znote" in cls:
        return 1
    if "toolbar" in cls or "filters" in cls:
        return 2
    return 3


def test_main_blocks_follow_the_template():
    hits = []
    for name in PAGES:
        p = _Main()
        p.feed((V2 / name).read_text(encoding="utf-8"))
        ranks = [(r, f"{t}#{i}.{'.'.join(sorted(c))}") for (t, c, i), lv in zip(p.kids, p.live, strict=True)
                 if (r := _rank(c, lv)) is not None]
        assert ranks and ranks[0][0] == 0, f"{name}: <main> starts with the hero"
        last = 0
        for r, desc in ranks:
            if r < last:
                hits.append(f"{name}: {desc} after a later block")
            last = max(last, r)
        hits += [f"{name}: the filter panel sits in {sorted(c)}, not a .toolbar" for c in p.inside if "toolbar" not in c]
    assert not hits, "hero → notice → toolbar → content:\n" + "\n".join(hits)


def _css(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_ekte_css_spaces_and_pads_the_blocks():
    css = _css(V2 / "ekte.css")
    assert "main#main > :not(:empty):not(.sr-only) ~ :not(:empty):not(.sr-only) { margin-top: var(--s-5); }" in css
    assert ".card-pad { padding: var(--pad); }" in css
    assert "padding: 6px var(--pad) 12px" in _css(V2 / "filterpanel.css")


def test_no_button_is_stretched():
    stretch = re.compile(r"(?:^|;|\s)(?:flex\s*:\s*1\b|flex-grow\s*:\s*[1-9]|width\s*:\s*100%)")
    hits = []
    for path in sorted(V2.glob("*.*")):
        if path.suffix not in (".css", ".html"):
            continue
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _css(path)):
            sel, body = m.group(1), m.group(2)
            if re.search(r"\.btn\b", sel) and stretch.search(body):
                hits.append(f"{path.name}: {sel.strip()[:70]}")
    assert not hits, "buttons are as wide as their labels (.actions):\n" + "\n".join(hits)


def test_no_inline_margins():
    hits = [f"{n}: {m.group(0)}" for n in PAGES
            for m in re.finditer(r'<(?:section|div|main)[^>]*style="[^"]*margin[^"]*"', (V2 / n).read_text(encoding="utf-8"))]
    assert not hits, "\n".join(hits)
