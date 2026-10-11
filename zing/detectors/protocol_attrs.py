"""Protocol attribute detectors — can every request attribute be sent, and does
every response attribute come back?

A relay can answer while quietly degrading the wire contract: stripping ``n`` or
``logprobs`` on the way in, or returning an envelope without ``id``, with
``completion_tokens: 0`` or a ``total_tokens`` that is not the sum of its parts.
Both detectors check each attribute of the wire protocol's catalog
(:mod:`zing.detectors.wire_attrs`) as one subject of a parametrized scale check,
so every attribute is scored — and listed — on its own while the published scale
stays small. The detector score is the mean of the counted attributes.
"""

from __future__ import annotations

import asyncio
from typing import Any

from zing import prompts
from zing.clients import detect_api
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.scale import Scale
from zing.detectors.wire_attrs import (
    CALL,
    PARAM,
    REQUEST_SCALE,
    RESPONSE_SCALE,
    Param,
    assess_response,
    classify_param,
    expected,
    is_rejection,
    merge_specs,
    request_params,
)
from zing.models import CompletionOutcome, DetectorResult, Dimension, Finding, RequestSpec

# Parameter probes in flight at once: enough to overlap latency, few enough not
# to trip a relay's rate limit.
_CONCURRENCY = 3
_PREVIEW = 120


def _preview(value: Any) -> Any:
    """An evidence-sized copy of an observed value."""
    if isinstance(value, str):
        return value[:_PREVIEW]
    if isinstance(value, (list, dict)):
        return f"<{type(value).__name__} of {len(value)}>"
    return value


def _finish(result: DetectorResult) -> DetectorResult:
    result.score = Scale.mean(result.findings)
    result.status = Scale.roll_up(result.findings)
    return result


@register
class ProtocolResponseDetector(Detector):
    id = "protocol_response"
    name = "Response attribute availability"
    dimension = Dimension.PROTOCOL
    min_suite = "standard"
    cost_hint = 1

    async def run(self, ctx: AuditContext) -> DetectorResult:
        protocol = detect_api(ctx.target)
        result = self.new_result(scoring=RESPONSE_SCALE.scoring())
        result.evidence["protocol"] = protocol

        spec = RequestSpec(
            messages=[{"role": "user", "content": prompts.text("protocol_response.probe")}],
            temperature=None,
            capture_raw=True,
        )
        if ctx.profile and ctx.profile.model.reasoning and protocol == "openai":
            spec.extra_body["max_completion_tokens"] = 1024
        else:
            spec.max_tokens = 256
        out = await ctx.client.complete(spec)
        if not (out.ok and out.raw_body is not None):
            result.findings.append(
                RESPONSE_SCALE.finding(
                    CALL,
                    "no_response",
                    title="Response-attribute probe returned no body",
                    summary=out.error_message or f"HTTP {out.status_code}; no response body.",
                    evidence={"status_code": out.status_code, "error_type": out.error_type},
                )
            )
            return _finish(result)

        table: dict[str, str] = {}
        for r in assess_response(protocol, out.raw_body):
            table[r.attr.path] = r.key
            label = RESPONSE_SCALE.get(r.attr.check, r.key).label
            result.findings.append(
                RESPONSE_SCALE.finding(
                    r.attr.check,
                    r.key,
                    subject=r.attr.path,
                    title=f"Response attribute {r.attr.path}",
                    summary=f"{r.attr.path}: {label}",
                    evidence={
                        "attribute": r.attr.path,
                        "availability": r.key,
                        "observed": None if r.key == "missing" else _preview(r.observed),
                        "expected": expected(r.attr.rule),
                    },
                    recommendation=None
                    if r.key == "valid"
                    else "A conformant endpoint returns every attribute of its wire protocol "
                    "with a valid value.",
                )
            )
        result.evidence["attributes"] = table
        return _finish(result)


@register
class ProtocolRequestDetector(Detector):
    id = "protocol_request"
    name = "Request attribute support"
    dimension = Dimension.PROTOCOL
    min_suite = "standard"
    cost_hint = 5

    async def run(self, ctx: AuditContext) -> DetectorResult:
        protocol = detect_api(ctx.target)
        model = ctx.profile.model if ctx.profile else None
        params = request_params(protocol, reasoning=bool(model and model.reasoning))
        result = self.new_result(scoring=REQUEST_SCALE.scoring())
        result.evidence["protocol"] = protocol
        sem = asyncio.Semaphore(_CONCURRENCY)
        calls = 0
        # Reasoning models on Chat Completions refuse max_tokens and need room to
        # think before they answer.
        limit: dict[str, Any] = (
            {"max_tokens": None, "extra_body": {"max_completion_tokens": 256}}
            if protocol == "openai" and model and model.reasoning
            else {"max_tokens": 16}
        )

        async def send(client, spec_fields: dict[str, Any]) -> CompletionOutcome:
            nonlocal calls
            fields: dict[str, Any] = {
                "messages": [{"role": "user", "content": prompts.text("protocol_request.probe")}],
                "temperature": None,
                "capture_raw": True,
                **limit,
                **spec_fields,
            }
            fields["extra_body"] = {**limit.get("extra_body", {}), **spec_fields.get("extra_body", {})}
            calls += 1
            async with sem:
                return await client.complete(RequestSpec(**fields))

        # Verified params each need their own call; accept-only params share one
        # and are retried alone only when that shared call is rejected.
        verified = [p for p in params if p.verify is not None]
        plain = [p for p in params if p.verify is None]
        probes = [send(ctx.client, p.spec) for p in verified]
        if plain:
            probes.append(send(ctx.client, merge_specs(plain)))
        outs = await asyncio.gather(*probes)
        outcomes: dict[str, tuple[CompletionOutcome, bool]] = {
            p.name: (o, False) for p, o in zip(verified, outs, strict=False)
        }
        if plain:
            batch = outs[-1]
            if is_rejection(batch) and len(plain) > 1:
                alone = await asyncio.gather(*(send(ctx.client, p.spec) for p in plain))
                outcomes.update({p.name: (o, False) for p, o in zip(plain, alone, strict=True)})
            else:
                outcomes.update({p.name: (batch, True) for p in plain})

        # A trusted baseline on the same protocol tells a relay that drops a
        # parameter from a model that never took it.
        baseline: dict[str, CompletionOutcome] = {}
        rejected = [p for p in params if is_rejection(outcomes[p.name][0])]
        if rejected and ctx.baseline_client is not None and ctx.baseline is not None \
                and detect_api(ctx.baseline) == protocol:
            base_outs = await asyncio.gather(
                *(send(ctx.baseline_client, p.spec) for p in rejected)
            )
            baseline = {p.name: o for p, o in zip(rejected, base_outs, strict=True)}

        unsupported = set(model.unsupported_params) if model else set()
        table: dict[str, str] = {}
        for p in params:
            out, batched = outcomes[p.name]
            known = p.name in unsupported or bool(model and model.reasoning and p.sampling)
            key = classify_param(p, out, known_unsupported=known, baseline=baseline.get(p.name))
            table[p.name] = key
            result.findings.append(self._finding(p, key, out, batched))
        result.evidence["attributes"] = table
        result.evidence["calls"] = calls
        return _finish(result)

    @staticmethod
    def _finding(p: Param, key: str, out: CompletionOutcome, batched: bool) -> Finding:
        label = REQUEST_SCALE.get(PARAM, key).label
        evidence: dict[str, Any] = {
            "attribute": p.name,
            "availability": key,
            "sent": p.spec.get("extra_body") or {
                k: v for k, v in p.spec.items() if k not in ("messages", "reasoning_retry")
            } or "system message",
            "status_code": out.status_code,
        }
        if batched:
            evidence["sent_with"] = "the other accept-only parameters, in one request"
        if out.error_message and not out.ok:
            evidence["error"] = out.error_message[:_PREVIEW]
        return REQUEST_SCALE.finding(
            PARAM,
            key,
            subject=p.name,
            title=f"Request attribute {p.name}",
            summary=f"{p.name}: {label}",
            evidence=evidence,
            recommendation="A conformant endpoint accepts and forwards every request parameter "
            "of its wire protocol."
            if key in ("ignored", "rejected", "dropped_by_relay")
            else None,
        )
