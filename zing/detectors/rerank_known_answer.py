"""Rerank known answer: a probe with one obviously relevant document must rank
it first (a stub or a random shuffle does not)."""

from __future__ import annotations

from zing.context import AuditContext
from zing.detectors.base import register
from zing.detectors.rerank import (
    KNOWN_ANSWER_TOP,
    RerankDetector,
    known_answer_probe,
    ranking,
    rerank,
)
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("rerank.known_answer", "first", 100.0, Status.PASS,
            label="The obviously relevant document is ranked first."),
    outcome("rerank.known_answer", "missed", 0.0, Status.FAIL, Severity.HIGH,
            label="Another document is ranked above the obviously relevant one."),
    outcome("rerank.known_answer", "no_ranking", None, Status.INCONCLUSIVE,
            label="No ranking was returned to check."),
)


@register
class RerankKnownAnswerDetector(RerankDetector):
    id = "rerank.known_answer"
    name = "Rerank known-answer probe"
    dimension = Dimension.CAPABILITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        query, documents = known_answer_probe()
        _res, results, problem = await rerank(ctx, query, documents)
        if problem is not None:
            result.findings.append(
                SCALE.finding(
                    "rerank.known_answer", "no_ranking",
                    title="Known-answer ranking not checked",
                    summary=f"No ranking to check: {problem}.",
                )
            )
            result.status = Status.INCONCLUSIVE
            return result

        top = results[0]
        evidence = {"top_index": top["index"], "expected": KNOWN_ANSWER_TOP,
                    "ranking": ranking(results)}
        if top["index"] == KNOWN_ANSWER_TOP:
            result.findings.append(
                SCALE.finding(
                    "rerank.known_answer", "first",
                    title="Reranker ranks the obvious answer first",
                    summary=f"Document {KNOWN_ANSWER_TOP} (the clearly relevant one) ranked "
                    f"first with score {top['relevance_score']:.4f}.",
                    evidence=evidence,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "rerank.known_answer", "missed",
                    title="Reranker does NOT rank the obvious answer first",
                    summary=f"Expected document {KNOWN_ANSWER_TOP} to rank first, but document "
                    f"{top['index']} did. A genuine relevance model ranks it first.",
                    evidence=evidence,
                    recommendation="Ask the relay which rerank model it serves; a ranking that "
                    "misses an obvious answer is not a genuine reranker's.",
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
