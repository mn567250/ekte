"""The verdict scale: ONE ladder for every place ekte shows a verdict (issue 228).

A run's risk level (:class:`ekte.models.RiskLevel`, decided by finding
severity in :func:`ekte.scoring.build_verdict`) and a score's grade letter
(:data:`ekte.scoring.GRADE_SCALE`) are shown on the same four steps, each with
one word, one colour and one mark:

========  ====================  ===========  =============  ======
level     word                  colour       web icon       CLI
========  ====================  ===========  =============  ======
clean     Consistent            --success    check          ✓
low       Mostly consistent     --fair       approx (≈)     ≈
medium    Deviations found      --warning    warning        ▲
high      Likely substituted    --danger     x              ✗
========  ====================  ===========  =============  ======

plus ``inconclusive`` (Insufficient signal, muted, ?) for a run that could
not be judged. Grades sit on the same steps (:data:`GRADE_LEVEL`): A and B
clean, C low, D medium, E and F high, so a score, its grade and a verdict
badge in the same colour mean the same thing. Info blue is never a verdict.

Who reads it: the CLI (:mod:`ekte.cli`), the Markdown, HTML and PDF reports
(:mod:`ekte.report.render`, :mod:`ekte.report.pdf`), the alerts
(:mod:`ekte.notify`), the web API's colour families (:mod:`ekte.web.metrics`,
:mod:`ekte.web.history_api`). The web UI's own copy (``RISK_LEVEL``,
``RISK_STYLE`` in ``ekte/web/static/i18n.js``) is checked against this module
by ``tests/test_risk_scale.py``, and so are the translations of the words.
"""

from __future__ import annotations

from dataclasses import dataclass

from ekte.models import RiskLevel


@dataclass(frozen=True)
class Step:
    """One step of the verdict scale."""

    word: str  # English; translated through the UI catalog (ekte/i18n/locales)
    family: str  # the web UI's colour family (class f-<family>, badge <family>)
    token: str  # the colour token (ekte/web/static/v2/tokens.css)
    icon: str  # the web icon (ekte/web/static/icons.js)
    mark: str  # the CLI and plain-text mark
    style: str  # the CLI (rich) style
    emoji: str  # alerts (ekte.notify)


SCALE: dict[RiskLevel, Step] = {
    RiskLevel.CLEAN: Step("Consistent", "good", "--success", "check", "✓", "green", "✅"),
    RiskLevel.LOW: Step("Mostly consistent", "fair", "--fair", "approx", "≈", "yellow4", "🟢"),
    RiskLevel.MEDIUM: Step("Deviations found", "warn", "--warning", "warning", "▲", "yellow", "🟡"),
    RiskLevel.HIGH: Step("Likely substituted", "bad", "--danger", "x", "✗", "bold red", "🔴"),
    RiskLevel.INCONCLUSIVE: Step("Insufficient signal", "grey", "--ink-muted", "help", "?", "dim", "⚪"),
}

# A grade letter's step: the score scale and the verdict scale are one scale.
GRADE_LEVEL: dict[str, RiskLevel] = {
    "A": RiskLevel.CLEAN, "B": RiskLevel.CLEAN, "C": RiskLevel.LOW,
    "D": RiskLevel.MEDIUM, "E": RiskLevel.HIGH, "F": RiskLevel.HIGH,
}


def step(level: RiskLevel | str | None) -> Step:
    """The step of a risk level (a :class:`RiskLevel` or its value); an
    unknown or missing level is ``inconclusive``."""
    try:
        return SCALE[RiskLevel(level)] if level is not None else SCALE[RiskLevel.INCONCLUSIVE]
    except ValueError:
        return SCALE[RiskLevel.INCONCLUSIVE]


def grade_step(letter: str | None) -> Step | None:
    """The step of a grade letter, or None for no (or an unknown) letter."""
    level = GRADE_LEVEL.get(str(letter or "").upper())
    return SCALE[level] if level is not None else None
