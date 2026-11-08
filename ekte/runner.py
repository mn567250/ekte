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
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ekte.detectors  # noqa: F401  -- populates the detector REGISTRY
from ekte import __version__, prompts
from ekte.clients import Client, detect_api, make_client
from ekte.config import SURFACE_OPS, AuditOptions
from ekte.context import AuditContext
from ekte.detectors.base import run_detector, select_detectors
from ekte.detectors.performance import planned_probe_requests, probe_modes, stream_mode
from ekte.errorclass import NETWORK, is_impaired, record_class
from ekte.evidence import EvidenceHeader, EvidenceWriter, new_run_id
from ekte.judge import Judge
from ekte.knowledge import ResolvedProfile, load_knowledge_base
from ekte.knowledge.freshness import bundled_date, stale_warning
from ekte.knowledge.snapshot import knowledge_usage, resolved_from_snapshot
from ekte.models import (
    AuditReport,
    DetectorResult,
    Dimension,
    KnowledgeUsage,
    RedactedTarget,
    ReliabilitySummary,
    TargetConfig,
)
from ekte.perf import RequestRecorder, build_performance, detector_scope
from ekte.perf.outcomes import run_outcomes
from ekte.perf.trend import RunningMedian
from ekte.scoring import build_dimensions, build_verdict
from ekte.utils.redact import fingerprint_secret

if TYPE_CHECKING:
    from ekte.replay import Replay


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


def run_secrets(*configs: TargetConfig | None) -> list[str | None]:
    """Every secret a run's configs carry (API keys, custom header values),
    to be scrubbed from anything relay-controlled the run stores."""
    out: list[str | None] = []
    for config in configs:
        if config is None:
            continue
        out.append(config.api_key)
        out.extend(v for v in (config.headers or {}).values() if isinstance(v, str))
    return out


def _open_evidence(
    path: Path,
    recorder: RequestRecorder,
    *,
    mode: str,
    options: AuditOptions,
    target: RedactedTarget,
    baseline: RedactedTarget | None,
    judge: RedactedTarget | None,
    secrets: list[str | None],
) -> EvidenceWriter:
    """Start the run's evidence file (blocking: called off the loop)."""
    head = EvidenceHeader(
        tool_version=__version__,
        run_id=_run_id_of(path),
        started_at=recorder.started_at.isoformat(),
        mode=mode,
        suite=options.suite,
        surface=options.surface,
        target=target,
        baseline=baseline,
        judge=judge,
        options=options.model_dump(mode="json"),
    )
    return EvidenceWriter(path, head, t0=recorder.t0, secrets=secrets)


def _run_id_of(path: Path) -> str:
    """The run id an evidence path names (``<run_id>.jsonl.zst``), else a new one."""
    from ekte.evidence import SUFFIX

    name = path.name
    stem = name[: -len(SUFFIX)] if name.endswith(SUFFIX) else ""
    if len(stem) == 32 and all(c in "0123456789abcdef" for c in stem):
        return stem
    return new_run_id()


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


def _fit_client(client: Client, profile: ResolvedProfile | None) -> None:
    """Tell a client what its endpoint's model is known to need: room to think
    on short probes (a reasoning model), and the request parameters it refuses
    (``unsupported_params``, left out or renamed by the client)."""
    model = profile.model if profile is not None else None
    client.reasoning_room = bool(model and model.reasoning)
    client.unsupported_params = set(model.unsupported_params) if model else set()


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
    previous_report: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    evidence: Path | None = None,
    replay: Replay | None = None,
) -> AuditReport:
    """Run one audit.

    ``replay`` answers every request from a recorded run's evidence instead of
    the network (see :mod:`ekte.replay`): a re-score with this ekte version.

    ``evidence`` is the path of the evidence file to write: every raw
    request/response pair of the run (see :mod:`ekte.evidence`); the report's
    ``evidence`` then names the file and its hash. None keeps no evidence.

    ``use_user_kb`` includes/excludes the user's kb.db entries (default: unless
    ``EKTE_NO_USER_KB``). ``pinned`` audits against a fixed profile snapshot
    (a watch's) instead of resolving the live knowledge base.
    ``previous_report`` is the last saved report of the same target and claimed
    model, for checks that compare across runs (embedding vector drift).
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
        knowledge = pinned.model_copy(
            update={"pinned": True, "warnings": list(kb.warnings), "kb_date": bundled_date()}
        )
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
    # Each streamed record carries its running medians (the live chart's
    # trend line), so the browser only draws.
    trend = RunningMedian()
    recorder = RequestRecorder(
        profile.model.tokenizer if profile and profile.model.tokenizer else None,
        on_record=lambda rec: _emit({"type": "request_done", "record": trend.tag(rec.model_dump())}),
    )
    redacted_target = await asyncio.to_thread(_redact, target)
    redacted_baseline = await asyncio.to_thread(_redact, baseline) if baseline else None
    writer: EvidenceWriter | None = None
    if evidence is not None:
        jt = (judge_target or baseline) if options.judge else None
        writer = await asyncio.to_thread(
            _open_evidence, Path(evidence), recorder, mode=mode, options=options,
            target=redacted_target, baseline=redacted_baseline,
            judge=await asyncio.to_thread(_redact, jt) if jt is not None else None,
            secrets=run_secrets(target, baseline, judge_target if options.judge else None),
        )
        recorder.evidence = writer
    if replay is not None:
        recorder.replay = True

    try:
        results, judge = await _run_detectors(
            target, options, baseline=baseline, judge_target=judge_target, mode=mode,
            kb=kb, profile=profile, recorder=recorder, writer=writer,
            previous_report=previous_report, emit=_emit, replay=replay,
        )
    except BaseException:
        if writer is not None:
            await asyncio.to_thread(writer.abort)
        raise
    evidence_ref = await asyncio.to_thread(writer.close) if writer is not None else None
    return _assemble(
        target, options, results, judge, baseline=baseline, judge_target=judge_target,
        mode=mode, command=command, profile=profile, knowledge=knowledge, recorder=recorder,
        redacted_target=redacted_target, redacted_baseline=redacted_baseline,
        evidence=replay.evidence if replay is not None else evidence_ref,
        rescored_from=replay.summary() if replay is not None else None,
    )


async def _run_detectors(
    target: TargetConfig,
    options: AuditOptions,
    *,
    baseline: TargetConfig | None,
    judge_target: TargetConfig | None,
    mode: str,
    kb: Any,
    profile: ResolvedProfile | None,
    recorder: RequestRecorder,
    writer: EvidenceWriter | None,
    previous_report: dict[str, Any] | None,
    emit: Callable[[dict[str, Any]], None],
    replay: Replay | None = None,
) -> tuple[list[DetectorResult], Judge | None]:
    """Open the clients and run the selected detectors one after another."""

    def connect(config: TargetConfig, endpoint: str) -> Client:
        if replay is None:
            return make_client(config)
        client = make_client(config, transport=replay.transport(endpoint))
        # repeat a failed attempt exactly when the recorded run did
        client.replay_retried = replay.was_retried
        return client

    _emit = emit
    # Only chat completions stream; the other surfaces' requests do not.
    request_mode = "non_stream" if options.surface != "chat" else stream_mode(options)
    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(connect(target, "target"))
        client.recorder, client.endpoint = recorder, "target"
        _fit_client(client, profile)

        baseline_client = None
        if baseline is not None:
            baseline_client = await stack.enter_async_context(connect(baseline, "baseline"))
            baseline_client.recorder, baseline_client.endpoint = recorder, "baseline"
            # The baseline may be another model (--baseline-model): its own profile.
            if baseline.claimed == target.claimed:
                _fit_client(baseline_client, profile)
            else:
                _fit_client(
                    baseline_client,
                    kb.resolve(baseline.claimed, baseline.declared_provider),
                )

        judge = None
        if options.judge:
            jt = judge_target or baseline
            if jt is not None:
                judge_client = await stack.enter_async_context(connect(jt, "judge"))
                # The judge's calls are not recorded; with evidence they are kept.
                judge_client.endpoint, judge_client.evidence = "judge", writer
                _fit_client(judge_client, kb.resolve(jt.claimed, jt.declared_provider))
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
            previous_report=previous_report,
        )

        detectors = select_detectors(
            options.suite,
            has_judge=judge is not None,
            has_baseline=baseline_client is not None,
            enabled=options.enabled,
            dimensions=options.dimensions,
            surface=options.surface,
        )
        total = len(detectors)
        has_baseline = baseline_client is not None
        # Target probe requests across all modes, for the live progress bar.
        probe_planned = planned_probe_requests(options, has_baseline=has_baseline)
        if any(d.id == "performance" for d in detectors):
            probe_planned *= len(probe_modes(options))
        elif any(d.id == "performance.embed" for d in detectors):
            probe_planned *= 2  # a single-input and a batch request per round
        elif any(d.id == "performance.rerank" for d in detectors):
            probe_planned *= 2  # a 4- and a 32-document request per round
        else:
            probe_planned = 0
        _emit({"type": "start", "total": total, "suite": options.suite,
               "dimensions": list(options.dimensions), "mode": mode,
               "target": target.name, "claimed_model": target.claimed,
               "has_baseline": has_baseline, "probe_requests": probe_planned,
               "api": detect_api(target), "stream_mode": request_mode})
        results: list[DetectorResult] = []
        for i, detector in enumerate(detectors):
            _emit({"type": "detector_start", "index": i, "total": total,
                   "id": detector.id, "name": detector.name, "dimension": detector.dimension.value})
            with detector_scope(detector.id):
                res = await run_detector(detector, ctx)
            if replay is not None:
                res = replay.after_detector(res)
            results.append(res)
            _emit({"type": "detector_done", "index": i, "total": total,
                   "id": res.id, "name": res.name, "dimension": res.dimension.value,
                   "status": res.status.value, "score": res.score,
                   "duration_ms": res.duration_ms, "findings": _event_findings(res)})
    return results, judge


def impaired_warning(records: list[Any], results: list[DetectorResult]) -> str | None:
    """The report's warning when requests failed in ekte or on the network path
    to the relay (after their repeats), or None when none did."""
    lost = [r for r in records if is_impaired(r)]
    if not lost:
        return None
    network = sum(1 for r in lost if record_class(r) == NETWORK)
    local = len(lost) - network
    repeats = sum(1 for r in records if r.retried)
    unjudged = sum(1 for d in results for f in d.findings if "impaired_requests" in f.evidence)
    parts = []
    if network:
        parts.append(f"{network} on the network path to the relay (proxy, DNS, connect or TLS)")
    if local:
        parts.append(f"{local} in ekte itself")
    return (
        f"The run was impaired: {len(lost)} request(s) failed before the relay could answer them "
        f"({' and '.join(parts)}), after {repeats} repeat(s). They are not counted against the "
        f"relay; {unjudged} check(s) that rest only on them read inconclusive."
    )


def _assemble(
    target: TargetConfig,
    options: AuditOptions,
    results: list[DetectorResult],
    judge: Judge | None,
    *,
    baseline: TargetConfig | None,
    judge_target: TargetConfig | None,
    mode: str,
    command: str | None,
    profile: ResolvedProfile | None,
    knowledge: KnowledgeUsage,
    recorder: RequestRecorder,
    redacted_target: RedactedTarget,
    redacted_baseline: RedactedTarget | None,
    evidence: Any,
    rescored_from: Any = None,
) -> AuditReport:
    """The report of a finished run."""
    request_mode = "non_stream" if options.surface != "chat" else stream_mode(options)
    reliability = _extract_reliability(results)
    performance = build_performance(
        recorder.records,
        tokenizer=recorder.tokenizer,
        has_baseline=baseline is not None,
        # Only chat probes have an output budget; embedding and rerank calls return no tokens.
        probe_max_tokens=options.performance_max_tokens if options.surface == "chat" else None,
        concurrency=options.reliability_concurrency,
        op=SURFACE_OPS[options.surface],
    )
    selected = list(options.dimensions) if options.suite == "custom" else None
    dimensions = build_dimensions(results, reliability, selected=selected, surface=options.surface)
    verdict = build_verdict(
        results,
        dimensions,
        profile_matched=profile is not None,
        used_judge=judge is not None,
        used_baseline=baseline is not None,
        selected=selected,
        match_confidence=profile.match_confidence if profile is not None else None,
        surface=options.surface,
    )

    warnings = [
        f"{d.id}: {d.error}" for d in results if d.error
    ]
    if (impaired := impaired_warning(recorder.records, results)) is not None:
        warnings.append(impaired)
    if (stale := stale_warning(knowledge.kb_date)) is not None:
        warnings.append(stale)
    notes = [
        "ekte performs black-box auditing: it gathers reproducible evidence of "
        "behavioral divergence, not cryptographic proof of model identity.",
        "Use `ekte compare` against a trusted baseline of the same declared model "
        "for the strongest downgrade evidence.",
        "Do not publish a report that names a vendor without reviewing sample size, "
        "cost, and local law/policy.",
    ]

    judge_endpoint = judge_target or baseline
    return AuditReport(
        tool_version=__version__,
        mode=mode,
        generated_at=recorder.now().isoformat(),
        started_at=recorder.started_at.isoformat(),
        command=command,
        suite=options.suite,
        surface=options.surface,
        embedding_dimensions=(
            max(0, options.embedding_dimensions) if options.surface == "embedding" else 0
        ),
        dimensions_selected=selected,
        stream_mode=request_mode,
        target=redacted_target,
        baseline=redacted_baseline,
        verdict=verdict,
        dimensions=dimensions,
        detectors=results,
        reliability=reliability,
        performance=performance,
        outcomes=run_outcomes(recorder.records),
        judge_used=judge is not None,
        judge_model=judge_endpoint.model if (options.judge and judge_endpoint is not None) else None,
        notes=notes,
        warnings=warnings,
        prompt_languages=_prompt_languages(results),
        knowledge=knowledge,
        evidence=evidence,
        rescored_from=rescored_from,
    )
