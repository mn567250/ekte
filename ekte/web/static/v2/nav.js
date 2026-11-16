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
 *
 * On phones (issue 231) the header is two rows: the logo with the version,
 * one "Display settings" button and the accessibility link, then the section
 * links. The button (a disclosure: aria-expanded / aria-controls) opens the
 * theme, motion and language switches in a popover below it; Escape or a
 * click outside closes it and Escape returns the focus to the button. On
 * wider screens the button is hidden and the switches sit in the row. The
 * switches come right after the button in the DOM, so reading and Tab order
 * match what is shown (BITV 9.1.3.2 / 9.2.4.3).
 *
 * Rows that scroll sideways (the section links, a primary tab bar of five or
 * more tabs) fade at the edge that hides more (EkteScroll.fade: .fl / .fr),
 * so hidden items are visible as such.
 *
 * The first item of .tail is the running version (v0.34.0, or v0.34.0+dev in
 * a source checkout), a link to its changelog. The server writes both onto the
 * header as data-version / data-changelog (ekte/web/changelog.py); without
 * them there is no link. The accessible name is the visible version plus a
 * visually hidden "Changelog" (BITV 9.2.5.3 label in name).
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
    var version = header.getAttribute("data-version");
    var changelog = header.getAttribute("data-changelog");
    var versionLink = version && changelog
      ? '<a class="ver" href="' + esc(changelog) + '" title="Changelog" data-en-title="Changelog">' +
        esc(version) + ' <span class="sr-only" data-en="Changelog">Changelog</span></a>'
      : "";
    header.innerHTML =
      '<a class="skip-link" href="#main" data-en="Skip to main content">Skip to main content</a>' +
      '<a class="logo" href="/" aria-label="ekte"><span class="b">' + ico("logo", { size: 18 }) +
      "</span><span>ekte<b>.</b></span></a>" +
      '<div class="tail">' + versionLink +
      '<button type="button" class="zset" aria-expanded="false" aria-controls="zset" aria-label="Display settings" title="Display settings"' +
      ' data-en-aria-label="Display settings" data-en-title="Display settings">' + ico("sliders", { size: 16 }) + "</button>" +
      '<div class="zset-panel" id="zset" role="group" aria-label="Display settings" data-en-aria-label="Display settings">' +
      '<select class="theme-sel" aria-label="Theme" title="Theme" data-en-aria-label="Theme" data-en-title="Theme">' +
      '<option value="system" data-en="Auto theme">Auto theme</option>' +
      '<option value="light" data-en="Light">Light</option>' +
      '<option value="dark" data-en="Dark">Dark</option></select>' +
      '<select class="motion-sel" aria-label="Motion" title="Motion" data-en-aria-label="Motion" data-en-title="Motion">' +
      '<option value="on" data-en="Motion on">Motion on</option>' +
      '<option value="off" data-en="Motion off">Motion off</option></select>' +
      '<select class="lang-sel" aria-label="Language" title="Language" data-en-aria-label="Language" data-en-title="Language"></select>' +
      "</div>" +
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
    settings(header);
    fade(header.querySelector(".links"));
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

  // The display settings popover (phones): a disclosure button and its panel.
  function settings(header) {
    var btn = header.querySelector(".zset"), panel = header.querySelector(".zset-panel");
    if (!btn || !panel) return;
    function set(open, focusBtn) {
      btn.setAttribute("aria-expanded", String(open));
      panel.classList.toggle("open", open);
      if (!open && focusBtn) btn.focus();
    }
    btn.addEventListener("click", function () { set(btn.getAttribute("aria-expanded") !== "true"); });
    header.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && btn.getAttribute("aria-expanded") === "true") {
        ev.preventDefault();
        set(false, panel.contains(document.activeElement) || document.activeElement === btn);
      }
    });
    document.addEventListener("click", function (ev) {
      if (btn.getAttribute("aria-expanded") === "true" && !btn.contains(ev.target) && !panel.contains(ev.target)) set(false);
    });
    // the focus leaving both (Tab past the last switch) closes it
    header.addEventListener("focusout", function (ev) {
      var to = ev.relatedTarget;
      if (to && !btn.contains(to) && !panel.contains(to) && btn.getAttribute("aria-expanded") === "true") set(false);
    });
  }

  // A row that scrolls sideways fades at each edge that hides more of it
  // (.fl: more to the left, .fr: more to the right; ekte.css draws the fade).
  function fade(row) {
    if (!row || row._fade) return;
    row._fade = true;
    row.classList.add("scroll-x");
    var tick = function () {
      var max = row.scrollWidth - row.clientWidth;
      row.classList.toggle("fl", max > 1 && row.scrollLeft > 1);
      row.classList.toggle("fr", max > 1 && row.scrollLeft < max - 1);
    };
    row.addEventListener("scroll", tick, { passive: true });
    if (window.ResizeObserver) new window.ResizeObserver(tick).observe(row);
    else window.addEventListener("resize", tick);
    if (window.requestAnimationFrame) window.requestAnimationFrame(tick);
    else tick();
  }
  window.EkteScroll = { fade: fade };

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
    // a primary tab bar of five or more tabs scrolls sideways on phones
    var bars = document.querySelectorAll('.tabs:not(.sub)[role="tablist"]');
    for (var t = 0; t < bars.length; t++) if (bars[t].querySelectorAll('[role="tab"]').length >= 5) fade(bars[t]);
    if (window.EKTE_LANG) window.EKTE_LANG.apply(document);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addFooters);
  else addFooters();
  // If lang.js already booted (script loaded late), translate the new markup.
  if (window.EKTE_LANG && document.readyState !== "loading") window.EKTE_LANG.apply(document);
})();
