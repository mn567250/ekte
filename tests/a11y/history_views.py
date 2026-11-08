"""A History server of its own for the History view tests
(test_history_controls.py, test_history_paging.py): the report fixture plus
seed.seed_history_views (two small groups, one group of 45 runs and 2,000 runs
of scripts/bench_fixture.py), served by the real endpoints, so sorting,
grouping and paging are the server's. Tests pick their runs by URL filters.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.a11y.harness import DESKTOP, settle


@pytest.fixture(scope="session")
def history_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    from tests.a11y.ekte_proc import EkteProc

    with EkteProc(tmp_path_factory.mktemp("ekte-history"), seed="seed_history_views") as z:
        yield z.url


def open_history(open_page: Any, base: str, query: str = "", theme: str = "light",
                 viewport: dict[str, int] | None = None, storage: str = "") -> Page:
    """``/history?<query>`` of ``base`` in a fresh context (English, ``theme``,
    empty storage; ``storage``: more init script run once)."""
    ctx = open_page.browser.new_context(viewport=viewport or DESKTOP, color_scheme="dark" if theme == "dark" else "light")
    open_page.contexts.append(ctx)
    ctx.add_init_script(
        "try { if (!sessionStorage.getItem('a11y.init')) { sessionStorage.setItem('a11y.init', '1');"
        " localStorage.clear(); localStorage.setItem('ekte.lang', 'en');"
        f" localStorage.setItem('ekte.v2.theme', {json.dumps(theme)}); {storage} }} }} catch (e) {{}}"
    )
    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    page = ctx.new_page()
    page.goto(base + "/history" + ("?" + query if query else ""), wait_until="networkidle")
    settle(page)
    return page
