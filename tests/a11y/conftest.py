"""Fixtures for the accessibility suite; the machinery lives in harness.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="a11y tests need playwright (pip install -e '.[a11y]')")

from tests.a11y.harness import _fresh_results, base_url, browser, open_page  # noqa: E402,F401
from tests.a11y.pages import PAGES_ENV, pages_of_test, parse_pages, selected  # noqa: E402

_HERE = Path(__file__).resolve().parent


# The longest tests (25-70 s each: they hover and focus every control in
# turn). Collected first, so a parallel run (pytest -n) starts them early
# instead of leaving one worker busy with them after the others are done.
SLOW_FIRST = ("test_content_on_hover_or_focus", "test_no_character_key_shortcuts", "test_pointer_cancellation")


# ZING_A11Y_PAGES="history,kb" runs only the tests of those pages (ids of
# tests/a11y/pages.py PAGES, or "all"); applied before the sharding below.
# ZING_A11Y_SHARD="k/n" runs the k-th of n equal parts of the suite (CI runs
# the parts as parallel jobs; tests.a11y.conformance merges their results).
SHARD_ENV = "ZING_A11Y_SHARD"


def _shard() -> tuple[int, int] | None:
    raw = os.environ.get(SHARD_ENV, "").strip()
    if not raw:
        return None
    try:
        k, n = (int(x) for x in raw.split("/"))
    except ValueError:
        raise pytest.UsageError(f"{SHARD_ENV} must look like 2/4, not {raw!r}") from None
    if not 1 <= k <= n:
        raise pytest.UsageError(f"{SHARD_ENV}={raw!r}: the shard number must be between 1 and {n}")
    return k, n


def _pages() -> frozenset[str] | None:
    try:
        return parse_pages(os.environ.get(PAGES_ENV, ""))
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from None


def _deselect(config: pytest.Config, items: list[pytest.Item], drop: set[int]) -> None:
    if drop:
        config.hook.pytest_deselected(items=[item for item in items if id(item) in drop])
        items[:] = [item for item in items if id(item) not in drop]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if _HERE in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.a11y)
    # stable: everything else keeps its order
    items.sort(key=lambda item: getattr(item, "originalname", "") not in SLOW_FIRST)
    a11y = [item for item in items if _HERE in Path(str(item.fspath)).resolve().parents]
    # ZING_A11Y_PAGES: only the tests of the chosen pages (tests/a11y/pages.py);
    # tests tied to no page (cross-page checks) always run
    chosen = _pages()
    if chosen is not None:
        drop = set()
        for item in a11y:
            spec = getattr(item, "callspec", None)
            name = getattr(item, "originalname", None) or item.name
            on = pages_of_test(Path(str(item.fspath)).name, name, spec.params if spec else {})
            if not selected(on, chosen):
                drop.add(id(item))
        _deselect(config, items, drop)
        a11y = [item for item in a11y if id(item) not in drop]
    shard = _shard()
    if shard is None:
        return
    k, n = shard
    # dealt round-robin after the sort above, so every shard gets its share of
    # the slow tests; only a11y tests are split, anything else runs everywhere
    _deselect(config, items, {id(item) for i, item in enumerate(a11y) if i % n != k - 1})
