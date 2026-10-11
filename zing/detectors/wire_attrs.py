"""Wire-attribute catalogs for the protocol attribute detectors.

What a conformant endpoint must send back (``RESPONSE_ATTRS``) and which request
parameters it must accept (``REQUEST_PARAMS``), per wire protocol ("openai" Chat
Completions, "anthropic" Messages, "responses" OpenAI Responses). The catalogs
are data; the functions below are pure, so the detectors in
:mod:`zing.detectors.protocol_attrs` stay thin and all judgement is testable
without a client.

Each attribute is one subject of a parametrized scale check (see
:mod:`zing.detectors.scale`): response attributes score against the
``protocol_response.core`` or ``.minor`` row set, request parameters against
``protocol_request.param``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from zing import prompts
from zing.detectors.helpers import MISSING, contains_ci, dig
from zing.detectors.scale import Scale, outcome
from zing.models import CompletionOutcome, Severity, Status

# --------------------------------------------------------------------------- #
# Response attributes
# --------------------------------------------------------------------------- #
CORE = "protocol_response.core"
MINOR = "protocol_response.minor"
CALL = "protocol_response.call"


@dataclass(frozen=True)
class Attr:
    """One response attribute and the rule its value must satisfy.

    Rules: ``str`` (non-empty string), ``int>0``, ``ts`` (a plausible Unix
    timestamp), ``list>0`` (non-empty list), ``=<value>`` (exact string),
    ``sum:<path>+<path>`` (a positive integer equal to the sum of two others).
    """

    path: str
    rule: str
    tier: str = "core"  # "core" | "minor"

    @property
    def check(self) -> str:
        return CORE if self.tier == "core" else MINOR


RESPONSE_ATTRS: dict[str, list[Attr]] = {
    "openai": [
        Attr("model", "str"),
        Attr("choices", "list>0"),
        Attr("choices.0.message.role", "=assistant"),
        Attr("choices.0.message.content", "str"),
        Attr("choices.0.finish_reason", "str"),
        Attr("usage.prompt_tokens", "int>0"),
        Attr("usage.completion_tokens", "int>0"),
        Attr("usage.total_tokens", "sum:usage.prompt_tokens+usage.completion_tokens"),
        Attr("id", "str", "minor"),
        Attr("object", "=chat.completion", "minor"),
        Attr("created", "ts", "minor"),
        Attr("choices.0.index", "int>=0", "minor"),
    ],
    "anthropic": [
        Attr("role", "=assistant"),
        Attr("model", "str"),
        Attr("content.0.text", "str"),
        Attr("stop_reason", "str"),
        Attr("usage.input_tokens", "int>0"),
        Attr("usage.output_tokens", "int>0"),
        Attr("id", "str", "minor"),
        Attr("type", "=message", "minor"),
    ],
    "responses": [
        Attr("model", "str"),
        Attr("status", "=completed"),
        Attr("output", "list>0"),
        Attr("usage.input_tokens", "int>0"),
        Attr("usage.output_tokens", "int>0"),
        Attr("usage.total_tokens", "sum:usage.input_tokens+usage.output_tokens"),
        Attr("id", "str", "minor"),
        Attr("object", "=response", "minor"),
        Attr("created_at", "ts", "minor"),
    ],
}

RESPONSE_SCALE = Scale(
    outcome(CORE, "valid", 100.0, Status.PASS,
            label="Present with a valid value."),
    outcome(CORE, "zero", 20.0, Status.FAIL, Severity.MEDIUM,
            label="Present but zero or empty (e.g. completion_tokens: 0)."),
    outcome(CORE, "invalid", 40.0, Status.WARN, Severity.MEDIUM,
            label="Present with a wrong type or value (e.g. total ≠ sum of parts)."),
    outcome(CORE, "missing", 0.0, Status.FAIL, Severity.MEDIUM,
            label="Missing from the response."),
    outcome(MINOR, "valid", 100.0, Status.PASS,
            label="Present with a valid value."),
    outcome(MINOR, "zero", 50.0, Status.WARN, Severity.LOW,
            label="Present but zero or empty."),
    outcome(MINOR, "invalid", 70.0, Status.WARN, Severity.LOW,
            label="Present with a wrong type or value."),
    outcome(MINOR, "missing", 60.0, Status.WARN, Severity.LOW,
            label="Missing from the response."),
    outcome(CALL, "no_response", None, Status.INCONCLUSIVE, Severity.LOW,
            label="The probe call returned no response body to judge by."),
    titles={
        CORE: "Core response attributes",
        MINOR: "Minor response attributes",
        CALL: "Response-attribute probe",
    },
)

_RULE_TEXT = {
    "str": "a non-empty string",
    "int>0": "an integer > 0",
    "int>=0": "an integer ≥ 0",
    "ts": "a Unix timestamp",
    "list>0": "a non-empty list",
}
# Earliest plausible creation time (2020-01-01); anything below is not a timestamp.
_MIN_TS = 1_577_836_800


def expected(rule: str) -> str:
    """Human-readable form of a rule, for evidence."""
    if rule.startswith("="):
        return repr(rule[1:])
    if rule.startswith("sum:"):
        return "an integer = " + rule[4:].replace("+", " + ")
    return _RULE_TEXT.get(rule, rule)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def judge(rule: str, value: Any, body: Any) -> str:
    """Outcome key (valid / zero / invalid / missing) of one value under a rule."""
    if value is MISSING:
        return "missing"
    if rule == "str":
        if not isinstance(value, str):
            return "invalid"
        return "valid" if value.strip() else "zero"
    if rule.startswith("="):
        return "valid" if value == rule[1:] else "invalid"
    if rule == "list>0":
        if not isinstance(value, list):
            return "invalid"
        return "valid" if value else "zero"
    if not _is_int(value):
        return "invalid"
    if rule == "int>=0":
        return "valid" if value >= 0 else "invalid"
    if value == 0:
        return "zero"
    if value < 0:
        return "invalid"
    if rule == "ts":
        return "valid" if value >= _MIN_TS else "invalid"
    if rule.startswith("sum:"):
        parts = [dig(body, p) for p in rule[4:].split("+")]
        if all(_is_int(p) for p in parts) and value != sum(parts):
            return "invalid"
    return "valid"


@dataclass(frozen=True)
class AttrResult:
    attr: Attr
    key: str
    observed: Any


def assess_response(protocol: str, body: dict[str, Any]) -> list[AttrResult]:
    """Judge every catalog attribute of ``protocol`` against a raw response body."""
    results = []
    for attr in RESPONSE_ATTRS[protocol]:
        value = dig(body, attr.path)
        results.append(AttrResult(attr, judge(attr.rule, value, body), value))
    return results


# --------------------------------------------------------------------------- #
# Request parameters
# --------------------------------------------------------------------------- #
PARAM = "protocol_request.param"

REQUEST_SCALE = Scale(
    outcome(PARAM, "honored", 100.0, Status.PASS,
            label="Accepted, and its effect is visible in the response."),
    outcome(PARAM, "accepted", 100.0, Status.PASS,
            label="Accepted (its effect cannot be observed from one response)."),
    outcome(PARAM, "ignored", 50.0, Status.WARN, Severity.LOW,
            label="Accepted, but its effect is missing from the response."),
    outcome(PARAM, "rejected", 40.0, Status.WARN, Severity.LOW,
            label="Rejected with a 4xx (possibly a limit of the model itself)."),
    outcome(PARAM, "dropped_by_relay", 15.0, Status.FAIL, Severity.MEDIUM,
            label="Rejected with a 4xx, while the baseline accepts it."),
    outcome(PARAM, "model_limit", None, Status.INFO,
            label="Rejected, but the model itself does not support it; not counted."),
    outcome(PARAM, "no_response", None, Status.INCONCLUSIVE, Severity.LOW,
            label="Server error or no response; not counted."),
    titles={PARAM: "Request parameters"},
)

Verifier = Callable[[CompletionOutcome], bool]


@dataclass(frozen=True)
class Param:
    """One request parameter: how to send it and, if observable, how to verify it.

    ``spec`` holds :class:`~zing.models.RequestSpec` fields (``extra_body`` for
    parameters without a field of their own). A param without ``verify`` is
    accept-only: all of them go out together in one call and are only retried
    one by one when that call is rejected. ``sampling`` marks parameters that
    reasoning models commonly refuse.
    """

    name: str
    spec: dict[str, Any] = field(default_factory=dict)
    verify: Verifier | None = None
    sampling: bool = False


def _system_honored(o: CompletionOutcome) -> bool:
    return contains_ci(o.content, "pineapple")


def _truncated(o: CompletionOutcome) -> bool:
    return o.finish_reason == "length"


def _two_choices(o: CompletionOutcome) -> bool:
    choices = dig(o.raw_body, "choices")
    return isinstance(choices, list) and len(choices) == 2


def _logprobs(o: CompletionOutcome) -> bool:
    content = dig(o.raw_body, "choices.0.logprobs.content")
    return isinstance(content, list) and bool(content)


def _system(name: str) -> Param:
    return Param(name, {"messages": prompts.get("protocol_request.system")}, _system_honored)


def _max_tokens(name: str, *, extra: bool = False) -> Param:
    messages = [{"role": "user", "content": prompts.text("protocol_request.long")}]
    # The truncation is the effect under test: never repeat it with a larger limit.
    if extra:  # reasoning models take the limit as max_completion_tokens
        return Param(
            name,
            {"messages": messages, "extra_body": {name: 16}, "reasoning_retry": False},
            _truncated,
        )
    return Param(name, {"messages": messages, "max_tokens": 16, "reasoning_retry": False}, _truncated)


def _body(name: str, value: Any, *, sampling: bool = False) -> Param:
    return Param(name, {"extra_body": {name: value}}, sampling=sampling)


def request_params(protocol: str, *, reasoning: bool = False) -> list[Param]:
    """The request-parameter catalog of ``protocol``.

    ``reasoning`` (from the knowledge-base profile) switches the OpenAI output
    limit to ``max_completion_tokens``, which those models require.
    """
    if protocol == "anthropic":
        return [
            _system("system"),
            _max_tokens("max_tokens"),
            Param("temperature", {"temperature": 0.5}, sampling=True),
            _body("top_p", 0.9, sampling=True),
            _body("top_k", 5, sampling=True),
            _body("metadata", {"user_id": "zing-audit"}),
        ]
    if protocol == "responses":
        return [
            _system("instructions"),
            _max_tokens("max_output_tokens"),
            Param("temperature", {"temperature": 0.5}, sampling=True),
            _body("top_p", 0.9, sampling=True),
            _body("metadata", {"probe": "zing-audit"}),
            _body("user", "zing-audit"),
        ]
    return [
        _system("system"),
        _max_tokens("max_completion_tokens", extra=True) if reasoning else _max_tokens("max_tokens"),
        Param("n", {"extra_body": {"n": 2}}, _two_choices),
        Param(
            "logprobs",
            {"extra_body": {"logprobs": True, "top_logprobs": 2}},
            _logprobs,
            sampling=True,
        ),
        Param("temperature", {"temperature": 0.5}, sampling=True),
        _body("top_p", 0.9, sampling=True),
        _body("seed", 7),
        _body("presence_penalty", 0.1, sampling=True),
        _body("frequency_penalty", 0.1, sampling=True),
        _body("user", "zing-audit"),
    ]


def merge_specs(params: list[Param]) -> dict[str, Any]:
    """One request carrying every param's fields (``extra_body`` merged)."""
    merged: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for p in params:
        for key, value in p.spec.items():
            if key == "extra_body":
                extra.update(value)
            else:
                merged[key] = value
    if extra:
        merged["extra_body"] = extra
    return merged


def is_rejection(o: CompletionOutcome) -> bool:
    return o.status_code is not None and 400 <= o.status_code <= 499


def classify_param(
    param: Param,
    o: CompletionOutcome,
    *,
    known_unsupported: bool = False,
    baseline: CompletionOutcome | None = None,
) -> str:
    """Outcome key of one parameter probe.

    ``known_unsupported``: the model itself is known not to take this parameter
    (knowledge base, or a sampling parameter on a reasoning model). ``baseline``:
    the same probe against a trusted endpoint, when one was configured.
    """
    if o.ok:
        if param.verify is None:
            return "accepted"
        return "honored" if param.verify(o) else "ignored"
    if not is_rejection(o):
        return "no_response"
    if baseline is not None and baseline.ok:
        return "dropped_by_relay"
    if baseline is not None and is_rejection(baseline):
        return "model_limit"
    return "model_limit" if known_unsupported else "rejected"
