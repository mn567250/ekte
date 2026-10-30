"""The prompt library: every text zing sends to an LLM API.

Same pattern as the UI/alert translations (``zing/i18n/locales/<code>.json``):
one JSON file per language, ``zing/prompts/<code>.json``, with a ``meta`` block
and the entries under ``prompts``. An entry is a string, or JSON data (a list of
messages, a tool schema, a list of documents, …) sent as-is.

Probe language is fixed, deliberately independent of the UI/alert language: the
same relay must get the same verdict whoever reads the report, and zing's
answer checks, token estimates and fingerprints are calibrated to these exact
texts. All probes here are English (:data:`PROBE_LANG`). Probes whose language
*is* the measurement — e.g. the Chinese fluency / tokenizer / self-id
fingerprints of China-native models — live with their expected answers in the
knowledge base and declare ``prompt_lang`` / ``language_bound`` there.

``{{name}}`` in a string marks a value filled in at run time (single braces are
literal, so JSON inside a prompt needs no escaping).
"""

from __future__ import annotations

import copy
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

PROBE_LANG = "en"

_DIR = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@cache
def _library(lang: str = PROBE_LANG) -> dict[str, Any]:
    data = json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    prompts: dict[str, Any] = data["prompts"]
    return prompts


def ids() -> list[str]:
    """Every prompt id in the library."""
    return list(_library())


def get(prompt_id: str) -> Any:
    """A library entry as-is (a deep copy, so callers may mutate it)."""
    try:
        return copy.deepcopy(_library()[prompt_id])
    except KeyError:
        raise KeyError(f"unknown prompt id {prompt_id!r} (see zing/prompts/{PROBE_LANG}.json)") from None


def text(prompt_id: str, **values: Any) -> str:
    """A string entry with its ``{{name}}`` placeholders filled from ``values``.

    Every placeholder must be supplied, and every supplied value must be used,
    so a typo can't silently send a half-filled prompt.
    """
    template = get(prompt_id)
    if not isinstance(template, str):
        raise TypeError(f"prompt {prompt_id!r} is not a string entry")
    names = set(_PLACEHOLDER.findall(template))
    missing = names - set(values)
    extra = set(values) - names
    if missing or extra:
        raise KeyError(f"prompt {prompt_id!r}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)
