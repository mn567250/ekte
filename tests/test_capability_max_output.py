"""The max-output check and a relay that clamps the output (#253).

An answer cut off with ``finish_reason: length`` reaches the cap only when at
least 80 % of the requested tokens came back: reported completion tokens when
present, else a text estimate, with a reasoning model's reasoning tokens counted
as delivered. Below that the relay clamped ``max_tokens``: ``clamped``, Fail.
"""

from __future__ import annotations

import pytest

from ekte.cli import _build_options
from ekte.config import AuditOptions
from ekte.context import AuditContext
from ekte.detectors.capability import SCALE, TO_CAP_SHARE, CapabilityDetector
from ekte.detectors.scale import Scale
from ekte.models import (
    CompletionOutcome,
    DetectorResult,
    RequestSpec,
    Severity,
    Status,
    TargetConfig,
)


def _numbers(n: int) -> str:
    return "\n".join(str(i) for i in range(1, n + 1))


class _Stub:
    """Answers the max-output probe with ``reply``; every other probe gets a
    plain answer (the other capability checks are not under test here)."""

    def __init__(self, reply: CompletionOutcome):
        self.reply = reply
        self.specs: list[RequestSpec] = []

    async def complete(self, spec: RequestSpec) -> CompletionOutcome:
        self.specs.append(spec)
        if spec.tools or spec.response_format:
            return CompletionOutcome(ok=True, status_code=200, content="ok", finish_reason="stop")
        return self.reply.model_copy()


def _ctx(knowledge_base, reply: CompletionOutcome, *, reasoning: bool | None = None, **options):
    target = TargetConfig(name="t", kind="target", base_url="https://relay.example/v1", api_key="k",
                          model="gpt-4o", api="openai")
    profile = knowledge_base.resolve("gpt-4o")
    if reasoning is not None:
        model = profile.model.model_copy(update={"reasoning": reasoning})
        profile = profile.model_copy(update={"model": model})
    return AuditContext(target=target, client=_Stub(reply), options=AuditOptions(suite="standard", **options),
                        kb=knowledge_base, profile=profile)


async def _max_output(ctx: AuditContext):
    result: DetectorResult = await CapabilityDetector().run(ctx)
    for f in result.findings:
        o = SCALE.get(f.scale_check, f.outcome or "")
        assert (f.status, f.severity, f.score) == (o.status, o.severity, o.score), f.id
    assert result.score == Scale.mean(result.findings)
    return next(f for f in result.findings if f.scale_check == "capability.max_output")


def _length(content: str, usage: dict | None = None) -> CompletionOutcome:
    return CompletionOutcome(ok=True, status_code=200, content=content, finish_reason="length", usage=usage)


async def test_clamped_relay_fails(knowledge_base):
    # The issue's reproduction: ten lines, 100 completion tokens, finish_reason
    # length against a 2048-token request.
    reply = _length(_numbers(10), {"prompt_tokens": 30, "completion_tokens": 100, "total_tokens": 130})
    f = await _max_output(_ctx(knowledge_base, reply))
    assert (f.outcome, f.status, f.severity, f.score) == ("clamped", Status.FAIL, Severity.MEDIUM, 0.0)
    assert f.evidence["requested_max_tokens"] == 2048
    assert f.evidence["delivered_tokens"] == 100
    assert f.evidence["delivered_source"] == "reported completion tokens"
    assert "100 of the requested 2048" in f.summary
    assert f.recommendation


async def test_clamp_without_usage_is_judged_by_the_text(knowledge_base):
    f = await _max_output(_ctx(knowledge_base, _length(_numbers(10))))
    assert f.outcome == "clamped"
    assert (f.evidence["delivered_tokens"], f.evidence["delivered_source"]) == (10, "text estimate")


@pytest.mark.parametrize("usage", [None, {"completion_tokens": 2000}], ids=["estimate", "reported"])
async def test_answer_to_the_cap_passes(knowledge_base, usage):
    f = await _max_output(_ctx(knowledge_base, _length(_numbers(2000), usage)))
    assert (f.outcome, f.status, f.score) == ("to_cap", Status.PASS, 100.0)
    assert f.evidence["delivered_tokens"] >= TO_CAP_SHARE * 2048


async def test_threshold_is_eighty_percent_of_the_cap(knowledge_base):
    below = await _max_output(_ctx(knowledge_base, _length("x", {"completion_tokens": 1638})))
    at = await _max_output(_ctx(knowledge_base, _length("x", {"completion_tokens": 1639})))
    assert (below.outcome, at.outcome) == ("clamped", "to_cap")


@pytest.mark.parametrize(
    "usage",
    [
        # completion_tokens includes the reasoning tokens (OpenAI)
        {"completion_tokens": 2048, "completion_tokens_details": {"reasoning_tokens": 2048}},
        # a relay reporting the reasoning apart from the visible output
        {"completion_tokens": 0, "completion_tokens_details": {"reasoning_tokens": 2040}},
        {"output_tokens": 3, "output_tokens_details": {"reasoning_tokens": 2045}},
    ],
)
async def test_reasoning_model_thinking_to_the_cap_passes(knowledge_base, usage):
    # Empty content, the whole budget spent thinking: reported reasoning tokens
    # make it a reasoning model even without the profile saying so.
    f = await _max_output(_ctx(knowledge_base, _length("", usage)))
    assert f.outcome == "to_cap"
    assert f.evidence["reasoning_tokens"] >= 2040


async def test_reasoning_profile_without_usage_is_not_called_clamped(knowledge_base):
    f = await _max_output(_ctx(knowledge_base, _length(""), reasoning=True))
    assert f.outcome == "to_cap"
    assert f.evidence["delivered_tokens"] is None
    assert f.evidence["delivered_source"].startswith("not countable")


async def test_reasoning_profile_still_catches_a_clamp(knowledge_base):
    reply = _length("1\n2", {"completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": 90}})
    f = await _max_output(_ctx(knowledge_base, reply, reasoning=True))
    assert f.outcome == "clamped"


async def test_usage_text_mismatch_is_noted(knowledge_base):
    # 2000 reported tokens for a three-number answer: still to_cap (the
    # reported count decides; billing judges the count), but noted.
    f = await _max_output(_ctx(knowledge_base, _length(_numbers(3), {"completion_tokens": 2000})))
    assert f.outcome == "to_cap"
    assert f.evidence["usage_text_mismatch"] == pytest.approx(666.7)
    agree = await _max_output(_ctx(knowledge_base, _length(_numbers(2000), {"completion_tokens": 2100})))
    assert "usage_text_mismatch" not in agree.evidence


async def test_mismatch_is_not_noted_for_a_reasoning_model(knowledge_base):
    reply = _length(_numbers(3), {"completion_tokens": 2000})
    f = await _max_output(_ctx(knowledge_base, reply, reasoning=True))
    assert "usage_text_mismatch" not in f.evidence


async def test_stopped_answers_keep_their_outcomes(knowledge_base):
    reply = CompletionOutcome(ok=True, status_code=200, content=_numbers(10), finish_reason="stop")
    f = await _max_output(_ctx(knowledge_base, reply))
    assert f.outcome == "far_below"
    assert "delivered_tokens" not in f.evidence


@pytest.mark.parametrize(("option", "requested"), [(None, 2048), (8192, 8192), (100_000, 16384), (512, 512)])
async def test_probe_size_follows_the_option(knowledge_base, option, requested):
    # gpt-4o declares 16384 output tokens: the probe asks min(declared, option).
    opts = {} if option is None else {"max_output_probe_tokens": option}
    ctx = _ctx(knowledge_base, _length("", {"completion_tokens": requested}), **opts)
    f = await _max_output(ctx)
    assert f.evidence["requested_max_tokens"] == requested
    assert ctx.client.specs[-1].max_tokens == requested
    assert f.outcome == "to_cap"
    assert f"capped at {option or 2048} tokens" in f.evidence["note"]


def test_option_from_cli_and_config_file():
    assert _build_options({}).max_output_probe_tokens == 2048
    assert _build_options({"run": {"max_output_probe_tokens": 4096}}).max_output_probe_tokens == 4096
    cfg = {"run": {"max_output_probe_tokens": 4096}}
    assert _build_options(cfg, max_output_probe_tokens=8192).max_output_probe_tokens == 8192
