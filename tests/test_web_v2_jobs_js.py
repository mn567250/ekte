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
global.window = { addEventListener() {} };
global.document = { hidden: false, addEventListener() {}, activeElement: null };
global.setTimeout = (fn, ms) => { timers.push(ms); return timers.length; };
global.clearTimeout = () => {};
global.fetch = (url) => { fetched.push(url); return Promise.resolve({ ok: true, json: () => ({ jobs: [] }) }); };
require(path.join(process.argv[1], "jobs.js"));
const J = window.EkteJobs;
const body = new Function("J", "timers", "fetched", "return (async () => {" + process.argv[2] + "})();");
body(J, timers, fetched).then((out) => console.log(JSON.stringify(out === undefined ? null : out)),
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
