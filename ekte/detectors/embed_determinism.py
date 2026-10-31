"""Embedding determinism: the same input twice gives the same vector."""

from __future__ import annotations

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import register
from ekte.detectors.embedding import DET_MIN_COSINE, EmbeddingDetector, cosine_similarity, embed
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("embed.determinism", "deterministic", 100.0, Status.PASS,
            label="The same input twice gives the same vector."),
    outcome("embed.determinism", "drifting", 50.0, Status.WARN, Severity.MEDIUM,
            label="The same input twice gives different vectors."),
    outcome("embed.determinism", "no_vector", None, Status.INCONCLUSIVE,
            label="No vectors were returned to compare."),
)


@register
class EmbedDeterminismDetector(EmbeddingDetector):
    id = "embed.determinism"
    name = "Embedding determinism"
    dimension = Dimension.RELIABILITY
    cost_hint = 2

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        text = prompts.text("embed.determinism_input")
        # Two separate requests: a backend that varies between calls shows here.
        _r1, first, problem = await embed(ctx, [text])
        if problem is None:
            _r2, second, problem = await embed(ctx, [text])
        if problem is not None:
            result.findings.append(
                SCALE.finding(
                    "embed.determinism", "no_vector",
                    title="Determinism not measured",
                    summary=f"No vectors to compare: {problem}.",
                )
            )
            result.status = Status.INCONCLUSIVE
            return result
        cos = cosine_similarity(first[0], second[0])
        evidence = {"cosine": cos, "threshold": DET_MIN_COSINE}
        if cos >= DET_MIN_COSINE:
            result.findings.append(
                SCALE.finding(
                    "embed.determinism", "deterministic",
                    title="Embeddings are deterministic",
                    summary=f"Same input twice gave cosine {cos:.6f} (~1.0).",
                    evidence=evidence,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "embed.determinism", "drifting",
                    title="Embeddings are not deterministic",
                    summary=f"Same input twice gave cosine {cos:.6f}, below {DET_MIN_COSINE}. "
                    "A genuine embedding model is deterministic; drift suggests a noisy or "
                    "re-wrapped backend.",
                    evidence=evidence,
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
