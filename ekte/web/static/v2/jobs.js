/* ekte web UI v2 — the "Running" list of background audits and running
 * monitors (/api/jobs), shared by the Audit page (kind "audit") and the
 * Monitors page (kind "monitor"). Styles: jobs.css.
 *
 * Markup: an empty <ul class="jlist" id="…"></ul> inside the page's own panel.
 *
 * EkteJobs.init(list, opts) polls /api/jobs and renders one <li class="job">
 * per queued / running run of that kind (a progress bar with role=progressbar,
 * "Watch live", "Open monitor" for monitors, Cancel), plus failed runs, which
 * never reach History (the server drops them after a while). It polls every
 * 2 s while a run is active and every 5 s otherwise (so a page notices a
 * run that starts elsewhere); polling pauses while the browser tab is hidden and
 * catches up when it is shown again. Re-renders on "ekte:lang" from cache.
 *   opts.kind            "audit" (everything but monitors, the default) or
 *                        "monitor"
 *   opts.onChange(active, rows)  called after every render with the number
 *                        of queued/running runs and of rows shown
 *   opts.onFinish()      called when a run that was active is no longer
 *                        (finished, failed or cancelled), e.g. to reload a list
 * Returns { refresh(), rows() }: refresh() polls now (returns a promise),
 * rows() the rows currently shown.
 */
(function () {
  "use strict";

  var ACTIVE_MS = 2000, IDLE_MS = 5000;

  var T = function (zh, en) { return window.T ? window.T(zh, en) : en; };
  var Tf = function (zh, en, vars) {
    return T(zh, en).replace(/\{(\w+)\}/g, function (m, k) { return vars && k in vars ? vars[k] : m; });
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

    function schedule() {
      clearTimeout(st.timer);
      st.timer = setTimeout(poll, Object.keys(st.active).length ? ACTIVE_MS : IDLE_MS);
    }
    function poll() {
      st.timer = null;
      if (document.hidden) st.due = true;
      else refresh();
    }
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && st.due) refresh();
    });

    function refresh() {
      if (st.busy) return st.busy;
      clearTimeout(st.timer);
      st.timer = null;
      st.due = false;
      st.busy = fetch("/api/jobs")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) return;
          var rows = (d.jobs || []).filter(mine);
          var now = {}, finished = false;
          rows.forEach(function (j) { if (isActive(j)) now[j.id] = true; });
          Object.keys(st.active).forEach(function (id) { if (!now[id]) finished = true; });
          st.active = now;
          // failed runs never reach History: keep them; cancelled and
          // finished ones go
          st.rows = rows.filter(function (j) { return isActive(j) || j.status === "error"; });
          render();
          if (finished && opts.onFinish) opts.onFinish();
        })
        .catch(function () {})
        .then(function () { st.busy = null; schedule(); });
      return st.busy;
    }

    function stateHTML(j) {
      if (j.status === "queued") {
        var hosts = (j.waiting_for || []).join(", ");
        return esc(hosts
          ? Tf("排队中：{h} 正在进行另一项检测", "Queued: another audit is using {h}", { h: hosts })
          : T("排队中：等待空闲的检测位", "Queued: waiting for a free audit slot"));
      }
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
          "<b>" + (q ? "" : pct + "%") + "</b></div>"
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
      return '<li class="job' + (j.status === "error" ? " err" : "") + '" data-job="' + esc(j.id) + '"><div class="jmain">' +
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

    refresh();
    return { refresh: refresh, rows: function () { return st.rows.slice(); } };
  }

  window.EkteJobs = { init: init };
})();
