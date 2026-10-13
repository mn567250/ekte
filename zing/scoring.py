"""Turn detector results into dimension scores and a headline verdict.

The verdict deliberately uses cautious, evidence-first language: zing reports
*divergence and risk*, never a definitive fraud accusation. The dimensions that
speak to "货不对板" (model identity, real context window, capability claims) carry
the most weight.
"""

from __future__ import annotations

from zing.models import (
    DetectorResult,
    Dimension,
    DimensionBreakdown,
    DimensionContribution,
    DimensionScore,
    Finding,
    ReliabilitySummary,
    RiskLevel,
    Severity,
    Status,
    StatusOverride,
    Verdict,
)

# Weights sum to 100. The substitution/truncation-revealing dimensions dominate.
# The overall score is the weighted mean over the dimensions that produced a
# score, so a dimension that did not run (or was not selected) drops out.
DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.CONNECTIVITY: 7.0,
    Dimension.PROTOCOL: 8.0,
    Dimension.CONTEXT_WINDOW: 19.0,
    Dimension.MODEL_IDENTITY: 21.0,
    Dimension.CAPABILITY: 13.0,
    Dimension.STREAMING: 6.0,
    Dimension.BILLING: 8.0,
    Dimension.RELIABILITY: 6.0,
    Dimension.SECURITY: 6.0,
    Dimension.PERFORMANCE: 6.0,
}

# Dimensions whose failure most directly indicates 货不对板.
_CORE_DIMENSIONS = (
    Dimension.MODEL_IDENTITY,
    Dimension.CONTEXT_WINDOW,
    Dimension.CAPABILITY,
)

# Pure transport/reachability dimensions. A HIGH here (relay down, throttled,
# transient 5xx) means we could not assess the model — NOT that the relay serves a
# different model — so it must not escalate the substitution risk ladder. Its score
# still counts; it just can't drive the "diverges from the claimed model" headline.
_INFRA_DIMENSIONS = (Dimension.CONNECTIVITY,)

# Transport/advisory checks (by finding check id): how the relay is reached and
# how it holds up under load, not WHICH model it serves. Plain HTTP, a flaky
# burst or a slow tail lower their dimension's score and status and are listed
# as advisories in the verdict, but never escalate the substitution risk ladder
# — a self-hosted ``http://localhost`` endpoint must not read as "diverges from
# the claimed model". Integrity tampering and an echoed API key (other SECURITY
# checks) still escalate.
ADVISORY_CHECKS = frozenset({
    "security.tls",
    "reliability.success_rate",
    "reliability.latency",
})

# Knowledge-base matches too loose to vouch for the profile the audit judged
# against: the verdict confidence is capped at "low".
_WEAK_MATCHES = frozenset({"fuzzy"})

# Statuses that count as a core dimension having produced a usable substitution signal.
_USABLE_STATUSES = (Status.PASS, Status.WARN, Status.FAIL)

_SEVERITY_ORDER = [
    Severity.INFO,
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
]


# How "bad" a status is, for picking the worst across a dimension's detectors.
# Substantive conclusions (WARN/FAIL) outrank the operational ERROR so a crashed
# sibling detector cannot mask a real WARN/FAIL in the same dimension; ERROR still
# outranks PASS/INCONCLUSIVE so a lone crash surfaces as a coverage gap.
_STATUS_BADNESS = {
    Status.NOT_RUN: 0,
    Status.INFO: 1,
    Status.PASS: 2,
    Status.INCONCLUSIVE: 3,
    Status.ERROR: 4,
    Status.WARN: 5,
    Status.FAIL: 6,
}


def _all_findings(detectors: list[DetectorResult]) -> list[tuple[DetectorResult, Finding]]:
    return [(d, f) for d in detectors for f in d.findings]


def is_advisory(finding: Finding) -> bool:
    """True for a transport/advisory finding (see ``ADVISORY_CHECKS``)."""
    return (finding.check or finding.id) in ADVISORY_CHECKS


def _titles(findings: list[Finding]) -> list[str]:
    """Finding titles, the subjects of one parametrized check (e.g. several
    missing response attributes) folded into one: "<first> (+2 more)"."""
    titles: list[str] = []
    more: list[int] = []
    at: dict[str, int] = {}  # parametrized check -> its index in ``titles``
    for f in findings:
        if f.check and f.subject:
            if f.check in at:
                more[at[f.check]] += 1
                continue
            at[f.check] = len(titles)
        titles.append(f.title)
        more.append(0)
    return [t + (f" (+{n} more)" if n else "") for t, n in zip(titles, more, strict=True)]


def _worst_status(statuses: list[Status]) -> Status:
    if not statuses:
        return Status.NOT_RUN
    return max(statuses, key=lambda s: _STATUS_BADNESS.get(s, 0))


def build_dimensions(
    detectors: list[DetectorResult],
    reliability: ReliabilitySummary | None,
    *,
    selected: list[str] | None = None,
) -> list[DimensionScore]:
    """Score every dimension. ``selected`` (a custom suite's dimensions) marks
    the rest as not selected rather than not run."""
    dimensions: list[DimensionScore] = []
    for dim, weight in DIMENSION_WEIGHTS.items():
        members = [d for d in detectors if d.dimension == dim]
        scored = [d.score for d in members if d.score is not None]
        score = round(sum(scored) / len(scored), 1) if scored else None

        # Status reflects what the detectors themselves concluded — we do NOT
        # re-derive FAIL purely from a soft score, which would over-escalate.
        detector_status = status = _worst_status([d.status for d in members])
        # But a serious finding always pulls the dimension down.
        worst = Severity.INFO
        for det in members:
            ws = det.worst_severity()
            if _SEVERITY_ORDER.index(ws) > _SEVERITY_ORDER.index(worst):
                worst = ws
        if worst in (Severity.HIGH, Severity.CRITICAL) and members:
            status = Status.FAIL
        elif worst == Severity.MEDIUM and status in (Status.PASS, Status.INFO):
            status = Status.WARN
        override = None
        if status != detector_status:
            override = StatusOverride(
                from_status=detector_status,
                to_status=status,
                severity=worst,
                findings=[f.id for det in members for f in det.findings if f.severity == worst],
            )
        breakdown = DimensionBreakdown(
            detectors=[
                DimensionContribution(
                    detector=d.id, score=d.score, status=d.status, counted=d.score is not None
                )
                for d in members
            ],
            detector_status=detector_status,
            status_override=override,
        )

        if selected is not None and dim.value not in selected:
            reason = "Not selected in this custom run."
        elif not members:
            reason = "Not run in this suite."
        elif score is None:
            reason = "Ran but produced no numeric score (see findings)."
        else:
            reason = "; ".join(_titles([
                f for det in members for f in det.findings
                if f.status in (Status.FAIL, Status.WARN)
            ]))[:200] or "All checks passed."
        dimensions.append(
            DimensionScore(
                dimension=dim,
                score=score,
                weight=weight,
                status=status,
                reason=reason,
                breakdown=breakdown,
            )
        )
    return dimensions


def overall_score(dimensions: list[DimensionScore]) -> float | None:
    scored = [d for d in dimensions if d.score is not None]
    if not scored:
        return None
    weighted = sum((d.score or 0.0) * d.weight for d in scored)
    total = sum(d.weight for d in scored)
    return round(weighted / total, 1) if total else None


def _rating(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def build_verdict(
    detectors: list[DetectorResult],
    dimensions: list[DimensionScore],
    *,
    profile_matched: bool,
    used_judge: bool,
    used_baseline: bool,
    selected: list[str] | None = None,
    match_confidence: str | None = None,
) -> Verdict:
    """The headline verdict. ``match_confidence`` is how the claimed model
    matched its knowledge-base profile (``exact``/``alias``/``fuzzy``…); a
    fuzzy match caps the confidence at "low"."""
    score = overall_score(dimensions)
    pairs = _all_findings(detectors)
    weak_match = profile_matched and match_confidence in _WEAK_MATCHES

    # Substitution risk is judged on what is SERVED, excluding pure transport
    # findings (a down/throttled honest relay must not read as "diverges") and
    # transport/advisory checks (plain HTTP, reliability under load).
    infra_dims = set(_INFRA_DIMENSIONS)
    substantive = [
        (d, f) for d, f in pairs if d.dimension not in infra_dims and not is_advisory(f)
    ]
    advisories = [
        f for d, f in pairs
        if d.dimension not in infra_dims and is_advisory(f)
        and f.severity in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
    ]
    critical = [f for _, f in substantive if f.severity == Severity.CRITICAL]
    high = [f for _, f in substantive if f.severity == Severity.HIGH]
    medium = [f for _, f in substantive if f.severity == Severity.MEDIUM]

    # Findings landing in a core (substitution-revealing) dimension weigh more.
    core_dims = set(_CORE_DIMENSIONS)
    core_high = [f for d, f in pairs if d.dimension in core_dims and f.severity in (Severity.HIGH, Severity.CRITICAL)]
    core_medium = [f for d, f in pairs if d.dimension in core_dims and f.severity == Severity.MEDIUM]
    # Core coverage measured over distinct DIMENSIONS that produced a usable signal,
    # not over detector count — two MODEL_IDENTITY detectors must not look like full
    # coverage while CONTEXT_WINDOW/CAPABILITY never ran.
    core_dims_ran = {
        d.dimension
        for d in detectors
        if d.dimension in core_dims and d.status in _USABLE_STATUSES
    }
    judge_effective = any(
        d.id == "quality_judge" and d.status in _USABLE_STATUSES for d in detectors
    )

    # --- risk classification: driven by FINDING SEVERITY, not score alone --- #
    # zing only reaches HIGH on hard, high-severity evidence — a single soft
    # signal or a merely-low score never escalates to HIGH on its own.
    if not core_dims_ran:
        # No core dimension produced a usable substitution signal (relay unreachable,
        # unprofiled, or only peripheral checks ran) — we cannot judge the claim.
        # Peripheral findings are still carried in the report as advisories.
        risk = RiskLevel.INCONCLUSIVE
    elif critical or core_high or len(high) >= 2:
        risk = RiskLevel.HIGH
    elif high or core_medium:  # exactly one high-severity finding outside the core dimensions
        risk = RiskLevel.MEDIUM
    elif medium:
        risk = RiskLevel.LOW
    else:
        risk = RiskLevel.CLEAN

    # --- confidence -------------------------------------------------------- #
    n_core_total = len(core_dims)
    if not profile_matched or weak_match:
        # Unprofiled, or a fuzzy match whose profile may not be the model's.
        confidence = "low"
    elif used_baseline and len(core_dims_ran) == n_core_total:
        confidence = "high"
    elif len(core_dims_ran) >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    # Only let an *effective* judge (one that produced a usable verdict, not merely a
    # constructed client) lift confidence.
    if judge_effective and confidence == "medium":
        confidence = "high"

    headline = _headline(risk, confidence)
    summary = _summary(
        risk, score, critical, high, medium, profile_matched, used_baseline,
        scored=sum(1 for d in dimensions if d.score is not None),
        selected=selected,
        weak_match=weak_match,
        advisories=bool(advisories),
    )
    # Substitution findings first; transport/reliability advisories after them.
    key = _titles(critical + high + medium + advisories)[:6]

    return Verdict(
        overall_score=score,
        rating=_rating(score),
        risk_level=risk,
        headline=headline,
        confidence=confidence,
        summary=summary,
        key_findings=key,
    )


def _headline(risk: RiskLevel, confidence: str) -> str:
    table = {
        RiskLevel.CLEAN: "Behavior is consistent with the claimed model.",
        RiskLevel.LOW: "Mostly consistent with the claimed model; minor concerns.",
        RiskLevel.MEDIUM: "Some behavior diverges from the claimed model — investigate.",
        RiskLevel.HIGH: "Strong evidence the relay does not deliver the claimed model as advertised.",
        RiskLevel.INCONCLUSIVE: "Not enough signal to judge — connectivity or coverage was insufficient.",
    }
    return f"{table[risk]} (confidence: {confidence})"


def _summary(
    risk: RiskLevel,
    score: float | None,
    critical: list[Finding],
    high: list[Finding],
    medium: list[Finding],
    profile_matched: bool,
    used_baseline: bool,
    *,
    scored: int = 0,
    selected: list[str] | None = None,
    weak_match: bool = False,
    advisories: bool = False,
) -> str:
    bits: list[str] = []
    if score is not None:
        bits.append(f"Overall health score {score}/100.")
    if selected is not None:
        bits.append(f"Custom run: {scored} of {len(selected)} selected dimensions scored.")
        if not set(selected) & {d.value for d in _CORE_DIMENSIONS}:
            bits.append(
                "No core dimension (model identity, context window, capability) was "
                "selected, so the substitution risk cannot be judged."
            )
    counts = []
    if critical:
        counts.append(f"{len(critical)} critical")
    if high:
        counts.append(f"{len(high)} high")
    if medium:
        counts.append(f"{len(medium)} medium")
    if counts:
        bits.append("Findings: " + ", ".join(counts) + ".")
    else:
        bits.append("No significant divergence findings.")
    if not profile_matched:
        bits.append(
            "The claimed model was not found in the knowledge base, so identity/"
            "capability checks are limited — pass --declared-provider or add a KB profile."
        )
    elif weak_match:
        bits.append(
            "The claimed model only fuzzily matched a knowledge-base profile, so "
            "confidence is capped at low — pass the exact model id or add a KB alias."
        )
    if advisories:
        bits.append(
            "Transport and reliability findings (plain HTTP, failures or slowness under "
            "load) are advisories: they lower the score but not the substitution risk."
        )
    if not used_baseline and risk in (RiskLevel.MEDIUM, RiskLevel.HIGH):
        bits.append("Run `zing compare` against a trusted baseline to strengthen the verdict.")
    bits.append(
        "zing reports black-box evidence of divergence and risk, not proof of fraud."
    )
    return " ".join(bits)
