/* ekte web UI v2 — the one shared header.
 *
 * Every v2 page has, as the first thing in <div class="wrap">:
 *   <header class="znav" data-page="audit|history|analytics|monitors|kb"></header>
 * and loads, right after /icons.js and before its own page script:
 *   <script src="/static/nav.js"></script>
 * The script also appends the one shared page footer (.zdisc) to .wrap: the
 * two disclaimers every page carries, "all local" and "black box, do not
 * blame". There is no disclaimer above the hero title on any page.
 * The header starts with a skip link to the page's <main id="main"
 * tabindex="-1"> (BITV 9.2.4.1 bypass blocks), visible only on focus.
 *
 * The markup follows the i18n convention of the whole UI (English inline,
 * the same English in data-en as the lookup key), so lang.js translates it at
 * boot and on every switch;
 * the language <select class="lang-sel"> is filled by lang.js too. The theme
 * <select class="theme-sel"> is driven by theme.js (loaded in <head>).
 *
 * The last item of .tail, next to the language switch, is an icon-only link
 * to the accessibility conformance report (/accessibility), so it sits in
 * the same place on every page (BITV 9.3.2.3). Its accessible name comes from
 * aria-label (the icon is aria-hidden), its tooltip from title.
 */
(function () {
  "use strict";

  var LINKS = [
    // [page id, href, icon, label (English; the key into the locale strings)]
    ["audit", "/", "bolt", "Audit"],
    ["monitors", "/watches", "bell", "Monitors"],
    ["history", "/history", "chart", "History"],
    ["analytics", "/analytics", "bars", "Analytics"],
    ["kb", "/kb", "book", "Knowledge"],
  ];

  // English; the key into the locale strings
  var DISC_LOCAL = 'All local: audits run from your own machine, and your API keys never leave it.';
  var DISC_BOX = 'A black box: ekte reports reproducible evidence of deviation, not proof of fraud. Do not blame a vendor for a single run.';

  function ico(name, opts) {
    return window.ekteIcon ? window.ekteIcon(name, opts || {}) : "";
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function render(header) {
    var page = header.getAttribute("data-page") || "";
    var links = LINKS.map(function (l) {
      var cur = l[0] === page ? ' aria-current="page"' : "";
      return (
        '<a href="' + l[1] + '"' + cur + ">" + ico(l[2]) +
        '<span data-en="' + esc(l[3]) + '">' + esc(l[3]) + "</span></a>"
      );
    }).join("");
    header.innerHTML =
      '<a class="skip-link" href="#main" data-en="Skip to main content">Skip to main content</a>' +
      '<a class="logo" href="/" aria-label="ekte"><span class="b">' + ico("logo", { size: 18 }) +
      "</span><span>ekte<b>.</b></span></a>" +
      '<div class="tail">' +
      '<select class="theme-sel" aria-label="Theme" title="Theme" data-en-aria-label="Theme" data-en-title="Theme">' +
      '<option value="system" data-en="Auto theme">Auto theme</option>' +
      '<option value="light" data-en="Light">Light</option>' +
      '<option value="dark" data-en="Dark">Dark</option></select>' +
      '<select class="motion-sel" aria-label="Motion" title="Motion" data-en-aria-label="Motion" data-en-title="Motion">' +
      '<option value="on" data-en="Motion on">Motion on</option>' +
      '<option value="off" data-en="Motion off">Motion off</option></select>' +
      '<select class="lang-sel" aria-label="Language" title="Language" data-en-aria-label="Language" data-en-title="Language"></select>' +
      '<a class="a11y" href="/accessibility"' + (page === "a11y" ? ' aria-current="page"' : "") +
      ' aria-label="Accessibility" title="Accessibility" data-en-aria-label="Accessibility" data-en-title="Accessibility">' +
      ico("a11y", { size: 16 }) + "</a>" +
      "</div>" +
      '<nav class="links" aria-label="Main navigation" data-en-aria-label="Main navigation">' + links + "</nav>";
    var ts = header.querySelector("select.theme-sel");
    if (window.EKTE_THEME) {
      ts.value = window.EKTE_THEME.get();
      ts.addEventListener("change", function () { window.EKTE_THEME.set(ts.value); });
    } else {
      ts.remove(); // page without theme.js
    }
    var ms = header.querySelector("select.motion-sel");
    if (window.EKTE_MOTION) {
      ms.value = window.EKTE_MOTION.get();
      ms.addEventListener("change", function () { window.EKTE_MOTION.set(ms.value); });
    } else {
      ms.remove();
    }
    // keep the active tab visible when the link row scrolls (phones). Scroll
    // the row itself: scrollIntoView() would also move Chromium's sequential
    // focus starting point to the active link, so the first Tab would jump
    // past the skip link. Not measured here: reading scrollWidth while the
    // page is still being parsed forces a synchronous layout of the half-built
    // page. Instead wait for DOMContentLoaded (lang.js, loaded earlier, has
    // translated the labels by then) and measure in the next animation frame,
    // with the layout the browser computes anyway. rAF runs while the page is
    // still visibility:hidden, so the row is scrolled before it is painted.
    var active = header.querySelector('[aria-current="page"]');
    if (!active) return;
    var fit = function () { centerActive(active); };
    var later = function () {
      if (window.requestAnimationFrame) window.requestAnimationFrame(fit);
      else fit();
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", later);
    else later();
  }

  function centerActive(active) {
    var row = active.parentNode;
    if (row && row.scrollWidth > row.clientWidth) {
      row.scrollLeft = active.offsetLeft - row.offsetLeft - (row.clientWidth - active.offsetWidth) / 2;
    }
  }

  // The shared footer: after <main>, as the last child of .wrap.
  function footer(header) {
    var wrap = header.parentNode;
    if (!wrap || wrap.querySelector("footer.zdisc")) return;
    var f = document.createElement("footer");
    f.className = "zdisc";
    f.innerHTML =
      '<p data-en="' + esc(DISC_LOCAL) + '">' + esc(DISC_LOCAL) + "</p>" +
      '<p data-en="' + esc(DISC_BOX) + '">' + esc(DISC_BOX) + "</p>";
    wrap.appendChild(f);
  }

  var headers = document.querySelectorAll("header.znav");
  for (var i = 0; i < headers.length; i++) render(headers[i]);
  // Appended once the page is parsed, so it lands after <main>, not before it.
  function addFooters() {
    for (var k = 0; k < headers.length; k++) footer(headers[k]);
    if (window.EKTE_LANG) window.EKTE_LANG.apply(document);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addFooters);
  else addFooters();
  // If lang.js already booted (script loaded late), translate the new markup.
  if (window.EKTE_LANG && document.readyState !== "loading") window.EKTE_LANG.apply(document);
})();
