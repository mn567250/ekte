/* ekte web UI — the performance panel (live during an audit, and in reports).
 *
 * Plain browser global, no modules; load after /lang.js. Exposes
 * window.EktePerf with:
 *   - Live(host)              live panel fed by the audit stream:
 *                               .reset({probeTotal, hasBaseline})
 *                               .add(records)   RequestRecord dicts (numbers only)
 *                               .render()       re-draw (e.g. after a language switch)
 *   - section(performance)    HTML for a report's `performance` block ("" if none)
 *   - wireSection(root, perf) hook up its metric tabs + tooltips inside `root`
 *   - chart(records, metric[, opts])
 *                             the timeline SVG (x = seconds since audit start);
 *                             records with a server-computed `trend` (running
 *                             median of the endpoint's last 5 successful
 *                             requests, ekte/perf/trend.py) also get a thin
 *                             line per endpoint behind the dots, inside its
 *                             p25–p75 band (`trend_band`); opts.scale "probe"
 *                             focuses the y-axis on the performance probe
 *
 * Y-range: "Full range" (0 to the slowest request) or "Probe focus", one fixed
 * range per audit taken from the first probe requests (see probeRange); the
 * requests above it sit as triangles on the top edge. The live panel focuses
 * on the probe automatically while it runs; a report starts on the full
 * range. Choosing one with the switch above the chart stops the automatic
 * change until "Back to automatic".
 *
 * Motion (chartmotion.js, if loaded): the live chart sweeps in when it is
 * first drawn or shows another metric, then only new requests pop in; a
 * report's chart sweeps in when it is opened or switches metric. When the
 * y-range changes, the requests slide to their new height (EkteMotion.rescale).
 *
 * Colors follow the categorical order validated for the reports: target is
 * slot 1 (blue), baseline slot 2 (orange); a failed request is a red cross
 * with its own legend entry, so identity is never carried by color alone.
 *
 * Theming: every colour in the injected CSS is a --zp-* custom property whose
 * default (declared with zero specificity, see CSS below) is a neutral built-in look.
 * A page restyles the panel by setting those properties on .zp-section,
 * .zp-live and .zp-tip (the tooltip lives on <body>), e.g. /v2/static/perf.css.
 *
 * Accessibility: the metric tabs are an ARIA tablist (arrow keys, Home, End);
 * each chart has a summary as its accessible name, and a data table with what
 * the hover tooltips show (visually hidden with the built-in styles until focused).
 */
(function () {
  "use strict";

  var T = function (zh, en) {
    return window.EKTE_LANG ? window.EKTE_LANG.t(zh, en) : en;
  };
  // English-keyed lookup without a Chinese variant (CN keeps the English
  // statistics shorthand, e.g. the "min / mean / max" column heads).
  var tr = function (en) {
    return window.EKTE_LANG && window.EKTE_LANG.tr ? window.EKTE_LANG.tr(en) : en;
  };
  // Backend notes are fixed English sentences with translations in every
  // language, CN included; server() translates backend text in every language.
  var note = function (s) {
    return window.EKTE_LANG ? window.EKTE_LANG.server(s) : s;
  };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  // Fill "{name}" placeholders of an already translated template.
  function fill(s, vals) {
    return String(s).replace(/\{(\w+)\}/g, function (m, k) {
      return Object.prototype.hasOwnProperty.call(vals, k) ? vals[k] : m;
    });
  }
  function loc() {
    return window.EKTE_LANG && window.EKTE_LANG.locale ? window.EKTE_LANG.locale() : undefined;
  }
  // Number formatting goes through one cached Intl.NumberFormat per locale and
  // digit count: Number#toLocaleString builds a new formatter on every call,
  // which dominated large live tables. The formatters come from
  // EKTE_LANG.intl (lang.js); loaded without it, this script keeps a small
  // cache of its own. The output is the same as v.toLocaleString(locale,
  // options) (that is how the spec defines it); when Intl is missing, or for
  // a non-number, that call is still what runs.
  var fmts = {};
  var digitOpts = {}; // one options object per digit count
  function numberFormat(locale, opts) {
    var Z = window.EKTE_LANG;
    if (Z && Z.intl) return Z.intl(Intl.NumberFormat, opts, locale);
    // undefined (the browser default) and "" (an error) must not share a key
    var key = (locale === undefined ? "" : "=" + locale) + "|" + (opts ? opts.maximumFractionDigits : "");
    return fmts[key] || (fmts[key] = new Intl.NumberFormat(locale, opts));
  }
  function format(v, digits) {
    var locale = loc();
    var opts = digits == null ? undefined
      : digitOpts[digits] || (digitOpts[digits] = { minimumFractionDigits: digits, maximumFractionDigits: digits });
    if (typeof v !== "number" || typeof Intl === "undefined" || !Intl.NumberFormat)
      return opts ? v.toLocaleString(locale, opts) : v.toLocaleString(locale);
    return numberFormat(locale, opts).format(v);
  }
  function fixed(v, digits) {
    return format(v, digits);
  }
  function num(v, unit) {
    if (v == null || isNaN(v)) return "—";
    if (unit === "ratio") return fixed(v * 100, 1) + "%";
    var a = Math.abs(v);
    if (v === 0 || a >= 100) return format(Math.round(v));
    return fixed(v, a >= 10 ? 1 : 2);
  }
  function int(v) {
    return v == null ? "—" : format(Number(v));
  }
  function endpointName(r) {
    return r.endpoint === "baseline" ? T("基线", "baseline") : T("目标", "target");
  }
  function phaseName(p) {
    return p === "probe" ? T("性能探测", "probe") : p === "passive" ? T("常规检测", "audit")
      : p === "probe_batch" ? T("批量探测", "batch probe")
      : p === "probe_docs" ? T("文档数探测", "document-count probe") : String(p || "—");
  }
  // The calls of a non-chat surface (ekte/config.py SURFACE_OPS): embedding
  // and rerank calls return no tokens and never stream.
  function isSurfaceCall(r) { return r.op === "embed" || r.op === "rerank"; }
  // The calls the charts show: completion calls, or a non-chat audit's
  // embedding/rerank calls (a chat report has none of those).
  function isCall(r) { return r.op === "complete" || isSurfaceCall(r); }
  // a request that could have streamed but did not (non-chat calls never stream)
  function unstreamed(r) { return !r.stream && !isSurfaceCall(r); }
  // A non-chat audit's performance: latency only, no tokens out, no streaming.
  function isEmbed(perf) {
    var recs = (perf && perf.requests) || [];
    return recs.some(isSurfaceCall) && !recs.some(function (r) { return r.op === "complete"; });
  }

  var METRICS = [
    { id: "latency", zh: "延迟", en: "Latency", unit: "ms", get: function (r) { return r.duration_ms; } },
    { id: "ttft", zh: "首 token 时间", en: "TTFT", unit: "ms", get: function (r) { return r.ttft_ms; } },
    {
      id: "tps", zh: "解码速度", en: "Decode speed", unit: "tok/s",
      get: function (r) { return r.decode_tps_local != null ? r.decode_tps_local : r.decode_tps_reported; },
    },
    { id: "itl", zh: "块间延迟", en: "Inter-chunk latency", unit: "ms", get: function (r) { return r.itl_mean_ms; } },
  ];
  function metric(id) {
    for (var i = 0; i < METRICS.length; i++) if (METRICS[i].id === id) return METRICS[i];
    return METRICS[0];
  }

  // Stat rows of a report endpoint block: [key, zh, en, unit].
  var ROWS = [
    ["latency_ms", "延迟", "Latency", "ms"],
    ["ttft_ms", "首 token 时间", "Time to first token", "ms"],
    ["decode_tps_reported", "解码速度（usage）", "Decode speed (usage)", "tok/s"],
    ["decode_tps_local", "解码速度（本地计数）", "Decode speed (local count)", "tok/s"],
    ["e2e_tps_reported", "端到端速度（usage）", "End-to-end speed (usage)", "tok/s"],
    ["e2e_tps_local", "端到端速度（本地计数）", "End-to-end speed (local count)", "tok/s"],
    ["itl_ms", "块间延迟", "Inter-chunk latency", "ms"],
    ["itl_jitter_ms", "块间抖动", "Inter-chunk jitter", "ms"],
    ["server_ms", "服务端时间（发送→首个输出）", "Server time (sent → first output)", "ms"],
    ["relay_processing_ms", "中转站自报处理时间", "Relay-reported processing", "ms"],
    ["network_rtt_ms", "网络往返（GET /models）", "Network round trip (GET /models)", "ms"],
    ["connect_ms", "TCP 连接", "TCP connect", "ms"],
    ["tls_ms", "TLS 握手", "TLS handshake", "ms"],
  ];
  var COLS = ["count", "min", "mean", "p50", "p75", "p90", "p95", "p99", "max", "stdev"];
  var COMPARE = {
    latency_p50: ["延迟 p50", "Latency p50"],
    latency_p90: ["延迟 p90", "Latency p90"],
    ttft_p50: ["TTFT p50", "TTFT p50"],
    ttft_p90: ["TTFT p90", "TTFT p90"],
    decode_tps_reported_p50: ["解码速度 p50（usage）", "Decode speed p50 (usage)"],
    decode_tps_local_p50: ["解码速度 p50（本地）", "Decode speed p50 (local)"],
    e2e_tps_local_p50: ["端到端速度 p50（本地）", "End-to-end speed p50 (local)"],
    itl_p50: ["块间延迟 p50", "Inter-chunk latency p50"],
    server_p50: ["服务端时间 p50", "Server time p50"],
    network_rtt_p50: ["网络往返 p50", "Network round trip p50"],
    error_rate: ["错误率", "Error rate"],
  };

  // Same floors as ekte/utils/stats.py: a percentile needs this many samples.
  var FLOOR = { p50: 1, p75: 4, p90: 10, p95: 20, p99: 100 };
  function pct(sorted, p) {
    if (!sorted.length) return null;
    var rank = (p / 100) * (sorted.length - 1), lo = Math.floor(rank), hi = Math.ceil(rank);
    return lo === hi ? sorted[lo] : sorted[lo] * (1 - (rank - lo)) + sorted[hi] * (rank - lo);
  }
  function p50(values) {
    var s = values.filter(function (v) { return v != null; }).sort(function (a, b) { return a - b; });
    return pct(s, 50);
  }

  // A tight axis: the smallest 1/2/2.5/5 x 10^n tick step that covers `v` in at
  // most 6 intervals, and the maximum rounded up to the next multiple of it
  // (510 -> 0..600 by 100, not 0..1000). Same as nice_axis in ekte/report/performance.py.
  function niceAxis(v) {
    if (!(v > 0)) return { max: 1, step: 0.25, n: 4 };
    var base = Math.pow(10, Math.floor(Math.log10(v / 6)));
    var steps = [1, 2, 2.5, 5, 10]; // v / 6 < 10 * base, so the last one always fits
    for (var i = 0; ; i++) {
      var step = steps[i] * base, n = Math.ceil(v / step - 1e-9);
      if (n <= 6) return { max: n * step, step: step, n: n };
    }
  }

  // ---- y-range: the full range, or focused on the performance probe ------ //
  // Probe focus has one fixed range per audit, from the first CALIB probe
  // requests (both endpoints, successful and uncached, in recorded order):
  // p75 + 3 × (p75 − p25), at least 1.5 × p75, on a nice axis. CALIB is the
  // running median's window (ekte/perf/trend.py); until that many probe
  // requests are in, the range is provisional.
  var CALIB = 5;
  function probeRange(records, m) {
    var v = (records || []).filter(function (r) {
      return isCall(r) && r.phase === "probe" && r.ok && !r.cached && m.get(r) != null;
    }).slice(0, CALIB).map(m.get).sort(function (a, b) { return a - b; });
    if (!v.length) return null;
    var lo = pct(v, 25), hi = pct(v, 75);
    return { top: Math.max(hi + 3 * (hi - lo), 1.5 * hi), n: v.length };
  }
  // What the chart shows: the user's choice (null: automatic), else `auto`;
  // probe focus falls back to the full range while this metric has no probe
  // values (non-streamed calls have no TTFT, for one).
  function scaleState(records, metricId, user, auto) {
    var range = probeRange(records, metric(metricId));
    var eff = user || auto;
    if (eff === "probe" && !range) eff = "full";
    return { eff: eff, user: user, range: range };
  }
  function hasProbe(records) {
    return (records || []).some(function (r) { return isCall(r) && r.phase === "probe"; });
  }

  // ---- timeline chart ------------------------------------------------- //
  var W = 720, H = 230, ML = 52, MR = 12, MT = 10, MB = 30;
  var MT_FOCUS = 26; // probe focus: room above the plot for the off-range triangles
  // opts.open keeps the data-table toggle expanded across re-renders;
  // opts.scale "probe" focuses the y-axis on the probe.
  function chart(records, metricId, opts) {
    var c = chartSvg(records, metricId, opts && opts.scale);
    return c.empty ? c.html : c.html + dataTable(c.calls, c.m, opts && opts.open);
  }
  // The SVG alone (or the "no samples" note): {html, empty, calls, m, over,
  // top} (top: a focused range's maximum; over: how many requests sit above
  // it, as triangles on the top edge). Its data table is
  // dataTable(calls, m, open); the live panel keeps that one in place.
  function chartSvg(records, metricId, scale) {
    var m = metric(metricId);
    var calls = (records || []).filter(isCall);
    var pts = calls.filter(function (r) { return r.ok && m.get(r) != null; });
    var failed = calls.filter(function (r) { return !r.ok; });
    if (!pts.length && !failed.length)
      return { html: '<div class="zp-empty">' + esc(T("暂无数据", "No samples yet")) + "</div>", empty: true, calls: calls, m: m, over: 0 };
    var end = 1;
    calls.forEach(function (r) { end = Math.max(end, (r.start_ms + (r.duration_ms || 0)) / 1000); });
    var xa = niceAxis(end), xMax = xa.max;
    var range = scale === "probe" ? probeRange(records, m) : null, mt = range ? MT_FOCUS : MT;
    var ya = niceAxis(range ? range.top : Math.max.apply(null, pts.map(m.get).concat([1])) * 1.05), yMax = ya.max;
    var pw = W - ML - MR, ph = H - mt - MB;
    var x = function (s) { return ML + (s / xMax) * pw; };
    var y = function (v) { return mt + ph - (v / yMax) * ph; };
    var above = function (r) { return range && m.get(r) > yMax; };
    var over = pts.filter(above).length;
    var o = ['<svg class="zp-chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' +
      esc(summary(m, pts, failed, range && { max: yMax, over: over })) + '">'];
    for (var i = 0; i <= ya.n; i++) {
      var v = ya.step * i, yy = y(v).toFixed(1);
      o.push('<line class="zp-grid" x1="' + ML + '" x2="' + (W - MR) + '" y1="' + yy + '" y2="' + yy + '"/>');
      o.push('<text class="zp-tick" x="' + (ML - 6) + '" y="' + (+yy + 4) + '" text-anchor="end">' + num(v) + "</text>");
    }
    for (var j = 0; j <= xa.n; j++) {
      var s = xa.step * j;
      o.push('<text class="zp-tick" x="' + x(s).toFixed(1) + '" y="' + (H - MB + 16) +
        '" text-anchor="' + (j === 0 ? "start" : j === xa.n ? "end" : "middle") + '">' + num(s) + "s</text>");
    }
    // band and line are cut at the top edge of a focused range
    o.push(bandPaths(pts, m, x, y, mt));
    o.push(trendPaths(pts, m, x, y, mt));
    var top = (mt - 4) / 2 + 2; // the triangles' centre line, above the plot
    pts.forEach(function (r) {
      var side = r.endpoint === "baseline" ? "b" : "t", cx = x(r.start_ms / 1000).toFixed(1);
      if (above(r)) {
        o.push('<path class="zp-off ' + side + '" d="M' + cx + "," + (top - 5) + "l5,9h-10z" +
          '" data-tip="' + esc(tip(r, m)) + '"/>');
        return;
      }
      // probe requests are small and translucent, so dense runs read as a
      // cloud around the median; audit requests keep their ring
      var probe = r.phase === "probe";
      var cls = "zp-pt " + side + (r.phase === "passive" ? " passive" : unstreamed(r) ? " hollow" : "") +
        (probe ? " probe" : "") + (r.cached ? " cached" : "");
      o.push('<circle class="' + cls + '" cx="' + cx + '" cy="' +
        y(m.get(r)).toFixed(1) + '" r="' + (probe ? 3 : 4) + '" data-tip="' + esc(tip(r, m)) + '"/>');
    });
    var by = mt + ph;
    failed.forEach(function (r) {
      var cx = x(r.start_ms / 1000);
      o.push('<path class="zp-fail" d="M' + (cx - 4).toFixed(1) + "," + (by - 4) + "l8,8m0,-8l-8,8" +
        '" data-tip="' + esc(tip(r, null)) + '"/>');
    });
    o.push("</svg>");
    return { html: o.join(""), empty: false, calls: calls, m: m, over: over, top: range ? yMax : null };
  }
  // The running-median line per endpoint, behind the dots: through each
  // successful request's `trend` value for this metric, in time order.
  function trendOf(r, m) {
    var v = r.trend && r.trend[m.id];
    return typeof v === "number" && isFinite(v) ? v : null;
  }
  // [p25, p75] of the same window (`trend_band`), or null
  function bandOf(r, m) {
    var b = r.trend_band && r.trend_band[m.id];
    return b && typeof b[0] === "number" && typeof b[1] === "number" && isFinite(b[0]) && isFinite(b[1]) ? b : null;
  }
  function series(pts, base, has) {
    return pts.filter(function (r) { return (r.endpoint === "baseline") === base && has(r); })
      .sort(function (a, b) { return a.start_ms - b.start_ms; });
  }
  // Cut at the plot's top edge (y = top; svg y grows downwards): a line
  // where it leaves and re-enters, a polygon along the edge (one
  // Sutherland–Hodgman pass). Points are [x, y]; returns path data or "".
  function cross(a, b, top) {
    return [a[0] + ((top - a[1]) * (b[0] - a[0])) / (b[1] - a[1]), top];
  }
  function pt(p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }
  function lineD(ps, top) {
    var d = "", on = false;
    ps.forEach(function (p, i) {
      var q = ps[i - 1], inside = p[1] >= top;
      if (i && (q[1] >= top) !== inside) {
        var c = cross(q, p, top);
        d += (inside ? "M" : "L") + pt(c);
        on = inside;
      }
      if (inside) { d += (on ? "L" : "M") + pt(p); on = true; } else on = false;
    });
    return /L/.test(d) ? d : "";
  }
  function polyD(ps, top) {
    var out = [];
    ps.forEach(function (p, i) {
      var q = ps[(i || ps.length) - 1];
      if ((q[1] >= top) !== (p[1] >= top)) out.push(cross(q, p, top));
      if (p[1] >= top) out.push(p);
    });
    return out.length > 2 ? "M" + out.map(pt).join("L") + "Z" : "";
  }
  function trendPaths(pts, m, x, y, top) {
    var out = [];
    [false, true].forEach(function (base) {
      var ps = series(pts, base, function (r) { return trendOf(r, m) != null; })
        .map(function (r) { return [x(r.start_ms / 1000), y(trendOf(r, m))]; });
      var d = ps.length > 1 ? lineD(ps, top) : "";
      if (d) out.push('<path class="' + (base ? "b" : "t") + '" d="' + d + '"/>');
    });
    return out.length ? '<g class="zp-trend">' + out.join("") + "</g>" : "";
  }
  // The p25–p75 band around each line: along the p75 values, back along the p25.
  function bandPaths(pts, m, x, y, top) {
    var out = [];
    [false, true].forEach(function (base) {
      var s = series(pts, base, function (r) { return bandOf(r, m) != null; });
      if (s.length < 2) return;
      var at = function (r, k) { return [x(r.start_ms / 1000), y(bandOf(r, m)[k])]; };
      var d = polyD(s.map(function (r) { return at(r, 1); }).concat(s.slice().reverse().map(function (r) { return at(r, 0); })), top);
      if (d) out.push('<path class="' + (base ? "b" : "t") + '" d="' + d + '"/>');
    });
    return out.length ? '<g class="zp-band">' + out.join("") + "</g>" : "";
  }
  function trendText() {
    return T("线：每个端点最近 5 次成功请求的滚动中位数", "line: running median of each endpoint's last 5 successful requests");
  }
  // The chart's accessible name: what it plots, how many requests, the median
  // per endpoint, the failures, the line and a focused y-range.
  function summary(m, pts, failed, focus) {
    var parts = [fill(T("{metric}（{unit}）随时间变化：{n} 个请求", "{metric} ({unit}) over time: {n} requests"),
      { metric: T(m.zh, m.en), unit: m.unit, n: int(pts.length + failed.length) })];
    var med = [
      [false, T("目标中位数 {value}", "target median {value}")],
      [true, T("基线中位数 {value}", "baseline median {value}")],
    ];
    med.forEach(function (e) {
      var vs = pts.filter(function (r) { return (r.endpoint === "baseline") === e[0] && !r.cached; }).map(m.get);
      if (vs.length) parts.push(fill(e[1], { value: num(p50(vs)) + " " + m.unit }));
    });
    if (failed.length) parts.push(fill(T("{n} 个失败", "{n} failed"), { n: int(failed.length) }));
    if (pts.some(function (r) { return trendOf(r, m) != null; })) parts.push(trendText());
    if (pts.some(function (r) { return bandOf(r, m) != null; }))
      parts.push(T("带：同样 5 次请求的 p25–p75", "band: p25–p75 of the same 5 requests"));
    if (focus)
      parts.push(fill(T("y 轴聚焦性能探测：0 至 {max}，{n} 个请求高于此范围（顶部三角形）",
        "y-axis focused on the probe: 0 to {max}, {n} requests above it (triangles at the top)"),
        { max: num(focus.max) + " " + m.unit, n: int(focus.over) }));
    return parts.join(T("；", "; "));
  }
  // What the hover tooltips show, as a table behind a toggle.
  // With `lazy`, a closed toggle comes without its table (the live panel fills
  // it in when it opens).
  function dataTable(calls, m, open, lazy) {
    var rows = dataRows(calls, m);
    if (!rows.length) return "";
    return '<details class="zp-data"' + (open ? " open" : "") + "><summary>" + esc(dataSummary()) +
      '</summary><div class="zp-data-scroll" tabindex="0">' + (open || !lazy ? dataTableHtml(rows, m) : "") +
      "</div></details>";
  }
  function dataSummary() {
    return T("查看数据表", "Show data table");
  }
  function dataRows(calls, m) {
    return calls.filter(function (r) { return !r.ok || m.get(r) != null; });
  }
  function dataHead(m) {
    return '<thead><tr><th class="r">#</th><th>' +
      esc(T("端点", "Endpoint")) + "</th><th>" + esc(T("阶段", "Phase")) + '</th><th class="r">' +
      esc(T("开始", "Start")) + ' <span class="zp-unit">s</span></th><th class="r">' + esc(T(m.zh, m.en)) +
      ' <span class="zp-unit">' + m.unit + '</span></th><th class="r">' + esc(T("滚动中位数", "Running median")) +
      ' <span class="zp-unit">' + m.unit + '</span></th><th class="r">p25–p75 <span class="zp-unit">' + m.unit +
      "</span></th><th>" + esc(T("状态", "Status")) + "</th></tr></thead>";
  }
  function dataRow(r, m) {
    var status = !r.ok
      ? T("失败", "failed") + " (" + (r.status_code || r.error_type || "?") + ")"
      : r.cached ? T("缓存命中（不计入统计）", "cached (excluded)") : "OK";
    return '<tr><td class="r">' + esc(r.seq) + "</td><td>" + esc(endpointName(r)) + "</td><td>" +
      esc(phaseName(r.phase) + (unstreamed(r) ? " · " + T("非流式", "non-streaming") : "")) + '</td><td class="r">' +
      num((r.start_ms || 0) / 1000) + '</td><td class="r">' + (r.ok ? num(m.get(r)) : "—") + '</td><td class="r">' +
      (trendOf(r, m) != null ? num(trendOf(r, m)) : "—") + '</td><td class="r">' +
      (bandOf(r, m) ? num(bandOf(r, m)[0]) + "–" + num(bandOf(r, m)[1]) : "—") + "</td><td>" +
      esc(status) + "</td></tr>";
  }
  function dataTableHtml(rows, m) {
    return '<table class="zp-table zp-small">' + dataHead(m) + "<tbody>" +
      rows.map(function (r) { return dataRow(r, m); }).join("") + "</tbody></table>";
  }
  function tip(r, m) {
    var head = "#" + r.seq + " · " + endpointName(r) + " · " + (r.detector || "—") + " · " + phaseName(r.phase) +
      (unstreamed(r) ? " · " + T("非流式", "non-streaming") : "");
    if (!m) return head + "\n" + T("失败", "failed") + " (" + (r.status_code || r.error_type || "?") + ")";
    var lines = [head, T(m.zh, m.en) + ": " + num(m.get(r)) + " " + m.unit];
    if (m.id !== "latency" && r.duration_ms != null) lines.push(T("延迟", "Latency") + ": " + num(r.duration_ms) + " ms");
    if (m.id !== "ttft" && r.ttft_ms != null) lines.push("TTFT: " + num(r.ttft_ms) + " ms");
    if (r.cached) lines.push(T("缓存命中（不计入统计）", "cached (excluded)"));
    return lines.join("\n");
  }

  // `over`: how many requests the chart drew as triangles above its range
  function legend(records, hasBaseline, over) {
    var calls = (records || []).filter(isCall);
    var probe = calls.some(function (r) { return r.phase !== "passive"; });
    var items = ['<span><i class="zp-key t"></i>' + esc(T("目标", "target")) + "</span>"];
    if (hasBaseline) items.push('<span><i class="zp-key b"></i>' + esc(T("基线", "baseline")) + "</span>");
    if (probe && calls.some(function (r) { return r.phase === "passive"; }))
      items.push('<span><i class="zp-key t passive"></i>' + esc(T("常规检测请求（圆环）", "audit request (ringed)")) + "</span>");
    if (calls.some(function (r) { return r.phase === "probe"; }))
      items.push('<span><i class="zp-key t probe"></i>' + esc(T("性能探测请求（小、浅色）", "probe request (small, lighter)")) + "</span>");
    if (calls.some(function (r) { return r.phase !== "passive" && unstreamed(r); }))
      items.push('<span><i class="zp-key t hollow"></i>' + esc(T("非流式请求（空心）", "non-streaming request (hollow)")) + "</span>");
    if (calls.some(function (r) { return !r.ok; }))
      items.push('<span><i class="zp-key x" aria-hidden="true">×</i>' + esc(T("失败请求", "failed request")) + "</span>");
    if (calls.some(function (r) { return r.trend_band; }))
      items.push('<span><i class="zp-key band" aria-hidden="true"></i>' +
        esc(T("滚动中位数（最近 5 次）及 p25–p75", "running median (last 5) with p25–p75")) + "</span>");
    else if (calls.some(function (r) { return r.trend; }))
      items.push('<span><i class="zp-key line" aria-hidden="true"></i>' + esc(T("滚动中位数（最近 5 次）", "running median (last 5)")) + "</span>");
    if (over)
      items.push('<span><i class="zp-key tri" aria-hidden="true"></i>' +
        esc(T("高于范围（数值见提示）", "above the range (value in the tooltip)")) + "</span>");
    return '<div class="zp-legend">' + items.join("") + "</div>";
  }

  // Metric tabs and the plot they control; `pid` keeps the ids unique per panel.
  var seq = 0;
  function tabs(active, pid, embed) {
    return '<div class="zp-tabs" role="tablist" aria-label="' + esc(T("性能指标", "Performance metric")) + '">' +
      METRICS.filter(function (m) { return !embed || m.id === "latency"; }).map(function (m) {
        var on = m.id === active;
        return '<button type="button" role="tab" id="' + pid + "-tab-" + m.id + '" aria-controls="' + pid +
          '-panel" data-metric="' + m.id + '" aria-selected="' + on + '" tabindex="' + (on ? 0 : -1) + '"' +
          (on ? ' class="on"' : "") + ">" + esc(T(m.zh, m.en)) + "</button>";
      }).join("") + "</div>";
  }
  function plot(records, active, pid, open, scale) {
    return plotHtml(chartSvg(records, active, scale), active, pid, open);
  }
  function plotHtml(c, active, pid, open) {
    return '<div class="zp-plot" role="tabpanel" id="' + pid + '-panel" aria-labelledby="' + pid + "-tab-" + active +
      '">' + (c.empty ? c.html : c.html + dataTable(c.calls, c.m, open)) + "</div>";
  }
  // The y-range switch above the chart (s from scaleState): "Full range" and
  // "Probe focus" as toggle buttons, whether the range was chosen
  // automatically or by the user, and a way back to automatic.
  function scaleName(eff) {
    return eff === "probe" ? T("聚焦性能探测", "Probe focus") : T("完整范围", "Full range");
  }
  // c: the chart drawn (chartSvg), for how many requests are above a focused range
  function scaleBar(s, c) {
    var btn = function (id) {
      return '<button type="button" data-scale="' + id + '" aria-pressed="' + (s.eff === id) + '"' +
        (id === "probe" && !s.range ? " disabled" : "") + ">" + esc(scaleName(id)) + "</button>";
    };
    var state = s.user ? T("由你选择", "set by you") : T("自动", "automatic");
    if (s.eff === "probe")
      state += " · " + fill(s.range.n < CALIB
        ? T("前 {n} 个探测请求前为暂定范围（{k}/{n}）", "provisional until {n} probe requests ({k}/{n})")
        : T("范围取自前 {n} 个探测请求", "range from the first {n} probe requests"), { n: int(CALIB), k: int(s.range.n) });
    if (c && c.over)
      state += " · " + fill(T("▲ {n} 个高于 {value}", "▲ {n} above {value}"), { n: int(c.over), value: num(c.top) + " " + c.m.unit });
    return '<div class="zp-scale"><div class="zp-seg" role="group" aria-label="' + esc(T("y 轴范围", "Y-axis range")) + '">' +
      btn("full") + btn("probe") + '</div><span class="zp-scale-s">' + esc(state) + "</span>" +
      (s.user ? '<button type="button" class="zp-auto" data-scale="auto">' + esc(T("恢复自动", "Back to automatic")) + "</button>" : "") +
      "</div>";
  }
  function scaleSaid(eff) {
    return fill(T("y 轴已自动切换为：{range}", "Y-axis switched to {range} automatically"), { range: scaleName(eff) });
  }

  // ---- tooltip + tabs wiring ------------------------------------------ //
  var tipEl = null;
  function showTip(evt, text) {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "zp-tip";
      tipEl.setAttribute("aria-hidden", "true"); // the data table carries the same text
      document.body.appendChild(tipEl);
    }
    tipEl.textContent = text;
    tipEl.style.display = "block";
    var pad = 14, w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    var left = evt.clientX + pad, top = evt.clientY + pad;
    if (left + w > window.innerWidth - 8) left = evt.clientX - w - pad;
    if (top + h > window.innerHeight - 8) top = evt.clientY - h - pad;
    tipEl.style.left = Math.max(8, left) + "px";
    tipEl.style.top = Math.max(8, top) + "px";
  }
  function hideTip() {
    if (tipEl) tipEl.style.display = "none";
  }
  var STEP = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  // onMetric(id) re-renders with another metric; onToggle(open) remembers the
  // data-table toggle's state for the next render.
  function wire(root, onMetric, onToggle) {
    if (!root) return;
    wireTabs(root, onMetric);
    var det = root.querySelector(".zp-data");
    if (det && onToggle) det.addEventListener("toggle", function () { onToggle(det.open); });
    root.querySelectorAll("[data-tip]").forEach(function (el) {
      el.addEventListener("mouseover", function (e) { showTip(e, el.getAttribute("data-tip")); });
      el.addEventListener("mouseleave", hideTip);
    });
  }
  // The tab buttons' handlers are properties, so wiring a tab twice is harmless.
  function wireTabs(root, onMetric) {
    root.querySelectorAll(".zp-tabs button").forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        onMetric(b.dataset.metric);
      };
      b.onkeydown = function (e) {
        var n = METRICS.length, i = METRICS.indexOf(metric(b.dataset.metric)), next;
        if (STEP[e.key]) next = (i + STEP[e.key] + n) % n;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = n - 1;
        else return;
        e.preventDefault();
        e.stopPropagation();
        var id = METRICS[next].id;
        onMetric(id);
        var t = root.querySelector('.zp-tabs [data-metric="' + id + '"]');
        if (t) t.focus();
      };
    });
  }

  // ---- report section --------------------------------------------------- //
  function statTable(ep) {
    var rows = ROWS.filter(function (r) { return ep[r[0]] && ep[r[0]].count; });
    if (!rows.length) return '<p class="zp-muted">' + esc(T("没有可统计的成功请求。", "No successful requests to summarize.")) + "</p>";
    return '<div class="zp-scroll"><table class="zp-table"><thead><tr><th>' + esc(T("指标", "Metric")) + "</th>" +
      COLS.map(function (c) { return '<th class="r">' + esc(FLOOR[c] ? c : tr(c)) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      rows.map(function (r) {
        var s = ep[r[0]];
        return "<tr><td>" + esc(T(r[1], r[2])) + ' <span class="zp-unit">' + r[3] + "</span></td>" +
          COLS.map(function (c) { return '<td class="r">' + (c === "count" ? int(s.count) : num(s[c])) + "</td>"; }).join("") +
          "</tr>";
      }).join("") + "</tbody></table></div>";
  }
  function p50of(stats) {
    return stats && stats.p50 != null ? stats.p50 : null;
  }
  function tiles(ep, embed) {
    var streamed = ep.ttft_ms && ep.ttft_ms.count;
    var tps = p50of(ep.decode_tps_local);
    if (tps == null) tps = p50of(ep.decode_tps_reported);
    var t = [[T("延迟 p50", "Latency p50"), num(p50of(ep.latency_ms)), "ms"]];
    if (embed) {
      // no tokens come back: latency and errors only
    } else if (streamed) {
      t.push(["TTFT p50", num(p50of(ep.ttft_ms)), "ms"]);
      t.push([T("解码速度 p50", "Decode speed p50"), num(tps), "tok/s"]);
    } else {
      // Non-streamed calls have no first token: end-to-end speed instead.
      t.push([T("端到端速度 p50", "End-to-end speed p50"), num(p50of(ep.e2e_tps_local)), "tok/s"]);
    }
    t.push([T("错误率", "Error rate"), num(ep.error_rate, "ratio"), ""]);
    return '<div class="zp-tiles">' + t.map(function (x) {
      return '<div class="zp-tile"><div class="zp-tl">' + esc(x[0]) + '</div><div class="zp-tv">' + esc(x[1]) +
        (x[2] ? ' <small>' + x[2] + "</small>" : "") + "</div></div>";
    }).join("") + "</div>";
  }
  function endpointBlock(ep, title, embed) {
    var o = [];
    if (title) o.push('<h4 class="zp-h">' + esc(title) + "</h4>");
    o.push(tiles(ep, embed));
    var line = int(ep.successes) + "/" + int(ep.requests) + " " + T("成功", "succeeded") + " · " +
      T("超时", "timeouts") + " " + num(ep.timeout_rate, "ratio") + " · 429 " + num(ep.rate_limited_rate, "ratio");
    if (ep.cached_excluded) line += " · " + int(ep.cached_excluded) + " " + T("缓存命中（不计入统计）", "cached (excluded)");
    o.push('<p class="zp-muted">' + esc(line) + "</p>");
    var extra = [];
    if (ep.cold_start_ms != null)
      extra.push(T("冷启动（首个请求）", "Cold start (first request)") + ": " + num(ep.cold_start_ms) + " ms" +
        (ep.cold_start_ttft_ms != null ? ", TTFT " + num(ep.cold_start_ttft_ms) + " ms" : ""));
    var c = ep.concurrency;
    if (c && embed)
      extra.push(T("并发负载", "Under load") + " (" + int(c.requests) + " × " + int(c.concurrency) + "): " +
        T("延迟 p50", "Latency p50") + " " + num(c.latency_ms && c.latency_ms.p50) + " ms");
    else if (c)
      extra.push(T("并发负载", "Under load") + " (" + int(c.requests) + " × " + int(c.concurrency) + "): " +
        T("总吞吐", "aggregate") + " " + num(c.aggregate_tps_local) + " tok/s, " + T("延迟 p50", "Latency p50") + " " +
        num(c.latency_ms && c.latency_ms.p50) + " ms");
    if (extra.length) o.push('<ul class="zp-list">' + extra.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>");
    o.push(statTable(ep));
    if ((ep.ttft_by_input || []).length > 1) {
      o.push('<div class="zp-wide"><table class="zp-table zp-small"><thead><tr><th>' + esc(T("提示词长度", "Prompt size")) + '</th><th class="r">n</th>' +
        '<th class="r">TTFT p50</th><th class="r">' + esc(T("延迟 p50", "Latency p50")) + "</th></tr></thead><tbody>" +
        ep.ttft_by_input.map(function (b) {
          return "<tr><td>" + esc(b.label) + '</td><td class="r">' + int(b.count) + '</td><td class="r">' + num(b.ttft_p50_ms) +
            '</td><td class="r">' + num(b.latency_p50_ms) + "</td></tr>";
        }).join("") + "</tbody></table></div>");
    }
    return o.join("");
  }

  // Same rule as PerformanceComparison.target_better in ekte/models.py: true /
  // false when the target is better / worse, null within 2% or with a side missing.
  function targetBetter(c) {
    if (c.delta == null || c.target == null || c.baseline == null) return null;
    var scale = Math.max(Math.abs(c.target), Math.abs(c.baseline));
    if (!scale || Math.abs(c.delta) / scale < 0.02) return null;
    return c.delta > 0 === !!c.higher_is_better;
  }
  function compareTable(rows) {
    return '<div class="zp-wide"><table class="zp-table"><thead><tr><th>' + esc(T("指标", "Metric")) + '</th><th class="r">' +
      esc(T("目标", "Target")) + '</th><th class="r">' + esc(T("基线", "Baseline")) + '</th><th class="r">Δ</th><th class="r">' +
      esc(T("比值", "Ratio")) + "</th></tr></thead><tbody>" + rows.map(function (c) {
        var lab = COMPARE[c.metric] ? T(COMPARE[c.metric][0], COMPARE[c.metric][1]) : c.metric;
        var sign = c.delta > 0 ? "+" : "";
        var d = c.delta == null ? "—" : c.unit === "ratio" ? sign + fixed(c.delta * 100, 1) + " pp" : sign + num(c.delta);
        var b = targetBetter(c), cls = b === true ? " zp-better" : b === false ? " zp-worse" : "";
        var mark = b === true ? "✓ " : b === false ? "✗ " : "";
        return "<tr><td>" + esc(lab) + ' <span class="zp-unit">' + esc(c.unit) + '</span></td><td class="r">' +
          num(c.target, c.unit) + '</td><td class="r">' + num(c.baseline, c.unit) + '</td><td class="r' + cls + '">' + mark + d +
          '</td><td class="r">' + (c.ratio == null ? "—" : fixed(c.ratio, 2) + "x") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<p class="zp-muted"><span class="zp-better">✓ ' + esc(T("目标更好", "target better")) + '</span> · <span class="zp-worse">✗ ' +
      esc(T("目标更差", "target worse")) + "</span> " + esc(T("（相差 2% 以内视为持平）", "(within 2% counts as even)")) + "</p>";
  }
  var MODE_TITLE = { stream: ["流式", "Streaming"], non_stream: ["非流式", "Non-streaming"] };
  function modeBlock(mode, target, baseline, comparison, titled, embed) {
    var o = [];
    if (titled && MODE_TITLE[mode]) o.push('<h4 class="zp-h zp-mode">' + esc(T(MODE_TITLE[mode][0], MODE_TITLE[mode][1])) + "</h4>");
    o.push(endpointBlock(target, baseline ? T("目标", "Target") : "", embed));
    if (baseline) o.push(endpointBlock(baseline, T("基线", "Baseline"), embed));
    if ((comparison || []).length) {
      o.push('<h4 class="zp-h">' + esc(T("目标 vs 基线", "Target vs baseline")) + "</h4>");
      o.push(compareTable(comparison));
    }
    return o.join("");
  }

  // scale: the y-range the user chose (null: automatic, which in a finished
  // report is the full range)
  var sectionState = { metric: "latency", open: false, scale: null };
  // The parts of a report's chart that follow its metric and y-range.
  function sectionParts(perf, pid) {
    var recs = perf.requests, st = sectionState;
    var shown = isEmbed(perf) ? "latency" : st.metric;
    var s = scaleState(recs, shown, st.scale, "full"), c = chartSvg(recs, shown, s.eff);
    return {
      scale: hasProbe(recs) ? scaleBar(s, c) : "",
      plot: plotHtml(c, shown, pid, st.open),
      legend: legend(recs, !!perf.baseline, c.over),
    };
  }
  function section(perf) {
    if (!perf || !perf.target) return "";
    var modes = perf.modes || [];
    var embed = isEmbed(perf);
    var kind = embed ? "" : [perf.mode].concat(modes.map(function (m) { return m.mode; }))
      .filter(function (m) { return MODE_TITLE[m]; })
      .map(function (m) { return T(MODE_TITLE[m][0], MODE_TITLE[m][1]); }).join(" + ");
    var src = perf.source === "probe" && embed
      ? T("来源：专用性能探测", "Source: dedicated probe") + " — " +
        fill(T("{n} 个请求", "{n} requests"), { n: int(perf.probe_requests) })
      : perf.source === "probe"
      ? T("来源：专用性能探测", "Source: dedicated probe") + " — " +
        fill(T("{n} × {max} tokens", "{n} × {max} tokens"), {
          n: int(perf.probe_requests),
          max: perf.probe_max_tokens ? int(perf.probe_max_tokens) : "?",
        }) + (kind ? " · " + kind : "")
      : T("来源：本次检测自身的请求", "Source: the audit's own requests");
    var pid = "zp" + ++seq;
    var o = ['<div class="zp-section" data-zp="' + pid + '">'];
    var scored = perf.source === "probe"
      ? T("稳定性计入性能表现维度", "Consistency is scored in the performance dimension")
      : T("仅供参考，不计分", "Informational — not scored");
    o.push('<p class="zp-muted">' + esc(src) + " · " + esc(scored) + "</p>");
    var parts = sectionParts(perf, pid);
    o.push(tabs(embed ? "latency" : sectionState.metric, pid, embed));
    o.push(parts.scale, parts.plot, parts.legend);
    o.push(modeBlock(perf.mode, perf.target, perf.baseline, perf.comparison, !embed && modes.length > 0, embed));
    modes.forEach(function (m) {
      o.push(modeBlock(m.mode, m.target, m.baseline, m.comparison, !embed, embed));
    });
    if (perf.probe_cost) {
      var pc = perf.probe_cost;
      o.push('<p class="zp-muted">' + esc(T("探测成本", "Probe cost")) + ": " + esc(T("请求数", "Requests")) + " " +
        int(pc.requests) + " · " + esc(embed
          ? fill(T("{input} 个输入 token（usage）", "{input} input tokens (usage)"), { input: num(pc.input_tokens_reported) })
          : fill(T("{input} + {output} tokens（usage）", "{input} + {output} tokens (usage)"),
            { input: num(pc.input_tokens_reported), output: num(pc.output_tokens_reported) })) + "</p>");
    }
    if ((perf.notes || []).length)
      o.push('<ul class="zp-list zp-notes">' + perf.notes.map(function (n) { return "<li>" + esc(note(n)) + "</li>"; }).join("") + "</ul>");
    o.push("</div>");
    return o.join("");
  }
  // Re-draw only the chart of a rendered section when its metric tab changes.
  function wireSection(root, perf) {
    if (!root) return;
    var sec = root.querySelector(".zp-section");
    var pid = sec && sec.getAttribute("data-zp");
    if (!pid) return;
    // a newly shown report's chart moves in; a re-render of the same one
    // (language switch) stays still
    if (root.zpPerf !== perf) {
      root.zpPerf = perf;
      motion(root.querySelector("svg.zp-chart"));
    }
    // redraw the y-range switch, plot and legend; `then(oldSvg)` adds motion
    function redraw(then) {
      var parts = sectionParts(perf, pid), old = root.querySelector("svg.zp-chart");
      hideTip();
      [[".zp-scale", parts.scale], [".zp-plot", parts.plot], [".zp-legend", parts.legend]].forEach(function (p) {
        var el = root.querySelector(p[0]);
        if (el) el.outerHTML = p[1];
      });
      wireSection(root, perf);
      then(old);
    }
    wire(root, function (id) {
      sectionState.metric = id;
      var tabsEl = root.querySelector(".zp-tabs");
      if (tabsEl) tabsEl.outerHTML = tabs(id, pid);
      redraw(function () { motion(root.querySelector("svg.zp-chart")); });
    }, function (open) {
      sectionState.open = open;
    });
    root.querySelectorAll(".zp-scale [data-scale]").forEach(function (b) {
      b.onclick = function () {
        var id = b.getAttribute("data-scale");
        sectionState.scale = id === "auto" ? null : id;
        redraw(function (old) {
          rescale(old, root.querySelector("svg.zp-chart"));
          var f = root.querySelector('.zp-seg [aria-pressed="true"]');
          if (f) f.focus(); // the pressed button was redrawn
        });
      };
    });
  }

  // ---- motion (chartmotion.js) ------------------------------------------ //
  function motion(svg, fresh) {
    var M = window.EkteMotion;
    if (!M || !svg) return;
    if (fresh) M.pop(svg, fresh);
    else M.enter(svg);
  }
  // the y-range changed: the requests slide from where `old` drew them
  function rescale(old, svg) {
    var M = window.EkteMotion;
    if (M && M.rescale && old && svg) M.rescale(old, svg);
  }
  // after a live render: a new chart (first draw, another metric) sweeps in,
  // a redrawn one pops only the requests it did not show before
  function liveMotion(self) {
    var svg = self.host && self.host.querySelector ? self.host.querySelector("svg.zp-chart") : null;
    if (!svg || svg === self.zmSvg) return;
    var old = self.zmSvg, moved = !!old && !!self.zmScale && self.zmScale !== self.scaleEff;
    self.zmSvg = svg;
    self.zmScale = self.scaleEff;
    var seen = {}, fresh = [], prev = self.zmSeen, first = !prev || self.zmMetric !== self.metric;
    Array.prototype.forEach.call(svg.querySelectorAll(".zp-pt, .zp-fail"), function (el) {
      var s = (/^#(\d+)\s/.exec(el.getAttribute("data-tip") || "") || [])[1];
      seen[s] = 1;
      if (!first && !prev[s]) fresh.push(el);
    });
    self.zmSeen = seen;
    self.zmMetric = self.metric;
    if (first) motion(svg);
    else if (moved) rescale(old, svg); // (a request new in this frame simply shows)
    else if (fresh.length) motion(svg, fresh);
  }

  // ---- live panel -------------------------------------------------------- //
  function Live(host) {
    this.host = host;
    this.metric = "latency";
    this.open = false;
    this.pid = "zpl" + ++seq;
    this.reset({});
  }
  Live.prototype.reset = function (opts) {
    this.records = [];
    this.probeTotal = (opts && opts.probeTotal) || 0;
    this.hasBaseline = !!(opts && opts.hasBaseline);
    this.pending = false;
    this.scale = null; // the y-range the user chose; null: automatic (a new audit starts automatic)
    this.scaleEff = null; // the y-range shown
    this.el = null; // the rendered panel's parts, patched in place by render()
    this.zmSeen = this.zmSvg = this.zmScale = null; // what the chart showed (liveMotion)
    this.table = null; // what the data table currently shows (see fillTable)
    if (this.host) this.host.innerHTML = "";
  };
  Live.prototype.add = function (records) {
    var self = this;
    (records || []).forEach(function (r) { self.records.push(r); });
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(function () {
      self.pending = false;
      self.render();
    });
  };
  // The first render builds the panel; later ones (one per animation frame
  // while records stream in) update its tiles, probe bar, chart and legend in
  // place, and redraw the tabs only when their markup changes (a new metric or
  // language). The data table is built only while its toggle is open, and new
  // records are appended to it.
  Live.prototype.render = function () {
    if (!this.host || !this.records.length) return;
    var recs = this.records;
    // completion calls, or a non-chat job's embedding/rerank calls
    var calls = recs.filter(isCall);
    var embedOnly = calls.length > 0 && !calls.some(function (r) { return r.op === "complete"; });
    // an embedding/rerank audit has latency only (no tokens, no streaming)
    if (embedOnly) this.metric = "latency";
    var target = calls.filter(function (r) { return r.endpoint !== "baseline" && r.ok && !r.cached; });
    var probeDone = calls.filter(function (r) { return r.endpoint !== "baseline" && r.phase === "probe"; }).length;
    var tps = target.map(function (r) { return r.decode_tps_local != null ? r.decode_tps_local : r.decode_tps_reported; });
    var ttftP50 = p50(target.map(function (r) { return r.ttft_ms; }));
    var tpsP50 = p50(tps);
    var decodeLabel = T("解码速度 p50", "Decode speed p50");
    // Non-streamed calls have no first token, so no TTFT and no decode speed
    // (it needs the first-token time). Until a streamed call lands, show the
    // end-to-end speed instead, as the final report does.
    if (tpsP50 == null) {
      var e2e = p50(target.map(function (r) { return r.e2e_tps_local != null ? r.e2e_tps_local : r.e2e_tps_reported; }));
      if (e2e != null) {
        tpsP50 = e2e;
        decodeLabel = T("端到端速度 p50", "End-to-end speed p50");
      }
    }
    function withUnit(v, unit) { return v == null ? "—" : num(v) + " " + unit; }
    // y-range: focused on the probe while it runs, unless the user chose one
    var running = this.probeTotal > 0 && probeDone > 0 && probeDone < this.probeTotal;
    var sc = scaleState(recs, this.metric, this.scale, running ? "probe" : "full");
    var said = !this.scale && this.scaleEff && sc.eff !== this.scaleEff ? scaleSaid(sc.eff) : "";
    this.scaleEff = sc.eff;
    var chartV = chartSvg(recs, this.metric, sc.eff);
    var v = {
      title: T("性能 · 实时", "Performance · live"),
      head: [
        [T("请求数", "Requests"), int(calls.length)],
        [T("延迟 p50", "Latency p50"), withUnit(p50(target.map(function (r) { return r.duration_ms; })), "ms")],
      ].concat(embedOnly ? [] : [
        ["TTFT p50", withUnit(ttftP50, "ms")],
        [decodeLabel, withUnit(tpsP50, "tok/s")],
      ]),
      probe: null,
      embed: embedOnly,
      tabs: tabs(this.metric, this.pid, embedOnly),
      scale: this.probeTotal > 0 || hasProbe(recs) ? scaleBar(sc, chartV) : "",
      chart: chartV,
      legend: legend(recs, this.hasBaseline, chartV.over),
    };
    if (this.probeTotal) {
      var label = T("性能探测", "Performance probe");
      v.probe = {
        label: label,
        text: label + " " + int(probeDone) + "/" + int(this.probeTotal),
        max: String(this.probeTotal),
        now: String(Math.min(probeDone, this.probeTotal)),
        width: Math.min(100, Math.round((probeDone / this.probeTotal) * 100)) + "%",
      };
    }
    // Streamed re-renders must not take keyboard focus away from a tab or
    // from the data-table toggle, ...
    var act = document.activeElement, refocus = null;
    if (act && act !== this.host && this.host.contains(act)) {
      // (the selected tab: after an arrow key the focused one is the old metric)
      if (act.getAttribute("data-metric")) refocus = '.zp-tabs [data-metric="' + this.metric + '"]';
      else if (act.tagName === "SUMMARY") refocus = ".zp-data summary";
      // a y-range button (gone after "Back to automatic": the pressed one)
      else if (act.getAttribute("data-scale"))
        refocus = act.getAttribute("data-scale") === "auto" ? '.zp-seg [aria-pressed="true"]'
          : '.zp-seg [data-scale="' + act.getAttribute("data-scale") + '"]';
    }
    // ... nor jump an open data table back to its top.
    var box = this.host.querySelector(".zp-data-scroll"), scrollTop = box ? box.scrollTop : 0;
    if (act && box && box.contains(act)) refocus = ".zp-data-scroll";
    var el = this.el;
    if (el && el.root.parentNode === this.host && !el.probe === !v.probe && !el.scale === !v.scale) this.patch(v);
    else this.build(v);
    if (said && this.el && this.el.say) this.el.say.textContent = said;
    liveMotion(this);
    box = this.host.querySelector(".zp-data-scroll");
    if (box && scrollTop && box.scrollTop !== scrollTop) box.scrollTop = scrollTop;
    // Only an element that was replaced is focused again (no focus() call,
    // and so no new announcement, while it stays in place).
    if (refocus && !this.host.contains(act)) {
      var f = this.host.querySelector(refocus);
      if (f) f.focus();
    }
  };
  function tileHtml(x) {
    return '<div class="zp-tile"><div class="zp-tl">' + esc(x[0]) + '</div><div class="zp-tv">' + esc(x[1]) + "</div></div>";
  }
  function plotInner(c, open) {
    return c.html + (c.empty ? "" : dataTable(c.calls, c.m, open, true));
  }
  Live.prototype.build = function (v) {
    var self = this;
    var prev = this.host.querySelector(".zp-data");
    // the toggle may have been opened before its "toggle" event ran
    var open = this.open || !!(prev && prev.open);
    var o = ['<div class="zp-live"><div class="zp-live-h">' + esc(v.title) + "</div>"];
    o.push('<div class="zp-tiles">' + v.head.map(tileHtml).join("") + "</div>");
    if (v.probe) {
      o.push('<div class="zp-probe"><span>' + esc(v.probe.text) + '</span><div class="zp-bar" role="progressbar" aria-label="' +
        esc(v.probe.label) + '" aria-valuemin="0" aria-valuemax="' + v.probe.max + '" aria-valuenow="' + v.probe.now +
        '"><i style="width:' + v.probe.width + '"></i></div></div>');
    }
    o.push(v.tabs);
    o.push(v.scale);
    o.push('<div class="zp-plot" role="tabpanel" id="' + this.pid + '-panel" aria-labelledby="' + this.pid + "-tab-" +
      this.metric + '">' + plotInner(v.chart, open) + "</div>");
    o.push(v.legend);
    // announces an automatic y-range switch (kept across patches, so it speaks)
    o.push('<div class="zp-sr" role="status"></div>');
    o.push("</div>");
    this.host.innerHTML = o.join("");
    this.markTable(open, v.chart);
    this.el = null;
    var root = this.host.querySelector(".zp-live");
    if (!root) return; // not a real DOM (the tests): nothing to update in place
    var probe = root.querySelector(".zp-probe");
    this.el = {
      root: root,
      title: root.querySelector(".zp-live-h"),
      tiles: Array.prototype.map.call(root.querySelectorAll(".zp-tile"), function (t) {
        return [t.querySelector(".zp-tl"), t.querySelector(".zp-tv")];
      }),
      probe: probe && { text: probe.querySelector("span"), bar: probe.querySelector(".zp-bar"), fill: probe.querySelector(".zp-bar i") },
      tabs: root.querySelector(".zp-tabs"),
      scale: root.querySelector(".zp-scale"),
      plot: root.querySelector(".zp-plot"),
      legend: root.querySelector(".zp-legend"),
      say: root.querySelector(".zp-sr"),
      cache: { tabs: v.tabs, tabsKey: tabs(METRICS[0].id, this.pid, v.embed), scale: v.scale, chart: v.chart.html, empty: v.chart.empty, legend: v.legend },
    };
    this.wirePlot();
    wireTabs(root, function (id) { self.setMetric(id); });
    // the y-range switch (redrawn as it changes: one delegated handler)
    root.addEventListener("click", function (e) {
      var b = e.target && e.target.closest ? e.target.closest("[data-scale]") : null;
      if (!b || !root.contains(b) || b.disabled) return;
      var id = b.getAttribute("data-scale");
      self.scale = id === "auto" ? null : id;
      self.render();
    });
    // One delegated tooltip handler for every chart mark, current and future
    // (shown where the pointer enters a mark: hover only, no movement tracking).
    root.addEventListener("mouseover", function (e) {
      var t = e.target && e.target.closest ? e.target.closest("[data-tip]") : null;
      if (t && root.contains(t)) showTip(e, t.getAttribute("data-tip"));
      else hideTip();
    });
    root.addEventListener("mouseleave", hideTip);
  };
  Live.prototype.setMetric = function (id) {
    this.metric = id;
    this.render();
  };
  // Hook up the data-table toggle (after the plot's contents were built).
  Live.prototype.wirePlot = function () {
    var self = this, el = this.el, det = el.plot.querySelector(".zp-data");
    el.det = det;
    el.box = det && det.querySelector(".zp-data-scroll");
    el.summary = det && det.querySelector("summary");
    if (!det) return;
    // Fill the table as the toggle opens, so it never shows up empty or stale
    // (a click on the summary runs before the details opens; "toggle" after).
    el.summary.addEventListener("click", function () {
      if (!det.open && self.el && self.el.det === det) self.fillTable();
    });
    det.addEventListener("toggle", function () {
      if (!self.el || self.el.det !== det) return;
      self.open = det.open;
      if (det.open) self.fillTable();
    });
  };
  Live.prototype.patch = function (v) {
    var self = this, el = this.el, c = el.cache;
    setText(el.title, v.title);
    v.head.forEach(function (x, i) {
      if (!el.tiles[i]) return;
      setText(el.tiles[i][0], x[0]);
      setText(el.tiles[i][1], x[1]);
    });
    if (v.probe) {
      setText(el.probe.text, v.probe.text);
      setAttr(el.probe.bar, "aria-label", v.probe.label);
      setAttr(el.probe.bar, "aria-valuemax", v.probe.max);
      setAttr(el.probe.bar, "aria-valuenow", v.probe.now);
      if (el.probe.fill.style.width !== v.probe.width) el.probe.fill.style.width = v.probe.width;
    }
    var tabsKey = tabs(METRICS[0].id, this.pid, v.embed);
    if (v.tabs !== c.tabs && tabsKey === c.tabsKey) {
      // another metric: move the selection, keeping the buttons (and focus)
      el.tabs.querySelectorAll("[data-metric]").forEach(function (b) {
        var on = b.getAttribute("data-metric") === self.metric;
        setAttr(b, "aria-selected", String(on));
        if (b.tabIndex !== (on ? 0 : -1)) b.tabIndex = on ? 0 : -1;
        b.classList.toggle("on", on);
        if (!on && b.getAttribute("class") === "") b.removeAttribute("class");
      });
      c.tabs = v.tabs;
    }
    if (v.tabs !== c.tabs) {
      // new labels (a language switch): redraw them
      c.tabsKey = tabsKey;
      el.tabs.outerHTML = v.tabs;
      el.tabs = el.root.querySelector(".zp-tabs");
      wireTabs(el.root, function (id) { self.setMetric(id); });
      c.tabs = v.tabs;
    }
    if (v.scale !== c.scale && el.scale) {
      el.scale.outerHTML = v.scale;
      el.scale = el.root.querySelector(".zp-scale");
      c.scale = v.scale;
    }
    setAttr(el.plot, "aria-labelledby", this.pid + "-tab-" + this.metric);
    if (v.chart.empty !== c.empty) {
      // the first samples arrived (or this metric has none): the plot gains
      // or loses its data table
      var open = this.open || !!(el.det && el.det.open);
      el.plot.innerHTML = plotInner(v.chart, open);
      this.markTable(open, v.chart);
      this.wirePlot();
    } else if (v.chart.html !== c.chart) {
      el.plot.firstElementChild.outerHTML = v.chart.html;
    }
    c.chart = v.chart.html;
    c.empty = v.chart.empty;
    if (el.summary) setText(el.summary, dataSummary());
    if (el.det && el.det.open) this.fillTable();
    if (v.legend !== c.legend) {
      el.legend.outerHTML = v.legend;
      el.legend = el.root.querySelector(".zp-legend");
      c.legend = v.legend;
    }
  };
  function setText(node, s) {
    if (node && node.textContent !== s) node.textContent = s;
  }
  function setAttr(node, name, s) {
    if (node && node.getAttribute(name) !== s) node.setAttribute(name, s);
  }
  // Note what a just built plot's data table holds (nothing while closed).
  Live.prototype.markTable = function (open, chart) {
    this.table = open && !chart.empty ? { recs: this.records, n: this.records.length, key: this.tableKey(chart.m) } : null;
  };
  // What a data-table row's markup depends on besides its record.
  Live.prototype.tableKey = function (m) {
    return [m.id, dataHead(m), loc(), T("失败", "failed"), T("缓存命中（不计入统计）", "cached (excluded)"),
      T("非流式", "non-streaming"), endpointName({}), endpointName({ endpoint: "baseline" }),
      phaseName("probe"), phaseName("passive")].join("\n");
  };
  // Bring the open data table up to date: append the rows of records added
  // since it was built, or rebuild it after a metric or language change.
  Live.prototype.fillTable = function () {
    var el = this.el, box = el && el.box;
    if (!box) return;
    var m = metric(this.metric), recs = this.records, key = this.tableKey(m), t = this.table;
    var tbody = box.querySelector("tbody");
    var complete = isCall;
    if (t && tbody && t.key === key && t.recs === recs && t.n <= recs.length) {
      if (t.n < recs.length) {
        var rows = dataRows(recs.slice(t.n).filter(complete), m);
        if (rows.length) tbody.insertAdjacentHTML("beforeend", rows.map(function (r) { return dataRow(r, m); }).join(""));
      }
    } else {
      var top = box.scrollTop;
      box.innerHTML = dataTableHtml(dataRows(recs.filter(complete), m), m);
      if (top && box.scrollTop !== top) box.scrollTop = top;
    }
    this.table = { recs: recs, n: recs.length, key: key };
  };

  // ---- styles (injected once) ------------------------------------------- //
  // Every colour is a --zp-* property. The defaults (a neutral palette) sit
  // in :where(), i.e. zero specificity, so any page rule setting them wins.
  var CSS =
    ":where(.zp-section,.zp-live,.zp-tip){--zp-t:#2a78d6;--zp-b:#eb6834;--zp-x:#d03b3b;--zp-surface:#fffefb;" +
    "--zp-grid:#e7ece5;--zp-ink:#0c211e;--zp-ink2:#566460;--zp-faint:#93a09b;--zp-panel:#fff;--zp-tile:#f5f8f4;" +
    "--zp-track:#e3ebe3;--zp-tab:#fbfdfa;--zp-tab-on:#0c211e;--zp-tab-on-ink:#fff;--zp-cached:#8c959f;" +
    "--zp-better:#1a7f37;--zp-worse:#cb3b2e;--zp-focus:#2a78d6;--zp-tip-bg:#0c211e;--zp-tip-ink:#fff;" +
    "--zp-tip-shadow:rgba(0,0,0,.5)}" +
    ".zp-section,.zp-live{text-align:left}" +
    ".zp-live{margin:18px auto 0;max-width:620px;background:var(--zp-panel);border:1px solid var(--zp-grid);border-radius:14px;padding:12px 14px}" +
    ".zp-live-h{font-weight:700;font-size:13px;color:var(--zp-ink);margin-bottom:8px}" +
    ".zp-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:4px 0 10px}" +
    "@media(max-width:520px){.zp-tiles{grid-template-columns:1fr 1fr}}" +
    ".zp-tile{background:var(--zp-tile);border:1px solid var(--zp-grid);border-radius:10px;padding:7px 9px}" +
    ".zp-tl{font-size:11px;color:var(--zp-faint);font-weight:600}" +
    ".zp-tv{font-weight:700;font-size:16px;color:var(--zp-ink);font-variant-numeric:tabular-nums}" +
    ".zp-tv small{font-size:11px;color:var(--zp-ink2);font-weight:600}" +
    ".zp-probe{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--zp-ink2);margin:0 0 8px;font-family:var(--mono,monospace)}" +
    ".zp-bar{flex:1;height:5px;background:var(--zp-track);border-radius:3px;overflow:hidden}" +
    ".zp-bar i{display:block;height:100%;background:var(--zp-t);transition:width .3s}" +
    ".zp-tabs{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 6px}" +
    ".zp-tabs button{font:600 12px var(--sans,system-ui);color:var(--zp-ink2);background:var(--zp-tab);border:1.5px solid var(--zp-grid);border-radius:999px;padding:4px 11px;cursor:pointer}" +
    ".zp-tabs button.on{color:var(--zp-tab-on-ink);background:var(--zp-tab-on);border-color:var(--zp-tab-on)}" +
    ".zp-tabs button:focus-visible,.zp-data summary:focus-visible{outline:2px solid var(--zp-focus);outline-offset:2px}" +
    ".zp-chart{width:100%;height:auto;display:block}" +
    ".zp-grid{stroke:var(--zp-grid);stroke-width:1}" +
    ".zp-tick{fill:var(--zp-ink2);font-size:11px;font-variant-numeric:tabular-nums}" +
    ".zp-pt{stroke:var(--zp-surface);stroke-width:2}.zp-pt.t{fill:var(--zp-t)}.zp-pt.b{fill:var(--zp-b)}" +
    // audit (passive) requests: a lightly tinted ring in the series colour, so the
    // mark keeps >= 3:1 (its stroke) yet reads apart from solid and hollow points;
    // cached hits: grey, ringed in the secondary ink
    ".zp-pt.passive{fill-opacity:.35}.zp-pt.passive.t{stroke:var(--zp-t)}.zp-pt.passive.b{stroke:var(--zp-b)}" +
    ".zp-pt.t.cached,.zp-pt.b.cached{fill:var(--zp-cached);fill-opacity:.6;stroke:var(--zp-ink2)}.zp-pt:hover{stroke:var(--zp-ink)}" +
    ".zp-pt.hollow{fill:var(--zp-surface)}.zp-pt.hollow.t{stroke:var(--zp-t)}.zp-pt.hollow.b{stroke:var(--zp-b)}" +
    ".zp-legend .zp-key.hollow{background:transparent;border:2px solid var(--zp-t);box-sizing:border-box}" +
    ".zp-better{color:var(--zp-better);font-weight:700}.zp-worse{color:var(--zp-worse);font-weight:700}" +
    ".zp-mode{border-top:1px solid var(--zp-grid);padding-top:14px;margin-top:20px;font-size:14.5px}" +
    ".zp-fail{stroke:var(--zp-x);stroke-width:2;stroke-linecap:round}" +
    // full opacity (>= 3:1 like the dots, BITV 9.1.4.11), thinner than a mark
    ".zp-trend path{fill:none;stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}" +
    ".zp-trend .t{stroke:var(--zp-t)}.zp-trend .b{stroke:var(--zp-b)}" +
    // the p25–p75 band: a wash behind the line (the line carries the 3:1)
    ".zp-band path{stroke:none;fill-opacity:.14}.zp-band .t{fill:var(--zp-t)}.zp-band .b{fill:var(--zp-b)}" +
    // probe requests: small and translucent with a hairline in the series
    // colour (the outline keeps each dot >= 3:1, BITV 9.1.4.11), so a dense run
    // reads as a light cloud around the median, not a chain of rings
    ".zp-pt.probe{stroke-width:1;fill-opacity:.4}.zp-pt.probe.t{stroke:var(--zp-t)}.zp-pt.probe.b{stroke:var(--zp-b)}" +
    ".zp-pt.probe.hollow{stroke-width:1.5;fill-opacity:1}.zp-pt.probe.cached{stroke:var(--zp-ink2)}" +
    // requests above a focused y-range: triangles on the top edge
    ".zp-off{stroke:var(--zp-surface);stroke-width:1.5}.zp-off.t{fill:var(--zp-t)}.zp-off.b{fill:var(--zp-b)}" +
    ".zp-off:hover{stroke:var(--zp-ink)}" +
    ".zp-key.line{width:14px;height:2px;border-radius:1px;background:var(--zp-ink2);vertical-align:middle}" +
    ".zp-legend .zp-key.probe{width:7px;height:7px;background:color-mix(in srgb,var(--zp-t) 40%,transparent);border:1px solid var(--zp-t);box-sizing:border-box}" +
    ".zp-key.band{width:16px;height:10px;border-radius:2px;vertical-align:middle;background:linear-gradient(var(--zp-ink2),var(--zp-ink2)) center/100% 2px no-repeat," +
    "color-mix(in srgb,var(--zp-ink2) 22%,transparent)}" +
    ".zp-key.tri{width:0;height:0;border-radius:0;border:solid transparent;border-width:0 5px 9px;border-bottom-color:var(--zp-t)}" +
    // the y-range switch above the chart
    ".zp-scale{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin:0 0 4px;font-size:12px;color:var(--zp-ink2)}" +
    ".zp-seg{display:inline-flex;gap:2px;padding:2px;border:1.5px solid var(--zp-grid);border-radius:999px;background:var(--zp-tab)}" +
    ".zp-seg button{font:600 12px var(--sans,system-ui);color:var(--zp-ink2);background:none;border:0;border-radius:999px;padding:3px 10px;min-height:24px;cursor:pointer}" +
    ".zp-seg button[aria-pressed=true]{color:var(--zp-tab-on-ink);background:var(--zp-tab-on)}" +
    ".zp-seg button:disabled{opacity:.5;cursor:not-allowed}" +
    ".zp-auto{font:600 12px var(--sans,system-ui);color:var(--zp-ink);background:none;border:0;padding:3px 2px;min-height:24px;cursor:pointer;text-decoration:underline;text-underline-offset:2px}" +
    ".zp-seg button:focus-visible,.zp-auto:focus-visible{outline:2px solid var(--zp-focus);outline-offset:2px}" +
    ".zp-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}" +
    ".zp-legend{display:flex;flex-wrap:wrap;gap:12px;font-size:11.5px;color:var(--zp-ink2);margin:2px 0 8px}" +
    ".zp-key{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;font-style:normal}" +
    ".zp-key.t{background:var(--zp-t)}.zp-key.b{background:var(--zp-b)}" +
    ".zp-legend .zp-key.passive{background:color-mix(in srgb,var(--zp-t) 35%,transparent);border:2px solid var(--zp-t);box-sizing:border-box}" +
    ".zp-key.x{width:auto;height:auto;border-radius:0;color:var(--zp-x);font-weight:800}" +
    ".zp-empty{font-size:12.5px;color:var(--zp-faint);padding:18px 0;text-align:center}" +
    ".zp-muted{font-size:12.5px;color:var(--zp-ink2);margin:6px 0;line-height:1.5}" +
    ".zp-h{font-size:13.5px;margin:16px 0 6px;color:var(--zp-ink)}" +
    ".zp-scroll{overflow-x:auto}" +  // .zp-wide: a plain wrapper (pages may let it scroll)
    ".zp-table{width:100%;border-collapse:collapse;font-size:12px;margin:6px 0 10px;font-variant-numeric:tabular-nums}" +
    ".zp-table th{font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--zp-faint);text-align:left;padding:5px 7px;border-bottom:1px solid var(--zp-grid)}" +
    ".zp-table td{padding:5px 7px;border-bottom:1px dotted var(--zp-grid);color:var(--zp-ink2);white-space:nowrap}" +
    ".zp-table .r{text-align:right}.zp-table.zp-small{width:auto}" +
    ".zp-unit{color:var(--zp-faint);font-size:10.5px}" +
    ".zp-list{font-size:12.5px;color:var(--zp-ink2);margin:6px 0;padding-left:18px;line-height:1.55}" +
    // The data table is for screen readers until it takes focus or is opened
    // (:where keeps this overridable: a page may always show the toggle).
    ".zp-plot{position:relative}" +
    ".zp-data:where(:not(:focus-within):not([open])){position:absolute;left:0;bottom:0;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}" +
    ".zp-data summary{font-size:12px;color:var(--zp-ink2);cursor:pointer;margin:2px 0 4px}" +
    ".zp-data-scroll{max-height:260px;overflow:auto}" +
    ".zp-tip{position:fixed;z-index:50;display:none;pointer-events:none;white-space:pre;background:var(--zp-tip-bg);color:var(--zp-tip-ink);" +
    "font:500 11.5px/1.45 var(--mono,monospace);padding:7px 9px;border-radius:8px;box-shadow:0 8px 24px -10px var(--zp-tip-shadow)}";
  (function inject() {
    if (typeof document === "undefined" || !document.head || document.getElementById("zp-css")) return;
    var st = document.createElement("style");
    st.id = "zp-css";
    st.textContent = CSS;
    document.head.appendChild(st);
  })();

  window.EktePerf = {
    Live: Live,
    section: section,
    wireSection: wireSection,
    chart: chart,
    niceAxis: niceAxis,
    CSS: CSS,
  };
})();
