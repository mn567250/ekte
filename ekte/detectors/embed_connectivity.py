"""Embedding connectivity: ``POST /embeddings`` returns one vector per input."""

from __future__ import annotations

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import register
from zing.detectors.embedding import EmbeddingDetector
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("embed.connectivity", "reachable", 100.0, Status.PASS,
            label="The embeddings endpoint returned vectors."),
    outcome("embed.connectivity", "malformed", 0.0, Status.FAIL, Severity.HIGH,
            label="The embeddings endpoint answered without one vector per input."),
    outcome("embed.connectivity", "failed", 0.0, Status.FAIL, Severity.HIGH,
            label="The embeddings request failed."),
)


@register
class EmbedConnectivityDetector(EmbeddingDetector):
    id = "embed.connectivity"
    name = "Embedding endpoint connectivity"
    dimension = Dimension.CONNECTIVITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        inputs = [prompts.text("embed.distinct_a"), prompts.text("embed.distinct_b")]
        res, vectors = await ctx.client.embeddings(inputs)
        if not res.ok:
            result.findings.append(
                SCALE.finding(
                    "embed.connectivity", "failed",
                    title="Embedding endpoint unreachable",
                    summary=f"POST /embeddings failed: {res.error_message or res.status_code}",
                    evidence={"status_code": res.status_code, "error": res.error_message},
                    recommendation="Verify base_url, api_key, and that the model id is served.",
                )
            )
        elif len(vectors) != len(inputs) or any(not v for v in vectors):
            result.findings.append(
                SCALE.finding(
                    "embed.connectivity", "malformed",
                    title="Embedding response malformed",
                    summary=f"Expected {len(inputs)} non-empty vectors, got {len(vectors)}.",
                    evidence={"returned_vectors": len(vectors)},
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "embed.connectivity", "reachable",
                    title="Embedding endpoint reachable",
                    summary=f"Got {len(vectors)} vectors of dimension {len(vectors[0])} "
                    f"in {res.duration_ms:.0f} ms.",
                    evidence={"vectors": len(vectors), "dimension": len(vectors[0]),
                              "duration_ms": res.duration_ms},
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
