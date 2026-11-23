"""Token estimation for billing/usage sanity checks.

We do not need exact tokenization — we need a defensible estimate to compare
against the ``usage`` numbers a relay reports, so we can flag inflated billing or
implausible counts. The count is always a language-aware stdlib heuristic that
handles CJK text reasonably: ekte must run in restricted environments, so it
never imports a tokenizer library or downloads an encoding at runtime.
"""

from __future__ import annotations

import re

_CJK = re.compile(
    r"[　-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯]"
)
_WORDISH = re.compile(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]")


def heuristic_token_count(text: str) -> int:
    """Language-aware token estimate.

    CJK characters count ~1 token each; runs of latin/digits and punctuation are
    each roughly one BPE token. Empirically within ~15-20% of real tokenizers,
    which is good enough to flag gross billing inflation.
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    non_cjk = _CJK.sub(" ", text)
    pieces = len(_WORDISH.findall(non_cjk))
    return cjk + pieces


# Real prompt tokens per heuristic token for the context-window filler
# (``ekte.detectors.helpers.build_filler``), by tokenizer family (the ``tokenizer:``
# field of ``ekte/knowledge/data/*.yaml``). The context-window probe builds each
# haystack at ``size / factor`` heuristic tokens so the REAL count stays within
# the rung. Entries are data measured offline with the family's real tokenizer
# (ekte never imports one at run time); a family without a measured entry uses
# ``DEFAULT_FILLER_REAL_PER_HEURISTIC``.
#
# Measured 2026-11-22 (issue #261) with ``scripts/measure_tokenizer_factors.py``:
# the published ``tokenizer.json`` at the pinned revision, ``build_filler`` at
# 1k/8k/32k/128k heuristic tokens x 5 nonces (20 texts per source), real tokens
# without special tokens / heuristic tokens. Each entry is the largest source
# median rounded UP to 0.01; "spread" is the min-max of all ratios. Families
# whose tokenizer is not published (claude-bpe-*, gemini, grok) stay on the
# default.
FILLER_REAL_PER_HEURISTIC: dict[str, float] = {
    # Xenova/gpt-4o @ 7956d98f2a83 (o200k conversion); median 1.1200, spread 1.1200-1.1200.
    "o200k_base": 1.12,
    # openai/gpt-oss-20b @ 6cee5e81ee83 and openai/gpt-oss-120b @ b5c939de8f75 (official);
    # median 1.1200, spread 1.1200-1.1200 (same counts as o200k_base on plain text).
    "o200k_harmony": 1.12,
    # Xenova/text-embedding-ada-002 @ f20698771af1 and Xenova/gpt-4 @ 1d9f1f1b1fae
    # (cl100k conversions); median 1.1533, spread 1.1533-1.1533.
    "cl100k_base": 1.16,
    # Qwen/Qwen3.5-397B-A17B @ 8472618112ab, Qwen3.6-35B-A3B @ 345d467b117d, Qwen3.8-27B @
    # 37561816e66b, Qwen3.8-Flash-Next @ 812d96e10a0d: median 1.4066; Qwen/Qwen3-8B @ b968826d9c46
    # and Qwen3-235B-A22B-Instruct-2507 @ ac9c66cc9b46 (the 151k vocabulary): median 1.3533;
    # spread 1.3533-1.4067. The denser (newer) tokenizer sets the factor.
    "qwen": 1.41,
    # deepseek-ai/DeepSeek-V4-Pro @ b5968e9190ef, V4-Flash @ 60d8d70770c6, V3.2 @ a7e62ac04ecb,
    # V3.1 @ c0781d039fb7; median 1.1467, spread 1.1467-1.1467.
    "deepseek-bpe": 1.15,
    # zai-org/GLM-5 @ c183ef8c61fa, GLM-4.7 @ 602d01efcdd3, GLM-4.6 @ be72194883d9, GLM-4.5 @
    # cbb2c7cfb52f; median 1.2177, spread 1.1533-1.2200.
    "glm": 1.22,
    # google/gemma-4-31b-it @ 842da3794eaa, google/gemma-4-E4B-it @ 4ecc2ba63bca,
    # unsloth/gemma-3-27b-it @ 7a5a3053dbd5 (byte-identical to gated google/gemma-3-27b-it);
    # median 1.3866, spread 1.3860-1.3867.
    "gemma": 1.39,
    # nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16 @ 2dc98e2afe4f, Nano-30B-A3B-BF16 @
    # bf77c3174f68; median 1.3800, spread 1.3800-1.3800.
    "nemotron-3": 1.38,
    # nvidia/Llama-3_3-Nemotron-Super-49B-v1_5 @ 420ba7d28211 (byte-identical to gated
    # meta-llama/Llama-3.3-70B-Instruct); median 1.1533, spread 1.1533-1.1533.
    "llama-3.3": 1.16,
    # mlx-community/c4ai-command-r7b-12-2024-bf16 @ f111eceb4c3d (byte-identical to gated
    # CohereLabs/c4ai-command-r7b-12-2024); median 1.3933, spread 1.3927-1.3933.
    "cohere": 1.40,
    # Xenova/Kimi-K3-tokenizer @ 4537b5bc42f0, checked against moonshotai/Kimi-K3 @ 1f5d44f794ef
    # (same tiktoken.model as Kimi K2/K2.5/K2.6/K2.7-Code: every rank and the split pattern
    # match); median 1.1400, spread 1.1400-1.1400. moonshot-v1's tokenizer is not published.
    "moonshot-bpe": 1.14,
}
DEFAULT_FILLER_REAL_PER_HEURISTIC = 1.2


def filler_real_per_heuristic(tokenizer: str | None) -> float:
    """Real tokens per heuristic token of the filler for ``tokenizer``'s family:
    its measured entry in ``FILLER_REAL_PER_HEURISTIC``, else the default."""
    if tokenizer and tokenizer in FILLER_REAL_PER_HEURISTIC:
        return FILLER_REAL_PER_HEURISTIC[tokenizer]
    return DEFAULT_FILLER_REAL_PER_HEURISTIC


def estimate_tokens(text: str, tokenizer: str | None = None) -> int:
    """Estimated token count for ``text``.

    ``tokenizer`` (the model family's tokenizer hint) is accepted for call-site
    compatibility but does not change the count: every family uses the heuristic.
    """
    return heuristic_token_count(text)


def estimate_messages_tokens(
    messages: list[dict], tokenizer: str | None = None, per_message_overhead: int = 4
) -> int:
    """Estimate prompt tokens for a chat ``messages`` array.

    The per-message overhead approximates the role/delimiter tokens that chat
    templates add (OpenAI uses ~3-4 per message plus a few for priming).
    """
    total = 0
    for message in messages:
        total += per_message_overhead
        content = message.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content, tokenizer)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total += estimate_tokens(part["text"], tokenizer)
        if isinstance(message.get("role"), str):
            total += estimate_tokens(message["role"], tokenizer)
    return total + 3
