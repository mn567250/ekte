"""The prompt library (zing/prompts) and the language of everything sent to an API.

Probes are English and independent of the UI/alert language; the only
non-English prompts are knowledge-base fingerprints whose language is the
measurement, and those must say so (prompt_lang + language_bound).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from zing import prompts
from zing.knowledge import load_knowledge_base

ROOT = Path(__file__).resolve().parent.parent
# CJK *script* (ideographs, kana). Fullwidth punctuation is not language text:
# e.g. DeepSeek's special-token probe sends "<｜begin▁of▁sentence｜>" to test
# the tokenizer, not a language.
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def test_library_is_english_and_labelled():
    data = json.loads((ROOT / "zing" / "prompts" / "en.json").read_text("utf-8"))
    assert data["meta"]["code"] == prompts.PROBE_LANG == "en"
    offenders = [pid for pid in prompts.ids() for s in _strings(prompts.get(pid)) if CJK.search(s)]
    assert offenders == []


def test_every_library_prompt_is_used_and_every_used_id_exists():
    source = "\n".join(p.read_text("utf-8") for p in (ROOT / "zing").rglob("*.py"))
    used = set(re.findall(r'prompts\.(?:text|get)\(\s*"([^"]+)"', source))
    assert used, "no prompt lookups found"
    assert used - set(prompts.ids()) == set(), "code uses unknown prompt ids"
    assert set(prompts.ids()) - used == set(), "library has prompts nothing sends"


def test_text_fills_placeholders_strictly():
    assert prompts.text("connectivity.echo", marker="ZING-1") == (
        "Reply with exactly this text and nothing else: ZING-1"
    )
    # Single braces are literal (JSON inside a prompt).
    assert '{"status":"ok","value":7429}' in prompts.text("capability.json_mode")
    with pytest.raises(KeyError):
        prompts.text("connectivity.echo")  # missing value
    with pytest.raises(KeyError):
        prompts.text("reliability.ping", extra="x")  # unexpected value
    with pytest.raises(KeyError):
        prompts.get("no.such.prompt")
    with pytest.raises(TypeError):
        prompts.text("protocol.multi_turn")  # a message list, not a string


def test_get_returns_a_copy():
    tool = prompts.get("capability.tools.weather_tool")
    tool["function"]["name"] = "mutated"
    assert prompts.get("capability.tools.weather_tool")["function"]["name"] == "get_weather"


def test_non_english_fingerprints_declare_why():
    kb = load_knowledge_base()
    bound = 0
    for provider in kb.providers.values():
        for fp in provider.fingerprints or []:
            if CJK.search(fp.prompt):
                assert fp.prompt_lang != "en", f"{provider.provider}/{fp.id} has CJK but prompt_lang=en"
                assert fp.language_bound, f"{provider.provider}/{fp.id} needs a language_bound reason"
                bound += 1
            else:
                assert fp.prompt_lang == "en", f"{provider.provider}/{fp.id}"
    assert bound == 7  # the Chinese fluency / tokenizer / self-id probes of China-native models


def test_fingerprint_schema_rejects_unexplained_language():
    from zing.knowledge.schema import FingerprintProbe

    with pytest.raises(ValueError):
        FingerprintProbe(id="x", signal="s", prompt="你好", prompt_lang="zh")
    FingerprintProbe(id="x", signal="s", prompt="你好", prompt_lang="zh", language_bound="measures zh")


# CJK may appear in detector code only in tables that MATCH answers (brand
# names, colour words, "can't see the image" phrases) — never in text sent to
# an API, which lives in zing/prompts/en.json or the knowledge base.
_ANSWER_MATCHERS = {"_RIVAL_BRANDS", "VENDOR_BRANDS", "_EXPECTED_COLORS", "_BLIND_PHRASES", "_TOKEN_RE", "_CJK_RE"}


def test_code_sends_no_hard_coded_non_english_text():
    offenders = []
    for path in sorted((ROOT / "zing").rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        allowed: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id in _ANSWER_MATCHERS for t in targets):
                    allowed.update(id(n) for n in ast.walk(node))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and CJK.search(node.value)
                and id(node) not in allowed
                and id(node) not in docstrings
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value[:60]!r}")
    # Remaining CJK literals are user-facing wording handled elsewhere (the
    # i18n glossary, CLI help text, finding summaries) — none is sent to an API.
    allowed_non_api = {"zing/i18n/__init__.py", "zing/cli.py", "zing/embed_audit.py", "zing/media_audit.py",
                       "zing/detectors/vision.py", "zing/utils/tokenize.py"}
    unexpected = [o for o in offenders if o.split(":")[0] not in allowed_non_api]
    assert unexpected == []


def test_report_records_prompt_languages():
    from zing.models import DetectorResult, Dimension
    from zing.runner import _prompt_languages

    plain = DetectorResult(id="protocol", name="p", dimension=Dimension.PROTOCOL)
    ident = DetectorResult(id="model_identity", name="m", dimension=Dimension.MODEL_IDENTITY,
                           evidence={"fingerprint_prompt_langs": ["en", "zh"]})
    assert _prompt_languages([plain]) == ["en"]
    assert _prompt_languages([plain, ident]) == ["en", "zh"]
