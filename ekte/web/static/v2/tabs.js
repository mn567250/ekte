/* zing web UI v2 — WAI-ARIA tabs with automatic activation, shared by the
 * Tools, Knowledge and Analytics pages.
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
 *   opts.writeHash       false: leave the hash alone (a page that keeps more
 *                        state in it, e.g. Analytics' #tab=…&range=…, writes
 *                        it itself from onSelect)
 * Returns { select(name, focus), current(), setDisabled(name, bool) }.
 *
 * setDisabled(name, true) marks a tab aria-disabled="true" (e.g. "Running"
 * while nothing runs): clicks on it are ignored, ←/→/Home/End skip it, and
 * if it was selected the first enabled tab is selected instead (without
 * moving focus). A disabled tab can also be authored with aria-disabled="true"
 * in the markup; an initial hash naming a disabled tab falls back to the
 * first enabled tab, and that tab is selected after all if it is enabled
 * before the user picks another one (a deep link to a tab that only enables
 * once data has loaded).
 */
(function () {
  "use strict";

  function init(list, opts) {
    opts = opts || {};
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    var names = tabs.map(function (t) { return t.id.replace(/^tab-/, ""); });
    var cur = null;
    var wanted = null; // a disabled tab the initial hash asked for

    function nameFor(hash) {
      hash = String(hash || "").replace(/^#/, "");
      if (!hash) return names[0];
      var n = opts.fromHash ? opts.fromHash(hash) : hash;
      return names.indexOf(n) >= 0 ? n : null;
    }

    function isOff(i) { return tabs[i].getAttribute("aria-disabled") === "true"; }
    function firstOn() {
      for (var i = 0; i < tabs.length; i++) if (!isOff(i)) return i;
      return 0;
    }
    // the next enabled tab from i in direction d (wraps); i itself if none
    function step(i, d) {
      for (var k = 1; k <= tabs.length; k++) {
        var j = ((i + d * k) % tabs.length + tabs.length) % tabs.length;
        if (!isOff(j)) return j;
      }
      return i;
    }

    function select(name, focus, keepHash) {
      var i = names.indexOf(name);
      if (i < 0 || isOff(i)) return;
      wanted = null;
      tabs.forEach(function (t, j) {
        var on = j === i;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tabs[i].focus();
      cur = name;
      if (!keepHash && opts.writeHash !== false) {
        try {
          history.replaceState(null, "", i === 0 ? location.pathname + location.search : "#" + name);
        } catch (e) { /* file:// or sandboxed */ }
      }
      if (opts.onSelect) opts.onSelect(name);
    }

    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { if (!isOff(i)) select(names[i], false); });
      t.addEventListener("keydown", function (e) {
        var n = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") n = step(i, 1);
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = step(i, -1);
        else if (e.key === "Home") n = firstOn();
        else if (e.key === "End") n = step(0, -1);
        if (n !== null) { e.preventDefault(); if (!isOff(n)) select(names[n], true); }
      });
    });
    // a link to #NAME on the same page (or the back button) selects that tab;
    // a disabled one is selected once it is enabled (as for the initial hash)
    window.addEventListener("hashchange", function () {
      var n = nameFor(location.hash);
      if (!n) return;
      if (isOff(names.indexOf(n))) wanted = n;
      else select(n, false, true);
    });

    function setDisabled(name, off) {
      var i = names.indexOf(name);
      if (i < 0) return;
      if (off) tabs[i].setAttribute("aria-disabled", "true");
      else tabs[i].removeAttribute("aria-disabled");
      if (!off && wanted === name) select(name, false, true);
      else if (off && cur === name) {
        var j = firstOn();
        if (j !== i) select(names[j], false);
      }
    }

    var first = nameFor(location.hash);
    if (!first || isOff(names.indexOf(first))) {
      if (first) wanted = first;
      first = names[firstOn()];
    }
    var keep = wanted;
    select(first, false, true);
    wanted = keep;
    return { select: select, current: function () { return cur; }, setDisabled: setDisabled };
  }

  window.ZingTabs = { init: init };
})();
