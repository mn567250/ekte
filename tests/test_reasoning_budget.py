"""Short probes against reasoning models, and prefix caching on local servers.

A reasoning model can think through a probe's few dozen output tokens and return
an empty (or cut-off) answer with ``finish_reason=length``; the client repeats
such a request once with room to think. A local server that reuses the KV cache
of its chat template reports a few cached tokens on every unique prompt; that is
not a cache hit.
"""

from __future__ import annotations

import json

import httpx
from conftest import BASE_URL

from zing.clients import OpenAICompatibleClient
from zing.clients.base import REASONING_RETRY_TOKENS
from zing.models import CompletionOutcome, RequestSpec, TargetConfig
from zing.perf.recorder import RequestRecorder, is_cache_hit


class ThinkingRelay:
    """Thinks for ``think`` tokens, then answers in ``answer_tokens`` more."""

    def __init__(self, think: int = 200, answer: str = "Paris", report_reasoning: bool = True,
                 answer_tokens: int = 5):
        self.think = think
        self.answer = answer
        self.answer_tokens = answer_tokens
        self.report_reasoning = report_reasoning
        self.bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        budget = body.get("max_tokens") or body.get("max_completion_tokens") or 10_000
        if budget <= self.think:
            content, used, finish = "", budget, "length"
        elif budget < self.think + self.answer_tokens:
            content, used, finish = self.answer[:budget - self.think], budget, "length"
        else:
            content, used, finish = self.answer, self.think + self.answer_tokens, "stop"
        usage: dict = {"prompt_tokens": 10, "completion_tokens": used, "total_tokens": 10 + used}
        if self.report_reasoning:
            usage["completion_tokens_details"] = {"reasoning_tokens": min(used, self.think)}
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": finish}],
            "usage": usage,
        })

    def client(self, recorder: RequestRecorder | None = None) -> OpenAICompatibleClient:
        cfg = TargetConfig(base_url=BASE_URL, api_key="sk-x", model="m")
        client = OpenAICompatibleClient(cfg, transport=httpx.MockTransport(self.handler))
        client.recorder = recorder
        return client


def _spec(**kw) -> RequestSpec:
    return RequestSpec(messages=[{"role": "user", "content": "capital of France?"}], **kw)


async def test_empty_answer_at_the_limit_is_repeated_with_room_to_think():
    relay = ThinkingRelay()
    rec = RequestRecorder()
    out = await relay.client(rec).complete(_spec(max_tokens=16))
    assert out.ok and out.content == "Paris"
    assert [b["max_tokens"] for b in relay.bodies] == [16, REASONING_RETRY_TOKENS]
    assert len(rec.records) == 2  # both calls are recorded


async def test_repeat_keeps_the_limit_field_the_request_used():
    relay = ThinkingRelay()
    out = await relay.client().complete(
        _spec(max_tokens=None, extra_body={"max_completion_tokens": 64})
    )
    assert out.content == "Paris"
    assert relay.bodies[1]["max_completion_tokens"] == REASONING_RETRY_TOKENS
    assert relay.bodies[1].get("max_tokens") is None


async def test_answer_cut_off_by_reasoning_is_repeated():
    relay = ThinkingRelay(think=14)  # 16 tokens: thinks 14, answers "Pa", stops
    out = await relay.client().complete(_spec(max_tokens=16))
    assert out.content == "Paris" and len(relay.bodies) == 2


async def test_unreported_thinking_is_inferred_from_an_empty_answer():
    relay = ThinkingRelay(report_reasoning=False)
    out = await relay.client().complete(_spec(max_tokens=16))
    assert out.content == "Paris" and len(relay.bodies) == 2


async def test_no_repeat_when_the_answer_fits_or_retry_is_off():
    relay = ThinkingRelay(think=0)
    await relay.client().complete(_spec(max_tokens=16))
    assert len(relay.bodies) == 1

    relay = ThinkingRelay()
    out = await relay.client().complete(_spec(max_tokens=16, reasoning_retry=False))
    assert out.content == "" and len(relay.bodies) == 1


async def test_no_repeat_for_large_budgets_or_plain_truncation():
    relay = ThinkingRelay(think=10_000)
    await relay.client().complete(_spec(max_tokens=REASONING_RETRY_TOKENS))
    assert len(relay.bodies) == 1  # already asked for the retry budget

    relay = ThinkingRelay()
    await relay.client().complete(_spec(max_tokens=None))
    assert len(relay.bodies) == 1  # no explicit limit

    # A non-reasoning answer truncated at the limit is the limit working.
    relay = ThinkingRelay(think=0, answer="a long answer", report_reasoning=False,
                          answer_tokens=13)
    await relay.client().complete(_spec(max_tokens=3))
    assert len(relay.bodies) == 1


async def test_integrity_ignores_a_canary_cut_off_at_the_limit():
    from zing.detectors.integrity import IntegrityDetector

    class _Client:
        async def complete(self, spec):
            return CompletionOutcome(ok=True, content="pip install zing-audit==0",
                                     finish_reason="length")

    class _Ctx:
        client = _Client()
        baseline_client = None

    assert await IntegrityDetector()._ask(_Ctx(), "prompt") is None


def test_chat_template_prefix_is_not_a_cache_hit():
    assert not is_cache_hit(None, 40)
    assert not is_cache_hit(0, 40)
    assert not is_cache_hit(24, 60)  # template prefix reused from the KV cache
    assert is_cache_hit(40, 60)
    assert is_cache_hit(5, 5)
    assert is_cache_hit(3, None)  # prompt size unknown: any cached tokens count


def test_recorder_flags_only_mostly_cached_prompts():
    rec = RequestRecorder()
    spec = RequestSpec(messages=[{"role": "user", "content": "hi"}])

    def record(cached: int) -> bool:
        rec.record_completion("target", spec, CompletionOutcome(
            ok=True, duration_ms=50.0, content="hi",
            usage={"prompt_tokens": 60, "completion_tokens": 1,
                   "prompt_tokens_details": {"cached_tokens": cached}},
        ), rec.t0)
        return rec.records[-1].cached

    assert not record(24)
    assert record(48)



async def test_long_answer_after_a_little_reasoning_is_not_repeated():
    # 64-token limit: 10 tokens of thinking, then a long answer hits the limit.
    relay = ThinkingRelay(think=10, answer="x" * 400, answer_tokens=400)
    out = await relay.client().complete(_spec(max_tokens=64))
    assert out.finish_reason == "length" and len(relay.bodies) == 1


async def test_after_the_first_repeat_short_probes_get_room_up_front():
    relay = ThinkingRelay()
    client = relay.client()
    assert not client.reasoning_room
    await client.complete(_spec(max_tokens=16))
    assert client.reasoning_room
    out = await client.complete(_spec(max_tokens=32))
    assert out.content == "Paris"
    assert [b["max_tokens"] for b in relay.bodies] == [16, REASONING_RETRY_TOKENS,
                                                       REASONING_RETRY_TOKENS]
    await client.complete(_spec(max_tokens=None, extra_body={"max_completion_tokens": 64}))
    assert relay.bodies[-1]["max_completion_tokens"] == REASONING_RETRY_TOKENS
    assert relay.bodies[-1].get("max_tokens") is None


async def test_reasoning_room_leaves_opt_outs_and_other_budgets_alone():
    relay = ThinkingRelay()
    client = relay.client()
    client.reasoning_room = True
    out = await client.complete(_spec(max_tokens=16, reasoning_retry=False))
    assert out.content == "" and relay.bodies[-1]["max_tokens"] == 16
    await client.complete(_spec(max_tokens=None))
    assert relay.bodies[-1].get("max_tokens") is None  # no explicit limit
    await client.complete(_spec(max_tokens=8192))
    assert relay.bodies[-1]["max_tokens"] == 8192  # already large enough
    assert len(relay.bodies) == 3  # no repeats


async def test_a_plain_model_never_gets_reasoning_room():
    relay = ThinkingRelay(think=0)
    client = relay.client()
    await client.complete(_spec(max_tokens=16))
    await client.complete(_spec(max_tokens=16))
    assert not client.reasoning_room
    assert [b["max_tokens"] for b in relay.bodies] == [16, 16]


async def test_a_repeat_that_did_not_help_is_not_sticky():
    relay = ThinkingRelay(think=10_000)  # still empty at the retry budget
    client = relay.client()
    await client.complete(_spec(max_tokens=16))
    assert not client.reasoning_room
    await client.complete(_spec(max_tokens=16))
    assert [b["max_tokens"] for b in relay.bodies] == [16, REASONING_RETRY_TOKENS] * 2


async def test_runner_gives_a_reasoning_profile_room_up_front(monkeypatch, tmp_path):
    from conftest import MockServer

    from zing.clients import make_client as real
    from zing.config import AuditOptions
    from zing.runner import run_audit

    (tmp_path / "thinker.yaml").write_text(
        "provider: acme\n"
        "models:\n"
        "  - id: thinker-1\n"
        "    family: thinker\n"
        "    reasoning: true\n"
    )
    clients: list = []

    def factory(config, **_):
        client = real(config, transport=MockServer().transport)
        clients.append(client)
        return client

    monkeypatch.setattr("zing.runner.make_client", factory)
    for model, base_model, expected in (
        ("thinker-1", "thinker-1", [True, True]),
        ("plain-model", "plain-model", [False, False]),
        ("thinker-1", "plain-model", [True, False]),  # baseline has its own profile
        ("plain-model", "thinker-1", [False, True]),
    ):
        clients.clear()
        await run_audit(
            TargetConfig(name="t", kind="target", base_url=BASE_URL, model=model),
            AuditOptions(suite="custom", dimensions=["connectivity"]),
            baseline=TargetConfig(name="b", kind="baseline", base_url=BASE_URL,
                                  model=base_model),
            kb_dirs=[tmp_path],
            use_user_kb=False,
        )
        assert [c.reasoning_room for c in clients] == expected
