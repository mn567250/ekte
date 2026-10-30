"""A model's own brand words, derived from its knowledge-base profile.

The identity detector treats vendor names in a self-identification answer as a
rival brand unless they are the model's own. ``identity_keywords`` is the
explicit list, but a user profile can leave it empty, so the profile's names
count too: the provider key, the leading name in the provider's
``display_name`` and the leading word of the model id and family (``acme`` from
``acme-2v-flash``), widened to the other names of the same vendor in
``VENDOR_BRANDS`` (a ``z.ai`` profile also owns ``zhipu``).

The derivation is deliberately narrow, since every own word lets an answer
pass as genuine: generic words ("ai", "open", "platform", ...) are dropped, a
derived word never overrides the profile's ``identity_forbidden``, and when the
model's own names point to a known vendor, provider words naming a different
vendor (a platform hosting another vendor's model) are left out.
"""

from __future__ import annotations

import re

from zing.knowledge.schema import ModelProfile, ProviderProfile

# Known LLM vendors, each with the brand words that name it (incl. Chinese). The
# identity detector treats all of them as rival brands except the model's own
# vendor (model_identity._RIVAL_BRANDS).
VENDOR_BRANDS: tuple[tuple[str, ...], ...] = (
    ("openai", "gpt", "chatgpt"),
    ("anthropic", "claude"),
    ("google", "gemini", "deepmind"),
    ("deepseek", "深度求索"),
    ("qwen", "tongyi", "通义", "通义千问", "alibaba", "阿里云", "阿里巴巴"),
    ("doubao", "豆包", "bytedance", "字节", "字节跳动", "seed"),
    ("kimi", "moonshot", "月之暗面"),
    ("glm", "chatglm", "zhipu", "智谱", "z.ai"),
    ("ernie", "文心", "文心一言", "baidu", "百度"),
    ("hunyuan", "混元", "tencent", "腾讯"),
    ("llama", "meta"),
    ("mistral", "mixtral"),
    ("grok", "xai"),
    ("cohere", "command"),
    ("minimax", "abab"),
    ("讯飞", "星火", "spark"),
    ("零一万物", "yi"),
    ("阶跃", "step"),
)

# Brand words that are also everyday English ("step by step", "a meta question",
# "a spark of", "the seed", "a command"). The identity detector counts them only
# in the direct self-identification answer and only written as a name
# (capitalised, "Meta", "Command R"); fingerprint answers never count them, so an
# honest model narrating "let me think step by step" is not a StepFun swap.
AMBIGUOUS_BRAND_WORDS: frozenset[str] = frozenset({
    "step", "command", "seed", "spark", "meta", "yi", "grok",
})

# Words that occur in vendor and model names without naming a brand.
_GENERIC = frozenset({
    "ai", "the", "model", "models", "chat", "text", "embedding", "embeddings",
    "api", "open", "platform", "cloud", "inc", "ltd", "llc", "corp", "co",
    "lab", "labs", "llm", "assistant", "technologies", "technology", "research",
    "preview", "latest", "base", "instruct", "omni", "engine", "studio",
    "image", "audio", "vision", "speech", "voice", "tts", "dall", "realtime",
    "search", "code", "coder",
})
# Where the leading name of a display_name ends: "Zhipu AI (智谱 / Z.ai) — BigModel".
_DISPLAY_CUT = re.compile(r"[(\[/,;:|—–]| - ")
_LEADING_ALPHA = re.compile(r"[a-z]+")


def _keep(word: str) -> bool:
    return len(word) >= 2 and word not in _GENERIC and any(ch.isalpha() for ch in word)


def _vendors(words: list[str]) -> set[int]:
    return {i for i, group in enumerate(VENDOR_BRANDS) if any(w in group for w in words)}


def own_brand_words(
    provider: ProviderProfile | None, model: ModelProfile, *, widen: bool = True
) -> list[str]:
    """Lower-case words that name this model's own brand: ``identity_keywords``
    as written, then the provider key, the leading name of the provider's
    display_name and the leading word of the model id and family, and (with
    ``widen``) the other names of the same vendor in ``VENDOR_BRANDS``."""
    out: list[str] = []
    for k in model.identity_keywords or []:
        if k.strip() and k.strip().lower() not in out:
            out.append(k.strip().lower())
    forbidden = {w.strip().lower() for w in model.identity_forbidden or []}

    model_words: list[str] = []
    for name in (model.id, model.family or ""):
        # Last path segment, before any ":tag" ("org/acme-2v-flash:q4" -> acme).
        m = _LEADING_ALPHA.match(name.lower().rsplit("/", 1)[-1])
        if m:
            model_words.append(m.group(0))
    provider_words: list[str] = []
    if provider is not None:
        provider_words.append(provider.provider.lower())
        lead = _DISPLAY_CUT.split(provider.display_name or "", maxsplit=1)[0]
        provider_words.extend(w.strip(".-_'\"").lower() for w in lead.split())
    model_vendors = _vendors(out + model_words)
    if model_vendors:
        # A platform serving another vendor's model: its own brand is a rival.
        provider_words = [w for w in provider_words if _vendors([w]) <= model_vendors]

    def add(words: list[str] | tuple[str, ...]) -> None:
        for w in words:
            if w not in out and w not in forbidden and _keep(w):
                out.append(w)

    add(provider_words)
    add(model_words)
    if widen:
        # The same vendor's other names are its own brand too.
        for i in sorted(_vendors(out)):
            add(VENDOR_BRANDS[i])
    return out
