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
from ekte.models import CompletionOutcome, Severity, Status, TargetConfig
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


# --------------------------------------------------------------------------- #
# Several prompt sizes: slope (proportional) vs intercept (fixed overhead) (#252)
# --------------------------------------------------------------------------- #
class _UsageStub:
    """Stub client: reported prompt tokens = ``factor`` x ekte's estimate + ``fixed``."""

    def __init__(self, factor: float = 1.0, fixed: int = 0, *, fail_after: int | None = None,
                 reasoning_tokens: int | None = None, prompt_of=None) -> None:
        self.factor, self.fixed, self.fail_after = factor, fixed, fail_after
        self.reasoning_tokens = reasoning_tokens
        self.prompt_of = prompt_of
        self.specs: list = []

    async def complete(self, spec):
        self.specs.append(spec)
        if self.fail_after is not None and len(self.specs) > self.fail_after:
            return CompletionOutcome(ok=False, status_code=500, error_message="down")
        text = "The report outlines a plan. Residents and the council disagree about costs."
        est = estimate_messages_tokens(spec.messages, None)
        prompt = self.prompt_of(est) if self.prompt_of else int(est * self.factor) + self.fixed
        completion = estimate_tokens(text, None)
        usage: dict = {"prompt_tokens": prompt, "completion_tokens": completion,
                       "total_tokens": prompt + completion}
        if self.reasoning_tokens is not None:
            completion = completion * 8
            usage.update(completion_tokens=completion, total_tokens=prompt + completion,
                         completion_tokens_details={"reasoning_tokens": self.reasoning_tokens})
        return CompletionOutcome(ok=True, status_code=200, content=text, usage=usage,
                                 finish_reason="stop")


def _ctx(client, *, baseline_client=None, baseline_model: str = "m-1", baseline_api: str = "openai"):
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model="m-1")
    baseline = None
    if baseline_client is not None:
        baseline = TargetConfig(base_url="https://api.test/v1", api_key="sk-y-123456",
                                model=baseline_model, api=baseline_api)
    return AuditContext(target=target, client=client, options=AuditOptions(suite="standard"),
                        kb=None, profile=None, baseline=baseline,  # type: ignore[arg-type]
                        baseline_client=baseline_client)


def _by_id(result):
    return {f.id: f for f in result.findings}


async def test_three_prompt_sizes_are_sent():
    stub = _UsageStub()
    await BillingDetector().run(_ctx(stub))
    sizes = [estimate_messages_tokens(s.messages, None) for s in stub.specs]
    assert len(sizes) == 3
    assert 100 <= sizes[0] <= 200 and 450 <= sizes[1] <= 750 and 2000 <= sizes[2] <= 2800


async def test_one_and_a_half_times_the_estimate_warns():
    # Before #252 this was "usage consistent", score 100.
    result = await BillingDetector().run(_ctx(_UsageStub(factor=1.5)))
    f = _by_id(result)["billing.prompt-slope"]
    assert (f.outcome, f.status, f.severity, f.cap) == ("elevated", Status.WARN, Severity.MEDIUM, 70.0)
    assert result.status == Status.WARN and result.score == 70.0
    assert "billing.usage-consistent" not in _by_id(result)


async def test_twice_the_estimate_fails_high():
    result = await BillingDetector().run(_ctx(_UsageStub(factor=2.0)))
    f = _by_id(result)["billing.prompt-slope"]
    assert (f.outcome, f.status, f.severity) == ("inflated", Status.FAIL, Severity.HIGH)
    assert 1.95 <= f.evidence["slope"] <= 2.05
    assert result.status == Status.FAIL and result.score == 55.0


async def test_two_point_four_times_was_consistent_before_and_fails_now():
    result = await BillingDetector().run(_ctx(_UsageStub(factor=2.4)))
    assert result.status == Status.FAIL
    assert _by_id(result)["billing.prompt-slope"].outcome == "inflated"


async def test_fixed_overhead_is_not_usage_inflation():
    # +300 hidden tokens on every request: the slope is normal, the intercept large.
    result = await BillingDetector().run(_ctx(_UsageStub(factor=1.0, fixed=300)))
    found = _by_id(result)
    assert "billing.usage-inflation" not in found
    assert found["billing.prompt-slope"].outcome == "proportional"
    f = found["billing.fixed-overhead"]
    assert (f.outcome, f.status, f.severity) == ("large", Status.WARN, Severity.LOW)
    assert 295 <= f.evidence["intercept"] <= 305
    assert "injected_prompt" in f.recommendation
    assert result.status == Status.WARN and result.score == 90.0


async def test_small_fixed_overhead_is_info():
    result = await BillingDetector().run(_ctx(_UsageStub(factor=1.15, fixed=7)))
    f = _by_id(result)["billing.fixed-overhead"]
    assert (f.outcome, f.status) == ("small", Status.INFO)
    assert result.status == Status.PASS and result.score == 100.0


async def test_single_usable_size_falls_back_to_the_wide_margin():
    # Only the first call succeeds: 2.4x is under the 2.5x single-request margin.
    result = await BillingDetector().run(_ctx(_UsageStub(factor=2.4, fail_after=1)))
    found = _by_id(result)
    assert found["billing.prompt-slope-unmeasured"].outcome == "unmeasured"
    assert "billing.usage-inflation" not in found and result.status == Status.PASS
    result = await BillingDetector().run(_ctx(_UsageStub(factor=3.0, fail_after=1)))
    found = _by_id(result)
    assert found["billing.prompt-slope-unmeasured"].outcome == "unmeasured"
    assert found["billing.usage-inflation"].cap == 55.0 and result.status == Status.FAIL


async def test_honest_mock_relay_stays_inside_the_slope_tolerance(audit_context, mock_server):
    mock_server.inflate_usage_factor = 1.0
    result = await BillingDetector().run(audit_context)
    assert len(mock_server.requests) == 3
    assert result.evidence["slope"] <= 1.35
    assert result.status == Status.PASS


# --------------------------------------------------------------------------- #
# Compare mode: the baseline's exact counts replace the slope verdict (#252)
# --------------------------------------------------------------------------- #
async def test_ten_percent_more_than_the_baseline_fails_high():
    base = _UsageStub(factor=1.1)
    target = _UsageStub(prompt_of=lambda est: int(int(est * 1.1) * 1.1))
    result = await BillingDetector().run(_ctx(target, baseline_client=base))
    found = _by_id(result)
    f = found["billing.prompt-vs-baseline"]
    assert (f.outcome, f.status, f.severity, f.cap) == ("inflated", Status.FAIL, Severity.HIGH, 55.0)
    assert f.evidence["target_prompt"] > f.evidence["baseline_prompt"] > 0
    assert len(base.specs) == 3 and [s.messages for s in base.specs] == [s.messages for s in target.specs]
    assert "billing.prompt-slope" not in found  # the baseline replaces the heuristic verdict
    assert result.status == Status.FAIL and result.score == 55.0


async def test_matching_the_baseline_passes_even_with_a_dense_tokenizer():
    # 1.5x the heuristic would warn on its own, but the baseline counts the same.
    base, target = _UsageStub(factor=1.5), _UsageStub(factor=1.5, fixed=3)
    result = await BillingDetector().run(_ctx(target, baseline_client=base))
    f = _by_id(result)["billing.prompt-vs-baseline"]
    assert (f.outcome, f.status) == ("matches", Status.PASS)
    assert result.status == Status.PASS and result.score == 100.0


async def test_a_hidden_prefix_fails_against_the_baseline():
    result = await BillingDetector().run(_ctx(_UsageStub(fixed=300), baseline_client=_UsageStub()))
    assert _by_id(result)["billing.prompt-vs-baseline"].outcome == "inflated"


async def test_baseline_of_another_protocol_or_model_is_not_compared():
    for kw in ({"baseline_api": "anthropic"}, {"baseline_model": "other-model"}):
        base = _UsageStub()
        result = await BillingDetector().run(_ctx(_UsageStub(factor=1.1), baseline_client=base, **kw))
        assert base.specs == [] and "billing.prompt-vs-baseline" not in _by_id(result)
        assert _by_id(result)["billing.prompt-slope"].outcome == "proportional"


# --------------------------------------------------------------------------- #
# Reasoning = the profile says so OR the response reports reasoning tokens
# --------------------------------------------------------------------------- #
async def test_reported_reasoning_tokens_mark_an_unprofiled_reasoning_model():
    result = await BillingDetector().run(_ctx(_UsageStub(reasoning_tokens=300)))
    found = _by_id(result)
    assert "billing.reasoning-tokens" in found
    assert "billing.usage-inflation-completion" not in found
    assert result.status == Status.PASS
