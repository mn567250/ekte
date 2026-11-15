"""Numbers, units, counts and relay names in the web UI go through ONE
formatter module, ekte/web/static/v2/fmt.js (issue 229), so History,
Analytics, Monitors and the report spell them alike: locale grouping
("1,300"), a space before the unit ("1,300 ms"), the same decimals per unit,
one relay name (the server's label, cut in the middle when long).

These rules keep pages from growing their own formatter again:

- every page that loads /i18n.js loads /static/fmt.js right after it;
- no script fills "{name}" placeholders itself (every Tf goes through
  EkteFmt.fill, which groups numbers);
- no script glues a unit to a number ("…" + "ms", Math.round(v) + " ms",
  String(Math.round(v))) or breaks relay URLs with <wbr>; CSS and SVG
  values (a width, an animation's duration) are not text, and a line may opt
  out with a reviewed "// fmt-ok: <reason>" comment.

fmt.js itself is checked under node.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests._helpers import run_subprocess

STATIC = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static"
V2 = STATIC / "v2"
FMT = V2 / "fmt.js"
NODE = shutil.which("node")


def _sources() -> list[tuple[str, str]]:
    out = []
    for path in sorted(STATIC.rglob("*")):
        if path.suffix not in (".html", ".js") or path == FMT or "vendor" in path.parts:
            continue
        if path.name in ("locales.js", "lang.js"):  # the translation layer itself
            continue
        out.append((path.relative_to(STATIC).as_posix(), path.read_text(encoding="utf-8")))
    return out


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def test_every_page_loads_the_formatters_after_i18n():
    pages = [p for p in sorted(V2.glob("*.html")) if '<script src="/i18n.js"></script>' in p.read_text(encoding="utf-8")]
    assert len(pages) >= 6
    missing = [p.name for p in pages
               if '<script src="/i18n.js"></script>\n<script src="/static/fmt.js"></script>' not in p.read_text(encoding="utf-8")]
    assert not missing, f"load /static/fmt.js right after /i18n.js: {missing}"


# a placeholder filler of a script's own: the regex or split/join over "{" + key + "}"
_OWN_FILL = re.compile(r"""\.replace\(\s*/\\\{\(\\w\+\)\\\}/g|\.split\(\s*["']\{["']\s*\+""")


def test_no_script_fills_placeholders_itself():
    hits = [f"{rel}:{_line(t, m.start())}" for rel, t in _sources() for m in _OWN_FILL.finditer(t)]
    assert not hits, "fill \"{name}\" placeholders with EkteFmt.fill (fmt.js):\n" + "\n".join(hits)


_UNIT = r"(?:ms|s|µs|tok/s|tok|tokens|pp|KB|MB|%)"
_GLUED = [
    # a number and a unit with no space: x + "ms", x + "%", x + "%</b>"
    (re.compile(r"""\+\s*(["'])""" + _UNIT + r"""(?:\1|<)"""), "a unit glued to a number"),
    # a rounded number with its unit: Math.round(v) + " ms"
    (re.compile(r"""Math\.round\([^()]*(?:\([^()]*\))?[^()]*\)\s*\+\s*["']\s*""" + _UNIT + r"""\b"""), "a number and unit by hand"),
    # a number shown without grouping
    (re.compile(r"""String\(\s*Math\.round\("""), "an unformatted number"),
    # relay URLs broken by hand (fmt.js relay() names them)
    (re.compile(r"""<wbr>"""), "a name broken with <wbr>"),
]
# CSS and SVG values are not text: a bar's width, an animation's duration
_CSS_LINE = re.compile(r"""\.style\b|style=|setAttribute\(|setProperty\(|\bwidth:""")
# an explicit, reviewed exception on the same line, with its reason
_RAW = "// fmt-ok:"
# i18n.js fills the server's finding texts: their numbers are the server's,
# as the Markdown and PDF reports print them
_EXEMPT = {"i18n.js"}


def test_no_script_formats_numbers_or_units_itself():
    hits = []
    for rel, text in _sources():
        if rel in _EXEMPT:
            continue
        lines = text.split("\n")
        for rx, what in _GLUED:
            for m in rx.finditer(text):
                line = lines[_line(text, m.start()) - 1]
                if _CSS_LINE.search(line) or _RAW in line:
                    continue
                hits.append(f"{rel}:{_line(text, m.start())}: {what}: {m.group(0)[:60]}")
    assert not hits, "format with EkteFmt (fmt.js):\n" + "\n".join(hits)


@pytest.mark.parametrize(("src", "bad"), [
    ('s + "ms"', True), ("v + '%'", True), ('"<b>" + pct + "%</b>"', True), ('a.setAttribute("dur", d + "ms")', False), ('Math.round(r.latency_p50_ms) + " ms"', True),
    ("String(Math.round(v))", True), ('x.replace(/([/.])/g, "$1<wbr>")', True),
    ('EkteFmt.unit(v, "ms")', False), ('w.toFixed(2) + \'%"></span>\'', False), ('"p50 " + EkteFmt.num(v)', False),
])
def test_the_rules_catch_hand_formatting(src: str, bad: bool):
    assert (any(rx.search(src) for rx, _ in _GLUED) and not _CSS_LINE.search(src)) is bad


_NODE_JS = r"""
global.window = {};
require(process.argv[1]);
const F = window.EkteFmt;
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(([fn, args]) => F[fn](...args))));
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_fmt_js_in_english():
    cases = [
        ("num", [1300]), ("num", [None]), ("num", [2.345, 1]),
        ("unit", [1300, "ms"]), ("unit", [0.125, "ratio"]), ("unit", [0.125, "percent"]), ("unit", [12.34, "tok_s"]),
        ("unit", [1300, "ms", {"bare": True}]), ("parts", [1300, "ms"]), ("parts", [0.5, "ratio"]),
        ("delta", [-120, "ms"]), ("delta", [0.031, "ratio"]), ("unitName", ["ms", True]), ("unitName", ["ms"]),
        ("runs", [1]), ("runs", [1300]), ("requests", [2]), ("models", [1]),
        ("elapsed", [850]), ("elapsed", [4200]), ("elapsed", [73000]),
        ("duration", [0.85]), ("duration", [6097]), ("duration", [65000]), ("duration", [7384000]),
        ("bytes", [512]), ("bytes", [1536]),
        ("middle", ["gateway.a-very-long-relay-hostname.example.org:8443", 30]),
        ("relay", ["relay-a.example", None]), ("relay", ["relay-a.example", "https://relay-a.example/v1"]),
        ("relay", ["gateway.a-very-long-relay-hostname.example.org", None, 20]), ("relay", ["<b>", None]),
        ("fill", ["{n} runs, run #{n}, {s}, {x}", {"n": 1300, "s": "a"}]),
    ]
    out = json.loads(run_subprocess(["node", "-e", _NODE_JS, str(FMT), json.dumps(cases)],
                                    capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    assert out == [
        "1,300", "—", "2.3",
        "1,300 ms", "12.5%", "12.5%", "12.3 tok/s",
        "1,300", {"text": "1,300", "unit": "ms"}, {"text": "50%", "unit": ""},
        "-120 ms", "+3.1 pp", "milliseconds", "ms",
        "1 run", "1,300 runs", "2 requests", "1 model",
        "850 ms", "4.2 s", "73 s",
        "850 µs", "6 s 97 ms", "1 min 5 s", "2 h 3 min 4 s",
        "512 bytes", "1.5 KB",
        "gateway.a-very-lon…le.org:8443",
        '<span class="relay-nm">relay-a.example</span>',
        '<span class="relay-nm" title="https://relay-a.example/v1">relay-a.example</span>',
        '<span class="relay-nm" title="gateway.a-very-long-relay-hostname.example.org">'
        '<span aria-hidden="true">gateway.a-ve…ple.org</span>'
        '<span class="sr-only">gateway.a-very-long-relay-hostname.example.org</span></span>',
        '<span class="relay-nm">&lt;b&gt;</span>',
        "1,300 runs, run #1300, a, {x}",
    ]
