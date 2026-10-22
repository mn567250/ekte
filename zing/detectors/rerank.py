"""Shared helpers of the rerank-surface detectors.

A reranker returns a relevance score per document, not chat or vectors, so the
rerank surface has its own detectors, scored on the same dimensions:

* ``rerank.connectivity`` — ``POST /rerank`` returns a ranking (CONNECTIVITY);
* ``rerank.known_answer`` — a probe with one obviously relevant document must
  rank it first (CAPABILITY);
* ``rerank.identity`` — the echoed model field (MODEL_IDENTITY);
* ``rerank.drift`` — the ranking and scores of a pinned probe against the
  previous saved run of the same target and claimed model; a different ranking
  means a silent model swap (MODEL_IDENTITY);
* ``rerank.determinism`` — the same query twice gives the same ranking and
  scores (RELIABILITY).
"""

from __future__ import annotations

from typing import Any

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector

SURFACE = "rerank"

# Index of the obviously relevant document in ``rerank.web.documents``.
KNOWN_ANSWER_TOP = 2
# Same query twice: scores equal up to this share of their magnitude (at least 1).
DET_SCORE_TOLERANCE = 1e-4


def known_answer_probe() -> tuple[str, list[str]]:
    """The known-answer probe: (query, documents), ``KNOWN_ANSWER_TOP`` first."""
    return prompts.text("rerank.web.query"), list(prompts.get("rerank.web.documents"))


def drift_probe() -> tuple[str, list[str]]:
    """The pinned probe of graded relevance: (query, documents)."""
    return prompts.text("rerank.drift.query"), list(prompts.get("rerank.drift.documents"))


def score_delta(a: float, b: float) -> float:
    """The difference of two scores relative to their magnitude (at least 1), so
    probability-like and logit-like scores are judged alike."""
    return abs(a - b) / max(1.0, abs(a), abs(b))


def max_score_delta(first: dict[int, float], second: dict[int, float]) -> float:
    """The largest :func:`score_delta` over the documents both runs scored."""
    common = first.keys() & second.keys()
    return max((score_delta(first[i], second[i]) for i in common), default=0.0)


def order_flips(first: dict[int, float], second: dict[int, float], tolerance: float) -> int:
    """Pairs of documents the two runs order oppositely, each by more than
    ``tolerance`` (:func:`score_delta`): near-tied documents trading places
    from float jitter do not count."""
    common = sorted(first.keys() & second.keys())
    flips = 0
    for n, i in enumerate(common):
        for j in common[n + 1:]:
            a, b = first[i] - first[j], second[i] - second[j]
            if (a * b < 0 and score_delta(first[i], first[j]) > tolerance
                    and score_delta(second[i], second[j]) > tolerance):
                flips += 1
    return flips


def ranking(results: list[dict[str, Any]]) -> list[int]:
    return [r["index"] for r in results]


def scores(results: list[dict[str, Any]]) -> dict[int, float]:
    return {r["index"]: r["relevance_score"] for r in results}


def ranks_all(results: list[dict[str, Any]], documents: list[str]) -> bool:
    """Whether the results score every document exactly once."""
    return sorted(ranking(results)) == list(range(len(documents)))


async def rerank(
    ctx: AuditContext, query: str, documents: list[str]
) -> tuple[Any, list[dict[str, Any]], str | None]:
    """One rerank call: (outcome, results, problem) — ``problem`` is set when the
    call failed or did not score every document exactly once."""
    result, results = await ctx.client.rerank(query, documents)
    if not result.ok:
        return result, [], (
            result.error_message or result.error_type or f"HTTP {result.status_code}"
        )
    if not ranks_all(results, documents):
        return result, [], (
            f"expected a score for each of {len(documents)} documents, got {len(results)} results"
        )
    return result, results, None


class RerankDetector(Detector):
    surface = SURFACE
    min_suite = "smoke"
    cost_hint = 1
