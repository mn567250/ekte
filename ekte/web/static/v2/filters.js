/* ekte web UI v2 — the shared filter fields, the view state in the URL query
 * string and widget fetching (window.EkteFilters). Builds on filterpanel.js,
 * which stays the collapsible frame; styles in filterpanel.css.
 *
 * No metric logic lives here: no value is computed, graded or classified.
 * The keys and values are the server's URL schema (docs/dev/web-server.md,
 * "Query core"; ekte/web/query.py), so the query string a widget sends to its
 * endpoint is the page's own query string, unchanged:
 *
 *   ?range=7d&relay=a&relay=b&trend.metric=latency_p50&tab=trends
 *
 *   shared filter keys   top level, from FIELDS (+ from / to with range)
 *   widget keys          dotted, one namespace per widget (kpi.*, trend.*,
 *                        groups.*, runs.*); the server's parser ignores them
 *   view keys            non-dotted page keys never sent to an endpoint
 *                        (opts.viewKeys, default ["tab"])
 *
 * A value equal to its default is left out of the URL, so links stay short;
 * a filter set back to empty over a non-empty default is written as "key=".
 * Unknown keys and invalid values in a URL are dropped (the server would
 * answer 400), keys the page does not show too: a filter never applies
 * without its field on screen.
 *
 * EkteFilters.create(opts) -> instance (one per page):
 *   opts.section     the empty <section class="card filters"> for the frame
 *   opts.fields      FIELDS keys the page shows, e.g. ["range", "relay", "q"]
 *   opts.defaults    { key: value } page defaults, shared ("range": "30d")
 *                    and widget keys ("trend.metric": "score")
 *   opts.page        names the localStorage fallback (the last filters,
 *                    shared across pages or this page's own, see
 *                    "remembered filters"; applied only when the URL has no
 *                    filter key) and the panel's remembered open state;
 *                    with it the foot shows "Keep filters across pages"
 *   opts.onChange(state, changed)  after every change (changed: the keys)
 *   opts.optionsUrl  option lists, default "/api/filters/options"; false: none
 *   opts.foot        HTML at the start of the panel's foot ("Showing 3 of 9"),
 *                    or a function returning it (called on every render)
 *   opts.extra()     HTML after the fields in the panel's body (a page's own
 *                    controls, e.g. History's trend picker; called on every
 *                    render, the page handles its events)
 *   opts.live        the page's live region (default #live, else one of ours)
 * instance:
 *   state()          { key: value } every declared, widget and view key with
 *                    its effective value (relay / model: arrays)
 *   widgetParams(ns) the query string for a widget: the shared filters plus
 *                    the ns.* keys (ns: a name, a list, or none), and tz:
 *                    the viewer's time zone, which resolves day ranges and
 *                    buckets times; it is never in state() or url(), so a
 *                    shared link resolves in each viewer's own zone
 *   set(patch)       { key: value | null } (null: back to the default)
 *   reset()          every filter back to its default (widget keys stay)
 *   load(widgets)    { ns: { url, done(data), fail(err) } }: fetches them all
 *                    at once with widgetParams(ns); a newer load (and every
 *                    change) aborts the requests still in flight; fail gets
 *                    one widget's error, never an abort
 *   signal()         the AbortSignal of the current state
 *   url()            the link to this view; copyLink() puts it on the clipboard
 *   render(), setOptions(options), panel (the EkteFilterPanel)
 * EkteFilters.state() / .widgetParams(ns): the same on the page's instance.
 * EkteFilters.fetchWidget(url, { signal }) -> Promise of the JSON: sends
 *   If-None-Match with the ETag last seen for that URL (kept in memory) and
 *   answers a 304 from that copy; an error status rejects with an Error that
 *   has .status and the server's message.
 * EkteFilters.keyed(key, labels): the text of an i18n key ("metric.score"),
 *   falling back to labels[key] (GET /api/metrics `labels`), then the key.
 * Pure helpers (tested under node): parse, serialise, params, initial,
 *   remember, scope, setScope (storage injectable), loader, viewerZone,
 *   FIELDS.
 *
 * /api/filters/options (issue 123) is read as { "<key>": [{ value, label?, runs? }] }
 * for the keys of FIELDS ("-" is "(unknown)"), requested with the shared
 * filters; a key it does not list keeps its fixed options.
 */
(function () {
  "use strict";

  var UNKNOWN = "-";
  var RANGES = ["24h", "7d", "30d", "90d", "365d"];
  var CUSTOM = "custom"; // the range select's "Custom range": from / to
  var ISO = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/;
  var DAY = /^\d{4}-\d{2}-\d{2}$/;

  // [zh, en] pairs, translated when shown
  var L = {
    q: ["搜索", "Search"], range: ["时间范围", "Period"], surface: ["接口类型", "Endpoint type"],
    relay: ["中转站 / 厂商", "Relay / provider"], model: ["声称模型", "Claimed model"], suite: ["套件", "Suite"],
    mode: ["模式", "Mode"], api: ["协议", "Protocol"], stream: ["探测请求", "Probe requests"],
    detect: ["协议识别", "Protocol detection"], risk: ["风险", "Risk"], min_score: ["最低健康分", "Min. score"],
    exec: ["执行方式", "Execution"], group: ["分组", "Group by"],
    from: ["开始日期", "Start date"], to: ["结束日期", "End date"],
  };
  var V = {
    range: { "": ["全部时间", "All time"], "24h": ["最近 24 小时", "Last 24 hours"], "7d": ["最近 7 天", "Last 7 days"],
      "30d": ["最近 30 天", "Last 30 days"], "90d": ["最近 90 天", "Last 90 days"], "365d": ["最近 365 天", "Last 365 days"],
      custom: ["自定义", "Custom range"] },
    surface: { chat: ["对话", "Chat"], embedding: ["嵌入", "Embeddings"], rerank: ["重排", "Reranking"] },
    stream: { stream: ["流式", "Streaming"], non_stream: ["非流式", "Non-streaming"], both: ["流式 + 非流式", "Streaming + non-streaming"] },
    detect: { auto: ["自动识别", "auto-detected"], manual: ["手动指定", "set manually"] },
    exec: { manual: ["手动", "Manual"], monitor: ["监控", "Monitor"] },
    group: { relay: ["中转站", "Relay"], model: ["模型", "Model"], relay_model: ["中转站 × 模型", "Relay × model"], all: ["全部", "All"] },
  };

  /* The URL schema of ekte/web/query.py, in the order fields are shown and
   * keys are written. kind: text | range | select | multi | number;
   * values: the fixed choices (null: free, listed by the options endpoint);
   * unknown: "-" ("(unknown)") is a valid value; def: the schema default
   * (range: the last 30 days on every page; "range=" is all time);
   * page: always remembered per page, never shared ("remembered filters"). */
  var FIELDS = {
    q: { kind: "text", def: "", page: true },
    range: { kind: "range", def: "30d", values: RANGES },
    surface: { kind: "select", def: "", values: ["chat", "embedding", "rerank"] },
    relay: { kind: "multi", def: [], values: null, unknown: true },
    model: { kind: "multi", def: [], values: null, unknown: true },
    suite: { kind: "select", def: "", values: null, unknown: true },
    mode: { kind: "select", def: "", values: null, unknown: true },
    api: { kind: "select", def: "", values: null, unknown: true },
    stream: { kind: "select", def: "", values: ["stream", "non_stream", "both"], unknown: true },
    detect: { kind: "select", def: "", values: ["auto", "manual"], unknown: true },
    risk: { kind: "select", def: "", values: ["clean", "low", "medium", "high", "inconclusive"] },
    min_score: { kind: "number", def: "" },
    exec: { kind: "select", def: "", values: ["manual", "monitor"] },
    group: { kind: "select", def: "relay", values: ["relay", "model", "relay_model", "all"], required: true },
  };
  var ORDER = Object.keys(FIELDS);

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function tr(pair) { return typeof T === "function" ? T(pair[0], pair[1]) : pair[1]; }
  function Tf(zh, en, vars) {
    return tr([zh, en]).replace(/\{(\w+)\}/g, function (m, k) { return vars && k in vars ? vars[k] : m; });
  }
  function isArr(v) { return Array.isArray(v); }
  function same(a, b) {
    if (isArr(a) || isArr(b)) {
      a = isArr(a) ? a : a ? [a] : [];
      b = isArr(b) ? b : b ? [b] : [];
      return a.length === b.length && a.every(function (x, i) { return x === b[i]; });
    }
    return String(a == null ? "" : a) === String(b == null ? "" : b);
  }
  function copy(v) { return isArr(v) ? v.slice() : v; }

  // the keys a page's state has: its fields, from / to with range
  function keysOf(fields) {
    var out = [];
    ORDER.forEach(function (k) {
      if (fields.indexOf(k) < 0) return;
      out.push(k);
      if (k === "range") out.push("from", "to");
    });
    return out;
  }
  function isWidgetKey(k) { return k.indexOf(".") > 0; }

  // one value of a shared key: the valid value, else undefined (dropped)
  function clean(key, v) {
    v = String(v).trim();
    if (v === "") return "";
    if (key === "from" || key === "to") return ISO.test(v) ? v : undefined;
    var f = FIELDS[key];
    if (f.kind === "number") {
      var n = Number(v);
      return isFinite(n) && n >= 0 && n <= 100 ? String(n) : undefined;
    }
    if (f.kind === "text" || f.kind === "multi") return v;
    if (v === UNKNOWN) return f.unknown ? v : undefined;
    return !f.values || f.values.indexOf(v) >= 0 ? v : undefined;
  }

  /* The state a query string names: only the keys it has. A key the page does
   * not declare, an invalid value, a repeated non-repeatable key (all but the
   * first) and from / to beside a range are dropped; relay / model are arrays
   * (an empty value: none). Widget and view keys are kept as given (a
   * repeated one as an array). */
  function parse(search, fields, viewKeys) {
    var qs = new URLSearchParams(String(search || "").replace(/^\?/, ""));
    var own = keysOf(fields || ORDER), view = viewKeys || ["tab"], out = {};
    qs.forEach(function (raw, k) {
      if (own.indexOf(k) >= 0) {
        var multi = FIELDS[k] && FIELDS[k].kind === "multi";
        var v = clean(k, raw);
        if (multi) {
          var list = out[k] || (out[k] = []);
          if (v && list.indexOf(v) < 0) list.push(v);
        } else if (!(k in out) && v !== undefined) {
          out[k] = v;
        }
      } else if (isWidgetKey(k) || view.indexOf(k) >= 0) {
        if (!(k in out)) out[k] = raw;
        else out[k] = [].concat(out[k], raw);
      }
    });
    if (out.range) { delete out.from; delete out.to; }
    // from / to without range: a custom range (as written before range had a
    // non-empty default), not the default range over the dates
    else if ((out.from || out.to) && !("range" in out)) out.range = "";
    // "group=" means the default: the server requires a value
    if (out.group === "") delete out.group;
    return out;
  }

  function append(q, k, v) {
    if (isArr(v)) {
      if (!v.length) q.append(k, "");
      v.forEach(function (x) { q.append(k, x); });
    } else {
      q.append(k, v == null ? "" : String(v));
    }
  }
  function extraKeys(state, own) {
    return Object.keys(state).filter(function (k) { return own.indexOf(k) < 0; }).sort();
  }
  function schemaDefault(k) { return FIELDS[k] ? copy(FIELDS[k].def) : ""; }

  /* The URL query string (without "?") of a state: every key whose value
   * differs from its default (defaults: the page's, over the schema's),
   * shared keys in schema order, then widget and view keys sorted. */
  function serialise(state, defaults, fields) {
    var own = keysOf(fields || ORDER), q = new URLSearchParams();
    defaults = defaults || {};
    own.concat(extraKeys(state, own)).forEach(function (k) {
      if (!(k in state)) return;
      var def = k in defaults ? defaults[k] : schemaDefault(k);
      if (!same(state[k], def)) append(q, k, state[k]);
    });
    return q.toString();
  }

  // The viewer's time zone (IANA name), "UTC" when the browser names none.
  function viewerZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch (e) { return "UTC"; }
  }

  /* The query string a widget sends to its endpoint: the shared filters with
   * a value, then the keys of the widget's namespace(s), sorted, then tz
   * (given: the viewer's zone, see widgetParams). Empty values are left out
   * (the server reads them as not given). */
  function params(state, fields, ns, tz) {
    var own = keysOf(fields || ORDER), q = new URLSearchParams();
    var spaces = ns == null ? [] : [].concat(ns);
    var pick = function (k) {
      var v = state[k];
      if (v == null || v === "" || (isArr(v) && !v.length)) return;
      append(q, k, v);
    };
    own.forEach(pick);
    extraKeys(state, own).forEach(function (k) {
      if (spaces.some(function (n) { return k.indexOf(n + ".") === 0; })) pick(k);
    });
    if (tz) q.append("tz", tz);
    return q.toString();
  }

  /* ---------------- remembered filters ----------------
   * Two memories in localStorage, used only when the URL has no filter key of
   * the page (the URL always wins):
   *   ekte.v2.filters.<page>   the page's last filters, a query string (all of
   *                            its keys, written in both modes)
   *   ekte.v2.filters.shared   JSON { key: value } of the shared keys pages
   *                            last showed, as shown (a page's defaults
   *                            differ: "all time" stays "all time"); each page
   *                            merges in only the keys it shows, the others
   *                            stay untouched
   * ekte.v2.filters.scope ("shared", the default, or "page") picks the memory.
   * Keys flagged page: true in FIELDS (q) always come from the page's own
   * memory. Shared mode with no shared memory yet reads the page's own (as
   * before the toggle existed). Every access is wrapped in try/catch. */
  var SCOPE_KEY = "ekte.v2.filters.scope", SHARED_KEY = "ekte.v2.filters.shared";

  function storeKey(page) { return "ekte.v2.filters." + page; }
  function storeOf(storage) {
    if (storage !== undefined) return storage;
    try { return window.localStorage; } catch (e) { return null; }
  }
  function getItem(store, k) {
    try { return store ? store.getItem(k) : null; } catch (e) { return null; }
  }
  function setItem(store, k, v) {
    try { if (store) store.setItem(k, v); } catch (e) { /* ignore */ }
  }
  function isPageKey(k) { return !!(FIELDS[k] && FIELDS[k].page); }
  // the keys a page writes to the shared memory (from / to with range)
  function sharedKeys(fields) { return keysOf(fields).filter(function (k) { return !isPageKey(k); }); }

  // "shared" (default) or "page"
  function scope(storage) {
    return getItem(storeOf(storage), SCOPE_KEY) === "page" ? "page" : "shared";
  }
  // the shared memory as an object, or null (none yet, or unreadable)
  function readShared(store) {
    var raw = getItem(store, SHARED_KEY);
    if (!raw) return null;
    try {
      var v = JSON.parse(raw);
      return v && typeof v === "object" && !isArr(v) ? v : null;
    } catch (e) { return null; }
  }
  // a { key: value } object as a query string, for parse() to validate
  function toSearch(obj, keys) {
    var q = new URLSearchParams();
    keys.forEach(function (k) { if (Object.prototype.hasOwnProperty.call(obj, k)) append(q, k, obj[k]); });
    return q.toString();
  }

  /* Merges the page's shown shared keys into the shared memory, with their
   * values as shown; keys the page does not show stay. */
  function share(state, fields, storage) {
    var store = storeOf(storage), mem = readShared(store) || {};
    sharedKeys(fields).forEach(function (k) { if (k in state) mem[k] = copy(state[k]); });
    setItem(store, SHARED_KEY, JSON.stringify(mem));
  }

  /* Sets the per-viewer preference ("shared" | "page"). Turning sharing on
   * merges the current view's shared keys (o: { state, fields }) into the
   * shared memory and leaves the view as it is; turning it off copies
   * nothing. */
  function setScope(value, storage, o) {
    var store = storeOf(storage), v = value === "page" ? "page" : "shared";
    setItem(store, SCOPE_KEY, v);
    if (v === "shared" && o && o.state) share(o.state, o.fields || [], store);
    return v;
  }

  /* The remembered filters of a page: { key: value } of its keys found in
   * memory (validated like a URL), empty when there are none. */
  function recall(o) {
    var fields = o.fields, store = storeOf(o.storage);
    var saved = getItem(store, storeKey(o.page));
    var mine = saved ? parse(saved, fields, []) : {};
    var shared = scope(store) === "shared" ? readShared(store) : null;
    if (!shared) return mine;
    var out = parse(toSearch(shared, sharedKeys(fields)), fields, []);
    keysOf(fields).forEach(function (k) { if (isPageKey(k) && k in mine) out[k] = mine[k]; });
    return out;
  }

  /* The state to start from: the URL's, else (no filter key in it) the
   * remembered filters (see above; storage may be missing or throw), each
   * over the defaults. source: "url" | "storage" | "defaults". */
  function initial(search, o) {
    var fields = o.fields, defaults = o.defaults || {}, own = keysOf(fields);
    var fromUrl = parse(search, fields, o.viewKeys);
    var source = own.some(function (k) { return k in fromUrl; }) ? "url" : "defaults";
    var start = fromUrl;
    if (source === "defaults" && o.page) {
      try {
        var fromStore = recall(o);
        if (own.some(function (k) { return k in fromStore; })) {
          source = "storage";
          // the URL's widget and view keys stay
          start = Object.assign({}, fromUrl, fromStore);
        }
      } catch (e) { /* storage unavailable: the defaults */ }
    }
    var state = {};
    own.forEach(function (k) { state[k] = copy(k in defaults ? defaults[k] : schemaDefault(k)); });
    Object.keys(defaults).forEach(function (k) { if (!(k in state)) state[k] = copy(defaults[k]); });
    Object.keys(start).forEach(function (k) { state[k] = copy(start[k]); });
    if (state.range) { state.from = ""; state.to = ""; }
    return { state: state, source: source };
  }

  /* After a filter change: the page's own memory always, and in shared mode
   * the shared memory too (merged, see share). */
  function remember(page, state, fields, defaults, storage) {
    if (!page) return;
    var mine = {}, store = storeOf(storage);
    keysOf(fields).forEach(function (k) { mine[k] = state[k]; });
    // (setItem / getItem swallow storage errors)
    setItem(store, storeKey(page), serialise(mine, defaults, fields));
    if (scope(store) === "shared") share(state, fields, store);
  }

  /* ---------------- fetching ---------------- */
  var etags = new Map(); // url -> { etag, data }, newest last
  var MAX_ETAGS = 200;

  function fetchWidget(url, o) {
    o = o || {};
    var hit = etags.get(url), headers = { Accept: "application/json" };
    if (hit) headers["If-None-Match"] = hit.etag;
    return fetch(url, { signal: o.signal, headers: headers, credentials: "same-origin" }).then(function (r) {
      if (r.status === 304 && hit) {
        etags.delete(url);
        etags.set(url, hit);
        return hit.data;
      }
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          var err = new Error((body && body.error) || "HTTP " + r.status);
          err.status = r.status;
          throw err;
        });
      }
      return r.json().then(function (data) {
        var tag = r.headers && r.headers.get ? r.headers.get("ETag") : null;
        etags.delete(url);
        if (tag) {
          etags.set(url, { etag: tag, data: data });
          if (etags.size > MAX_ETAGS) etags.delete(etags.keys().next().value);
        }
        return data;
      });
    });
  }

  function isAbort(err) { return err && (err.name === "AbortError" || err.code === 20); }

  /* A loader: run(widgets, paramsFor) fetches every widget at once, after
   * aborting what the previous run still has in flight. abort() stops the
   * current run; signal() is its AbortSignal. A widget's result is delivered
   * only while its run is the latest. */
  function loader() {
    var ctl = null;
    function fresh() {
      if (ctl) ctl.abort();
      ctl = new AbortController();
      return ctl;
    }
    return {
      abort: function () { fresh(); },
      signal: function () { return (ctl || fresh()).signal; },
      run: function (widgets, paramsFor) {
        var mine = fresh();
        return Promise.all(Object.keys(widgets).map(function (ns) {
          var w = widgets[ns], qs = paramsFor(ns);
          var url = w.url + (qs ? (w.url.indexOf("?") >= 0 ? "&" : "?") + qs : "");
          return fetchWidget(url, { signal: mine.signal }).then(function (data) {
            if (!mine.signal.aborted && w.done) w.done(data);
          }, function (err) {
            if (mine.signal.aborted || isAbort(err)) return;
            if (w.fail) w.fail(err);
          });
        }));
      },
    };
  }

  /* The text of an i18n key such as "metric.latency_p50" (ekte/web/metrics.py):
   * the current language's translation, else `labels[key]` (GET /api/metrics
   * sends every key's English text there; the English bundle has no keyed
   * strings), else the key itself. */
  function keyed(key, labels) {
    var Lg = window.EKTE_LANG, v = Lg && Lg.tr ? Lg.tr(key) : key;
    if (v != null && v !== key) return v;
    return (labels && labels[key]) || key;
  }

  /* ---------------- the component ---------------- */
  var current = null;

  function valueLabel(key, v, opts) {
    if (v === UNKNOWN) return tr(["（未知）", "(unknown)"]);
    if (key === "risk") return window.EKTE_I18N && EKTE_I18N.label ? EKTE_I18N.label("RISK_LEVEL", v) : v;
    if (V[key] && V[key][v]) return tr(V[key][v]);
    var o = opts && opts[key];
    if (o) for (var i = 0; i < o.length; i++) if (o[i].value === v && o[i].label) return o[i].label;
    return v;
  }
  function num(n) { return window.EKTE_LANG && EKTE_LANG.numFmt ? EKTE_LANG.numFmt().format(n) : String(n); }
  function runs(n) { return n == null ? "" : ' <span class="ekf-n">(' + esc(num(n)) + ")</span>"; }
  // the end date shown for an exclusive `to` day: the day before
  function shiftDay(d, by) {
    var t = Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10)) + by * 864e5;
    return new Date(t).toISOString().slice(0, 10);
  }

  function create(o) {
    o = o || {};
    var fields = (o.fields || []).slice();
    fields.forEach(function (k) { if (!FIELDS[k]) throw new Error("EkteFilters: unknown filter key " + k); });
    // the fixed keys beside ekte.v2.filters.<page>
    if (o.page === "shared" || o.page === "scope") throw new Error("EkteFilters: page name " + o.page + " is reserved");
    var defaults = Object.assign({}, o.defaults || {});
    var viewKeys = o.viewKeys || ["tab"];
    var own = keysOf(fields);
    var section = o.section;
    var init = initial(location.search, { fields: fields, defaults: defaults, page: o.page, viewKeys: viewKeys, storage: o.storage });
    var st = init.state;
    var options = {}; // key -> [{ value, label, runs }]
    var custom = !!(st.from || st.to);
    var widgets = loader(), optLoad = loader();
    var debounce = null, sayT = null;

    var live = o.live || document.getElementById("live");
    if (!live) {
      live = document.createElement("p");
      live.className = "sr-only";
      live.setAttribute("role", "status");
      section.parentNode.insertBefore(live, section.nextSibling);
    }

    var panel = window.EkteFilterPanel.create(section, {
      storeKey: "ekte.v2.filters." + (o.page || "page") + ".open",
      open: init.source === "url" && activeCount() > 0,
      onReset: function () { reset(); },
    });

    function active(k) {
      if (k === "from" || k === "to") return false;
      if (k === "range") return !same(st.range, defOf("range")) || !!(st.from || st.to);
      return !same(st[k], defOf(k));
    }
    function defOf(k) { return k in defaults ? defaults[k] : schemaDefault(k); }
    function activeCount() { return fields.filter(active).length; }

    function rangeText() {
      if (st.range || !(st.from || st.to)) return tr(V.range[st.range] || [st.range, st.range]);
      var to = DAY.test(st.to) ? shiftDay(st.to, -1) : st.to;
      return (st.from || "…") + " – " + (to || "…");
    }
    function summary() {
      return fields.filter(active).map(function (k) {
        var lab = function (v) { return Tf("{label}：{value}", "{label}: {value}", { label: tr(L[k]), value: v }); };
        if (k === "range") return rangeText();
        if (k === "q") return lab(st.q.trim());
        if (k === "min_score") return lab("≥ " + st.min_score);
        var vals = [].concat(st[k]).map(function (v) { return valueLabel(k, v, options); });
        return lab(vals.length ? vals.join(", ") : tr(["全部", "All"]));
      });
    }

    // the values a choice field offers: fixed ones, the server's, the current
    function choices(k) {
      var f = FIELDS[k], seen = {}, out = [], server = options[k];
      var add = function (v, n) {
        if (v === "" || v == null || seen[v]) return;
        seen[v] = out.length + 1;
        out.push({ value: v, runs: n });
      };
      if (f.values) f.values.forEach(function (v) { add(v); });
      (server || []).forEach(function (x) {
        if (x.value === UNKNOWN && !f.unknown) return;
        if (seen[x.value]) out[seen[x.value] - 1].runs = x.runs;
        else add(x.value, x.runs);
      });
      [].concat(st[k]).forEach(function (v) { add(v); });
      // "(unknown)" when the server lists it, or there is no list to ask
      if (f.unknown && !seen[UNKNOWN] && !server) add(UNKNOWN);
      // "(unknown)" last
      out.sort(function (a, b) { return (a.value === UNKNOWN) - (b.value === UNKNOWN); });
      return out;
    }

    function fieldHTML(k) {
      var f = FIELDS[k], label = esc(tr(L[k]));
      if (f.kind === "text") {
        return '<label class="ekf-q"><span>' + label + '</span><input class="in" type="search" data-f="q" value="' + esc(st.q) +
          '" placeholder="' + esc(tr(["中转站、模型、套件、协议…", "Relay, model, suite, protocol…"])) + '" autocomplete="off" /></label>';
      }
      if (f.kind === "number") {
        return '<label><span>' + label + '</span><input class="in" type="number" inputmode="numeric" min="0" max="100" step="1" data-f="' + k +
          '" value="' + esc(st[k]) + '" placeholder="0" /></label>';
      }
      if (f.kind === "range") {
        var cur = custom ? CUSTOM : st.range;
        var opts = [""].concat(RANGES, [CUSTOM]).map(function (v) {
          return '<option value="' + v + '"' + (v === cur ? " selected" : "") + ">" + esc(tr(V.range[v])) + "</option>";
        }).join("");
        var to = DAY.test(st.to) ? shiftDay(st.to, -1) : "";
        return '<label><span>' + label + '</span><select class="in" data-f="range">' + opts + "</select></label>" +
          (custom
            ? '<label><span>' + esc(tr(L.from)) + '</span><input class="in" type="date" data-f="from" value="' + esc(DAY.test(st.from) ? st.from : String(st.from).slice(0, 10)) + '" /></label>' +
              '<label><span>' + esc(tr(L.to)) + '</span><input class="in" type="date" data-f="to" value="' + esc(to) + '" /></label>'
            : "");
      }
      if (f.kind === "multi") {
        var list = choices(k), sel = st[k];
        if (!list.length) return ""; // nothing to choose from
        var boxes = list.map(function (c, i) {
          return '<label class="ekf-opt"><input type="checkbox" id="ekf-' + k + "-" + i + '" data-m="' + k + '" value="' + esc(c.value) + '"' +
            (sel.indexOf(c.value) >= 0 ? " checked" : "") + " /><span>" + esc(valueLabel(k, c.value, options)) + runs(c.runs) + "</span></label>";
        }).join("");
        return '<fieldset class="ekf-multi" data-key="' + k + '"><legend>' + label + "</legend>" +
          '<div class="ekf-opts">' + boxes + "</div></fieldset>";
      }
      var all = f.required ? "" : '<option value="">' + esc(tr(["全部", "All"])) + "</option>";
      return '<label><span>' + label + '</span><select class="in" data-f="' + k + '">' + all +
        choices(k).map(function (c) {
          return '<option value="' + esc(c.value) + '"' + (c.value === st[k] ? " selected" : "") + ">" +
            esc(valueLabel(k, c.value, options)) + (c.runs != null ? " (" + num(c.runs) + ")" : "") + "</option>";
        }).join("") + "</select></label>";
    }

    function footHTML() {
      var foot = typeof o.foot === "function" ? o.foot() : o.foot;
      // the remembered-filters preference: per viewer, never in the URL
      var keep = o.page
        ? '<label class="ekf-scope"><input type="checkbox" id="fscope"' + (scope(o.storage) === "shared" ? " checked" : "") +
          " /><span>" + esc(tr(["在页面间保留筛选", "Keep filters across pages"])) + "</span></label>"
        : "";
      return '<span class="ekf-foot">' + (foot || "") + "</span>" + keep +
        '<span class="ekf-share"><span class="ekf-sharest" id="fsharest" role="status"></span>' +
        '<button type="button" class="linkbtn" id="fshare">' + esc(tr(["复制此视图的链接", "Copy link to this view"])) + "</button></span>" +
        '<div class="ekf-sharefb" id="fsharefb" hidden><label><span>' + esc(tr(["此视图的链接", "Link to this view"])) +
        '</span><input class="in" type="text" id="fshareurl" readonly /></label></div>';
    }

    function render() {
      // an open "copy the link" fallback stays open (with the current link)
      var fb = section.querySelector("#fsharefb"), fbOpen = !!(fb && !fb.hidden);
      panel.render({
        body: '<div class="ekf-grid">' + fields.map(fieldHTML).join("") + "</div>" + (o.extra ? o.extra() : ""),
        foot: footHTML(), count: activeCount(), summary: summary(),
      });
      if (fbOpen) {
        section.querySelector("#fsharefb").hidden = false;
        section.querySelector("#fshareurl").value = url();
      }
    }
    function sync() { panel.sync({ count: activeCount(), summary: summary() }); }

    function writeUrl() {
      var qs = serialise(st, defaults, fields);
      try { history.replaceState(history.state, "", location.pathname + (qs ? "?" + qs : "") + location.hash); } catch (e) { /* ignore */ }
      var fb = section.querySelector("#fshareurl");
      if (fb && !section.querySelector("#fsharefb").hidden) fb.value = url();
    }

    function say(msg) {
      clearTimeout(sayT);
      // a fresh text each time, so the same message is announced again
      live.textContent = "";
      sayT = setTimeout(function () { live.textContent = msg; }, 60);
    }

    // patch: { key: value | null }; null resets the key to its default
    function set(patch, how) {
      how = how || {};
      var changed = [];
      Object.keys(patch).forEach(function (k) {
        var shared = own.indexOf(k) >= 0;
        if (!shared && !isWidgetKey(k) && viewKeys.indexOf(k) < 0) throw new Error("EkteFilters: key " + k + " is not on this page");
        var v = patch[k];
        if (v == null) v = copy(defOf(k));
        else if (shared && FIELDS[k] && FIELDS[k].kind === "multi") v = [].concat(v).filter(Boolean);
        else if (shared) { v = clean(k, v); if (v === undefined) return; }
        if (same(st[k], v)) return;
        st[k] = copy(v);
        changed.push(k);
      });
      if (changed.indexOf("range") >= 0 && st.range) { st.from = ""; st.to = ""; }
      if (!changed.length) return changed;
      var filters = changed.some(function (k) { return own.indexOf(k) >= 0; });
      writeUrl();
      if (filters) {
        remember(o.page, st, fields, defaults, o.storage);
        widgets.abort(); // a newer state: what is in flight is stale
        if (how.render) render(); else sync();
        if (!how.quiet) say(Tf("筛选已更新：{n} 项生效", "Filters updated: {n} active", { n: activeCount() }));
        loadOptions();
      }
      if (o.onChange) o.onChange(state(), changed);
      return changed;
    }

    function reset() {
      var patch = {};
      own.forEach(function (k) { patch[k] = null; });
      custom = false;
      set(patch, { render: true });
    }

    function state() {
      var out = {};
      Object.keys(st).forEach(function (k) { out[k] = copy(st[k]); });
      return out;
    }
    function widgetParams(ns) { return params(st, fields, ns, viewerZone()); }
    function url() {
      var qs = serialise(st, defaults, fields);
      return location.origin + location.pathname + (qs ? "?" + qs : "");
    }

    function setOptions(data) {
      options = {};
      if (data && typeof data === "object") {
        own.forEach(function (k) {
          if (isArr(data[k])) {
            options[k] = data[k].filter(function (x) { return x && typeof x.value === "string"; });
          }
        });
      }
      render();
    }
    function loadOptions() {
      if (o.optionsUrl === false) return;
      optLoad.run({ options: { url: o.optionsUrl || "/api/filters/options", done: setOptions,
        // without option lists the fields keep their fixed values
        fail: function () { /* keep the fixed options */ } } }, function () { return widgetParams(); });
    }

    function copyLink() {
      var link = url(), fb = section.querySelector("#fsharefb"), field = section.querySelector("#fshareurl");
      var stEl = section.querySelector("#fsharest");
      var tell = function (msg) { if (stEl) stEl.textContent = msg; };
      function fallback() {
        fb.hidden = false;
        field.value = link;
        field.focus();
        field.select();
        tell(tr(["无法自动复制，请复制下面的链接。", "Could not copy automatically — copy the link from the field below."]));
      }
      try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) { fallback(); return Promise.resolve(false); }
        return navigator.clipboard.writeText(link).then(function () {
          if (!fb.hidden) field.value = link;
          tell(tr(["链接已复制", "Link copied"]));
          return true;
        }, function () { fallback(); return false; });
      } catch (e) { fallback(); return Promise.resolve(false); }
    }

    /* ---- events ---- */
    function fieldValue(el) {
      var k = el.getAttribute("data-f");
      if (k === "to") return el.value ? shiftDay(el.value, 1) : "";
      return el.value;
    }
    section.addEventListener("change", function (ev) {
      var el = ev.target;
      if (el.closest("#fshareurl")) return;
      if (el.id === "fscope") {
        // the view stays as it is; on: its shared keys go into the shared memory
        setScope(el.checked ? "shared" : "page", o.storage, { state: st, fields: fields });
        return;
      }
      var m = el.getAttribute("data-m");
      if (m) {
        var vals = Array.prototype.map.call(section.querySelectorAll('input[data-m="' + m + '"]:checked'), function (x) { return x.value; });
        var p = {}; p[m] = vals;
        return set(p);
      }
      var k = el.getAttribute("data-f");
      if (!k) return;
      if (k === "range") {
        var wasCustom = custom;
        custom = el.value === CUSTOM;
        if (custom) {
          if (!wasCustom) { set({ range: "" }, { quiet: true }); render(); }
          return;
        }
        set({ range: el.value, from: null, to: null }, { render: wasCustom });
        return;
      }
      if (k === "q" || k === "min_score") return; // on input, below
      var patch = {}; patch[k] = fieldValue(el);
      set(patch);
    });
    section.addEventListener("input", function (ev) {
      var k = ev.target.getAttribute("data-f");
      if (k !== "q" && k !== "min_score") return;
      var el = ev.target;
      clearTimeout(debounce);
      debounce = setTimeout(function () {
        if (k === "min_score" && el.validity && !el.validity.valid) return;
        var patch = {}; patch[k] = el.value;
        set(patch); // no re-render: the caret stays where it is
      }, 300);
    });
    section.addEventListener("click", function (ev) {
      if (ev.target.closest("#fshare")) copyLink();
    });
    window.addEventListener("ekte:lang", function () { render(); });

    // the URL shows the view: one from storage too, without dropped keys
    writeUrl();
    render();
    loadOptions();

    var inst = {
      state: state, widgetParams: widgetParams, set: set, reset: reset, render: render, url: url, copyLink: copyLink,
      setOptions: setOptions, panel: panel, source: init.source,
      signal: function () { return widgets.signal(); },
      load: function (ws) { return widgets.run(ws, widgetParams); },
    };
    current = inst;
    return inst;
  }

  window.EkteFilters = {
    create: create,
    state: function () { return current ? current.state() : {}; },
    widgetParams: function (ns) { return current ? current.widgetParams(ns) : ""; },
    fetchWidget: fetchWidget, keyed: keyed,
    parse: parse, serialise: serialise, params: params, initial: initial, loader: loader, viewerZone: viewerZone,
    remember: remember, scope: scope, setScope: setScope,
    FIELDS: FIELDS, UNKNOWN: UNKNOWN,
  };
})();
