/* zing web UI v2 — Knowledge page: pure helpers (no DOM, no text).
 *
 * The page lists three kinds of items from GET /api/kb/profiles — models,
 * providers and relays (see zing/knowledge/catalog.py) — through one section
 * component (kbsection.js). What depends only on the data lives here, so it
 * can be tested under node (tests/test_web_kbview_js.py):
 *   sourceKind(src)       "yours" | "kbdir" | "packaged" from an item's source
 *   sourceFile(src)       the file / path / entry number behind it
 *   modelProvider(key)    "openai" from a model key "model:openai/gpt-4o"
 *   matches(kind, item, f) whether an item passes the filters
 *                         f = { model, provider, relay, source } ("" = any):
 *                         model (a model key): that model, its provider;
 *                         provider: its models and its provider rows;
 *                         relay (a relay key): that relay; source: every tab.
 *                         A filter a tab has no field for leaves it alone.
 *   active(f)             how many filters are set
 *   options(data, f)      the values that exist, for the filter's selects:
 *                         { models (narrowed to f.provider), providers,
 *                         relays: [{v, t, group?}], sources: [kind…] }
 *   groups(items, field)  [{key, items}] in first-seen order
 *   summary(items)        {total, yours, off}
 *   itemsOf(data, kind)   the list for a tab ([] when missing)
 */
(function () {
  "use strict";

  function sourceKind(src) {
    src = String(src || "");
    if (src.indexOf("kb.db:") === 0) return "yours";
    if (src.indexOf("kb_dir:") === 0) return "kbdir";
    return "packaged";
  }

  function sourceFile(src) {
    src = String(src || "");
    var i = src.indexOf(":");
    if (src.indexOf("kb.db:entry/") === 0) return "#" + src.slice(12);
    return i >= 0 ? src.slice(i + 1) : src;
  }

  function modelProvider(key) {
    var m = /^model:([^/]+)\//.exec(String(key || ""));
    return m ? m[1] : "";
  }

  function matches(kind, it, f) {
    f = f || {};
    if (f.source && sourceKind(it.source) !== f.source) return false;
    if (kind === "models") {
      if (f.model && it.key !== f.model) return false;
      if (f.provider && it.provider !== f.provider) return false;
    } else if (kind === "providers") {
      if (f.model && it.provider !== modelProvider(f.model)) return false;
      if (f.provider && it.provider !== f.provider) return false;
    } else if (kind === "relays") {
      if (f.relay && it.key !== f.relay) return false;
    }
    return true;
  }

  function active(f) {
    f = f || {};
    return ["model", "provider", "relay", "source"].filter(function (k) { return !!f[k]; }).length;
  }

  function options(data, f) {
    f = f || {};
    var provs = [], seen = {};
    itemsOf(data, "providers").forEach(function (p) {
      if (seen[p.provider]) return;
      seen[p.provider] = true;
      provs.push({ v: p.provider, t: p.display_name || p.provider });
    });
    var models = itemsOf(data, "models")
      .filter(function (m) { return !f.provider || m.provider === f.provider; })
      .map(function (m) { return { v: m.key, t: m.id, group: m.provider_name || m.provider }; });
    var relays = itemsOf(data, "relays").map(function (r) { return { v: r.key, t: r.display_name || r.provider }; });
    var kinds = {};
    ["models", "providers", "relays"].forEach(function (k) {
      itemsOf(data, k).forEach(function (it) { kinds[sourceKind(it.source)] = true; });
    });
    var sources = ["packaged", "kbdir", "yours"].filter(function (k) { return kinds[k]; });
    return { models: models, providers: provs, relays: relays, sources: sources };
  }

  function groups(items, field) {
    var out = [], at = {};
    (items || []).forEach(function (it) {
      var k = it[field];
      if (!(k in at)) {
        at[k] = out.length;
        out.push({ key: k, items: [] });
      }
      out[at[k]].items.push(it);
    });
    return out;
  }

  function summary(items) {
    var s = { total: 0, yours: 0, off: 0 };
    (items || []).forEach(function (it) {
      s.total++;
      if (it.yours) s.yours++;
      if (!it.enabled) s.off++;
    });
    return s;
  }

  function itemsOf(data, kind) {
    return (data && Array.isArray(data[kind])) ? data[kind] : [];
  }

  window.ZingKbView = {
    _: {
      sourceKind: sourceKind, sourceFile: sourceFile, modelProvider: modelProvider, matches: matches,
      active: active, options: options, groups: groups, summary: summary, itemsOf: itemsOf,
    },
  };
})();
