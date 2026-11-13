"""The History widgets (ekte/web/history_api.py): GET /api/history/groups and
/api/history/runs, checked against a port of the History page's JavaScript
(the grouping, sorting, paging and relay names it did before #124)."""

from __future__ import annotations

import functools
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.knowledge.relays import add_relay  # noqa: E402
from ekte.web import history, history_api, metrics, query  # noqa: E402
from ekte.web.query import QueryError  # noqa: E402
from ekte.web.relay_map import JOIN_SQL  # noqa: E402
from ekte.web.server import create_app, history_report  # noqa: E402
from tests import test_query as tq  # noqa: E402
from tests.test_analytics import RELAY  # noqa: E402
from tests.test_query import T0, _bench_module, _save  # noqa: E402

data, seeded = tq.data, tq.seeded  # the query core's fixtures

SORTS = [f"{d}{k}" for k in history_api.SORTS for d in ("", "-")]


@pytest.fixture
def client(data):
    return TestClient(create_app(), base_url="http://localhost")


def _conn():
    return history.query_connection()


def _all_runs() -> list[dict]:
    """Every run as the old page held it (newest saved first)."""
    cur = _conn().execute(
        "SELECT h.id, m.started_at, h.risk_level, h.score, h.rating, rm.relay_key, h.claimed_model,"
        f" h.base_url FROM history h JOIN history_metrics m ON m.history_id = h.id {JOIN_SQL}"
        " ORDER BY h.id DESC")
    names = [c[0] for c in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# The page's JavaScript before #124 (history.html sortRows / groupsOf), with
# its time ``ts`` read as the run's start time
# --------------------------------------------------------------------------- #
RISKN = {"clean": 0, "inconclusive": 1, "low": 2, "medium": 3, "high": 4}
GRADEN = {"A": 6, "B": 5, "C": 4, "D": 3, "E": 2, "F": 1}
SORTV = {
    "time": lambda r: r["started_at"],
    "risk": lambda r: RISKN.get(r["risk_level"] or "inconclusive"),
    "score": lambda r: r["score"] if isinstance(r["score"], (int, float)) else None,
    "grade": lambda r: GRADEN.get(str(r["rating"] or "").upper()),
}


def _by_key(fn, direction):
    def cmp(a, b):
        x, y = fn(a), fn(b)
        if x is None or y is None:
            return (0 if y is None else 1) if x is None else -1
        if x == y:
            return 0
        return (-1 if x < y else 1) * (1 if direction == "asc" else -1)
    return cmp


def js_sorted(rows: list[dict], sort: str) -> list[dict]:
    key, direction = (sort[1:], "desc") if sort.startswith("-") else (sort, "asc")
    main, newest = _by_key(SORTV[key], direction), _by_key(SORTV["time"], "desc")
    indexed = list(enumerate(rows))
    indexed.sort(key=functools.cmp_to_key(
        lambda a, b: main(a[1], b[1]) or newest(a[1], b[1]) or a[0] - b[0]))
    return [r for _, r in indexed]


def js_groups(rows: list[dict], sort: str) -> list[tuple[str, list[int]]]:
    """``[(group key as the server names it, [run ids in order])]``."""
    out: dict[str, list[int]] = {}
    for r in js_sorted(rows, sort):
        out.setdefault(f"{r['relay_key']}|{r['claimed_model'] or '(unknown)'}", []).append(r["id"])
    return list(out.items())


def _pages(fn, cursor_key, limit_key, limit, **params):
    """Every page of a paged endpoint function, concatenated."""
    items, after = [], None
    while True:
        p = {**params, limit_key: str(limit)}
        if after:
            p[cursor_key] = after
        page = fn(_conn(), p)
        items.append(page)
        after = page["after"]
        if after is None:
            return items


# --------------------------------------------------------------------------- #
# Order and paging match the page's behaviour
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sort", SORTS)
def test_group_and_row_order_and_paging_match_the_page(seeded, sort):
    expected = js_groups(_all_runs(), sort)
    pages = _pages(history_api.groups, "groups.after", "groups.limit", 3,
                   **{"groups.sort": sort, "trend.metrics": "score"})
    got = [g for p in pages for g in p["groups"]]
    assert [g["key"] for g in got] == [k for k, _ in expected]
    assert all(p["total_groups"] == len(expected) for p in pages)
    assert pages[0]["total_runs"] == 60
    for key, ids in expected:
        rows = [r for p in _pages(history_api.runs, "runs.after", "runs.limit", 4,
                                  **{"group.key": key, "runs.sort": sort})
                for r in p["rows"]]
        assert [r["id"] for r in rows] == ids
    assert [g["runs"] for g in got] == [len(ids) for _, ids in expected]


@pytest.mark.parametrize("group", ["relay", "model", "all"])
def test_other_groupings_cover_every_run_once(seeded, group):
    groups = [g for p in _pages(history_api.groups, "groups.after", "groups.limit", 2,
                                group=group, **{"trend.metrics": "score"}) for g in p["groups"]]
    seen = []
    for g in groups:
        page = history_api.runs(_conn(), {"group": group, "group.key": g["key"],
                                          "runs.limit": "200"})
        assert page["total"] == g["runs"] == len(page["rows"])
        seen += [r["id"] for r in page["rows"]]
    assert sorted(seen) == sorted(r["id"] for r in _all_runs())
    if group == "all":
        assert [g["key"] for g in groups] == ["(all)"] and groups[0]["relay"] is None


def test_filters_apply(seeded):
    out = history_api.groups(_conn(), {"risk": "high", "trend.metrics": "score"})
    want = [r for r in _all_runs() if r["risk_level"] == "high"]
    assert out["total_runs"] == len(want) > 0
    assert [g["key"] for g in out["groups"]] == [k for k, _ in js_groups(want, "-time")]


def test_reaches_the_oldest_of_2000_runs(data):
    _bench_module().build(runs=2000, relays=4, requests=5)
    rows = [r for p in _pages(history_api.runs, "runs.after", "runs.limit", 200,
                              group="all", **{"group.key": "(all)"}) for r in p["rows"]]
    assert len(rows) == 2000
    oldest = _conn().execute("SELECT history_id FROM history_metrics"
                             " ORDER BY started_at, history_id DESC LIMIT 1").fetchone()[0]
    assert rows[-1]["id"] == oldest
    groups = [g for p in _pages(history_api.groups, "groups.after", "groups.limit", 5,
                                **{"trend.metrics": "score"}) for g in p["groups"]]
    assert sum(g["runs"] for g in groups) == 2000


def test_focus_returns_the_page_holding_the_run(seeded):
    key, ids = js_groups(_all_runs(), "-time")[0]
    assert len(ids) >= 8
    target = ids[5]
    page = history_api.runs(_conn(), {"group.key": key, "runs.limit": "2", "runs.focus": str(target)})
    assert page["focus"] == {"id": target, "found": True}
    assert [r["id"] for r in page["rows"]] == ids[:6] and page["limit"] == 6
    rest = history_api.runs(_conn(), {"group.key": key, "runs.limit": "2", "runs.after": page["after"]})
    assert [r["id"] for r in rest["rows"]] == ids[6:8]
    # after a cursor: from there to the page that holds it
    first = history_api.runs(_conn(), {"group.key": key, "runs.limit": "2"})
    page = history_api.runs(_conn(), {"group.key": key, "runs.limit": "2", "runs.after": first["after"],
                                      "runs.focus": str(target)})
    assert [r["id"] for r in page["rows"]] == ids[2:6]
    # a run of another group (or already passed) is not found; the page is as without
    other = js_groups(_all_runs(), "-time")[1][1][0]
    page = history_api.runs(_conn(), {"group.key": key, "runs.limit": "4", "runs.focus": str(other)})
    assert page["focus"] == {"id": other, "found": False} and len(page["rows"]) == 4
    # the groups' page grows to the group of a run
    expected = js_groups(_all_runs(), "-time")
    last_key, last_ids = expected[-1]
    out = history_api.groups(_conn(), {"groups.limit": "2", "groups.focus": str(last_ids[0]),
                                       "trend.metrics": "score"})
    assert out["focus"] == {"id": last_ids[0], "key": last_key}
    assert [g["key"] for g in out["groups"]] == [k for k, _ in expected] and out["after"] is None


# --------------------------------------------------------------------------- #
# Groups: description, latest run, trends
# --------------------------------------------------------------------------- #
def test_group_description(seeded):
    out = history_api.groups(_conn(), {"trend.metrics": "score,error_rate", "groups.limit": "200"})
    runs = _all_runs()
    by_key = dict(js_groups(runs, "-time"))
    for g in out["groups"]:
        ids = by_key[g["key"]]
        mine = [r for r in runs if r["id"] in ids]
        newest = max(mine, key=lambda r: (r["started_at"], r["id"]))
        assert g["latest"]["id"] == newest["id"] and g["runs"] == len(ids)
        assert g["low_n"] is (len(ids) < metrics.MIN_RUNS)
        assert g["base_urls"] == sorted({r["base_url"] for r in mine})  # one URL each here
        assert g["relay"]["key"] == newest["relay_key"]
        assert g["claimed_model"] == newest["claimed_model"]
        assert g["label"] == f"{g['relay']['label']} · {g['claimed_model']}"
    saved = [g for g in out["groups"] if g["relay"]["key"] != g["relay"]["label"]]
    assert {g["relay"]["label"] for g in saved} >= {"Cheap GPT"}


def test_summary_row_carries_the_display_decisions(data):
    rid = _save(T0, score=64.0, risk=None, api_auto=True, watch_id=3)
    row = history_api.runs(_conn(), {"group": "all", "group.key": "(all)"})["rows"][0]
    assert row["id"] == rid
    assert row["risk_level"] == "inconclusive"
    assert row["family"] == {"risk": "grey", "score": "warn", "grade": "good"}  # grade B
    assert (row["mode"], row["detect"], row["exec"], row["surface"]) == ("check", "auto", "monitor", "chat")
    assert row["started_at"].startswith("2026-03-02T12:00:00")
    assert set(row) >= {"ts", "score", "grade", "suite", "api", "stream_mode", "watch_id",
                        "latency_p50_ms", "relay_key", "claimed_model", "base_url"}


def test_trend_points_are_the_stored_per_run_values(seeded, monkeypatch):
    monkeypatch.setattr(history_api, "POINTS", 5)
    for mids in (("score", "error_rate"), ("grade", "latency_p50"), ("ttft_p50", "decode_tps")):
        out = history_api.groups(_conn(), {"trend.metrics": ",".join(mids), "groups.limit": "200"})
        assert out["trend_metrics"] == list(mids)
        for g in out["groups"]:
            for mid in mids:
                m = metrics.METRICS[mid]
                col = history_api._run_value_sql(m)
                stored = [v for (v,) in _conn().execute(
                    f"SELECT {col} FROM history h JOIN history_metrics m ON m.history_id = h.id"
                    f" {JOIN_SQL} WHERE rm.relay_key || '|' || COALESCE(NULLIF(h.claimed_model, ''),"
                    " '(unknown)') = ? ORDER BY m.started_at DESC, h.id DESC LIMIT 5", (g["key"],))]
                want = [float(v) for v in reversed(stored) if v is not None]
                t = g["trends"][mid]
                assert t["points"] == want and t["n"] == len(want)
                assert t["first"] == (want[0] if want else None)
                assert t["last"] == metrics.present(m, want[-1] if want else None,
                                                    t["first"], n=len(want))
    # error rate per run is the #118 outcome model's stored rate
    rate = _conn().execute("SELECT error_rate FROM history_metrics WHERE error_rate > 0").fetchone()[0]
    assert 0 < rate < 1


def test_one_run_trends_equal_the_group_and_the_aggregator(data, client):
    rid = _save(T0, score=71.5, outcomes={"success": 7, "relay_5xx": 2, "rate_limited": 1})
    trends = client.get(f"/api/history/{rid}?trend=1").json()["history_trends"]
    assert list(trends) == list(metrics.HISTORY_TRENDS)
    assert "history_trends" not in client.get(f"/api/history/{rid}").json()
    group = history_api.groups(_conn(), {"trend.metrics": "score,error_rate"})["groups"][0]
    cells = query.aggregate(_conn(), query.Query(), list(metrics.HISTORY_TRENDS), "all")[0].metrics
    for mid in metrics.HISTORY_TRENDS:
        assert trends[mid]["value"] == cells[mid].value, mid
        if mid in group["trends"]:
            assert trends[mid] == group["trends"][mid]["last"]
    assert trends["error_rate"]["value"] == pytest.approx(0.2)
    assert trends["score"]["grade"] == "C" and trends["score"]["family"] == "sky"


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", [None, "", ",", "score,grade,ttft_p50", "nope", "score,score",
                                   "duration"])
def test_trend_metrics_must_be_one_or_two_trend_ids(seeded, client, value):
    params = {} if value is None else {"trend.metrics": value}
    r = client.get("/api/history/groups", params=params)
    assert r.status_code == 400 and "trend.metrics" in r.json()["error"]


def test_trend_metrics_forms(seeded):
    a = history_api.groups(_conn(), {"trend.metrics": "latency_p50,score"})
    b = history_api.groups(_conn(), [("trend.metrics", "score"), ("trend.metrics", "latency_p50")])
    assert a["trend_metrics"] == b["trend_metrics"] == ["score", "latency_p50"]


@pytest.mark.parametrize("path,params,word", [
    ("groups", {"groups.sort": "name"}, "groups.sort"),
    ("groups", {"groups.limit": "0"}, "groups.limit"),
    ("groups", {"groups.after": "garbage"}, "groups.after"),
    ("groups", {"groups.page": "2"}, "groups.page"),
    ("groups", {"group": "suite"}, "group"),
    ("groups", {"risk": "awful"}, "risk"),
    ("runs", {}, "group.key"),
    ("runs", {"group.key": "x", "runs.limit": "201"}, "runs.limit"),
    ("runs", {"group.key": "x", "runs.focus": "abc"}, "runs.focus"),
    ("runs", {"group.key": "x", "runs.nope": "1"}, "runs.nope"),
])
def test_bad_parameters_answer_400(seeded, client, path, params, word):
    if path == "groups":
        params = {"trend.metrics": "score", **params}
    r = client.get(f"/api/history/{path}", params=params)
    assert r.status_code == 400 and word in r.json()["error"]


def test_cursor_of_another_sort_is_rejected(seeded):
    page = history_api.groups(_conn(), {"groups.limit": "1", "trend.metrics": "score"})
    with pytest.raises(QueryError):
        history_api.groups(_conn(), {"groups.after": page["after"], "groups.sort": "score",
                                     "trend.metrics": "score"})
    with pytest.raises(QueryError):
        history_api.runs(_conn(), {"group.key": "x", "runs.after": page["after"]})


def test_other_widgets_keys_are_ignored(seeded):
    a = history_api.groups(_conn(), {"trend.metrics": "score", "runs.sort": "score", "kpi.x": "1"})
    assert a == history_api.groups(_conn(), {"trend.metrics": "score"})


def test_endpoints_are_cached_with_etags(seeded, client):
    params = {"trend.metrics": "score", "range": "365d"}
    r = client.get("/api/history/groups", params=params)
    assert r.status_code == 200 and r.json()["group"] == "relay_model"
    etag = r.headers["etag"]
    assert client.get("/api/history/groups", params=params,
                      headers={"If-None-Match": etag}).status_code == 304
    key = r.json()["groups"][0]["key"] if r.json()["groups"] else "x"
    r = client.get("/api/history/runs", params={"group.key": key})
    assert r.status_code == 200 and r.headers["etag"]
    # a write drops the cached answers
    _save(None, score=10.0)
    assert client.get("/api/history/groups", params=params,
                      headers={"If-None-Match": etag}).status_code == 200


def _revalidates(client, url):
    """GET ``url`` twice, the second time with the first answer's ETag: the
    first answer (200, ETag, no-cache) and the second's status."""
    first = client.get(url)
    assert first.status_code == 200, (url, first.text)
    assert first.headers["etag"] and first.headers["cache-control"] == "no-cache", url
    again = client.get(url, headers={"If-None-Match": first.headers["etag"]})
    assert again.headers.get("etag") == first.headers["etag"]
    assert again.headers.get("cache-control") == "no-cache"
    return first, again.status_code


@pytest.mark.parametrize("path", ["/api/history/status", "/api/history/{rid}",
                                  "/api/history/{rid}?trend=1"])
def test_status_and_report_detail_revalidate_until_a_write(seeded, client, path):
    rid = max(r["id"] for r in _all_runs())
    url = path.format(rid=rid)
    first, status = _revalidates(client, url)
    assert status == 304
    # rescores save a new run; a save, like a delete, bumps the data version
    _save(None, score=10.0)
    after = client.get(url, headers={"If-None-Match": first.headers["etag"]})
    assert after.status_code == 200 and after.headers["etag"] != first.headers["etag"]
    assert after.json() == first.json() or path.endswith("status")
    history.delete(rid - 1)
    gone = client.get(url, headers={"If-None-Match": after.headers["etag"]})
    assert gone.status_code == 200 and gone.headers["etag"] != after.headers["etag"]


def test_report_detail_keys_on_trend_and_answers_404_uncached(seeded, client):
    rid = max(r["id"] for r in _all_runs())
    plain = client.get(f"/api/history/{rid}")
    trend = client.get(f"/api/history/{rid}?trend=1")
    assert plain.headers["etag"] != trend.headers["etag"]
    assert "history_trends" in trend.json() and "history_trends" not in plain.json()
    # other parameters do not split the cache; trend=0 is the plain answer
    assert client.get(f"/api/history/{rid}?trend=0&x=1").headers["etag"] == plain.headers["etag"]
    assert client.get(f"/api/history/{rid}?trend=abc").status_code == 422
    history.delete(rid)
    for _ in range(2):  # never cached
        r = client.get(f"/api/history/{rid}?trend=1")
        assert r.status_code == 404 and r.json() == {"error": "not found"}
        assert "etag" not in r.headers
    assert client.get(f"/api/history/{rid}",
                      headers={"If-None-Match": plain.headers["etag"]}).status_code == 404


def test_every_cached_route_sends_an_etag_and_no_cache(seeded, monkeypatch):
    """Every GET registered through cached_endpoint (and the report detail,
    which builds one per run) answers with an ETag and Cache-Control:
    no-cache, never no-store, and revalidates with a 304."""
    from ekte.web import cache

    handlers = set()
    original = cache.cached_endpoint

    def recording(*args, **kwargs):
        decorate = original(*args, **kwargs)

        def wrap(fn):
            handler = decorate(fn)
            handlers.add(handler)
            return handler
        return wrap

    monkeypatch.setattr(cache, "cached_endpoint", recording)
    app = create_app()
    client = TestClient(app, base_url="http://localhost")
    paths = sorted(r.path for r in app.routes if getattr(r, "endpoint", None) in handlers)
    assert {"/api/history/status", "/api/history/groups", "/api/history/runs",
            "/api/metrics", "/api/analytics/summary"} <= set(paths)
    rid = max(r["id"] for r in _all_runs())
    key = history_api.groups(_conn(), {"trend.metrics": "score"})["groups"][0]["key"]
    # the parameters an endpoint cannot do without
    extra = {"/api/history/groups": "?trend.metrics=score",
             "/api/history/runs": "?group.key=" + key,
             "/api/analytics/breakdown": "?breakdown.metric=relay_overhead"}
    for path in [*paths, f"/api/history/{rid}", f"/api/history/{rid}?trend=1"]:
        _, status = _revalidates(client, path + extra.get(path, ""))
        assert status == 304, path


def test_a_day_range_keeps_its_etag_all_day_and_no_range_is_all_time(seeded, client, monkeypatch):
    """History's widgets resolve range=30d in the viewer's tz to a fixed start
    (the same ETag minutes apart, a new one at local midnight), and without a
    range they cover all time (the page sends range=30d by default and
    nothing for "all time", #152)."""
    clock = [datetime(2026, 9, 10, 12, 0, 10, tzinfo=UTC)]

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0]

    monkeypatch.setattr(query, "datetime", Frozen)
    params = {"trend.metrics": "score", "range": "30d", "tz": "America/Los_Angeles"}
    first = client.get("/api/history/groups", params=params)
    assert first.status_code == 200
    clock[0] += timedelta(minutes=1)
    assert client.get("/api/history/groups", params=params,
                      headers={"If-None-Match": first.headers["etag"]}).status_code == 304
    clock[0] = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)  # 00:00 in Los Angeles
    assert client.get("/api/history/groups", params=params).headers["etag"] != first.headers["etag"]
    # the last 30 days hold fewer runs than all time
    pairs = history_api.resolve_params(params, now=clock[0])
    assert dict(pairs)["from"] == "2026-08-13T07:00:00.000000+00:00" and "to" not in dict(pairs)
    last30 = history_api.groups(_conn(), pairs)
    every = history_api.groups(_conn(), {"trend.metrics": "score"})
    assert 0 < last30["total_runs"] < every["total_runs"] == 60
    # 24h stays exact
    hours = dict(history_api.resolve_params({"range": "24h"}, now=clock[0]))
    assert hours["to"] == "2026-09-11T07:00:00.000000+00:00" and hours["from"] == "2026-09-10T07:00:00.000000+00:00"


# --------------------------------------------------------------------------- #
# Relay names
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("urls,names", [
    (["https://a.example/v1"], ["a.example"]),
    (["https://a.example/v1", "https://b.example/v1"], ["a.example", "b.example"]),
    # one host: the paths tell them apart
    (["https://a.example/v1", "https://a.example/v2/"], ["a.example/v1", "a.example/v2"]),
    (["https://a.example", "https://a.example/v1"], ["a.example", "a.example/v1"]),
    # ports keep two servers on one host apart
    (["http://h:8080/v1", "http://h:9090/v1"], ["h:8080", "h:9090"]),
    (["http://h:8080/v1", "http://h:8080/v2"], ["h:8080/v1", "h:8080/v2"]),
    # default ports are dropped, so these share host h
    (["http://h:80/a", "http://h/b"], ["h/a", "h/b"]),
    (["https://h:443/v1"], ["h"]),
    (["HTTPS://Relay.Example/v1/"], ["relay.example"]),
    (["https://user:pw@h.example/v1"], ["h.example"]),
    (["http://[::1]:8080/v1"], ["[::1]:8080"]),
    # not a URL (the browser's URL() throws): the text itself
    (["(unknown)"], ["(unknown)"]),
    (["relay.example/v1"], ["relay.example/v1"]),
])
def test_url_labels(urls, names):
    assert history_api.url_labels(urls) == dict(zip(urls, names, strict=True))


def test_relay_labels_name_saved_relays_and_disambiguate_urls(data):
    add_relay("Cheap GPT", RELAY)
    for url in (RELAY, "https://x.example/a", "https://x.example/b", "https://y.example:8443/v1"):
        _save(T0, base_url=url)
    labels = history_api.relay_labels(_conn())
    assert "Cheap GPT" in labels.values()
    assert {v for k, v in labels.items() if "x.example" in k} == {"x.example/a", "x.example/b"}
    assert {v for k, v in labels.items() if "y.example" in k} == {"y.example:8443"}
    out = history_api.groups(_conn(), {"group": "relay", "trend.metrics": "score"})
    assert sorted(g["relay"]["label"] for g in out["groups"]) == sorted(
        ["Cheap GPT", "x.example/a", "x.example/b", "y.example:8443"])
    assert {g["label"] for g in out["groups"]} == {g["relay"]["label"] for g in out["groups"]}


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
def _perf_record(i: int) -> dict:
    """A stored request record: mostly successes, every 20th a failed one
    without a failure class (a run saved before classes were recorded)."""
    if i % 20 == 19:
        return {"op": "complete", "ok": False, "endpoint": "target", "status_code": 502,
                "error_type": "HTTPStatusError", "duration_ms": 900.0 + i}
    return {"op": "complete", "ok": True, "endpoint": "target", "duration_ms": 600.0 + i * 3 % 97,
            "ttft_ms": 300.0 + i * 7 % 53, "decode_tps_local": 40.0 + i % 11,
            "itl_mean_ms": 20.0 + i % 5}


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_benchmark_20k_runs_under_budget(bench_data, monkeypatch):
    """Each History widget answers within the budget (p95, cold cache: the
    functions are called directly) on the 20k-run fixture. Opt-in
    (EKTE_BENCH=1), as tests/test_query.py; EKTE_BENCH_BUDGET_MS overrides 50,
    EKTE_BENCH_REPORT collects the timings (tests/bench_report.py)."""
    from tests import bench_report

    budget = bench_report.budget()
    conn = _conn()
    t = {"trend.metrics": "score,latency_p50"}
    first = history_api.groups(conn, t)
    key = first["groups"][0]["key"]
    end = _bench_module().END

    def at_end(params):
        return history_api.resolve_params(params, now=end)

    cases = {
        "groups -time": lambda: history_api.groups(conn, t),
        "groups page 2": lambda: history_api.groups(conn, {**t, "groups.after": first["after"]}),
        "groups by relay, score": lambda: history_api.groups(conn, {**t, "group": "relay",
                                                                     "groups.sort": "score"}),
        "groups all": lambda: history_api.groups(conn, {**t, "group": "all"}),
        "groups filtered": lambda: history_api.groups(conn, {**t, "surface": "chat", "risk": "clean"}),
        "runs -time": lambda: history_api.runs(conn, {"group.key": key}),
        "runs -grade, focus": lambda: history_api.runs(conn, {"group.key": key, "runs.sort": "-grade",
                                                              "runs.focus": "5"}),
        "runs all, score": lambda: history_api.runs(conn, {"group": "all", "group.key": "(all)",
                                                           "runs.sort": "score"}),
        # relative ranges (#152), resolved at the fixture's END as the endpoints' prepare does
        "groups range 30d Berlin": lambda: history_api.groups(conn, at_end({**t, "range": "30d",
                                                                            "tz": "Europe/Berlin"})),
        "groups range 365d": lambda: history_api.groups(conn, at_end({**t, "range": "365d"})),
        "groups range 24h": lambda: history_api.groups(conn, at_end({**t, "range": "24h"})),
        "runs range 30d Berlin": lambda: history_api.runs(conn, at_end({"group.key": key, "range": "30d",
                                                                        "tz": "Europe/Berlin"})),
        "runs range 24h": lambda: history_api.runs(conn, at_end({"group.key": key, "range": "24h"})),
    }
    # status and report detail (GET /api/history/status, /api/history/{rid}
    # with and without trend=1) on the fixture's 16 kB reports
    cases |= {name: (lambda fn=fn: fn(conn))
              for name, fn in _bench_module().history_cases(conn).items()}
    results = {name: bench_report.measure(fn) for name, fn in cases.items()}
    # The fixture's reports carry no performance section: trend=1 over a run
    # of 100 requests (the fixture's --requests) as well, so the running
    # medians and bands are timed too (the stored report, plus the requests).
    rid = int(conn.execute("SELECT MAX(id) FROM history").fetchone()[0])
    real_get, template = history.get, [_perf_record(i) for i in range(100)]

    def with_requests(r):
        report = real_get(r)
        report["performance"] = {"requests": [dict(rec) for rec in template]}
        return report

    with monkeypatch.context() as m:
        m.setattr(history, "get", with_requests)
        assert history_report(rid, trend=True)["performance"]["requests"][-2]["trend_band"]
        results["history report, trend=1, 100 requests"] = bench_report.measure(
            lambda: history_report(rid, trend=True))
    slow = {name: round(p95, 1) for name, (_, p95) in results.items() if p95 >= budget}
    bench_report.record("history_api", results, budget)
    assert not slow, f"p95 over {budget} ms: {slow}"
