"""Per-dimension details for the Markdown and HTML reports.

For every dimension that ran, this explains how its score and status came about
and lists every check behind it, passed and failed alike:

* the score — the equal-weight mean of the dimension's detector scores, with
  each detector's score and whether it was counted;
* the status — the worst status the detectors concluded, and, when a finding's
  severity overrode it, which findings did;
* per detector — each check's outcome and the points it scored. A detector that
  publishes a scoring scale (``DetectorResult.scoring``) also gets the full
  scale, i.e. every outcome each check could have had and its points.

Detectors without a scale still show all their findings, so every dimension is
covered and a detector gains the points/scale view by adopting
:class:`zing.detectors.scale.Scale` — nothing here has to change.

Every dimension is listed, those that did not run included (with the reason),
and a dimension can carry extra content past its checks: register a renderer in
``_EXTRAS`` (the performance dimension's measurements live there).
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass, field

from zing.models import (
    AuditReport,
    DetectorResult,
    Dimension,
    DimensionScore,
    Finding,
    ScoringOutcome,
    Status,
)
from zing.report import performance as perf_render
from zing.scoring import DIMENSION_WEIGHTS, _worst_status

_STATUS_EMOJI: dict[Status, str] = {
    Status.PASS: "✅",
    Status.WARN: "⚠️",
    Status.FAIL: "❌",
    Status.INCONCLUSIVE: "❔",
    Status.NOT_RUN: "➖",
    Status.INFO: "ℹ️",
    Status.ERROR: "💥",
}
_STATUS_CLASS: dict[Status, str] = {
    Status.PASS: "pass",
    Status.WARN: "warn",
    Status.FAIL: "fail",
    Status.INCONCLUSIVE: "muted",
    Status.NOT_RUN: "muted",
    Status.INFO: "info",
    Status.ERROR: "fail",
}
_POSITIVE = (Status.PASS, Status.INFO)
_NOT_COUNTED = "not counted"


def _num(score: float | None) -> str:
    return "—" if score is None else f"{score:g}"


def _members(report: AuditReport, d: DimensionScore) -> list[DetectorResult]:
    return [det for det in report.detectors if det.dimension == d.dimension]


def all_dimensions(report: AuditReport) -> list[DimensionScore]:
    """The report's dimensions plus, as "not run", any it does not carry (a
    report from before that dimension existed), in scoring order."""
    have = {d.dimension: d for d in report.dimensions}
    extra = [
        DimensionScore(dimension=dim, weight=w, status=Status.NOT_RUN,
                       reason="Not recorded in this report.")
        for dim, w in DIMENSION_WEIGHTS.items()
        if dim not in have
    ]
    return list(report.dimensions) + extra


def _not_run_reason(d: DimensionScore) -> str:
    return d.reason or "Not run in this suite."


# Extra content a dimension's details carry past its checks, per output format:
# a renderer returns "" / [] when the report has nothing to add.
_Extra = tuple[Callable[[AuditReport], list[str]], Callable[[AuditReport], str]]
_EXTRAS: dict[Dimension, _Extra] = {
    Dimension.PERFORMANCE: (
        lambda r: perf_render.markdown_section(
            r.performance, title="Performance measurements", level=4
        ),
        lambda r: perf_render.html_section(r.performance, nested=True),
    ),
}


def _extra_markdown(report: AuditReport, d: DimensionScore) -> list[str]:
    x = _EXTRAS.get(d.dimension)
    return x[0](report) if x else []


def _extra_html(report: AuditReport, d: DimensionScore) -> str:
    x = _EXTRAS.get(d.dimension)
    return x[1](report) if x else ""


def score_explanation(d: DimensionScore, members: list[DetectorResult]) -> str:
    """One line: how the dimension score was computed."""
    names = {det.id: det.name for det in members}
    if d.breakdown is not None:
        parts = [(c.detector, c.score, c.counted) for c in d.breakdown.detectors]
    else:  # reports from before the breakdown existed
        parts = [(det.id, det.score, det.score is not None) for det in members]
    counted = [(i, s) for i, s, ok in parts if ok]
    skipped = [i for i, _, ok in parts if not ok]
    if not counted:
        line = "No detector produced a numeric score."
    elif len(counted) == 1:
        i, s = counted[0]
        line = f"Score of one detector: {names.get(i, i)} {_num(s)}."
    else:
        terms = ", ".join(f"{names.get(i, i)} {_num(s)}" for i, s in counted)
        line = f"Mean of {len(counted)} detectors, equal weight: {terms} → {_num(d.score)}."
    if skipped:
        line += " Not counted (no numeric score): " + ", ".join(names.get(i, i) for i in skipped) + "."
    return line


def status_explanation(d: DimensionScore) -> str:
    """One line: where the dimension status came from."""
    b = d.breakdown
    if b is None:
        return f"Status {d.status.value}."
    o = b.status_override
    if o is None:
        return f"Status {d.status.value}: the worst status its detectors concluded."
    n = len(o.findings)
    return (
        f"Status {o.to_status.value}: raised from {o.from_status.value} by "
        f"{n} {o.severity.value}-severity finding{'s' if n != 1 else ''} "
        f"({', '.join(o.findings)}); a serious finding always pulls a dimension down, "
        "whatever the score."
    )


def _labels(det: DetectorResult) -> dict[tuple[str, str], ScoringOutcome]:
    return {(o.check, o.outcome): o for o in (det.scoring.outcomes if det.scoring else [])}


def _check_titles(det: DetectorResult) -> dict[str, str]:
    titles: dict[str, str] = dict(det.scoring.titles) if det.scoring else {}
    for f in det.findings:
        titles.setdefault(f.id, f.title)
    return titles


def _scale_by_check(det: DetectorResult) -> list[tuple[str, list[ScoringOutcome]]]:
    groups: dict[str, list[ScoringOutcome]] = {}
    for o in det.scoring.outcomes if det.scoring else []:
        groups.setdefault(o.check, []).append(o)
    return list(groups.items())


def _effect(
    method: str,
    score: float | None,
    deduction: float | None = None,
    cap: float | None = None,
    max_deduction: float | None = None,
) -> str:
    """What a finding (or a scale outcome) did to the detector score."""
    if method != "deductions":
        return _NOT_COUNTED if score is None else _num(score)
    parts = []
    if deduction:
        parts.append(f"−{_num(round(deduction, 1))}")
    elif max_deduction:
        parts.append(f"up to −{_num(max_deduction)}")
    if cap is not None:
        parts.append(f"cap {_num(cap)}")
    return " · ".join(parts) or "no deduction"


def _points(f: Finding, method: str) -> str:
    return _effect(method, f.score, f.deduction, f.cap)


def _scale_points(o: ScoringOutcome, method: str) -> str:
    return _effect(method, o.score, o.deduction, o.cap, o.max_deduction)


_METHOD_NOTE = {
    "mean_of_checks": "Detector score: mean of the counted checks' points.",
    "deductions": (
        "Detector score: starts at 100; findings deduct points or cap it "
        "(the lowest cap wins)."
    ),
}


@dataclass
class _Group:
    """The subjects of one parametrized check (e.g. every response attribute)."""

    check: str
    title: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def status(self) -> Status:
        # The scoring module's order, so a group reads like a dimension status
        # (a warning or failure outranks a detector error).
        return _worst_status([f.status for f in self.findings])

    @property
    def ok(self) -> int:
        return sum(f.status == Status.PASS for f in self.findings)

    @property
    def mean(self) -> float | None:
        points = [f.score for f in self.findings if f.score is not None]
        return round(sum(points) / len(points), 1) if points else None

    def points(self, method: str) -> str:
        """The group's effect: "avg 90" on a mean scale; on a deduction scale
        the subjects' deductions summed and the lowest cap."""
        if method != "deductions":
            return f"avg {_num(self.mean)}"
        deducted = sum(f.deduction or 0.0 for f in self.findings)
        caps = [f.cap for f in self.findings if f.cap is not None]
        return _effect(method, None, deducted, min(caps) if caps else None)

    def outline(self, labels: dict[tuple[str, str], ScoringOutcome]) -> str:
        """"8 of 9 OK; missing: usage.total_tokens" — the problems by name."""
        text = f"{self.ok} of {len(self.findings)} OK"
        issues = [
            f"{f.subject} ({_label(labels, f)})" for f in self.findings if f.status != Status.PASS
        ]
        return text + ("; " + "; ".join(issues) if issues else "")


def _label(labels: dict[tuple[str, str], ScoringOutcome], f: Finding) -> str:
    o = labels.get((f.scale_check, f.outcome or ""))
    return o.label if o and o.label else f.summary


def _observed(f: Finding) -> str:
    ev = f.evidence
    if ev.get("observed") is not None:
        return str(ev["observed"])[:60]
    if ev.get("status_code") is not None:
        return f"HTTP {ev['status_code']}"
    return "—"


def _rows(det: DetectorResult) -> list[Finding | _Group]:
    """The detector's findings, the subjects of each parametrized check folded
    into one group (in first-seen order)."""
    titles = det.scoring.titles if det.scoring else {}
    rows: list[Finding | _Group] = []
    groups: dict[str, _Group] = {}
    for f in det.findings:
        if not (f.check and f.subject):
            rows.append(f)
            continue
        if f.check not in groups:
            groups[f.check] = _Group(f.check, titles.get(f.check, f.check))
            rows.append(groups[f.check])
        groups[f.check].findings.append(f)
    return rows


def fold_passed_subjects(det: DetectorResult) -> tuple[list[Finding], list[tuple[str, list[str]]]]:
    """For a findings listing: the findings to show one by one, and the passed
    subjects of each parametrized check folded into ``(title, subjects)`` —
    problems stay itemised, a wall of passed attributes does not."""
    titles = det.scoring.titles if det.scoring else {}
    shown: list[Finding] = []
    folded: dict[str, list[str]] = {}
    for f in det.findings:
        if f.check and f.subject and f.status == Status.PASS:
            folded.setdefault(f.check, []).append(f.subject)
        else:
            shown.append(f)
    return shown, [(titles.get(c, c), subjects) for c, subjects in folded.items()]


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def markdown_section(report: AuditReport, md) -> list[str]:
    """The "Dimension details" section, every dimension listed; ``md`` escapes
    untrusted inline text."""
    lines = ["## Dimension details", ""]
    for d in all_dimensions(report):
        members = _members(report, d)
        emoji = _STATUS_EMOJI.get(d.status, "")
        lines.append(f"### {emoji} {d.dimension.value} — {_num(d.score)} ({d.status.value})")
        lines.append("")
        if members:
            lines.append(f"- {md(score_explanation(d, members))}")
            lines.append(f"- {md(status_explanation(d))}")
        else:
            lines.append(f"- {md(_not_run_reason(d))}")
        lines.append("")
        for det in members:
            lines.extend(_markdown_detector(det, md))
        lines.extend(_extra_markdown(report, d))
    return lines


def _markdown_detector(det: DetectorResult, md) -> list[str]:
    lines = [f"**{md(det.name)}** (`{det.id}`) — score {_num(det.score)}, {det.status.value}", ""]
    if det.error:
        lines += [f"> Detector error: {md(det.error)}", ""]
    if not det.findings:
        return lines + ["_No findings._", ""]
    labels = _labels(det)
    if det.scoring is not None:
        lines.append("| | Check | Outcome | Points |")
        lines.append("| --- | --- | --- | ---: |")
        groups: list[_Group] = []
        for row in _rows(det):
            if isinstance(row, _Group):
                groups.append(row)
                lines.append(
                    f"| {_STATUS_EMOJI.get(row.status, '')} | {md(row.title)} | "
                    f"{md(row.outline(labels))} | {row.points(det.scoring.method)} |"
                )
                continue
            lines.append(
                f"| {_STATUS_EMOJI.get(row.status, '')} | {md(row.title)} | "
                f"{md(_label(labels, row))} | {_points(row, det.scoring.method)} |"
            )
        lines.append("")
        for g in groups:
            lines.append(f"<details><summary>{md(g.title)}: all {len(g.findings)}</summary>")
            lines.append("")
            lines.append("| | Attribute | Observed | Outcome | Points |")
            lines.append("| --- | --- | --- | --- | ---: |")
            for f in g.findings:
                lines.append(
                    f"| {_STATUS_EMOJI.get(f.status, '')} | `{md(f.subject or '')}` | "
                    f"{md(_observed(f))} | {md(_label(labels, f))} | {_points(f, det.scoring.method)} |"
                )
            lines.append("")
            lines.append("</details>")
            lines.append("")
        if det.scoring.method in _METHOD_NOTE:
            lines.append(f"_{_METHOD_NOTE[det.scoring.method]}_")
            lines.append("")
        titles = _check_titles(det)
        lines.append("<details><summary>Scoring scale</summary>")
        lines.append("")
        for check, outcomes in _scale_by_check(det):
            lines.append(f"- {md(titles.get(check, check))} (`{check}`)")
            for o in outcomes:
                lines.append(f"  - {_scale_points(o, det.scoring.method)}: {md(o.label)}")
        lines.append("")
        lines.append("</details>")
        lines.append("")
        return lines
    passed = [f for f in det.findings if f.status in _POSITIVE]
    other = [f for f in det.findings if f.status not in _POSITIVE]
    for heading, group in (("Passed", passed), ("Issues and open points", other)):
        if not group:
            continue
        lines.append(f"_{heading}_")
        lines.append("")
        for f in group:
            lines.append(f"- {_STATUS_EMOJI.get(f.status, '')} {md(f.title)}")
        lines.append("")
    return lines


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pill(status: Status) -> str:
    return f'<span class="pill {_STATUS_CLASS.get(status, "muted")}">{_esc(status.value)}</span>'


def html_section(report: AuditReport) -> str:
    """The "Dimension details" section: every dimension, each one expandable."""
    out = ['<section class="card"><h2>Dimension details</h2>']
    for d in all_dimensions(report):
        members = _members(report, d)
        out.append('<details class="dim">')
        out.append(
            f"<summary>{_pill(d.status)} <strong>{_esc(d.dimension.value)}</strong> "
            f'<span class="tag">score {_esc(_num(d.score))}</span></summary>'
        )
        if members:
            out.append(f'<p class="muted">{_esc(score_explanation(d, members))}</p>')
            out.append(f'<p class="muted">{_esc(status_explanation(d))}</p>')
        else:
            out.append(f'<p class="muted">{_esc(_not_run_reason(d))}</p>')
        for det in members:
            out.append(_html_detector(det))
        out.append(_extra_html(report, d))
        out.append("</details>")
    out.append("</section>")
    return "".join(out)


def _html_detector(det: DetectorResult) -> str:
    out = [
        '<div class="dim-det"><h3 class="det-title">'
        f"{_esc(det.name)} {_pill(det.status)} "
        f'<span class="tag">{_esc(det.id)}</span> '
        f'<span class="tag">score {_esc(_num(det.score))}</span></h3>'
    ]
    if det.error:
        out.append(f'<p class="fail">Detector error: {_esc(det.error)}</p>')
    if not det.findings:
        out.append('<p class="muted">No findings.</p></div>')
        return "".join(out)
    labels = _labels(det)
    if det.scoring is not None:
        out.append(
            '<table><thead><tr><th></th><th>Check</th><th>Outcome</th>'
            '<th class="num">Points</th></tr></thead><tbody>'
        )
        for row in _rows(det):
            if isinstance(row, _Group):
                out.append(
                    f"<tr><td>{_pill(row.status)}</td><td>{_esc(row.title)}</td>"
                    f"<td>{_esc(row.outline(labels))}{_html_group(row, labels, det.scoring.method)}</td>"
                    f'<td class="num">{_esc(row.points(det.scoring.method))}</td></tr>'
                )
                continue
            out.append(
                f"<tr><td>{_pill(row.status)}</td><td>{_esc(row.title)}</td>"
                f'<td>{_esc(_label(labels, row))}</td>'
                f'<td class="num">{_esc(_points(row, det.scoring.method))}</td></tr>'
            )
        out.append("</tbody></table>")
        if det.scoring.method in _METHOD_NOTE:
            out.append(f'<p class="muted">{_esc(_METHOD_NOTE[det.scoring.method])}</p>')
        titles = _check_titles(det)
        out.append('<details class="scale"><summary>Scoring scale</summary><ul>')
        for check, outcomes in _scale_by_check(det):
            out.append(f"<li>{_esc(titles.get(check, check))} <code>{_esc(check)}</code><ul>")
            for o in outcomes:
                pts = _scale_points(o, det.scoring.method)
                out.append(f"<li><strong>{_esc(pts)}</strong> — {_esc(o.label)}</li>")
            out.append("</ul></li>")
        out.append("</ul></details></div>")
        return "".join(out)
    out.append('<ul class="checks">')
    for f in sorted(det.findings, key=lambda f: f.status not in _POSITIVE):
        out.append(f"<li>{_pill(f.status)} {_esc(f.title)}</li>")
    out.append("</ul></div>")
    return "".join(out)


def _html_group(
    g: _Group, labels: dict[tuple[str, str], ScoringOutcome], method: str
) -> str:
    rows = "".join(
        f"<tr><td>{_pill(f.status)}</td><td><code>{_esc(f.subject)}</code></td>"
        f"<td><code>{_esc(_observed(f))}</code></td><td>{_esc(_label(labels, f))}</td>"
        f'<td class="num">{_esc(_points(f, method))}</td></tr>'
        for f in g.findings
    )
    return (
        f'<details class="scale"><summary>All {len(g.findings)}</summary><table><thead><tr>'
        "<th></th><th>Attribute</th><th>Observed</th><th>Outcome</th>"
        f'<th class="num">Points</th></tr></thead><tbody>{rows}</tbody></table></details>'
    )


DIM_CSS = """
details.dim { border-top: 1px solid var(--line); padding: .5rem 0; }
details.dim:first-of-type { border-top: 0; }
details.dim > summary { cursor: pointer; }
.dim-det { margin: .5rem 0 .75rem 1rem; }
details.scale { margin: .35rem 0; font-size: .88rem; }
details.scale > summary { cursor: pointer; color: var(--ink-muted); }
ul.checks { list-style: none; padding-left: 0; margin: .35rem 0; }
ul.checks li { margin: .2rem 0; }
"""
