/* ekte web UI v2 — the one shared header.
 *
 * Every v2 page has, as the first thing in <div class="wrap">:
 *   <header class="znav" data-page="audit|history|analytics|monitors|kb"></header>
 * and loads, right after /icons.js and before its own page script:
 *   <script src="/v2/static/nav.js"></script>
 * The script also appends the one shared page footer (.zdisc) to .wrap: the
 * two disclaimers every page carries, "all local" and "black box, do not
 * blame". There is no disclaimer above the hero title on any page.
 * The header starts with a skip link to the page's <main id="main"
 * tabindex="-1"> (BITV 9.2.4.1 bypass blocks), visible only on focus.
 *
 * The markup follows the i18n convention of the whole UI (Chinese inline,
 * English in data-en), so lang.js translates it at boot and on every switch;
 * the language <select class="lang-sel"> is filled by lang.js too. The theme
 * <select class="theme-sel"> is driven by theme.js (loaded in <head>). The
 * "Classic UI" link goes back to the classic page (?ui=v1 — see server.py).
 *
 * The last item of .tail, next to the language switch, is an icon-only link
 * to the accessibility conformance report (/v2/accessibility), so it sits in
 * the same place on every page (BITV 9.3.2.3). Its accessible name comes from
 * aria-label (the icon is aria-hidden), its tooltip from title.
 */
(function () {
  "use strict";

  var LINKS = [
    // [page id, href, icon, zh, en]
    ["audit", "/v2/", "bolt", "检测", "Audit"],
    ["monitors", "/v2/watches", "bell", "监控", "Monitors"],
    ["history", "/v2/history", "chart", "检测历史", "History"],
    ["analytics", "/v2/analytics", "bars", "分析", "Analytics"],
    ["kb", "/v2/kb", "book", "知识库", "Knowledge"],
  ];

  // [zh, en]
  var DISC_LOCAL = ["全部在本地：检测从你自己的机器发起，API 密钥不会离开本机。", 'All local: audits run from your own machine, and your API keys never leave it.'];
  var DISC_BOX = ["黑盒：ekte 给出的是可复现的偏离证据，不是欺诈证明。请勿仅凭单次结果指责厂商。", 'A black box: ekte reports reproducible evidence of deviation, not proof of fraud. Do not blame a vendor for a single run.'];

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
        '<span data-en="' + esc(l[4]) + '">' + l[3] + "</span></a>"
      );
    }).join("");
    header.innerHTML =
      '<a class="skip-link" href="#main" data-en="Skip to main content">跳到主要内容</a>' +
      '<a class="logo" href="/v2/" aria-label="ekte"><span class="b">' + ico("logo", { size: 18 }) +
      "</span><span>ekte<b>.</b></span></a>" +
      '<div class="tail">' +
      '<a class="classic" href="?ui=v1" data-en="Classic UI">经典界面</a>' +
      '<select class="theme-sel" aria-label="主题" title="主题" data-en-aria-label="Theme" data-en-title="Theme">' +
      '<option value="system" data-en="Auto theme">跟随系统</option>' +
      '<option value="light" data-en="Light">浅色</option>' +
      '<option value="dark" data-en="Dark">深色</option></select>' +
      '<select class="motion-sel" aria-label="动画" title="动画" data-en-aria-label="Motion" data-en-title="Motion">' +
      '<option value="on" data-en="Motion on">动画开</option>' +
      '<option value="off" data-en="Motion off">动画关</option></select>' +
      '<select class="lang-sel" aria-label="语言" title="语言" data-en-aria-label="Language" data-en-title="Language"></select>' +
      '<a class="a11y" href="/v2/accessibility"' + (page === "a11y" ? ' aria-current="page"' : "") +
      ' aria-label="无障碍" title="无障碍" data-en-aria-label="Accessibility" data-en-title="Accessibility">' +
      ico("a11y", { size: 16 }) + "</a>" +
      "</div>" +
      '<nav class="links" aria-label="主导航" data-en-aria-label="Main navigation">' + links + "</nav>";
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
      '<p data-en="' + esc(DISC_LOCAL[1]) + '">' + DISC_LOCAL[0] + "</p>" +
      '<p data-en="' + esc(DISC_BOX[1]) + '">' + DISC_BOX[0] + "</p>";
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
