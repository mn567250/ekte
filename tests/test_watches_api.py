"""The Monitors API (ekte/web/watches_api.py): GET /api/watches filtered and
cached, GET /api/watches/options counting monitors, live state in /api/jobs."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web import server, watches, watches_api  # noqa: E402

KEY = "env:EKTE_TEST_KEY"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(data):
    return TestClient(server.create_app(), base_url="http://localhost")


def _watch(**cfg) -> int:
    return watches.create({"base_url": "https://relay-a.example/v1", "api_key": KEY, "model": "gpt-4o",
                           "interval_sec": 3600, **cfg})


def _draft(**cfg) -> int:
    return watches.create({"base_url": "https://relay-a.example/v1", "model": "gpt-4o", **cfg}, draft=True)


def _names(client, query: str = "") -> list[str]:
    r = client.get("/api/watches" + (f"?{query}" if query else ""))
    assert r.status_code == 200, r.text
    return sorted(w["name"] for w in r.json())


@pytest.fixture
def mixed(data):
    """active / paused / draft monitors over two relays, models and surfaces."""
    a = _watch(name="Alpha", alert_on="medium", suite="quick")
    watches.mark_run(a, "high", 40.0, None, 1.0)
    b = _watch(name="Beta", base_url="https://relay-b.example/v1", model="m-raw", claimed_model="claude-x",
               alert_on="high", enabled=False)
    watches.mark_run(b, "medium", 60.0, None, 1.0)
    c = _draft(name="Gamma", base_url="https://relay-b.example/v1", model="text-embed", surface="embedding")
    d = _watch(name="Delta", alert_on="low")
    watches.mark_run(d, "low", 70.0, None, 1.0)
    return {"Alpha": a, "Beta": b, "Gamma": c, "Delta": d}


# --------------------------------------------------------------------------- #
# state and alerting
# --------------------------------------------------------------------------- #
def test_state_and_alerting_on_every_row(client, mixed):
    rows = {w["name"]: w for w in client.get("/api/watches").json()}
    assert {n: w["state"] for n, w in rows.items()} == {
        "Alpha": "active", "Beta": "paused", "Gamma": "draft", "Delta": "active"}
    # high >= medium; medium < high; no run; low >= low
    assert {n: w["alerting"] for n, w in rows.items()} == {
        "Alpha": True, "Beta": False, "Gamma": False, "Delta": True}


@pytest.mark.parametrize(("risk", "threshold", "alerting"), [
    ("low", "medium", False),          # below
    ("medium", "medium", True),        # at
    ("high", "medium", True),          # above
    ("inconclusive", "low", False),
    ("clean", "low", False),
    (None, "low", False),              # never ran
    ("medium", None, True),            # no threshold: medium
])
def test_alerting_follows_the_alert_threshold(data, risk, threshold, alerting):
    wid = _watch(alert_on=threshold)
    if risk is not None:
        watches.mark_run(wid, risk, 50.0, None, 1.0)
    [row] = watches_api.rows()
    assert row["alerting"] is alerting
    # the scheduler alerts on the same rule
    assert server._risk_meets(risk, threshold or "medium") is alerting


def test_a_draft_stays_a_draft_until_its_interval_is_set(client, data):
    wid = _draft(name="d")
    assert client.get("/api/watches").json()[0]["state"] == "draft"
    # the key stays optional: an interval alone finishes the setup
    assert client.patch(f"/api/watches/{wid}", json={"interval_sec": 1800}).status_code == 200
    assert client.get("/api/watches").json()[0]["state"] == "paused"
    assert client.patch(f"/api/watches/{wid}", json={"enabled": True}).status_code == 200
    assert client.get("/api/watches").json()[0]["state"] == "active"


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def test_each_key_filters(client, mixed):
    rows = {w["name"]: w for w in client.get("/api/watches").json()}
    relay_b = rows["Beta"]["relay_key"]
    assert rows["Gamma"]["relay_key"] == relay_b != rows["Alpha"]["relay_key"]
    assert _names(client, "state=draft") == ["Gamma"]
    assert _names(client, "state=paused") == ["Beta"]
    assert _names(client, "state=active") == ["Alpha", "Delta"]
    assert _names(client, "alerting=yes") == ["Alpha", "Delta"]
    assert _names(client, "alerting=no") == ["Beta", "Gamma"]
    assert _names(client, "surface=embedding") == ["Gamma"]
    assert _names(client, "surface=chat") == ["Alpha", "Beta", "Delta"]
    assert _names(client, f"relay={relay_b}") == ["Beta", "Gamma"]
    assert _names(client, f"relay={relay_b}&relay={rows['Alpha']['relay_key']}") == [
        "Alpha", "Beta", "Delta", "Gamma"]
    assert _names(client, f"relay={relay_b}&state=draft") == ["Gamma"]
    # model: the claimed model, else the model
    assert _names(client, "model=claude-x") == ["Beta"]
    assert _names(client, "model=m-raw") == []
    assert _names(client, "model=gpt-4o") == ["Alpha", "Delta"]
    assert _names(client, "suite=quick") == ["Alpha"]
    # embeddings never stream: "-" is "no probe request mode"
    assert _names(client, "stream=-") == ["Gamma"]
    assert _names(client, f"stream={rows['Alpha']['stream_mode']}") == ["Alpha", "Beta", "Delta"]
    assert _names(client, f"api={rows['Alpha']['api_resolved']}") == sorted(
        n for n, w in rows.items() if w["api_resolved"] == rows["Alpha"]["api_resolved"])
    assert _names(client, "suite=-") == []


def test_q_matches_name_url_relay_label_models_and_suite(client, mixed):
    assert _names(client, "q=alph") == ["Alpha"]
    assert _names(client, "q=ALPHA") == ["Alpha"]          # ASCII case-insensitive
    assert _names(client, "q=relay-b") == ["Beta", "Gamma"]  # base URL / relay label
    assert _names(client, "q=claude") == ["Beta"]          # claimed model
    assert _names(client, "q=M-RAW") == ["Beta"]           # model
    assert _names(client, "q=quick") == ["Alpha"]          # suite
    assert _names(client, "q=nothing-like-it") == []
    rows = {w["name"]: w for w in client.get("/api/watches").json()}
    assert rows["Beta"]["relay_label"] == "relay-b.example"


def test_q_lowercases_ascii_only(data):
    _watch(name="ÄRGER")
    assert [w["name"] for w in watches_api.list_watches({"q": "ärger"})] == []
    assert [w["name"] for w in watches_api.list_watches({"q": "ÄRGER"})] == ["ÄRGER"]


def test_unknown_and_run_only_keys_are_refused(client, mixed):
    for bad in ("range=30d", "risk=high", "from=2026-01-01", "exec=monitor", "group=relay", "watch=7", "foo=1",
                "runs.sort=time", f"{watches_api.TOKEN}=x", ":error=x"):
        r = client.get(f"/api/watches?{bad}")
        assert r.status_code == 400, bad
        assert "unknown parameter" in r.json()["error"], bad
        assert client.get(f"/api/watches/options?{bad}").status_code == 400, bad
    for bad, msg in (("state=running", "state must be one of"), ("alerting=maybe", "alerting must be one of"),
                     ("surface=video", "surface must be one of"), ("state=draft&state=paused", "more than once"),
                     ("suite=a&suite=b", "more than once")):
        r = client.get(f"/api/watches?{bad}")
        assert r.status_code == 400 and msg in r.json()["error"], (bad, r.text)


def test_tz_is_accepted_validated_and_ignored(client, mixed):
    """Every widget request of the pages carries tz (EkteFilters.widgetParams):
    accepted, validated like query.py does, and not part of the answer or key."""
    plain = client.get("/api/watches?state=active")
    berlin = client.get("/api/watches?state=active&tz=Europe/Berlin")
    assert berlin.status_code == 200, berlin.text
    assert berlin.json() == plain.json()
    assert berlin.headers["etag"] == plain.headers["etag"]
    opts = client.get("/api/watches/options?tz=Europe/Berlin")
    assert opts.status_code == 200, opts.text
    assert "tz" not in opts.json()["filters"]
    for path in ("/api/watches", "/api/watches/options"):
        r = client.get(f"{path}?tz=Bad/Zone")
        assert r.status_code == 400 and "time zone" in r.json()["error"], (path, r.text)
        assert client.get(f"{path}?tz=UTC&tz=UTC").status_code == 400, path


def test_rows_never_contain_keys_or_live_state(client, data):
    _watch(api_key="sk-secret-do-not-leak")
    r = client.get("/api/watches")
    assert "sk-secret-do-not-leak" not in r.text
    [w] = r.json()
    assert "api_key" not in w
    assert not {"running", "queued", "progress"} & set(w)


# --------------------------------------------------------------------------- #
# Options
# --------------------------------------------------------------------------- #
def _opts(client, query: str = "") -> dict:
    r = client.get("/api/watches/options" + (f"?{query}" if query else ""))
    assert r.status_code == 200, r.text
    return r.json()


def _counts(entries: list) -> dict:
    return {o["value"]: o["monitors"] for o in entries}


def test_options_count_monitors_not_runs(client, mixed):
    # many runs of one monitor still count it once
    for _ in range(5):
        watches.mark_run(mixed["Alpha"], "high", 40.0, None, 2.0)
    out = _opts(client)
    assert set(watches_api.OPTION_KEYS) <= set(out) and out["monitors"] == 4
    assert _counts(out["state"]) == {"active": 2, "paused": 1, "draft": 1}
    assert _counts(out["alerting"]) == {"yes": 2, "no": 2}
    assert _counts(out["surface"]) == {"chat": 3, "embedding": 1}
    assert _counts(out["model"]) == {"gpt-4o": 2, "claude-x": 1, "text-embed": 1}
    assert _counts(out["stream"])["-"] == 1
    relays = {o["label"]: o["monitors"] for o in out["relay"]}
    assert relays == {"relay-a.example": 2, "relay-b.example": 2}
    # most monitors first
    assert [o["monitors"] for o in out["state"]] == sorted((o["monitors"] for o in out["state"]), reverse=True)


def test_options_count_under_every_filter_but_their_own(client, mixed):
    out = _opts(client, "state=draft")
    assert out["filters"] == {"state": "draft"} and out["monitors"] == 1
    # the state list ignores state=draft: its siblings stay
    assert _counts(out["state"]) == {"active": 2, "paused": 1, "draft": 1}
    # every other list counts the drafts only
    assert _counts(out["surface"]) == {"embedding": 1}
    assert _counts(out["alerting"]) == {"no": 1}
    out = _opts(client, "q=relay-b&alerting=no")
    assert out["monitors"] == 2
    assert _counts(out["alerting"]) == {"no": 2}
    assert _counts(out["state"]) == {"paused": 1, "draft": 1}


def test_options_of_no_monitors(client, data):
    out = _opts(client)
    assert out["monitors"] == 0 and all(out[k] == [] for k in watches_api.OPTION_KEYS)


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/api/watches?state=draft", "/api/watches/options"])
def test_etag_304_until_a_monitor_changes_or_runs(client, mixed, path):
    def etag() -> str:
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        return r.headers["etag"]

    seen = [etag()]
    assert client.get(path, headers={"If-None-Match": seen[-1]}).status_code == 304
    assert etag() == seen[-1]  # unchanged data, same ETag

    def changed() -> None:
        now = etag()
        assert now not in seen
        seen.append(now)
        assert client.get(path, headers={"If-None-Match": now}).status_code == 304

    assert client.patch(f"/api/watches/{mixed['Gamma']}", json={"interval_sec": 600}).status_code == 200
    changed()  # edited
    watches.mark_run(mixed["Alpha"], "clean", 99.0, None, 5.0)
    changed()  # a run finished
    _watch(name="Epsilon")
    changed()  # created
    assert client.delete(f"/api/watches/{mixed['Beta']}").status_code == 200
    changed()  # deleted


def test_the_cached_list_follows_the_master_key_and_memory_keys(client, data, monkeypatch):
    from ekte import secretbox

    wid = watches.create({"base_url": "https://relay-a.example/v1", "api_key": "sk-mem", "model": "m",
                          "interval_sec": 3600}, key_storage=watches.STORAGE_MEMORY)
    first = client.get("/api/watches")
    assert first.json()[0]["key_status"] == "memory"
    watches.forget_memory_keys()  # a restart's loss, no store write
    r = client.get("/api/watches", headers={"If-None-Match": first.headers["etag"]})
    assert r.status_code == 200 and r.json()[0]["key_status"] == "missing"
    assert wid == r.json()[0]["id"]
    before = watches_api.token()
    box = secretbox.SecretBox([secretbox.generate_key()])
    monkeypatch.setattr(secretbox, "current", lambda: box)
    assert watches_api.token() != before


def test_the_token_is_stable_while_kb_db_cannot_be_read(data, monkeypatch):
    """The loader builds a fresh copy per call then: one fixed token, not a new one per request."""
    import ekte.knowledge as knowledge
    from ekte.knowledge.schema import KnowledgeBase

    _watch()
    monkeypatch.setattr(knowledge, "load_knowledge_base", lambda **_kw: KnowledgeBase(
        warnings=["kb.db could not be read: locked"]))
    assert watches_api.token(1.0) == watches_api.token(1.0)
    [row] = watches_api.rows()
    assert row["kb_changed"] is False


def test_the_cached_list_follows_the_run_window_phase(data, monkeypatch):
    wid = _watch(run_window={"tz": "UTC", "days": [0, 1, 2, 3, 4, 5, 6], "start": "08:00", "end": "09:00"})
    assert watches.get(wid)["run_window"] is not None
    day = 1_800_000_000 - 1_800_000_000 % 86400  # a UTC midnight
    inside, outside = day + 8.5 * 3600, day + 10 * 3600
    assert watches_api.token(inside) != watches_api.token(outside)
    assert watches_api.token(day + 10 * 3600) == watches_api.token(day + 11 * 3600)


# --------------------------------------------------------------------------- #
# Live state: /api/jobs
# --------------------------------------------------------------------------- #
def test_jobs_carry_the_live_state_the_page_shows(client, data):
    wid = _watch(name="Live")
    server._running_watches[wid] = {"total": 4, "done": 1, "name": "Live", "waiting_for": ["x"]}
    try:
        [job] = [j for j in client.get("/api/jobs").json()["jobs"] if j.get("watch_id") == wid]
        assert job["id"] == f"monitor-{wid}" and job["status"] == "queued" and job["progress"] is None
        server._running_watches[wid]["started"] = True
        [job] = [j for j in client.get("/api/jobs").json()["jobs"] if j.get("watch_id") == wid]
        assert job["status"] == "running" and job["progress"] == 25
    finally:
        server._running_watches.pop(wid, None)


def test_the_monitors_page_reads_live_state_from_jobs():
    from pathlib import Path

    html = (Path(server.__file__).parent / "static" / "v2" / "watches.html").read_text(encoding="utf-8")
    body = html[html.index("  function load() {"):]
    body = body[:body.index("\n  }\n")]
    jobs = html[html.index("  function readJobs() {"):]
    jobs = jobs[:jobs.index("\n  }\n")]
    # jobs first: a run no longer listed there has saved its result already
    assert '"/api/jobs"' in jobs and '"/api/watches?"' in body
    assert body.index("readJobs()") < body.index('"/api/watches?"')
    # the list through the browser cache, with the filters; progress from the
    # job event streams (#160), no polling
    assert "EkteFilters.fetchWidget(" in body and "F.widgetParams()" in body
    assert 'new EventSource("/api/jobs/monitor-"' in html
    assert "schedulePoll" not in html and "setInterval" not in html


def test_the_endpoints_are_listed_in_the_server_docstring_and_the_docs():
    from pathlib import Path

    doc = (Path(server.__file__).resolve().parents[2] / "docs" / "dev" / "web-server.md").read_text(
        encoding="utf-8")
    for path in ("/api/watches/options",):
        assert path in (server.__doc__ or "") and path in doc


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_benchmark_monitors_under_budget(bench_data):
    """The Monitors endpoints answer in under 50 ms p95 with the fixture's 200
    monitors (cold cache: the functions behind them called directly, relays
    resolved once per call). Opt-in (EKTE_BENCH=1); EKTE_BENCH_BUDGET_MS
    overrides 50, EKTE_BENCH_REPORT collects the timings (tests/bench_report.py)."""
    from tests import bench_report

    budget = bench_report.budget()
    all_rows = watches_api.rows()
    assert len(all_rows) >= 200
    assert {r["state"] for r in all_rows} == {"active", "paused", "draft"}
    assert {r["alerting"] for r in all_rows} == {True, False}
    relay = all_rows[0]["relay_key"]

    def prepared(params: dict) -> list:
        # as the endpoint: prepare (the cache-key token), then the answer
        return watches_api.resolve_params(params)

    def profiles_cold() -> None:
        # the first answer after a knowledge-base change: no profile remembered
        watches_api._profiles = (object(), {})
        watches_api.list_watches(prepared({}))

    cases = {
        "watches, unfiltered": lambda: watches_api.list_watches(prepared({})),
        "watches, unfiltered, profiles cold": profiles_cold,
        "watches, relay + state": lambda: watches_api.list_watches(prepared({"relay": relay, "state": "active"})),
        "watches, q": lambda: watches_api.list_watches(prepared({"q": "relay-1"})),
        "watches/options": lambda: watches_api.options(prepared({})),
        "watches/options, filtered": lambda: watches_api.options(prepared({"state": "active", "alerting": "yes"})),
        "watches token (every request)": watches_api.token,
    }
    results = {name: bench_report.measure(fn) for name, fn in cases.items()}
    bench_report.record("watches_api", results, budget)
    slow = {name: round(p95, 1) for name, (_, p95) in results.items() if p95 >= budget}
    assert not slow, f"p95 over {budget} ms: {slow}"
