"""The performance section of the Markdown, HTML and compact reports.

Pure functions of :class:`~ekte.models.PerformanceReport`. The HTML view draws
its charts as inline SVG (no scripts, no external assets) so the report stays a
single self-contained file: one timeline per metric, switched with CSS-only
tabs, with a native tooltip on every point.
"""

from __future__ import annotations

import html
import math
from collections.abc import Callable

from ekte.errorclass import LOCAL, NETWORK, record_class
from ekte.models import (
    EndpointPerformance,
    PerformanceComparison,
    PerformanceReport,
    PerfStats,
    RequestRecord,
)
from ekte.perf.trend import CHART_OPS, RunningMedian

# (label, unit, getter) — the stat table rows, in reading order.
STAT_ROWS: tuple[tuple[str, str, Callable[[EndpointPerformance], PerfStats]], ...] = (
    ("Latency", "ms", lambda e: e.latency_ms),
    ("Time to first token", "ms", lambda e: e.ttft_ms),
    ("Decode speed (usage)", "tok/s", lambda e: e.decode_tps_reported),
    ("Decode speed (local count)", "tok/s", lambda e: e.decode_tps_local),
    ("End-to-end speed (usage)", "tok/s", lambda e: e.e2e_tps_reported),
    ("End-to-end speed (local count)", "tok/s", lambda e: e.e2e_tps_local),
    ("Inter-chunk latency", "ms", lambda e: e.itl_ms),
    ("Inter-chunk jitter", "ms", lambda e: e.itl_jitter_ms),
    ("Server time (sent → first output)", "ms", lambda e: e.server_ms),
    ("Relay-reported processing", "ms", lambda e: e.relay_processing_ms),
    ("Network round trip (GET /models)", "ms", lambda e: e.network_rtt_ms),
    ("TCP connect", "ms", lambda e: e.connect_ms),
    ("TLS handshake", "ms", lambda e: e.tls_ms),
)
STAT_COLUMNS = ("count", "min", "mean", "p50", "p75", "p90", "p95", "p99", "max", "stdev")

COMPARE_LABELS = {
    "latency_p50": "Latency p50",
    "latency_p90": "Latency p90",
    "ttft_p50": "TTFT p50",
    "ttft_p90": "TTFT p90",
    "decode_tps_reported_p50": "Decode speed p50 (usage)",
    "decode_tps_local_p50": "Decode speed p50 (local)",
    "e2e_tps_local_p50": "End-to-end speed p50 (local)",
    "itl_p50": "Inter-chunk latency p50",
    "server_p50": "Server time p50",
    "network_rtt_p50": "Network round trip p50",
    "error_rate": "Error rate",
}


def _tps(r: RequestRecord) -> float | None:
    return r.decode_tps_local if r.decode_tps_local is not None else r.decode_tps_reported


# (id, label, unit, getter) — the chart metrics.
CHART_METRICS: tuple[tuple[str, str, str, Callable[[RequestRecord], float | None]], ...] = (
    ("latency", "Latency", "ms", lambda r: r.duration_ms),
    ("ttft", "TTFT", "ms", lambda r: r.ttft_ms),
    ("tps", "Decode speed", "tok/s", _tps),
    ("itl", "Inter-chunk latency", "ms", lambda r: r.itl_mean_ms),
)


def fmt_num(value: float | int | None, unit: str = "") -> str:
    if value is None:
        return "—"
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    if isinstance(value, int) or value == 0 or abs(value) >= 100:
        text = f"{value:,.0f}"
    elif abs(value) >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    return text


def _signed(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "ratio":
        return f"{value * 100:+.1f} pp"
    return ("+" if value > 0 else "") + fmt_num(value)


MODE_LABELS = {"stream": "streaming", "non_stream": "non-streaming"}
MODE_TITLES = {"stream": "Streaming", "non_stream": "Non-streaming"}


def _source_line(perf: PerformanceReport) -> str:
    if perf.source == "probe":
        modes = [perf.mode] + [m.mode for m in perf.modes]
        kind = " and ".join(MODE_LABELS.get(m, m) for m in modes)
        tokens = f", {perf.probe_max_tokens} output tokens each" if perf.probe_max_tokens else ""
        return (
            f"Source: dedicated probe — {perf.probe_requests} uncacheable {kind} "
            f"requests per endpoint{tokens}."
        )
    return "Source: the audit's own requests (no dedicated probe in this suite)."


# One block per measured request mode: (mode, target, baseline, comparison).
Block = tuple[str, EndpointPerformance, "EndpointPerformance | None", "list[PerformanceComparison]"]


def _blocks(perf: PerformanceReport) -> list[Block]:
    out: list[Block] = [(perf.mode, perf.target, perf.baseline, perf.comparison)]
    out += [(m.mode, m.target, m.baseline, m.comparison) for m in perf.modes]
    return out


def _endpoints(block: Block) -> list[EndpointPerformance]:
    return [e for e in (block[1], block[2]) if e is not None]


def _visible_rows(eps: list[EndpointPerformance]):
    """Stat rows with data for at least one endpoint."""
    return [row for row in STAT_ROWS if any(row[2](e).count for e in eps)]


def _block_title(perf: PerformanceReport, mode: str) -> str | None:
    """A heading per mode once more than one mode was measured."""
    return MODE_TITLES.get(mode, mode) if perf.modes else None


def _verdict_mark(c: PerformanceComparison) -> tuple[str, str]:
    """(css class, marker) for the target-vs-baseline delta."""
    better = c.target_better
    if better is None:
        return "same", ""
    return ("better", "✓ ") if better else ("worse", "✗ ")


def _reliability_line(e: EndpointPerformance) -> str:
    return (
        f"{e.successes}/{e.requests} succeeded · errors {fmt_num(e.error_rate, 'ratio')} · "
        f"timeouts {fmt_num(e.timeout_rate, 'ratio')} · 429 {fmt_num(e.rate_limited_rate, 'ratio')}"
        + (f" · {e.cached_excluded} cached (excluded)" if e.cached_excluded else "")
        + (f" · {e.network_errors} network failures (not the relay's)" if e.network_errors else "")
        + (f" · {e.local_errors} ekte failures (not the relay's)" if e.local_errors else "")
    )


def fail_text(r: RequestRecord) -> str:
    """A failed request's status, as the web UI's data table shows it:
    ``failed (502)`` at the relay, ``failed (ProxyError · network)`` on the
    network path, ``failed (TypeError · ekte)`` in ekte, ``repeated (…)`` for
    an attempt that was repeated."""
    what = str(r.status_code or r.error_type or "?")
    cls = record_class(r)
    if cls == NETWORK:
        what += " · network"
    elif cls == LOCAL:
        what += " · ekte"
    return f"{'repeated' if r.retried else 'failed'} ({what})"


def _extras(e: EndpointPerformance) -> list[str]:
    out: list[str] = []
    if e.cold_start_ms is not None:
        out.append(
            f"Cold start (first request): {fmt_num(e.cold_start_ms)} ms"
            + (f", TTFT {fmt_num(e.cold_start_ttft_ms)} ms" if e.cold_start_ttft_ms else "")
        )
    c = e.concurrency
    if c is not None:
        out.append(
            f"Under load ({c.requests} requests at concurrency {c.concurrency}): "
            f"{c.successes} succeeded, aggregate {fmt_num(c.aggregate_tps_local)} tok/s "
            f"(local) / {fmt_num(c.aggregate_tps_reported)} tok/s (usage), "
            f"latency p50 {fmt_num(c.latency_ms.p50)} ms"
        )
    return out


# --------------------------------------------------------------------------- #
# compact JSON
# --------------------------------------------------------------------------- #
def compact_performance(perf: PerformanceReport | None) -> dict | None:
    """Headline numbers for the agent-facing compact report."""
    if perf is None:
        return None

    def r(value: float | None, digits: int = 1) -> float | None:
        return round(value, digits) if value is not None else None

    def ep(e: EndpointPerformance) -> dict:
        tps = e.decode_tps_local.p50
        return {
            "e2e_tps_p50": r(e.e2e_tps_local.p50),
            "requests": e.requests,
            "error_rate": r(e.error_rate, 4),
            "latency_p50_ms": r(e.latency_ms.p50),
            "latency_p95_ms": r(e.latency_ms.p95),
            "ttft_p50_ms": r(e.ttft_ms.p50),
            "decode_tps_p50": r(tps if tps is not None else e.decode_tps_reported.p50),
            "network_rtt_p50_ms": r(e.network_rtt_ms.p50),
        }

    def block(target: EndpointPerformance, baseline, comparison) -> dict:
        out: dict = {"target": ep(target)}
        if baseline is not None:
            out["baseline"] = ep(baseline)
            out["comparison"] = {
                c.metric: {
                    "delta": r(c.delta, 4),
                    "ratio": r(c.ratio, 3),
                    "target_better": c.target_better,
                }
                for c in comparison
            }
        return out

    out: dict = {"source": perf.source, "mode": perf.mode}
    out.update(block(perf.target, perf.baseline, perf.comparison))
    for m in perf.modes:
        out[m.mode] = block(m.target, m.baseline, m.comparison)
    return out


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def _markdown_block(perf: PerformanceReport, block: Block, level: int = 2) -> list[str]:
    """One mode's tables; ``level`` is the section heading's level, the
    block's headings sit below it."""
    mode, _, _, comparison = block
    h3, h4 = "#" * min(6, level + 1), "#" * min(6, level + 2)
    lines: list[str] = []
    title = _block_title(perf, mode)
    if title:
        lines += [f"{h3} {title}", ""]
    eps = _endpoints(block)
    visible = _visible_rows(eps)
    for e in eps:
        if len(eps) > 1:
            lines += [f"{h4 if title else h3} {e.endpoint.capitalize()}", ""]
        lines.append(f"- Requests: {_reliability_line(e)}")
        lines += [f"- {x}" for x in _extras(e)]
        lines.append("")
        rows = [r for r in visible if r[2](e).count]
        if rows:
            lines.append("| Metric | " + " | ".join(STAT_COLUMNS) + " |")
            lines.append("| --- | " + " | ".join("---:" for _ in STAT_COLUMNS) + " |")
            for label, unit, get in rows:
                s = get(e)
                cells = [str(s.count)] + [fmt_num(getattr(s, c)) for c in STAT_COLUMNS[1:]]
                lines.append(f"| {label} ({unit}) | " + " | ".join(cells) + " |")
            lines.append("")
        if e.ttft_by_input:
            lines.append("| Prompt size | Requests | TTFT p50 (ms) | Latency p50 (ms) |")
            lines.append("| --- | ---: | ---: | ---: |")
            for b in e.ttft_by_input:
                lines.append(
                    f"| {b.label} | {b.count} | {fmt_num(b.ttft_p50_ms)} | {fmt_num(b.latency_p50_ms)} |"
                )
            lines.append("")
    if comparison:
        lines += [f"{h4 if title else h3} Target vs baseline", ""]
        lines.append("| Metric | Target | Baseline | Δ | Ratio |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for c in comparison:
            mark = {"better": "🟢 ✓ ", "worse": "🔴 ✗ "}.get(_verdict_mark(c)[0], "")
            lines.append(
                f"| {COMPARE_LABELS.get(c.metric, c.metric)} ({c.unit}) | "
                f"{fmt_num(c.target, c.unit)} | {fmt_num(c.baseline, c.unit)} | "
                f"{mark}{_signed(c.delta, c.unit)} | "
                f"{'—' if c.ratio is None else f'{c.ratio:.2f}x'} |"
            )
        lines.append("")
        lines.append("_🟢 ✓ target better · 🔴 ✗ target worse than the baseline (within 2% is even)._")
        lines.append("")
    return lines


def _scored_line(perf: PerformanceReport) -> str:
    # The probe scores the performance dimension; passive stats never score.
    if perf.source == "probe":
        return "Consistency is scored in the performance dimension."
    return "Informational — not scored."


def markdown_section(
    perf: PerformanceReport | None, *, title: str = "Performance", level: int = 2
) -> list[str]:
    """The measurements under a ``level`` heading (the report nests them in the
    performance dimension's details)."""
    if perf is None:
        return []
    lines = [f"{'#' * level} {title}", "", f"_{_source_line(perf)} {_scored_line(perf)}_", ""]
    for block in _blocks(perf):
        lines += _markdown_block(perf, block, level)
    if perf.probe_cost is not None:
        pc = perf.probe_cost
        lines.append(
            f"Probe cost: {pc.requests} requests, {pc.input_tokens_reported:,} input + "
            f"{pc.output_tokens_reported:,} output tokens (usage); "
            f"{pc.input_tokens_local:,} + {pc.output_tokens_local:,} (local count)."
        )
        lines.append("")
    for note in perf.notes:
        lines.append(f"- {note}")
    if perf.notes:
        lines.append("")
    return lines


# --------------------------------------------------------------------------- #
# HTML + SVG
# --------------------------------------------------------------------------- #
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def nice_axis(value: float) -> tuple[float, float, int]:
    """A tight axis for ``value``: ``(max, step, intervals)``.

    The step is the smallest 1, 2, 2.5 or 5 x 10^n that covers ``value`` in at
    most 6 intervals, and the maximum the next multiple of it (510 -> 0..600 by
    100, not 0..1000). Same as niceAxis in ekte/web/static/perf.js.
    """
    if value <= 0:
        return 1.0, 0.25, 4
    base = 10 ** math.floor(math.log10(value / 6))
    for mult in (1, 2, 2.5, 5, 10):  # value / 6 < 10 * base: the last one always fits
        step = mult * base
        n = math.ceil(value / step - 1e-9)
        if n <= 6:
            return n * step, step, n
    raise AssertionError("unreachable")


def time_axis(end_s: float) -> tuple[float, float]:
    """The time axis up to ``end_s``: ``(max, tick step)``.

    The axis ends where the last request ended, not at a rounded-up maximum
    (a live chart grows by exactly the time each request adds); ``nice_axis``
    only picks the tick step. Same as timeAxis in ekte/web/static/perf.js.
    """
    x_max = end_s if end_s > 0 else 1.0
    return x_max, nice_axis(x_max)[1]


def time_ticks(
    x_max: float, step: float, x: Callable[[float], float], right: float, half_char: float
) -> list[tuple[float, str]]:
    """``(position, label)`` of the time ticks that fit: one per ``step`` from
    0, leaving out those whose label (``half_char`` per character either side
    of its centre) would not fit before ``right``. As timeTicks in perf.js."""
    out: list[tuple[float, str]] = []
    j = 0
    while (sec := step * j) <= x_max + 1e-9:
        label = f"{fmt_num(sec)}s"
        if j and x(sec) + len(label) * half_char > right:
            break
        out.append((x(sec), label))
        j += 1
    return out


# A trend point: (start in s, running median, (p25, p75) or None).
TrendPoint = tuple[float, float, "tuple[float, float] | None"]


class Timeline:
    """What a timeline chart of one metric plots, in data units: the
    renderers (inline SVG here, ReportLab in ekte/report/pdf.py) only map it
    to their canvas. The same as perf.js's chartSvg draws for the full range:
    the calls (completions, or a non-chat audit's embedding / rerank calls),
    the time axis up to the last request, the value axis, and per endpoint the
    running median of its last 5 successful requests with their p25–p75
    (ekte/perf/trend.py, as the web UI gets them from attach_trends)."""

    def __init__(
        self,
        records: list[RequestRecord],
        metric: tuple[str, str, str, Callable[[RequestRecord], float | None]],
    ) -> None:
        mid, _, _, get = metric
        self.calls = [r for r in records if r.op in CHART_OPS]
        self.plotted: list[tuple[RequestRecord, float]] = []
        for r in self.calls:
            value = get(r)
            if r.ok and value is not None:
                self.plotted.append((r, value))
        self.failed = [r for r in self.calls if not r.ok]
        end_s = max(
            [1.0] + [(r.start_ms + (r.duration_ms or 0)) / 1000 for r in self.calls]
        )
        self.x_max, self.x_step = time_axis(end_s)
        top = max([v for _, v in self.plotted] + [1.0]) * 1.05
        self.y_max, self.y_step, self.y_n = nice_axis(top)
        self.trends = _trend_series(self.calls, mid)

    @property
    def empty(self) -> bool:
        return not self.plotted

    @property
    def has_line(self) -> bool:
        return any(len(s) > 1 for s in self.trends.values())

    @property
    def has_band(self) -> bool:
        return any(len(self.band(s)) > 1 for s in self.trends.values())

    @staticmethod
    def band(series: list[TrendPoint]) -> list[tuple[float, float, float]]:
        """The band's points ``(start, p25, p75)`` of one endpoint's series."""
        return [(t, b[0], b[1]) for t, _, b in series if b is not None]


def _trend_series(calls: list[RequestRecord], metric_id: str) -> dict[str, list[TrendPoint]]:
    """Per endpoint, in time order: each tagged request's running median and
    p25–p75 of ``metric_id`` (the values the live stream sends)."""
    tagger = RunningMedian()
    out: dict[str, list[TrendPoint]] = {"target": [], "baseline": []}
    for r in calls:
        rec = tagger.tag(r.model_dump(include=_TREND_FIELDS))
        mid = (rec.get("trend") or {}).get(metric_id)
        if mid is None:
            continue
        band = (rec.get("trend_band") or {}).get(metric_id)
        ep = "baseline" if r.endpoint == "baseline" else "target"
        out[ep].append((r.start_ms / 1000, mid, (band[0], band[1]) if band else None))
    for series in out.values():
        series.sort(key=lambda p: p[0])
    return out


# the record fields RunningMedian reads
_TREND_FIELDS = {
    "op", "ok", "cached", "endpoint", "duration_ms", "ttft_ms",
    "decode_tps_local", "decode_tps_reported", "itl_mean_ms",
}

def trend_kind(records: list[RequestRecord]) -> str | None:
    """What the charts draw behind the dots, for the legend: "band" (a
    running median with its p25–p75), "line" (the median alone) or None."""
    tls = [Timeline(records, m) for m in CHART_METRICS]
    if any(t.has_band for t in tls):
        return "band"
    return "line" if any(t.has_line for t in tls) else None


TREND_TEXT = "line: running median of each endpoint's last 5 successful requests"
BAND_TEXT = "band: p25–p75 of the same 5 requests"


_W, _H = 860, 260
_ML, _MR, _MT, _MB = 56, 16, 12, 34


def surface_call(r: RequestRecord) -> bool:
    """An embedding / rerank call: no tokens out, never streamed."""
    return r.op in ("embed", "rerank")


def timeline_svg(
    records: list[RequestRecord],
    metric: tuple[str, str, str, Callable[[RequestRecord], float | None]],
) -> str:
    """Scatter of ``metric`` per request over the audit's timeline, with each
    endpoint's running median and its p25–p75 band behind the dots."""
    _, label, unit, _ = metric
    tl = Timeline(records, metric)
    if tl.empty:
        return f'<p class="muted">No {_esc(label)} samples.</p>'
    pw, ph = _W - _ML - _MR, _H - _MT - _MB

    def x(sec: float) -> float:
        return _ML + sec / tl.x_max * pw

    def y(val: float) -> float:
        return _MT + ph - val / tl.y_max * ph

    name = f"{label} per request over the audit"
    if tl.has_line:
        name += f"; {TREND_TEXT}"
    if tl.has_band:
        name += f"; {BAND_TEXT}"
    out = [
        f'<svg class="perf-chart" viewBox="0 0 {_W} {_H}" role="img" aria-label="{_esc(name)}">'
    ]
    for i in range(tl.y_n + 1):
        v = tl.y_step * i
        yy = y(v)
        out.append(f'<line class="grid" x1="{_ML}" x2="{_W - _MR}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        out.append(
            f'<text class="tick" x="{_ML - 6}" y="{yy + 4:.1f}" text-anchor="end">{fmt_num(v)}</text>'
        )
    for i, (px, tick) in enumerate(time_ticks(tl.x_max, tl.x_step, x, _W - 2, 3.3)):
        anchor = "middle" if i else "start"
        out.append(
            f'<text class="tick" x="{px:.1f}" y="{_H - _MB + 16}" text-anchor="{anchor}">{tick}</text>'
        )
    out.append(
        f'<text class="tick" x="{_ML}" y="{_H - 2}">seconds since audit start · {_esc(unit)}</text>'
    )
    bands, lines = [], []
    for ep, series in tl.trends.items():
        band = tl.band(series)
        if len(band) > 1:
            top = [f"{x(t):.1f},{y(hi):.1f}" for t, _, hi in band]
            bottom = [f"{x(t):.1f},{y(lo):.1f}" for t, lo, _ in reversed(band)]
            bands.append(f'<path class="{ep}" d="M{"L".join(top + bottom)}Z"/>')
        if len(series) > 1:
            pts = [f"{x(t):.1f},{y(v):.1f}" for t, v, _ in series]
            lines.append(f'<path class="{ep}" d="M{"L".join(pts)}"/>')
    if bands:
        out.append(f'<g class="band">{"".join(bands)}</g>')
    if lines:
        out.append(f'<g class="trend">{"".join(lines)}</g>')
    for r, v in tl.plotted:
        cls = (
            f"pt {r.endpoint}"
            + (" passive" if r.phase == "passive" else "")
            + (" nonstream" if r.phase != "passive" and not r.stream and not surface_call(r) else "")
            + (" cached" if r.cached else "")
        )
        tip = (
            f"#{r.seq} {r.endpoint} · {r.detector or '—'} · {r.phase}"
            f"{'' if r.stream or surface_call(r) else ' · non-streaming'}"
            f"{' · cached (excluded)' if r.cached else ''}\n{label}: {fmt_num(v)} {unit}"
        )
        out.append(
            f'<circle class="{cls}" cx="{x(r.start_ms / 1000):.1f}" cy="{y(v):.1f}" r="4">'
            f"<title>{_esc(tip)}</title></circle>"
        )
    base_y = _MT + ph
    for r in tl.failed:
        cx = x(r.start_ms / 1000)
        tip = f"#{r.seq} {r.endpoint} · {r.detector or '—'} · {fail_text(r)}"
        if r.duration_ms is not None:  # the time it took to fail
            tip += f"\nLatency: {fmt_num(r.duration_ms)} ms"
        out.append(
            f'<path class="fail-mark" d="M{cx - 4:.1f},{base_y - 4:.1f}l8,8m0,-8l-8,8">'
            f"<title>{_esc(tip)}</title></path>"
        )
    out.append("</svg>")
    return "".join(out)


def _legend(
    has_baseline: bool, has_passive: bool, has_nonstream: bool, has_failed: bool,
    trend: str | None = None,
) -> str:
    items = ['<span><i class="key target"></i>target</span>']
    if has_baseline:
        items.append('<span><i class="key baseline"></i>baseline</span>')
    if has_passive:
        items.append('<span><i class="key target passive"></i>audit request (lighter)</span>')
    if has_nonstream:
        items.append('<span><i class="key target hollow"></i>non-streaming request (hollow)</span>')
    if has_failed:
        items.append('<span><i class="key fail">×</i>failed request</span>')
    if trend == "band":
        items.append('<span><i class="key band"></i>running median (last 5) with p25–p75</span>')
    elif trend == "line":
        items.append('<span><i class="key line"></i>running median (last 5)</span>')
    return f'<div class="perf-legend">{"".join(items)}</div>'


def _stat_table(visible, e: EndpointPerformance) -> str:
    rows = [r for r in visible if r[2](e).count]
    if not rows:
        return '<p class="muted">No successful requests to summarize.</p>'
    out = ['<div class="scroll"><table class="perf"><thead><tr><th>Metric</th>']
    out += [f'<th class="num">{c}</th>' for c in STAT_COLUMNS]
    out.append("</tr></thead><tbody>")
    for label, unit, get in rows:
        s = get(e)
        out.append(f"<tr><td>{_esc(label)} <span class=\"muted\">{_esc(unit)}</span></td>")
        out.append(f'<td class="num">{s.count}</td>')
        out += [f'<td class="num">{fmt_num(getattr(s, c))}</td>' for c in STAT_COLUMNS[1:]]
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _html_block(perf: PerformanceReport, block: Block) -> str:
    mode, _, _, comparison = block
    out: list[str] = []
    title = _block_title(perf, mode)
    if title:
        out.append(f'<h3 class="perf-mode">{_esc(title)}</h3>')
    eps = _endpoints(block)
    visible = _visible_rows(eps)
    for e in eps:
        if len(eps) > 1:
            out.append(f"<h4>{_esc(e.endpoint.capitalize())}</h4>")
        out.append(f'<p class="meta">{_esc(_reliability_line(e))}</p>')
        extras = _extras(e)
        if extras:
            out.append("<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in extras) + "</ul>")
        out.append(_stat_table(visible, e))
        if e.ttft_by_input:
            out.append(
                '<table class="perf small"><thead><tr><th>Prompt size</th>'
                '<th class="num">Requests</th><th class="num">TTFT p50 ms</th>'
                '<th class="num">Latency p50 ms</th></tr></thead><tbody>'
            )
            for b in e.ttft_by_input:
                out.append(
                    f"<tr><td>{_esc(b.label)}</td><td class=\"num\">{b.count}</td>"
                    f'<td class="num">{fmt_num(b.ttft_p50_ms)}</td>'
                    f'<td class="num">{fmt_num(b.latency_p50_ms)}</td></tr>'
                )
            out.append("</tbody></table>")

    if comparison:
        out.append(
            '<h4>Target vs baseline</h4><table class="perf"><thead><tr><th>Metric</th>'
            '<th class="num">Target</th><th class="num">Baseline</th>'
            '<th class="num">Δ</th><th class="num">Ratio</th></tr></thead><tbody>'
        )
        for c in comparison:
            ratio = "—" if c.ratio is None else f"{c.ratio:.2f}x"
            cls, mark = _verdict_mark(c)
            out.append(
                f"<tr><td>{_esc(COMPARE_LABELS.get(c.metric, c.metric))} "
                f'<span class="muted">{_esc(c.unit)}</span></td>'
                f'<td class="num">{fmt_num(c.target, c.unit)}</td>'
                f'<td class="num">{fmt_num(c.baseline, c.unit)}</td>'
                f'<td class="num delta {cls}">{mark}{_signed(c.delta, c.unit)}</td>'
                f'<td class="num">{ratio}</td></tr>'
            )
        out.append("</tbody></table>")
        out.append(
            '<p class="meta"><span class="delta better">✓ target better</span> · '
            '<span class="delta worse">✗ target worse</span> than the baseline '
            "(within 2% counts as even).</p>"
        )
    return "".join(out)


def html_section(perf: PerformanceReport | None, *, nested: bool = False) -> str:
    """The measurements as a card of their own, or ``nested`` in the
    performance dimension's details."""
    if perf is None:
        return ""
    out = [
        '<div class="perf-card perf-nested"><h4>Performance measurements</h4>'
        if nested
        else '<section class="card perf-card"><h2>Performance</h2>'
    ]
    out.append(f'<p class="muted">{_esc(_source_line(perf))} {_esc(_scored_line(perf))}</p>')

    records = perf.requests
    charts = [(m, timeline_svg(records, m)) for m in CHART_METRICS]
    charts = [(m, svg) for m, svg in charts if not svg.startswith("<p")]
    if charts:
        out.append('<div class="perf-tabs">')
        for i, (m, _svg) in enumerate(charts):
            mid = m[0]
            checked = " checked" if i == 0 else ""
            out.append(
                f'<input type="radio" name="perf-metric" id="perf-{mid}"{checked}>'
                f'<label for="perf-{mid}">{_esc(m[1])}</label>'
            )
        for m, svg in charts:
            out.append(f'<div class="perf-panel" id="panel-{m[0]}">{svg}</div>')
        out.append("</div>")
        calls = [r for r in records if r.op in CHART_OPS]
        out.append(
            _legend(
                perf.baseline is not None,
                any(r.phase == "passive" for r in calls) and perf.source == "probe",
                any(r.phase != "passive" and not r.stream and not surface_call(r) for r in calls),
                any(not r.ok for r in calls),
                trend_kind(records),
            )
        )

    for block in _blocks(perf):
        out.append(_html_block(perf, block))

    if perf.probe_cost is not None:
        pc = perf.probe_cost
        out.append(
            f'<p class="meta">Probe cost: {pc.requests} requests, '
            f"{pc.input_tokens_reported:,} input + {pc.output_tokens_reported:,} output tokens "
            f"(usage); {pc.input_tokens_local:,} + {pc.output_tokens_local:,} (local count).</p>"
        )
    if perf.notes:
        out.append("<ul class=\"perf-notes\">" + "".join(f"<li>{_esc(n)}</li>" for n in perf.notes) + "</ul>")
    out.append("</div>" if nested else "</section>")
    return "".join(out)


PERF_CSS = """
.perf-card { --series-target: var(--chart-0); --series-baseline: var(--chart-2);
  --status-critical: var(--danger); --chart-surface: var(--surface); --grid: var(--line); }
.perf-tabs { display: flex; flex-wrap: wrap; gap: .25rem .5rem; margin: .5rem 0; }
.perf-tabs input { position: absolute; opacity: 0; pointer-events: none; }
.perf-tabs label { font-size: .85rem; padding: .2rem .7rem; border: 1px solid var(--border);
  border-radius: 999px; cursor: pointer; color: var(--ink-muted); }
.perf-tabs input:checked + label { background: var(--primary); border-color: var(--primary);
  color: var(--on-primary); }
.perf-tabs input:focus-visible + label { outline: 2px solid var(--primary); outline-offset: 2px; }
.perf-panel { display: none; width: 100%; order: 99; }
#perf-latency:checked ~ #panel-latency, #perf-ttft:checked ~ #panel-ttft,
#perf-tps:checked ~ #panel-tps, #perf-itl:checked ~ #panel-itl { display: block; }
.perf-chart { width: 100%; height: auto; display: block; }
.perf-chart .grid { stroke: var(--grid); stroke-width: 1; }
.perf-chart .tick { fill: var(--ink-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.perf-chart .pt { stroke: var(--chart-surface); stroke-width: 2; }
.perf-chart .pt.target { fill: var(--series-target); }
.perf-chart .pt.baseline { fill: var(--series-baseline); }
.perf-chart .pt.passive { fill-opacity: .45; }
.perf-chart .pt.cached { fill: var(--ink-muted); fill-opacity: .6; }
.perf-chart .pt.nonstream { fill: var(--chart-surface); stroke-width: 2; }
.perf-chart .pt.nonstream.target { stroke: var(--series-target); }
.perf-chart .pt.nonstream.baseline { stroke: var(--series-baseline); }
.perf-legend .key.target.hollow { background: transparent; border: 2px solid var(--series-target);
  width: 10px; height: 10px; box-sizing: border-box; }
.perf-card { --good: var(--success); --bad: var(--danger); }
.delta.better { color: var(--good); font-weight: 600; }
.delta.worse { color: var(--bad); font-weight: 600; }
.perf-nested { margin: .75rem 0 .5rem 1rem; padding-top: .5rem; border-top: 1px solid var(--line); }
.perf-nested > h4 { margin: .25rem 0; }
h3.perf-mode { margin-top: 1.5rem; border-top: 1px solid var(--line); padding-top: 1rem; }
.perf-chart .fail-mark { stroke: var(--status-critical); stroke-width: 2; stroke-linecap: round; }
.perf-legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: .8rem; color: var(--ink-muted);
  margin: .25rem 0 .75rem; }
.perf-legend .key { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  margin-right: .35rem; vertical-align: -1px; font-style: normal; }
.perf-legend .key.target { background: var(--series-target); }
.perf-legend .key.baseline { background: var(--series-baseline); }
.perf-legend .key.passive { opacity: .45; }
.perf-legend .key.fail { color: var(--status-critical); width: auto; height: auto;
  font-weight: 700; border-radius: 0; }
.perf-chart .trend path { fill: none; stroke-width: 1.5; stroke-linejoin: round; stroke-linecap: round; }
.perf-chart .trend .target { stroke: var(--series-target); }
.perf-chart .trend .baseline { stroke: var(--series-baseline); }
.perf-chart .band path { stroke: none; fill-opacity: .14; }
.perf-chart .band .target { fill: var(--series-target); }
.perf-chart .band .baseline { fill: var(--series-baseline); }
.perf-legend .key.line { width: 14px; height: 2px; border-radius: 1px; background: var(--ink-muted);
  vertical-align: middle; }
.perf-legend .key.band { width: 16px; height: 10px; border-radius: 2px; vertical-align: middle;
  background: linear-gradient(var(--ink-muted), var(--ink-muted)) center / 100% 2px no-repeat,
  color-mix(in srgb, var(--ink-muted) 22%, transparent); }
.scroll { overflow-x: auto; }
table.perf { font-size: .82rem; margin: .5rem 0 1rem; }
table.perf td, table.perf th { padding: .3rem .45rem; white-space: nowrap; }
table.perf.small { width: auto; }
.perf-notes { font-size: .85rem; color: var(--ink-muted); }
"""
