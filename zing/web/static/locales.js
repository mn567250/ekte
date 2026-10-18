/* zing web UI — translation lookups for every language but EN.
 *
 * The translations themselves are data: zing/i18n/locales/<code>.json, shared
 * with the Python side (webhook alerts). The server serves /locales.js as
 * `window.ZING_I18N_DATA = {languages, locales}` followed by this file, so
 * the data is in place before the code below runs. Load it before /lang.js.
 *
 * /locales.js carries one language when asked for one (`?lang=<code>`, else
 * the `zing_lang` cookie lang.js writes) and every language otherwise. A
 * one-language bundle adds `lang`, `keys` (below) and `common` (the other
 * languages' forms of the few strings every page needs for all of them) to
 * the data. A second bundle loaded later (lang.js does, to switch to a
 * language not loaded yet) merges its data into the existing
 * window.ZING_LOCALES instead of replacing it; window.ZING_I18N_DATA then
 * holds that last bundle's data only, so read ZING_LOCALES, not it.
 *
 * Exposes window.ZING_LOCALES = { strings, findings, patterns, add, has, merge, keys, languages }:
 *   - strings[lang][english]   UI text; the English string (a `data-en`
 *                              attribute or the 2nd argument of T(zh, en)) is
 *                              the key. Missing keys fall back to English.
 *   - findings[lang][id]       { title, tpl, generic } per audit finding, same
 *                              placeholder rules as i18n.js ("zh" is the
 *                              original Chinese catalog).
 *                              Both maps hold one object per language from the
 *                              start (empty, or only `common`, until its data is loaded) and keep
 *                              it, so a reference taken early (i18n.js keeps
 *                              findings.zh) sees data merged later.
 *   - patterns                 [regex, english template, {group: fn}] used by
 *                              ZING_LANG.server() to translate known backend
 *                              sentences (verdict summary and headline).
 *   - add(code, strings, findings)   register a language at runtime.
 *   - has(code)                true when that language's data is loaded
 *                              (always for "en", the key language).
 *   - merge(data)              add() every language of a ZING_I18N_DATA-shaped
 *                              object ({ locales: { code: { strings, findings } } }).
 *   - keys                    { strings: every translatable English string,
 *                                findings: every finding id }.
 *   - languages                [{ code, label, html, locale, order }] in menu order.
 *
 * Adding a language: add zing/i18n/locales/<code>.json (copy de.json).
 */
(function () {
  "use strict";

  var DATA = window.ZING_I18N_DATA || { languages: [], locales: {} };

  // A further bundle (/locales.js?lang=…, loaded by lang.js on a switch):
  // add its language to the lookups already in place.
  var prev = window.ZING_LOCALES;
  if (prev && typeof prev.merge === "function") {
    prev.merge(DATA);
    return;
  }

  function esc(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // Sentences of the backend verdict summary (zing/scoring.py::_summary).
  var P = [
    ["Overall health score ([\\d.]+)/100\\.", "Overall health score {1}/100."],
    ["Custom run: (\\d+) of (\\d+) selected dimensions scored\\.", "Custom run: {1} of {2} selected dimensions scored."],
    [
      "Findings: ((?:\\d+ (?:critical|high|medium)(?:, )?)+)\\.",
      "Findings: {1}.",
      {
        1: function (g, tr) {
          // "4 high, 5 medium": translate the words and the list separator
          return g
            .split(", ")
            .map(function (part) {
              return part.replace(/\b(critical|high|medium)\b/g, function (w) {
                return tr(w);
              });
            })
            .join(tr(", "));
        },
      },
    ],
  ];
  // Headlines naming the dimensions that drove the risk ("Context window,
  // Billing & usage"): translate each name and the list separator.
  var dimList = {
    1: function (g, tr) {
      return g
        .split(", ")
        .map(function (n) {
          return tr(n);
        })
        .join(tr(", "));
    },
  };
  P.push(
    [
      "Strong evidence the relay does not deliver what it advertises: (.+?)\\.(?= \\(confidence: |$)",
      "Strong evidence the relay does not deliver what it advertises: {1}.",
      dimList,
    ],
    [
      "Some checks diverge from what is advertised: (.+?) — investigate\\.",
      "Some checks diverge from what is advertised: {1} — investigate.",
      dimList,
    ]
  );
  P.push([
    "\\(confidence: (low|medium|high)\\)",
    "(confidence: {1})",
    {
      1: function (g, tr) {
        return tr(g.charAt(0).toUpperCase() + g.slice(1)).toLowerCase();
      },
    },
  ]);
  [
    "Behavior is consistent with the claimed model.",
    "Mostly consistent with the claimed model; minor concerns.",
    "Some behavior diverges from the claimed model — investigate.",
    "Strong evidence the relay does not deliver the claimed model as advertised.",
    "Not enough signal to judge — connectivity or coverage was insufficient.",
    "No significant divergence findings.",
    "The claimed model was not found in the knowledge base, so identity/capability checks are limited — pass --declared-provider or add a KB profile.",
    "Run `zing compare` against a trusted baseline to strengthen the verdict.",
    "The claimed model only fuzzily matched a knowledge-base profile, so confidence is capped at low — pass the exact model id or add a KB alias.",
    "Transport and reliability findings (plain HTTP, failures or slowness under load) are advisories: they lower the score but not the substitution risk.",
    "No core dimension (model identity, context window, capability) was selected, so the substitution risk cannot be judged.",
    "Model identity was not selected, so this verdict covers only the selected dimensions, not which model is served.",
    "No problems found in the checked dimensions; model identity was not verified.",
    "Minor concerns in the checked dimensions; model identity was not verified.",
    "zing reports black-box evidence of divergence and risk, not proof of fraud.",
  ].forEach(function (s) {
    P.push([esc(s), s]);
  });

  var strings = {};
  var findings = {};
  var loaded = {};

  // The (emptied) object of language `code` in `map`: one per language, kept
  // for good (see the header).
  function slot(map, code) {
    if (!Object.prototype.hasOwnProperty.call(map, code)) map[code] = {};
    var d = map[code];
    Object.keys(d).forEach(function (k) {
      delete d[k];
    });
    return d;
  }

  // Register a language. `s` maps English UI string -> translation; `f` maps
  // finding id -> [title, summary template, generic title (optional: when a
  // title placeholder is missing from the evidence)]. Missing entries fall
  // back to English at runtime.
  function add(code, s, f) {
    var sd = slot(strings, code);
    Object.keys(s || {}).forEach(function (k) {
      sd[k] = s[k];
    });
    var d = slot(findings, code);
    Object.keys(f || {}).forEach(function (id) {
      d[id] = { title: f[id][0], tpl: f[id][1], generic: f[id][2] };
    });
    loaded[code] = true;
  }

  function has(code) {
    return code === "en" || loaded[code] === true;
  }

  function merge(data) {
    var locs = (data && data.locales) || {};
    Object.keys(locs).forEach(function (code) {
      if (code === "en") return; // English is the key language
      add(code, locs[code].strings, locs[code].findings);
    });
    // A few strings of the languages not loaded (see zing/i18n lang_bundle).
    var common = (data && data.common) || {};
    Object.keys(common).forEach(function (code) {
      if (code === "en" || loaded[code]) return;
      var d = strings[code] || (strings[code] = {});
      Object.keys(common[code] || {}).forEach(function (k) {
        d[k] = common[code][k];
      });
    });
  }

  (DATA.languages || []).forEach(function (l) {
    if (l.code !== "en") {
      slot(strings, l.code);
      slot(findings, l.code);
    }
  });
  merge(DATA);

  // A one-language bundle sends the keys; the full one has en and zh to read them from.
  var en = DATA.locales.en || {};
  var zh = DATA.locales.zh || {};
  window.ZING_LOCALES = {
    strings: strings,
    findings: findings,
    patterns: P,
    add: add,
    has: has,
    merge: merge,
    keys: DATA.keys || { strings: Object.keys(en.strings || {}), findings: Object.keys(zh.findings || {}) },
    languages: DATA.languages || [],
  };
})();
