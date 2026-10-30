"""Render an :class:`~ekte.models.AuditReport` to PDF.

The PDF is typeset natively with ReportLab (pure Python, BSD-licensed, no system
libraries), from the same data and the same helpers as the HTML report: the
dimension details come from :mod:`ekte.report.dimensions`, the performance
tables and charts from :mod:`ekte.report.performance`. The CLI
(``--format pdf``) and the web UI's PDF download both call :func:`render_pdf`,
so the two always produce the same document.

Relay-controlled text is escaped before it reaches ReportLab's paragraph markup
(:func:`_t`), so it cannot inject markup, and the document references no
external resources: rendering never touches the network or the filesystem.

Fonts are the PDF standard fonts, so nothing is embedded or shipped: Helvetica
and Courier for Latin text, Symbol and ZapfDingbats for marks such as ✓ ✗ → Δ,
and the Adobe CID font STSong-Light for Chinese (and every other character the
Latin fonts lack), which PDF viewers supply themselves.
"""

from __future__ import annotations

import codecs
from collections.abc import Callable, Iterable
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.rl_codecs import RL_Codecs
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    Indenter,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ekte.models import AuditReport, DetectorResult, Finding, PerformanceReport, Status
from ekte.report import dimensions as dims
from ekte.report import palette
from ekte.report import performance as perf_render
from ekte.report.render import (
    _DISCLAIMER,
    _RISK_COLOR,
    _RISK_LABEL,
    _fmt_duration,
    _fmt_evidence_value,
    _fmt_score,
    _knowledge_lines,
    _run_config_meta,
)

# --------------------------------------------------------------------------- #
# Fonts: pick, per character, a standard font that has the glyph
# --------------------------------------------------------------------------- #
_CJK = "STSong-Light"
RL_Codecs.register()  # the "symbol" and "zapfdingbats" codecs
if _CJK not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(UnicodeCIDFont(_CJK))

_SKIP = {"\ufe0f", "\ufe0e", "\u200d"}  # emoji variation selectors / joiner


def _encodes(ch: str, encoding: str) -> bool:
    try:
        codecs.encode(ch, encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _font_for(ch: str, latin: str) -> str:
    if ch.isascii() or _encodes(ch, "cp1252"):  # Helvetica/Courier use WinAnsi
        return latin
    if _encodes(ch, "symbol"):
        return "Symbol"
    if _encodes(ch, "zapfdingbats"):
        return "ZapfDingbats"
    return _CJK


def _t(value: object, *, bold: bool = False, mono: bool = False,
       color: str | None = None, size: float | None = None, back: str | None = None) -> str:
    """Paragraph markup for (untrusted) text: escaped, each run in a font with its glyphs."""
    latin = ("Courier" if mono else "Helvetica") + ("-Bold" if bold else "")
    runs: list[tuple[str, list[str]]] = []
    for ch in str(value):
        if ch in _SKIP:
            continue
        if ch in "\r\n\t":
            ch = " "
        font = _font_for(ch, latin)
        if runs and runs[-1][0] == font:
            runs[-1][1].append(ch)
        else:
            runs.append((font, [ch]))
    attrs = ""
    if color:
        attrs += f' color="{color}"'
    if size:
        attrs += f' size="{size:g}"'
    if back:
        attrs += f' backColor="{back}"'
    return "".join(f'<font name="{font}"{attrs}>{escape("".join(chars))}</font>' for font, chars in runs)


# --------------------------------------------------------------------------- #
# Palette and styles (the HTML report's light theme: tokens.css via palette)
# --------------------------------------------------------------------------- #
_C = palette.LIGHT
_INK = _C["ink"]
_MUTED = _C["ink-muted"]
_LINE = _C["line"]
_HAIR = _C["line"]
_PANEL = _C["sunken"]
_ON_FILL = _C["on-primary"]  # text and icons on a solid status fill

_PILL: dict[str, tuple[str, str]] = {  # css class -> (background, text)
    "pass": (_C["success-tint"], _C["success"]),
    "warn": (_C["warning-tint"], _C["warning"]),
    "fail": (_C["danger-tint"], _C["danger"]),
    "info": (_C["info-tint"], _C["info"]),
    "muted": (_C["sunken"], _C["ink-muted"]),
}
_SEV_COLOR = {"info": _C["ink-muted"], "low": _C["warning"], "medium": _C["warning"],
              "high": _C["danger"], "critical": _C["danger"]}
_TARGET, _BASELINE, _CRITICAL, _CACHED = _C["chart-0"], _C["chart-2"], _C["danger"], _C["ink-muted"]
_TARGET_FADED = _C["heat-3"]  # the brand faded into the card, like the lighter audit-request dots
_GOOD, _BAD = _C["success"], _C["danger"]


def _var(css: str) -> str:
    """Resolve a ``var(--token)`` colour shared with the HTML report to its light value."""
    return _C[css[len("var(--") : -1]] if css.startswith("var(--") else css


_PAGE_W, _PAGE_H = A4
_MARGIN_X, _MARGIN_TOP, _MARGIN_BOTTOM = 12 * mm, 14 * mm, 16 * mm
_WIDTH = _PAGE_W - 2 * _MARGIN_X - 12  # the frame pads 6pt on each side


def _style(name: str, **kw: Any) -> ParagraphStyle:
    base: dict[str, Any] = {"fontName": "Helvetica", "fontSize": 9, "leading": 12.5,
                            "textColor": colors.HexColor(_INK), "spaceAfter": 3}
    base.update(kw)
    return ParagraphStyle(name, **base)


_S = {
    "title": _style("title", fontSize=18, leading=22, spaceAfter=4),
    "h2": _style("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=10,
                 spaceAfter=2),
    "h3": _style("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=13.5, spaceBefore=7,
                 spaceAfter=3),
    "h4": _style("h4", fontName="Helvetica-Bold", fontSize=9.5, leading=12.5, spaceBefore=5,
                 spaceAfter=2),
    "group": _style("group", fontName="Helvetica-Bold", fontSize=8.5, leading=11, spaceBefore=8,
                    textColor=colors.HexColor(_MUTED)),
    "body": _style("body"),
    "muted": _style("muted", textColor=colors.HexColor(_MUTED)),
    "meta": _style("meta", fontSize=8, leading=11, textColor=colors.HexColor(_MUTED), spaceAfter=1),
    "small": _style("small", fontSize=8, leading=10.5, spaceAfter=1),
    "sub": _style("sub", fontSize=8.5, leading=11, spaceBefore=4, spaceAfter=1),
    "bullet": _style("bullet", leftIndent=10, bulletIndent=2, spaceAfter=1.5),
    "cell": _style("cell", fontSize=8, leading=10, spaceAfter=0),
    "cell_num": _style("cell_num", fontSize=8, leading=10, spaceAfter=0, alignment=TA_RIGHT),
    "head": _style("head", fontName="Helvetica-Bold", fontSize=8, leading=10, spaceAfter=0,
                   textColor=colors.HexColor(_MUTED)),
    "head_num": _style("head_num", fontName="Helvetica-Bold", fontSize=8, leading=10, spaceAfter=0,
                       textColor=colors.HexColor(_MUTED), alignment=TA_RIGHT),
    "badge": _style("badge", fontName="Helvetica-Bold", fontSize=9.5, leading=12, spaceAfter=0,
                    textColor=colors.HexColor(_ON_FILL)),
    "warning": _style("warning", backColor=colors.HexColor(_C["warning-tint"]),
        borderColor=colors.HexColor(_C["warning-fill"]), borderWidth=0.6,
        borderPadding=(4, 6, 5, 6), leftIndent=6, rightIndent=6, spaceBefore=5, spaceAfter=5),
    "disclaimer": _style("disclaimer", fontSize=8, leading=11, textColor=colors.HexColor(_MUTED)),
}
for _name, _base in list(_S.items()):  # Chinese text wraps between any two characters
    _S[_name + "/cjk"] = ParagraphStyle(_name + "/cjk", parent=_base, wordWrap="CJK")


# Room a heading needs below it, or it moves to the next page. (Not keepWithNext:
# chained to a flowable taller than a page, ReportLab re-wraps it without end.)
_ROOM = {"h2": 90.0, "h3": 60.0, "h4": 48.0, "sub": 40.0, "group": 50.0}


def _head(markup: str, style: str) -> list[Flowable]:
    return [CondPageBreak(_ROOM[style]), _p(markup, style)]


def _p(markup: str, style: str = "body") -> Paragraph:
    """A paragraph of markup built with :func:`_t` (never raw untrusted text)."""
    return Paragraph(markup, _S[style + "/cjk"] if _CJK in markup else _S[style])


def _pill(status: Status) -> str:
    bg, fg = _PILL[dims._STATUS_CLASS.get(status, "muted")]
    return _t(f" {status.value.upper()} ", bold=True, size=7, color=fg, back=bg)


def _tag(text: str) -> str:
    return _t(f" {text} ", size=7, color=_MUTED, back=_HAIR)


def _code(text: object) -> str:
    return _t(text, mono=True, size=7.5, back=_HAIR)


def _h(text: str, level: str = "h2") -> list[Flowable]:
    out = _head(_t(text, bold=True), level)
    if level == "h2":
        out.append(_Rule())
    return out


class _Rule(Flowable):
    """A hairline under a section heading that stays with the heading."""

    def __init__(self, color: str = _LINE) -> None:
        super().__init__()
        self.color = color

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self.width = avail_width
        return avail_width, 6

    def draw(self) -> None:
        self.canv.setStrokeColor(colors.HexColor(self.color))
        self.canv.setLineWidth(0.6)
        self.canv.line(0, 4, self.width, 4)


def _bullets(items: Iterable[str], style: str = "bullet") -> list[Flowable]:
    return [Paragraph(m, _S[style + "/cjk"] if _CJK in m else _S[style], bulletText="•")
            for m in items]


def _table(header: list[str] | None, rows: list[list[str]], widths: list[float],
           num: Iterable[int] = (), *, back: str | None = None, font: float | None = None) -> Table:
    """A report table: hairline rows, muted header, right-aligned ``num`` columns.

    Cells are markup from :func:`_t`; the table splits across pages, inside a row if it must.
    """
    num = set(num)

    def cell(markup: str, col: int, head: bool) -> Paragraph:
        name = ("head" if head else "cell") + ("_num" if col in num else "")
        style = _S[name + "/cjk"] if _CJK in markup else _S[name]
        if font:
            style = ParagraphStyle(f"{style.name}/{font}", parent=style, fontSize=font,
                                   leading=font * 1.3)
        return Paragraph(markup, style)

    data = []
    if header is not None:
        data.append([cell(_t(h, bold=True), i, True) for i, h in enumerate(header)])
    data += [[cell(m, i, False) for i, m in enumerate(r)] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header is not None else 0, hAlign="LEFT",
              splitInRow=1)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor(_HAIR)),
    ]
    if header is not None:
        style.append(("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor(_LINE)))
    if back:
        style.append(("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(back)))
    t.setStyle(TableStyle(style))
    return t


def _fit(fractions: list[float], width: float = _WIDTH) -> list[float]:
    total = sum(fractions)
    return [width * f / total for f in fractions]


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
def _header(report: AuditReport) -> list[Flowable]:
    v = report.verdict
    out: list[Flowable] = [
        _p(_t("ekte audit ", bold=True) + _t(report.target.model, color=_MUTED), "title")
    ]
    label = _RISK_LABEL.get(v.risk_level, v.risk_level.value)
    badge = Table([[_p(_t(label, bold=True, color=_ON_FILL), "badge")]], hAlign="LEFT",
                  colWidths=[pdfmetrics.stringWidth(label, "Helvetica-Bold", 9.5) + 20])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1),
         colors.HexColor(_var(_RISK_COLOR.get(v.risk_level, "var(--ink-muted)")))),
        ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    out += [badge, Spacer(1, 6)]
    gap = " " * 6
    out.append(_p(
        _t(_fmt_score(v.overall_score), bold=True, size=12) + _t("/100") + gap
        + _t("rating ") + _t(v.rating or "—", bold=True) + gap
        + _t("confidence ") + _t(v.confidence, bold=True), "body"))
    meta = [
        _t("mode ") + _code(report.mode),
        _t("suite ") + _code(report.suite)
        + (_t(f" ({', '.join(report.dimensions_selected)})") if report.dimensions_selected else ""),
        _t("target ") + _code(report.target.name) + _t(" → ") + _code(report.target.base_url),
    ]
    if report.target.declared_provider:
        meta.append(_t("provider ") + _code(report.target.declared_provider))
    if report.baseline:
        meta.append(_t("baseline ") + _code(report.baseline.model))
    for label, value, note in _run_config_meta(report):
        meta.append(_t(f"{label} ") + _code(value) + (_t(f" ({note})") if note else ""))
    if report.judge_used:
        meta.append(_t("judge ") + _code(report.judge_model or "on"))
    if report.generated_at:
        meta.append(_t("generated ") + _code(report.generated_at))
    out.append(_p(_t(" · ").join(meta), "meta"))
    out.append(_p(_t(f"ekte v{report.tool_version}"), "meta"))
    return out


def _verdict(report: AuditReport) -> list[Flowable]:
    v = report.verdict
    out = _h("Verdict")
    if v.headline:
        out.append(_p(_t(v.headline, bold=True, size=10.5)))
    if v.summary:
        out.append(_p(_t(v.summary)))
    if v.key_findings:
        out += _h("Key findings", "h3")
        out += _bullets(_t(kf) for kf in v.key_findings)
    return out


def _dimensions(report: AuditReport) -> list[Flowable]:
    rows = [
        [_t(d.dimension.value), _t(_fmt_score(d.score)), _t(f"{d.weight:g}"), _pill(d.status)]
        for d in dims.all_dimensions(report)
    ]
    return _h("Dimensions") + [
        _table(["Dimension", "Score", "Weight", "Status"], rows, _fit([4, 1.2, 1.2, 2]), num=(1, 2))
    ]


def _dimension_details(report: AuditReport) -> list[Flowable]:
    out = _h("Dimension details")
    for d in dims.all_dimensions(report):
        members = dims._members(report, d)
        out += _head(_pill(d.status) + " " + _t(d.dimension.value, bold=True, size=10) + " "
                     + _tag(f"score {dims._num(d.score)}"), "h3")
        if members:
            notes = [dims.score_explanation(d, members), dims.status_explanation(d)]
        else:
            notes = [dims._not_run_reason(d)]
        out += [_p(_t(n), "muted") for n in notes]
        out.append(Indenter(left=10))
        for det in members:
            out += _dimension_detector(det)
        if d.dimension.value == "performance" and report.performance is not None:
            out += _performance(report.performance)
        out.append(Indenter(left=-10))
    return out


def _detector_title(det: DetectorResult, *tags: str) -> list[Flowable]:
    return _head(_t(det.name, bold=True) + " " + _pill(det.status) + "".join(
        " " + _tag(x) for x in tags), "h4")


def _dimension_detector(det: DetectorResult) -> list[Flowable]:
    width = _WIDTH - 10
    out = _detector_title(det, det.id, f"score {dims._num(det.score)}")
    if det.error:
        out.append(_p(_t(f"Detector error: {det.error}", color=_BAD)))
    if not det.findings:
        return out + [_p(_t("No findings."), "muted")]
    labels = dims._labels(det)
    if det.scoring is None:
        ordered = sorted(det.findings, key=lambda f: f.status not in dims._POSITIVE)
        return out + _bullets((_pill(f.status) + " " + _t(f.title) for f in ordered), "bullet")
    method = det.scoring.method
    rows, groups = [], []
    for row in dims._rows(det):
        if isinstance(row, dims._Group):
            groups.append(row)
            rows.append([_pill(row.status), _t(row.title), _t(row.outline(labels)),
                         _t(row.points(method))])
        else:
            rows.append([_pill(row.status), _t(row.title), _t(dims._label(labels, row)),
                         _t(dims._points(row, method))])
    out.append(_table(["", "Check", "Outcome", "Points"], rows, _fit([1.3, 3, 4.5, 1.3], width),
                      num=(3,)))
    for g in groups:
        out += _head(_t(f"{g.title}: all {len(g.findings)}", bold=True, size=8), "sub")
        sub = [
            [_pill(f.status), _code(f.subject or ""), _code(dims._observed(f)),
             _t(dims._label(labels, f)), _t(dims._points(f, method))]
            for f in g.findings
        ]
        out.append(_table(["", "Attribute", "Observed", "Outcome", "Points"], sub,
                          _fit([1.3, 2.6, 2.2, 3.4, 1], width), num=(4,), font=7.5))
    if method in dims._METHOD_NOTE:
        out.append(_p(_t(dims._METHOD_NOTE[method]), "muted"))
    titles = dims._check_titles(det)
    scale = _head(_t("Scoring scale", bold=True, size=8, color=_MUTED), "sub")
    for check, outcomes in dims._scale_by_check(det):
        scale.append(_p(_t(titles.get(check, check), size=8) + " " + _code(check), "small"))
        scale += _bullets(
            (_t(dims._scale_points(o, method), bold=True, size=8) + _t(f" — {o.label}", size=8)
             for o in outcomes), "bullet")
    out += scale
    return out


def _finding(f: Finding) -> Table:
    """One finding as a shaded panel; its rows split across pages if they must."""
    sev = f.severity.value
    rows: list[list[Any]] = [[_p(
        _pill(f.status) + " " + _t(sev.upper(), bold=True, size=7, color=_SEV_COLOR.get(sev, _MUTED))
        + " " + _t(f.title, bold=True), "body")]]
    if f.summary:
        rows.append([_p(_t(f.summary))])
    if f.evidence:
        ev = [[_t(k, color=_MUTED), _code(_fmt_evidence_value(v, k))]
              for k, v in list(f.evidence.items())[:12]]
        rows.append([_table(None, ev, _fit([1, 3], _WIDTH - 22))])
    if f.recommendation:
        rows.append([_p(_t(f"Recommendation: {f.recommendation}", color=_MUTED), "body")])
    return _panel(rows)


def _panel(rows: list[list[Any]], back: str = _PANEL, border: str = _HAIR) -> Table:
    t = Table(rows, colWidths=[_WIDTH - 10], hAlign="LEFT", splitInRow=1)  # long text may span pages
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(back)),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
    ]))
    return t


def _findings(report: AuditReport) -> list[Flowable]:
    out = _h("Findings")
    groups = [("Target", report.detectors)]
    if report.baseline_detectors:
        groups.append(("Baseline", report.baseline_detectors))
    for label, detectors in groups:
        if len(groups) > 1:
            out += _head(_t(label.upper(), bold=True), "group")
        if not detectors:
            out.append(_p(_t("No detectors ran."), "muted"))
            continue
        for det in detectors:
            out += _detector_title(det, det.id, det.dimension.value, f"score {_fmt_score(det.score)}")
            if det.error:
                out.append(_p(_t(f"Detector error: {det.error}", color=_BAD)))
            if not det.findings:
                out.append(_p(_t("No findings."), "muted"))
            shown, folded = dims.fold_passed_subjects(det)
            items: list[Flowable] = []
            for title, subjects in folded:
                items.append(_panel([
                    [_p(_pill(Status.PASS) + " " + _t(title, bold=True))],
                    [_p(_t(f"{len(subjects)} passed: ") + _code(", ".join(subjects))
                        + _t(" (points under Dimension details)"))],
                ]))
            items += [_finding(f) for f in shown]
            for item in items:
                out += [Indenter(left=5), item, Indenter(left=-5), Spacer(1, 4)]
    return out


def _reliability(report: AuditReport) -> list[Flowable]:
    r = report.reliability
    if r is None:
        return []
    items = [_t(f"Requests: {r.successes}/{r.requests} succeeded ({r.success_rate * 100:.0f}%)")]
    if r.rate_limited:
        items.append(_t(f"Rate-limited (429): {r.rate_limited} (excluded from success rate)"))
    parts = [f"{k} {_fmt_duration(v)}" for k, v in (r.latency_ms or {}).items() if v is not None]
    if parts:
        items.append(_t(f"Latency: {', '.join(parts)}"))
    if r.errors:
        items.append(_t("Errors: " + ", ".join(f"{k}: {n}" for k, n in r.errors.items())))
    return _h("Reliability") + _bullets(items)


def _knowledge(report: AuditReport) -> list[Flowable]:
    if report.knowledge is None:
        return []
    rows = [[_t(label, color=_MUTED), _code(value)] for label, value in _knowledge_lines(report.knowledge)]
    return _h("Knowledge base") + [_table(None, rows, _fit([1, 4]))]


def _notes_and_warnings(report: AuditReport) -> list[Flowable]:
    out: list[Flowable] = []
    if report.notes:
        out += _h("Notes") + _bullets(_t(n) for n in report.notes)
    if report.warnings:
        out += _h("Warnings")
        for w in report.warnings:  # shaded paragraphs: they split across pages on their own
            out += [_p(_t(w), "warning"), Spacer(1, 4)]
    return out


# --------------------------------------------------------------------------- #
# Performance (nested in the performance dimension's details)
# --------------------------------------------------------------------------- #
def _performance(perf: PerformanceReport) -> list[Flowable]:
    out: list[Flowable] = [
        CondPageBreak(120),
        *_head(_t("Performance measurements", bold=True), "h4"),
        _p(_t(f"{perf_render._source_line(perf)} {perf_render._scored_line(perf)}"), "muted"),
    ]
    calls = [r for r in perf.requests if r.op == "complete"]
    charts = [(m, _timeline(perf, m)) for m in perf_render.CHART_METRICS]
    drawn = [(m, d) for m, d in charts if d is not None]
    cells = [[_p(_t(f"{m[1]} ({m[2]})", bold=True, size=8), "small"), drawing] for m, drawing in drawn]
    if len(cells) % 2:
        cells.append([])
    if cells:
        grid = Table([cells[i:i + 2] for i in range(0, len(cells), 2)],
                     colWidths=[(_WIDTH - 10) / 2] * 2, hAlign="LEFT")
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        out.append(grid)
    if drawn:
        legend = [_t("●", color=_TARGET) + _t(" target")]
        if perf.baseline is not None:
            legend.append(_t("●", color=_BASELINE) + _t(" baseline"))
        if perf.source == "probe" and any(r.phase == "passive" for r in calls):
            legend.append(_t("●", color=_TARGET_FADED) + _t(" audit request (lighter)"))
        if any(r.phase != "passive" and not r.stream for r in calls):
            legend.append(_t("○", color=_TARGET) + _t(" non-streaming request (hollow)"))
        if any(not r.ok for r in calls):
            legend.append(_t("×", bold=True, color=_CRITICAL) + _t(" failed request"))
        out.append(_p((" " * 4).join(legend), "meta"))
    for block in perf_render._blocks(perf):
        out += _perf_block(perf, block)
    if perf.probe_cost is not None:
        pc = perf.probe_cost
        out.append(_p(_t(
            f"Probe cost: {pc.requests} requests, {pc.input_tokens_reported:,} input + "
            f"{pc.output_tokens_reported:,} output tokens (usage); "
            f"{pc.input_tokens_local:,} + {pc.output_tokens_local:,} (local count)."), "meta"))
    if perf.notes:
        out += _bullets(_t(n, color=_MUTED) for n in perf.notes)
    return out


def _perf_block(perf: PerformanceReport, block: perf_render.Block) -> list[Flowable]:
    mode, _, _, comparison = block
    width = _WIDTH - 10
    fmt = perf_render.fmt_num
    out: list[Flowable] = []
    title = perf_render._block_title(perf, mode)
    if title:
        out += _head(_t(title, bold=True), "h4")
    eps = perf_render._endpoints(block)
    visible = perf_render._visible_rows(eps)
    for e in eps:
        if len(eps) > 1:
            out += _head(_t(e.endpoint.capitalize(), bold=True, size=8.5), "sub")
        out.append(_p(_t(perf_render._reliability_line(e)), "meta"))
        out += _bullets(_t(x, size=8) for x in perf_render._extras(e))
        rows = [r for r in visible if r[2](e).count]
        if rows:
            body = []
            for label, unit, get in rows:
                s = get(e)
                body.append([_t(label) + _t(f" {unit}", color=_MUTED), _t(str(s.count))]
                            + [_t(fmt(getattr(s, c))) for c in perf_render.STAT_COLUMNS[1:]])
            cols = len(perf_render.STAT_COLUMNS)
            out.append(_table(["Metric", *perf_render.STAT_COLUMNS], body,
                              _fit([4.2] + [1] * cols, width), num=range(1, cols + 1), font=7))
        else:
            out.append(_p(_t("No successful requests to summarize."), "muted"))
        if e.ttft_by_input:
            body = [[_t(b.label), _t(str(b.count)), _t(fmt(b.ttft_p50_ms)), _t(fmt(b.latency_p50_ms))]
                    for b in e.ttft_by_input]
            out.append(Spacer(1, 4))
            out.append(_table(["Prompt size", "Requests", "TTFT p50 ms", "Latency p50 ms"], body,
                              _fit([2, 1, 1.2, 1.2], width * 0.6), num=(1, 2, 3), font=7.5))
    if comparison:
        out += _head(_t("Target vs baseline", bold=True, size=8.5), "sub")
        body = []
        for c in comparison:
            cls, mark = perf_render._verdict_mark(c)
            color = {"better": _GOOD, "worse": _BAD}.get(cls)
            delta = _t(mark + perf_render._signed(c.delta, c.unit), bold=color is not None, color=color)
            body.append([
                _t(perf_render.COMPARE_LABELS.get(c.metric, c.metric)) + _t(f" {c.unit}", color=_MUTED),
                _t(fmt(c.target, c.unit)), _t(fmt(c.baseline, c.unit)), delta,
                _t("—" if c.ratio is None else f"{c.ratio:.2f}x"),
            ])
        out.append(_table(["Metric", "Target", "Baseline", "Δ", "Ratio"], body,
                          _fit([4, 1.4, 1.4, 1.4, 1.1], width), num=(1, 2, 3, 4), font=7.5))
        out.append(_p(_t("✓ target better", bold=True, color=_GOOD) + _t(" · ")
                      + _t("✗ target worse", bold=True, color=_BAD)
                      + _t(" than the baseline (within 2% counts as even)."), "meta"))
    return out


def _timeline(perf: PerformanceReport, metric: tuple[str, str, str, Callable[..., Any]]) -> Drawing | None:
    """The HTML report's scatter of ``metric`` per request, as a vector drawing."""
    _, _label, unit, get = metric
    calls = [r for r in perf.requests if r.op == "complete"]
    plotted = [(r, v) for r in calls if r.ok and (v := get(r)) is not None]
    if not plotted:
        return None
    failed = [r for r in calls if not r.ok]
    w, h = (_WIDTH - 10) / 2 - 8, 120.0
    ml, mr, mt, mb = 34.0, 6.0, 6.0, 24.0
    pw, ph = w - ml - mr, h - mt - mb
    x_max, x_step, x_n = perf_render.nice_axis(
        max((r.start_ms + (r.duration_ms or 0)) / 1000 for r in calls) or 1.0)
    y_max, y_step, y_n = perf_render.nice_axis(max(v for _, v in plotted) * 1.05)

    def x(sec: float) -> float:
        return ml + sec / x_max * pw

    def y(val: float) -> float:
        return mb + val / y_max * ph

    d = Drawing(w, h)
    grid, tick = colors.HexColor(_HAIR), colors.HexColor(_MUTED)
    for i in range(y_n + 1):
        v = y_step * i
        d.add(Line(ml, y(v), w - mr, y(v), strokeColor=grid, strokeWidth=0.6))
        d.add(String(ml - 4, y(v) - 2.5, perf_render.fmt_num(v), fontName="Helvetica",
                     fontSize=6.5, fillColor=tick, textAnchor="end"))
    for i in range(x_n + 1):
        s = x_step * i
        anchor = "start" if i == 0 else "end" if i == x_n else "middle"
        d.add(String(x(s), mb - 10, f"{perf_render.fmt_num(s)}s", fontName="Helvetica",
                     fontSize=6.5, fillColor=tick, textAnchor=anchor))
    d.add(String(ml, 2, f"seconds since audit start · {unit}", fontName="Helvetica",
                 fontSize=6.5, fillColor=tick))
    for r, v in plotted:
        series = colors.HexColor(_BASELINE if r.endpoint == "baseline" else _TARGET)
        fill: Any = series
        stroke: Any = colors.HexColor(_C["surface"])
        opacity = 1.0
        if r.phase == "passive":
            opacity = 0.45
        if r.cached:
            fill, opacity = colors.HexColor(_CACHED), 0.6
        elif r.phase != "passive" and not r.stream:
            fill, stroke = colors.HexColor(_C["surface"]), series
        d.add(Circle(x(r.start_ms / 1000), y(v), 2.6, fillColor=fill, strokeColor=stroke,
                     strokeWidth=0.8, fillOpacity=opacity))
    red = colors.HexColor(_CRITICAL)
    for r in failed:
        cx, cy = x(r.start_ms / 1000), y(0)
        d.add(Line(cx - 2.6, cy - 2.6, cx + 2.6, cy + 2.6, strokeColor=red, strokeWidth=1.2))
        d.add(Line(cx - 2.6, cy + 2.6, cx + 2.6, cy - 2.6, strokeColor=red, strokeWidth=1.2))
    return d


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #
def _footer(report: AuditReport) -> Callable[[Any, Any], None]:
    left = _t(f"ekte audit — {report.target.model}", size=7, color=_MUTED)

    def draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        p = _p(left, "meta")
        p.wrapOn(canvas, _WIDTH * 0.75, 20)
        p.drawOn(canvas, _MARGIN_X, 8 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor(_MUTED))
        canvas.drawRightString(_PAGE_W - _MARGIN_X, 8 * mm + 2, f"page {doc.page}")
        canvas.restoreState()

    return draw


def render_pdf(report: AuditReport) -> bytes:
    """The audit report as PDF bytes (A4)."""
    story: list[Flowable] = []
    story += _header(report)
    story += _verdict(report)
    story += _dimensions(report)
    story += _dimension_details(report)
    story += _findings(report)
    story += _reliability(report)
    story += _knowledge(report)
    story += _notes_and_warnings(report)
    story += [Spacer(1, 10), _Rule(), _p(_t("Disclaimer. ", bold=True) + _t(_DISCLAIMER), "disclaimer")]

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_MARGIN_X, rightMargin=_MARGIN_X,
        topMargin=_MARGIN_TOP, bottomMargin=_MARGIN_BOTTOM,
        title=f"ekte audit — {report.target.model}", author="ekte", creator="ekte",
        subject="LLM relay audit report",
    )
    footer = _footer(report)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
