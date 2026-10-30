"""Embedding distinctness: unrelated inputs give clearly different vectors."""

from __future__ import annotations

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import register
from zing.detectors.embedding import (
    DISTINCT_MAX_COSINE,
    EmbeddingDetector,
    cosine_similarity,
    embed,
)
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("embed.distinctness", "distinct", 100.0, Status.PASS,
            label="Unrelated inputs give clearly different vectors."),
    outcome("embed.distinctness", "collapsed", 30.0, Status.WARN, Severity.HIGH,
            label="Unrelated inputs give near-identical vectors (a degenerate or stub backend)."),
    outcome("embed.distinctness", "no_vector", None, Status.INCONCLUSIVE,
            label="No vectors were returned to compare."),
)


@register
class EmbedDistinctnessDetector(EmbeddingDetector):
    id = "embed.distinctness"
    name = "Embedding distinctness"
    dimension = Dimension.CAPABILITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        _res, vectors, problem = await embed(
            ctx, [prompts.text("embed.distinct_a"), prompts.text("embed.distinct_b")]
        )
        if problem is not None:
            result.findings.append(
                SCALE.finding(
                    "embed.distinctness", "no_vector",
                    title="Distinctness not measured",
                    summary=f"No vectors to compare: {problem}.",
                )
            )
            result.status = Status.INCONCLUSIVE
            return result
        cos = cosine_similarity(vectors[0], vectors[1])
        evidence = {"cosine": cos, "threshold": DISTINCT_MAX_COSINE}
        if cos < DISTINCT_MAX_COSINE:
            result.findings.append(
                SCALE.finding(
                    "embed.distinctness", "distinct",
                    title="Different inputs produce distinct vectors",
                    summary=f"Unrelated texts gave cosine {cos:.4f} (< {DISTINCT_MAX_COSINE}).",
                    evidence=evidence,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "embed.distinctness", "collapsed",
                    title="Different inputs produce near-identical vectors",
                    summary=f"Two unrelated texts gave cosine {cos:.4f} (>= {DISTINCT_MAX_COSINE}). "
                    "Vectors that barely vary across inputs indicate a degenerate or stub "
                    "embedding backend.",
                    evidence=evidence,
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
