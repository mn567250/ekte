"""Embedding model identity: the vector length against the claimed model's,
and the model field the relay echoes."""

from __future__ import annotations

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import register
from ekte.detectors.embedding import EmbeddingDetector, embed
from ekte.detectors.scale import Scale, outcome
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
    outcome("embed.model_field", "missing", None, Status.INFO,
            label="The relay echoes no model field."),
)


def _model_key(name: str | None) -> str:
    """A model id without provider prefix or case, for a loose comparison."""
    return (name or "").strip().lower().rsplit("/", 1)[-1]


def echoes_model(returned: str | None, *requested: str | None) -> bool:
    """Whether the echoed model names the requested one (a dated or prefixed
    variant of the same id counts)."""
    got = _model_key(returned)
    return any(
        want and (got == want or got.startswith(want) or want.startswith(got))
        for want in map(_model_key, requested)
    )


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
                    title="Vector dimension not measured",
                    summary=f"No vector to measure: {problem}.",
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
                    title="Claimed dimension unknown — recording observed dimension",
                    summary=f"No KB dimension for the claimed model; observed {returned}-d.",
                    evidence=evidence,
                )
            )
        elif returned == claimed:
            result.findings.append(
                SCALE.finding(
                    "embed.dimension", "match",
                    title="Vector dimension matches the claimed model",
                    summary=f"Returned {returned}-d vectors, as expected for the claim.",
                    evidence=evidence,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "embed.dimension", "mismatch",
                    title="Vector dimension does NOT match the claimed model",
                    summary=f"Returned {returned}-d vectors but the claimed model produces "
                    f"{claimed}-d. Strong evidence of a substituted embedding model.",
                    evidence=evidence,
                    recommendation="Ask the relay which embedding model it serves; vectors of "
                    "another length are not interchangeable with the claimed model's.",
                )
            )

        echoed = res.model_returned
        key = (
            "missing" if not echoed
            else "matches" if echoes_model(echoed, ctx.target.model, ctx.target.claimed)
            else "differs"
        )
        result.findings.append(
            SCALE.finding(
                "embed.model_field", key,
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
