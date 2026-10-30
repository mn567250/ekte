"""Embedding vector drift: a pinned input's vector against the previous saved
run of the same target and claimed model (a silent model swap shows here).

Only a small rounded sample of the vector is kept in the report evidence."""

from __future__ import annotations

import math
from typing import Any

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import register
from ekte.detectors.embedding import EmbeddingDetector, cosine_similarity, embed, sha
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, Severity, Status

# Vector drift on the pinned input, as the cosine of the stored samples.
DRIFT_STABLE = 0.995
DRIFT_SHIFTED = 0.95
# Leading components of the (unit-length) pinned vector kept in the report —
# enough to compare runs, far less than the whole vector.
DRIFT_SAMPLE = 64
DRIFT_DIGITS = 5

SCALE = Scale(
    outcome("embed.drift", "stable", 100.0, Status.PASS,
            label="The pinned input's vector matches the previous run."),
    outcome("embed.drift", "shifted", 60.0, Status.WARN, Severity.MEDIUM,
            label="The pinned input's vector moved since the previous run (cosine 0.95 to 0.995)."),
    outcome("embed.drift", "swapped", 0.0, Status.FAIL, Severity.HIGH,
            label="The pinned input's vector changed since the previous run (cosine below 0.95, "
            "or another length): the model was swapped."),
    outcome("embed.drift", "baseline", None, Status.INFO,
            label="No previous run to compare with; this run's vector is the baseline."),
    outcome("embed.drift", "no_vector", None, Status.INCONCLUSIVE,
            label="No vector was returned for the pinned input."),
)


def drift_sample(vector: list[float]) -> list[float]:
    """The leading components of the unit-length vector, rounded."""
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [round(x / norm, DRIFT_DIGITS) for x in vector[:DRIFT_SAMPLE]]


def previous_drift(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """The drift evidence (dimension, sample, input hash) a saved report recorded."""
    if not isinstance(report, dict):
        return None
    for det in report.get("detectors") or []:
        if not isinstance(det, dict) or det.get("id") != "embed.drift":
            continue
        for f in det.get("findings") or []:
            ev = f.get("evidence") if isinstance(f, dict) else None
            if isinstance(ev, dict) and isinstance(ev.get("sample"), list) and ev.get("dimension"):
                return ev
    return None


@register
class EmbedDriftDetector(EmbeddingDetector):
    id = "embed.drift"
    name = "Embedding vector drift"
    dimension = Dimension.MODEL_IDENTITY

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        text = prompts.text("embed.drift_input")
        _res, vectors, problem = await embed(ctx, [text])
        if problem is not None:
            result.findings.append(
                SCALE.finding(
                    "embed.drift", "no_vector",
                    title="Vector drift not measured",
                    summary=f"No vector for the pinned input: {problem}.",
                )
            )
            result.status = Status.INCONCLUSIVE
            return result

        vector = vectors[0]
        sample = drift_sample(vector)
        evidence: dict[str, Any] = {
            "input_sha": sha(text),
            "dimension": len(vector),
            "sample": sample,
        }
        prev = previous_drift(ctx.previous_report)
        if prev is None or prev.get("input_sha") != evidence["input_sha"]:
            result.findings.append(
                SCALE.finding(
                    "embed.drift", "baseline",
                    title="Vector drift baseline recorded",
                    summary="No previous run of this target and model recorded a vector for "
                    "the pinned input; this run's vector is the baseline for the next one.",
                    evidence=evidence,
                )
            )
        else:
            if prev["dimension"] != len(vector):
                cos = 0.0
            else:
                cos = cosine_similarity(sample, [float(x) for x in prev["sample"]])
            key = "stable" if cos >= DRIFT_STABLE else "shifted" if cos >= DRIFT_SHIFTED else "swapped"
            evidence.update(
                cosine=round(cos, 6),
                previous_dimension=prev["dimension"],
                previous_generated_at=(ctx.previous_report or {}).get("generated_at"),
            )
            result.findings.append(
                SCALE.finding(
                    "embed.drift", key,
                    title="Vector unchanged since the previous run" if key == "stable"
                    else "Vector shifted since the previous run" if key == "shifted"
                    else "Vector changed since the previous run",
                    summary=f"The pinned input's vector has cosine {cos:.4f} with the previous "
                    f"run's ({len(vector)}-d now, {prev['dimension']}-d then).",
                    evidence=evidence,
                    recommendation="A different vector for the same input means the relay now "
                    "serves another model; stored embeddings no longer match new ones."
                    if key == "swapped" else None,
                )
            )
        result.status = Scale.roll_up(result.findings)
        result.score = Scale.mean(result.findings)
        return result
