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
from ekte.perf.recorder import usage_tokens
from ekte.utils.tokenize import estimate_tokens

# The filler's pool of natural-ish sentences (ekte/prompts/en.json). Varied so it
# is not trivially compressible by a relay's summarizer shim (which would defeat
# truncation tests).
_FILLER_SENTENCES: list[str] = prompts.get("context_window.filler_sentences")


def stable_marker(seed: str, nonce: str, prefix: str = "EKTE") -> str:
    """A high-entropy marker derived from ``seed`` and the run's ``nonce``
    (``AuditContext.run_nonce``).

    Used as a needle/canary that a model cannot have memorized. The same seed
    gives the same marker within a run and a different one in every other run,
    so no relay can keep a table of ekte's markers. An empty ``nonce`` gives
    the marker of runs from before the nonce existed (replay of old evidence).
    """
    material = f"{nonce}|{seed}" if nonce else seed
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


def _filler_offsets(nonce: str) -> tuple[int, int]:
    """Where a run's filler starts numbering its lines and cycling its sentences."""
    if not nonce:
        return 0, 0
    digest = hashlib.sha256(f"ekte-filler|{nonce}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100_000, digest[4] % len(_FILLER_SENTENCES)


@lru_cache(maxsize=4)
def build_filler(target_tokens: int, tokenizer: str | None = None, nonce: str = "") -> str:
    """Build filler text of approximately ``target_tokens`` tokens.

    Lines are numbered so position is meaningful and the text resists dedup.
    The run's ``nonce`` sets the first line number and the first sentence, so
    every run sends a different long prompt of practically the same token
    count (a five-digit number for a five-digit number); an empty nonce gives
    the filler of runs from before the nonce existed.

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
    base, first = _filler_offsets(nonce)
    parts: list[str] = []
    total = 0
    idx = 0
    while True:
        number = (base + idx) % 100_000
        line = f"[{number:05d}] {_FILLER_SENTENCES[(first + idx) % len(_FILLER_SENTENCES)]}"
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
    nonce: str = "",
) -> str:
    """Embed ``needle`` at fractional ``depth`` (0.0=start, 1.0=end) in filler.

    The returned text is a full prompt: filler with the needle sentence inserted,
    followed by a retrieval instruction.
    """
    depth = max(0.0, min(1.0, depth))
    filler = build_filler(total_tokens, tokenizer, nonce)
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


def is_reasoning(ctx: Any, *outcomes: Any) -> bool:
    """Whether the endpoint under test is a reasoning model, decided the same
    way by every detector (#262).

    True when the claimed profile says ``reasoning: true``, when the client
    has learned that the endpoint reasons (``reasoning_room``: a short probe
    already needed the reasoning repeat, see "Reasoning models" in the
    methodology), or when any of ``outcomes`` reports reasoning tokens. An
    unprofiled reasoning model is therefore recognised by what it does, not
    only by its knowledge-base entry.
    """
    profile = getattr(ctx, "profile", None)
    if profile is not None and getattr(profile.model, "reasoning", False) is True:
        return True
    if getattr(getattr(ctx, "client", None), "reasoning_room", False) is True:
        return True
    return any(
        (usage_tokens(getattr(o, "usage", None))["reasoning"] or 0) > 0
        for o in outcomes
        if o is not None
    )


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
