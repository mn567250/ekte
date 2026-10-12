/* zing web UI v2 — the collapsible filter panel shared by History and
 * Analytics (styles: filterpanel.css).
 *
 * The page owns its filters and their fields; this owns the frame around
 * them, rendered into an empty <section class="card filters" id="filters">:
 *
 *   .ftop > button#ftog.disclosure[aria-expanded][aria-controls=fbody]
 *             icon, title, badge #factive "N active" (hidden at 0)
 *   p#fsum.fsum     one line naming the active filters ("Last 30 days ·
 *                   standard · Streaming · Example Relay"), shown while the
 *                   panel is closed and described by the toggle, so a shared
 *                   link says what it filters without opening the panel
 *   div#fbody.fbody the page's fields, hidden while closed
 *   div.ffoot       the page's always-visible note (e.g. "Showing 3 of 9")
 *                   and button#freset "Reset filters" (hidden at 0 active)
 *
 * ZingFilterPanel.create(section, opts):
 *   opts.label()     the section's accessible name (text)
 *   opts.title()     the toggle's text
 *   opts.icon        icon name on the toggle (default "search")
 *   opts.storeKey    localStorage key remembering open / closed (per viewer,
 *                    may be missing or throw); closed by default
 *   opts.open        true: start open whatever is remembered (e.g. a link
 *                    that carried filters)
 *   opts.onReset()   "Reset filters": reset the page's filters and re-render;
 *                    focus then goes to the first field, or to the toggle
 *                    while the panel is closed
 * Returns:
 *   render(p)        (re)builds the panel; p = { body, foot (HTML), count,
 *                    summary: [texts] }; focus stays on the field (data-f /
 *                    data-range / id) or toggle that had it
 *   sync(p)          p = { count, summary }: badge, summary and reset only
 *   setOpen(open), isOpen(), focusStart()
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function Tf(zh, en, vars) {
    return T(zh, en).replace(/\{(\w+)\}/g, function (m, k) { return vars && k in vars ? vars[k] : m; });
  }
  var ico = function (n) { return window.zingIcon ? window.zingIcon(n, {}) : ""; };
  // the attributes a field is found again by after a re-render
  var KEYS = ["data-f", "data-range", "id"];

  function create(section, opts) {
    opts = opts || {};
    var open = opts.open === true;
    if (!open) {
      try { open = JSON.parse(localStorage.getItem(opts.storeKey) || "false") === true; } catch (e) { /* closed */ }
    }
    var last = { count: 0, summary: [] };
    var $ = function (id) { return section.querySelector("#" + id); };

    function badgeText(n) { return Tf("{n} 项生效", "{n} active", { n: n }); }

    function sync(p) {
      last = { count: p.count || 0, summary: (p.summary || []).filter(Boolean) };
      var fa = $("factive"), rb = $("freset"), fs = $("fsum"), tog = $("ftog");
      if (fa) { fa.hidden = !last.count; fa.textContent = badgeText(last.count); }
      if (rb) rb.hidden = !last.count;
      if (fs) {
        fs.textContent = last.summary.join(" · ");
        fs.hidden = open || !last.summary.length;
      }
      // closed: the toggle's description says what is filtered
      if (tog) {
        if (fs && !fs.hidden) tog.setAttribute("aria-describedby", "fsum");
        else tog.removeAttribute("aria-describedby");
      }
    }

    function render(p) {
      var ae = document.activeElement, focus = null;
      if (ae && section.contains(ae)) {
        KEYS.some(function (k) { var v = ae.getAttribute(k); if (v) focus = [k, v]; return !!v; });
      }
      section.setAttribute("aria-label", opts.label());
      section.hidden = false;
      section.innerHTML = '<div class="ftop"><button type="button" class="disclosure" id="ftog" aria-expanded="' + open + '" aria-controls="fbody">' +
        '<span class="t">' + ico(opts.icon || "search") + "<span>" + esc(opts.title()) + "</span>" +
        '<span class="badge sky" id="factive" hidden></span></span>' +
        '<span class="cv" aria-hidden="true">' + ico("chevronDown") + "</span></button></div>" +
        '<p class="fsum" id="fsum" hidden></p>' +
        '<div class="fbody" id="fbody"' + (open ? "" : " hidden") + ">" + (p.body || "") + "</div>" +
        '<div class="ffoot">' + (p.foot || "<span></span>") +
        '<button type="button" class="linkbtn" id="freset" hidden>' + esc(T("重置筛选", "Reset filters")) + "</button></div>";
      sync(p);
      if (focus) {
        var el = focus[0] === "id" ? $(focus[1]) : section.querySelector("[" + focus[0] + '="' + CSS.escape(focus[1]) + '"]');
        if (el) el.focus();
      }
    }

    function setOpen(v) {
      open = !!v;
      try { localStorage.setItem(opts.storeKey, JSON.stringify(open)); } catch (e) { /* ignore */ }
      var b = $("ftog"), body = $("fbody");
      if (b) b.setAttribute("aria-expanded", String(open));
      if (body) body.hidden = !open;
      sync(last);
    }

    // the first field while open, else the toggle
    function focusStart() {
      var el = open ? section.querySelector("#fbody input, #fbody select, #fbody button") : $("ftog");
      if (el) el.focus();
    }

    section.addEventListener("click", function (ev) {
      if (ev.target.closest("#ftog")) return setOpen(!open);
      if (ev.target.closest("#freset")) {
        if (opts.onReset) opts.onReset();
        focusStart();
      }
    });

    return { render: render, sync: sync, setOpen: setOpen, isOpen: function () { return open; }, focusStart: focusStart };
  }

  window.ZingFilterPanel = { create: create };
})();
