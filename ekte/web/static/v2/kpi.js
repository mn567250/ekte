/* ekte web UI v2 — KPI tiles: one look and one behaviour for every key
 * figure of the UI (#208): the Analytics key figures and panel headlines, the
 * live performance panel, the report's performance section and verdict
 * scores, and the History group trends.
 *
 * Plain browser global, no modules; works without a DOM (html() only, for
 * the node tests). Exposes window.EkteKpi with:
 *   - html(tiles, opts)          the tile list's HTML
 *   - mount(box, tiles, opts)    draws it into box; returns { update(tiles),
 *                                el }: update() patches the tiles in place
 *                                when the same tiles are shown (no focus moved,
 *                                nothing announced again), else draws anew
 *   - count(box, tiles, opts)    counts the figures up from the ones shown
 *                                before (in box, or under opts.key when box
 *                                is drawn anew; EkteMotion.count; from 0 the
 *                                first time; still: only remembered)
 *   - fromServer(t, ctx)         a tile of the server (ekte.web.metrics.tile)
 *                                as a tile here
 *
 * A tile (all optional but id and label):
 *   { id, label, text (the value as shown), unit (small suffix), value (the
 *     number counted up), na (keeps its slot: "n/a"), naText, hint
 *     (toggletip text), delta: { text, sign (-1|0|1), dir: better | worse |
 *     neutral | none, sr (spoken trend) }, note (a muted line instead of a
 *     delta), caption, faded (aria-describedby id), group (a new group
 *     starts after a divider), family (good | sky | warn | bad | grey:
 *     colours the value), slot (HTML before the value, e.g. a sparkline),
 *     sr (spoken value instead of text + unit) }
 * opts: { label (the list's accessible name), cols (a fixed column count;
 *   default: as many as fit), variant: "grid" (boxes, default) | "compact"
 *   (borderless, label over value, a slot beside them: History, report),
 *   align: "end" (compact: right-aligned), cls (extra class of the list),
 *   count (mount: count the figures up), still, fmt(v, tile) (count-up
 *   formatter) }
 *
 * Toggletips (a tile's hint) follow WCAG 1.4.13: shown on hover and focus,
 * hoverable, dismissed with Escape until left; wired once for the document.
 */
(function () {
  "use strict";

  var T = function (zh, en) { return window.T ? window.T(zh, en) : en; };
  var Tf = function (zh, en, vars) {
    return T(zh, en).replace(/\{(\w+)\}/g, function (m, k) { return vars && k in vars ? vars[k] : m; });
  };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var ico = function (n) { return window.ekteIcon ? window.ekteIcon(n, {}) : ""; };
  var uid = 0;

  // ---- one tile ------------------------------------------------------------ //
  function hintHTML(t, p) {
    if (!t.hint) return "";
    var id = p + "-" + String(t.id).replace(/[^\w-]/g, "_");
    return '<span class="kh"><button type="button" class="khint" aria-describedby="' + id + '" aria-label="' +
      esc(Tf("关于：{name}", "About: {name}", { name: t.label })) + '">' + ico("info") + "</button>" +
      '<span class="ktip" role="tooltip" id="' + id + '">' + esc(t.hint) + "</span></span>";
  }
  function deltaHTML(t) {
    var d = t.delta;
    if (!d) return t.note ? '<span class="kd few">' + esc(t.note) + "</span>" : "";
    var cls = d.dir === "better" ? " good" : d.dir === "worse" ? " bad" : d.dir === "none" ? " few" : "";
    var word = d.dir === "better" ? " · " + T("变好", "better") : d.dir === "worse" ? " · " + T("变差", "worse") : "";
    var arrow = !d.sign ? "" : d.sign > 0 ? "▲ " : "▼ ";
    return '<span class="kd' + cls + '"><span aria-hidden="true">' + arrow + "</span>" +
      (d.sr ? '<span class="sr-only">' + esc(d.sr) + " </span>" : "") + esc(d.text) + esc(word) + "</span>";
  }
  function valueHTML(t) {
    if (t.na) return '<span class="kv" aria-hidden="true">' + esc(T("不适用", "n/a")) + "</span>";
    var text = t.text == null || t.text === "" ? "—" : String(t.text);
    var none = text === "—";
    var shown = esc(text) + (t.unit && !none ? "<small>" + esc(t.unit) + "</small>" : "");
    var spoken = t.sr != null ? t.sr : none ? T("无数据", "no data") : text + (t.unit ? " " + t.unit : "");
    // the figure counts up (aria-hidden); assistive tech reads only the final value
    return '<span class="kv' + (none ? " none" : "") + '"><span aria-hidden="true" data-kv="' + esc(t.id) + '">' + shown +
      '</span><span class="sr-only">' + esc(spoken) + "</span></span>";
  }
  function inner(t, p) {
    var head = '<span class="khead"><span class="kl">' + esc(t.label) + "</span>" + hintHTML(t, p) + "</span>";
    var caption = t.na ? t.naText || T("此接口类型不测量此项", "Not measured on this surface") : t.caption;
    return (t.slot ? '<span class="kslot">' + t.slot + "</span>" : "") + head + valueHTML(t) +
      (t.na ? "" : deltaHTML(t)) + (caption ? '<span class="kc">' + esc(caption) + "</span>" : "");
  }
  function tileClass(t, prev) {
    return "kpi" + (t.na ? " na" : "") + (prev && t.group !== prev.group ? " sep" : "") +
      (t.family ? " f-" + t.family : "") + (t.slot ? " slotted" : "");
  }
  function tileHTML(t, prev, p) {
    return '<li class="' + esc(tileClass(t, prev)) + '" data-id="' + esc(t.id) + '"' +
      (t.faded && !t.na ? ' aria-describedby="' + esc(t.faded) + '"' : "") + ">" + inner(t, p) + "</li>";
  }
  function listClass(opts) {
    var v = opts.variant === "compact" ? " compact" : "";
    return "kpis" + v + (opts.cols ? " cols" : "") + (opts.align === "end" ? " end" : "") + (opts.cls ? " " + opts.cls : "");
  }
  // opts.idp: the prefix of the list's element ids (default: a new one)
  function html(tiles, opts) {
    opts = opts || {};
    var p = opts.idp || "kh" + ++uid;
    return '<ul class="' + esc(listClass(opts)) + '"' + (opts.cols ? ' style="--kpi-cols:' + Number(opts.cols) + '"' : "") +
      (opts.label ? ' aria-label="' + esc(opts.label) + '"' : "") + ">" +
      tiles.map(function (t, i) { return tileHTML(t, tiles[i - 1], p); }).join("") + "</ul>";
  }

  // ---- in place ------------------------------------------------------------ //
  function shape(tiles, opts) {
    return listClass(opts) + "|" + tiles.map(function (t, i) { return t.id + ":" + tileClass(t, tiles[i - 1]) + ":" + (t.faded || ""); }).join(",");
  }
  function mount(box, tiles, opts) {
    opts = Object.assign({}, opts || {});
    opts.idp = opts.idp || "kh" + ++uid;
    var h = { el: null, key: null, update: update };
    function draw(list) {
      box.innerHTML = html(list, opts);
      h.el = box.firstElementChild;
      h.key = shape(list, opts);
      Array.prototype.forEach.call(h.el.children, function (li, i) { li._kpi = inner(list[i], opts.idp); });
    }
    function update(list) {
      if (!h.el || h.el.parentNode !== box || !h.el.children || h.key !== shape(list, opts)) draw(list);
      else {
        // the same tiles: each one's content replaced only where it changed;
        // a tile holding the focus keeps its head (the hint button)
        var items = h.el.children;
        list.forEach(function (t, i) {
          var li = items[i], fresh = inner(t, opts.idp);
          if (li._kpi === fresh) return;
          li._kpi = fresh;
          if (!li.contains(document.activeElement)) { li.innerHTML = fresh; return; }
          var tmp = document.createElement("li");
          tmp.innerHTML = fresh;
          Array.prototype.forEach.call(li.children, function (c, k) {
            if (!c.contains(document.activeElement) && tmp.children[k]) c.outerHTML = tmp.children[k].outerHTML;
          });
        });
        if (opts.label) h.el.setAttribute("aria-label", opts.label);
      }
      if (opts.count) count(box, list, opts);
    }
    update(tiles);
    return h;
  }

  // ---- counting up --------------------------------------------------------- //
  // the figures shown before: per opts.key (a box drawn anew keeps them), else per box
  var SHOWN = typeof WeakMap === "function" ? new WeakMap() : null, KEYED = {};
  function count(box, tiles, opts) {
    opts = opts || {};
    if (!SHOWN || !box) return;
    var shown = (opts.key ? KEYED[opts.key] : SHOWN.get(box)) || {}, now = {}, items = [];
    tiles.forEach(function (t) {
      if (t.na || typeof t.value !== "number" || !isFinite(t.value)) return;
      var el = box.querySelector('[data-kv="' + cssEsc(t.id) + '"]');
      if (!el) return;
      var kind = t.kind || "";
      now[t.id] = { v: t.value, kind: kind };
      var was = shown[t.id], from = was && was.kind === kind ? was.v : 0;
      if (from !== t.value) items.push({ el: el, from: from, to: t.value, tile: t });
    });
    if (opts.key) KEYED[opts.key] = now;
    else SHOWN.set(box, now);
    var M = window.EkteMotion;
    if (opts.still || !M || !items.length || !opts.fmt) return;
    M.count(items, function (v, it) { return opts.fmt(v, it.tile); });
  }
  function cssEsc(s) { return window.CSS && CSS.escape ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, "\\$&"); }

  // ---- a server tile (ekte.web.metrics.tile) ------------------------------- //
  // ctx: { label(key) -> text, fmt(v, format) -> text, fmtDelta(d, format) ->
  //   text, previous (the answer compares with a previous range), runs (the
  //   runs of the range: "data from n of runs"), fewId (the note a faded
  //   tile is described by), caption(t) -> text (an extra line), hint(t) ->
  //   text (the toggletip; default the pooled rate's hint) }
  function fromServer(t, ctx) {
    var label = ctx.label(t.label_key);
    var out = { id: t.id, label: label, group: t.group || 0, kind: t.format };
    if (!t.applies) { out.na = true; return out; }
    out.value = t.value;
    out.text = ctx.fmt(t.value, t.format);
    out.family = ctx.family ? t.family : null;
    var hint = ctx.hint ? ctx.hint(t) : t.hint_key ? ctx.label(t.hint_key) + ". " +
      T("只计中转站的失败；网络和 ekte 自身的失败不计入。", "Relay failures only; network and ekte failures are excluded.") : "";
    if (hint) out.hint = hint;
    if (ctx.previous) {
      if (t.delta == null) out.note = T("上一周期无数据", "No data in the previous period");
      else {
        out.delta = { text: ctx.fmtDelta(t.delta, t.format), sign: t.delta > 0 ? 1 : t.delta < 0 ? -1 : 0, dir: t.direction,
          sr: t.trend_key ? ctx.label(t.trend_key) : "" };
        if (t.direction === "none" && ctx.fewId) out.faded = ctx.fewId;
      }
    }
    var cov = "";
    if (t.n === 0) cov = T("这些检测均未测得此项", "Not measured in these runs");
    else if (t.n != null && ctx.runs != null && t.n < ctx.runs) {
      cov = Tf("{n} / {runs} 次检测有此数据", "Data from {n} of {runs} runs", { n: t.n, runs: ctx.runs });
    }
    var extra = ctx.caption ? ctx.caption(t) : "";
    out.caption = [extra, cov].filter(Boolean).join(" · ");
    return out;
  }

  // ---- toggletips: one delegated wiring for the document -------------------- //
  // a tip stays while the pointer or focus is on it; Escape hides every
  // shown one (also one shown by hover only) until it is left
  if (typeof document !== "undefined" && document && document.addEventListener) {
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      Array.prototype.forEach.call(document.querySelectorAll(".kpi .kh"), function (k) {
        if (k.matches(":hover") || k.contains(document.activeElement)) k.classList.add("off");
      });
    });
    ["mouseout", "focusout"].forEach(function (type) {
      document.addEventListener(type, function (ev) {
        var k = ev.target && ev.target.closest && ev.target.closest(".kpi .kh");
        if (k && !k.contains(ev.relatedTarget)) k.classList.remove("off");
      });
    });
  }

  window.EkteKpi = { html: html, mount: mount, count: count, fromServer: fromServer, esc: esc };
})();
