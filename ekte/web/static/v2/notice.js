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
 *                data-note-act="<act>"; the page handles their clicks,
 *       role:    optional; false: no role at all, for a notice the page
 *                announces itself (History's new-runs notice says it once
 *                through its own live region) }
 *
 * The level sets the colour and the icon; the words say the same, so colour
 * never carries the meaning alone. "error" is the same as "critical"; an
 * unknown level is "info". The role follows the importance (roleFor): a
 * critical notice is role="alert" (announced at once), any other
 * role="status" (announced politely). Showing the same notice again changes
 * nothing, so a screen reader does not hear it twice: a page that redraws
 * its notice on every poll announces it only when it says something new.
 *
 *   EkteNotice.callout(level, html, o)  the same Callout, inline size, as
 *     markup for a message inside a card or form (see below)
 *   EkteNotice.empty(text, o)  the EmptyState as markup (see below)
 *
 * Pure helpers (tested under node): levelOf(level), roleFor(n).
 */
(function () {
  "use strict";

  var ICON = { info: "info", success: "check", warning: "warning", critical: "warning", neutral: "info" };

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

  // the level drawn: "error" is critical, an unknown level info
  function levelOf(level) {
    if (level === "error") return "critical";
    return Object.prototype.hasOwnProperty.call(ICON, level) ? level : "info";
  }
  // the notice's role: alert for critical, status otherwise, none with role: false
  function roleFor(n) {
    if (!n || n.role === false) return null;
    return levelOf(n.level) === "critical" ? "alert" : "status";
  }

  function show(el, n) {
    if (!el) return;
    if (!n) {
      el.hidden = true;
      el.removeAttribute("data-sig");
      el.innerHTML = "";
      return;
    }
    var level = levelOf(n.level), role = roleFor(n);
    var ico = window.ekteIcon ? window.ekteIcon(n.icon || ICON[level], { size: 18 }) : "";
    var html = '<span class="ico">' + ico + "</span>" +
      '<div class="txt"><b>' + esc(n.title) + "</b>" + (n.detail ? ' <span class="meta">' + seg(n.detail) + "</span>" : "") +
      (n.items && n.items.length ? "<ul>" + n.items.map(function (i) { return "<li>" + seg(i) + "</li>"; }).join("") + "</ul>" : "") +
      "</div>" +
      (n.actions && n.actions.length ? '<div class="act">' + n.actions.map(function (a) {
        return '<button type="button" class="btn sm' + (a.primary ? " pri" : "") + '" data-note-act="' + esc(a.act) + '">' + esc(a.label) + "</button>";
      }).join("") + "</div>" : "");
    var sig = level + "|" + (role || "") + "|" + html;
    if (el.getAttribute("data-sig") === sig && !el.hidden) return;
    el.setAttribute("data-sig", sig);
    el.className = "znote " + level;
    if (role) el.setAttribute("role", role);
    else el.removeAttribute("role");
    el.innerHTML = html;
    el.hidden = false;
  }

  // The same Callout in its inline size, as markup, for a message inside a
  // card or a form (a load failure, a form error, a hint that needs action):
  //   EkteNotice.callout(level, html, { role, icon })
  // html is already escaped markup; role: "alert" / "status" (default: by
  // level, as roleFor), or false when the element it goes into is the live
  // region. A page draws no message box of its own (issue 226);
  // tests/test_web_callouts.py keeps it so.
  function callout(level, html, o) {
    o = o || {};
    level = levelOf(level);
    var role = o.role === false ? null : o.role || (level === "critical" ? "alert" : null);
    var ico = window.ekteIcon ? window.ekteIcon(o.icon || ICON[level], { size: 16 }) : "";
    return '<div class="znote inline ' + level + '"' + (role ? ' role="' + role + '"' : "") + '>' +
      '<span class="ico">' + ico + '</span><div class="txt">' + html + "</div></div>";
  }

  // The EmptyState (ekte.css .empty, issue 227) as markup: an icon, one
  // sentence (text, escaped here) and an optional action (html):
  //   EkteNotice.empty(text, { icon, action, html })
  // o.html: the sentence is already markup.
  function empty(text, o) {
    o = o || {};
    var ico = window.ekteIcon ? window.ekteIcon(o.icon || "info", { size: 28 }) : "";
    return '<div class="empty"><span class="ico" aria-hidden="true">' + ico + "</span><p>" +
      (o.html ? text : esc(text)) + "</p>" + (o.action || "") + "</div>";
  }

  window.EkteNotice = { show: show, levelOf: levelOf, roleFor: roleFor, callout: callout, empty: empty };
})();
