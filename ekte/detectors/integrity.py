"""Response-integrity / tampering detector.

A malicious proxy can rewrite content in flight — typosquatting an install URL or
package name, swapping a domain — while leaving everything else intact. zing sends
known-answer canaries ("output exactly this line") whose values are sensitive
(a URL, a pinned package) and checks whether the structure comes back with the
value SUBSTITUTED.

It is deliberately precise to avoid false positives: an exact echo is PASS, a
non-echo (the model didn't comply / paraphrased) is INCONCLUSIVE, and only a
*structure-preserved value substitution* is treated as tampering. A lone
substitution caps at MEDIUM; in ``compare`` mode, a substitution the trusted
baseline does NOT make (it returns the canary intact) is escalated to CRITICAL.
A baseline that errors or returns nothing usable corroborates nothing, so the
substitution stays MEDIUM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from zing import prompts
from zing.context import AuditContext
from zing.detectors.base import Detector, register
from zing.detectors.helpers import contains_ci
from zing.detectors.scale import Scale, outcome
from zing.models import DetectorResult, Dimension, RequestSpec, Severity, Status


@dataclass
class _Canary:
    id: str
    prompt: str
    expected: str                 # exact substring that must survive intact
    pattern: re.Pattern           # matches the structure (group(0)) and value(s)
    correct: str                  # the canonical value the structure should carry

    def substitution(self, text: str) -> str | None:
        """Return a description if the structure is present but the value changed."""
        m = self.pattern.search(text or "")
        if not m:
            return None
        found = m.group("val")
        if found == self.correct:
            return None
        return f"{self.id}: expected {self.correct!r}, got {found!r}"


_CANARIES: tuple[_Canary, ...] = (
    _Canary(
        id="install_url",
        prompt=prompts.text("integrity.install_url"),
        expected="https://downloads.zing-audit.test/safe/setup.sh",
        pattern=re.compile(r"ZING_URL=https?://(?P<val>[^/\s\"']+)"),
        correct="downloads.zing-audit.test",
    ),
    _Canary(
        id="package_pin",
        prompt=prompts.text("integrity.package_pin"),
        expected="zing-audit==0.1.0",
        pattern=re.compile(r"pip install (?P<val>[A-Za-z0-9._-]+==[0-9][0-9A-Za-z.\-]*)"),
        correct="zing-audit==0.1.0",
    ),
)


# The detector score is its one verdict's points (the published scale).
SCALE = Scale(
    outcome("integrity.verdict", "intact", 100.0, Status.PASS,
            label="Known-answer canaries came back intact."),
    outcome("integrity.verdict", "tampering", 45.0, Status.FAIL, Severity.MEDIUM,
            label="A canary value was substituted (not yet confirmed by a baseline)."),
    outcome("integrity.verdict", "tampering_corroborated", 10.0, Status.FAIL, Severity.CRITICAL,
            label="A canary value was substituted while the trusted baseline kept it intact."),
    outcome("integrity.verdict", "inconclusive", None, Status.INCONCLUSIVE,
            label="No canary was echoed verbatim, so tampering could not be assessed."),
    titles={"integrity.verdict": "Response integrity"},
)


@register
class IntegrityDetector(Detector):
    id = "integrity"
    name = "Response integrity / tampering"
    dimension = Dimension.SECURITY
    min_suite = "deep"
    cost_hint = 3

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        substitutions: list[str] = []
        # Per substitution: did the trusted baseline return that canary intact?
        # Only a baseline that actually answered — verbatim — corroborates; one
        # that errored or returned nothing usable leaves the substitution
        # uncorroborated.
        baseline_intact: list[bool] = []
        verbatim = 0
        noncompliant = 0

        for canary in _CANARIES:
            text = await self._ask(ctx, canary.prompt)
            if text is None:
                noncompliant += 1
                continue
            if contains_ci(text, canary.expected):
                verbatim += 1
                continue
            sub = canary.substitution(text)
            if sub:
                intact = False
                if ctx.has_baseline:
                    base = await self._ask(ctx, canary.prompt, baseline=True)
                    if base is not None and not contains_ci(base, canary.expected):
                        # Baseline also failed to echo it — likely model behavior, not tampering.
                        noncompliant += 1
                        continue
                    intact = base is not None
                substitutions.append(sub)
                baseline_intact.append(intact)
            else:
                noncompliant += 1

        result.evidence.update(
            {"substitutions": substitutions, "verbatim": verbatim, "noncompliant": noncompliant}
        )

        if substitutions:
            confirmed = [sub for sub, ok in zip(substitutions, baseline_intact, strict=True) if ok]
            corroborated = bool(confirmed)
            # Compare mode ran, but the baseline errored / answered nothing usable
            # (empty, cut off) for every substituted canary — it confirmed nothing.
            baseline_unavailable = ctx.has_baseline and not corroborated
            if corroborated:
                unconfirmed = len(substitutions) - len(confirmed)
                tail = (
                    " — and the trusted baseline returned it intact, strong evidence "
                    "of in-flight tampering."
                    + (
                        f" ({unconfirmed} other substitution(s) could not be checked: "
                        "the baseline returned no usable answer for them.)"
                        if unconfirmed
                        else ""
                    )
                )
            elif baseline_unavailable:
                tail = (
                    ". The trusted baseline returned no usable answer (error, empty or "
                    "cut off) for the substituted canary value(s), so the substitution is "
                    "not corroborated; re-run `zing compare` once the baseline answers."
                )
            else:
                tail = (
                    ". Treat as a strong signal; run `zing compare` against a "
                    "trusted baseline to confirm."
                )
            result.findings.append(
                SCALE.finding(
                    "integrity.verdict",
                    "tampering_corroborated" if corroborated else "tampering",
                    id="integrity.tampering",
                    title="Relay-controlled value substitution detected",
                    summary=(
                        "A known-answer canary came back with its value substituted while "
                        "its structure was preserved" + tail
                    ),
                    evidence={
                        "substitutions": substitutions,
                        "baseline_corroborated": corroborated,
                        "baseline_unavailable": baseline_unavailable,
                        # the substitutions the baseline returned intact
                        "corroborated_substitutions": confirmed,
                    },
                    recommendation="A proxy rewriting URLs/package names is a supply-chain risk — stop using it.",
                )
            )
            result.status = Status.FAIL
            result.score = Scale.mean(result.findings)
        elif verbatim:
            result.findings.append(
                SCALE.finding(
                    "integrity.verdict",
                    "intact",
                    id="integrity.intact",
                    title="Known-answer canaries returned intact",
                    summary=f"{verbatim} canary value(s) echoed verbatim; no substitution observed.",
                    evidence={"verbatim": verbatim, "noncompliant": noncompliant},
                )
            )
            result.status = Status.PASS
            result.score = Scale.mean(result.findings)
        else:
            result.findings.append(
                SCALE.finding(
                    "integrity.verdict",
                    "inconclusive",
                    id="integrity.inconclusive",
                    title="Integrity canaries inconclusive",
                    summary="The model did not echo any canary verbatim, so tampering could not be assessed.",
                    evidence={"noncompliant": noncompliant},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
        return result

    async def _ask(self, ctx: AuditContext, prompt: str, *, baseline: bool = False) -> str | None:
        client = ctx.baseline_client if baseline else ctx.client
        if client is None:
            return None
        outcome = await client.complete(
            RequestSpec(messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=80)
        )
        # An answer cut off at the output limit (e.g. `==0` for `==0.1.0` after a
        # reasoning model thought through the budget) is not a substitution.
        if outcome.ok and outcome.has_content() and outcome.finish_reason != "length":
            return outcome.content
        return None
