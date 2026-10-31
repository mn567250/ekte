"""Every client records when the first streamed REASONING delta arrives
(``CompletionOutcome.first_reasoning_ms``), so the streaming detector can time a
reasoning model's stream from its first token of either kind."""

from __future__ import annotations

import json

import httpx

from ekte.clients import AnthropicClient, OpenAICompatibleClient, ResponsesClient
from ekte.models import RequestSpec, TargetConfig


def _sse(events: list[dict], *, done: bool = False) -> httpx.MockTransport:
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + ("data: [DONE]\n\n" if done else "")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


def _target(api: str) -> TargetConfig:
    return TargetConfig(base_url="https://relay.test/v1", api_key="sk-test", model="m", api=api)


_SPEC = RequestSpec(messages=[{"role": "user", "content": "hi"}], max_tokens=32, stream=True)


def _chat(delta: dict) -> dict:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


async def test_chat_completions_reasoning_content_is_timed():
    transport = _sse([_chat({"reasoning_content": "thinking"}), _chat({"content": "answer"})], done=True)
    async with OpenAICompatibleClient(_target("openai"), transport=transport) as c:
        out = await c.complete(_SPEC)
    assert out.ok and out.content == "answer"
    assert out.first_reasoning_ms is not None and out.ttft_ms is not None
    assert out.first_reasoning_ms <= out.ttft_ms


async def test_chat_completions_without_reasoning_leaves_it_unset():
    transport = _sse([_chat({"content": "answer"})], done=True)
    async with OpenAICompatibleClient(_target("openai"), transport=transport) as c:
        out = await c.complete(_SPEC)
    assert out.first_reasoning_ms is None


async def test_anthropic_thinking_delta_is_timed():
    transport = _sse([
        {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "answer"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ])
    async with AnthropicClient(_target("anthropic"), transport=transport) as c:
        out = await c.complete(_SPEC)
    assert out.ok and out.content == "answer"
    assert out.first_reasoning_ms is not None and out.first_reasoning_ms <= (out.ttft_ms or 0)


async def test_responses_reasoning_event_is_timed():
    transport = _sse([
        {"type": "response.reasoning_summary_text.delta", "delta": "thinking"},
        {"type": "response.output_text.delta", "delta": "answer"},
        {"type": "response.completed",
         "response": {"status": "completed", "usage": {"input_tokens": 3, "output_tokens": 5}}},
    ])
    async with ResponsesClient(_target("responses"), transport=transport) as c:
        out = await c.complete(_SPEC)
    assert out.ok and out.content == "answer"
    assert out.first_reasoning_ms is not None and out.first_reasoning_ms <= (out.ttft_ms or 0)
