"""Real user flows, status messages, focus management and accessibility-tree
snapshots (BITV 9.4.1.3, 9.2.4.3, 9.4.1.2, 9.1.3.1, 9.2.4.6).

The main tasks are run end to end in the browser, against a private zing
server (zing_proc.py) and a fake OpenAI-compatible relay on 127.0.0.1
(fake_relay.py), so nothing leaves the machine:

1. an audit on /v2/, followed to the rendered report (every language);
2. failing audits: an empty form, a URL the server refuses, an unreachable relay;
3. a monitor: scheduled from History, activated with an API key (which opens
   the master-key dialog), edited, paused, the key locked and unlocked, deleted;
4. look-up, filter, check/save/delete of an entry on /v2/kb;
5. the audit page's embedding and rerank endpoint types (and a rerun).

At every step an init script (TRACK_JS) watches the DOM with a
MutationObserver installed before the page's own scripts run:

* status messages (9.4.1.3): when a message element on the page's list gets
  new text, it must sit inside a live region (role status/alert/log, aria-live
  or <output>) that was in the DOM, live, in an earlier mutation batch. A
  region created together with its message is not announced by screen readers.
  Messages that receive focus are exempt (moving focus announces them).
* focus (9.2.4.3): when the focused element is removed, hidden or disabled and
  focus falls to <body>, that is recorded; it is an issue when focus is still
  on <body> once the step has settled (the page did not put it anywhere).
* dialogs (9.2.4.3, 9.4.1.2): an open modal dialog holds the focus; a closed
  one leaves focus outside it, and back on the button that opened it when
  the dialog was cancelled.

The accessibility-tree snapshots store Playwright's aria snapshot of <body>
for every page and language (after expand_all) in tests/a11y/snapshots/ and
compare against it; ZING_A11Y_UPDATE_SNAPSHOTS=1 rewrites them. Each snapshot
must also name every interactive node and no generic one.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import difflib
import json
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Locator, Page

from tests.a11y.fake_relay import EMBED_DIM, FakeRelay
from tests.a11y.harness import (
    DESKTOP,
    LANGS,
    PAGES,
    _free_port,
    assert_no_issues,
    expand_all,
    settle,
    track_network,
)
from tests.a11y.zing_proc import FIXED_TS, ZingProc

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"
UPDATE = os.environ.get("ZING_A11Y_UPDATE_SNAPSHOTS") == "1"
FLOW_LANGS = [x for x in ("en", "de") if x in LANGS]
TIMEOUT = 30_000

# --------------------------------------------------------------------------- #
# servers and pages
# --------------------------------------------------------------------------- #


@pytest.fixture
def zing(tmp_path: Path) -> Iterator[ZingProc]:
    """A fresh zing server (saved report fixture, no monitor, no master key)."""
    with ZingProc(tmp_path / "data") as z:
        yield z


@pytest.fixture(scope="session")
def zing_seeded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ZingProc]:
    """A zing server nobody changes: report fixture plus its monitor (snapshots)."""
    with ZingProc(tmp_path_factory.mktemp("zing-snap"), seed_monitor=True) as z:
        yield z


@pytest.fixture
def relay() -> Iterator[FakeRelay]:
    with FakeRelay() as r:
        yield r


@pytest.fixture
def broken_relay() -> Iterator[FakeRelay]:
    with FakeRelay(fail=True) as r:
        yield r


def new_context(browser: Browser, base: str, lang: str, **opts: Any) -> BrowserContext:
    """A context like harness.Opener's: language preset, light theme, UTC, and
    offline except for ``base`` (the fake relay is reached by the server)."""
    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light", timezone_id="UTC", locale="en-US", **opts)
    track_network(ctx)
    ctx.add_init_script(
        f"try {{ localStorage.setItem('zing.lang', {json.dumps(lang)});"
        f" localStorage.setItem('zing.v2.theme', 'light'); }} catch (e) {{}}"
    )
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    return ctx


@pytest.fixture
def contexts(browser: Browser) -> Iterator[list[BrowserContext]]:
    made: list[BrowserContext] = []
    yield made
    for c in made:
        with contextlib.suppress(Exception):
            c.close()


# --------------------------------------------------------------------------- #
# in-page tracker
# --------------------------------------------------------------------------- #
TRACK_JS = r"""
(() => {
  if (window.__a11y) return;
  const LIVE = '[role=status],[role=alert],[role=log],[aria-live=polite],[aria-live=assertive],output';
  const S = window.__a11y = {
    batch: 0, armed: false, watch: [], events: [], losses: [], dialogs: [],
    born: new WeakMap(), liveAt: new WeakMap(), changed: new WeakMap(), last: null, lastDesc: '', trail: [],
  };
  const desc = el => {
    if (!el || el.nodeType !== 1) return String(el);
    const name = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('placeholder') || '')
      .trim().replace(/\s+/g, ' ').slice(0, 50);
    const act = el.getAttribute('data-act') || el.getAttribute('data-mk') || el.getAttribute('data-zmk');
    return `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${act ? '[' + act + ']' : ''}> "${name}"`;
  };
  S.desc = desc;
  const mark = (n, b) => {
    if (n.nodeType !== 1) return;
    S.born.set(n, b);
    for (const d of n.querySelectorAll('*')) S.born.set(d, b);
  };
  const liveSince = el => {
    if (!el.matches(LIVE)) return Infinity;
    return S.liveAt.has(el) ? S.liveAt.get(el) : (S.born.get(el) ?? 0);
  };
  const msgBatch = el => {
    let m = Math.max(S.born.get(el) ?? 0, S.changed.get(el) ?? 0);
    for (const d of el.querySelectorAll('*')) m = Math.max(m, S.born.get(d) ?? 0, S.changed.get(d) ?? 0);
    return m;
  };
  const shown = el => el.isConnected && (el.checkVisibility ? el.checkVisibility() : el.getClientRects().length > 0);
  const text = el => (el.innerText || '').trim().replace(/\s+/g, ' ');
  // a status message changed in batch b: is it announced?
  // the text last seen per watched message (a repaint with the same text is no news)
  S.prev = new Map();
  S.key = (sel, el, i) => sel + '|' + i;
  S.snapshotTexts = () => {
    S.prev.clear();
    for (const sel of S.watch) document.querySelectorAll(sel).forEach((el, i) => S.prev.set(S.key(sel, el, i), shown(el) ? text(el) : ''));
  };
  const judge = (el, sel, b, i) => {
    const t = shown(el) ? text(el) : '';
    const k = S.key(sel, el, i), before = S.prev.get(k);
    S.prev.set(k, t);
    if (!t || t === before) return;
    const a = document.activeElement;
    if (a && a !== document.body && (el.contains(a) || a.contains(el))) return;  // focus moved to it
    const regions = [];
    for (let p = el; p && p !== document.documentElement; p = p.parentElement) {
      if (p.matches(LIVE)) regions.push(p);
    }
    let why = null;
    if (!regions.length) why = 'is not inside a live region (role=status/alert/log or aria-live)';
    else if (regions.every(r => liveSince(r) >= b)) why = 'is in a live region that was created together with the message (' + desc(regions[0]) + ')';
    else if (regions.every(r => r.closest('[aria-hidden=true]'))) why = 'is in a live region hidden with aria-hidden';
    S.events.push({ sel, el, text: t.slice(0, 90), ok: !why, why: why || '' });
  };
  // focus fell to <body> because the focused element went away
  const checkFocus = () => {
    const a = document.activeElement;
    if (a && a !== document.body && a !== document.documentElement) return;
    const el = S.last;
    if (!el) return;
    const gone = !el.isConnected ? 'was removed' : !shown(el) ? 'was hidden' : el.disabled ? 'was disabled'
      : el.closest('[inert]') ? 'became inert' : null;
    if (gone) S.losses.push({ desc: S.lastDesc, why: gone });
    S.last = null;
  };
  S.checkFocus = checkFocus;
  document.addEventListener('focusin', e => {
    S.last = e.target; S.lastDesc = desc(e.target);
    S.trail.push(e.target); if (S.trail.length > 8) S.trail.shift();
  }, true);
  // decided after the event (removal can blur before the node is gone);
  // Flow.step also settles it before each step
  document.addEventListener('focusout', e => { if (!e.relatedTarget) setTimeout(checkFocus, 0); }, true);
  setInterval(checkFocus, 40);
  const dialogOpen = d => d.matches('dialog') ? d.open : !d.hidden && shown(d);
  const onDialog = (d, b) => {
    const rec = S.dialogs.find(x => x.el === d && !x.closedAt);
    if (dialogOpen(d) && !rec) {
      const opener = [...S.trail].reverse().find(x => !d.contains(x)) || null;
      const lab = document.getElementById(d.getAttribute('aria-labelledby') || '');
      const name = (d.getAttribute('aria-label') || (lab ? lab.textContent : '')).trim();
      S.dialogs.push({ el: d, name, opener, openerDesc: desc(opener), openedAt: b, closedAt: 0,
                       modal: d.matches(':modal') || d.getAttribute('aria-modal') === 'true' });
    } else if (!dialogOpen(d) && rec) rec.closedAt = b;
  };
  new MutationObserver(records => {
    const b = ++S.batch;
    for (const r of records) {
      if (r.type === 'childList') {
        r.addedNodes.forEach(n => mark(n, b));
        if (r.addedNodes.length && r.target.nodeType === 1) S.changed.set(r.target, b);
      } else if (r.type === 'characterData') {
        if (r.target.parentElement) S.changed.set(r.target.parentElement, b);
      } else if (r.type === 'attributes') {
        const el = r.target;
        if ((r.attributeName === 'role' || r.attributeName === 'aria-live') && el.matches(LIVE)) {
          const was = r.oldValue;
          const wasLive = r.attributeName === 'role' ? /^(status|alert|log)$/.test(was || '') : /^(polite|assertive)$/.test(was || '');
          if (!wasLive) S.liveAt.set(el, b);
        } else if (r.attributeName === 'hidden' && !el.hidden) {
          S.changed.set(el, b);
        }
        if (r.attributeName === 'open' || r.attributeName === 'hidden') {
          if (el.matches('dialog, [role=dialog], [role=alertdialog]')) onDialog(el, b);
        }
      }
    }
    for (const r of records) {
      if (r.type === 'childList') r.addedNodes.forEach(n => {
        if (n.nodeType === 1) for (const d of [n, ...n.querySelectorAll('dialog[open], [role=dialog], [role=alertdialog]')])
          if (d.matches('dialog, [role=dialog], [role=alertdialog]')) onDialog(d, b);
      });
    }
    checkFocus();
    if (!S.armed) return;
    for (const sel of S.watch) {
      document.querySelectorAll(sel).forEach((el, i) => { if (msgBatch(el) === b) judge(el, sel, b, i); });
    }
  }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true,
                         attributeOldValue: true, attributeFilter: ['role', 'aria-live', 'hidden', 'open'] });
})();
"""

DIALOG_STATE_JS = """
() => {
  const S = window.__a11y;
  const a = document.activeElement;
  return S.dialogs.map(d => ({
    open: !d.closedAt, modal: d.modal, openedAt: d.openedAt, closedAt: d.closedAt,
    focusInside: d.el.contains(a),
    onOpener: !!d.opener && a === d.opener,
    openerUsable: !!d.opener && d.opener.isConnected && d.opener.getClientRects().length > 0 && !d.opener.disabled,
    opener: d.openerDesc, name: d.name,
  }));
}
"""


class Flow:
    """Runs the steps of one user task and collects what goes wrong."""

    def __init__(self, page: Page, where: str, messages: list[str]) -> None:
        self.page = page
        self.where = where
        self.issues: list[str] = []
        self.judged: set[str] = set()  # message selectors the tracker judged at least once
        self.watch(messages)

    def watch(self, messages: list[str]) -> None:
        """(Re)arm the tracker on the current document with these message selectors."""
        self.page.evaluate("sels => { __a11y.watch = sels; __a11y.snapshotTexts(); __a11y.armed = true; __a11y.events = []; __a11y.losses = []; }", messages)
        self.messages = messages

    def step(
        self, name: str, action: Callable[[], Any], cancel_dialog: bool = False, messages: list[str] | None = None
    ) -> None:
        """Run one user action and check what it did. ``messages``: watch these
        message selectors (instead of the flow's) during this step only."""
        page = self.page
        start = page.evaluate(
            "sels => { __a11y.checkFocus(); __a11y.events = []; __a11y.losses = []; if (sels) __a11y.watch = sels;"
            " return __a11y.batch; }",
            messages,
        )
        try:
            action()
            settle(page)
        finally:
            if messages is not None:
                page.evaluate("sels => { __a11y.watch = sels; }", self.messages)
        page.evaluate("() => __a11y.checkFocus()")
        # a message that has the focus by now (the page moved focus to it or
        # to its container, e.g. a heading with a count) is announced anyway
        res = page.evaluate(
            """() => {
                 const a = document.activeElement, focused = !!a && a !== document.body;
                 return {
                   events: __a11y.events.map(e => ({ sel: e.sel, text: e.text, why: e.why,
                     ok: e.ok || (focused && (e.el.contains(a) || a.contains(e.el))) })),
                   losses: __a11y.losses, body: !focused, active: __a11y.desc(a) };
               }"""
        )
        last: dict[str, dict[str, Any]] = {}
        for ev in res["events"]:
            self.judged.add(ev["sel"])
            if not ev["ok"]:
                last[ev["sel"]] = ev  # one issue per message and step: the latest text
        for ev in last.values():
            self.issues.append(f'{name}: message "{ev["text"]}" ({ev["sel"]}) {ev["why"]}  —  BITV 9.4.1.3 Status messages')
        lost_focus = bool(res["body"] and res["losses"])
        if lost_focus:
            lost = res["losses"][-1]
            self.issues.append(
                f"{name}: focus lost to <body>: the focused {lost['desc']} {lost['why']} and focus was not moved"
                "  —  BITV 9.2.4.3 Focus order"
            )
        for d in page.evaluate(DIALOG_STATE_JS):
            if d["open"] and d["openedAt"] > start and d["modal"] and not d["focusInside"]:
                self.issues.append(f"{name}: modal dialog \"{d['name'].strip()}\" opened without moving focus into it  —  BITV 9.2.4.3")
            if d["closedAt"] > start:
                if d["focusInside"] or (res["body"] and not lost_focus):
                    self.issues.append(f"{name}: dialog \"{d['name'].strip()}\" closed and left focus nowhere (<body>)  —  BITV 9.2.4.3")
                elif cancel_dialog and d["openerUsable"] and not d["onOpener"]:
                    self.issues.append(
                        f"{name}: cancelled dialog \"{d['name'].strip()}\" did not return focus to {d['opener']}"
                        f" (focus is on {res['active']})  —  BITV 9.2.4.3"
                    )

    def navigate(
        self, name: str, action: Callable[[], Any], url_glob: str, messages: list[str], expect_focus: str | None = None
    ) -> None:
        """A step that loads another page (the tracker starts over there)."""
        action()
        self.page.wait_for_url(url_glob)
        self.page.wait_for_load_state("load")
        settle(self.page)
        self.watch(messages)
        if expect_focus is not None and not self.page.evaluate(
            "sel => { const a = document.activeElement; return !!a && !!a.closest(sel); }", expect_focus
        ):
            active = self.page.evaluate("() => __a11y.desc(document.activeElement)")
            self.issues.append(f"{name}: after loading, focus is on {active}, not in {expect_focus}  —  BITV 9.2.4.3")

    def done(self, *observed: str, kind: str = "flows") -> None:
        """Report; ``observed``: message selectors the flow must have produced
        (guards against a tracker that silently saw nothing)."""
        missing = [m for m in observed if m not in self.judged]
        assert not missing, f"{self.where}: the flow produced no message at {missing}; the test lost track of the UI"
        assert_no_issues(self.issues, self.where, kind)


def open_flow(
    contexts: list[BrowserContext], browser: Browser, base: str, path: str, lang: str, messages: list[str],
    where: str, **opts: Any,
) -> Flow:
    ctx = new_context(browser, base, lang, **opts)
    contexts.append(ctx)
    ctx.add_init_script(TRACK_JS)
    page = ctx.new_page()
    page.set_default_timeout(TIMEOUT)
    page.goto(base + path, wait_until="load")
    settle(page)
    return Flow(page, f"{where} [{lang}]", messages)


def press(page: Page, selector: str, key: str = "Enter") -> None:
    """Keyboard activation, as a keyboard or screen-reader user would."""
    page.locator(selector).first.focus()
    page.keyboard.press(key)


# --------------------------------------------------------------------------- #
# 1 + 2: audit
# --------------------------------------------------------------------------- #
AUDIT_MESSAGES = ["#now", "#formerr", "#formnote", ".zmp-status"]
RELAY_STATUS = ".zmp-status"


def enter_url(page: Page, url_sel: str, model_sel: str, url: str) -> None:
    """Type a relay URL and leave the field: the relay configuration lists the
    relay's models (its result is a status message)."""
    page.fill(url_sel, url)
    page.dispatch_event(url_sel, "change")
    page.wait_for_function(
        "sel => { const s = document.querySelector(sel); return !!s && !s.classList.contains('is-busy') && !!s.innerText.trim(); }",
        arg=f".grp:has({model_sel}) {RELAY_STATUS}",
    )


def pick_model(page: Page, model_sel: str, model: str) -> None:
    """Pick a model from the relay's list, or type it when there is no list."""
    sel = page.locator(f".grp:has({model_sel}) select.zmp-sel")
    if sel.is_visible():
        sel.select_option(model)
    else:
        page.fill(model_sel, model)
        page.dispatch_event(model_sel, "change")


def fill_audit(page: Page, url: str) -> None:
    """Fill the audit form: key, relay URL (its models are listed), model."""
    page.fill("#i-key", "sk-test")
    enter_url(page, "#i-url", "#i-model", url)
    pick_model(page, "#i-model", "gpt-4o-mini")
    page.click('#api button[data-v="openai"]')
    page.click('#suite button[data-v="smoke"]')


def save_relay(page: Page, name: str) -> None:
    """Save the URL as a relay; it is selected in the relay list afterwards."""
    press(page, ".grp:has(#i-url) .rc-save-t")
    page.fill("#i-url-rname", name)
    press(page, "#i-url-rname", "Enter")
    page.wait_for_function("() => !['', '__other__'].includes(document.querySelector('#i-url-relay').value)")


def reselect_relay(page: Page) -> None:
    """Clear the URL, then pick the saved relay again: its URL is filled in."""
    key = page.input_value("#i-url-relay")
    page.fill("#i-url", "")
    page.dispatch_event("#i-url", "change")
    page.select_option("#i-url-relay", key)
    page.wait_for_function("() => document.querySelector('#i-url').value.trim().length > 0")


def delete_relays(page: Page) -> None:
    """Remove the relays the flow saved (the session server is shared)."""
    page.evaluate(
        """async () => {
          const kb = await (await fetch('/api/kb')).json();
          for (const p of kb.providers) if (p.relay && p.entry_id) await fetch('/api/kb/entries/' + p.entry_id, { method: 'DELETE' });
        }"""
    )


def run_to_report(flow: Flow, name: str) -> None:
    page = flow.page

    def go() -> None:
        press(page, "#go")
        page.wait_for_selector("#v3.show #report >> :is(h1, h2)", timeout=TIMEOUT)

    flow.step(name, go)
    if not page.evaluate("() => document.activeElement && document.activeElement.closest('#v3') !== null"):
        active = page.evaluate("() => __a11y.desc(document.activeElement)")
        flow.issues.append(f"{name}: the report is shown but focus is on {active}, not on the report  —  BITV 9.2.4.3")


@pytest.mark.bitv("9.4.1.3", "9.2.4.3")
@pytest.mark.parametrize("lang", LANGS)
def test_audit_flow(browser, contexts, zing, relay, lang: str) -> None:
    """Start an audit, follow the scan to the report, start another one."""
    flow = open_flow(contexts, browser, zing.url, "/v2/", lang, AUDIT_MESSAGES, "audit flow")
    page = flow.page
    flow.step("fill the form; the relay's models are listed", lambda: fill_audit(page, relay.url))
    flow.step("save the relay to the knowledge base", lambda: save_relay(page, f"A11y relay {lang}"))
    flow.step("pick the saved relay: its URL is filled in", lambda: reselect_relay(page))
    run_to_report(flow, "start the audit")
    # "Test another": the report's own action, back to the form
    flow.step("test another", lambda: press(page, '#report [data-action="0"]'))
    if not page.evaluate("() => !!document.activeElement && !!document.activeElement.closest('#v1')"):
        flow.issues.append("test another: the form is shown but focus is not in it  —  BITV 9.2.4.3")
    delete_relays(page)
    flow.done("#now", ".zmp-status")


@pytest.mark.bitv("9.4.1.3", "9.2.4.3", "9.3.3.1")
@pytest.mark.parametrize("lang", FLOW_LANGS)
def test_failing_audit_flow(browser, contexts, zing, broken_relay, lang: str) -> None:
    """Errors: an empty form, a URL the server refuses, a relay that answers
    HTTP 500, a port nobody listens on."""
    flow = open_flow(contexts, browser, zing.url, "/v2/", lang, AUDIT_MESSAGES, "failing audit flow")
    page = flow.page
    flow.step("submit the empty form", lambda: press(page, "#go"))
    if not page.locator("#formerr").inner_text().strip():
        flow.issues.append("submit the empty form: no error message is shown  —  BITV 9.3.3.1")

    def bad_url() -> None:
        fill_audit(page, "ftp://relay.invalid/v1")
        press(page, "#go")
        page.wait_for_function("() => document.querySelector('#formerr').innerText.trim().length > 0")

    flow.step("submit a URL the server refuses", bad_url)
    fill_audit(page, broken_relay.url)
    run_to_report(flow, "audit a relay that answers HTTP 500")
    flow.step("back to the form", lambda: press(page, '#report [data-action="0"]'))
    fill_audit(page, f"http://127.0.0.1:{_free_port()}/v1")
    run_to_report(flow, "audit an unreachable relay")
    flow.done("#formerr", "#now")


# --------------------------------------------------------------------------- #
# 3: monitors (incl. the master-key dialogs)
# --------------------------------------------------------------------------- #
MONITOR_MESSAGES = [".mon-msg", ".zmk-msg", ".zmk-err", "[data-zmk=copied]", "[id^='m-']"]
DLG = "dialog.zmk-dlg"


def wait_text(page: Page, selector: str) -> None:
    page.wait_for_function(
        "sel => [...document.querySelectorAll(sel)].some(e => (e.innerText || '').trim())", arg=selector
    )


@pytest.mark.bitv("9.4.1.3", "9.2.4.3", "9.4.1.2")
@pytest.mark.parametrize("lang", FLOW_LANGS)
def test_monitor_flow(browser, contexts, zing, relay, lang: str) -> None:
    """Schedule a run as a monitor, activate it with an API key (creating the
    master key in its dialog), edit, pause, lock/unlock the key, delete it."""
    flow = open_flow(
        contexts, browser, zing.url, "/v2/history", lang, MONITOR_MESSAGES, "monitor flow",
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = flow.page
    flow.navigate(
        "schedule a run as monitor (History)", lambda: press(page, "button[data-sched]"), "**/v2/watches*", MONITOR_MESSAGES,
        expect_focus=".setup",
    )
    page.wait_for_selector(".mon .setup")

    def setup() -> None:
        page.select_option(".setup select[data-act=f-interval]", index=1)
        page.fill(".setup input[data-act=f-key]", "sk-test")

    flow.step("set interval and API key", setup)
    flow.step("activate: the master-key dialog opens", lambda: (
        press(page, ".setup [data-act=activate]"), page.wait_for_selector(f"{DLG}[open]")))
    flow.step("show the new master key", lambda: (
        press(page, "[data-zmk=show]"),
        page.wait_for_function("() => (document.querySelector('#zmk-key') || {}).value")))
    key = page.input_value("#zmk-key")
    flow.step("copy it", lambda: (press(page, "[data-zmk=copy]"), wait_text(page, "[data-zmk=copied]")))
    flow.step("confirm it was saved", lambda: (
        press(page, "[data-zmk=saved]", " "), press(page, "[data-zmk=next]"), page.wait_for_selector("#zmk-typed")))

    def confirm() -> None:
        page.fill("#zmk-typed", key)
        page.keyboard.press("Enter")
        page.wait_for_selector(f"{DLG}:not([open])", state="attached")
        wait_text(page, ".mon-msg")

    flow.step("enter the key: dialog closes, monitor activated", confirm)
    flow.step("edit the interval", lambda: press(page, "[data-act=edit-interval]"))

    def save_interval() -> None:
        page.select_option("select[data-act=f-interval]", index=2)
        press(page, "[data-act=save-interval]")
        page.wait_for_selector("[data-act=edit-interval]")
        wait_text(page, ".mon-msg")

    flow.step("save the interval", save_interval)
    flow.step("pause the monitor", lambda: (
        press(page, "input[data-act=enabled]", " "),
        page.wait_for_function("() => !document.querySelector('input[data-act=enabled]').checked")))
    flow.step("lock the master key", lambda: (press(page, "#mk-bar [data-mk=lock]"), page.wait_for_selector("#mk-bar [data-mk=unlock]")))
    flow.step("open the unlock dialog", lambda: (press(page, "#mk-bar [data-mk=unlock]"), page.wait_for_selector(f"{DLG}[open]")))
    flow.step("cancel it with Escape", lambda: (
        page.keyboard.press("Escape"), page.wait_for_selector(f"{DLG}:not([open])", state="attached")), cancel_dialog=True)

    def unlock() -> None:
        press(page, "#mk-bar [data-mk=unlock]")
        page.wait_for_selector(f"{DLG}[open] #zmk-unlock")
        page.fill("#zmk-unlock", key)
        page.keyboard.press("Enter")
        page.wait_for_selector("#mk-bar [data-mk=lock]")

    flow.step("unlock with the key", unlock)
    flow.step("delete: ask", lambda: press(page, "[data-act=del]"))
    flow.step("delete: confirm", lambda: (press(page, "[data-act=del-yes]"), page.wait_for_selector(".mon", state="detached")))
    flow.done(".mon-msg", ".zmk-msg", "[data-zmk=copied]")


# --------------------------------------------------------------------------- #
# 4: knowledge base
# --------------------------------------------------------------------------- #
KB_MESSAGES = [
    "#res", "#kbwarn", "#m-err", "#m-ok", "#m-scan", "#m-copy-msg", "#p-err", "#p-ok", "#p-scan", "#r-err", "#r-ok",
    "li.item [role=status]",
]  # fmt: skip
# while filtering, the number of matching items is the answer the user waits for
KB_FILTER_MESSAGES = [*KB_MESSAGES, "#kb-found"]
KB_YAML = """provider: a11yflow
display_name: A11y Flow
models:
- id: a11yflow-large
  context_window_tokens: 64000
  max_output_tokens: 4096
"""
KB_PROVIDER_YAML = """provider: a11yprov
display_name: A11y Provider
base_url_hints: [https://a11y-provider.example/v1]
models: []
"""


def _kb_open_filters(flow: Flow) -> None:
    """The one filter card for every tab, closed by default."""
    page = flow.page
    if page.locator("#ftog").get_attribute("aria-expanded") != "true":
        flow.step("open the filters", lambda: press(page, "#ftog"))


def _kb_section_steps(flow: Flow, tab: str, field: str, value: str, item_key: str) -> None:
    """The steps every Knowledge tab shares: filter, switch an item off and on."""
    page = flow.page
    _kb_open_filters(flow)
    flt = page.locator(f"#filters [data-f={field}]")
    flow.step(f"{tab}: filter by {field}", lambda: flt.select_option(value), messages=KB_FILTER_MESSAGES)
    switch = f'#{tab}-list li[data-key="{item_key}"] input[data-act=on]'

    def toggle(on: bool) -> Callable[[], None]:
        def run() -> None:
            press(page, switch, " ")
            page.wait_for_function(
                "([sel, on]) => { const i = document.querySelector(sel); return !!i && i.checked === on"
                " && !!i.closest('li.item') && i.closest('li.item').classList.contains('off') !== on; }",
                arg=[switch, on])
        return run

    flow.step(f"{tab}: switch {item_key} off", toggle(False))
    flow.step(f"{tab}: switch it on again", toggle(True))
    flow.step(f"{tab}: clear the filter", lambda: flt.select_option(""), messages=KB_FILTER_MESSAGES)


def _kb_delete_steps(flow: Flow, tab: str) -> None:
    page = flow.page
    lst = f"#{tab}-list"
    sel = f"{lst} li.item:has([data-act=del])"
    flow.step(f"{tab}: switch your entry off", lambda: (
        press(page, f"{sel} input[data-act=on]", " "), page.wait_for_selector(f"{lst} li.item.off:has([data-act=del])")))
    flow.step(f"{tab}: delete: ask", lambda: press(page, f"{lst} [data-act=del]"))
    flow.step(f"{tab}: delete: cancel", lambda: press(page, f"{lst} [data-act=del-no]"))
    n = page.locator(sel).count()
    flow.step(f"{tab}: delete: confirm", lambda: (
        press(page, f"{lst} [data-act=del]"), press(page, f"{lst} [data-act=del-yes]"),
        page.wait_for_function("([s, n]) => document.querySelectorAll(s).length < n", arg=[sel, n])))


@pytest.mark.bitv("9.4.1.3", "9.2.4.3", "9.3.3.1")
@pytest.mark.parametrize("lang", FLOW_LANGS)
def test_kb_flow(browser, contexts, zing, lang: str) -> None:
    """Every tab of the Knowledge page: filter, switch packaged items off and
    on, add (model wizard, provider wizard, relay form), switch and delete
    your own entry; plus the model-id lookup and the tabs' keyboard use."""
    flow = open_flow(contexts, browser, zing.url, "/v2/kb", lang, KB_MESSAGES, "knowledge-base flow")
    page = flow.page
    page.wait_for_selector("#models-list li.item", state="attached")

    _kb_open_filters(flow)
    model = page.locator("#filters [data-f=model]")
    flow.step("pick a model id: its profile", lambda: (model.select_option("model:openai/gpt-4o"), wait_text(page, "#res")),
              messages=KB_FILTER_MESSAGES)
    # a fresh server has no entries of yours: only "Packaged" is offered
    flow.step("only packaged entries", lambda: page.locator("#filters [data-f=source]").select_option("packaged"),
              messages=KB_FILTER_MESSAGES)
    flow.step("reset the filters", lambda: press(page, "#freset"), messages=KB_FILTER_MESSAGES)

    # ---- models
    _kb_section_steps(flow, "models", "model", "model:openai/gpt-4o-mini", "model:openai/gpt-4o-mini")
    flow.step("models: open the add form", lambda: press(page, "#add-models > summary"))
    flow.step("models: copy the prompt without a model id", lambda: (press(page, "#m-copy"), wait_text(page, "#m-copy-msg")))
    flow.step("models: check without YAML", lambda: (press(page, "#m-check"), wait_text(page, "#m-err")))
    flow.step("models: check invalid YAML", lambda: (
        page.fill("#m-yaml", "provider: x\nmodels:\n- id: m\n  nope: 1"), press(page, "#m-check"),
        wait_text(page, "#m-scan, #m-err")))
    flow.step("models: check valid YAML", lambda: (
        page.fill("#m-yaml", KB_YAML), press(page, "#m-check"), page.wait_for_selector("#m-save:not([disabled])")))
    flow.step("models: save it", lambda: (
        press(page, "#m-save"), wait_text(page, "#m-ok"),
        page.wait_for_selector('#models-list li[data-key="model:a11yflow/a11yflow-large"]', state="attached")))
    page.evaluate("document.querySelector('#models-list details[data-group=a11yflow]').open = true")
    _kb_delete_steps(flow, "models")

    # ---- providers (arrow keys move between the tabs)
    flow.step("switch to the providers tab", lambda: (
        press(page, "#tab-models", "ArrowRight"), page.wait_for_selector("#panel-providers:not([hidden]) li.item")))
    _kb_section_steps(flow, "providers", "provider", "openai", "provider:openai")
    flow.step("providers: open the add form", lambda: press(page, "#add-providers > summary"))
    flow.step("providers: check valid YAML", lambda: (
        page.fill("#p-yaml", KB_PROVIDER_YAML), press(page, "#p-check"), page.wait_for_selector("#p-save:not([disabled])")))
    flow.step("providers: save it", lambda: (
        press(page, "#p-save"), wait_text(page, "#p-ok"), page.wait_for_selector("#providers-list li.item:has([data-act=del])")))
    _kb_delete_steps(flow, "providers")

    # ---- relays (End jumps to the last tab)
    flow.step("switch to the relays tab", lambda: (
        press(page, "#tab-providers", "End"), page.wait_for_selector("#panel-relays:not([hidden])")))
    flow.step("relays: open the add form", lambda: press(page, "#add-relays > summary"))
    flow.step("relays: save without a name", lambda: (press(page, "#r-save"), wait_text(page, "#r-err")))
    flow.step("relays: save with a bad URL", lambda: (
        page.fill("#r-name", "A11y Relay"), page.fill("#r-url", "relay.example"), press(page, "#r-save"),
        wait_text(page, "#r-err")))
    flow.step("relays: save it", lambda: (
        page.fill("#r-url", "https://a11y-relay.example/v1"), press(page, "#r-save"), wait_text(page, "#r-ok"),
        page.wait_for_selector("#relays-list li.item")))
    _kb_section_steps(flow, "relays", "relay", "provider:a11y-relay", "provider:a11y-relay")
    _kb_delete_steps(flow, "relays")
    flow.done("#res", "#m-ok", "#p-ok", "#r-ok", "#r-err", "#kb-found")


# --------------------------------------------------------------------------- #
# accessibility-tree snapshots
# --------------------------------------------------------------------------- #
# Masked before comparing: what may differ between runs or releases without
# the page's structure changing.
VOLATILE = [
    # a release number (zing x.y.z), not an IP address
    (re.compile(r"(?:(?<=zing )|(?<=\bv))\d+\.\d+\.\d+(?:[-+][\w.]+)?"), "<version>"),
    # hex ids / fingerprints (digits and letters a-f mixed)
    (re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{8,}\b"), "<id>"),
    # measured times
    (re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:ms|s)\b"), "<duration>"),
    # thousands separators: whether 4-digit numbers are grouped ("8.192" vs
    # "8192" in Italian) depends on the browser's ICU/CLDR version
    (re.compile("(?<=\\d)[.,\u00a0\u202f '\u2019](?=\\d{3}(?!\\d))"), ""),
]
# roles that must carry a name (an empty one is announced as just "button", …)
NAMED_ROLES = {
    "button", "link", "textbox", "searchbox", "combobox", "checkbox", "switch", "tab",
    "radio", "spinbutton", "slider", "menuitem", "menuitemcheckbox", "menuitemradio",
}
_SNAP_LINE = re.compile(r"^(?P<ind>\s*)- (?P<body>.*)$")
_SNAP_NODE = re.compile(r'^(?P<role>[a-z]+)(?: "(?P<name>(?:[^"\\]|\\.)*)")?(?P<rest>.*)$')


def condense_tables(snapshot: str) -> str:
    """Keep the first row of every table body: the other rows repeat its
    structure, and the knowledge base's data tables grow with every release."""
    out: list[str] = []
    body_ind: int | None = None  # indent of the rowgroup being condensed
    rows = 0
    for line in snapshot.splitlines():
        ind = len(line) - len(line.lstrip())
        if body_ind is not None and ind <= body_ind:
            if rows > 1:
                out.append(" " * (body_ind + 2) + "# … more rows of the same shape")
            body_ind = None
        if body_ind is not None:
            if ind == body_ind + 2 and line.lstrip().startswith("- row"):
                rows += 1
            if rows > 1:
                continue
        elif line.lstrip() == "- rowgroup:":
            body_ind, rows = ind, 0
        out.append(line)
    if body_ind is not None and rows > 1:
        out.append(" " * (body_ind + 2) + "# … more rows of the same shape")
    return "\n".join(out)


def condense_items(snapshot: str) -> str:
    """Keep the first of consecutive sibling blocks that hold an on/off switch
    (the Knowledge page's models, providers and relays, and their provider
    groups): the others repeat its structure and grow with every release."""
    lines = snapshot.splitlines()
    out: list[str] = []

    def block_end(i: int) -> int:
        ind = len(lines[i]) - len(lines[i].lstrip())
        j = i + 1
        while j < len(lines) and len(lines[j]) - len(lines[j].lstrip()) > ind:
            j += 1
        return j

    def has_switch(i: int, j: int) -> bool:
        return any(x.lstrip().startswith('- switch "') for x in lines[i:j])

    i = 0
    while i < len(lines):
        j = block_end(i)
        if not has_switch(i, j) or not lines[i].lstrip().startswith(("- listitem", "- group")):
            out.append(lines[i])
            i += 1
            continue
        out.append(lines[i])
        if j - i > 1:
            out.extend(condense_items("\n".join(lines[i + 1:j])).splitlines())
        ind = len(lines[i]) - len(lines[i].lstrip())
        head = lines[i].lstrip().split(":")[0].split(" ")[1]
        k, more = j, 0
        while k < len(lines) and len(lines[k]) - len(lines[k].lstrip()) == ind and lines[k].lstrip().startswith("- " + head):
            e = block_end(k)
            if not has_switch(k, e):
                break
            k, more = e, more + 1
        if more:
            out.append(" " * ind + "# … more items of the same shape")
        i = k
    return "\n".join(out)


def mask(snapshot: str) -> str:
    snapshot = condense_items(condense_tables(snapshot))
    for rx, repl in VOLATILE:
        snapshot = rx.sub(repl, snapshot)
    return snapshot.rstrip() + "\n"


def snapshot_nodes(snapshot: str) -> Iterator[tuple[str, str | None, str]]:
    """(role, name or None, context path) for every node line of an aria snapshot."""
    path: list[tuple[int, str]] = []
    for line in snapshot.splitlines():
        m = _SNAP_LINE.match(line)
        if not m:
            continue
        body = m["body"]
        if body.startswith("'") and body.rstrip(":").endswith("'"):  # YAML single-quoted key
            body = body.rstrip(":")[1:-1].replace("''", "'")
        node = _SNAP_NODE.match(body)
        if not node or node["role"] == "text" or body.startswith("/"):
            continue
        ind = len(m["ind"])
        while path and path[-1][0] >= ind:
            path.pop()
        name = node["name"]
        where = " > ".join(p[1] for p in path[-3:])
        path.append((ind, node["role"] + (" " + json.dumps(name, ensure_ascii=False) if name else "")))
        yield node["role"], (None if name is None else name.replace('\\"', '"')), where


# Roles that ARIA 1.2 forbids naming (a name there is not announced): a
# div/span with aria-label but no role is the usual case. Playwright's aria
# snapshot drops generic nodes, so this is read from the DOM of the same page.
NAMED_GENERICS_JS = """
() => {
  const PROHIBITED = new Set(['caption', 'code', 'deletion', 'emphasis', 'generic', 'insertion', 'none',
                              'paragraph', 'presentation', 'strong', 'subscript', 'superscript']);
  const IMPLICIT = { DIV: 'generic', SPAN: 'generic', B: 'generic', I: 'generic', U: 'generic', S: 'generic',
                     SMALL: 'generic', Q: 'generic', BDI: 'generic', BDO: 'generic', DATA: 'generic', PRE: 'generic',
                     P: 'paragraph', CODE: 'code', EM: 'emphasis', STRONG: 'strong', DEL: 'deletion',
                     INS: 'insertion', SUB: 'subscript', SUP: 'superscript', CAPTION: 'caption' };
  const out = [];
  for (const el of document.body.querySelectorAll('[aria-label], [aria-labelledby]')) {
    if (el.closest('[hidden], [aria-hidden=true]') || !el.checkVisibility()) continue;
    let role = (el.getAttribute('role') || '').trim().split(/\\s+/)[0] || IMPLICIT[el.tagName] || '';
    if (!role && /^(HEADER|FOOTER)$/.test(el.tagName) && el.parentElement.closest('article, aside, main, nav, section')) role = 'generic';
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
    const name = (el.getAttribute('aria-label') || ids.map(i => (document.getElementById(i) || {}).textContent || '').join(' ')).trim();
    if (PROHIBITED.has(role) && name)
      out.push(`${role} <${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : ''}> named "${name.slice(0, 60)}"`);
  }
  return out;
}
"""

_snapshots: dict[tuple[str, str], tuple[str, list[str]]] = {}

# The report page shows when the conformance report was generated, formatted
# with Intl. The wording differs between ICU versions (Chromium builds: "4 de
# octubre de 2026, 19:42" vs "… a las 19:42"), so the date is replaced by a
# placeholder, formatted here exactly as the page formats it.
MASK_REPORT_DATE_JS = """
async () => {
  let rep;
  try { rep = await (await fetch('/v2/static/bitv-report.json')).json(); } catch (e) { return 0; }
  if (!rep || !rep.generated_at || !window.ZING_LANG) return 0;
  const d = new Date(rep.generated_at);
  const forms = new Set();
  try { forms.add(d.toLocaleString(ZING_LANG.locale(), { dateStyle: 'long', timeStyle: 'short' })); } catch (e) {}
  forms.add(d.toLocaleString());
  let n = 0;
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let t = walk.nextNode(); t; t = walk.nextNode())
    for (const f of forms) if (f && t.nodeValue.includes(f)) { t.nodeValue = t.nodeValue.split(f).join('<report date>'); n++; }
  return n;
}
"""


def aria_tree(browser: Browser, contexts: list[BrowserContext], base: str, page_id: str, lang: str) -> tuple[str, list[str]]:
    """Aria snapshot of <body> after load + expand_all (clock and time zone
    fixed), and the named generic elements of that same state."""
    key = (page_id, lang)
    if key not in _snapshots:
        ctx = new_context(browser, base, lang)
        contexts.append(ctx)
        ctx.clock.set_fixed_time(dt.datetime.fromtimestamp(FIXED_TS, dt.timezone.utc))
        page = ctx.new_page()
        page.goto(base + PAGES[page_id], wait_until="load")
        settle(page)
        expand_all(page)
        page.mouse.move(0, 0)
        settle(page)
        page.evaluate(MASK_REPORT_DATE_JS)
        _snapshots[key] = (mask(page.locator("body").aria_snapshot()), list(page.evaluate(NAMED_GENERICS_JS)))
    return _snapshots[key]


needs_aria_snapshot = pytest.mark.skipif(
    not hasattr(Locator, "aria_snapshot"), reason="aria snapshots need playwright >= 1.49"
)


@needs_aria_snapshot
@pytest.mark.bitv("9.1.3.1", "9.4.1.2", "9.2.4.6")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", list(PAGES))
def test_aria_snapshot_unchanged(browser, contexts, zing_seeded, page_id: str, lang: str) -> None:
    """Regression guard: the accessibility tree (roles, names, states, structure)
    matches the reviewed snapshot. ZING_A11Y_UPDATE_SNAPSHOTS=1 rewrites it."""
    got = aria_tree(browser, contexts, zing_seeded.url, page_id, lang)[0]
    path = SNAP_DIR / f"{page_id}-{lang}.yml"
    if UPDATE:
        SNAP_DIR.mkdir(exist_ok=True)
        path.write_text(got, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(f"no snapshot {path.name}: review the page, then run with ZING_A11Y_UPDATE_SNAPSHOTS=1")
    want = path.read_text(encoding="utf-8")
    if got != want:
        diff = "".join(difflib.unified_diff(
            want.splitlines(keepends=True), got.splitlines(keepends=True), f"{path.name} (stored)", "(page now)", n=2))
        issues = [
            "accessibility tree differs from the reviewed snapshot (BITV 9.1.3.1 / 9.4.1.2 / 9.2.4.6);"
            f" review it, then ZING_A11Y_UPDATE_SNAPSHOTS=1 if intended:\n{diff[:6000]}"
        ]
        assert_no_issues(issues, f"{page_id} [{lang}]", "aria-snapshot")


@needs_aria_snapshot
@pytest.mark.bitv("9.4.1.2", "9.1.3.1", "9.2.4.6")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", list(PAGES))
def test_aria_tree_names(browser, contexts, zing_seeded, page_id: str, lang: str) -> None:
    """Every interactive node has a non-empty accessible name; no generic
    node carries one (aria-label on a plain div/span is not announced)."""
    tree, named_generics = aria_tree(browser, contexts, zing_seeded.url, page_id, lang)
    issues: list[str] = []
    for role, name, where in snapshot_nodes(tree):
        if role in NAMED_ROLES and not (name or "").strip():
            issues.append(f"{role} without an accessible name (in {where or 'body'})  —  BITV 9.4.1.2 Name, role, value")
        elif role == "generic" and name:
            issues.append(f'generic node with a name "{name}" (in {where or "body"})  —  BITV 9.4.1.2 / 9.1.3.1')
    for el in named_generics:
        issues.append(f"{el}: this role cannot carry a name, give it a role or drop the label  —  BITV 9.4.1.2 / 9.1.3.1")
    assert_no_issues(issues, f"{page_id} [{lang}]", "aria-names")


# --------------------------------------------------------------------------- #
# 5: the audit page's embedding and rerank surfaces (formerly /v2/tools)
# --------------------------------------------------------------------------- #
def type_model(page: Page, input_sel: str, model: str) -> None:
    """Type a model id, switching the relay's model list to free text if needed."""
    if not page.locator(input_sel).is_visible():
        press(page, f".grp:has({input_sel}) .zmp-custom")
    page.fill(input_sel, model)
    page.dispatch_event(input_sel, "change")


def fill_surface(page: Page, url: str, model: str) -> None:
    """Fill the form for a non-chat surface: key, relay URL, model, smoke suite."""
    page.fill("#i-key", "sk-test")
    enter_url(page, "#i-url", "#i-model", url)
    type_model(page, "#i-model", model)
    page.click('#suite button[data-v="smoke"]')


def pick_surface(page: Page, surface: str) -> None:
    """Choose the endpoint type with the arrow keys, as a keyboard user would."""
    page.locator("#surface input:checked").focus()
    for _ in range(3):
        if page.locator(f"#surface input[value={surface}]").is_checked():
            return
        page.keyboard.press("ArrowRight")
    raise AssertionError(f"the arrow keys never reach the {surface} endpoint type")


LATEST_RUN_JS = """
async () => {
  const rows = await (await fetch('/api/history?limit=1')).json();
  return (Array.isArray(rows) ? rows : rows.items)[0].id;
}
"""


@pytest.mark.bitv("9.4.1.3", "9.2.4.3", "9.3.3.1")
@pytest.mark.parametrize("lang", FLOW_LANGS)
def test_surface_flow(browser, contexts, zing, relay, broken_relay, lang: str) -> None:
    """Audit an embedding endpoint (and rerun it), then a rerank endpoint
    (working and broken), on the audit page's endpoint-type selector."""
    flow = open_flow(contexts, browser, zing.url, "/v2/", lang, AUDIT_MESSAGES, "surface flow")
    page = flow.page
    flow.step("choose the embedding endpoint type", lambda: pick_surface(page, "embedding"))
    flow.step("embedding: submit the empty form", lambda: press(page, "#go"))
    if not page.locator("#formerr").inner_text().strip():
        flow.issues.append("embedding: submit the empty form: no error message is shown  —  BITV 9.3.3.1")

    def embed() -> None:
        fill_surface(page, relay.url, "a11y-embed")
        page.fill("#i-edims", str(EMBED_DIM))

    flow.step("embedding: fill the form", embed)
    run_to_report(flow, "embedding: audit the endpoint")
    rid = page.evaluate(LATEST_RUN_JS)
    flow.navigate(f"embedding: rerun #{rid}", lambda: page.goto(f"{zing.url}/v2/?rerun={rid}"), "**/v2/?rerun=*", AUDIT_MESSAGES)
    page.wait_for_function("() => document.querySelector('#i-edims').value !== ''")
    if page.input_value("#i-edims") != str(EMBED_DIM) or not page.locator("#sf-embedding").is_checked():
        flow.issues.append(f"rerun: the claimed dimension is {page.input_value('#i-edims')!r}, want {EMBED_DIM}")

    flow.step("choose the rerank endpoint type", lambda: pick_surface(page, "rerank"))
    flow.step("rerank: fill the form", lambda: fill_surface(page, relay.url, "a11y-rerank"))
    run_to_report(flow, "rerank: audit the endpoint")
    flow.step("back to the form", lambda: press(page, '#report [data-action="0"]'))
    if not page.evaluate("() => !!document.activeElement && !!document.activeElement.closest('#v1')"):
        flow.issues.append("back to the form: the form is shown but focus is not in it  —  BITV 9.2.4.3")
    fill_surface(page, broken_relay.url, "a11y-rerank")
    run_to_report(flow, "rerank: a relay that answers HTTP 500")
    flow.done("#formerr", "#now")
