/* ekte web UI v2 — the one page notice (styles: .znote in ekte.css).
 *
 * Every page that has one keeps it in the same place, right under the hero:
 *   <div class="znote" id="note" hidden></div>
 * The page decides what it says; this draws it, so it looks and reads the
 * same everywhere:
 *
 *   EkteNotice.show(el, n)   n = null hides it, else
 *     { level: "info" | "success" | "warning" | "critical",
 *       icon:    optional icons.js name (default: by level),
 *       title:   text, bold,
 *       detail:  [segments]: a string is text, { code: s } a <code>,
 *       items:   optional [segments lists], a list under the detail (the
 *                lower-severity messages folded into this one),
 *       actions: optional [{ act, label, primary }]: buttons carrying
 *                data-note-act="<act>"; the page handles their clicks }
 *
 * The level sets the colour and the icon; the words say the same, so colour
 * never carries the meaning alone. A critical notice is role="alert", any
 * other role="status". Showing the same notice again changes nothing, so a
 * screen reader does not hear it twice.
 */
(function () {
  "use strict";

  var ICON = { info: "info", success: "check", warning: "warning", critical: "warning" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function seg(parts) {
    return (Array.isArray(parts) ? parts : [parts]).map(function (p) {
      return p && typeof p === "object" ? "<code>" + esc(p.code) + "</code>" : esc(p);
    }).join("");
  }

  function show(el, n) {
    if (!el) return;
    if (!n) {
      el.hidden = true;
      el.removeAttribute("data-sig");
      el.innerHTML = "";
      return;
    }
    var level = ICON[n.level] ? n.level : "info";
    var ico = window.ekteIcon ? window.ekteIcon(n.icon || ICON[level], { size: 18 }) : "";
    var html = '<span class="ico">' + ico + "</span>" +
      '<div class="txt"><b>' + esc(n.title) + "</b>" + (n.detail ? ' <span class="meta">' + seg(n.detail) + "</span>" : "") +
      (n.items && n.items.length ? "<ul>" + n.items.map(function (i) { return "<li>" + seg(i) + "</li>"; }).join("") + "</ul>" : "") +
      "</div>" +
      (n.actions && n.actions.length ? '<div class="act">' + n.actions.map(function (a) {
        return '<button type="button" class="btn sm' + (a.primary ? " pri" : "") + '" data-note-act="' + esc(a.act) + '">' + esc(a.label) + "</button>";
      }).join("") + "</div>" : "");
    var sig = level + "|" + html;
    if (el.getAttribute("data-sig") === sig && !el.hidden) return;
    el.setAttribute("data-sig", sig);
    el.className = "znote " + level;
    el.setAttribute("role", level === "critical" ? "alert" : "status");
    el.innerHTML = html;
    el.hidden = false;
  }

  window.EkteNotice = { show: show };
})();
