"""Shared helpers of the embedding-surface detectors.

The chat checks (identity probes, streaming, tool calls, ...) mean nothing for a
model that returns a vector, so the embedding surface has its own detectors,
scored on the same dimensions:

* ``embed.connectivity`` — ``POST /embeddings`` returns vectors (CONNECTIVITY);
* ``embed.identity`` — the vector length against the claimed model's (the
  headline 货不对板 signal: a relay claiming a 3072-d model but returning 1536-d
  vectors serves another model) and the echoed model field (MODEL_IDENTITY);
* ``embed.drift`` — a pinned input's vector against the previous saved run of
  the same target and claimed model; a different vector means a silent model
  swap (MODEL_IDENTITY);
* ``embed.determinism`` — the same input twice gives the same vector (RELIABILITY);
* ``embed.distinctness`` — unrelated inputs give clearly different vectors
  (CAPABILITY);
* ``performance.embed`` — the performance probe (:mod:`zing.detectors.embed_performance`).

All math is pure stdlib — no numpy dependency.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from zing.context import AuditContext
from zing.detectors.base import Detector

SURFACE = "embedding"

# Same input twice should be essentially identical; unrelated texts comfortably
# below 1.0 (identical vectors for different inputs is the tell).
DET_MIN_COSINE = 0.9999
DISTINCT_MAX_COSINE = 0.98


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors. 0.0 if either is degenerate."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def embed(ctx: AuditContext, inputs: list[str]) -> tuple[Any, list[list[float]], str | None]:
    """One embeddings call: (outcome, vectors, problem) — ``problem`` is set when
    the call failed or did not return one non-empty vector per input."""
    result, vectors = await ctx.client.embeddings(inputs)
    if not result.ok:
        return result, [], result.error_message or f"HTTP {result.status_code}"
    if len(vectors) != len(inputs) or any(not v for v in vectors):
        return result, [], f"expected {len(inputs)} non-empty vectors, got {len(vectors)}"
    return result, vectors, None


class EmbeddingDetector(Detector):
    surface = SURFACE
    min_suite = "smoke"
    cost_hint = 1
