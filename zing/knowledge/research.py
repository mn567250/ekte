"""The research prompt users copy into an external AI assistant.

The assistant researches a model and answers with a zing provider YAML
document, which the user then uploads on the Knowledge base page (or imports
with the API); :mod:`zing.knowledge.importer` checks it before anything is
stored. The field reference is generated from the pydantic schema, so the
prompt cannot drift from what the importer accepts.
"""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel

from zing.knowledge.schema import FingerprintProbe, KnowledgeBase, ModelProfile, ProviderProfile

# What each field means — the schema itself carries only names, types, defaults.
_HELP: dict[str, str] = {
    # provider
    "provider": "short lower-case key, e.g. openai, deepseek (reuse an existing key when the provider is listed below)",
    "display_name": "human-readable provider name",
    "openai_compatible": "true when the official API speaks the OpenAI chat-completions protocol",
    "base_url_hints": "official API base URLs",
    "default_tool_format": "openai_function | anthropic_tool_use",
    "fingerprints": "behavioral probes (see the fingerprint fields); may be empty",
    "relay_red_flags": "short notes on tell-tale signs a relay is not serving the genuine model",
    "sources": "URLs of the official documentation you used",
    # model
    "id": "the exact model id sent in API requests",
    "aliases": "other ids / snapshot names the same model is served under",
    "family": "model family, e.g. gpt-4o, claude-3.5",
    "context_window_tokens": "native context window in tokens (-1 = unknown)",
    "max_output_tokens": "maximum output tokens per request (-1 = unknown)",
    "knowledge_cutoff": "training data cutoff as stated by the provider, e.g. 2024-10",
    "tokenizer": "tokenizer name, e.g. o200k_base, cl100k_base",
    "modalities": "input modalities, e.g. [text, image]",
    "reasoning": "true for reasoning/thinking models",
    "embedding_dimensions": "embedding models only: native vector length (0 otherwise)",
    "image_sizes": "image-generation models only: supported sizes like 1024x1024",
    "audio_voices": "TTS models only: supported voice ids",
    "tool_format": "openai_function | anthropic_tool_use | null",
    "supports_tools": "native function/tool calling",
    "supports_json_mode": "JSON object output mode",
    "supports_json_schema": "strict JSON-schema structured output",
    "usage_in_stream": "token usage reported in streamed responses",
    "unsupported_params": "request parameters the model itself rejects (e.g. temperature, top_p)",
    "identity_keywords": "lower-case words the genuine model uses to identify itself",
    "identity_forbidden": "lower-case words that would betray a different model (rival brands)",
    "performance": "optional published native-API speed: {decode_tps: [low, high] tok/s, "
    "ttft_ms: [low, high], source: URL, measured: YYYY-MM}; wide ranges, null when unknown",
    "notes": "one paragraph: what matters for spotting a substitute, with dates",
    # fingerprint
    "signal": "what the probe measures",
    "prompt": "the exact prompt sent to the model (English unless language_bound)",
    "native_expected": "how the genuine model answers",
    "downgrade_signal": "how a cheaper substitute tends to answer",
    "pure_code_checkable": "true when the expect_* checks decide pass/fail without an LLM judge",
    "expect_contains": "all of these substrings must appear (case-insensitive)",
    "expect_contains_any": "at least one of these must appear",
    "expect_not_contains": "none of these may appear",
    "expect_regex": "a short regular expression the answer must match (no nested quantifiers)",
    "max_tokens": "output tokens for this probe (1-32768); the identity check skips a "
    "pure_code_checkable probe above 512",
    "temperature": "sampling temperature (0-2)",
    "weight": "relative weight of this probe (0-10)",
    "prompt_lang": "language of the prompt; en unless the language itself is measured",
    "language_bound": "required when prompt_lang is not en: why the probe must not be English",
}


def _type_name(annotation: Any) -> str:
    text = getattr(annotation, "__name__", None) or str(annotation)
    return text.replace("typing.", "").replace("zing.knowledge.schema.", "")


def _fields(model: type[BaseModel], skip: tuple[str, ...] = ()) -> list[str]:
    lines = []
    for name, info in model.model_fields.items():
        if name in skip:
            continue
        default = "required" if info.is_required() else f"default {info.get_default(call_default_factory=True)!r}"
        help_text = _HELP.get(name, "")
        lines.append(f"  - {name} ({_type_name(info.annotation)}, {default}){': ' + help_text if help_text else ''}")
    return lines


_EXAMPLE = {
    "provider": "exampleai",
    "display_name": "Example AI",
    "openai_compatible": True,
    "base_url_hints": ["https://api.example.ai/v1"],
    "default_tool_format": "openai_function",
    "sources": ["https://docs.example.ai/models"],
    "models": [{
        "id": "example-large-2",
        "aliases": ["example-large-2-2026-01-15"],
        "family": "example-large",
        "context_window_tokens": 200000,
        "max_output_tokens": 16384,
        "knowledge_cutoff": "2025-06",
        "tokenizer": "example-bpe",
        "modalities": ["text", "image"],
        "reasoning": False,
        "tool_format": "openai_function",
        "supports_tools": True,
        "supports_json_mode": True,
        "supports_json_schema": True,
        "usage_in_stream": True,
        "unsupported_params": [],
        "identity_keywords": ["example", "example ai"],
        "identity_forbidden": ["gpt", "openai", "claude", "anthropic", "gemini", "qwen", "deepseek"],
        "fingerprints": [{
            "id": "example-large-2.cutoff",
            "signal": "knowledge cutoff",
            "prompt": "In one sentence: what is the most recent month and year you have reliable knowledge of?",
            "native_expected": "Names mid-2025.",
            "downgrade_signal": "An older cutoff suggests a smaller predecessor.",
            "pure_code_checkable": True,
            "expect_contains_any": ["2025"],
        }],
        "notes": "Released 2026-01-15. 200K context, 16K output. Older example-large-1 has 32K context.",
    }],
}


def research_prompt(model_id: str, provider: str | None = None, kb: KnowledgeBase | None = None) -> str:
    """The prompt text for researching ``model_id`` (optionally of ``provider``)."""
    model_id = (model_id or "").strip() or "<MODEL ID>"
    known = ", ".join(sorted(kb.providers)) if kb is not None else ""
    provider_line = (
        f"The model is served by the provider `{provider.strip()}`."
        if provider and provider.strip()
        else "Work out which provider publishes it."
    )
    example = yaml.safe_dump(_EXAMPLE, allow_unicode=True, sort_keys=False, width=100)
    parts = [
        f"Research the large-language-model API model `{model_id}` and write its profile for zing, "
        "an open-source tool that audits whether an API relay really serves the model it claims.",
        provider_line,
        "",
        "Rules:",
        "- Use only official, authoritative sources: the provider's model cards, API reference, pricing "
        "and release notes. List the URLs under `sources`.",
        "- Never guess numbers. If a value is not officially documented, leave the default "
        "(-1 for token limits, null or an empty list otherwise) and say so in `notes`. A wrong value "
        "makes zing wrongly accuse honest relays.",
        "- Fingerprint probes are optional. Only add probes whose expected answer you can justify from "
        "the sources; keep prompts short, English, and free of anything personal. Omit them when unsure.",
        "- Output exactly one YAML document in a single ```yaml code block, nothing else: no anchors (&) "
        "or aliases (*), no fields that are not listed below.",
        "- If the provider is one of these existing keys, reuse it and include only the new model(s); "
        f"the provider's other settings cannot be changed: {known or '(none)'}.",
        "",
        "Provider fields (top level):",
        *_fields(ProviderProfile, skip=("models",)),
        "  - models: list of model entries",
        "",
        "Model fields (each item of `models`):",
        *_fields(ModelProfile),
        "",
        "Fingerprint fields (each item of `fingerprints`):",
        *_fields(FingerprintProbe),
        "",
        "Example of the expected shape (fictional values):",
        "```yaml",
        example.rstrip(),
        "```",
    ]
    return "\n".join(parts) + "\n"
