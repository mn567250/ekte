"""Hover/focus content, character keys, pointer and input behaviour.

BITV 9.1.4.13 Content on hover or focus, 9.2.1.4 Character key shortcuts,
9.2.5.1 Pointer gestures, 9.2.5.2 Pointer cancellation, 9.2.5.4 Motion
actuation, 9.3.2.2 On input.

Each page is reloaded with an init script (``INSTRUMENT_JS``) that records
every event listener and ``on…`` handler the app registers, tags the ones for
keys and pointer-down events so it can tell which of them change the page, and
tracks short timers so a check can wait until delayed reactions (a tooltip
with a show delay, a debounced filter) have run instead of sleeping. Then the
page is used like a person would: hover and focus everything, press every
printable key, press a control and slide off it before releasing, change
every field. What changed is read back from the DOM.
"""

from __future__ import annotations

import string
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from tests.a11y.harness import LANGS, PAGES, assert_no_issues, expand_all, settle

PAGE_IDS = list(PAGES)
# English plus the language with the longest strings: wider labels, other wrapping
TWO_LANGS = [lang for lang in ("en", "de") if lang in LANGS]
# every printable character of a US keyboard except Space (the activation key)
PRINTABLE = string.ascii_lowercase + string.ascii_uppercase + string.digits + string.punctuation
NEUTRAL = (0, 0)  # where the pointer rests between probes (as in test_keyboard)
PERSIST_MS = 1500  # 9.1.4.13 persistent: still shown after this long

INSTRUMENT_JS = r"""
(() => {
  if (window.__a11y) return;
  const oST = window.setTimeout.bind(window), oCT = window.clearTimeout.bind(window);
  const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
  const A = window.__a11y = { listeners: [], reactions: [], timers: new Map(), seq: 0 };
  const KEY = ['keydown', 'keypress', 'keyup'], DOWN = ['mousedown', 'pointerdown', 'touchstart'];
  const WATCH = new Set([...KEY, ...DOWN]);
  A.GESTURE = ['pointermove', 'pointerrawupdate', 'mousemove', 'touchmove', 'drag', 'dragstart', 'dragend',
               'dragenter', 'dragover', 'dragleave', 'drop', 'gesturestart', 'gesturechange', 'gestureend'];
  A.MOTION = ['devicemotion', 'deviceorientation', 'deviceorientationabsolute'];
  A.HOVER = ['mouseenter', 'mouseover', 'pointerenter', 'pointerover'];
  const ALL = [...KEY, ...DOWN, ...A.GESTURE, ...A.MOTION, ...A.HOVER, 'click'];

  A.desc = el => {
    if (el === window) return 'window';
    if (el === document) return 'document';
    if (el && el.nodeType !== 1) el = el.parentElement;
    if (!el) return '(none)';
    const name = (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder')
                  || el.getAttribute('name') || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    const cls = typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : '';
    return `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls}>${name ? ' "' + name + '"' : ''}`;
  };
  const own = r => r.type === 'attributes' && /^data-a11y/.test(r.attributeName || '');
  const describeMutations = recs => {
    const seen = new Set();
    for (const r of recs) {
      const what = r.type === 'attributes' ? `${r.attributeName} of ${A.desc(r.target)}`
        : r.type === 'characterData' ? `text of ${A.desc(r.target)}` : `content of ${A.desc(r.target)}`;
      seen.add(what);
    }
    return [...seen];
  };
  A.describeMutations = describeMutations;

  // -- listener registry; key and pointer-down listeners are wrapped to see what they do
  const printable = ev => typeof ev.key === 'string' && ev.key.length === 1 && ev.key !== ' '
    && !ev.ctrlKey && !ev.altKey && !ev.metaKey;
  const mo = new MutationObserver(() => {});
  mo.observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  const react = (fn, type) => function (ev) {
    const call = () => typeof fn === 'function' ? fn.call(this, ev) : fn.handleEvent(ev);
    if (KEY.includes(type) && !printable(ev)) return call();
    mo.takeRecords();
    const focus = document.activeElement, href = location.href;
    try { return call(); } finally {
      let muts = mo.takeRecords().filter(r => !own(r));
      // pressing may restyle the control (visual feedback): not an action
      if (DOWN.includes(type)) muts = muts.filter(r => !(r.type === 'attributes' && /^(class|style)$/.test(r.attributeName)));
      const what = describeMutations(muts).slice(0, 4).map(w => 'changed ' + w);
      if (KEY.includes(type) && document.activeElement !== focus) what.push('moved focus to ' + A.desc(document.activeElement));
      if (location.href !== href) what.push('navigated to ' + location.href);
      if (what.length) A.reactions.push({ type, key: ev.key || '', target: A.desc(ev.currentTarget), what: what.join('; ') });
    }
  };
  const wrapped = new WeakMap();
  const wrapperOf = (fn, type, opts, make) => {
    const cap = typeof opts === 'boolean' ? opts : !!(opts && opts.capture);
    let m = wrapped.get(fn);
    if (!m) { m = new Map(); wrapped.set(fn, m); }
    const k = type + (cap ? '/c' : '');
    if (!m.has(k) && make) m.set(k, react(fn, type));
    return m.get(k);
  };
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    if (fn && (typeof fn === 'function' || typeof fn === 'object')) {
      A.listeners.push({ target: this, type, fn });
      if (WATCH.has(type)) return add.call(this, type, wrapperOf(fn, type, opts, true), opts);
    }
    return add.call(this, type, fn, opts);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, opts) {
    const i = A.listeners.findIndex(l => l.target === this && l.type === type && l.fn === fn);
    if (i >= 0) A.listeners.splice(i, 1);
    const w = fn && WATCH.has(type) ? wrapperOf(fn, type, opts, false) : null;
    return remove.call(this, type, w || fn, opts);
  };
  // on<type> properties (el.onkeydown = …): wrapped the same way
  for (const proto of [HTMLElement.prototype, SVGElement.prototype, Document.prototype, window, Window.prototype]) {
    for (const t of WATCH) {
      const d = Object.getOwnPropertyDescriptor(proto, 'on' + t);
      if (!d || !d.set || !d.configurable) continue;
      Object.defineProperty(proto, 'on' + t, {
        configurable: true, enumerable: d.enumerable,
        get() { const v = d.get.call(this); return (v && v.__a11yFn) || v; },
        set(v) {
          let w = v;
          if (typeof v === 'function') { w = react(v, t); w.__a11yFn = v; }
          d.set.call(this, w);
        },
      });
    }
  }
  // every handler for the given event types: listeners, on… properties and on… attributes
  A.handlers = types => {
    const out = [];
    for (const l of A.listeners) if (types.includes(l.type)) out.push({ target: l.target, type: l.type, how: 'addEventListener' });
    for (const target of [window, document, ...document.querySelectorAll('*')]) {
      for (const t of types) {
        if (target['on' + t]) out.push({ target, type: t, how: 'on' + t + (target.nodeType === 1 && target.hasAttribute('on' + t) ? ' attribute' : ' property') });
      }
    }
    return out;
  };

  // -- short timers, so a check can wait for delayed reactions instead of sleeping
  window.setTimeout = function (fn, delay, ...args) {
    if (typeof fn !== 'function') return oST(fn, delay, ...args);
    const s = A.seq++;
    const id = oST(function () { A.timers.delete(id); return fn.apply(this, args); }, delay);
    if ((+delay || 0) <= 2000) A.timers.set(id, s);
    return id;
  };
  window.clearTimeout = function (id) { A.timers.delete(id); return oCT(id); };
  const frames = () => new Promise(r => {
    let done = false;
    const f = () => { if (!done) { done = true; r(); } };
    requestAnimationFrame(() => requestAnimationFrame(f));
    oST(f, 120);
  });
  A.frames = frames;
  // two frames, every short timer set so far has run, finite animations ended
  A.quiet = async (max = 2500) => {
    const t0 = performance.now();
    await frames();
    const lim = A.seq;
    while ([...A.timers.values()].some(s => s < lim) && performance.now() - t0 < max) await new Promise(r => oST(r, 20));
    await frames();
    const anims = document.getAnimations().filter(a => a.effect && a.effect.getComputedTiming().iterations !== Infinity);
    await Promise.race([Promise.all(anims.map(a => a.finished.catch(() => null))), new Promise(r => oST(r, 1500))]);
  };

  // -- what is visible: element identity survives across snapshots
  const ids = new WeakMap();
  let nid = 0;
  const idOf = el => { let i = ids.get(el); if (i === undefined) { i = ++nid; ids.set(el, i); } return i; };
  A.shown = el => {
    if (!el || !el.isConnected || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const REPLACED = new Set(['IMG', 'svg', 'CANVAS', 'VIDEO', 'INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'IFRAME', 'PROGRESS', 'METER']);
  const isContent = el => REPLACED.has(el.tagName)
    || [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const elements = () => [...document.body.querySelectorAll('*')]
    .filter(el => !(el instanceof SVGElement && el.tagName !== 'svg') && !el.closest('[data-a11y-start]'));
  A.snap = () => {
    const all = new Set(), content = new Set();
    for (const el of elements()) {
      if (!A.shown(el)) continue;
      all.add(idOf(el));
      if (isContent(el)) content.add(idOf(el));
    }
    A.before = { all, content };
  };
  const textRects = el => {
    if (REPLACED.has(el.tagName)) return [el.getBoundingClientRect()];
    const out = [];
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      out.push(...r.getClientRects());
    }
    return out;
  };
  // content shown before that the revealed box now covers (it is on top there)
  const covers = root => {
    // an overlay with pointer-events: none still covers what is under it
    const pe = root.style.getPropertyValue('pointer-events'), prio = root.style.getPropertyPriority('pointer-events');
    root.style.setProperty('pointer-events', 'auto', 'important');
    try { return coveredBy(root); } finally { root.style.setProperty('pointer-events', pe, prio); }
  };
  const coveredBy = root => {
    const box = root.getBoundingClientRect();
    for (const el of elements()) {
      if (!A.before.content.has(idOf(el)) || root.contains(el) || el.contains(root) || !A.shown(el)) continue;
      for (const r of textRects(el)) {
        const x1 = Math.max(box.left, r.left), x2 = Math.min(box.right, r.right);
        const y1 = Math.max(box.top, r.top), y2 = Math.min(box.bottom, r.bottom);
        if (x2 - x1 < 2 || y2 - y1 < 2) continue;
        const x = (x1 + x2) / 2, y = (y1 + y2) / 2;
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
        const top = document.elementFromPoint(x, y);
        if (top && root.contains(top)) return A.desc(el);
      }
    }
    return null;
  };
  // content that is visible now but was not at A.snap(), grouped by the
  // outermost newly visible box; a trigger that itself only became visible
  // (an off-screen skip link getting focus) does not count as revealed content
  const revealed = trig => {
    const B = A.before, roots = new Set();
    const trigWas = trig && B.all.has(idOf(trig));
    for (const el of elements()) {
      if (!isContent(el) || B.content.has(idOf(el)) || !A.shown(el)) continue;
      if (trig && !trigWas && trig.contains(el)) continue;
      let root = el;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        if (B.all.has(idOf(p))) break;
        if (A.shown(p)) root = p;
      }
      if (trig && root.contains(trig)) continue;
      roots.add(root);
    }
    return [...roots].filter(r => ![...roots].some(o => o !== r && o.contains(r)));
  };
  const info = root => ({ desc: A.desc(root), text: root.textContent.trim().replace(/\s+/g, ' ').slice(0, 60) });
  // right after the hover/focus, before waiting for timers: content that
  // shows only briefly is gone again by the time A.diff runs
  A.diffEarly = trig => { A.early = revealed(trig); };
  A.diff = trig => {
    const roots = revealed(trig);
    const vanished = (A.early || []).filter(r => !roots.some(o => o === r || o.contains(r)) && !A.shown(r)).map(info);
    A.early = [];
    return {
      vanished,
      shown: roots.map((root, k) => {
        root.setAttribute('data-a11y-rv', String(k));
        return { k, ...info(root), covers: covers(root) };
      }),
    };
  };
  A.revealedShown = k => A.shown(document.querySelector(`[data-a11y-rv="${k}"]`));
  A.pointIn = k => {
    const el = document.querySelector(`[data-a11y-rv="${k}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const x1 = Math.max(r.left, 0), x2 = Math.min(r.right, innerWidth), y1 = Math.max(r.top, 0), y2 = Math.min(r.bottom, innerHeight);
    if (x2 - x1 < 2 || y2 - y1 < 2) return null;
    return [(x1 + x2) / 2, (y1 + y2) / 2];
  };
  // a point on el that the pointer really hits (after scrolling it into view)
  A.hitPoint = el => {
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    for (const r of el.getClientRects()) {
      for (const [fx, fy] of [[0.5, 0.5], [0.2, 0.5], [0.8, 0.5], [0.5, 0.2], [0.5, 0.8]]) {
        const x = r.left + r.width * fx, y = r.top + r.height * fy;
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
        const hit = document.elementFromPoint(x, y);
        if (hit && (hit === el || el.contains(hit))) return [x, y];
      }
    }
    return null;
  };

  // -- DOM/state watch over one interaction
  A.watchStart = () => {
    A.watch && A.watch.disconnect();
    A.watched = [];
    A.watch = new MutationObserver(recs => A.watched.push(...recs));
    A.watch.observe(document, { subtree: true, childList: true, attributes: true, characterData: true, attributeOldValue: true });
    A.state0 = A.formState();
    A.active0 = document.activeElement;
  };
  A.watchEnd = () => {
    A.watched.push(...A.watch.takeRecords());
    A.watch.disconnect();
    return A.watched.filter(r => !own(r) && !(r.type === 'attributes' && r.oldValue === r.target.getAttribute(r.attributeName)));
  };
  A.formState = () => new Map([...document.querySelectorAll('input, select, textarea')]
    .map(el => [el, el.type === 'checkbox' || el.type === 'radio' ? String(el.checked) : el.value]));
  A.formChanges = () => {
    const now = A.formState(), out = [];
    for (const [el, v] of A.state0) if (el.isConnected && now.get(el) !== v) out.push(`value of ${A.desc(el)}`);
    return out;
  };
})();
"""


def instrumented(open_page: Any, page_id: str, lang: str = "en", expand: bool = True) -> Page:
    """Open a page with INSTRUMENT_JS running before the app's own scripts."""
    page: Page = open_page(PAGES[page_id], lang)
    page.context.add_init_script(INSTRUMENT_JS)
    page.reload(wait_until="load")
    settle(page)
    if expand:
        expand_all(page)
    page.mouse.move(*NEUTRAL)
    quiet(page)
    return page


def quiet(page: Page) -> None:
    page.evaluate("() => window.__a11y.quiet()")


def take_reactions(page: Page) -> list[dict[str, str]]:
    """Listener reactions recorded so far (cleared, so a reload loses none)."""
    return list(page.evaluate("() => window.__a11y.reactions.splice(0)"))


def _navigated(page: Page, url: str) -> bool:
    """Whether the page left ``url``: another path, or a new document (the
    helpers INPUTS_JS installed are gone). A page that keeps its view in the
    query string (filters.js: ``history.replaceState``) stays the same
    document; that is no change of context."""
    if page.url.split("?")[0].split("#")[0] != url.split("?")[0].split("#")[0]:
        return True
    if page.url.split("#")[0] == url.split("#")[0]:
        return False
    try:
        return not page.evaluate("() => !!window.__a11y")
    except PlaywrightError:
        return True


def _reopen(page: Page, url: str) -> None:
    """Back to the page under test after a navigation, in the same state."""
    page.goto(url, wait_until="load")
    settle(page)
    expand_all(page)
    page.mouse.move(*NEUTRAL)
    quiet(page)


def _navigated(changes: list[str] | None) -> bool:
    return any(c.startswith("navigated") for c in changes or [])


# --------------------------------------------------------------------------- #
# 9.1.4.13 Content on hover or focus
# --------------------------------------------------------------------------- #
# Everything that may show content on hover or focus: controls, elements with a
# description or popup, subjects of :hover rules (".tip:hover .bubble" -> ".tip")
# and targets of mouseenter/mouseover listeners.
HOVER_CANDIDATES_JS = r"""
() => {
  const A = window.__a11y;
  const split = sel => {
    const out = []; let depth = 0, cur = '';
    for (const ch of sel) {
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { out.push(cur); cur = ''; } else cur += ch;
    }
    return [...out, cur];
  };
  const subjectOf = part => {
    const i = part.indexOf(':hover');
    if (i < 0) return null;
    let j = i + 6, depth = 0;
    for (; j < part.length; j++) {
      const ch = part[j];
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      else if (depth === 0 && /[\s>+~]/.test(ch)) break;
    }
    let s = (part.slice(0, i) + part.slice(i + 6, j)).trim();
    s = s.replace(/::?(before|after|placeholder|marker|selection|first-line|first-letter|backdrop)\b/g, '')
         .replace(/:(hover|focus-visible|focus-within|focus|active)\b/g, '');
    if (!s || /[\s>+~]$/.test(s)) s += '*';
    return s;
  };
  const subjects = new Set();
  const walk = rules => {
    for (const r of rules) {
      if (r.selectorText && r.selectorText.includes(':hover')) {
        for (const part of split(r.selectorText)) {
          const s = subjectOf(part);
          if (!s) continue;
          try { document.querySelectorAll(s).forEach(e => subjects.add(e)); } catch (e) { /* not a selector */ }
        }
      }
      if (r.cssRules) walk(r.cssRules);
    }
  };
  for (const sheet of document.styleSheets) { try { walk(sheet.cssRules); } catch (e) { /* cross-origin */ } }
  for (const h of A.handlers(A.HOVER)) if (h.target.nodeType === 1) subjects.add(h.target);
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, label, [tabindex], '
    + '[role=button], [role=link], [role=tab], [role=menuitem], [role=switch], [role=checkbox], '
    + '[aria-describedby], [aria-haspopup]:not([aria-haspopup=false]), [aria-expanded], [title]';
  const all = new Set([...document.querySelectorAll(sel), ...subjects]);
  const out = [];
  let i = 0;
  for (const el of [...document.body.querySelectorAll('*')].filter(e => all.has(e))) {
    if (el.closest('[inert]')) continue;
    const hover = A.shown(el);
    const focus = el.tabIndex >= 0 && !el.disabled && el.getClientRects().length > 0 && !el.closest('[hidden]');
    if (!hover && !focus) continue;
    el.setAttribute('data-a11y-hv', String(i));
    out.push({ i: i++, desc: A.desc(el), hover, focus });
  }
  return out;
}
"""


def _check_revealed(page: Page, how: str, trig: str, point: list[float] | None, rev: dict[str, Any]) -> list[str]:
    """The three 9.1.4.13 conditions for one piece of revealed content."""
    k = rev["k"]
    what = f"{rev['desc']} \"{rev['text']}\" shown on {how} of {trig}"

    def shown() -> bool:
        return bool(page.evaluate("k => window.__a11y.revealedShown(k)", k))

    page.wait_for_timeout(PERSIST_MS)
    if not shown():
        return [f"{what} disappears after less than {PERSIST_MS / 1000:.1f} s while the {how} stays (not persistent)"]
    issues: list[str] = []
    if how == "hover" and point is not None:
        target = page.evaluate("k => window.__a11y.pointIn(k)", k)
        if target is not None:
            page.mouse.move(*target, steps=8)
            quiet(page)
            if not shown():
                issues.append(f"{what} disappears when the pointer moves onto it (not hoverable)")
            page.mouse.move(*point, steps=8)
            quiet(page)
            if not shown():
                return issues
    focus0 = page.evaluate("() => window.__a11y.desc(document.activeElement)")
    page.keyboard.press("Escape")
    quiet(page)
    if shown() and rev["covers"]:
        issues.append(
            f"{what} covers {rev['covers']} and Escape does not hide it (not dismissible without moving {how})"
        )
    if how == "focus" and page.evaluate("() => window.__a11y.desc(document.activeElement)") != focus0:
        issues.append(f"Escape hides {what} only by moving focus away (not dismissible without moving focus)")
    return issues


def hover_focus_issues(page: Page) -> list[str]:
    issues: list[str] = []
    for cand in page.evaluate(HOVER_CANDIDATES_JS):
        sel = f'[data-a11y-hv="{cand["i"]}"]'
        for how in ("hover", "focus"):
            if not cand[how]:
                continue
            point = page.evaluate(
                "s => { const el = document.querySelector(s);"
                " document.activeElement && document.activeElement.blur();"
                " return el ? window.__a11y.hitPoint(el) || [] : null; }",
                sel,
            )
            if point is None or (how == "hover" and not point):
                continue  # gone, or covered by something else: the pointer cannot reach it
            page.mouse.move(*NEUTRAL)
            quiet(page)
            page.evaluate("() => window.__a11y.snap()")
            if how == "hover":
                page.mouse.move(*point)
            else:
                page.evaluate("s => document.querySelector(s).focus({ preventScroll: true })", sel)
            page.evaluate(
                "async s => { await window.__a11y.frames(); window.__a11y.diffEarly(document.querySelector(s)); }", sel
            )
            quiet(page)
            found = page.evaluate("s => window.__a11y.diff(document.querySelector(s))", sel)
            for rev in found["vanished"]:
                issues.append(
                    f"{rev['desc']} \"{rev['text']}\" shown on {how} of {cand['desc']} disappears by itself"
                    f" while the {how} stays (not persistent)"
                )
            for rev in found["shown"]:
                issues += _check_revealed(page, how, cand["desc"], point or None, rev)
            page.mouse.move(*NEUTRAL)
            page.evaluate(
                "() => { document.activeElement && document.activeElement.blur();"
                " document.querySelectorAll('[data-a11y-rv]').forEach(e => e.removeAttribute('data-a11y-rv')); }"
            )
            quiet(page)
    return issues


@pytest.mark.bitv("9.1.4.13")
@pytest.mark.parametrize("lang", TWO_LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_content_on_hover_or_focus(open_page, page_id: str, lang: str) -> None:
    """9.1.4.13 Content on hover or focus: every element is hovered and focused;
    content that appears must stay while hovered/focused (persistent), let the
    pointer move onto it (hoverable) and, where it covers other content, hide
    with Escape without moving pointer or focus (dismissible). Native title
    tooltips are drawn by the browser and exempt; colour/underline changes are
    not content."""
    page = instrumented(open_page, page_id, lang)
    assert_no_issues(hover_focus_issues(page), f"{page_id} [{lang}]", "hover-focus")


# --------------------------------------------------------------------------- #
# 9.2.1.4 Character key shortcuts
# --------------------------------------------------------------------------- #
# Tab stops where printable keys have no meaning of their own: no text entry,
# no type-ahead (select, listbox, combobox, menu, tree, grid).
KEY_TARGETS_JS = r"""
() => {
  const A = window.__a11y;
  const typing = 'input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=button])'
    + ':not([type=submit]):not([type=reset]):not([type=image]):not([type=file]):not([type=color]), '
    + 'select, textarea, [contenteditable]:not([contenteditable=false]), '
    + '[role=textbox], [role=searchbox], [role=combobox], [role=listbox], [role=menu], [role=menubar], '
    + '[role=tree], [role=treegrid], [role=grid], [role=spinbutton]';
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll('a[href], button, input, summary, [tabindex]')) {
    if (el.tabIndex < 0 || el.disabled || el.closest('[inert], [hidden]') || !A.shown(el)) continue;
    if (el.matches(typing) || el.closest(typing)) continue;
    el.setAttribute('data-a11y-k', String(i));
    out.push({ sel: `[data-a11y-k="${i++}"]`, desc: A.desc(el) });
  }
  return out;
}
"""

KEY_START_JS = r"""
sel => {
  const el = sel ? document.querySelector(sel) : document.body;
  document.activeElement && document.activeElement.blur();
  if (sel) { if (!el) return false; el.focus({ preventScroll: true }); if (document.activeElement !== el) return false; }
  window.__a11y.watchStart();
  return true;
}
"""

# what changed outside the focused control (anything, with focus on <body>)
KEY_END_JS = r"""
sel => {
  const A = window.__a11y;
  const el = sel ? document.querySelector(sel) : null;
  const out = A.describeMutations(A.watchEnd().filter(r => !el || !el.contains(r.target))).map(w => 'changed ' + w);
  out.push(...A.formChanges().map(w => 'changed ' + w));
  if (document.activeElement !== A.active0) out.push('moved focus to ' + A.desc(document.activeElement));
  return out;
}
"""


def _press(page: Page, sel: str | None, keys: str) -> list[str] | None:
    """Type ``keys`` with focus on ``sel`` (None = body); returns what changed."""
    url, n_pages = page.url, len(page.context.pages)
    if not page.evaluate(KEY_START_JS, sel):
        return None
    page.keyboard.type(keys)
    settle(page)
    quiet(page)
    changes: list[str] = []
    if page.url != url:
        changes.append(f"navigated to {page.url}")
        _reopen(page, url)
    else:
        changes += page.evaluate(KEY_END_JS, sel)
    if len(page.context.pages) > n_pages:
        changes.append("opened a new window")
        for extra in page.context.pages[n_pages:]:
            extra.close()
    return changes


PAGE_LEVEL = ("window", "document", "<html", "<body")


def character_key_issues(page: Page) -> list[str]:
    issues: list[str] = []
    reactions: list[dict[str, str]] = []

    def press(sel: str | None, keys: str) -> list[str]:
        changes = _press(page, sel, keys) or []
        reactions.extend(take_reactions(page))
        if _navigated(changes):
            page.evaluate(KEY_TARGETS_JS)  # the reopened page needs its markers again
        return changes

    targets = [{"sel": None, "desc": "<body> (nothing focused)"}, *page.evaluate(KEY_TARGETS_JS)]
    for t in targets:
        changes = press(t["sel"], PRINTABLE)
        if not changes:
            continue
        # what also changes in the same time without any key is background
        # activity, not a shortcut
        noise = set(press(t["sel"], ""))
        changes = [c for c in changes if c not in noise]
        if not changes:
            continue
        # name the keys where a single press repeats the change (a one-shot
        # change, like opening a panel, does not repeat)
        hits: dict[str, list[str]] = {}
        for ch in PRINTABLE:
            got = [c for c in press(t["sel"], ch) if c not in noise]
            if got:
                hits[ch] = got
            if len(hits) >= 4:
                break
        for ch, got in hits.items():
            issues.append(f"key {ch!r} with focus on {t['desc']}: {'; '.join(got[:3])} (single-key shortcut)")
        if not hits:
            issues.append(
                f"printable keys with focus on {t['desc']}: {'; '.join(changes[:3])} (single-key shortcut;"
                " see the listener findings for the key)"
            )
    for r in reactions:
        if r["type"] in ("keydown", "keypress", "keyup") and r["target"].startswith(PAGE_LEVEL):
            issues.append(
                f"{r['type']} listener on {r['target']} reacts to the unmodified key {r['key']!r}: {r['what']}"
                " (page-level single-key shortcut: needs a modifier, a way to turn it off or remap it)"
            )
    return sorted(set(issues))


@pytest.mark.bitv("9.2.1.4")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_no_character_key_shortcuts(open_page, page_id: str) -> None:
    """9.2.1.4 Character key shortcuts: with focus on the page and on every
    control that does not take text, every printable key (letters, digits,
    punctuation; no Ctrl/Alt/Meta) must do nothing outside the focused
    control. Page-level key handlers that react to such keys are named."""
    page = instrumented(open_page, page_id)
    assert_no_issues(character_key_issues(page), f"{page_id} [en]", "character-keys")


# --------------------------------------------------------------------------- #
# 9.2.5.1 Pointer gestures, 9.2.5.4 Motion actuation
# --------------------------------------------------------------------------- #
GESTURES_JS = r"""
() => {
  const A = window.__a11y, out = [];
  for (const h of A.handlers([...A.GESTURE, ...A.MOTION])) {
    const step = A.MOTION.includes(h.type) ? '9.2.5.4 Motion actuation' : '9.2.5.1 Pointer gestures';
    out.push(`${h.type} handler (${h.how}) on ${A.desc(h.target)}: ${step}`);
  }
  for (const el of document.querySelectorAll('[draggable=true]')) out.push(`draggable=true on ${A.desc(el)}: 9.2.5.1 Pointer gestures`);
  return [...new Set(out)];
}
"""


def gesture_issues(page: Page) -> list[str]:
    return [
        f"{f} (check for a path-based/multipoint gesture or motion without a single-pointer alternative)"
        for f in page.evaluate(GESTURES_JS)
    ]


@pytest.mark.bitv("9.2.5.1", "9.2.5.4")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_no_path_gestures_or_motion_actuation(open_page, page_id: str) -> None:
    """9.2.5.1 Pointer gestures / 9.2.5.4 Motion actuation: the UI is operated
    by single clicks only. Guard: any handler for pointer/mouse/touch movement,
    drag and drop, gestures or device motion/orientation (or a draggable
    element) fails until a person has checked it has a single-pointer
    alternative and can be operated without moving the device."""
    page = instrumented(open_page, page_id)
    assert_no_issues(gesture_issues(page), f"{page_id} [en]", "pointer-gestures")


# --------------------------------------------------------------------------- #
# 9.2.5.2 Pointer cancellation
# --------------------------------------------------------------------------- #
CLICK_TARGETS_JS = r"""
() => {
  const A = window.__a11y;
  const inter = 'a[href], button, summary, label, input[type=checkbox], input[type=radio], input[type=button], '
    + 'input[type=submit], input[type=reset], input[type=image], input[type=file], input[type=color], '
    + '[role=button], [role=link], [role=tab], [role=checkbox], [role=radio], [role=switch], [role=menuitem], '
    + '[role=menuitemcheckbox], [role=menuitemradio], [role=option], [onclick]';
  const set = new Set(document.querySelectorAll(inter));
  // elements with their own click listener (not containers delegating clicks)
  for (const h of A.handlers(['click'])) {
    if (h.target.nodeType === 1 && h.target !== document.body && !h.target.querySelector(inter)) set.add(h.target);
  }
  const out = [];
  let i = 0;
  for (const el of [...document.body.querySelectorAll('*')].filter(e => set.has(e))) {
    if (el.disabled || el.closest('[inert], [hidden]') || !A.shown(el)) continue;
    el.setAttribute('data-a11y-pc', String(i));
    out.push({ sel: `[data-a11y-pc="${i++}"]`, desc: A.desc(el) });
  }
  return out;
}
"""

# press point on the element and a release point just outside it (preferably
# on nothing interactive), after focusing the element so focus effects are over
PRESS_POINTS_JS = r"""
sel => {
  const A = window.__a11y, el = document.querySelector(sel);
  if (!el || !A.shown(el)) return null;
  document.activeElement && document.activeElement.blur();
  if (el.tabIndex >= 0) el.focus({ preventScroll: true });
  const down = A.hitPoint(el);
  if (!down) return null;
  const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const inter = 'a[href], button, input, select, textarea, summary, label, [tabindex], [role], [onclick]';
  let fallback = null;
  for (const d of [16, 32, 64]) {
    for (const [x, y] of [[cx, r.top - d], [cx, r.bottom + d], [r.left - d, cy], [r.right + d, cy]]) {
      if (x < 1 || y < 1 || x > innerWidth - 2 || y > innerHeight - 2) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit || el.contains(hit)) continue;
      if (!hit.closest(inter)) return { down, off: [x, y] };
      fallback = fallback || [x, y];
    }
  }
  return fallback ? { down, off: fallback } : null;
}
"""

PRESS_END_JS = r"""
() => {
  const A = window.__a11y;
  // pressing restyles the control (:active, a class): feedback, not an action
  const recs = A.watchEnd().filter(r => !(r.type === 'attributes' && /^(class|style)$/.test(r.attributeName)));
  return [...A.describeMutations(recs), ...A.formChanges()];
}
"""


def _slide_off(page: Page, pts: dict[str, list[float]], press: bool) -> list[str]:
    """Press on the control, slide off, release outside; returns what changed
    (press=False makes the same movement without a button, for comparison)."""
    url, n_pages = page.url, len(page.context.pages)
    page.evaluate("() => window.__a11y.watchStart()")
    page.mouse.move(*pts["down"])
    if press:
        page.mouse.down()
    page.mouse.move(*pts["off"], steps=6)
    if press:
        page.mouse.up()
    settle(page)
    quiet(page)
    changes: list[str] = []
    if page.url != url:
        changes.append(f"navigated to {page.url}")
        _reopen(page, url)
    else:
        changes += page.evaluate(PRESS_END_JS)
    if len(page.context.pages) > n_pages:
        changes.append("opened a new window")
        for extra in page.context.pages[n_pages:]:
            extra.close()
    return changes


def pointer_cancellation_issues(page: Page) -> list[str]:
    issues: list[str] = []
    dialogs: list[str] = []
    reactions: list[dict[str, str]] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    for t in page.evaluate(CLICK_TARGETS_JS):
        pts = page.evaluate(PRESS_POINTS_JS, t["sel"])
        if not pts:
            continue
        quiet(page)
        reactions += take_reactions(page)
        changes = _slide_off(page, pts, press=True)
        reactions += take_reactions(page)
        if _navigated(changes):
            page.evaluate(CLICK_TARGETS_JS)  # the reopened page needs its markers again
        elif changes and "opened a new window" not in changes:
            # the same pointer path without pressing: hover effects are not the press
            page.evaluate(PRESS_POINTS_JS, t["sel"])
            quiet(page)
            hover_only = set(_slide_off(page, pts, press=False))
            changes = [c for c in changes if c not in hover_only]
        if dialogs:
            changes.append(f"opened a browser dialog {dialogs[-1]!r}")
            dialogs.clear()
        if changes:
            issues.append(f"press on {t['desc']} and release outside it: {'; '.join(changes[:4])} (action not cancelled)")
        page.mouse.move(*NEUTRAL)
    for r in reactions:
        if r["type"] in ("mousedown", "pointerdown", "touchstart"):
            issues.append(f"{r['type']} listener on {r['target']} acts on the down-event: {r['what']}")
    return sorted(set(issues))


@pytest.mark.bitv("9.2.5.2")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_pointer_cancellation(open_page, page_id: str) -> None:
    """9.2.5.2 Pointer cancellation: pressing a control and sliding off it
    before releasing must not trigger it (no navigation, no new window, no
    state or content change); down-event listeners must not act."""
    page = instrumented(open_page, page_id)
    assert_no_issues(pointer_cancellation_issues(page), f"{page_id} [en]", "pointer-cancellation")


# --------------------------------------------------------------------------- #
# 9.3.2.2 On input
# --------------------------------------------------------------------------- #
INPUTS_JS = r"""
() => {
  const A = window.__a11y, out = [];
  const stable = el => {
    if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) return '#' + CSS.escape(el.id);
    // no text-bearing attributes: they change with the UI language
    const attrs = [...el.attributes].filter(a => /^(name|type|role|data-(?!a11y)[\w-]+)$/.test(a.name));
    const s = el.tagName.toLowerCase() + attrs.map(a => `[${a.name}="${CSS.escape(a.value)}"]`).join('');
    return document.querySelectorAll(s).length === 1 ? s : null;
  };
  let i = 0;
  const sel = 'select, textarea, input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=reset])'
    + ':not([type=image]):not([type=file]), [role=switch]:not(input), [role=checkbox]:not(input)';
  for (const el of document.querySelectorAll(sel)) {
    if (el.disabled || el.readOnly || el.closest('[inert], [hidden]') || !A.shown(el)) continue;
    const type = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea'
      : el.tagName === 'INPUT' ? el.type : 'toggle';
    el.setAttribute('data-a11y-in', String(i));
    out.push({ mark: `[data-a11y-in="${i}"]`, stable: stable(el), type, desc: A.desc(el), main: !!el.closest('main'), i: i++ });
  }
  // fields in the page's main content first, the header's language/theme last
  return out.sort((a, b) => (b.main - a.main) || (a.i - b.i));
}
"""

# what a change of context looks like from inside the page
CONTEXT_JS = r"""
() => {
  const A = window.__a11y;
  const main = document.querySelector('main') || document.body;
  const sig = new Map();
  for (const el of main.querySelectorAll('*')) {
    if (!A.shown(el)) continue;
    const k = el.tagName + (el.getAttribute('role') ? '/' + el.getAttribute('role') : '');
    sig.set(k, (sig.get(k) || 0) + 1);
  }
  const dialogs = [...document.querySelectorAll('dialog, [role=dialog], [role=alertdialog]')]
    .filter(d => d.matches(':modal') || (A.shown(d) && (d.open || d.getAttribute('role'))))
    .map(d => A.desc(d));
  const live = [...document.querySelectorAll('[role=status], [role=alert], [role=log], [aria-live]:not([aria-live=off]), output')]
    .map(e => e.textContent.trim()).filter(Boolean);
  return { sig: Object.fromEntries(sig), dialogs, live };
}
"""

SAMPLES = {
    "email": "a11y@example.com",
    "url": "https://example.com/v1",
    "number": "2",
    "tel": "0123456",
    "date": "2026-01-02",
    "time": "12:30",
    "month": "2026-01",
    "week": "2026-W02",
    "datetime-local": "2026-01-02T12:30",
    "color": "#336699",
}


def _replaced_share(before: dict[str, int], after: dict[str, int]) -> float:
    """Share of the main content that was replaced by other content. Content
    that only disappears (a filter hiding rows) or only appears (dependent
    fields) is a change of content, not of context; text changes in place
    (a language switch) keep the structure and count as nothing."""
    total = sum(before.values())
    gone = sum(max(0, n - after.get(k, 0)) for k, n in before.items())
    new = sum(max(0, n - before.get(k, 0)) for k, n in after.items())
    return min(gone, new) / total if total else 0.0


def _sel(f: dict[str, Any]) -> str:
    # the field itself, or the same field re-rendered by the app
    return f["mark"] + (", " + f["stable"] if f["stable"] else "")


IS_FIELD_JS = "s => { const a = document.activeElement, el = document.querySelector(s); return !!el && !!a && (a === el || el.contains(a) || a.matches(s)); }"
NO_FOCUS_JS = "() => !document.activeElement || document.activeElement === document.body"


def _change(page: Page, f: dict[str, Any]) -> str | None:
    """Change one field like a user would; returns a restore token or None."""
    loc = page.locator(_sel(f)).first
    kind = f["type"]
    if kind == "select":
        values = loc.evaluate(
            "el => [el.value, ...[...el.options].filter(o => !o.disabled && o.value !== el.value).map(o => o.value)]"
        )
        if len(values) < 2:
            return None
        loc.select_option(values[1])
        return str(values[0])
    if kind in ("checkbox", "toggle"):
        page.keyboard.press("Space")
        return "toggle"
    if kind == "radio":
        if not loc.is_checked():
            page.keyboard.press("Space")
        return None
    if kind == "range":
        page.keyboard.press("ArrowRight")
        return None
    old = str(loc.input_value())
    if kind in SAMPLES and kind not in ("number", "email", "url", "tel"):
        loc.fill(SAMPLES[kind])
    else:
        page.keyboard.press("End")
        page.keyboard.type(SAMPLES.get(kind, " a11y"))
    return old


def _restore(page: Page, f: dict[str, Any], token: str) -> None:
    """Undo the change (monitor settings are saved on change)."""
    loc = page.locator(_sel(f)).first
    if not loc.count():
        return
    if f["type"] == "select":
        loc.select_option(token)
    elif token == "toggle":
        loc.focus()
        page.keyboard.press("Space")
    else:
        loc.fill(token)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    settle(page)
    quiet(page)


def on_input_issues(page: Page) -> list[str]:
    issues: list[str] = []
    dialogs: list[str] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    for f in page.evaluate(INPUTS_JS):
        sel = _sel(f)
        loc = page.locator(sel).first
        try:
            if not loc.is_visible() or not loc.is_enabled():
                continue
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.focus(timeout=2000)
        except PlaywrightError:
            continue  # re-rendered away by an earlier change
        quiet(page)
        url, n_pages = page.url, len(page.context.pages)
        before = page.evaluate(CONTEXT_JS)
        token = _change(page, f)
        settle(page)
        quiet(page)
        found: list[str] = []
        if _navigated(page, url):
            issues.append(f"changing {f['desc']}: navigated to {page.url} (change of context on input)")
            _reopen(page, url)
            page.evaluate(INPUTS_JS)  # markers for the remaining fields
            continue
        if not page.evaluate(IS_FIELD_JS, sel):
            active = page.evaluate("() => window.__a11y.desc(document.activeElement)")
            found.append("focus was lost (moved to the page start)" if page.evaluate(NO_FOCUS_JS) else f"focus moved to {active}")
        page.evaluate("s => { const el = document.querySelector(s); el && el.blur(); }", sel)
        settle(page)
        quiet(page)
        if not found and not page.evaluate(NO_FOCUS_JS):
            found.append(f"leaving the field moved focus to {page.evaluate('() => window.__a11y.desc(document.activeElement)')}")
        if _navigated(page, url):
            found.append(f"leaving the field navigated to {page.url}")
        if len(page.context.pages) > n_pages:
            found.append("opened a new window")
            for extra in page.context.pages[n_pages:]:
                extra.close()
        if dialogs:
            found.append(f"opened a browser dialog {dialogs[-1]!r}")
            dialogs.clear()
        if _navigated(page, url):
            _reopen(page, url)
            page.evaluate(INPUTS_JS)
        else:
            after = page.evaluate(CONTEXT_JS)
            opened = [d for d in after["dialogs"] if d not in before["dialogs"]]
            if opened:
                found.append(f"opened the dialog {opened[0]}")
            share = _replaced_share(before["sig"], after["sig"])
            # announced = a live region now says something it did not say before
            announced = any(t not in before["live"] for t in after["live"])
            if share > 0.5 and not announced:
                found.append(f"replaced {share:.0%} of the main content without a status message")
            if token is not None:
                _restore(page, f, token)
            if opened:
                # close it (restoring may have opened it again), or every
                # remaining field is inert behind it
                page.keyboard.press("Escape")
                page.evaluate("() => document.querySelectorAll('dialog[open]').forEach(d => d.close())")
                settle(page)
        issues += [f"changing {f['desc']}: {what} (change of context on input)" for what in found]
    return issues


@pytest.mark.bitv("9.3.2.2")
@pytest.mark.parametrize("lang", TWO_LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_on_input_no_change_of_context(open_page, page_id: str, lang: str) -> None:
    """9.3.2.2 On input: changing a select, checkbox, radio, switch, range or
    text field (and leaving it) must not navigate, open a window or dialog,
    move focus elsewhere or replace most of the main content unannounced.
    Dependent fields appearing next to the control are fine."""
    page = instrumented(open_page, page_id, lang)
    assert_no_issues(on_input_issues(page), f"{page_id} [{lang}]", "on-input")
