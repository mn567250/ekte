"""Where a failed request failed: ekte itself, the network path, or the relay.

Only a ``relay`` failure is the audited relay's fault and counts against it.
``local`` (ekte's own code, its connection pool, a request it could not build)
and ``network`` (a proxy, DNS, connect or TLS failure before the relay
answered) are retried :func:`non_relay_retries` times and, if they persist,
reported as an impaired run, never as relay errors.

:func:`classify_exception` sorts a live exception; :func:`classify_name` sorts
what an older record kept (its ``error_type``, the exception's class name), so
runs saved before the classification existed get the same classes.

:func:`outcome` gives every counted request record exactly one of
:data:`OUTCOMES`, the single definition the per-run counts and rates
(:mod:`ekte.perf.outcomes`) rest on.
"""

from __future__ import annotations

import json
import logging
import socket
import ssl

import httpx

from ekte import legacy

LOCAL = "local"
NETWORK = "network"
RELAY = "relay"
ERROR_CLASSES = (LOCAL, NETWORK, RELAY)

# How often a local or network failure is repeated before it counts as an
# impaired request (relay failures are never repeated here).
RETRIES_ENV = "EKTE_NON_RELAY_RETRIES"
DEFAULT_RETRIES = 1
MAX_RETRIES = 10

log = logging.getLogger(__name__)

# error_type values the clients set themselves (not exception class names)
_RELAY_TYPES = frozenset({
    "http_error",  # an HTTP error status
    "DeadlineTimeout",  # the relay did not finish within the request's deadline
    "IncompleteRanking",  # a rerank answer that left documents out
})
_LOCAL_TYPES = frozenset({"Unsupported"})  # the client has no such endpoint

# Exception class names, for records that kept only the name. A name in
# neither set counts as a relay failure, as every failure did before.
_NETWORK_NAMES = frozenset({
    "ProxyError", "ConnectError", "ConnectTimeout",
    "gaierror", "herror", "SSLError", "SSLCertVerificationError",
    "ConnectionRefusedError",
})
_LOCAL_NAMES = frozenset({
    "PoolTimeout", "LocalProtocolError", "UnsupportedProtocol", "InvalidURL",
    "ReplayMiss",
    "TypeError", "KeyError", "AttributeError", "IndexError", "NameError",
    "AssertionError", "RuntimeError", "NotImplementedError", "RecursionError",
    "ZeroDivisionError", "OverflowError", "ValueError", "LookupError",
    "MemoryError", "ImportError", "ModuleNotFoundError", "UnboundLocalError",
})


def classify_exception(exc: BaseException) -> str:
    """The class of a request that raised ``exc``."""
    # ekte's own side: its pool, a request httpx refused to send, a replay gap
    if isinstance(exc, (httpx.PoolTimeout, httpx.LocalProtocolError, httpx.UnsupportedProtocol,
                        httpx.InvalidURL)):
        return LOCAL
    if type(exc).__name__ == "ReplayMiss":
        return LOCAL
    # never reached the relay: the proxy, DNS, connect and TLS
    if isinstance(exc, (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout,
                        socket.gaierror, ssl.SSLError, ConnectionRefusedError)):
        return NETWORK
    # reached the relay, which answered too late, broke off or sent garbage
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError,
                        httpx.DecodingError, httpx.TooManyRedirects, json.JSONDecodeError,
                        UnicodeDecodeError)):
        return RELAY
    # anything else is a bug in ekte, not a relay answer
    return LOCAL


def classify_name(error_type: str | None, status_code: int | None = None) -> str:
    """The class of a failed request from what its record kept."""
    if status_code is not None:
        return RELAY
    if error_type in _RELAY_TYPES:
        return RELAY
    if error_type in _LOCAL_TYPES or error_type in _LOCAL_NAMES:
        return LOCAL
    if error_type in _NETWORK_NAMES:
        return NETWORK
    return RELAY


def record_class(rec: object) -> str | None:
    """The class of a request record (a RequestRecord or its dict); None when it
    succeeded. Records saved before the classification get it from their
    ``error_type`` and ``status_code``."""
    get = rec.get if isinstance(rec, dict) else lambda k, d=None: getattr(rec, k, d)
    if get("ok", False):
        return None
    stored = get("error_class", None)
    if stored in ERROR_CLASSES:
        return str(stored)
    return classify_name(get("error_type", None), get("status_code", None))


# --------------------------------------------------------------------------- #
# Outcomes: what happened to one request, exactly one per counted record
# --------------------------------------------------------------------------- #
SUCCESS = "success"
RATE_LIMITED = "rate_limited"
RELAY_TIMEOUT = "relay_timeout"
RELAY_5XX = "relay_5xx"
RELAY_4XX = "relay_4xx"
RELAY_OTHER = "relay_other"
# The relay's own failures: the error rate's numerator.
RELAY_ERRORS = (RELAY_TIMEOUT, RELAY_5XX, RELAY_4XX, RELAY_OTHER)
# Failures before the relay could answer: left out of the judged base.
IMPAIRED = (NETWORK, LOCAL)
OUTCOMES = (SUCCESS, RATE_LIMITED, *RELAY_ERRORS, *IMPAIRED)

# ekte's own repeat of a call with another max-tokens parameter: never counted.
_UNCOUNTED_PHASES = frozenset({"param_retry"})


def outcome(rec: object) -> str | None:
    """The outcome of a request record (a RequestRecord or its dict), one of
    :data:`OUTCOMES`; None for a record that never counts (a repeated
    attempt, superseded by its repeat, or ekte's ``param_retry``).

    Precedence: success, then a network or local failure, then the relay's
    answer: rate-limited (flag or HTTP 429), timeout, 5xx, 4xx, anything else.
    """
    get = rec.get if isinstance(rec, dict) else lambda k, d=None: getattr(rec, k, d)
    if get("retried", False) or get("phase", None) in _UNCOUNTED_PHASES:
        return None
    if get("ok", False):
        return SUCCESS
    cls = record_class(rec)
    if cls in IMPAIRED:
        return str(cls)
    status = get("status_code", None)
    if not isinstance(status, int) or isinstance(status, bool):
        status = None
    if get("rate_limited", False) or status == 429:
        return RATE_LIMITED
    if get("timeout", False):
        return RELAY_TIMEOUT
    if status is not None and 500 <= status <= 599:
        return RELAY_5XX
    if status is not None and 400 <= status <= 499:
        return RELAY_4XX
    return RELAY_OTHER


def is_relay_failure(rec: object) -> bool:
    """A failed request that counts against the relay (a repeated attempt never does)."""
    get = rec.get if isinstance(rec, dict) else lambda k, d=None: getattr(rec, k, d)
    return not get("retried", False) and record_class(rec) == RELAY


def is_impaired(rec: object) -> bool:
    """A request that finally failed on ekte's side or the network path."""
    get = rec.get if isinstance(rec, dict) else lambda k, d=None: getattr(rec, k, d)
    return not get("retried", False) and record_class(rec) in (LOCAL, NETWORK)


def attach_classes(records: object) -> None:
    """Give every failed record dict without an ``error_class`` (a run saved
    before the classification) the class :func:`record_class` derives, in
    place: what the web UI shows for older runs."""
    if not isinstance(records, list):
        return
    for rec in records:
        if isinstance(rec, dict) and not rec.get("ok") and rec.get("error_class") is None:
            rec["error_class"] = record_class(rec)


# --------------------------------------------------------------------------- #
# Proxy failures: who the HTTPS proxy's answer to CONNECT points at
# --------------------------------------------------------------------------- #
# The proxy itself refused the tunnel (407 authentication, 403 policy, ...):
# the proxy or ekte's proxy settings are at fault.
PROXY_REFUSED = "proxy_refused"
# The proxy could not reach the relay host (502/503/504, typically after its
# own connect timeout): the problem lies between the proxy and the relay host
# (its DNS, firewall, load balancer or an address the proxy cannot route to);
# the proxy only reports it.
PROXY_UNREACHABLE = "proxy_upstream_unreachable"
# Any other answer.
PROXY_OTHER = "proxy_other"
PROXY_REASONS = (PROXY_REFUSED, PROXY_UNREACHABLE, PROXY_OTHER)
_UNREACHABLE_STATUSES = frozenset({502, 503, 504})

# How each reason reads in the reports and the web UI.
PROXY_REASON_TEXT = {
    PROXY_REFUSED: "the proxy refused the tunnel",
    PROXY_UNREACHABLE: "relay host unreachable via the proxy",
    PROXY_OTHER: "proxy error",
}


def proxy_reason(status: int | None) -> str | None:
    """What an HTTPS proxy's answer to CONNECT says (one of
    :data:`PROXY_REASONS`), or None when no answer was kept."""
    if not isinstance(status, int) or isinstance(status, bool):
        return None
    if status in _UNREACHABLE_STATUSES:
        return PROXY_UNREACHABLE
    if 400 <= status <= 499:
        return PROXY_REFUSED
    return PROXY_OTHER


def record_proxy_reason(rec: object) -> str | None:
    """The proxy reason of a failed request record (a RequestRecord or its
    dict); None when it kept no proxy answer (also every record saved before
    they were kept)."""
    get = rec.get if isinstance(rec, dict) else lambda k, d=None: getattr(rec, k, d)
    if get("ok", False):
        return None
    return proxy_reason(get("proxy_status", None))


def retryable(error_class: str | None, error_type: str | None) -> bool:
    """Whether a failure of this class is repeated: local and network ones,
    except a call the client cannot make at all."""
    return error_class in (LOCAL, NETWORK) and error_type not in _LOCAL_TYPES


def non_relay_retries() -> int:
    """``EKTE_NON_RELAY_RETRIES`` (0 to :data:`MAX_RETRIES`; default
    :data:`DEFAULT_RETRIES`, also for a value that is not a whole number)."""
    raw = legacy.getenv(RETRIES_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_RETRIES
    try:
        value = int(raw.strip())
    except ValueError:
        log.warning("%s=%r is not a whole number; using %d", RETRIES_ENV, raw, DEFAULT_RETRIES)
        return DEFAULT_RETRIES
    return max(0, min(MAX_RETRIES, value))
