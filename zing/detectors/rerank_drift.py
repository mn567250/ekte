"""Rerank drift: the ranking and scores of a pinned probe against the previous
saved run of the same target and claimed model (a silent model swap shows here).

The report evidence keeps the ranking and the rounded score of each document."""

from __future__ import annotations

from typing import Any

from zing.context import AuditContext
from zing.detectors.base import register
from zing.detectors.embedding import sha
from zing.detectors.rerank import RerankDetector, drift_probe, max_score_delta, ranking, rerank
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, Severity, Status

# Largest score change on the pinned probe, relative to the score's magnitude
# (at least 1), with the same ranking.
DRIFT_STABLE = 0.01
DRIFT_SHIFTED = 0.1
DRIFT_DIGITS = 5

SCALE = Scale(
    outcome("rerank.drift", "stable", 100.0, Status.PASS,
            label="The pinned probe's ranking and scores match the previous run."),
    outcome("rerank.drift", "shifted", 60.0, Status.WARN, Severity.MEDIUM,
            label="The pinned probe's scores moved since the previous run (by 1% to 10%), "
            "with the same ranking."),
    outcome("rerank.drift", "swapped", 0.0, Status.FAIL, Severity.HIGH,
            label="The pinned probe's ranking changed since the previous run, or its scores "
            "moved by more than 10%: the model was swapped."),
    outcome("rerank.drift", "baseline", None, Status.INFO,
            label="No previous run to compare with; this run's ranking is the baseline."),
    outcome("rerank.drift", "no_ranking", None, Status.INCONCLUSIVE,
            label="No ranking was returned for the pinned probe."),
)


def probe_sha(query: str, documents: list[str]) -> str:
    """A short hash of the probe, so a changed probe is not taken for drift."""
    return sha("\n".join([query, *documents]))


def previous_drift(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """The drift evidence (ranking, scores, probe hash) a saved report recorded."""
    if not isinstance(report, dict):
        return None
    for det in report.get("detectors") or []:
        if not isinstance(det, dict) or det.get("id") != "rerank.drift":
            continue
        for f in det.get("findings") or []:
            ev = f.get("evidence") if isinstance(f, dict) else None
            if (isinstance(ev, dict) and isinstance(ev.get("ranking"), list)
                    and isinstance(ev.get("scores"), list) and ev.get("probe_sha")):
                return ev
    return None


@register
class RerankDriftDetector(RerankDetector):
    id = "rerank.drift"
    name = "Rerank drift"
    dimension = Dimension.MODEL_IDENTITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        query, documents = drift_probe()
        _res, results, problem = await rerank(ctx, query, documents)
        if problem is not None:
            result.findings.append(
                SCALE.finding(
                    "rerank.drift", "no_ranking",
                    title="Rerank drift not measured",
                    summary=f"No ranking for the pinned probe: {problem}.",
                )
            )
            result.status = Status.INCONCLUSIVE
            return result

        by_index = {r["index"]: r["relevance_score"] for r in results}
        evidence: dict[str, Any] = {
            "probe_sha": probe_sha(query, documents),
            "ranking": ranking(results),
            # in document order, so a run is compared document by document
            "scores": [round(by_index[i], DRIFT_DIGITS) for i in range(len(documents))],
        }
        prev = previous_drift(ctx.previous_report)
        if prev is None or prev.get("probe_sha") != evidence["probe_sha"]:
            result.findings.append(
                SCALE.finding(
                    "rerank.drift", "baseline",
                    title="Rerank drift baseline recorded",
                    summary="No previous run of this target and model recorded a ranking for "
                    "the pinned probe; this run's ranking is the baseline for the next one.",
                    evidence=evidence,
                )
            )
        else:
            current = dict(enumerate(evidence["scores"]))
            previous = {i: float(s) for i, s in enumerate(prev["scores"])}
            delta = max_score_delta(current, previous)
            same_order = [int(i) for i in prev["ranking"]] == evidence["ranking"]
            key = (
                "swapped" if not same_order or delta > DRIFT_SHIFTED
                else "shifted" if delta > DRIFT_STABLE
                else "stable"
            )
            evidence.update(
                max_score_delta=round(delta, 6),
                same_ranking=same_order,
                previous_ranking=prev["ranking"],
                previous_generated_at=(ctx.previous_report or {}).get("generated_at"),
            )
            result.findings.append(
                SCALE.finding(
                    "rerank.drift", key,
                    title="Ranking unchanged since the previous run" if key == "stable"
                    else "Scores shifted since the previous run" if key == "shifted"
                    else "Ranking changed since the previous run",
                    summary=f"The pinned probe's ranking is {'the same as' if same_order else 'different from'} "
                    f"the previous run's; the largest score change is {delta:.2%}.",
                    evidence=evidence,
                    recommendation="A different ranking for the same probe means the relay now "
                    "serves another model; search results will no longer match earlier ones."
                    if key == "swapped" else None,
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
