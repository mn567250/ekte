"""The exported reports use the web UI's colour tokens (ekte/web/static/v2/tokens.css).

ekte/report/palette.py reads tokens.css: the HTML report embeds its
declarations and styles itself with var(--…) only; the PDF takes resolved
values from palette.LIGHT. No other report module carries a colour literal.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ekte.models import AuditReport
from ekte.report import palette, render_html

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "ekte" / "report"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_report.json"

# a hex colour literal: #rgb / #rrggbb(aa) after ":", ",", "(", a space or a quote
_HEX = re.compile(r"(?<=[\s:,(\"'])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b(?![\w-])")
_RGB = re.compile(r"\brgba?\(")
_RESOLVED = re.compile(r"(?:#[0-9a-f]{6}|rgba\([^()]*\)|transparent)$")
# a colour token's value is one colour expression; box-shadow tokens (--shadow-card)
# combine lengths with var(--shadow…) and are left to CSS
_COLOUR = re.compile(r"(?:light-dark|var|color-mix|rgba)\(|#")


def _declared() -> set[str]:
    css = palette.TOKENS_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*--([a-z0-9-]+):", css, re.M))


def test_palette_resolves_every_token_for_both_themes():
    names = _declared()
    assert names
    assert {k for k, v in palette._RAW.items() if not _COLOUR.match(v)} <= {
        "shadow-card",
        "shadow-pop",
    }, "only the box-shadow tokens may hold something other than one colour"
    for theme, values in (("light", palette.LIGHT), ("dark", palette.DARK)):
        assert set(values) == names, f"{theme}: keys differ from tokens.css"
        bad = {
            k: v
            for k, v in values.items()
            if _COLOUR.match(palette._RAW[k]) and not _RESOLVED.match(v)
        }
        assert not bad, f"{theme}: unresolved values: {bad}"


def test_palette_follows_tokens_css():
    # pins the parser to the file: the brand is Emerald in both themes
    assert palette.LIGHT["primary"] == "#005b35"
    assert palette.DARK["primary"] == "#47d89d"
    # heat steps are color-mix() of --primary into --surface
    assert palette.LIGHT["heat-5"] == palette.LIGHT["primary"]
    assert palette.LIGHT["heat-1"] not in (palette.LIGHT["primary"], palette.LIGHT["surface"])


def test_no_colour_literals_in_report_modules():
    hits = []
    for path in sorted(REPORT.glob("*.py")):
        if path.name == "palette.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in _HEX.finditer(line):
                hits.append(f"{path.name}:{n}: {m.group(0)}  {line.strip()[:90]}")
            for m in _RGB.finditer(line):
                hits.append(f"{path.name}:{n}: {m.group(0)}  {line.strip()[:90]}")
            if "@media (prefers-color-scheme" in line:
                hits.append(f"{path.name}:{n}: per-theme block  {line.strip()[:90]}")
    assert not hits, "report colours belong in tokens.css (via palette.py):\n" + "\n".join(hits)


def test_html_report_embeds_the_tokens():
    report = AuditReport.model_validate(json.loads(_FIXTURE.read_text(encoding="utf-8")))
    html = render_html(report)
    assert palette.tokens_css() in html
    assert "var(--primary)" in html or "var(--success)" in html
    assert "prefers-color-scheme" not in html
