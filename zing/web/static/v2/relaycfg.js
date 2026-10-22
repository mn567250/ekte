/* zing web UI v2 — guided relay configuration (audit, baseline, embedding, rerank).
 *
 * Plain browser global, no modules. Exposes:
 *   window.ZingRelayConfig.bind(opts) -> { set(values), refresh(), setKind(kind) }
 *
 * The flow, on the page's existing inputs (they stay the canonical value
 * holders, so form-submit code keeps reading input.value):
 *   0. GET /api/kb: the knowledge base's providers (with their base URLs) and
 *      the relays the user saved;
 *   1. "Relay / provider" select, inserted before the URL field;
 *   2. picking one fills in its base URL (other URLs offered in a datalist);
 *   3. the API key (optional);
 *   4. the relay's models are listed (POST /api/models) when an entry is
 *      picked and when the URL or key field changes (change event, not every
 *      keystroke); "Refresh models" retries;
 *   5. "Model to request" select over those ids — a failed or empty list
 *      falls back to the text input ("Enter manually" toggles);
 *   6. + 7. "Claimed model" select over the knowledge base's models of the
 *      form's kind, grouped by provider; a requested model the knowledge base
 *      knows (POST /api/kb/resolve, exact id or alias) is preselected.
 * The declared provider (a hidden input) is derived: the claimed model's
 * provider, else the provider the requested model resolves to. A saved relay
 * is never a declared provider. A URL the knowledge base doesn't know can be
 * saved as a relay under a name (POST /api/kb/relays).
 *
 * opts: { url, key, model, claimed?, provider?, kind?: "chat"|"embedding"|"rerank",
 *         api?: () => "auto"|"openai"|…,
 *         relayLabel?: [zh, en] }  (selectors or elements; relayLabel names the
 *         relay select, default "Relay / provider", so a page with two flows
 *         can tell them apart)
 *
 * Styling: /v2/static/fields.css (.zmp, .zmp-sel, .zmp-fetch, .zmp-status,
 * .zmp-custom from the model picker, plus .rc-*). Pure helpers are exposed as
 * ZingRelayConfig._ for the node tests (tests/test_web_relaycfg_js.py).
 */
(function () {
  "use strict";

  var OTHER = "__other__";
  var ENDPOINTS = ["/chat/completions", "/completions", "/messages", "/responses", "/embeddings", "/rerank"];

  function T(zh, en) { return window.ZING_LANG ? window.ZING_LANG.t(zh, en) : en; }
  function isZh() { return !!(window.ZING_LANG && window.ZING_LANG.isZh && window.ZING_LANG.isZh()); }
  // KB names may carry Chinese brand names: dropped in every language but CN
  // (a name that is only Chinese, e.g. a saved relay, is kept as it is).
  function nameText(s) {
    s = String(s == null ? "" : s);
    if (isZh() || !window.ZING_LANG || !window.ZING_LANG.stripCJK) return s;
    return window.ZING_LANG.stripCJK(s).trim() || s;
  }
  // "DeepSeek (DeepSeek-AI / …)" -> "DeepSeek" (the full name stays in the title)
  function shortName(s) {
    s = String(s == null ? "" : s);
    return s.split(/\s*(?:\(|—|;|,)\s*/)[0].trim() || s;
  }

  // ---------- pure helpers (tested under node) ----------
  // A typed URL as a base URL, like zing.knowledge.relays.normalize_url.
  function normUrl(url) {
    url = String(url == null ? "" : url).trim();
    if (!/^https?:\/\/[^\s/?#]+\S*$/i.test(url)) return "";
    url = url.split("#")[0].split("?")[0].replace(/\/+$/, "");
    for (var i = 0; i < ENDPOINTS.length; i++) {
      if (url.toLowerCase().slice(-ENDPOINTS[i].length) === ENDPOINTS[i]) {
        url = url.slice(0, -ENDPOINTS[i].length).replace(/\/+$/, "");
        break;
      }
    }
    return url;
  }
  // The relay select's groups: providers with base URLs, then saved relays.
  function relayGroups(providers) {
    var prov = [], relays = [];
    (providers || []).forEach(function (p) {
      if (!p || !(p.base_urls || []).length) return;
      (p.relay ? relays : prov).push(p);
    });
    return { providers: prov, relays: relays };
  }
  // The provider/relay whose base URLs contain `url` (normalized), or null.
  function matchRelay(url, providers) {
    var u = normUrl(url);
    if (!u) return null;
    for (var i = 0; i < (providers || []).length; i++) {
      var p = providers[i];
      if ((p.base_urls || []).indexOf(u) >= 0) return p;
    }
    return null;
  }
  // Claimed-model groups: per provider, its models of `kind` (chat by default).
  function claimedGroups(providers, kind) {
    var want = kind === "embedding" || kind === "rerank" ? kind : "chat";
    var out = [];
    (providers || []).forEach(function (p) {
      var ms = (p.models || []).filter(function (m) { return m && m.id && (m.kind || "chat") === want; });
      if (ms.length) out.push({ provider: p.provider, name: p.display_name || p.provider, models: ms });
    });
    return out;
  }
  // A /api/models answer as a status: ok | empty | auth | error.
  function fetchState(data) {
    if (data && data.ok) {
      var n = Array.isArray(data.models) ? data.models.length : 0;
      return { kind: n ? "ok" : "empty", count: n };
    }
    var code = data && data.status_code;
    if (code === 401 || code === 403) return { kind: "auth", code: code };
    var msg = (data && data.error) || "";
    if (code) msg = "HTTP " + code + (msg ? ": " + msg : "");
    return { kind: "error", message: msg || "?" };
  }

  // ---------- shared data ----------
  var kbPromise = null;
  function loadKb(reload) {
    if (reload || !kbPromise) {
      kbPromise = fetch("/api/kb")
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function (d) { return (d && Array.isArray(d.providers)) ? d.providers : []; })
        .catch(function () { return []; });
    }
    return kbPromise;
  }
  // GET /models answers per url|key|api (Refresh bypasses it).
  var modelCache = Object.create(null);

  function resolveEl(r) { return typeof r === "string" ? document.querySelector(r) : r || null; }
  function el(tag, cls, attrs) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }
  function opt(value, text, title) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    if (title) o.title = title;
    return o;
  }
  function fire(input) {
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
  // Name a select by the field's visible label (aria-labelledby, so the name
  // follows the label through every language switch).
  function labelBy(sel, input) {
    var l = input.id && document.querySelector('label[for="' + input.id + '"]');
    if (!l) return;
    if (!l.id) l.id = input.id + "-lab";
    sel.setAttribute("aria-labelledby", l.id);
  }
  function paintSel(sel) {
    var o = sel.options[sel.selectedIndex];
    sel.classList.toggle("is-empty", !sel.value);
    sel.title = o && sel.value ? o.title || o.textContent : "";
  }

  // A select over a text input, with an "Enter manually" toggle; the input
  // keeps the value. Used for the requested and the claimed model.
  function choice(input, onPick) {
    var wrap = el("div", "zmp zmp-unstyled rc-choice");
    input.parentNode.insertBefore(wrap, input);
    var sel = el("select", "in zmp-sel");
    var tog = el("button", "linkbtn zmp-custom", { type: "button", "aria-pressed": "false" });
    wrap.appendChild(sel);
    wrap.appendChild(input);
    var c = { wrap: wrap, sel: sel, input: input, toggle: tog, manual: false, chosen: false, hasList: true };
    c.setManual = function (on, byUser) {
      c.manual = !!on;
      if (byUser) c.chosen = true;
      sel.hidden = c.manual;
      input.hidden = !c.manual;
      tog.setAttribute("aria-pressed", String(c.manual));
      // nothing to pick from (yet): no "pick from the list" toggle
      tog.hidden = c.manual && !c.hasList;
      tog.textContent = c.manual ? T("← 从列表选择", "← Pick from the list") : T("手动输入", "Enter manually");
    };
    labelBy(sel, input);
    c.paint = function () { c.setManual(c.manual); };
    sel.addEventListener("change", function () {
      paintSel(sel);
      input.value = sel.value;
      fire(input);
      if (onPick) onPick(sel.value, sel.options[sel.selectedIndex]);
    });
    tog.addEventListener("click", function () {
      c.setManual(!c.manual, true);
      (c.manual ? input : sel).focus();
    });
    return c;
  }

  function bind(opts) {
    opts = opts || {};
    var url = resolveEl(opts.url), key = resolveEl(opts.key), model = resolveEl(opts.model);
    if (!url || !model) return null;
    var claimed = resolveEl(opts.claimed), provider = resolveEl(opts.provider);
    var kind = opts.kind || "chat";
    var relayLabel = opts.relayLabel || ["中转站 / 厂商", "Relay / provider"];
    var api = typeof opts.api === "function" ? opts.api : function () { return "auto"; };
    var base = url.id || "rc";
    var providers = [], loaded = false;

    // ---- 1 + 2: relay / provider select, before the URL field ----
    var urlGrp = url.closest(".grp");
    var rGrp = el("div", "grp rc-relay");
    var rLab = el("label", "lab", { for: base + "-relay" });
    var rWrap = el("div", "zmp zmp-unstyled");
    var rSel = el("select", "in zmp-sel rc-sel", { id: base + "-relay", "aria-describedby": base + "-relay-hint" });
    var rHint = el("div", "hint", { id: base + "-relay-hint" });
    rWrap.appendChild(rSel);
    rGrp.appendChild(rLab);
    rGrp.appendChild(rWrap);
    rGrp.appendChild(rHint);
    urlGrp.parentNode.insertBefore(rGrp, urlGrp);
    var dl = el("datalist", "", { id: base + "-urls" });
    urlGrp.appendChild(dl);
    url.setAttribute("list", dl.id);

    // Save to knowledge base: a disclosure under the URL field.
    var sv = el("div", "rc-save");
    var svT = el("button", "linkbtn zmp-custom rc-save-t", { type: "button", "aria-expanded": "false", "aria-controls": base + "-save" });
    var svBody = el("div", "rc-save-body", { id: base + "-save" });
    var svLab = el("label", "lab", { for: base + "-rname" });
    var svRow = el("div", "rc-save-row");
    var svIn = el("input", "in", { id: base + "-rname", type: "text", autocomplete: "off", spellcheck: "false", maxlength: "64" });
    var svGo = el("button", "btn sm", { type: "button" });
    var svNo = el("button", "btn sm", { type: "button" });
    var svErr = el("p", "ferr", { id: base + "-rname-err" });
    svErr.hidden = true;
    svBody.hidden = true;
    svRow.appendChild(svIn);
    svRow.appendChild(svGo);
    svRow.appendChild(svNo);
    svBody.appendChild(svLab);
    svBody.appendChild(svRow);
    svBody.appendChild(svErr);
    sv.appendChild(svT);
    sv.appendChild(svBody);
    urlGrp.appendChild(sv);

    // ---- 4 + 5: the relay's models ----
    var m = choice(model, function () { resetClaimed(); resolve(); });
    var fRow = el("div", "zmp-fetch");
    var fBtn = el("button", "btn sm zmp-fetch-btn", { type: "button" });
    var fStatus = el("span", "zmp-status", { role: "status" });
    fRow.appendChild(fBtn);
    fRow.appendChild(fStatus);
    m.wrap.insertBefore(fRow, model.nextSibling);
    m.wrap.appendChild(m.toggle);
    var fetched = [], fstate = null, fseq = 0, fctl = null, fkey = "";

    // ---- 6 + 7: the claimed model ----
    var c = null, cHint = null, cGroups = [];
    if (claimed) {
      c = choice(claimed, function (v, o) {
        c.chosen = true;
        if (!v) { resolve(); return; }
        var p = (o && o.getAttribute("data-provider")) || "";
        setProvider(p);
        paintMatch(p ? { matched: true, provider: p, model_id: v, match_confidence: "exact" } : { matched: false });
      });
      c.wrap.appendChild(c.toggle);
      cHint = el("p", "hint rc-match", { role: "status" });
      c.wrap.parentNode.appendChild(cHint);
      claimed.addEventListener("change", function () { if (c.manual) resolve(); });
    }

    // ---- painting ----
    function paintRelays() {
      var keep = rSel.value;
      var g = relayGroups(providers);
      rSel.innerHTML = "";
      rSel.appendChild(opt("", T("选择中转站或厂商…", "Select a relay or provider…")));
      [[g.providers, T("厂商", "Providers")], [g.relays, T("你保存的中转站", "Your relays")]].forEach(function (x) {
        if (!x[0].length) return;
        var og = document.createElement("optgroup");
        og.label = x[1];
        x[0].forEach(function (p) {
          var full = nameText(p.display_name || p.provider);
          og.appendChild(opt(p.provider, p.relay ? full : shortName(full), full + " — " + p.base_urls[0]));
        });
        rSel.appendChild(og);
      });
      rSel.appendChild(opt(OTHER, T("其他（手动填写地址）", "Other (enter the URL)")));
      rSel.value = keep;
      if (rSel.value !== keep) rSel.value = "";
      paintSel(rSel);
    }
    function paintUrls(p) {
      dl.innerHTML = "";
      ((p && p.base_urls) || []).forEach(function (u) { dl.appendChild(opt(u, u)); });
    }
    function syncRelay() {
      var p = matchRelay(url.value, providers);
      var v = p ? p.provider : url.value.trim() ? OTHER : rSel.value === OTHER ? OTHER : "";
      if (rSel.value !== v) { rSel.value = v; paintSel(rSel); }
      if (p) paintUrls(p);
      var savable = !p && !!normUrl(url.value);
      sv.hidden = !savable;
      if (!savable) openSave(false);
    }
    function openSave(open) {
      svT.setAttribute("aria-expanded", String(open));
      svBody.hidden = !open;
      if (!open) saveErr(null);
    }
    function saveErr(text) {
      svErr.hidden = !text;
      svErr.textContent = text || "";
      if (text) { svIn.setAttribute("aria-invalid", "true"); svIn.setAttribute("aria-describedby", svErr.id); }
      else { svIn.removeAttribute("aria-invalid"); svIn.removeAttribute("aria-describedby"); }
    }
    function paintModels() {
      var keep = model.value.trim();
      m.sel.innerHTML = "";
      m.sel.appendChild(opt("", T("选择模型…", "Select a model…")));
      fetched.forEach(function (id) { m.sel.appendChild(opt(id, id, id)); });
      m.hasList = fetched.length > 0;
      if (keep && fetched.indexOf(keep) < 0) {
        m.sel.appendChild(opt(keep, keep + " " + T("（中转站未列出）", "(not listed by the relay)")));
      }
      m.sel.value = keep;
      paintSel(m.sel);
      m.setManual(m.manual);
    }
    function paintFetch() {
      var hasUrl = !!url.value.trim(), st = fstate, k = "", text = "";
      fBtn.disabled = !hasUrl || st === "busy";
      fBtn.textContent = T("刷新模型列表", "Refresh models");
      if (st === "busy") { k = "busy"; text = T("正在获取中转站的模型…", "Listing the relay's models…"); }
      else if (st && st.kind === "ok") { k = "ok"; text = "✓ " + T("中转站列出的模型：{n}", "Models listed by the relay: {n}").replace("{n}", st.count); }
      else if (st && st.kind === "empty") { k = "warn"; text = "⚠ " + T("中转站未列出任何模型——请手动填写模型。", "The relay lists no models — enter the model manually."); }
      else if (st && st.kind === "auth") { k = "warn"; text = T("请填写 API 密钥以列出模型（HTTP {code}）。", "Enter the API key to list the models (HTTP {code}).").replace("{code}", st.code); }
      else if (st && st.kind === "error") { k = "error"; text = "✗ " + T("无法列出模型：", "Could not list the models: ") + st.message; }
      else if (!hasUrl) text = T("选择中转站或填写地址后，zing 会列出它的模型。", "Select a relay or enter its URL, and zing lists its models.");
      fStatus.className = "zmp-status" + (k ? " is-" + k : "");
      fStatus.textContent = text;
    }
    function paintClaimed() {
      if (!c) return;
      var keep = claimed.value.trim();
      cGroups = claimedGroups(providers, kind);
      c.sel.innerHTML = "";
      c.sel.appendChild(opt("", T("同请求的模型", "Same as the model to request")));
      var known = false;
      cGroups.forEach(function (g) {
        var og = document.createElement("optgroup");
        og.label = shortName(nameText(g.name));
        g.models.forEach(function (x) {
          var alias = (x.aliases || []).filter(function (a) { return a && nameText(a) === a; })[0];
          var text = alias && alias.toLowerCase() !== x.id.toLowerCase() ? x.id + " · " + alias : x.id;
          var o = opt(x.id, text, text);
          o.setAttribute("data-provider", g.provider);
          og.appendChild(o);
          if (x.id === keep) known = true;
        });
        c.sel.appendChild(og);
      });
      if (keep && !known) c.sel.appendChild(opt(keep, keep + " " + T("（知识库未收录）", "(not in the knowledge base)")));
      c.sel.value = keep;
      paintSel(c.sel);
      c.hasList = !loaded || cGroups.length > 0;
      if (loaded && !cGroups.length && !c.chosen) c.setManual(true);
    }
    var match = null;
    function paintMatch(r) {
      match = r === undefined ? match : r;
      if (!cHint) return;
      var t = "";
      var target = (claimed && claimed.value.trim()) || model.value.trim();
      if (match && match.matched && match.match_confidence !== "fuzzy") {
        t = T("模型资料：{p}", "Model profile: {p}").replace("{p}", match.provider + "/" + match.model_id);
      } else if (match && match.matched) {
        t = T("最接近的资料：{p}——若正确，请在上方选择它。", "Closest profile: {p} — select it above if it is right.").replace("{p}", match.provider + "/" + match.model_id);
      } else if (match && target) {
        t = T("知识库未收录此模型：检测不使用模型资料。", "This model is not in the knowledge base: the audit runs without a model profile.");
      }
      cHint.textContent = t;
    }
    function paintAll() {
      rLab.innerHTML = "";
      rLab.appendChild(document.createTextNode(T(relayLabel[0], relayLabel[1]) + " "));
      var o = el("span", "opt");
      o.textContent = T("可选", "Optional");
      rLab.appendChild(o);
      rHint.textContent = T("选择后会自动填写地址；不在列表中的中转站请选“其他”并填写地址。",
        "Selecting one fills in its URL; for any other relay choose “Other” and enter the URL.");
      svT.textContent = T("保存到知识库", "Save to knowledge base");
      svLab.textContent = T("中转站名称", "Name of the relay");
      svGo.textContent = T("保存", "Save");
      svNo.textContent = T("取消", "Cancel");
      paintRelays();
      paintModels();
      m.paint();
      paintFetch();
      if (c) { paintClaimed(); c.paint(); paintMatch(); }
    }

    // ---- 4: list the relay's models ----
    function listModels(force) {
      var u = url.value.trim();
      if (fctl) fctl.abort();
      fctl = null;
      if (!u) {
        fstate = null; fetched = []; fkey = "";
        paintModels();
        if (!m.chosen) m.setManual(true);
        paintFetch();
        return Promise.resolve();
      }
      var body = { base_url: u, api_key: key ? key.value.trim() : "", api: api() || "auto" };
      var ck = body.base_url + "|" + body.api_key + "|" + body.api;
      if (!force && ck === fkey) return Promise.resolve();
      fkey = ck;
      var seq = ++fseq;
      fstate = "busy";
      paintFetch();
      var cached = !force && modelCache[ck];
      var ctl = window.AbortController ? new AbortController() : null;
      fctl = ctl;
      var p = cached
        ? Promise.resolve(cached)
        : fetch("/api/models", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body), signal: ctl ? ctl.signal : undefined,
          }).then(function (r) { return r.json().catch(function () { return { error: "HTTP " + r.status }; }); });
      return p
        .then(function (data) {
          if (seq !== fseq) return;
          if (data && data.ok) modelCache[ck] = data;
          var st = fetchState(data);
          fstate = st;
          fetched = st.kind === "ok" ? data.models.slice() : [];
          paintModels();
          // a list to pick from, unless the user chose to type (or is typing)
          if (!m.chosen && document.activeElement !== model) m.setManual(!fetched.length);
          paintFetch();
        })
        .catch(function (e) {
          if (seq !== fseq || (e && e.name === "AbortError")) return;
          fstate = { kind: "error", message: String((e && e.message) || e) };
          fetched = [];
          paintModels();
          if (!m.chosen) m.setManual(true);
          paintFetch();
        })
        .then(function () { if (seq === fseq) fctl = null; });
    }

    // ---- 6 + 7: profile of the requested / claimed model; derived provider ----
    var rseq = 0;
    function resetClaimed() {
      if (c && !c.chosen && claimed.value) { claimed.value = ""; paintClaimed(); }
    }
    function setProvider(v) {
      if (!provider || v === null) return;
      if (provider.value !== v) { provider.value = v; fire(provider); }
    }
    function relayHint() {
      var p = matchRelay(url.value, providers);
      return p && !p.relay ? p.provider : null;
    }
    function resolve() {
      if (!c && !provider) return Promise.resolve();
      var target = (claimed && claimed.value.trim()) || model.value.trim();
      var seq = ++rseq;
      if (!target) { setProvider(""); paintMatch(null); return Promise.resolve(); }
      return fetch("/api/kb/resolve", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: target, provider: relayHint() }),
      })
        .then(function (r) { return r.ok ? r.json() : { matched: false }; })
        .catch(function () { return { matched: false }; })
        .then(function (r) {
          if (seq !== rseq) return;
          var sure = r && r.matched && r.match_confidence !== "fuzzy";
          setProvider(sure ? r.provider : "");
          // preselect the profile the requested model resolves to
          if (c && sure && !c.chosen && !claimed.value.trim() && !c.manual) {
            claimed.value = r.model_id;
            paintClaimed();
            fire(claimed);
          }
          paintMatch(r);
        });
    }

    // ---- events ----
    rSel.addEventListener("change", function () {
      paintSel(rSel);
      var p = null;
      providers.forEach(function (x) { if (x.provider === rSel.value) p = x; });
      paintUrls(p);
      // the URL's change event lists the relay's models
      if (p) { url.value = p.base_urls[0]; fire(url); }
    });
    url.addEventListener("input", function () { syncRelay(); paintFetch(); });
    url.addEventListener("change", function () { listModels(false); });
    if (key) key.addEventListener("change", function () { if (url.value.trim()) listModels(false); });
    fBtn.addEventListener("click", function () { listModels(true); });
    // typed model (the select's own picks go through choice's onPick)
    model.addEventListener("change", function () {
      if (!m.manual) return;
      resetClaimed();
      resolve();
    });
    svT.addEventListener("click", function () {
      var open = svT.getAttribute("aria-expanded") !== "true";
      openSave(open);
      if (open) svIn.focus();
    });
    svNo.addEventListener("click", function () { openSave(false); svT.focus(); });
    svIn.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); save(); }
      else if (e.key === "Escape") { e.preventDefault(); openSave(false); svT.focus(); }
    });
    svIn.addEventListener("input", function () { if (svIn.value.trim()) saveErr(null); });
    svGo.addEventListener("click", save);
    function save() {
      var name = svIn.value.trim();
      if (!name) { saveErr(T("请填写中转站名称。", "Enter a name for the relay.")); svIn.focus(); return; }
      svGo.disabled = true;
      fetch("/api/kb/relays", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, base_url: url.value.trim() }),
      })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) {
            saveErr(T("无法保存：", "Could not save: ") + (window.ZING_LANG ? window.ZING_LANG.server(res.d.error || "?") : res.d.error || "?"));
            svIn.focus();
            return;
          }
          svIn.value = "";
          openSave(false);
          return loadKb(true).then(function (list) {
            window.dispatchEvent(new CustomEvent("zing:kb", { detail: list }));
            rSel.value = res.d.provider;
            paintSel(rSel);
            fStatus.className = "zmp-status is-ok";
            fStatus.textContent = "✓ " + T("已将“{name}”保存到知识库。", "Saved “{name}” to the knowledge base.").replace("{name}", res.d.display_name);
            rSel.focus();
          });
        })
        .catch(function (e) { saveErr(T("无法保存：", "Could not save: ") + String((e && e.message) || e)); })
        .then(function () { svGo.disabled = false; });
    }
    window.addEventListener("zing:kb", function (e) {
      providers = e.detail || providers;
      paintRelays();
      syncRelay();
      paintClaimed();
    });
    window.addEventListener("zing:lang", paintAll);

    // ---- init ----
    m.hasList = false;
    m.setManual(true);
    if (c) c.setManual(false);
    sv.hidden = true;
    paintAll();
    var ready = loadKb(false).then(function (list) {
      providers = list;
      loaded = true;
      paintRelays();
      syncRelay();
      paintClaimed();
      if (c) c.paint();
    });

    return {
      ready: ready,
      // Fill the fields (e.g. a re-run from History); the relay's models are listed.
      set: function (v) {
        return ready.then(function () {
          url.value = v.url || "";
          model.value = v.model || "";
          if (claimed) { claimed.value = v.claimed || ""; c.chosen = !!v.claimed; paintClaimed(); }
          if (provider && v.provider != null) provider.value = v.provider;
          syncRelay();
          paintModels();
          var p = matchRelay(url.value, providers);
          paintUrls(p);
          return listModels(false).then(resolve);
        });
      },
      refresh: function () { return listModels(true); },
      // Switch the claimed-model list to another kind (the audit page's endpoint type).
      setKind: function (k) {
        k = k || "chat";
        if (k === kind) return;
        kind = k;
        if (!c) return;
        // a claimed model of the other kind does not carry over
        claimed.value = "";
        c.chosen = false;
        c.setManual(false);
        paintClaimed();  // back to manual entry when this kind has no models
        c.paint();
      },
    };
  }

  window.ZingRelayConfig = {
    bind: bind,
    _: {
      normUrl: normUrl, relayGroups: relayGroups, matchRelay: matchRelay, claimedGroups: claimedGroups,
      fetchState: fetchState, shortName: shortName,
    },
  };
})();
