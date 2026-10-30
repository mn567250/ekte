"""Report renderers and writers.

The :class:`~zing.models.AuditReport` is the single source of truth; this package
turns it into the artifacts users consume: machine-readable JSON (the
LLM-facing API), human Markdown, a self-contained HTML page, and a PDF document
(typeset with ReportLab). ``write_reports`` persists the chosen format(s) to disk.
"""

from __future__ import annotations

from zing.report.render import (
    compact_dict,
    render_compact,
    render_html,
    render_json,
    render_markdown,
)
from zing.report.writer import render_pdf, report_stem, write_reports

__all__ = [
    "write_reports",
    "render_json",
    "render_compact",
    "compact_dict",
    "render_markdown",
    "render_html",
    "render_pdf",
    "report_stem",
]
