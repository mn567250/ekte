"""Published scoring scales — how a detector's checks turn into its score.

A detector that adopts a :class:`Scale` declares every possible outcome of each
of its checks up front (status, severity, points), builds its findings from that
table, and attaches the table to its result. Behavior and report can then never
disagree: the report shows the points each check scored *and* what it could
have scored, positive and negative alike.

Outcomes with ``score=None`` (typically an inconclusive check) are not counted:
they neither raise nor lower the detector score.

Two methods turn findings into the detector score: ``Scale`` averages the
checks' points ("mean_of_checks"); ``DeductionScale`` starts at 100 and lets
findings deduct points or cap the score ("deductions").

A *parametrized* check applies one row set of the scale to many subjects — e.g.
every attribute of a response envelope. Its findings carry ``check`` (the scale
check) and ``subject`` (what was checked), so the scale stays small however many
subjects there are, and reports can group the subjects under their check.
"""

from __future__ import annotations

from typing import Any

from zing.models import DetectorScoring, Finding, ScoringOutcome, Severity, Status


def outcome(
    check: str,
    key: str,
    score: float | None,
    status: Status,
    severity: Severity = Severity.INFO,
    *,
    label: str,
    deduction: float | None = None,
    max_deduction: float | None = None,
    cap: float | None = None,
) -> ScoringOutcome:
    return ScoringOutcome(
        check=check, outcome=key, score=score, status=status, severity=severity, label=label,
        deduction=deduction, max_deduction=max_deduction, cap=cap,
    )


class Scale:
    """A detector's scoring scale: every (check, outcome) it can report."""

    method = "mean_of_checks"

    def __init__(self, *outcomes: ScoringOutcome, titles: dict[str, str] | None = None) -> None:
        self.outcomes = list(outcomes)
        # Display titles of the parametrized checks, for grouping in reports.
        self.titles = dict(titles or {})
        self._by_key = {(o.check, o.outcome): o for o in self.outcomes}
        if len(self._by_key) != len(self.outcomes):
            raise ValueError("duplicate (check, outcome) in scoring scale")

    def get(self, check: str, key: str) -> ScoringOutcome:
        return self._by_key[(check, key)]

    def finding(
        self,
        check: str,
        key: str,
        *,
        title: str,
        summary: str = "",
        evidence: dict[str, Any] | None = None,
        recommendation: str | None = None,
        subject: str | None = None,
        id: str | None = None,
        deduction: float | None = None,
    ) -> Finding:
        """A finding whose status, severity and points come from the scale.

        With ``subject`` the finding is one subject of a parametrized check: its
        id is ``<check>.<subject>`` and it records both. ``id`` gives a finding of
        the check an id of its own (e.g. one per knowledge-base probe) without
        grouping it. ``deduction`` sets the variable deduction of an outcome with
        ``max_deduction``.
        """
        o = self.get(check, key)
        fid = id or (f"{check}.{subject}" if subject else check)
        return Finding(
            id=fid,
            check=check if fid != check else None,
            subject=subject,
            title=title,
            status=o.status,
            severity=o.severity,
            summary=summary,
            evidence=evidence or {},
            recommendation=recommendation,
            outcome=key,
            score=o.score,
            deduction=o.deduction if deduction is None else deduction,
            cap=o.cap,
        )

    def keys(self, check: str) -> list[str]:
        """The outcome keys of one check, in scale order."""
        return [o.outcome for o in self.outcomes if o.check == check]

    def scoring(self) -> DetectorScoring:
        return DetectorScoring(
            method=self.method,
            outcomes=[o.model_copy() for o in self.outcomes],
            titles=dict(self.titles),
        )

    @staticmethod
    def mean(findings: list[Finding]) -> float | None:
        """Average points of the counted checks; None when none was counted."""
        points = [f.score for f in findings if f.outcome is not None and f.score is not None]
        return round(sum(points) / len(points), 1) if points else None

    @staticmethod
    def roll_up(findings: list[Finding]) -> Status:
        """Worst-of status across the checks, ignoring purely informational ones."""
        order = [Status.PASS, Status.INCONCLUSIVE, Status.WARN, Status.FAIL]
        worst = Status.PASS
        for finding in findings:
            if finding.status in order and order.index(finding.status) > order.index(worst):
                worst = finding.status
        return worst


class DeductionScale(Scale):
    """A scale for detectors that start at 100 and lose points per problem: each
    outcome may deduct points (fixed, or up to ``max_deduction``) and/or cap the
    score."""

    method = "deductions"

    @staticmethod
    def total(findings: list[Finding], start: float = 100.0) -> float:
        """``start`` minus every deduction, capped by the lowest cap, in 0-100."""
        score = start - sum(f.deduction or 0.0 for f in findings)
        score = max(0.0, min(100.0, score))
        caps = [f.cap for f in findings if f.cap is not None]
        if caps:
            score = min(score, min(caps))
        return round(score, 1)
