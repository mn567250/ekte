/* ekte web UI v2 — the change signal in the browser (issue 156).
 *
 * One poller per tab asks GET /api/version every 10 s while the tab is
 * visible, and once as soon as it becomes visible again; a hidden tab polls
 * not at all. Only a tab loaded hidden (opened in the background) asks once
 * at start, with the page's own data, for the baseline: a change before it is
 * first shown is then noticed when it is. The answer is {data, live}: opaque
 * tokens, compared for equality only (ekte/web/server.py version_tokens). A plain fetch, so the browser
 * revalidates by ETag and the server answers 304 while nothing changed.
 *
 * When a token changes, an event is dispatched on window:
 *   ekte:data   a history write (a run saved, rescored or deleted, from any
 *               process, the CLI included)
 *   ekte:live   a job or monitor run started or ended, monitor settings changed
 * with detail {before, after} (the token before and after the change). The
 * first answer only sets the baseline: no event. Errors are silent; the next
 * tick asks again.
 *
 *   EkteLive.start() / stop()   start (on load) / stop polling, for tests
 *   EkteLive.poll()             ask now (a promise)
 *   EkteLive.tokens()           the last answer, or null
 *   EkteLive.version()          ask once for the page itself (a promise of
 *                               {data, live}; no event, the poller's baseline
 *                               stays): History notes which data its list shows
 *   EkteLive.createPoller(env)  the scheduling logic on its own: pure, with
 *                               the clock, the fetch, the visibility and the
 *                               events passed in (tests/test_web_v2_live_js.py)
 *
 * No data endpoint is polled: the pages refetch their own (cached) URLs only
 * when an event says the data changed.
 */
(function () {
  "use strict";

  var INTERVAL = 10000;
  var KEYS = [["data", "ekte:data"], ["live", "ekte:live"]];

  // env: { ask() -> Promise<{data, live}> (rejects on any error),
  //        visible() -> bool, emit(name, detail),
  //        setTimeout(fn, ms), clearTimeout(id), interval (ms, default 10 s) }
  function createPoller(env) {
    var every = env.interval || INTERVAL;
    var last = null, timer = null, busy = null, on = false;

    function clear() {
      if (timer != null) env.clearTimeout(timer);
      timer = null;
    }
    // the next tick, while running and visible (a hidden tab waits for show)
    function schedule() {
      clear();
      if (on && env.visible()) timer = env.setTimeout(tick, every);
    }
    function apply(v) {
      if (!v || typeof v !== "object") return;
      var was = last;
      last = { data: v.data, live: v.live };
      if (!was) return; // the first answer is the baseline
      KEYS.forEach(function (k) {
        if (was[k[0]] !== last[k[0]]) env.emit(k[1], { before: was[k[0]], after: last[k[0]] });
      });
    }
    // one request at a time; a tick while one is on its way waits for it
    function poll() {
      if (busy) return busy;
      clear();
      var p;
      try { p = Promise.resolve(env.ask()); } catch (e) { p = Promise.reject(e); }
      busy = p.then(apply, function () { /* silent: the next tick asks again */ }).then(function () {
        busy = null;
        schedule();
      });
      return busy;
    }
    function tick() {
      timer = null;
      if (on && env.visible()) poll();
    }
    // visibilitychange: hidden stops the clock, visible asks at once
    function onVisibility() {
      if (!on) return;
      if (!env.visible()) { clear(); return; }
      if (!busy) poll();
    }
    return {
      // the first start asks at once, hidden or not (the baseline of the data
      // the page is loading); a later start asks only while visible
      start: function () {
        if (on) return;
        on = true;
        if ((env.visible() || !last) && !busy) poll();
      },
      stop: function () { on = false; clear(); },
      poll: poll,
      onVisibility: onVisibility,
      tokens: function () { return last ? { data: last.data, live: last.live } : null; },
      running: function () { return on; },
      pending: function () { return timer != null; },
    };
  }

  var api = { createPoller: createPoller, INTERVAL: INTERVAL };
  if (typeof window === "undefined") return;
  if (window.EkteLive) return; // loaded twice: one poller per tab
  window.EkteLive = api;
  if (typeof document === "undefined" || typeof fetch !== "function") return; // node: the helper only

  function ask() {
    return fetch("/api/version", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }
  var poller = createPoller({
    ask: ask,
    visible: function () { return document.visibilityState === "visible"; },
    emit: function (name, detail) {
      var ev;
      try { ev = new CustomEvent(name, { detail: detail }); } catch (e) {
        ev = document.createEvent("CustomEvent");
        ev.initCustomEvent(name, false, false, detail);
      }
      window.dispatchEvent(ev);
    },
    setTimeout: function (fn, ms) { return window.setTimeout(fn, ms); },
    clearTimeout: function (id) { window.clearTimeout(id); },
  });
  document.addEventListener("visibilitychange", poller.onVisibility);
  api.start = poller.start;
  api.stop = poller.stop;
  api.poll = poller.poll;
  api.tokens = poller.tokens;
  api.version = ask;
  poller.start();
})();
