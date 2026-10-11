"""Knowledge-base data contracts.

A ``ProviderProfile`` describes one platform (OpenAI, Anthropic, DeepSeek, ...).
Each holds ``ModelProfile`` entries with the native specs and a set of
``FingerprintProbe`` behaviors that distinguish the genuine model from a cheaper
substitute. Detectors resolve the claimed model id to a ``ResolvedProfile`` and
audit against it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FingerprintProbe(BaseModel):
    """A runnable behavioral probe that separates genuine from substituted models."""

    model_config = ConfigDict(extra="forbid")

    id: str
    signal: str
    prompt: str
    native_expected: str = ""
    downgrade_signal: str = ""
    pure_code_checkable: bool = False
    # Deterministic checks (used when pure_code_checkable). All are optional.
    expect_contains: list[str] = Field(default_factory=list)
    expect_contains_any: list[str] = Field(default_factory=list)
    expect_not_contains: list[str] = Field(default_factory=list)
    expect_regex: str | None = None
    # Sampling overrides for this probe.
    max_tokens: int = 256
    temperature: float = 0.0
    weight: float = 1.0
    # Language of the prompt. Probes are English (like zing/prompts/en.json)
    # unless the language IS the measurement (e.g. Chinese fluency of a
    # China-native model); then ``language_bound`` says why, and the probe is
    # sent as written regardless of any UI or alert language.
    prompt_lang: str = "en"
    language_bound: str | None = None

    @model_validator(mode="after")
    def _non_english_probes_say_why(self) -> FingerprintProbe:
        if self.prompt_lang != "en" and not self.language_bound:
            raise ValueError(
                f"fingerprint {self.id!r}: prompt_lang={self.prompt_lang!r} needs a "
                "language_bound reason (why this probe must not be in English)"
            )
        return self


class PerformanceReference(BaseModel):
    """Typical speed of the model on its native (data-centre) API, as published
    measurements. Deliberately wide ranges: the performance detector only flags a
    target far outside them, and a slower one only mildly (it may be served
    locally or on smaller hardware)."""

    model_config = ConfigDict(extra="forbid")

    # Output tokens per second after the first token, [low, high].
    decode_tps: tuple[float, float] | None = None
    # Time to first token for a short prompt, milliseconds, [low, high].
    ttft_ms: tuple[float, float] | None = None
    source: str = ""
    measured: str | None = None  # when the figures were taken, e.g. "2026-09"

    @model_validator(mode="after")
    def _ranges(self) -> PerformanceReference:
        for name in ("decode_tps", "ttft_ms"):
            rng = getattr(self, name)
            if rng is not None and not 0 < rng[0] <= rng[1]:
                raise ValueError(f"performance.{name} must be [low, high] with 0 < low <= high")
        return self


class ModelProfile(BaseModel):
    """Native specifications for one model id."""

    model_config = ConfigDict(extra="forbid")

    id: str
    aliases: list[str] = Field(default_factory=list)
    family: str | None = None
    context_window_tokens: int = -1
    max_output_tokens: int = -1
    knowledge_cutoff: str | None = None
    tokenizer: str | None = None
    modalities: list[str] = Field(default_factory=lambda: ["text"])
    reasoning: bool = False
    # Native output dimensionality of an embedding model's vectors. 0 means the
    # model is not an embedding model (or the dimension is unknown). The embedding
    # auditor compares a relay's returned vector length against this.
    embedding_dimensions: int = 0
    # Native output sizes an image-generation model supports, as "WxH" strings
    # (e.g. ["1024x1024", "1792x1024"]). Empty = not an image model / unknown. The
    # image auditor decodes the returned bytes and checks the dimensions against
    # the requested size and this list.
    image_sizes: list[str] = Field(default_factory=list)
    # Voice ids a TTS/audio model supports (e.g. ["alloy", "nova"]). Empty = not
    # an audio model / unknown.
    audio_voices: list[str] = Field(default_factory=list)
    # Capability claims to verify.
    tool_format: str | None = None        # openai_function | anthropic_tool_use | ...
    supports_tools: bool = True
    supports_json_mode: bool = False
    supports_json_schema: bool = False
    usage_in_stream: bool = True
    # Request parameters the model itself refuses (e.g. "temperature" on some
    # reasoning models), so a relay's 4xx for them is not held against the relay.
    unsupported_params: list[str] = Field(default_factory=list)
    # Identity expectations: words a genuine model uses to identify itself, and
    # words that would betray a different model behind the curtain.
    identity_keywords: list[str] = Field(default_factory=list)
    identity_forbidden: list[str] = Field(default_factory=list)
    # Model-specific fingerprints (added to the provider-level ones).
    fingerprints: list[FingerprintProbe] = Field(default_factory=list)
    # Published native-API speed, for the performance detector's reference check.
    performance: PerformanceReference | None = None
    notes: str = ""


class ProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    display_name: str = ""
    openai_compatible: bool = True
    base_url_hints: list[str] = Field(default_factory=list)
    default_tool_format: str = "openai_function"
    models: list[ModelProfile] = Field(default_factory=list)
    # Fingerprints shared across all models of this provider.
    fingerprints: list[FingerprintProbe] = Field(default_factory=list)
    relay_red_flags: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ResolvedProfile(BaseModel):
    """The KB match for a claimed model id."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderProfile
    model: ModelProfile
    match_confidence: str = "exact"  # exact | alias | fuzzy | family | none

    def all_fingerprints(self) -> list[FingerprintProbe]:
        return [*self.provider.fingerprints, *self.model.fingerprints]


class KnowledgeBase(BaseModel):
    """All loaded provider profiles plus model-id resolution.

    Besides the merged profiles it records where each one came from, so a
    report can name exactly what it audited against: ``provider_sources`` /
    ``model_sources`` (keyed ``provider`` / ``provider/model_id``) hold
    ``packaged:<file>``, ``kb_dir:<path>`` or ``kb.db:entry/<id>``;
    ``entries`` the user's kb.db entries that were applied (same keys, prefixed
    ``provider:`` / ``model:``); ``shadowed`` the source a user model replaced.
    """

    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderProfile] = Field(default_factory=dict)
    provider_sources: dict[str, str] = Field(default_factory=dict)
    model_sources: dict[str, str] = Field(default_factory=dict)
    entries: dict[str, dict[str, Any]] = Field(default_factory=dict)
    shadowed: dict[str, str] = Field(default_factory=dict)
    # False when the user's kb.db entries were deliberately left out
    # (--no-user-kb / ZING_NO_USER_KB).
    user_kb: bool = True
    # kb.db entries that were skipped (invalid, unknown provider, ...).
    warnings: list[str] = Field(default_factory=list)
    # packaged / ZING_KB_DIR items switched off in kb.db ("provider:<p>" or
    # "model:<p>/<id>"), left out of ``providers``.
    disabled: list[str] = Field(default_factory=list)

    def all_models(self) -> list[tuple[ProviderProfile, ModelProfile]]:
        pairs: list[tuple[ProviderProfile, ModelProfile]] = []
        for provider in self.providers.values():
            for model in provider.models:
                pairs.append((provider, model))
        return pairs

    def resolve(
        self, model_id: str, provider_hint: str | None = None
    ) -> ResolvedProfile | None:
        """Resolve a claimed model id to a profile.

        Resolution order: exact id, alias, then a normalized fuzzy/substring match.
        A ``provider_hint`` narrows the search and breaks ties.
        """
        if not model_id:
            return None
        norm = _normalize(model_id)
        candidates = self.all_models()
        if provider_hint:
            hint = provider_hint.lower()
            narrowed = [
                (p, m) for p, m in candidates if p.provider.lower() == hint
            ]
            if narrowed:
                candidates = narrowed

        # 1) exact id
        for provider, model in candidates:
            if model.id == model_id:
                return ResolvedProfile(provider=provider, model=model, match_confidence="exact")
        # 2) alias (exact)
        for provider, model in candidates:
            if model_id in model.aliases:
                return ResolvedProfile(provider=provider, model=model, match_confidence="alias")
        # 3) normalized exact (id or alias)
        for provider, model in candidates:
            names = [model.id, *model.aliases]
            if any(_normalize(n) == norm for n in names):
                return ResolvedProfile(provider=provider, model=model, match_confidence="alias")
        # 4) substring / fuzzy on normalized names
        best: tuple[ProviderProfile, ModelProfile] | None = None
        best_len = 0
        for provider, model in candidates:
            names = [model.id, *model.aliases]
            for n in names:
                nn = _normalize(n)
                if nn and (nn in norm or norm in nn) and len(nn) > best_len:
                    best = (provider, model)
                    best_len = len(nn)
        if best is not None:
            return ResolvedProfile(provider=best[0], model=best[1], match_confidence="fuzzy")
        return None


def _normalize(name: str) -> str:
    """Lowercase and strip separators/date suffixes for tolerant matching."""
    return "".join(ch for ch in name.lower() if ch.isalnum())
