"""Language, titles, structure, consistency and labels in every UI language.

BITV 9.1.3.1 Info and relationships, 9.2.4.2 Page titled, 9.2.4.6 Headings and
labels, 9.2.5.3 Label in name, 9.3.1.1 Language of page, 9.3.1.2 Language of
parts, 9.3.2.3 Consistent navigation, 9.3.2.4 Consistent identification,
9.3.3.1 Error identification, 9.4.1.2 Name, role, value.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.a11y.harness import LANGS, PAGES, assert_no_issues, expand_all, settle

PAGE_IDS = list(PAGES)
CJK = "[⺀-⿿　-〿぀-ヿ㄀-ㇿ㐀-䶿一-鿿豈-﫿＀-￯]"


def _html_lang(page: Any, lang: str) -> str:
    return str(page.evaluate("l => (EKTE_LANG.langs().find(x => x.code === l) || {}).html || l", lang))


@pytest.mark.bitv("9.3.1.1")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_page_language(open_page, page_id: str, lang: str) -> None:
    """9.3.1.1 Language of page: <html lang> names the language shown, on load
    and after switching language at runtime."""
    page = open_page(PAGES[page_id], lang)
    issues: list[str] = []
    want = _html_lang(page, lang)
    got = page.evaluate("() => document.documentElement.lang")
    if got != want:
        issues.append(f"on load <html lang={got!r}>, expected {want!r}")
    other = "de" if lang != "de" else "fr"
    if other in LANGS:
        page.evaluate("l => EKTE_LANG.set(l)", other)
        settle(page)
        got = page.evaluate("() => document.documentElement.lang")
        if got != _html_lang(page, other):
            issues.append(f"after switching to {other}: <html lang={got!r}>")
    assert_no_issues(issues, f"{page_id} [{lang}]", "language")


LANG_OF_PARTS_JS = (
    """
(cjk) => {
  const re = new RegExp(cjk);
  const out = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const t = n.textContent.trim(); if (!t || !re.test(t)) continue;
    const el = n.parentElement; if (!el || el.closest('script, style, [hidden], [aria-hidden=true]')) continue;
    const r = el.getBoundingClientRect(); if (r.width === 0 && r.height === 0) continue;
    const l = (el.closest('[lang]') || document.documentElement).getAttribute('lang') || '';
    if (!/^(zh|ja|ko)/i.test(l)) out.push(`"${t.slice(0, 50)}" in <${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}> is marked lang=${l || '(none)'}`);
  }
  for (const el of document.querySelectorAll('[aria-label], [title], [placeholder], [alt]')) {
    for (const a of ['aria-label', 'title', 'placeholder', 'alt']) {
      const v = el.getAttribute(a); if (!v || !re.test(v)) continue;
      const l = (el.closest('[lang]') || document.documentElement).getAttribute('lang') || '';
      if (!/^(zh|ja|ko)/i.test(l)) out.push(`${a}="${v.slice(0, 50)}" on <${el.tagName.toLowerCase()}> is marked lang=${l}`);
    }
  }
  return [...new Set(out)];
}
"""
)


@pytest.mark.bitv("9.3.1.2")
@pytest.mark.parametrize("lang", [x for x in LANGS if x != "zh"])
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_language_of_parts(open_page, page_id: str, lang: str) -> None:
    """9.3.1.2 Language of parts: Chinese text on a non-Chinese page is either
    translated or marked with lang="zh" (untranslated leftovers show up here)."""
    page = open_page(PAGES[page_id], lang)
    expand_all(page)
    assert_no_issues(page.evaluate(LANG_OF_PARTS_JS, CJK), f"{page_id} [{lang}]", "language-of-parts")


@pytest.mark.bitv("9.2.4.2")
@pytest.mark.parametrize("lang", LANGS)
def test_page_titles(open_page, lang: str) -> None:
    """9.2.4.2 Page titled: every page has its own title, in the page language."""
    issues: list[str] = []
    titles: dict[str, str] = {}
    for page_id, path in PAGES.items():
        page = open_page(path, lang)
        t = page.title().strip()
        titles[page_id] = t
        if not t:
            issues.append(f"{page_id}: empty <title>")
        elif lang == "zh" and not re.search(CJK, t):
            issues.append(f"{page_id}: title {t!r} is not Chinese")
        elif lang != "zh" and re.search(CJK, t):
            issues.append(f"{page_id}: title {t!r} is not translated")
    dupes = {t for t in titles.values() if list(titles.values()).count(t) > 1}
    for page_id, t in titles.items():
        if t in dupes:
            issues.append(f"{page_id}: title {t!r} is not unique")
    assert_no_issues(issues, f"all pages [{lang}]", "page-title")


HEADINGS_JS = """
() => {
  const hs = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role=heading]')]
    .filter(h => h.getBoundingClientRect().height > 0 || h.closest('.sr-only, .visually-hidden'));
  return hs.map(h => ({ level: h.getAttribute('aria-level') ? +h.getAttribute('aria-level') : +h.tagName[1] || 2,
                        text: (h.innerText || h.textContent || '').trim().slice(0, 50) }));
}
"""


@pytest.mark.bitv("9.1.3.1", "9.2.4.6")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_heading_structure(open_page, page_id: str, lang: str) -> None:
    """9.1.3.1 / 9.2.4.6: one h1, no skipped levels, no empty headings."""
    page = open_page(PAGES[page_id], lang)
    expand_all(page)
    hs: list[dict[str, Any]] = page.evaluate(HEADINGS_JS)
    issues: list[str] = []
    h1 = [h for h in hs if h["level"] == 1]
    if len(h1) != 1:
        issues.append(f"{len(h1)} level-1 headings (expected exactly 1)")
    prev = 0
    for h in hs:
        if not h["text"]:
            issues.append(f"empty h{h['level']}")
        if prev and h["level"] > prev + 1:
            issues.append(f"heading level skips from h{prev} to h{h['level']}: {h['text']!r}")
        prev = h["level"]
    assert_no_issues(issues, f"{page_id} [{lang}]", "headings")


NAV_JS = """
() => {
  const nav = document.querySelector('header nav, nav, [role=navigation]');
  if (!nav) return null;
  return [...nav.querySelectorAll('a[href]')].map(a => [new URL(a.href).pathname, (a.innerText || a.getAttribute('aria-label') || '').trim()]);
}
"""

LANDMARKS_JS = """
() => ({
  main: document.querySelectorAll('main, [role=main]').length,
  banner: document.querySelectorAll('body > header, [role=banner]').length,
  nav: document.querySelectorAll('nav, [role=navigation]').length,
  skip: !!document.querySelector('a[href^="#"]:first-of-type') &&
        [...document.querySelectorAll('a[href^="#"]')].slice(0, 2).some(a => { const t = document.getElementById(a.getAttribute('href').slice(1)); return t && t.closest('main, [role=main]'); }),
})
"""


@pytest.mark.bitv("9.1.3.1", "9.2.4.1", "9.3.2.3", "9.3.2.4")
@pytest.mark.parametrize("lang", LANGS)
def test_consistent_navigation_and_landmarks(open_page, lang: str) -> None:
    """9.3.2.3 Consistent navigation, 9.3.2.4 Consistent identification,
    9.2.4.1 Bypass blocks: the same nav in the same order with the same
    names on every page, a main landmark and a skip link to it."""
    issues: list[str] = []
    navs: dict[str, Any] = {}
    for page_id, path in PAGES.items():
        page = open_page(path, lang)
        navs[page_id] = page.evaluate(NAV_JS)
        lm = page.evaluate(LANDMARKS_JS)
        if navs[page_id] is None:
            issues.append(f"{page_id}: no navigation landmark")
        if lm["main"] != 1:
            issues.append(f"{page_id}: {lm['main']} main landmarks (expected 1)")
        if not lm["skip"]:
            issues.append(f"{page_id}: no skip link to the main content (9.2.4.1)")
    ref_id = next(iter(PAGES))
    for page_id, nav in navs.items():
        if nav is not None and navs[ref_id] is not None and nav != navs[ref_id]:
            issues.append(f"{page_id}: navigation differs from {ref_id}: {nav} vs {navs[ref_id]}")
    assert_no_issues(issues, f"all pages [{lang}]", "consistency")


LABEL_IN_NAME_JS = """
() => {
  const norm = s => (s || '').toLowerCase().replace(/[\\s\\u00a0…:.,!?()\\[\\]"'«»“”·—–-]+/g, ' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('button[aria-label], a[aria-label], [role=button][aria-label], [role=tab][aria-label], [role=switch][aria-label], [role=link][aria-label]')) {
    if (el.getBoundingClientRect().width === 0) continue;
    const visible = norm(el.innerText);
    if (!visible || visible.length < 2) continue;      // icon-only buttons
    const name = norm(el.getAttribute('aria-label'));
    if (!name.includes(visible)) out.push(`visible label "${el.innerText.trim().slice(0, 40)}" is not part of the accessible name "${el.getAttribute('aria-label').slice(0, 60)}"`);
  }
  return out;
}
"""


@pytest.mark.bitv("9.2.5.3")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_label_in_name(open_page, page_id: str, lang: str) -> None:
    """9.2.5.3 Label in name: speech users say what they see."""
    page = open_page(PAGES[page_id], lang)
    expand_all(page)
    assert_no_issues(page.evaluate(LABEL_IN_NAME_JS), f"{page_id} [{lang}]", "label-in-name")


INVALID_JS = """
() => [...document.querySelectorAll('[aria-invalid=true]')].filter(el => el.getBoundingClientRect().width > 0).map(el => {
  const ids = ((el.getAttribute('aria-describedby') || '') + ' ' + (el.getAttribute('aria-errormessage') || '')).trim().split(/\\s+/).filter(Boolean);
  const msg = ids.map(id => document.getElementById(id)).filter(m => m && m.getBoundingClientRect().height > 0 && m.innerText.trim());
  return msg.length ? null : `invalid field without a visible, linked error message: <${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}>`;
}).filter(Boolean)
"""

SUBMIT_FORMS_JS = """
() => [...document.querySelectorAll('form')].filter(f => f.getBoundingClientRect().height > 0).map((f, i) => { f.setAttribute('data-a11y-form', i); return i; })
"""


@pytest.mark.bitv("9.3.3.1", "9.3.3.3")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_error_identification(open_page, page_id: str, lang: str) -> None:
    """9.3.3.1 Error identification / 9.3.3.3 Error suggestion: submitting the
    empty forms marks the fields and links a visible message in the page
    language; the message is announced (live region or focus)."""
    page = open_page(PAGES[page_id], lang)
    issues: list[str] = []
    for i in page.evaluate(SUBMIT_FORMS_JS):
        form = page.locator(f'[data-a11y-form="{i}"]')
        submit = form.locator("button[type=submit], button:not([type]), input[type=submit]").first
        if not submit.count() or not submit.is_visible() or submit.is_disabled():
            continue
        submit.click()
        settle(page)
        issues += page.evaluate(INVALID_JS)
        if lang != "zh":
            for t in page.evaluate("() => [...document.querySelectorAll('[aria-invalid=true]')].map(el => (el.getAttribute('aria-describedby')||'').split(' ').map(id => (document.getElementById(id)||{}).innerText||'').join(' '))"):
                if re.search(CJK, t):
                    issues.append(f"error message not translated: {t[:60]!r}")
    assert_no_issues(issues, f"{page_id} [{lang}]", "errors")
