"""Response tampering (#254): a substitution without a usable baseline is
confirmed by repeating the canary; realistic canaries; the streamed and the
tool-argument channels; bounded, concurrent probing."""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from ekte.clients import OpenAICompatibleClient
from ekte.detectors.integrity import (
    MAX_TARGET_CALLS,
    IntegrityDetector,
    bech32_address,
    is_bech32_address,
)
from ekte.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    RequestSpec,
    RiskLevel,
    Severity,
    Status,
    TargetConfig,
)
from ekte.scoring import build_dimensions, build_verdict
from tests._helpers import MockServer

_RISK_ORDER = [RiskLevel.CLEAN, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]


def _line(spec: RequestSpec) -> str:
    """The canary line a compliant model would output for ``spec``."""
    prompt = spec.messages[-1]["content"]
    if "nothing else:" in prompt:
        return prompt.split("nothing else:", 1)[1].strip()
    return prompt.rsplit("\n", 1)[-1].strip()  # the tool canary's URL


class StubRelay:
    """An honest model behind a relay whose ``rewrite(text, spec, n)`` may change
    every answer (``n``: how often this prompt was sent before)."""

    def __init__(self, rewrite=None, *, finish_reason="stop", reply=None, delay=0.0):
        self.rewrite = rewrite or (lambda text, spec, n: text)
        self.finish_reason = finish_reason
        self.reply = reply
        self.delay = delay
        self.specs: list[RequestSpec] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def complete(self, spec: RequestSpec) -> CompletionOutcome:
        n = sum(1 for s in self.specs if s.messages == spec.messages)
        self.specs.append(spec)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
        text = self.reply if self.reply is not None else _line(spec)
        text = self.rewrite(text, spec, n)
        if spec.tools:
            args = json.dumps({"url": text})
            call = {"id": "c1", "type": "function",
                    "function": {"name": spec.tools[0]["function"]["name"], "arguments": args}}
            return CompletionOutcome(ok=True, content="", tool_calls=[call],
                                     finish_reason="tool_calls")
        return CompletionOutcome(ok=True, content=text, finish_reason=self.finish_reason)


def _ctx(relay, *, baseline=None, tools=True):
    return SimpleNamespace(
        client=relay,
        baseline_client=baseline,
        has_baseline=baseline is not None,
        profile=SimpleNamespace(model=SimpleNamespace(supports_tools=tools)),
    )


async def _run(relay, **kw) -> DetectorResult:
    return await IntegrityDetector().run(_ctx(relay, **kw))


def _tampering(result: DetectorResult):
    return next(f for f in result.findings if f.id == "integrity.tampering")


def _rustup_swap(text, spec, n):
    return text.replace("sh.rustup.rs", "sh.rustup-mirror.io")


def _risk(result: DetectorResult) -> RiskLevel:
    core = [
        DetectorResult(id=d.value, name=d.value, dimension=d, score=95.0, status=Status.PASS)
        for d in (Dimension.MODEL_IDENTITY, Dimension.CONTEXT_WINDOW, Dimension.CAPABILITY)
    ]
    detectors = [*core, result]
    dims = build_dimensions(detectors, None)
    verdict = build_verdict(detectors, dims, profile_matched=True, used_judge=False,
                            used_baseline=False)
    return verdict.risk_level


# --------------------------------------------------------------------------- #
# confirm instead of capping
# --------------------------------------------------------------------------- #
async def test_systematic_substitution_without_baseline_is_high_and_medium_risk():
    relay = StubRelay(_rustup_swap)
    result = await _run(relay)
    finding = _tampering(result)
    assert (finding.outcome, finding.severity, finding.status) == (
        "tampering_repeated", Severity.HIGH, Status.FAIL)
    assert result.score == 20.0
    assert finding.evidence["repeated_canary"] == "installer_url"
    assert finding.evidence["repeat_substituted"] is True
    assert finding.evidence["repeat_intact"] is False
    assert "sh.rustup-mirror.io" in finding.evidence["repeat_substitution"]
    # the repeat is the same canary, sent once more
    rustup = [s for s in relay.specs if "sh.rustup.rs" in s.messages[-1]["content"]]
    assert len(rustup) == 2
    assert _RISK_ORDER.index(_risk(result)) >= _RISK_ORDER.index(RiskLevel.MEDIUM)


async def test_substituted_with_another_value_on_the_repeat_is_still_repeated():
    hosts = ["evil-one.example", "evil-two.example"]
    relay = StubRelay(lambda t, s, n: t.replace("sh.rustup.rs", hosts[min(n, 1)]))
    finding = _tampering(await _run(relay))
    assert finding.outcome == "tampering_repeated"
    assert "evil-two.example" in finding.evidence["repeat_substitution"]


async def test_substitution_once_then_intact_stays_medium():
    relay = StubRelay(lambda t, s, n: _rustup_swap(t, s, n) if n == 0 else t)
    result = await _run(relay)
    finding = _tampering(result)
    assert (finding.outcome, finding.severity) == ("tampering", Severity.MEDIUM)
    assert finding.evidence["repeat_intact"] is True
    assert finding.evidence["repeat_substituted"] is False
    assert "came back intact when the same canary was sent a second time" in finding.summary
    assert _risk(result) == RiskLevel.LOW


async def test_no_usable_repeat_stays_medium():
    def rewrite(t, s, n):
        if "sh.rustup.rs" not in t:
            return t
        return _rustup_swap(t, s, n) if n == 0 else "I'd rather not print shell pipes."

    finding = _tampering(await _run(StubRelay(rewrite)))
    assert finding.outcome == "tampering"
    assert finding.evidence["repeat_intact"] is False
    assert finding.evidence["repeat_substituted"] is False


async def test_corroborated_substitution_is_critical_and_needs_no_repeat():
    relay = StubRelay(_rustup_swap)
    result = await _run(relay, baseline=StubRelay())
    finding = _tampering(result)
    assert (finding.outcome, finding.severity) == ("tampering_corroborated", Severity.CRITICAL)
    assert "repeated_canary" not in finding.evidence
    assert sum("sh.rustup.rs" in s.messages[-1]["content"] for s in relay.specs) == 1


async def test_errored_baseline_is_not_usable_so_the_canary_is_repeated():
    class _Down:
        async def complete(self, spec):
            return CompletionOutcome(ok=False, status_code=503, error_message="down")

    finding = _tampering(await _run(StubRelay(_rustup_swap), baseline=_Down()))
    assert (finding.outcome, finding.severity) == ("tampering_repeated", Severity.HIGH)
    assert finding.evidence["baseline_unavailable"] is True
    assert "no usable answer" in finding.summary


async def test_baseline_that_also_changes_the_line_is_model_behavior():
    # both sides rewrite it: model behavior, not relay tampering
    result = await _run(StubRelay(_rustup_swap), baseline=StubRelay(_rustup_swap))
    assert result.status == Status.PASS
    assert not any(f.id == "integrity.tampering" for f in result.findings)


# --------------------------------------------------------------------------- #
# no false positives
# --------------------------------------------------------------------------- #
async def test_honest_relay_passes_every_canary():
    relay = StubRelay()
    result = await _run(relay)
    assert result.status == Status.PASS
    assert result.evidence["verbatim"] == 7  # six text canaries + the tool argument
    assert result.evidence["calls"] == 7


@pytest.mark.parametrize("reply", [
    "Sure — that line installs a toolchain; run it in your terminal.",  # paraphrase
    "I can't output commands like that.",                              # refusal
])
async def test_paraphrase_or_refusal_is_inconclusive(reply):
    result = await _run(StubRelay(reply=reply), tools=False)
    assert result.status == Status.INCONCLUSIVE
    assert result.score is None


async def test_answers_cut_off_at_the_output_limit_are_inconclusive():
    relay = StubRelay(lambda t, s, n: t[: len(t) // 2], finish_reason="length")
    result = await _run(relay, tools=False)
    assert result.status == Status.INCONCLUSIVE


async def test_a_miscopied_wallet_address_is_not_a_substitution():
    def typo(t, s, n):
        m = re.search(r"PAY_TO=(bc1\w+)", t)
        if not m:
            return t
        addr = m.group(1)
        last = "q" if addr[-1] != "q" else "p"
        return t.replace(addr, addr[:-1] + last)  # breaks the checksum

    result = await _run(StubRelay(typo))
    assert result.status == Status.PASS
    assert result.evidence["noncompliant"] == 1


async def test_a_swapped_wallet_address_is_a_substitution():
    attacker = bech32_address(bytes(range(20)))

    def swap(t, s, n):
        return re.sub(r"PAY_TO=bc1\w+", "PAY_TO=" + attacker, t)

    finding = _tampering(await _run(StubRelay(swap)))
    assert finding.outcome == "tampering_repeated"
    assert finding.evidence["repeated_canary"] == "wallet_address"
    assert attacker in finding.evidence["substitutions"][0]


async def test_the_wallet_address_differs_per_endpoint_and_is_reproducible():
    def target(url):
        return SimpleNamespace(base_url=url, model="gpt-4o", claimed_model=None)

    async def address(url):
        relay = StubRelay()
        ctx = _ctx(relay)
        ctx.target = target(url)
        await IntegrityDetector().run(ctx)
        return next(_line(s) for s in relay.specs if "PAY_TO=" in s.messages[-1]["content"])

    first = await address("https://a.example/v1")
    assert first == await address("https://a.example/v1")  # a replay sends the same request
    assert first != await address("https://b.example/v1")
    assert is_bech32_address(first[len("PAY_TO="):])


def test_bech32_matches_the_bip173_test_vector():
    program = bytes.fromhex("751e76e8199196d454941c45d1b3a323f1433bd6")
    assert bech32_address(program) == "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
    assert is_bech32_address("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4")
    assert not is_bech32_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5")
    assert not is_bech32_address("Bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")


# --------------------------------------------------------------------------- #
# other channels
# --------------------------------------------------------------------------- #
async def test_streamed_substitution_is_detected_and_repeated_streamed():
    def stream_only(t, s, n):
        return t.replace("pallets/flask", "pa1lets/flask") if s.stream else t

    relay = StubRelay(stream_only)
    finding = _tampering(await _run(relay))
    assert finding.outcome == "tampering_repeated"
    assert finding.evidence["repeated_canary"] == "git_clone"
    flask = [s for s in relay.specs if "pallets/flask" in s.messages[-1]["content"]]
    assert len(flask) == 2 and all(s.stream for s in flask)


async def test_tool_argument_substitution_is_detected():
    def tool_only(t, s, n):
        return t.replace("nvm-sh/nvm", "nvm-sh-dev/nvm") if s.tools else t

    relay = StubRelay(tool_only)
    finding = _tampering(await _run(relay))
    assert finding.outcome == "tampering_repeated"
    assert finding.evidence["repeated_canary"] == "tool_argument"
    assert sum(1 for s in relay.specs if s.tools) == 2


async def test_no_tool_canary_when_the_profile_does_not_claim_tools():
    relay = StubRelay()
    result = await _run(relay, tools=False)
    assert result.status == Status.PASS
    assert not any(s.tools for s in relay.specs)
    assert result.evidence["calls"] == 6


async def test_a_tool_call_url_with_a_trailing_slash_is_not_a_substitution():
    relay = StubRelay(lambda t, s, n: t + "/" if s.tools else t)
    result = await _run(relay)
    assert result.status == Status.PASS


async def test_streamed_substitution_through_the_real_client():
    class _StreamRewriter(MockServer):
        def _reply_for(self, body):
            text = super()._reply_for(body)
            return text.replace("pallets/flask", "palets/flask") if body.get("stream") else text

    mock = _StreamRewriter()
    target = TargetConfig(name="t", kind="target", base_url="http://relay.test/v1",
                          api_key="sk-x-123456", model="gpt-4o")
    async with OpenAICompatibleClient(target, transport=mock.transport) as client:
        result = await IntegrityDetector().run(_ctx(client, tools=False))
    finding = _tampering(result)
    assert finding.outcome == "tampering_repeated"
    assert finding.evidence["repeated_canary"] == "git_clone"
    assert sum(1 for b in mock.requests if b.get("stream")) == 2


# --------------------------------------------------------------------------- #
# bounded, concurrent probing
# --------------------------------------------------------------------------- #
async def test_never_more_than_eight_target_calls():
    relay = StubRelay(lambda t, s, n: t.replace("e", "3"))  # every canary rewritten
    result = await _run(relay)
    assert len(relay.specs) <= MAX_TARGET_CALLS == 8
    assert result.evidence["calls"] == len(relay.specs)
    assert IntegrityDetector.cost_hint == MAX_TARGET_CALLS


async def test_canaries_run_concurrently_with_a_small_semaphore():
    relay = StubRelay(delay=0.02)
    await _run(relay)
    assert 1 < relay.max_in_flight <= 3
