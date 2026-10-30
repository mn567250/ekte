/* zing web UI v2 — Knowledge page: one section component for every tab.
 *
 * Each tab (models, providers, relays) is the same thing: the complete set of
 * its items — packaged, ZING_KB_DIR and the user's own, the latter marked with
 * a "Yours" badge — each with an on/off switch, a delete button for the
 * user's own items, and an "Add …" form. One filter above the tabs (kb.html)
 * applies to every section. Only a small config differs per tab (kb.html).
 * Pure data helpers live in kbview.js.
 *
 * The tab panel holds a static skeleton (so lang.js translates it):
 *   [data-kb=title]     the h2 (tabindex=-1: focus lands here after a delete)
 *   [data-kb=count]     totals next to it ("98 models · 2 yours · 1 off")
 *   [data-kb=add]       <details> holding the add form, built by cfg.add
 *   [data-kb=list]      the items
 *
 * ZingKbSection.mount(panel, cfg, page) → { render() }
 *   cfg.kind     "models" | "providers" | "relays" (the key in the API data)
 *   cfg.groupBy  optional item field: items are grouped in <details>
 *   cfg.group(g) the html of a group's summary
 *   cfg.name(it) the html of an item's name
 *   cfg.meta(it) [html…] shown under the name
 *   cfg.count(s) the totals text from kbview.summary()
 *   cfg.add(el, page) builds the add form into el
 *   page.data()  the last GET /api/kb/profiles answer
 *   page.reload() refetch and re-render every section (Promise)
 *   page.filters() the shared filters ({ model, provider, relay, source },
 *                 kbview.matches)
 * Returns { render(), rendered(), filter() → { n, total }, openAdd(focus) };
 * filter() re-applies page.filters() after they change.
 *
 * Add forms (ZingKbSection.wizard / relayForm) carry Chinese text with data-en
 * like the static markup and are translated with ZING_LANG.apply(), so a
 * language switch keeps what the user typed.
 */
(function () {
  "use strict";

  var V = window.ZingKbView._;
  var L = window.ZING_LANG;

  function T(zh, en) { return window.T ? window.T(zh, en) : en; }
  function Tf(zh, en, vals) {
    var s = T(zh, en);
    Object.keys(vals || {}).forEach(function (k) { s = s.split("{" + k + "}").join(String(vals[k])); });
    return s;
  }
  function icon(name, opts) { return typeof window.zingIcon === "function" ? window.zingIcon(name, opts) : ""; }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function translate(el) { if (L && L.apply) L.apply(el); }
  function send(method, url, body) {
    var init = { method: method };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    return fetch(url, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
    });
  }
  // busy buttons stay focusable: aria-disabled, not disabled
  function setBusy(btn, busy) {
    if (busy) btn.setAttribute("aria-disabled", "true"); else btn.removeAttribute("aria-disabled");
  }
  function isBusy(btn) { return btn.getAttribute("aria-disabled") === "true"; }

  function sourceBadge(src) {
    var k = V.sourceKind(src);
    if (k === "yours") return '<span class="badge good">' + esc(T("你的", "Yours")) + "</span>";
    if (k === "kbdir") return '<span class="badge sky" title="' + esc(V.sourceFile(src)) + '">ZING_KB_DIR</span>';
    return '<span class="badge grey">' + esc(T("内置", "Packaged")) + "</span>";
  }
  function sourceText(src) {
    var k = V.sourceKind(src), f = V.sourceFile(src);
    if (k === "yours") return Tf("你的条目 {id}", "your entry {id}", { id: f });
    if (k === "kbdir") return "ZING_KB_DIR " + f;
    return Tf("内置 {file}", "packaged {file}", { file: f });
  }

  // ---- the section --------------------------------------------------------- //
  function mount(panel, cfg, page) {
    var q = function (k) { return panel.querySelector('[data-kb="' + k + '"]'); };
    var title = q("title"), count = q("count"), list = q("list");
    var addBox = q("add");
    var ui = {};        // per item key: { confirm, msg }
    var openGroups = {}; // group key -> true while the user has it open
    var rendered = false;
    var prefix = cfg.kind;

    function st(key) { return ui[key] || (ui[key] = {}); }

    if (addBox && cfg.add) cfg.add(addBox.querySelector("[data-kb=add-body]"), page);

    function row(it, i) {
      var s = st(it.key), id = prefix + "-i" + i;
      var userKb = page.data().user_kb !== false;
      var meta = (cfg.meta(it) || []).filter(Boolean);
      var actions = "";
      if (it.yours && it.entry_id != null && userKb) {
        actions = s.confirm
          ? '<span class="ask">' + esc(T("删除这个条目？", "Delete this entry?")) + "</span>" +
            '<button type="button" class="btn sm danger" data-act="del-yes" data-key="' + esc(it.key) + '">' + icon("trash") + esc(T("删除", "Delete")) + "</button>" +
            '<button type="button" class="btn sm" data-act="del-no" data-key="' + esc(it.key) + '">' + esc(T("取消", "Cancel")) + "</button>"
          : '<button type="button" class="btn sm danger" data-act="del" data-key="' + esc(it.key) + '" aria-describedby="' + id + '-n">' +
            icon("trash") + esc(T("删除", "Delete")) + "</button>";
      }
      return (
        '<li class="card item' + (it.enabled ? "" : " off") + '" data-key="' + esc(it.key) + '">' +
          '<div class="what"><span class="nm" id="' + id + '-n">' + cfg.name(it) + "</span> " + sourceBadge(it.source) +
            (meta.length ? '<span class="meta">' + meta.join(' <span class="sep" aria-hidden="true">·</span> ') + "</span>" : "") +
          "</div>" +
          (actions ? '<span class="acts">' + actions + "</span>" : "") +
          '<label class="switch"><input type="checkbox" role="switch" data-act="on" data-key="' + esc(it.key) + '"' +
            ' aria-labelledby="' + id + "-n " + id + '-s"' + (it.enabled ? " checked" : "") + (userKb ? "" : " disabled") +
            '><span></span> <em class="sw-t" id="' + id + '-s">' + esc(it.enabled ? T("启用中", "Enabled") : T("已停用", "Disabled")) + "</em></label>" +
          (s.msg ? '<span class="hint" role="status">' + esc(s.msg()) + "</span>" : "") +
        "</li>"
      );
    }

    function render() {
      var data = page.data();
      if (!data) return;
      rendered = true;
      var items = V.itemsOf(data, cfg.kind);
      count.textContent = cfg.count(V.summary(items));
      // keep focus on the same control across the re-render (Delete -> Cancel …)
      var a = document.activeElement, keep = null;
      if (a && list.contains(a) && a.getAttribute("data-act")) keep = [a.getAttribute("data-act"), a.getAttribute("data-key")];
      var i = 0, html;
      if (!items.length) {
        html = '<p class="empty">' + esc(cfg.empty()) + "</p>";
      } else if (cfg.groupBy) {
        html = V.groups(items, cfg.groupBy).map(function (g) {
          return '<details class="card grp" data-group="' + esc(g.key) + '"' + (openGroups[g.key] ? " open" : "") +
            "><summary>" + cfg.group(g) + '</summary><ul class="items">' +
            g.items.map(function (it) { return row(it, i++); }).join("") + "</ul></details>";
        }).join("");
      } else {
        html = '<ul class="items">' + items.map(function (it) { return row(it, i++); }).join("") + "</ul>";
      }
      list.innerHTML = html + '<p class="empty" data-kb="none" hidden>' + esc(T("没有符合筛选条件的项。", "Nothing matches the filters.")) + "</p>";
      applyFilter();
      if (keep) {
        var alt = { del: "del-no", "del-no": "del", "del-yes": "del" }[keep[0]] || keep[0];
        var sel = function (act) { return '[data-act="' + act + '"][data-key="' + cssEsc(keep[1]) + '"]'; };
        var to = list.querySelector(sel(keep[0])) || list.querySelector(sel(alt));
        if (to) {
          var g = to.closest("details");
          if (g) g.open = true;
          to.focus();
        } else title.focus();
      }
    }

    function cssEsc(s) {
      return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, "\\$&");
    }

    // Filtering hides rows instead of rebuilding them: cheap, and focus stays.
    function applyFilter() {
      var data = page.data();
      if (!data) return { n: 0, total: 0 };
      var items = V.itemsOf(data, cfg.kind);
      var f = page.filters(), on = V.active(f) > 0;
      var hit = {};
      items.forEach(function (it) { if (V.matches(cfg.kind, it, f)) hit[it.key] = true; });
      var n = 0;
      Array.prototype.forEach.call(list.querySelectorAll("li.item"), function (li) {
        var show = !on || hit[li.getAttribute("data-key")];
        li.hidden = !show;
        if (show) n++;
      });
      Array.prototype.forEach.call(list.querySelectorAll("details.grp"), function (d) {
        var any = d.querySelector("li.item:not([hidden])");
        d.hidden = !any;
        if (on && any) d.open = true;
        // clearing the filters closes what the user had not opened, unless
        // focus is inside (it would fall to <body>)
        else if (!on) d.open = !!openGroups[d.getAttribute("data-group")] || d.contains(document.activeElement);
      });
      var none = list.querySelector('[data-kb="none"]');
      if (none) none.hidden = !(items.length && !n);
      return { n: n, total: items.length };
    }
    list.addEventListener("toggle", function (ev) {
      var d = ev.target;
      // only the user's own opening/closing is remembered, not the filter's
      if (d.classList && d.classList.contains("grp") && !V.active(page.filters())) openGroups[d.getAttribute("data-group")] = d.open;
    }, true);

    list.addEventListener("click", function (ev) {
      var t = ev.target.closest("button[data-act]");
      if (!t) return;
      var key = t.getAttribute("data-key"), act = t.getAttribute("data-act"), s = st(key);
      var it = V.itemsOf(page.data(), cfg.kind).filter(function (x) { return x.key === key; })[0];
      if (!it) return;
      if (act === "del") { s.confirm = true; s.msg = null; render(); }
      else if (act === "del-no") { s.confirm = false; render(); }
      else if (act === "del-yes") {
        if (isBusy(t)) return;
        setBusy(t, true);
        send("DELETE", "/api/kb/entries/" + it.entry_id).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          delete ui[key];
          return page.reload().then(function () { title.focus(); });
        }).catch(function () {
          s.confirm = false;
          s.msg = function () { return T("无法更新这个条目，请重试。", "Could not update the entry — please try again."); };
          render();
        });
      }
    });

    list.addEventListener("change", function (ev) {
      var t = ev.target;
      if (t.getAttribute("data-act") !== "on") return;
      var key = t.getAttribute("data-key"), on = t.checked, s = st(key);
      // optimistic: this row only; the reload brings the rest (counts, notes)
      var li = t.closest("li.item"), lab = li && li.querySelector(".sw-t");
      if (li) li.classList.toggle("off", !on);
      if (lab) lab.textContent = on ? T("启用中", "Enabled") : T("已停用", "Disabled");
      s.msg = null;
      send("PUT", "/api/kb/enabled", { key: key, enabled: on }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return page.reload();
      }).catch(function () {
        t.checked = !on;
        if (li) li.classList.toggle("off", on);
        s.msg = function () { return T("无法更新这个条目，请重试。", "Could not update the entry — please try again."); };
        render();
      });
    });

    return {
      render: render,
      rendered: function () { return rendered; },
      filter: applyFilter,
      openAdd: function (focus) {
        if (!addBox) return;
        addBox.open = true;
        if (focus) addBox.querySelector("summary").focus();
      },
    };
  }

  // ---- add form: research prompt + YAML check/save -------------------------- //
  // opts.prefix (unique per page), opts.prompt (show the research-prompt step),
  // opts.placeholder (of the YAML field), opts.hint (markup above it, data-en)
  function wizard(el, page, opts) {
    var p = opts.prefix, n = 0;
    var id = function (k) { return p + "-" + k; };
    var html = "";
    if (opts.prompt) {
      html +=
        '<div class="step"><h3><span class="n">' + (++n) + '</span><span data-en="Copy the research prompt">复制调研提示词</span></h3>' +
        '<div class="two"><div class="grp">' +
        '<label class="lab" for="' + id("model") + '"><span data-en="Model id">模型 ID</span> <span class="key">id</span></label>' +
        '<input class="in mono" id="' + id("model") + '" autocomplete="off" spellcheck="false" autocapitalize="off" placeholder="例如 example-large-2" data-en-placeholder="e.g. example-large-2">' +
        '</div><div class="grp">' +
        '<label class="lab" for="' + id("prov") + '"><span data-en="Provider">厂商</span> <span class="opt" data-en="Optional">可选</span></label>' +
        '<input class="in" id="' + id("prov") + '" autocomplete="off" spellcheck="false" autocapitalize="off" placeholder="例如 openai / deepseek" data-en-placeholder="e.g. openai / deepseek">' +
        "</div></div>" +
        '<div class="row"><button class="btn pri" type="button" id="' + id("copy") + '">' + icon("arrowRight") + ' <span data-en="Copy prompt">复制提示词</span></button>' +
        '<span class="hint" id="' + id("copy-msg") + '" role="status"></span></div>' +
        '<details class="inline"><summary data-en="Show the prompt">查看提示词</summary>' +
        '<textarea class="in prompt" id="' + id("prompt") + '" readonly aria-label="提示词" data-en-aria-label="Prompt"></textarea></details>' +
        '<p class="hint" data-en="Paste it into the AI assistant of your choice. It answers with one YAML document.">把它粘贴到你选择的 AI 助手中，它会返回一份 YAML 文档。</p></div>';
    }
    html +=
      '<div class="step"><h3><span class="n">' + (++n) + '</span><span data-en="Upload or paste the YAML">上传或粘贴 YAML</span></h3>' +
      (opts.hint || "") +
      '<div class="grp"><label class="lab" for="' + id("yaml") + '" data-en="Profile YAML">资料 YAML</label>' +
      '<textarea class="in yaml" id="' + id("yaml") + '" spellcheck="false" autocapitalize="off" placeholder="' + esc(opts.placeholder) + '"></textarea></div>' +
      '<div class="row"><label class="btn" for="' + id("file") + '">' + icon("folder") + ' <span data-en="Choose a .yaml file">选择 .yaml 文件</span></label>' +
      '<input type="file" id="' + id("file") + '" accept=".yaml,.yml,text/yaml,application/yaml,text/plain" hidden>' +
      '<span class="hint mono" id="' + id("file-name") + '"></span></div></div>' +
      '<div class="step"><h3><span class="n">' + (++n) + '</span><span data-en="Check and save">检查并保存</span></h3>' +
      '<p class="hint" data-en="The check validates the schema and limits, flags unsafe regular expressions, lists every prompt zing would send to relays, and shows which model ids would resolve differently. Nothing is stored until you save.">检查会校验结构与上限、标记不安全的正则表达式、列出 zing 将发送给中转站的所有提示词，并显示哪些模型 ID 的匹配结果会改变。保存之前不会写入任何内容。</p>' +
      '<div class="row"><button class="btn" type="button" id="' + id("check") + '">' + icon("search") + ' <span data-en="Check">检查</span></button>' +
      '<button class="btn pri" type="button" id="' + id("save") + '" disabled>' + icon("check") + ' <span data-en="Save to knowledge base">保存到知识库</span></button></div>' +
      '<div aria-live="polite"><div class="scan" id="' + id("scan") + '" hidden></div>' +
      '<div class="errbox" id="' + id("err") + '" role="alert" hidden></div>' +
      '<div class="okbox" id="' + id("ok") + '" hidden></div></div></div>';
    el.innerHTML = html;
    translate(el);

    var $ = function (k) { return document.getElementById(id(k)); };
    var copyMsg = null, fileName = null, scanned = null, formErr = null, formOk = null;

    function paintCopyMsg() { if ($("copy-msg")) $("copy-msg").textContent = copyMsg ? copyMsg() : ""; }
    if (opts.prompt) {
      $("copy").addEventListener("click", function () {
        if (!$("model").value.trim()) {
          copyMsg = function () { return T("请先填写模型 ID。", "Enter the model id first."); };
          paintCopyMsg();
          $("model").focus();
          return;
        }
        var qs = "?model=" + encodeURIComponent($("model").value.trim()) + "&provider=" + encodeURIComponent($("prov").value.trim());
        fetch("/api/kb/prompt" + qs).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.text();
        }).then(function (text) {
          var box = $("prompt");
          box.value = text;
          var show = function () { box.parentNode.open = true; box.select(); };
          if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text).then(function () {
              copyMsg = function () { return T("提示词已复制。", "Prompt copied."); };
              paintCopyMsg();
            }, function () {
              copyMsg = function () { return T("无法访问剪贴板，请从下方复制。", "Clipboard not available — copy it from below."); };
              paintCopyMsg();
              show();
            });
          }
          show();
        }).catch(function () {
          copyMsg = function () { return T("无法生成提示词。", "Could not build the prompt."); };
          paintCopyMsg();
        });
      });
    }

    $("file").addEventListener("change", function () {
      var f = this.files && this.files[0];
      if (!f) return;
      if (f.size > 512 * 1024) {
        formErr = function () { return T("文件大于 512 KB。", "The file is larger than 512 KB."); };
        paintForm();
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        $("yaml").value = String(reader.result || "");
        fileName = f.name;
        $("file-name").textContent = f.name;
        invalidate();
      };
      reader.readAsText(f);
    });
    $("yaml").addEventListener("input", invalidate);

    function invalidate() {
      scanned = null;
      formOk = null;
      paintScan();
      paintForm();
    }
    function paintForm() {
      var e = $("err"), o = $("ok");
      e.hidden = !formErr;
      e.textContent = formErr ? formErr() : "";
      o.hidden = !formOk;
      o.innerHTML = formOk ? icon("check") + "<span>" + esc(formOk()) + "</span>" : "";
      var sv = $("save"), off = !(scanned && scanned.ok);
      // the focused button is about to be disabled: move focus to "Check"
      // first (else it falls to <body>); the live region announces the outcome
      if (off && document.activeElement === sv) $("check").focus();
      sv.disabled = off;
    }
    var ACTION = {
      add: ["新增", "new"],
      update: ["更新你的条目", "updates your entry"],
      shadow: ["覆盖内置模型", "replaces a packaged model"],
    };
    function list(head, cls, items, fn) {
      if (!items || !items.length) return "";
      return "<div><h4>" + esc(head) + "</h4><ul" + (cls ? ' class="' + cls + '"' : "") + ">" + items.map(fn).join("") + "</ul></div>";
    }
    function paintScan() {
      var box = $("scan");
      if (!scanned) { box.hidden = true; box.innerHTML = ""; return; }
      var s = scanned, path = function (x) { return x.path ? "<code>" + esc(x.path) + "</code> " : ""; };
      var html =
        list(T("错误（阻止保存）", "Errors (block saving)"), "bad", s.errors, function (e) { return "<li>" + path(e) + esc(e.message) + "</li>"; }) +
        list(T("模型", "Models"), "", s.models, function (m) {
          var a = ACTION[m.action] || [m.action, m.action];
          return "<li><code>" + esc(m.provider + "/" + m.id) + "</code> — " + esc(T(a[0], a[1])) + "</li>";
        }) +
        list(T("警告", "Warnings"), "warn", s.warnings, function (w) { return "<li>" + path(w) + esc(w.message) + "</li>"; }) +
        list(T("匹配结果将改变", "Resolution changes"), "", s.resolution_changes, function (c) {
          return "<li><code>" + esc(c.id) + "</code>: " + esc(c.before || "—") + " → " + esc(c.after || "—") + "</li>";
        });
      if (s.probes && s.probes.length) {
        html += "<div><h4>" + esc(Tf("将发送给中转站的提示词（{n}）", "Prompts zing will send to relays ({n})", { n: s.probes.length })) + "</h4>" +
          "<details><summary>" + esc(T("逐条查看", "Review them")) + "</summary><ul>" +
          s.probes.map(function (pr) {
            return "<li><code>" + esc(pr.id) + "</code> (" + esc(pr.owner) + ", " + esc(pr.prompt_lang) + ")<pre>" + esc(pr.prompt) + "</pre></li>";
          }).join("") + "</ul></details></div>";
      }
      if (s.ok) html += '<p class="hint">' + esc(T("检查通过，可以保存。", "Check passed — ready to save.")) + "</p>";
      box.innerHTML = html;
      box.hidden = false;
    }
    $("check").addEventListener("click", function () {
      formErr = null; formOk = null;
      var text = $("yaml").value;
      if (!text.trim()) {
        formErr = function () { return T("请先粘贴或上传 YAML。", "Paste or upload the YAML first."); };
        scanned = null;
        paintScan(); paintForm();
        return;
      }
      var btn = $("check");
      if (isBusy(btn)) return;
      setBusy(btn, true);
      send("POST", "/api/kb/scan", { yaml: text }).then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        scanned = res.body;
      }).catch(function () {
        scanned = null;
        formErr = function () { return T("检查失败，请重试。", "The check failed — please try again."); };
      }).then(function () {
        setBusy(btn, false);
        paintScan(); paintForm();
      });
    });
    $("save").addEventListener("click", function () {
      var btn = $("save");
      if (!(scanned && scanned.ok) || isBusy(btn)) return;
      setBusy(btn, true);
      formErr = null; formOk = null;
      send("POST", "/api/kb/import", { yaml: $("yaml").value, filename: fileName }).then(function (res) {
        if (!res.ok) {
          scanned = res.body && res.body.errors ? res.body : null;
          formErr = function () { return T("未保存：YAML 未通过检查。", "Not saved: the YAML did not pass the check."); };
          return;
        }
        var k = (res.body.entry_ids || []).length;
        formOk = function () { return Tf("已保存 {n} 个条目，下一次检测即会使用。", "Saved {n} entries — the next audit uses them.", { n: k }); };
        scanned = null;
        $("yaml").value = "";
        $("file").value = "";
        fileName = null;
        $("file-name").textContent = "";
        return page.reload();
      }).catch(function () {
        formErr = function () { return T("网络错误，保存失败。", "Network error — not saved."); };
      }).then(function () {
        setBusy(btn, false);
        paintScan(); paintForm();
      });
    });

    window.addEventListener("zing:lang", function () { paintCopyMsg(); paintScan(); paintForm(); });
  }

  // ---- add form: a relay (name + base URL) --------------------------------- //
  function relayForm(el, page, opts) {
    var p = opts.prefix;
    var id = function (k) { return p + "-" + k; };
    el.innerHTML =
      '<form id="' + id("form") + '" novalidate><div class="two"><div class="grp">' +
      '<label class="lab" for="' + id("name") + '" data-en="Name of the relay">中转站名称</label>' +
      '<input class="in" id="' + id("name") + '" maxlength="64" autocomplete="off" spellcheck="false" aria-describedby="' + id("err") + '">' +
      '</div><div class="grp">' +
      '<label class="lab" for="' + id("url") + '"><span data-en="Relay URL">中转站地址</span> <span class="key">base_url</span></label>' +
      '<input class="in" id="' + id("url") + '" type="text" inputmode="url" autocomplete="off" spellcheck="false" autocapitalize="off" maxlength="500" placeholder="https://relay.example.com/v1" aria-describedby="' + id("err") + '">' +
      "</div></div>" +
      '<div class="row"><button class="btn pri" type="submit" id="' + id("save") + '">' + icon("plus") + ' <span data-en="Save relay">保存中转站</span></button></div>' +
      '<div aria-live="polite"><div class="errbox" id="' + id("err") + '" role="alert" hidden></div>' +
      '<div class="okbox" id="' + id("ok") + '" hidden></div></div></form>';
    translate(el);

    var $ = function (k) { return document.getElementById(id(k)); };
    var err = null, ok = null, bad = null;
    function paint() {
      $("err").hidden = !err;
      $("err").textContent = err ? err() : "";
      $("ok").hidden = !ok;
      $("ok").innerHTML = ok ? icon("check") + "<span>" + esc(ok()) + "</span>" : "";
      ["name", "url"].forEach(function (k) {
        if (bad === k) $(k).setAttribute("aria-invalid", "true"); else $(k).removeAttribute("aria-invalid");
      });
    }
    function fail(field, msg) {
      err = msg; ok = null; bad = field;
      paint();
      if (field) $(field).focus();
    }
    $("form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var btn = $("save");
      if (isBusy(btn)) return;
      var name = $("name").value.trim(), url = $("url").value.trim();
      if (!name) return fail("name", function () { return T("请填写中转站名称。", "Enter a name for the relay."); });
      if (!/^https?:\/\/\S+$/i.test(url)) {
        return fail("url", function () { return T("请填写以 http:// 或 https:// 开头的地址。", "Enter a URL that starts with http:// or https://."); });
      }
      setBusy(btn, true);
      send("POST", "/api/kb/relays", { name: name, base_url: url }).then(function (res) {
        if (!res.ok) {
          var msg = (res.body && res.body.error) || "?";
          // 409: the name (or URL) is taken; 400: the URL is not usable
          return fail(res.status === 409 ? "name" : "url", function () { return T("无法保存：", "Could not save: ") + (L ? L.server(msg) : msg); });
        }
        err = null; bad = null;
        var shown = res.body.display_name || name;
        ok = function () { return Tf("已将“{name}”保存到知识库。", "Saved “{name}” to the knowledge base.", { name: shown }); };
        $("name").value = "";
        $("url").value = "";
        paint();
        return page.reload();
      }).catch(function () {
        fail(null, function () { return T("网络错误，保存失败。", "Network error — not saved."); });
      }).then(function () { setBusy(btn, false); });
    });
    window.addEventListener("zing:lang", paint);
  }

  window.ZingKbSection = { mount: mount, wizard: wizard, relayForm: relayForm, sourceText: sourceText, esc: esc, Tf: Tf };
})();
