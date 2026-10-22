"""Rerank connectivity: ``POST /rerank`` returns a score for every document."""

from __future__ import annotations

from zing.context import AuditContext
from zing.detectors.base import register
from zing.detectors.rerank import RerankDetector, known_answer_probe, ranks_all
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("rerank.connectivity", "reachable", 100.0, Status.PASS,
            label="The rerank endpoint returned a ranking."),
    outcome("rerank.connectivity", "malformed", 0.0, Status.FAIL, Severity.HIGH,
            label="The rerank endpoint answered without one score per document."),
    outcome("rerank.connectivity", "failed", 0.0, Status.FAIL, Severity.HIGH,
            label="The rerank request failed."),
)


@register
class RerankConnectivityDetector(RerankDetector):
    id = "rerank.connectivity"
    name = "Rerank endpoint connectivity"
    dimension = Dimension.CONNECTIVITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        query, documents = known_answer_probe()
        res, results = await ctx.client.rerank(query, documents)
        if not res.ok:
            result.findings.append(
                SCALE.finding(
                    "rerank.connectivity", "failed",
                    title="Rerank endpoint unreachable",
                    summary=f"POST /rerank failed: {res.error_message or res.status_code}",
                    evidence={"status_code": res.status_code, "error": res.error_message},
                    recommendation="Verify base_url, api_key, and that the model id is served.",
                )
            )
        elif not ranks_all(results, documents):
            result.findings.append(
                SCALE.finding(
                    "rerank.connectivity", "malformed",
                    title="Rerank response malformed",
                    summary=f"Expected a score for each of {len(documents)} documents, "
                    f"got {len(results)} results.",
                    evidence={"results": len(results), "documents": len(documents)},
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "rerank.connectivity", "reachable",
                    title="Rerank endpoint reachable",
                    summary=f"Got {len(results)} ranked results in {res.duration_ms:.0f} ms.",
                    evidence={"results": len(results), "duration_ms": res.duration_ms},
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
