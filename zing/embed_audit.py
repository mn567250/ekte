"""Entry points for the non-chat Tools: embedding and rerank audits.

Embedding audits run through the runner as the ``embedding`` surface (the
detectors live in ``zing/detectors/embed_*.py``), are saved to history like any
audit, and come back to the Tools page as a small verdict dict
(:func:`tool_verdict`).

The rerank audit is still a standalone known-answer probe that bypasses the
runner: one document is obviously the most relevant to the query, and a
genuine reranker ranks it first.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from zing.clients import make_client
from zing.config import AuditOptions
from zing.detectors.embedding import cosine_similarity  # noqa: F401  -- re-exported
from zing.models import AuditReport, RiskLevel, Severity, Status, TargetConfig
from zing.utils.redact import fingerprint_secret


def _finding(
    id_: str,
    title: str,
    status: Status,
    severity: Severity,
    summary: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id_,
        "title": title,
        "status": status.value,
        "severity": severity.value,
        "summary": summary,
        "evidence": evidence or {},
    }


def _redacted_target(target: TargetConfig) -> dict[str, Any]:
    return {
        "name": target.name,
        "base_url": target.base_url,
        "model": target.model,
        "claimed_model": target.claimed_model,
        "declared_provider": target.declared_provider,
        "api_key_fingerprint": fingerprint_secret(target.api_key),
    }


def _verdict(
    findings: list[dict[str, Any]], target: TargetConfig
) -> dict[str, Any]:
    """Roll findings up into a risk level + 0-100 score."""
    has_fail = any(f["status"] == Status.FAIL.value for f in findings)
    has_error = any(f["status"] == Status.ERROR.value for f in findings)
    has_warn = any(f["status"] == Status.WARN.value for f in findings)
    # A high-severity *finding* (fail/warn) is a mismatch signal. An ERROR finding
    # (couldn't reach/parse the endpoint) is high-severity too, but it is evidence
    # of nothing about the model — that is handled as INCONCLUSIVE first.
    has_high = any(
        f["severity"] in (Severity.HIGH.value, Severity.CRITICAL.value)
        and f["status"] != Status.ERROR.value
        for f in findings
    )

    if has_error:
        # Could not reach / parse the endpoint — not a mismatch, but not clean.
        risk = RiskLevel.INCONCLUSIVE
        score = 50.0
    elif has_fail or has_high:
        risk = RiskLevel.HIGH
        score = 20.0
    elif has_warn:
        risk = RiskLevel.MEDIUM
        score = 65.0
    else:
        risk = RiskLevel.CLEAN
        score = 100.0

    return {
        "risk_level": risk.value,
        "score": score,
        "findings": findings,
        "target": _redacted_target(target),
    }


# --------------------------------------------------------------------------- #
# Embedding audit (through the runner)
# --------------------------------------------------------------------------- #
def tool_verdict(report: AuditReport, report_id: int | None = None) -> dict[str, Any]:
    """The Tools page's small verdict dict for an embedding-surface report:
    ``risk_level``, ``score``, the flattened ``findings`` and the redacted
    ``target`` (the rerank verdict's shape), plus the saved ``report_id``."""
    findings = [
        {
            "id": f.id,
            "title": f.title,
            "status": f.status.value,
            "severity": f.severity.value,
            "summary": f.summary,
            "evidence": f.evidence,
        }
        for d in report.detectors
        for f in d.findings
    ]
    target = report.target
    return {
        "risk_level": report.verdict.risk_level.value,
        "score": report.verdict.overall_score,
        "rating": report.verdict.rating,
        "headline": report.verdict.headline,
        "surface": report.surface,
        "suite": report.suite,
        "findings": findings,
        "target": {
            "name": target.name,
            "base_url": target.base_url,
            "model": target.model,
            "claimed_model": target.claimed_model,
            "declared_provider": target.declared_provider,
            "api_key_fingerprint": target.api_key_fingerprint,
        },
        "report_id": report_id,
    }


def _previous(target: TargetConfig) -> dict[str, Any] | None:
    """The last saved embedding run of this target and claimed model (best-effort)."""
    try:
        from zing.web import history

        return history.latest_for(target.base_url, target.claimed, surface="embedding")
    except Exception:
        return None


def _save(report: AuditReport) -> int | None:
    """Persist to history (best-effort: a store failure must not lose the verdict)."""
    try:
        from zing.web import history

        rid = history.save(json.loads(report.model_dump_json()))
    except Exception:
        return None
    return rid if isinstance(rid, int) and rid >= 0 else None


async def run_embedding_audit(
    target: TargetConfig,
    *,
    claimed_dimensions: int = 0,
    suite: str = "standard",
    kb_dirs: list[Path] | None = None,
    command: str | None = None,
    save: bool = True,
) -> tuple[AuditReport, int | None]:
    """Audit an embeddings endpoint with the runner (surface ``embedding``).

    ``claimed_dimensions`` overrides the claimed model's vector length (0 = from
    the knowledge base). The previous saved run of the same target and claimed
    model is the reference for the vector-drift check; with ``save`` the report
    goes to history. Returns the report and its history id (None if not saved).
    """
    from zing.runner import run_audit

    previous = await asyncio.to_thread(_previous, target) if save else None
    options = AuditOptions(
        suite=suite, surface="embedding", embedding_dimensions=max(0, claimed_dimensions)
    )
    report = await run_audit(
        target, options, mode="check", command=command, kb_dirs=kb_dirs, previous_report=previous
    )
    report_id = await asyncio.to_thread(_save, report) if save else None
    return report, report_id


# --------------------------------------------------------------------------- #
# Rerank audit (known-answer probe)
# --------------------------------------------------------------------------- #
async def audit_rerank(
    target: TargetConfig,
    query: str,
    documents: list[str],
    expected_top_index: int,
) -> dict[str, Any]:
    """Known-answer rerank probe.

    One document in ``documents`` is obviously the most relevant answer to
    ``query`` (at ``expected_top_index``). A genuine reranker ranks it first; we
    flag it if it does not. Returns the same small verdict dict shape.
    """
    findings: list[dict[str, Any]] = []

    async with make_client(target) as client:
        outcome, results = await client.rerank(query, documents)

    if not outcome.ok:
        findings.append(
            _finding(
                "rerank.connectivity",
                "Rerank endpoint unreachable",
                Status.ERROR,
                Severity.HIGH,
                f"POST /rerank failed: {outcome.error_message or outcome.status_code}",
                {"status_code": outcome.status_code, "error": outcome.error_message},
            )
        )
        return _verdict(findings, target)

    if not results:
        findings.append(
            _finding(
                "rerank.connectivity",
                "Rerank response empty",
                Status.ERROR,
                Severity.HIGH,
                "Endpoint returned no ranking results.",
                {"results": 0},
            )
        )
        return _verdict(findings, target)

    findings.append(
        _finding(
            "rerank.connectivity",
            "Rerank endpoint reachable",
            Status.PASS,
            Severity.INFO,
            f"Got {len(results)} ranked results.",
            {"results": len(results)},
        )
    )

    top = results[0]
    top_index = top["index"]
    ranking = [r["index"] for r in results]
    if top_index == expected_top_index:
        findings.append(
            _finding(
                "rerank.known_answer",
                "Reranker ranks the obvious answer first",
                Status.PASS,
                Severity.INFO,
                (
                    f"Document {expected_top_index} (the clearly-relevant one) ranked "
                    f"first with score {top['relevance_score']:.4f}."
                ),
                {"top_index": top_index, "expected": expected_top_index, "ranking": ranking},
            )
        )
    else:
        findings.append(
            _finding(
                "rerank.known_answer",
                "Reranker does NOT rank the obvious answer first",
                Status.WARN,
                Severity.HIGH,
                (
                    f"Expected document {expected_top_index} to rank first, but "
                    f"document {top_index} did. The reranker is not behaving as a "
                    f"genuine relevance model would."
                ),
                {"top_index": top_index, "expected": expected_top_index, "ranking": ranking},
            )
        )

    return _verdict(findings, target)
