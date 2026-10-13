"""Real context window & truncation detector — the headline check.

Measures the largest prompt the relay can actually ingest and recall a needle
from, and compares it to the advertised context window. A relay that silently
truncates, summarizes, or RAG-shims long prompts will recall well below its
claim, or fail a needle buried in the middle while passing start and end. A
server that keeps only the END of an over-long prompt (a local runtime cutting
the prompt to its configured context length) still recalls a needle near the
end, so each size is decided at the START edge first. zing reports the measured
divergence; it never asserts fraud outright.

The probe never exceeds the *probed window* ``upper = min(declared, cap)``
(``--max-context-tokens``), and every rung stays at or below 90% of it, leaving
room for the answer and the chat template. Sizes are budgets of REAL tokens: the
haystack is built smaller by zing's heuristic count (see
``_HEURISTIC_UNDERCOUNT``) so a real tokenizer stays within the rung.

Scoring follows the published ``SCALE`` (method "deductions"): the score starts
at 100, the window verdict deducts the share of the top rung (90% of the probed
window) that did not recall, and a needle lost in the middle (confirmed with a
fresh needle) deducts 15. Recall at the top rung of a window capped below the
declared one is verified only up to the cap, never read as truncation. Without a
declared window the measurement is reported but not scored; errors (a rejected
parameter, HTTP errors, 5xx) and timeouts end the ladder as inconclusive, never
as a recall failure.
"""

from __future__ import annotations

import asyncio

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.helpers import build_filler, contains_ci, stable_marker
from zing.detectors.scale import DeductionScale, outcome
from zing.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    RequestSpec,
    Severity,
    Status,
)
from zing.utils.tokenize import estimate_tokens

# A 4xx whose body mentions one of these context-specific phrases is the relay
# rejecting the prompt for SIZE — strong evidence of where the real ceiling sits.
# Kept deliberately narrow: bare "length"/"token"/"max_tokens" also appear in
# parameter-validation errors (see _PARAM_REJECTION_HINTS), which must NOT be read
# as a context ceiling or an honest reasoning model would be flagged truncated.
_CONTEXT_ERROR_HINTS = (
    "context length",
    "context_length",
    "context window",
    "context_length_exceeded",
    "maximum context",
    "exceeds the context",
    "reduce the length of the messages",
    "too many tokens",
)

# A 4xx complaining about a request PARAMETER (not the prompt size). Reasoning
# models reject "max_tokens" and require "max_completion_tokens"; that is a
# parameter mismatch, not a context truncation, and must stay inconclusive.
_PARAM_REJECTION_HINTS = (
    "max_tokens",
    "max_completion_tokens",
    "unsupported parameter",
    "unsupported value",
    "unknown parameter",
    "is not supported",
    "use 'max_completion_tokens'",
)


_LOST_IN_MIDDLE_DEDUCTION = 15.0

# Every rung stays at or below this share of the probed window: the rest is room
# for the answer (64 output tokens), the chat template and the needle question.
_TOP_RUNG_SHARE = 0.9
# The ladder halves down from the top rung, at most this many sizes.
_MAX_RUNGS = 7
# The smallest rung a small window may drop to below the configured floor (a
# 2K-token window still gets a three-rung ladder: ~1.8K, ~920, ~460).
_MIN_RUNG = 256
# zing's stdlib heuristic (zing/utils/tokenize.py) under-counts this filler by
# ~12% (o200k) to ~15% (cl100k) against real tokenizers, so a haystack sized by
# the heuristic alone would overshoot its rung. Each haystack is built at
# size / 1.2 heuristic tokens, so its real token count stays within the rung.
_HEURISTIC_UNDERCOUNT = 1.2
# What "tokens" means in this detector's sizes and evidence.
_TOKEN_UNIT = (
    "rung sizes are budgets of real prompt tokens; each haystack is built at "
    "size / 1.2 by zing's heuristic count, which under-counts real tokenizers by ~12-15%"
)

# Statuses of a probe that produced no answer to judge: a rejected parameter, an
# HTTP error, a 5xx / transport / malformed response. Inconclusive, never a miss.
_ERROR_STATUSES = frozenset({"param_error", "http_error", "error"})

SCALE = DeductionScale(
    outcome("context_window.window", "consistent", None, Status.PASS,
            label="Recall held at the top rung (90% of the probed window): no deduction."),
    outcome("context_window.window", "verified_to_cap", None, Status.PASS,
            label="Recall verified up to the probe cap; the declared window above it "
                  "was not exercised."),
    outcome("context_window.window", "short", None, Status.WARN, Severity.MEDIUM,
            max_deduction=50.0,
            label="Recall held up to 50-90% of the probed window; deducts the share of "
                  "the top rung that did not recall."),
    outcome("context_window.window", "truncated", None, Status.FAIL, Severity.HIGH,
            max_deduction=100.0,
            label="Recall failed below half of the probed window; deducts the share of "
                  "the top rung that did not recall."),
    outcome("context_window.window", "no_recall", None, Status.FAIL, Severity.HIGH,
            deduction=100.0, label="Not even the smallest probe size recalled the needle."),
    outcome("context_window.lost_in_middle", "lost", None, Status.WARN, Severity.MEDIUM,
            deduction=_LOST_IN_MIDDLE_DEDUCTION,
            label="The start and end were recalled but the middle was not, twice."),
    outcome("context_window.rejected_below_claim", "rejected", None, Status.FAIL, Severity.HIGH,
            label="A prompt well below the declared window was rejected as too long."),
    outcome("context_window.measured", "no_claim", None, Status.INFO,
            label="No declared window to compare against: measured only, not scored."),
    outcome("context_window.no_ladder", "no_sizes", None, Status.INCONCLUSIVE, Severity.LOW,
            label="No probe size fit between the floor and the cap."),
    outcome("context_window.timed_out", "timeout", None, Status.INCONCLUSIVE, Severity.LOW,
            label="A probe timed out before the declared window was reached: "
                  "a slow endpoint, not evidence of truncation."),
    outcome("context_window.probe_error", "error", None, Status.INCONCLUSIVE, Severity.LOW,
            label="A probe was answered with an error (a rejected parameter, an HTTP or "
                  "server error) before the top rung: not evidence of truncation."),
    titles={"context_window.window": "Effective context window"},
)


def _front_note(size: int) -> str:
    """The sentence a verdict summary gains when the window ended on front
    truncation (the start of a prompt dropped while its end was recalled)."""
    return (
        f" The start of a ~{size}-token prompt was dropped while its end was still "
        "recalled (front truncation)."
    )



def _window_deduction(share: float) -> float:
    """Points the window verdict takes off: the unrecalled share of the top rung
    (rounded like the score itself)."""
    return round(100.0 - round(min(1.0, share) * 100, 1), 1)


def _heuristic_size(size: int) -> int:
    """The heuristic token count a ``size``-token rung's haystack is built at."""
    return max(1, int(size / _HEURISTIC_UNDERCOUNT))


def _build_haystack(size: int, *, needle: str, depth: float, tokenizer: str | None) -> str:
    """A full probe prompt (filler, the needle at fractional ``depth``, the
    question) whose heuristic count stays within ``_heuristic_size(size)``.

    Unlike ``helpers.build_haystack`` the budget is a ceiling: the shared filler
    grows in 50-line steps (hundreds of tokens past a small target), so it is
    trimmed back line by line, and the needle and question count against it.
    """
    needle_line = prompts.text("context_window.needle", needle=needle)
    question = prompts.text("context_window.question")
    budget = _heuristic_size(size) - estimate_tokens(needle_line + "\n" + question, tokenizer)
    lines: list[str] = []
    total = 0
    for line in build_filler(max(1, budget), tokenizer).split("\n"):
        total += estimate_tokens(line if not lines else "\n" + line, tokenizer)
        if total > budget and lines:
            break
        lines.append(line)
    lines.insert(int(len(lines) * max(0.0, min(1.0, depth))), needle_line)
    return "\n".join(lines) + question


@register
class ContextWindowDetector(Detector):
    id = "context_window"
    name = "Real context window & truncation"
    dimension = Dimension.CONTEXT_WINDOW
    min_suite = "deep"
    cost_hint = 14

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        tokenizer = ctx.tokenizer_hint()

        declared = ctx.declared_context_window()
        cap = ctx.options.max_context_probe_tokens
        floor = ctx.options.context_probe_floor_tokens
        # The probed window: the declared one, or the probe cap when that is lower.
        upper = min(declared, cap) if declared else cap
        capped = bool(declared and declared > cap)

        ladder_sizes = self._ladder(floor, upper)
        if not ladder_sizes:
            result.findings.append(
                SCALE.finding(
                    "context_window.no_ladder",
                    "no_sizes",
                    title="Context-window probe could not run",
                    summary=f"No probe sizes fit between floor and cap (upper={upper}).",
                    evidence={"declared": declared, "upper": upper, "probe_cap": cap, "floor": floor},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
            return result
        top = ladder_sizes[-1]

        # Reasoning models reject max_tokens and require max_completion_tokens; probe
        # them accordingly so a 400 isn't misread as a context ceiling.
        reasoning = bool(ctx.profile and getattr(ctx.profile.model, "reasoning", False))

        # --- Ascending ladder: find the largest recalling size and the first
        # failing/rejected size above it. Stop after the first failure. Each size is
        # probed at the START edge and a miss is confirmed before it counts. ------ #
        ladder_log: list[dict] = []
        calls = 0
        effective_window: int | None = None
        last_pass: int | None = None
        first_fail: int | None = None
        rejected_at: int | None = None
        # A timeout says the endpoint is slow at this size, not that it truncates:
        # it ends the ladder without counting as a failure.
        timed_out_at: int | None = None
        # Likewise an error answer (a rejected parameter, an HTTP or server error):
        # there was no answer to judge, so it ends the ladder as inconclusive.
        errored_at: int | None = None
        errors: list[dict] = []
        # The smallest size whose start was dropped while its end was recalled.
        front_truncated_at: int | None = None

        def log(size: int, recalled: bool, rejected: bool, status: str, **extra) -> None:
            ladder_log.append(
                {
                    "size": size,
                    "heuristic_tokens": _heuristic_size(size),
                    "recalled": recalled,
                    "rejected": rejected,
                    "status": status,
                    **extra,
                }
            )

        for size in ladder_sizes:
            recalled, rejected, status, n = await self._probe_size(
                ctx, size, tokenizer=tokenizer, reasoning=reasoning, errors=errors
            )
            calls += n
            log(size, recalled, rejected, status)
            if recalled:
                last_pass = size
                effective_window = size
                continue
            if status == "timeout":
                timed_out_at = size
                break
            if status in _ERROR_STATUSES:
                errored_at = size
                break
            if status == "front_truncated":
                front_truncated_at = size
            # First confirmed non-recall (a clean fail or a size rejection).
            first_fail = size
            if rejected:
                rejected_at = size
            break

        # --- One binary-search refine between last pass and first failure. A
        # timeout or error here leaves the bounds as they are. ------------------ #
        if last_pass is not None and first_fail is not None and first_fail > last_pass:
            mid = (last_pass + first_fail) // 2
            if last_pass < mid < first_fail:
                recalled, rejected, status, n = await self._probe_size(
                    ctx, mid, tokenizer=tokenizer, reasoning=reasoning, errors=errors
                )
                calls += n
                log(mid, recalled, rejected, status, refine=True)
                if recalled:
                    last_pass = mid
                    effective_window = mid
                elif rejected and rejected_at is None:
                    rejected_at = mid
                elif status == "front_truncated":
                    front_truncated_at = mid

        # --- Lost-in-the-middle at a mid size (depths 0.1 / 0.5 / 0.9). ------- #
        depth_results: dict[str, bool | None] = {}
        mid_size = min(32_000, effective_window or 16_000)
        stopped_at = timed_out_at if timed_out_at is not None else errored_at
        # Only worth spending calls if the mid size is at/below what we know works.
        if (
            mid_size >= floor
            and (effective_window is None or mid_size <= effective_window)
            and (stopped_at is None or mid_size < stopped_at)
        ):
            for depth in (0.1, 0.5, 0.9):
                depth_results[f"{depth:.1f}"], n = await self._probe_depth(
                    ctx, mid_size, depth, tokenizer=tokenizer, reasoning=reasoning
                )
                calls += n
            start_ok = depth_results.get("0.1") is True
            end_ok = depth_results.get("0.9") is True
            if start_ok and end_ok and depth_results.get("0.5") is False:
                # One missed middle needle may be a benign paraphrase: confirm it
                # with a fresh needle before calling it lost.
                depth_results["0.5_retry"], n = await self._probe_depth(
                    ctx, mid_size, 0.5, tokenizer=tokenizer, reasoning=reasoning, attempt=1
                )
                calls += n
            if start_ok and end_ok and depth_results.get("0.5_retry") is False:
                result.findings.append(
                    SCALE.finding(
                        "context_window.lost_in_middle",
                        "lost",
                        title="Needle in the middle was not recalled",
                        summary=(
                            "Start and end of the prompt were recalled but the middle "
                            "was not, twice with fresh needles (lost-in-the-middle; cheap "
                            "RAG/summarization shim suspected)."
                        ),
                        evidence={"mid_size": mid_size, "depth_results": depth_results},
                        recommendation="Compare against a trusted baseline to confirm.",
                    )
                )
                result.status = Status.WARN

        # --- Verdicts ---------------------------------------------------------- #
        # A window that ended on front truncation says so in its verdict; the
        # evidence keys exist only then (the UI's translated templates key on them).
        front_ev: dict = (
            {"front_truncated": True, "front_truncated_at": front_truncated_at}
            if front_truncated_at is not None
            else {}
        )
        front_note = _front_note(front_truncated_at) if front_truncated_at is not None else ""
        if rejected_at is not None and declared and rejected_at < 0.9 * declared:
            result.findings.append(
                SCALE.finding(
                    "context_window.rejected_below_claim",
                    "rejected",
                    title="Endpoint rejects context below its advertised window",
                    summary=(
                        f"A ~{rejected_at}-token prompt was rejected with a context-length "
                        f"error, well below the declared {declared}-token window."
                    ),
                    evidence={"declared": declared, "rejected_at": rejected_at},
                    recommendation="Treat the advertised context window as unverified.",
                )
            )

        verified = (
            f"recall verified up to ~{effective_window} tokens"
            if effective_window
            else "no size could be verified"
        )
        # The ladder stopped on a timeout or an error answer below the top rung:
        # the window is unverified, so report that instead of a window verdict.
        if timed_out_at is not None:
            result.findings.append(
                SCALE.finding(
                    "context_window.timed_out",
                    "timeout",
                    title="Context-window probe timed out",
                    summary=(
                        f"A ~{timed_out_at}-token probe timed out; {verified}. A slow "
                        "endpoint, not evidence of truncation."
                    ),
                    evidence={
                        "declared": declared,
                        "timed_out_at": timed_out_at,
                        "effective_window": effective_window,
                    },
                    recommendation=(
                        "Raise --timeout / --max-request-time, or lower --max-context-tokens, "
                        "to measure the full window."
                    ),
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
        elif errored_at is not None:
            err = errors[-1] if errors else {}
            detail = err.get("error_message") or err.get("error_status") or "error"
            code = f"HTTP {err['status_code']}: " if err.get("status_code") else ""
            result.findings.append(
                SCALE.finding(
                    "context_window.probe_error",
                    "error",
                    title="Context-window probe answered with an error",
                    summary=(
                        f"A ~{errored_at}-token probe was answered with an error "
                        f"({code}{detail}); {verified}. Not evidence of truncation."
                    ),
                    evidence={
                        "declared": declared,
                        "errored_at": errored_at,
                        "effective_window": effective_window,
                        **err,
                    },
                    recommendation=(
                        "Check the error (e.g. a request parameter this endpoint rejects) "
                        "and re-run to measure the window."
                    ),
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
        elif declared:
            measured = effective_window or 0
            # Judged against the probed window, never the part above the cap.
            ratio = measured / upper
            window_ev = {
                "declared": declared,
                "upper": upper,
                "probe_cap": cap,
                "top_rung": top,
                "effective_window": measured,
                "ratio": round(ratio, 3),
                "tokens": _TOKEN_UNIT,
            }
            claim = (
                f"the probed {upper} (declared {declared}, capped by --max-context-tokens)"
                if capped
                else f"the declared {declared}"
            )
            if effective_window is None:
                # Even the smallest ladder rung did not recall — nothing usable.
                result.findings.append(
                    SCALE.finding(
                        "context_window.window",
                        "no_recall",
                        id="context_window.no_recall",
                        title="No probe size recalled the needle",
                        summary=(
                            f"Even a ~{ladder_sizes[0]}-token prompt failed recall; the "
                            f"usable window appears far below the declared {declared}."
                            + front_note
                        ),
                        evidence={
                            "declared": declared,
                            "upper": upper,
                            "probe_cap": cap,
                            "smallest_probed": ladder_sizes[0],
                            **front_ev,
                        },
                    )
                )
                result.status = Status.FAIL
            elif ratio < 0.5:
                result.findings.append(
                    SCALE.finding(
                        "context_window.window",
                        "truncated",
                        id="context_window.truncation",
                        deduction=_window_deduction(measured / top),
                        title="Real context window far below the declared one",
                        summary=(
                            f"Real context window ~{measured} << {claim} "
                            f"(silent truncation suspected)." + front_note
                        ),
                        evidence={**window_ev, **front_ev},
                        recommendation=(
                            "The server silently drops the start of long prompts; raise its "
                            "context-length setting or treat the declared window as unverified."
                            if front_ev
                            else "The relay likely truncates or summarizes long prompts."
                        ),
                    )
                )
                result.status = Status.FAIL
            elif measured < top:
                result.findings.append(
                    SCALE.finding(
                        "context_window.window",
                        "short",
                        id="context_window.short",
                        deduction=_window_deduction(measured / top),
                        title="Real context window below the declared one",
                        summary=(
                            f"Real context window ~{measured} is below {claim} "
                            f"(recall degrades before the advertised limit)." + front_note
                        ),
                        evidence={**window_ev, **front_ev},
                    )
                )
                result.status = Status.WARN if result.status != Status.FAIL else result.status
            elif capped:
                # Full recall up to the cap: the window above it was never sent.
                result.findings.append(
                    SCALE.finding(
                        "context_window.window",
                        "verified_to_cap",
                        id="context_window.verified_to_cap",
                        title="Context window verified up to the probe cap",
                        summary=(
                            f"Recalled a needle at ~{measured} tokens, the top rung below the "
                            f"{cap}-token probe cap; the declared {declared}-token window "
                            "above it was not exercised."
                        ),
                        evidence=window_ev,
                        recommendation=(
                            "Raise --max-context-tokens to exercise the full declared window."
                        ),
                    )
                )
                if result.status not in (Status.FAIL, Status.WARN):
                    result.status = Status.PASS
            else:
                result.findings.append(
                    SCALE.finding(
                        "context_window.window",
                        "consistent",
                        id="context_window.consistent",
                        title="Measured context window consistent with the claim",
                        summary=(
                            f"Recalled a needle at ~{measured} tokens, the top rung (90%) of "
                            f"the declared {declared}-token window."
                        ),
                        evidence=window_ev,
                    )
                )
                if result.status not in (Status.FAIL, Status.WARN):
                    result.status = Status.PASS

            result.score = SCALE.total(result.findings)
        else:
            # Declared window unknown — report the measurement, do not score.
            result.findings.append(
                SCALE.finding(
                    "context_window.measured",
                    "no_claim",
                    title="Measured effective context window",
                    summary=(
                        f"No declared context window to compare against; measured "
                        f"effective window ~{effective_window or '<' + str(ladder_sizes[0])} tokens."
                        + front_note
                    ),
                    evidence={
                        "declared": None,
                        "upper": upper,
                        "effective_window": effective_window,
                        **front_ev,
                    },
                )
            )
            result.status = Status.INFO
            result.score = None

        result.evidence.update(
            {
                "declared": declared,
                "upper": upper,
                "probe_cap": cap,
                "top_rung": top,
                "tokens": _TOKEN_UNIT,
                "effective_window": effective_window,
                "timed_out_at": timed_out_at,
                "errored_at": errored_at,
                "front_truncated_at": front_truncated_at,
                "ladder": ladder_log,
                "depth_results": depth_results,
                "calls": calls,
            }
        )
        return result

    # -- internals ---------------------------------------------------------- #
    @staticmethod
    def _ladder(floor: int, upper: int) -> list[int]:
        """Ascending ladder halving down from a top rung at 90% of ``upper``.

        Every rung stays at or below ``_TOP_RUNG_SHARE`` of the probed window
        (room for the answer and the chat template), the top rung is always that
        90% rung, and halving (rather than doubling up from a floor) keeps a rung
        from landing on the full window. At most ``_MAX_RUNGS`` sizes, none below
        ``floor`` — except that a small window lowers the floor (to a quarter of
        the top rung, not below ``_MIN_RUNG``) so it still gets a few rungs.
        """
        top = int(upper * _TOP_RUNG_SHARE)
        if top < _MIN_RUNG:
            return []
        low = min(floor, max(_MIN_RUNG, top // 4))
        sizes = [top]
        while len(sizes) < _MAX_RUNGS and sizes[-1] // 2 >= low:
            sizes.append(sizes[-1] // 2)
        return sorted(sizes)

    async def _probe_size(
        self,
        ctx: AuditContext,
        size: int,
        *,
        tokenizer: str | None,
        reasoning: bool,
        errors: list[dict] | None = None,
    ) -> tuple[bool, bool, str, int]:
        """Decide recall at ``size``, START edge first.

        Returns ``(recalled, rejected_for_size, status, calls)``. A truncated prompt
        whose trailing question survives can only have lost its START (a server
        cutting the prompt to its context length keeps the end), so the start edge
        (depth 0.0) decides: recalled there, the size passes in one call.

        A single missed needle is not enough to declare a size failed (a benign
        paraphrase or a dropped marker would falsely shrink the window and drive a
        HIGH truncation verdict), so a start miss is checked at the end edge (0.95):
        missed there too, the size fails. Recalled at the end, the start is probed
        once more with a fresh needle: recalled now, the first miss was a one-off
        and the size passes; missed again, the server drops the start of the prompt
        and the size fails as ``"front_truncated"``. At most three calls per size.
        A clear size-rejection, a timeout or an error answer (one of
        ``_ERROR_STATUSES``: nothing to judge, so never a miss) ends the size on the
        first hit; an error's details are appended to ``errors``.
        """
        calls = 0
        status = "no_recall"
        # (depth, attempt): start, end, then the start again with a fresh needle.
        for depth, attempt in ((0.0, 0), (0.95, 0), (0.0, 1)):
            outcome = await self._probe(
                ctx, size, depth=depth, tokenizer=tokenizer, reasoning=reasoning, attempt=attempt
            )
            calls += 1
            recalled, rejected, status = self._classify(outcome, size)
            if recalled and depth == 0.0:
                return True, False, status, calls
            if status in _ERROR_STATUSES:
                if errors is not None:
                    errors.append(self._error_info(outcome, status))
                return False, False, status, calls
            if rejected or status == "timeout":
                # A timeout at one edge would time out at the other too.
                return False, rejected, status, calls
            if depth == 0.95 and not recalled:
                # Missed at both edges: a plain failure.
                return False, False, status, calls
            # else a start miss (try the end edge) or an end recall (re-probe the start).
        # The end recalled but the start missed twice (clean answers without the
        # needle: an error would have returned above): front truncation.
        return False, False, "front_truncated", calls

    async def _probe_depth(
        self,
        ctx: AuditContext,
        size: int,
        depth: float,
        *,
        tokenizer: str | None,
        reasoning: bool,
        attempt: int = 0,
    ) -> tuple[bool | None, int]:
        """One lost-in-the-middle probe: ``(recalled, calls)``. A timeout or an
        error answer is unknown (``None``), not a lost needle."""
        outcome = await self._probe(
            ctx, size, depth=depth, tokenizer=tokenizer, reasoning=reasoning, attempt=attempt
        )
        recalled, _, status = self._classify(outcome, size)
        if status == "timeout" or status in _ERROR_STATUSES:
            return None, 1
        return recalled, 1

    @staticmethod
    def _error_info(outcome: CompletionOutcome, status: str) -> dict:
        """The evidence an error answer leaves: its status, HTTP code and message."""
        message = (outcome.error_message or outcome.error_type or "").strip()
        return {
            "error_status": status,
            "status_code": outcome.status_code,
            "error_message": message[:200] or None,
        }

    async def _probe(
        self,
        ctx: AuditContext,
        size: int,
        *,
        depth: float,
        tokenizer: str | None,
        reasoning: bool = False,
        attempt: int = 0,
    ) -> CompletionOutcome:
        # A re-probe (attempt > 0) gets a fresh needle, so an answer that merely
        # repeats the previous probe's marker cannot pass it.
        seed = f"ctxwin-{size}-{depth}" + (f"-{attempt}" if attempt else "")
        needle = stable_marker(seed)
        # Building a ~200k-token haystack is CPU work; run it off the event loop so
        # concurrent audits in `zing serve` keep measuring honest latencies.
        # Built smaller by the heuristic's under-count so the REAL token count of
        # the prompt stays within ``size``.
        haystack = await asyncio.to_thread(
            _build_haystack, size, needle=needle, depth=depth, tokenizer=tokenizer
        )
        messages = [{"role": "user", "content": haystack}]
        outcome = await self._call(ctx, messages, use_completion_tokens=reasoning)
        # A non-reasoning probe that gets a max_tokens parameter rejection is very
        # likely an unprofiled reasoning model — retry once with max_completion_tokens
        # rather than misreading the 4xx as a context ceiling.
        if not reasoning and self._is_param_rejection(outcome):
            outcome = await self._call(ctx, messages, use_completion_tokens=True)
        # Stash the needle so the caller's classifier can check recall.
        outcome.headers.setdefault("x-zing-needle", needle)
        return outcome

    @staticmethod
    async def _call(
        ctx: AuditContext, messages: list[dict], *, use_completion_tokens: bool
    ) -> CompletionOutcome:
        if use_completion_tokens:
            spec = RequestSpec(
                messages=messages,
                temperature=0.0,
                max_tokens=None,
                extra_body={"max_completion_tokens": 64},
            )
        else:
            spec = RequestSpec(messages=messages, temperature=0.0, max_tokens=64)
        return await ctx.client.complete(spec)

    @staticmethod
    def _classify(outcome: CompletionOutcome, size: int) -> tuple[bool, bool, str]:
        """Return (recalled, rejected_for_size, status_label).

        ``recalled`` is True only on a successful response echoing the needle.
        ``rejected_for_size`` is True for a 400..422 whose error text reads like a
        context/length rejection — the relay declining the prompt at this size.
        """
        needle = outcome.headers.get("x-zing-needle", "")
        if outcome.ok and outcome.has_content() and needle:
            if contains_ci(outcome.content, needle):
                return True, False, "recalled"
            return False, False, "no_recall"

        code = outcome.status_code
        if code is not None and 400 <= code <= 422:
            text = (outcome.error_message or "").lower()
            # Context-size rejection takes priority: a clear context phrase is a real
            # ceiling even if the message also names max_tokens.
            if any(hint in text for hint in _CONTEXT_ERROR_HINTS):
                return False, True, "rejected"
            # A bare parameter rejection (e.g. "max_tokens is not supported, use
            # max_completion_tokens") is NOT a size ceiling — stay inconclusive.
            if any(hint in text for hint in _PARAM_REJECTION_HINTS):
                return False, False, "param_error"
            return False, False, "http_error"
        if "timeout" in (outcome.error_type or "").lower():
            return False, False, "timeout"
        # Other transport errors, 5xx, malformed/empty responses: no answer to judge,
        # so inconclusive like the 4xx errors above — never a recall failure.
        return False, False, "error"

    @staticmethod
    def _is_param_rejection(outcome: CompletionOutcome) -> bool:
        """True if a 4xx is rejecting the max_tokens parameter (not the prompt size)."""
        code = outcome.status_code
        if code is None or not (400 <= code <= 422):
            return False
        text = (outcome.error_message or "").lower()
        if any(hint in text for hint in _CONTEXT_ERROR_HINTS):
            return False
        return any(hint in text for hint in _PARAM_REJECTION_HINTS)
