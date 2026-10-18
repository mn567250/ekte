/* zing web UI v2 — light / dark theme choice.
 *
 * Load in <head>, right after /lang.js, so the stored choice is applied before
 * the first paint (no flash):
 *   <script src="/v2/static/theme.js"></script>
 * zing.css does the rest: data-theme="light" / "dark" on <html> forces a theme,
 * no attribute follows prefers-color-scheme. A page may ship its own default
 * (the console is <html data-theme="dark">); "system" keeps that default.
 *
 * The choice ("system" | "light" | "dark") is a per-browser convenience in
 * localStorage, shared by every v2 page and kept in sync across open tabs.
 * nav.js renders the <select class="theme-sel"> and calls ZING_THEME.set.
 *
 * Chart motion ("on" | "off", ZING_MOTION) works the same way: "off" sets
 * data-motion="off" on <html>, which chartmotion.js / .css honour (as they do
 * prefers-reduced-motion). nav.js renders its <select class="motion-sel">.
 */
(function () {
  "use strict";

  var KEY = "zing.v2.theme";
  var root = document.documentElement;
  var pageDefault = root.getAttribute("data-theme") || "";
  var CHOICES = ["system", "light", "dark"];

  function get() {
    try {
      var v = localStorage.getItem(KEY);
      return CHOICES.indexOf(v) >= 0 ? v : "system";
    } catch (e) {
      return "system";
    }
  }

  function apply(choice) {
    var t = choice === "light" || choice === "dark" ? choice : pageDefault;
    if (t) root.setAttribute("data-theme", t);
    else root.removeAttribute("data-theme");
    var sw = document.querySelectorAll("select.theme-sel");
    for (var i = 0; i < sw.length; i++) sw[i].value = choice;
  }

  function set(choice) {
    choice = CHOICES.indexOf(choice) >= 0 ? choice : "system";
    try {
      localStorage.setItem(KEY, choice);
    } catch (e) {}
    apply(choice);
  }

  // another tab changed the theme
  window.addEventListener("storage", function (ev) {
    if (ev.key === KEY) apply(get());
  });

  window.ZING_THEME = { get: get, set: set, apply: function () { apply(get()); } };
  apply(get());

  // ---- chart motion: "on" (default; reduced motion still wins) | "off" ----
  var MKEY = "zing.v2.motion";
  function mget() {
    try { return localStorage.getItem(MKEY) === "off" ? "off" : "on"; } catch (e) { return "on"; }
  }
  function mapply(choice) {
    if (choice === "off") root.setAttribute("data-motion", "off");
    else root.removeAttribute("data-motion");
    var sw = document.querySelectorAll("select.motion-sel");
    for (var i = 0; i < sw.length; i++) sw[i].value = choice;
  }
  function mset(choice) {
    choice = choice === "off" ? "off" : "on";
    try { localStorage.setItem(MKEY, choice); } catch (e) {}
    mapply(choice);
  }
  window.addEventListener("storage", function (ev) {
    if (ev.key === MKEY) mapply(mget());
  });
  window.ZING_MOTION = { get: mget, set: mset };
  mapply(mget());
})();
