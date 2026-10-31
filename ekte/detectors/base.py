"""Detector base class, registry, and suite selection.

Every detector subclasses :class:`Detector`, declares its identity and the suite
tier it first appears in, implements ``run``, and registers itself with
``@register``. The runner discovers detectors through the registry, so adding a
new check is a single self-contained file.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import ClassVar

from ekte.context import AuditContext
from ekte.models import DetectorResult, Dimension, Status

# Suite tiers, cheapest to most thorough. A detector with ``min_suite="standard"``
# runs in standard, deep, and full but not smoke.
SUITE_ORDER: tuple[str, ...] = ("smoke", "standard", "deep", "full")

# The ``custom`` suite is not a tier: it runs the detectors of the selected
# dimensions at this depth.
CUSTOM_SUITE = "custom"
CUSTOM_DEPTH = "deep"

REGISTRY: dict[str, type[Detector]] = {}


def register(cls: type[Detector]) -> type[Detector]:
    if cls.id in REGISTRY:
        raise ValueError(f"Duplicate detector id: {cls.id}")
    REGISTRY[cls.id] = cls
    return cls


class Detector(ABC):
    """Base class for all checks."""

    id: ClassVar[str]
    name: ClassVar[str]
    dimension: ClassVar[Dimension]
    min_suite: ClassVar[str] = "standard"
    # The kind of endpoint this check audits ("chat" or "embedding").
    surface: ClassVar[str] = "chat"
    requires_judge: ClassVar[bool] = False
    requires_baseline: ClassVar[bool] = False
    # Approximate number of API calls this detector issues — used by `--dry-run` so
    # an agent can budget token/cost before committing. A rough upper bound is fine.
    cost_hint: ClassVar[int] = 2

    @classmethod
    def applies(cls, suite: str, *, has_baseline: bool) -> bool:
        """Extra suite gating beyond ``min_suite`` (e.g. only with a baseline)."""
        return True

    @abstractmethod
    async def run(self, ctx: AuditContext) -> DetectorResult:
        """Execute the check and return a populated result."""
        raise NotImplementedError

    # -- helpers for subclasses -------------------------------------------- #
    def new_result(self, **kwargs) -> DetectorResult:
        return DetectorResult(
            id=self.id, name=self.name, dimension=self.dimension, **kwargs
        )


def _tier(suite: str) -> int:
    if suite == CUSTOM_SUITE:
        suite = CUSTOM_DEPTH
    try:
        return SUITE_ORDER.index(suite)
    except ValueError:
        return SUITE_ORDER.index("standard")


def select_detectors(
    suite: str,
    *,
    has_judge: bool,
    has_baseline: bool,
    enabled,
    dimensions: list[str] | None = None,
    surface: str = "chat",
) -> list[Detector]:
    """Instantiate the detectors that should run for this configuration.

    Only the detectors of ``surface`` are considered (None reads as chat).
    ``enabled`` is a callable ``(detector_id) -> bool`` from :class:`AuditOptions`.
    Detectors requiring a judge/baseline are silently dropped when unavailable.
    On the ``custom`` suite only the detectors of ``dimensions`` run.
    """
    suite_tier = _tier(suite)
    custom = suite == CUSTOM_SUITE
    selected = set(dimensions or [])
    surface = surface or "chat"
    chosen: list[Detector] = []
    for det_id, cls in sorted(REGISTRY.items()):
        if cls.surface != surface:
            continue
        if _tier(cls.min_suite) > suite_tier:
            continue
        if custom and cls.dimension.value not in selected:
            continue
        if not enabled(det_id):
            continue
        if cls.requires_judge and not has_judge:
            continue
        if cls.requires_baseline and not has_baseline:
            continue
        if not cls.applies(suite, has_baseline=has_baseline):
            continue
        chosen.append(cls())
    return chosen


async def run_detector(detector: Detector, ctx: AuditContext) -> DetectorResult:
    """Run a detector, capturing timing and turning crashes into an error result."""
    started = time.perf_counter()
    try:
        result = await detector.run(ctx)
    except Exception as exc:  # a misbehaving relay must not crash the audit
        return DetectorResult(
            id=detector.id,
            name=detector.name,
            dimension=detector.dimension,
            status=Status.ERROR,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    if result.duration_ms is None:
        result.duration_ms = (time.perf_counter() - started) * 1000
    return result
