"""End-to-end checks of the umbrella #150 (Definition of done), on the final code.

One test per checkbox, over one data directory that all three pages read:
runs of two monitors that share relay, model and suite, a manual run of the
same relay and model, and monitors in ``watches.db``. Where a browser test
already proves a checkbox, the test here checks the server's side of it and
names the browser test (``tests/a11y``, Playwright) in its docstring.

| Definition of done | Here | Browser / other tests |
|---|---|---|
| 1. sub-issues closed, final PR merged | ``test_dod_01`` (the consolidated CHANGELOG entry) | the final PR's CI |
| 2. one panel, the fields that apply, filters in the URL | ``test_dod_02`` | ``a11y/test_watches_page.py::test_relay_filter_is_in_the_url_and_the_request``, ``a11y/test_analytics_view.py::test_link_restores_tab_filters_and_view``, ``a11y/test_history_controls.py::test_copied_link_reproduces_the_view``, ``test_web_v2_filters_js.py::test_pages_hold_the_field_matrix`` |
| 3. every GET cached with an ETag, reload: 304 | ``test_dod_03`` | ``a11y/test_browser_cache.py`` (History, Analytics, Monitors) |
| 4. a day range keeps its ETag, an hour range is exact | ``test_dod_04`` | ``test_history_api.py`` / ``test_analytics_widgets.py::test_a_day_range_keeps_its_etag_all_day*`` |
| 5. 30d default, from local midnight | ``test_dod_05`` | ``a11y/test_history_controls.py::test_history_defaults_to_the_last_30_days`` |
| 6. a CLI run shows up live | ``test_dod_06`` | ``a11y/test_live_refresh.py::test_analytics_updates_in_place_and_keeps_focus``, ``::test_history_shows_new_runs_notice_once`` |
| 7. hidden tabs don't poll, no data polled on a timer | ``test_dod_07`` | ``a11y/test_live_refresh.py::test_hidden_tab_sends_no_version_requests``, ``::test_no_page_polls_data_on_a_timer``, ``test_web_v2_jobs_js.py`` |
| 8. monitor progress from the job event streams | ``test_dod_08`` | ``a11y/test_watches_page.py::test_running_monitor_follows_its_event_stream`` |
| 9. filters remembered across pages, per page with the toggle off, URL wins | ``test_dod_09`` | ``a11y/test_filter_memory.py``, ``a11y/test_watches_page.py::test_shared_memory_carries_relay_not_state`` |
| 10. ``watch=<id>``: exactly one monitor's runs | ``test_dod_10`` | ``test_history_api.py``, ``test_analytics_widgets.py`` (``watch``) |
| 11. links reproduce the filters, a monitor's History link focuses its run | ``test_dod_11`` | ``a11y/test_watches_page.py::test_monitor_links_open_their_targets``, ``a11y/test_history_controls.py::test_group_opens_in_analytics``, ``a11y/test_history_focus.py`` |
| 12. performance budget | ``test_dod_12`` (every component endpoint has a budget case) | ``EKTE_BENCH=1 pytest -m slow`` (see docs/dev/web-server.md#benchmark) |
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ekte.web import history, query
from tests.test_analytics import _report

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web.server import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "ekte" / "web" / "static" / "v2"
RELAY = "https://relay.example/v1"
OTHER = "https://other.example/v1"
NOW = datetime.now(UTC).replace(microsecond=0)


def _bench():
    from tests.test_query import _bench_module

    return _bench_module()


@pytest.fixture
def site(tmp_path, monkeypatch) -> dict[str, Any]:
    """Two monitors (ids 1, 2) on the same relay, model and suite, each with
    runs, a manual run of that relay and model, a run of another relay, and
    two monitors more in watches.db; the run ids by owner."""
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    history.init()
    _bench().build_watches(watches=4, relays=2)
    runs: dict[str, list[int]] = {"w1": [], "w2": [], "manual": [], "other": []}
    for k in range(3):
        runs["w1"].append(history.save(_report(NOW - timedelta(hours=2 + k)), watch_id=1))
    for k in range(2):
        runs["w2"].append(history.save(_report(NOW - timedelta(hours=8 + k)), watch_id=2))
    runs["manual"].append(history.save(_report(NOW - timedelta(hours=12))))
    runs["other"].append(history.save(_report(NOW - timedelta(hours=1), base_url=OTHER, model="model-b")))
    # one monitor run older than the default range
    runs["old"] = [history.save(_report(NOW - timedelta(days=40)), watch_id=1)]
    return {"dir": tmp_path, "runs": runs}


@pytest.fixture
def client(site):
    return TestClient(create_app(), base_url="http://localhost")


def _node(body: str) -> Any:
    from tests.test_web_v2_filters_js import run

    return run(body)


def _component_urls(client: TestClient, runs: dict[str, list[int]]) -> dict[str, list[str]]:
    """Every GET a component of the three pages makes, as the pages make it
    (the shared filters, the page's default range, the viewer's tz)."""
    tz = "&tz=Europe%2FBerlin"
    shared = "range=30d" + tz
    key = client.get("/api/history/groups?trend.metrics=score&" + shared).json()["groups"][0]["key"]
    rid = runs["w1"][0]
    return {
        "history": [
            "/api/metrics", "/api/history/status", "/api/filters/options?" + shared,
            "/api/history/groups?trend.metrics=score&" + shared,
            "/api/history/groups?groups.limit=1&trend.metrics=score&" + shared,  # the new-runs count
            "/api/history/runs?group.key=" + key + "&" + shared,
            f"/api/history/{rid}", f"/api/history/{rid}?trend=1",
        ],
        "analytics": [
            "/api/metrics", "/api/history/status", "/api/filters/options?" + shared,
            *(f"/api/analytics/{w}?{shared}" for w in ("summary", "series", "heatmap", "leaderboard",
                                                         "errors", "integrity")),
            "/api/analytics/breakdown?breakdown.metric=relay_overhead&" + shared,
        ],
        "watches": ["/api/watches?" + tz[1:], "/api/watches/options?" + tz[1:],
                    "/api/watches?relay=relay-00.example&state=active" + tz],
        "every page": ["/api/version"],
    }


def _freeze(monkeypatch, clock: list[datetime]) -> None:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0]

    monkeypatch.setattr(query, "datetime", Frozen)


# --------------------------------------------------------------------------- #
def test_dod_01_one_changelog_entry_names_every_step_and_its_breaking_changes():
    """The umbrella lands as one CHANGELOG entry (under Unreleased, then under
    the release that ships it), naming #151 … #161 and the breaking changes
    the umbrella asks to mark."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = re.split(r"\n(?=## \[)", text)
    mine = []
    for section in sections:
        entries = re.split(r"\n(?=### )", section)
        found = [e for e in entries if e.startswith("### ") and "issues/150)" in e.splitlines()[0]]
        if found:
            mine += found
            break
    assert len(mine) == 1, "one entry for #150"
    entry = mine[0]
    for n in range(151, 162):
        assert f"#{n}" in entry, n
    breaking = entry.split("#### Breaking changes", 1)[1].split("####", 1)[0]
    assert "History defaults to the last 30 days" in breaking
    assert "`GET /api/watches` answers differently" in breaking
    # no step keeps an entry of its own
    others = [e.splitlines()[0] for e in entries if e is not entry and "part of [#150]" in e.lower()]
    assert others == []


def test_dod_02_one_panel_with_the_fields_that_apply_and_filters_in_the_url():
    """The three pages create the shared panel (EkteFilters.create) from the
    registry, with the keys of the umbrella's table D, and keep the filters in
    the query string: a parsed URL is written back unchanged, other pages'
    keys dropped."""
    pages = _node("return F.PAGES;")
    shared = {"surface", "relay", "model", "suite", "api", "stream"}
    assert set(pages["history"]) == shared | {"q", "range", "mode", "detect", "risk", "min_score", "exec", "watch",
                                               "scoring_version", "audit_version"}
    assert set(pages["analytics"]) == shared | {"range", "exec", "watch", "scoring_version", "audit_version",
                                                "group"}
    assert set(pages["watches"]) == shared | {"q", "state", "alerting"}
    for page in ("history", "analytics", "watches"):
        src = (STATIC / f"{page}.html").read_text(encoding="utf-8")
        assert "window.EkteFilters.create(" in src and f"EkteFilters.PAGES.{page}" in src, page
    got = _node("""
      const out = {};
      for (const p of ["history", "analytics", "watches"]) {
        const f = F.PAGES[p];
        const st = F.parse("?relay=a&relay=b&suite=quick&risk=high&state=paused&group=model", f);
        out[p] = F.serialise(st, {}, f);
      }
      return out;
    """)
    assert got == {"history": "relay=a&relay=b&suite=quick&risk=high",
                   "analytics": "relay=a&relay=b&suite=quick&group=model",
                   "watches": "relay=a&relay=b&suite=quick&state=paused"}


def test_dod_03_every_component_get_is_cached_and_a_reload_is_304(client, site):
    """Every GET a component of History, Analytics and Monitors makes answers
    with an ETag and Cache-Control: no-cache, and asked again with that ETag
    (a reload with unchanged data) with 304. /api/jobs is live state and
    stays uncached by design (#150 Decisions)."""
    for page, urls in _component_urls(client, site["runs"]).items():
        for url in urls:
            first = client.get(url)
            assert first.status_code == 200, (page, url, first.text)
            assert first.headers["etag"] and first.headers["cache-control"] == "no-cache", url
            again = client.get(url, headers={"If-None-Match": first.headers["etag"]})
            assert again.status_code == 304, (page, url)
    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200 and "etag" not in jobs.headers
    assert "no-cache" not in jobs.headers.get("cache-control", "")


def test_dod_04_a_day_range_keeps_its_etag_and_an_hour_range_is_exact(client, site, monkeypatch):
    """The same day: the same ETag for every History and Analytics component
    minutes apart; 24h moves with the clock."""
    clock = [NOW.replace(hour=9, minute=0, second=10)]
    _freeze(monkeypatch, clock)
    urls = [u for p in ("history", "analytics") for u in _component_urls(client, site["runs"])[p]
            if "range=30d" in u]
    first = {u: client.get(u).headers["etag"] for u in urls}
    clock[0] += timedelta(minutes=7)
    for u in urls:
        assert client.get(u, headers={"If-None-Match": first[u]}).status_code == 304, u
    hour = "/api/analytics/summary?range=24h"
    a = client.get(hour).json()
    clock[0] += timedelta(minutes=3)
    b = client.get(hour).json()
    assert a["to"] != b["to"]
    assert datetime.fromisoformat(b["to"]) - datetime.fromisoformat(b["from"]) == timedelta(hours=24)


def test_dod_05_both_pages_default_to_30d_from_local_midnight():
    """filters.js defines the 30d default once and History and Analytics start
    on it; 30d is today plus the 29 days before, from 00:00 in the viewer's
    zone, with no end (the umbrella's example: Nov 10 → Oct 12 00:00)."""
    assert _node("return F.FIELDS.range.def;") == "30d"
    got = _node("""
      return ["history", "analytics"].map((p) =>
        F.initial("", { page: p, fields: F.PAGES[p], defaults: {}, storage: null }).state.range);
    """)
    assert got == ["30d", "30d"]
    now = datetime(2026, 11, 10, 15, 30, tzinfo=UTC)
    q = query.parse_query({"range": "30d", "tz": "Europe/Berlin"}, now=now)
    assert q.start == datetime(2026, 10, 11, 22, 0, tzinfo=UTC)  # Oct 12, 00:00 CEST
    assert q.end is None


def test_dod_06_a_run_saved_by_another_process_changes_the_signal_and_counts_one(client, site):
    """A run saved by another process (as the CLI saves one) changes the
    `data` token the pages poll, and the answers they then refetch hold it:
    Analytics' summary counts one more run, and History's groups.limit=1
    answer (its "N new runs" count) one more."""
    count = "/api/history/groups?groups.limit=1&trend.metrics=score&range=30d"
    summary = "/api/analytics/summary?range=30d"
    v0, n0, s0 = (client.get("/api/version").json(), client.get(count).json()["total_runs"],
                  client.get(summary).json()["runs"])
    report = _report(NOW - timedelta(minutes=5))
    code = ("import json, sys; from ekte.web import history; history.init();"
            " history.save(json.loads(sys.argv[1]))")
    env = dict(os.environ, EKTE_DATA_DIR=str(site["dir"]), PYTHONPATH=str(ROOT))
    subprocess.run([sys.executable, "-c", code, json.dumps(report)], cwd=str(ROOT), env=env,
                   check=True, timeout=60)
    v1 = client.get("/api/version").json()
    assert v1["data"] != v0["data"] and v1["live"] == v0["live"]
    assert client.get(count).json()["total_runs"] == n0 + 1
    assert client.get(summary).json()["runs"] == s0 + 1


def test_dod_07_only_the_change_signal_is_polled():
    """live.js is the one poller (every 10 s, and only while the tab is
    visible); no page or script schedules a data request of its own: the
    Running lists read /api/jobs on the change signal (jobs.js live mode on
    the Audit page, poll: false on Monitors) and nothing sets an interval but
    the Audit page's elapsed-time clock."""
    live = (STATIC / "live.js").read_text(encoding="utf-8")
    assert "var INTERVAL = 10000;" in live and 'visible: function () { return document.visibilityState === "visible"; }' in live
    for path in sorted(STATIC.glob("*.html")):
        src = path.read_text(encoding="utf-8")
        intervals = re.findall(r"setInterval\(([^,]+),", src)
        assert intervals in ([], ["tick"]) and (not intervals or path.name == "index.html"), path.name
        for m in re.finditer(r"EkteJobs\.init\([^{]*\{(?P<opts>[^}]*)", src):
            assert "live: true" in m["opts"] or "poll: false" in m["opts"], path.name
    assert "/api/watches" not in live


def test_dod_08_monitor_progress_comes_from_the_job_event_streams():
    """The Monitors page opens /api/jobs/monitor-<id>/events for each running
    monitor and folds its events with EkteJobs.progress(), which counts as
    the server counts /api/jobs (test_web_v2_jobs_js.py); /api/watches holds
    no live state (test_watches_api.py)."""
    src = (STATIC / "watches.html").read_text(encoding="utf-8")
    assert 'new EventSource("/api/jobs/monitor-" + encodeURIComponent(wid) + "/events")' in src
    assert "window.EkteJobs.progress()" in src
    assert re.search(r"poll: false", src)


def test_dod_09_filters_are_shared_by_default_per_page_when_off_and_the_url_wins():
    from tests.test_web_v2_filters_js import _PAGES

    got = _node(_PAGES + """
      const s = mem({});
      const scope = F.scope(s);
      use(hist, "?relay=a", s);
      const shared = open(ana, "", s).state.relay;
      const url = open(ana, "?relay=b", s);
      F.setScope("page", s);
      use(ana, "?relay=c", s);
      return { scope, shared, url: [url.source, url.state.relay], perPage: [open(hist, "", s).state.relay,
               open(ana, "", s).state.relay] };
    """)
    assert got["scope"] == "shared" and got["shared"] == ["a"]
    assert got["url"] == ["url", ["b"]]
    assert got["perPage"] == [["a"], ["c"]]


def test_dod_10_watch_shows_exactly_one_monitors_runs(client, site):
    """Monitors 1 and 2 share relay, model and suite: relay + model + suite
    merges them, watch=<id> does not, on History and on Analytics."""
    runs = site["runs"]
    for wid, own in (("1", runs["w1"] + runs["old"]), ("2", runs["w2"])):
        body = client.get(f"/api/history/runs?group=all&group.key=(all)&range=&watch={wid}").json()
        assert sorted(r["id"] for r in body["rows"]) == sorted(own)
        assert client.get(f"/api/history/groups?trend.metrics=score&range=&watch={wid}").json()["total_runs"] \
            == len(own)
        assert client.get(f"/api/analytics/summary?range=&watch={wid}").json()["runs"] == len(own)
    merged = client.get("/api/history/groups", params={
        "trend.metrics": "score", "range": "", "relay": RELAY, "model": "model-a", "suite": "standard",
        "exec": "monitor"}).json()["total_runs"]
    assert merged == len(runs["w1"]) + len(runs["old"]) + len(runs["w2"])


def test_dod_11_links_reproduce_the_filters_and_focus_the_exact_run(client, site):
    """A History group's link opens Analytics with the filters Analytics
    shows; a monitor's History link (runs.focus=<id>, default range) finds a
    run 40 days old: the server says the range alone leaves it out, and
    History widens the range (a11y/test_history_focus.py)."""
    link = _node("""
      return F.href("analytics", { range: "7d", relay: ["relay.example"], model: ["model-a"], risk: "high",
                                   q: "x", watch: "1", exec: "monitor" }, { tab: "overview" });
    """)
    assert link == "/analytics?range=7d&relay=relay.example&model=model-a&exec=monitor&watch=1&tab=overview"
    target = _node(f"return F.parse({json.dumps(link.split('?')[1])}, F.PAGES.analytics);")
    assert target["relay"] == ["relay.example"] and target["watch"] == "1" and "risk" not in target
    old = site["runs"]["old"][0]
    focus = client.get(f"/api/history/runs?group=all&group.key=(all)&range=30d&tz=UTC&watch=1"
                       f"&runs.focus={old}").json()["focus"]
    assert focus["found"] is False and focus["outside"] is True and focus["by_range_only"] is True
    src = (STATIC / "watches.html").read_text(encoding="utf-8")
    assert 'window.EkteFilters.href("history", f, { "runs.focus": String(reportId) })' in src


def test_dod_12_every_component_endpoint_has_a_budget_case():
    """The budget tests (opt-in, EKTE_BENCH=1) time every endpoint a
    component uses: the function behind each endpoint of test_dod_03 is
    called in a budget test (marked slow) or in its case list."""
    import ast

    bodies = []
    for f in ("test_query.py", "test_analytics_widgets.py", "test_history_api.py", "test_watches_api.py",
              "test_web_version.py"):
        src = (ROOT / "tests" / f).read_text(encoding="utf-8")
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_benchmark"):
                assert any(ast.unparse(d) == "pytest.mark.slow" for d in node.decorator_list), node.name
                bodies.append(ast.get_source_segment(src, node) or "")
            elif isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "WIDGET_CASES" for t in node.targets):
                bodies.append(ast.get_source_segment(src, node) or "")
    timed = "\n".join(bodies)
    # History's status and report detail: scripts/bench_fixture.py history_cases()
    assert "history_cases(conn)" in timed
    bench = (ROOT / "scripts" / "bench_fixture.py").read_text(encoding="utf-8")
    timed += "\n" + bench.split("def history_cases", 1)[1].split("\ndef ", 1)[0]
    for name in ("metrics.catalogue", "filter_options", "widget_summary", "widget_series", "widget_heatmap",
                 "widget_leaderboard", "widget_breakdown", "widget_errors", "widget_integrity",
                 "history_api.groups", "history_api.runs", "history.status()", "history_report(rid, trend=True)",
                 "watches_api.list_watches", "watches_api.options", "version_tokens"):
        assert name in timed, name
