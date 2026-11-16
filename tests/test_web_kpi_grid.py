"""KPI tiles have one grid (issue 233), defined in kpi.css only:

- as many columns as fit (every tile at least --kpi-min wide): no page sets a
  column count of its own (no ``cols`` option, no ``--kpi-cols``) and no other
  stylesheet lays out ``.kpis``;
- each tile is a subgrid, so label, value, change and caption sit on rows
  shared across a row of tiles (tests/a11y/test_kpi_grid.py measures the
  baselines in the browser);
- a tile that starts a new group (another base) is named by a tag, not by a
  border style of its own: no dashed tiles;
- tile labels are short: the KPI label, else the short label.
"""

from __future__ import annotations

import re
from pathlib import Path

from ekte import i18n
from ekte.web import metrics

STATIC = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static"
KPI_CSS = STATIC / "v2" / "kpi.css"


def _sources(*suffixes: str) -> list[Path]:
    return [p for p in sorted(STATIC.rglob("*")) if p.suffix in suffixes and "vendor" not in p.parts]


def _css(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_no_page_sets_a_column_count():
    call = re.compile(r"""(?:\bK|EkteKpi)\.(?:html|mount)\((.*)""")
    hits = []
    for path in _sources(".js", ".html"):
        text = path.read_text(encoding="utf-8")
        hits += [f"{path.name}: --kpi-cols" for _ in re.finditer(r"--kpi-cols", text)]
        hits += [f"{path.name}: {m.group(0)[:80]}" for m in call.finditer(text) if re.search(r"\bcols\s*:", m.group(1))]
    assert not hits, "KPI tiles take as many columns as fit (kpi.css):\n" + "\n".join(hits)
    css = _css(KPI_CSS)
    assert ".kpis.cols" not in css and "subgrid" in css and "auto-fit" in css


def test_only_kpi_css_lays_out_the_grid():
    hits = []
    for path in _sources(".css", ".html"):
        if path == KPI_CSS:
            continue
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _css(path)):
            sel, body = m.group(1), m.group(2)
            if re.search(r"\.kpis?\b", sel) and re.search(r"grid-template|grid-row|grid-column|display\s*:", body):
                hits.append(f"{path.name}: {sel.strip()[:70]}")
    assert not hits, "the KPI grid is kpi.css's:\n" + "\n".join(hits)


def test_no_tile_has_a_border_style_of_its_own():
    hits = []
    for path in _sources(".css", ".html"):
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _css(path)):
            if re.search(r"\.kpi\b", m.group(1)) and re.search(r"border(?:-style)?\s*:[^;]*\b(?:dashed|dotted)\b", m.group(2)):
                hits.append(f"{path.name}: {m.group(1).strip()[:70]}")
    assert not hits, "a tile of another group is named by its tag (.ktag), not a dashed border:\n" + "\n".join(hits)


def test_every_new_group_is_tagged_and_translated():
    data = i18n._load()
    for name, groups in metrics.KPI_SETS.items():
        for g in groups[1:]:
            m = metrics.get(g[0])
            assert m.tag_key, f"{name}: {m.id} starts a new group; give it a tag (metric.{m.id}.tag)"
            for code in i18n.codes():
                assert data[code]["strings"].get(m.tag_key), (code, m.tag_key)


def test_tiles_use_the_short_label():
    for mid in [*metrics.METRICS, *metrics.COUNTS]:
        m = metrics.get(mid)
        tile = metrics.tile(m)
        want = m.kpi_label_key if m.kpi else m.short_label_key
        assert tile["label_key"] == want == m.tile_label_key, mid
        assert tile["tag_key"] == m.tag_key
