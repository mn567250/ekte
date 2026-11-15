"""Tabs have two levels with one look each, styled in ekte.css only
(issue 225): a primary bar (<div class="tabs" role="tablist">) and secondary
bars inside a tab's panel (<div class="tabs sub">). These rules keep pages
from growing a tab style of their own again; tests/a11y/test_tab_levels.py
measures what the browser draws.

- no page or stylesheet but ekte.css styles [role=tab], .tabs or .tab-count;
- every tablist is a primary or a secondary bar, a secondary one sits inside
  a tab panel, and every tab of a primary bar has an icon;
- a count in a tab is the one count badge (.tab-count);
- icons named in markup ([data-icon]) are filled by icons.js, not by a loop
  of the page's own.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static"
V2 = STATIC / "v2"
EKTE_CSS = V2 / "ekte.css"


def _css_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".css":
        return text
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))


def test_only_ekte_css_styles_tabs():
    sel = re.compile(r"""\[role=["']?tab["']?\]|\.tabs\b|\.tab-count\b|\.subtabs\b|\.tcount\b(?=[^{}]*\{[^}]*\})""")
    hits = []
    for path in sorted(V2.glob("*.*")):
        if path.suffix not in (".css", ".html") or path == EKTE_CSS:
            continue
        css = re.sub(r"/\*.*?\*/", "", _css_of(path), flags=re.S)
        # selectors only (the part before each "{")
        for m in re.finditer(r"([^{}]+)\{", css):
            if sel.search(m.group(1)) and ".tsel" not in m.group(1):
                hits.append(f"{path.name}: {m.group(1).strip()[:80]}")
    assert not hits, "tabs are styled in ekte.css only (.tabs, .tabs.sub, .tab-count):\n" + "\n".join(hits)


class _Bars(HTMLParser):
    """Each tablist's classes, whether it sits in a tab panel, and its tabs'
    icon and count slots."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict[str, str | None]] = []
        self.bars: list[dict] = []
        self.tab: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag not in ("input", "br", "img", "meta", "link", "hr", "wbr", "source"):
            self.stack.append(a)
        if a.get("role") == "tablist":
            in_panel = any(x.get("role") == "tabpanel" for x in self.stack[:-1])
            self.bars.append({"cls": (a.get("class") or "").split(), "in_panel": in_panel, "tabs": [],
                              "id": a.get("id") or a.get("aria-label")})
        elif a.get("role") == "tab" and self.bars:
            self.tab = {"icon": False, "counts": []}
            self.bars[-1]["tabs"].append(self.tab)
        elif self.tab is not None:
            if a.get("data-icon"):
                self.tab["icon"] = True
            cls = (a.get("class") or "").split()
            if tag == "span" and ({"count", "tcount", "tab-count"} & set(cls)):
                self.tab["counts"].append(cls)

    def handle_endtag(self, tag: str) -> None:
        if self.stack:
            closed = self.stack.pop()
            if closed.get("role") == "tab":
                self.tab = None


def _bars() -> dict[str, list[dict]]:
    out = {}
    for page in sorted(V2.glob("*.html")):
        p = _Bars()
        p.feed(page.read_text(encoding="utf-8"))
        if p.bars:
            out[page.name] = p.bars
    return out


def test_every_tablist_is_a_primary_or_a_secondary_bar():
    bars = _bars()
    assert {"index.html", "watches.html", "kb.html", "analytics.html"} <= set(bars)
    hits = []
    for page, bs in bars.items():
        for b in bs:
            if "tabs" not in b["cls"]:
                hits.append(f"{page} {b['id']}: not a .tabs bar")
            elif "sub" in b["cls"] and not b["in_panel"]:
                hits.append(f"{page} {b['id']}: a secondary bar outside a tab panel")
            elif "sub" not in b["cls"] and b["in_panel"]:
                hits.append(f"{page} {b['id']}: a bar inside a tab panel must be secondary (.tabs.sub)")
            if "sub" not in b["cls"] and not all(t["icon"] for t in b["tabs"]):
                hits.append(f"{page} {b['id']}: every primary tab has an icon")
            for t in b["tabs"]:
                hits += [f"{page} {b['id']}: a count is <span class=\"tab-count\">, not {c}"
                         for c in t["counts"] if "tab-count" not in c]
    assert not hits, "\n".join(hits)


def test_icons_are_filled_by_icons_js():
    loop = re.compile(r"""\[data-icon\]["']\)\s*\.forEach""")
    hits = [p.name for p in sorted(V2.glob("*.*")) if p.suffix in (".html", ".js")
            and loop.search(p.read_text(encoding="utf-8"))]
    assert not hits, f"icons.js fills [data-icon]; drop the page's own loop: {hits}"
    assert "window.ekteFillIcons" in (STATIC / "icons.js").read_text(encoding="utf-8")
