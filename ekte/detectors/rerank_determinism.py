"""Rerank determinism: the same query twice gives the same ranking and scores."""

from __future__ import annotations

from ekte.context import AuditContext
from ekte.detectors.base import register
from ekte.detectors.rerank import (
    DET_SCORE_TOLERANCE,
    RerankDetector,
    drift_probe,
    max_score_delta,
    order_flips,
    ranking,
    rerank,
    scores,
)
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, Severity, Status

SCALE = Scale(
    outcome("rerank.determinism", "deterministic", 100.0, Status.PASS,
            label="The same query twice gives the same ranking and scores."),
    outcome("rerank.determinism", "drifting", 50.0, Status.WARN, Severity.MEDIUM,
            label="The same query twice gives a different ranking or scores."),
    outcome("rerank.determinism", "no_ranking", None, Status.INCONCLUSIVE,
            label="No rankings were returned to compare."),
)


@register
class RerankDeterminismDetector(RerankDetector):
    id = "rerank.determinism"
    name = "Rerank determinism"
    dimension = Dimension.RELIABILITY
    cost_hint = 2

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        query, documents = drift_probe()
        # Two separate requests: a backend that varies between calls shows here.
        _r1, first, problem = await rerank(ctx, query, documents)
        if problem is None:
            _r2, second, problem = await rerank(ctx, query, documents)
        if problem is not None:
            result.findings.append(
                SCALE.finding(
                    "rerank.determinism", "no_ranking",
                    title="Determinism not measured",
                    summary=f"No rankings to compare: {problem}.",
                )
            )
            result.status = Status.INCONCLUSIVE
            return result
        delta = max_score_delta(scores(first), scores(second))
        # near-tied documents trading places within the tolerance still count as same
        same_order = order_flips(scores(first), scores(second), DET_SCORE_TOLERANCE) == 0
        evidence = {"same_ranking": same_order, "max_score_delta": round(delta, 8),
                    "threshold": DET_SCORE_TOLERANCE,
                    "ranking": ranking(first), "second_ranking": ranking(second)}
        if same_order and delta <= DET_SCORE_TOLERANCE:
            result.findings.append(
                SCALE.finding(
                    "rerank.determinism", "deterministic",
                    title="Rankings are deterministic",
                    summary=f"Same query twice gave the same ranking (largest score change "
                    f"{delta:.2g}).",
                    evidence=evidence,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "rerank.determinism", "drifting",
                    title="Rankings are not deterministic",
                    summary=f"Same query twice gave {'the same' if same_order else 'a different'} "
                    f"ranking with a largest score change of {delta:.2g} (tolerance "
                    f"{DET_SCORE_TOLERANCE}). A genuine reranker is deterministic; drift "
                    "suggests a noisy or re-wrapped backend.",
                    evidence=evidence,
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
