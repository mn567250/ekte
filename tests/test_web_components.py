"""One Table, one Disclosure and one EmptyState (issue 227), all in ekte.css:

- every data table is <table class="tbl"> (pages add only their own cells),
  and no stylesheet but ekte.css lays out a table (border-collapse);
- a disclosure is a button and a region (aria-expanded, aria-controls), never
  a native <details>; pages that build one with data-disclosure /
  EkteDisclosure load disclosure.js;
- an empty state is .empty (EkteNotice.empty); the old variants (empty-data,
  empty-row, empty-box, jempty, nomatch, the report's .none) are gone;
- History's column header lines up with its rows without negative offsets.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static"
V2 = STATIC / "v2"
EKTE_CSS = V2 / "ekte.css"


def _files(*suffixes: str) -> list[Path]:
    return [p for p in sorted(STATIC.rglob("*")) if p.suffix in suffixes and "vendor" not in p.parts]


def _rel(p: Path) -> str:
    return p.relative_to(STATIC).as_posix()


def _css(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_every_table_is_the_table_component():
    tag = re.compile(r"<table\b([^>]*)>")
    hits = []
    for p in _files(".html", ".js"):
        for m in tag.finditer(p.read_text(encoding="utf-8")):
            cls = re.search(r"""class=\\?["']([^"'\\]*)""", m.group(1))
            if not cls or "tbl" not in cls.group(1).split():
                hits.append(f"{_rel(p)}: {m.group(0)[:60]}")
    assert not hits, 'a data table is <table class="tbl"> (ekte.css):\n' + "\n".join(hits)


def test_only_ekte_css_lays_out_tables():
    hits = []
    for p in _files(".css", ".html", ".js"):
        if p == EKTE_CSS:
            continue
        text = _css(p) if p.suffix != ".js" else p.read_text(encoding="utf-8")
        hits += [f"{_rel(p)}: border-collapse" for _ in re.finditer(r"border-collapse\s*:", text)]
    assert not hits, "tables are laid out by ekte.css's .tbl:\n" + "\n".join(hits)


def test_no_native_details():
    # (the comment in disclosure.js that explains why is not markup)
    hits = [_rel(p) for p in _files(".html", ".js")
            if re.search(r"""['"]<(?:details|summary)\b""", p.read_text(encoding="utf-8"))
            or (p.suffix == ".html" and re.search(r"<(?:details|summary)\b", p.read_text(encoding="utf-8")))]
    assert not hits, f"a disclosure is a button and a region (disclosure.js), not <details>: {hits}"


def test_every_disclosure_button_names_its_region():
    btn = re.compile(r"""<button\b[^>]*class=\\?["'][^"']*\bdisclosure\b[^>]*>""")
    hits = []
    for p in _files(".html", ".js"):
        for m in btn.finditer(p.read_text(encoding="utf-8")):
            if "aria-expanded" not in m.group(0) or "aria-controls" not in m.group(0):
                hits.append(f"{_rel(p)}: {m.group(0)[:80]}")
    assert not hits, "a .disclosure button carries aria-expanded and aria-controls:\n" + "\n".join(hits)


def test_pages_that_build_disclosures_load_the_script():
    users = {"kbsection.js"}  # scripts that build them for their page
    hits = []
    for page in sorted(V2.glob("*.html")):
        html = page.read_text(encoding="utf-8")
        own = "data-disclosure" in html or "EkteDisclosure" in html
        via = any(f'/static/{s}"' in html for s in users)
        if (own or via) and '<script src="/static/disclosure.js"></script>' not in html:
            hits.append(page.name)
    assert not hits, f"load /static/disclosure.js: {hits}"


def test_one_empty_state():
    old = re.compile(r"""\b(?:empty-data|empty-row|empty-box|jempty|nomatch)\b|<p class=["']none["']|\.zr \.none\b|empty boxed""")
    hits = [f"{_rel(p)}: {m.group(0)}" for p in _files(".html", ".js", ".css")
            for m in old.finditer(p.read_text(encoding="utf-8"))]
    assert not hits, "an empty state is .empty (EkteNotice.empty):\n" + "\n".join(hits)


def test_history_header_has_no_offsets():
    css = _css(V2 / "history.html")
    hits = re.findall(r"\.sortb[^{]*\{[^}]*margin(?:-left)?\s*:[^;]*-\d{2,}px", css)
    assert not hits, f"the column header lines up through --cols, not negative margins: {hits}"
