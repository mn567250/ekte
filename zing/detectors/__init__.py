"""Detector package.

Importing this package imports every detector module, which runs each
``@register`` decorator and populates :data:`zing.detectors.base.REGISTRY`. The
runner relies on that side effect to discover detectors.
"""

from zing.detectors import (  # noqa: F401  -- imported for registration side effects
    billing,
    capability,
    connectivity,
    context_window,
    determinism,
    embed_connectivity,
    embed_determinism,
    embed_distinctness,
    embed_drift,
    embed_identity,
    embed_performance,
    injected_prompt,
    integrity,
    model_identity,
    performance,
    prompt_cache,
    protocol,
    protocol_attrs,
    quality_judge,  # noqa: F401
    reliability,
    rerank_connectivity,
    rerank_determinism,
    rerank_drift,
    rerank_identity,
    rerank_known_answer,
    security,
    streaming,
    vision,
)
from zing.detectors.base import (
    REGISTRY,
    Detector,
    register,
    run_detector,
    select_detectors,
)

__all__ = ["REGISTRY", "Detector", "register", "run_detector", "select_detectors"]
