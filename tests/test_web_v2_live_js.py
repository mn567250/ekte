"""The change-signal poller (ekte/web/static/v2/live.js, #156), evaluated under
node: its pure scheduling helper ``EkteLive.createPoller`` with a fake clock,
a fake ``/api/version`` and a visibility switch. No event for the first
answer, one event per changed token, no polling while hidden, one poll on
becoming visible again, errors silent and retried on the next tick."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests._helpers import run_subprocess

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")

STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"

# a fake environment: clock (advance), answers (queue; an Error rejects),
# visibility, the emitted events and the number of requests
_JS = r"""
const path = require("path");
global.window = {};
require(path.join(process.argv[1], "live.js"));
const L = window.EkteLive;
function makeEnv() {
  const env = { now: 0, timers: [], answers: [], events: [], asks: 0, shown: true, nextId: 1 };
  env.ask = () => {
    env.asks++;
    const a = env.answers.length ? env.answers.shift() : env.last;
    if (a instanceof Error) return Promise.reject(a);
    env.last = a;
    return Promise.resolve(a);
  };
  env.visible = () => env.shown;
  env.emit = (name, detail) => env.events.push([name, detail]);
  env.setTimeout = (fn, ms) => { const id = env.nextId++; env.timers.push({ id, at: env.now + ms, fn }); return id; };
  env.clearTimeout = (id) => { env.timers = env.timers.filter((t) => t.id !== id); };
  const flush = () => new Promise((r) => setImmediate(r));
  // run the clock forward by ms, firing due timers and settling promises
  env.advance = async (ms) => {
    const end = env.now + ms;
    for (;;) {
      await flush(); await flush();
      env.timers.sort((a, b) => a.at - b.at);
      const t = env.timers[0];
      if (!t || t.at > end) break;
      env.timers.shift();
      env.now = t.at;
      t.fn();
    }
    env.now = end;
    await flush(); await flush();
  };
  return env;
}
const body = new Function("L", "makeEnv", "return (async () => {" + process.argv[2] + "})();");
body(L, makeEnv).then((out) => console.log(JSON.stringify(out === undefined ? null : out)),
  (err) => { console.error(err && err.stack || err); process.exit(1); });
"""


def run(body: str) -> Any:
    out = run_subprocess(
        ["node", "-e", _JS, str(STATIC), body],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    return json.loads(out)


SETUP = """
const env = makeEnv();
env.answers.push({ data: "d1", live: "l1" });
const p = L.createPoller(env);
"""


def test_the_first_answer_is_only_the_baseline() -> None:
    out = run(SETUP + """
p.start();
await env.advance(0);
const first = { asks: env.asks, events: env.events.length, tokens: p.tokens() };
await env.advance(25000);  // two more ticks, same tokens
return { first, asks: env.asks, events: env.events.length };
""")
    assert out["first"] == {"asks": 1, "events": 0, "tokens": {"data": "d1", "live": "l1"}}
    assert out == {**out, "asks": 3, "events": 0}


def test_a_changed_token_dispatches_its_event() -> None:
    out = run(SETUP + """
env.answers.push({ data: "d2", live: "l1" }, { data: "d2", live: "l2" }, { data: "d3", live: "l3" });
p.start();
await env.advance(30000);
return env.events;
""")
    assert out == [
        ["ekte:data", {"before": "d1", "after": "d2"}],
        ["ekte:live", {"before": "l1", "after": "l2"}],
        ["ekte:data", {"before": "d2", "after": "d3"}],
        ["ekte:live", {"before": "l2", "after": "l3"}],
    ]


def test_every_ten_seconds_while_visible() -> None:
    out = run(SETUP + """
p.start();
const at = [];
for (const ms of [0, 9999, 1, 10000, 10000]) { await env.advance(ms); at.push(env.asks); }
return at;
""")
    assert out == [1, 1, 2, 3, 4]


def test_no_polling_while_hidden_one_poll_on_becoming_visible() -> None:
    out = run(SETUP + """
p.start();
await env.advance(0);
env.shown = false; p.onVisibility();
await env.advance(60000);
const hidden = { asks: env.asks, pending: p.pending() };
env.answers.push({ data: "d2", live: "l1" });
env.shown = true; p.onVisibility();
await env.advance(0);
const shown = { asks: env.asks, events: env.events };
await env.advance(10000);
return { hidden, shown, after: env.asks };
""")
    assert out["hidden"] == {"asks": 1, "pending": False}
    assert out["shown"] == {"asks": 2, "events": [["ekte:data", {"before": "d1", "after": "d2"}]]}
    assert out["after"] == 3


def test_a_tab_loaded_hidden_takes_its_baseline_then_waits() -> None:
    # opened in the background: one request with the page's own load (the
    # baseline), none after it, and a change made meanwhile is noticed on show
    out = run(SETUP + """
env.shown = false;
p.start();
await env.advance(60000);
const before = [env.asks, p.pending()];
env.answers.push({ data: "d2", live: "l1" });
env.shown = true; p.onVisibility();
await env.advance(0);
p.stop(); env.shown = false; p.start();  // a later start while hidden: nothing
await env.advance(30000);
return [before, env.asks, env.events];
""")
    assert out == [[1, False], 2, [["ekte:data", {"before": "d1", "after": "d2"}]]]


def test_a_tick_while_hidden_skips_and_a_fast_show_hide_asks_once() -> None:
    # hidden between two ticks without a visibilitychange (a missed event):
    # the due tick asks nothing and schedules nothing
    out = run(SETUP + """
p.start();
await env.advance(0);
env.shown = false;
await env.advance(30000);
const asks = env.asks;
env.shown = true; p.onVisibility(); p.onVisibility();  // shown twice: one request
await env.advance(0);
return [asks, env.asks];
""")
    assert out == [1, 2]


def test_errors_are_silent_and_retried_on_the_next_tick() -> None:
    out = run(SETUP + """
env.answers.push(new Error("offline"), { data: "d2", live: "l1" });
p.start();
await env.advance(10000);
const mid = { asks: env.asks, events: env.events.length, tokens: p.tokens() };
await env.advance(10000);
return { mid, asks: env.asks, events: env.events };
""")
    assert out["mid"] == {"asks": 2, "events": 0, "tokens": {"data": "d1", "live": "l1"}}
    assert out["asks"] == 3
    assert out["events"] == [["ekte:data", {"before": "d1", "after": "d2"}]]


def test_a_throwing_ask_is_an_error_too() -> None:
    out = run(SETUP + """
let n = 0;
const ask = env.ask;
env.ask = () => { if (++n === 2) throw new Error("boom"); return ask(); };
p.start();
await env.advance(20000);
return env.asks + n;
""")
    assert out == 2 + 3  # three calls, the second threw before reaching the fake


def test_stop_and_start() -> None:
    out = run(SETUP + """
p.start();
await env.advance(0);
p.stop();
await env.advance(60000);
const stopped = [env.asks, p.running(), p.pending()];
p.start();
await env.advance(0);
p.start();  // a second start changes nothing
await env.advance(0);
return { stopped, asks: env.asks, running: p.running() };
""")
    assert out == {"stopped": [1, False, False], "asks": 2, "running": True}


def test_one_request_at_a_time() -> None:
    out = run("""
const env = makeEnv();
let release;
env.ask = () => { env.asks++; return new Promise((r) => { release = () => r({ data: "d", live: "l" }); }); };
const p = L.createPoller(env);
p.start();
await env.advance(0);
p.poll(); env.shown = true; p.onVisibility();
await env.advance(50000);  // the answer is still on its way: no new tick
const waiting = [env.asks, p.pending()];
release();
await env.advance(0);
return { waiting, pending: p.pending() };
""")
    assert out == {"waiting": [1, False], "pending": True}


def test_loaded_twice_keeps_one_instance() -> None:
    out = run("""
const first = window.EkteLive;
delete require.cache[require.resolve(require("path").join(process.argv[1], "live.js"))];
require(require("path").join(process.argv[1], "live.js"));
return [window.EkteLive === first, L.INTERVAL];
""")
    assert out == [True, 10000]


def test_the_page_poller_uses_a_plain_fetch_and_visibility() -> None:
    src = (STATIC / "live.js").read_text(encoding="utf-8")
    assert 'fetch("/api/version"' in src
    assert "cache:" not in src  # the browser revalidates by ETag (no cache mode override)
    assert 'document.visibilityState === "visible"' in src
    assert 'addEventListener("visibilitychange"' in src
    assert "setInterval" not in src
