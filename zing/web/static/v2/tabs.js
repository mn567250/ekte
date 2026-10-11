/* zing web UI v2 — WAI-ARIA tabs with automatic activation, shared by the
 * Tools and Knowledge pages.
 *
 * Markup (static, so lang.js translates it and nothing shifts at boot):
 *   <div class="tabs" role="tablist" aria-label="…">
 *     <button type="button" role="tab" id="tab-NAME" aria-controls="panel-NAME"
 *             aria-selected="true" tabindex="0">…</button> …
 *   </div>
 *   <section role="tabpanel" id="panel-NAME" aria-labelledby="tab-NAME" tabindex="0"> …
 *
 * ZingTabs.init(tablist, opts) wires the keyboard (←/→/↑/↓ move and select,
 * Home/End), keeps one tab in the tab order (roving tabindex), shows only the
 * selected panel, and mirrors the selection in the URL hash (#NAME; the first
 * tab has none) so a tab can be linked and survives a reload.
 *   opts.onSelect(name)  called after every selection, also the initial one
 *   opts.fromHash(hash)  maps a hash without "#" to a tab name (default: the
 *                        hash itself when such a tab exists); lets a page
 *                        accept deep links such as #add-relays
 * Returns { select(name, focus), current() }.
 */
(function () {
  "use strict";

  function init(list, opts) {
    opts = opts || {};
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    var names = tabs.map(function (t) { return t.id.replace(/^tab-/, ""); });
    var cur = null;

    function nameFor(hash) {
      hash = String(hash || "").replace(/^#/, "");
      if (!hash) return names[0];
      var n = opts.fromHash ? opts.fromHash(hash) : hash;
      return names.indexOf(n) >= 0 ? n : null;
    }

    function select(name, focus, keepHash) {
      var i = names.indexOf(name);
      if (i < 0) return;
      tabs.forEach(function (t, j) {
        var on = j === i;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tabs[i].focus();
      cur = name;
      if (!keepHash) {
        try {
          history.replaceState(null, "", i === 0 ? location.pathname + location.search : "#" + name);
        } catch (e) { /* file:// or sandboxed */ }
      }
      if (opts.onSelect) opts.onSelect(name);
    }

    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(names[i], false); });
      t.addEventListener("keydown", function (e) {
        var n = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % tabs.length;
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === "Home") n = 0;
        else if (e.key === "End") n = tabs.length - 1;
        if (n !== null) { e.preventDefault(); select(names[n], true); }
      });
    });
    // a link to #NAME on the same page (or the back button) selects that tab
    window.addEventListener("hashchange", function () {
      var n = nameFor(location.hash);
      if (n) select(n, false, true);
    });

    select(nameFor(location.hash) || names[0], false, true);
    return { select: select, current: function () { return cur; } };
  }

  window.ZingTabs = { init: init };
})();
