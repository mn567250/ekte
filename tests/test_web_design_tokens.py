"""The web UI's design tokens besides colour live in one block of ekte.css
(issue 213): font sizes, letter-spacing, radii, control heights, durations and
easings. Every other stylesheet, page and script under ekte/web/static (CSS
in <style> blocks, style attributes and CSS strings in scripts included) uses
var(--…) for them, so the values cannot drift apart again. Colours have their
own rule (tokens.css, test_web_v2_tokens.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "ekte" / "web" / "static"
EKTE_CSS = STATIC / "v2" / "ekte.css"
BEGIN, END = "/* tokens:begin", "/* tokens:end */"

# token families the block defines; var() of one of these prefixes must exist
FAMILIES = ("t-", "track-", "label-", "s-", "r-", "h-", "dur-", "ease-")

_PROP = re.compile(
    r"(?<![\w-])(font-size|font|border(?:-(?:top|bottom)-(?:left|right))?-radius|letter-spacing|"
    r"transition(?:-duration|-delay|-timing-function)?|animation(?:-duration|-delay|-timing-function)?)"
    r"\s*:\s*([^;}\"'\n]+)"
)
_CUSTOM = re.compile(r"(?<![\w-])(--[\w-]+)\s*:\s*([^;}\"'\n]+)")
_TIME = re.compile(r"(?<![\w.-])(\d*\.?\d+)(ms|s)(?![\w-])")
_EASE_WORD = re.compile(r"(?<![\w(-])ease(?:-in|-out|-in-out)?(?![\w-])")
_VAR = re.compile(r"var\(\s*--([\w-]+)")


def _token_block() -> str:
    css = EKTE_CSS.read_text(encoding="utf-8")
    assert css.count(BEGIN) == 1 and css.count(END) == 1, "ekte.css must hold exactly one token block"
    return css[css.index(BEGIN):css.index(END)]


def _sources() -> list[tuple[Path, str]]:
    out = []
    for path in sorted(STATIC.rglob("*")):
        if path.suffix not in (".css", ".html", ".js") or path.name == "tokens.css" or "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if path == EKTE_CSS:
            # the block itself is the one allowed place; keep line numbers
            a, z = text.index(BEGIN), text.index(END)
            text = text[:a] + re.sub(r"[^\n]", " ", text[a:z]) + text[z:]
        out.append((path, text))
    return out


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _value_issue(prop: str, value: str) -> str | None:
    v = value.strip().removesuffix("!important").strip()
    if prop == "font-size":
        ok = re.fullmatch(r"var\(--(t-[\w-]+|label-size)\)|inherit|1em|100%", v)
        return None if ok else "font-size must be var(--t-…) or var(--label-size)"
    if prop == "font":
        return "font shorthand with a literal size" if re.search(r"(?<![\w.-])\d*\.?\d+(px|rem|em)(?![\w-])", v) else None
    if prop.endswith("radius"):
        rest = re.sub(r"var\(--r-[\w-]+\)|(?<![\w.-])0(?![\w.%])|50%|inherit", "", v).strip()
        return f"radius must be var(--r-…), 0 or 50%: {v}" if rest else None
    if prop == "letter-spacing":
        ok = re.fullmatch(r"var\(--track-[\w-]+\)|0|normal|inherit", v)
        return None if ok else "letter-spacing must be var(--track-…)"
    # transition / animation
    times = [m for m in _TIME.finditer(v) if float(m.group(1)) != 0]
    if times:
        return f"literal duration {times[0].group(0)}: use var(--dur-…)"
    if "cubic-bezier(" in v or _EASE_WORD.search(v):
        return "literal easing: use var(--ease-…)"
    return None


def test_ekte_css_holds_the_only_token_block():
    _token_block()
    others = [p.name for p, t in _sources() if p != EKTE_CSS and (BEGIN in t or END in t)]
    assert not others, f"a second token block: {others}"


def test_no_literal_design_values_outside_the_token_block():
    hits = []
    for path, text in _sources():
        rel = path.relative_to(STATIC).as_posix()
        for m in _PROP.finditer(text):
            issue = _value_issue(m.group(1), m.group(2))
            if issue:
                hits.append(f"{rel}:{_line(text, m.start())}: {issue}  [{m.group(0).strip()[:70]}]")
        # a local custom property must not smuggle in a duration or an easing
        for m in _CUSTOM.finditer(text):
            v = m.group(2)
            if "cubic-bezier(" in v or any(float(t.group(1)) != 0 for t in _TIME.finditer(v)):
                hits.append(f"{rel}:{_line(text, m.start())}: literal motion value in {m.group(1)}: put it in the token block")
    assert not hits, "literal design values outside the token block (ekte.css):\n" + "\n".join(hits)


def test_every_uppercase_label_uses_the_label_tokens():
    hits = []
    for path, text in _sources():
        for m in re.finditer(r"text-transform\s*:\s*uppercase", text):
            a, z = text.rfind("{", 0, m.start()), text.find("}", m.end())
            block = text[a:z]
            missing = [d for d in ("font-size: var(--label-size)", "font-weight: var(--label-weight)",
                                   "letter-spacing: var(--track-label)") if d not in re.sub(r"\s*:\s*", ": ", block)]
            if missing:
                hits.append(f"{path.relative_to(STATIC).as_posix()}:{_line(text, m.start())}: missing {missing}")
    assert not hits, "uppercase labels use --label-size, --label-weight and --track-label:\n" + "\n".join(hits)


def test_no_page_restyles_the_field_label():
    # the field label (.lab) has one look, ekte.css's: a page rule that only
    # resizes it (".setup .lab { font-size: … }") escapes the uppercase check
    # above, so no other stylesheet sets its type
    sel = re.compile(r"\.lab(?![\w-])\s*$")
    typ = re.compile(r"(?:^|[;{\s])(?:font-size|font-weight|letter-spacing|text-transform)\s*:")
    hits = []
    for path, text in _sources():
        if path.name == "ekte.css" or path.suffix not in (".css", ".html"):
            continue
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            if any(sel.search(part.strip()) for part in m.group(1).split(",")) and typ.search(m.group(2)):
                hits.append(f"{path.relative_to(STATIC).as_posix()}:{_line(text, m.start())}: {m.group(1).strip()[:60]}")
    assert not hits, "the field label's type is ekte.css's (.lab):\n" + "\n".join(hits)


def test_every_design_token_used_is_defined():
    defined = set(re.findall(r"(?<![\w-])--([\w-]+)\s*:", _token_block()))
    hits = []
    for path, text in _sources():
        for m in _VAR.finditer(text):
            name = m.group(1)
            if name.startswith(FAMILIES) and name not in defined:
                hits.append(f"{path.relative_to(STATIC).as_posix()}:{_line(text, m.start())}: --{name}")
    assert not hits, "undefined design tokens:\n" + "\n".join(hits)


def test_scripts_take_their_timings_from_the_tokens():
    # an animation timing kept as a constant in a script drifts from the CSS;
    # chartmotion.js reads --dur-… instead (getComputedStyle)
    const = re.compile(r"\b[A-Z][A-Z_]+\s*=\s*\d+\s*;\s*//\s*ms\b")
    hits = [f"{p.relative_to(STATIC).as_posix()}:{_line(t, m.start())}: {m.group(0)}"
            for p, t in _sources() if p.suffix in (".js", ".html") for m in const.finditer(t)]
    assert not hits, "read timings from the --dur-… tokens:\n" + "\n".join(hits)


@pytest.mark.parametrize(
    ("prop", "value", "bad"),
    [
        ("font-size", "13px", True), ("font-size", "var(--t-sm)", False), ("font", "600 12px var(--sans)", True),
        ("border-radius", "10px", True), ("border-radius", "var(--r-sm) var(--r-sm) 0 0", False),
        ("border-radius", "50%", False), ("letter-spacing", "0.4px", True), ("letter-spacing", "var(--track-label)", False),
        ("transition", "color 0.15s", True), ("transition", "color var(--dur-fast) var(--ease-out)", False),
        ("transition", "width var(--dur-slow) ease", True), ("animation", "x 1s cubic-bezier(0, 0, 1, 1)", True),
        ("animation", "zm-draw var(--zm-t, var(--dur-slower)) linear var(--zm-d, 0ms) both", False),
    ],
)
def test_the_rules_catch_literals(prop: str, value: str, bad: bool):
    assert (_value_issue(prop, value) is not None) is bad
