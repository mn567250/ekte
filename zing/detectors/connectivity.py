"""Connectivity detector — the canonical example all detectors mirror.

Checks the two most basic things: is the endpoint reachable, and does a plain
chat completion for the claimed model actually return content. Everything else
builds on this passing. Each check scores points from the published scale
``SCALE``; the detector score is their average and its status the worst of
their statuses.
"""

from __future__ import annotations

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.helpers import contains_ci, stable_marker
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, RequestSpec, Severity, Status

SCALE = Scale(
    outcome("connectivity.models", "listed", 100.0, Status.PASS,
            label="The model list (/v1/models) responded."),
    outcome("connectivity.models", "unavailable", 60.0, Status.WARN, Severity.LOW,
            label="The model list (/v1/models) did not respond; some relays disable it."),
    outcome("connectivity.chat", "canary_echoed", 100.0, Status.PASS,
            label="A chat completion returned content and echoed the canary."),
    outcome("connectivity.chat", "canary_missing", 85.0, Status.PASS,
            label="A chat completion returned content but did not echo the canary."),
    outcome("connectivity.chat", "failed", 0.0, Status.FAIL, Severity.HIGH,
            label="The chat completion failed or returned no content."),
)


@register
class ConnectivityDetector(Detector):
    id = "connectivity"
    name = "Connectivity & basic completion"
    dimension = Dimension.CONNECTIVITY
    min_suite = "smoke"

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())

        # 1) /models reachability (secondary — some relays disable it).
        models_outcome, model_ids = await ctx.client.list_models()
        if models_outcome.ok:
            claimed_listed = any(ctx.target.model == mid for mid in model_ids)
            result.findings.append(
                SCALE.finding(
                    "connectivity.models",
                    "listed",
                    title="/v1/models reachable",
                    summary=(
                        f"Listed {len(model_ids)} models; claimed model "
                        f"{'is' if claimed_listed else 'is NOT'} present."
                    ),
                    evidence={"model_count": len(model_ids), "claimed_listed": claimed_listed},
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "connectivity.models",
                    "unavailable",
                    title="/v1/models not reachable",
                    summary=models_outcome.error_message or f"HTTP {models_outcome.status_code}",
                    evidence={"status_code": models_outcome.status_code},
                )
            )

        # 2) Basic chat completion with an exact canary (most important signal).
        marker = stable_marker("connectivity")
        spec = RequestSpec(
            messages=[
                {"role": "user", "content": prompts.text("connectivity.echo", marker=marker)}
            ],
            temperature=0.0,
            max_tokens=32,
        )
        chat = await ctx.client.complete(spec)
        if chat.ok and chat.has_content():
            recalled = contains_ci(chat.content, marker)
            result.findings.append(
                SCALE.finding(
                    "connectivity.chat",
                    "canary_echoed" if recalled else "canary_missing",
                    title="Basic chat completion works",
                    summary=f"Returned content in {chat.duration_ms:.0f} ms; canary {'echoed' if recalled else 'not echoed'}.",
                    evidence={
                        "duration_ms": chat.duration_ms,
                        "model_returned": chat.model_returned,
                        "canary_echoed": recalled,
                    },
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "connectivity.chat",
                    "failed",
                    title="Basic chat completion failed",
                    summary=chat.error_message or f"HTTP {chat.status_code}",
                    evidence={"status_code": chat.status_code, "error_type": chat.error_type},
                    recommendation="Verify base_url, api_key, and that the model id is served.",
                )
            )

        # Like every scale-based detector, the status is the worst of its checks:
        # a disabled /models is a WARN even when chat works (score 80).
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        result.evidence["model_ids_sample"] = model_ids[:20]
        return result
