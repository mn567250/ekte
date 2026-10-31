"""Billing detector tests — token/usage inflation.

Inflation (the buyer-harmful direction) should FAIL; honest accounting should not.
"""

from __future__ import annotations

import json

import httpx

from ekte.clients import OpenAICompatibleClient
from ekte.config import AuditOptions
from ekte.context import AuditContext
from ekte.detectors.billing import BillingDetector
from ekte.models import Severity, Status, TargetConfig
from ekte.utils.tokenize import estimate_messages_tokens, estimate_tokens


async def test_billing_flags_gross_inflation(audit_context, mock_server):
    mock_server.inflate_usage_factor = 6.0  # 6x overbilling on prompt + completion
    result = await BillingDetector().run(audit_context)
    assert result.status == Status.FAIL
    assert any(f.severity == Severity.HIGH for f in result.findings)


async def test_billing_passes_honest_usage(audit_context, mock_server):
    mock_server.inflate_usage_factor = 1.0
    result = await BillingDetector().run(audit_context)
    assert result.status != Status.FAIL


async def test_billing_warns_on_missing_usage(audit_context, mock_server):
    mock_server.emit_usage = False
    result = await BillingDetector().run(audit_context)
    assert result.status == Status.WARN
    assert any(f.id == "billing.missing-usage" for f in result.findings)


class _ReasoningMock:
    """Honest prompt tokens, but completion far exceeds visible text (reasoning tokens)."""

    def __init__(self, model: str = "deepseek-v4-flash", factor: int = 8) -> None:
        self.model = model
        self.factor = factor

    @property
    def transport(self):
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        text = "A concise two-sentence answer."
        prompt = estimate_messages_tokens(body["messages"], None)
        completion = estimate_tokens(text, None) * self.factor  # hidden reasoning inflates the count
        return httpx.Response(
            200,
            json={
                "model": self.model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion},
            },
        )


async def test_billing_reasoning_completion_not_flagged(knowledge_base):
    # deepseek-v4-flash is a reasoning model: high completion tokens are EXPECTED
    # (hidden reasoning), not inflation — must not FAIL.
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model="deepseek-v4-flash")
    async with OpenAICompatibleClient(target, transport=_ReasoningMock().transport) as c:
        ctx = AuditContext(
            target=target, client=c, options=AuditOptions(suite="standard"),
            kb=knowledge_base, profile=knowledge_base.resolve("deepseek-v4-flash"),
        )
        result = await BillingDetector().run(ctx)
    assert result.status != Status.FAIL
    assert all(f.severity != Severity.HIGH for f in result.findings)
    assert any(f.id == "billing.reasoning-tokens" for f in result.findings)


async def test_billing_completion_divergence_is_a_soft_signal(knowledge_base):
    # gpt-4o has an OpenAI-family tokenizer hint, but ekte never counts exactly
    # (no tokenizer is downloaded), so an inflated completion is only a WARN.
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model="gpt-4o")
    mock = _ReasoningMock(model="gpt-4o", factor=30)
    async with OpenAICompatibleClient(target, transport=mock.transport) as c:
        ctx = AuditContext(
            target=target, client=c, options=AuditOptions(suite="standard"),
            kb=knowledge_base, profile=knowledge_base.resolve("gpt-4o"),
        )
        assert ctx.tokenizer_hint() == "o200k_base"
        result = await BillingDetector().run(ctx)
    assert result.status == Status.WARN
    found = next(f for f in result.findings if f.id == "billing.usage-inflation-completion")
    assert (found.outcome, found.cap) == ("above_heuristic", 70.0)
    assert found.evidence["exact_tokenizer"] is False
    assert "heuristic" in result.evidence["estimate_note"]
    assert "tiktoken" not in result.evidence["estimate_note"]
