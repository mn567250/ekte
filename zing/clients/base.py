"""Shared HTTP machinery for relay clients.

Both the OpenAI-compatible and Anthropic-native clients speak raw HTTP (not an
official SDK) so the detectors can reason about the raw evidence — status codes,
headers, partial streams, per-chunk timing. The transport lifecycle, timeout,
secret redaction, and error shaping are identical across protocols and live here;
subclasses only supply the auth headers and the protocol-specific request/response
translation.
"""

from __future__ import annotations

import asyncio
import re
import ssl
import threading
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

import httpx

from zing.models import CompletionOutcome, RequestRecord, RequestSpec, TargetConfig
from zing.perf.recorder import (
    RequestRecorder,
    current_net_trace,
    net_trace_scope,
    usage_tokens,
)
from zing.utils.net import is_local_host
from zing.utils.redact import redact_json, redact_text

# One TLS context for every relay client in the process. httpx builds a new
# one per AsyncClient (and one more per proxy mount): loading the CA bundle
# costs ~20-30 ms each, on the event loop the audits time their chunks on.
# It is created once, with httpx's own defaults (verification on, CA bundle
# from SSL_CERT_FILE / SSL_CERT_DIR or certifi), off the loop; an
# SSLContext is safe to share between connections and threads. Changing
# those variables later in the process does not affect it.
_SSL_CONTEXT: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()

# Per-completion timeout budget. A fixed timeout fails slow endpoints on large
# requests: a non-streaming call sends nothing until prefill and decode are both
# done, and a self-hosted model can need minutes to read a long prompt. Each
# completion therefore gets ``timeout_sec`` plus time for its prompt and output at
# deliberately low throughputs, and never more than ``max_request_sec``.
_PREFILL_TPS = 100.0
_DECODE_TPS = 10.0
# Local or private hosts (llama.cpp, Ollama, vLLM on modest hardware).
_LOCAL_PREFILL_TPS = 30.0
_LOCAL_DECODE_TPS = 3.0
_LOCAL_MIN_BASE_SEC = 300.0
# Output budget assumed when a request sets no max_tokens.
_DEFAULT_OUTPUT_TOKENS = 1024
# Output budget of the one repeat a reasoning model gets when a short request
# ran out of tokens while thinking (see complete()). Requests that already ask
# for this much are never repeated.
REASONING_RETRY_TOKENS = 4096
# Sampling parameters the client leaves out of a request once the endpoint's
# model is known not to take them (its profile's ``unsupported_params``, or a 4xx
# that named one). Reasoning models refuse e.g. ``temperature`` other than 1.
SAMPLING_PARAMS = frozenset(
    {"temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty"}
)
# Phrases of a 4xx that rejects a request PARAMETER (not the prompt or the key).
# The parameter itself must also be named in the error for the client to adapt.
_PARAM_REJECTION_PHRASES = (
    "unsupported parameter",
    "unsupported value",
    "unknown parameter",
    "unrecognized request argument",
    "is not supported",
    "not supported with this model",
    "does not support",
    "only the default",
    "extra inputs are not permitted",
    "is deprecated",
    "use 'max_completion_tokens'",
)
# How far (characters) from a rejection phrase the refused name may stand.
_NAME_REACH = 24
# Repeats of one request for refused parameters, at most (one per parameter,
# e.g. max_tokens and then temperature on an unprofiled reasoning model).
_MAX_PARAM_RETRIES = 3
# Statuses that never mean a parameter was refused.
_NOT_PARAM_STATUSES = frozenset({401, 403, 404, 408, 409, 413, 429})
# The httpx timeout of the completion running in this task (see complete()).
_CALL_TIMEOUT: ContextVar[httpx.Timeout | None] = ContextVar("zing_call_timeout", default=None)


def _prompt_tokens(messages: list[dict[str, Any]]) -> int:
    """A generous prompt-size estimate (~2 characters per token) for the timeout
    budget. Counting characters keeps a 200k-token prompt off the event loop's
    clock; CJK text (~1 token per character) is covered by the low throughputs."""
    chars = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
    return chars // 2


def _output_tokens(spec: RequestSpec) -> int:
    """The output budget a request asks for (or the default when it sets none)."""
    for value in (
        spec.max_tokens,
        spec.extra_body.get("max_completion_tokens"),
        spec.extra_body.get("max_output_tokens"),
    ):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return _DEFAULT_OUTPUT_TOKENS


def _budget_field(spec: RequestSpec) -> tuple[str, int] | None:
    """The output-limit field a request sets explicitly, and its value."""
    if isinstance(spec.max_tokens, int) and spec.max_tokens > 0:
        return "max_tokens", spec.max_tokens
    for name in ("max_completion_tokens", "max_output_tokens"):
        value = spec.extra_body.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return name, value
    return None


def reasoning_retry_spec(spec: RequestSpec, outcome: CompletionOutcome) -> RequestSpec | None:
    """The request to repeat when a reasoning model spent a short output budget
    on hidden thinking, else None.

    Short probes ask for a few dozen tokens; a reasoning model can think through
    all of them and return an empty answer (or one cut off mid-way) with
    ``finish_reason=length``. That is the probe's budget running out, not the
    relay misbehaving, so it is repeated once with ``REASONING_RETRY_TOKENS``.
    """
    if not outcome.ok or outcome.tool_calls or outcome.finish_reason != "length":
        return None
    budget = _short_budget(spec)
    if budget is None:
        return None
    name, limit = budget
    # No visible answer at all although the limit was reached (thinking the
    # relay may not count), or an answer cut off after reasoning took at least
    # half the budget. A long answer that merely ran into its limit is left alone.
    if outcome.has_content():
        reasoning = usage_tokens(outcome.usage)["reasoning"] or 0
        if reasoning * 2 < limit:
            return None
    return _with_budget(spec, name, REASONING_RETRY_TOKENS)


def reasoning_room_spec(spec: RequestSpec) -> RequestSpec:
    """The request to send to an endpoint known to reason: a short explicit
    output budget is raised to ``REASONING_RETRY_TOKENS`` up front, so the probe
    is not sent once short and then again. Opt-out probes, requests without an
    explicit limit and those that already ask for enough are left as they are."""
    budget = _short_budget(spec)
    if budget is None:
        return spec
    return _with_budget(spec, budget[0], REASONING_RETRY_TOKENS)


def _short_budget(spec: RequestSpec) -> tuple[str, int] | None:
    """The explicit output limit a reasoning model may get more room on: set,
    below ``REASONING_RETRY_TOKENS``, and on a probe that has not opted out."""
    if not spec.reasoning_retry:
        return None
    budget = _budget_field(spec)
    if budget is None or budget[1] >= REASONING_RETRY_TOKENS:
        return None
    return budget


def _with_budget(spec: RequestSpec, name: str, value: int) -> RequestSpec:
    """A copy of ``spec`` with ``value`` in the output-limit field ``name``."""
    if name == "max_tokens":
        return spec.model_copy(update={"max_tokens": value})
    return spec.model_copy(update={"extra_body": {**spec.extra_body, name: value}})


def rejected_params(outcome: CompletionOutcome, sent: set[str]) -> set[str]:
    """The parameters among ``sent`` that a 4xx rejects by name, else empty.

    OpenAI names the field in ``error.param``; other servers only in the message
    ("Unsupported parameter: 'max_tokens' is not supported with this model").
    A name only counts as a whole word, so ``max_tokens`` is not found inside
    "use 'max_completion_tokens' instead".
    """
    status = outcome.status_code
    if outcome.ok or status is None or not 400 <= status < 500 or status in _NOT_PARAM_STATUSES:
        return set()
    text = (outcome.error_message or "").lower()
    spans = [
        (m.start(), m.end())
        for phrase in _PARAM_REJECTION_PHRASES
        for m in re.finditer(re.escape(phrase), text)
    ]
    if not spans:
        return set()
    error = (outcome.raw_error or {}).get("error")
    param = error.get("param") if isinstance(error, dict) else None
    if isinstance(param, str) and param:
        # The server says which field it means: trust that alone.
        return {param} & sent
    # Otherwise a name counts only next to a rejection phrase, so a message
    # that echoes the request body does not condemn every field in it.
    named = set()
    for name in sent:
        for m in re.finditer(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])", text):
            if any(m.start() < end + _NAME_REACH and start < m.end() + _NAME_REACH
                   for start, end in spans):
                named.add(name)
                break
    return named


def shared_ssl_context() -> ssl.SSLContext:
    """The process-wide TLS context (created on first use)."""
    global _SSL_CONTEXT
    with _SSL_LOCK:
        if _SSL_CONTEXT is None:
            _SSL_CONTEXT = httpx.create_ssl_context()
        return _SSL_CONTEXT


async def get_ssl_context() -> ssl.SSLContext:
    """The shared TLS context, built in a worker thread the first time (for
    code on the event loop; :func:`shared_ssl_context` blocks)."""
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    return await asyncio.to_thread(shared_ssl_context)


class BaseHTTPClient:
    """Connection lifecycle + redaction + error shaping shared by all clients."""

    def __init__(
        self,
        config: TargetConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.base_url = self._normalize_base_url(config.base_url)
        self._client: httpx.AsyncClient | None = None
        # Set by the runner to log every call for the performance section;
        # ``endpoint`` says which side ("target" / "baseline") this client is.
        self.recorder: RequestRecorder | None = None
        self.endpoint = config.kind
        self.local = is_local_host(self.base_url)
        # True once the endpoint is known to reason (its profile says so, or a
        # short probe already needed the reasoning repeat): short probes then go
        # out with ``REASONING_RETRY_TOKENS`` from the start (see complete()).
        self.reasoning_room = False
        # Request parameters the endpoint's model refuses: set by the runner from
        # the profile's ``unsupported_params`` and extended (sticky) whenever a
        # 4xx names a parameter the client can do without. Listed sampling
        # parameters are left out of requests; on Chat Completions a listed
        # ``max_tokens`` sends the output limit as ``max_completion_tokens``.
        # Requests with ``exact_params`` are sent as they are.
        self.unsupported_params: set[str] = set()

    # -- lifecycle ---------------------------------------------------------- #
    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self._timeout(),
            transport=self.transport,
            verify=await get_ssl_context(),
            headers=self._headers(),
            follow_redirects=False,
            event_hooks={"request": [self._attach_trace]},
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def _session(self):
        """Yield a client: the pooled one if open, else a short-lived one."""
        if self._client is not None:
            yield self._client
            return
        client = httpx.AsyncClient(
            timeout=self._timeout(),
            transport=self.transport,
            verify=await get_ssl_context(),
            headers=self._headers(),
            follow_redirects=False,
            event_hooks={"request": [self._attach_trace]},
        )
        try:
            yield client
        finally:
            await client.aclose()

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        stripped = base_url.strip().rstrip("/")
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return stripped

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.config.timeout_sec,
            connect=min(15.0, self.config.timeout_sec),
        )

    def request_budget(self, spec: RequestSpec) -> tuple[httpx.Timeout, float]:
        """The httpx timeout and the wall-clock deadline (seconds) for a completion.

        Non-streaming, the read timeout covers prefill and decode (no byte arrives
        before both are done). Streaming, it covers prefill only, the longest gap
        between chunks; the deadline still bounds the whole stream, so a relay
        that trickles a byte now and then cannot hold a request open forever.
        Both are clamped to ``max_request_sec`` (or ``timeout_sec`` if larger).
        """
        cfg = self.config
        base = cfg.timeout_sec
        prefill_tps, decode_tps = _PREFILL_TPS, _DECODE_TPS
        if self.local:
            base = max(base, _LOCAL_MIN_BASE_SEC)
            prefill_tps, decode_tps = _LOCAL_PREFILL_TPS, _LOCAL_DECODE_TPS
        cap = max(cfg.max_request_sec, cfg.timeout_sec)
        prefill = _prompt_tokens(spec.messages) / prefill_tps
        decode = _output_tokens(spec) / decode_tps
        total = min(cap, base + prefill + decode)
        read = min(cap, base + prefill) if spec.stream else total
        connect = min(15.0, cfg.timeout_sec)
        # Keep connect + read inside the deadline's slack, so httpx reports its own
        # timeout first whenever it can.
        return httpx.Timeout(read, connect=connect), total + connect

    def _call_timeout(self) -> httpx.Timeout:
        """The timeout for the completion in flight (set by :meth:`complete`)."""
        return _CALL_TIMEOUT.get() or self._timeout()

    def _extra_secrets(self) -> list[str | None]:
        """Secrets to scrub from any relay-controlled text before it is stored."""
        return [self.config.api_key]

    def _raw_body(self, data: Any, capture: bool) -> dict[str, Any] | None:
        """The redacted raw response body, when the request asked for it."""
        if not capture or not isinstance(data, dict):
            return None
        return redact_json(data, extra_secrets=self._extra_secrets())

    @staticmethod
    async def _attach_trace(request: httpx.Request) -> None:
        """Hand the in-flight call's transport events to its performance trace."""
        net = current_net_trace()
        if net is not None:
            request.extensions["trace"] = net.trace

    # Subclasses provide protocol-specific auth headers and request handling.
    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _build_body(self, spec: RequestSpec) -> dict[str, Any]:
        raise NotImplementedError

    def _drop_unsupported(self, body: dict[str, Any], spec: RequestSpec) -> dict[str, Any]:
        """``body`` without the sampling parameters the model refuses."""
        if spec.exact_params:
            return body
        for name in SAMPLING_PARAMS & self.unsupported_params:
            body.pop(name, None)
        return body

    def _adaptable(self, spec: RequestSpec, body: dict[str, Any]) -> set[str]:
        """The parameters of ``body`` the client can adapt when they are
        rejected (subclasses add their output-limit field)."""
        return set(SAMPLING_PARAMS & body.keys())

    def _adapt(
        self, spec: RequestSpec, sent: dict[str, Any], outcome: CompletionOutcome
    ) -> bool:
        """Learn from a 4xx that rejected parameters of the body ``sent``; True
        when the request now goes out differently and is worth repeating (also
        when a concurrent request already learned the same thing)."""
        if spec.exact_params:
            return False
        named = rejected_params(outcome, self._adaptable(spec, sent))
        if not named:
            return False
        self.unsupported_params |= named
        return self._build_body(spec) != sent

    async def _complete(self, spec: RequestSpec) -> CompletionOutcome:
        raise NotImplementedError

    async def _list_models(
        self, headers: dict[str, str] | None = None
    ) -> tuple[CompletionOutcome, list[str]]:
        raise NotImplementedError

    # -- public calls (recorded for the performance section) --------------- #
    async def complete(self, spec: RequestSpec) -> CompletionOutcome:
        if self.reasoning_room:
            spec = reasoning_room_spec(spec)
        outcome = await self._complete_adapted(spec)
        retry = reasoning_retry_spec(spec, outcome)
        if retry is not None:
            outcome = await self._complete_adapted(retry)
            # Sticky once the room helped: later short probes get it on their
            # first try instead of being sent twice.
            if outcome.ok and outcome.has_content():
                self.reasoning_room = True
        return outcome

    async def _complete_adapted(self, spec: RequestSpec) -> CompletionOutcome:
        """One completion, repeated when a 4xx named a parameter the client can
        adapt (dropped, or the output limit renamed). The learned names stay in
        ``unsupported_params``, so later requests go out adapted from the start;
        at most ``_MAX_PARAM_RETRIES`` repeats.
        Rejected attempts are recorded with phase ``param_retry``: the request
        was zing's, not a relay error."""
        for _ in range(_MAX_PARAM_RETRIES):
            sent = self._build_body(spec)
            outcome, record = await self._complete_recorded(spec)
            if not self._adapt(spec, sent, outcome):
                return outcome
            if record is not None:
                record.phase = "param_retry"
        return (await self._complete_recorded(spec))[0]

    async def _complete_recorded(
        self, spec: RequestSpec
    ) -> tuple[CompletionOutcome, RequestRecord | None]:
        if self.recorder is None:
            return await self._complete_bounded(spec), None
        started = time.perf_counter()
        with net_trace_scope() as net:
            outcome = await self._complete_bounded(spec)
        record = self.recorder.record_completion(self.endpoint, spec, outcome, started, net)
        return outcome, record

    async def _complete_bounded(self, spec: RequestSpec) -> CompletionOutcome:
        """Run one completion under its timeout budget and hard deadline."""
        timeout, deadline = self.request_budget(spec)
        started = time.perf_counter()
        token = _CALL_TIMEOUT.set(timeout)
        try:
            return await asyncio.wait_for(self._complete(spec), deadline)
        except asyncio.TimeoutError:
            return CompletionOutcome(
                ok=False,
                duration_ms=(time.perf_counter() - started) * 1000,
                error_type="DeadlineTimeout",
                error_message=f"Request exceeded its {deadline:.0f} s deadline.",
            )
        finally:
            _CALL_TIMEOUT.reset(token)

    async def list_models(
        self, *, no_cache: bool = False
    ) -> tuple[CompletionOutcome, list[str]]:
        """GET /models. ``no_cache`` asks intermediaries for a fresh answer, for a
        round-trip measurement."""
        headers = {"Cache-Control": "no-cache"} if no_cache else None
        if self.recorder is None:
            return await self._list_models(headers)
        started = time.perf_counter()
        with net_trace_scope() as net:
            outcome, ids = await self._list_models(headers)
        self.recorder.record_models(self.endpoint, outcome, started, net)
        return outcome, ids

    # -- error shaping (shared) -------------------------------------------- #
    def _error_from_response(
        self, response: httpx.Response, duration_ms: float, headers: dict[str, str]
    ) -> CompletionOutcome:
        secrets = self._extra_secrets()
        raw_error: dict[str, Any] | None = None
        message = response.text[:1000]
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                # A relay can echo the bearer token / a sibling key inside the error
                # body, so scrub every string value recursively before we keep it.
                raw_error = redact_json(parsed, extra_secrets=secrets)
                error = parsed.get("error") or parsed
                if isinstance(error, dict):
                    message = str(error.get("message") or error)[:1000]
        except Exception:
            pass
        return CompletionOutcome(
            ok=False,
            status_code=response.status_code,
            duration_ms=duration_ms,
            headers=headers,
            error_type="http_error",
            error_message=redact_text(message, extra_secrets=secrets),
            raw_error=raw_error,
        )

    def _exception_outcome(self, exc: Exception, started: float) -> CompletionOutcome:
        duration_ms = (time.perf_counter() - started) * 1000
        return CompletionOutcome(
            ok=False,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=redact_text(str(exc)[:1000], extra_secrets=self._extra_secrets()),
        )
