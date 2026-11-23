"""Injected-system-prompt detector.

A relay can silently prepend its own hidden system/developer prompt to every
request — to steer behavior, watermark, or simply pad billable input. Two
independent tells are combined so an honest relay is not falsely accused:

1. A *fixed input overhead*. With no system message, the reported ``prompt_tokens``
   should sit just above an independent estimate (a small, roughly-constant chat
   template overhead). A hidden prepended prompt shows up as a LARGE overhead that
   stays constant as the user message grows — distinguishing it from proportional
   billing inflation.
2. A *leak* response when asked to repeat any preceding instructions. The answer
   is classified (:func:`classify_leak_answer`) as ``none`` (``NONE`` or an honest
   denial such as "there are no system instructions"), ``leak`` (a quoted passage
   or at least two second-person imperative sentences outside a denial) or
   ``unclear`` (anything else, e.g. a refusal), which counts as no leak.

Only when both point the same way does this rise to a (still cautious) WARN; a
single tell stays low and never escalates overall risk on its own. A leak alone
is informational and not counted: models confabulate system prompts.
"""

from __future__ import annotations

import re

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors import advice
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import usage_field
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, RequestSpec, Severity, Status
from ekte.utils.tokenize import estimate_messages_tokens

# Overhead (reported prompt_tokens − estimate) above this, holding roughly constant
# across message sizes, reads as a hidden prepended prompt rather than template noise.
_OVERHEAD_TOKENS = 30
# The two probes' overheads must agree within this to count as a *fixed* prefix.
_OVERHEAD_CONSISTENCY = 16
# How much of the leak answer the evidence keeps, so a reader can check the classification.
_LEAK_EVIDENCE_CHARS = 300

# A denial: a negation, at most a few words, then a qualifier (system, developer,
# prior, ...) and the thing denied (instructions, prompt, message) - or the thing
# denied followed by "before / preceding / above".
_NEGATION = (
    r"(?:there\s+(?:are|is|were|was)\s+no"
    r"|there\s+(?:aren't|are\s+not|isn't|is\s+not|weren't|wasn't)\s+any"
    r"|i\s+(?:have|had|got|received|see|found)\s+no"
    r"|i\s+(?:do\s+not|don't|did\s+not|didn't)\s+(?:have|see|find|receive|have\s+access\s+to)\s+any"
    r"|i\s+(?:cannot|can't|can\s+not|could\s+not|couldn't|am\s+unable\s+to)\s+(?:see|find|access|detect)\s+any"
    r"|no)"
)
_GAP = r"(?:\s+[\w'-]+){0,3}?"
_QUALIFIER = r"(?:system|developer|prior|preceding|previous|earlier|hidden)"
_DENIED = r"(?:instructions?|prompts?|messages?)"
_DENIAL_RE = re.compile(
    rf"\b{_NEGATION}{_GAP}\s+{_QUALIFIER}\b[\w\s/,'-]{{0,40}}?\b{_DENIED}\b"
    rf"|\b{_NEGATION}{_GAP}\s+{_DENIED}\s+(?:before|preceding|prior\s+to|above|ahead\s+of)\b",
    re.IGNORECASE,
)
# A quoted passage (straight or curly double quotes, backticks), a fenced block or
# a block quote: quoted instruction text.
_QUOTED_RE = re.compile(
    r'"[^"\n]{20,}"|\u201c[^\u201d\n]{20,}\u201d|```|`[^`\n]{20,}`|^\s*>\s*\S',
    re.MULTILINE,
)
# A sentence in the second-person imperative, as system prompts are written.
_IMPERATIVE_RE = re.compile(
    r"^(?:you\s+are|you're|you\s+must|you\s+should|you\s+will|you\s+need\s+to|you\s+have\s+to"
    r"|you\s+may\s+not|always|never|do\s+not|don't)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
# A short label before the sentence proper ("System prompt: You are ...", "- ", "1.").
_SENTENCE_PREFIX_RE = re.compile(r"^(?:[-*\u2022]\s*|\d+[.)]\s*|[\w '-]{1,30}:\s*)+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def classify_leak_answer(text: str) -> str:
    """Classify the answer to the leak probe: ``none``, ``leak`` or ``unclear``.

    ``leak`` needs instruction-like content - a quoted or block-quoted passage, or
    at least two second-person imperative sentences outside a denial sentence.
    ``none`` is ``NONE`` or a denial (no system / developer / prior instructions)
    in the first two sentences. Anything else (a refusal, small talk) is
    ``unclear``. Leak content wins over a denial: a denial followed by quoted
    instructions is a leak.
    """
    stripped = text.strip()
    if stripped.upper().strip(" .!\"'`") == "NONE":
        return "none"
    sentences = _sentences(stripped)
    denials = [bool(_DENIAL_RE.search(s)) for s in sentences]
    imperatives = sum(
        1
        for s, denial in zip(sentences, denials, strict=True)
        if not denial and _IMPERATIVE_RE.match(_SENTENCE_PREFIX_RE.sub("", s.lstrip("\"'\u201c`(")))
    )
    if _QUOTED_RE.search(stripped) or imperatives >= 2:
        return "leak"
    if any(denials[:2]):
        return "none"
    return "unclear"


# The detector score is its one verdict's points (the published scale).
SCALE = Scale(
    outcome("injected_prompt.verdict", "clean", 100.0, Status.PASS,
            label="Input-token overhead is small and no hidden instructions leaked."),
    outcome("injected_prompt.verdict", "leak", None, Status.INFO,
            label="Instruction-like text leaked when asked (not counted: models confabulate)."),
    outcome("injected_prompt.verdict", "overhead", 75.0, Status.WARN, Severity.LOW,
            label="A large fixed input-token overhead, constant across message sizes."),
    outcome("injected_prompt.verdict", "suspected", 55.0, Status.WARN, Severity.MEDIUM,
            label="A fixed input-token overhead and a leaked preamble together."),
    outcome("injected_prompt.verdict", "inconclusive", None, Status.INCONCLUSIVE,
            label="No usable prompt token counts to measure the overhead."),
    titles={"injected_prompt.verdict": "Injected system prompt"},
)


@register
class InjectedPromptDetector(Detector):
    id = "injected_prompt"
    name = "Injected system-prompt detection"
    dimension = Dimension.INTEGRITY
    min_suite = "deep"
    cost_hint = 3

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        tok = ctx.tokenizer_hint()

        overhead = await self._measure_overhead(ctx, tok)
        leak = await self._leak_probe(ctx)
        leaked = leak["leak_answer_kind"] == "leak"

        result.evidence.update({"overhead": overhead, "leak_detected": leaked, **leak})

        fixed_prefix = (
            overhead is not None
            and overhead["min"] >= _OVERHEAD_TOKENS
            and overhead["spread"] <= _OVERHEAD_CONSISTENCY
        )

        if fixed_prefix and leaked:
            assert overhead is not None  # fixed_prefix implies a measured overhead
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "suspected",
                    id="injected_prompt.suspected",
                    title="Hidden system prompt likely injected",
                    summary=(
                        f"Reported prompt tokens carry a large fixed overhead "
                        f"(~{overhead['min']} tokens beyond estimate, constant across "
                        f"message sizes) AND the model leaked instruction-like content "
                        f"when asked. A hidden prepended system prompt is suspected."
                    ),
                    evidence={"overhead": overhead, "leak_detected": True, **leak},
                    recommendation="Compare prompt_tokens against a trusted baseline for the same input.",
                )
            )
            result.status = Status.WARN
            result.score = Scale.mean(result.findings)
        elif fixed_prefix:
            assert overhead is not None
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "overhead",
                    id="injected_prompt.overhead",
                    title="Unexpected fixed input-token overhead",
                    summary=(
                        f"Prompt tokens sit ~{overhead['min']} above estimate and stay "
                        f"constant as the message grows — consistent with a hidden "
                        f"prepended prompt, but a single signal. Corroborate."
                    ),
                    evidence={"overhead": overhead, "leak_detected": False, **leak},
                )
            )
            result.status = Status.WARN
            result.score = Scale.mean(result.findings)
        elif leaked:
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "leak",
                    id="injected_prompt.leak",
                    title="Model surfaced instruction-like preamble (weak)",
                    summary=(
                        "When asked to repeat preceding instructions the model returned "
                        "instruction-like text rather than NONE. Models confabulate, so "
                        "on its own this is not counted."
                    ),
                    evidence={"overhead": overhead, "leak_detected": True, **leak},
                )
            )
            result.status = Status.INFO
            result.score = Scale.mean(result.findings)
        elif overhead is None:
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "inconclusive",
                    id="injected_prompt.inconclusive",
                    title="Could not measure input-token overhead",
                    summary="No usable prompt_tokens in the responses; overhead check skipped.",
                    recommendation=advice.NO_PROMPT_TOKENS,
                    evidence={"leak_detected": False, **leak},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = Scale.mean(result.findings)
        else:
            result.findings.append(
                SCALE.finding(
                    "injected_prompt.verdict",
                    "clean",
                    id="injected_prompt.clean",
                    title="No sign of an injected system prompt",
                    summary="Input-token overhead is small/template-sized and no preamble leaked.",
                    evidence={"overhead": overhead, "leak_detected": False, **leak},
                )
            )
            result.status = Status.PASS
            result.score = Scale.mean(result.findings)
        return result

    # ------------------------------------------------------------------ #
    async def _measure_overhead(self, ctx: AuditContext, tok: str | None) -> dict | None:
        """Reported prompt_tokens minus an independent estimate, for two sizes."""
        overheads: list[int] = []
        for content in (prompts.text("injected_prompt.small"), prompts.text("injected_prompt.large")):
            messages = [{"role": "user", "content": content}]
            outcome = await ctx.client.complete(
                # only the prompt token count is read, never the answer
                RequestSpec(messages=messages, temperature=0.0, max_tokens=8, reasoning_retry=False)
            )
            if not outcome.ok:
                continue
            reported = usage_field(outcome.usage, "prompt_tokens", "input_tokens")
            if reported is None:
                continue
            estimate = estimate_messages_tokens(messages, tok)
            overheads.append(reported - estimate)
        if len(overheads) < 2:
            return None
        return {
            "values": overheads,
            "min": min(overheads),
            "spread": max(overheads) - min(overheads),
        }

    async def _leak_probe(self, ctx: AuditContext) -> dict:
        """The leak probe's answer, classified: ``leak_answer_kind`` (None without
        an answer) and the first characters of the answer."""
        outcome = await ctx.client.complete(
            RequestSpec(
                messages=[{"role": "user", "content": prompts.text("injected_prompt.leak")}],
                temperature=0.0,
                max_tokens=200,
            )
        )
        if not (outcome.ok and outcome.has_content()):
            return {"leak_answer_kind": None, "leak_answer": None}
        text = outcome.content.strip()
        return {
            "leak_answer_kind": classify_leak_answer(text),
            "leak_answer": text[:_LEAK_EVIDENCE_CHARS],
        }
