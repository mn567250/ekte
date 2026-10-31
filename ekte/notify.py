"""Webhook alerting for scheduled re-audits.

`ekte watch` re-runs an audit on an interval and, when the verdict crosses a risk
threshold (or regresses versus the previous saved run), POSTs a concise alert to
one or more webhooks. Alerts are written in the watch's language (``lang``; English
by default, any language in ``ekte/i18n/locales``), including the verdict headline
and the key findings. This module owns two concerns:

* **Formatting** — turning an :class:`~ekte.models.AuditReport` dict into the
  body each chat platform expects (generic JSON, Slack, Feishu/Lark, DingTalk).
  The text is intentionally compact: a single human-readable digest of risk,
  score, target, and the top key findings, with an optional "since last run"
  delta when a previous report is supplied.
* **Delivery** — :func:`send` auto-detects the platform from the webhook host
  (or takes an explicit ``kind``), POSTs via ``httpx`` (a core dependency), and
  returns whether it succeeded. It never raises: an unreachable webhook must not
  abort the watch loop.

Everything operates on plain report *dicts* (``AuditReport.model_dump()`` /
``json.loads(report.model_dump_json())``) so callers don't have to import the
pydantic models, and so a report loaded back from history works unchanged.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from ekte import i18n
from ekte.clients.base import get_ssl_context
from ekte.models import WEBHOOK_SCHEMA_VERSION, RiskLevel

# Ordering used to decide whether the current risk is *worse* than the previous
# run. INCONCLUSIVE deliberately sits below LOW: an inconclusive result is not a
# regression to alert on, but it's worse than a clean one.
_RISK_ORDER: dict[str, int] = {
    RiskLevel.CLEAN.value: 0,
    RiskLevel.INCONCLUSIVE.value: 1,
    RiskLevel.LOW.value: 2,
    RiskLevel.MEDIUM.value: 3,
    RiskLevel.HIGH.value: 4,
}

# Human-facing label per risk level: (emoji, English label; translated per lang).
_RISK_LABEL: dict[str, tuple[str, str]] = {
    RiskLevel.CLEAN.value: ("✅", "Consistent"),
    RiskLevel.LOW.value: ("🔵", "Low risk"),
    RiskLevel.MEDIUM.value: ("🟡", "Medium risk"),
    RiskLevel.HIGH.value: ("🔴", "High risk"),
    RiskLevel.INCONCLUSIVE.value: ("⚪", "Undetermined"),
}

_MAX_FINDINGS = 5


# --------------------------------------------------------------------------- #
# Risk helpers
# --------------------------------------------------------------------------- #
def _risk_value(report: dict[str, Any] | None) -> str:
    """The risk_level string of a report dict, defaulting to ``inconclusive``."""
    if not report:
        return RiskLevel.INCONCLUSIVE.value
    verdict = report.get("verdict") or {}
    risk = verdict.get("risk_level")
    if isinstance(risk, RiskLevel):
        return risk.value
    if isinstance(risk, str) and risk:
        return risk
    return RiskLevel.INCONCLUSIVE.value


def _risk_rank(risk: str) -> int:
    return _RISK_ORDER.get(risk, _RISK_ORDER[RiskLevel.INCONCLUSIVE.value])


def _t(lang: str | None, template: str, *args: Any) -> str:
    """Translate an English alert template and fill its {1}, {2}, … slots."""
    out = i18n.ui(lang, template)
    for n, value in enumerate(args, start=1):
        out = out.replace("{" + str(n) + "}", str(value))
    return out


def _risk_label(risk: str, lang: str | None = i18n.DEFAULT) -> str:
    """e.g. "🔴 High risk (HIGH)" / "🔴 高风险（HIGH）"."""
    if risk not in _RISK_LABEL:
        return risk
    emoji, label = _RISK_LABEL[risk]
    return f"{emoji} " + _t(lang, "{1} ({2})", i18n.ui(lang, label), risk.upper())


def _key_findings(report: dict[str, Any], lang: str) -> list[str]:
    """The verdict's key findings (finding titles) in ``lang``, capped."""
    verdict = report.get("verdict") or {}
    titles = [f for f in (verdict.get("key_findings") or []) if isinstance(f, str) and f.strip()]
    # key_findings are English titles; map each back to its finding's id so
    # the translated catalog title can be used.
    found: dict[str, dict[str, Any]] = {}
    for det in report.get("detectors") or []:
        for f in det.get("findings") or []:
            if f.get("title") and f.get("id"):
                found.setdefault(f["title"], f)
    return [
        i18n.finding_title(lang, (found.get(t) or {}).get("id"), t, (found.get(t) or {}).get("evidence"))
        for t in titles[:_MAX_FINDINGS]
    ]


def regressed(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    """True if ``current``'s risk is strictly worse than ``previous``'s.

    Uses :data:`_RISK_ORDER` (clean < inconclusive < low < medium < high). With no
    previous run there is nothing to regress from, so this returns ``False``.
    """
    if previous is None:
        return False
    return _risk_rank(_risk_value(current)) > _risk_rank(_risk_value(previous))


def _delta_line(
    current: dict[str, Any], previous: dict[str, Any] | None, lang: str | None = i18n.DEFAULT
) -> str | None:
    """A "since last run" line describing the risk change, or ``None`` if no previous."""
    if previous is None:
        return None
    cur = _risk_value(current)
    prev = _risk_value(previous)
    if cur == prev:
        return _t(lang, "Since last run: risk unchanged ({1})", _risk_label(prev, lang))
    direction = _t(lang, "worse ⬆️" if _risk_rank(cur) > _risk_rank(prev) else "better ⬇️")
    return _t(lang, "Since last run: {1} → {2} ({3})", _risk_label(prev, lang), _risk_label(cur, lang), direction)


# --------------------------------------------------------------------------- #
# Text digest
# --------------------------------------------------------------------------- #
def build_text(
    report: dict[str, Any], previous: dict[str, Any] | None = None, lang: str | None = i18n.DEFAULT
) -> str:
    """A compact multi-line alert digest shared by every text platform.

    Includes the verdict (risk label + score + rating), the target (base_url and
    claimed model), the top key findings, and a "since last run" delta when a
    previous report is given — all in ``lang`` (English by default).
    """
    lang = i18n.normalize(lang)
    report = report or {}
    verdict = report.get("verdict") or {}
    target = report.get("target") or {}

    risk = _risk_value(report)
    score = verdict.get("overall_score")
    rating = verdict.get("rating")
    base_url = target.get("base_url") or "—"
    claimed = target.get("claimed_model") or target.get("model") or "—"
    headline = i18n.backend(lang, verdict.get("headline") or "")

    score_part = i18n.ui(lang, "n/a") if score is None else f"{score}/100"
    if rating:
        grade = _t(lang, "(grade {1})", rating)
        score_part += grade if grade.startswith("（") else f" {grade}"

    lines = [
        "🛰️ " + _t(lang, "ekte relay audit alert"),
        _t(lang, "Risk: {1}", _risk_label(risk, lang)),
        _t(lang, "Score: {1}", score_part),
        _t(lang, "Target: {1}", base_url),
        _t(lang, "Claimed model: {1}", claimed),
    ]
    if headline:
        lines.append(_t(lang, "Verdict: {1}", headline))

    delta = _delta_line(report, previous, lang)
    if delta:
        lines.append(delta)

    findings = _key_findings(report, lang)
    if findings:
        lines.append(_t(lang, "Key findings:"))
        for f in findings:
            lines.append(f"  • {f}")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Per-platform payload formatters
# --------------------------------------------------------------------------- #
def format_generic(
    report: dict[str, Any], previous: dict[str, Any] | None = None, lang: str | None = i18n.DEFAULT
) -> dict[str, Any]:
    """A structured JSON payload for a generic / custom webhook consumer.

    Keys and machine values (``risk_level``, ``score``, …) are language-neutral;
    the human-readable values (``text``, ``headline``, ``key_findings``) are in
    ``lang``, which is also reported as ``language``.
    """
    lang = i18n.normalize(lang)
    report = report or {}
    verdict = report.get("verdict") or {}
    target = report.get("target") or {}
    return {
        "schema_version": WEBHOOK_SCHEMA_VERSION,
        "tool": "ekte",
        "event": "audit_alert",
        "language": lang,
        "text": build_text(report, previous, lang),
        "risk_level": _risk_value(report),
        "score": verdict.get("overall_score"),
        "rating": verdict.get("rating"),
        "headline": i18n.backend(lang, verdict.get("headline") or ""),
        "base_url": target.get("base_url"),
        "claimed_model": target.get("claimed_model") or target.get("model"),
        "key_findings": _key_findings(report, lang),
        "previous_risk_level": _risk_value(previous) if previous is not None else None,
        "regressed": regressed(report, previous),
    }


def format_slack(
    report: dict[str, Any], previous: dict[str, Any] | None = None, lang: str | None = i18n.DEFAULT
) -> dict[str, Any]:
    """Slack incoming-webhook body — a single ``text`` field (mrkdwn)."""
    return {"text": build_text(report, previous, lang)}


def format_feishu(
    report: dict[str, Any], previous: dict[str, Any] | None = None, lang: str | None = i18n.DEFAULT
) -> dict[str, Any]:
    """Feishu/Lark custom-bot body — ``msg_type: "text"`` with a ``content.text``."""
    return {"msg_type": "text", "content": {"text": build_text(report, previous, lang)}}


def format_dingtalk(
    report: dict[str, Any], previous: dict[str, Any] | None = None, lang: str | None = i18n.DEFAULT
) -> dict[str, Any]:
    """DingTalk custom-robot body — ``msgtype: "text"`` with a ``text.content``."""
    return {"msgtype": "text", "text": {"content": build_text(report, previous, lang)}}


_FORMATTERS = {
    "generic": format_generic,
    "slack": format_slack,
    "feishu": format_feishu,
    "dingtalk": format_dingtalk,
}


# --------------------------------------------------------------------------- #
# Platform detection + delivery
# --------------------------------------------------------------------------- #
def detect_kind(webhook_url: str) -> str:
    """Guess the platform from the webhook host.

    hooks.slack.com → slack; feishu / larksuite → feishu; dingtalk → dingtalk;
    anything else → generic.
    """
    host = (urlparse(webhook_url).hostname or "").lower()
    if "hooks.slack.com" in host or host.endswith("slack.com"):
        return "slack"
    if "feishu" in host or "larksuite" in host or "larkoffice" in host:
        return "feishu"
    if "dingtalk" in host:
        return "dingtalk"
    return "generic"


def build_payload(
    report: dict[str, Any],
    *,
    kind: str = "auto",
    previous: dict[str, Any] | None = None,
    webhook_url: str | None = None,
    lang: str | None = i18n.DEFAULT,
) -> dict[str, Any]:
    """Pick the formatter by ``kind`` (or auto-detect from ``webhook_url``)."""
    resolved = kind
    if resolved == "auto":
        resolved = detect_kind(webhook_url or "")
    formatter = _FORMATTERS.get(resolved, format_generic)
    return formatter(report, previous, lang)


async def send(
    webhook_url: str,
    report: dict[str, Any],
    *,
    kind: str = "auto",
    previous: dict[str, Any] | None = None,
    timeout: float = 10.0,
    lang: str | None = i18n.DEFAULT,
) -> bool:
    """POST an alert for ``report`` to ``webhook_url``; return whether it succeeded.

    The payload shape is chosen from ``kind`` (``slack`` | ``feishu`` | ``dingtalk``
    | ``generic``) or auto-detected from the URL host when ``kind == "auto"``. The
    alert is written in ``lang`` (English by default).
    Never raises — a network error, timeout, or non-2xx status simply returns
    ``False`` so the watch loop keeps running.
    """
    if not webhook_url:
        return False
    payload = build_payload(report, kind=kind, previous=previous, webhook_url=webhook_url, lang=lang)
    try:
        # the relay clients' shared TLS context: no CA bundle load per alert
        async with httpx.AsyncClient(timeout=timeout, verify=await get_ssl_context()) as client:
            resp = await client.post(webhook_url, json=payload)
        return resp.status_code < 400
    except Exception:
        return False
