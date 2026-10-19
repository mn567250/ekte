"""Which web UI v2 pages the a11y suite tests, and which of them a change affects.

Standard library only: the CI scope job (``python -m tests.a11y.affected``)
and the unit tests import it without Playwright.

Three tables live here, and only here:

- :data:`PAGES`: page id -> URL path of every page the suite tests
  (``harness.PAGES`` is this dict).
- :data:`TEST_PAGES`: tests that open a fixed page without a ``page_id``
  parameter (the History-only files, the flows), so ``ZING_A11Y_PAGES`` can
  deselect them. Tests parametrised by ``page_id`` (or by a ``state`` such as
  ``history-charts``) need no entry; tests that cover every page at once
  (consistent navigation, page titles, …) have none on purpose and always run.
- :data:`RULES`: changed file -> pages whose tests it can break.

A new page needs an entry in :data:`PAGES` and rules for its files in
:data:`RULES`; a new test that opens one fixed page needs an entry in
:data:`TEST_PAGES`. Anything under :data:`FAIL_SAFE` that no rule matches runs
the whole suite, so a forgotten rule costs CI time, never coverage.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache

PAGES: dict[str, str] = {
    "audit": "/v2/",
    "history": "/v2/history",
    "monitors": "/v2/watches",
    "tools": "/v2/tools",
    "kb": "/v2/kb",
    "analytics": "/v2/analytics",
    "accessibility": "/v2/accessibility",
}

# pytest selection (tests/a11y/conftest.py)
PAGES_ENV = "ZING_A11Y_PAGES"

# Tests without a page_id parameter that open one fixed page (or a few):
# "<file>" for a whole file, "<file>::<test>" for one test.
TEST_PAGES: dict[str, tuple[str, ...]] = {
    "test_history_controls.py": ("history",),
    "test_analytics_view.py": ("analytics",),
    "test_history_paging.py": ("history",),
    "test_flows.py::test_audit_flow": ("audit",),
    "test_flows.py::test_failing_audit_flow": ("audit",),
    "test_flows.py::test_monitor_flow": ("history", "monitors"),  # starts on History
    "test_flows.py::test_tools_flow": ("tools",),
    "test_flows.py::test_kb_flow": ("kb",),
    "test_structure.py::test_report_states_not_by_colour_alone": ("history",),
    "test_structure.py::test_list_states_not_by_colour_alone": ("history", "monitors"),
    "test_structure.py::test_tool_result_states_not_by_colour_alone": ("tools",),
}


def parse_pages(raw: str) -> frozenset[str] | None:
    """``ZING_A11Y_PAGES`` -> the selected page ids; None = no selection (all).

    Accepts a comma list of :data:`PAGES` ids, or ``all``; empty means all.
    Raises ValueError for an unknown id."""
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    if not ids or "all" in ids:
        return None
    unknown = sorted(set(ids) - set(PAGES))
    if unknown:
        raise ValueError(f"{PAGES_ENV}: unknown page id(s) {', '.join(unknown)}; known: all, {', '.join(PAGES)}")
    return frozenset(ids)


def pages_of_test(file: str, name: str, params: Mapping[str, object]) -> frozenset[str] | None:
    """The pages one collected test opens; None = not tied to a page (always runs).

    ``file`` is the test file's name, ``name`` the test function's name (without
    the parameter suffix), ``params`` its ``callspec.params``."""
    fixed = TEST_PAGES.get(f"{file}::{name}") or TEST_PAGES.get(file)
    if fixed:
        return frozenset(fixed)
    page = params.get("page_id")
    if isinstance(page, str) and page in PAGES:
        return frozenset({page})
    state = params.get("state")
    if isinstance(state, str):
        # test_time_media.py: "<page>", "<page>+expanded", "<page>-<app state>"
        head = state.split("+", 1)[0]
        if head not in PAGES:
            head = head.split("-", 1)[0]
        if head in PAGES:
            return frozenset({head})
    return None


def selected(pages: frozenset[str] | None, chosen: frozenset[str] | None) -> bool:
    """Does a test on ``pages`` run when ``chosen`` pages are selected?"""
    return chosen is None or pages is None or bool(pages & chosen)


# --------------------------------------------------------------------------- #
# changed files -> affected pages
# --------------------------------------------------------------------------- #
ALL = ("*",)  # every page
NONE: tuple[str, ...] = ()  # no page: the change cannot affect the UI

# Rules are tried in order; the FIRST matching pattern decides. Patterns are
# repository-relative globs: * stays within a path segment, ** spans segments.
_V2 = "zing/web/static/v2/"
_ST = "zing/web/static/"
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # -- web UI v2 pages and the assets each loads (<script>/<link> tags) --
    (_V2 + "index.html", ("audit",)),
    (_V2 + "history.html", ("history",)),
    (_V2 + "watches.html", ("monitors",)),
    (_V2 + "tools.html", ("tools",)),
    (_V2 + "kb.html", ("kb",)),
    (_V2 + "kbsection.js", ("kb",)),
    (_V2 + "kbview.js", ("kb",)),
    (_V2 + "analytics.html", ("analytics",)),
    (_V2 + "charts.js", ("analytics",)),
    (_V2 + "charts.css", ("analytics",)),
    (_V2 + "chartmotion.js", ("audit", "history", "analytics")),
    (_V2 + "chartmotion.css", ("audit", "history", "analytics")),
    (_V2 + "filterpanel.js", ("history", "analytics")),
    (_V2 + "filterpanel.css", ("history", "analytics")),
    (_V2 + "accessibility.html", ("accessibility",)),
    # the page fetches bitv-report.json; the catalogue is what it is built from
    (_V2 + "bitv-*.json", ("accessibility",)),
    (_V2 + "dimpick.js", ("audit",)),
    (_V2 + "relaycfg.js", ("audit", "tools")),
    (_V2 + "report.js", ("audit", "history")),
    (_V2 + "report.css", ("audit", "history")),
    (_V2 + "perf.css", ("audit", "history")),
    (_V2 + "masterkey.js", ("monitors",)),
    (_V2 + "tabs.js", ("tools", "kb", "analytics", "audit", "monitors")),
    (_V2 + "jobs.js", ("audit", "monitors")),
    (_V2 + "jobs.css", ("audit", "monitors")),
    (_V2 + "fields.css", ("audit", "kb", "monitors", "tools")),
    (_V2 + "nav.js", ALL),
    (_V2 + "theme.js", ALL),
    (_V2 + "tokens.css", ALL),
    (_V2 + "zing.css", ALL),
    # -- assets shared with the classic UI (zing/web/static/*.js) --
    (_ST + "perf.js", ("audit", "history")),
    (_ST + "secretfield.js", ("audit", "monitors", "tools")),
    (_ST + "i18n.js", ALL),
    (_ST + "icons.js", ALL),
    (_ST + "lang.js", ALL),
    (_ST + "locales.js", ALL),
    # classic UI only: no v2 page loads these
    (_ST + "modelpicker.js", NONE),
    (_ST + "console.html", NONE),
    (_ST + "index.html", NONE),
    (_ST + "history.html", NONE),
    (_ST + "tools.html", NONE),
    (_ST + "watches.html", NONE),
    # -- server side --
    (
        "zing/web/history.py",
        ("audit", "history", "monitors", "analytics"),
    ),  # report view, history list, monitor from history, the analytics queries
    ("zing/web/analytics.py", ("analytics",)),  # the /api/analytics/* endpoints
    ("zing/web/analytics_store.py", ("analytics",)),
    ("zing/web/jobs.py", ("audit", "monitors")),  # running audits (the Running tabs)
    ("zing/web/watches.py", ("history", "monitors")),  # "schedule as monitor" on History
    ("zing/web/masterkey.py", ("monitors",)),
    ("zing/web/*.py", ALL),  # server, security, caching, __init__: every page
    # the knowledge base: the Knowledge page lists it, the relay configuration
    # of the audit and tools pages picks providers and models from it
    ("zing/knowledge/**", ("audit", "kb", "tools")),
    # -- the audit pipeline: the audit flow (test_flows.py) runs a real audit
    # against a fake relay and renders its report; the report export is on
    # the audit and History pages. tests/test_a11y_pages.py checks that every
    # module the server and the runner import has a rule here --
    ("zing/report/**", ("audit", "history")),
    ("zing/detectors/**", ("audit",)),
    ("zing/clients/**", ("audit",)),
    ("zing/judge/**", ("audit",)),
    ("zing/perf/**", ("audit",)),
    ("zing/prompts/**", ("audit",)),
    ("zing/utils/**", ("audit",)),
    ("zing/runner.py", ("audit",)),
    ("zing/scoring.py", ("audit",)),
    ("zing/config.py", ("audit",)),
    ("zing/context.py", ("audit",)),
    ("zing/models.py", ("audit",)),
    ("zing/embed_audit.py", ("tools",)),  # the embedding check on the tools page
    ("zing/notify.py", ("monitors",)),  # monitor webhooks
    ("zing/secretbox.py", ("monitors",)),  # the monitors' stored keys
    ("zing/datadir.py", ("audit", "history", "monitors")),  # where history and monitors live
    ("zing/__init__.py", ALL),  # imported by the server (version)
    # -- UI strings: fragments are merged into one table per language and
    # re-declare shared keys ("Cancel", "API key", …), so a fragment can change
    # any page; only fragments whose keys are used by known pages alone are
    # narrowed (tests/test_a11y_pages.py checks this against the sources) --
    ("zing/i18n/locales/fragments/v2-form-errors/*", ("audit",)),
    ("zing/i18n/locales/fragments/v2-all-dimensions/*", ("audit", "history")),
    ("zing/i18n/locales/fragments/v2-download/*", ("audit", "history")),
    ("zing/i18n/locales/fragments/v2-exec-log/*", ("audit", "history")),
    ("zing/i18n/locales/fragments/v2-scoring/*", ("audit", "history", "analytics")),
    # v2-analytics also holds the navigation label "Analytics", shown on every page
    ("zing/i18n/**", ALL),
    # -- the suite itself --
    ("tests/a11y/README.md", NONE),
    ("tests/a11y/llm_review.py", NONE),  # advisory review, not part of the suite
    ("tests/a11y/test_history_*.py", ("history",)),
    ("tests/a11y/test_analytics_*.py", ("analytics",)),
    ("tests/a11y/filter_panel.py", ("history", "analytics")),  # the filter panel check both use
    # the runs every a11y server is seeded with (History, Monitors, Analytics, …)
    ("tests/a11y/seed.py", ALL),
    *((f"tests/a11y/snapshots/{p}-*.yml", (p,)) for p in PAGES),
    ("tests/a11y/**", ALL),  # harness, conftest, fixtures, other test files, vendor
    ("tests/fixtures/web_report.json", ALL),  # the report every a11y server is seeded with
    # -- how the suite is installed and run --
    (".github/workflows/ci.yml", ALL),
    ("pyproject.toml", ALL),
    ("uv.lock", ALL),
)

# A changed file under these prefixes that no rule matches runs everything.
FAIL_SAFE = ("zing/web/", "zing/i18n/", "tests/a11y/")


@cache
def _glob_re(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def match(path: str) -> tuple[str, ...] | None:
    """The pages of the first rule matching ``path`` (ALL, NONE or ids); None = no rule."""
    for pattern, pages in RULES:
        if _glob_re(pattern).match(path):
            return pages
    return None


@dataclass(frozen=True)
class Scope:
    pages: tuple[str, ...]  # in PAGES order
    full: bool  # every page: the complete suite (and a conformance report)
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"pages": list(self.pages), "full": self.full, "reason": self.reason}


def full_scope(reason: str) -> Scope:
    return Scope(tuple(PAGES), True, reason)


def affected(paths: Iterable[str]) -> Scope:
    """Changed repository paths -> the pages whose a11y tests must run."""
    chosen: set[str] = set()
    why: dict[tuple[str, ...], list[str]] = {}  # pages -> the files that select them
    files = sorted({p.strip().removeprefix("./") for p in paths if p.strip()})
    for path in files:
        pages = match(path)
        if pages is None:
            if path.startswith(FAIL_SAFE):
                return full_scope(f"{path} matches no rule in tests/a11y/pages.py (fail-safe: run everything)")
            continue
        if pages == ALL:
            return full_scope(f"{path} affects every page")
        if pages:
            chosen.update(pages)
            why.setdefault(tuple(p for p in PAGES if p in pages), []).append(path)
    if not chosen:
        return Scope((), False, "no changed file affects the web UI" if files else "no changed files")
    ordered = tuple(p for p in PAGES if p in chosen)
    if len(ordered) == len(PAGES):
        return full_scope("every page is affected")
    parts = []
    for ids, paths_ in why.items():
        more = f" (+{len(paths_) - 2} more)" if len(paths_) > 2 else ""
        parts.append(f"{', '.join(paths_[:2])}{more} -> {', '.join(ids)}")
    return Scope(ordered, False, "; ".join(parts))


# --------------------------------------------------------------------------- #
# CI jobs
# --------------------------------------------------------------------------- #
# Share of the full suite's test time per page, from a full local run's
# JUnit XML (1,299 tests, 4,465 s of test time; tests/a11y/README.md). Tests tied to no page (cross-page
# checks, self-checks) run in every selection and weigh in as "common".
WEIGHTS: dict[str, float] = {
    "audit": 0.12,
    "history": 0.24,
    "monitors": 0.09,
    "tools": 0.08,
    "kb": 0.23,
    "analytics": 0.10,
    "accessibility": 0.10,
    "common": 0.04,
}
FULL_JOBS = 4


def job_count(pages: Iterable[str], full_jobs: int = FULL_JOBS) -> int:
    """How many parallel jobs a selection gets: as many as keep each job's
    share near a full-run shard's, at least 1, at most ``full_jobs``."""
    share = WEIGHTS["common"] + sum(WEIGHTS.get(p, 1 / len(PAGES)) for p in set(pages))
    total = sum(WEIGHTS.values())
    # 15 % slack, so a selection just over a shard's size does not get a whole extra runner
    need = math.ceil(share * full_jobs / (total * 1.15))
    return max(1, min(full_jobs, need))


def matrix(scope: Scope, full_jobs: int = FULL_JOBS) -> list[dict[str, str]]:
    """GitHub Actions matrix entries {shard, pages} for an a11y run of ``scope``.

    Every job runs the same page selection and takes its round-robin share
    (``ZING_A11Y_SHARD=k/n``), which balances jobs better than splitting by
    page (one page can be a quarter of the suite)."""
    if not scope.pages:
        return []
    n = full_jobs if scope.full else job_count(scope.pages, full_jobs)
    pages = "all" if scope.full else ",".join(scope.pages)
    return [{"shard": f"{k}/{n}", "pages": pages} for k in range(1, n + 1)]
