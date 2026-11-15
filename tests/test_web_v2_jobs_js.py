"""The Running list helper (ekte/web/static/v2/jobs.js) under node (#160):
EkteJobs.progress() counts a run's progress from its event stream as the
server counts it for /api/jobs (ekte/web/jobs.py track_progress /
progress_pct), and init(list, {poll: false}) never polls: the page hands in
the jobs with set()."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from ekte.web import jobs
from tests._helpers import run_subprocess

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")

STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"

_JS = r"""
const path = require("path");
const timers = [], fetched = [];
const handlers = {}, streams = [];
global.window = { addEventListener(name, fn) { (handlers[name] = handlers[name] || []).push(fn); } };
global.EventSource = function (url) { this.url = url; this.closed = false; streams.push(this); };
global.EventSource.prototype.close = function () { this.closed = true; };
global.document = { hidden: false, addEventListener() {}, activeElement: null };
global.setTimeout = (fn, ms) => { timers.push(ms); return timers.length; };
global.clearTimeout = () => {};
global.fetch = (url) => { fetched.push(url); return Promise.resolve({ ok: true, json: () => ({ jobs: [] }) }); };
require(path.join(process.argv[1], "fmt.js"));
require(path.join(process.argv[1], "jobs.js"));
const J = window.EkteJobs;
const body = new Function("J", "timers", "fetched", "handlers", "streams",
  "return (async () => {" + process.argv[2] + "})();");
body(J, timers, fetched, handlers, streams).then((out) => console.log(JSON.stringify(out === undefined ? null : out)),
  (err) => { console.error(err && err.stack || err); process.exit(1); });
"""


def run(body: str) -> Any:
    out = run_subprocess(["node", "-e", _JS, str(STATIC), body],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


# one run's events as the stream sends them (request_done records batched into "requests")
EVENTS: list[dict[str, Any]] = [
    {"type": "queued", "waiting_for": ["relay.example"]},
    {"type": "running"},
    {"type": "start", "total": 4, "probe_requests": 8},
    {"type": "detector_start", "id": "identity"},
    {"type": "detector_done", "id": "identity", "index": 0},
    {"type": "detector_start", "id": "performance"},
    {"type": "requests", "records": [{"detector": "performance", "endpoint": "target"}] * 3
     + [{"detector": "performance", "endpoint": "baseline"}, {"detector": "identity", "endpoint": "target"}]},
    {"type": "requests", "records": [{"detector": "performance", "endpoint": "target"}] * 2},
    {"type": "detector_done", "id": "performance", "index": 1},
    {"type": "detector_start", "id": "capability"},
    {"type": "detector_done", "id": "capability", "index": 2},
    {"type": "done"},
]


def _server_pcts() -> list[int]:
    state: dict[str, Any] = {}
    out = []
    for ev in EVENTS:
        if ev["type"] == "requests":
            for rec in ev["records"]:
                jobs.track_progress(state, {"type": "request_done", "record": rec})
        else:
            jobs.track_progress(state, ev)
        out.append(jobs.progress_pct(state))
    return out


def test_progress_counts_as_the_server_does():
    got = run(f"""
      const p = J.progress(), out = [];
      for (const ev of {json.dumps(EVENTS)}) {{ p.add(ev); out.push([p.pct(), p.status(), p.known(), p.counts()]); }}
      p.add(null); p.add("x");
      return out;
    """)
    assert [g[0] for g in got] == _server_pcts()
    assert [g[1] for g in got][:3] == ["queued", "running", "running"] and got[-1][1] == "done"
    assert [g[2] for g in got][:3] == [False, False, True]
    assert max(g[0] for g in got) <= 99
    assert got[5][3] == {"done": 1, "total": 4, "current": "performance"} and got[-1][3]["done"] == 3


def test_poll_false_never_polls_and_shows_what_it_is_given():
    got = run("""
      const list = { innerHTML: "", contains: () => false, addEventListener() {}, querySelector: () => null };
      const seen = [];
      const j = J.init(list, { kind: "monitor", poll: false, onChange: (a, n) => seen.push([a, n]) });
      await Promise.resolve();
      j.set([{ id: "monitor-1", kind: "monitor", watch_id: 1, status: "running", progress: 40 },
             { id: "job-2", kind: "audit", status: "running" }]);
      j.set([]);
      return { timers, fetched, seen, rows: j.rows() };
    """)
    assert got["fetched"] == [] and got["timers"] == []
    assert got["seen"] == [[1, 1], [0, 0]]
    assert got["rows"] == []


def test_polling_stays_the_default():
    got = run("""
      const list = { innerHTML: "", contains: () => false, addEventListener() {}, querySelector: () => null };
      J.init(list, {});
      await new Promise((r) => setImmediate(r));
      return { timers, fetched };
    """)
    assert got["fetched"] == ["/api/jobs"] and got["timers"]


def test_live_mode_reads_jobs_on_the_change_signal_and_follows_streams():
    """The Audit page (#161): /api/jobs once at start and on every ekte:live,
    progress from each active run's event stream, nothing on a timer."""
    got = run("""
      let answer = [{ id: "job-1", kind: "audit", status: "running", progress: 0 }];
      global.fetch = (url) => { fetched.push(url); return Promise.resolve({ ok: true, json: () => ({ jobs: answer }) }); };
      const list = { innerHTML: "", contains: () => false, addEventListener() {}, querySelector: () => null };
      const j = J.init(list, { kind: "audit", live: true });
      await new Promise((r) => setImmediate(r));
      const first = { fetched: fetched.slice(), streams: streams.map((s) => s.url) };
      const es = streams[0];
      es.onmessage({ data: JSON.stringify({ type: "running" }) });
      es.onmessage({ data: JSON.stringify({ type: "start", total: 4 }) });
      es.onmessage({ data: JSON.stringify({ type: "detector_done", index: 1 }) });
      const row = j.rows()[0];
      answer = [];
      handlers["ekte:live"].forEach((fn) => fn());
      await new Promise((r) => setImmediate(r));
      return { first, timers, fetched, pct: row.progress, done: row.done, closed: es.closed, rows: j.rows() };
    """)
    assert got["first"] == {"fetched": ["/api/jobs"], "streams": ["/api/jobs/job-1/events"]}
    assert got["timers"] == []
    assert got["fetched"] == ["/api/jobs", "/api/jobs"]
    assert got["pct"] == 50 and got["done"] == 2
    assert got["closed"] is True and got["rows"] == []


def test_live_mode_streams_running_rows_only_and_rereads_after_done():
    """No stream for a queued run or one the page follows itself; a "done"
    reads /api/jobs at once, again after an answer that was in flight, and
    an answer from before the end does not reopen the stream."""
    got = run("""
      const queue = [];
      global.fetch = (url) => { fetched.push(url);
        return new Promise((resolve) => queue.push(resolve)); };
      const answer = (jobs) => queue.shift()({ ok: true, json: () => ({ jobs }) });
      const tick = () => new Promise((r) => setImmediate(r));
      const list = { innerHTML: "", contains: () => false, addEventListener() {}, querySelector: () => null };
      const run = (id, status) => ({ id, kind: "audit", status, progress: 0 });
      const j = J.init(list, { kind: "audit", live: true, skip: (id) => id === "job-3" });
      answer([run("job-1", "running"), run("job-2", "queued"), run("job-3", "running")]);
      await tick();
      const opened = streams.map((s) => s.url);
      // the change signal asks while the run ends: the stale answer comes back after "done"
      handlers["ekte:live"].forEach((fn) => fn());
      streams[0].onmessage({ data: JSON.stringify({ type: "done" }) });
      const inFlight = fetched.length;
      answer([run("job-1", "running"), run("job-2", "running")]);
      await tick();
      const afterStale = { streams: streams.map((s) => [s.url, s.closed]), fetched: fetched.length };
      answer([run("job-2", "running")]);
      await tick();
      return { opened, inFlight, afterStale, rows: j.rows().map((r) => r.id), timers,
               streams: streams.map((s) => [s.url, s.closed]) };
    """)
    assert got["opened"] == ["/api/jobs/job-1/events"]
    assert got["inFlight"] == 2  # the done joined the refresh in flight ...
    assert got["afterStale"]["fetched"] == 3  # ... which reads once more when it is back
    # job-1 ended: the stale answer did not reopen its stream; job-2 now runs
    assert got["afterStale"]["streams"] == [["/api/jobs/job-1/events", True], ["/api/jobs/job-2/events", False]]
    assert got["rows"] == ["job-2"] and got["timers"] == []


def test_the_audit_page_follows_the_change_signal():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<script src="/static/live.js"></script>' in page
    assert "live: true," in page
