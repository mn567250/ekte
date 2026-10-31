"""Render an :class:`~ekte.models.AuditReport` to JSON, Markdown, or HTML.

JSON is the canonical machine output (the model's own ``model_dump_json``, so its
field names match :mod:`ekte.models` exactly). Markdown and HTML are derived,
human-facing views of the same data — they never invent facts the report does not
carry, and every relay/user string is escaped before it reaches HTML (via
:func:`_esc`) or Markdown (via :func:`_md`), so relay-controlled text cannot inject
markup, break tables, or spoof structure.

All three renderers are pure: they take a report and return a string. ekte reports
black-box evidence of divergence and risk, not proof of fraud; the disclaimer in
each human view says so.
"""

from __future__ import annotations

import html
import json
from decimal import Decimal
from typing import Any

from ekte.models import (
    AuditReport,
    KnowledgeUsage,
    RedactedTarget,
    RiskLevel,
    Severity,
    Status,
)
from ekte.report import dimensions as dimension_details
from ekte.report import palette
from ekte.report.performance import (
    PERF_CSS,
    compact_performance,
)

_DISCLAIMER = (
    "ekte performs black-box auditing. It gathers reproducible evidence of "
    "behavioral divergence and risk — not cryptographic proof of model identity "
    "or fraud. Treat findings as signals to investigate, review sample size and "
    "cost, and consider `ekte compare` against a trusted baseline of the same "
    "declared model before drawing conclusions."
)

# Risk presentation, shared shape with the CLI's _RISK_STYLE.
_RISK_LABEL: dict[RiskLevel, str] = {
    RiskLevel.CLEAN: "CLEAN",
    RiskLevel.LOW: "LOW RISK",
    RiskLevel.MEDIUM: "MEDIUM RISK",
    RiskLevel.HIGH: "HIGH RISK",
    RiskLevel.INCONCLUSIVE: "INCONCLUSIVE",
}
_RISK_COLOR: dict[RiskLevel, str] = {
    RiskLevel.CLEAN: "var(--success)",
    RiskLevel.LOW: "var(--info)",
    RiskLevel.MEDIUM: "var(--warning)",  # not --warning-fill: the label needs >= 4.5:1
    RiskLevel.HIGH: "var(--danger)",
    RiskLevel.INCONCLUSIVE: "var(--ink-muted)",
}

# The performance probe's configured request mode (AuditReport.stream_mode).
_STREAM_MODE_LABEL: dict[str, str] = {
    "stream": "streaming",
    "non_stream": "non-streaming",
    "both": "streaming + non-streaming",
}


def _protocol_bits(t: RedactedTarget) -> tuple[str, str] | None:
    """(protocol, how it was chosen) of a target, or None for an old report."""
    if not t.api:
        return None
    if t.api_auto is None:
        return t.api, ""
    return t.api, "auto-detected" if t.api_auto else "set manually"


def _run_config_meta(report: AuditReport) -> list[tuple[str, str, str]]:
    """(label, value, note) meta entries for the protocol and probe request mode."""
    out: list[tuple[str, str, str]] = []
    proto = _protocol_bits(report.target)
    if proto:
        out.append(("protocol", proto[0], proto[1]))
    if report.baseline is not None:
        bproto = _protocol_bits(report.baseline)
        if bproto:
            out.append(("baseline protocol", bproto[0], bproto[1]))
    if report.stream_mode:
        out.append(("requests", _STREAM_MODE_LABEL.get(report.stream_mode, report.stream_mode), ""))
    return out


_SEVERITY_EMOJI: dict[Severity, str] = {
    Severity.INFO: "ℹ️",
    Severity.LOW: "🟡",
    Severity.MEDIUM: "🟠",
    Severity.HIGH: "🔴",
    Severity.CRITICAL: "⛔",
}
_STATUS_EMOJI: dict[Status, str] = {
    Status.PASS: "✅",
    Status.WARN: "⚠️",
    Status.FAIL: "❌",
    Status.INCONCLUSIVE: "❔",
    Status.NOT_RUN: "➖",
    Status.INFO: "ℹ️",
    Status.ERROR: "💥",
}


# --------------------------------------------------------------------------- #
# Small shared formatters
# --------------------------------------------------------------------------- #
def _fmt_score(score: float | None) -> str:
    return "—" if score is None else f"{score:g}"


def _fmt_duration(ms: float) -> str:
    """A duration in mixed units, only those it needs: ``850 µs``, ``457 ms``,
    ``6 s 97 ms``, ``1 min 5 s``, ``2 h 3 min 4 s``."""
    sign = "-" if ms < 0 else ""
    ms = abs(ms)
    if ms == 0:
        return "0 ms"
    if ms < 1:
        return f"{sign}{ms * 1000:.0f} µs"
    if ms < 10:
        return f"{sign}{ms:.1f} ms".replace(".0 ms", " ms")
    total_ms = round(ms)
    if total_ms < 1000:
        return f"{sign}{total_ms} ms"
    if total_ms < 60_000:
        parts = [(total_ms // 1000, "s"), (total_ms % 1000, "ms")]
    else:
        total_s = round(ms / 1000)
        parts = [(total_s // 3600, "h"), (total_s // 60 % 60, "min"), (total_s % 60, "s")]
    while parts and parts[0][0] == 0:
        parts.pop(0)
    return sign + " ".join(f"{n} {unit}" for n, unit in parts if n)


def _fmt_float(value: float) -> str:
    """Three significant digits, never in scientific notation."""
    text = f"{value:.3g}"
    if "e" not in text:
        return text
    if abs(value) >= 1000:
        return f"{value:.0f}"
    return format(Decimal(text), "f")


def _duration_ms(key: str, value: object) -> float | None:
    """The value in milliseconds when the evidence key names a duration."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if key.endswith("_ms"):
        return float(value)
    if key.endswith(("_s", "_sec", "_seconds")):
        return float(value) * 1000
    return None


def _fmt_evidence_value(value: object, key: str = "") -> str:
    """Compact, single-line rendering of one evidence value for a highlight.

    ``key`` is the evidence key: ``*_ms``/``*_s`` values render as durations."""
    ms = _duration_ms(key, value)
    if ms is not None:
        text = _fmt_duration(ms)
    elif isinstance(value, float):
        text = _fmt_float(value)
    elif isinstance(value, (list, tuple)):
        items = ", ".join(_fmt_evidence_value(v, key) for v in list(value)[:6])
        if len(value) > 6:
            items += ", …"
        text = f"[{items}]"
    elif isinstance(value, dict):
        text = "{…}"
    else:
        text = str(value)
    text = " ".join(text.split())  # collapse whitespace/newlines
    return text if len(text) <= 160 else text[:157] + "…"


# Markdown metacharacters that let untrusted text break out of an inline context
# (tables, code spans, emphasis, links, raw HTML) or inject block structure.
_MD_ESCAPE = ("\\", "`", "|", "*", "_", "{", "}", "[", "]", "<", ">", "#")


def _md(value: object) -> str:
    """Escape a relay/user-controlled string for safe inline Markdown.

    Newlines are collapsed first so the text cannot escape its list item and inject
    a heading or table row; then Markdown metacharacters are backslash-escaped.
    """
    text = " ".join(str(value).split())
    for ch in _MD_ESCAPE:
        text = text.replace(ch, "\\" + ch)
    return text


def render_json(report: AuditReport) -> str:
    """Canonical machine output — field names match :mod:`ekte.models` exactly."""
    return report.model_dump_json(indent=2)


# --------------------------------------------------------------------------- #
# Compact JSON — a lean, agent/LLM-facing view (no bulky evidence)
# --------------------------------------------------------------------------- #
def _compact_finding(dimension: str, finding) -> dict:
    out = {
        "dimension": dimension,
        "id": finding.id,
        "severity": finding.severity.value,
        "status": finding.status.value,
        "title": finding.title,
    }
    # Only the actionable findings carry their summary/recommendation; pass/info
    # findings stay one line so the payload stays small.
    if finding.score is not None:
        out["points"] = finding.score
    if finding.status in (Status.WARN, Status.FAIL, Status.ERROR):
        if finding.summary:
            out["summary"] = finding.summary
        if finding.recommendation:
            out["recommendation"] = finding.recommendation
    return out


def compact_dict(report: AuditReport) -> dict:
    """A small, stable dict an agent can read without ingesting full evidence.

    ~5-10x smaller than the full report: verdict + per-dimension status + a flat
    findings list (severity/status/title, plus summary only for warn/fail/error).
    """
    v = report.verdict
    t = report.target
    target: dict[str, Any] = {"name": t.name, "model": t.model, "base_url": t.base_url}
    if t.claimed_model:
        target["claimed_model"] = t.claimed_model
    if t.declared_provider:
        target["provider"] = t.declared_provider
    if t.api:
        target["api"] = t.api
        target["api_auto"] = t.api_auto

    rel = None
    if report.reliability:
        r = report.reliability
        rel = {
            "requests": r.requests,
            "successes": r.successes,
            "success_rate": round(r.success_rate, 4),
            "rate_limited": r.rate_limited,
            "latency_p95_ms": r.latency_ms.get("p95"),
        }

    return {
        "schema_version": report.schema_version,
        "tool": "ekte",
        "version": report.tool_version,
        "generated_at": report.generated_at,
        "mode": report.mode,
        "suite": report.suite,
        "dimensions_selected": report.dimensions_selected,
        "stream_mode": report.stream_mode,
        "target": target,
        "baseline": (
            {
                "model": report.baseline.model,
                "base_url": report.baseline.base_url,
                "api": report.baseline.api,
                "api_auto": report.baseline.api_auto,
            }
            if report.baseline
            else None
        ),
        "verdict": {
            "risk": v.risk_level.value,
            "score": v.overall_score,
            "rating": v.rating,
            "confidence": v.confidence,
            "headline": v.headline,
            "summary": v.summary,
            "key_findings": v.key_findings,
        },
        "dimensions": {
            d.dimension.value: {"score": d.score, "status": d.status.value}
            for d in report.dimensions
            if d.status != Status.NOT_RUN
        },
        "findings": [
            _compact_finding(det.dimension.value, f)
            for det in report.detectors
            for f in det.findings
        ],
        "reliability": rel,
        "performance": compact_performance(report.performance),
        "judge_used": report.judge_used,
        "knowledge": _compact_knowledge(report.knowledge),
        "warnings": report.warnings or [],
    }


def _knowledge_lines(k: KnowledgeUsage) -> list[tuple[str, str]]:
    """(label, value) rows describing the knowledge-base profile a run used."""
    rows: list[tuple[str, str]] = []
    if k.kb_date:
        rows.append(("Knowledge-base date", k.kb_date))
    if not k.matched:
        rows += [("Profile", f"none — no knowledge-base profile matches `{k.requested_model}`")]
    else:
        rows += [
            ("Profile", f"{k.provider}/{k.model_id} (match: {k.match_confidence}"
                        f"{', pinned by the watch' if k.pinned else ''})"),
            ("Model source", k.model_source or "—"),
            ("Provider source", k.provider_source or "—"),
        ]
        if k.shadows:
            rows.append(("Shadows", k.shadows))
        for e in k.user_entries:
            what = f"model {e.provider}/{e.model_id}" if e.kind == "model" else f"provider {e.provider}"
            origin = f", from {e.origin}" if e.origin else ""
            rows.append(("Your entry", f"kb.db entry {e.id}: {what}{origin}"))
        rows.append(("Profile hash", k.profile_hash or "—"))
    if not k.user_kb:
        rows.append(("Your entries", "left out (--no-user-kb)"))
    for w in k.warnings:
        rows.append(("Skipped", w))
    return rows


def _compact_knowledge(k: KnowledgeUsage | None) -> dict | None:
    if k is None:
        return None
    return {
        "kb_date": k.kb_date,
        "matched": k.matched,
        "provider": k.provider,
        "model_id": k.model_id,
        "match_confidence": k.match_confidence,
        "source": k.model_source,
        "user_entries": [e.id for e in k.user_entries],
        "user_kb": k.user_kb,
        "pinned": k.pinned,
        "profile_hash": k.profile_hash,
    }


def render_compact(report: AuditReport) -> str:
    """Lean JSON for agents/LLMs — verdict + findings without bulky evidence."""
    return json.dumps(compact_dict(report), ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def render_markdown(report: AuditReport) -> str:
    v = report.verdict
    lines: list[str] = []

    risk_label = _RISK_LABEL.get(v.risk_level, v.risk_level.value)
    score = _fmt_score(v.overall_score)
    rating = v.rating or "—"
    lines.append(f"# ekte audit — {report.target.model}")
    lines.append("")
    lines.append(
        f"**Risk:** {risk_label}  ·  **Score:** {score}/100  ·  "
        f"**Rating:** {rating}  ·  **Confidence:** {v.confidence}"
    )
    lines.append("")

    # Metadata line.
    meta = [
        f"mode `{report.mode}`",
        f"suite `{report.suite}`"
        + (f" ({', '.join(report.dimensions_selected)})" if report.dimensions_selected else ""),
        f"target `{report.target.name}` → `{report.target.base_url}`",
    ]
    if report.target.declared_provider:
        meta.append(f"provider `{report.target.declared_provider}`")
    if report.baseline:
        meta.append(f"baseline `{report.baseline.model}`")
    for label, value, note in _run_config_meta(report):
        meta.append(f"{label} `{value}`" + (f" ({note})" if note else ""))
    if report.judge_used:
        meta.append(f"judge `{report.judge_model or 'on'}`")
    if report.generated_at:
        meta.append(f"generated `{report.generated_at}`")
    lines.append("  ·  ".join(meta))
    lines.append(f"\n_ekte v{report.tool_version}_")
    lines.append("")

    # Verdict.
    lines.append("## Verdict")
    lines.append("")
    if v.headline:
        lines.append(f"**{v.headline}**")
        lines.append("")
    if v.summary:
        lines.append(_md(v.summary))
        lines.append("")
    if v.key_findings:
        lines.append("**Key findings**")
        lines.append("")
        for kf in v.key_findings:
            lines.append(f"- {_md(kf)}")
        lines.append("")

    # Dimensions table.
    lines.append("## Dimensions")
    lines.append("")
    lines.append("| Dimension | Score | Weight | Status |")
    lines.append("| --- | ---: | ---: | --- |")
    for d in dimension_details.all_dimensions(report):
        emoji = _STATUS_EMOJI.get(d.status, "")
        lines.append(
            f"| {d.dimension.value} | {_fmt_score(d.score)} | "
            f"{d.weight:g} | {emoji} {d.status.value} |"
        )
    lines.append("")
    lines.extend(dimension_details.markdown_section(report, _md))

    # Findings grouped per detector.
    lines.append("## Findings")
    lines.append("")
    detector_groups = [("Target", report.detectors)]
    if report.baseline_detectors:
        detector_groups.append(("Baseline", report.baseline_detectors))

    for group_label, detectors in detector_groups:
        if len(detector_groups) > 1:
            lines.append(f"### {group_label}")
            lines.append("")
        if not detectors:
            lines.append("_No detectors ran._")
            lines.append("")
            continue
        for det in detectors:
            det_emoji = _STATUS_EMOJI.get(det.status, "")
            score_txt = _fmt_score(det.score)
            lines.append(
                f"### {det_emoji} {det.name} "
                f"(`{det.id}` · {det.dimension.value} · score {score_txt})"
            )
            lines.append("")
            if det.error:
                lines.append(f"> Detector error: {_md(det.error)}")
                lines.append("")
            if not det.findings:
                lines.append("_No findings._")
                lines.append("")
                continue
            shown, folded = dimension_details.fold_passed_subjects(det)
            for title, subjects in folded:
                lines.append(
                    f"- ✅ **{_md(title)}** — {len(subjects)} passed: "
                    f"{_md(', '.join(subjects))} (points under Dimension details)"
                )
            for f in shown:
                sev = _SEVERITY_EMOJI.get(f.severity, "")
                stat = _STATUS_EMOJI.get(f.status, "")
                lines.append(
                    f"- {stat} **{_md(f.title)}** — {sev} {f.severity.value} / {f.status.value}"
                )
                if f.summary:
                    lines.append(f"  - {_md(f.summary)}")
                for key, value in list(f.evidence.items())[:8]:
                    lines.append(f"  - `{_md(key)}`: {_md(_fmt_evidence_value(value, key))}")
                if f.recommendation:
                    lines.append(f"  - _Recommendation: {_md(f.recommendation)}_")
            lines.append("")

    # Reliability.
    if report.reliability:
        r = report.reliability
        lines.append("## Reliability")
        lines.append("")
        lines.append(
            f"- Requests: {r.successes}/{r.requests} succeeded "
            f"({r.success_rate * 100:.0f}%)"
        )
        if r.rate_limited:
            lines.append(f"- Rate-limited (429): {r.rate_limited} (excluded from success rate)")
        if r.latency_ms:
            parts = [
                f"{k} {_fmt_duration(v)}"
                for k, v in r.latency_ms.items()
                if v is not None
            ]
            if parts:
                lines.append(f"- Latency: {', '.join(parts)}")
        if r.errors:
            errs = ", ".join(f"{k}: {n}" for k, n in r.errors.items())
            lines.append(f"- Errors: {errs}")
        lines.append("")

    if report.knowledge is not None:
        lines.append("## Knowledge base")
        lines.append("")
        for label, value in _knowledge_lines(report.knowledge):
            lines.append(f"- **{label}:** {_md(value)}")
        lines.append("")

    # Notes & warnings.
    if report.notes:
        lines.append("## Notes")
        lines.append("")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")
    if report.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in report.warnings:
            lines.append(f"- ⚠️ {_md(w)}")
        lines.append("")

    # Disclaimer footer.
    lines.append("---")
    lines.append("")
    lines.append(f"> **Disclaimer.** {_DISCLAIMER}")
    lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


_STATUS_CLASS: dict[Status, str] = {
    Status.PASS: "pass",
    Status.WARN: "warn",
    Status.FAIL: "fail",
    Status.INCONCLUSIVE: "muted",
    Status.NOT_RUN: "muted",
    Status.INFO: "info",
    Status.ERROR: "fail",
}


def render_html(report: AuditReport) -> str:
    v = report.verdict
    risk_label = _RISK_LABEL.get(v.risk_level, v.risk_level.value)
    risk_color = _RISK_COLOR.get(v.risk_level, "var(--ink-muted)")
    score = _fmt_score(v.overall_score)
    rating = v.rating or "—"

    out: list[str] = []
    out.append("<!DOCTYPE html>")
    out.append('<html lang="en"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append(f"<title>ekte audit — {_esc(report.target.model)}</title>")
    out.append(_CSS)
    out.append("</head><body><main>")

    # Header + risk badge.
    out.append('<header class="report-head">')
    out.append(f"<h1>ekte audit <span class=\"model\">{_esc(report.target.model)}</span></h1>")
    out.append(
        f'<div class="badge" style="background:{risk_color}">{_esc(risk_label)}</div>'
    )
    out.append('<div class="scoreline">')
    out.append(f"<span><strong>{_esc(score)}</strong>/100</span>")
    out.append(f"<span>rating <strong>{_esc(rating)}</strong></span>")
    out.append(f"<span>confidence <strong>{_esc(v.confidence)}</strong></span>")
    out.append("</div>")
    # Metadata.
    meta_bits = [
        f"mode <code>{_esc(report.mode)}</code>",
        f"suite <code>{_esc(report.suite)}</code>"
        + (
            f" ({_esc(', '.join(report.dimensions_selected))})"
            if report.dimensions_selected
            else ""
        ),
        f"target <code>{_esc(report.target.name)}</code> → <code>{_esc(report.target.base_url)}</code>",
    ]
    if report.target.declared_provider:
        meta_bits.append(f"provider <code>{_esc(report.target.declared_provider)}</code>")
    if report.baseline:
        meta_bits.append(f"baseline <code>{_esc(report.baseline.model)}</code>")
    for label, value, note in _run_config_meta(report):
        meta_bits.append(
            f"{_esc(label)} <code>{_esc(value)}</code>" + (f" ({_esc(note)})" if note else "")
        )
    if report.judge_used:
        meta_bits.append(f"judge <code>{_esc(report.judge_model or 'on')}</code>")
    if report.generated_at:
        meta_bits.append(f"generated <code>{_esc(report.generated_at)}</code>")
    out.append(f'<p class="meta">{" · ".join(meta_bits)}</p>')
    out.append(f'<p class="meta">ekte v{_esc(report.tool_version)}</p>')
    out.append("</header>")

    # Verdict.
    out.append('<section class="card">')
    out.append("<h2>Verdict</h2>")
    if v.headline:
        out.append(f"<p class=\"headline\">{_esc(v.headline)}</p>")
    if v.summary:
        out.append(f"<p>{_esc(v.summary)}</p>")
    if v.key_findings:
        out.append("<h3>Key findings</h3><ul>")
        for kf in v.key_findings:
            out.append(f"<li>{_esc(kf)}</li>")
        out.append("</ul>")
    out.append("</section>")

    # Dimensions table.
    out.append('<section class="card"><h2>Dimensions</h2>')
    out.append('<table><thead><tr>'
                "<th>Dimension</th><th class=\"num\">Score</th>"
                "<th class=\"num\">Weight</th><th>Status</th>"
                "</tr></thead><tbody>")
    for d in dimension_details.all_dimensions(report):
        cls = _STATUS_CLASS.get(d.status, "muted")
        out.append(
            "<tr>"
            f"<td>{_esc(d.dimension.value)}</td>"
            f'<td class="num">{_esc(_fmt_score(d.score))}</td>'
            f'<td class="num">{_esc(f"{d.weight:g}")}</td>'
            f'<td><span class="pill {cls}">{_esc(d.status.value)}</span></td>'
            "</tr>"
        )
    out.append("</tbody></table>")
    out.append("</section>")
    out.append(dimension_details.html_section(report))

    # Findings per detector.
    detector_groups = [("Target", report.detectors)]
    if report.baseline_detectors:
        detector_groups.append(("Baseline", report.baseline_detectors))

    out.append('<section class="card"><h2>Findings</h2>')
    for group_label, detectors in detector_groups:
        if len(detector_groups) > 1:
            out.append(f"<h3 class=\"group\">{_esc(group_label)}</h3>")
        if not detectors:
            out.append('<p class="muted">No detectors ran.</p>')
            continue
        for det in detectors:
            det_cls = _STATUS_CLASS.get(det.status, "muted")
            out.append('<div class="detector">')
            out.append(
                '<h3 class="det-title">'
                f"{_esc(det.name)} "
                f'<span class="pill {det_cls}">{_esc(det.status.value)}</span> '
                f'<span class="tag">{_esc(det.id)}</span> '
                f'<span class="tag">{_esc(det.dimension.value)}</span> '
                f'<span class="tag">score {_esc(_fmt_score(det.score))}</span>'
                "</h3>"
            )
            if det.error:
                out.append(f'<p class="fail">Detector error: {_esc(det.error)}</p>')
            if not det.findings:
                out.append('<p class="muted">No findings.</p>')
            shown, folded = dimension_details.fold_passed_subjects(det)
            for title, subjects in folded:
                out.append(
                    '<div class="finding"><p class="f-head"><span class="pill pass">pass</span> '
                    f"<strong>{_esc(title)}</strong></p><p>{len(subjects)} passed: "
                    f"<code>{_esc(', '.join(subjects))}</code> (points under Dimension details)</p></div>"
                )
            for f in shown:
                f_cls = _STATUS_CLASS.get(f.status, "muted")
                sev = _esc(f.severity.value)
                out.append('<div class="finding">')
                out.append(
                    '<p class="f-head">'
                    f'<span class="pill {f_cls}">{_esc(f.status.value)}</span> '
                    f'<span class="sev sev-{sev}">{sev}</span> '
                    f"<strong>{_esc(f.title)}</strong></p>"
                )
                if f.summary:
                    out.append(f"<p>{_esc(f.summary)}</p>")
                if f.evidence:
                    out.append('<table class="evidence"><tbody>')
                    for key, value in list(f.evidence.items())[:12]:
                        out.append(
                            "<tr>"
                            f"<td class=\"ekey\">{_esc(key)}</td>"
                            f"<td><code>{_esc(_fmt_evidence_value(value, key))}</code></td>"
                            "</tr>"
                        )
                    out.append("</tbody></table>")
                if f.recommendation:
                    out.append(f'<p class="rec">Recommendation: {_esc(f.recommendation)}</p>')
                out.append("</div>")
            out.append("</div>")
    out.append("</section>")

    # Reliability.
    if report.reliability:
        r = report.reliability
        out.append('<section class="card"><h2>Reliability</h2><ul>')
        out.append(
            f"<li>Requests: {r.successes}/{r.requests} succeeded "
            f"({r.success_rate * 100:.0f}%)</li>"
        )
        if r.rate_limited:
            out.append(
                f"<li>Rate-limited (429): {r.rate_limited} (excluded from success rate)</li>"
            )
        if r.latency_ms:
            parts = [
                f"{_esc(k)} {_esc(_fmt_duration(v))}"
                for k, v in r.latency_ms.items()
                if v is not None
            ]
            if parts:
                out.append(f"<li>Latency: {', '.join(parts)}</li>")
        if r.errors:
            errs = ", ".join(f"{_esc(k)}: {n}" for k, n in r.errors.items())
            out.append(f"<li>Errors: {errs}</li>")
        out.append("</ul></section>")

    if report.knowledge is not None:
        out.append('<section class="card"><h2>Knowledge base</h2><table class="evidence"><tbody>')
        for label, value in _knowledge_lines(report.knowledge):
            out.append(f'<tr><td class="ekey">{_esc(label)}</td><td><code>{_esc(value)}</code></td></tr>')
        out.append("</tbody></table></section>")

    # Notes & warnings.
    if report.notes:
        out.append('<section class="card"><h2>Notes</h2><ul>')
        for n in report.notes:
            out.append(f"<li>{_esc(n)}</li>")
        out.append("</ul></section>")
    if report.warnings:
        out.append('<section class="card warnings"><h2>Warnings</h2><ul>')
        for w in report.warnings:
            out.append(f"<li>{_esc(w)}</li>")
        out.append("</ul></section>")

    # Disclaimer.
    out.append(f'<footer class="disclaimer"><strong>Disclaimer.</strong> {_esc(_DISCLAIMER)}</footer>')
    out.append("</main></body></html>")

    return "".join(out)


_CSS = "<style>" + palette.tokens_css() + """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1rem;
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--ink); background: var(--bg);
}
main { max-width: 920px; margin: 0 auto; }
h1 { font-size: 1.7rem; margin: 0 0 .25rem; }
h1 .model { font-weight: 500; color: var(--ink-muted); }
h2 { font-size: 1.2rem; margin: 0 0 .75rem; border-bottom: 1px solid var(--line); padding-bottom: .35rem; }
h3 { font-size: 1rem; margin: 1rem 0 .5rem; }
h3.group { color: var(--ink-muted); text-transform: uppercase; letter-spacing: .04em; font-size: .8rem; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .85em;
  background: var(--sunken); padding: .1em .35em; border-radius: 4px; }
.report-head { margin-bottom: 1.5rem; }
.badge { display: inline-block; color: var(--on-primary); font-weight: 700; letter-spacing: .03em;
  padding: .35rem .9rem; border-radius: 999px; font-size: .9rem; margin: .25rem 0 .75rem; }
.scoreline { display: flex; gap: 1.5rem; flex-wrap: wrap; font-size: 1.05rem; margin-bottom: .5rem; }
.scoreline strong { font-size: 1.15rem; }
.meta { color: var(--ink-muted); font-size: .85rem; margin: .2rem 0; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 1.1rem 1.25rem; margin-bottom: 1.25rem; }
.card.warnings { border-color: var(--warning-fill); background: var(--warning-tint); }
.headline { font-size: 1.1rem; font-weight: 600; margin: 0 0 .5rem; }
table { width: 100%; border-collapse: collapse; font-size: .92rem; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--ink-muted); font-weight: 600; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.pill { display: inline-block; padding: .05rem .5rem; border-radius: 999px;
  font-size: .78rem; font-weight: 600; text-transform: uppercase; letter-spacing: .02em; }
.pill.pass { background: var(--success-tint); color: var(--success); }
.pill.warn { background: var(--warning-tint); color: var(--warning); }
.pill.fail { background: var(--danger-tint); color: var(--danger); }
.pill.info { background: var(--info-tint); color: var(--info); }
.pill.muted { background: var(--sunken); color: var(--ink-muted); }
.muted { color: var(--ink-muted); }
.fail { color: var(--danger); }
.tag { display: inline-block; background: var(--sunken); color: var(--ink-muted); border-radius: 4px;
  padding: .05rem .4rem; font-size: .75rem; font-weight: 500; margin-left: .25rem; }
.detector { border-top: 1px solid var(--line); padding-top: .75rem; margin-top: .75rem; }
.detector:first-of-type { border-top: 0; padding-top: 0; margin-top: 0; }
.det-title { display: flex; align-items: center; flex-wrap: wrap; gap: .3rem; }
.finding { background: var(--sunken); border: 1px solid var(--line); border-radius: 8px;
  padding: .6rem .75rem; margin: .5rem 0; }
.f-head { margin: 0 0 .35rem; }
.sev { font-size: .75rem; font-weight: 700; text-transform: uppercase; }
.sev-info { color: var(--ink-muted); } .sev-low { color: var(--warning); } .sev-medium { color: var(--warning); }
.sev-high { color: var(--danger); } .sev-critical { color: var(--danger); }
table.evidence { font-size: .85rem; margin: .35rem 0; }
table.evidence td { border-bottom: 1px solid var(--line); padding: .25rem .5rem; }
td.ekey { color: var(--ink-muted); white-space: nowrap; font-weight: 500; }
.rec { font-style: italic; color: var(--ink-muted); margin: .35rem 0 0; }
.disclaimer { color: var(--ink-muted); font-size: .85rem; border-top: 1px solid var(--line);
  padding-top: 1rem; margin-top: 1.5rem; }
@page { size: A4; margin: 14mm 12mm; }
@media print {
  body { padding: 0; background: var(--surface); font-size: 12px; }
  main { max-width: none; }
  .card { break-inside: auto; }
  .finding, tr, .badge, h2, h3 { break-inside: avoid; }
  h2, h3 { break-after: avoid; }
}
""" + dimension_details.DIM_CSS + PERF_CSS + """</style>"""
