"""Embedding model identity: the vector length against the claimed model's,
and the model field the relay echoes."""

from __future__ import annotations

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors import advice
from ekte.detectors.base import register
from ekte.detectors.embedding import EmbeddingDetector, embed
from ekte.detectors.scale import Scale, outcome
from ekte.knowledge.model_ids import compare_echoed_model
from ekte.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("embed.dimension", "match", 100.0, Status.PASS,
            label="The vector length matches the claimed model."),
    outcome("embed.dimension", "mismatch", 0.0, Status.FAIL, Severity.HIGH,
            label="The vector length differs from the claimed model's (another model is served)."),
    outcome("embed.dimension", "unknown", None, Status.INFO,
            label="The claimed model's vector length is unknown; the observed length is recorded."),
    outcome("embed.dimension", "no_vector", None, Status.INCONCLUSIVE,
            label="No vector was returned to measure."),
    outcome("embed.model_field", "matches", 100.0, Status.PASS,
            label="The relay echoes the requested model."),
    outcome("embed.model_field", "differs", 50.0, Status.WARN, Severity.MEDIUM,
            label="The relay echoes a different model than the one requested."),
    outcome("embed.model_field", "unknown", None, Status.INFO,
            label="The relay echoes a different model id that ekte cannot place: recorded, not judged."),
    outcome("embed.model_field", "missing", None, Status.INFO,
            label="The relay echoes no model field."),
)

# compare_echoed_model's verdict -> the embedding/rerank scale outcome.
ECHO_OUTCOMES = {"consistent": "matches", "diverges": "differs", "unknown": "unknown"}


def echoed_model_outcome(ctx: AuditContext, echoed: str | None) -> tuple[str, dict]:
    """The ``*.model_field`` outcome key for the echoed model id, with the
    comparison's evidence. Compared as the chat identity detector does:
    knowledge base first, see ekte.knowledge.model_ids."""
    if not echoed:
        return "missing", {}
    cmp = compare_echoed_model(
        ctx.kb, echoed, ctx.target.claimed, ctx.target.model, claimed_profile=ctx.profile
    )
    return ECHO_OUTCOMES[cmp.verdict], cmp.evidence()


@register
class EmbedIdentityDetector(EmbeddingDetector):
    id = "embed.identity"
    name = "Embedding model identity"
    dimension = Dimension.MODEL_IDENTITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        res, vectors, problem = await embed(ctx, [prompts.text("embed.determinism_input")])
        claimed = ctx.embedding_dimensions()
        if problem is not None:
            result.findings.append(
                SCALE.finding(
                    "embed.dimension", "no_vector",
                    calls=[res],
                    title="Vector dimension not measured",
                    summary=f"No vector to measure: {problem}.",
                    recommendation=advice.failure_advice(res),
                    evidence={"claimed": claimed},
                )
            )
            result.status = Status.INCONCLUSIVE
            return result

        returned = len(vectors[0])
        evidence = {"returned": returned, "claimed": claimed}
        if claimed <= 0:
            result.findings.append(
                SCALE.finding(
                    "embed.dimension", "unknown",
                    calls=[res],
                    title="Claimed dimension unknown — recording observed dimension",
                    summary=f"No KB dimension for the claimed model; observed {returned}-d.",
                    evidence=evidence,
                )
            )
        elif returned == claimed:
            result.findings.append(
                SCALE.finding(
                    "embed.dimension", "match",
                    calls=[res],
                    title="Vector dimension matches the claimed model",
                    summary=f"Returned {returned}-d vectors, as expected for the claim.",
                    evidence=evidence,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "embed.dimension", "mismatch",
                    calls=[res],
                    title="Vector dimension does NOT match the claimed model",
                    summary=f"Returned {returned}-d vectors but the claimed model produces "
                    f"{claimed}-d. Strong evidence of a substituted embedding model.",
                    evidence=evidence,
                    recommendation="Ask the relay which embedding model it serves; vectors of "
                    "another length are not interchangeable with the claimed model's.",
                )
            )

        echoed = res.model_returned
        key, comparison = echoed_model_outcome(ctx, echoed)
        result.findings.append(
            SCALE.finding(
                "embed.model_field", key,
                calls=[res],
                title="Echoed model field" if key != "differs"
                else "Echoed model field differs from the request",
                summary=f"Relay reported model: {echoed or '(none)'}.",
                evidence={
                    "model_returned": echoed,
                    "model_requested": ctx.target.model,
                    "claimed_model": ctx.target.claimed_model,
                    **comparison,
                },
            )
        )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
