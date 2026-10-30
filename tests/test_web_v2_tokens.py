"""Web UI v2 colours live in one file: ekte/web/static/v2/tokens.css.

Every other v2 stylesheet, page and script uses var(--…) only, and no file
but tokens.css switches colours per theme. tokens.css writes each colour token
once as light-dark(<light>, <dark>).
"""

from __future__ import annotations

import re
from pathlib import Path

V2 = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static" / "v2"
TOKENS = V2 / "tokens.css"

# a CSS colour literal: #rgb / #rrggbb(aa), or a colour function
_LITERAL = re.compile(
    r"(?<=[\s:,(])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b(?![\w-])"
    r"|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(\s*[\d.]"
)


def _sources() -> list[Path]:
    return sorted(p for ext in ("*.css", "*.html", "*.js") for p in V2.glob(ext) if p != TOKENS)


def test_no_colour_literals_outside_tokens_css():
    hits = []
    for path in _sources():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # a hex value follows ":", "," "(" or a space; "#feed" in $("#feed") is an id
            for m in _LITERAL.finditer(line):
                hits.append(f"{path.name}:{n}: {m.group(0)}  {line.strip()[:90]}")
    assert not hits, "colour literals outside tokens.css:\n" + "\n".join(hits)


def test_no_per_theme_colour_blocks_outside_tokens_css():
    bad = [
        p.name
        for p in _sources()
        if "@media (prefers-color-scheme" in p.read_text(encoding="utf-8")
    ]
    assert not bad, f"per-theme colour rules belong in tokens.css: {bad}"


def test_tokens_css_declares_each_colour_once_for_both_themes():
    css = TOKENS.read_text(encoding="utf-8")
    decls = re.findall(r"^\s*(--[a-z0-9-]+):\s*([^;]+);", css, re.M)
    names = [n for n, _ in decls]
    assert len(names) == len(set(names)), "a token is declared twice"
    literal = [n for n, v in decls if _LITERAL.search(v) and not v.startswith("light-dark(")]
    assert not literal, f"literal colours must be written as light-dark(<light>, <dark>): {literal}"


def test_every_v2_page_links_tokens_before_ekte_css():
    for page in sorted(V2.glob("*.html")):
        html = page.read_text(encoding="utf-8")
        tok = html.find('href="/v2/static/tokens.css"')
        ekte = html.find('href="/v2/static/ekte.css"')
        assert 0 <= tok < ekte, f"{page.name}: tokens.css must be linked before ekte.css"
