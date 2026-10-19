"""Time limits, moving and flashing content, images of text and the contrast of
chart graphics — BITV/EN 301 549 steps axe cannot decide.

9.2.2.1 Timing adjustable, 9.2.2.2 Pause, stop, hide, 9.2.3.1 Three flashes,
9.1.4.5 Images of text, 9.1.4.11 Non-text contrast (charts, meters, progress).

Besides the five pages (as loaded and with every disclosure opened) the checks
visit states only a running app reaches, all without network access:

* ``audit-running``: the audit page following a background audit. The page's
  ``fetch`` is wrapped by an init script that answers ``/api/jobs/<id>`` and
  serves ``/api/jobs/<id>/events`` as an open event stream fed from the test
  (checks done, one running, live performance records), so the scan view with
  its radar, blinking check icon, ticking clock and live chart stays up.
* ``audit-jobs``: the audit page's "Running" tab (v2/jobs.js) with a running
  and a queued background audit (``/api/jobs`` answered by a route), so the
  page polls every 2 s. (This list used to be History's "In progress".)
* ``monitors-running``: Monitors with the monitor running (spinner, progress,
  polling every 2 s).
* ``history-charts``: History with three runs of one relay (sparklines for all
  four trend metrics) whose report carries a ``performance`` block built by
  ``zing.perf.build_performance`` (timeline chart, legend, meters); the seeded
  fixture report has no performance data.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route

from tests.a11y.harness import PAGES, REPORT_FIXTURE, THEMES, assert_no_issues, expand_all, settle
from tests.a11y.test_visual import ANIMATIONS_JS, COLOR_LIB, DESCRIBE
from zing.models import RequestRecord
from zing.perf import build_performance

PAGE_IDS = list(PAGES)
EXPANDED = [f"{p}+expanded" for p in PAGE_IDS]
APP_STATES = ["audit-running", "audit-jobs", "monitors-running"]
ALL_STATES = PAGE_IDS + EXPANDED + APP_STATES
# WCAG 2.3.1 is defined for a 1024 x 768 screen (10 degree field = 341 x 256 px)
XGA = {"width": 1024, "height": 768}

# --------------------------------------------------------------------------- #
# fixture data
# --------------------------------------------------------------------------- #
FAKE_JOB = "a11y-run"


def _perf_records() -> list[RequestRecord]:
    """Every kind of point the timeline draws: target + baseline probe calls,
    non-streamed (hollow), ordinary audit requests (lighter), a cached one and
    a failed one."""
    recs: list[RequestRecord] = []

    def add(**kw: Any) -> None:
        recs.append(RequestRecord(seq=len(recs), **kw))

    for i in range(6):
        add(endpoint="target", phase="probe", detector="performance", ok=True, stream=True, start_ms=1000.0 + i * 1500,
            duration_ms=1200.0 + i * 40, ttft_ms=300.0 + i * 10, decode_tps_local=110.0 - i, output_tokens_local=128)
        add(endpoint="baseline", phase="probe", detector="performance", ok=True, stream=True, start_ms=1100.0 + i * 1500,
            duration_ms=1000.0 + i * 30, ttft_ms=250.0 + i * 5, decode_tps_local=60.0 + i, output_tokens_local=128)
    for i in range(3):
        add(endpoint="target", phase="probe", detector="performance", ok=True, stream=False, start_ms=11000.0 + i * 900,
            duration_ms=1500.0 + i * 50, e2e_tps_local=90.0, output_tokens_local=128)
    for i in range(4):
        add(endpoint="target", phase="passive", detector="connectivity", ok=True, stream=True, start_ms=200.0 + i * 2200,
            duration_ms=900.0 + i * 70, ttft_ms=280.0, decode_tps_local=100.0, output_tokens_local=64)
    add(endpoint="target", phase="passive", detector="billing", ok=True, stream=True, start_ms=9500.0,
        duration_ms=400.0, ttft_ms=120.0, decode_tps_local=150.0, cached=True)
    add(endpoint="target", phase="probe", detector="performance", ok=False, status_code=502, start_ms=13000.0)
    return recs


def _report_with_performance() -> dict[str, Any]:
    rep = json.loads(REPORT_FIXTURE.read_text(encoding="utf-8"))
    perf = build_performance(_perf_records(), has_baseline=True, probe_max_tokens=128)
    assert perf is not None
    rep["performance"] = perf.model_dump(mode="json")
    return rep


def _running_events() -> list[dict[str, Any]]:
    """An audit half-way through: two checks done (with findings for the live
    feed), live performance records, one check still running."""
    dets = json.loads(REPORT_FIXTURE.read_text(encoding="utf-8"))["detectors"]
    total = 5
    evs: list[dict[str, Any]] = [
        {"type": "running"},
        {"type": "start", "total": total, "claimed_model": "test-model", "has_baseline": True, "probe_requests": 24},
    ]
    for i, d in enumerate(dets[:2]):
        base = {"index": i, "total": total, "id": d["id"], "name": d.get("name") or d["id"], "dimension": d.get("dimension")}
        evs.append({"type": "detector_start", **base})
        evs.append({"type": "detector_done", **base, "status": d.get("status"), "score": d.get("score"),
                    "duration_ms": d.get("duration_ms") or 1234, "findings": d.get("findings") or []})
    evs.append({"type": "requests", "records": [r.model_dump(mode="json") for r in _perf_records()]})
    d = dets[2]
    evs.append({"type": "detector_start", "index": 2, "total": total, "id": d["id"], "name": d.get("name") or d["id"],
                "dimension": d.get("dimension")})
    return evs


# Answers the job endpoints in the page itself: Playwright routes cannot keep
# a response body open, and the scan view needs an event stream that stays open.
FAKE_JOB_INIT = (
    """
(() => {
  const JOB = '"""
    + FAKE_JOB
    + """';
  const orig = window.fetch.bind(window);
  const enc = new TextEncoder();
  const json = o => new Response(JSON.stringify(o), { status: 200, headers: { 'Content-Type': 'application/json' } });
  window.fetch = function (input, init) {
    const path = new URL(String(typeof input === 'string' ? input : input.url), location.href).pathname;
    if (path === '/api/jobs/' + JOB) return Promise.resolve(json({ id: JOB, status: 'running', started: Date.now() / 1000 - 12,
      base_url: 'https://relay.example.test/v1', model: 'test-model', claimed_model: 'test-model' }));
    if (path === '/api/jobs/' + JOB + '/cancel') return Promise.resolve(json({ ok: true }));
    if (path === '/api/jobs/' + JOB + '/events') {
      const body = new ReadableStream({ start(c) {
        window.__a11yPush = ev => c.enqueue(enc.encode('data: ' + JSON.stringify(ev) + '\\n\\n'));
      } });
      return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    }
    return orig(input, init);
  };
})();
"""
)

TRENDS_INIT = (
    "try { localStorage.setItem('zing.v2.history.trends', JSON.stringify(['score', 'grade', 'lat', 'tps'])); } catch (e) {}"
)


def _fulfill_json(route: Route, data: Any) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


def _quiet(handler: Callable[[Route], None]) -> Callable[[Route], None]:
    """A route handler that ignores a closed page: a poll still in flight when
    the test's context closes must not fail the next test on this worker."""

    def run(route: Route) -> None:
        with contextlib.suppress(PlaywrightError):
            handler(route)

    return run


def _route_history_charts(page: Page) -> None:
    """Three runs of one relay (trend sparklines) whose reports carry performance data."""
    report = _report_with_performance()

    def history_list(route: Route) -> None:
        rows = route.fetch().json()
        if not rows:
            return _fulfill_json(route, rows)
        r0 = rows[0]
        out = []
        for k, (score, rating, lat, tps) in enumerate(((84, "B", 980.0, 92.0), (71, "C", 1130.0, 81.0), (62, "D", 1240.0, 77.0))):
            out.append(dict(r0, id=r0["id"] if k == 0 else f"a11y-{k}", score=score, rating=rating,
                            latency_p50_ms=lat, decode_tps_p50=tps, ts=r0.get("ts")))
        _fulfill_json(route, out)

    page.route(re.compile(r"/api/history(\?.*)?$"), _quiet(history_list))
    page.route(re.compile(r"/api/history/[^/?]+$"), _quiet(lambda route: _fulfill_json(route, report)))


def _route_audit_jobs(page: Page) -> None:
    now = time.time()
    jobs = {"jobs": [
        {"id": "a11y-j1", "kind": "audit", "status": "running", "progress": 40, "done": 2, "total": 5, "started": now - 30,
         "claimed_model": "test-model", "model": "test-model", "base_url": "https://relay.example.test/v1", "suite": "standard"},
        {"id": "a11y-j2", "kind": "audit", "status": "queued", "waiting_for": ["relay.example.test"],
         "claimed_model": "other-model", "model": "other-model", "base_url": "https://relay.example.test/v1", "suite": "quick"},
    ]}
    page.route(re.compile(r"/api/jobs$"), _quiet(lambda route: _fulfill_json(route, jobs) if route.request.method == "GET" else route.continue_()))


def _route_monitors_running(page: Page) -> None:
    def watches(route: Route) -> None:
        if route.request.method != "GET":
            return route.continue_()
        rows = route.fetch().json()
        _fulfill_json(route, [dict(w, running=True, progress=40) for w in rows])

    page.route(re.compile(r"/api/watches$"), _quiet(watches))


def open_state(
    open_page: Any,
    state: str,
    theme: str = "light",
    lang: str = "en",
    init: str | None = None,
    **opts: Any,
) -> Page:
    """Open a page state (see the module docstring). ``init`` is an extra init
    script that must run before the page's own scripts (the page is loaded a
    second time after it is installed)."""
    page_id, _, extra = state.partition("+")
    app = {"audit-running": "audit", "audit-jobs": "audit", "monitors-running": "monitors", "history-charts": "history"}
    path = PAGES[app.get(page_id, page_id)]
    page = open_page(path, lang, theme, **opts)
    reload_needed = init is not None
    if init:
        page.context.add_init_script(init)
    if page_id == "audit-running":
        page.context.add_init_script(FAKE_JOB_INIT)
        path = f"{path}?job={FAKE_JOB}"
        reload_needed = True
    elif page_id == "audit-jobs":
        _route_audit_jobs(page)
        # #running deep-links the tab; tabs.js selects it once jobs.js has
        # rows and enables it
        path = f"{path}#running"
        reload_needed = True
    elif page_id == "monitors-running":
        _route_monitors_running(page)
        reload_needed = True
    elif page_id == "history-charts":
        page.context.add_init_script(TRENDS_INIT)
        _route_history_charts(page)
        reload_needed = True
    if reload_needed:
        page.goto(open_page.base_url + path, wait_until="load")
        settle(page)
    if page_id == "audit-running":
        page.wait_for_function("() => typeof window.__a11yPush === 'function'")
        page.evaluate("evs => evs.forEach(e => window.__a11yPush(e))", _running_events())
        page.wait_for_selector("#dets .det.run", state="visible")
        page.wait_for_selector("#perf-live .zp-chart", state="visible")
        settle(page)
    elif page_id == "audit-jobs":
        page.wait_for_selector("#panel-running .jlist .job", state="visible")
    elif page_id == "monitors-running":
        page.wait_for_selector(".spin", state="visible")
    elif page_id == "history-charts":
        page.wait_for_selector(".trend svg", state="visible")
    if extra == "expanded":
        expand_all(page)
    if page_id == "history-charts":
        # one report open (the rows are an accordion), every dimension in it
        page.locator(".row .rmain").first.click()
        page.wait_for_selector(".panel:not([hidden]) .zr-dim .dtog", state="visible")
        page.evaluate(
            """() => { for (const b of document.querySelectorAll('.panel:not([hidden]) .dtog[aria-expanded=false]')) b.click();
                       for (const d of document.querySelectorAll('.panel:not([hidden]) details:not([open])')) d.open = true; }"""
        )
        page.wait_for_function("() => [...document.querySelectorAll('.zp-chart')].some(e => e.getClientRects().length)")
        settle(page)
    return page


# --------------------------------------------------------------------------- #
# 9.2.2.1 Timing adjustable
# --------------------------------------------------------------------------- #
# Installed before the page's scripts: remembers every timer that is pending,
# so that after the observation window the ones not yet due can be fired (as if
# the user had stayed idle for as long as they ask), and counts those that ran.
TIMERS_INIT = """
(() => {
  const T = window.__a11yTimers = { pending: new Map(), fired: [] };
  const st = window.setTimeout, si = window.setInterval, ct = window.clearTimeout, ci = window.clearInterval;
  const run = (fn, args, self) => typeof fn === 'function' ? fn.apply(self, args) : (0, eval)(String(fn));
  window.setTimeout = function (fn, ms, ...args) {
    const rec = { kind: 'timeout', ms: Number(ms) || 0, fn, args };
    const id = st.call(window, function () {
      T.pending.delete(id);
      if (T.fired.length < 500) T.fired.push({ kind: 'timeout', ms: rec.ms });
      return run(fn, args, this);
    }, ms);
    T.pending.set(id, rec);
    return id;
  };
  window.setInterval = function (fn, ms, ...args) {
    const rec = { kind: 'interval', ms: Number(ms) || 0, fn, args };
    const id = si.call(window, function () {
      if (T.fired.length < 500) T.fired.push({ kind: 'interval', ms: rec.ms });
      return run(fn, args, this);
    }, ms);
    T.pending.set(id, rec);
    return id;
  };
  window.clearTimeout = function (id) { T.pending.delete(id); return ct.call(window, id); };
  window.clearInterval = function (id) { T.pending.delete(id); return ci.call(window, id); };
})();
"""

SNAPSHOT_JS = """
() => {
  const vis = el => el.isConnected && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
    && el.getClientRects().length > 0;
  const own = el => { let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent; return t.trim().replace(/\\s+/g, ' '); };
  const texts = [], controls = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (el.closest('[data-a11y-start]')) continue;
    const t = own(el);
    if (t && vis(el)) texts.push({ el, t });
    if (el.matches('button, input:not([type=hidden]), select, textarea, a[href], [role=button], [role=tab]') && vis(el) && !el.disabled
        && el.getAttribute('aria-disabled') !== 'true') controls.push(el);
  }
  window.__a11ySnap = { texts, controls };
  window.__a11ySentinel = true;
  return texts.length;
}
"""

LOSSES_JS = (
    """
() => {
  """
    + DESCRIBE
    + """
  const vis = el => el.isConnected && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
    && el.getClientRects().length > 0;
  const snap = window.__a11ySnap;
  if (!snap) return ['page was replaced (the observation snapshot is gone)'];
  // innerText applies text-transform: compare case-insensitively
  const now = (document.body.innerText || '').replace(/\\s+/g, ' ').toLowerCase();
  const out = [];
  for (const { el, t } of snap.texts) {
    if (vis(el) || now.includes(t.toLowerCase())) continue;
    out.push(`content disappeared without user action: "${t.slice(0, 60)}"` + (el.isConnected ? ` (${describeEl(el)} hidden)` : ' (removed)'));
  }
  for (const el of snap.controls) {
    if (!el.isConnected || !vis(el)) continue;   // removals are reported with their text
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') out.push(`control was disabled without user action: ${describeEl(el)}`);
  }
  return out.slice(0, 20);
}
"""
)

FIRE_PENDING_JS = """
() => {
  const T = window.__a11yTimers; if (!T) return [];
  const due = [...T.pending.entries()].filter(([, r]) => r.ms >= 1000).sort((a, b) => a[1].ms - b[1].ms);
  const fired = [];
  for (const [id, r] of due) {
    if (r.kind === 'timeout') { clearTimeout(id); }
    try { typeof r.fn === 'function' ? r.fn.apply(window, r.args) : (0, eval)(String(r.fn)); } catch (e) { /* the page's own error */ }
    fired.push(`${r.kind} ${r.ms} ms`);
  }
  return fired;
}
"""

META_REFRESH_JS = """
() => [...document.querySelectorAll('meta[http-equiv]')]
  .filter(m => /^refresh$/i.test(m.getAttribute('http-equiv')))
  .map(m => m.getAttribute('content') || '')
"""


def _refresh_delay(content: str) -> float | None:
    m = re.match(r"\s*(\d+(?:\.\d+)?)", content or "")
    return float(m.group(1)) if m else None


@pytest.mark.bitv("9.2.2.1")
@pytest.mark.parametrize("state", PAGE_IDS + EXPANDED + APP_STATES)
def test_no_time_limits(open_page, state: str) -> None:
    """9.2.2.1 Timing adjustable: the page sets no time limit on the user.

    Every timer (setTimeout/setInterval) is recorded by an init script. After
    the page has settled, the visible text and the enabled controls are
    snapshot; the page then idles 5 s, after which every timer still pending
    (>= 1 s, e.g. a 15-minute session timeout) is fired as if the user had kept
    idling. Fails on: a meta refresh or ``Refresh`` header with a delay (axe
    ``meta-refresh`` checks the markup only), any navigation of the document
    without user action, visible content that disappears (unless the same text
    is still shown, i.e. it was merely re-rendered), and controls that become
    disabled (a session that ends). Time limits over 20 hours are exempt by
    WCAG; firing the long timers at once covers them too, so a finding there
    needs a look at the delay given in the message."""
    navs: list[str] = []
    page = open_state(open_page, state, init=TIMERS_INIT)
    issues: list[str] = []
    for content in page.evaluate(META_REFRESH_JS):
        delay = _refresh_delay(content)
        if delay is None or delay > 0:
            issues.append(f'<meta http-equiv="refresh" content="{content}"> reloads/redirects after a delay')
    main = page.main_frame
    page.on("framenavigated", lambda f: navs.append(f.url) if f == main else None)
    page.evaluate(SNAPSHOT_JS)
    page.wait_for_timeout(5000)  # the observation window: nothing the user does
    fired = page.evaluate("() => (window.__a11yTimers ? window.__a11yTimers.fired : []).map(f => f.kind + ' ' + f.ms + ' ms')")
    losses = page.evaluate(LOSSES_JS) if not navs else []
    long_fired: list[str] = []
    if not navs and not losses:
        long_fired = page.evaluate(FIRE_PENDING_JS)
        settle(page)
        losses = page.evaluate(LOSSES_JS) if not navs else []
    if navs or not page.evaluate("() => window.__a11ySentinel === true"):
        issues.append(f"page navigated without user action to {navs[-1] if navs else '(reloaded)'}")
    timers = sorted(set(fired + long_fired))
    issues += [f"{m}  (timers that ran: {', '.join(timers[:8]) or 'none'})" for m in losses]
    refresh = page.request.get(page.url).headers.get("refresh")
    if refresh and (_refresh_delay(refresh) or 0) > 0:
        issues.append(f"HTTP Refresh header '{refresh}' reloads/redirects after a delay")
    assert_no_issues(issues, f"{state} [en] idle 5 s, then pending timers fired", "timing-adjustable")


# --------------------------------------------------------------------------- #
# 9.2.2.2 Pause, stop, hide
# --------------------------------------------------------------------------- #
# Observes the page for `ms` and returns every element that visibly changed by
# itself at two or more moments (auto-updating) and every animation that runs
# longer than 5 s (moving / blinking), with the exemptions of the docstring.
OBSERVE_JS = (
    """
async (ms) => {
  """
    + DESCRIBE
    + """
  const vis = el => el.isConnected && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
    && el.getClientRects().length > 0;
  const own = el => { let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent; return t.trim().replace(/\\s+/g, ' '); };
  // structural key: a re-render with identical markup maps to the same keys
  const key = el => { const p = []; for (let e = el; e && e !== document.body; e = e.parentElement)
    p.push(e.tagName + (e.id ? '#' + e.id : ':' + (e.parentElement ? [...e.parentElement.children].indexOf(e) : 0))); return p.reverse().join('>'); };
  const texts = () => { const m = new Map(); for (const el of document.body.querySelectorAll('*')) {
    const t = own(el); if (t && vis(el)) m.set(key(el), { t, el }); } return m; };
  const STATUS = '[role=status],[role=progressbar],[role=meter],[role=timer],[role=log],[role=alert],[aria-live=polite],[aria-live=assertive],output';
  const controlled = el => { for (const c of document.querySelectorAll('[aria-controls]')) {
      if (!vis(c) || c.disabled) continue;
      for (const id of c.getAttribute('aria-controls').split(/\\s+/)) { const t = id && document.getElementById(id); if (t && t.contains(el)) return true; }
    }
    const d = el.closest('details[open]'); return !!(d && d.querySelector(':scope > summary')); };
  const hits = new Map();   // element -> { buckets:Set, kind }
  const t0 = performance.now();
  const hit = (el, kind) => { if (!el || el.nodeType !== 1) return; const h = hits.get(el) || { buckets: new Set(), kind };
    h.buckets.add(Math.floor((performance.now() - t0) / 100)); hits.set(el, h); };
  let prev = texts(), dirty = false;
  const diff = () => { dirty = false; const cur = texts();
    for (const [k, v] of cur) { const p = prev.get(k); if (!p || p.t !== v.t) hit(v.el, 'text'); }
    for (const [k, v] of prev) if (!cur.has(k)) hit(v.el.isConnected ? v.el : null, 'text');
    prev = cur; };
  const ATTRS = ['style', 'class', 'hidden', 'd', 'cx', 'cy', 'r', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'width', 'height', 'points', 'transform', 'src', 'open'];
  const mo = new MutationObserver(recs => {
    for (const r of recs) {
      if (r.type === 'attributes') { if (r.target.getAttribute(r.attributeName) !== r.oldValue && vis(r.target)) hit(r.target, 'attribute'); }
      else if (!dirty) { dirty = true; requestAnimationFrame(diff); }
    }
  });
  mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeOldValue: true, attributeFilter: ATTRS });
  await new Promise(r => setTimeout(r, ms));
  mo.disconnect(); diff();
  const secs = ms / 1000, out = [];
  window.__a11yFlagged = [];
  for (const [el, h] of hits) {
    if (h.buckets.size < 2 || !vis(el)) continue;
    if (el.closest(STATUS) || controlled(el)) continue;
    // report the outermost changing element only
    let p = el.parentElement, inner = false; for (; p; p = p.parentElement) { const ph = hits.get(p); if (ph && ph.buckets.size >= 2) { inner = true; break; } }
    if (inner) continue;
    window.__a11yFlagged.push(el);
    out.push({ desc: describeEl(el), kind: 'updates (' + h.kind + ')', n: h.buckets.size, rate: (h.buckets.size / secs).toFixed(1) + '/s' });
  }
  for (const a of document.getAnimations()) {
    if (a.playState !== 'running' || !a.effect) continue;
    const t = a.effect.getComputedTiming(), el = a.effect.target;
    if (!el || !vis(el)) continue;
    const total = t.activeDuration === Infinity ? Infinity : t.activeDuration + (t.delay || 0);
    if (total <= 5000) continue;
    if (el.closest(STATUS) || controlled(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 48 && r.height <= 48) continue;   // small spinner / busy indicator
    window.__a11yFlagged.push(el);
    const name = a.animationName || a.transitionProperty || 'script animation';
    out.push({ desc: describeEl(el), kind: 'moves/blinks (' + name + ', ' + (t.iterations === Infinity ? 'endless' : Math.round(total) + ' ms') + ')',
               n: 0, rate: Math.round(t.duration) + ' ms per cycle' });
  }
  return out;
}
"""
)

STILL_SHOWN_JS = """
() => (window.__a11yFlagged || []).filter(el => el.isConnected
  && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getClientRects().length > 0).length
"""

# A state may offer a stop/hide control for everything that moves in it; the
# test presses it and checks that the moving / updating content is gone.
HIDE_MECHANISM = {
    # "Continue in background" hides the scan view (and "Cancel" stops it)
    "audit-running": "#bg",
}


@pytest.mark.bitv("9.2.2.2")
@pytest.mark.parametrize("state", PAGE_IDS + EXPANDED + APP_STATES)
def test_auto_updating_content_can_be_paused(open_page, state: str) -> None:
    """9.2.2.2 Pause, stop, hide: the page is observed for 6 s at rest.

    Reported: (1) elements whose visible text, geometry or styling changed by
    themselves at two or more moments (auto-updating; a single change is a
    fetch completing, not an update cycle), with how often; (2) animations that
    run longer than 5 s (moving / blinking). A re-render with identical
    markup and text is no visible update and is not counted.

    Not a violation: updates inside a status container (role status,
    progressbar, meter, timer, log, alert, aria-live, <output>) — status of a
    process the user started, which 4.1.3 wants announced, not stopped; small
    busy indicators (spinner up to 48 x 48 px); content inside a panel a
    visible control can hide (aria-controls, <details>). For an app state that
    offers a stop/hide button for all of it (the running audit's "Continue in
    background"), the button is pressed and must remove every reported item —
    then the mechanism exists and nothing is reported."""
    page = open_state(open_page, state)
    found: list[dict[str, Any]] = page.evaluate(OBSERVE_JS, 6000)
    if found and state in HIDE_MECHANISM:
        btn = page.locator(HIDE_MECHANISM[state])
        if btn.is_visible() and btn.is_enabled():
            btn.click()
            settle(page)
            if page.evaluate(STILL_SHOWN_JS) == 0 and not page.evaluate(OBSERVE_JS, 3000):
                found = []
    issues = [f"{f['kind']}: {f['desc']}" + (f"  {f['n']} changes in 6 s (~{f['rate']})" if f["n"] else f"  {f['rate']}")
              + " — no pause/stop/hide control" for f in found]
    assert_no_issues(issues, f"{state} [en] observed 6 s", "pause-stop-hide")


@pytest.mark.bitv("9.2.2.2")
@pytest.mark.parametrize("state", PAGE_IDS + APP_STATES)
def test_motion_switch_stops_all_motion(open_page, state: str) -> None:
    """9.2.2.2 Pause, stop, hide: the header's "Motion off" switch is an
    on-page way to stop every movement, the running audit's radar and the
    spinners included: no animation loops or runs longer than 200 ms. The
    switch is set while the page runs, as a user would."""
    page = open_state(open_page, state)
    page.locator("select.motion-sel").select_option("off")
    assert page.evaluate("() => document.documentElement.getAttribute('data-motion')") == "off"
    settle(page)
    anims: list[dict[str, Any]] = page.evaluate(ANIMATIONS_JS)
    issues = [
        f"{a['name']} on {a['el']} ({'infinite' if a['infinite'] else str(a['duration']) + ' ms'})"
        for a in anims
        if a["visible"] and (a["infinite"] or (isinstance(a["duration"], (int, float)) and a["duration"] > 200))
    ]
    assert_no_issues(issues, f"{state} [en] with motion off", "motion-switch")


# --------------------------------------------------------------------------- #
# 9.2.3.1 Three flashes or below threshold
# --------------------------------------------------------------------------- #
FLASH_LIB = """
  // WCAG 2.3.1: a flash is a pair of opposing changes in relative luminance of
  // >= 10 % where the darker state is below 0.80, or a pair involving a
  // saturated red; > 3 flashes in any 1 s over > 25 % of a 10-degree field
  // (341 x 256 px at 1024 x 768 -> 21824 px^2) fails.
  const AREA = 21824 * (innerWidth * innerHeight) / (1024 * 768);
  const parseC = c => { const m = /rgba?\\(([^)]+)\\)/.exec(c || ''); if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lin = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const L = c => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const red = c => c[0] + c[1] + c[2] > 0 && c[0] / (c[0] + c[1] + c[2]) >= 0.8;
  const blend = (fg, a, bg) => [0, 1, 2].map(i => fg[i] * a + bg[i] * (1 - a));
  // the colour the element shows: its own and its ancestors' backgrounds
  // composited with their opacity; without an own background its fill / text colour
  const shown = el => {
    const chain = []; for (let p = el; p && p.nodeType === 1; p = p.parentElement) chain.push(p);
    chain.reverse();
    let col = [255, 255, 255], op = 1;
    for (const p of chain) {
      const s = getComputedStyle(p); op *= parseFloat(s.opacity);
      if (s.visibility === 'hidden') continue;
      const c = parseC(s.backgroundColor);
      if (c && c[3] > 0) col = blend(c, c[3] * op, col);
      else if (p === el) {
        const f = parseC(el instanceof SVGElement ? s.fill : s.color);
        if (f && f[3] > 0) col = blend(f, f[3] * op, col);
      }
    }
    return col;
  };
  const area = el => { const r = el.getBoundingClientRect();
    const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
    const h = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)); return w * h; };
  // flashes in the worst 1 s window of a colour series sampled every `dt` ms
  const flashes = (cols, dt) => {
    const tr = [];   // times of qualifying transitions
    let ext = cols[0], dir = 0;
    cols.forEach((c, i) => {
      const a = L(ext), b = L(c), d = b - a;
      const lum = Math.abs(d) >= 0.1 && Math.min(a, b) < 0.8;
      const rd = red(ext) !== red(c);
      if (lum || rd) { const nd = Math.sign(d) || (red(c) ? 1 : -1);
        if (nd !== dir) { tr.push(i * dt); dir = nd; } ext = c; }
      else if ((dir > 0 && b > L(ext)) || (dir < 0 && b < L(ext))) ext = c;   // still moving the same way
    });
    let worst = 0;
    for (let i = 0; i < tr.length; i++) { let j = i; while (j < tr.length && tr[j] - tr[i] < 1000) j++; worst = Math.max(worst, j - i); }
    return worst / 2;
  };
"""

ANIMATION_FLASH_JS = (
    """
() => {
  """
    + DESCRIBE
    + FLASH_LIB
    + """
  const PROPS = /opacity|visibility|color|background|filter|fill|stroke|border|shadow|outline/i;
  const out = [];
  for (const a of document.getAnimations()) {
    const eff = a.effect; if (!eff || !eff.target || eff.pseudoElement) continue;
    const el = eff.target;
    const props = (eff.getKeyframes ? eff.getKeyframes() : []).flatMap(k => Object.keys(k)).filter(p => PROPS.test(p));
    if (a.transitionProperty && PROPS.test(a.transitionProperty)) props.push(a.transitionProperty);
    if (!props.length || area(el) <= AREA) continue;
    // sample the animation's own timeline (paused, so this is exact and
    // independent of machine load): 10 ms steps over its first 2 s
    const t = eff.getComputedTiming(), was = a.playState, cur = a.currentTime;
    const span = Math.min(2000, t.activeDuration === Infinity ? 2000 : t.activeDuration);
    if (!(span > 0)) continue;
    a.pause();
    const cols = [];
    for (let ms = 0; ms <= span; ms += 10) { a.currentTime = (t.delay || 0) + ms; cols.push(shown(el)); }
    a.currentTime = cur; if (was === 'running') a.play();
    const n = flashes(cols, 10);
    if (n > 3) out.push(`${n} flashes/s from ${a.animationName || a.transitionProperty || 'animation'} (${[...new Set(props)].join(', ')}) over ${Math.round(area(el))} px^2: ${describeEl(el)}`);
  }
  return out;
}
"""
)

SAMPLE_FLASH_JS = (
    """
async () => {
  """
    + DESCRIBE
    + FLASH_LIB
    + """
  const big = [...document.body.querySelectorAll('*')].filter(el => area(el) > AREA
    && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }));
  const series = big.map(() => []);
  for (let i = 0; i < 40; i++) {           // every 50 ms for 2 s
    big.forEach((el, k) => series[k].push(shown(el)));
    await new Promise(r => setTimeout(r, 50));
  }
  const out = [];
  big.forEach((el, k) => { const n = flashes(series[k], 50);
    if (n > 3) out.push(`${n} flashes/s measured over ${Math.round(area(el))} px^2: ${describeEl(el)}`); });
  return out;
}
"""
)


@pytest.mark.bitv("9.2.3.1")
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("state", PAGE_IDS + EXPANDED + APP_STATES)
def test_no_flashing_above_threshold(open_page, state: str, theme: str) -> None:
    """9.2.3.1 Three flashes or below threshold, at 1024 x 768.

    (1) Every Web Animation / CSS animation / transition that touches opacity,
    visibility, colour, background, filter, fill, stroke, border or shadow on
    an element larger than 21824 px^2 (25 % of a 10-degree field) is paused
    and stepped through its first 2 s in 10 ms steps; the colour the element
    then shows (backgrounds and opacity of the element and its ancestors
    composited, else its fill / text colour) gives a luminance series. (2) As
    a cross-check for script-driven flashing, every large element is sampled
    the same way every 50 ms for 2 s in real time. A flash is a pair of
    opposing luminance changes >= 0.1 with the darker side < 0.8, or a change
    into / out of saturated red; > 3 in any 1 s fails."""
    page = open_state(open_page, state, theme, viewport=XGA)
    issues = list(page.evaluate(ANIMATION_FLASH_JS)) + list(page.evaluate(SAMPLE_FLASH_JS))
    assert_no_issues(issues, f"{state} [en, {theme}] at 1024x768", "three-flashes")


# --------------------------------------------------------------------------- #
# 9.1.4.5 Images of text
# --------------------------------------------------------------------------- #
IMAGES_JS = (
    """
async () => {
  """
    + DESCRIBE
    + """
  const vis = el => el.isConnected && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
    && el.getClientRects().length > 0;
  const hidden = el => !!el.closest('[aria-hidden=true]');
  const decorative = el => hidden(el) || /^(presentation|none)$/.test(el.getAttribute('role') || '')
    || (el.tagName === 'IMG' && el.getAttribute('alt') === '');
  const urls = v => [...String(v || '').matchAll(/url\\(\\s*(['"]?)(.*?)\\1\\s*\\)/g)].map(m => m[2]);
  const isSvg = u => /^data:image\\/svg\\+xml/i.test(u) || /\\.svg(z)?([?#]|$)/i.test(u);
  const svgCache = new Map();
  const svgHasText = async u => {
    if (!svgCache.has(u)) svgCache.set(u, (async () => {
      try {
        let src;
        if (/^data:/i.test(u)) { const i = u.indexOf(','); const body = u.slice(i + 1);
          src = /;base64/i.test(u.slice(0, i)) ? atob(body) : decodeURIComponent(body); }
        else { const r = await fetch(new URL(u, location.href)); src = await r.text(); }
        return /<(text|textPath)\\b/i.test(src);
      } catch (e) { return false; }
    })());
    return svgCache.get(u);
  };
  const out = [];
  const check = async (el, u, how) => {
    if (!u || u === 'none') return;
    if (isSvg(u)) {
      if (await svgHasText(u)) out.push(`SVG image with <text> (picture of text?) via ${how}: ${describeEl(el)} ${u.slice(0, 80)}`);
      return;
    }
    out.push(`raster image via ${how}, may hold text (review; mark decorative or use real text): ${describeEl(el)} ${u.slice(0, 80)}`);
  };
  for (const el of document.querySelectorAll('img, input[type=image], video[poster], object, embed')) {
    if (!vis(el)) continue;
    const u = el.tagName === 'VIDEO' ? el.poster : el.tagName === 'OBJECT' ? el.data : el.currentSrc || el.src;
    if (el.tagName === 'OBJECT' || el.tagName === 'EMBED') { if (!/^image\\//.test(el.type || '') && !/\\.(png|jpe?g|gif|webp|avif|bmp|svg)/i.test(u || '')) continue; }
    if (decorative(el) && !(isSvg(u) && el.tagName === 'IMG' && el.getAttribute('alt') === '')) { if (!isSvg(u)) continue; }
    await check(el, u, '<' + el.tagName.toLowerCase() + '>');
  }
  for (const el of document.querySelectorAll('canvas')) {
    if (vis(el) && !hidden(el)) out.push(`<canvas> (raster drawing, may hold text; review): ${describeEl(el)}`);
  }
  for (const el of document.querySelectorAll('svg image, svg feImage')) {
    if (!vis(el.closest('svg') || el) || hidden(el)) continue;
    await check(el, el.getAttribute('href') || el.getAttribute('xlink:href'), '<svg><image>');
  }
  for (const el of document.body.querySelectorAll('*')) {
    if (!vis(el)) continue;
    for (const pseudo of [null, '::before', '::after', '::marker']) {
      const s = getComputedStyle(el, pseudo);
      if (pseudo && (s.content === 'none' || s.content === 'normal') && s.backgroundImage === 'none') continue;
      for (const prop of ['backgroundImage', 'maskImage', 'webkitMaskImage', 'borderImageSource', 'listStyleImage', 'content']) {
        for (const u of urls(s[prop])) {
          if (hidden(el) && !isSvg(u)) continue;   // decorative: hidden from assistive tech
          await check(el, u, `CSS ${prop}${pseudo || ''}`);
        }
      }
    }
  }
  // inline SVG <text>: allowed for charts / logos that have an accessible equivalent
  for (const svg of document.querySelectorAll('svg')) {
    if (!vis(svg) || svg.parentElement.closest('svg')) continue;
    const txt = [...svg.querySelectorAll('text, textPath')].map(t => t.textContent.trim()).filter(Boolean);
    if (!txt.length) continue;
    const name = (svg.getAttribute('aria-label') || '').trim()
      || (svg.getAttribute('aria-labelledby') || '').split(/\\s+/).map(id => (document.getElementById(id) || {}).textContent || '').join('').trim()
      || ((svg.querySelector(':scope > title') || {}).textContent || '').trim();
    const named = !hidden(svg) && /^(img|graphics-document|figure)$/.test(svg.getAttribute('role') || 'img') && name;
    if (!named) out.push(`inline <svg> shows text "${txt.join(' ').slice(0, 40)}" without an accessible name / equivalent: ${describeEl(svg.parentElement)}`);
  }
  return [...new Set(out)];
}
"""
)


@pytest.mark.bitv("9.1.4.5")
@pytest.mark.parametrize("state", PAGE_IDS + EXPANDED + ["audit-running", "history-charts"])
def test_no_images_of_text(open_page, state: str) -> None:
    """9.1.4.5 Images of text, without OCR: a guard that no picture can carry text.

    Enumerates <img>, <picture>, <input type=image>, video posters, image
    <object>/<embed>, <canvas>, <svg><image>, and CSS background-image,
    mask-image, border-image, list-style-image and content: url() (also on
    ::before / ::after / ::marker). Raster images (anything but SVG) fail for
    human review unless purely decorative (alt="", role=presentation/none or
    aria-hidden); a canvas always does. SVG images are fetched and fail if they
    contain <text>; inline SVG with <text> passes only as a chart / logo with an
    accessible name (the performance chart: role=img, a summary as aria-label
    and a data table). Today the UI uses inline SVG paths only, so any image
    added later is flagged here."""
    page = open_state(open_page, state)
    assert_no_issues(page.evaluate(IMAGES_JS), f"{state} [en]", "images-of-text")


# --------------------------------------------------------------------------- #
# 9.1.4.11 Non-text contrast: charts, meters, progress bars
# --------------------------------------------------------------------------- #
GRAPHICS_JS = (
    """
() => {
  """
    + COLOR_LIB
    + DESCRIBE
    + """
  const vis = el => el.isConnected && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
    && el.getClientRects().length > 0 && (el.getBoundingClientRect().width > 0 || el.getBoundingClientRect().height > 0);
  const opac = (el, stop) => { let a = 1; for (let p = el; p && p !== stop; p = p.parentElement) a *= parseFloat(getComputedStyle(p).opacity); return a; };
  const withA = (c, a) => [c[0], c[1], c[2], c[3] * a];
  const hex = c => '#' + c.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const out = new Map();
  const add = (k, msg) => { const e = out.get(k); if (e) e.n++; else out.set(k, { msg, n: 1 }); };
  // decorative parts of a chart: gridlines, the shaded area under a line (the
  // line carries the data), a dashed reference baseline, the performance
  // chart's p25–p75 wash around its running median (the line carries it; the
  // values are in the data table)
  const DECOR = '.zp-grid, .area, .base, .zp-band path';
  for (const svg of document.querySelectorAll('svg')) {
    if (!vis(svg) || svg.closest('[aria-hidden=true]') || svg.parentElement.closest('svg')) continue;
    if ((svg.getAttribute('role') || '') !== 'img') continue;   // charts; icons are aria-hidden
    const bg = bgOf(svg.parentElement || svg);
    const name = (svg.getAttribute('aria-label') || '').slice(0, 40);
    for (const sh of svg.querySelectorAll('circle, ellipse, rect, line, polyline, polygon, path')) {
      if (sh.closest('defs, clipPath, mask, marker, pattern, symbol') || sh.matches(DECOR) || !vis(sh)) continue;
      const s = getComputedStyle(sh), a = opac(sh, svg.parentElement);
      const cands = [];
      const f = parse(s.fill);
      if (f && f[3] > 0) cands.push(['fill', over(withA(f, parseFloat(s.fillOpacity) * a), bg)]);
      const k = parse(s.stroke);
      if (k && k[3] > 0 && parseFloat(s.strokeWidth) >= 1) cands.push(['stroke', over(withA(k, parseFloat(s.strokeOpacity) * a), bg)]);
      if (!cands.length) continue;
      const best = Math.max(...cands.map(c => ratio(c[1], bg)));
      if (best < 3) {
        const cls = sh.getAttribute('class') || sh.tagName;
        add(`${name}|${cls}|${cands.map(c => hex(c[1])).join()}`, `chart mark <${sh.tagName.toLowerCase()} class="${cls}"> ${best.toFixed(2)}:1 < 3:1 ` +
          `(${cands.map(c => c[0] + ' ' + hex(c[1])).join(', ')} on ${hex(bg)}) in chart "${name}"`);
      }
    }
  }
  // legend keys identify the series: the swatch (background, border or glyph)
  for (const key of document.querySelectorAll('.zp-key')) {
    if (!vis(key)) continue;
    const s = getComputedStyle(key), bg = bgOf(key.parentElement), a = opac(key, key.parentElement);
    const cands = [];
    const b = parse(s.backgroundColor); if (b && b[3] > 0) cands.push(over(withA(b, a), bg));
    const bc = parse(s.borderTopColor); if (bc && parseFloat(s.borderTopWidth) >= 1) cands.push(over(withA(bc, a), bg));
    if ((key.textContent || '').trim()) { const c = parse(s.color); if (c) cands.push(over(withA(c, a), bg)); }
    if (!cands.length) continue;
    const best = Math.max(...cands.map(c => ratio(c, bg)));
    if (best < 3) add('key|' + key.className + '|' + cands.map(hex).join(), `legend key ${best.toFixed(2)}:1 < 3:1 (${cands.map(hex).join(', ')} on ${hex(bg)}): ${describeEl(key)}`);
  }
  // meters / determinate progress bars drawn with a fill element: fill vs track
  for (const m of document.querySelectorAll('[role=meter], [role=progressbar]')) {
    if (!vis(m) || /^(PROGRESS|METER)$/.test(m.tagName)) continue;          // native, UA-drawn
    if (m.getAttribute('aria-valuenow') == null) continue;                  // indeterminate: no value to show
    const fill = [...m.querySelectorAll('*')].find(x => { const r = x.getBoundingClientRect(); const c = parse(getComputedStyle(x).backgroundColor);
      return r.width >= 1 && r.height >= 1 && c && c[3] > 0; });
    if (!fill) continue;
    const around = bgOf(m.parentElement);
    const own = parse(getComputedStyle(m).backgroundColor);
    const track = own && own[3] > 0 ? over(withA(own, opac(m, m.parentElement)), around) : around;
    const fc = over(withA(parse(getComputedStyle(fill).backgroundColor), opac(fill, m)), track);
    const r = ratio(fc, track);
    if (r < 3) add('meter|' + fill.className + '|' + hex(fc) + hex(track), `${m.getAttribute('role')} fill ${r.toFixed(2)}:1 < 3:1 against its track ` +
      `(${hex(fc)} on ${hex(track)}): ${describeEl(m)} > <${fill.tagName.toLowerCase()} class="${fill.className}">`);
  }
  return [...out.values()].map(e => e.msg + (e.n > 1 ? ` (x${e.n})` : ''));
}
"""
)

NO_TRANSITIONS_CSS = "*, *::before, *::after { transition: none !important; animation: none !important; }"


@pytest.mark.bitv("9.1.4.11")
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("state", ["history-charts", "audit-running", "audit-jobs", "monitors-running"])
def test_chart_and_meter_contrast(open_page, state: str, theme: str) -> None:
    """9.1.4.11 Non-text contrast of graphics: data marks of every chart
    (svg role=img: performance timeline points / failure crosses, trend
    sparkline lines and end dots) against the chart background; legend keys;
    and the fill of every determinate meter / progress bar (report dimension
    meters, audit progress, live probe bar, job and monitor progress) against
    its track. Colours include fill-/stroke-opacity and element opacity; the
    better of fill and stroke counts (a hollow point is its stroke). Gridlines,
    the area under a sparkline and its dashed baseline are decorative; an
    indeterminate bar (no aria-valuenow) shows no value. >= 3:1 in both themes."""
    page = open_state(open_page, state, theme)
    page.add_style_tag(content=NO_TRANSITIONS_CSS)
    settle(page)
    assert_no_issues(page.evaluate(GRAPHICS_JS), f"{state} [en, {theme}]", "non-text-contrast-graphics")
