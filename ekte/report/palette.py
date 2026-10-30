"""The report palette, read from the web UI's colour tokens.

``ekte/web/static/v2/tokens.css`` is the one place ekte defines colours. The
exported reports follow it too:

* the HTML report embeds :func:`tokens_css` (the token declarations, both
  themes via ``light-dark()``) and styles itself with ``var(--…)`` only;
* the PDF (reportlab, no CSS) takes resolved hex values from :data:`LIGHT`.

Only what tokens.css itself uses is understood: ``light-dark(<a>, <b>)``,
``var(--name)`` references, ``color-mix(in srgb, <a> N%, <b>)`` and plain
``#rrggbb`` / ``rgba()`` values.
"""

from __future__ import annotations

import re
from pathlib import Path

TOKENS_PATH = Path(__file__).resolve().parents[1] / "web" / "static" / "v2" / "tokens.css"

_DECL = re.compile(r"^\s*--([a-z0-9-]+):\s*([^;]+);", re.M)
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _split_args(s: str) -> list[str]:
    """Split a function's argument list on top-level commas."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def _hex(v: str) -> tuple[float, float, float]:
    v = v.lstrip("#")
    return tuple(int(v[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _resolve(value: str, raw: dict[str, str], side: int, seen: tuple[str, ...] = ()) -> str:
    """One theme's value of a token expression (side 0 = light, 1 = dark)."""
    v = value.strip()
    if v.startswith("light-dark(") and v.endswith(")"):
        return _resolve(_split_args(v[len("light-dark(") : -1])[side], raw, side, seen)
    if v.startswith("var(") and v.endswith(")"):
        name = v[4:-1].strip().removeprefix("--")
        if name in seen or name not in raw:
            raise ValueError(f"tokens.css: cannot resolve --{name}")
        return _resolve(raw[name], raw, side, (*seen, name))
    if v.startswith("color-mix(") and v.endswith(")"):
        space, a, b = _split_args(v[len("color-mix(") : -1])
        if space != "in srgb":
            raise ValueError(f"tokens.css: only 'in srgb' mixes are supported, got {space!r}")
        ca, _, pct = a.rpartition(" ")
        w = float(pct.rstrip("%")) / 100
        x, y = _hex(_resolve(ca, raw, side, seen)), _hex(_resolve(b, raw, side, seen))
        return _to_hex(tuple(p * w + q * (1 - w) for p, q in zip(x, y, strict=True)))  # type: ignore[arg-type]
    return v


def _load() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    raw = dict(_DECL.findall(_COMMENT.sub("", TOKENS_PATH.read_text(encoding="utf-8"))))
    light = {k: _resolve(v, raw, 0) for k, v in raw.items()}
    dark = {k: _resolve(v, raw, 1) for k, v in raw.items()}
    return raw, light, dark


_RAW, LIGHT, DARK = _load()
"""Token name (without ``--``) -> resolved value, for each theme."""


def tokens_css() -> str:
    """The token declarations as CSS, for embedding in a self-contained report.

    Follows the reader's colour scheme (``color-scheme: light dark``) and
    prints in the light theme.
    """
    decls = "".join(f"--{k}:{v};" for k, v in _RAW.items())
    return (
        ":root{color-scheme:light dark;" + decls + "}"
        "@media print{:root{color-scheme:light;}}"
    )
