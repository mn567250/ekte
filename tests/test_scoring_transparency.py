"""Transparent scoring: published scales, dimension breakdowns, report details.

The protocol detector is the pilot of the pattern: each check scores points from
a published scale (``SCALE``), inconclusive checks are left out of the mean, and
the dimension records how its score and status were derived so the reports can
explain both — positive and negative findings alike.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from zing.detectors.protocol import SCALE, ProtocolDetector
from zing.detectors.scale import Scale, outcome
from zing.models import (
    AuditReport,
    CompletionOutcome,
    DetectorResult,
    Dimension,
    Finding,
    RedactedTarget,
    Severity,
    Status,
    Verdict,
)
from zing.report import compact_dict, render_html, render_markdown
from zing.scoring import build_dimensions

_BLUE = CompletionOutcome(ok=True, status_code=200, content="Your favorite color is blue.",
                          finish_reason="stop",
                          usage={"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14})
_STOPPED = CompletionOutcome(ok=True, status_code=200, content="alpha ", finish_reason="stop")
_REJECTED = CompletionOutcome(ok=False, status_code=400,
                              raw_error={"error": {"message": "messages is empty"}})
_TIMEOUT = CompletionOutcome(ok=False, error_type="timeout", error_message="Read timed out.")


async def _run(*outcomes: CompletionOutcome) -> DetectorResult:
    queue = list(outcomes)

    async def complete(_spec):
        return queue.pop(0)

    ctx = SimpleNamespace(client=SimpleNamespace(complete=complete))
    return await ProtocolDetector().run(ctx)  # type: ignore[arg-type]


def _finding(result: DetectorResult, fid: str) -> Finding:
    return next(f for f in result.findings if f.id == fid)


async def test_every_check_scores_from_the_published_scale():
    result = await _run(_BLUE, _STOPPED, _REJECTED)
    assert result.score == 100.0 and result.status == Status.PASS
    assert result.scoring is not None and result.scoring.method == "mean_of_checks"
    assert len(result.scoring.outcomes) == len(SCALE.outcomes)
    for f in result.findings:
        o = SCALE.get(f.id, f.outcome or "")
        assert (f.score, f.status, f.severity) == (o.score, o.status, o.severity)
    assert [f.outcome for f in result.findings] == [
        "recalled", "truncated", "rejected_openai_body",
    ]


async def test_inconclusive_checks_are_left_out_of_the_mean():
    # stop (no content) is not counted: (55 + 100) / 2, not / 3 with a 50
    forgotten = CompletionOutcome(ok=True, status_code=200, content="I don't know.")
    result = await _run(forgotten, _TIMEOUT, _REJECTED)
    stop = _finding(result, "protocol.stop")
    assert stop.status == Status.INCONCLUSIVE and stop.outcome == "no_content"
    assert stop.score is None
    assert result.score == 77.5
    assert _finding(result, "protocol.multi_turn").score == 55.0


async def test_no_counted_check_means_no_score():
    result = await _run(_TIMEOUT, _TIMEOUT, _REJECTED)
    assert result.score == 100.0  # error_schema still counts: a rejection is conclusive
    result = await _run(_TIMEOUT, _TIMEOUT, _TIMEOUT)
    # a request that never got an HTTP response is still a (WARN) outcome
    assert _finding(result, "protocol.error_schema").outcome == "no_http_response"
    assert result.score == 55.0
    assert Scale.mean([f for f in result.findings if f.id != "protocol.error_schema"]) is None


def test_scale_rejects_duplicate_outcomes():
    with pytest.raises(ValueError):
        Scale(outcome("c", "a", 1.0, Status.PASS, label="x"), outcome("c", "a", 2.0, Status.PASS, label="y"))


def test_every_protocol_outcome_has_a_label():
    assert all(o.label for o in SCALE.outcomes)
    checks = {o.check for o in SCALE.outcomes}
    assert checks == {"protocol.multi_turn", "protocol.stop", "protocol.error_schema"}


def _det(id_: str, score: float | None, status: Status, *findings: Finding) -> DetectorResult:
    return DetectorResult(id=id_, name=id_.title(), dimension=Dimension.PROTOCOL,
                          score=score, status=status, findings=list(findings))


def test_dimension_breakdown_uses_equal_detector_weights():
    dims = build_dimensions(
        [_det("protocol", 80.0, Status.PASS), _det("determinism", 100.0, Status.PASS),
         _det("other", None, Status.INCONCLUSIVE)],
        None,
    )
    d = next(x for x in dims if x.dimension == Dimension.PROTOCOL)
    assert d.score == 90.0
    b = d.breakdown
    assert b is not None and b.method == "mean_of_detectors"
    assert [(c.detector, c.counted) for c in b.detectors] == [
        ("protocol", True), ("determinism", True), ("other", False),
    ]
    assert b.status_override is None and b.detector_status == Status.INCONCLUSIVE


def test_dimension_breakdown_explains_a_severity_override():
    medium = Finding(id="protocol.multi_turn", title="Multi-turn", status=Status.WARN,
                     severity=Severity.MEDIUM)
    dims = build_dimensions([_det("protocol", 88.8, Status.PASS, medium)], None)
    d = next(x for x in dims if x.dimension == Dimension.PROTOCOL)
    assert d.status == Status.WARN
    o = d.breakdown.status_override
    assert o is not None
    assert (o.from_status, o.to_status, o.severity) == (Status.PASS, Status.WARN, Severity.MEDIUM)
    assert o.findings == ["protocol.multi_turn"]
    # dimensions that did not run carry an empty breakdown
    assert next(x for x in dims if x.dimension == Dimension.BILLING).breakdown.detectors == []


async def _report() -> AuditReport:
    forgotten = CompletionOutcome(ok=True, status_code=200, content="I don't know.")
    protocol = await _run(forgotten, _TIMEOUT, _REJECTED)
    legacy = _det("determinism", 100.0, Status.PASS,
                  Finding(id="determinism.temp1_variability", title="Output varies at temperature=1.0",
                          status=Status.PASS))
    detectors = [protocol, legacy]
    return AuditReport(
        tool_version="test", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="http://relay.test/v1", model="gpt-4o"),
        verdict=Verdict(), dimensions=build_dimensions(detectors, None), detectors=detectors,
    )


async def test_markdown_explains_scores_status_and_scale():
    md = render_markdown(await _report())
    details = md[md.index("## Dimension details"):md.index("## Findings")]
    assert "### ⚠️ protocol — 88.8 (warn)" in details
    assert "Mean of 2 detectors, equal weight: OpenAI-compatibility conformance 77.5, Determinism 100 → 88.8." in details
    assert "- Status warn: the worst status its detectors concluded." in details
    # every check with its outcome and points, positive and negative
    assert "| ⚠️ | Multi-turn conversation memory | The color from an earlier turn was not recalled. | 55 |" in details
    assert "| ✅ | Error response schema | Rejected with a 4xx and an OpenAI-style error body. | 100 |" in details
    assert "| not counted |" in details
    # the full scale, including outcomes that did not happen
    assert "  - 30: The invalid request was accepted (2xx)." in details
    # a detector without a scale still lists its findings
    assert "- ✅ Output varies at temperature=1.0" in details
    # dimensions that did not run are listed too, with the reason
    assert "### ➖ billing — — (not_run)\n\n- Not run in this suite." in details


async def test_html_has_expandable_dimension_details():
    page = render_html(await _report())
    assert page.count('<details class="dim">') == 10  # every dimension, run or not
    assert "Scoring scale" in page and "not counted" in page
    assert "The invalid request was accepted (2xx)." in page


async def test_compact_carries_points():
    compact = compact_dict(await _report())
    points = {f["id"]: f.get("points") for f in compact["findings"]}
    assert points["protocol.multi_turn"] == 55.0 and points["protocol.stop"] is None


def test_markdown_explains_a_status_override():
    medium = Finding(id="protocol.multi_turn", title="Multi-turn", status=Status.WARN,
                     severity=Severity.MEDIUM)
    detectors = [_det("protocol", 88.8, Status.PASS, medium)]
    report = AuditReport(
        tool_version="test", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="u", model="m"),
        verdict=Verdict(), dimensions=build_dimensions(detectors, None), detectors=detectors,
    )
    md = render_markdown(report)
    assert "Score of one detector: Protocol 88.8." in md
    assert "Status warn: raised from pass by 1 medium-severity finding (protocol.multi\\_turn)" in md


def test_reports_without_breakdown_still_render():
    report = AuditReport.model_validate({
        "tool_version": "old", "mode": "check", "suite": "standard",
        "target": {"name": "t", "kind": "target", "base_url": "u", "model": "m"},
        "verdict": {},
        "dimensions": [{"dimension": "protocol", "score": 70.0, "weight": 8.0, "status": "warn"}],
        "detectors": [{"id": "protocol", "name": "P", "dimension": "protocol", "score": 70.0,
                       "status": "warn", "findings": [{"id": "protocol.stop", "title": "Stop",
                                                       "status": "warn"}]}],
    })
    md = render_markdown(report)
    assert "Score of one detector: P 70." in md and "- ⚠️ Stop" in md


# --------------------------------------------------------------------------- #
# Parametrized checks: many subjects, one row
# --------------------------------------------------------------------------- #
async def _attr_report() -> AuditReport:
    """The response-attribute detector on a body with a zero completion count
    and no id: 12 attribute findings in two parametrized checks (8 core, 4 minor)."""
    from tests.test_protocol_attrs import BODIES, _drop, _respond, _set

    body = _drop(_set(BODIES["openai"], "usage.completion_tokens", 0), "id")
    body["usage"]["total_tokens"] = 12
    det, _ = await _respond("openai", body)
    return AuditReport(
        tool_version="test", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="http://relay.test/v1", model="gpt-4o"),
        verdict=Verdict(), dimensions=build_dimensions([det], None), detectors=[det],
    )


def test_scale_finding_with_a_subject():
    f = SCALE.finding("protocol.stop", "ignored", title="t")
    assert (f.id, f.check, f.subject, f.scale_check) == ("protocol.stop", None, None, "protocol.stop")
    g = Scale(outcome("c", "ok", 100.0, Status.PASS, label="x"), titles={"c": "C"})
    f = g.finding("c", "ok", title="t", subject="a.b")
    assert (f.id, f.check, f.subject, f.scale_check) == ("c.a.b", "c", "a.b", "c")
    assert g.scoring().titles == {"c": "C"}


async def test_markdown_groups_the_subjects_of_a_check():
    md = render_markdown(await _attr_report())
    details = md[md.index("## Dimension details"):md.index("## Findings")]
    # one row per parametrized check, problems named, points averaged
    assert "| ❌ | Core response attributes | 7 of 8 OK; usage.completion\\_tokens (Present but zero or empty" in details
    assert "| ⚠️ | Minor response attributes | 3 of 4 OK; id (Missing from the response.) | avg 90 |" in details
    assert details.count("| ❌ |") + details.count("| ⚠️ |") == 2 + 2  # two groups + two subject rows
    # every subject with its observed value and points, behind a disclosure
    assert "<details><summary>Core response attributes: all 8</summary>" in details
    assert "| ✅ | `usage.prompt\\_tokens` | 12 | Present with a valid value. | 100 |" in details
    assert "| ❌ | `usage.completion\\_tokens` | 0 |" in details
    # the scale lists each check once, not once per subject
    assert details.count("(`protocol_response.core`)") == 1
    # the findings section keeps problems itemised, passed subjects folded
    findings = md[md.index("## Findings"):]
    assert "**Core response attributes** — 7 passed: model, choices" in findings
    assert "Response attribute usage.completion\\_tokens" in findings
    assert "Response attribute usage.prompt\\_tokens" not in findings


async def test_html_groups_the_subjects_of_a_check():
    page = render_html(await _attr_report())
    assert page.count("<summary>All 8</summary>") == 1 and page.count("<summary>All 4</summary>") == 1
    assert "7 of 8 OK; usage.completion_tokens (Present but zero or empty" in page
    assert "<code>usage.completion_tokens</code></td><td><code>0</code>" in page
    assert "7 passed: <code>model, choices" in page


def _deduction_report() -> AuditReport:
    """A deduction-scored detector with one parametrized check: one subject
    passes, one deducts 20, one errored."""
    from zing.detectors.scale import DeductionScale

    scale = DeductionScale(
        outcome("d.attr", "ok", None, Status.PASS, label="Fine."),
        outcome("d.attr", "bad", None, Status.WARN, Severity.LOW, label="Bad.", deduction=20.0),
        outcome("d.attr", "error", None, Status.ERROR, label="Errored."),
        titles={"d.attr": "Attributes"},
    )
    findings = [
        scale.finding("d.attr", key, title=f"Attribute {sub}", subject=sub)
        for key, sub in (("ok", "a"), ("bad", "b"), ("error", "c"))
    ]
    det = DetectorResult(
        id="d", name="D", dimension=Dimension.PROTOCOL, status=Status.WARN,
        score=DeductionScale.total(findings), findings=findings, scoring=scale.scoring(),
    )
    return AuditReport(
        tool_version="test", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="http://relay.test/v1", model="m"),
        verdict=Verdict(), dimensions=build_dimensions([det], None), detectors=[det],
    )


def test_html_group_rows_use_the_detector_scoring_method():
    # A deduction scale's subject rows show what each deducted, as in Markdown,
    # not "not counted" as if the points were a mean of checks.
    report = _deduction_report()
    page = render_html(report)
    assert "<code>b</code>" in page and '<td class="num">−20</td>' in page
    assert '<td class="num">no deduction</td>' in page
    md = render_markdown(report)
    assert "| `b` | — | Bad. | −20 |" in md
    # the group row sums its subjects' deductions rather than averaging scores
    assert "| Attributes | 1 of 3 OK; b (Bad.); c (Errored.) | −20 |" in md
    assert page.count('<td class="num">−20</td>') == 2  # the group row and subject b


def test_pdf_group_rows_use_the_detector_scoring_method():
    pytest.importorskip("reportlab")
    from reportlab.platypus import Paragraph, Table

    from zing.report.pdf import _dimension_detector

    def texts(flowables) -> list[str]:
        out = []
        for fl in flowables:
            if isinstance(fl, Paragraph):
                out.append(fl.getPlainText())
            elif isinstance(fl, Table):
                out += texts(c for row in fl._cellvalues for c in row)
        return out

    cells = texts(_dimension_detector(_deduction_report().detectors[0]))
    assert cells.count("−20") == 2  # the group row and subject b
    assert "no deduction" in cells and "not counted" not in cells


def test_group_status_follows_the_scoring_order():
    # Like a dimension status: a warning outranks a detector error, and a pass
    # outranks an informational note.
    from zing.report.dimensions import _Group

    report = _deduction_report()
    group = _Group("d.attr", "Attributes", list(report.detectors[0].findings))
    assert group.status == Status.WARN
    info = Finding(id="x", title="x", status=Status.INFO)
    passed = Finding(id="y", title="y", status=Status.PASS)
    assert _Group("x", "x", [info, passed]).status == Status.PASS
