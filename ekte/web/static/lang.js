/* zing web UI — language switch (English · 中文 · Français · Español ·
 * Português · Italiano · Deutsch; the list comes from zing/i18n/locales/).
 *
 * Plain browser global, no modules. Load it in <head> after /locales.js and
 * before any page script, so the current language is known while the page
 * renders. Exposes window.ZING_LANG with:
 *   - get()            -> a code from LANGS below ("en", "zh", "fr", …)
 *   - langs()          the registry: [{ code, label, html, locale }] in menu order
 *                      (label is the language's own name: "English", "中文", …)
 *   - isZh()           true when the original Chinese UI is shown
 *   - set(lang)        persist + re-translate static markup + fire "zing:lang";
 *                      when lang's data isn't loaded yet it first loads
 *                      /locales.js?lang=<code> (asynchronously: get() changes
 *                      once it is in); if that fails the language stays as it
 *                      was and the switchers show it again
 *   - t(zh, en)        CN -> zh; otherwise the English text translated via tr()
 *   - tr(en)           English string -> current language (from ZING_LOCALES)
 *   - trFor(lang, en)  English string -> the given language
 *   - locale()         BCP 47 locale for dates/numbers ("fr-FR", …)
 *   - intl(Ctor, opts[, locale])
 *                      a shared Intl formatter, e.g. intl(Intl.DisplayNames,
 *                      { type: "language" }), built once per (constructor,
 *                      locale, options) and reused; locale defaults to
 *                      locale(), so after set() callers get formatters for
 *                      the new language. Same output as a new Ctor(locale,
 *                      opts); a bad locale or options still throw
 *   - numFmt(opts)     intl(Intl.NumberFormat, opts)
 *   - dateFmt(opts)    intl(Intl.DateTimeFormat, opts)
 *   - code(v)          uppercase enum code ("HIGH", "FAIL") in the UI language
 *   - server(text)     translation of free text from the backend (detector
 *                      names, recommendations, verdict sentences, notes) into
 *                      the UI language, CN included; unknown text stays English
 *   - exportText(text) same, for downloaded files
 *   - stripCJK(text)   drop CJK runs (e.g. "Moonshot AI (月之暗面 / Kimi)")
 *   - markCJK(text)    HTML-escaped text with CJK runs wrapped in
 *                      <span lang="zh"> outside CN (BITV 9.3.1.2 language of
 *                      parts), for names that stay Chinese in every language
 *   - apply(root)      (re)translate static markup under root
 * and a global shorthand T(zh, en).
 *
 * The Chinese text in the HTML is the original and stays untouched: elements
 * carry their English text in data attributes (the English doubles as the
 * lookup key for the other languages) and the Chinese is remembered on first
 * switch, so CN always shows exactly what shipped.
 *   data-en="…"              innerHTML outside CN (only text/inline markup inside!)
 *   data-en-placeholder="…"  / data-en-title / data-en-aria-label  attributes
 * A <select class="lang-sel"> anywhere on the page becomes the switcher; its
 * options are generated from LANGS, the single list of supported languages.
 *
 * Adding a language: add zing/i18n/locales/<code>.json (its "meta" gives the
 * menu label — the language's own name, not a flag — <html lang>, locale and
 * menu order). Nothing else changes: pages, T(zh, en) call sites and data-en
 * markup stay as they are, and any string missing from a translation falls
 * back to English. Feature work may ship its strings as fragments,
 * zing/i18n/locales/fragments/<feature>/<code>.json ({"strings": {…}}), which
 * zing/i18n merges into that language's strings before serving /locales.js.
 *
 * Only the chosen language is downloaded: the choice is kept in localStorage
 * ("zing.lang") and mirrored in a "zing_lang" cookie, from which the server
 * picks the one-language /locales.js (no cookie: every language). Should the
 * stored language's data be missing at boot anyway (cookie lost or out of
 * date), the cookie is fixed and the page reloaded once while still hidden
 * (a sessionStorage flag prevents a loop); if that isn't possible, or the
 * reload doesn't come before the reveal timers below, the page
 * shows in English and switches once /locales.js?lang=<code> has loaded.
 *
 * Outside CN the page is hidden (html visibility) until the static markup is
 * translated. So a failure never leaves it blank, it is shown anyway ~1.5 s
 * after DOMContentLoaded (8 s at most after this script ran) or on a window
 * "error" once the HTML is parsed (e.g. a later script throws, or boot never
 * runs). Pages may also add
 *   <noscript><style>html{visibility:visible!important}</style></noscript>
 * for browsers with JavaScript disabled.
 */
(function () {
  "use strict";

  var KEY = "zing.lang";
  var COOKIE = "zing_lang"; // read by the server for /locales.js
  var RELOAD = "zing.lang.reload"; // sessionStorage: language reloaded for
  var DEFAULT = "en";
  // The supported languages in dropdown order, from zing/i18n/locales/*.json
  // (via /locales.js). EN and CN are always available: English is the key
  // language and CN the original markup.
  var LANG_LIST = ((window.ZING_LOCALES || {}).languages || []).slice();
  if (!LANG_LIST.length)
    LANG_LIST = [
      { code: "en", label: "English", html: "en", locale: "en-US" },
      { code: "zh", label: "中文", html: "zh-CN", locale: "zh-CN" },
    ];
  var LANGS = {};
  LANG_LIST.forEach(function (l) {
    LANGS[l.code] = l;
  });
  var ATTRS = ["placeholder", "title", "aria-label"];
  var CJK = /[⺀-⿿　-〿぀-ヿ㄀-ㇿ㐀-䶿一-鿿豈-﫿＀-￯]/;
  var CJK_RUN = /[⺀-⿿　-〿぀-ヿ㄀-ㇿ㐀-䶿一-鿿豈-﫿＀-￯]+/g;

  // Chinese terms the (otherwise English) backend embeds in its sentences.
  var GLOSSARY = [
    ["货不对板", "bait-and-switch"],
    ["中转站", "relay"],
  ];

  // Intl formatters are costly to build (Number#toLocaleString and friends
  // build one per call): keep one per (constructor, locale, options). The key
  // includes the locale, so a language switch needs no reset.
  var intlCtors = [];
  var intlCaches = [];
  function intl(Ctor, opts, loc) {
    if (arguments.length < 3) loc = LANGS[lang].locale;
    if (typeof Ctor !== "function") throw new TypeError("intl: not a constructor");
    var i = intlCtors.indexOf(Ctor);
    if (i < 0) {
      intlCtors.push(Ctor);
      intlCaches.push({});
      i = intlCtors.length - 1;
    }
    var cache = intlCaches[i];
    // undefined (the browser default), "" (an error), "en,de" (an error) and
    // ["en", "de"] must not share a key
    var k = (loc === undefined ? "" : JSON.stringify(loc)) + "|" + JSON.stringify(opts || {});
    return cache[k] || (cache[k] = new Ctor(loc, opts));
  }

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      if (v && LANGS[v]) return v;
    } catch (e) {}
    // No stored choice (or no localStorage): the cookie mirrors it.
    var c = readCookie();
    return c && LANGS[c] ? c : DEFAULT;
  }

  function locales() {
    return window.ZING_LOCALES || {};
  }

  // Is language `l`'s data loaded? (A ZING_LOCALES without has() is a bundle
  // that carries every language.)
  function has(l) {
    var L = locales();
    return l === DEFAULT || typeof L.has !== "function" || L.has(l);
  }

  function readCookie() {
    try {
      var m = /(?:^|;\s*)zing_lang=([^;]*)/.exec(document.cookie || "");
      return m ? m[1] : null;
    } catch (e) {
      return null;
    }
  }

  function writeCookie(l) {
    if (readCookie() === l) return;
    try {
      document.cookie = COOKIE + "=" + l + "; path=/; max-age=31536000; SameSite=Lax";
    } catch (e) {}
  }

  function persist(l) {
    try {
      localStorage.setItem(KEY, l);
    } catch (e) {}
    writeCookie(l);
  }

  // Reload once, so the server sends the bundle the cookie now names. False
  // when that can't help (no cookie, no sessionStorage, already tried).
  function reloadFor(l) {
    try {
      if (readCookie() !== l || sessionStorage.getItem(RELOAD) === l) return false;
      sessionStorage.setItem(RELOAD, l);
      if (sessionStorage.getItem(RELOAD) !== l) return false;
      location.reload();
      return true;
    } catch (e) {
      return false;
    }
  }

  var wanted = read();
  var lang = wanted;
  var reloading = false; // a reload is under way: keep the page hidden
  var late = null; // the stored language, when it has to load after boot
  writeCookie(wanted);
  if (has(wanted)) {
    try {
      if (sessionStorage.getItem(RELOAD) != null) sessionStorage.removeItem(RELOAD);
    } catch (e) {}
  } else {
    // English until the stored language's data is here (never a page
    // without text, never a reload loop).
    lang = DEFAULT;
    late = wanted;
    reloading = reloadFor(wanted);
  }

  function tr(en) {
    if (en == null || lang === "en" || lang === "zh") return en;
    var d = (locales().strings || {})[lang] || {};
    return Object.prototype.hasOwnProperty.call(d, en) ? d[en] : en;
  }

  // Uppercase enum codes shown as-is in CN/EN (e.g. "HIGH", "FAIL");
  // other languages look up the uppercase code itself.
  function code(v) {
    var c = String(v == null ? "" : v).toUpperCase();
    return lang === "en" || lang === "zh" ? c : tr(c);
  }

  function t(zh, en) {
    return lang === "zh" ? zh : tr(en);
  }

  function stripCJK(s) {
    s = String(s == null ? "" : s);
    if (!CJK.test(s)) return s;
    return s
      .replace(CJK_RUN, "")
      .replace(/\(\s*[\/·,，]?\s*/g, "(")
      .replace(/\s*[\/·,，]?\s*\)/g, ")")
      .replace(/\(\s*\)/g, "")
      .replace(/\s+\/\s+(?=[\/)]|$)/g, "")
      .replace(/\s*\/\s*(?=\()/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  function escHTML(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function markCJK(s) {
    s = String(s == null ? "" : s);
    if (lang === "zh" || !CJK.test(s)) return escHTML(s);
    var out = "", last = 0, m;
    CJK_RUN.lastIndex = 0;
    while ((m = CJK_RUN.exec(s))) {
      out += escHTML(s.slice(last, m.index)) + '<span lang="zh">' + escHTML(m[0]) + "</span>";
      last = m.index + m[0].length;
    }
    return out + escHTML(s.slice(last));
  }

  // English string -> language `l` (no current-language shortcut; "zh"
  // only knows the backend strings registered for exports).
  function trIn(l, en) {
    if (en == null || l === "en") return en;
    var d = (locales().strings || {})[l] || {};
    return Object.prototype.hasOwnProperty.call(d, en) ? d[en] : en;
  }

  // Backend text (always English) -> language `l`: drop the embedded Chinese
  // terms (not for zh), then translate exact known strings (detector names,
  // recommendations, …) and known sentence patterns (verdict summary and
  // headline) from ZING_LOCALES; anything unknown stays English.
  function backendIn(l, text) {
    if (text == null) return text;
    var s = String(text);
    if (l !== "zh")
      GLOSSARY.forEach(function (g) {
        s = s.split(g[0]).join(g[1]);
      });
    if (l === "en") return s;
    var exact = trIn(l, s);
    if (exact !== s) return exact;
    var t = function (en) {
      return trIn(l, en);
    };
    (locales().patterns || []).forEach(function (p) {
      s = s.replace(new RegExp(p[0], "g"), function () {
        var groups = arguments;
        return t(p[1]).replace(/\{(\d)\}/g, function (_m, i) {
          var g = groups[+i];
          return g == null ? "" : p[2] && p[2][i] ? p[2][i](g, t) : g;
        });
      });
    });
    // Chinese sentences are not separated by spaces.
    if (l === "zh") s = s.replace(/([。）])\s+(?=\S)/g, "$1");
    return s;
  }

  // Backend text in the UI, in the UI language (CN included: zh.json carries
  // the backend's sentences too).
  function server(text) {
    return backendIn(lang, text);
  }

  // Backend text in a downloaded artefact: the same translation, so the file
  // is in the chosen language throughout.
  function exportText(text) {
    return backendIn(lang, text);
  }

  function applyEl(el) {
    if (el.hasAttribute("data-en")) {
      if (el.__zingZh == null) el.__zingZh = el.innerHTML;
      var html = lang === "zh" ? el.__zingZh : tr(el.getAttribute("data-en"));
      if (el.tagName === "TITLE") el.textContent = html;
      else if (el.innerHTML !== html) el.innerHTML = html;
    }
    ATTRS.forEach(function (a) {
      var enA = "data-en-" + a;
      if (!el.hasAttribute(enA)) return;
      el.__zingZhAttr = el.__zingZhAttr || {};
      if (!(a in el.__zingZhAttr)) el.__zingZhAttr[a] = el.getAttribute(a);
      var v = lang === "zh" ? el.__zingZhAttr[a] : tr(el.getAttribute(enA));
      if (v == null) el.removeAttribute(a);
      else el.setAttribute(a, v);
    });
  }

  function apply(root) {
    root = root || document;
    var sel = "[data-en],[data-en-placeholder],[data-en-title],[data-en-aria-label]";
    if (root.nodeType === 1 && root.matches && root.matches(sel)) applyEl(root);
    var els = root.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) applyEl(els[i]);
    document.documentElement.lang = LANGS[lang].html;
    syncSwitchers();
  }

  function syncSwitchers() {
    var sw = document.querySelectorAll("select.lang-sel");
    for (var j = 0; j < sw.length; j++) sw[j].value = lang;
  }

  // Load language `l`'s bundle (/locales.js?lang=l merges itself into
  // ZING_LOCALES), then done(loaded?). Concurrent calls share one request.
  var loading = {};
  function load(l, done) {
    if (loading[l]) {
      loading[l].push(done);
      return;
    }
    var cbs = (loading[l] = [done]);
    function finish() {
      delete loading[l];
      var ok = has(l);
      cbs.forEach(function (cb) {
        cb(ok);
      });
    }
    try {
      var s = document.createElement("script");
      s.src = "/locales.js?lang=" + encodeURIComponent(l);
      s.async = true;
      s.onload = s.onerror = function () {
        s.onload = s.onerror = null;
        if (s.parentNode) s.parentNode.removeChild(s);
        finish();
      };
      (document.head || document.documentElement).appendChild(s);
    } catch (e) {
      setTimeout(finish, 0);
    }
  }

  var pending = null; // the language being loaded for the latest set()
  function set(next) {
    next = LANGS[next] ? next : DEFAULT;
    if (!has(next)) {
      pending = next;
      load(next, function (ok) {
        if (pending !== next) return; // superseded by a later choice
        pending = null;
        if (ok) set(next);
        else syncSwitchers(); // keep the current language
      });
      return;
    }
    pending = null;
    late = null;
    if (next === lang) {
      persist(lang); // e.g. English picked while the stored language loads
      return;
    }
    lang = next;
    persist(lang);
    apply(document);
    try {
      window.dispatchEvent(new CustomEvent("zing:lang", { detail: { lang: lang } }));
    } catch (e) {}
  }

  function wireSwitchers() {
    var sw = document.querySelectorAll("select.lang-sel");
    for (var i = 0; i < sw.length; i++) {
      if (sw[i].__zingWired) continue;
      sw[i].__zingWired = true;
      sw[i].innerHTML = "";
      LANG_LIST.forEach(function (l) {
        var o = document.createElement("option");
        o.value = l.code;
        o.textContent = l.label;
        sw[i].appendChild(o);
      });
      sw[i].value = lang;
      sw[i].addEventListener("change", function (ev) {
        set(ev.target.value);
      });
    }
  }

  // Keep the page hidden until the static markup is in the chosen language,
  // so a non-CN user never sees a flash of the Chinese original.
  // Never leave it blank, though: if boot doesn't run or a script fails,
  // show the page anyway. The 1.5 s grace starts once the HTML is parsed (a
  // slow download must not flash the Chinese original); a script error after
  // that reveals at once, and a cap covers a DOMContentLoaded that never comes.
  var timers = [];
  function reveal() {
    timers.forEach(function (id) {
      clearTimeout(id);
    });
    timers = [];
    try {
      window.removeEventListener("error", onError);
    } catch (e) {}
    document.documentElement.style.visibility = "";
    if (reloading) {
      // The reload didn't happen in time: load the language in place.
      reloading = false;
      if (late) set(late);
    }
  }
  function onError() {
    // Before DOMContentLoaded boot is still to come and will reveal the page.
    if (document.readyState !== "loading") reveal();
  }
  function arm() {
    timers.push(setTimeout(reveal, 1500));
  }
  if (lang !== "zh") {
    document.documentElement.style.visibility = "hidden";
    try {
      window.addEventListener("error", onError);
      timers.push(setTimeout(reveal, 8000));
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arm);
      else arm();
    } catch (e) {
      reveal();
    }
  }
  document.documentElement.lang = LANGS[lang].html;

  function boot() {
    try {
      apply(document);
      wireSwitchers();
    } finally {
      // While reloading the page stays hidden; the timers above still
      // reveal it should the reload not happen.
      if (!reloading) reveal();
    }
    if (late && !reloading) set(late);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.ZING_LANG = {
    get: function () {
      return lang;
    },
    langs: function () {
      return LANG_LIST.slice();
    },
    isZh: function () {
      return lang === "zh";
    },
    locale: function () {
      return LANGS[lang].locale;
    },
    intl: intl,
    numFmt: function (opts) {
      return intl(Intl.NumberFormat, opts);
    },
    dateFmt: function (opts) {
      return intl(Intl.DateTimeFormat, opts);
    },
    set: set,
    t: t,
    tr: tr,
    trFor: trIn,
    code: code,
    server: server,
    exportText: exportText,
    stripCJK: stripCJK,
    markCJK: markCJK,
    apply: apply,
  };
  window.T = t;
})();
