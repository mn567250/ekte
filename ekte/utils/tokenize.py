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
