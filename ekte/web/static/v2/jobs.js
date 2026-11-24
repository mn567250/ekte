/* ekte web UI v2 — the "Running" list of background audits and running
 * monitors (/api/jobs), shared by the Audit page (kind "audit") and the
 * Monitors page (kind "monitor"). Styles: jobs.css.
 *
 * Markup: an empty <ul class="jlist" id="…"></ul> inside the page's own panel.
 *
 * EkteJobs.init(list, opts) reads /api/jobs and renders one <li class="job">
 * per queued / running run of that kind (a progress bar with role=progressbar,
 * "Watch live", "Open monitor" for monitors, Cancel), plus failed runs, which
 * never reach History (the server drops them after a while). Re-renders on
 * "ekte:lang" from cache. How it learns about changes depends on opts:
 *   opts.live: true      the change signal (live.js, issue 161): /api/jobs is
 *                        read once at start and again on every "ekte:live"
 *                        (a run started or ended) and when a run's stream
 *                        says it is done; the progress of each running row
 *                        follows its event stream (/api/jobs/<id>/events),
 *                        except for opts.skip(id) (a run the page follows
 *                        itself). Nothing on a timer (the Audit page).
 *   default              polls every 2 s while a run is active and every 5 s
 *                        otherwise; polling pauses while the tab is hidden
 *                        and catches up when it is shown again.
 *   opts.kind            "audit" (everything but monitors, the default) or
 *                        "monitor"
 *   opts.onChange(active, rows)  called after every render with the number
 *                        of queued/running runs and of rows shown
 *   opts.onFinish()      called when a run that was active is no longer
 *                        (finished, failed or cancelled), e.g. to reload a list
 *   opts.poll: false     no polling and no first request: the page hands in
 *                        the jobs itself with set() (the Monitors page, which
 *                        reads /api/jobs on the change signal and follows each
 *                        run's event stream, issue 160)
 * Returns { refresh(), rows(), set(jobs) }: refresh() polls now (returns a
 * promise), rows() the rows currently shown, set(jobs) shows the jobs of a
 * /api/jobs answer (its `jobs` list) as if a poll had returned them.
 *
 * EkteJobs.progress(): a run's progress from its event stream
 * (/api/jobs/<id>/events), counted as the server counts it for /api/jobs
 * (ekte/web/jobs.py track_progress / progress_pct): add(event) folds one
 * event in, pct() is the percent done (0-99), status() "queued" | "running"
 * | "done" | null (no status event yet), known() whether a "start" event
 * gave the number of checks, counts() {done, total, current} as /api/jobs
 * lists them. Pure, tested under node.
 */
(function () {
  "use strict";

  var ACTIVE_MS = 2000, IDLE_MS = 5000;

  var T = function (zh, en) { return window.T ? window.T(zh, en) : en; };
  // placeholders through fmt.js (numbers grouped in the UI locale, issue 229)
  var Tf = function (zh, en, vars) {
    return window.EkteFmt.fill(T(zh, en), vars);
  };
  var ico = function (n, o) { return window.ekteIcon ? window.ekteIcon(n, o || {}) : ""; };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };
  var srvT = function (s) { return window.EKTE_LANG ? window.EKTE_LANG.server(s) : s; };
  var STREAM = {
    stream: ["流式", "Streaming"],
    non_stream: ["非流式", "Non-streaming"],
    both: ["流式 + 非流式", "Streaming + non-streaming"],
  };
  var streamLabel = function (v) { return STREAM[v] ? T(STREAM[v][0], STREAM[v][1]) : v; };
  var detectLabel = function (v) { return v === "auto" ? T("自动识别", "auto-detected") : T("手动指定", "set manually"); };
  function fmtTime(sec) {
    var d = new Date(sec * 1000);
    if (isNaN(d)) return "";
    try {
      return window.EKTE_LANG.dateFmt({ dateStyle: "medium", timeStyle: "short" }).format(d);
    } catch (e) {
      return d.toLocaleString();
    }
  }
  function isActive(j) { return j.status === "queued" || j.status === "running"; }

  function init(list, opts) {
    opts = opts || {};
    var mine = opts.kind === "monitor"
      ? function (j) { return j.kind === "monitor"; }
      : function (j) { return j.kind !== "monitor"; };
    // msg: per-run notes (a function, so it follows the language)
    var st = { rows: [], timer: null, due: false, active: {}, msg: {}, busy: null };

    var follows = opts.live === true;
    var polls = opts.poll !== false && !follows;
    var streams = {}; // live mode: job id -> {es, prog}
    function schedule() {
      clearTimeout(st.timer);
      if (!polls) return;
      st.timer = setTimeout(poll, Object.keys(st.active).length ? ACTIVE_MS : IDLE_MS);
    }
    function poll() {
      st.timer = null;
      if (document.hidden) st.due = true;
      else refresh();
    }
    document.addEventListener("visibilitychange", function () {
      if (polls && !document.hidden && st.due) refresh();
    });

    // the jobs of one /api/jobs answer
    function apply(all) {
      var rows = (all || []).filter(mine);
      var now = {}, finished = false;
      rows.forEach(function (j) { if (isActive(j)) now[j.id] = true; });
      Object.keys(st.active).forEach(function (id) { if (!now[id]) finished = true; });
      st.active = now;
      // failed runs never reach History: keep them; cancelled and
      // finished ones go
      st.rows = rows.filter(function (j) { return isActive(j) || j.status === "error"; });
      if (follows) syncStreams();
      render();
      if (finished && opts.onFinish) opts.onFinish();
    }

    // live mode: one event stream per running row (a queued row shows no
    // progress; its start bumps the change signal), so at most as many
    // connections as audits run at once (EKTE_MAX_PARALLEL_AUDITS);
    // opts.skip(id) leaves out a run the page follows itself. EventSource
    // reconnects by itself after a drop (the server replays the log: the
    // count starts again); a stream the browser gives up on is closed, and
    // the next ekte:live reads /api/jobs again. A run whose stream said
    // "done" is not reopened by an answer from before it ended.
    var ended = {};
    function syncStreams() {
      var running = {};
      st.rows.forEach(function (j) {
        if (j.status === "running" && !ended[j.id] && !(opts.skip && opts.skip(j.id))) running[j.id] = true;
      });
      Object.keys(streams).forEach(function (id) { if (!running[id]) closeStream(id); });
      Object.keys(running).forEach(function (id) { if (!streams[id]) openStream(id); });
    }
    function closeStream(id) {
      var s = streams[id];
      if (!s) return;
      try { s.es.close(); } catch (e) { /* closed */ }
      delete streams[id];
    }
    function openStream(id) {
      if (typeof EventSource !== "function") return;
      var es;
      try { es = new EventSource("/api/jobs/" + encodeURIComponent(id) + "/events"); } catch (e) { return; }
      var s = streams[id] = { es: es, prog: progress(), opened: false };
      es.onopen = function () {
        if (streams[id] !== s) return;
        if (s.opened) s.prog = progress(); // a reconnect: the log is replayed from the start
        s.opened = true;
      };
      es.onmessage = function (m) {
        if (streams[id] !== s) return;
        var ev;
        try { ev = JSON.parse(m.data); } catch (e) { return; }
        s.prog.add(ev);
        if (ev && ev.type === "done") {
          // the run ended: read /api/jobs now (not only when the change signal says so)
          ended[id] = true;
          closeStream(id);
          refresh();
          return;
        }
        onProgress(id, s.prog);
      };
      es.onerror = function () { if (streams[id] === s && es.readyState === 2) closeStream(id); };
    }
    // one stream event: re-render only when what a row shows changed, at
    // most once a frame (a replayed log arrives as a burst)
    function onProgress(id, prog) {
      var j = null;
      for (var i = 0; i < st.rows.length; i++) if (st.rows[i].id === id) { j = st.rows[i]; break; }
      if (!j) return;
      var before = [j.status, j.progress, j.done, j.total].join();
      var status = prog.status();
      if (status === "running" || status === "queued") j.status = status;
      if (prog.known()) {
        var c = prog.counts();
        j.progress = prog.pct();
        j.done = c.done;
        j.total = c.total;
      }
      if ([j.status, j.progress, j.done, j.total].join() !== before) renderSoon();
    }
    var frame = null;
    function renderSoon() {
      if (typeof requestAnimationFrame !== "function") { render(); return; }
      if (frame != null) return;
      frame = requestAnimationFrame(function () { frame = null; render(); });
    }

    // a refresh asked while one is in flight reads /api/jobs once more when
    // it is back: that answer may predate the change it was asked for
    function refresh() {
      if (st.busy) {
        st.again = true;
        return st.busy;
      }
      clearTimeout(st.timer);
      st.timer = null;
      st.due = false;
      st.again = false;
      st.busy = fetch("/api/jobs")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d) apply(d.jobs); })
        .catch(function () {})
        .then(function () {
          st.busy = null;
          if (st.again && follows) return refresh();
          schedule();
        });
      return st.busy;
    }

    function stateHTML(j) {
      if (j.status === "queued") {
        var hosts = (j.waiting_for || []).join(", ");
        return esc(hosts
          ? Tf("排队中：{h} 正在进行另一项检测", "Queued: another audit is using {h}", { h: hosts })
          : T("排队中：等待空闲的检测位", "Queued: waiting for a free audit slot"));
      }
      // a refusal (e.g. a re-score that would have no score, issue 306) is no failure:
      // the run is unchanged and the reason says why
      if (j.status === "error" && j.refused) return esc(T("未重新评分：", "Not re-scored: ")) + esc(srvT(j.error || ""));
      if (j.status === "error") return esc(T("检测失败：", "Audit failed: ")) + esc(srvT(j.error || ""));
      var line = "<b>" + esc(T("正在运行", "Running now")) + "</b>";
      if (j.total) line += " · " + esc(Tf("已完成 {n} / {total} 项检测", "{n} of {total} checks done", { n: j.done || 0, total: j.total }));
      if (j.started) line += " · " + esc(fmtTime(j.started));
      return line;
    }
    function rowHTML(j) {
      var mon = j.kind === "monitor";
      var title = j.claimed_model || j.model || "?";
      var pct = Math.max(0, Math.min(100, Number(j.progress) || 0));
      var q = j.status === "queued";
      var label = Tf("{name} 的运行进度", "Progress of {name}", { name: title });
      var prog = isActive(j)
        ? '<div class="jprog"><div class="bar' + (q ? " q" : "") + '" role="progressbar" aria-valuemin="0" aria-valuemax="100"' +
          (q ? "" : ' aria-valuenow="' + pct + '"') + ' aria-label="' + esc(label) + '"><span style="width:' + pct + '%"></span></div>' +
          "<b>" + (q ? "" : esc(window.EkteFmt.unit(pct / 100, "ratio", { digits: 0 }))) + "</b></div>"
        : "";
      var live = isActive(j)
        ? '<a class="btn sm pri" href="/?job=' + encodeURIComponent(j.id) + '">' + ico("eye") + esc(T("实时查看", "Watch live")) + "</a>"
        : "";
      var open = (mon
        ? '<a class="btn sm" href="/watches#w-' + esc(j.watch_id) + '">' + ico("bell") + esc(T("打开监控", "Open monitor")) + "</a>"
        : "") + live;
      var cancel = isActive(j)
        ? '<button type="button" class="btn sm danger" data-jcancel="' + esc(j.id) + '">' + ico("x") + esc(T("取消", "Cancel")) + "</button>"
        : "";
      var cls = j.status === "error" ? (j.refused ? " refused" : " err") : "";
      return '<li class="job' + cls + '" data-job="' + esc(j.id) + '"><div class="jmain">' +
        '<div class="jt">' + esc(title) + ' <span class="key">' + esc(j.suite || "standard") + "</span>" +
        (j.api ? ' <span class="key">' + esc(j.api) + (j.api_auto ? " (" + esc(detectLabel("auto")) + ")" : "") + "</span>" : "") +
        (j.stream_mode ? ' <span class="key">' + esc(streamLabel(j.stream_mode)) + "</span>" : "") +
        (mon ? ' <span class="key">' + esc(T("监控", "Monitor")) + "</span>" : "") + "</div>" +
        '<div class="ju">' + esc(j.base_url || "") + "</div>" +
        '<div class="js" role="status">' + stateHTML(j) + (st.msg[j.id] ? " · " + esc(st.msg[j.id]()) : "") + "</div>" +
        prog + '</div><div class="jact">' + open + cancel + "</div></li>";
    }
    function render() {
      var a = document.activeElement;
      var focusId = a && a.getAttribute && list.contains(a) ? a.getAttribute("data-jcancel") : null;
      list.innerHTML = st.rows.map(rowHTML).join("");
      if (focusId) {
        var again = list.querySelector('[data-jcancel="' + focusId + '"]');
        if (again) again.focus();
      }
      if (opts.onChange) opts.onChange(Object.keys(st.active).length, st.rows.length);
    }

    list.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-jcancel]");
      if (!b) return;
      var id = b.getAttribute("data-jcancel");
      var row = st.rows.filter(function (j) { return j.id === id; })[0];
      var url = row && row.kind === "monitor"
        ? "/api/watches/" + encodeURIComponent(row.watch_id) + "/cancel"
        : "/api/jobs/" + encodeURIComponent(id) + "/cancel";
      b.disabled = true;
      fetch(url, { method: "POST" })
        .then(function (r) {
          if (!r.ok) st.msg[id] = function () { return T("无法取消运行，请重试。", "Could not cancel the run — please try again."); };
        })
        .catch(function () {})
        // a poll already in flight may predate the cancel: wait, then poll again
        .then(function () { return st.busy; })
        .then(refresh);
    });
    window.addEventListener("ekte:lang", render);
    if (follows) window.addEventListener("ekte:live", function () { refresh(); });

    if (polls || follows) refresh();
    return { refresh: refresh, rows: function () { return st.rows.slice(); }, set: apply };
  }

  // the performance probes (ekte/web/jobs.py _PROBES)
  var PROBES = ["performance", "performance.embed", "performance.rerank"];
  function progress() {
    var c = { total: 0, done: 0, planned: 0, probeDone: 0, current: null, status: null };
    return {
      add: function (ev) {
        if (!ev || typeof ev !== "object") return;
        var t = ev.type;
        if (t === "queued" || t === "running" || t === "done") c.status = t;
        else if (t === "start") { c.total = Number(ev.total) || 0; c.planned = Number(ev.probe_requests) || 0; }
        else if (t === "detector_start") c.current = ev.id;
        else if (t === "detector_done") { c.done = (Number(ev.index) || 0) + 1; c.current = null; }
        else if (t === "requests") {
          // request_done records, batched by the stream
          (ev.records || []).forEach(function (r) {
            if (r && PROBES.indexOf(r.detector) >= 0 && r.endpoint === "target") c.probeDone++;
          });
        }
      },
      pct: function () {
        if (!c.total) return 0;
        var done = c.done;
        if (PROBES.indexOf(c.current) >= 0 && c.planned) done += Math.min(c.probeDone / c.planned, 1);
        return Math.max(0, Math.min(99, Math.floor(done * 100 / c.total)));
      },
      status: function () { return c.status; },
      // the run's size is known (a "start" event was seen)
      known: function () { return c.total > 0; },
      // the counters /api/jobs lists beside the percent
      counts: function () { return { done: c.done, total: c.total, current: c.current }; },
    };
  }

  window.EkteJobs = { init: init, progress: progress };
})();
