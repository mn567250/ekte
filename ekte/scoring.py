"""Turn detector results into dimension scores and a headline verdict.

The verdict deliberately uses cautious, evidence-first language: ekte reports
*divergence and risk*, never a definitive fraud accusation. It is judged on the
dimensions that actually ran (a custom run checks only its selection), and the
dimensions that break what the relay advertises (model identity, real context
window, capability claims, billed usage) decide the risk.
"""

from __future__ import annotations

from ekte.models import (
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

# Dimensions judged against the claimed model's knowledge-base profile: when
# one of them ran, the verdict needs one of them to produce a usable result,
# and an unmatched or fuzzy profile caps the confidence.
_PROFILE_DIMENSIONS = (
    Dimension.MODEL_IDENTITY,
    Dimension.CONTEXT_WINDOW,
    Dimension.CAPABILITY,
)

# Dimensions whose failure means the relay does not deliver what it advertises
# (货不对板): a different model, a smaller context window, missing capabilities
# or inflated billing. One HIGH finding here makes the risk HIGH.
_CORE_DIMENSIONS = (*_PROFILE_DIMENSIONS, Dimension.BILLING)

# Pure transport/reachability dimensions. A HIGH here (relay down, throttled,
# transient 5xx) means we could not assess the model — NOT that the relay serves a
# different model — so it must not escalate the substitution risk ladder. Its score
# still counts; it just can't drive the "diverges from the claimed model" headline.
_INFRA_DIMENSIONS = (Dimension.CONNECTIVITY,)

# The embedding surface reuses the chat dimensions it has evidence for. Model
# identity (vector dimension, echoed model, drift on a pinned probe) dominates:
# a different embedding model silently breaks every stored vector.
_EMBEDDING_WEIGHTS: dict[Dimension, float] = {
    Dimension.CONNECTIVITY: 10.0,
    Dimension.MODEL_IDENTITY: 40.0,
    Dimension.CAPABILITY: 15.0,
    Dimension.RELIABILITY: 15.0,
    Dimension.PERFORMANCE: 20.0,
}

# The rerank surface: identity (echoed model, drift on a pinned probe) and
# capability (ranking a known answer first) carry the verdict together.
_RERANK_WEIGHTS: dict[Dimension, float] = {
    Dimension.MODEL_IDENTITY: 30.0,
    Dimension.CAPABILITY: 30.0,
    Dimension.PERFORMANCE: 20.0,
    Dimension.RELIABILITY: 10.0,
    Dimension.CONNECTIVITY: 10.0,
}

# Per-surface weights and dimension sets; ``chat`` keeps the tables above.
SURFACE_WEIGHTS: dict[str, dict[Dimension, float]] = {
    "chat": DIMENSION_WEIGHTS,
    "embedding": _EMBEDDING_WEIGHTS,
    "rerank": _RERANK_WEIGHTS,
}
_SURFACE_PROFILE_DIMENSIONS: dict[str, tuple[Dimension, ...]] = {
    "chat": _PROFILE_DIMENSIONS,
    "embedding": (Dimension.MODEL_IDENTITY,),
    "rerank": (Dimension.MODEL_IDENTITY,),
}
# For embeddings a dimension mismatch (MODEL_IDENTITY HIGH) makes the risk HIGH;
# for rerank a failed known-answer ranking (CAPABILITY HIGH) does too.
_SURFACE_CORE_DIMENSIONS: dict[str, tuple[Dimension, ...]] = {
    "chat": _CORE_DIMENSIONS,
    "embedding": (Dimension.MODEL_IDENTITY,),
    "rerank": (Dimension.MODEL_IDENTITY, Dimension.CAPABILITY),
}
_SURFACE_INFRA_DIMENSIONS: dict[str, tuple[Dimension, ...]] = {
    "chat": _INFRA_DIMENSIONS,
    "embedding": (Dimension.CONNECTIVITY,),
    "rerank": (Dimension.CONNECTIVITY,),
}


def weights_for(surface: str | None) -> dict[Dimension, float]:
    """The dimension weights of ``surface`` (None or unknown reads as chat)."""
    return SURFACE_WEIGHTS.get(surface or "chat", DIMENSION_WEIGHTS)


def _dims_for(table: dict[str, tuple[Dimension, ...]], surface: str | None) -> set[Dimension]:
    return set(table.get(surface or "chat", table["chat"]))

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

# Statuses that count as a dimension having produced a usable result.
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
    surface: str = "chat",
) -> list[DimensionScore]:
    """Score every dimension of ``surface``. ``selected`` (a custom suite's
    dimensions) marks the rest as not selected rather than not run."""
    dimensions: list[DimensionScore] = []
    for dim, weight in weights_for(surface).items():
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
    surface: str = "chat",
) -> Verdict:
    """The headline verdict, judged on the dimensions that ran.
    ``match_confidence`` is how the claimed model matched its knowledge-base
    profile (``exact``/``alias``/``fuzzy``…); a fuzzy match caps the
    confidence at "low". ``surface`` picks the profile / core / infra
    dimension sets."""
    score = overall_score(dimensions)
    pairs = _all_findings(detectors)
    weak_match = profile_matched and match_confidence in _WEAK_MATCHES

    # Substitution risk is judged on what is SERVED, excluding pure transport
    # findings (a down/throttled honest relay must not read as "diverges") and
    # transport/advisory checks (plain HTTP, reliability under load).
    infra_dims = _dims_for(_SURFACE_INFRA_DIMENSIONS, surface)
    substantive = [
        (d, f) for d, f in pairs if d.dimension not in infra_dims and not is_advisory(f)
    ]
    advisories = [
        f for d, f in pairs
        if d.dimension not in infra_dims and is_advisory(f)
        and f.severity in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
    ]
    critical = [(d, f) for d, f in substantive if f.severity == Severity.CRITICAL]
    high = [(d, f) for d, f in substantive if f.severity == Severity.HIGH]
    medium = [(d, f) for d, f in substantive if f.severity == Severity.MEDIUM]

    # Findings landing in a core dimension weigh more.
    core_dims = _dims_for(_SURFACE_CORE_DIMENSIONS, surface)
    core_high = [(d, f) for d, f in high if d.dimension in core_dims]
    core_medium = [(d, f) for d, f in medium if d.dimension in core_dims]

    # Coverage is measured over distinct DIMENSIONS, not detector count — two
    # MODEL_IDENTITY detectors must not look like broad coverage.
    attempted = {d.dimension for d in detectors if d.dimension not in infra_dims}
    checked = {
        d.dimension
        for d in detectors
        if d.dimension not in infra_dims and d.status in _USABLE_STATUSES
    }
    profile_dims = _dims_for(_SURFACE_PROFILE_DIMENSIONS, surface)
    judge_effective = any(
        d.id == "quality_judge" and d.status in _USABLE_STATUSES for d in detectors
    )

    # --- risk classification: driven by FINDING SEVERITY, not score alone --- #
    # ekte only reaches HIGH on hard, high-severity evidence — a single soft
    # signal or a merely-low score never escalates to HIGH on its own.
    # When the profile-backed dimensions ran, they decide whether the claim can
    # be judged at all (relay unreachable, model unprofiled); a custom run
    # without them is judged on whatever it checked.
    judged = bool(checked & profile_dims) if attempted & profile_dims else bool(checked)
    if not judged:
        # Peripheral findings are still carried in the report as advisories.
        risk = RiskLevel.INCONCLUSIVE
        causes: list[tuple[DetectorResult, Finding]] = []
    elif critical or core_high or len(high) >= 2:
        risk = RiskLevel.HIGH
        causes = critical + core_high or high
    elif high or core_medium:  # exactly one high-severity finding outside the core dimensions
        risk = RiskLevel.MEDIUM
        causes = high + core_medium
    elif medium:
        risk = RiskLevel.LOW
        causes = medium
    else:
        risk = RiskLevel.CLEAN
        causes = []
    drivers = _in_order({d.dimension for d, _ in causes})

    # --- confidence -------------------------------------------------------- #
    core_attempted = attempted & core_dims
    core_checked = checked & core_dims
    if attempted & profile_dims and (not profile_matched or weak_match):
        # Unprofiled, or a fuzzy match whose profile may not be the model's.
        confidence = "low"
    elif used_baseline and core_checked and core_checked == core_attempted:
        confidence = "high"
    elif len(core_checked) >= 2 or (not core_attempted and len(checked) >= 2):
        confidence = "medium"
    else:
        confidence = "low"
    # Only let an *effective* judge (one that produced a usable verdict, not merely a
    # constructed client) lift confidence.
    if judge_effective and confidence == "medium":
        confidence = "high"

    identity_checked = Dimension.MODEL_IDENTITY in checked
    headline = _headline(risk, confidence, drivers, identity_checked=identity_checked)
    # The knowledge-base caveats only matter when a profile-backed dimension ran.
    profile_used = bool(attempted & profile_dims)
    summary = _summary(
        risk, score, [f for _, f in critical], [f for _, f in high], [f for _, f in medium],
        profile_matched or not profile_used, used_baseline,
        scored=sum(1 for d in dimensions if d.score is not None),
        selected=selected,
        weak_match=weak_match and profile_used,
        advisories=bool(advisories),
    )
    # Substitution findings first; transport/reliability advisories after them.
    key = _titles([f for _, f in critical + high + medium] + advisories)[:6]

    return Verdict(
        overall_score=score,
        rating=_rating(score),
        risk_level=risk,
        headline=headline,
        confidence=confidence,
        summary=summary,
        key_findings=key,
        drivers=[d.value for d in drivers],
        checked=[d.value for d in _in_order(checked)],
    )


def _in_order(dims: set[Dimension]) -> list[Dimension]:
    """``dims`` in scoring order (``DIMENSION_WEIGHTS``)."""
    return [d for d in DIMENSION_WEIGHTS if d in dims]


# English names of the dimensions, as the reports show them.
DIMENSION_NAMES: dict[Dimension, str] = {
    Dimension.CONNECTIVITY: "Connectivity",
    Dimension.PROTOCOL: "Protocol compliance",
    Dimension.CONTEXT_WINDOW: "Context window",
    Dimension.MODEL_IDENTITY: "Model identity",
    Dimension.CAPABILITY: "Capability claims",
    Dimension.STREAMING: "Streaming authenticity",
    Dimension.BILLING: "Billing & usage",
    Dimension.RELIABILITY: "Concurrency reliability",
    Dimension.SECURITY: "Transport security",
    Dimension.PERFORMANCE: "Performance",
}


def _headline(
    risk: RiskLevel,
    confidence: str,
    drivers: list[Dimension] | None = None,
    *,
    identity_checked: bool = True,
) -> str:
    """The headline names what drove the risk: the claimed-model sentences
    only when model identity is among the drivers (or none are known)."""
    drivers = drivers or []
    if risk in (RiskLevel.HIGH, RiskLevel.MEDIUM):
        scoped = bool(drivers) and Dimension.MODEL_IDENTITY not in drivers
    else:
        scoped = not identity_checked and risk != RiskLevel.INCONCLUSIVE
    # (risk, scoped): "scoped" sentences speak of the checked dimensions
    # (``{1}``: the drivers), the others of the claimed model.
    table = {
        (RiskLevel.CLEAN, False): "Behavior is consistent with the claimed model.",
        (RiskLevel.CLEAN, True): "No problems found in the checked dimensions; model identity was not verified.",
        (RiskLevel.LOW, False): "Mostly consistent with the claimed model; minor concerns.",
        (RiskLevel.LOW, True): "Minor concerns in the checked dimensions; model identity was not verified.",
        (RiskLevel.MEDIUM, False): "Some behavior diverges from the claimed model — investigate.",
        (RiskLevel.MEDIUM, True): "Some checks diverge from what is advertised: {1} — investigate.",
        (RiskLevel.HIGH, False): "Strong evidence the relay does not deliver the claimed model as advertised.",
        (RiskLevel.HIGH, True): "Strong evidence the relay does not deliver what it advertises: {1}.",
        (RiskLevel.INCONCLUSIVE, False): "Not enough signal to judge — connectivity or coverage was insufficient.",
    }
    names = ", ".join(DIMENSION_NAMES[d] for d in drivers)
    sentence = table[(risk, scoped)].replace("{1}", names)
    return f"{sentence} (confidence: {confidence})"


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
        if Dimension.MODEL_IDENTITY.value not in selected:
            bits.append(
                "Model identity was not selected, so this verdict covers only the "
                "selected dimensions, not which model is served."
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
        bits.append("Run `ekte compare` against a trusted baseline to strengthen the verdict.")
    bits.append(
        "ekte reports black-box evidence of divergence and risk, not proof of fraud."
    )
    return " ".join(bits)
