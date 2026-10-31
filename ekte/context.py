"""The runtime context handed to every detector.

A detector receives one ``AuditContext`` and returns a ``DetectorResult``. The
context bundles the live target client, the resolved knowledge-base profile for
the claimed model, run options, and (optionally) a baseline client and an LLM
judge. Detectors must not mutate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ekte.clients import Client
from ekte.config import AuditOptions
from ekte.judge import Judge
from ekte.knowledge import KnowledgeBase, ResolvedProfile
from ekte.knowledge.schema import PerformanceReference
from ekte.models import TargetConfig
from ekte.perf import RequestRecorder


@dataclass
class AuditContext:
    target: TargetConfig
    client: Client
    options: AuditOptions
    kb: KnowledgeBase
    profile: ResolvedProfile | None = None
    baseline: TargetConfig | None = None
    baseline_client: Client | None = None
    judge: Judge | None = None
    # Logs every target/baseline call for the performance section.
    recorder: RequestRecorder | None = None
    # The previous saved report of the same target and claimed model (a report
    # dict, as history stores it), for checks that compare across runs.
    previous_report: dict[str, Any] | None = None

    @property
    def has_judge(self) -> bool:
        return self.judge is not None

    @property
    def has_baseline(self) -> bool:
        return self.baseline_client is not None

    def declared_context_window(self) -> int | None:
        """The context window the relay claims, from config override or KB profile."""
        if self.target.declared_context_window:
            return self.target.declared_context_window
        if self.profile and self.profile.model.context_window_tokens > 0:
            return self.profile.model.context_window_tokens
        return None

    def declared_max_output(self) -> int | None:
        if self.target.declared_max_output:
            return self.target.declared_max_output
        if self.profile and self.profile.model.max_output_tokens > 0:
            return self.profile.model.max_output_tokens
        return None

    def performance_reference(self) -> PerformanceReference | None:
        """Published native-API speed of the claimed model, if the KB has it."""
        return self.profile.model.performance if self.profile else None

    def embedding_dimensions(self) -> int:
        """The claimed model's native vector length: the run's override, else
        the KB profile's; 0 when unknown."""
        if self.options.embedding_dimensions > 0:
            return self.options.embedding_dimensions
        if self.profile and self.profile.model.embedding_dimensions > 0:
            return self.profile.model.embedding_dimensions
        return 0

    def tokenizer_hint(self) -> str | None:
        if self.profile and self.profile.model.tokenizer:
            return self.profile.model.tokenizer
        return None
