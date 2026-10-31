"""Request parameters a model refuses.

Reasoning models refuse ``max_tokens`` (they take ``max_completion_tokens``) and
sampling parameters such as ``temperature``. A client told by the profile
(``unsupported_params``) builds requests without them; an unprofiled endpoint
that names a refused parameter in a 4xx gets the request once more, adapted, and
every later request goes out adapted from the start. ``exact_params`` probes are
sent as they are.
"""

from __future__ import annotations

import json

import httpx
from test_anthropic import AnthropicMock
from test_responses import ResponsesMock

from ekte.clients import AnthropicClient, OpenAICompatibleClient, ResponsesClient
from ekte.clients.base import rejected_params
from ekte.models import CompletionOutcome, RequestSpec, TargetConfig
from ekte.perf.recorder import RequestRecorder
from ekte.perf.summary import summarize_endpoint
from tests._helpers import BASE_URL

_MAX_TOKENS = (
    "Unsupported parameter: 'max_tokens' is not supported with this model. "
    "Use 'max_completion_tokens' instead."
)
_TEMPERATURE = (
    "Unsupported value: 'temperature' does not support 0.0 with this model. "
    "Only the default (1) value is supported."
)


class ReasoningEndpoint:
    """Answers like an official reasoning model on Chat Completions: 400 for
    ``max_tokens`` and for a non-default ``temperature``."""

    def __init__(self, *, knows_completion_tokens: bool = True) -> None:
        self.knows_completion_tokens = knows_completion_tokens
        self.bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.knows_completion_tokens:
            if "max_tokens" in body:
                return self._reject(_MAX_TOKENS, "max_tokens")
        elif "max_completion_tokens" in body:
            return self._reject("Unknown parameter: 'max_completion_tokens'.",
                                "max_completion_tokens")
        if body.get("temperature") not in (None, 1):
            return self._reject(_TEMPERATURE, "temperature")
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Paris"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })

    @staticmethod
    def _reject(message: str, param: str) -> httpx.Response:
        return httpx.Response(400, json={"error": {
            "message": message, "type": "invalid_request_error", "param": param,
            "code": "unsupported_parameter",
        }})

    def client(self, recorder: RequestRecorder | None = None) -> OpenAICompatibleClient:
        cfg = TargetConfig(base_url=BASE_URL, api_key="sk-x", model="m")
        client = OpenAICompatibleClient(cfg, transport=httpx.MockTransport(self.handler))
        client.recorder, client.endpoint = recorder, "target"
        return client


def _spec(**kw) -> RequestSpec:
    return RequestSpec(messages=[{"role": "user", "content": "Capital of France?"}], **kw)


# -- a profile that lists the refused parameters --------------------------- #
def test_profiled_reasoning_model_gets_its_own_parameters():
    client = ReasoningEndpoint().client()
    client.unsupported_params = {"max_tokens", "temperature", "top_p"}
    body = client._build_body(_spec(max_tokens=32, temperature=0.0, top_p=0.5, seed=1))
    assert body["max_completion_tokens"] == 32
    assert "max_tokens" not in body and "temperature" not in body and "top_p" not in body
    assert body["seed"] == 1  # not a refused parameter


def test_a_limit_set_by_the_request_is_not_sent_twice():
    client = ReasoningEndpoint().client()
    client.unsupported_params = {"max_tokens"}
    body = client._build_body(_spec(max_tokens=16, extra_body={"max_completion_tokens": 256}))
    assert body["max_completion_tokens"] == 256 and "max_tokens" not in body
    # Without the profile constraint the request is built as before.
    plain = ReasoningEndpoint().client()._build_body(_spec(extra_body={"max_completion_tokens": 8}))
    assert plain["max_completion_tokens"] == 8 and "max_tokens" not in plain


async def test_profiled_requests_need_no_retry():
    server = ReasoningEndpoint()
    client = server.client()
    client.unsupported_params = {"max_tokens", "temperature"}
    out = await client.complete(_spec(max_tokens=32))
    assert out.ok and len(server.bodies) == 1


# -- an unprofiled endpoint ------------------------------------------------- #
async def test_unprofiled_endpoint_is_adapted_once_and_it_sticks():
    server = ReasoningEndpoint()
    rec = RequestRecorder()
    client = server.client(rec)
    out = await client.complete(_spec(max_tokens=32))  # temperature=0.0 by default
    assert out.ok and out.content == "Paris"
    # max_tokens rejected, then temperature rejected, then accepted.
    assert len(server.bodies) == 3
    assert client.unsupported_params == {"max_tokens", "temperature"}
    assert [r.phase for r in rec.records] == ["param_retry", "param_retry", "passive"]
    assert summarize_endpoint(rec.records).errors == 0

    out = await client.complete(_spec(max_tokens=32, stream=False))
    assert out.ok and len(server.bodies) == 4  # adapted from the start
    assert server.bodies[-1]["max_completion_tokens"] == 32
    assert "temperature" not in server.bodies[-1]


async def test_concurrent_rejections_all_retry():
    import asyncio

    server = ReasoningEndpoint()
    client = server.client()
    client.unsupported_params = {"temperature"}
    outs = await asyncio.gather(*(client.complete(_spec(max_tokens=8)) for _ in range(4)))
    assert all(o.ok for o in outs)


async def test_renamed_limit_falls_back_when_the_endpoint_only_knows_max_tokens():
    server = ReasoningEndpoint(knows_completion_tokens=False)
    client = server.client()
    client.unsupported_params = {"max_tokens", "temperature"}  # profile says so
    out = await client.complete(_spec(max_tokens=32))
    assert out.ok
    assert server.bodies[-1]["max_tokens"] == 32
    assert "max_completion_tokens" not in server.bodies[-1]
    # And it stays that way.
    await client.complete(_spec(max_tokens=32))
    assert len(server.bodies) == 3


async def test_exact_params_sends_the_request_as_specified():
    server = ReasoningEndpoint()
    client = server.client()
    client.unsupported_params = {"max_tokens", "temperature"}
    out = await client.complete(_spec(max_tokens=16, exact_params=True))
    assert not out.ok and out.status_code == 400
    assert len(server.bodies) == 1
    assert server.bodies[0]["max_tokens"] == 16 and server.bodies[0]["temperature"] == 0.0
    assert "exact_params" not in server.bodies[0]


async def test_other_errors_are_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {
            "message": "This model's maximum context length is 8192 tokens; "
                       "reduce the length of the messages or max_tokens."}})

    calls: list[int] = []

    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return handler(request)

    cfg = TargetConfig(base_url=BASE_URL, api_key="sk-x", model="m")
    client = OpenAICompatibleClient(cfg, transport=httpx.MockTransport(counting))
    out = await client.complete(_spec(max_tokens=16))
    assert not out.ok and len(calls) == 1 and not client.unsupported_params


def test_rejected_params_needs_a_named_parameter_and_a_rejection():
    def bad(status: int, message: str, param: str | None = None) -> CompletionOutcome:
        raw = {"error": {"message": message, "param": param}} if param else None
        return CompletionOutcome(ok=False, status_code=status, error_message=message,
                                 raw_error=raw)

    sent = {"max_tokens", "temperature"}
    assert rejected_params(bad(400, _MAX_TOKENS), sent) == {"max_tokens"}
    assert rejected_params(bad(400, _TEMPERATURE), sent) == {"temperature"}
    # The name inside "max_completion_tokens" is not "max_tokens".
    assert rejected_params(bad(400, "Use 'max_completion_tokens' instead."), sent) == set()
    assert rejected_params(bad(401, _MAX_TOKENS), sent) == set()
    assert rejected_params(bad(500, _MAX_TOKENS), sent) == set()
    assert rejected_params(bad(400, "max_tokens is too large: 99999"), sent) == set()
    assert rejected_params(bad(400, "Unsupported value.", "temperature"), sent) == {"temperature"}
    assert rejected_params(bad(400, _TEMPERATURE), {"max_tokens"}) == set()  # not sent
    # A message echoing the request does not condemn every field it mentions.
    echo = "'tools' is not supported by this deployment. Request was: {\"temperature\": 0, \"max_tokens\": 16}"
    assert rejected_params(bad(400, echo), sent) == set()
    # A server-named field is trusted alone.
    assert rejected_params(bad(400, _MAX_TOKENS, "tools"), sent) == set()


# -- the other wire protocols ----------------------------------------------- #
async def test_anthropic_client_drops_refused_sampling_parameters():
    mock = AnthropicMock()
    async with AnthropicClient(
        TargetConfig(base_url="https://api.anthropic.test/v1", api_key="k", model="claude-x"),
        transport=mock.transport,
    ) as c:
        c.unsupported_params = {"temperature", "top_p", "top_k"}
        out = await c.complete(_spec(max_tokens=16, top_p=0.9, extra_body={"top_k": 5}))
    assert out.ok
    body = mock.requests[0]
    assert body["max_tokens"] == 16
    assert not {"temperature", "top_p", "top_k"} & body.keys()


async def test_anthropic_client_adapts_to_a_rejected_temperature():
    mock = AnthropicMock()
    inner = mock._handler

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if "temperature" in body:
            mock.requests.append(body)
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error",
                "message": "temperature is not supported for this model."}})
        return inner(request)

    cfg = TargetConfig(base_url="https://api.anthropic.test/v1", api_key="k", model="claude-x")
    async with AnthropicClient(cfg, transport=httpx.MockTransport(handler)) as c:
        out = await c.complete(_spec(max_tokens=16))
        assert out.ok and c.unsupported_params == {"temperature"}
        await c.complete(_spec(max_tokens=16))
    assert len(mock.requests) == 3


async def test_responses_client_drops_refused_sampling_parameters():
    mock = ResponsesMock()
    async with ResponsesClient(
        TargetConfig(base_url="https://api.openai.test/v1", api_key="k", model="m"),
        transport=mock.transport,
    ) as c:
        c.unsupported_params = {"max_tokens", "temperature", "top_p"}
        out = await c.complete(_spec(max_tokens=16, top_p=0.5))
    assert out.ok
    body = mock.requests[0]
    assert body["max_output_tokens"] == 16  # Responses' own limit field, unchanged
    assert "temperature" not in body and "top_p" not in body


# -- the runner hands the profile's constraints to the clients -------------- #
async def test_runner_sets_unsupported_params_from_each_profile(monkeypatch, tmp_path):
    from ekte.clients import make_client as real
    from ekte.config import AuditOptions
    from ekte.runner import run_audit
    from tests._helpers import MockServer

    (tmp_path / "thinker.yaml").write_text(
        "provider: acme\n"
        "models:\n"
        "  - id: thinker-1\n"
        "    family: thinker\n"
        "    reasoning: true\n"
        "    unsupported_params: [max_tokens, temperature]\n"
    )
    clients: list = []

    def factory(config, **_):
        client = real(config, transport=MockServer().transport)
        clients.append(client)
        return client

    monkeypatch.setattr("ekte.runner.make_client", factory)
    await run_audit(
        TargetConfig(name="t", kind="target", base_url=BASE_URL, model="thinker-1"),
        AuditOptions(suite="custom", dimensions=["connectivity"]),
        baseline=TargetConfig(name="b", kind="baseline", base_url=BASE_URL, model="plain-model"),
        kb_dirs=[tmp_path],
        use_user_kb=False,
    )
    target, baseline = clients
    assert {"max_tokens", "temperature"} <= target.unsupported_params
    assert not baseline.unsupported_params


# -- protocol_request still sees the raw rejection --------------------------- #
async def test_protocol_request_classifies_a_reasoning_models_refusals_as_model_limits():
    from types import SimpleNamespace

    from ekte.detectors.protocol_attrs import ProtocolRequestDetector
    from ekte.knowledge import load_knowledge_base

    server = ReasoningEndpoint()
    inner = server.handler

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        for name in ("top_p", "presence_penalty", "frequency_penalty", "logprobs"):
            if name in body:
                server.bodies.append(body)
                return server._reject(f"Unsupported parameter: '{name}' is not supported "
                                      "with this model.", name)
        return inner(request)

    profile = load_knowledge_base(include_user=False).resolve("o3", None)
    assert profile is not None
    target = TargetConfig(base_url=BASE_URL, api_key="sk-x", model="o3")
    client = OpenAICompatibleClient(target, transport=httpx.MockTransport(handler))
    client.unsupported_params = set(profile.model.unsupported_params)
    learned = set(client.unsupported_params)
    ctx = SimpleNamespace(target=target, client=client, profile=profile,
                          baseline=None, baseline_client=None)
    result = await ProtocolRequestDetector().run(ctx)  # type: ignore[arg-type]
    keys = result.evidence["attributes"]
    assert keys["temperature"] == keys["top_p"] == keys["logprobs"] == "model_limit"
    assert client.unsupported_params == learned  # exact probes teach the client nothing
