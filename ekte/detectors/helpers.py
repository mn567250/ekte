"""Shared building blocks for detectors.

Centralized so every detector generates filler text, needles, and parses model
output the same way — important when several detectors compare results.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from typing import Any

from ekte import prompts
from ekte.utils.tokenize import estimate_tokens

# The filler's pool of natural-ish sentences (ekte/prompts/en.json). Varied so it
# is not trivially compressible by a relay's summarizer shim (which would defeat
# truncation tests).
_FILLER_SENTENCES: list[str] = prompts.get("context_window.filler_sentences")


def stable_marker(seed: str, prefix: str = "EKTE") -> str:
    """A reproducible high-entropy marker derived from ``seed``.

    Used as a needle/canary that a model cannot have memorized.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


@lru_cache(maxsize=4)
def build_filler(target_tokens: int, tokenizer: str | None = None) -> str:
    """Build filler text of approximately ``target_tokens`` tokens.

    Lines are numbered so position is meaningful and the text resists dedup.

    Linear in the output size: each line is counted once and a running total is
    kept, instead of re-joining and re-counting the whole text every 50 lines
    (which was quadratic — ~6 s at the default 200k-token probe cap, blocking the
    event loop). Same 50-line stepping and stop rule. Each line after the first
    is counted together with its leading newline separator: the heuristic count
    is additive over whitespace-joined lines (a newline yields no piece), so the
    output is byte-identical to the old algorithm; an exact BPE tokenizer gets
    its separator token counted too, staying close to the joined-text count.

    Memoized (a few entries): the context-window probe builds a size again to
    confirm a miss at the other needle depth and revisits sizes in its refine
    and lost-in-the-middle phases. The result is an immutable ``str``, so sharing
    it is safe; callers that insert a needle work on a split copy.
    """
    if target_tokens <= 0:
        return ""
    parts: list[str] = []
    total = 0
    idx = 0
    while True:
        line = f"[{idx:05d}] {_FILLER_SENTENCES[idx % len(_FILLER_SENTENCES)]}"
        parts.append(line)
        total += estimate_tokens(line if idx == 0 else "\n" + line, tokenizer)
        idx += 1
        if idx % 50 == 0 and total >= target_tokens:
            break
        if idx > 400_000:  # hard safety stop
            break
    return "\n".join(parts)


def build_haystack(
    *,
    total_tokens: int,
    needle: str,
    depth: float,
    tokenizer: str | None = None,
    instruction: str = "",
) -> str:
    """Embed ``needle`` at fractional ``depth`` (0.0=start, 1.0=end) in filler.

    The returned text is a full prompt: filler with the needle sentence inserted,
    followed by a retrieval instruction.
    """
    depth = max(0.0, min(1.0, depth))
    filler = build_filler(total_tokens, tokenizer)
    lines = filler.split("\n")
    needle_line = prompts.text("context_window.needle", needle=needle)
    insert_at = int(len(lines) * depth)
    lines.insert(insert_at, needle_line)
    body = "\n".join(lines)
    tail = instruction or prompts.text("context_window.question")
    return body + tail


def contains_ci(haystack: str, needle: str) -> bool:
    """Case-insensitive substring test, tolerant of surrounding whitespace."""
    return needle.strip().lower() in (haystack or "").lower()


def contains_all(text: str, needles: list[str]) -> bool:
    return all(contains_ci(text, n) for n in needles)


def contains_any(text: str, needles: list[str]) -> bool:
    return any(contains_ci(text, n) for n in needles)


def contains_word(text: str, word: str) -> bool:
    """Case-insensitive WHOLE-WORD match (boundaries on non-alphanumerics).

    Unlike :func:`contains_ci`, this won't match a brand inside a longer token —
    e.g. ``"meta"`` does not match ``"metadata"`` and ``"gpt"`` does not match
    ``"ChatGPT"`` — which matters for identity brand checks. Internal hyphens/dots
    in the term (``"gpt-5"``) are matched literally.
    """
    word = (word or "").strip()
    if not word:
        return False
    pattern = r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text or "", re.IGNORECASE) is not None


def contains_word_any(text: str, words: list[str]) -> bool:
    return any(contains_word(text, w) for w in words)


def words_present(text: str, words: list[str]) -> list[str]:
    """Return the subset of ``words`` present in ``text`` as whole words."""
    return [w for w in (words or []) if contains_word(text, w)]


def first_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from text, tolerating code fences/prose."""
    if not text:
        return None
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def usage_field(usage: dict[str, Any] | None, *names: str) -> int | None:
    """Read the first present integer field from a usage dict (handles aliases)."""
    if not isinstance(usage, dict):
        return None
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)):
            return int(value)
    return None


MISSING: Any = object()


def dig(obj: Any, path: str) -> Any:
    """The value at a dotted path (``choices.0.message.role``) or :data:`MISSING`.

    Numeric segments index lists. JSON ``null`` counts as missing: a relay that
    sends ``"usage": null`` has not provided usage.
    """
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, MISSING)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else MISSING
        else:
            return MISSING
        if cur is MISSING or cur is None:
            return MISSING
    return cur
