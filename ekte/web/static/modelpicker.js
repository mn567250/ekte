/* zing web UI — reusable, page-agnostic claimed-model picker.
 *
 * Plain browser global, no modules, no external deps. Exposes:
 *   window.ZingModelPicker.enhance({ claimedInput, providerInput, label })
 *
 * Turns an EXISTING claimed-model text <input> into a compact two-step picker:
 *   供应商 (provider) <select>  →  模型 (model) <select>
 * The original input stays in the DOM as the canonical value holder (hidden in
 * select mode), so any form-submit code that reads `input.value` keeps working.
 * Selecting a model writes its id into the input and fires input+change events.
 *
 * A "自定义输入" / "← 选择模型" ("Custom input" / "← Pick a model" in EN) text toggle flips to free-text mode, which simply
 * re-shows the original input for manual typing, and back. On init: if the input
 * already holds a value that is NOT a known model id, it starts in custom mode
 * showing that value; otherwise it starts in select mode.
 *
 * Data: GET /api/kb (cached at module scope as a single shared promise). If the
 * fetch fails, enhance() is a no-op and the page keeps its plain text input.
 *
 * Relay models: when the page passes `urlInput` (and optionally `keyInput`),
 * a "Fetch models" button is shown for every provider. It POSTs /api/models,
 * which lists the relay's own /models — instant connection feedback plus the
 * exact ids it accepts. The API key is optional (self-hosted Ollama / LM Studio
 * need none). The provider list gains "Custom (from relay)", which lists only
 * the fetched ids; a knowledge-base provider keeps its own models and, once
 * fetched, adds the relay's ids the knowledge base does not know yet (a
 * "Relay only" group), so a model newer than the knowledge base can still be
 * picked. A fetched id is written into `modelInput` (the requested model;
 * defaults to `claimedInput`). `api` is an optional function returning the
 * page's protocol choice ("auto" default).
 *
 * Styling: keyed off the page CSS vars (--line, --teal, --ink, --ink2, --sans,
 * #fbfdfa input bg) so it visually matches the .in / select look on every page.
 *
 * `unstyled: true` (the v2 UI, with /v2/static/fields.css) skips every inline
 * style and exposes class hooks instead: wrapper .zmp.zmp-unstyled, rows
 * .zmp-sels / .zmp-fetch, selects .in.zmp-sel (.zmp-prov / .zmp-model, plus
 * .is-empty while the placeholder is shown), the relay button .btn.sm
 * .zmp-fetch-btn, its status .zmp-status (.is-busy/.is-ok/.is-warn/.is-error)
 * and the mode toggle .linkbtn.zmp-custom[aria-pressed]. Both selects get a
 * translated aria-label; options and selects carry the full label as `title`,
 * and provider names are shortened ("DeepSeek (DeepSeek-AI / …)" → "DeepSeek").
 *
 * Usage (per-page agent copy):
 *   ZingModelPicker.enhance({ claimedInput: "#e-claimed", providerInput: "#e-provider" });
 */
(function () {
  "use strict";

  var _kbPromise = null; // shared across every enhance() call on the page
  var CUSTOM = "__custom__"; // provider-select value of the relay-fetched list

  // UI language (lang.js): CN keeps the original strings, others translate.
  function isEn() {
    return !!(window.ZING_LANG && !window.ZING_LANG.isZh());
  }
  function tr(zh, en) {
    return window.ZING_LANG ? window.ZING_LANG.t(zh, en) : zh;
  }
  // KB display names / aliases may contain Chinese brand names; drop them
  // in every language but CN.
  function enText(s) {
    return isEn() ? window.ZING_LANG.stripCJK(s) : s;
  }

  function loadKb() {
    if (_kbPromise == null) {
      _kbPromise = fetch("/api/kb")
        .then(function (r) {
          if (!r.ok) throw new Error("kb http " + r.status);
          return r.json();
        })
        .then(function (data) {
          var providers = (data && data.providers) || [];
          return Array.isArray(providers) ? providers : [];
        });
    }
    return _kbPromise;
  }

  function resolveEl(ref) {
    if (ref == null) return null;
    if (typeof ref === "string") return document.querySelector(ref);
    return ref; // assume an element
  }

  // Set of every known model id across all providers (for init mode detection).
  function knownIds(providers) {
    var ids = Object.create(null);
    providers.forEach(function (p) {
      (p.models || []).forEach(function (m) {
        if (m && m.id) ids[m.id] = true;
      });
    });
    return ids;
  }

  // Minimal inline styles keyed off the page's CSS vars so the picker matches
  // the local .in / select look without needing the page to ship extra CSS.
  function styleSelect(sel) {
    sel.style.width = "100%";
    sel.style.border = "1.5px solid var(--line, #e7ece5)";
    sel.style.background = "#fbfdfa";
    sel.style.borderRadius = "13px";
    sel.style.fontFamily = "var(--sans, system-ui, sans-serif)";
    sel.style.fontWeight = "500";
    sel.style.fontSize = "15.5px";
    sel.style.color = "var(--ink, #0c211e)";
    sel.style.padding = "12px 13px";
    sel.style.outline = "none";
    sel.style.cursor = "pointer";
    sel.addEventListener("focus", function () {
      sel.style.borderColor = "var(--teal, #0f6f5f)";
      sel.style.boxShadow = "0 0 0 4px rgba(15,111,95,.12)";
    });
    sel.addEventListener("blur", function () {
      sel.style.borderColor = "var(--line, #e7ece5)";
      sel.style.boxShadow = "none";
    });
  }

  function opt(value, text, title) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    if (title) o.title = title;
    return o;
  }

  // Short provider name for the unstyled (v2) picker: the part before the
  // first parenthesis, em dash, semicolon or comma, e.g.
  // "Alibaba Cloud — Qwen / …" → "Alibaba Cloud". The full name stays in
  // the option's title.
  function shortName(s) {
    s = String(s == null ? "" : s);
    var cut = s.split(/\s*(?:\(|\u2014|;|,)\s*/)[0].trim();
    return cut || s;
  }

  function enhance(opts) {
    opts = opts || {};
    var claimedInput = resolveEl(opts.claimedInput);
    if (!claimedInput) return; // nothing to enhance
    var providerInput = resolveEl(opts.providerInput); // optional
    var relay = {
      urlInput: resolveEl(opts.urlInput), // optional: enables the custom provider
      keyInput: resolveEl(opts.keyInput),
      modelInput: resolveEl(opts.modelInput) || claimedInput,
      api: typeof opts.api === "function" ? opts.api : null,
    };

    loadKb()
      .then(function (providers) {
        if (!providers.length && !relay.urlInput) return; // nothing to offer
        build(claimedInput, providerInput, providers, opts.label, relay, !!opts.unstyled);
      })
      .catch(function () {
        // Defensive: any failure leaves the original input untouched.
      });
  }

  function build(claimedInput, providerInput, providers, label, relay, unstyled) {
    var ids = knownIds(providers);
    // Inline styles only for the classic (styled) picker.
    function css(el, prop, value) {
      if (!unstyled) el.style[prop] = value;
    }

    // Container inserted right before the original input; the input is moved
    // inside it so "free-text mode" can re-show it in place.
    var wrap = document.createElement("div");
    wrap.className = unstyled ? "zmp zmp-unstyled" : "zmp";
    css(wrap, "display", "flex");
    css(wrap, "flexDirection", "column");
    css(wrap, "gap", "8px");

    var parent = claimedInput.parentNode;
    parent.insertBefore(wrap, claimedInput);

    // The two selects live in their own row container so we can hide/show them
    // as a unit when toggling to custom mode.
    var selectRow = document.createElement("div");
    if (unstyled) selectRow.className = "zmp-sels";
    css(selectRow, "display", "flex");
    css(selectRow, "flexDirection", "column");
    css(selectRow, "gap", "8px");

    var provSel = document.createElement("select");
    var modelSel = document.createElement("select");
    if (unstyled) {
      provSel.className = "in zmp-sel zmp-prov";
      modelSel.className = "in zmp-sel zmp-model";
    } else {
      styleSelect(provSel);
      styleSelect(modelSel);
    }

    // v2: the field's own <label for> names the selects (it points at the
    // text input, which is hidden while the selects are shown); technical
    // key chips and the "optional" suffix are left out of the name.
    function fieldLabel() {
      if (!claimedInput.id || !document.querySelector) return "";
      var el = document.querySelector('label[for="' + claimedInput.id + '"]');
      if (!el) return "";
      var c = el.cloneNode(true);
      var drop = c.querySelectorAll ? c.querySelectorAll(".key,.opt") : [];
      for (var i = 0; i < drop.length; i++) drop[i].parentNode.removeChild(drop[i]);
      return (c.textContent || "").replace(/\s+/g, " ").trim();
    }

    function paintLabels() {
      var lbl = typeof label === "function" ? label() : label;
      if (!lbl && unstyled) lbl = fieldLabel();
      if (lbl) {
        provSel.setAttribute("aria-label", lbl + tr(" 供应商", " provider"));
        modelSel.setAttribute("aria-label", lbl + tr(" 模型", " model"));
      } else if (unstyled) {
        provSel.setAttribute("aria-label", tr("供应商", "Provider"));
        modelSel.setAttribute("aria-label", tr("模型", "Model"));
      }
    }
    paintLabels();

    // v2: the chosen option's full text as the select's tooltip, and an
    // .is-empty hook while the placeholder is shown.
    function paintSel(sel) {
      if (!unstyled) return;
      var o = sel.options[sel.selectedIndex];
      var empty = !sel.value;
      sel.classList.toggle("is-empty", empty);
      sel.title = o && !empty ? o.title || o.textContent : "";
    }

    function fillProviders() {
      var keep = provSel.value;
      provSel.innerHTML = "";
      provSel.appendChild(opt("", tr("选择供应商…", "Select provider…")));
      providers.forEach(function (p) {
        var full = enText(p.display_name || p.provider) || p.provider;
        if (unstyled) provSel.appendChild(opt(p.provider, shortName(full), full));
        else provSel.appendChild(opt(p.provider, full));
      });
      if (relay.urlInput) {
        provSel.appendChild(opt(CUSTOM, tr("自定义（从中转站获取）", "Custom (from relay)")));
      }
      provSel.value = keep;
      paintSel(provSel);
    }
    fillProviders();
    modelSel.appendChild(opt("", tr("选择模型…", "Select model…")));
    modelSel.disabled = true;
    paintSel(modelSel);

    selectRow.appendChild(provSel);

    // "Fetch models" button + status line, shown for every provider whenever
    // the page has a relay URL field (it lives in selectRow, so custom-input
    // mode hides it too).
    var fetchRow = document.createElement("div");
    fetchRow.style.display = "none";
    css(fetchRow, "alignItems", "center");
    css(fetchRow, "flexWrap", "wrap");
    css(fetchRow, "gap", "10px");
    var fetchBtn = document.createElement("button");
    fetchBtn.type = "button";
    css(fetchBtn, "font", "inherit");
    css(fetchBtn, "fontSize", "13px");
    css(fetchBtn, "fontWeight", "700");
    css(fetchBtn, "fontFamily", "var(--sans, system-ui, sans-serif)");
    css(fetchBtn, "color", "#fff");
    css(fetchBtn, "background", "var(--teal, #0f6f5f)");
    css(fetchBtn, "border", "0");
    css(fetchBtn, "borderRadius", "10px");
    css(fetchBtn, "padding", "8px 14px");
    css(fetchBtn, "cursor", "pointer");
    var fetchStatus = document.createElement("span");
    css(fetchStatus, "fontSize", "12.5px");
    css(fetchStatus, "fontFamily", "var(--sans, system-ui, sans-serif)");
    css(fetchStatus, "color", "var(--ink2, #4a5d59)");
    css(fetchStatus, "wordBreak", "break-word");
    if (unstyled) {
      fetchRow.className = "zmp-fetch";
      fetchBtn.className = "btn sm zmp-fetch-btn";
      fetchStatus.className = "zmp-status";
      fetchStatus.setAttribute("role", "status");
    }
    fetchRow.appendChild(fetchBtn);
    fetchRow.appendChild(fetchStatus);
    selectRow.appendChild(fetchRow);

    selectRow.appendChild(modelSel);

    // Toggle link between select mode and free-text (custom) mode.
    var toggle = document.createElement("button");
    toggle.type = "button";
    if (unstyled) toggle.className = "linkbtn zmp-custom";
    css(toggle, "alignSelf", "flex-start");
    css(toggle, "font", "inherit");
    css(toggle, "fontSize", "12px");
    css(toggle, "fontWeight", "700");
    css(toggle, "fontFamily", "var(--sans, system-ui, sans-serif)");
    css(toggle, "color", "var(--teal, #0f6f5f)");
    css(toggle, "background", "none");
    css(toggle, "border", "0");
    css(toggle, "padding", "0");
    css(toggle, "cursor", "pointer");

    wrap.appendChild(selectRow);
    // Move the original input into the wrap so it shows in custom mode in place.
    wrap.appendChild(claimedInput);
    wrap.appendChild(toggle);

    // ---- Custom provider: models fetched from the relay ----------------- //
    var fetched = []; // ids from the last successful fetch
    var fetchState = null; // null | "loading" | {ok, count} | {error}

    function isCustom() {
      return provSel.value === CUSTOM;
    }

    function paintFetch() {
      fetchRow.style.display = relay.urlInput ? "flex" : "none";
      var hasUrl = !!(relay.urlInput && relay.urlInput.value.trim());
      var loading = fetchState === "loading";
      fetchBtn.disabled = !hasUrl || loading;
      css(fetchBtn, "opacity", fetchBtn.disabled ? "0.5" : "1");
      css(fetchBtn, "cursor", fetchBtn.disabled ? "not-allowed" : "pointer");
      fetchBtn.textContent = tr("获取模型列表", "Fetch models");
      fetchBtn.title = hasUrl ? "" : tr("请先填写 base_url", "Enter the base_url first");
      var st = fetchState;
      var kind = "";
      if (st === "loading") {
        kind = "busy";
        css(fetchStatus, "color", "var(--ink2, #4a5d59)");
        fetchStatus.textContent = tr("正在获取模型…", "Fetching models…");
      } else if (st && st.error) {
        kind = "error";
        css(fetchStatus, "color", "var(--red, #b3261e)");
        fetchStatus.textContent = "✗ " + tr("连接失败", "Connection failed") + " — " + st.error;
      } else if (st && st.count === 0) {
        kind = "warn";
        css(fetchStatus, "color", "var(--amber, #9a6700)");
        fetchStatus.textContent = "⚠ " + tr("中转站未返回任何模型", "The relay returned no models");
      } else if (st) {
        kind = "ok";
        css(fetchStatus, "color", "var(--teal, #0f6f5f)");
        fetchStatus.textContent = "✓ " + tr("已找到模型：", "Models found:") + " " + st.count;
      } else {
        fetchStatus.textContent = "";
      }
      if (unstyled) fetchStatus.className = "zmp-status" + (kind ? " is-" + kind : "");
    }

    function fillFetched() {
      modelSel.innerHTML = "";
      modelSel.appendChild(
        opt("", fetched.length ? tr("选择模型…", "Select model…") : tr("请先获取模型…", "Fetch models first…"))
      );
      fetched.forEach(function (id) {
        modelSel.appendChild(opt(id, id, unstyled ? id : ""));
      });
      modelSel.disabled = fetched.length === 0;
      var cur = (relay.modelInput.value || "").trim();
      if (cur && fetched.indexOf(cur) !== -1) modelSel.value = cur;
      paintSel(modelSel);
    }

    function fetchModels() {
      var url = relay.urlInput ? relay.urlInput.value.trim() : "";
      if (!url) return;
      fetchState = "loading";
      paintFetch();
      fetch("/api/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: url,
          api_key: relay.keyInput ? relay.keyInput.value.trim() : "",
          api: relay.api ? relay.api() || "auto" : "auto",
        }),
      })
        .then(function (r) {
          return r.json().catch(function () {
            return { error: "HTTP " + r.status };
          });
        })
        .then(function (data) {
          if (data && data.ok) {
            fetched = Array.isArray(data.models) ? data.models : [];
            fetchState = { ok: true, count: fetched.length };
          } else {
            fetched = [];
            var msg = (data && data.error) || "";
            if (data && data.status_code) msg = "HTTP " + data.status_code + (msg ? ": " + msg : "");
            fetchState = { error: msg || "?" };
          }
        })
        .catch(function (e) {
          fetched = [];
          fetchState = { error: String((e && e.message) || e) };
        })
        .then(function () {
          if (isCustom()) fillFetched();
          else if (provSel.value) {
            var keep = modelSel.value;
            fillModels(provSel.value);
            modelSel.value = keep;
            paintSel(modelSel);
          }
          paintFetch();
        });
    }

    fetchBtn.addEventListener("click", fetchModels);
    if (relay.urlInput) relay.urlInput.addEventListener("input", paintFetch);

    function fillModels(providerId) {
      if (providerId === CUSTOM) {
        fillFetched();
        return null;
      }
      modelSel.innerHTML = "";
      modelSel.appendChild(opt("", tr("选择模型…", "Select model…")));
      var prov = null;
      for (var i = 0; i < providers.length; i++) {
        if (providers[i].provider === providerId) {
          prov = providers[i];
          break;
        }
      }
      var models = (prov && prov.models) || [];
      var listed = Object.create(null); // ids the relay's /models returned
      fetched.forEach(function (id) {
        listed[id] = true;
      });
      models.forEach(function (m) {
        if (!m || !m.id) return;
        var aliases = (m.aliases || []).filter(function (a) {
          return !isEn() || (a && window.ZING_LANG.stripCJK(a) === a);
        });
        var alias = aliases.length ? aliases[0] : "";
        // Show id, with a short alias hint when it differs from the id.
        var text =
          alias && alias.toLowerCase() !== m.id.toLowerCase()
            ? m.id + " · " + alias
            : m.id;
        if (listed[m.id]) text += " ✓";
        modelSel.appendChild(opt(m.id, text, unstyled ? text : ""));
      });
      // Relay ids the knowledge base doesn't know (e.g. a model released after
      // it was last updated): still pickable, so a stale KB never blocks a run.
      var extra = fetched.filter(function (id) {
        return !ids[id];
      });
      if (extra.length) {
        var grp = document.createElement("optgroup");
        grp.label = tr("仅中转站提供（知识库未收录）", "Relay only (not in knowledge base)");
        extra.forEach(function (id) {
          grp.appendChild(opt(id, id, unstyled ? id : ""));
        });
        modelSel.appendChild(grp);
      }
      modelSel.disabled = models.length + extra.length === 0;
      paintSel(modelSel);
      return prov;
    }

    function setClaimed(value) {
      claimedInput.value = value;
      claimedInput.dispatchEvent(new Event("input", { bubbles: true }));
      claimedInput.dispatchEvent(new Event("change", { bubbles: true }));
    }

    provSel.addEventListener("change", function () {
      var pid = provSel.value;
      paintSel(provSel);
      fillModels(pid);
      paintFetch();
      if (providerInput && pid && pid !== CUSTOM) {
        providerInput.value = pid;
        providerInput.dispatchEvent(new Event("input", { bubbles: true }));
        providerInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    modelSel.addEventListener("change", function () {
      paintSel(modelSel);
      if (!modelSel.value) return;
      if (isCustom() || !ids[modelSel.value]) {
        // A relay-listed id is what the relay accepts: the requested model.
        relay.modelInput.value = modelSel.value;
        relay.modelInput.dispatchEvent(new Event("input", { bubbles: true }));
        relay.modelInput.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        setClaimed(modelSel.value);
      }
    });

    // ---- Mode switching ------------------------------------------------- //
    var custom = false;

    function applyMode() {
      if (custom) {
        selectRow.style.display = "none";
        claimedInput.style.display = "";
        toggle.textContent = tr("← 选择模型", "← Pick a model");
      } else {
        selectRow.style.display = "";
        claimedInput.style.display = "none";
        toggle.textContent = tr("自定义输入", "Custom input");
      }
      if (unstyled) toggle.setAttribute("aria-pressed", custom ? "true" : "false");
    }

    toggle.addEventListener("click", function () {
      custom = !custom;
      applyMode();
      if (custom) claimedInput.focus();
    });

    // ---- Initial mode --------------------------------------------------- //
    var current = (claimedInput.value || "").trim();
    if (current && !ids[current]) {
      // Existing value isn't a known model id → free-text mode showing it.
      custom = true;
    } else if (current && ids[current]) {
      // Pre-select the matching provider + model in the selects.
      for (var i = 0; i < providers.length; i++) {
        var p = providers[i];
        var hit = (p.models || []).some(function (m) {
          return m && m.id === current;
        });
        if (hit) {
          provSel.value = p.provider;
          fillModels(p.provider);
          modelSel.value = current;
          paintSel(provSel);
          paintSel(modelSel);
          if (providerInput && !providerInput.value) providerInput.value = p.provider;
          break;
        }
      }
    }
    paintFetch();
    applyMode();

    // Re-label everything in place when the UI language changes.
    window.addEventListener("zing:lang", function () {
      var keepModel = modelSel.value;
      paintLabels();
      fillProviders();
      if (provSel.value) {
        fillModels(provSel.value);
        modelSel.value = keepModel;
        paintSel(modelSel);
      } else {
        modelSel.options[0].textContent = tr("选择模型…", "Select model…");
      }
      paintFetch();
      applyMode();
    });
  }

  window.ZingModelPicker = { enhance: enhance };
})();
