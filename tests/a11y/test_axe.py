"""axe-core rule checks (WCAG 2.1 A/AA = EN 301 549 ch. 9 = BITV 2.0) on every v2 page.

Each page is checked in every UI language and in both themes, as loaded and with
every disclosure opened (rendered report, advanced options, monitor details),
and every tab panel is checked on its own.
"""

from __future__ import annotations

import pytest

from tests.a11y.harness import (
    LANGS,
    PAGES,
    THEMES,
    WCAG_TAGS,
    assert_no_violations,
    expand_all,
    run_axe,
    settle,
    show_tab,
    tab_states,
)

PAGE_IDS = list(PAGES)

# BITV steps the enabled axe 4.13 rules tagged wcag2a/wcag2aa/wcag21a/wcag21aa
# decide (time-based media and audio are n/a here). Each step's outcome comes
# from its own rules (tests/a11y/results.py), not from the whole test.
AXE_WCAG_STEPS = (
    "9.1.1.1", "9.1.3.1", "9.1.3.5", "9.1.4.1", "9.1.4.3", "9.1.4.4", "9.1.4.12",
    "9.2.1.1", "9.2.2.1", "9.2.2.2", "9.2.4.1", "9.2.4.2", "9.2.4.4",
    "9.3.1.1", "9.3.1.2", "9.3.3.2", "9.4.1.2",
)


@pytest.mark.bitv(*AXE_WCAG_STEPS, axe=True)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_wcag_rules_as_loaded(open_page, page_id: str, lang: str, theme: str) -> None:
    page = open_page(PAGES[page_id], lang, theme)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"{page_id} [{lang}, {theme}] as loaded")


@pytest.mark.bitv(*AXE_WCAG_STEPS, axe=True)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_wcag_rules_expanded(open_page, page_id: str, lang: str, theme: str) -> None:
    page = open_page(PAGES[page_id], lang, theme)
    expand_all(page)
    assert_no_violations(run_axe(page, WCAG_TAGS), f"{page_id} [{lang}, {theme}] with disclosures open")


@pytest.mark.bitv(*AXE_WCAG_STEPS, axe=True)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_wcag_rules_every_tab_panel(open_page, page_id: str, theme: str) -> None:
    page = open_page(PAGES[page_id], "en", theme)
    found = []
    for sel in tab_states(page):
        show_tab(page, sel)
        settle(page)
        found += [dict(v, id=f"{v['id']} (tab {sel})") for v in run_axe(page, WCAG_TAGS)]
    assert_no_violations(found, f"{page_id} [en, {theme}] each tab panel")


@pytest.mark.bitv("9.1.3.1", "9.2.4.1", "9.2.4.3", "9.2.4.6", axe=True)
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_best_practices(open_page, page_id: str, lang: str) -> None:
    """axe best-practice rules (landmarks, heading order, …): not a WCAG criterion
    on their own, but they back 1.3.1 / 2.4.1 / 2.4.6 in a BITV review."""
    page = open_page(PAGES[page_id], lang, "light")
    expand_all(page)
    assert_no_violations(run_axe(page, ["best-practice"]), f"{page_id} [{lang}] best practices", "axe-best-practice")
