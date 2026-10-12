/* zing web UI v2 — hand-drawn inline-SVG charts and value formatting.
 *
 * Plain browser global, no modules, no libraries, no outgoing requests. Load
 * after /lang.js (T, ZING_LANG) and /icons.js. Exposes window.ZingCharts with:
 *   - esc(s)                  HTML-escaped text (every label from the API
 *                             goes through it: relay names are user input)
 *   - fmt(v, unit, o)         a value in the UI locale with its unit
 *                             (ratio -> %, ms, tok/s, …); "—" for null.
 *                             o.bare drops the unit suffix
 *   - fmtDelta(d, unit)       a signed difference ("+2.1", "−120 ms", "+3 pp")
 *   - unitName(unit)          the unit as an axis caption ("%", "ms", …)
 *   - timeChart(host, cfg)    a time-series line chart: one median line per
 *                             series with its p25–p75 band, gaps where a
 *                             bucket has no data, faded hollow markers for
 *                             buckets with few runs, dashed annotation lines,
 *                             a crosshair + tooltip for the bucket column under
 *                             the pointer (pointer only: the page renders the same
 *                             values as a data table, the accessible
 *                             equivalent, BITV 9.1.1.1 / 9.1.3.1)
 *
 * timeChart cfg:
 *   title, desc     accessible name / description of the <svg role="img">
 *   unit            metric unit (fmt)
 *   bucketMs        bucket length; points further apart than 1.5 buckets are
 *                   not joined (an empty bucket is a gap, never a zero)
 *   domain          [t0, t1] in ms, or null for the data's extent
 *   xTick(t, step)  tick label; tipTime(t) the tooltip's heading
 *   series          [{ label, cls: "s0".."s3", shape, points: [{ t, v, lo, hi, n, runs, low }] }]
 *   marks           [{ t, kind: "tool_version" | "kb_profile", text }]
 *   lowHint         text shown in the tooltip for a bucket with few runs
 *   yMin, yMax      fixed scale bounds (e.g. 0 / 100 for scores), optional
 *   ref             { v, text }: a dashed reference line (e.g. 100 %), optional
 *
 *   - heatmap(host, cfg)      a weekday x hour grid (7 x 24) on a one-hue
 *                             sequential scale (5 steps, light = low): cells
 *                             with few runs hatched and faded, empty cells an
 *                             outline only; legend below; per-cell tooltip
 *     cfg: id, title, desc, unit, cells [{ dow 1..7 (Mon..Sun), hour 0..23,
 *          v, runs, low }], days [7 short names], tipTime(dow, hour),
 *          lowHint, legend { low, high, few, none } texts
 *   - stackBars(host, cfg)    bars over time, each stacked from categories
 *                             (shares of the bucket's total), faded for few
 *                             runs; per-bar tooltip
 *     cfg: id, title, desc, bucketMs, domain, xTick, tipTime, lowHint,
 *          cats [{ id, label, cls }], bars [{ t, total, counts{id: n}, runs, low }],
 *          totalText(bar) a line for the tooltip
 *
 * Colours come from charts.css (series slots s0..s3 per theme); text in the
 * chart wears ink tokens, never the series colour. Shapes (circle, square,
 * triangle, diamond) tell the series apart without colour.
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var SHAPES = ["circle", "square", "triangle", "diamond"];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function Tx(zh, en) { return window.T ? window.T(zh, en) : en; }
  function Tf(zh, en, vars) {
    return Tx(zh, en).replace(/\{(\w+)\}/g, function (m, k) { return vars && k in vars ? vars[k] : m; });
  }
  function nf(opts) {
    try { return window.ZING_LANG.numFmt(opts); } catch (e) { return new Intl.NumberFormat(undefined, opts); }
  }

  var DIGITS = { score: 1, ratio: 1, ms: 0, "tok/s": 1, tokens: 0, count: 1, s: 1 };
  var SUFFIX = { ms: " ms", "tok/s": " tok/s", tokens: " tok", s: " s" };

  function fmt(v, unit, o) {
    if (typeof v !== "number" || !isFinite(v)) return "—";
    o = o || {};
    if (unit === "ratio") return nf({ style: "percent", maximumFractionDigits: o.digits != null ? o.digits : 1 }).format(v);
    var d = o.digits != null ? o.digits : DIGITS[unit] != null ? DIGITS[unit] : 1;
    var s = nf({ maximumFractionDigits: d }).format(v);
    return o.bare || !SUFFIX[unit] ? s : s + SUFFIX[unit];
  }

  function fmtDelta(d, unit) {
    if (typeof d !== "number" || !isFinite(d)) return "—";
    if (unit === "ratio") {
      return Tf("{n} 个百分点", "{n} pp", { n: nf({ maximumFractionDigits: 1, signDisplay: "exceptZero" }).format(d * 100) });
    }
    var s = nf({ maximumFractionDigits: DIGITS[unit] != null ? DIGITS[unit] : 1, signDisplay: "exceptZero" }).format(d);
    return SUFFIX[unit] ? s + SUFFIX[unit] : s;
  }

  function unitName(unit) {
    return {
      score: Tx("健康分（0–100）", "score (0–100)"), ratio: "%", ms: "ms", "tok/s": "tok/s",
      tokens: "tokens", count: Tx("个数", "count"), s: Tx("秒", "seconds"),
    }[unit] || unit || "";
  }

  /* ---------------- scales ---------------- */
  function niceStep(span, count) {
    var raw = span / Math.max(1, count), mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), r = raw / mag;
    return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag;
  }
  function yTicks(lo, hi, count) {
    if (hi <= lo) hi = lo + 1;
    var step = niceStep(hi - lo, count), out = [];
    // from the tick at or below lo to the tick at or above hi, so every
    // value sits inside the labelled range; "|| 0": no "-0" on the axis
    var first = Math.floor(lo / step + 1e-9), last = Math.ceil(hi / step - 1e-9);
    for (var i = first; i <= last; i++) out.push(i * step || 0);
    return out;
  }
  var H1 = 36e5, D1 = 864e5;
  var TSTEPS = [H1, 3 * H1, 6 * H1, 12 * H1, D1, 2 * D1, 7 * D1, 14 * D1, 28 * D1, 91 * D1, 182 * D1, 364 * D1];
  // tick times in the viewer's local time: whole hours, local midnights
  function xTicks(t0, t1, count) {
    var want = (t1 - t0) / Math.max(1, count), step = TSTEPS[TSTEPS.length - 1];
    for (var i = 0; i < TSTEPS.length; i++) if (TSTEPS[i] >= want) { step = TSTEPS[i]; break; }
    var d = new Date(t0), out = [];
    if (step < D1) {
      d.setMinutes(0, 0, 0);
      var hours = step / H1;
      while (d.getHours() % hours) d.setHours(d.getHours() + 1);
      while (d.getTime() < t0) d.setHours(d.getHours() + hours);
      for (; d.getTime() <= t1 && out.length < 60; d.setHours(d.getHours() + hours)) out.push(d.getTime());
    } else {
      d.setHours(0, 0, 0, 0);
      var days = Math.round(step / D1);
      if (d.getTime() < t0) d.setDate(d.getDate() + 1);
      if (days === 7 || days === 14) while (d.getDay() !== 1) d.setDate(d.getDate() + 1); // Mondays (ISO weeks)
      for (; d.getTime() <= t1 && out.length < 60; d.setDate(d.getDate() + days)) out.push(d.getTime());
    }
    return { ticks: out, step: step };
  }

  /* ---------------- marks ---------------- */
  function shapePath(shape, x, y, r) {
    var f = function (n) { return n.toFixed(1); };
    if (shape === "square") { var s = r * 0.9; return "M" + f(x - s) + "," + f(y - s) + "h" + f(2 * s) + "v" + f(2 * s) + "h" + f(-2 * s) + "Z"; }
    if (shape === "triangle") { var h = r * 1.15; return "M" + f(x) + "," + f(y - h) + "L" + f(x + h) + "," + f(y + h * 0.8) + "L" + f(x - h) + "," + f(y + h * 0.8) + "Z"; }
    if (shape === "diamond") { var q = r * 1.2; return "M" + f(x) + "," + f(y - q) + "L" + f(x + q) + "," + f(y) + "L" + f(x) + "," + f(y + q) + "L" + f(x - q) + "," + f(y) + "Z"; }
    return "M" + f(x - r) + "," + f(y) + "a" + r + "," + r + " 0 1,0 " + f(2 * r) + ",0a" + r + "," + r + " 0 1,0 " + f(-2 * r) + ",0Z";
  }
  // a legend / tooltip key: a short line with the series' marker on it
  function keySVG(cls, shape) {
    return '<svg class="ckey ' + esc(cls) + '" width="22" height="12" viewBox="0 0 22 12" aria-hidden="true" focusable="false">' +
      '<line x1="1" x2="21" y1="6" y2="6"/><path d="' + shapePath(shape, 11, 6, 3.6) + '"/></svg>';
  }

  // runs of consecutive buckets (a gap > 1.5 buckets starts a new run)
  function segments(points, bucketMs) {
    var out = [], cur = [];
    points.forEach(function (p, i) {
      if (i && p.t - points[i - 1].t > bucketMs * 1.5) { out.push(cur); cur = []; }
      cur.push(p);
    });
    if (cur.length) out.push(cur);
    return out;
  }

  /* ---------------- the chart ---------------- */
  function timeChart(host, cfg) {
    var series = (cfg.series || []).filter(function (s) { return s.points && s.points.length; });
    var all = [];
    series.forEach(function (s) { s.points.forEach(function (p) { all.push(p); }); });
    var W = Math.max(260, Math.floor(host.clientWidth || 640));
    var narrow = W < 480;
    var H = narrow ? 220 : 270;
    var M = { l: 0, r: 14, t: 18, b: 30 };
    var half = cfg.bucketMs / 2;
    var ts = all.map(function (p) { return p.t; });
    var t0 = cfg.domain ? cfg.domain[0] : Math.min.apply(null, ts);
    var t1 = cfg.domain ? cfg.domain[1] : Math.max.apply(null, ts) + cfg.bucketMs;
    if (!(t1 > t0)) t1 = t0 + cfg.bucketMs;
    var vals = [];
    all.forEach(function (p) { [p.v, p.lo, p.hi].forEach(function (v) { if (typeof v === "number") vals.push(v); }); });
    if (cfg.ref && typeof cfg.ref.v === "number") vals.push(cfg.ref.v);
    var lo = Math.min.apply(null, vals.concat(cfg.yMin != null ? [cfg.yMin] : [0]));
    var hi = Math.max.apply(null, vals.concat(cfg.yMax != null ? [cfg.yMax] : []));
    if (cfg.unit === "ratio" && hi <= 1) hi = 1;
    var yt = yTicks(lo, hi, narrow ? 4 : 5);
    lo = Math.min(lo, yt[0]);
    hi = Math.max(hi, yt[yt.length - 1]);
    var ylab = yt.map(function (v) { return fmt(v, cfg.unit, { bare: true, digits: cfg.unit === "ratio" ? 0 : undefined }); });
    M.l = 12 + Math.max.apply(null, ylab.map(function (s) { return s.length; })) * 7;
    var pw = W - M.l - M.r, ph = H - M.t - M.b;
    var X = function (t) { return M.l + ((t - t0) / (t1 - t0)) * pw; };
    var Y = function (v) { return M.t + ph - ((v - lo) / (hi - lo || 1)) * ph; };
    var xt = xTicks(t0, t1, Math.max(2, Math.floor(pw / (narrow ? 82 : 96))));
    var f1 = function (n) { return n.toFixed(1); };

    var out = [];
    out.push('<svg class="tchart" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H +
      '" role="img" aria-labelledby="' + esc(cfg.id) + '-t" aria-describedby="' + esc(cfg.id) + '-d" focusable="false">' +
      '<title id="' + esc(cfg.id) + '-t">' + esc(cfg.title) + '</title><desc id="' + esc(cfg.id) + '-d">' + esc(cfg.desc) + "</desc>");
    // grid + y axis
    out.push('<g class="grid">');
    yt.forEach(function (v, i) {
      var y = f1(Y(v));
      out.push('<line x1="' + M.l + '" x2="' + (W - M.r) + '" y1="' + y + '" y2="' + y + '"' + (v === 0 ? ' class="zero"' : "") + "/>" +
        '<text x="' + (M.l - 8) + '" y="' + y + '" dy="0.32em" text-anchor="end">' + esc(ylab[i]) + "</text>");
    });
    out.push("</g>");
    // x axis
    out.push('<g class="xaxis"><line x1="' + M.l + '" x2="' + (W - M.r) + '" y1="' + (M.t + ph) + '" y2="' + (M.t + ph) + '"/>');
    xt.ticks.forEach(function (t) {
      var x = f1(X(t));
      out.push('<line class="tick" x1="' + x + '" x2="' + x + '" y1="' + (M.t + ph) + '" y2="' + (M.t + ph + 4) + '"/>' +
        '<text x="' + x + '" y="' + (H - 8) + '" text-anchor="middle">' + esc(cfg.xTick(t, xt.step)) + "</text>");
    });
    out.push("</g>");
    // annotations: one dashed line per bucket; labels of lines closer than
    // 34 px share one label (both kinds listed) so their text never overlaps
    var xs = {};
    (cfg.marks || []).forEach(function (m) {
      var x = X(m.t + half), k = x.toFixed(1);
      (xs[k] = xs[k] || { x: x, kinds: {} }).kinds[m.kind] = 1;
    });
    var lines = Object.keys(xs).map(function (k) { return xs[k]; }).sort(function (a, b) { return a.x - b.x; });
    var groups = [];
    lines.forEach(function (l) {
      var g = groups[groups.length - 1];
      if (g && l.x - g.x0 < 34) {
        g.x1 = l.x;
        Object.keys(l.kinds).forEach(function (k) { g.kinds[k] = 1; });
      } else groups.push({ x0: l.x, x1: l.x, kinds: Object.assign({}, l.kinds) });
    });
    out.push('<g class="marks">');
    lines.forEach(function (l) {
      out.push('<line x1="' + f1(l.x) + '" x2="' + f1(l.x) + '" y1="' + (M.t - 2) + '" y2="' + (M.t + ph) + '"/>');
    });
    groups.forEach(function (g) {
      var glyph = (g.kinds.tool_version ? "v" : "") + (g.kinds.kb_profile ? (g.kinds.tool_version ? "·" : "") + "KB" : "");
      var x = Math.min(W - M.r - 12, (g.x0 + g.x1) / 2);
      out.push('<text x="' + f1(x) + '" y="' + (M.t - 6) + '" text-anchor="middle">' + glyph + "</text>");
    });
    out.push("</g>");
    if (cfg.ref && typeof cfg.ref.v === "number") {
      var ry = f1(Y(cfg.ref.v));
      out.push('<g class="ref"><line x1="' + M.l + '" x2="' + (W - M.r) + '" y1="' + ry + '" y2="' + ry + '"/>' +
        '<text x="' + (W - M.r - 4) + '" y="' + ry + '" dy="-0.45em" text-anchor="end">' + esc(cfg.ref.text) + "</text></g>");
    }
    // series: band, line, markers
    series.forEach(function (s, si) {
      var shape = s.shape || SHAPES[si % SHAPES.length];
      out.push('<g class="ser ' + esc(s.cls) + '">');
      segments(s.points, cfg.bucketMs).forEach(function (seg) {
        var band = seg.filter(function (p) { return typeof p.lo === "number" && typeof p.hi === "number"; });
        if (band.length === seg.length && band.length > 1) {
          var top = band.map(function (p) { return f1(X(p.t + half)) + "," + f1(Y(p.hi)); });
          var bot = band.slice().reverse().map(function (p) { return f1(X(p.t + half)) + "," + f1(Y(p.lo)); });
          out.push('<path class="band" d="M' + top.join("L") + "L" + bot.join("L") + 'Z"/>');
        } else {
          band.forEach(function (p) { // a lone bucket: its band as a short bar
            out.push('<line class="whisk" x1="' + f1(X(p.t + half)) + '" x2="' + f1(X(p.t + half)) + '" y1="' + f1(Y(p.hi)) + '" y2="' + f1(Y(p.lo)) + '"/>');
          });
        }
        if (seg.length > 1) {
          out.push('<path class="line" d="M' + seg.map(function (p) { return f1(X(p.t + half)) + "," + f1(Y(p.v)); }).join("L") + '"/>');
        }
      });
      s.points.forEach(function (p) {
        out.push('<path class="pt' + (p.low ? " low" : "") + '" d="' + shapePath(shape, X(p.t + half), Y(p.v), narrow ? 3.4 : 4) + '"/>');
      });
      out.push("</g>");
    });
    out.push('<line class="cross" x1="0" x2="0" y1="' + M.t + '" y2="' + (M.t + ph) + '" visibility="hidden"/>');
    // hover targets: one column per bucket with data, reaching halfway to its
    // neighbours (no pointermove tracking: hovering a column is enough)
    var times = {};
    all.forEach(function (p) { times[p.t] = 1; });
    var list = Object.keys(times).map(Number).sort(function (a, b) { return a - b; });
    list.forEach(function (t, i) {
      var x = X(t + half), a = i ? (X(list[i - 1] + half) + x) / 2 : M.l, b = i < list.length - 1 ? (X(list[i + 1] + half) + x) / 2 : W - M.r;
      out.push('<rect class="hit" data-t="' + t + '" x="' + f1(a) + '" y="' + M.t + '" width="' + f1(Math.max(1, b - a)) + '" height="' + ph + '"/>');
    });
    out.push("</svg>");

    host.innerHTML = out.join("") + '<div class="ctip" aria-hidden="true" hidden></div>';
    wireTooltip(host, cfg, series, X, half, W);
  }

  // Crosshair + tooltip for the hovered bucket column, listing every series
  // there. Pointer only and aria-hidden: the data table has the same values.
  // Escape hides it (BITV 9.1.4.13 dismissible); it stays while the pointer
  // is over it (hoverable).
  function wireTooltip(host, cfg, series, X, half, W) {
    var svg = host.querySelector("svg"), tip = host.querySelector(".ctip"), cross = svg.querySelector(".cross");
    var shown = null;
    function hide() {
      shown = null;
      tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
    }
    function show(t) {
      if (shown === t) return;
      shown = t;
      var x = X(t + half);
      cross.setAttribute("x1", x.toFixed(1));
      cross.setAttribute("x2", x.toFixed(1));
      cross.setAttribute("visibility", "visible");
      var rows = series.map(function (s, si) {
        var p = s.points.filter(function (q) { return q.t === t; })[0];
        if (!p) return "";
        var spread = typeof p.lo === "number" ? '<span class="sub">p25–p75 ' + esc(fmt(p.lo, cfg.unit)) + " – " + esc(fmt(p.hi, cfg.unit)) + "</span>" : "";
        return '<li class="' + (p.low ? "low" : "") + '">' + keySVG(s.cls, s.shape || SHAPES[si % SHAPES.length]) +
          "<span><b>" + esc(fmt(p.v, cfg.unit)) + "</b> " + '<span class="nm">' + esc(s.label) + "</span>" + spread +
          '<span class="sub">' + esc(Tf("{n} 次检测", "{n} runs", { n: p.runs != null ? p.runs : p.n })) + "</span>" +
          (p.low ? '<span class="sub lowtxt">' + esc(cfg.lowHint) + "</span>" : "") + "</span></li>";
      }).join("");
      var notes = (cfg.marks || []).filter(function (m) { return m.t === t; }).map(function (m) {
        return '<p class="mk">' + esc(m.text) + "</p>";
      }).join("");
      tip.innerHTML = '<p class="when">' + esc(cfg.tipTime(t)) + "</p><ul>" + rows + "</ul>" + notes;
      tip.hidden = false;
      var bw = svg.getBoundingClientRect().width || W, scale = bw / W;
      var tw = tip.offsetWidth, left = x * scale + 14;
      if (left + tw > bw) left = Math.max(0, x * scale - tw - 14);
      tip.style.left = left + "px";
    }
    svg.addEventListener("mouseover", function (ev) {
      var hit = ev.target.closest && ev.target.closest("rect.hit");
      if (hit) show(Number(hit.getAttribute("data-t")));
    });
    // the host is re-used by every render: replace, never stack, its handlers
    host.onpointerleave = hide;
    if (host.zcKey) document.removeEventListener("keydown", host.zcKey);
    host.zcKey = function (ev) {
      if (ev.key === "Escape" && shown != null) hide();
    };
    document.addEventListener("keydown", host.zcKey);
  }

  // A tooltip for marks with a data-k attribute (pointer only, aria-hidden:
  // the page's table has the same values). html(k) fills it, at(k) gives the
  // mark's x in SVG units. Escape hides it; it stays while hovered.
  function tipFor(host, W, html, at, onShow) {
    var svg = host.querySelector("svg"), tip = host.querySelector(".ctip"), shown = null;
    function hide() {
      shown = null;
      tip.hidden = true;
      if (onShow) onShow(null);
    }
    svg.addEventListener("mouseover", function (ev) {
      var hit = ev.target.closest && ev.target.closest("[data-k]");
      if (!hit) return;
      var k = hit.getAttribute("data-k");
      if (shown === k) return;
      shown = k;
      tip.innerHTML = html(k);
      tip.hidden = false;
      if (onShow) onShow(k);
      var bw = svg.getBoundingClientRect().width || W, scale = bw / W, x = at(k);
      var tw = tip.offsetWidth, left = x * scale + 14;
      if (left + tw > bw) left = Math.max(0, x * scale - tw - 14);
      tip.style.left = left + "px";
    });
    host.onpointerleave = hide;
    if (host.zcKey) document.removeEventListener("keydown", host.zcKey);
    host.zcKey = function (ev) {
      if (ev.key === "Escape" && shown != null) hide();
    };
    document.addEventListener("keydown", host.zcKey);
  }

  function svgOpen(cfg, W, H, cls) {
    return '<svg class="' + cls + '" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H +
      '" role="img" aria-labelledby="' + esc(cfg.id) + '-t" aria-describedby="' + esc(cfg.id) + '-d" focusable="false">' +
      '<title id="' + esc(cfg.id) + '-t">' + esc(cfg.title) + '</title><desc id="' + esc(cfg.id) + '-d">' + esc(cfg.desc) + "</desc>";
  }
  function hatch(id) {
    return '<defs><pattern id="' + esc(id) + '" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
      '<line x1="0" y1="0" x2="0" y2="5"/></pattern></defs>';
  }

  /* ---------------- weekday x hour heatmap ---------------- */
  var STEPS = 5;
  function heatmap(host, cfg) {
    var cells = (cfg.cells || []).filter(function (c) { return typeof c.v === "number" && isFinite(c.v); });
    var W = Math.max(300, Math.floor(host.clientWidth || 640));
    var narrow = W < 520;
    var ch = narrow ? 18 : 22, top = 18;
    var left = 10 + Math.max.apply(null, cfg.days.map(function (d) { return String(d).length; })) * 7;
    var cw = (W - left - 2) / 24, H = top + 7 * ch + 2;
    var vs = cells.map(function (c) { return c.v; });
    var lo = vs.length ? Math.min.apply(null, vs) : 0, hi = vs.length ? Math.max.apply(null, vs) : 1;
    var step = function (v) { return hi > lo ? Math.min(STEPS - 1, Math.floor(((v - lo) / (hi - lo)) * STEPS)) : Math.floor(STEPS / 2); };
    var at = {};
    cells.forEach(function (c) { at[c.dow + "-" + c.hour] = c; });
    var f1 = function (n) { return n.toFixed(1); };
    var pat = esc(cfg.id) + "-hatch";
    var out = [svgOpen(cfg, W, H, "hmap"), hatch(pat)];
    out.push('<g class="hx">');
    for (var h = 0; h < 24; h += narrow ? 6 : 3) {
      out.push('<text x="' + f1(left + h * cw + 1) + '" y="11">' + esc(cfg.hourLabel ? cfg.hourLabel(h) : String(h)) + "</text>");
    }
    out.push('</g><g class="hy">');
    cfg.days.forEach(function (d, i) {
      out.push('<text x="' + (left - 8) + '" y="' + f1(top + i * ch + ch / 2) + '" dy="0.32em" text-anchor="end">' + esc(d) + "</text>");
    });
    out.push("</g><g class=\"cells\">");
    for (var dow = 1; dow <= 7; dow++) {
      for (var hr = 0; hr < 24; hr++) {
        var c = at[dow + "-" + hr], x = f1(left + hr * cw + 1), y = f1(top + (dow - 1) * ch + 1);
        var w = f1(Math.max(1, cw - 2)), hh = ch - 2;
        if (!c) {
          out.push('<rect class="none" x="' + x + '" y="' + y + '" width="' + w + '" height="' + hh + '" rx="3"/>');
          continue;
        }
        var k = dow + "-" + hr;
        out.push('<rect class="q' + (step(c.v) + 1) + (c.low ? " low" : "") + '" data-k="' + k + '" x="' + x + '" y="' + y +
          '" width="' + w + '" height="' + hh + '" rx="3"/>');
        if (c.low) out.push('<rect class="hatch" fill="url(#' + pat + ')" x="' + x + '" y="' + y + '" width="' + w + '" height="' + hh + '" rx="3" pointer-events="none"/>');
      }
    }
    out.push("</g></svg>");
    var L = cfg.legend || {};
    var sw = function (cls) {
      return '<svg width="16" height="12" viewBox="0 0 16 12" aria-hidden="true" focusable="false" class="hmap hsw">' +
        (cls === "low" ? hatch(pat + "-l") + '<rect class="q3 low" x="0.5" y="0.5" width="15" height="11" rx="3"/><rect class="hatch" fill="url(#' + pat + '-l)" x="0.5" y="0.5" width="15" height="11" rx="3"/>'
          : '<rect class="' + cls + '" x="0.5" y="0.5" width="15" height="11" rx="3"/>') + "</svg>";
    };
    var scale = "";
    for (var i = 1; i <= STEPS; i++) scale += sw("q" + i);
    var legend = '<ul class="hlegend">' +
      '<li><span class="hv">' + esc(fmt(lo, cfg.unit)) + "</span>" + '<span class="hscale" aria-hidden="true">' + scale + "</span>" +
      '<span class="hv">' + esc(fmt(hi, cfg.unit)) + "</span>" + '<span class="sub">' + esc(L.scale || "") + "</span></li>" +
      "<li>" + sw("low") + "<span>" + esc(L.few || "") + "</span></li>" +
      "<li>" + sw("none") + "<span>" + esc(L.none || "") + "</span></li></ul>";
    host.innerHTML = out.join("") + '<div class="ctip" aria-hidden="true" hidden></div>' + legend;
    tipFor(host, W, function (k) {
      var c = at[k];
      return '<p class="when">' + esc(cfg.tipTime(c.dow, c.hour)) + "</p><ul><li><span><b>" + esc(fmt(c.v, cfg.unit)) + "</b>" +
        '<span class="sub">' + esc(Tf("{n} 次检测", "{n} runs", { n: c.runs })) + "</span>" +
        (c.low ? '<span class="sub lowtxt">' + esc(cfg.lowHint) + "</span>" : "") + "</span></li></ul>";
    }, function (k) {
      var c = at[k];
      return left + c.hour * cw + cw;
    });
  }

  /* ---------------- stacked bars over time ---------------- */
  function stackBars(host, cfg) {
    var bars = (cfg.bars || []).filter(function (b) { return b.total > 0; });
    var W = Math.max(260, Math.floor(host.clientWidth || 640));
    var narrow = W < 480;
    var H = narrow ? 200 : 240;
    var M = { l: 0, r: 14, t: 14, b: 30 };
    var ts = bars.map(function (b) { return b.t; });
    var t0 = cfg.domain ? cfg.domain[0] : Math.min.apply(null, ts);
    var t1 = cfg.domain ? cfg.domain[1] : Math.max.apply(null, ts) + cfg.bucketMs;
    if (!(t1 > t0)) t1 = t0 + cfg.bucketMs;
    var shareOf = function (b, id) { return (b.counts[id] || 0) / b.total; };
    var tops = bars.map(function (b) { return cfg.cats.reduce(function (a, c) { return a + shareOf(b, c.id); }, 0); });
    var hi = Math.max.apply(null, tops.concat([0.01]));
    var yt = yTicks(0, hi, narrow ? 3 : 4);
    hi = yt[yt.length - 1];
    var ylab = yt.map(function (v) { return fmt(v, "ratio", { digits: hi < 0.05 ? 1 : 0 }); });
    M.l = 12 + Math.max.apply(null, ylab.map(function (x) { return x.length; })) * 7;
    var pw = W - M.l - M.r, ph = H - M.t - M.b;
    var X = function (t) { return M.l + ((t - t0) / (t1 - t0)) * pw; };
    var Y = function (v) { return M.t + ph - (v / (hi || 1)) * ph; };
    var xt = xTicks(t0, t1, Math.max(2, Math.floor(pw / (narrow ? 82 : 96))));
    var f1 = function (n) { return n.toFixed(1); };
    var bw = Math.max(2, Math.min(36, X(t0 + cfg.bucketMs) - X(t0) - 2));
    var out = [svgOpen(cfg, W, H, "tchart sbars")];
    out.push('<g class="grid">');
    yt.forEach(function (v, i) {
      var y = f1(Y(v));
      out.push('<line x1="' + M.l + '" x2="' + (W - M.r) + '" y1="' + y + '" y2="' + y + '"' + (v === 0 ? ' class="zero"' : "") + "/>" +
        '<text x="' + (M.l - 8) + '" y="' + y + '" dy="0.32em" text-anchor="end">' + esc(ylab[i]) + "</text>");
    });
    out.push('</g><g class="xaxis"><line x1="' + M.l + '" x2="' + (W - M.r) + '" y1="' + (M.t + ph) + '" y2="' + (M.t + ph) + '"/>');
    xt.ticks.forEach(function (t) {
      var x = f1(X(t));
      out.push('<line class="tick" x1="' + x + '" x2="' + x + '" y1="' + (M.t + ph) + '" y2="' + (M.t + ph + 4) + '"/>' +
        '<text x="' + x + '" y="' + (H - 8) + '" text-anchor="middle">' + esc(cfg.xTick(t, xt.step)) + "</text>");
    });
    out.push("</g>");
    bars.forEach(function (b, i) {
      var cx = X(b.t + cfg.bucketMs / 2), x = f1(cx - bw / 2), acc = 0;
      out.push('<g class="bar' + (b.low ? " low" : "") + '">');
      cfg.cats.forEach(function (c) {
        var v = shareOf(b, c.id);
        if (!v) return;
        var y0 = Y(acc), y1 = Y(acc + v);
        acc += v;
        // a 1px surface gap between stacked segments
        out.push('<rect class="seg ' + esc(c.cls) + '" x="' + x + '" y="' + f1(y1) + '" width="' + f1(bw) + '" height="' + f1(Math.max(1, y0 - y1 - 1)) + '"/>');
      });
      // the hover target: the whole bucket column
      out.push('<rect class="hit" data-k="' + i + '" x="' + f1(cx - Math.max(bw, 12) / 2) + '" y="' + M.t + '" width="' + f1(Math.max(bw, 12)) + '" height="' + ph + '"/></g>');
    });
    out.push("</svg>");
    host.innerHTML = out.join("") + '<div class="ctip" aria-hidden="true" hidden></div>';
    tipFor(host, W, function (k) {
      var b = bars[Number(k)];
      var rows = cfg.cats.slice().reverse().map(function (c) {
        var n = b.counts[c.id] || 0;
        return '<li><span class="sw ' + esc(c.cls) + '" aria-hidden="true"></span><span><b>' + esc(fmt(n / b.total, "ratio")) + "</b> " +
          '<span class="nm">' + esc(c.label) + '</span><span class="sub">' + esc(Tf("{n} 次请求", "{n} requests", { n: n })) + "</span></span></li>";
      }).join("");
      return '<p class="when">' + esc(cfg.tipTime(b.t)) + "</p><ul>" + rows + "</ul>" +
        '<p class="mk">' + esc(cfg.totalText(b)) + (b.low ? "<br>" + esc(cfg.lowHint) : "") + "</p>";
    }, function (k) { return X(bars[Number(k)].t + cfg.bucketMs / 2); });
  }

  window.ZingCharts = {
    esc: esc,
    fmt: fmt,
    fmtDelta: fmtDelta,
    unitName: unitName,
    keySVG: keySVG,
    SHAPES: SHAPES,
    timeChart: timeChart,
    heatmap: heatmap,
    stackBars: stackBars,
  };
})();
