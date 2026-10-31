"""Protocol detector — OpenAI-compatibility conformance.

A relay can return content yet still violate the OpenAI chat-completion contract:
forget prior turns, ignore ``stop``, or reject malformed input with a non-standard
error body. (Which request/response attributes survive the relay is checked
attribute by attribute in :mod:`ekte.detectors.protocol_attrs`.) Each sub-check exercises one such
contract and scores points from the published scale ``SCALE`` (every possible
outcome of every check); the detector score is the average of the counted checks.
An inconclusive check (no usable response) is not counted, nor is the stop check
on the Responses API, which has no ``stop`` parameter to honor.
"""

from __future__ import annotations

from ekte import prompts
from ekte.clients import detect_api
from ekte.context import AuditContext
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import contains_ci
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, RequestSpec, Severity, Status

_NO_RESPONSE = "No usable response to judge by."

SCALE = Scale(
    outcome("protocol.multi_turn", "recalled", 100.0, Status.PASS,
            label="The color from an earlier turn was recalled."),
    outcome("protocol.multi_turn", "forgotten", 55.0, Status.WARN, Severity.MEDIUM,
            label="The color from an earlier turn was not recalled."),
    outcome("protocol.multi_turn", "no_content", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
    outcome("protocol.stop", "truncated", 100.0, Status.PASS,
            label="Output stopped at the stop sequence."),
    outcome("protocol.stop", "unconfirmed", 70.0, Status.WARN, Severity.LOW,
            label="Stop handling could not be confirmed from the text."),
    outcome("protocol.stop", "ignored", 60.0, Status.WARN, Severity.LOW,
            label="Text after the stop sequence was returned."),
    outcome("protocol.stop", "no_content", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
    outcome("protocol.stop", "not_applicable", None, Status.INFO,
            label="The Responses API has no stop parameter; not checked, not counted."),
    outcome("protocol.error_schema", "rejected_openai_body", 100.0, Status.PASS,
            label="Rejected with a 4xx and an OpenAI-style error body."),
    outcome("protocol.error_schema", "rejected_other_body", 80.0, Status.WARN, Severity.LOW,
            label="Rejected with a 4xx, but the body is not OpenAI-style."),
    outcome("protocol.error_schema", "no_http_response", 55.0, Status.WARN, Severity.LOW,
            label="No HTTP response; client-error handling could not be confirmed."),
    outcome("protocol.error_schema", "unexpected_status", 55.0, Status.WARN, Severity.LOW,
            label="Another HTTP status; client-error handling could not be confirmed."),
    outcome("protocol.error_schema", "server_error", 35.0, Status.FAIL, Severity.MEDIUM,
            label="The invalid request caused a server error (5xx)."),
    outcome("protocol.error_schema", "accepted", 30.0, Status.FAIL, Severity.MEDIUM,
            label="The invalid request was accepted (2xx)."),
)


@register
class ProtocolDetector(Detector):
    id = "protocol"
    name = "OpenAI-compatibility conformance"
    dimension = Dimension.PROTOCOL
    min_suite = "standard"
    cost_hint = 3

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())

        await self._check_multi_turn(ctx, result)
        await self._check_stop_sequence(ctx, result)
        await self._check_error_schema(ctx, result)

        result.score = Scale.mean(result.findings)
        result.status = Scale.roll_up(result.findings)
        return result

    # 1) Does the relay carry prior turns through to the model? ------------- #
    async def _check_multi_turn(self, ctx: AuditContext, result: DetectorResult) -> None:
        spec = RequestSpec(
            messages=prompts.get("protocol.multi_turn"),
            temperature=0.0,
            max_tokens=16,
        )
        outcome = await ctx.client.complete(spec)
        if not (outcome.ok and outcome.has_content()):
            result.findings.append(
                SCALE.finding(
                    "protocol.multi_turn",
                    "no_content",
                    title="Multi-turn memory check did not return content",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}; no content.",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        recalled = contains_ci(outcome.content, "blue")
        result.findings.append(
            SCALE.finding(
                "protocol.multi_turn",
                "recalled" if recalled else "forgotten",
                title="Multi-turn conversation memory",
                summary=(
                    "Prior turns were honored; the recalled color was returned."
                    if recalled
                    else "Response did not recall the color from earlier turns; "
                    "the relay may be dropping conversation history."
                ),
                evidence={
                    "recalled_blue": recalled,
                    "content_preview": outcome.content[:120],
                },
                recommendation=None
                if recalled
                else "Verify the relay forwards the full messages array to the model.",
            )
        )

    # 2) Is the ``stop`` sequence actually applied? ------------------------- #
    async def _check_stop_sequence(self, ctx: AuditContext, result: DetectorResult) -> None:
        api = detect_api(ctx.target)
        if api == "responses":
            # The Responses API has no ``stop`` parameter (the client drops it), so
            # a relay can't be blamed for text past the stop sequence there.
            result.findings.append(
                SCALE.finding(
                    "protocol.stop",
                    "not_applicable",
                    id="protocol.stop_not_applicable",
                    title="Stop-sequence check not applicable",
                    summary=(
                        "The Responses API has no stop parameter, so stop-sequence "
                        "handling was not checked and is not counted."
                    ),
                    evidence={"api": api},
                )
            )
            return
        spec = RequestSpec(
            messages=[{"role": "user", "content": prompts.text("protocol.stop")}],
            stop="STOP",
            temperature=0.0,
            max_tokens=32,
        )
        outcome = await ctx.client.complete(spec)
        if not (outcome.ok and outcome.has_content()):
            result.findings.append(
                SCALE.finding(
                    "protocol.stop",
                    "no_content",
                    title="Stop-sequence check did not return content",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}; no content.",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        has_alpha = contains_ci(outcome.content, "alpha")
        has_beta = contains_ci(outcome.content, "beta")
        if has_alpha and not has_beta:
            key = "truncated"
            summary = "Output was truncated at the stop sequence as expected."
        elif has_beta:
            key = "ignored"
            summary = "Text after the stop sequence ('beta') was present; stop was ignored."
        else:
            key = "unconfirmed"
            summary = "Could not confirm stop handling from the response text."
        result.findings.append(
            SCALE.finding(
                "protocol.stop",
                key,
                title="Stop-sequence handling",
                summary=summary,
                evidence={
                    "contains_alpha": has_alpha,
                    "contains_beta": has_beta,
                    "finish_reason": outcome.finish_reason,
                    "content_preview": outcome.content[:120],
                },
            )
        )

    # 3) Does a malformed request fail with an OpenAI-style error body? ----- #
    async def _check_error_schema(self, ctx: AuditContext, result: DetectorResult) -> None:
        spec = RequestSpec(messages=[])  # empty messages — deliberately invalid
        outcome = await ctx.client.complete(spec)

        status_code = outcome.status_code
        raw_error = outcome.raw_error
        conforming = isinstance(raw_error, dict) and "error" in raw_error
        # Any client-error (4xx) is a correct rejection of an invalid request — not
        # only the 400-422 subset. The error-body SHAPE is a softer secondary signal.
        is_4xx = status_code is not None and 400 <= status_code <= 499
        is_5xx = status_code is not None and 500 <= status_code <= 599
        accepted = outcome.ok or status_code == 200

        if is_4xx and conforming:
            key = "rejected_openai_body"
            summary = f"Invalid request rejected with HTTP {status_code} and an OpenAI-style error body."
        elif is_4xx:
            key = "rejected_other_body"
            summary = (
                f"Invalid request was correctly rejected with HTTP {status_code}, but the "
                "body is not an OpenAI-style {'error': {...}} object."
            )
        elif accepted:
            key = "accepted"
            summary = "Empty-messages request was accepted (2xx) instead of being rejected."
        elif is_5xx:
            key = "server_error"
            summary = (
                f"Invalid request produced a server error (HTTP {status_code}) rather than a 4xx."
            )
        elif status_code is None:
            key = "no_http_response"
            summary = (
                f"Invalid request got no HTTP response ({outcome.error_type or 'unknown'}); "
                "could not confirm OpenAI-style client-error handling."
            )
        else:
            key = "unexpected_status"
            summary = (
                f"Invalid request produced an unexpected outcome (HTTP {status_code}); could not "
                "confirm OpenAI-style client-error handling."
            )
        result.findings.append(
            SCALE.finding(
                "protocol.error_schema",
                key,
                title="Error response schema",
                summary=summary,
                evidence={
                    "status_code": status_code,
                    "conforming_error_body": conforming,
                    "raw_error_keys": sorted(raw_error.keys()) if isinstance(raw_error, dict) else None,
                    "accepted_invalid": accepted,
                    # set only without an HTTP response (the UI picks its template by it)
                    "error_type": (outcome.error_type or "unknown") if status_code is None else None,
                },
                recommendation=None
                if key == "rejected_openai_body"
                else "A conformant relay should reject invalid input with a 4xx and an "
                "{'error': {...}} body.",
            )
        )

