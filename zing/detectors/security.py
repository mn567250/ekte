"""Transport & secret-handling signals — static checks plus one light call.

Black-box auditing cannot prove what a relay does with a key server-side, so this
detector sticks to what is observable: whether the transport is encrypted, whether
the relay leaks its upstream identity in response headers, and whether the API key
is ever reflected back to the caller. Stronger claims (prompt logging, shared
upstream keys) are flagged as out-of-band — only reliability/timing can hint at
them indirectly.
"""

from __future__ import annotations

import ipaddress

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.helpers import contains_ci, stable_marker
from zing.detectors.scale import DeductionScale, outcome
from zing.models import DetectorResult, Dimension, RequestSpec, Severity, Status
from zing.utils.net import is_local_host, url_host
from zing.utils.redact import REDACTED_KEY

# Response headers that reveal upstream/proxy identity. Presence is informational:
# it can corroborate a substitution finding but is not itself a failure. Matched
# case-insensitively; "*"-suffixed entries match by prefix (header families).
_REVEALING_HEADERS: tuple[str, ...] = (
    "server",
    "via",
    "x-powered-by",
    "x-upstream-",
    "x-litellm-",
    "openai-organization",
    "x-served-by",
    "x-proxy-",
    "cf-",
)


def _is_local_transport(base_url: str) -> bool:
    """Whether plain HTTP to ``base_url`` stays on this machine or a private
    network. A public DNS name that merely starts with "127." is not loopback."""
    if not is_local_host(base_url):
        return False
    host = url_host(base_url)
    if host.startswith("127."):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return False
    return True


def _header_matches(name: str) -> bool:
    lname = name.lower()
    for marker in _REVEALING_HEADERS:
        if marker.endswith("-"):
            if lname.startswith(marker):
                return True
        elif lname == marker:
            return True
    return False


# Scoring follows the published scale (method "deductions"): the score starts
# at 100 and each transport-security failure caps it; the lowest cap wins.
# Plain HTTP to this machine or a private network (a self-hosted model) is only
# a WARN: the key does not cross the public internet. The TLS check is a
# transport advisory (zing.scoring.ADVISORY_CHECKS): it lowers this dimension,
# never the substitution risk.
SCALE = DeductionScale(
    outcome("security.tls", "https", None, Status.PASS,
            label="The endpoint uses HTTPS."),
    outcome("security.tls", "plain_http", None, Status.FAIL, Severity.HIGH, cap=40.0,
            label="The endpoint is not HTTPS; the API key travels in clear text."),
    outcome("security.tls", "plain_http_local", None, Status.WARN, Severity.LOW,
            label="Plain HTTP to a local or private-network host; the API key does not cross the internet."),
    outcome("security.key_echo", "not_echoed", None, Status.PASS,
            label="The API key does not appear in the response."),
    outcome("security.key_echo", "echoed", None, Status.FAIL, Severity.HIGH, cap=30.0,
            label="The API key appears verbatim in the response."),
    outcome("security.headers", "clean", None, Status.PASS,
            label="No response header reveals the upstream (informational)."),
    outcome("security.headers", "revealing", None, Status.INFO, Severity.LOW,
            label="Response headers reveal the upstream or proxy (informational)."),
    outcome("security.headers", "unavailable", None, Status.INCONCLUSIVE,
            label="No response headers to inspect."),
    outcome("security.note", "limits", None, Status.INFO,
            label="Prompt logging and shared upstream keys are not provable from outside."),
)


@register
class SecurityDetector(Detector):
    id = "security"
    name = "Transport & secret-handling signals"
    dimension = Dimension.SECURITY
    min_suite = "smoke"
    cost_hint = 1

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        base_url = ctx.target.base_url or ""
        is_https = base_url.strip().lower().startswith("https://")
        local_http = not is_https and _is_local_transport(base_url)
        scheme = base_url.split("://", 1)[0].strip().lower() if "://" in base_url else ""

        # 1) TLS: an http endpoint sends the bearer token in clear text.
        if is_https:
            result.findings.append(
                SCALE.finding(
                    "security.tls",
                    "https",
                    title="Endpoint uses HTTPS",
                    summary="Transport is encrypted; the API key is protected in transit.",
                    evidence={"scheme": "https"},
                )
            )
        elif local_http:
            result.findings.append(
                SCALE.finding(
                    "security.tls",
                    "plain_http_local",
                    title="Endpoint is plain HTTP on a local/private host",
                    summary=(
                        "Endpoint is not HTTPS, but it is on this machine or a private network, "
                        "so the API key does not cross the public internet."
                    ),
                    evidence={
                        "scheme": scheme,
                        "local": True,
                    },
                    recommendation="Use https:// if this endpoint is reachable from other machines.",
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "security.tls",
                    "plain_http",
                    title="Endpoint is not HTTPS",
                    summary="Endpoint is not HTTPS; the API key is sent in clear text.",
                    evidence={"scheme": scheme},
                    recommendation="Use an https:// base_url so the bearer token is not exposed on the wire.",
                )
            )

        # 2) + 3) One small chat call funds both the header-hygiene and key-echo
        # checks. Headers reaching us are already redacted by the client.
        marker = stable_marker("security")
        spec = RequestSpec(
            messages=[
                {"role": "user", "content": prompts.text("security.echo", marker=marker)}
            ],
            temperature=0.0,
            max_tokens=32,
        )
        chat = await ctx.client.complete(spec)

        # 2) Header hygiene — purely informational.
        if chat.headers:
            revealing = {k: v for k, v in chat.headers.items() if _header_matches(k)}
            if revealing:
                result.findings.append(
                    SCALE.finding(
                        "security.headers",
                        "revealing",
                        title="Response leaks upstream/proxy headers",
                        summary=(
                            f"Found {len(revealing)} revealing header(s): "
                            f"{', '.join(sorted(revealing))}. "
                            "Informational — can corroborate the upstream identity, not a failure."
                        ),
                        evidence={"revealing_headers": revealing},
                    )
                )
            else:
                result.findings.append(
                    SCALE.finding(
                        "security.headers",
                        "clean",
                        title="No revealing upstream headers",
                        summary=f"Inspected {len(chat.headers)} response headers; none expose upstream identity.",
                        evidence={"header_count": len(chat.headers)},
                    )
                )
        else:
            result.findings.append(
                SCALE.finding(
                    "security.headers",
                    "unavailable",
                    title="No response headers to inspect",
                    summary=chat.error_message or "Call returned no headers; header hygiene not assessed.",
                    evidence={"status_code": chat.status_code, "error_type": chat.error_type},
                )
            )

        # 3) Secret echo — the key must not appear verbatim in returned text.
        # The client scrubs the configured key to REDACTED_KEY before any relay text
        # reaches us, so the raw key never lands in a report. We detect an echo by the
        # presence of that sentinel; for an atypically short key (not pattern-scrubbed)
        # we fall back to a direct comparison.
        key = ctx.target.api_key or ""
        key_echoed = False
        if key:
            haystacks = [chat.content or "", chat.error_message or ""]
            key_echoed = any(REDACTED_KEY in text for text in haystacks)
            if not key_echoed and len(key) < 6:
                key_echoed = any(contains_ci(text, key) for text in haystacks if text)
            if key_echoed:
                result.findings.append(
                    SCALE.finding(
                        "security.key_echo",
                        "echoed",
                        title="API key reflected in response",
                        summary="The API key appears verbatim in the relay's response; treat the key as exposed.",
                        evidence={"location": "content_or_error"},
                        recommendation="Rotate the key and avoid this relay echoing credentials.",
                    )
                )
            else:
                result.findings.append(
                    SCALE.finding(
                        "security.key_echo",
                        "not_echoed",
                        title="API key not reflected in response",
                        summary="The API key does not appear in the response content or error text.",
                        evidence={},
                    )
                )

        # 4) Limits of black-box inspection — no score impact.
        result.findings.append(
            SCALE.finding(
                "security.note",
                "limits",
                title="Prompt logging & shared upstream keys are not black-box provable",
                summary=(
                    "Whether a relay logs prompts or multiplexes a shared upstream key cannot be "
                    "verified from the client side. Treat the reliability and streaming-timing "
                    "dimensions as indirect signals (e.g. cross-request latency coupling)."
                ),
                evidence={},
            )
        )

        # SCORE: 100 healthy https with no key echo; plain http to a remote host
        # caps at 40 (key on the wire), to a local/private host it is uncapped; a
        # verbatim key echo, the dominant transport-security failure, caps at 30 —
        # the lowest cap wins.
        result.score = SCALE.total(result.findings)
        if key_echoed or not (is_https or local_http):
            result.status = Status.FAIL
        elif local_http:
            result.status = Status.WARN
        else:
            result.status = Status.PASS

        result.evidence["https"] = is_https
        result.evidence["key_present"] = bool(key)
        return result
