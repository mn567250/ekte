"""One verdict scale (issue 228): ekte/risk_scale.py is the ladder every
verdict, score and grade is shown on. These tests keep its copies and its
colours from drifting:

- the web UI's copy in ekte/web/static/i18n.js (words, colour families,
  icons, grade steps and thresholds) equals the Python scale;
- every UI language translates each word, and the Chinese web words are the
  Chinese catalog's;
- no other script or page maps a risk level to a colour or an icon, or
  colours a score by thresholds of its own; no other Python module labels
  risk levels;
- the four colours are readable (text >= 4.5:1 on the surfaces and their
  tint) and stay apart from each other in both themes; "consistent" is the
  brand green itself, so no second green competes with it.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path

import pytest

from ekte import risk_scale, scoring
from ekte.models import DetectorResult, Dimension, Finding, RiskLevel, Severity, Status
from ekte.report import palette
from tests._helpers import run_subprocess

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ekte" / "web" / "static"
I18N_JS = STATIC / "i18n.js"
LOCALES = ROOT / "ekte" / "i18n" / "locales"
NODE = shutil.which("node")

_JS = r"""
global.window = { EKTE_LANG: { isZh: () => false, tr: (s) => s } };
require(process.argv[1]);
const I = window.EKTE_I18N;
const scores = [100, 90, 89.9, 80, 79.9, 70, 69.9, 60, 59.9, 0, null];
console.log(JSON.stringify({
  style: I.RISK_STYLE, grades: I.GRADE_LEVEL, thresholds: I.GRADE_THRESHOLDS, floor: I.GRADE_FLOOR,
  en: I.EN.RISK_LEVEL, zh: I.RISK_LEVEL,
  gradeOf: scores.map(I.gradeOf), scoreFamily: scores.map((s) => I.scoreStep(s).family),
  unknown: I.risk("nope"),
}));
"""


@pytest.fixture(scope="module")
def web() -> dict:
    if NODE is None:
        pytest.skip("node not installed")
    out = run_subprocess(["node", "-e", _JS, str(I18N_JS)], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    return json.loads(out)


def test_the_web_copy_is_the_python_scale(web):
    assert web["style"] == {lvl.value: {"family": s.family, "icon": s.icon} for lvl, s in risk_scale.SCALE.items()}
    assert web["en"] == {lvl.value: s.word for lvl, s in risk_scale.SCALE.items()}
    assert web["grades"] == {g: lvl.value for g, lvl in risk_scale.GRADE_LEVEL.items()}
    assert [tuple(t) for t in web["thresholds"]] == list(scoring.GRADE_THRESHOLDS)
    assert web["floor"] == scoring.GRADE_FLOOR
    scores = [100, 90, 89.9, 80, 79.9, 70, 69.9, 60, 59.9, 0]
    assert web["gradeOf"] == [scoring.rating(s) for s in scores] + [None]
    assert web["scoreFamily"] == [risk_scale.grade_step(scoring.rating(s)).family for s in scores] + ["grey"]
    assert web["unknown"]["level"] == "inconclusive"


def test_every_grade_letter_has_a_step():
    assert set(risk_scale.GRADE_LEVEL) == set(scoring.GRADE_SCALE)
    assert set(risk_scale.SCALE) == set(RiskLevel)
    # steps go one way: a better grade never sits on a worse step
    order = [RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.CLEAN]
    ranks = [order.index(risk_scale.GRADE_LEVEL[g]) for g in scoring.GRADE_SCALE]
    assert ranks == sorted(ranks)


def test_every_language_translates_the_words(web):
    words = [s.word for s in risk_scale.SCALE.values()]
    for path in sorted(LOCALES.glob("*.json")):
        strings = json.loads(path.read_text(encoding="utf-8"))["strings"]
        missing = [w for w in words if not strings.get(w)]
        assert not missing, f"{path.name}: translate {missing}"
    zh = json.loads((LOCALES / "zh.json").read_text(encoding="utf-8"))["strings"]
    assert web["zh"] == {lvl.value: zh[s.word] for lvl, s in risk_scale.SCALE.items()}


def _sources(*suffixes: str) -> list[tuple[str, str]]:
    return [(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
            for p in sorted(STATIC.rglob("*")) if p.suffix in suffixes and "vendor" not in p.parts]


# a risk-level map of a page's own: { clean: "good", … } or clean: { c: "good", … }
# ("clean" is the level only risk maps have: severity and status maps share
# low / medium / high / inconclusive)
_LEVEL_MAP = re.compile(r"""\bclean\s*:\s*\{?\s*(?:\w+\s*:\s*)?["'](?:good|fair|sky|warn|bad|check|warning|x)["']""")
# a score coloured by numbers of its own: v >= 85 ? "good" …
_THRESHOLD = re.compile(r""">=\s*\d{2}\s*\?\s*["'](?:good|fair|sky|warn|bad)["']""")


def test_no_page_keeps_a_scale_of_its_own():
    hits = []
    for rel, text in _sources(".js", ".html"):
        if rel.endswith("static/i18n.js"):
            continue
        for rx in (_LEVEL_MAP, _THRESHOLD):
            hits += [f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}" for m in rx.finditer(text)]
    assert not hits, "use EKTE_I18N.risk / scoreStep / gradeStep (i18n.js):\n" + "\n".join(hits)


def test_no_python_module_labels_risk_levels_itself():
    old = ("Bait-and-switch", "Mostly trustworthy", "LOW RISK", "HIGH RISK", "MEDIUM RISK", "Low risk", "High risk")
    hits = []
    for path in sorted((ROOT / "ekte").rglob("*.py")):
        if path.name == "risk_scale.py":
            continue
        text = path.read_text(encoding="utf-8")
        hits += [f"{path.relative_to(ROOT)}: {w}" for w in old if f'"{w}"' in text]
        hits += [f"{path.relative_to(ROOT)}: {m.group(0)}"
                 for m in re.finditer(r"RiskLevel\.\w+(?:\.value)?\s*:\s*\(?\s*\"[^\"]+\"", text)]
    assert not hits, "risk labels come from ekte.risk_scale:\n" + "\n".join(hits)


# --------------------------------------------------------------------------- #
# Colours
# --------------------------------------------------------------------------- #
def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _contrast(a: str, b: str) -> float:
    la, lb = (0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(bl) for r, g, bl in (_rgb(a), _rgb(b)))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _oklab(h: str) -> tuple[float, float, float]:
    r, g, b = (_lin(c) for c in _rgb(h))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l_ + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l_ - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l_ + 0.7827717662 * m - 0.8086757660 * s)


STEPS = [RiskLevel.CLEAN, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_scale_colours_are_readable_and_apart(theme):
    tok = palette.LIGHT if theme == "light" else palette.DARK
    colour = {lvl: tok[risk_scale.SCALE[lvl].token.removeprefix("--")] for lvl in STEPS}
    tint = {RiskLevel.CLEAN: "success-tint", RiskLevel.LOW: "fair-tint", RiskLevel.MEDIUM: "warning-tint",
            RiskLevel.HIGH: "danger-tint"}
    for lvl in STEPS:
        for bg in ("bg", "surface", "sunken", None):
            back = tok[tint[lvl]] if bg is None else tok[bg]
            assert _contrast(colour[lvl], back) >= 4.5, (theme, lvl, bg or tint[lvl])
    # neighbouring steps and info blue stay apart (OKLab distance x100, the chart series' bar)
    for a, b in zip(STEPS, STEPS[1:], strict=False):
        assert 100 * math.dist(_oklab(colour[a]), _oklab(colour[b])) >= 8.5, (theme, a, b)
    for lvl in STEPS:
        assert 100 * math.dist(_oklab(colour[lvl]), _oklab(tok["info"])) >= 8.5, (theme, lvl, "info")
    # "consistent" is the brand green: no second green competes with --primary
    assert tok["success"] == tok["primary"]


# --------------------------------------------------------------------------- #
# The ladder that decides the level (ekte/scoring.py::build_verdict), one row
# per rule of the methodology's "Risk verdict" table (#255: advisories never
# climb it, and two HIGH findings outside the core need two detectors).
# --------------------------------------------------------------------------- #
def _detector(det_id: str, dim: Dimension, *findings: tuple[str, Severity]) -> DetectorResult:
    return DetectorResult(
        id=det_id, name=det_id, dimension=dim, score=50.0 if findings else 100.0,
        status=Status.FAIL if findings else Status.PASS,
        findings=[Finding(id=f, check=f, title=f, status=Status.FAIL, severity=s)
                  for f, s in findings],
    )


_H, _M, _C = Severity.HIGH, Severity.MEDIUM, Severity.CRITICAL
_LADDER = [
    ("nothing", [], RiskLevel.CLEAN),
    ("critical anywhere", [("integrity", Dimension.INTEGRITY, ("integrity.t", _C))], RiskLevel.HIGH),
    ("high in a core dimension",
     [("billing", Dimension.BILLING, ("billing.x", _H))], RiskLevel.HIGH),
    ("two highs of two detectors",
     [("security", Dimension.SECURITY, ("security.key_echo", _H)),
      ("integrity", Dimension.INTEGRITY, ("integrity.t", _H))], RiskLevel.HIGH),
    ("two highs of one detector",
     [("integrity", Dimension.INTEGRITY, ("integrity.a", _H), ("integrity.b", _H))],
     RiskLevel.MEDIUM),
    ("one high outside the core",
     [("security", Dimension.SECURITY, ("security.key_echo", _H))], RiskLevel.MEDIUM),
    ("advisory high + high",
     [("streaming", Dimension.STREAMING, ("streaming.failed", _H)),
      ("security", Dimension.SECURITY, ("security.key_echo", _H))], RiskLevel.MEDIUM),
    ("medium in a core dimension",
     [("capability", Dimension.CAPABILITY, ("capability.x", _M))], RiskLevel.MEDIUM),
    ("medium outside the core",
     [("protocol", Dimension.PROTOCOL, ("protocol.x", _M))], RiskLevel.LOW),
    ("advisories only",
     [("streaming", Dimension.STREAMING, ("streaming.unsupported", _M)),
      ("security", Dimension.SECURITY, ("security.tls", _H)),
      ("reliability", Dimension.RELIABILITY, ("reliability.success_rate", _H))], RiskLevel.CLEAN),
]


@pytest.mark.parametrize(("case", "failing", "level"), _LADDER, ids=[c[0] for c in _LADDER])
def test_the_ladder_sets_the_level(case, failing, level):
    detectors = [_detector(d.value, d) for d in (
        Dimension.MODEL_IDENTITY, Dimension.CONTEXT_WINDOW, Dimension.CAPABILITY)]
    detectors = [d for d in detectors if d.id not in {f[0] for f in failing}]
    detectors += [_detector(det_id, dim, *fs) for det_id, dim, *fs in failing]
    dims = scoring.build_dimensions(detectors, None)
    verdict = scoring.build_verdict(detectors, dims, profile_matched=True, used_judge=False,
                                    used_baseline=True)
    assert verdict.risk_level == level, case
    # every level the ladder gives is a step of the one scale
    assert verdict.risk_level in risk_scale.SCALE
