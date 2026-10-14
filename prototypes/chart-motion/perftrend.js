/* perftrend.js — proposed addition to perf.js (prototype): a running-median
 * line per endpoint behind the live chart's request dots.
 *
 * For every successful, uncached request the line takes the median of that
 * endpoint's last N such requests (N = 5), drawn at the request's x. Failed
 * and cached requests do not feed it (as the p50 tiles), so a failure never
 * pulls the line to zero and the line never "connects" a failure. The dots,
 * crosses, tooltips and data table stay exactly as perf.js draws them.
 *
 * In perf.js itself this would be a few lines inside chartSvg() using its own
 * x / y scales; here it reads the dots' cx and rebuilds the y scale with the
 * same niceAxis rule, so perf.js can stay unchanged.
 *
 *   ZingPerfTrend.draw(svg, records, metricId) -> true if a line was drawn
 */
(function () {
  "use strict";
  var N = 5, H = 230, MT = 10, MB = 30; // perf.js chart geometry
  var GET = {
    latency: function (r) { return r.duration_ms; },
    ttft: function (r) { return r.ttft_ms; },
    tps: function (r) { return r.decode_tps_local != null ? r.decode_tps_local : r.decode_tps_reported; },
    itl: function (r) { return r.itl_mean_ms; },
  };
  function niceAxis(v) { // same rule as perf.js
    if (!(v > 0)) return { max: 1 };
    var base = Math.pow(10, Math.floor(Math.log10(v / 6))), steps = [1, 2, 2.5, 5, 10];
    for (var i = 0; ; i++) { var step = steps[i] * base, n = Math.ceil(v / step - 1e-9); if (n <= 6) return { max: n * step }; }
  }
  function median(a) {
    var s = a.slice().sort(function (x, y) { return x - y; }), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  function draw(svg, records, metricId) {
    var get = GET[metricId] || GET.latency;
    var calls = records.filter(function (r) { return r.op === "complete"; });
    var pts = calls.filter(function (r) { return r.ok && get(r) != null; });
    if (!pts.length) return false;
    var yMax = niceAxis(Math.max.apply(null, pts.map(get).concat([1])) * 1.05).max, ph = H - MT - MB;
    var y = function (v) { return MT + ph - (v / yMax) * ph; };
    // each dot's x, by its request number (the tooltip starts with "#seq ")
    var xs = {};
    Array.prototype.forEach.call(svg.querySelectorAll("circle.zp-pt"), function (c) {
      var m = /^#(\d+)\s/.exec(c.getAttribute("data-tip") || "");
      if (m) xs[m[1]] = c.getAttribute("cx");
    });
    var out = [];
    ["target", "baseline"].forEach(function (ep) {
      var win = [], d = [];
      pts.filter(function (r) { return (r.endpoint === "baseline" ? "baseline" : "target") === ep && !r.cached; })
        .sort(function (a, b) { return a.start_ms - b.start_ms; })
        .forEach(function (r) {
          win.push(get(r)); if (win.length > N) win.shift();
          if (xs[r.seq] != null) d.push(xs[r.seq] + "," + y(median(win)).toFixed(1));
        });
      if (d.length > 1) out.push('<path class="' + (ep === "baseline" ? "b" : "t") + '" d="M' + d.join("L") + '"/>');
    });
    if (!out.length) return false;
    var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "zp-trend");
    g.innerHTML = out.join("");
    var first = svg.querySelector(".zp-pt, .zp-fail");
    svg.insertBefore(g, first); // behind the dots and crosses
    return true;
  }
  window.ZingPerfTrend = { draw: draw, N: N };
})();
