"""Identity fingerprints that cannot fit the identity output cap.

The identity check caps every fingerprint probe at
``ModelIdentityDetector.MAX_FINGERPRINT_OUTPUT`` tokens. A probe whose expected
answer needs more (a count-to-4000 max-output check) would diverge on every
genuine model, so it is skipped and reported as not run instead.
"""

from __future__ import annotations

import json

import httpx
import pytest

from zing.clients import OpenAICompatibleClient
from zing.config import AuditOptions
from zing.context import AuditContext
from zing.detectors.model_identity import ModelIdentityDetector
from zing.knowledge.schema import (
    FingerprintProbe,
    KnowledgeBase,
    ModelProfile,
    ProviderProfile,
    ResolvedProfile,
)
from zing.models import Status, TargetConfig

CAP = ModelIdentityDetector.MAX_FINGERPRINT_OUTPUT


class _FingerprintMock:
    """Answers every fingerprint with "yes" and records each request body."""

    def __init__(self, brand: str = "Acme"):
        self.brand = brand
        self.requests: list[dict] = []

    @property
    def transport(self):
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        self.requests.append(body)
        user = " ".join(m.get("content", "") for m in body["messages"]).lower()
        is_id = "what model are you" in user or "who are you" in user or "which model" in user
        text = f"I am {self.brand}." if is_id else "yes"
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    def sent(self, prompt: str) -> list[dict]:
        return [r for r in self.requests if r["messages"][0]["content"] == prompt]


def _fp(fp_id: str, prompt: str, **kw) -> FingerprintProbe:
    return FingerprintProbe(id=fp_id, signal=f"signal {fp_id}", prompt=prompt, pure_code_checkable=True, **kw)


async def _run(profile: ResolvedProfile, mock: _FingerprintMock, kb: KnowledgeBase | None = None):
    target = TargetConfig(base_url="https://relay.test/v1", api_key="sk-x-123456", model=profile.model.id)
    async with OpenAICompatibleClient(target, transport=mock.transport) as c:
        ctx = AuditContext(
            target=target, client=c, options=AuditOptions(suite="standard"),
            kb=kb or KnowledgeBase(), profile=profile,
        )
        return await ModelIdentityDetector().run(ctx)


def _acme(fingerprints: list[FingerprintProbe]) -> ResolvedProfile:
    return ResolvedProfile(
        provider=ProviderProfile(provider="acme", fingerprints=fingerprints),
        model=ModelProfile(id="acme-1", identity_keywords=["acme"]),
    )


async def test_probe_over_the_cap_is_skipped_not_diverged():
    fps = [
        _fp("count", "Count to 4000.", expect_regex=r"\b4000\b", max_tokens=20000),
        _fp("count2", "Count to 5000.", expect_regex=r"\b5000\b", max_tokens=CAP + 1),
        _fp("short", "Say yes.", expect_contains=["yes"], max_tokens=CAP),  # exactly at the cap: runs
    ]
    mock = _FingerprintMock()
    result = await _run(_acme(fps), mock)

    by_id = {f.id: f for f in result.findings}
    for fp_id in ("count", "count2"):
        f = by_id[f"model_identity.fp.{fp_id}"]
        assert f.outcome == "skipped_output_cap"
        assert f.status == Status.INFO and not f.deduction
        assert f.evidence["probe"] == fp_id
    # The skipped probes were never sent; the one within the cap was.
    assert not mock.sent("Count to 4000.") and not mock.sent("Count to 5000.")
    assert [r["max_tokens"] for r in mock.sent("Say yes.")] == [CAP]
    assert by_id["model_identity.fp.short"].outcome == "consistent"
    # Neither the aggregate, the score nor the status picks the skips up.
    assert "model_identity.fp_aggregate" not in by_id
    assert result.score == 100.0 and result.status == Status.PASS
    assert result.evidence["fingerprints_run"] == 1
    assert result.evidence["fingerprints_violated"] == 0
    assert result.evidence["fingerprints_skipped"] == ["count", "count2"]


async def test_skipped_probe_frees_its_slot_and_its_weight():
    slots = ModelIdentityDetector.MAX_FINGERPRINTS
    long_fp = _fp("long", "Count to 4000.", expect_regex=r"\b4000\b", max_tokens=20000)
    # As many within-cap probes as there are slots; the last one diverges.
    short = [_fp(f"s{i}", f"Say yes ({i}).", expect_contains=["yes"]) for i in range(slots - 1)]
    last = _fp("last", "Say no.", expect_contains=["no"])
    mock = _FingerprintMock()
    result = await _run(_acme([long_fp, *short, last]), mock)

    by_id = {f.id: f for f in result.findings}
    assert by_id["model_identity.fp.long"].outcome == "skipped_output_cap"
    # Without the skip the slice would have dropped the last probe.
    assert mock.sent("Say no.")
    diverged = by_id["model_identity.fp.last"]
    assert diverged.outcome == "diverged"
    # Its weight share counts only the probes that ran.
    assert diverged.deduction == pytest.approx(100.0 / slots)
    assert result.evidence["fingerprints_run"] == slots
    # A single divergence stays LOW: no aggregate.
    assert "model_identity.fp_aggregate" not in by_id


async def test_genuine_glm_is_not_flagged_by_its_max_output_probe(knowledge_base):
    # The packaged GLM max-output probe counts to 4000, far past the cap.
    profile = knowledge_base.resolve("glm-4.7-flash")
    assert profile is not None
    assert any(fp.id == "true-max-output" and fp.max_tokens > CAP for fp in profile.all_fingerprints())
    mock = _FingerprintMock(brand="GLM, built by Zhipu AI")
    result = await _run(profile, mock, knowledge_base)

    f = next(f for f in result.findings if f.id == "model_identity.fp.true-max-output")
    assert f.outcome == "skipped_output_cap"
    assert "true-max-output" in result.evidence["fingerprints_skipped"]
    assert all(r["max_tokens"] <= CAP for r in mock.requests)


@pytest.mark.parametrize(
    "fp,warned",
    [
        ("{id: f, signal: s, prompt: p, pure_code_checkable: true, expect_regex: x, max_tokens: 20000}", True),
        ("{id: f, signal: s, prompt: p, pure_code_checkable: true, expect_regex: x, max_tokens: 512}", False),
        # Not run by the identity check at all: no output cap applies.
        ("{id: f, signal: s, prompt: p, max_tokens: 20000}", False),
    ],
)
def test_importer_warns_about_probes_the_identity_check_skips(fp, warned):
    from zing.knowledge.importer import scan

    result = scan(f"provider: x\nmodels:\n- id: m\n  fingerprints:\n  - {fp}\n")
    assert result.ok, result.errors
    hits = [w for w in result.warnings if "identity check skips" in w["message"]]
    assert bool(hits) == warned
    if warned:
        assert hits[0]["path"].endswith(".max_tokens")
