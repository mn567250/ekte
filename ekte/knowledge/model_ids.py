"""Comparing the ``model`` id a relay echoes with the model it was asked for.

Shared by the chat, embedding and rerank identity detectors. The comparison
goes through the knowledge base first: an echoed id that resolves to the
claimed model's profile is consistent whatever its spelling (snapshot, alias,
provider prefix), one that resolves to a different known profile diverges.
Only an id the knowledge base cannot place falls back to a lexical heuristic
on normalized ids (a smaller-tier word, a different family, a different
version number), and when that finds nothing either the result is
``unknown``: a different id ekte cannot judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ekte.knowledge.schema import KnowledgeBase, ResolvedProfile

Verdict = Literal["consistent", "diverges", "unknown"]

# Whole tokens that name a cheaper/smaller tier of a family. In the echoed id
# but not in the requested one, they mark a downgrade (``gpt-4o`` ->
# ``gpt-4o-mini``). Matched as tokens, so ``mini`` is not found in ``gemini``.
DOWNGRADE_TOKENS = frozenset({
    "mini", "nano", "micro", "flash", "lite", "small", "tiny", "8b", "7b", "3b", "1b",
})

# A leading ``vendor.`` segment (AWS Bedrock ``anthropic.``, cross-region
# ``us.``, ...): letters only, followed by a letter, so ``gpt-4.1`` and
# ``o1.5`` keep their dots.
_DOTTED_PREFIX = re.compile(r"^(?:[a-z]{2,}|ai21)\.(?=[a-z])")
# Bedrock's trailing model version, ``-v1:0`` / ``-v2:0``.
_BEDROCK_VERSION = re.compile(r"-v\d+:\d+$")
# A trailing snapshot date: 2024-08-06, 20240307, 260428 (yymmdd) or 0613 (mmdd).
_DATE_SUFFIX = re.compile(r"[-_.](?:\d{4}[-_.]\d{2}[-_.]\d{2}|\d{8}|\d{6}|\d{4})$")
_PARAM_SIZE = re.compile(r"\d+b")


def tokens(name: str) -> list[str]:
    """The separator-delimited, lower-case tokens of a model id."""
    return [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t]


def normalize_model_id(name: str | None) -> str:
    """A model id without the decorations relays and clouds add: lower-case,
    no ``provider/`` path (``openai/``, ``models/``, ``azure/``), no leading
    ``vendor.`` segment (``anthropic.``, ``us.anthropic.``), no ``@version``,
    Bedrock ``-v2:0`` or ``:tag`` suffix, and no trailing snapshot date. A
    ``:tag`` naming a size or tier (``llama3.1:8b``) is kept, as ``-8b``."""
    s = (name or "").strip().lower()
    s = s.rsplit("/", 1)[-1]
    while _DOTTED_PREFIX.match(s):
        s = _DOTTED_PREFIX.sub("", s, count=1)
    s = re.sub(r"@[\w.-]*$", "", s)
    s = _BEDROCK_VERSION.sub("", s)
    if ":" in s:
        head, _, tag = s.rpartition(":")
        keep = [t for t in tokens(tag) if t in DOWNGRADE_TOKENS or _PARAM_SIZE.fullmatch(t)]
        s = head + "".join(f"-{t}" for t in keep)
    while True:
        stripped = _DATE_SUFFIX.sub("", s)
        if stripped == s or not stripped:
            break
        s = stripped
    return s


def _family(norm: str) -> str:
    """The leading letters of the first token (``qwen`` of ``qwen2.5-72b``)."""
    toks = tokens(norm)
    m = re.match(r"[a-z]+", toks[0]) if toks else None
    return m.group(0) if m else ""


def _version(norm: str) -> list[str]:
    """The numbers after the family name (``['3', '5']`` of ``gpt-3.5-turbo``)."""
    return re.findall(r"\d+", norm[len(_family(norm)):])


def heuristic_verdict(wanted: str, returned: str) -> Verdict:
    """Lexical comparison of two ids the knowledge base could not place."""
    want, got = normalize_model_id(wanted), normalize_model_id(returned)
    if not want or not got or want == got:
        return "consistent"
    want_tokens = set(tokens(want))
    # A downgrade-tier word in the echoed id that the requested one lacks;
    # checked before the substring tolerance, or gpt-4o -> gpt-4o-mini would
    # pass as a snapshot of gpt-4o.
    if any(t in DOWNGRADE_TOKENS and t not in want_tokens for t in tokens(got)):
        return "diverges"
    flat_want, flat_got = "".join(tokens(want)), "".join(tokens(got))
    if flat_want in flat_got or flat_got in flat_want:
        return "consistent"
    fam_want, fam_got = _family(want), _family(got)
    if fam_want and fam_got and fam_want != fam_got:
        return "diverges"
    ver_want, ver_got = _version(want), _version(got)
    if ver_want and ver_got and ver_want != ver_got:
        return "diverges"
    return "unknown"


@dataclass(frozen=True)
class EchoComparison:
    verdict: Verdict
    # How the verdict was reached: "kb" (both ids resolved) or "heuristic".
    basis: Literal["kb", "heuristic"]
    returned_profile: str | None = None
    claimed_profile: str | None = None

    def evidence(self) -> dict[str, str | None]:
        return {
            "basis": self.basis,
            "returned_profile": self.returned_profile,
            "claimed_profile": self.claimed_profile,
        }


def _resolve(kb: KnowledgeBase | None, name: str | None) -> ResolvedProfile | None:
    if kb is None or not name:
        return None
    return kb.resolve(name) or kb.resolve(normalize_model_id(name))


def _same_model(a: ResolvedProfile, b: ResolvedProfile) -> bool:
    return normalize_model_id(a.model.id) == normalize_model_id(b.model.id)


def compare_echoed_model(
    kb: KnowledgeBase | None,
    returned: str,
    *wanted: str | None,
    claimed_profile: ResolvedProfile | None = None,
) -> EchoComparison:
    """Compare the echoed ``returned`` id with the ``wanted`` ids (the claimed
    model and the id sent, which may be a deployment alias).

    ``claimed_profile`` is the claimed model's knowledge-base profile; without
    it the first ``wanted`` id that resolves stands in for it. When both the
    claimed model and the echoed id resolve, the profiles decide. Otherwise the
    heuristic runs against every wanted id (and the claimed profile's id):
    consistent with any of them is consistent, else ``unknown`` when any
    comparison could not tell, else ``diverges``.
    """
    names = list(dict.fromkeys(w.strip() for w in wanted if w and w.strip()))
    claimed = claimed_profile
    if claimed is None:
        claimed = next((r for r in (_resolve(kb, n) for n in names) if r), None)
    got = _resolve(kb, returned)
    claimed_id = claimed.model.id if claimed else None
    if got is not None and claimed is not None:
        return EchoComparison(
            "consistent" if _same_model(got, claimed) else "diverges",
            "kb", got.model.id, claimed_id,
        )
    if claimed_id and claimed_id not in names:
        names.append(claimed_id)
    verdicts = {heuristic_verdict(n, returned) for n in names} or {"unknown"}
    verdict: Verdict = (
        "consistent" if "consistent" in verdicts
        else "unknown" if "unknown" in verdicts
        else "diverges"
    )
    return EchoComparison(verdict, "heuristic", got.model.id if got else None, claimed_id)
