/* ekte web UI v2 — the ONE place numbers, units, counts, durations and relay
 * names become text (issue 229). Every page loads it right after /i18n.js:
 *   <script src="/static/fmt.js"></script>
 * and every number with a unit, every "{n} runs" and every relay name in the
 * UI goes through it (tests/test_web_formatters.py fails on a page that
 * glues a unit to a number itself), so History, Analytics, Monitors and the
 * report spell them alike: locale grouping ("1,300", "1.300"), a space
 * before the unit ("1,300 ms"), the same decimals per unit everywhere.
 *
 * Plain browser global, no modules; works without lang.js (node tests):
 * then in English with the browser's number format. window.EkteFmt:
 *   num(v, digits)        a number in the UI locale, at most `digits`
 *                         decimals (default 0); "—" for null / NaN
 *   unit(v, unit, o)      a value with its unit: ratio -> "12.5 %" (the
 *                         locale's percent), ms, s, tok/s, tokens, score,
 *                         count; o.digits overrides the unit's decimals,
 *                         o.bare drops the unit
 *   parts(v, unit, o)     the same as { text, unit } (KPI tiles set the unit
 *                         smaller); unit "" for ratio, score and count
 *   delta(d, unit)        a signed difference: "+2.1", "−120 ms", "+3 pp"
 *   unitName(unit, long)  the unit as an axis caption ("ms", "%"), or
 *                         written out (long: "milliseconds", "percentage
 *                         points", "tokens per second")
 *   runs(n), requests(n), models(n)
 *                         "1 run" / "1,300 runs" (one form per count, the
 *                         number formatted)
 *   elapsed(ms)           a wall-clock time: "850 ms", "4.2 s", "73 s"
 *   duration(ms)          in mixed units, only those it needs (mirrors
 *                         _fmt_duration in ekte/report/render.py): 850 µs,
 *                         457 ms, 6 s 97 ms, 1 min 5 s, 2 h 3 min 4 s
 *   bytes(n)              a file size: "512 bytes", "1.5 KB", "2.3 MB"
 *   relay(label, full, max)
 *                         a relay's name as HTML: the label the server gives
 *                         (a saved name, else the host, plus port and path
 *                         when needed), cut in the middle with "…" past
 *                         `max` characters (default 40) instead of breaking
 *                         mid-word; the full name (or URL) in the title
 *   middle(s, max)        that cut as text
 *   fill(text, vars)      "{name}" placeholders filled from vars: every
 *                         page's Tf(zh, en, vars) is T(zh, en) through this,
 *                         so a number in a sentence ("{n} runs") is grouped
 *                         like every other number ("1,300 runs"); a number
 *                         right after "#" is an id and stays as it is
 *                         ("run #42"); strings are inserted unchanged
 *
 * Unit ids: the server's metric formats are accepted too (percent and
 * ratio_percent = ratio, tok_s = tok/s).
 */
(function () {
  "use strict";

  function Tx(zh, en) { return window.T ? window.T(zh, en) : en; }
  function fill(text, vars) {
    return String(text).replace(/(#?)\{(\w+)\}/g, function (m, hash, k) {
      if (!vars || !Object.prototype.hasOwnProperty.call(vars, k)) return m;
      var v = vars[k];
      return hash + (typeof v === "number" && !hash && isFinite(v) ? num(v, 20) : String(v));
    });
  }
  function Tf(zh, en, vars) { return fill(Tx(zh, en), vars); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var cache = {};
  function nf(opts) {
    try { if (window.EKTE_LANG && window.EKTE_LANG.numFmt) return window.EKTE_LANG.numFmt(opts); } catch (e) { /* below */ }
    var k = JSON.stringify(opts || {});
    return cache[k] || (cache[k] = new Intl.NumberFormat(undefined, opts));
  }
  function ok(v) { return typeof v === "number" && isFinite(v); }

  var ALIAS = { percent: "ratio", ratio_percent: "ratio", tok_s: "tok/s" };
  function id(unit) { return ALIAS[unit] || unit; }
  var DIGITS = { score: 1, ratio: 1, ms: 0, "tok/s": 1, tokens: 0, count: 1, s: 1 };
  var SHORT = { ms: "ms", "tok/s": "tok/s", tokens: "tok", s: "s" };

  function num(v, digits) {
    v = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
    if (!ok(v)) return "—";
    return nf({ maximumFractionDigits: digits == null ? 0 : digits }).format(v);
  }

  function parts(v, unit, o) {
    unit = id(unit);
    o = o || {};
    if (!ok(v)) return { text: "—", unit: "" };
    if (unit === "ratio") return { text: nf({ style: "percent", maximumFractionDigits: o.digits != null ? o.digits : 1 }).format(v), unit: "" };
    var d = o.digits != null ? o.digits : DIGITS[unit] != null ? DIGITS[unit] : 1;
    return { text: nf({ maximumFractionDigits: d }).format(v), unit: SHORT[unit] || "" };
  }

  function unit(v, u, o) {
    var p = parts(v, u, o);
    return (o && o.bare) || !p.unit ? p.text : p.text + " " + p.unit;
  }

  function delta(d, u) {
    u = id(u);
    if (!ok(d)) return "—";
    if (u === "ratio") {
      return Tf("{n} 个百分点", "{n} pp", { n: nf({ maximumFractionDigits: 1, signDisplay: "exceptZero" }).format(d * 100) });
    }
    var s = nf({ maximumFractionDigits: DIGITS[u] != null ? DIGITS[u] : 1, signDisplay: "exceptZero" }).format(d);
    return SHORT[u] ? s + " " + SHORT[u] : s;
  }

  function unitName(u, long) {
    u = id(u);
    if (long) {
      return {
        score: Tx("健康分（0–100）", "score (0–100)"), ratio: Tx("百分比", "percent"), pp: Tx("百分点", "percentage points"),
        ms: Tx("毫秒", "milliseconds"), s: Tx("秒", "seconds"), "tok/s": Tx("每秒 token 数", "tokens per second"),
        tokens: "tokens", count: Tx("个数", "count"),
      }[u] || u || "";
    }
    return {
      score: Tx("健康分（0–100）", "score (0–100)"), ratio: "%", ms: "ms", "tok/s": "tok/s",
      tokens: "tokens", count: Tx("个数", "count"), s: Tx("秒", "seconds"),
    }[u] || u || "";
  }

  // "1 run" / "{n} runs": the English key of each form is what the locale
  // fragments translate
  function counter(zhOne, enOne, zhMany, enMany) {
    return function (n) { return n === 1 ? Tx(zhOne, enOne) : Tf(zhMany, enMany, { n: num(n) }); };
  }
  var runs = counter("1 次检测", "1 run", "{n} 次检测", "{n} runs");
  var requests = counter("1 次请求", "1 request", "{n} 次请求", "{n} requests");
  var models = counter("1 个模型", "1 model", "{n} 个模型", "{n} models");

  function elapsed(ms) {
    if (!ok(ms)) return "—";
    return ms < 1000 ? num(ms, 0) + " ms" : num(ms / 1000, ms < 10000 ? 1 : 0) + " s";
  }

  function duration(ms) {
    if (!ok(ms)) return "—";
    var sign = ms < 0 ? "-" : "";
    ms = Math.abs(ms);
    if (ms === 0) return "0 ms";
    if (ms < 1) return sign + num(Math.round(ms * 1000)) + " µs";
    if (ms < 10) return sign + num(ms, 1) + " ms";
    var t = Math.round(ms), list;
    if (t < 1000) return sign + num(t) + " ms";
    if (t < 60000) list = [[Math.floor(t / 1000), "s"], [t % 1000, "ms"]];
    else {
      var s = Math.round(ms / 1000);
      list = [[Math.floor(s / 3600), "h"], [Math.floor(s / 60) % 60, "min"], [s % 60, "s"]];
    }
    return sign + list.filter(function (p) { return p[0]; })
      .map(function (p) { return num(p[0]) + " " + p[1]; }).join(" ");
  }

  function bytes(n) {
    n = Number(n) || 0;
    return n < 1024 ? Tf("{n} 字节", "{n} bytes", { n: num(n) })
      : n < 1048576 ? num(n / 1024, 1) + " KB" : num(n / 1048576, 1) + " MB";
  }

  function middle(s, max) {
    s = String(s == null ? "" : s);
    max = max || 40;
    if (s.length <= max) return s;
    var head = Math.ceil((max - 1) * 0.6), tail = max - 1 - head;
    return s.slice(0, head) + "…" + s.slice(s.length - tail);
  }

  function relay(label, full, max) {
    var text = String(label == null || label === "" ? full || "" : label);
    var shown = middle(text, max);
    var title = full && full !== text ? full : shown !== text ? text : "";
    // a cut name is read in full by screen readers (the title is not)
    var inner = shown === text ? esc(text)
      : '<span aria-hidden="true">' + esc(shown) + '</span><span class="sr-only">' + esc(text) + "</span>";
    return '<span class="relay-nm"' + (title ? ' title="' + esc(title) + '"' : "") + ">" + inner + "</span>";
  }

  window.EkteFmt = {
    num: num, unit: unit, parts: parts, delta: delta, unitName: unitName,
    runs: runs, requests: requests, models: models,
    elapsed: elapsed, duration: duration, bytes: bytes, relay: relay, middle: middle, fill: fill,
  };
})();
