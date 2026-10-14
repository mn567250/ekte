/* heatgrid.js — proposed replacement for ZingCharts.heatmap (prototype).
 *
 * Weekdays run across (7 columns), the day runs down in buckets of
 * cfg.bucketH hours: a divisor of 24 (1, 2, 3, 4, 6; default 4 -> 6 rows),
 * so every block has the same length. Cells are square; their size follows the
 * width and keeps the grid at most MAXH px tall. Same
 * colour scale, hatching, empty outlines, legend and pointer-only tooltip as
 * the current heatmap; same <svg role="img"> name and description.
 *
 * cfg: id, title, desc, unit, cells [{ dow 1..7, hour 0..23, v, runs }]
 *      (hourly, as the API sends them), bucketH, minRuns, days [7 names],
 *      rowLabel(h0, h1), tipTime(dow, h0, h1), lowHint, legend { few, none }
 *
 * Hourly cells are merged per bucket here with a run-weighted mean of their
 * values (prototype only: the real chart should get bucketed medians from
 * the server, a mean of medians is not a median).
 */
(function () {
  "use strict";
  var C = window.ZingCharts, esc = C.esc, fmt = C.fmt, STEPS = 5, MAX = 60, MAXH = 440;

  function heatGrid(host, cfg) {
    var B = [1, 2, 3, 4, 6].indexOf(cfg.bucketH) >= 0 ? cfg.bucketH : 4, rows = Math.ceil(24 / B), at = {}, list = [];
    (cfg.cells || []).forEach(function (c) {
      if (typeof c.v !== "number" || !isFinite(c.v)) return;
      var r = Math.floor(c.hour / B), k = c.dow + "-" + r, a = at[k];
      if (!a) { a = at[k] = { dow: c.dow, row: r, sum: 0, runs: 0 }; list.push(a); }
      a.sum += c.v * (c.runs || 1); a.runs += c.runs || 1;
    });
    list.forEach(function (a) { a.v = a.sum / a.runs; a.low = a.runs < (cfg.minRuns || 3); });
    var vs = list.map(function (a) { return a.v; });
    var lo = vs.length ? Math.min.apply(null, vs) : 0, hi = vs.length ? Math.max.apply(null, vs) : 1;
    var step = function (v) { return hi > lo ? Math.min(STEPS - 1, Math.floor(((v - lo) / (hi - lo)) * STEPS)) : 2; };

    var W0 = Math.max(260, Math.floor(host.clientWidth || 640));
    var left = 48, top = 20;
    var size = Math.max(16, Math.min(MAX, Math.floor((W0 - left - 2) / 7), Math.floor(MAXH / rows)));   // square cells
    var W = left + 7 * size + 2, H = top + rows * size + 2;
    var f1 = function (n) { return n.toFixed(1); }, pat = esc(cfg.id) + "-hatch";
    var out = ['<svg class="hmap hgrid" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H +
      '" role="img" aria-labelledby="' + esc(cfg.id) + '-t" aria-describedby="' + esc(cfg.id) + '-d" focusable="false">' +
      '<title id="' + esc(cfg.id) + '-t">' + esc(cfg.title) + '</title><desc id="' + esc(cfg.id) + '-d">' + esc(cfg.desc) + "</desc>" +
      '<defs><pattern id="' + pat + '" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5"/></pattern></defs>'];
    out.push('<g class="hx">');
    // narrow cells (1-hour blocks) get shortened day names; the full name is
    // in the tooltip and the table
    var cut = size < 22 ? 1 : size < 34 ? 2 : 0;
    cfg.days.forEach(function (d, i) {
      out.push('<text x="' + f1(left + i * size + size / 2 + 1) + '" y="12" text-anchor="middle">' + esc(cut ? String(d).slice(0, cut) : d) + "</text>");
    });
    out.push('</g><g class="hy">');
    for (var r = 0; r < rows; r++) {
      out.push('<text x="' + (left - 8) + '" y="' + f1(top + r * size + size / 2 + 1) + '" dy="0.32em" text-anchor="end">' +
        esc(cfg.rowLabel(r * B, Math.min(24, (r + 1) * B))) + "</text>");
    }
    out.push('</g><g class="cells">');
    for (var dow = 1; dow <= 7; dow++) {
      for (r = 0; r < rows; r++) {
        var a = at[dow + "-" + r], x = f1(left + (dow - 1) * size + 2), y = f1(top + r * size + 2), s = size - 2;
        if (!a) { out.push('<rect class="none" x="' + x + '" y="' + y + '" width="' + s + '" height="' + s + '" rx="4"/>'); continue; }
        out.push('<rect class="q' + (step(a.v) + 1) + (a.low ? " low" : "") + '" data-k="' + dow + "-" + r + '" x="' + x + '" y="' + y + '" width="' + s + '" height="' + s + '" rx="4"/>');
        if (a.low) out.push('<rect class="hatch" fill="url(#' + pat + ')" x="' + x + '" y="' + y + '" width="' + s + '" height="' + s + '" rx="4" pointer-events="none"/>');
      }
    }
    out.push("</g></svg>");
    var L = cfg.legend || {};
    var sw = function (cls) {
      return '<svg width="16" height="12" viewBox="0 0 16 12" aria-hidden="true" focusable="false" class="hmap hsw">' +
        (cls === "low" ? '<defs><pattern id="' + pat + '-l" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5"/></pattern></defs>' +
          '<rect class="q3 low" x="0.5" y="0.5" width="15" height="11" rx="3"/><rect class="hatch" fill="url(#' + pat + '-l)" x="0.5" y="0.5" width="15" height="11" rx="3"/>'
          : '<rect class="' + cls + '" x="0.5" y="0.5" width="15" height="11" rx="3"/>') + "</svg>";
    };
    var scale = "";
    for (var i = 1; i <= STEPS; i++) scale += sw("q" + i);
    host.innerHTML = out.join("") + '<div class="ctip" aria-hidden="true" hidden></div>' +
      '<ul class="hlegend"><li><span class="hv">' + esc(fmt(lo, cfg.unit)) + '</span><span class="hscale" aria-hidden="true">' + scale +
      '</span><span class="hv">' + esc(fmt(hi, cfg.unit)) + "</span></li><li>" + sw("low") + "<span>" + esc(L.few || "") + "</span></li><li>" +
      sw("none") + "<span>" + esc(L.none || "") + "</span></li></ul>";

    // pointer-only tooltip (aria-hidden: the data table has the same values);
    // Escape hides it, it stays while hovered — as tipFor in charts.js
    var svg = host.querySelector("svg"), tip = host.querySelector(".ctip"), shown = null;
    function hide() { shown = null; tip.hidden = true; }
    svg.addEventListener("mouseover", function (ev) {
      var hit = ev.target.closest && ev.target.closest("[data-k]");
      if (!hit) return;
      var k = hit.getAttribute("data-k");
      if (shown === k) return;
      shown = k;
      var a = at[k], h0 = a.row * B;
      tip.innerHTML = '<p class="when">' + esc(cfg.tipTime(a.dow, h0, Math.min(24, h0 + B))) + "</p><ul><li><span><b>" + esc(fmt(a.v, cfg.unit)) + "</b>" +
        '<span class="sub">' + esc(a.runs + " runs") + "</span>" + (a.low ? '<span class="sub lowtxt">' + esc(cfg.lowHint) + "</span>" : "") + "</span></li></ul>";
      tip.hidden = false;
      var bw = svg.getBoundingClientRect().width || W, sc = bw / W, xr = (left + a.dow * size) * sc + 10, tw = tip.offsetWidth;
      tip.style.left = (xr + tw > host.clientWidth ? Math.max(0, (left + (a.dow - 1) * size) * sc - tw - 10) : xr) + "px";
    });
    host.onpointerleave = hide;
    if (host.zcKey) document.removeEventListener("keydown", host.zcKey);
    host.zcKey = function (ev) { if (ev.key === "Escape" && shown != null) hide(); };
    document.addEventListener("keydown", host.zcKey);
  }

  C.heatGrid = heatGrid;
})();
