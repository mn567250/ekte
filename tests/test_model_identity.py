"""Model-identity detector tests — the core 货不对板 check.

Covers the false-positive/false-negative fixes: the #1 silent downgrade
(gpt-4o -> gpt-4o-mini) must be caught, while an honest model that merely
contrasts itself against rival brands must not be flagged HIGH.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ekte.clients import OpenAICompatibleClient
from ekte.config import AuditOptions
from ekte.context import AuditContext
from ekte.detectors.helpers import contains_word, contains_word_any, words_present
from ekte.detectors.model_identity import ModelIdentityDetector
from ekte.models import Severity, Status, TargetConfig


@pytest.mark.parametrize(
    "requested,returned,diverges",
    [
        ("gpt-4o", "gpt-4o-mini", True),     # the #1 silent downgrade
        ("gpt-4.1", "gpt-4.1-nano", True),
        ("gpt-5.4", "gpt-5.4-mini", True),
        ("gpt-4o", "gpt-4o-2024-08-06", False),         # snapshot, not a downgrade
        ("claude-3-haiku", "claude-3-haiku-20240307", False),
        ("gpt-4o", "qwen-max", True),                    # different family
        ("gpt-4o", "gpt-4o", False),
    ],
)
def test_model_field_diverges(requested, returned, diverges):
    assert ModelIdentityDetector._model_field_diverges(requested, returned) is diverges


def test_contains_word_respects_boundaries():
    assert not contains_word("metadata about the model", "meta")
    assert not contains_word("I am ChatGPT", "gpt")
    assert contains_word("I am ChatGPT", "chatgpt")
    assert contains_word("Unlike Llama models", "llama")
    assert contains_word("I'm GPT-5", "gpt-5")


def test_words_present_filters_to_whole_words():
    text = "I am Claude by Anthropic, not a Google or Meta model"
    assert set(words_present(text, ["google", "meta", "metadata"])) == {"google", "meta"}
    assert contains_word_any(text, ["claude", "anthropic"])


async def test_rival_brand_self_id_is_high(audit_context, mock_server):
    # gpt-4o relay that self-identifies as Claude -> strong substitution signal.
    mock_server.self_identity = "I am Claude, an AI assistant made by Anthropic."
    result = await ModelIdentityDetector().run(audit_context)
    assert result.status == Status.FAIL
    assert any(f.severity == Severity.HIGH for f in result.findings)


async def test_honest_self_id_with_negation_is_not_high(audit_context, mock_server):
    # Honest gpt-4o naming rivals only to contrast itself must NOT be flagged HIGH.
    mock_server.self_identity = (
        "I am GPT-4o, made by OpenAI — not Claude, Gemini, or a Meta model."
    )
    result = await ModelIdentityDetector().run(audit_context)
    assert all(f.severity != Severity.HIGH for f in result.findings)
    assert result.status != Status.FAIL


async def test_echoed_downgrade_model_field_is_flagged(audit_context, mock_server):
    # The relay claims gpt-4o but echoes model=gpt-4o-mini.
    mock_server.served_model = "gpt-4o-mini"
    result = await ModelIdentityDetector().run(audit_context)
    field_findings = [f for f in result.findings if f.id == "model_identity.model_field"]
    assert field_findings and field_findings[0].status == Status.WARN


def test_forbidden_brands_includes_global_rivals(knowledge_base):
    # A DeepSeek profile's forbidden set must include rivals the KB never listed
    # (Doubao/ByteDance) so a Doubao substitution can't slip through.
    resolved = knowledge_base.resolve("deepseek-v4-flash")
    forbidden = {b.lower() for b in ModelIdentityDetector._forbidden_brands(resolved.model, resolved.provider)}
    assert {"doubao", "豆包", "bytedance", "字节跳动"} <= forbidden
    assert "deepseek" not in forbidden  # the model's own brand is never forbidden


class _SelfIdMock:
    def __init__(self, self_identity: str, served_model: str = "deepseek-v4-flash"):
        self.self_identity = self_identity
        self.served_model = served_model

    @property
    def transport(self):
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        user = " ".join(m.get("content", "") for m in body["messages"]).lower()
        is_id = "what model are you" in user or "who are you" in user or "which model" in user
        text = self.self_identity if is_id else "ok"
        return httpx.Response(
            200,
            json={
                "model": self.served_model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )


async def test_doubao_sold_as_deepseek_is_detected(knowledge_base):
    # A ByteDance/Doubao model audited against the deepseek-v4-flash profile must FAIL.
    mock = _SelfIdMock("I am Doubao (豆包), a model developed by ByteDance (字节跳动).")
    target = TargetConfig(
        base_url="https://relay.test/v1", api_key="sk-x-123456",
        model="doubao-seed-2-0-lite-260428", claimed_model="deepseek-v4-flash",
    )
    assert target.claimed == "deepseek-v4-flash"
    async with OpenAICompatibleClient(target, transport=mock.transport) as c:
        ctx = AuditContext(
            target=target, client=c, options=AuditOptions(suite="standard"),
            kb=knowledge_base, profile=knowledge_base.resolve(target.claimed),
        )
        result = await ModelIdentityDetector().run(ctx)
    assert result.status == Status.FAIL
    assert any(f.severity == Severity.HIGH for f in result.findings)


async def test_genuine_deepseek_self_id_passes(knowledge_base):
    mock = _SelfIdMock("I am DeepSeek-V4, a model from DeepSeek (深度求索).")
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model="deepseek-v4-flash")
    async with OpenAICompatibleClient(target, transport=mock.transport) as c:
        ctx = AuditContext(
            target=target, client=c, options=AuditOptions(suite="standard"),
            kb=knowledge_base, profile=knowledge_base.resolve("deepseek-v4-flash"),
        )
        result = await ModelIdentityDetector().run(ctx)
    self_id = [f for f in result.findings if f.id == "model_identity.self_id"]
    assert self_id and self_id[0].status == Status.PASS


# ----- own brand words: a profile without identity_keywords --------------- #
def _own_brand_kb(self_id_fingerprint: bool = False):
    from ekte.knowledge.schema import FingerprintProbe, KnowledgeBase, ModelProfile, ProviderProfile

    fps = [FingerprintProbe(
        id="glm.who", signal="self-description", prompt="Who are you? One sentence.",
        pure_code_checkable=True, expect_regex=r"\w",
    )] if self_id_fingerprint else []
    provider = ProviderProfile(
        provider="glm", display_name="Z.ai", fingerprints=fps,
        models=[ModelProfile(id="glm-4.6v-flash", family="glm-4.6v", identity_keywords=[])],
    )
    return KnowledgeBase(providers={"glm": provider})


async def _run_own_brand(answer: str, *, self_id_fingerprint: bool = False):
    kb = _own_brand_kb(self_id_fingerprint)
    mock = _SelfIdMock(answer, served_model="glm-4.6v-flash")
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model="glm-4.6v-flash")
    async with OpenAICompatibleClient(target, transport=mock.transport) as c:
        ctx = AuditContext(
            target=target, client=c, options=AuditOptions(suite="standard"),
            kb=kb, profile=kb.resolve("glm-4.6v-flash"),
        )
        return await ModelIdentityDetector().run(ctx)


def test_own_brand_words_from_names():
    from ekte.knowledge.identity import own_brand_words
    from ekte.knowledge.schema import ModelProfile, ProviderProfile

    model = ModelProfile(id="glm-4.6v-flash", family="glm-4.6v")
    # Provider key, display_name and model id, widened to the vendor's other names.
    assert own_brand_words(ProviderProfile(provider="glm", display_name="Z.ai"), model) == [
        "glm", "z.ai", "chatglm", "zhipu", "智谱"]
    # Only the leading name of a long display_name counts, without generic words.
    long_name = ProviderProfile(provider="zp", display_name="Zhipu AI (智谱 / Z.ai) — BigModel open platform")
    assert own_brand_words(long_name, ModelProfile(id="vision-9"), widen=False) == ["zp", "zhipu"]
    assert not {"ai", "open", "platform", "bigmodel"} & set(own_brand_words(long_name, model))
    # Explicit keywords come first and are kept as given (lower-cased).
    assert own_brand_words(None, ModelProfile(id="org/acme-1:q4", identity_keywords=["Acme AI"])) == [
        "acme ai", "acme"]
    forbidden = {b.lower() for b in ModelIdentityDetector._forbidden_brands(model, long_name)}
    assert not {"glm", "zhipu", "z.ai"} & forbidden
    assert {"qwen", "openai"} <= forbidden


async def test_own_brand_without_identity_keywords_is_not_a_rival():
    result = await _run_own_brand("I am the GLM-4.5V model, built by Zhipu AI.", self_id_fingerprint=True)
    assert result.status != Status.FAIL
    assert all(f.severity != Severity.HIGH for f in result.findings)
    self_id = next(f for f in result.findings if f.id == "model_identity.self_id")
    assert self_id.status == Status.PASS
    assert next(f for f in result.findings if f.id == "model_identity.fp.glm.who").status == Status.PASS


async def test_rival_brand_still_flagged_without_identity_keywords():
    result = await _run_own_brand("I am Qwen, a model developed by Alibaba Cloud.", self_id_fingerprint=True)
    assert result.status == Status.FAIL
    self_id = next(f for f in result.findings if f.id == "model_identity.self_id")
    assert self_id.severity == Severity.HIGH
    assert next(f for f in result.findings if f.id == "model_identity.fp.glm.who").severity == Severity.HIGH


def test_own_brand_words_stay_narrow():
    from ekte.knowledge.identity import own_brand_words
    from ekte.knowledge.schema import ModelProfile, ProviderProfile

    # A platform serving another vendor's model: its own brand stays a rival.
    host = ProviderProfile(provider="qwen", display_name="Alibaba Cloud — Model Studio")
    words = own_brand_words(host, ModelProfile(id="deepseek-r1"))
    assert "deepseek" in words and not {"qwen", "alibaba"} & set(words)
    assert "qwen" in ModelIdentityDetector._forbidden_brands(ModelProfile(id="deepseek-r1"), host)
    # A derived word never overrides an explicit identity_forbidden.
    tune = ModelProfile(id="llama-3-hermes", identity_forbidden=["llama", "meta"])
    assert not {"llama", "meta"} & set(own_brand_words(None, tune))
    # Unwidened (as the import stores them): only the profile's own names.
    glm = ProviderProfile(provider="glm", display_name="Z.ai")
    assert own_brand_words(glm, ModelProfile(id="glm-4.6v-flash"), widen=False) == ["glm", "z.ai"]
    # Generic words from a model id do not count.
    assert own_brand_words(None, ModelProfile(id="tts-1")) == []


# ----- no usable evidence: inconclusive, not a clean 100 ------------------ #
class _FnMock:
    """A relay whose reply to each request comes from ``fn(user_text)``, which
    returns ``(http_status, content, model)``."""

    def __init__(self, fn):
        self.fn = fn

    @property
    def transport(self):
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        user = " ".join(m.get("content", "") for m in body["messages"])
        status, text, model = self.fn(user)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "bad request", "type": "invalid_request_error"}})
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )


async def _run_fn(knowledge_base, fn, model: str = "deepseek-v4-flash", kb=None):
    kb = kb or knowledge_base
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model=model)
    async with OpenAICompatibleClient(target, transport=_FnMock(fn).transport) as c:
        ctx = AuditContext(
            target=target, client=c, options=AuditOptions(suite="standard"),
            kb=kb, profile=kb.resolve(model),
        )
        return await ModelIdentityDetector().run(ctx)


async def test_every_request_rejected_is_inconclusive(knowledge_base):
    result = await _run_fn(knowledge_base, lambda u: (400, "", ""))
    assert result.status == Status.INCONCLUSIVE and result.score is None
    no_ev = next(f for f in result.findings if f.id == "model_identity.no_evidence")
    assert no_ev.status == Status.INCONCLUSIVE and no_ev.outcome == "none"


async def test_empty_answers_with_echoed_model_are_inconclusive(knowledge_base):
    # A matching echoed model field alone is no identity evidence.
    result = await _run_fn(knowledge_base, lambda u: (200, "", "deepseek-v4-flash"))
    assert next(f for f in result.findings if f.id == "model_identity.model_field").status == Status.PASS
    assert result.status == Status.INCONCLUSIVE and result.score is None
    assert any(f.id == "model_identity.no_evidence" for f in result.findings)


async def test_partial_evidence_still_scores(knowledge_base):
    def fn(user):
        if "What model are you" in user:
            return 200, "I am DeepSeek-V4, a model from DeepSeek.", "deepseek-v4-flash"
        return 400, "", ""

    result = await _run_fn(knowledge_base, fn)
    assert result.status == Status.PASS and result.score == 100.0
    assert not any(f.id == "model_identity.no_evidence" for f in result.findings)


async def test_diverging_model_field_alone_is_evidence(knowledge_base):
    result = await _run_fn(knowledge_base, lambda u: (200, "", "qwen-max"))
    assert result.status == Status.WARN and result.score is not None
    assert not any(f.id == "model_identity.no_evidence" for f in result.findings)


# ----- ambiguous brand words ("step", "meta", ...) ------------------------ #
def test_ambiguous_brand_words_count_only_as_names():
    from ekte.detectors.model_identity import _brand_hits

    words = ["step", "meta", "qwen"]
    assert _brand_hits("Let me think step by step, a meta question.", words, ambiguous=True) == []
    assert _brand_hits("I am Step-2 by StepFun, not Meta.", words, ambiguous=True) == ["step", "meta"]
    # A sentence-initial capital proves nothing unless a version is attached.
    assert _brand_hits("Step by step. Meta-level: no.", words, ambiguous=True) == []
    assert _brand_hits("Step-2 here.", words, ambiguous=True) == ["step"]
    for text in ("- Step by step", "## Step by step", "1) Step by step", "Intro\nStep one",
                 "Step 1: I am an AI assistant.", "I ran a Meta-analysis."):
        assert _brand_hits(text, words, ambiguous=True) == [], text
    # A version or model letter makes it a name in any case and position.
    for text, hit in (("I am grok-2.", "grok"), ("Command R+, here to help.", "command"),
                      ("Developer: Meta", "meta"), ("I am Yi-34B.", "yi")):
        assert _brand_hits(text, [hit], ambiguous=True) == [hit], text
    # In fingerprint answers they never count; unambiguous brands always do.
    assert _brand_hits("I am Step-2, not Qwen.", words, ambiguous=False) == ["qwen"]
    assert _brand_hits("built on qwen", words, ambiguous=True) == ["qwen"]


async def test_step_by_step_in_a_fingerprint_is_not_a_rival(knowledge_base):
    # Honest DeepSeek narrating its knowledge-cutoff answer "step by step".
    def fn(user):
        if "What model are you" in user:
            return 200, "I am DeepSeek-V4, developed by DeepSeek.", "deepseek-v4-flash"
        return 200, "2024-07. Let me think step by step: a meta point, the seed of an idea.", "deepseek-v4-flash"

    result = await _run_fn(knowledge_base, fn)
    assert not any(f.outcome == "rival_brand" for f in result.findings)
    assert all(f.severity != Severity.HIGH for f in result.findings)
    assert result.status != Status.FAIL


async def test_ambiguous_word_in_self_id(knowledge_base):
    # Written as a name in the self-description it still betrays a swap ...
    rival = await _run_fn(knowledge_base, lambda u: (200, "I am Step-2, a large language model.", "deepseek-v4-flash"))
    self_id = next(f for f in rival.findings if f.id == "model_identity.self_id")
    assert self_id.outcome == "rival_brand" and rival.status == Status.FAIL
    # ... the everyday word does not.
    plain = await _run_fn(
        knowledge_base, lambda u: (200, "Step by step: I am a large language model.", "deepseek-v4-flash")
    )
    assert next(f for f in plain.findings if f.id == "model_identity.self_id").outcome == "evasive"


async def test_vendor_owning_an_ambiguous_word_keeps_it(knowledge_base):
    from ekte.knowledge.schema import KnowledgeBase, ModelProfile, ProviderProfile

    provider = ProviderProfile(
        provider="cohere", display_name="Cohere",
        models=[ModelProfile(id="command-r-plus", family="command-r", identity_keywords=[])],
    )
    kb = KnowledgeBase(providers={"cohere": provider})
    assert "command" not in ModelIdentityDetector._forbidden_brands(provider.models[0], provider)
    result = await _run_fn(
        knowledge_base, lambda u: (200, "I am Command R+, a model built by Cohere.", "command-r-plus"),
        model="command-r-plus", kb=kb,
    )
    assert next(f for f in result.findings if f.id == "model_identity.self_id").status == Status.PASS
    assert result.status == Status.PASS
