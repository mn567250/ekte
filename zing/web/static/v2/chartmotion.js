/* chartmotion.js — opt-in entrance motion for charts drawn by charts.js.
 *
 * Plain browser global, no libraries; load after charts.js. Exposes
 * window.ZingMotion with:
 *   - enter(host)          call right after a draw whose DATA changed (a new
 *                          filter, metric or range) — not after a redraw for
 *                          a resize or a language switch
 *   - fresh(host, k)       live updates: pop in only the last k markers of
 *                          each series (the rest of the chart stays still)
 *   - pop(svg, marks)      live updates: pop in exactly these marks (the
 *                          perf.js live chart: the new requests' dots and
 *                          failure crosses)
 *   - rescale(old, svg)    perf.js: the y-range changed (full range / probe
 *                          focus): each request slides from where the old
 *                          <svg> drew it to its new height; the axis and
 *                          the running-median lines and bands fade in
 *   - count(els, show)     KPI figures: each element counts up to its new
 *                          value; els is a list of {el, from, to, …}, show(v, it)
 *                          formats item it's value v on the way
 *   enter() also takes the <svg> itself instead of its host.
 *
 * It never changes what the chart says: no element is added or removed and
 * no ARIA attribute is touched. The temporary class, pathLength and --zm-d
 * are removed again when the motion ends, so the DOM at rest is exactly what
 * charts.js drew. Nothing happens under prefers-reduced-motion, nor while the
 * header's motion switch (nav.js) sets data-motion="off" on <html>.
 */
(function () {
  "use strict";

  var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  function still() {
    return !mq || mq.matches || document.documentElement.getAttribute("data-motion") === "off";
  }

  // x of a marker from its path data ("M12.3,45.6…"): string work, no layout
  var SWEEP = 600; // ms for the left-to-right reveal of a line chart
  var SEG = 170;   // ms between the segments of one stacked bar
  var STEP = 110;  // ms per colour step of a heat-grid cell (as --zm-step in the CSS)
  var WAVE = 420;  // ms from the first heat-grid cell starting to the last
  var NS = "http://www.w3.org/2000/svg";

  function pairs(d) {
    return d.replace(/[MZ]/g, "").split("L").filter(Boolean);
  }
  // band path "M top… L bottom (reversed)… Z" -> collapsed onto the median line
  function grow(band, at, anims) {
    var line = band.nextElementSibling;
    if (!line || !line.classList.contains("line")) return;
    var b = pairs(band.getAttribute("d") || ""), l = pairs(line.getAttribute("d") || ""), n = l.length;
    // no SMIL (never in current browsers): the band simply shows
    if (b.length !== 2 * n || !n || typeof band.ownerSVGElement.animationsPaused !== "function") return;
    var flat = "M" + l.join("L") + "L" + l.slice().reverse().join("L") + "Z";
    var end = at(parseFloat(l[n - 1])), dur = end + 420;
    var a = document.createElementNS(NS, "animate");
    a.setAttribute("attributeName", "d");
    a.setAttribute("values", flat + ";" + flat + ";" + band.getAttribute("d"));
    a.setAttribute("keyTimes", "0;" + (end / dur).toFixed(3) + ";1");
    a.setAttribute("calcMode", "spline");
    a.setAttribute("keySplines", "0 0 1 1;0.2 0.8 0.2 1");
    a.setAttribute("dur", dur + "ms");
    a.setAttribute("begin", "indefinite");
    a.setAttribute("fill", "remove");
    band.appendChild(a);
    anims.push(a);
  }

  function px(el) {
    var m = /^M\s*(-?[\d.]+)/.exec(el.getAttribute("d") || "");
    return m ? parseFloat(m[1]) : 0;
  }

  function cleanup(svg, ms, cls, els, anims) {
    clearTimeout(svg.zmT);
    svg.zmT = setTimeout(function () {
      svg.classList.remove(cls);
      (anims || []).forEach(function (a) { if (a.parentNode) a.parentNode.removeChild(a); });
      els.forEach(function (el) {
        el.style.removeProperty("--zm-d");
        el.style.removeProperty("--zm-t");
        el.style.removeProperty("--zm-dy");
        if (!el.getAttribute("style")) el.removeAttribute("style");
        if (el.zmPL) { el.removeAttribute("pathLength"); el.zmPL = false; }
        el.classList.remove("zm-fresh");
        el.classList.remove("zm-mv");
      });
    }, ms);
  }

  function enter(host) {
    var svg = host && (host instanceof SVGElement ? host : host.querySelector("svg"));
    if (!svg || still()) return;
    var touched = [], anims = [], until = 1150, i;
    // stacked bars are drawn as "tchart sbars": test for them first
    if (svg.classList.contains("tchart") && !svg.classList.contains("sbars")) {
      // One sweep from left to right over SWEEP ms: each line segment draws
      // while the sweep crosses it (a segment after a gap waits its turn) and
      // each marker pops in as the sweep reaches its x. The line is drawn by
      // its dash; with pathLength="1" nothing is measured.
      var lines = svg.querySelectorAll(".ser .line"), pts = svg.querySelectorAll(".ser .pt");
      var lo = Infinity, hi = -Infinity, xs = [], ends = [];
      for (i = 0; i < pts.length; i++) { xs[i] = px(pts[i]); lo = Math.min(lo, xs[i]); hi = Math.max(hi, xs[i]); }
      for (i = 0; i < lines.length; i++) {
        var d = lines[i].getAttribute("d") || "", last = /(-?[\d.]+),-?[\d.]+\s*$/.exec(d);
        ends[i] = [px(lines[i]), last ? parseFloat(last[1]) : px(lines[i])];
        lo = Math.min(lo, ends[i][0]); hi = Math.max(hi, ends[i][1]);
      }
      var at = function (x) { return Math.round(((x - lo) / (hi - lo || 1)) * SWEEP); };
      for (i = 0; i < lines.length; i++) {
        lines[i].setAttribute("pathLength", "1"); lines[i].zmPL = true;
        lines[i].style.setProperty("--zm-d", at(ends[i][0]) + "ms");
        lines[i].style.setProperty("--zm-t", Math.max(60, at(ends[i][1]) - at(ends[i][0])) + "ms");
        touched.push(lines[i]);
      }
      for (i = 0; i < pts.length; i++) { pts[i].style.setProperty("--zm-d", Math.max(0, at(xs[i]) - 60) + "ms"); touched.push(pts[i]); }
      // The p25–p75 band grows out of its median line once the sweep has
      // drawn that segment: its path morphs from the line (top and bottom
      // edges on the median) to the band. SMIL <animate> on d works in every
      // current browser (CSS d animation does not in Safari); it is removed
      // again with the rest.
      var bands = svg.querySelectorAll(".ser .band");
      for (i = 0; i < bands.length; i++) grow(bands[i], at, anims);
    } else if (svg.classList.contains("sbars")) {
      var bars = svg.querySelectorAll(".bar");
      for (i = 0; i < bars.length; i++) {
        // bars start left to right; inside a bar the segments grow in drawing
        // order, which is bottom to top (each starts as the one below it ends)
        var b0 = Math.round((i / Math.max(1, bars.length - 1)) * 300), segs = bars[i].querySelectorAll(".seg");
        for (var j = 0; j < segs.length; j++) { segs[j].style.setProperty("--zm-d", (b0 + j * SEG) + "ms"); touched.push(segs[j]); }
      }
    } else if (svg.classList.contains("zp-chart")) {
      // perf.js request timeline: dots and failure crosses pop in as a sweep
      // passes their x; a running-median line (if drawn) draws with it
      var marks = svg.querySelectorAll(".zp-pt, .zp-fail"), mx = [], m0 = Infinity, m1 = -Infinity;
      for (i = 0; i < marks.length; i++) {
        mx[i] = marks[i].tagName === "circle" ? parseFloat(marks[i].getAttribute("cx")) || 0 : px(marks[i]) + 4;
        m0 = Math.min(m0, mx[i]); m1 = Math.max(m1, mx[i]);
      }
      for (i = 0; i < marks.length; i++) {
        marks[i].style.setProperty("--zm-d", Math.round(((mx[i] - m0) / (m1 - m0 || 1)) * SWEEP) + "ms");
        touched.push(marks[i]);
      }
      var tl = svg.querySelectorAll(".zp-trend path");
      for (i = 0; i < tl.length; i++) {
        var a0 = px(tl[i]), lm = /(-?[\d.]+),-?[\d.]+\s*$/.exec(tl[i].getAttribute("d") || ""), a1 = lm ? parseFloat(lm[1]) : a0;
        var at0 = Math.round(((a0 - m0) / (m1 - m0 || 1)) * SWEEP), at1 = Math.round(((a1 - m0) / (m1 - m0 || 1)) * SWEEP);
        tl[i].setAttribute("pathLength", "1"); tl[i].zmPL = true;
        tl[i].style.setProperty("--zm-d", at0 + "ms");
        tl[i].style.setProperty("--zm-t", Math.max(60, at1 - at0) + "ms");
        touched.push(tl[i]);
      }
    } else if (svg.classList.contains("hgrid")) {
      // The empty grid shows first (each cell as an empty tile), then every cell
      // fills at the same pace through the colour scale and stops at its own
      // step: light cells settle early, dark ones keep darkening (the step
      // durations live in the CSS). Cells start in a wave from the bottom-left
      // corner, left to right and bottom to top (positions from the x / y
      // attributes: no layout read).
      var cells = svg.querySelectorAll(".cells rect[data-k]"), cx = [], cy = [], x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, last = 0;
      for (i = 0; i < cells.length; i++) {
        cx[i] = parseFloat(cells[i].getAttribute("x")) || 0; cy[i] = parseFloat(cells[i].getAttribute("y")) || 0;
        x0 = Math.min(x0, cx[i]); x1 = Math.max(x1, cx[i]); y0 = Math.min(y0, cy[i]); y1 = Math.max(y1, cy[i]);
      }
      for (i = 0; i < cells.length; i++) {
        var delay = Math.round(((cx[i] - x0) / (x1 - x0 || 1) * 0.6 + (y1 - cy[i]) / (y1 - y0 || 1) * 0.4) * WAVE);
        var q = /\bq(\d)\b/.exec(cells[i].getAttribute("class")), done = delay + (q ? +q[1] : 1) * STEP;
        cells[i].style.setProperty("--zm-d", delay + "ms");
        touched.push(cells[i]);
        var h = cells[i].nextElementSibling; // a few-runs cell's hatching shows once the cell is filled
        if (h && h.classList.contains("hatch")) { h.style.setProperty("--zm-d", done + "ms"); touched.push(h); }
        last = Math.max(last, done + 200);
      }
      until = Math.max(until, last + 100);
    } else if (svg.classList.contains("hmap")) {
      // one fade for the whole grid: ~170 cells animated one by one cost
      // dropped frames on a slow CPU, a single group animation does not
    } else return;
    svg.classList.add("zm-in");
    for (i = 0; i < anims.length; i++) anims[i].beginElement();
    cleanup(svg, until, "zm-in", touched, anims);
  }

  function fresh(host, k) {
    var svg = host && host.querySelector("svg.tchart");
    if (!svg || still() || !(k > 0)) return;
    var touched = [], sers = svg.querySelectorAll(".ser");
    for (var s = 0; s < sers.length; s++) {
      var pts = sers[s].querySelectorAll(".pt");
      for (var i = Math.max(0, pts.length - k); i < pts.length; i++) { pts[i].classList.add("zm-fresh"); touched.push(pts[i]); }
    }
    svg.classList.add("zm-new");
    cleanup(svg, 450, "zm-new", touched);
  }

  function pop(svg, marks) {
    if (!svg || still() || !marks || !marks.length) return;
    var touched = [];
    for (var i = 0; i < marks.length; i++) { marks[i].classList.add("zm-fresh"); touched.push(marks[i]); }
    svg.classList.add("zm-new");
    cleanup(svg, 450, "zm-new", touched);
  }

  // perf.js y-range switch. Marks are matched by request number (the "#n"
  // their tooltip starts with) and slide vertically by the difference: a
  // translate, so a dot keeps its shape (scaling the plot would stretch it).
  // A dot that becomes a triangle above a focused range slides up into it.
  // The axis, the running-median lines and their bands fade in (cut at a
  // focused range's top edge, their points differ: no morph).
  var RESCALE = 420; // ms
  function rescale(old, svg) {
    if (!old || !svg || still()) return;
    var key = function (el) { return (/^#(\d+)\s/.exec(el.getAttribute("data-tip") || "") || [])[1]; };
    var py = function (el) {
      if (el.tagName === "circle") return parseFloat(el.getAttribute("cy")) || 0;
      var m = /^M\s*-?[\d.]+,(-?[\d.]+)/.exec(el.getAttribute("d") || "");
      return m ? parseFloat(m[1]) : 0;
    };
    var was = {}, touched = [], i;
    var before = old.querySelectorAll(".zp-pt, .zp-off"), after = svg.querySelectorAll(".zp-pt, .zp-off");
    for (i = 0; i < before.length; i++) was[key(before[i])] = py(before[i]);
    for (i = 0; i < after.length; i++) {
      var k = key(after[i]), dy = k in was ? was[k] - py(after[i]) : 0;
      if (Math.abs(dy) < 0.5) continue;
      after[i].style.setProperty("--zm-dy", dy.toFixed(1) + "px");
      after[i].classList.add("zm-mv");
      touched.push(after[i]);
    }
    svg.classList.add("zm-rs");
    cleanup(svg, RESCALE + 60, "zm-rs", touched);
  }

  var COUNT = 700; // ms for a KPI figure to count up
  function count(items, show) {
    function paint(k) {
      // ease-out cubic: fast at first, settling on the value; whole-number
      // targets (run counts) stay whole on the way
      var e = 1 - Math.pow(1 - k, 3);
      items.forEach(function (it) {
        var v = k >= 1 ? it.to : it.from + (it.to - it.from) * e;
        it.el.textContent = show(Math.round(it.to) === it.to && k < 1 ? Math.round(v) : v, it);
      });
    }
    var host = items.length && items[0].el;
    if (still() || !host || typeof host.animate !== "function") return paint(1);
    // an empty Web Animation is the clock: it shows in document.getAnimations(),
    // so whatever waits for the page's animations also waits for the count,
    // and the final value lands the moment it ends
    var clock = host.animate([], { duration: COUNT });
    clock.finished.then(function () { paint(1); }, function () { /* replaced */ });
    paint(0);
    function step() {
      // a newer render replaced these elements: stop
      if (!host.isConnected) { clock.cancel(); return; }
      if (clock.playState === "finished") return;
      paint(Math.min(1, (clock.currentTime || 0) / COUNT));
      window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  window.ZingMotion = { enter: enter, fresh: fresh, pop: pop, rescale: rescale, count: count };
})();
