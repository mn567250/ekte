"""Tests for dimension scoring and the headline verdict.

These exercise the spine that turns raw detector findings into a risk level,
using synthetic :class:`DetectorResult` lists so the logic is isolated from any
real relay behaviour.
"""

from __future__ import annotations

import json
import random
import re

import pytest

from ekte.detectors import REGISTRY
from ekte.models import (
    AuditReport,
    DetectorResult,
    Dimension,
    Finding,
    RedactedTarget,
    RiskLevel,
    Severity,
    Status,
)
from ekte.report import render_html, render_markdown
from ekte.scoring import (
    ADVISORY_CHECKS,
    COVERAGE_LIMITED_BELOW,
    COVERAGE_RATING_LIMIT,
    COVERAGE_UNRATED_BELOW,
    RISK_SCORE_CAPS,
    build_dimensions,
    build_verdict,
    coverage_pct,
    overall_score,
    rating,
)


def _result(
    dimension: Dimension,
    *,
    score: float | None,
    status: Status,
    findings: list[Finding] | None = None,
) -> DetectorResult:
    return DetectorResult(
        id=f"{dimension.value}-det",
        name=dimension.value,
        dimension=dimension,
        score=score,
        status=status,
        findings=findings or [],
    )


def _info(dim_id: str) -> Finding:
    return Finding(id=f"{dim_id}.ok", title="All good", status=Status.PASS, severity=Severity.INFO)


def _clean_core_detectors() -> list[DetectorResult]:
    """One passing detector for each core (substitution-revealing) dimension."""
    return [
        _result(Dimension.MODEL_IDENTITY, score=95.0, status=Status.PASS, findings=[_info("identity")]),
        _result(Dimension.CONTEXT_WINDOW, score=92.0, status=Status.PASS, findings=[_info("context")]),
        _result(Dimension.CAPABILITY, score=90.0, status=Status.PASS, findings=[_info("capability")]),
    ]


# --------------------------------------------------------------------------- #
# build_dimensions
# --------------------------------------------------------------------------- #
def test_build_dimensions_covers_every_dimension():
    dims = build_dimensions([], reliability=None)
    assert {d.dimension for d in dims} == set(Dimension)
    # Nothing ran -> NOT_RUN with no score.
    for d in dims:
        assert d.status == Status.NOT_RUN
        assert d.score is None


def test_build_dimensions_averages_member_scores():
    detectors = [
        _result(Dimension.CONNECTIVITY, score=80.0, status=Status.PASS),
        _result(Dimension.CONNECTIVITY, score=100.0, status=Status.PASS),
    ]
    dims = {d.dimension: d for d in build_dimensions(detectors, reliability=None)}
    conn = dims[Dimension.CONNECTIVITY]
    assert conn.score == 90.0
    assert conn.status == Status.PASS


def test_high_severity_finding_forces_dimension_fail():
    findings = [
        Finding(
            id="identity.mismatch",
            title="Self-identification mismatch",
            status=Status.WARN,
            severity=Severity.HIGH,
        )
    ]
    # Even with a decent score, a HIGH finding pulls the dimension to FAIL.
    detectors = [_result(Dimension.MODEL_IDENTITY, score=75.0, status=Status.WARN, findings=findings)]
    dims = {d.dimension: d for d in build_dimensions(detectors, reliability=None)}
    assert dims[Dimension.MODEL_IDENTITY].status == Status.FAIL


# --------------------------------------------------------------------------- #
# overall_score
# --------------------------------------------------------------------------- #
def test_overall_score_none_when_nothing_scored():
    dims = build_dimensions([], reliability=None)
    assert overall_score(dims) is None


def test_overall_score_is_weighted():
    detectors = _clean_core_detectors()
    dims = build_dimensions(detectors, reliability=None)
    score = overall_score(dims)
    assert score is not None
    assert 85.0 <= score <= 100.0


# --------------------------------------------------------------------------- #
# build_verdict
# --------------------------------------------------------------------------- #
def test_verdict_clean_case():
    detectors = _clean_core_detectors()
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.CLEAN
    assert verdict.overall_score is not None
    assert verdict.rating in ("A", "B")
    assert "consistent" in verdict.headline.lower()


def test_verdict_high_risk_on_core_high_severity_identity_finding():
    finding = Finding(
        id="identity.downgrade",
        title="Likely model downgrade",
        status=Status.FAIL,
        severity=Severity.HIGH,
    )
    detectors = [
        _result(Dimension.MODEL_IDENTITY, score=20.0, status=Status.FAIL, findings=[finding]),
        _result(Dimension.CONTEXT_WINDOW, score=90.0, status=Status.PASS, findings=[_info("context")]),
        _result(Dimension.CAPABILITY, score=90.0, status=Status.PASS, findings=[_info("capability")]),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.HIGH
    assert "Likely model downgrade" in verdict.key_findings


def test_verdict_inconclusive_when_no_core_dimensions_ran():
    # Only connectivity ran — no substitution-revealing evidence at all.
    detectors = [
        _result(Dimension.CONNECTIVITY, score=100.0, status=Status.PASS, findings=[_info("conn")]),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.INCONCLUSIVE


def test_verdict_single_noncore_high_is_medium():
    finding = Finding(
        id="streaming.fake",
        title="Streaming may be buffered",
        status=Status.WARN,
        severity=Severity.HIGH,
    )
    detectors = [
        *_clean_core_detectors(),
        _result(Dimension.STREAMING, score=40.0, status=Status.WARN, findings=[finding]),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    # A single high-severity finding outside the core dimensions caps at MEDIUM.
    assert verdict.risk_level == RiskLevel.MEDIUM


def test_verdict_connectivity_high_does_not_escalate_clean_cores():
    # A transport/connectivity HIGH (relay down/flaky) must NOT make an otherwise
    # clean set of core checks read as "diverges from the claimed model".
    conn_fail = Finding(
        id="connectivity.unreachable",
        title="Endpoint unreachable",
        status=Status.FAIL,
        severity=Severity.HIGH,
    )
    detectors = [
        *_clean_core_detectors(),
        _result(Dimension.CONNECTIVITY, score=0.0, status=Status.FAIL, findings=[conn_fail]),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.CLEAN


def test_verdict_unreachable_relay_is_inconclusive_not_medium():
    # Connectivity HIGH while the core detectors all errored out -> no usable
    # substitution signal -> INCONCLUSIVE, never a divergence verdict.
    conn_fail = Finding(
        id="connectivity.unreachable",
        title="Endpoint unreachable",
        status=Status.FAIL,
        severity=Severity.HIGH,
    )
    detectors = [
        _result(Dimension.CONNECTIVITY, score=0.0, status=Status.FAIL, findings=[conn_fail]),
        _result(Dimension.MODEL_IDENTITY, score=None, status=Status.ERROR),
        _result(Dimension.CAPABILITY, score=None, status=Status.ERROR),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.INCONCLUSIVE


def test_verdict_confidence_low_when_profile_unmatched():
    detectors = _clean_core_detectors()
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=False, used_judge=False, used_baseline=False
    )
    assert verdict.confidence == "low"


def test_verdict_confidence_high_with_baseline_and_full_core():
    detectors = _clean_core_detectors()
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=True
    )
    assert verdict.confidence == "high"


def test_verdict_fuzzy_kb_match_caps_confidence_at_low():
    # Baseline + full core would be "high", but a fuzzy profile may not be the
    # model's own: confidence stays low and the summary says why.
    detectors = _clean_core_detectors()
    dims = build_dimensions(detectors, reliability=None)
    exact = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=True,
        match_confidence="exact",
    )
    fuzzy = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=True,
        match_confidence="fuzzy",
    )
    assert exact.confidence == "high" and "fuzzily" not in exact.summary
    assert fuzzy.confidence == "low" and "(confidence: low)" in fuzzy.headline
    assert "only fuzzily matched a knowledge-base profile" in fuzzy.summary


# --------------------------------------------------------------------------- #
# transport/advisory findings never escalate the substitution risk
# --------------------------------------------------------------------------- #
def _plain_http(severity: Severity = Severity.HIGH) -> Finding:
    return Finding(id="security.tls", title="Endpoint is not HTTPS", status=Status.FAIL,
                   severity=severity, outcome="plain_http", cap=40.0)


def test_verdict_plain_http_is_an_advisory_not_a_divergence():
    detectors = [
        *_clean_core_detectors(),
        _result(Dimension.SECURITY, score=40.0, status=Status.FAIL, findings=[_plain_http()]),
    ]
    dims = {d.dimension: d for d in build_dimensions(detectors, reliability=None)}
    verdict = build_verdict(
        detectors, list(dims.values()), profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.CLEAN
    # It still fails its dimension and is listed as an advisory.
    assert dims[Dimension.SECURITY].status == Status.FAIL
    assert "Endpoint is not HTTPS" in verdict.key_findings
    assert "advisories" in verdict.summary and "Findings:" not in verdict.summary


def test_verdict_reliability_failures_do_not_escalate():
    # e.g. a reasoning model that 400s every tiny reliability ping.
    burst = Finding(id="reliability.success_rate", title="Some concurrent requests failed",
                    status=Status.FAIL, severity=Severity.MEDIUM, outcome="many_failed")
    slow = Finding(id="reliability.latency", title="High tail latency under load",
                   status=Status.WARN, severity=Severity.LOW, outcome="slow")
    detectors = [
        *_clean_core_detectors(),
        _result(Dimension.RELIABILITY, score=0.0, status=Status.FAIL, findings=[burst, slow]),
        _result(Dimension.SECURITY, score=40.0, status=Status.FAIL, findings=[_plain_http()]),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.CLEAN
    assert verdict.key_findings == ["Some concurrent requests failed", "Endpoint is not HTTPS"]


def test_verdict_integrity_and_key_echo_still_escalate():
    tamper = Finding(id="integrity.tampered", title="Response tampered", status=Status.FAIL,
                     severity=Severity.CRITICAL)
    echo = Finding(id="security.key_echo", title="API key reflected in response",
                   status=Status.FAIL, severity=Severity.HIGH, outcome="echoed")
    for finding, risk in ((tamper, RiskLevel.HIGH), (echo, RiskLevel.MEDIUM)):
        detectors = [
            *_clean_core_detectors(),
            _result(Dimension.SECURITY, score=30.0, status=Status.FAIL, findings=[finding]),
        ]
        dims = build_dimensions(detectors, reliability=None)
        verdict = build_verdict(
            detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
        )
        assert verdict.risk_level == risk, finding.id


# --------------------------------------------------------------------------- #
# the verdict follows the dimensions that ran and drove the risk
# --------------------------------------------------------------------------- #
def _high(dim: Dimension, check: str, title: str) -> DetectorResult:
    finding = Finding(id=check, title=title, status=Status.FAIL, severity=Severity.HIGH)
    return _result(dim, score=25.0, status=Status.FAIL, findings=[finding])


def test_verdict_context_window_high_does_not_blame_the_model():
    # Identity passes, the context window is cut: HIGH, driven by the context
    # window, with a headline that names it and leaves the model alone.
    detectors = [
        _result(Dimension.MODEL_IDENTITY, score=100.0, status=Status.PASS, findings=[_info("identity")]),
        _high(Dimension.CONTEXT_WINDOW, "context_window.rejected", "Endpoint rejects context below its advertised window"),
        _result(Dimension.CAPABILITY, score=93.0, status=Status.PASS, findings=[_info("capability")]),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.risk_level == RiskLevel.HIGH
    assert verdict.drivers == ["context_window"]
    assert verdict.checked == ["context_window", "model_identity", "capability"]
    assert verdict.headline == (
        "Strong evidence the relay does not deliver what it advertises: Context window. "
        "(confidence: medium)"
    )


def test_verdict_identity_high_keeps_the_claimed_model_headline():
    detectors = [
        _high(Dimension.MODEL_IDENTITY, "identity.downgrade", "Likely model downgrade"),
        _high(Dimension.CONTEXT_WINDOW, "context_window.rejected", "Context cut"),
    ]
    dims = build_dimensions(detectors, reliability=None)
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False
    )
    assert verdict.drivers == ["context_window", "model_identity"]
    assert verdict.headline.startswith("Strong evidence the relay does not deliver the claimed model")


def test_verdict_custom_billing_run_is_judged():
    # A custom run of billing alone: inflated usage is HIGH, not "insufficient
    # signal", and the unmatched profile does not cap a profile-free run.
    detectors = [_high(Dimension.BILLING, "billing.usage-inflation", "Usage inflated")]
    dims = build_dimensions(detectors, reliability=None, selected=["billing"])
    verdict = build_verdict(
        detectors, dims, profile_matched=False, used_judge=False, used_baseline=False,
        selected=["billing"],
    )
    assert verdict.risk_level == RiskLevel.HIGH
    assert verdict.drivers == ["billing"]
    assert "Billing & usage" in verdict.headline
    assert "Model identity was not selected" in verdict.summary
    assert "knowledge base" not in verdict.summary


def test_verdict_custom_clean_run_without_identity_is_scoped():
    detectors = [
        _result(Dimension.STREAMING, score=100.0, status=Status.PASS, findings=[_info("streaming")]),
        _result(Dimension.PROTOCOL, score=100.0, status=Status.PASS, findings=[_info("protocol")]),
    ]
    selected = ["streaming", "protocol"]
    dims = build_dimensions(detectors, reliability=None, selected=selected)
    verdict = build_verdict(
        detectors, dims, profile_matched=False, used_judge=False, used_baseline=False,
        selected=selected,
    )
    assert verdict.risk_level == RiskLevel.CLEAN
    assert verdict.confidence == "medium"
    assert verdict.headline.startswith("No problems found in the checked dimensions; model identity was not verified.")


def test_verdict_custom_run_of_connectivity_only_is_inconclusive():
    detectors = [_result(Dimension.CONNECTIVITY, score=100.0, status=Status.PASS, findings=[_info("conn")])]
    dims = build_dimensions(detectors, reliability=None, selected=["connectivity"])
    verdict = build_verdict(
        detectors, dims, profile_matched=True, used_judge=False, used_baseline=False,
        selected=["connectivity"],
    )
    assert verdict.risk_level == RiskLevel.INCONCLUSIVE
    assert verdict.drivers == []


# --------------------------------------------------------------------------- #
# The overall score and rating agree with the risk verdict (#247): a serious
# finding caps its dimension at its detector's score, and the risk level caps
# the overall score (high <= 49, medium <= 69), so no report reads "rating A,
# risk high". Advisory and connectivity findings cap nothing.
# --------------------------------------------------------------------------- #
_CHAT = [
    "connectivity", "protocol", "protocol_request", "protocol_response", "determinism",
    "context_window", "model_identity", "capability", "vision", "streaming", "billing",
    "reliability", "security", "injected_prompt", "integrity", "performance",
]


def _clean(surface_ids: list[str] = _CHAT) -> dict[str, DetectorResult]:
    return {
        i: DetectorResult(id=i, name=i, dimension=REGISTRY[i].dimension, score=100.0,
                          status=Status.PASS)
        for i in surface_ids
    }


def _failing(det: str, fid: str, severity: Severity, score: float) -> DetectorResult:
    return DetectorResult(
        id=det, name=det, dimension=REGISTRY[det].dimension, score=score, status=Status.FAIL,
        findings=[Finding(id=fid, check=fid, title=f"{fid} title", status=Status.FAIL,
                          severity=severity, summary="")],
    )


def _judge(detectors: list[DetectorResult], surface: str = "chat"):
    dims = build_dimensions(detectors, None, surface=surface)
    verdict = build_verdict(detectors, dims, profile_matched=True, used_judge=False,
                            used_baseline=True, surface=surface)
    return dims, verdict


def _dim(dims, dimension: Dimension):
    return next(d for d in dims if d.dimension == dimension)


# The five rows of the issue: everything else clean.
_ROWS = [
    ("integrity", "integrity.tampering", Severity.CRITICAL, 10.0, RiskLevel.HIGH, 94.6),
    ("billing", "billing.usage-inflation", Severity.HIGH, 55.0, RiskLevel.HIGH, 96.4),
    ("security", "security.key_echo", Severity.HIGH, 30.0, RiskLevel.MEDIUM, 97.2),
    ("model_identity", "model_identity.self_id", Severity.HIGH, 20.0, RiskLevel.HIGH, 83.2),
    ("context_window", "context_window.truncation", Severity.HIGH, 11.0, RiskLevel.HIGH, 83.1),
]


@pytest.mark.parametrize(("det", "fid", "severity", "score", "risk", "uncapped"), _ROWS,
                         ids=[r[1] for r in _ROWS])
def test_the_risk_caps_the_overall_score(det, fid, severity, score, risk, uncapped):
    detectors = _clean()
    detectors[det] = _failing(det, fid, severity, score)
    _, v = _judge(list(detectors.values()))
    assert v.risk_level == risk
    cap = RISK_SCORE_CAPS[risk]
    assert v.overall_score == cap and v.rating == rating(cap)
    assert v.rating not in ("A", "B") and (risk != RiskLevel.HIGH or v.rating == "F")
    assert v.uncapped_score == uncapped
    assert v.score_cap is not None
    assert (v.score_cap.risk_level, v.score_cap.cap, v.score_cap.findings) == (risk, cap, [fid])
    assert (f"Overall health score {cap}/100. Score capped at {cap:g} because the risk level is "
            f"{risk.value}; the weighted mean of the dimensions is {uncapped}.") in v.summary


def test_a_serious_finding_caps_its_dimension():
    detectors = _clean()
    detectors["integrity"] = _failing("integrity", "integrity.tampering", Severity.CRITICAL, 10.0)
    dims, _ = _judge(list(detectors.values()))
    d = _dim(dims, Dimension.INTEGRITY)
    assert d.score == 10.0  # not the mean of integrity, injected_prompt, determinism: 70
    cap = d.breakdown.score_cap
    assert cap is not None
    assert (cap.detector, cap.findings, cap.cap, cap.uncapped_score) == (
        "integrity", ["integrity.tampering"], 10.0, 70.0)


def test_the_lowest_capping_detector_wins_and_medium_findings_do_not_cap():
    detectors = _clean()
    detectors["protocol"] = _failing("protocol", "protocol.a", Severity.HIGH, 60.0)
    detectors["protocol_request"] = _failing("protocol_request", "protocol.b", Severity.HIGH, 40.0)
    detectors["protocol_response"] = _failing("protocol_response", "protocol.c", Severity.MEDIUM, 100.0)
    dims, _ = _judge(list(detectors.values()))
    d = _dim(dims, Dimension.PROTOCOL)
    assert d.score == 40.0
    assert d.breakdown.score_cap.detector == "protocol_request"


def test_no_cap_when_the_capping_detector_scores_above_the_mean():
    detectors = _clean()
    detectors["protocol"] = _failing("protocol", "protocol.a", Severity.HIGH, 90.0)
    detectors["protocol_request"] = DetectorResult(
        id="protocol_request", name="r", dimension=Dimension.PROTOCOL, score=0.0, status=Status.FAIL)
    dims, _ = _judge(list(detectors.values()))
    d = _dim(dims, Dimension.PROTOCOL)
    assert d.breakdown.score_cap is None and d.score == round((90 + 0 + 100) / 3, 1)


def test_plain_http_lowers_only_its_dimension():
    detectors = _clean()
    detectors["security"] = _failing("security", "security.tls", Severity.HIGH, 40.0)
    dims, v = _judge(list(detectors.values()))
    assert v.risk_level == RiskLevel.CLEAN
    assert v.score_cap is None and v.overall_score == v.uncapped_score == 97.6
    assert v.rating == "A" and "capped" not in v.summary
    assert _dim(dims, Dimension.SECURITY).score == 40.0


@pytest.mark.parametrize("fid", sorted(ADVISORY_CHECKS))
def test_advisory_findings_cap_no_dimension(fid):
    det = {"security": "security", "reliability": "reliability"}[fid.split(".")[0]]
    detectors = _clean()
    detectors[det] = _failing(det, fid, Severity.HIGH, 20.0)
    # a passing sibling in the same dimension, so a cap would show
    detectors["sibling"] = DetectorResult(id="sibling", name="s", dimension=REGISTRY[det].dimension,
                                          score=100.0, status=Status.PASS)
    dims, v = _judge(list(detectors.values()))
    assert _dim(dims, REGISTRY[det].dimension).breakdown.score_cap is None
    assert _dim(dims, REGISTRY[det].dimension).score == 60.0
    assert v.score_cap is None


def test_connectivity_findings_cap_nothing():
    detectors = _clean()
    detectors["connectivity"] = _failing("connectivity", "connectivity.down", Severity.CRITICAL, 0.0)
    detectors["sibling"] = DetectorResult(id="sibling", name="s", dimension=Dimension.CONNECTIVITY,
                                          score=100.0, status=Status.PASS)
    dims, v = _judge(list(detectors.values()))
    assert _dim(dims, Dimension.CONNECTIVITY).breakdown.score_cap is None
    assert _dim(dims, Dimension.CONNECTIVITY).score == 50.0
    assert v.risk_level == RiskLevel.CLEAN and v.score_cap is None


def test_low_clean_and_inconclusive_risks_are_uncapped():
    detectors = _clean()
    detectors["streaming"] = _failing("streaming", "streaming.x", Severity.MEDIUM, 0.0)
    _, v = _judge(list(detectors.values()))
    assert v.risk_level == RiskLevel.LOW and v.score_cap is None
    assert v.overall_score == v.uncapped_score
    # inconclusive: only connectivity ran
    _, v = _judge([_failing("connectivity", "connectivity.down", Severity.CRITICAL, 0.0)])
    assert v.risk_level == RiskLevel.INCONCLUSIVE and v.score_cap is None


@pytest.mark.parametrize("surface", ["chat", "embedding", "rerank"])
def test_no_combination_reads_a_or_b_with_high_risk(surface):
    ids = [i for i, d in REGISTRY.items() if d.surface == surface]
    rng = random.Random(247)
    severities = list(Severity)
    for _ in range(400):
        detectors = []
        for i in ids:
            det = REGISTRY[i]
            findings = [
                Finding(id=f"{i}.f{n}", title="t", status=Status.FAIL, severity=rng.choice(severities))
                for n in range(rng.randint(0, 2))
            ]
            detectors.append(DetectorResult(
                id=i, name=i, dimension=det.dimension, score=rng.choice([None, 0.0, 30.0, 70.0, 100.0]),
                status=Status.FAIL if findings else Status.PASS, findings=findings))
        _, v = _judge(detectors, surface)
        if v.risk_level == RiskLevel.HIGH:
            assert v.rating not in ("A", "B", "C", "D"), v
        if v.risk_level == RiskLevel.MEDIUM:
            assert v.rating not in ("A", "B", "C"), v


def _report(detectors: list[DetectorResult]) -> AuditReport:
    dims, v = _judge(detectors)
    return AuditReport(
        tool_version="test", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="u", model="m"),
        verdict=v, dimensions=dims, detectors=detectors,
    )


def _tampered() -> AuditReport:
    detectors = _clean()
    detectors["integrity"] = _failing("integrity", "integrity.tampering", Severity.CRITICAL, 10.0)
    return _report(list(detectors.values()))


def test_markdown_and_html_show_both_caps():
    report = _tampered()
    md = render_markdown(report)
    assert "_Score: Capped at 49 by the high risk (weighted mean of the dimensions 94.6); " in md
    assert "integrity.tampering" in md
    assert ("→ 70. Capped at 10, the score of integrity, by its HIGH/CRITICAL finding "
            "(integrity.tampering)") in md.replace("\\_", "_")
    page = render_html(report)
    assert 'class="meta score-cap">Score: Capped at 49 by the high risk' in page
    assert "Capped at 10, the score of integrity" in page


def test_pdf_shows_both_caps():
    pytest.importorskip("reportlab")
    from reportlab.platypus import Paragraph

    from ekte.report.pdf import _dimension_details, _header

    def texts(flowables) -> str:
        return " ".join(fl.getPlainText() for fl in flowables if isinstance(fl, Paragraph))

    report = _tampered()
    assert "Score: Capped at 49 by the high risk" in texts(_header(report))
    assert "Capped at 10, the score of integrity" in texts(_dimension_details(report))


def test_reports_without_caps_validate_and_render():
    # a 1.5 report: no uncapped_score / score_cap
    report = AuditReport.model_validate(json.loads(_report(list(_clean().values())).model_dump_json(
        exclude={"verdict": {"uncapped_score", "score_cap"}})))
    assert report.verdict.score_cap is None
    assert "Capped" not in render_markdown(report)
    assert not re.search(r"score-cap", render_html(report))


# --------------------------------------------------------------------------- #
# Coverage limits the rating (#249): a dimension that ran but could not be
# judged drops out of the weighted mean, so the rating says how much was
# judged: below 50% of the weight of the dimensions that ran there is no
# rating, below 80% (or with a core dimension not judged) it is at most B.
# --------------------------------------------------------------------------- #
def _unjudged(det: str, status: Status = Status.INCONCLUSIVE) -> DetectorResult:
    return DetectorResult(id=det, name=det, dimension=REGISTRY[det].dimension, score=None,
                          status=status)


def test_an_unjudged_context_window_no_longer_rates_a():
    detectors = _clean()
    detectors["context_window"] = _unjudged("context_window")
    _, v = _judge(list(detectors.values()))
    assert v.overall_score == 100.0 and v.risk_level == RiskLevel.CLEAN
    assert v.coverage == 0.81 and v.not_judged == ["context_window"]
    assert v.rating == COVERAGE_RATING_LIMIT == "B"
    assert v.rating_limit is not None
    assert (v.rating_limit.reason, v.rating_limit.limit, v.rating_limit.unlimited_rating) == (
        "core_not_judged", "B", "A")
    assert ("Coverage 81%: Context window ran but could not be judged. Rating limited to B "
            "because a core dimension could not be judged.") in v.summary


def test_only_identity_and_security_judged_is_not_rated():
    detectors = {
        i: d if d.dimension in (Dimension.MODEL_IDENTITY, Dimension.SECURITY) else _unjudged(i)
        for i, d in _clean().items()
    }
    _, v = _judge(list(detectors.values()))
    assert v.overall_score == 100.0
    assert v.coverage == 0.25 and v.rating is None
    assert v.rating_limit is not None
    assert (v.rating_limit.reason, v.rating_limit.limit) == ("low_coverage", None)
    assert "context_window" in v.not_judged and "model_identity" not in v.not_judged
    assert "Not rated: too little was judged (coverage below 50%)." in v.summary


def test_low_coverage_limits_the_rating_to_b():
    # protocol, streaming, reliability, integrity, security, performance: 32 of 100
    peripheral = (Dimension.PROTOCOL, Dimension.STREAMING, Dimension.RELIABILITY,
                  Dimension.INTEGRITY, Dimension.SECURITY, Dimension.PERFORMANCE)
    detectors = {i: _unjudged(i) if d.dimension in peripheral else d for i, d in _clean().items()}
    _, v = _judge(list(detectors.values()))
    assert v.coverage == 0.68 and v.rating == "B"
    assert v.rating_limit is not None and v.rating_limit.reason == "low_coverage"
    assert "Rating limited to B because coverage is below 80%." in v.summary


def test_a_crashed_dimension_is_not_judged_and_info_only_does_not_count():
    detectors = _clean()
    detectors["streaming"] = _unjudged("streaming", Status.ERROR)
    _, v = _judge(list(detectors.values()))
    assert v.not_judged == ["streaming"] and v.coverage == 0.94
    assert v.rating == "A" and v.rating_limit is None  # 94%, no core dimension missing
    # a dimension whose detectors only reported information (nothing claimed) does not count
    detectors = _clean()
    detectors["context_window"] = _unjudged("context_window", Status.INFO)
    _, v = _judge(list(detectors.values()))
    assert v.coverage == 1.0 and v.not_judged == [] and v.rating == "A"


def test_full_coverage_keeps_the_rating():
    _, v = _judge(list(_clean().values()))
    assert v.coverage == 1.0 and v.not_judged == [] and v.rating_limit is None
    assert v.rating == "A" and "Coverage" not in v.summary


def test_custom_run_of_two_scored_dimensions_keeps_coverage_and_rating():
    detectors = [_clean()["billing"], _clean()["streaming"]]
    selected = ["billing", "streaming"]
    dims = build_dimensions(detectors, None, selected=selected)
    v = build_verdict(detectors, dims, profile_matched=True, used_judge=False,
                      used_baseline=True, selected=selected)
    assert v.coverage == 1.0 and v.rating == "A" and v.rating_limit is None


def test_dimensions_not_in_the_suite_do_not_reduce_coverage():
    # a smoke run: connectivity and security only
    detectors = [_clean()["connectivity"], _clean()["security"]]
    _, v = _judge(detectors)
    assert v.coverage == 1.0 and v.not_judged == [] and v.rating == "A"
    # nothing ran: no coverage
    _, v = _judge([])
    assert v.coverage is None and v.rating is None and v.rating_limit is None


def test_no_rating_limit_when_the_rating_is_already_lower():
    detectors = _clean()
    detectors["integrity"] = _failing("integrity", "integrity.tampering", Severity.CRITICAL, 10.0)
    detectors["context_window"] = _unjudged("context_window")
    _, v = _judge(list(detectors.values()))
    assert v.rating == "F" and v.rating_limit is None and v.not_judged == ["context_window"]


def test_coverage_thresholds_and_percentages():
    assert (COVERAGE_UNRATED_BELOW, COVERAGE_LIMITED_BELOW) == (0.5, 0.8)
    assert coverage_pct(0.29) == 29 and coverage_pct(0.7999) == 79 and coverage_pct(1.0) == 100


@pytest.mark.parametrize("surface", ["embedding", "rerank"])
def test_an_unjudged_identity_limits_other_surfaces(surface):
    ids = [i for i, d in REGISTRY.items() if d.surface == surface]
    detectors = [
        _unjudged(i) if REGISTRY[i].dimension == Dimension.MODEL_IDENTITY
        else DetectorResult(id=i, name=i, dimension=REGISTRY[i].dimension, score=100.0,
                            status=Status.PASS)
        for i in ids
    ]
    _, v = _judge(detectors, surface)
    assert "model_identity" in v.not_judged and v.rating not in ("A", None)


def _unjudged_report(only: tuple[Dimension, ...] | None = None) -> AuditReport:
    if only is None:
        detectors = _clean()
        detectors["context_window"] = _unjudged("context_window")
    else:
        detectors = {i: d if d.dimension in only else _unjudged(i) for i, d in _clean().items()}
    return _report(list(detectors.values()))


def test_reports_show_coverage_and_the_rating_limit():
    from ekte.report import compact_dict

    report = _unjudged_report()
    md = render_markdown(report)
    assert "**Coverage:** 81%  ·  **Rating:** B" in md
    assert ("_Coverage 81%: not judged (ran without a usable result): Context window; rating at "
            "most B (a core dimension could not be judged; the score alone gives A)._") in md
    page = render_html(report)
    assert "<span>coverage <strong>81%</strong></span>" in page
    assert 'class="meta coverage">Coverage 81%: not judged' in page
    c = compact_dict(report)["verdict"]
    assert (c["coverage"], c["not_judged"], c["rating"]) == (0.81, ["context_window"], "B")
    assert c["rating_limit"] == {"reason": "core_not_judged", "limit": "B", "unlimited_rating": "A"}
    # not rated
    report = _unjudged_report((Dimension.MODEL_IDENTITY, Dimension.SECURITY))
    md = render_markdown(report)
    assert "**Coverage:** 25%  ·  **Rating:** not rated: too little was judged" in md
    assert "no rating (coverage below 50%; the score alone gives A)" in md
    assert "rating <strong>not rated: too little was judged</strong>" in render_html(report)


def test_pdf_shows_coverage():
    pytest.importorskip("reportlab")
    from reportlab.platypus import Paragraph

    from ekte.report.pdf import _header

    text = " ".join(fl.getPlainText() for fl in _header(_unjudged_report((
        Dimension.MODEL_IDENTITY, Dimension.SECURITY))) if isinstance(fl, Paragraph))
    assert "coverage 25%" in text and "rating not rated: too little was judged" in text
    assert "Coverage 25%: not judged" in text


def test_reports_without_coverage_validate_and_render():
    # a report written before coverage existed
    report = AuditReport.model_validate(json.loads(_report(list(_clean().values())).model_dump_json(
        exclude={"verdict": {"coverage", "not_judged", "rating_limit"}})))
    assert report.verdict.coverage is None
    assert "**Coverage:** —" in render_markdown(report)
    assert 'class="meta coverage"' not in render_html(report)


def test_a_smoke_run_against_an_honest_relay_has_full_coverage(monkeypatch):
    import asyncio

    from ekte.clients import make_client as real
    from ekte.config import AuditOptions
    from ekte.models import TargetConfig
    from ekte.runner import run_audit
    from tests._helpers import BASE_URL, DEFAULT_MODEL, MockServer

    server = MockServer()
    monkeypatch.setattr(
        "ekte.runner.make_client", lambda config, **_: real(config, transport=server.transport))
    target = TargetConfig(name="t", kind="target", base_url=BASE_URL, model=DEFAULT_MODEL)
    report = asyncio.run(run_audit(target, AuditOptions(suite="smoke")))
    v = report.verdict
    assert v.coverage == 1.0 and v.not_judged == [] and v.rating_limit is None
    assert v.rating == rating(v.overall_score)
