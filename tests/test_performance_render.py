"""The performance section in the Markdown, HTML, compact and CLI outputs."""

from __future__ import annotations

import io
import re

import pytest
from rich.console import Console

from ekte import cli
from ekte.models import AuditReport, RedactedTarget, RequestRecord, Verdict
from ekte.perf import build_performance
from ekte.report import compact_dict, render_html, render_markdown
from ekte.report.performance import fmt_num, nice_axis, timeline_svg


def _rec(seq: int, endpoint: str, **kw) -> RequestRecord:
    base: dict = {
        "seq": seq, "endpoint": endpoint, "phase": "probe", "detector": "performance",
        "ok": True, "stream": True, "start_ms": seq * 1500.0, "duration_ms": 1200.0 + seq,
        "ttft_ms": 300.0, "decode_tps_local": 110.0, "decode_tps_reported": 112.0,
        "itl_mean_ms": 9.0, "output_tokens_local": 128, "input_tokens_local": 40,
    }
    base.update(kw)
    return RequestRecord(**base)


def _report(*, baseline: bool = True, perf: bool = True) -> AuditReport:
    recs = [_rec(i, "target") for i in range(6)]
    recs.append(_rec(6, "target", ok=False, status_code=502, ttft_ms=None, detector="<script>"))
    if baseline:
        recs += [_rec(10 + i, "baseline", decode_tps_local=60.0, duration_ms=1000.0 + i) for i in range(6)]
    return AuditReport(
        tool_version="0.0.0",
        mode="compare" if baseline else "check",
        suite="deep",
        target=RedactedTarget(name="t", kind="target", base_url="https://r/v1", model="m"),
        baseline=(
            RedactedTarget(name="b", kind="baseline", base_url="https://b/v1", model="m")
            if baseline
            else None
        ),
        verdict=Verdict(),
        performance=build_performance(recs, has_baseline=baseline, probe_max_tokens=128)
        if perf
        else None,
    )


def test_markdown_has_stats_and_comparison():
    md = render_markdown(_report())
    # the measurements sit in the performance dimension's details
    details = md[md.index("## Dimension details"):md.index("## Findings")]
    perf = details[details.index("### ➖ performance"):]
    assert "#### Performance measurements" in perf
    assert "## Performance" not in md.replace("#### Performance measurements", "")
    assert "dedicated probe — 7 uncacheable streaming requests per endpoint" in md
    assert "| Latency (ms) | 6 |" in md
    assert "##### Target vs baseline" in perf
    # higher tokens/s is better for the target, higher latency worse
    assert re.search(r"\| Decode speed p50 \(local\) \(tok/s\) \| 110 \| 60\.0 \| 🟢 ✓ \+50\.0 \| 1\.83x \|", md)
    assert "| Latency p50 (ms) | 1,202 | 1,002 | 🔴 ✗ +200 |" in md


def test_html_draws_inline_svg_without_scripts():
    page = render_html(_report())
    assert "<h2>Performance</h2>" not in page  # no separate card
    details = page[page.index("<h2>Dimension details</h2>"):]
    dim = details[details.index("<strong>performance</strong>"):]
    section = dim[dim.index("<h4>Performance measurements</h4>"):]
    assert "<svg" in section and 'class="pt target"' in section and 'class="pt baseline"' in section
    assert 'class="fail-mark"' in section  # the failed request is marked
    assert "<script" not in page  # self-contained, no JS
    assert "&lt;script&gt;" in section  # tooltips are escaped
    assert 'id="perf-latency"' in section and 'id="panel-ttft"' in section
    assert '<td class="num delta better">✓ +50.0</td>' in section
    assert 'class="num delta worse">✗ +200</td>' in section


def test_old_reports_without_performance_still_render():
    report = _report(perf=False)
    assert "Performance measurements" not in render_markdown(report)
    assert "Performance measurements" not in render_html(report)
    assert compact_dict(report)["performance"] is None
    # A report saved before the field existed loads fine.
    raw = report.model_dump()
    raw.pop("performance")
    assert AuditReport.model_validate(raw).performance is None


def test_compact_carries_headline_numbers():
    perf = compact_dict(_report())["performance"]
    assert perf["source"] == "probe"
    assert perf["target"]["decode_tps_p50"] == 110.0
    assert perf["comparison"]["decode_tps_local_p50"]["ratio"] == 1.833


def test_cli_summary_prints_performance(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buf, width=200))
    cli._print_summary(_report(), [])
    text = buf.getvalue()
    assert "Performance (target, stream)" in text and "Performance (baseline, stream)" in text
    assert "decode 110 tok/s" in text


def test_helpers():
    assert nice_axis(0) == (1.0, 0.25, 4)
    assert nice_axis(3.2) == (4, 1, 4)
    assert nice_axis(110) == (120, 20, 6)
    assert nice_axis(250) == (250, 50, 5)
    assert nice_axis(441) == (500, 100, 5)
    assert nice_axis(510) == (600, 100, 6)  # not 0..1000: no half-empty plot
    assert nice_axis(1300) == (1500, 250, 6)
    top, step, n = nice_axis(0.3)  # float noise must not add an interval
    assert n == 6 and step == pytest.approx(0.05) and top == pytest.approx(0.3)
    assert fmt_num(None) == "—" and fmt_num(0.0) == "0" and fmt_num(1234.5) == "1,234"
    assert fmt_num(0.031, "ratio") == "3.1%"
    assert "No Latency samples" in timeline_svg([], ("latency", "Latency", "ms", lambda r: r.duration_ms))


def test_timeline_axes_fit_the_data():
    recs = [RequestRecord(seq=i, endpoint="target", phase="probe", ok=True, stream=True,
                          start_ms=i * 50_000.0, duration_ms=420.0) for i in range(11)]  # ends ~500.4 s
    svg = timeline_svg(recs, ("latency", "Latency", "ms", lambda r: r.duration_ms))
    assert ">600s</text>" in svg and "1,000s" not in svg
    assert ">500</text>" in svg and ">1,000</text>" not in svg  # 420 ms x 1.05 -> 0..500


def test_every_dimension_is_listed_even_if_not_run():
    md = render_markdown(_report())
    details = md[md.index("## Dimension details"):md.index("## Findings")]
    for dim in ("connectivity", "protocol", "context_window", "model_identity", "capability",
                "streaming", "billing", "reliability", "security", "performance"):
        assert f"### ➖ {dim} — — (not_run)" in details, dim
        assert f"| {dim} | — |" in md, dim
    assert "- Not recorded in this report." in details
    page = render_html(_report())
    assert page.count('<details class="dim">') == 10
