/* ekte web UI v2 — the monitors' master key: create (shown once), unlock,
 * lock, rotate, move a legacy key file out, reset a lost key.
 *
 *   <script src="/static/masterkey.js"></script>   (after lang.js / icons.js)
 *   EkteMasterKey.mountBar(el, onChange)   status line + the allowed actions
 *   EkteMasterKey.withKey(doFetch)         run doFetch(); on 423 (no master key)
 *                                          open the right dialog, then retry once
 *   EkteMasterKey.setStorage(mode)         "memory" (store no API key) or
 *                                          "encrypted"; asks for the key as needed
 *
 * A master key exists only to encrypt stored API keys: while none are stored
 * (storage "memory", the default) the status bar stays hidden.
 *
 * The server never stores the key on disk and holds it in memory only until
 * it restarts, so the user keeps it: the new-key dialog shows it once, offers
 * copy / download, and has it typed back (a form with autocomplete
 * "new-password", which also lets the browser's password manager offer to save
 * it; Chromium gets an explicit PasswordCredential). The unlock dialog uses the
 * same fixed username with "current-password", so the vault fills it in.
 * The key never lands in browser storage, the URL or a log, and every reference
 * to it is dropped when a dialog closes.
 */
(function () {
  "use strict";

  var CRED_ID = "ekte-master-key";
  var CRED_NAME = "ekte master key";
  // The id a password manager saved the key under before the rename
  // (zing -> ekte); still accepted when the saved key is filled in.
  // Deprecated: removed in ekte 1.0.0.
  var LEGACY_CRED_ID = "zing-master-key";

  function T(zh, en) {
    return typeof window.T === "function" ? window.T(zh, en) : en;
  }
  // T(zh, en) with {name} placeholders filled after translation.
  function Tf(zh, en, vals) {
    var s = T(zh, en);
    Object.keys(vals || {}).forEach(function (k) {
      s = s.split("{" + k + "}").join(String(vals[k]));
    });
    return s;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function icon(name) {
    return typeof window.ekteIcon === "function" ? window.ekteIcon(name) : "";
  }

  // ---- pure logic (tested under node) ------------------------------------ //

  // Which dialog a 423 needs: "setup" (no key yet), "unlock", or null.
  function decide(status) {
    var acts = (status && status.actions) || [];
    if (status && status.state === "uninitialized" && acts.indexOf("new") >= 0) return "setup";
    if (acts.indexOf("unlock") >= 0) return "unlock";
    return null;
  }

  // Best effort: Chromium saves it explicitly; other browsers offer to save
  // from the form submit itself.
  function storeCredential(key) {
    try {
      if (!key || typeof window.PasswordCredential !== "function" ||
          typeof navigator === "undefined" || !navigator.credentials || !navigator.credentials.store) {
        return Promise.resolve(false);
      }
      var c = new window.PasswordCredential({ id: CRED_ID, name: CRED_NAME, password: key });
      return navigator.credentials.store(c).then(function () { return true; }, function () { return false; });
    } catch (e) {
      return Promise.resolve(false);
    }
  }

  // Chromium only: the saved key, without a prompt when the vault allows.
  function savedCredential() {
    try {
      if (typeof navigator === "undefined" || !navigator.credentials || !navigator.credentials.get ||
          typeof window.PasswordCredential !== "function") {
        return Promise.resolve("");
      }
      return navigator.credentials.get({ password: true, mediation: "optional" }).then(function (c) {
        return c && (c.id === CRED_ID || c.id === LEGACY_CRED_ID) && c.password ? c.password : "";
      }, function () { return ""; });
    } catch (e) {
      return Promise.resolve("");
    }
  }

  function api(path, body) {
    var opts = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    };
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        return { ok: r.ok, status: r.status, body: j || {} };
      });
    });
  }
  function status() {
    return api("/api/secret").then(function (res) { return res.body; });
  }

  // Run doFetch() (returns a fetch Promise). A 423 means the master key must
  // be created or entered first: do that (`ask`, by default the dialogs), then
  // retry exactly once. Resolves with the response the caller should look at.
  function withKey(doFetch, ask) {
    return doFetch().then(function (r) {
      if (!r || r.status !== 423) return r;
      return (ask || ensure)().then(function (ok) { return ok ? doFetch() : r; });
    });
  }

  // Switch where API keys are kept. A switch that needs the master key (to
  // open the stored keys, or to encrypt them) asks for it first. Resolves
  // {ok, status, body}; body is the new status with `moved` on success.
  function setStorage(mode) {
    return withKey(function () {
      return fetch("/api/secret/storage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: mode }),
      });
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.ok) announce();
        return { ok: r.ok, status: r.status, body: j || {} };
      });
    });
  }

  // Open whatever dialog the current state needs; resolves true once a key is held.
  // Announces the change ("ekte:masterkey") so a mounted status bar follows.
  function ensure() {
    return status().then(function (st) {
      var need = decide(st);
      var p = need === "setup" ? newKeyDialog("setup") : need === "unlock" ? unlockDialog()
        : Promise.resolve(!!st && st.state === "unlocked");
      return p.then(function (ok) {
        if (ok && need) announce();
        return ok;
      });
    }, function () { return false; });
  }
  function announce() {
    try { window.dispatchEvent(new Event("ekte:masterkey")); } catch (e) { /* old browsers */ }
  }

  // ---- dialogs ------------------------------------------------------------ //
  var dlg = null, settle = null;
  function dialog() {
    if (dlg) return dlg;
    dlg = document.createElement("dialog");
    dlg.className = "zmk-dlg";
    dlg.setAttribute("aria-labelledby", "zmk-title");
    // Esc and every Cancel button end the open dialog with `false`.
    dlg.addEventListener("cancel", function (ev) { ev.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener("click", function (ev) {
      if (settle && ev.target.closest("[data-zmk=cancel]")) settle(false);
    });
    document.body.appendChild(dlg);
    return dlg;
  }
  // Show `html` in the modal; `wire(d, done)` attaches handlers. Resolves
  // with what done() is called with (false on Esc / Cancel).
  function open(html, wire) {
    var d = dialog();
    if (settle) settle(false); // one dialog at a time
    return new Promise(function (resolve) {
      function done(v) {
        if (settle !== done) return;
        settle = null;
        if (d.open) d.close();
        d.innerHTML = ""; // drop the key from the DOM
        resolve(v);
      }
      settle = done;
      d.innerHTML = html;
      if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
      wire(d, done);
      var first = d.querySelector("[autofocus]") || d.querySelector("input:not(.sr-only), button");
      if (first) first.focus();
    });
  }
  function userField() {
    return '<input class="sr-only" type="text" tabindex="-1" aria-hidden="true" readonly autocomplete="username" name="username" value="' + CRED_ID + '">';
  }
  function cancelBtn() {
    return '<button type="button" class="btn" data-zmk="cancel">' + esc(T("取消", "Cancel")) + "</button>";
  }
  function errLine() {
    return '<p class="zmk-err" role="alert" hidden></p>';
  }
  // The error line of the step on screen (the new-key dialog has three).
  function showErr(d, text) {
    var e = d.querySelector(".zmk-step:not([hidden]) .zmk-err") || d.querySelector(".zmk-err");
    if (e) { e.textContent = text; e.hidden = !text; }
  }
  function serverErr(res) {
    // 409: the key's state changed meanwhile (another tab, the CLI)
    if (res && res.status === 409) {
      return T("主密钥的状态已改变，请刷新页面后重试。", "The master key's state changed meanwhile — reload the page and try again.");
    }
    var e = res && res.body && res.body.error;
    var L = window.EKTE_LANG;
    return e ? (L && L.server ? L.server(e) : e) : T("出错了，请重试。", "Something went wrong — please try again.");
  }

  // Each dialog's wording, translated when the dialog opens.
  var COPY = {
    setup: function () {
      return {
        title: T("创建主密钥", "Create your master key"),
        intro: T("主密钥用于加密本机保存的中转站 API 密钥。ekte 不会把它写入磁盘：每次重启 ekte serve 后，你需要再次输入它，监控才会运行。请把它保存在密码管理器或其他安全的地方，不要放在 ekte 的数据目录里。丢失主密钥意味着需要重新输入每个监控的 API 密钥。",
          "The master key encrypts the relay API keys stored on this machine. ekte never writes it to disk: after every restart of ekte serve you enter it again before monitors run. Keep it in a password manager or another safe place — not in ekte's data folder. Losing it means re-entering every monitor's API key."),
      };
    },
    migrate: function () {
      return {
        title: T("把主密钥移出数据目录", "Move your master key out of the data folder"),
        intro: T("你的主密钥目前保存在数据库旁边（secret.key），能读取该目录的人就能解密你的 API 密钥。ekte 会生成一个新的主密钥、用它重新加密所有 API 密钥，并删除 secret.key。之后每次重启都需要输入新密钥。",
          "Your master key is stored next to the databases (secret.key), so anyone who can read that folder can decrypt your API keys. ekte creates a new master key, re-encrypts every API key with it and deletes secret.key. From then on you enter the new key after each restart."),
      };
    },
    rotate: function () {
      return {
        title: T("更换主密钥", "Rotate the master key"),
        intro: T("ekte 会生成一个新的主密钥并用它重新加密所有 API 密钥。确认之后，旧密钥将不再有效。",
          "ekte creates a new master key and re-encrypts every API key with it. Once you confirm, the old key stops working."),
      };
    },
  };

  // mode: "setup" | "migrate" | "rotate". Resolves true once the new key is in use.
  function newKeyDialog(mode) {
    var c = (COPY[mode] || COPY.setup)();
    var key = null;
    var html =
      '<form method="dialog" class="zmk-body" novalidate>' +
        '<h2 id="zmk-title">' + icon("lock") + esc(c.title) + "</h2>" +
        '<div class="zmk-step" data-step="intro"><p>' + esc(c.intro) + "</p>" + errLine() +
          '<div class="zmk-act"><button type="button" class="btn pri" data-zmk="show" autofocus>' + esc(T("生成并显示密钥", "Show the new key")) + "</button>" + cancelBtn() + "</div></div>" +
        '<div class="zmk-step" data-step="show" hidden>' +
          "<p>" + esc(T("这是唯一一次显示。请立即保存：", "This is the only time it is shown. Save it now:")) + "</p>" +
          '<label class="lab" for="zmk-key">' + esc(T("新的主密钥", "New master key")) + ' <span class="opt" data-zmk="fp"></span></label>' +
          '<input class="in mono" id="zmk-key" readonly autocomplete="off" spellcheck="false" autocapitalize="off">' +
          '<div class="zmk-row"><button type="button" class="btn sm" data-zmk="copy">' + esc(T("复制", "Copy")) + "</button>" +
          '<button type="button" class="btn sm" data-zmk="download">' + esc(T("下载 .txt", "Download .txt")) + "</button>" +
          '<span class="hint" data-zmk="copied" role="status"></span></div>' +
          '<label class="zmk-check"><input type="checkbox" data-zmk="saved"> ' +
            esc(T("我已把它保存在安全的地方（不在 ekte 数据目录中）", "I stored it somewhere safe (not in ekte's data folder)")) + "</label>" +
          '<div class="zmk-act"><button type="button" class="btn pri" data-zmk="next" disabled>' + esc(T("下一步", "Next")) + "</button>" + cancelBtn() + "</div></div>" +
        '<div class="zmk-step" data-step="confirm" hidden>' +
          "<p>" + esc(T("请粘贴刚才保存的密钥以确认。浏览器可能会提示你把它保存到密码管理器。",
            "Paste the key you saved to confirm. Your browser may offer to save it in its password manager.")) + "</p>" +
          userField() +
          '<label class="lab" for="zmk-typed">' + esc(T("主密钥", "Master key")) + "</label>" +
          '<input class="in mono" id="zmk-typed" type="password" name="password" autocomplete="new-password" spellcheck="false" autocapitalize="off" required>' +
          errLine() +
          '<div class="zmk-act"><button type="submit" class="btn pri" data-zmk="confirm">' + esc(T("确认并启用", "Confirm and use it")) + "</button>" + cancelBtn() + "</div></div>" +
      "</form>";
    return open(html, function (d, done) {
      function step(name) {
        showErr(d, "");
        Array.prototype.forEach.call(d.querySelectorAll(".zmk-step"), function (s) {
          s.hidden = s.getAttribute("data-step") !== name;
        });
        var f = d.querySelector('[data-step="' + name + '"] input:not(.sr-only):not([type=checkbox]), [data-step="' + name + '"] .btn.pri');
        if (f) f.focus();
      }
      var showBtn = d.querySelector('[data-zmk="show"]');
      showBtn.addEventListener("click", function () {
        showBtn.disabled = true;
        api("/api/secret/new", {}).then(function (res) {
          showBtn.disabled = false;
          if (!res.ok || !res.body.key) { showErr(d, serverErr(res)); return; }
          key = res.body.key;
          d.querySelector("#zmk-key").value = key;
          d.querySelector('[data-zmk="fp"]').textContent = Tf("指纹 {fp}", "fingerprint {fp}", { fp: res.body.fingerprint || "" });
          step("show");
          d.querySelector("#zmk-key").select();
        }, function () { showBtn.disabled = false; showErr(d, serverErr(null)); });
      });
      d.querySelector('[data-zmk="copy"]').addEventListener("click", function () {
        var note = d.querySelector('[data-zmk="copied"]');
        var ok = function () { note.textContent = T("已复制。剪贴板会保留它，直到被覆盖。", "Copied. Your clipboard keeps it until something else is copied."); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(key).then(ok, function () { d.querySelector("#zmk-key").select(); });
        } else {
          d.querySelector("#zmk-key").select();
        }
      });
      d.querySelector('[data-zmk="download"]').addEventListener("click", function () {
        var blob = new Blob([CRED_NAME + "\n" + key + "\n"], { type: "text/plain" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "ekte-master-key.txt";
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
      });
      var saved = d.querySelector('[data-zmk="saved"]'), next = d.querySelector('[data-zmk="next"]');
      saved.addEventListener("change", function () { next.disabled = !saved.checked; });
      next.addEventListener("click", function () { step("confirm"); });
      d.querySelector("form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var typed = d.querySelector("#zmk-typed").value;
        if (!typed.trim()) { showErr(d, T("请粘贴主密钥。", "Paste the master key.")); return; }
        var btn = d.querySelector('[data-zmk="confirm"]');
        btn.disabled = true;
        api("/api/secret/new/confirm", { key: typed }).then(function (res) {
          btn.disabled = false;
          if (res.status === 410) { key = null; step("intro"); showErr(d, serverErr(res)); return; }
          if (!res.ok) { showErr(d, serverErr(res)); return; }
          return storeCredential(typed.trim()).then(function () { key = null; typed = null; done(true); });
        }, function () { btn.disabled = false; showErr(d, serverErr(null)); });
      });
    }).then(function (v) { key = null; return v; });
  }

  function unlockDialog() {
    var html =
      '<form method="dialog" class="zmk-body" novalidate>' +
        '<h2 id="zmk-title">' + icon("lock") + esc(T("输入主密钥", "Enter your master key")) + "</h2>" +
        "<p>" + esc(T("ekte serve 重启后不会记住主密钥。输入它即可解锁已保存的 API 密钥，监控会继续运行。",
          "ekte serve does not remember the master key across restarts. Enter it to unlock the stored API keys; monitors carry on.")) + "</p>" +
        userField() +
        '<label class="lab" for="zmk-unlock">' + esc(T("主密钥", "Master key")) + "</label>" +
        '<input class="in mono" id="zmk-unlock" type="password" name="password" autocomplete="current-password" spellcheck="false" autocapitalize="off" required autofocus>' +
        errLine() +
        '<div class="zmk-act"><button type="submit" class="btn pri" data-zmk="unlock">' + esc(T("解锁", "Unlock")) + "</button>" + cancelBtn() + "</div>" +
      "</form>";
    return open(html, function (d, done) {
      var input = d.querySelector("#zmk-unlock");
      savedCredential().then(function (k) { if (k && !input.value) input.value = k; });
      d.querySelector("form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var typed = input.value;
        if (!typed.trim()) { showErr(d, T("请输入主密钥。", "Enter the master key.")); return; }
        var btn = d.querySelector('[data-zmk="unlock"]');
        btn.disabled = true;
        api("/api/secret/unlock", { key: typed }).then(function (res) {
          btn.disabled = false;
          if (!res.ok) {
            showErr(d, res.status === 403 ? T("主密钥不正确。", "That is not the master key.") : serverErr(res));
            input.select();
            return;
          }
          return storeCredential(typed.trim()).then(function () { typed = null; done(true); });
        }, function () { btn.disabled = false; showErr(d, serverErr(null)); });
      });
    });
  }

  // ---- status bar ----------------------------------------------------------- //
  function keysUsing(st) {
    var c = (st && st.counts) || {};
    return (c.encrypted || 0) + (c.locked || 0) + (c.unreadable || 0) + (c.plain || 0);
  }
  function sourceLabel(src) {
    if (src === "EKTE_SECRET_KEY") return T("来自 EKTE_SECRET_KEY", "from EKTE_SECRET_KEY");
    if (src === "legacy") return T("来自数据目录中的 secret.key", "from secret.key in the data folder");
    return T("已输入", "entered by you");
  }

  // Render the master key's state and actions into `el`; onChange() after any change.
  function mountBar(el, onChange) {
    var st = null, resetOpen = false, msg = "";
    function changed() {
      return refresh().then(function () { if (onChange) onChange(st); });
    }
    function refresh() {
      return status().then(function (s) { st = s; draw(); return s; }, function () { draw(); });
    }
    function btn(act, label, cls) {
      return '<button type="button" class="btn sm' + (cls ? " " + cls : "") + '" data-mk="' + act + '">' + esc(label) + "</button>";
    }
    function draw() {
      // no API key is stored: there is nothing for a master key to do
      if (!st || !st.state || st.storage === "memory") { el.innerHTML = ""; el.className = ""; el.hidden = true; return; }
      el.hidden = false;
      var acts = st.actions || [], html = "", kind = "";
      if (st.state === "unlocked") {
        kind = "ok";
        html = "<b>" + esc(T("主密钥已解锁", "Master key unlocked")) + "</b> <span class=\"zmk-meta\">" +
          esc(sourceLabel(st.source)) + " · " + esc(T("指纹", "fingerprint")) + " <code>" + esc(st.fingerprint) + "</code></span>";
      } else if (st.state === "locked") {
        kind = "warn";
        html = "<b>" + esc(T("主密钥已锁定", "Master key locked")) + "</b> <span class=\"zmk-meta\">" +
          esc(T("使用 API 密钥的监控已暂停，输入主密钥后继续。", "Monitors that use an API key are paused until you enter it.")) + "</span>";
      } else if (st.state === "env_mismatch") {
        kind = "bad";
        html = "<b>" + esc(T("EKTE_SECRET_KEY 不匹配", "EKTE_SECRET_KEY does not match")) + "</b> <span class=\"zmk-meta\">" +
          esc(T("它不是加密已保存 API 密钥所用的主密钥。请改回正确的值，或取消设置它并重置。",
            "It is not the master key the stored API keys were encrypted with. Set it back, or unset it and reset.")) + "</span>";
      } else {
        // no key yet: nothing can be stored or run with a key until one exists
        kind = "bad";
        html = "<b>" + esc(T("尚无主密钥", "No master key yet")) + "</b> <span class=\"zmk-meta\">" +
          esc(T("保存第一个 API 密钥时会创建它。", "It is created when you store the first API key.")) + "</span>";
      }
      var buttons = "";
      if (acts.indexOf("unlock") >= 0) buttons += btn("unlock", T("解锁", "Unlock"), "pri");
      if (acts.indexOf("new") >= 0) {
        buttons += st.state === "uninitialized" ? btn("setup", T("立即创建", "Create now"))
          : st.source === "legacy" ? btn("migrate", T("移出数据目录", "Move it out"), "pri")
          : btn("rotate", T("更换", "Rotate"));
      }
      if (acts.indexOf("lock") >= 0) buttons += btn("lock", T("锁定", "Lock"));
      if (acts.indexOf("reset") >= 0) buttons += btn("reset", T("忘记了密钥？", "Forgot the key?"), "link");
      var warn = "";
      if ((st.warnings || []).indexOf("legacy_key_file") >= 0) {
        warn += '<p class="zmk-warn">' + esc(T("主密钥仍保存在数据库旁边（secret.key）。把它移出去，备份或同步的数据目录才不会泄露你的 API 密钥。",
          "Your master key is still stored next to the databases (secret.key). Move it out so a backup or synced copy of the data folder cannot reveal your API keys.")) + "</p>";
      }
      if ((st.warnings || []).indexOf("env_in_data_dir") >= 0) {
        warn += '<p class="zmk-warn">' + esc(T("EKTE_SECRET_KEY 指向数据目录内的文件，请把它放到别处。",
          "EKTE_SECRET_KEY points to a file inside the data folder — keep it elsewhere.")) + "</p>";
      }
      var reset = "";
      if (resetOpen) {
        var n = keysUsing(st);
        reset = '<form class="zmk-reset" novalidate><p id="zmk-reset-q">' +
          esc(n === 1 ? T("将丢弃 1 个已加密的 API 密钥，相关监控会暂停，直到你重新输入密钥。",
            "1 encrypted API key will be dropped; its monitor pauses until you enter the key again.")
            : Tf("将丢弃 {n} 个已加密的 API 密钥，相关监控会暂停，直到你重新输入密钥。",
            "{n} encrypted API keys will be dropped; their monitors pause until you enter the keys again.", { n: n })) +
          " " + esc(T("输入 RESET 以确认：", "Type RESET to confirm:")) + "</p>" +
          '<div class="zmk-row"><input class="in mono" data-mk="reset-in" aria-labelledby="zmk-reset-q" autocomplete="off" spellcheck="false">' +
          '<button type="submit" class="btn sm danger" data-mk="reset-yes">' + esc(T("重置", "Reset")) + "</button>" +
          btn("reset-no", T("取消", "Cancel")) + "</div></form>";
      }
      // keep focus on the equivalent control across the re-render (Lock
      // becomes Unlock and back), else it would fall to <body>
      var a = document.activeElement, keep = a && el.contains(a) ? a.getAttribute("data-mk") : null;
      el.className = "zmk-bar " + kind;
      el.innerHTML = '<div class="zmk-line"><span class="zmk-ico">' + icon("lock") + "</span><div class=\"zmk-text\">" + html + "</div>" +
        '<div class="zmk-btns">' + buttons + "</div></div>" + warn + reset +
        '<p class="zmk-msg" role="status">' + esc(msg) + "</p>";
      if (keep) {
        var alt = { lock: "unlock", unlock: "lock", "reset-no": "reset", "reset-yes": "reset", "reset-in": "reset",
          setup: "lock", migrate: "lock", rotate: "lock" }[keep];
        var to = el.querySelector('[data-mk="' + keep + '"]') || (alt && el.querySelector('[data-mk="' + alt + '"]')) ||
          el.querySelector("button[data-mk]");
        if (to) to.focus();
      }
    }
    el.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-mk]");
      if (!b || b.tagName !== "BUTTON") return;
      var act = b.getAttribute("data-mk");
      msg = "";
      if (act === "unlock") unlockDialog().then(function (ok) { if (ok) changed(); });
      else if (act === "setup" || act === "migrate" || act === "rotate") {
        newKeyDialog(act).then(function (ok) {
          if (!ok) return;
          msg = act === "rotate" ? T("主密钥已更换，旧密钥已失效。", "Master key rotated; the old key no longer works.")
            : act === "migrate" ? T("新的主密钥已启用，secret.key 已删除。", "New master key in use; secret.key was deleted.")
            : T("主密钥已创建。", "Master key created.");
          changed();
        });
      } else if (act === "lock") {
        api("/api/secret/lock", {}).then(function () {
          msg = T("主密钥已锁定。", "Master key locked.");
          changed();
        });
      } else if (act === "reset") {
        resetOpen = true;
        draw();
        var i = el.querySelector('[data-mk="reset-in"]');
        if (i) i.focus();
      } else if (act === "reset-no") {
        resetOpen = false;
        draw();
      }
    });
    el.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var i = el.querySelector('[data-mk="reset-in"]');
      if (!i || i.value.trim() !== "RESET") { if (i) i.focus(); return; }
      api("/api/secret/reset", { confirm: "RESET" }).then(function (res) {
        resetOpen = false;
        msg = res.ok ? T("已重置。请为每个监控重新输入 API 密钥。", "Reset done. Enter each monitor's API key again.") : serverErr(res);
        changed();
      });
    });
    el.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && resetOpen) { resetOpen = false; draw(); }
    });
    window.addEventListener("ekte:lang", draw);
    window.addEventListener("ekte:masterkey", refresh);
    refresh();
    return { refresh: refresh };
  }

  window.EkteMasterKey = {
    CRED_ID: CRED_ID,
    decide: decide,
    storeCredential: storeCredential,
    withKey: withKey,
    ensure: ensure,
    newKeyDialog: newKeyDialog,
    unlockDialog: unlockDialog,
    mountBar: mountBar,
    setStorage: setStorage,
  };
})();
