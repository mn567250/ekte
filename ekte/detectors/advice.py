"""What to change when a check could not judge: one fixed recommendation per
kind of failure.

A finding that is not counted because its request failed, timed out or came
back empty says *why* in its summary; its recommendation says *what to change*
so the next run can judge. The sentences are fixed (no values in them) so every
UI language translates them by exact match (``ekte/i18n/locales``), and each
one names the option to change where there is one.
"""

from __future__ import annotations

from typing import Any

from ekte import errorclass

# One sentence per failure kind; the keys are what :func:`failure_kind` returns.
FAILURE_ADVICE: dict[str, str] = {
    "timeout": (
        "The request timed out: raise --timeout (and --max-request-time for long answers) "
        "and re-run."
    ),
    "rate_limited": (
        "The relay rate-limited the request (HTTP 429): lower --concurrency or wait for the "
        "limit to reset, then re-run."
    ),
    "rejected": (
        "The endpoint rejected the request (HTTP 400/422), often a parameter it does not "
        "support for this model: check the error text and re-run."
    ),
    "auth": (
        "The endpoint refused the key (HTTP 401/403): check the API key and its access to "
        "this model, then re-run."
    ),
    "not_found": (
        "The endpoint or model was not found (HTTP 404): check --base-url and --model, "
        "then re-run."
    ),
    "upstream": (
        "The relay or its upstream failed (HTTP 5xx): re-run later; if it keeps failing, "
        "the relay is unstable for this model."
    ),
    "network": (
        "The request never reached the relay (proxy, DNS, connect or TLS failure): check the "
        "network path and --base-url, then re-run."
    ),
    "local": (
        "The request failed inside ekte, not at the relay: re-run; if it persists, report "
        "it with the evidence file."
    ),
    "unsupported": (
        "This client has no such endpoint for the configured wire protocol: check --api "
        "for this relay."
    ),
    "empty": (
        "The relay answered without usable content: check that it serves this model and "
        "returns its text, then re-run."
    ),
    "other": "The request failed at the relay: check the error text and re-run.",
}

# Not-counted findings that do not rest on one failed request.
NO_STREAM_DELTAS = (
    "The relay sent no streamed content deltas, so there is no time to first token: it does "
    "not stream this model's answers (see the Streaming findings). Fix streaming at the relay, "
    "or re-run with --performance-non-streaming to measure end-to-end throughput instead."
)
TOO_SHORT_FOR_DECODE = (
    "The answers were too short to time decoding (fewer than 2 tokens after the first): "
    "check that the model answers the probe with text and that the relay does not cut it off."
)
PROBE_FAILURES = (
    "Most probe requests failed, so too few were left to judge: fix the failures shown under "
    "Probe request failures, then re-run."
)
PROBE_CACHED = (
    "Most probe requests came back from a cache and were left out: audit a relay without "
    "response caching, or ask its operator to disable it for this key, then re-run."
)
STANDARD_PROBE_CAP = (
    "The standard suite sends only 5 probe requests per endpoint, fewer than consistency "
    "needs: run the deep, full or custom suite to judge it."
)
MORE_PROBE_REQUESTS = (
    "Too few probe requests were sent: raise --performance-requests to at least 10 and re-run."
)

# Checks that could not judge for a reason of their own.
NO_MODEL_FIELD = (
    "The relay's responses carry no model field, so it cannot be compared with the requested "
    "model; nothing to change on your side, the other identity findings still apply."
)
NO_PROMPT_TOKENS = (
    "The relay returns no usage.prompt_tokens, so a hidden system prompt cannot be measured: "
    "ask its operator to forward the upstream usage block, then re-run."
)
NO_CANARY_ECHO = (
    "The model did not repeat the canaries word for word, so substitution could not be "
    "checked: re-run, and if it persists audit with a model that follows copy instructions."
)
NO_CONTEXT_LADDER = (
    "The probe cap is below the probe floor: raise --max-context-tokens above "
    "context_probe_floor_tokens (1000 by default), or check the declared context window, "
    "then re-run."
)
NO_IDENTITY_EVIDENCE = (
    "No identity probe got a usable answer: fix the failures shown in the identity findings "
    "(or under Connectivity) and re-run, or run ekte compare against a trusted baseline."
)
BY_DESIGN = (
    "Nothing to change: this probe is skipped by design to keep the identity check's output "
    "small, and another probe takes its place."
)
JUDGE_FAILED = (
    "The judge call failed or its answer could not be parsed: check --judge-base-url, "
    "--judge-model and --judge-api-key, then re-run."
)
JUDGE_UNDECIDED = (
    "The judge could not decide from these answers: re-run, or weigh the fingerprint and "
    "self-identification findings instead."
)

# Why a dimension did not run (ekte.detectors.base.not_run_reason), most
# actionable first: the first reason that applies to any of its checks wins.
NOT_RUN_REASONS: dict[str, str] = {
    "suite_standard": "Not run in this suite: its checks run on the standard suite or higher.",
    "baseline": (
        "Not run in this suite: on the standard suite its checks need a trusted baseline "
        "(ekte compare); the deep, full and custom suites run them without one."
    ),
    "suite_deep": "Not run in this suite: its checks run on the deep, full or custom suite.",
    "suite_full": "Not run in this suite: its checks run on the full suite only.",
    "judge": "Not run: its checks need an LLM judge (--judge with --judge-model).",
    "disabled": "Not run: its checks are switched off in the configuration.",
}


def failure_kind(outcome: Any) -> str:
    """What kind of failure ``outcome`` (a CompletionOutcome or a request record)
    is: a key of :data:`FAILURE_ADVICE`."""
    if outcome is None:
        return "other"
    if getattr(outcome, "ok", False):
        return "empty"
    error_type = getattr(outcome, "error_type", None)
    status = getattr(outcome, "status_code", None)
    if error_type == "Unsupported":
        return "unsupported"
    if status == 429 or getattr(outcome, "rate_limited", False) is True:
        return "rate_limited"
    if getattr(outcome, "timeout", False) is True:
        return "timeout"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if status in (400, 413, 422):
        return "rejected"
    if status is not None and status >= 500:
        return "upstream"
    name = str(error_type or "")
    if name == "DeadlineTimeout" or (
        "Timeout" in name and name not in ("ConnectTimeout", "PoolTimeout")
    ):
        return "timeout"
    klass = getattr(outcome, "error_class", None) or (
        errorclass.classify_name(error_type, status) if error_type or status else None
    )
    if klass == errorclass.NETWORK:
        return "network"
    if klass == errorclass.LOCAL:
        return "local"
    return "other"


def failure_advice(outcome: Any) -> str:
    """The fixed recommendation for a check that failed on ``outcome``."""
    return FAILURE_ADVICE[failure_kind(outcome)]


def few_samples_advice(
    *,
    requests: int,
    failed: int,
    cached: int,
    missing: int,
    missing_advice: str | None,
    minimum: int,
    capped: bool,
) -> str:
    """What to change when a sample-based check had fewer than ``minimum`` clean
    samples: the biggest reason the probe requests were left out wins.

    ``requests`` are the probe requests the check looked at; ``failed``,
    ``cached`` and ``missing`` (succeeded but without this metric's value) are
    the ones it left out. ``capped`` means the suite caps the probe below
    ``minimum`` (standard with a baseline)."""
    if requests < minimum:
        return STANDARD_PROBE_CAP if capped else MORE_PROBE_REQUESTS
    reasons = [(failed, PROBE_FAILURES), (cached, PROBE_CACHED)]
    if missing_advice:
        reasons.append((missing, missing_advice))
    count, advice = max(reasons, key=lambda r: r[0])
    return advice if count else MORE_PROBE_REQUESTS
