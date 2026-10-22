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
    assert_no_issues,
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


# The audit page's endpoint type (surface): every state of the form passes axe
# and keeps its structure. Fields a surface does not use are hidden with their
# labels and hints (no orphaned label or description), the selector is a named
# radio group and the first stop of the form.
SURFACE_STATE_JS = """
() => {
  const shown = (el) => !!el && el.checkVisibility();
  const out = { issues: [] };
  const form = document.getElementById("form");
  const group = form.querySelector("fieldset");
  const radios = [...group.querySelectorAll('input[type="radio"]')];
  out.checked = (radios.find((r) => r.checked) || {}).value || null;
  out.legend = (group.querySelector("legend") || {}).textContent || "";
  out.names = radios.map((r) => (r.labels[0] || {}).textContent.trim());
  out.first = form.querySelector("input, select, textarea, button") === radios[0];
  out.groups = Object.fromEntries(["api-grp", "pmode-grp", "bapi-grp", "edims-grp"]
    .map((id) => [id, shown(document.getElementById(id))]));
  out.dims = [...document.querySelectorAll("#dims button")].filter(shown).map((b) => b.dataset.v);
  for (const label of form.querySelectorAll("label[for]")) {
    // the model pickers swap a text input for a select in place: a label
    // is orphaned only when its whole field group is hidden
    const ctl = document.getElementById(label.htmlFor);
    if (shown(label) && !shown(ctl) && !shown(ctl && ctl.closest(".grp"))) out.issues.push(`orphaned label for #${label.htmlFor}`);
    if (shown(ctl) && !shown(label)) out.issues.push(`#${label.htmlFor} is shown, its label is hidden`);
  }
  for (const el of form.querySelectorAll("[aria-describedby], [aria-labelledby]")) {
    if (!shown(el)) continue;
    for (const attr of ["aria-describedby", "aria-labelledby"]) {
      for (const id of (el.getAttribute(attr) || "").split(/\\s+/).filter(Boolean)) {
        const ref = document.getElementById(id);
        // a hint may be empty (nothing to say), but never sit in a hidden group
        if (!ref || ref.closest("[hidden]")) out.issues.push(`#${el.id || el.tagName} ${attr} -> hidden #${id}`);
      }
    }
  }
  return out;
}
"""

# The custom suite's dimensions on the embedding and rerank surfaces (zing/scoring.py).
SURFACE_DIMS = ["model_identity", "capability", "connectivity", "reliability", "performance"]


@pytest.mark.bitv(*AXE_WCAG_STEPS, axe=True)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("surface", ["chat", "embedding", "rerank"])
@pytest.mark.parametrize("page_id", ["audit"])
def test_audit_surface_states(open_page, page_id: str, surface: str, theme: str) -> None:
    page = open_page(f"{PAGES[page_id]}?surface={surface}", "en", theme)
    page.click('#suite button[data-v="custom"]')  # the custom suite's dimensions too
    page.mouse.move(0, 0)
    expand_all(page)
    settle(page)
    where = f"{page_id} ?surface={surface} [en, {theme}]"
    assert_no_violations(run_axe(page, WCAG_TAGS), where)
    st = page.evaluate(SURFACE_STATE_JS)
    issues = list(st["issues"])
    if st["checked"] != surface:
        issues.append(f"?surface={surface} preselects {st['checked']!r}")
    if not st["legend"].strip() or not all(st["names"]):
        issues.append(f"radio group without a legend or option names: {st['legend']!r} {st['names']}")
    if not st["first"]:
        issues.append("the endpoint type is not the first field of the form")
    chat = surface == "chat"
    want = {"api-grp": chat, "pmode-grp": chat, "bapi-grp": chat, "edims-grp": surface == "embedding"}
    if st["groups"] != want:
        issues.append(f"shown field groups {st['groups']}, want {want}")
    if not chat and st["dims"] != SURFACE_DIMS:
        issues.append(f"custom dimensions shown {st['dims']}, want {SURFACE_DIMS}")
    if chat and len(st["dims"]) != 10:
        issues.append(f"chat shows {len(st['dims'])} custom dimensions, want all 10")
    assert_no_issues(issues, where, "surface-states")
