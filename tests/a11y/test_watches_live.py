"""The Monitors page still shows a running monitor's progress once the live
state left ``GET /api/watches`` (#158): the page reads it from ``/api/jobs``
(job ``monitor-<id>``). The suite's server runs in this process, so the test
marks the seeded monitor as running in ``ekte.web.server._running_watches``,
exactly as a run does, and reads the card."""

from __future__ import annotations

import httpx

from ekte.web import server


def _seeded_monitor(base_url: str) -> dict:
    [watch] = httpx.get(base_url + "/api/watches", timeout=10).json()
    assert not {"running", "queued", "progress"} & set(watch)
    return watch


def test_watches_page_shows_progress_from_jobs(open_page, base_url) -> None:
    watch = _seeded_monitor(base_url)
    wid = int(watch["id"])
    state = {"name": watch["name"], "base_url": watch["base_url"], "model": watch["model"],
             "since": 0.0, "started": True, "total": 4, "done": 1}
    server._running_watches[wid] = state
    try:
        page = open_page("/watches")
        bar = page.locator('.mon-prog [role="progressbar"]').first
        bar.wait_for()
        assert bar.get_attribute("aria-valuenow") == "25"
        assert page.locator(".mon-prog b").first.inner_text() == "25%"
        assert "Running now" in page.locator(".mon").first.inner_text()
        # queued: waiting for its relay, the card says so
        state["started"] = False
        page.reload(wait_until="load")
        page.wait_for_function(
            "() => (document.querySelector('.mon') || {}).innerText.includes('Queued')")
    finally:
        server._running_watches.pop(wid, None)
    # finished: the next load shows no progress any more
    page.reload(wait_until="load")
    page.locator(".mon").first.wait_for()
    page.wait_for_function("() => !document.querySelector('.mon-prog')")
