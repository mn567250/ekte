/* zing web UI — masked API key fields with a show/hide toggle.
 *
 * Plain browser global, no modules; load after /lang.js and /icons.js.
 * The markup does the real work, so keys stay masked even without JS:
 *   <input type="password" data-secret="i-url" autocomplete="current-password">
 * where data-secret names the id of the base_url input the key belongs to.
 * That URL input carries autocomplete="username", so the browser's password
 * manager stores the key under the relay URL. At most one current-password
 * field per form: two would read as a change-password form, so a second key
 * (e.g. the baseline's) uses autocomplete="off" and is only stored explicitly.
 *
 * Theming: the wrapper is .secret-wrap.zsf and the toggle .secret-eye.zsf-toggle
 * (aria-pressed="true" while the key is shown); its colours come from the
 * optional custom properties --zsf-color / --zsf-color-on / --zsf-focus,
 * falling back to --faint / --ink / --teal (the v2 UI sets them in
 * /v2/static/fields.css).
 *
 * Exposes window.ZingSecret with:
 *   - enhance(root)       add the eye toggle to every input[data-secret] under root
 *                         (idempotent; runs on the document at load)
 *   - isReference(value)  true for env:VAR / file:/path — not secrets, so they
 *                         start revealed and are never offered to the vault
 *   - remember(form)      after a run: re-mask the form's literal keys and, where
 *                         the Credential Management API exists (Chromium), offer
 *                         each URL + key pair to the browser's password manager
 */
(function () {
  "use strict";

  var CSS =
    ".secret-wrap{position:relative;display:block}" +
    ".secret-wrap>input{padding-right:44px}" +
    "input[data-secret]::-ms-reveal,input[data-secret]::-ms-clear{display:none}" +
    ".secret-eye{position:absolute;top:0;right:4px;bottom:0;margin:auto 0;width:36px;height:32px;" +
    "display:flex;align-items:center;justify-content:center;padding:0;border:0;border-radius:8px;" +
    "background:none;color:var(--zsf-color,var(--faint));font-size:18px;cursor:pointer;transition:color .15s}" +
    ".secret-eye:hover,.secret-eye[aria-pressed=true]{color:var(--zsf-color-on,var(--ink))}" +
    ".secret-eye:focus-visible{outline:2px solid var(--zsf-focus,var(--teal,var(--grn,currentColor)));outline-offset:-2px}";

  function isReference(value) {
    return /^\s*(env|file):/i.test(String(value == null ? "" : value));
  }

  function icon(name) {
    return window.zingIcon ? window.zingIcon(name) : "";
  }

  function setShown(input, shown) {
    input.type = shown ? "text" : "password";
    var btn = input.__zingEye;
    if (!btn) return;
    btn.setAttribute("aria-pressed", shown ? "true" : "false");
    btn.innerHTML = icon(shown ? "eyeOff" : "eye");
  }

  function injectCss() {
    if (typeof document === "undefined" || !document.head || document.getElementById("zs-css")) return;
    var st = document.createElement("style");
    st.id = "zs-css";
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function enhance(root) {
    if (typeof document === "undefined") return;
    injectCss();
    var inputs = (root || document).querySelectorAll("input[data-secret]");
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i];
      if (input.__zingEye) continue;
      var wrap = document.createElement("span");
      wrap.className = "secret-wrap zsf";
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      // A constant label plus aria-pressed is the standard toggle pattern, so
      // a language switch (lang.js re-translates data-en-*) is all it needs.
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secret-eye zsf-toggle";
      btn.setAttribute("aria-label", "显示密钥");
      btn.setAttribute("title", "显示密钥");
      btn.setAttribute("data-en-aria-label", "Show key");
      btn.setAttribute("data-en-title", "Show key");
      if (input.id) {
        btn.setAttribute("aria-controls", input.id);
        // Every toggle is named "Show key" (its visible tooltip, WCAG 2.5.3);
        // the field's label, as the description, tells them apart.
        var lab = document.querySelector('label[for="' + input.id + '"]');
        if (lab) {
          if (!lab.id) lab.id = input.id + "-lab";
          btn.setAttribute("aria-describedby", lab.id);
        }
      }
      wrap.appendChild(btn);
      input.__zingEye = btn;
      btn.addEventListener("mousedown", function (e) {
        e.preventDefault(); // keep focus (and the caret) in the input
      });
      btn.addEventListener("click", (function (inp) {
        return function () {
          setShown(inp, inp.type === "password");
        };
      })(input));
      setShown(input, isReference(input.value));
      if (window.ZING_LANG) window.ZING_LANG.apply(wrap);
    }
  }

  function remember(form) {
    if (!form || !form.querySelectorAll) return;
    var inputs = form.querySelectorAll("input[data-secret]");
    var pairs = [];
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i], key = input.value.trim();
      if (!key || isReference(key)) continue;
      setShown(input, false);
      var urlInput = document.getElementById(input.getAttribute("data-secret"));
      var url = urlInput ? urlInput.value.trim() : "";
      if (url) pairs.push({ id: url, password: key });
    }
    if (!pairs.length || typeof window.PasswordCredential !== "function") return;
    try {
      if (!navigator.credentials || !navigator.credentials.store) return;
      // One prompt at a time: the browser rejects a store while one is open.
      pairs.reduce(function (p, c) {
        return p.then(function () {
          return navigator.credentials.store(new window.PasswordCredential(c));
        }).catch(function () {});
      }, Promise.resolve());
    } catch (e) {}
  }

  window.ZingSecret = { enhance: enhance, isReference: isReference, remember: remember };

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { enhance(document); });
    } else {
      enhance(document);
    }
  }
})();
