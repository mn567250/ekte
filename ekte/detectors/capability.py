"""Capability-claim verification detector.

Compares the capabilities a model is *claimed* to have (from the resolved KB
profile, when present) against what the relay actually delivers: tool calling,
JSON mode, strict JSON schema, and effective max output. A relay can claim a
premium model yet quietly serve a cheaper substitute that lacks — or, tellingly,
*over*-delivers — these features. Findings stay observation-first; when no
profile is resolved we report observed behavior only and make no downgrade claim.

Budget: up to 4 chat completions, plus at most one plain control request and,
with a baseline on the same protocol, one baseline request per rejected probe.

Each check scores points from the published scale ``SCALE``; the detector score
is the mean of the counted checks. A probe that failed to complete is not
counted, and neither are observations without a claim to verify: no tool call
or no JSON object when the feature is not claimed, and the strict-schema result
when the profile says the model lacks strict schemas. A model is never marked
down for what nobody claimed (a tool call or JSON object that does come back
still passes).

A relay that answers the tools, JSON-mode or strict-schema probe with a 4xx
(not 401, 403, 408 or 429) although the profile claims the feature has refused
a claimed capability: ``rejected``, counted like ``not_delivered``. It is only
counted when the relay does answer a request without the feature parameter
(else it rejects everything: ``failed``) and a baseline on the same protocol,
if configured, does not reject the probe too (else ``model_limit``).
"""

from __future__ import annotations

from typing import Any

from ekte import errorclass, prompts
from ekte.clients import detect_api
from ekte.context import AuditContext
from ekte.detectors import advice
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import first_json_object, is_reasoning, usage_field
from ekte.detectors.scale import Scale, outcome
from ekte.models import CompletionOutcome, DetectorResult, Dimension, RequestSpec, Severity, Status
from ekte.perf.recorder import usage_tokens
from ekte.utils.tokenize import estimate_tokens

_NO_RESPONSE = "No usable response to judge by."  # same sentence as protocol's scale
_MODEL_LIMIT = "Rejected with a 4xx, and the baseline rejects it too: a limit of the model."
_REJECTED_UNCLAIMED = "Rejected with a 4xx; the capability is not claimed."
# 4xx answers that say nothing about the feature: credentials, policy, the
# relay giving up on time, rate limits.
_NOT_A_REJECTION = frozenset({401, 403, 408, 429})
_PREVIEW = 200
# A max-output answer cut off with finish_reason length counts as reaching the
# cap only when at least this share of the requested tokens came back; below it
# the relay clamped max_tokens (#253).
TO_CAP_SHARE = 0.8
# Reported completion tokens and the text estimate this many times apart (either
# way) are noted in the evidence of a non-reasoning model's max-output finding.
USAGE_MISMATCH_FACTOR = 3.0
REJECTED_ADVICE = (
    "The relay refuses a request parameter the claimed model supports; ask the provider "
    "to forward it, or use an endpoint that serves the feature."
)



def _tool_call(outcome: CompletionOutcome) -> tuple[dict[str, Any] | None, str | None]:
    """The first tool call's ``function`` object and name, if any."""
    call = outcome.tool_calls[0] if outcome.ok and outcome.tool_calls else None
    fn = call.get("function") if isinstance(call, dict) else None
    if not isinstance(fn, dict):
        return None, None
    name = fn.get("name")
    return fn, name if isinstance(name, str) and name else None


def _retry_result(retry: CompletionOutcome) -> str:
    """How a repeat that did not deliver ended, for the finding's evidence."""
    if retry.ok:
        return "not_delivered"
    if retry.status_code is not None and 400 <= retry.status_code < 500:
        return f"rejected (HTTP {retry.status_code})"
    return "failed"


SCALE = Scale(
    outcome("capability.tools", "delivered", 100.0, Status.PASS,
            label="A tool call came back for an explicit tool-use request."),
    outcome("capability.tools", "not_delivered", 0.0, Status.FAIL, Severity.MEDIUM,
            label="Tool calling is claimed but no tool call came back."),
    outcome("capability.tools", "not_claimed", None, Status.INFO,
            label="No tool call came back, and tool calling is not claimed."),
    outcome("capability.tools", "rejected", 0.0, Status.FAIL, Severity.MEDIUM,
            label="Tool calling is claimed but the relay rejected the probe with a 4xx."),
    outcome("capability.tools", "model_limit", None, Status.INFO,
            label=_MODEL_LIMIT),
    outcome("capability.tools", "rejected_unclaimed", None, Status.INFO,
            label=_REJECTED_UNCLAIMED),
    outcome("capability.tools", "failed", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
    outcome("capability.tools.encoding", "non_openai", None, Status.WARN, Severity.LOW,
            label="Tool arguments arrived as an object, not the JSON string OpenAI returns."),
    outcome("capability.json_mode", "delivered", 100.0, Status.PASS,
            label="JSON mode returned a parseable object with the requested value."),
    outcome("capability.json_mode", "value_mismatch", None, Status.INFO,
            label="A JSON object came back with the wrong value; JSON mode is not claimed."),
    outcome("capability.json_mode", "no_json", None, Status.INFO,
            label="No parseable JSON object came back; JSON mode is not claimed."),
    outcome("capability.json_mode", "not_delivered", 0.0, Status.FAIL, Severity.MEDIUM,
            label="JSON mode is claimed but no valid object with the value came back."),
    outcome("capability.json_mode", "rejected", 0.0, Status.FAIL, Severity.MEDIUM,
            label="JSON mode is claimed but the relay rejected the probe with a 4xx."),
    outcome("capability.json_mode", "model_limit", None, Status.INFO,
            label=_MODEL_LIMIT),
    outcome("capability.json_mode", "rejected_unclaimed", None, Status.INFO,
            label=_REJECTED_UNCLAIMED),
    outcome("capability.json_mode", "failed", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
    outcome("capability.json_schema", "honored", 100.0, Status.PASS,
            label="The strict schema is claimed and the response conformed."),
    outcome("capability.json_schema", "absent_as_claimed", None, Status.INFO,
            label="The strict schema was not enforced, consistent with the claim."),
    outcome("capability.json_schema", "over_delivered", None, Status.INFO,
            label="The response conformed although the claimed model lacks strict schemas."),
    outcome("capability.json_schema", "not_enforced", 40.0, Status.WARN, Severity.LOW,
            label="The strict schema is claimed but the response did not conform."),
    outcome("capability.json_schema", "rejected", 0.0, Status.FAIL, Severity.MEDIUM,
            label="The strict schema is claimed but the relay rejected the probe with a 4xx."),
    outcome("capability.json_schema", "model_limit", None, Status.INFO,
            label=_MODEL_LIMIT),
    outcome("capability.json_schema", "rejected_unclaimed", None, Status.INFO,
            label=_REJECTED_UNCLAIMED),
    outcome("capability.json_schema", "failed", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
    outcome("capability.max_output", "to_cap", 100.0, Status.PASS,
            label="Output continued up to the requested token cap."),
    outcome("capability.max_output", "clamped", 0.0, Status.FAIL, Severity.MEDIUM,
            label=(
                "The output was cut off with finish_reason length well below the requested "
                "limit: the relay limits output tokens."
            )),
    outcome("capability.max_output", "plausible", 90.0, Status.PASS,
            label="Output stopped before the cap at a plausible length."),
    outcome("capability.max_output", "stopped_early", 70.0, Status.WARN, Severity.LOW,
            label="Output stopped below a quarter of the requested length."),
    outcome("capability.max_output", "far_below", 60.0, Status.WARN, Severity.LOW,
            label="Output stopped below a quarter of the request despite a large claimed maximum."),
    outcome("capability.max_output", "failed", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
)


# A rejected probe: how prose names its feature, and its result titles.
_FEATURE_NAMES = {
    "capability.tools": "tool calling",
    "capability.json_mode": "JSON mode",
    "capability.json_schema": "strict JSON schemas",
}
_REJECTED_TITLES = {
    "capability.tools": "Claimed tool calling rejected by the relay",
    "capability.json_mode": "Claimed JSON mode rejected by the relay",
    "capability.json_schema": "Claimed strict JSON schema rejected by the relay",
}
_UNCOUNTED_TITLES = {
    "capability.tools": "Tool-calling probe rejected (not counted)",
    "capability.json_mode": "JSON-mode probe rejected (not counted)",
    "capability.json_schema": "JSON-schema probe rejected (not counted)",
}


def is_feature_rejection(out: CompletionOutcome) -> bool:
    """The relay itself answered with a 4xx that can be about the request's
    content: not 401/403 (credentials, policy), 408 (the relay's own timeout) or
    429 (rate limit), and not a failure on ekte's side or the network path."""
    code = out.status_code
    if out.ok or code is None or not 400 <= code <= 499 or code in _NOT_A_REJECTION:
        return False
    return out.error_class not in errorclass.IMPAIRED


@register
class CapabilityDetector(Detector):
    id = "capability"
    name = "Capability-claim verification"
    dimension = Dimension.CAPABILITY
    min_suite = "standard"
    cost_hint = 4

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        model = ctx.profile.model if ctx.profile else None
        result.evidence["has_profile"] = model is not None
        # Whether the relay answers a request without a feature parameter: a
        # probe that came back, or the one plain control request (_rejection).
        self._relay_answers: bool | None = None

        await self._check_tools(ctx, result, model)
        await self._check_json_mode(ctx, result, model)
        await self._check_json_schema(ctx, result, model)
        await self._check_max_output(ctx, result, model)

        result.score = Scale.mean(result.findings)
        result.status = self._roll_up_status(result)
        return result

    # -- sub-checks -------------------------------------------------------- #
    async def _check_tools(self, ctx, result, model) -> None:
        """Probe function/tool calling and inspect the arguments encoding."""
        spec = RequestSpec(
            messages=[
                {
                    "role": "user",
                    "content": prompts.text("capability.tools"),
                }
            ],
            tools=[prompts.get("capability.tools.weather_tool")],
            tool_choice="auto",
            temperature=0.0,
            max_tokens=128,
        )
        outcome = await ctx.client.complete(spec)
        claimed = bool(model and model.supports_tools)

        if not outcome.ok:
            if await self._rejection(ctx, result, spec, outcome, claimed, "capability.tools"):
                return
            result.findings.append(
                SCALE.finding(
                    "capability.tools",
                    "failed",
                    recommendation=advice.failure_advice(outcome),
                    calls=[outcome],
                    title="Tool-calling probe failed to complete",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        self._relay_answers = True
        fn, fn_name = _tool_call(outcome)
        calls = [outcome]
        retry_evidence: dict[str, Any] = {}
        if not fn_name and claimed:
            # Genuine models occasionally answer in text with tool_choice auto:
            # one sample must not decide a MEDIUM finding. Repeat once with the
            # tool forced (Anthropic: {"type": "any"}); a model that rejects
            # forced tool use (4xx) falls back to the first answer.
            forced = spec.model_copy(update={"tool_choice": "required"})
            retry = await ctx.client.complete(forced)
            calls.append(retry)
            r_fn, r_name = _tool_call(retry)
            if retry.ok and r_name:
                outcome, fn, fn_name = retry, r_fn, r_name
                retry_evidence = {"needed_required": True}
            else:
                retry_evidence = {"required_retry": _retry_result(retry)}

        if fn_name:
            # Native OpenAI returns function.arguments as a JSON *string*. A dict
            # here suggests a non-OpenAI engine behind an OpenAI-shaped relay.
            args = fn.get("arguments") if isinstance(fn, dict) else None
            non_openai_encoding = isinstance(args, (dict, list))
            evidence = {
                "tool_name": fn_name,
                "arguments_type": type(args).__name__,
                "non_openai_arguments_encoding": non_openai_encoding,
            }
            result.findings.append(
                SCALE.finding(
                    "capability.tools",
                    "delivered",
                    calls=calls,
                    title="Tool calling delivered",
                    summary=f"Returned a tool call to '{fn_name}'."
                    + (
                        " The first request (tool_choice auto) got a text answer; the "
                        "repeat with tool_choice required got the call."
                        if retry_evidence else ""
                    ),
                    evidence={**evidence, **retry_evidence},
                )
            )
            if non_openai_encoding:
                result.findings.append(
                    SCALE.finding(
                        "capability.tools.encoding",
                        "non_openai",
                        calls=[outcome],
                        title="Non-OpenAI tool arguments encoding",
                        summary=(
                            "function.arguments arrived as a structured object rather than a "
                            "JSON string; genuine OpenAI-compatible APIs return a string "
                            "(possible substitute engine)."
                        ),
                        evidence=evidence,
                    )
                )
        elif claimed:
            result.findings.append(
                SCALE.finding(
                    "capability.tools",
                    "not_delivered",
                    calls=calls,
                    title="Claimed tool-calling not delivered",
                    summary=(
                        "Profile claims tool-calling support but the relay returned no tool "
                        "call for an explicit tool-use request, nor for its repeat with "
                        "tool_choice required."
                    ),
                    evidence={
                        "finish_reason": outcome.finish_reason,
                        "had_content": outcome.has_content(),
                        **retry_evidence,
                    },
                    recommendation="Confirm the served engine actually supports function calling.",
                )
            )
        else:
            # No claim to verify against — observed-only.
            result.findings.append(
                SCALE.finding(
                    "capability.tools",
                    "not_claimed",
                    calls=[outcome],
                    title="No tool call returned",
                    summary="Relay returned no tool call; capability not claimed in any profile.",
                    evidence={"finish_reason": outcome.finish_reason},
                )
            )

    async def _check_json_mode(self, ctx, result, model) -> None:
        """Verify response_format=json_object yields a parseable object."""
        spec = RequestSpec(
            messages=[
                {
                    "role": "user",
                    "content": prompts.text("capability.json_mode"),
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=80,
        )
        outcome = await ctx.client.complete(spec)
        claimed = bool(model and model.supports_json_mode)

        if not outcome.ok:
            if await self._rejection(ctx, result, spec, outcome, claimed, "capability.json_mode"):
                return
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "failed",
                    recommendation=advice.failure_advice(outcome),
                    calls=[outcome],
                    title="JSON-mode probe failed to complete",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        self._relay_answers = True
        parsed = first_json_object(outcome.content)
        value_ok = parsed is not None and parsed.get("value") == 7429
        calls = [outcome]
        retry_evidence: dict[str, Any] = {}
        if not value_ok and claimed:
            # One sample must not decide a MEDIUM finding: repeat once. A repeat
            # that fails to complete falls back to the first answer.
            retry = await ctx.client.complete(spec)
            calls.append(retry)
            r_parsed = first_json_object(retry.content) if retry.ok else None
            if r_parsed is not None and r_parsed.get("value") == 7429:
                outcome, parsed, value_ok = retry, r_parsed, True
                retry_evidence = {"needed_repeat": True}
            else:
                retry_evidence = {"repeat": _retry_result(retry)}

        if parsed is not None and value_ok:
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "delivered",
                    calls=calls,
                    title="JSON mode delivered",
                    summary="response_format=json_object produced a parseable object with the requested value."
                    + (" The first answer did not; its repeat did." if retry_evidence else ""),
                    evidence={"parsed_keys": sorted(parsed.keys()), **retry_evidence},
                )
            )
        elif claimed:
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "not_delivered",
                    calls=calls,
                    title="Claimed JSON mode not delivered",
                    summary=(
                        "Profile claims JSON-mode support but the relay did not return a valid "
                        "JSON object carrying the requested value, twice."
                    ),
                    evidence={"parsed": parsed is not None, "value_matched": value_ok, **retry_evidence},
                    recommendation="Verify the served engine honors response_format=json_object.",
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "value_mismatch" if parsed is not None else "no_json",
                    calls=[outcome],
                    title="JSON mode observed without strong claim",
                    summary=(
                        "Returned a JSON object but value mismatched."
                        if parsed is not None
                        else "No parseable JSON object returned; capability not claimed."
                    ),
                    evidence={"parsed": parsed is not None, "value_matched": value_ok},
                )
            )

    async def _check_json_schema(self, ctx, result, model) -> None:
        """Strict json_schema: verify when claimed; flag over-delivery when not.

        If the model is claimed to support it, verify it works. If the profile
        says the genuine model lacks strict json_schema, a conforming object is
        noted as a faint substitute hint and a non-conforming one as consistent —
        neither is counted. Single call; skipped when we have no profile to
        anchor the claim.
        """
        if model is None:
            return  # Nothing to compare against — skip to stay within budget.

        spec = RequestSpec(
            messages=[
                {
                    "role": "user",
                    "content": prompts.text("capability.json_schema"),
                }
            ],
            response_format=prompts.get("capability.json_schema.person_schema"),
            temperature=0.0,
            max_tokens=80,
        )
        outcome = await ctx.client.complete(spec)

        if not outcome.ok:
            claimed = bool(model.supports_json_schema)
            if await self._rejection(ctx, result, spec, outcome, claimed, "capability.json_schema"):
                return
            result.findings.append(
                SCALE.finding(
                    "capability.json_schema",
                    "failed",
                    recommendation=advice.failure_advice(outcome),
                    calls=[outcome],
                    title="JSON-schema probe failed to complete",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        self._relay_answers = True
        parsed = first_json_object(outcome.content)
        enforced = self._matches_person_schema(parsed)

        if model.supports_json_schema:
            if enforced:
                result.findings.append(
                    SCALE.finding(
                        "capability.json_schema",
                        "honored",
                        calls=[outcome],
                        title="Strict JSON schema honored",
                        summary="Relay returned an object conforming to the strict schema, as claimed.",
                        evidence={"conforms": True},
                    )
                )
            else:
                result.findings.append(
                    SCALE.finding(
                        "capability.json_schema",
                        "not_enforced",
                        calls=[outcome],
                        title="Claimed strict JSON schema not enforced",
                        summary="Profile claims json_schema support but the response did not conform.",
                        evidence={"conforms": False, "parsed": parsed is not None},
                    )
                )
        else:
            # Claimed model does NOT support strict json_schema. A conforming object
            # here is only a faint hint of a substitute: the person schema is trivial
            # enough that plain instruction-following satisfies it without real schema
            # enforcement, so this is INFO-only and never escalates risk on its own.
            if enforced:
                result.findings.append(
                    SCALE.finding(
                        "capability.json_schema",
                        "over_delivered",
                        calls=[outcome],
                        title="Returned a schema-conforming object though claimed model lacks strict json_schema",
                        summary=(
                            "The response conformed to the requested schema even though the claimed "
                            "model is not documented to support strict json_schema. This trivial "
                            "schema is satisfiable by instruction-following alone, so it is not "
                            "reliable substitute evidence — informational only."
                        ),
                        evidence={"conforms": True, "claimed_supports_json_schema": False},
                    )
                )
            else:
                result.findings.append(
                    SCALE.finding(
                        "capability.json_schema",
                        "absent_as_claimed",
                        calls=[outcome],
                        title="Strict JSON schema not enforced (consistent with claim)",
                        summary="Relay did not enforce strict json_schema, consistent with the claimed model.",
                        evidence={"conforms": False},
                    )
                )

    async def _check_max_output(self, ctx, result, model) -> None:
        """Flag a relay that clamps the output, or gross under-delivery of
        output length against the claimed max.

        Cost-bounded: we request at most ``--max-output-probe-tokens`` (2048 by
        default), so this only catches a model or relay that stops far below
        that, not the full claimed ceiling. An answer cut off with
        ``finish_reason: length`` reaches the cap only when at least
        :data:`TO_CAP_SHARE` of the requested tokens came back (reasoning tokens
        count): a relay that clamps ``max_tokens`` also stops with ``length``.
        """
        declared = ctx.declared_max_output()
        probe_cap = max(1, ctx.options.max_output_probe_tokens)
        cap = min(declared or probe_cap, probe_cap)
        spec = RequestSpec(
            messages=[
                {
                    "role": "user",
                    "content": prompts.text("capability.max_output"),
                }
            ],
            temperature=0.0,
            max_tokens=cap,
            reasoning_retry=False,  # stopping at the cap is the effect under test
        )
        outcome = await ctx.client.complete(spec)

        if not outcome.ok:
            result.findings.append(
                SCALE.finding(
                    "capability.max_output",
                    "failed",
                    recommendation=advice.failure_advice(outcome),
                    calls=[outcome],
                    title="Max-output probe failed to complete",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        content = outcome.content or ""
        lines = [ln for ln in content.splitlines() if ln.strip()]
        line_count = len(lines)
        char_count = len(content)
        finish = outcome.finish_reason
        evidence: dict[str, Any] = {
            "declared_max_output": declared,
            "requested_max_tokens": cap,
            "finish_reason": finish,
            "line_count": line_count,
            "char_count": char_count,
            "note": f"probe capped at {probe_cap} tokens; full declared ceiling not exercised",
        }

        if finish == "length":
            delivered, source = self._delivered_tokens(ctx, outcome, content, evidence)
            evidence["delivered_tokens"] = delivered
            evidence["delivered_source"] = source
            evidence["to_cap_share"] = TO_CAP_SHARE
            if delivered is None or delivered >= TO_CAP_SHARE * cap:
                # Hit the cap — expected, the model kept producing as asked.
                result.findings.append(
                    SCALE.finding(
                        "capability.max_output",
                        "to_cap",
                        calls=[outcome],
                        title="Sustained output to the request cap",
                        summary=(
                            f"Produced ~{line_count} lines"
                            + (f" (~{delivered} tokens)" if delivered is not None else "")
                            + f" and stopped at the {cap}-token cap (finish_reason=length)."
                        ),
                        evidence=evidence,
                    )
                )
            else:
                result.findings.append(
                    SCALE.finding(
                        "capability.max_output",
                        "clamped",
                        calls=[outcome],
                        title="Output clamped below the requested limit",
                        summary=(
                            f"Cut off (finish_reason=length) at ~{delivered} of the requested "
                            f"{cap} tokens ({source}): the relay limits output tokens."
                        ),
                        evidence=evidence,
                        recommendation=(
                            "The relay caps max_tokens below what was requested; long answers "
                            "will be truncated. Ask the provider to forward max_tokens, or use "
                            "an endpoint that honors it."
                        ),
                    )
                )
            return

        # Stopped early. Gauge how far below the cap by a rough token estimate.
        produced_ratio = (char_count / 4) / cap if cap else 0.0
        large_claim = bool(declared and declared >= 4096)

        if produced_ratio < 0.25 and large_claim:
            # LOW, not MEDIUM: a 2048-token probe is weak evidence — models stop
            # early on tedious tasks for benign reasons, so this must not escalate
            # overall risk on its own.
            result.findings.append(
                SCALE.finding(
                    "capability.max_output",
                    "far_below",
                    calls=[outcome],
                    title="Output stopped far below requested length",
                    summary=(
                        f"Model gave up early (finish_reason={finish}) at roughly "
                        f"{produced_ratio*100:.0f}% of the {cap}-token request despite a large "
                        f"declared max_output of {declared}. Weak signal (short probe)."
                    ),
                    evidence=evidence,
                    recommendation="Long-form generation may under-deliver relative to the claimed ceiling; confirm with a longer probe.",
                )
            )
        elif produced_ratio < 0.25:
            result.findings.append(
                SCALE.finding(
                    "capability.max_output",
                    "stopped_early",
                    calls=[outcome],
                    title="Output stopped early",
                    summary=f"Model stopped early (finish_reason={finish}) at ~{produced_ratio*100:.0f}% of the request cap.",
                    evidence=evidence,
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "capability.max_output",
                    "plausible",
                    calls=[outcome],
                    title="Output length plausible",
                    summary=f"Produced ~{line_count} lines (finish_reason={finish}); no gross under-delivery.",
                    evidence=evidence,
                )
            )

    @staticmethod
    def _delivered_tokens(
        ctx: AuditContext, out: CompletionOutcome, content: str, evidence: dict[str, Any]
    ) -> tuple[int | None, str]:
        """Tokens an answer cut off by ``length`` delivered, and where the count
        comes from: the reported completion tokens when present, else an
        estimate from the text. For a reasoning model the reasoning tokens count
        as delivered (they spend the same budget), and without any usage the
        count is unknown (None); a non-reasoning model whose
        reported count and text estimate are more than
        :data:`USAGE_MISMATCH_FACTOR` apart gets that noted in ``evidence``."""
        reported = usage_field(out.usage, "completion_tokens", "output_tokens")
        reasoning_tokens = usage_tokens(out.usage)["reasoning"] or 0
        reasoning = is_reasoning(ctx, out)
        estimated = estimate_tokens(content)
        evidence["reported_completion_tokens"] = reported
        evidence["estimated_text_tokens"] = estimated
        if reasoning:
            evidence["reasoning_tokens"] = reasoning_tokens or None
        if reported is not None:
            delivered, source = reported, "reported completion tokens"
            # completion_tokens normally includes the reasoning tokens; a relay
            # that reports them apart must not look clamped for thinking.
            if reasoning and reasoning_tokens + estimated > delivered:
                delivered = reasoning_tokens + estimated
                source = "reasoning tokens + text estimate"
        elif reasoning and reasoning_tokens:
            delivered, source = reasoning_tokens + estimated, "reasoning tokens + text estimate"
        elif reasoning:
            # No usage at all: the hidden reasoning cannot be counted, so a
            # short visible answer says nothing about a clamp.
            return None, "not countable (reasoning model without usage)"
        else:
            delivered, source = estimated, "text estimate"
        if not reasoning and reported is not None:
            hi, lo = max(reported, estimated), max(1, min(reported, estimated))
            if hi > USAGE_MISMATCH_FACTOR * lo:
                evidence["usage_text_mismatch"] = round(hi / lo, 1)
        return delivered, source

    # -- rejected probes --------------------------------------------------- #
    async def _rejection(
        self,
        ctx: AuditContext,
        result: DetectorResult,
        spec: RequestSpec,
        out: CompletionOutcome,
        claimed: bool,
        check: str,
    ) -> bool:
        """Report a probe the relay rejected with a 4xx. False when ``out`` is no
        such rejection or the relay rejects a plain request too: the caller then
        reports ``failed``."""
        if not is_feature_rejection(out):
            return False
        name = _FEATURE_NAMES[check]
        error = (out.error_message or "").strip()[:_PREVIEW] or "no error message"
        evidence: dict[str, Any] = {
            "status_code": out.status_code,
            "error_type": out.error_type,
            "relay_error": error,
            "claimed": claimed,
        }
        calls = [out]
        if not claimed:
            result.findings.append(
                SCALE.finding(
                    check,
                    "rejected_unclaimed",
                    calls=calls,
                    title=_UNCOUNTED_TITLES[check],
                    summary=(
                        f"The relay rejected the {name} probe with HTTP {out.status_code}: {error}. "
                        f"The profile does not claim {name}, so this is not counted."
                    ),
                    evidence=evidence,
                )
            )
            return True

        base = await self._baseline_probe(ctx, spec)
        if base is not None:
            evidence["baseline_status_code"] = base.status_code
            calls.append(base)
            # An answer or a feature rejection is a usable comparison.
            if base.ok or is_feature_rejection(base):
                result.baseline_compared = True
            if is_feature_rejection(base):
                result.findings.append(
                    SCALE.finding(
                        check,
                        "model_limit",
                        calls=calls,
                        title=_UNCOUNTED_TITLES[check],
                        summary=(
                            f"The relay rejected the {name} probe with HTTP {out.status_code}: {error}. "
                            f"The baseline rejects it too (HTTP {base.status_code}): a limit of the "
                            "model, not of the relay, so this is not counted."
                        ),
                        evidence=evidence,
                    )
                )
                return True

        if not await self._relay_answers_plain(ctx, spec, evidence, calls):
            return False
        result.findings.append(
            SCALE.finding(
                check,
                "rejected",
                calls=calls,
                title=_REJECTED_TITLES[check],
                summary=(
                    f"The profile claims {name}, but the relay rejected the probe with "
                    f"HTTP {out.status_code}: {error}"
                ),
                evidence=evidence,
                recommendation=REJECTED_ADVICE,
            )
        )
        return True

    async def _relay_answers_plain(
        self,
        ctx: AuditContext,
        spec: RequestSpec,
        evidence: dict[str, Any],
        calls: list[CompletionOutcome],
    ) -> bool:
        """Whether the relay answers a request at all: known once a probe of
        this run came back, else asked once with ``spec`` minus its feature
        parameters."""
        if self._relay_answers is None:
            plain = spec.model_copy(update={"tools": None, "tool_choice": None, "response_format": None})
            control = await ctx.client.complete(plain)
            self._relay_answers = control.ok
            evidence["plain_status_code"] = control.status_code
            calls.append(control)
        return bool(self._relay_answers)

    @staticmethod
    async def _baseline_probe(ctx: AuditContext, spec: RequestSpec) -> CompletionOutcome | None:
        """The same probe against the baseline, when one speaks the target's
        protocol; None otherwise."""
        if ctx.baseline_client is None or ctx.baseline is None:
            return None
        if detect_api(ctx.baseline) != detect_api(ctx.target):
            return None
        return await ctx.baseline_client.complete(spec)

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _matches_person_schema(parsed) -> bool:
        """True only if ``parsed`` strictly conforms to the person schema."""
        if not isinstance(parsed, dict):
            return False
        if set(parsed.keys()) != {"name", "age"}:
            return False
        return isinstance(parsed.get("name"), str) and isinstance(parsed.get("age"), int) and not isinstance(
            parsed.get("age"), bool
        )

    @staticmethod
    def _roll_up_status(result: DetectorResult) -> Status:
        """Derive the detector status from the worst sub-check finding."""
        statuses = {f.status for f in result.findings}
        if Status.FAIL in statuses:
            return Status.FAIL
        if Status.WARN in statuses:
            return Status.WARN
        if statuses & {Status.PASS}:
            return Status.PASS
        if statuses and statuses <= {Status.INFO}:
            return Status.INFO
        return Status.INCONCLUSIVE
