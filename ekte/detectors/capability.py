"""Capability-claim verification detector.

Compares the capabilities a model is *claimed* to have (from the resolved KB
profile, when present) against what the relay actually delivers: tool calling,
JSON mode, strict JSON schema, and effective max output. A relay can claim a
premium model yet quietly serve a cheaper substitute that lacks — or, tellingly,
*over*-delivers — these features. Findings stay observation-first; when no
profile is resolved we report observed behavior only and make no downgrade claim.

Budget: up to 4 chat completions.

Each check scores points from the published scale ``SCALE``; the detector score
is the mean of the counted checks. A probe that failed to complete is not
counted, and neither are observations without a claim to verify: no tool call
or no JSON object when the feature is not claimed, and the strict-schema result
when the profile says the model lacks strict schemas. A model is never marked
down for what nobody claimed (a tool call or JSON object that does come back
still passes).
"""

from __future__ import annotations

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import first_json_object
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, RequestSpec, Severity, Status

_NO_RESPONSE = "No usable response to judge by."  # same sentence as protocol's scale

SCALE = Scale(
    outcome("capability.tools", "delivered", 100.0, Status.PASS,
            label="A tool call came back for an explicit tool-use request."),
    outcome("capability.tools", "not_delivered", 0.0, Status.FAIL, Severity.MEDIUM,
            label="Tool calling is claimed but no tool call came back."),
    outcome("capability.tools", "not_claimed", None, Status.INFO,
            label="No tool call came back, and tool calling is not claimed."),
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
    outcome("capability.json_schema", "failed", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
    outcome("capability.max_output", "to_cap", 100.0, Status.PASS,
            label="Output continued up to the requested token cap."),
    outcome("capability.max_output", "plausible", 90.0, Status.PASS,
            label="Output stopped before the cap at a plausible length."),
    outcome("capability.max_output", "stopped_early", 70.0, Status.WARN, Severity.LOW,
            label="Output stopped below a quarter of the requested length."),
    outcome("capability.max_output", "far_below", 60.0, Status.WARN, Severity.LOW,
            label="Output stopped below a quarter of the request despite a large claimed maximum."),
    outcome("capability.max_output", "failed", None, Status.INCONCLUSIVE, Severity.LOW,
            label=_NO_RESPONSE),
)


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
            result.findings.append(
                SCALE.finding(
                    "capability.tools",
                    "failed",
                    title="Tool-calling probe failed to complete",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        call = outcome.tool_calls[0] if outcome.tool_calls else None
        fn = call.get("function") if isinstance(call, dict) else None
        fn_name = fn.get("name") if isinstance(fn, dict) else None
        has_call = bool(fn_name)

        if has_call:
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
                    title="Tool calling delivered",
                    summary=f"Returned a tool call to '{fn_name}'.",
                    evidence=evidence,
                )
            )
            if non_openai_encoding:
                result.findings.append(
                    SCALE.finding(
                        "capability.tools.encoding",
                        "non_openai",
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
                    title="Claimed tool-calling not delivered",
                    summary=(
                        "Profile claims tool-calling support but the relay returned no tool "
                        "call for an explicit tool-use request."
                    ),
                    evidence={"finish_reason": outcome.finish_reason, "had_content": outcome.has_content()},
                    recommendation="Confirm the served engine actually supports function calling.",
                )
            )
        else:
            # No claim to verify against — observed-only.
            result.findings.append(
                SCALE.finding(
                    "capability.tools",
                    "not_claimed",
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
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "failed",
                    title="JSON-mode probe failed to complete",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        parsed = first_json_object(outcome.content)
        value_ok = parsed is not None and parsed.get("value") == 7429

        if parsed is not None and value_ok:
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "delivered",
                    title="JSON mode delivered",
                    summary="response_format=json_object produced a parseable object with the requested value.",
                    evidence={"parsed_keys": sorted(parsed.keys())},
                )
            )
        elif claimed:
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "not_delivered",
                    title="Claimed JSON mode not delivered",
                    summary=(
                        "Profile claims JSON-mode support but the relay did not return a valid "
                        "JSON object carrying the requested value."
                    ),
                    evidence={"parsed": parsed is not None, "value_matched": value_ok},
                    recommendation="Verify the served engine honors response_format=json_object.",
                )
            )
        else:
            result.findings.append(
                SCALE.finding(
                    "capability.json_mode",
                    "value_mismatch" if parsed is not None else "no_json",
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
            result.findings.append(
                SCALE.finding(
                    "capability.json_schema",
                    "failed",
                    title="JSON-schema probe failed to complete",
                    summary=outcome.error_message or f"HTTP {outcome.status_code}",
                    evidence={"status_code": outcome.status_code, "error_type": outcome.error_type},
                )
            )
            return

        parsed = first_json_object(outcome.content)
        enforced = self._matches_person_schema(parsed)

        if model.supports_json_schema:
            if enforced:
                result.findings.append(
                    SCALE.finding(
                        "capability.json_schema",
                        "honored",
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
                        title="Strict JSON schema not enforced (consistent with claim)",
                        summary="Relay did not enforce strict json_schema, consistent with the claimed model.",
                        evidence={"conforms": False},
                    )
                )

    async def _check_max_output(self, ctx, result, model) -> None:
        """Flag gross under-delivery of output length against the claimed max.

        Cost-bounded: we request at most 2048 tokens, so this only catches a model
        that gives up far below the cap, not the full claimed ceiling.
        """
        declared = ctx.declared_max_output()
        cap = min(declared or 2048, 2048)
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
        evidence = {
            "declared_max_output": declared,
            "requested_max_tokens": cap,
            "finish_reason": finish,
            "line_count": line_count,
            "char_count": char_count,
            "note": "probe capped at 2048 tokens; full declared ceiling not exercised",
        }

        if finish == "length":
            # Hit the cap — expected, the model kept producing as asked.
            result.findings.append(
                SCALE.finding(
                    "capability.max_output",
                    "to_cap",
                    title="Sustained output to the request cap",
                    summary=f"Produced ~{line_count} lines and stopped at the {cap}-token cap (finish_reason=length).",
                    evidence=evidence,
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
                    title="Output length plausible",
                    summary=f"Produced ~{line_count} lines (finish_reason={finish}); no gross under-delivery.",
                    evidence=evidence,
                )
            )

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
