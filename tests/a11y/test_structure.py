"""Order, consistency and content heuristics.

BITV 9.1.3.2 Meaningful sequence, 9.2.4.3 Focus order, 9.3.2.4 Consistent
identification, 9.2.4.5 Multiple ways, 9.3.3.4 Error prevention (data),
9.1.3.3 Sensory characteristics, 9.1.4.1 Use of colour.

What these checks decide and where a person is still needed:

* Reading and Tab order are compared with the visual order "top to bottom,
  then left to right within a row" (the UI has no RTL language). A pair only
  counts as inverted when the later element lies *entirely* left of the earlier
  one in the same row, or *entirely* above it in the same column or column to
  the left. Moving up into a column further right (a sidebar) is a normal
  column break and is allowed.
* Consistent identification keys controls by what they do (href, function
  data attributes, the shared header's classes), never by their label, and
  compares accessible name and role computed by axe-core.
* Multiple ways: each page by its URL and from every other page's navigation.
* Error prevention clicks every destructive control on a fresh page. Delete
  and reset requests are intercepted in the test's own browser context and
  answered with a fake success, so the shared fixture data is never touched;
  the data that makes every destructive action appear (a locked master key,
  a knowledge base entry of the user's) is mocked the same way.
* Sensory characteristics is a word-list heuristic (step stays partial).
* Use of colour renders the same component in every state and compares what
  is left without colour (text, icons, shapes): two states may not differ by
  colour alone.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page

from tests.a11y.harness import (
    AXE,
    DESKTOP,
    LANGS,
    PAGES,
    REPORT_FIXTURE,
    THEMES,
    assert_no_issues,
    expand_all,
    settle,
    to_top,
)

PAGE_IDS = list(PAGES)
PHONE = {"width": 375, "height": 800}
VIEWPORTS = {"desktop": DESKTOP, "375px": PHONE}
ORDER_LANGS = [x for x in ("en", "de") if x in LANGS]

# --------------------------------------------------------------------------- #
# shared in-page helpers
# --------------------------------------------------------------------------- #
DESCRIBE = """
const describeEl = el => {
  const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
  return `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls}> "${t}"`;
};
"""

# geometry: "is b shown before a?" for a that comes first (DOM or Tab order)
GEOMETRY = """
const CONTROL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex], [role=button], [role=link], [role=tab], [role=switch], [role=checkbox]';
const shown = el => {
  if (el.closest('[aria-hidden=true], [inert], [hidden]')) return false;
  const s = getComputedStyle(el), r = el.getBoundingClientRect();
  return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0;
};
const meaningful = el => !!((el.innerText || '').trim() || el.matches(CONTROL) ||
  el.querySelector(CONTROL + ', img[alt]:not([alt=""]), svg[role=img], canvas, [role=img]'));
const box = el => { const r = el.getBoundingClientRect();
  return { left: r.left + scrollX, right: r.right + scrollX, top: r.top + scrollY, bottom: r.bottom + scrollY, width: r.width, height: r.height }; };
const TOL = 1;
// 'row' / 'column' / null: b (later) is shown before a (earlier)
const inverted = (a, b) => {
  const ov = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  if (ov > 0.5 * Math.min(a.height, b.height)) return b.right <= a.left + TOL ? 'left of it in the same row' : null;
  if (b.bottom > a.top + TOL) return null;                       // not above
  const xov = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  if (xov > 0) return 'above it in the same column';
  if (b.right <= a.left + TOL) return 'above and left of it';
  return null;                                                   // up into a column further right
};
"""

# --------------------------------------------------------------------------- #
# 9.1.3.2 meaningful sequence
# --------------------------------------------------------------------------- #
SEQUENCE_JS = (
    "() => {"
    + DESCRIBE
    + GEOMETRY
    + """
  const out = [];
  const flowKids = p => {
    const kids = [];
    for (const c of p.children) {
      if (/^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT)$/.test(c.tagName)) continue;
      const s = getComputedStyle(c);
      if (s.display === 'contents') { kids.push(...flowKids(c)); continue; }
      if (s.position === 'absolute' || s.position === 'fixed') continue;   // checked below
      if (shown(c) && meaningful(c)) kids.push(c);
    }
    return kids;
  };
  const cause = (p, a, b) => {
    const ps = getComputedStyle(p), why = [];
    if (/reverse/.test(ps.flexDirection) && /flex/.test(ps.display)) why.push('flex-direction: ' + ps.flexDirection);
    if (/reverse/.test(ps.flexWrap) && /flex/.test(ps.display)) why.push('flex-wrap: ' + ps.flexWrap);
    for (const el of [a, b]) {
      const s = getComputedStyle(el);
      if (s.order !== '0' && /flex|grid/.test(ps.display)) why.push(`order: ${s.order} on ${describeEl(el)}`);
      if (/grid/.test(ps.display) && (s.gridRowStart !== 'auto' || s.gridColumnStart !== 'auto' || s.gridArea.split('/').some(x => x.trim() !== 'auto')))
        why.push(`grid placement (${s.gridArea}) on ${describeEl(el)}`);
      if (s.float !== 'none') why.push(`float: ${s.float} on ${describeEl(el)}`);
    }
    return why.length ? why.join(', ') : 'layout';
  };
  for (const p of document.body.querySelectorAll('*')) {
    if (!shown(p) || getComputedStyle(p).display === 'contents') continue;
    const kids = flowKids(p);
    if (kids.length < 2) continue;
    const boxes = kids.map(box);
    const all = kids.length <= 40;
    let first = null, n = 0;
    for (let i = 0; i < kids.length; i++) {
      for (let j = i + 1; j < (all ? kids.length : Math.min(i + 2, kids.length)); j++) {
        const how = inverted(boxes[i], boxes[j]);
        if (!how) continue;
        n++;
        if (!first) first = `${describeEl(kids[j])} comes after ${describeEl(kids[i])} in the DOM but is shown ${how} (${cause(p, kids[i], kids[j])})`;
      }
    }
    if (first) out.push(`reading order differs from visual order inside ${describeEl(p)}: ${first}` + (n > 1 ? ` (+${n - 1} more pair(s))` : ''));
  }
  // content taken out of the flow and shown far from where it is read
  const vh = innerHeight;
  for (const el of document.body.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    if (s.position !== 'absolute' && s.position !== 'fixed') continue;
    if (!shown(el) || !meaningful(el)) continue;
    if (el.closest('dialog, [role=dialog], [role=alertdialog], [role=tooltip], [popover], [role=status], [role=alert], [aria-live], [role=menu], [role=listbox]')) continue;
    const b = box(el);
    if (b.bottom < 0 || b.right < 0) continue;                     // parked off-screen (skip link)
    let ref = el.previousElementSibling;
    while (ref && !(shown(ref) && !/absolute|fixed/.test(getComputedStyle(ref).position))) ref = ref.previousElementSibling;
    if (!ref) ref = el.parentElement;
    while (ref && ref !== document.body && !shown(ref)) ref = ref.parentElement;
    if (!ref || ref === document.body) continue;
    const r = box(ref);
    const dy = Math.max(0, r.top - b.bottom, b.top - r.bottom), dx = Math.max(0, r.left - b.right, b.left - r.right);
    if (dy > Math.max(200, vh / 4) || dx > 400)
      out.push(`${describeEl(el)} is positioned (${s.position}) ${Math.round(Math.max(dx, dy))} px away from where it is read, after ${describeEl(ref)}`);
  }
  return out;
}
"""
)


@pytest.mark.bitv("9.1.3.2")
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("lang", ORDER_LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_reading_order_matches_visual_order(open_page, page_id: str, lang: str, viewport: str) -> None:
    """9.1.3.2 Meaningful sequence: siblings are shown in DOM order (no CSS
    order / *-reverse / grid placement / float that swaps meaningful content,
    no positioned content far from where it is read)."""
    page = open_page(PAGES[page_id], lang, viewport=VIEWPORTS[viewport])
    expand_all(page)
    page.evaluate("() => window.scrollTo(0, 0)")
    assert_no_issues(page.evaluate(SEQUENCE_JS), f"{page_id} [{lang}, {viewport}]", "meaningful-sequence")


# --------------------------------------------------------------------------- #
# 9.2.4.3 focus order
# --------------------------------------------------------------------------- #
STAMP_JS = """
k => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return false;
  if (!el.hasAttribute('data-a11y-tab')) el.setAttribute('data-a11y-tab', String(k));
  return true;
}
"""

FOCUS_ORDER_JS = (
    "() => {"
    + DESCRIBE
    + GEOMETRY
    + """
  // measure every stop in one layout state: no element scrolled
  window.scrollTo(0, 0);
  for (const el of document.querySelectorAll('*')) { if (el.scrollLeft) el.scrollLeft = 0; if (el.scrollTop) el.scrollTop = 0; }
  const stops = [...document.querySelectorAll('[data-a11y-tab]')]
    .sort((x, y) => +x.getAttribute('data-a11y-tab') - +y.getAttribute('data-a11y-tab'));
  const fixed = el => { for (let p = el; p && p.nodeType === 1; p = p.parentElement) if (getComputedStyle(p).position === 'fixed') return true; return false; };
  const out = [];
  let prev = null;
  for (const el of stops) {
    if (!shown(el) || fixed(el)) { prev = null; continue; }   // a dialog or toast: not part of the page order
    const b = box(el);
    if (prev) {
      const how = inverted(prev.b, b);
      if (how) out.push(`Tab moves from ${describeEl(prev.el)} to ${describeEl(el)}, which is shown ${how}`);
    }
    prev = { el, b };
  }
  return out;
}
"""
)


def tab_through(page: Page, limit: int = 400) -> int:
    """Press Tab from the top until focus leaves the page, stamping each stop
    with its position in the sequence (data-a11y-tab)."""
    page.mouse.move(0, 0)
    to_top(page)
    k = 0
    for k in range(limit):
        page.keyboard.press("Tab")
        if not page.evaluate(STAMP_JS, k):
            break
    return k


@pytest.mark.bitv("9.2.4.3")
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("lang", ORDER_LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_focus_order_matches_visual_order(open_page, page_id: str, lang: str, viewport: str) -> None:
    """9.2.4.3 Focus order: each Tab press moves forward in the visual reading
    order (right within a row, down within a column, or on to the next column)."""
    page = open_page(PAGES[page_id], lang, viewport=VIEWPORTS[viewport])
    expand_all(page)
    tab_through(page)
    assert_no_issues(page.evaluate(FOCUS_ORDER_JS), f"{page_id} [{lang}, {viewport}]", "focus-order")


# --------------------------------------------------------------------------- #
# 9.3.2.4 consistent identification
# --------------------------------------------------------------------------- #
# Data attributes that hold a control's function (data-act="del",
# data-mk="reset", data-dl="json", ...). Translation, layout and record-id
# attributes are not functions; values with digits are record ids.
NOT_A_FUNCTION = r"^data-(en|a11y|id$|i$|msg$|l0$|w$|v$|f$|page$|theme$|step$|seg$|tip$|zp$|metric$)"
# class tokens that only style a control (a component class like "rdel" or
# "secret-eye" names its function)
STYLE_CLASSES = r"^(btn|sm|lg|pri|primary|danger|danger-solid|ghost|link|linkbtn|in|mono|on|off|active|open|is-.*|has-.*|good|bad|warn|sky|grey|tag|badge|pill|more)$"

IDENTIFY_JS = """
([notFn, styleCls]) => {
  const NOT = new RegExp(notFn), STYLE = new RegExp(styleCls);
  axe.setup(document);
  const out = [];
  try {
    const sel = 'a[href], button, select, input:not([type=hidden]), textarea, summary, [role=button], [role=link], [role=tab], [role=switch], [role=checkbox], [role=menuitem]';
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      if ((r.width === 0 || r.height === 0) && !el.matches('.skip-link')) continue;
      if (el.closest('[aria-hidden=true], [inert]')) continue;
      let key = null;
      const href = el.getAttribute('href');
      if (href != null && el.matches('a')) {
        if (/^[?#]/.test(href)) key = 'link ' + href;
        else { const u = new URL(href, location.href); key = 'link ' + (u.origin === location.origin ? '' : u.origin) + u.pathname + u.search + u.hash; }
      }
      if (!key) for (const a of el.attributes) {
        if (a.name.startsWith('data-') && !NOT.test(a.name) && /^[a-z][a-z_-]*$/i.test(a.value)) { key = `[${a.name}=${a.value}]`; break; }
      }
      if (!key && el.id && !/\\d/.test(el.id)) key = '#' + el.id;
      if (!key && typeof el.className === 'string') {
        const cls = el.className.trim().split(/\\s+/).filter(c => c && !STYLE.test(c)).sort();
        if (cls.length) key = el.tagName.toLowerCase() + '.' + cls.join('.');
      }
      if (!key) continue;
      const lm = el.closest('nav, header, footer, main, aside, dialog, [role=dialog], [role=navigation], [role=banner], [role=contentinfo]');
      const where = lm ? (lm.getAttribute('role') || lm.tagName.toLowerCase()) : 'page';
      const vn = axe.utils.getNodeFromTree(el);
      const name = (vn ? axe.commons.text.accessibleTextVirtual(vn) : '').replace(/\\s+/g, ' ').trim();
      const role = (vn && axe.commons.aria.getRole(vn)) || el.tagName.toLowerCase();
      out.push({ key: `${key} in ${where}`, role, name });
    }
  } finally { axe.teardown(); }
  return out;
}
"""


@pytest.mark.bitv("9.3.2.4")
@pytest.mark.parametrize("lang", LANGS)
def test_consistent_identification(open_page, lang: str) -> None:
    """9.3.2.4 Consistent identification: a control that does the same thing
    (same link target, same data-act/-mk/-dl function, same id, same component
    class) has the same accessible name and role on every page it appears on.

    Each page contributes the set of (role, name) it uses for a function in a
    landmark; one page may use several (the logo and the "Audit" link both go
    to /v2/, the audit form has two model pickers). Two pages clash when they
    share no (role, name) for the same function: the same thing is called
    differently."""
    found: dict[str, dict[str, set[tuple[str, str]]]] = {}
    for page_id, path in PAGES.items():
        page = open_page(path, lang)
        expand_all(page)
        page.add_script_tag(path=str(AXE))
        for c in page.evaluate(IDENTIFY_JS, [NOT_A_FUNCTION, STYLE_CLASSES]):
            found.setdefault(c["key"], {}).setdefault(page_id, set()).add((c["role"], c["name"]))
    issues: list[str] = []
    for key, per_page in sorted(found.items()):
        pages = list(per_page)
        clash = [(a, b) for i, a in enumerate(pages) for b in pages[i + 1 :] if not per_page[a] & per_page[b]]
        if not clash:
            continue
        shown = "; ".join(
            f"{pid}: " + " | ".join(f"{role} {name!r}" for role, name in sorted(v)) for pid, v in per_page.items()
        )
        issues.append(f"{key} is identified differently across pages — {shown}")
    assert_no_issues(issues, f"all pages [{lang}]", "consistent-identification")


# --------------------------------------------------------------------------- #
# 9.2.4.5 multiple ways
# --------------------------------------------------------------------------- #
NAV_LINKS_JS = """
() => {
  // site-wide navigation: the nav landmark, the page header (banner) and the
  // page footer (contentinfo)
  const navs = [...document.querySelectorAll('nav, [role=navigation], [role=banner], [role=contentinfo]')].concat(
    [...document.querySelectorAll('header, footer')].filter(f => !f.closest('article, aside, main, nav, section')));
  const out = {};
  for (const nav of navs) for (const a of nav.querySelectorAll('a[href]')) {
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin) continue;
    const r = a.getBoundingClientRect(), s = getComputedStyle(a);
    // a link in a scrolled row is still there; one that is hidden is not
    const usable = r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && !a.closest('[hidden], [inert], [aria-hidden=true]');
    out[u.pathname] = out[u.pathname] || usable;
  }
  return out;
}
"""


def _norm_path(path: str) -> str:
    return path.rstrip("/") or "/"


@pytest.mark.bitv("9.2.4.5")
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
def test_every_page_reachable_from_every_page(open_page, base_url: str, viewport: str) -> None:
    """9.2.4.5 Multiple ways: every v2 page can be opened by its own URL and
    from a usable link in the site-wide navigation (nav landmark, page header
    or page footer) of every other page (two ways; the app is too small to need
    search or a site map)."""
    import httpx

    issues: list[str] = []
    for page_id, path in PAGES.items():
        r = httpx.get(base_url + path, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            issues.append(f"{page_id}: direct URL {path} answers HTTP {r.status_code}")
    for page_id, path in PAGES.items():
        page = open_page(path, "en", viewport=VIEWPORTS[viewport])
        links = {_norm_path(k): v for k, v in page.evaluate(NAV_LINKS_JS).items()}
        for other_id, other in PAGES.items():
            if other_id == page_id:
                continue
            got = links.get(_norm_path(other))
            if got is None:
                issues.append(f"{page_id}: its navigation/footer has no link to {other_id} ({other})")
            elif not got:
                issues.append(f"{page_id}: the navigation link to {other_id} ({other}) is hidden")
    assert_no_issues(issues, f"all pages [en, {viewport}]", "multiple-ways")


# --------------------------------------------------------------------------- #
# 9.3.3.4 error prevention (data)
# --------------------------------------------------------------------------- #
# Requests that destroy data. In the test's browser context they never reach
# the server: they are logged and answered with a fake success, so the UI
# behaves as after a real delete while the shared fixture data stays intact.
DESTRUCTIVE_POSTS = re.compile(r"/(reset|clear|purge|wipe|delete|remove)(/|$)")
# Every destructive action of the app; each must be found and checked.
EXPECTED_DESTRUCTIVE = {
    "history": [r"DELETE /api/history/\d+$", r"DELETE /api/history$"],
    "monitors": [r"DELETE /api/watches/\d+$", r"POST /api/secret/reset$"],
    "kb": [r"DELETE /api/kb/entries/\d+$"],
}
# a lost master key (the only state that offers "reset"), answered to this page only
LOCKED_VAULT = {
    "state": "locked", "source": None, "fingerprint": None, "actions": ["unlock", "reset"], "warnings": [],
    "error": None, "counts": {"encrypted": 1, "locked": 0, "unreadable": 0, "plain": 0},
}  # fmt: skip
# one entry of the user's own, so the knowledge base page offers "Delete"
FAKE_KB_ENTRY = {
    "id": 990001, "kind": "model", "provider": "a11y", "model_id": "a11y-test-model", "enabled": True,
    "origin": "a11y", "created_ts": 1790000000, "updated_ts": 1790000000,
}  # fmt: skip
# the same entry as the Knowledge page lists it (a model of your own: deletable)
FAKE_KB_MODEL = {
    "key": "model:a11y/a11y-test-model", "provider": "a11y", "provider_name": "A11y", "id": "a11y-test-model",
    "aliases": [], "kind": "chat", "context_window_tokens": 8192, "max_output_tokens": 1024,
    "source": "kb.db:entry/990001", "yours": True, "entry_id": 990001, "enabled": True, "provider_enabled": True,
    "shadows": None, "effective_source": None,
}  # fmt: skip

DESTRUCTIVE_WORDS = r"\b(delete|remove|clear|erase|reset|drop|discard|purge|wipe|forget)\b"
UNDO_WORDS = r"\b(undo|restore|revert)\b"

CONTROL_HELPERS = """
const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && !el.closest('[hidden], [inert], [aria-hidden=true]'); };
const label = el => [el.getAttribute('aria-label'), el.innerText, el.getAttribute('title'), el.value]
  .filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
const fnOf = el => [...el.attributes].filter(a => a.name.startsWith('data-') && !/^data-(en|a11y)/.test(a.name))
  .map(a => a.value).join(' ').replace(/[-_]/g, ' ');
"""

CANDIDATES_JS = (
    "([words]) => {"
    + CONTROL_HELPERS
    + """
  const re = new RegExp(words, 'i');
  const out = [];
  for (const el of document.querySelectorAll('button, [role=button], a[href], input[type=submit], input[type=button]')) {
    if (!vis(el) || el.disabled) continue;
    if (re.test(label(el)) || re.test(fnOf(el)) || el.matches('.danger, .danger-solid')) {
      el.setAttribute('data-a11y-d', String(out.length));
      out.push(label(el).slice(0, 50) || el.outerHTML.slice(0, 60));
    }
  }
  return out;
}
"""
)

# marks what is on screen before the click; returns the clicked control's identity
SNAPSHOT_JS = (
    "(sel) => {"
    + CONTROL_HELPERS
    + """
  for (const el of document.querySelectorAll('button, [role=button], a[href], input, select, textarea'))
    if (el.getBoundingClientRect().width > 0) el.setAttribute('data-a11y-seen', '');
  const t = document.querySelector(sel);
  return label(t) + '|' + fnOf(t);
}
"""
)

# open disclosures, but not the ones that start a delete (expand_all would)
SAFE_EXPAND_JS = (
    "([words]) => {"
    + CONTROL_HELPERS
    + """
  const re = new RegExp(words, 'i');
  let n = 0;
  for (const el of document.querySelectorAll('[aria-expanded="false"]')) {
    if (!vis(el) || el.closest('nav, header') || el.hasAttribute('aria-haspopup')) continue;
    if (re.test(label(el)) || re.test(fnOf(el)) || el.matches('.danger, .danger-solid')) continue;
    el.click(); n++;
  }
  for (const d of document.querySelectorAll('details:not([open])')) { d.open = true; n++; }
  return n;
}
"""
)

# the controls a click revealed: a confirmation step shows a new "yes" button
NEW_CONTROLS_JS = (
    "([words, undo, clicked]) => {"
    + CONTROL_HELPERS
    + """
  const re = new RegExp(words, 'i'), reUndo = new RegExp(undo, 'i');
  // re-rendered markup brings the clicked control back as a "new" one: skip it
  const fresh = [...document.querySelectorAll('button, [role=button], a[href], input, select, textarea')]
    .filter(el => vis(el) && !el.hasAttribute('data-a11y-seen') && label(el) + '|' + fnOf(el) !== clicked);
  fresh.forEach((el, i) => el.setAttribute('data-a11y-new', String(i)));
  let yes = null, undoBtn = null, typed = null;
  for (const el of fresh) {
    if (el.disabled) continue;
    if (!undoBtn && reUndo.test(label(el))) undoBtn = label(el);
    if (!yes && el.matches('button, input[type=submit]') && !/\\b(no|cancel)\\b/i.test(fnOf(el) + ' ' + label(el)) &&
        (re.test(label(el)) || re.test(fnOf(el)) || el.matches('.danger, .danger-solid')))
      yes = el.getAttribute('data-a11y-new');
  }
  // "Type RESET to confirm": the upper-case word after "type" / "enter"
  const input = fresh.find(el => el.matches('input:not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea') && !el.value);
  if (input) {
    const ids = (input.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
    const q = ids.map(id => (document.getElementById(id) || {}).innerText || '').join(' ') + ' ' + ((input.closest('form') || {}).innerText || '');
    const m = /\\b(?:[Tt]ype|[Ee]nter)\\s+["'“„«]?([A-Z]{3,})\\b/.exec(q);
    typed = { i: input.getAttribute('data-a11y-new'), word: m ? m[1] : null };
  }
  return { yes, undo: undoBtn, typed };
}
"""
)


@pytest.fixture
def open_routed_page(open_page: Any) -> Iterator[Any]:
    """open_page for tests that mock requests: the mocks are removed (pending
    ones ignored) before the contexts close, so none fails into the next test."""
    yield open_page
    for ctx in open_page.contexts:
        with contextlib.suppress(Exception):
            ctx.unroute_all(behavior="ignoreErrors")


def _guarded_page(open_page: Any, page_id: str, log: list[str], dialogs: list[str]) -> Page:
    """The page with destructive requests intercepted, and the data seeded
    (for this browser context only) that makes every destructive action show."""
    import httpx

    page: Page = open_page(PAGES[page_id], "en")
    kb = httpx.get(open_page.base_url + "/api/kb/profiles", timeout=10).json()
    kb["entries"] = [FAKE_KB_ENTRY, *(kb.get("entries") or [])]
    kb["models"] = [FAKE_KB_MODEL, *(kb.get("models") or [])]
    kb["entry_count"] = len(kb["entries"])

    def handle(route: Any) -> None:
        req = route.request
        path = urlparse(req.url).path
        if req.method == "DELETE" or (req.method == "POST" and DESTRUCTIVE_POSTS.search(path)):
            log.append(f"{req.method} {path}")
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
        elif req.method == "GET" and path == "/api/secret":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(LOCKED_VAULT))
        elif req.method == "GET" and path == "/api/kb/profiles":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(kb))
        else:
            route.fallback()

    page.context.route("**/api/**", handle)

    def on_dialog(d: Any) -> None:
        dialogs.append(f"{d.type}: {d.message[:80]}")
        d.dismiss()  # "Cancel": nothing may be deleted

    page.on("dialog", on_dialog)
    page.reload(wait_until="load")
    settle(page)
    for _ in range(2):
        if not page.evaluate(SAFE_EXPAND_JS, [DESTRUCTIVE_WORDS]):
            break
        settle(page)
    return page


@pytest.mark.bitv("9.3.3.4")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_destructive_actions_ask_first(open_routed_page, page_id: str) -> None:
    """9.3.3.4 Error prevention (data): every action that deletes or resets
    data asks first (a confirm() dialog or an inline confirmation step) or can
    be undone. Each destructive-looking control is clicked on a fresh page: a
    destructive request sent by that first click, with no dialog and no undo
    control appearing, fails. An inline confirmation must be what deletes:
    its "yes" is pressed and the request has to follow. Every destructive
    endpoint of the app must be met this way."""
    log: list[str] = []
    dialogs: list[str] = []
    page = _guarded_page(open_routed_page, page_id, log, dialogs)
    names: list[str] = page.evaluate(CANDIDATES_JS, [DESTRUCTIVE_WORDS])
    issues: list[str] = []
    checked: list[str] = []
    for i, name in enumerate(names):
        if i:
            log.clear()
            dialogs.clear()
            page = _guarded_page(open_routed_page, page_id, log, dialogs)
            page.evaluate(CANDIDATES_JS, [DESTRUCTIVE_WORDS])
        target = page.locator(f'[data-a11y-d="{i}"]')
        if not target.count():
            issues.append(f"destructive control {name!r} is gone after reloading the page")
            continue
        clicked = page.evaluate(SNAPSHOT_JS, f'[data-a11y-d="{i}"]')
        target.first.click()
        settle(page)
        new = page.evaluate(NEW_CONTROLS_JS, [DESTRUCTIVE_WORDS, UNDO_WORDS, clicked])
        if log:
            checked += log
            if dialogs:
                issues.append(f"{name!r}: {', '.join(log)} sent although the confirmation dialog was cancelled")
            elif not new["undo"]:
                issues.append(f"{name!r} deletes at once ({', '.join(log)}): no confirmation, no undo")
            continue
        if dialogs or new["yes"] is None:
            continue  # asked by confirm() and nothing sent, or not destructive at all
        if new["typed"] and new["typed"]["word"]:
            page.locator(f'[data-a11y-new="{new["typed"]["i"]}"]').fill(new["typed"]["word"])
        page.locator(f'[data-a11y-new="{new["yes"]}"]').first.click()
        settle(page)
        checked += log
    for pattern in EXPECTED_DESTRUCTIVE.get(page_id, []):
        if not any(re.search(pattern, x) for x in checked):
            issues.append(f"no control found that sends {pattern!r}: destructive action missing or not checked")
    assert_no_issues(issues, f"{page_id} [en]", "error-prevention")


# --------------------------------------------------------------------------- #
# 9.1.3.3 sensory characteristics (heuristic: the step stays "partial")
# --------------------------------------------------------------------------- #
# A sentence is reported when it holds all three of
#   * an instruction verb (click, wählen, cliquez, 点击, ...),
#   * a sensory cue: side (left/right, not above/below: those follow the
#     reading order, which test_reading_order_matches_visual_order checks),
#     colour, shape, size or sound,
#   * a UI object noun (button, icon, field, ...),
# and does not also name the control by its label (quoted text or <b>,
# <strong>, <code>, <kbd>). "Click the green button on the right" fails;
# 'Click the green "Save" button' and "Use the form above" pass.
_SENSE: dict[str, tuple[str, str, str]] = {
    # lang: (verbs, sensory cues, objects) as regex alternatives
    "en": (
        r"click|tap|press|select|choose|use|hit|push|pick|look for|find|follow|open|enter|type|check",
        r"left|right|left-hand|right-hand|red|green|blue|yellow|orange|grey|gray|purple|round|square|circular|"
        r"triangular|star-shaped|big|large|small|tiny|beep|chime|tone",
        r"buttons?|icons?|links?|fields?|box(es)?|symbols?|arrows?|dots?|circles?|lights?|tabs?|menus?|columns?|"
        r"corners?|sides?|panels?|badges?|switch(es)?|toggles?|bars?",
    ),
    "de": (
        r"klicken|klicke|klick|tippen|tippe|drücken|drücke|wählen|wähle|nutzen|nutze|verwenden|verwende|öffnen|öffne|"
        r"geben sie|gib|suchen|suche|achten|beachten",
        r"links|rechts|linken|rechten|rot\w*|grün\w*|blau\w*|gelb\w*|orange\w*|grau\w*|rund\w*|eckig\w*|quadratisch\w*|"
        r"dreieckig\w*|groß\w*|klein\w*|piep\w*|signalton",
        r"schaltfläche\w*|button\w*|knopf|knöpfe|symbol\w*|icon\w*|link\w*|feld\w*|kästchen|pfeil\w*|punkt\w*|kreis\w*|"
        r"menü\w*|spalte\w*|ecke\w*|seite|leiste\w*|reiter|schalter\w*",
    ),
    "fr": (
        r"cliquez|cliquer|appuyez|appuyer|touchez|sélectionnez|choisissez|utilisez|ouvrez|saisissez|cherchez",
        r"gauche|droite|rouge|vert|verte|bleu|bleue|jaune|orange|gris|grise|rond|ronde|carré|carrée|triangulaire|"
        r"grand|grande|petit|petite|bip|signal sonore",
        r"bouton|boutons|icône|icônes|lien|liens|champ|champs|case|cases|symbole|flèche|point|cercle|menu|colonne|"
        r"coin|côté|panneau|onglet|interrupteur|barre",
    ),
    "es": (
        r"haga clic|haz clic|pulse|pulsa|presione|presiona|toque|toca|seleccione|selecciona|elija|elige|use|usa|"
        r"utilice|abra|abre|introduzca|busque",
        r"izquierda|derecha|rojo|roja|verde|azul|amarillo|amarilla|naranja|gris|redondo|redonda|cuadrado|cuadrada|"
        r"triangular|grande|pequeño|pequeña|pitido|sonido",
        r"botón|botones|icono|iconos|enlace|enlaces|campo|campos|casilla|símbolo|flecha|punto|círculo|menú|columna|"
        r"esquina|lado|panel|pestaña|interruptor|barra",
    ),
    "pt": (
        r"clique|clica|toque|toca|pressione|prima|selecione|seleciona|escolha|escolhe|use|usa|utilize|abra|abre|"
        r"insira|introduza|digite|procure",
        r"esquerda|direita|vermelho|vermelha|verde|azul|amarelo|amarela|laranja|cinza|cinzento|redondo|redonda|"
        r"quadrado|quadrada|triangular|grande|pequeno|pequena|bipe|som",
        r"botão|botões|ícone|ícones|link|links|campo|campos|caixa|símbolo|seta|ponto|círculo|menu|coluna|canto|lado|"
        r"painel|separador|aba|interruptor|barra",
    ),
    "it": (
        r"clicca|cliccare|fai clic|premi|premere|tocca|seleziona|scegli|usa|utilizza|apri|inserisci|cerca",
        r"sinistra|destra|rosso|rossa|verde|blu|giallo|gialla|arancione|grigio|grigia|rotondo|rotonda|quadrato|"
        r"quadrata|triangolare|grande|piccolo|piccola|bip|segnale acustico",
        r"pulsante|pulsanti|bottone|icona|icone|link|campo|campi|casella|simbolo|freccia|punto|cerchio|menu|colonna|"
        r"angolo|lato|pannello|scheda|interruttore|barra",
    ),
    "zh": (
        r"点击|单击|点按|按下|轻触|选择|使用|打开|输入|查找",
        r"左侧|右侧|左边|右边|左上角|右上角|左下角|右下角|红色|绿色|蓝色|黄色|橙色|灰色|圆形|方形|三角形|大的|小的|"
        r"提示音|蜂鸣",
        r"按钮|图标|链接|输入框|框|符号|箭头|圆点|圆圈|菜单|标签页|栏|角|开关|面板",
    ),
}
_LABEL_REF = re.compile(r"[\"“”„«»‘’「」『』]|'[^']+'|<(b|strong|code|kbd)\b|class=['\"][^'\"]*\bkbd\b")
_SENTENCE_END = re.compile(r"(?<=[.!?。！？；;])\s*|\n+")


def _sense_patterns(lang: str) -> tuple[re.Pattern[str], ...]:
    verbs, cues, objects = _SENSE[lang]
    if lang == "zh":
        return tuple(re.compile(f"(?:{p})") for p in (verbs, cues, objects))
    return tuple(re.compile(rf"(?<![\w-])(?:{p})(?![\w-])", re.I) for p in (verbs, cues, objects))


def sensory_instructions(text: str, lang: str) -> list[str]:
    """Sentences of `text` (in `lang`) that give an instruction by a sensory
    cue alone; markup counts as a label reference."""
    verbs, cues, objects = _sense_patterns(lang)
    found = []
    for sentence in _SENTENCE_END.split(text):
        cued = verbs.search(sentence) and cues.search(sentence) and objects.search(sentence)
        if cued and not _LABEL_REF.search(sentence):
            found.append(re.sub(r"<[^>]+>", "", sentence).strip())
    return found


SENSORY_SAMPLES = {
    # lang: (instructions by a sensory cue alone, ones that are fine)
    "en": (["Click the green button on the right to continue.", "Press the round icon to start."],
           ['Click the green "Save" button.', "Use the form above to add your first one.", "Latency above 30 s."]),
    "de": (["Klicken Sie auf den roten Knopf rechts.", "Wähle das runde Symbol."],
           ["Legen Sie die erste mit dem Formular oben an.", "Klicken Sie auf die grüne Schaltfläche „Speichern“."]),
    "fr": (["Cliquez sur le bouton rouge à droite."], ["Cliquez sur le bouton « Enregistrer »."]),
    "es": (["Haga clic en el botón verde de la derecha."], ["Use el formulario de arriba."]),
    "pt": (["Clique no botão vermelho à direita."], ["Clique no botão <b>Guardar</b>."]),
    "it": (["Clicca il pulsante rosso a destra."], ["Il modello è più piccolo."]),
    "zh": (["请点击右侧的绿色按钮。"], ["点击“保存”按钮。", "使用上面的表单添加第一个监控。"]),
}  # fmt: skip


@pytest.mark.bitv("9.1.3.3")
def test_sensory_heuristic_self_check() -> None:
    """The word lists catch a sensory-only instruction in every language and
    let a labelled or reading-order reference pass (guards the heuristic)."""
    issues = []
    for lang in LANGS:
        bad, good = SENSORY_SAMPLES.get(lang, ([], []))
        if not bad:
            issues.append(f"no samples for {lang!r}")
        issues += [f"[{lang}] not caught: {s!r}" for s in bad if not sensory_instructions(s, lang)]
        issues += [f"[{lang}] false alarm: {s!r}" for s in good if sensory_instructions(s, lang)]
    assert_no_issues(issues, "sensory heuristic", "sensory-characteristics")


LOCALES = Path(__file__).resolve().parents[2] / "zing" / "i18n" / "locales"
STATIC = Path(__file__).resolve().parents[2] / "zing" / "web" / "static"


def _locale_strings() -> Iterator[tuple[str, str, str]]:
    """(lang, string, where) for every string of the UI: locale files and
    fragments (keys are the English source), and the Chinese/English pairs
    written into the pages (data-en attributes, T("zh", "en") calls)."""

    def walk(node: Any, lang: str, where: str) -> Iterator[tuple[str, str, str]]:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    yield "en", k, where
                    yield lang, v, where
                else:
                    yield from walk(v, lang, where)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v, lang, where)

    for f in sorted([*LOCALES.glob("*.json"), *LOCALES.glob("fragments/*/*.json")]):
        data = json.loads(f.read_text(encoding="utf-8"))
        yield from walk({k: v for k, v in data.items() if k != "meta"}, f.stem, str(f.relative_to(LOCALES.parents[2])))
    pair = re.compile(r"""T[f]?\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*""")
    attr = re.compile(r"""data-en(?:-[\w-]+)?=["']([^"']*)["']""")
    for f in sorted([*STATIC.glob("*.js"), *STATIC.glob("*.html"), *STATIC.glob("v2/*")]):
        if f.suffix not in {".js", ".html"}:
            continue
        src = f.read_text(encoding="utf-8")
        where = str(f.relative_to(STATIC.parents[2]))
        for zh, en in pair.findall(src):
            yield "zh", zh, where
            yield "en", en, where
        for en in attr.findall(src):
            yield "en", en, where


@pytest.mark.bitv("9.1.3.3")
def test_no_sensory_only_instructions_in_strings() -> None:
    """9.1.3.3 Sensory characteristics: no UI string, in any language, tells
    the user to find or use something only by side, colour, shape, size or
    sound (heuristic, see _SENSE)."""
    strings = list(_locale_strings())
    issues = sorted(
        {
            f"[{lang}] {hit!r} ({where})"
            for lang, text, where in strings
            if lang in _SENSE
            for hit in sensory_instructions(text, lang)
        }
    )
    issues += [f"no sensory word list for {lang!r} in _SENSE" for lang in LANGS if lang not in _SENSE]
    scanned = {lang for lang, _, _ in strings}
    issues += [f"no strings found for {lang!r}: the scan misses its locale files" for lang in LANGS if lang not in scanned]
    assert_no_issues(issues, "locale files and page sources", "sensory-characteristics")


VISIBLE_TEXT_JS = """
() => {
  const out = [];
  const seen = new Set();
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'; };
  // innerText of each element that has text of its own; markup that names a
  // label (<b>, <code>, ...) is kept as a tag so it counts as a reference
  for (const el of document.body.querySelectorAll('*')) {
    if (/^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT)$/.test(el.tagName) || !vis(el)) continue;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    // SVG elements (chart labels) have no innerText
    let t = (el.innerText ?? el.textContent ?? '').trim();
    if (el.querySelector('b, strong, code, kbd')) t += ' <b>';
    if (t && !seen.has(t)) { seen.add(t); out.push(t); }
  }
  for (const el of document.querySelectorAll('[aria-label], [title], [placeholder]'))
    for (const a of ['aria-label', 'title', 'placeholder']) {
      const v = el.getAttribute(a); if (v && !seen.has(v)) { seen.add(v); out.push(v); }
    }
  return out;
}
"""


@pytest.mark.bitv("9.1.3.3")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_no_sensory_only_instructions_on_page(open_page, page_id: str, lang: str) -> None:
    """9.1.3.3 Sensory characteristics: the same heuristic on what each page
    shows (generated text included), every disclosure open."""
    page = open_page(PAGES[page_id], lang)
    expand_all(page)
    texts: list[str] = page.evaluate(VISIBLE_TEXT_JS)
    if lang not in _SENSE:
        issues = [f"no sensory word list for {lang!r} in _SENSE"]
    else:
        issues = sorted({repr(hit) for t in texts for hit in sensory_instructions(t, lang)})
    assert_no_issues(issues, f"{page_id} [{lang}]", "sensory-characteristics")


# --------------------------------------------------------------------------- #
# 9.1.4.1 use of colour
# --------------------------------------------------------------------------- #
# Each status component is rendered once per state with everything else
# equal. What is left without colour (visible text, icon shapes, images,
# pseudo-element content, border style, font weight/style, decoration) must
# differ between two states whose colours differ: otherwise the states are
# told apart by colour alone. Screen-reader-only text does not count.
NO_TRANSITIONS_CSS = "*, *::before, *::after { transition: none !important; animation: none !important; }"

SIGNATURE_JS = """
(sel) => {
  const root = document.querySelector(sel);
  if (!root) return null;
  // the same disclosures open in every state
  for (let k = 0; k < 2; k++)
    for (const b of root.querySelectorAll('[aria-expanded="false"]')) if (b.getBoundingClientRect().width > 0) b.click();
  const shown = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0; };
  const plain = [], colour = [];
  const walk = el => {
    if (!shown(el)) return;
    const s = getComputedStyle(el);
    for (const p of ['::before', '::after']) {
      const c = getComputedStyle(el, p).content;
      if (c && c !== 'none' && c !== 'normal' && c !== '""') plain.push(p + c);
    }
    const bw = ['Top', 'Right', 'Bottom', 'Left'].filter(sd => parseFloat(s['border' + sd + 'Width']) > 0);
    plain.push(`<${el.tagName.toLowerCase()} ${s.fontWeight} ${s.fontStyle} ${s.textDecorationLine} ${bw.map(sd => s['border' + sd + 'Style']).join('/')}>`);
    colour.push([s.color, s.backgroundColor, s.backgroundImage, ...bw.map(sd => s['border' + sd + 'Color']), s.fill, s.stroke, s.opacity].join(' '));
    if (el.tagName.toLowerCase() === 'svg') { plain.push('svg:' + el.innerHTML.replace(/\\s+/g, ' ')); return; }
    if (el.tagName.toLowerCase() === 'img') { plain.push('img:' + el.getAttribute('src')); return; }
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) plain.push(n.textContent.trim());
      else if (n.nodeType === 1) walk(n);
    }
  };
  walk(root);
  return { plain: plain.join('|'), colour: colour.join('|') };
}
"""


def colour_only_pairs(states: list[tuple[str, dict[str, str] | None]], what: str) -> list[str]:
    """Groups of states whose colour-free rendering is identical although their
    colours differ (states identical in colour too are not a colour problem)."""
    issues = [f"{what} {name}: not rendered" for name, sig in states if sig is None]
    groups: dict[str, list[tuple[str, str]]] = {}
    for name, sig in states:
        if sig is not None:
            groups.setdefault(sig["plain"], []).append((name, sig["colour"]))
    for same in groups.values():
        if len({colour for _, colour in same}) > 1:
            names = ", ".join(repr(name) for name, _ in same)
            issues.append(f"{what}: states {names} differ only by colour (same text, icons and shapes)")
    return issues


RENDER_REPORT_JS = """
(report) => {
  let host = document.getElementById('a11y-states');
  if (host) host.remove();
  host = document.createElement('div');
  host.id = 'a11y-states';
  (document.querySelector('main') || document.body).appendChild(host);
  ZingReport.render(host, report, {});
}
"""

RISKS = ["clean", "low", "medium", "high", "inconclusive"]
STATUSES = ["pass", "info", "warn", "fail", "error", "inconclusive", "not_run"]
SEVERITIES = ["critical", "high", "medium", "low", "info"]


def _report_state_sets(report: dict[str, Any]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Copies of the fixture report that differ in one status field each."""

    def variant(path: list[Any], value: Any) -> dict[str, Any]:
        r = json.loads(json.dumps(report))
        node = r
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
        return r

    return {
        "verdict risk level": [(v, variant(["verdict", "risk_level"], v)) for v in RISKS],
        "dimension status": [(v, variant(["dimensions", 0, "status"], v)) for v in STATUSES],
        "detector status": [(v, variant(["detectors", 0, "status"], v)) for v in STATUSES],
        "finding status": [(v, variant(["detectors", 0, "findings", 0, "status"], v)) for v in STATUSES],
        "finding severity": [(v, variant(["detectors", 0, "findings", 0, "severity"], v)) for v in SEVERITIES],
    }


@pytest.mark.bitv("9.1.4.1")
@pytest.mark.parametrize("lang", LANGS)
def test_report_states_not_by_colour_alone(open_page, lang: str) -> None:
    """9.1.4.1 Use of colour: the rendered report (risk badge, verdict banner,
    dimension meters and status, detector and finding chips) shows each
    state by text or icon too, not by colour alone."""
    page = open_page(PAGES["history"], lang)
    page.add_style_tag(content=NO_TRANSITIONS_CSS)
    report = json.loads(REPORT_FIXTURE.read_text(encoding="utf-8"))
    issues: list[str] = []
    for what, variants in _report_state_sets(report).items():
        states = []
        for name, rep in variants:
            page.evaluate(RENDER_REPORT_JS, rep)
            settle(page)
            states.append((name, page.evaluate(SIGNATURE_JS, "#a11y-states")))
        issues += colour_only_pairs(states, what)
    assert_no_issues(issues, f"report [{lang}]", "use-of-colour")


def _mock_list(page: Page, path: str, rows: Any) -> None:
    body = json.dumps(rows)

    def handle(route: Any) -> None:
        if route.request.method == "GET" and urlparse(route.request.url).path == path:
            route.fulfill(status=200, content_type="application/json", body=body)
        else:
            route.fallback()

    page.context.route("**/api/**", handle)
    page.reload(wait_until="load")
    settle(page)
    page.add_style_tag(content=NO_TRANSITIONS_CSS)


@pytest.mark.bitv("9.1.4.1")
@pytest.mark.parametrize("lang", LANGS)
def test_list_states_not_by_colour_alone(open_routed_page, base_url: str, lang: str) -> None:
    """9.1.4.1 Use of colour: history rows (risk badge) and monitor cards
    (status badge) in every state, from mocked lists that differ only there."""
    import httpx

    issues: list[str] = []
    # history: one row per risk level, everything else equal
    first = httpx.get(base_url + "/api/history?limit=1&perf=1", timeout=10).json()[0]
    rows = [dict(first, id=900001 + k, risk_level=v) for k, v in enumerate(RISKS)]
    page = open_routed_page(PAGES["history"], lang)
    _mock_list(page, "/api/history", rows)
    states = [(r["risk_level"], page.evaluate(SIGNATURE_JS, f'li.row[data-id="{r["id"]}"] .rmain')) for r in rows]
    issues += colour_only_pairs(states, "history row")
    # monitors: every badge state of a card
    mon = httpx.get(base_url + "/api/watches", timeout=10).json()[0]
    base = dict(mon, interval_sec=3600, enabled=False, running=False, last_risk=None, last_run_ts=None)
    cards = {f"last risk {v}": dict(base, last_risk=v, last_run_ts=1790000000) for v in RISKS}
    cards |= {"not run yet": base, "no result": dict(base, last_run_ts=1790000000), "needs setup": dict(base, interval_sec=None)}
    watches = [dict(w, id=900001 + k) for k, w in enumerate(cards.values())]
    page = open_routed_page(PAGES["monitors"], lang)
    _mock_list(page, "/api/watches", watches)
    states = [(name, page.evaluate(SIGNATURE_JS, f'#w-{w["id"]} .mon-title .badge')) for name, w in zip(cards, watches, strict=True)]
    issues += colour_only_pairs(states, "monitor status badge")
    assert_no_issues(issues, f"history + monitors [{lang}]", "use-of-colour")


DIMS_STATE_JS = """
(id) => {
  const a = document.activeElement, card = document.getElementById('w-' + id);
  const input = card.querySelector('[data-act="f-dims"]');
  const err = input && document.getElementById('dme-' + id);
  return {
    focus: a ? (a.getAttribute('data-act') || a.tagName) : null,
    name: input ? input.getAttribute('aria-label') : null,
    described: input ? (input.getAttribute('aria-describedby') || '').split(' ')
      .filter(x => { const e = document.getElementById(x); return e && !e.hidden && e.textContent.trim(); }).length : 0,
    invalid: input ? input.getAttribute('aria-invalid') : null,
    error: err && !err.hidden ? err.textContent.trim() : '',
    surfaces: [...document.querySelectorAll('.mon')].map(c => c.querySelector('.mon-meta .badge') ? c.querySelector('.mon-meta .badge').textContent.trim() : ''),
  };
}
"""


@pytest.mark.bitv("9.3.3.1", "9.3.3.2", "9.4.1.2", "9.2.4.3")
@pytest.mark.parametrize("lang", LANGS)
def test_tool_monitor_cards(open_routed_page, base_url: str, lang: str) -> None:
    """Embedding and rerank monitor cards: the surface reads as text, and the
    claimed-dimension editor is named, described, reports a wrong value next to
    the field with focus on it, and Escape returns focus to its button."""
    import httpx

    mon = httpx.get(base_url + "/api/watches", timeout=10).json()[0]
    base = dict(mon, interval_sec=3600, enabled=False, running=False)
    watches = [dict(base, id=900101, surface="embedding", embedding_dimensions=1536),
               dict(base, id=900102, surface="rerank", embedding_dimensions=0)]  # fmt: skip
    page = open_routed_page(PAGES["monitors"], lang)
    _mock_list(page, "/api/watches", watches)
    issues: list[str] = []
    s = page.evaluate(DIMS_STATE_JS, 900101)
    if len([x for x in s["surfaces"] if x]) != 2:
        issues.append(f"the embedding and rerank cards do not both name their surface: {s['surfaces']}")
    if page.locator('#w-900102 [data-act="edit-dims"]').count():
        issues.append("a rerank card offers a claimed dimension")
    page.locator('#w-900101 [data-act="edit-dims"]').focus()
    page.keyboard.press("Enter")
    settle(page)
    s = page.evaluate(DIMS_STATE_JS, 900101)
    if s["focus"] != "f-dims":
        issues.append(f"opening the editor puts focus on {s['focus']}, not on the field")
    if not s["name"] or not s["described"]:
        issues.append("the claimed-dimension field has no name or no hint")
    page.keyboard.press("Control+a")
    page.keyboard.type("12x")
    page.keyboard.press("Enter")
    settle(page)
    s = page.evaluate(DIMS_STATE_JS, 900101)
    if s["invalid"] != "true" or not s["error"] or s["focus"] != "f-dims":
        issues.append(f"a wrong value is not reported on the field: {s}")
    page.keyboard.press("Escape")
    settle(page)
    s = page.evaluate(DIMS_STATE_JS, 900101)
    if s["focus"] != "edit-dims":
        issues.append(f"Escape leaves focus on {s['focus']}, not on the edit button")
    assert_no_issues(issues, f"tool monitor cards [{lang}]", "tool-monitors")


EMBED_RESULT = {
    "risk_level": "high", "score": 50,
    "target": {"base_url": "http://relay.invalid/v1", "model": "text-embedding-3-small"},
    "findings": [{"id": "embed.dimension", "status": "fail", "title": "Vector dimension", "summary": "Vector dimension check.",
                  "evidence": {"returned": 1536, "claimed": 1536}}],
}  # fmt: skip

SUBMIT_EMBED_JS = """
() => {
  document.getElementById('e-url').value = 'http://relay.invalid/v1';
  document.getElementById('e-model').value = 'text-embedding-3-small';
  document.getElementById('embed-form').requestSubmit();
}
"""


@pytest.mark.bitv("9.1.4.1")
@pytest.mark.parametrize("lang", LANGS)
def test_tool_result_states_not_by_colour_alone(open_routed_page, lang: str) -> None:
    """9.1.4.1 Use of colour: the embedding check's result card (verdict badge,
    check status) in every state, from a mocked /api/embed answer."""
    page = open_routed_page(PAGES["tools"], lang)
    page.add_style_tag(content=NO_TRANSITIONS_CSS)
    answer: dict[str, Any] = {}

    def handle(route: Any) -> None:
        if route.request.method == "POST" and urlparse(route.request.url).path == "/api/embed":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))
        else:
            route.fallback()

    page.context.route("**/api/**", handle)
    sets = {
        "verdict badge": [(v, dict(EMBED_RESULT, risk_level=v)) for v in RISKS],
        "check status": [
            (v, dict(EMBED_RESULT, findings=[dict(EMBED_RESULT["findings"][0], status=v)])) for v in STATUSES
        ],
    }
    issues: list[str] = []
    for what, variants in sets.items():
        states = []
        for name, data in variants:
            answer.clear()
            answer.update(data)
            page.evaluate("() => { document.getElementById('e-out').innerHTML = ''; }")
            with page.expect_response("**/api/embed"):
                page.evaluate(SUBMIT_EMBED_JS)
            page.wait_for_selector("#e-out .res")
            settle(page)
            states.append((name, page.evaluate(SIGNATURE_JS, "#e-out .res")))
        issues += colour_only_pairs(states, what)
    assert_no_issues(issues, f"tools [{lang}]", "use-of-colour")


# links inside running text: underlined, or 3:1 against the text around them
# plus an underline on hover and focus (WCAG technique G183, failure F73)
INLINE_LINKS_JS = (
    """
() => {
  const parse = c => { const m = /rgba?\\(([^)]+)\\)/.exec(c || ''); if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  """
    + DESCRIBE
    + """
  const out = [];
  let i = 0;
  for (const a of document.querySelectorAll('a[href]')) {
    const s = getComputedStyle(a), r = a.getBoundingClientRect();
    if (r.width === 0 || s.visibility === 'hidden' || !s.display.startsWith('inline') || s.display === 'inline-flex') continue;
    if (a.closest('nav, [role=navigation], [aria-hidden=true]')) continue;
    let block = a.parentElement;
    while (block && getComputedStyle(block).display.startsWith('inline')) block = block.parentElement;
    if (!block) continue;
    // text of the block outside links and controls: is the link part of a sentence?
    let around = '';
    const walk = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode())
      if (!n.parentElement.closest('a, button, [role=button], select, label') && !n.parentElement.closest('[aria-hidden=true]')) around += n.textContent;
    if ((around.match(/[\\p{L}\\p{N}]/gu) || []).length < 3) continue;
    a.setAttribute('data-a11y-link', String(i++));
    out.push({ i: a.getAttribute('data-a11y-link'), desc: describeEl(a),
               ratio: ratio(parse(s.color), parse(getComputedStyle(block).color)) });
  }
  return out;
}
"""
)

UNDERLINED_JS = """
(i) => {
  const a = document.querySelector(`[data-a11y-link="${i}"]`);
  const marked = el => { const s = getComputedStyle(el);
    return s.textDecorationLine.includes('underline') ||
      (parseFloat(s.borderBottomWidth) >= 1 && s.borderBottomStyle !== 'none' && !/rgba\\(.*, 0\\)$/.test(s.borderBottomColor)) ||
      /gradient|url\\(/.test(s.backgroundImage); };
  if (marked(a) || [...a.querySelectorAll('*')].some(marked)) return true;
  // text-decoration drawn by an inline ancestor reaches the link too
  for (let p = a.parentElement; p && getComputedStyle(p).display.startsWith('inline'); p = p.parentElement)
    if (getComputedStyle(p).textDecorationLine.includes('underline')) return true;
  return false;
}
"""


@pytest.mark.bitv("9.1.4.1")
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_links_in_text_not_by_colour_alone(open_page, page_id: str, theme: str) -> None:
    """9.1.4.1 Use of colour: a link inside running text is underlined (or
    otherwise marked), or has 3:1 contrast to the surrounding text and gets
    an underline on hover and on keyboard focus."""
    page = open_page(PAGES[page_id], "en", theme)
    expand_all(page)
    page.add_style_tag(content=NO_TRANSITIONS_CSS)
    issues: list[str] = []
    for link in page.evaluate(INLINE_LINKS_JS):
        if page.evaluate(UNDERLINED_JS, link["i"]):
            continue
        if link["ratio"] < 3:
            issues.append(
                f"link in text is not underlined and its colour has {link['ratio']:.2f}:1 < 3:1 to the text: {link['desc']}"
            )
            continue
        loc = page.locator(f'[data-a11y-link="{link["i"]}"]')
        loc.hover()
        hover = page.evaluate(UNDERLINED_JS, link["i"])
        page.mouse.move(0, 0)
        loc.focus()
        focus = page.evaluate(UNDERLINED_JS, link["i"])
        loc.blur()
        if not (hover and focus):
            missing = " and ".join(x for x, ok in (("hover", hover), ("focus", focus)) if not ok)
            issues.append(f"link in text is told apart by colour only, no underline on {missing}: {link['desc']}")
    assert_no_issues(issues, f"{page_id} [en, {theme}]", "use-of-colour")
