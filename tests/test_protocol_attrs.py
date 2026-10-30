"""Protocol attribute detectors: request parameters in, response attributes out.

The catalogs and judgements (ekte/detectors/wire_attrs.py) are pure, so most of
this is table-driven: a conformant body per wire protocol, then every catalog
attribute removed or zeroed in turn. The detectors run against a scripted
``complete`` so every branch — batched accept, isolation after a rejection,
baseline comparison — is reachable without a network.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from ekte.clients import AnthropicClient, OpenAICompatibleClient, ResponsesClient
from ekte.detectors.helpers import MISSING, dig
from ekte.detectors.protocol_attrs import ProtocolRequestDetector, ProtocolResponseDetector
from ekte.detectors.wire_attrs import (
    CORE,
    MINOR,
    PARAM,
    REQUEST_SCALE,
    RESPONSE_ATTRS,
    RESPONSE_SCALE,
    assess_response,
    judge,
    request_params,
)
from ekte.models import CompletionOutcome, RequestSpec, Status, TargetConfig
from ekte.scoring import build_dimensions, build_verdict

BODIES = {
    "openai": {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1767225600, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "The quick brown fox"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    },
    "anthropic": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": "The quick brown fox"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 5},
    },
    "responses": {
        "id": "resp_1", "object": "response", "created_at": 1767225600, "model": "gpt-4o",
        "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "The quick brown fox"}]}],
        "usage": {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17},
    },
}
_API = {"openai": "openai", "anthropic": "anthropic", "responses": "responses"}


def _drop(body: dict, path: str) -> dict:
    body = copy.deepcopy(body)
    *parents, last = path.split(".")
    node = body
    for p in parents:
        node = node[int(p)] if isinstance(node, list) else node[p]
    if isinstance(node, list):
        node.pop(int(last))
    else:
        del node[last]
    return body


def _set(body: dict, path: str, value) -> dict:
    body = copy.deepcopy(body)
    *parents, last = path.split(".")
    node = body
    for p in parents:
        node = node[int(p)] if isinstance(node, list) else node[p]
    node[int(last) if isinstance(node, list) else last] = value
    return body


def _keys(protocol: str, body: dict) -> dict[str, str]:
    return {r.attr.path: r.key for r in assess_response(protocol, body)}


# --------------------------------------------------------------------------- #
# Pure judgement
# --------------------------------------------------------------------------- #
def test_dig_reads_paths_and_treats_null_as_missing():
    body = {"a": [{"b": 1}], "u": None}
    assert dig(body, "a.0.b") == 1
    assert dig(body, "a.1.b") is MISSING and dig(body, "u.x") is MISSING
    assert dig(body, "a.x") is MISSING and dig(None, "a") is MISSING


@pytest.mark.parametrize("protocol", sorted(BODIES))
def test_a_conformant_body_is_valid_throughout(protocol):
    assert set(_keys(protocol, BODIES[protocol]).values()) == {"valid"}


@pytest.mark.parametrize(("protocol", "path"), [
    (p, a.path) for p in sorted(RESPONSE_ATTRS) for a in RESPONSE_ATTRS[p]
])
def test_every_attribute_is_missed_when_absent(protocol, path):
    keys = _keys(protocol, _drop(BODIES[protocol], path))
    assert keys[path] == "missing"


@pytest.mark.parametrize(("protocol", "path"), [
    (p, a.path) for p in sorted(RESPONSE_ATTRS) for a in RESPONSE_ATTRS[p] if a.rule == "int>0"
])
def test_zero_token_counts_score_as_zero(protocol, path):
    assert _keys(protocol, _set(BODIES[protocol], path, 0))[path] == "zero"


def test_usage_null_misses_every_usage_attribute():
    keys = _keys("openai", _set(BODIES["openai"], "usage", None))
    assert [k for p, k in keys.items() if p.startswith("usage.")] == ["missing"] * 3


@pytest.mark.parametrize(("rule", "value", "key"), [
    ("str", "", "zero"), ("str", 3, "invalid"), ("=assistant", "user", "invalid"),
    ("int>0", "5", "invalid"), ("int>0", True, "invalid"), ("int>0", -1, "invalid"),
    ("int>=0", 0, "valid"), ("ts", 12, "invalid"), ("list>0", [], "zero"), ("list>0", {}, "invalid"),
])
def test_rules(rule, value, key):
    assert judge(rule, value, {}) == key


def test_total_must_be_the_sum_of_its_parts():
    body = _set(BODIES["openai"], "usage.total_tokens", 99)
    assert _keys("openai", body)["usage.total_tokens"] == "invalid"
    # a partial usage object: the sum cannot be checked, the total itself can
    body = _drop(BODIES["openai"], "usage.prompt_tokens")
    assert _keys("openai", body)["usage.total_tokens"] == "valid"


def test_the_scales_cover_every_outcome_the_judgement_can_emit():
    for check in (CORE, MINOR):
        assert set(RESPONSE_SCALE.keys(check)) == {"valid", "zero", "invalid", "missing"}
        assert check in RESPONSE_SCALE.titles
    assert set(REQUEST_SCALE.keys(PARAM)) == {
        "honored", "accepted", "ignored", "rejected", "dropped_by_relay", "model_limit", "no_response",
    }
    assert all(o.label for o in RESPONSE_SCALE.outcomes + REQUEST_SCALE.outcomes)


# --------------------------------------------------------------------------- #
# Response detector
# --------------------------------------------------------------------------- #
def _ctx(complete, *, api="openai", model="gpt-4o", profile=None, baseline=None):
    return SimpleNamespace(
        target=TargetConfig(base_url="http://relay.test/v1", model=model, api=api),
        client=SimpleNamespace(complete=complete),
        profile=profile,
        baseline=TargetConfig(base_url="http://base.test/v1", model=model, api=api) if baseline else None,
        baseline_client=SimpleNamespace(complete=baseline) if baseline else None,
    )


def _ok(body: dict | None = None, **kw) -> CompletionOutcome:
    return CompletionOutcome(ok=True, status_code=200, content="ok", raw_body=body or {}, **kw)


async def _respond(api: str, body: dict | None, outcome: CompletionOutcome | None = None):
    seen: list[RequestSpec] = []

    async def complete(spec):
        seen.append(spec)
        return outcome or _ok(body)

    result = await ProtocolResponseDetector().run(_ctx(complete, api=api))  # type: ignore[arg-type]
    return result, seen


@pytest.mark.parametrize("protocol", sorted(BODIES))
async def test_response_detector_scores_every_attribute(protocol):
    result, seen = await _respond(protocol, BODIES[protocol])
    assert len(seen) == 1 and seen[0].capture_raw and not seen[0].stream
    assert result.score == 100.0 and result.status == Status.PASS
    assert len(result.findings) == len(RESPONSE_ATTRS[protocol])
    for f in result.findings:
        o = RESPONSE_SCALE.get(f.check, f.outcome)
        assert (f.score, f.status, f.severity) == (o.score, o.status, o.severity)
        assert f.id == f"{f.check}.{f.subject}" and f.evidence["attribute"] == f.subject
    assert result.evidence["attributes"] == {a.path: "valid" for a in RESPONSE_ATTRS[protocol]}
    assert result.scoring.titles == RESPONSE_SCALE.titles


async def test_zero_completion_tokens_do_not_score_well():
    body = _set(BODIES["openai"], "usage.completion_tokens", 0)
    body["usage"]["total_tokens"] = 12
    result, _ = await _respond("openai", body)
    f = next(x for x in result.findings if x.subject == "usage.completion_tokens")
    assert (f.outcome, f.score, f.status) == ("zero", 20.0, Status.FAIL)
    assert f.evidence["observed"] == 0 and f.recommendation
    assert result.status == Status.FAIL and result.score < 95


async def test_missing_minor_attribute_costs_little():
    result, _ = await _respond("openai", _drop(BODIES["openai"], "id"))
    f = next(x for x in result.findings if x.subject == "id")
    assert (f.check, f.outcome, f.score, f.status) == (MINOR, "missing", 60.0, Status.WARN)
    assert result.score == round((11 * 100 + 60) / 12, 1)


async def test_no_body_is_inconclusive_and_not_scored():
    failed = CompletionOutcome(ok=False, status_code=502, error_message="bad gateway")
    result, _ = await _respond("openai", None, failed)
    assert [f.id for f in result.findings] == ["protocol_response.call"]
    assert result.score is None and result.status == Status.INCONCLUSIVE


# --------------------------------------------------------------------------- #
# Request detector
# --------------------------------------------------------------------------- #
def _names(spec: RequestSpec) -> set[str]:
    """Which catalog params a request carries."""
    names = set(spec.extra_body)
    if spec.temperature is not None:
        names.add("temperature")
    if spec.max_tokens != 16 and spec.max_tokens is not None:
        names.add("max_tokens")
    if any(m.get("role") == "system" for m in spec.messages):
        names.add("system")
    if "Count from 1" in json.dumps(spec.messages):
        names.add("max_tokens")
    return names


def _relay(*, reject=(), ignore=(), fail=()):
    """A scripted relay: rejects/ignores/fails requests carrying these params."""
    seen: list[RequestSpec] = []

    async def complete(spec: RequestSpec) -> CompletionOutcome:
        seen.append(spec)
        names = _names(spec)
        if names & set(fail):
            return CompletionOutcome(ok=False, status_code=503, error_message="upstream down")
        if names & set(reject):
            return CompletionOutcome(ok=False, status_code=400, error_message="unsupported parameter")
        body = {"choices": [{"index": 0}]}
        out = _ok(body, finish_reason="stop")
        if "n" in names and "n" not in ignore:
            body["choices"].append({"index": 1})
        if "logprobs" in names and "logprobs" not in ignore:
            body["choices"][0]["logprobs"] = {"content": [{"token": "ok"}]}
        if "system" in names and "system" not in ignore:
            out.content = "PINEAPPLE"
        if "max_tokens" in names and "max_tokens" not in ignore:
            out.finish_reason = "length"
        return out

    return complete, seen


async def _request(complete, **kw):
    return await ProtocolRequestDetector().run(_ctx(complete, **kw))  # type: ignore[arg-type]


async def test_a_faithful_relay_honors_every_parameter_in_few_calls():
    complete, seen = _relay()
    result = await _request(complete)
    params = request_params("openai")
    verified = [p for p in params if p.verify]
    assert len(seen) == len(verified) + 1 == result.evidence["calls"]  # accept-only ones share a call
    assert result.score == 100.0 and result.status == Status.PASS
    keys = result.evidence["attributes"]
    assert {keys[p.name] for p in verified} == {"honored"}
    assert {keys[p.name] for p in params if not p.verify} == {"accepted"}
    assert all(s.capture_raw and s.temperature in (None, 0.5) for s in seen)
    # The raw rejection is the evidence: the client must not adapt these probes.
    assert all(s.exact_params for s in seen)


async def test_a_rejected_batch_is_retried_one_by_one():
    complete, seen = _relay(reject=("seed",))
    result = await _request(complete)
    keys = result.evidence["attributes"]
    assert keys["seed"] == "rejected" and keys["top_p"] == "accepted" and keys["user"] == "accepted"
    plain = [p for p in request_params("openai") if not p.verify]
    assert len(seen) == len(request_params("openai")) - len(plain) + 1 + len(plain)
    seed = next(f for f in result.findings if f.subject == "seed")
    assert (seed.score, seed.status) == (40.0, Status.WARN) and seed.recommendation
    assert "sent_with" not in seed.evidence


async def test_an_ignored_parameter_is_flagged():
    complete, _ = _relay(ignore=("n", "logprobs"))
    result = await _request(complete)
    keys = result.evidence["attributes"]
    assert keys["n"] == keys["logprobs"] == "ignored"
    assert result.status == Status.WARN


async def test_server_errors_are_not_counted():
    complete, _ = _relay(fail=("n",))
    result = await _request(complete)
    n = next(f for f in result.findings if f.subject == "n")
    assert (n.outcome, n.score, n.status) == ("no_response", None, Status.INCONCLUSIVE)
    assert result.score == 100.0


async def test_reasoning_models_are_not_blamed_for_refusing_sampling_parameters():
    profile = SimpleNamespace(model=SimpleNamespace(reasoning=True, unsupported_params=[]))
    complete, seen = _relay(reject=("temperature", "top_p", "logprobs"))
    result = await ProtocolRequestDetector().run(
        _ctx(complete, profile=profile)  # type: ignore[arg-type]
    )
    keys = result.evidence["attributes"]
    assert keys["temperature"] == keys["top_p"] == keys["logprobs"] == "model_limit"
    assert "max_completion_tokens" in keys and "max_tokens" not in keys
    assert all(s.max_tokens is None for s in seen)
    assert result.score == 100.0


async def test_knowledge_base_lists_unsupported_parameters():
    profile = SimpleNamespace(model=SimpleNamespace(reasoning=False, unsupported_params=["seed"]))
    complete, _ = _relay(reject=("seed",))
    result = await ProtocolRequestDetector().run(_ctx(complete, profile=profile))  # type: ignore[arg-type]
    assert result.evidence["attributes"]["seed"] == "model_limit"


async def test_a_baseline_tells_a_dropping_relay_from_a_model_limit():
    complete, _ = _relay(reject=("seed", "user"))
    base, base_seen = _relay(reject=("user",))
    result = await _request(complete, baseline=base)
    keys = result.evidence["attributes"]
    assert keys["seed"] == "dropped_by_relay" and keys["user"] == "model_limit"
    assert len(base_seen) == 2  # only the rejected params go to the baseline
    seed = next(f for f in result.findings if f.subject == "seed")
    assert (seed.score, seed.status) == (15.0, Status.FAIL)


@pytest.mark.parametrize("api", ["anthropic", "responses"])
async def test_other_protocols_use_their_own_catalog(api):
    complete, _ = _relay()
    result = await _request(complete, api=api, model="claude-sonnet-5")
    assert list(result.evidence["attributes"]) == [p.name for p in request_params(api)]
    assert result.score == 100.0


# --------------------------------------------------------------------------- #
# Folding in the verdict and dimension reason
# --------------------------------------------------------------------------- #
async def test_many_missing_attributes_take_one_key_finding():
    body = _set(BODIES["openai"], "usage", None)
    result, _ = await _respond("openai", body)
    dims = build_dimensions([result], None)
    verdict = build_verdict([result], dims, profile_matched=True, used_judge=False, used_baseline=False)
    assert verdict.key_findings == ["Response attribute usage.prompt_tokens (+2 more)"]
    protocol = next(d for d in dims if d.dimension.value == "protocol")
    assert protocol.reason == "Response attribute usage.prompt_tokens (+2 more)"


# --------------------------------------------------------------------------- #
# Clients: the raw body is kept only on request, redacted, never sent
# --------------------------------------------------------------------------- #
_SECRET = "sk-test-secret-key-do-not-leak"


def _transport(body: dict, sent: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(("cls", "api"), [
    (OpenAICompatibleClient, "openai"), (AnthropicClient, "anthropic"), (ResponsesClient, "responses"),
])
async def test_clients_capture_the_raw_body_on_request(cls, api):
    body = copy.deepcopy(BODIES[api])
    body["echo"] = f"key {_SECRET}"
    sent: list[dict] = []
    config = TargetConfig(base_url="http://relay.test/v1", model="m", api_key=_SECRET, api=api)
    async with cls(config, transport=_transport(body, sent)) as client:
        plain = await client.complete(RequestSpec(messages=[{"role": "user", "content": "hi"}]))
        raw = await client.complete(
            RequestSpec(messages=[{"role": "user", "content": "hi"}], capture_raw=True)
        )
    assert plain.raw_body is None
    assert raw.raw_body is not None and raw.raw_body["id"] == body["id"]
    assert _SECRET not in json.dumps(raw.raw_body)
    assert all("capture_raw" not in s for s in sent)
