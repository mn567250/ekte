"""WCAG 2.1 success criteria -> EN 301 549 clause / BITV 2.0 test step.

BITV 2.0 requires EN 301 549, whose chapter 9 (web) repeats WCAG 2.1 A/AA with
"9." in front of the criterion number: WCAG 1.4.3 is EN 301 549 9.1.4.3, which
is also the BITV-Test step number (Prüfschritt 9.1.4.3 "Kontraste von Texten
ausreichend"). axe-core tags its rules "wcag143", so the mapping is mechanical.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# The single source of truth for the 50 WCAG 2.1 A/AA criteria (= EN 301 549
# 9.x.x.x / BITV steps): number, level, title, how far the tests decide it and
# how. The conformance report (tests/a11y/conformance.py) and the report page
# in web UI v2 (/accessibility) read the same file.
CATALOGUE_FILE = Path(__file__).resolve().parents[2] / "ekte" / "web" / "static" / "v2" / "bitv-catalogue.json"


def catalogue() -> dict[str, Any]:
    """The coverage catalogue: {"standards": {...}, "steps": [{step, wcag, level, title, automation, how}]}."""
    return dict(json.loads(CATALOGUE_FILE.read_text(encoding="utf-8")))


# WCAG 2.1 level A + AA (the EN 301 549 / BITV scope), with short titles.
CRITERIA: dict[str, str] = {s["wcag"]: s["title"] for s in catalogue()["steps"]}

_TAG = re.compile(r"^wcag(\d)(\d)(\d+)$")


def criterion_of(tag: str) -> str | None:
    """axe tag "wcag1410" -> "1.4.10" (None for non-criterion tags)."""
    m = _TAG.match(tag)
    if not m:
        return None
    sc = ".".join(m.groups())
    return sc if sc in CRITERIA else None


def bitv(sc: str) -> str:
    """WCAG criterion -> BITV/EN 301 549 label, e.g. "BITV 9.1.4.3 Contrast (Minimum)"."""
    return f"BITV/EN 9.{sc} {CRITERIA.get(sc, '')}".rstrip()


def describe(tags: list[str]) -> str:
    """Human label for an axe rule's tags ("best practice" when it maps to no criterion)."""
    scs = [sc for sc in (criterion_of(t) for t in tags) if sc]
    if not scs:
        return "best practice (no WCAG criterion)"
    return "; ".join(f"WCAG {sc} / {bitv(sc)}" for sc in scs)
