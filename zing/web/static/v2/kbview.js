/* zing web UI v2 — Knowledge page: pure helpers (no DOM, no text).
 *
 * The page lists three kinds of items from GET /api/kb/profiles — models,
 * providers and relays (see zing/knowledge/catalog.py) — through one section
 * component (kbsection.js). What depends only on the data lives here, so it
 * can be tested under node (tests/test_web_kbview_js.py):
 *   sourceKind(src)       "yours" | "kbdir" | "packaged" from an item's source
 *   sourceFile(src)       the file / path / entry number behind it
 *   haystack(kind, item)  the lower-case text the filter searches
 *   filter(kind, items, q) the items matching every word of q
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

  function haystack(kind, it) {
    var parts;
    if (kind === "models") {
      parts = [it.id, it.provider, it.provider_name].concat(it.aliases || []);
    } else {
      parts = [it.provider, it.display_name].concat(it.base_urls || []);
    }
    return parts.filter(Boolean).join(" ").toLowerCase();
  }

  function filter(kind, items, q) {
    var words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return (items || []).slice();
    return (items || []).filter(function (it) {
      var hay = haystack(kind, it);
      return words.every(function (w) { return hay.indexOf(w) >= 0; });
    });
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
      sourceKind: sourceKind, sourceFile: sourceFile, haystack: haystack, filter: filter,
      groups: groups, summary: summary, itemsOf: itemsOf,
    },
  };
})();
