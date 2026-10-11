"""Audit orchestration: wire up context, run detectors, assemble the report.

Detectors run sequentially against a single endpoint on purpose — concurrent
hammering would trip rate limits and confound the latency/streaming timing
measurements. The reliability detector does its own bounded concurrency
internally.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import zing.detectors  # noqa: F401  -- populates the detector REGISTRY
from zing import __version__, prompts
from zing.clients import detect_api, make_client
from zing.config import AuditOptions
from zing.context import AuditContext
from zing.detectors.base import run_detector, select_detectors
from zing.detectors.performance import planned_probe_requests, probe_modes, stream_mode
from zing.judge import Judge
from zing.knowledge import ResolvedProfile, load_knowledge_base
from zing.knowledge.snapshot import knowledge_usage, resolved_from_snapshot
from zing.models import (
    AuditReport,
    DetectorResult,
    Dimension,
    KnowledgeUsage,
    RedactedTarget,
    ReliabilitySummary,
    TargetConfig,
)
from zing.perf import RequestRecorder, build_performance, detector_scope
from zing.scoring import build_dimensions, build_verdict
from zing.utils.redact import fingerprint_secret


def _redact(config: TargetConfig) -> RedactedTarget:
    return RedactedTarget(
        name=config.name,
        kind=config.kind,
        base_url=config.base_url,
        model=config.model,
        claimed_model=config.claimed_model,
        declared_provider=config.declared_provider,
        api_key_fingerprint=fingerprint_secret(config.api_key),
        api=detect_api(config),
        api_auto=(config.api or "auto").lower() == "auto",
    )


def _event_findings(result: DetectorResult) -> list[dict[str, Any]]:
    """Compact, size-bounded findings for a live progress event (evidence trimmed)."""
    out: list[dict[str, Any]] = []
    for f in result.findings:
        ev: dict[str, Any] = {}
        for k, v in list(f.evidence.items())[:8]:
            s: Any = v if isinstance(v, (int, float, bool)) or v is None else str(v)
            if isinstance(s, str) and len(s) > 240:
                s = s[:237] + "…"
            ev[k] = s
        out.append(
            {
                "id": f.id,
                "title": f.title,
                "status": f.status.value,
                "severity": f.severity.value,
                "summary": f.summary,
                "recommendation": f.recommendation,
                "evidence": ev,
            }
        )
    return out


def _prompt_languages(detectors: list[DetectorResult]) -> list[str]:
    """Languages of everything sent to the endpoint: the prompt library's plus
    those of the language-bound fingerprints that actually ran."""
    langs = {prompts.PROBE_LANG}
    for det in detectors:
        langs.update(det.evidence.get("fingerprint_prompt_langs") or [])
    return sorted(langs)


def _extract_reliability(detectors: list[DetectorResult]) -> ReliabilitySummary | None:
    for det in detectors:
        if det.dimension == Dimension.RELIABILITY:
            payload = det.evidence.get("reliability")
            if isinstance(payload, dict):
                try:
                    return ReliabilitySummary(**payload)
                except Exception:
                    return None
    return None


async def run_audit(
    target: TargetConfig,
    options: AuditOptions,
    *,
    baseline: TargetConfig | None = None,
    judge_target: TargetConfig | None = None,
    mode: str = "check",
    command: str | None = None,
    kb_dirs: list[Path] | None = None,
    use_user_kb: bool | None = None,
    pinned: KnowledgeUsage | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> AuditReport:
    """Run one audit.

    ``use_user_kb`` includes/excludes the user's kb.db entries (default: unless
    ``ZING_NO_USER_KB``). ``pinned`` audits against a fixed profile snapshot
    (a watch's) instead of resolving the live knowledge base.
    """
    # YAML + kb.db reads (a deep copy even when cached): off the event loop,
    # which timestamps the streamed chunks.
    kb = await asyncio.to_thread(load_knowledge_base, kb_dirs, include_user=use_user_kb)
    profile: ResolvedProfile | None = None
    stale_pin: str | None = None
    if pinned is not None and pinned.profile:
        try:
            profile = resolved_from_snapshot(pinned.profile, pinned.match_confidence)
        except Exception as exc:  # e.g. the schema changed since the snapshot was taken
            stale_pin = f"pinned profile no longer valid, using the live knowledge base: {str(exc).splitlines()[0]}"
    if profile is not None and pinned is not None:
        knowledge = pinned.model_copy(update={"pinned": True, "warnings": list(kb.warnings)})
    else:
        # Resolve against the CLAIMED model (defaults to the requested model id), so an
        # endpoint serving model X can be audited against the profile it's sold as.
        profile = kb.resolve(target.claimed, target.declared_provider)
        knowledge = knowledge_usage(kb, profile, target.claimed)
        if stale_pin:
            knowledge.warnings.append(stale_pin)

    def _emit(event: dict[str, Any]) -> None:
        if on_event is not None:
            # a progress sink must never break the audit
            with suppress(Exception):
                on_event(event)

    # Every target/baseline call is logged for the performance section and
    # streamed as a live progress event.
    recorder = RequestRecorder(
        profile.model.tokenizer if profile and profile.model.tokenizer else None,
        on_record=lambda rec: _emit({"type": "request_done", "record": rec.model_dump()}),
    )

    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(make_client(target))
        client.recorder, client.endpoint = recorder, "target"

        baseline_client = None
        if baseline is not None:
            baseline_client = await stack.enter_async_context(make_client(baseline))
            baseline_client.recorder, baseline_client.endpoint = recorder, "baseline"

        judge = None
        if options.judge:
            jt = judge_target or baseline
            if jt is not None:
                judge_client = await stack.enter_async_context(make_client(jt))
                judge = Judge(judge_client, jt.model)

        ctx = AuditContext(
            target=target,
            client=client,
            options=options,
            kb=kb,
            profile=profile,
            baseline=baseline,
            baseline_client=baseline_client,
            judge=judge,
            recorder=recorder,
        )

        detectors = select_detectors(
            options.suite,
            has_judge=judge is not None,
            has_baseline=baseline_client is not None,
            enabled=options.enabled,
            dimensions=options.dimensions,
        )
        total = len(detectors)
        has_baseline = baseline_client is not None
        # Target probe requests across all modes, for the live progress bar.
        probe_planned = (
            planned_probe_requests(options, has_baseline=has_baseline) * len(probe_modes(options))
            if any(d.id == "performance" for d in detectors)
            else 0
        )
        _emit({"type": "start", "total": total, "suite": options.suite,
               "dimensions": list(options.dimensions), "mode": mode,
               "target": target.name, "claimed_model": target.claimed,
               "has_baseline": has_baseline, "probe_requests": probe_planned,
               "api": detect_api(target), "stream_mode": stream_mode(options)})
        results: list[DetectorResult] = []
        for i, detector in enumerate(detectors):
            _emit({"type": "detector_start", "index": i, "total": total,
                   "id": detector.id, "name": detector.name, "dimension": detector.dimension.value})
            with detector_scope(detector.id):
                res = await run_detector(detector, ctx)
            results.append(res)
            _emit({"type": "detector_done", "index": i, "total": total,
                   "id": res.id, "name": res.name, "dimension": res.dimension.value,
                   "status": res.status.value, "score": res.score,
                   "duration_ms": res.duration_ms, "findings": _event_findings(res)})

    reliability = _extract_reliability(results)
    performance = build_performance(
        recorder.records,
        tokenizer=recorder.tokenizer,
        has_baseline=baseline is not None,
        probe_max_tokens=options.performance_max_tokens,
        concurrency=options.reliability_concurrency,
    )
    selected = list(options.dimensions) if options.suite == "custom" else None
    dimensions = build_dimensions(results, reliability, selected=selected)
    verdict = build_verdict(
        results,
        dimensions,
        profile_matched=profile is not None,
        used_judge=judge is not None,
        used_baseline=baseline_client is not None,
        selected=selected,
    )

    warnings = [
        f"{d.id}: {d.error}" for d in results if d.error
    ]
    notes = [
        "zing performs black-box auditing: it gathers reproducible evidence of "
        "behavioral divergence, not cryptographic proof of model identity.",
        "Use `zing compare` against a trusted baseline of the same declared model "
        "for the strongest downgrade evidence.",
        "Do not publish a report that names a vendor without reviewing sample size, "
        "cost, and local law/policy.",
    ]

    judge_endpoint = judge_target or baseline
    return AuditReport(
        tool_version=__version__,
        mode=mode,
        generated_at=datetime.now(timezone.utc).isoformat(),
        command=command,
        suite=options.suite,
        dimensions_selected=selected,
        stream_mode=stream_mode(options),
        target=_redact(target),
        baseline=_redact(baseline) if baseline else None,
        verdict=verdict,
        dimensions=dimensions,
        detectors=results,
        reliability=reliability,
        performance=performance,
        judge_used=judge is not None,
        judge_model=judge_endpoint.model if (options.judge and judge_endpoint is not None) else None,
        notes=notes,
        warnings=warnings,
        prompt_languages=_prompt_languages(results),
        knowledge=knowledge,
    )
