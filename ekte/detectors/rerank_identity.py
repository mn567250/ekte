"""Rerank model identity: the model field the relay echoes."""

from __future__ import annotations

from ekte.context import AuditContext
from ekte.detectors.base import register
from ekte.detectors.embed_identity import echoes_model
from ekte.detectors.rerank import RerankDetector, known_answer_probe
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("rerank.model_field", "matches", 100.0, Status.PASS,
            label="The relay echoes the requested model."),
    outcome("rerank.model_field", "differs", 50.0, Status.WARN, Severity.MEDIUM,
            label="The relay echoes a different model than the one requested."),
    outcome("rerank.model_field", "missing", None, Status.INFO,
            label="The relay echoes no model field."),
    outcome("rerank.model_field", "no_response", None, Status.INCONCLUSIVE,
            label="The rerank request failed; there is no model field to check."),
)


@register
class RerankIdentityDetector(RerankDetector):
    id = "rerank.identity"
    name = "Rerank model identity"
    dimension = Dimension.MODEL_IDENTITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        query, documents = known_answer_probe()
        res, _results = await ctx.client.rerank(query, documents)
        if not res.ok:
            result.findings.append(
                SCALE.finding(
                    "rerank.model_field", "no_response",
                    title="Echoed model field not checked",
                    summary=f"POST /rerank failed: {res.error_message or res.status_code}.",
                    evidence={"status_code": res.status_code},
                )
            )
            result.status = Status.INCONCLUSIVE
            return result

        echoed = res.model_returned
        key = (
            "missing" if not echoed
            else "matches" if echoes_model(echoed, ctx.target.model, ctx.target.claimed)
            else "differs"
        )
        result.findings.append(
            SCALE.finding(
                "rerank.model_field", key,
                title="Echoed model field" if key != "differs"
                else "Echoed model field differs from the request",
                summary=f"Relay reported model: {echoed or '(none)'}.",
                evidence={
                    "model_returned": echoed,
                    "model_requested": ctx.target.model,
                    "claimed_model": ctx.target.claimed_model,
                },
            )
        )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
