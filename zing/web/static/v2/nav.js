/* zing web UI v2 — the one shared header.
 *
 * Every v2 page has, as the first thing in <div class="wrap">:
 *   <header class="znav" data-page="audit|tools|history|monitors|kb"></header>
 * and loads, right after /icons.js and before its own page script:
 *   <script src="/v2/static/nav.js"></script>
 * Optional: data-trust on the header adds the "runs locally" line under it
 * (inside the header, so it stays in the banner landmark).
 * The header starts with a skip link to the page's <main id="main"
 * tabindex="-1"> (BITV 9.2.4.1 bypass blocks), visible only on focus.
 *
 * The markup follows the i18n convention of the whole UI (Chinese inline,
 * English in data-en), so lang.js translates it at boot and on every switch;
 * the language <select class="lang-sel"> is filled by lang.js too. The theme
 * <select class="theme-sel"> is driven by theme.js (loaded in <head>). The
 * "Classic UI" link goes back to the classic page (?ui=v1 — see server.py).
 *
 * It also adds the footer link to the accessibility conformance report
 * (/v2/accessibility) to every page, as the last row of the page's <footer>
 * inside <div class="wrap"> (one is created when the page has none), so the
 * link sits in the same place on every page (BITV 9.3.2.3).
 */
(function () {
  "use strict";

  var LINKS = [
    // [page id, href, icon, zh, en]
    ["audit", "/v2/", "bolt", "检测", "Audit"],
    ["tools", "/v2/tools", "toolbox", "工具", "Tools"],
    ["history", "/v2/history", "chart", "检测历史", "History"],
    ["monitors", "/v2/watches", "bell", "监控", "Monitors"],
    ["kb", "/v2/kb", "book", "知识库", "Knowledge"],
  ];

  function ico(name, opts) {
    return window.zingIcon ? window.zingIcon(name, opts || {}) : "";
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
      '<a class="logo" href="/v2/" aria-label="zing"><span class="b">' + ico("bolt", { size: 16 }) +
      "</span><span>zing<b>.</b></span></a>" +
      '<div class="tail">' +
      '<a class="classic" href="?ui=v1" data-en="Classic UI">经典界面</a>' +
      '<select class="theme-sel" aria-label="主题" title="主题" data-en-aria-label="Theme" data-en-title="Theme">' +
      '<option value="system" data-en="Auto theme">跟随系统</option>' +
      '<option value="light" data-en="Light">浅色</option>' +
      '<option value="dark" data-en="Dark">深色</option></select>' +
      '<select class="lang-sel" aria-label="语言" title="语言" data-en-aria-label="Language" data-en-title="Language"></select>' +
      "</div>" +
      '<nav class="links" aria-label="主导航" data-en-aria-label="Main navigation">' + links + "</nav>";
    if (header.hasAttribute("data-trust")) {
      var p = document.createElement("p");
      p.className = "trust";
      p.innerHTML =
        ico("lock") +
        ' <span data-en="Runs locally · keys <b>never leave</b>">本地运行 · 密钥<b>不经手</b></span>';
      header.appendChild(p);
    }
    var ts = header.querySelector("select.theme-sel");
    if (window.ZING_THEME) {
      ts.value = window.ZING_THEME.get();
      ts.addEventListener("change", function () { window.ZING_THEME.set(ts.value); });
    } else {
      ts.remove(); // page without theme.js
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

  function footerLinks(page) {
    var wrap = document.querySelector("body > .wrap");
    if (!wrap) return;
    var foot = null;
    for (var c = wrap.firstElementChild; c; c = c.nextElementSibling) if (c.tagName === "FOOTER") foot = c;
    if (!foot) {
      foot = document.createElement("footer");
      wrap.appendChild(foot);
    }
    if (foot.querySelector(".foot-links")) return;
    var p = document.createElement("p");
    p.className = "foot foot-links";
    p.innerHTML =
      '<a href="/v2/accessibility"' + (page === "a11y" ? ' aria-current="page"' : "") +
      ' data-en="Accessibility">无障碍</a>';
    foot.appendChild(p);
  }

  var headers = document.querySelectorAll("header.znav");
  for (var i = 0; i < headers.length; i++) render(headers[i]);
  footerLinks(headers.length ? headers[0].getAttribute("data-page") || "" : "");
  // If lang.js already booted (script loaded late), translate the new markup.
  if (window.ZING_LANG && document.readyState !== "loading") window.ZING_LANG.apply(document);
})();
