"""The query core (ekte/web/query.py): URL schema, SQL run selection,
aggregation, time series and keyset paging, checked against a plain-Python
reference (tests/analytics_reference.py) on the same database."""

from __future__ import annotations

import json
import math
import random
import re
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from ekte import datadir, errorclass
from ekte.knowledge.relays import add_relay
from ekte.perf.outcomes import from_counts
from ekte.web import analytics, history, query, run_row
from ekte.web.analytics import AnalyticsError
from ekte.web.query import Query, QueryError, parse_query
from tests import analytics_reference as reference
from tests.test_analytics import OPENAI, OTHER, RELAY, T0, _report

NOW = datetime(2026, 6, 1, 12, 0, 30, tzinfo=UTC)
SPECIAL = "https://we%ird_relay.example/v1"  # % and _ in a URL (q escaping)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    return tmp_path


def _conn():
    return history.query_connection()


def _write(sql: str, args=()) -> None:
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        conn.execute(sql, args)


def _save(started, watch_id=None, outcomes=None, surface=None, api_auto=None, mode="check",
          **kw) -> int:
    report = _report(started, **kw)
    report["mode"] = mode
    if surface is not None:
        report["surface"] = surface
    if api_auto is not None:
        report["target"]["api_auto"] = api_auto
    if outcomes is not None:
        report["outcomes"] = from_counts({"complete": outcomes}).model_dump()
    rid = history.save(report, watch_id=watch_id)
    assert rid > 0
    return rid


@pytest.fixture
def seeded(data):
    """60 runs over 200 days (both DST changes of Europe/Berlin), four relays,
    two models, varied outcomes, suites, versions and missing values."""
    add_relay("Cheap GPT", RELAY)
    rng = random.Random(7)
    urls = (RELAY, OPENAI, OTHER, SPECIAL)
    for i in range(60):
        started = T0 + timedelta(days=i * 200 / 60, hours=rng.randrange(24), minutes=rng.randrange(60))
        ok = rng.randrange(5, 40)
        outcomes = {"success": ok, "relay_5xx": rng.randrange(0, 4), "rate_limited": rng.randrange(0, 3),
                    "relay_timeout": rng.randrange(0, 2), "network": rng.randrange(0, 2)}
        _save(
            started, watch_id=7 if i % 5 == 0 else None, outcomes=outcomes,
            base_url=urls[i % 4], model="model-a" if i % 3 else "model-b",
            score=None if i % 11 == 0 else float(rng.randrange(40, 100)),
            risk=None if i % 13 == 0 else rng.choice(("clean", "low", "high")),
            suite=rng.choice(("standard", "quick")), stream_mode=rng.choice(("stream", "non_stream")),
            api=rng.choice(("openai", "anthropic")),
            tool_version="0.10.0" if i < 20 else "0.11.0" if i < 45 else "0.10.0",
            kb_hash=None if i % 7 == 0 else "kb1" if i < 30 else "kb2",
            ttft=None if i % 6 == 0 else float(rng.randrange(100, 900)),
            tps=float(rng.randrange(10, 90)),
            billing=None if i % 9 == 0 else (rng.uniform(0.9, 1.3), rng.uniform(0.9, 1.3)),
            protocol=None if i % 8 == 0 else float(rng.randrange(50, 100)),
            api_auto=(None, True, False)[i % 3],
        )
    return data


# --------------------------------------------------------------------------- #
# URL schema and parser
# --------------------------------------------------------------------------- #
def test_parse_every_key():
    q = parse_query({
        "from": "2026-03-01", "to": "2026-03-08T00:00:00+02:00", "surface": "chat",
        "relay": ["b", "a", "b"], "model": "m", "suite": "-", "mode": "check", "api": "openai",
        "stream": "non_stream", "detect": "auto", "risk": "high", "min_score": "62.5",
        "exec": "monitor", "q": "50%_off", "group": "relay_model",
        "trend.metric": "score", "runs.after": "whatever",  # a widget's own: ignored
    })
    assert q.start == datetime(2026, 3, 1, tzinfo=UTC)
    assert q.end == datetime(2026, 3, 7, 22, tzinfo=UTC)
    assert q.relays == ("a", "b") and q.models == ("m",)
    assert (q.suite, q.mode, q.api, q.stream, q.detect, q.risk) == ("-", "check", "openai", "non_stream",
                                                                    "auto", "high")
    assert (q.min_score, q.exec, q.text, q.group) == (62.5, "monitor", "50%_off", "relay_model")
    canon = q.canonical()
    assert list(canon) == sorted(canon)
    assert canon["from"] == "2026-03-01T00:00:00.000000+00:00" and canon["relay"] == ["a", "b"]
    assert parse_query(q.params()) == q  # round trip
    assert parse_query({}) == Query() and Query().canonical() == {"group": "relay"}
    # Starlette's QueryParams (repeated keys) and plain pairs work alike
    from starlette.datastructures import QueryParams

    assert parse_query(QueryParams("relay=x&relay=y&q=+a+")).relays == ("x", "y")
    assert parse_query([("q", " a "), ("suite", "")]) == Query(text="a")


def test_range_resolves_to_absolute_bounds():
    q = parse_query({"range": "7d"}, now=NOW)
    assert q.end == datetime(2026, 6, 1, 12, 1, tzinfo=UTC)  # the next whole minute
    assert q.start == q.end - timedelta(days=7)
    assert "range" not in q.canonical() and q.canonical()["to"] == "2026-06-01T12:01:00.000000+00:00"
    assert parse_query({"range": "24h"}, now=NOW.replace(second=0)).end == NOW.replace(second=0)
    for r, delta in query.RANGES.items():
        q = parse_query({"range": r}, now=NOW)
        assert q.end - q.start == delta
    # the cache key form: range resolved, widget keys kept
    pairs = query.resolve_params([("range", "30d"), ("trend.metric", "score")], now=NOW)
    assert ("trend.metric", "score") in pairs and not any(k == "range" for k, _ in pairs)
    assert dict(pairs)["to"] == "2026-06-01T12:01:00.000000+00:00"
    bad = [("range", "1y")]
    assert query.resolve_params(bad) == bad  # left for the endpoint to reject


@pytest.mark.parametrize("params, message", [
    ({"color": "red"}, "unknown parameter 'color'"),
    ({"days": "7"}, "unknown parameter 'days'"),
    ({"suite": ["a", "b"]}, "suite given more than once"),
    ({"range": "1y"}, "range must be one of 24h, 7d, 30d, 90d, 365d"),
    ({"range": "7d", "from": "2026-01-01"}, "range cannot be combined"),
    ({"from": "yesterday"}, "from must be an ISO 8601 timestamp"),
    ({"to": "2026-13-01"}, "to must be an ISO 8601 timestamp"),
    ({"from": "2026-03-02", "to": "2026-03-01"}, "from must be before to"),
    ({"surface": "image"}, "surface must be one of chat, embedding, rerank"),
    ({"detect": "maybe"}, "detect must be one of auto, manual, -"),
    ({"risk": "critical"}, "risk must be one of clean, low, medium, high, inconclusive"),
    ({"min_score": "abc"}, "min_score must be a number from 0 to 100"),
    ({"min_score": "101"}, "min_score must be a number from 0 to 100"),
    ({"min_score": "nan"}, "min_score must be a number from 0 to 100"),
    ({"exec": "adhoc"}, "exec must be one of manual, monitor"),
    ({"group": "suite"}, "group must be one of relay, model, relay_model, all"),
    ({"q": "x" * 501}, "q is longer than 500 characters"),
    ({"relay": 5}, "relay must be a string"),
])
def test_invalid_parameters(params, message):
    with pytest.raises(QueryError, match=message.replace("(", r"\(")):
        parse_query(params)
    assert issubclass(QueryError, AnalyticsError)  # handlers answering 400 for it catch this too


# --------------------------------------------------------------------------- #
# Run selection
# --------------------------------------------------------------------------- #
def _ids(q: Query) -> set[int]:
    sel = query.select_runs(q)
    return {int(r[0]) for r in _conn().execute(f"SELECT m.history_id {sel.sql}", sel.args)}


def _expected(pred) -> set[int]:
    """The runs a Python predicate over the analytics rows (plus relay key) keeps."""
    resolver = analytics.RelayResolver()
    rows = reference.runs()
    full = {int(r["id"]): dict(r) for r in _conn().execute("SELECT * FROM history")}
    return {int(r["id"]) for r in rows
            if pred({**full[int(r["id"])], **r, "relay_key": resolver.resolve(r).key})}


def test_every_filter_in_sql(seeded):
    # older rows: no surface (reads as chat), no mode / suite / api / stream mode
    _write("UPDATE history SET surface = NULL WHERE id = 2")
    _write("UPDATE history SET mode = NULL, suite = '', api = NULL, stream_mode = NULL WHERE id IN (3, 4)")
    _write("UPDATE history SET surface = 'embedding' WHERE id = 5")
    _write("UPDATE history SET claimed_model = NULL WHERE id = 6")
    count = query.count_runs
    c = _conn()
    assert count(c, Query()) == 60
    cases = {
        "surface=chat": (Query(surface="chat"), lambda r: (r["surface"] or "chat") == "chat"),
        "surface=embedding": (Query(surface="embedding"), lambda r: r["surface"] == "embedding"),
        "relay": (Query(relays=("cheap-gpt",)), lambda r: r["relay_key"] == "cheap-gpt"),
        "relay x2": (Query(relays=("cheap-gpt", OTHER)), lambda r: r["relay_key"] in ("cheap-gpt", OTHER)),
        "model x2": (Query(models=("model-a", "model-b")), lambda r: r["claimed_model"] in ("model-a", "model-b")),
        "model unknown": (Query(models=("(unknown)",)), lambda r: not r["claimed_model"]),
        "suite": (Query(suite="quick"), lambda r: r["suite"] == "quick"),
        "suite -": (Query(suite="-"), lambda r: not r["suite"]),
        "mode": (Query(mode="check"), lambda r: r["mode"] == "check"),
        "mode -": (Query(mode="-"), lambda r: not r["mode"]),
        "api": (Query(api="anthropic"), lambda r: r["api"] == "anthropic"),
        "api -": (Query(api="-"), lambda r: not r["api"]),
        "stream": (Query(stream="non_stream"), lambda r: r["stream_mode"] == "non_stream"),
        "stream -": (Query(stream="-"), lambda r: not r["stream_mode"]),
        "detect auto": (Query(detect="auto"), lambda r: r["api_auto"] == 1),
        "detect manual": (Query(detect="manual"), lambda r: r["api_auto"] == 0),
        "detect -": (Query(detect="-"), lambda r: r["api_auto"] is None),
        "risk high": (Query(risk="high"), lambda r: r["risk_level"] == "high"),
        "risk inconclusive": (Query(risk="inconclusive"),
                              lambda r: (r["risk_level"] or "inconclusive") == "inconclusive"),
        "min_score": (Query(min_score=70.0), lambda r: r["score"] is not None and r["score"] >= 70),
        "exec manual": (Query(exec="manual"), lambda r: r["watch_id"] is None),
        "exec monitor": (Query(exec="monitor"), lambda r: r["watch_id"] is not None),
        "from/to": (parse_query({"from": "2026-04-01", "to": "2026-05-01"}),
                    lambda r: "2026-04-01" <= r["started_at"] < "2026-05-01"),
        "q": (Query(text="OPENAI.com"), lambda r: "openai.com" in (r["base_url"] or "")),
        "q label": (Query(text="cheap gpt"), lambda r: r["relay_key"] == "cheap-gpt"),
        "q %_": (Query(text="we%ird_r"), lambda r: r["base_url"] == SPECIAL),
        "combined": (Query(surface="chat", models=("model-a",), exec="manual", min_score=50.0),
                     lambda r: (r["surface"] or "chat") == "chat" and r["claimed_model"] == "model-a"
                     and r["watch_id"] is None and (r["score"] or -1) >= 50),
    }
    for name, (q, pred) in cases.items():
        want = _expected(pred)
        assert _ids(q) == want, name
        assert want or name in ("mode -",), f"{name} selects nothing: a weak test"
    # % and _ are literal, not wildcards
    assert _ids(Query(text="we_ird")) == set() and _ids(Query(text="%")) == _ids(Query(text="we%"))
    assert _ids(Query(text="\\")) == set()
    assert query.default_surface(c) == "chat"
    assert query.default_surface(c, Query(surface="chat", relays=("nope",))) == "chat"


# --------------------------------------------------------------------------- #
# Aggregation: the same values as the Python path, pooled rates on purpose not
# --------------------------------------------------------------------------- #
def _chat_metrics() -> list[str]:
    return [m.id for m in analytics.metrics_for("chat")] + ["dim:protocol"]


def _pooled_by_hand(group: str, metric: analytics.Metric) -> dict[str, float | None]:
    """Σ outcome counts ÷ Σ base per group, straight from history_outcomes."""
    resolver = analytics.RelayResolver()
    counts: dict[int, dict[str, int]] = {}
    for rid, outcome, n in _conn().execute("SELECT history_id, outcome, n FROM history_outcomes"):
        counts.setdefault(int(rid), {})[outcome] = counts.get(int(rid), {}).get(outcome, 0) + int(n)
    num: dict[str, int] = {}
    den: dict[str, int] = {}
    for run in reference.runs():
        run["_group"] = resolver.resolve(run)
        key = reference.group_of(group)(run)[0]
        c = counts.get(int(run["id"]), {})
        total = sum(c.values())
        base = total if metric.base == "requests_total" else total - sum(c.get(o, 0) for o in errorclass.IMPAIRED)
        if base > 0:
            num[key] = num.get(key, 0) + sum(c.get(o, 0) for o in metric.outcomes)
            den[key] = den.get(key, 0) + base
    return {k: num[k] / den[k] for k in den}


@pytest.mark.parametrize("group", analytics.GROUPS)
def test_aggregate_matches_the_python_path(seeded, group):
    mids = _chat_metrics()
    new = {g.key: g for g in query.aggregate(_conn(), Query(surface="chat"), mids, group, quantiles=True)}
    old = {row["key"]: row for row in reference.breakdown(mids, group)}
    assert list(new) == [r["key"] for r in sorted(old.values(), key=lambda r: (-r["runs"], r["label"].lower(), r["key"]))]
    changed = False
    for key, row in old.items():
        g = new[key]
        assert g.describe() == {k: row[k] for k in g.describe()}, key
        assert g.runs == row["runs"] and g.low_n == row["low_n"]
        for mid in mids:
            cell, want = g.metrics[mid], row["metrics"][mid]
            m = analytics.metric(mid)
            assert (cell.n, cell.coverage, cell.low_n) == (want["n"], want["coverage"], want["low_n"]), (key, mid)
            if m.agg == "pooled":
                # intended change (#118): Σ counts ÷ Σ base, not the median of per-run rates
                assert cell.value == pytest.approx(_pooled_by_hand(group, m).get(key), abs=1e-12)
                assert cell.numerator / cell.denominator == cell.value if cell.denominator else True
                changed |= cell.value != want["value"]
            else:
                assert (cell.value, cell.median, cell.p25, cell.p75) == (
                    want["value"], want["median"], want["p25"], want["p75"]), (key, mid)
    assert changed  # the pooled rates do differ from the old medians on this data


def test_pooled_rates_add_up_and_match_the_outcome_counts(seeded):
    c = _conn()
    for group in analytics.GROUPS:
        for q in (Query(), Query(surface="chat", exec="manual"), parse_query({"q": "openai"})):
            for g in query.aggregate(c, q, ["success_rate", "error_rate", "rate_limited_rate",
                                            "timeout_rate", "impaired_rate"], group):
                s, e, r = (g.metrics[k] for k in ("success_rate", "error_rate", "rate_limited_rate"))
                assert s.denominator == e.denominator == r.denominator
                if s.denominator:
                    assert s.numerator + e.numerator + r.numerator == s.denominator
                    assert s.value + e.value + r.value == pytest.approx(1.0, abs=1e-12)
                assert g.metrics["timeout_rate"].numerator <= e.numerator
    # the numerators recovered from rate x base are the history_outcomes counts
    every = query.aggregate(c, Query(), ["success_rate", "impaired_rate"], "all")[0]
    sums = dict(c.execute("SELECT outcome, SUM(n) FROM history_outcomes GROUP BY outcome").fetchall())
    assert every.metrics["success_rate"].numerator == sums["success"]
    assert every.metrics["impaired_rate"].numerator == sums.get("network", 0) + sums.get("local", 0)
    assert every.metrics["impaired_rate"].denominator == sum(sums.values())


def test_aggregate_edges(seeded):
    c = _conn()
    assert query.aggregate(c, Query(relays=("nope",)), ["score"], "all") == []
    assert query.aggregate(c, Query(relays=("nope",)), ["score"], "relay") == []
    (g,) = query.aggregate(c, Query(), [], "all")
    assert g.key == analytics.ALL_KEY and g.runs == 60 and g.metrics == {} and not g.low_n
    assert g.public()["first_run"] <= g.public()["last_run"]
    with pytest.raises(AnalyticsError, match="does not apply to the embedding surface"):
        query.aggregate(c, Query(surface="embedding"), ["ttft_p50"])
    with pytest.raises(AnalyticsError, match="unknown metric"):
        query.aggregate(c, Query(), ["nope"])
    with pytest.raises(QueryError, match="group must be one of"):
        query.aggregate(c, Query(), ["score"], "suite")
    pub = query.aggregate(c, Query(group="model"), ["score", "success_rate"])[0].public()
    assert pub["kind"] == "model" and set(pub["metrics"]["score"]) >= {"value", "n", "coverage", "low_n"}


# --------------------------------------------------------------------------- #
# n = 1: every aggregation of one run returns exactly its stored value
# --------------------------------------------------------------------------- #
def test_one_run_returns_its_stored_value_for_every_metric(data):
    report = json.loads((datadir.Path(__file__).parent / "fixtures" / "history_report.json").read_text())
    report["outcomes"] = from_counts({"complete": {"success": 7, "relay_5xx": 2, "rate_limited": 1,
                                                   "relay_timeout": 1, "network": 1}}).model_dump()
    rid = history.save(report)
    rng = random.Random(1)
    # give every per-run column a value (the report lacks some), awkward floats included
    cols = [m.column for m in analytics.METRICS.values() if m.agg != "pooled"
            and m.column in history.analytics_store.METRIC_COLS]
    stored = dict(_conn().execute("SELECT * FROM history_metrics WHERE history_id = ?", (rid,)).fetchone())
    for col in cols:
        if stored[col] is None:
            value = 1 if col == "model_mismatch" else round(rng.uniform(0.1, 999.0), 9) / 7
            _write(f"UPDATE history_metrics SET {col} = ? WHERE history_id = ?", (value, rid))
    _write("UPDATE history SET score = ? WHERE id = ?", (100 / 3, rid))
    _write("INSERT OR REPLACE INTO history_dimensions VALUES (?, 'dimension', 'odd', ?, 'pass', 1.0)",
           (rid, 0.1 + 0.2))
    run = reference.runs()[0]
    run["_dims"] = {"odd": 0.1 + 0.2}
    c = _conn()
    ids = [*analytics.METRICS, "dim:odd", "dim:missing"]
    # the native path only where this SQLite build has median()/percentile()
    for native in ((True, False) if query._has_native() else (False,)):
        query._native = native
        try:
            for group in analytics.GROUPS:
                (g,) = query.aggregate(c, Query(), ids, group, quantiles=True)
                assert g.runs == 1
                for mid in ids:
                    m, cell = analytics.metric(mid), g.metrics[mid]
                    want = reference.run_value(m, run)
                    assert cell.value == want, (mid, native, group)
                    assert cell.n == (want is not None) and cell.low_n
                    if m.agg == "median":
                        assert cell.median == cell.p25 == cell.p75 == want
                    if m.agg == "pooled" and want is not None:
                        assert cell.value == run[m.column]
                    if mid not in ("dim:missing",):
                        assert want is not None, f"{mid}: the run should have a value"
                (s,) = query.series(c, Query(), "score", group, "day", quantiles=True).series
                assert s.points[0].cell.value == run["score"] == 100 / 3
        finally:
            query._native = None


# --------------------------------------------------------------------------- #
# median / percentile fallback
# --------------------------------------------------------------------------- #
def test_fallback_aggregates_match_native(seeded):
    if not query._has_native():
        pytest.skip("this SQLite build has no native median()/percentile() to compare against")
    c = _conn()
    assert query.sql_functions(c) == ("median", "percentile")
    mids = _chat_metrics()

    def run():
        return (
            [g.public() for grp in analytics.GROUPS
             for g in query.aggregate(c, Query(surface="chat"), mids, grp, quantiles=True)],
            [query.series(c, Query(surface="chat"), "ttft_p50", "relay", b, "Europe/Berlin",
                          quantiles=True).public() for b in analytics.BUCKETS],
        )

    rng = random.Random(3)
    values = json.dumps([rng.uniform(-1e6, 1e6) for _ in range(101)])
    ordered = sorted(json.loads(values))
    native = run()
    query._native = False
    try:
        assert query.sql_functions(c) == ("ekte_median", "ekte_percentile")
        assert run() == native
        for p in (0, 1, 25, 50, 75, 99.5, 100):
            row = c.execute(f"SELECT ekte_percentile(value, {p}), ekte_median(value),"
                            f" percentile(value, {p}), median(value) FROM json_each(?)",
                            (values,)).fetchone()
            assert row[0] == row[2] == analytics.percentile(ordered, p / 100)
            assert row[1] == row[3] == analytics.percentile(ordered, 0.5)
    finally:
        query._native = None


def test_fallback_when_the_build_lacks_median(monkeypatch):
    real = query.sqlite3.connect

    class NoMedian:
        def __init__(self):
            self.conn = real(":memory:")

        def execute(self, sql, *a):
            if "median" in sql:
                raise query.sqlite3.OperationalError("no such function: median")
            return self.conn.execute(sql, *a)

        def close(self):
            self.conn.close()

    monkeypatch.setattr(query, "_native", None)
    monkeypatch.setattr(query.sqlite3, "connect", lambda *a, **k: NoMedian())
    assert query._has_native() is False
    monkeypatch.setattr(query.sqlite3, "connect", real)
    c = real(":memory:")
    assert query.sql_functions(c) == ("ekte_median", "ekte_percentile")
    assert c.execute("SELECT ekte_median(x), ekte_percentile(x, 25) FROM (SELECT 1 AS x UNION ALL"
                     " SELECT 2 UNION ALL SELECT NULL UNION ALL SELECT 4)").fetchone() == (2.0, 1.5)
    assert c.execute("SELECT ekte_median(x) FROM (SELECT NULL AS x)").fetchone() == (None,)


# --------------------------------------------------------------------------- #
# Time series: the same buckets and values as the Python path
# --------------------------------------------------------------------------- #
_POINT_KEYS = ("bucket", "dow", "hour", "hours", "week", "runs", "value", "median", "p25", "p75", "n",
               "low_n")


def _compare_series(params: dict, **kw) -> None:
    tz = params.get("tz", "UTC")
    old = reference.series(params.get("metric", "score"), params.get("group") or "relay",
                           params.get("bucket", "day"), ZoneInfo(tz), tz,
                           block=int(params.get("block", 1)), fold=params.get("fold", "week"))
    new = query.series(_conn(), Query(surface="chat"), params.get("metric", "score"), params.get("group"),
                       params.get("bucket", "day"), kw.pop("tz", "UTC"), quantiles=True, **kw).public()
    for k in ("bucket", "block", "fold", "fold_requested", "span_days", "tz", "group", "metric"):
        assert new[k] == old[k], (k, params)
    assert [s["key"] for s in new["series"]] == [s["key"] for s in old["series"]]
    for a, b in zip(new["series"], old["series"], strict=True):
        for k in ("key", "label", "kind", "in_kb", "runs", "n", "coverage", "mixed", "annotations"):
            assert a[k] == b[k], (k, a["key"], params)
        assert [{k: p.get(k) for k in _POINT_KEYS} for p in a["points"]] == [
            {k: p.get(k) for k in _POINT_KEYS} for p in b["points"]], (a["key"], params)


@pytest.mark.parametrize("bucket", analytics.BUCKETS)
@pytest.mark.parametrize("group", analytics.GROUPS)
def test_series_matches_the_python_path(seeded, bucket, group):
    for tz in ("UTC", "Europe/Berlin", "America/St_Johns", "Asia/Kathmandu"):
        for metric in ("score", "ttft_p50", "risk_high_share", "dim:protocol"):
            _compare_series({"metric": metric, "group": group, "bucket": bucket, "tz": tz}, tz=tz)


def test_series_blocks_folds_keys_and_offsets(seeded):
    for fold in analytics.FOLDS:
        for block in analytics.BLOCKS:
            _compare_series({"metric": "score", "bucket": "dow_hour", "block": str(block), "fold": fold,
                             "tz": "Europe/Berlin"}, tz="Europe/Berlin", block=block, fold=fold)
    # a fixed offset, and keys given (one without runs)
    keys = [OTHER, "cheap-gpt", "nope"]
    zone = timezone(timedelta(minutes=-330))
    old = reference.series("score", "relay", "day", zone, str(zone), keys=keys)
    new = query.series(_conn(), Query(surface="chat"), "score", "relay", "day", zone,
                       keys=keys).public()
    assert new["tz"] == old["tz"] and [s["key"] for s in new["series"]] == keys
    for a, b in zip(new["series"], old["series"], strict=True):
        assert (a["runs"], a["n"], [p["bucket"] for p in a["points"]]) == (
            b["runs"], b["n"], [p["bucket"] for p in b["points"]])
    assert new["series"][2]["runs"] == 0 and new["series"][2]["points"] == []
    # pooled per bucket
    s = query.series(_conn(), Query(), "error_rate", "all", "week").series[0]
    assert all(p.cell.denominator and p.cell.value == p.cell.numerator / p.cell.denominator
               for p in s.points)
    assert sum(p.cell.numerator for p in s.points) == query.aggregate(
        _conn(), Query(), ["error_rate"], "all")[0].metrics["error_rate"].numerator
    with pytest.raises(QueryError, match="at most 4 keys"):
        query.series(_conn(), Query(), "score", keys=["a", "b", "c", "d", "e"])
    for kw, message in (({"bucket": "month"}, "bucket must be one of"), ({"block": 5}, "block must be one of"),
                        ({"fold": "year"}, "fold must be one of"), ({"tz": "Mars/Olympus"}, "unknown time zone")):
        with pytest.raises(QueryError, match=message):
            query.series(_conn(), Query(), "score", **kw)
    assert query.series(_conn(), Query(relays=("nope",)), "score").series == []


def test_offset_sql_is_exact_across_transitions():
    zone = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = [start + timedelta(days=7 * i) for i in range(53)]
    sql = query.offset_sql(zone, points, "t")
    c = query.sqlite3.connect(":memory:")
    for t in (datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC), datetime(2026, 3, 29, 1, tzinfo=UTC),
              datetime(2026, 10, 25, 0, 59, 59, tzinfo=UTC), datetime(2026, 10, 25, 1, tzinfo=UTC),
              datetime(2026, 7, 1, tzinfo=UTC)):
        got = c.execute(f"SELECT {sql} FROM (SELECT ? AS started_us) t", (query.us_of(t),)).fetchone()[0]
        assert got == t.astimezone(zone).utcoffset().total_seconds()
    assert query.offset_sql(UTC, points) == "0" and query.offset_sql(zone, []) == "0"
    # far apart points (days with runs only): the change goes to the later one
    sparse = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)]
    assert f"m.started_us < {query.us_of(sparse[1])} " in query.offset_sql(zone, sparse)


def test_series_with_a_damaged_far_future_run(seeded):
    _save(datetime(5000, 1, 1, tzinfo=UTC), base_url=OTHER)
    out = query.series(_conn(), Query(surface="chat"), "score", "relay", "day", "Europe/Berlin").public()
    _compare_series({"metric": "score", "group": "relay", "tz": "Europe/Berlin"}, tz="Europe/Berlin")
    assert any(p["bucket"].startswith("5000-01-01") for s in out["series"] for p in s["points"])


# --------------------------------------------------------------------------- #
# Keyset paging
# --------------------------------------------------------------------------- #
_RISK = {"high": 4, "medium": 3, "low": 2, "clean": 1}
_GRADE = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}


def _walk(q: Query, sort: str, limit: int) -> list[int]:
    out, after, pages = [], None, 0
    while True:
        page = query.page_runs(_conn(), q, sort, after, limit)
        assert len(page.rows) <= limit and page.sort == sort
        out += [int(r["id"]) for r in page.rows]
        pages += 1
        after = page.after
        if after is None:
            return out
        assert pages < 1000


@pytest.mark.parametrize("sort", ["time", "-time", "score", "-score", "risk", "-risk", "grade", "-grade"])
def test_page_runs_walks_every_run_once_in_order(seeded, sort):
    _write("UPDATE history SET rating = CASE WHEN score >= 90 THEN 'A' WHEN score >= 70 THEN 'C'"
           " WHEN score IS NULL THEN NULL ELSE 'F' END")
    _write("UPDATE history_metrics SET started_at = NULL WHERE history_id IN (3, 9)")
    rows = {int(r["id"]): dict(r) for r in _conn().execute(
        "SELECT h.*, m.started_at FROM history h JOIN history_metrics m ON m.history_id = h.id")}
    key = sort.lstrip("-")

    def value(r):
        return {"time": r["started_at"], "score": r["score"], "risk": _RISK.get(r["risk_level"], 0),
                "grade": _GRADE.get(r["rating"], 0)}[key]

    desc = sort.startswith("-")
    # NULLs first ascending, last descending; ties by id in the same direction
    want = sorted(rows, key=lambda i: (value(rows[i]) is not None, value(rows[i]) or 0, i), reverse=desc)
    if key == "time":
        want = sorted(rows, key=lambda i: (rows[i]["started_at"] is not None, rows[i]["started_at"] or "", i),
                      reverse=desc)
    for limit in (1, 7, 200):
        assert _walk(Query(), sort, limit) == want, limit
    chat = Query(surface="chat", models=("model-a",))
    assert _walk(chat, sort, 5) == [i for i in want if rows[i]["claimed_model"] == "model-a"]


def test_page_rows_cursor_and_limits(seeded):
    page = query.page_runs(_conn(), Query(), "-time", limit=3)
    row = page.rows[0]
    assert set(row) == {c.split(" AS ")[-1].split(".")[-1] for c in query.PAGE_COLUMNS}
    assert row["relay_key"] and row["surface"] == "chat" and "report_json" not in row
    assert query.page_runs(_conn(), Query()).public()["sort"] == "-time"
    assert len(query.page_runs(_conn(), Query()).rows) == query.PAGE_LIMIT
    # a run saved while paging neither repeats nor shifts the next page
    second = query.page_runs(_conn(), Query(), "-time", page.after, 3)
    _save(T0 + timedelta(days=400))
    again = query.page_runs(_conn(), Query(), "-time", page.after, 3)
    assert [r["id"] for r in again.rows] == [r["id"] for r in second.rows]
    for after, message in (("garbage!", "not a valid cursor"), (page.after, "not a cursor of this sort")):
        with pytest.raises(QueryError, match=message):
            query.page_runs(_conn(), Query(), "score" if after == page.after else "-time", after)
    for limit in (0, 201, True, "5"):
        with pytest.raises(QueryError, match="limit must be from 1 to 200"):
            query.page_runs(_conn(), Query(), limit=limit)  # type: ignore[arg-type]
    with pytest.raises(QueryError, match="sort must be one of"):
        query.page_runs(_conn(), Query(), "label")


# --------------------------------------------------------------------------- #
# The benchmark fixture
# --------------------------------------------------------------------------- #
def _bench_module():
    import importlib.util

    path = datadir.Path(__file__).resolve().parent.parent / "scripts" / "bench_fixture.py"
    spec = importlib.util.spec_from_file_location("bench_fixture", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bench_fixture_builds_a_consistent_history(data):
    bench = _bench_module()
    assert bench.build(runs=400, relays=6, requests=50, report_bytes=5000) == 400
    c = _conn()
    assert query.count_runs(c, Query()) == 400
    assert c.execute("SELECT COUNT(*) FROM history WHERE requests_split IS NULL").fetchone()[0] == 0
    (g,) = query.aggregate(c, Query(), ["success_rate", "error_rate", "rate_limited_rate"], "all")
    sums = dict(c.execute("SELECT outcome, SUM(n) FROM history_outcomes GROUP BY outcome").fetchall())
    assert g.metrics["success_rate"].numerator == sums["success"]
    assert sum(g.metrics[k].numerator for k in ("success_rate", "error_rate", "rate_limited_rate")) == \
        g.metrics["success_rate"].denominator
    assert 0.8 < g.metrics["success_rate"].value < 1
    assert len(query.aggregate(c, Query(), ["score"], "relay")) == 6
    for name, fn in bench.cases(c).items():
        assert fn(c) is not None, name
    # the selections read history through its covering index, never its rows
    sel = query.select_runs(parse_query({"surface": "chat", "q": "relay", "exec": "manual",
                                         "detect": "auto", "min_score": "50", "suite": "-"}))
    plan = " ".join(r[3] for r in c.execute(f"EXPLAIN QUERY PLAN SELECT m.history_id {sel.sql}", sel.args))
    assert "COVERING INDEX idx_history_query" in plan
    assert math.isfinite(bench.bench(repeat=1)["page_runs -time"][1])


def test_bench_queries_group_on_the_run_row(data):
    """What keeps the 20k-run budget, checked on a small fixture: no
    benchmarked query looks a run up in relay_map (runs carry their relay id),
    and the annotations, read from the series buckets, still equal the Python
    path's on runs whose versions change and roll out (several per bucket)."""
    bench = _bench_module()
    bench.build(runs=600, relays=5, requests=10, report_bytes=100)
    c = _conn()
    assert c.execute("SELECT COUNT(*) FROM history_metrics WHERE relay_id IS NULL").fetchone()[0] == 0
    sqls: list[str] = []
    c.set_trace_callback(sqls.append)
    try:
        for fn in bench.cases(c).values():
            fn(c)
    finally:
        c.set_trace_callback(None)
    selects = [s for s in sqls if s.lstrip().upper().startswith(("SELECT", "WITH"))]
    assert len(selects) > 10
    for sql in selects:
        plan = " ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql))
        assert "relay_map" not in plan, sql
    for group in ("relay", "model", "relay_model", "all"):
        for bucket in ("day", "week", "hour"):
            _compare_series({"metric": "score", "group": group, "bucket": bucket,
                             "tz": "America/New_York"}, tz="America/New_York")
    s = query.series(c, Query(surface="chat"), "score", "relay", "week")
    kinds = {a["kind"] for x in s.series for a in x.annotations}
    assert kinds == {"tool_version", "kb_profile"}


_READS_HISTORY = re.compile(r"\b(?:SCAN|SEARCH) (?:h|history)\b(?! USING INTEGER PRIMARY KEY)")
_EKTE_CHECKS = ("SELECT EXISTS (SELECT id FROM history WHERE requests_split IS NULL",)


def test_no_aggregation_reads_history(data):
    """Issue #145: every statement the benchmarked query core, Analytics and
    History calls run reads the run rows (history_metrics) only; history is
    read just for page rows, by id (one primary-key lookup per row shown),
    and for free-text search (through its covering index)."""
    from ekte.web import analytics_widgets, history_api
    from tests.test_analytics_widgets import WIDGET_CASES

    bench = _bench_module()
    bench.build(runs=600, relays=5, requests=10, report_bytes=100)
    c = _conn()
    t = {"trend.metrics": "score,latency_p50"}
    calls = [*((lambda fn=fn: fn(c)) for fn in bench.cases(c).values()),
             *((lambda fn=fn, p=p: fn(p)) for _, fn, p in WIDGET_CASES)]
    for group in ("relay", "model", "relay_model", "all"):
        for sort in ("-time", "score", "-risk", "grade"):
            calls.append(lambda g=group, s=sort: history_api.groups(
                c, {**t, "group": g, "groups.sort": s, "groups.focus": "7"}))
        key = history_api.groups(c, {**t, "group": group})["groups"][0]["key"]
        calls.append(lambda g=group, k=key: history_api.runs(
            c, {"group": g, "group.key": k, "runs.sort": "-grade", "runs.focus": "5"}))
    calls.append(lambda: analytics_widgets.widget_heatmap({"heat.fold": "4weeks", "suite": "quick",
                                                           "relay": "https://relay-01.example/v1"}))
    sqls: list[str] = []
    c.set_trace_callback(sqls.append)
    try:
        for call in calls:
            call()
    finally:
        c.set_trace_callback(None)
    selects = {s for s in sqls if s.lstrip().upper().startswith(("SELECT", "WITH"))
               and not s.startswith(_EKTE_CHECKS)}
    assert len(selects) > 50
    for sql in selects:
        plan = "\n".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql))
        assert not _READS_HISTORY.search(plan), (sql, plan)
    # free-text search reads history through its covering index, and only then
    sel = query.select_runs(parse_query({"q": "relay-0"}))
    plan = "\n".join(r[3] for r in c.execute(f"EXPLAIN QUERY PLAN SELECT COUNT(*) {sel.sql}", sel.args))
    assert "SEARCH h USING COVERING INDEX idx_history_query" in plan
    # relay and relay x model groups are read in index order: no sort
    for group in ("relay", "relay_model"):
        sql = f"SELECT COUNT(*) FROM history_metrics m GROUP BY {run_row.GROUP_BY_SQL[group]}"
        plan = "\n".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql))
        assert "COVERING INDEX idx_run_row" in plan and "TEMP B-TREE" not in plan, plan


def test_annotations_of_interleaved_values_and_equal_times(data):
    """Versions and profiles that alternate, repeat, go missing and change
    between runs started at the same instant: the annotations still equal the
    Python path's (one run compared with the previous one)."""
    rng = random.Random(3)
    for i in range(90):
        started = T0 + timedelta(hours=(i // 3) * 7 + rng.randrange(3))  # equal times
        _save(started, base_url=(RELAY, OTHER)[i % 2], model=("model-a", "model-b")[i % 3 == 0],
              tool_version=rng.choice(("0.1.0", "0.2.0", "0.2.0", "0.3.0", None)),
              kb_hash=rng.choice(("kb1", "kb1", "kb2", None)))
    for group in ("relay", "model", "relay_model", "all"):
        for bucket in ("hour", "day", "week"):
            _compare_series({"metric": "score", "group": group, "bucket": bucket})
    s = query.series(_conn(), Query(surface="chat"), "score", "all", "week")
    kinds = [a["kind"] for a in s.series[0].annotations]
    assert kinds.count("tool_version") > 20 and kinds.count("kb_profile") > 10


def test_buckets_without_unixepoch(seeded):
    """SQLite before 3.38 (no unixepoch()) buckets alike: the run row's start
    time is made with strftime(), and buckets are integer arithmetic on it."""
    sql = " ".join([*(run_row._value_sql(d) for _, d in run_row.RUN_COLUMNS.values()),
                    *(b for size in analytics.BUCKETS for b in query._bucket_sql(size, "0", 1, "4weeks"))])
    assert "unixepoch(" not in sql  # (the 'unixepoch' modifier of strftime() is older)
    for bucket in analytics.BUCKETS:
        _compare_series({"metric": "score", "group": "relay", "bucket": bucket,
                         "tz": "Europe/Berlin"}, tz="Europe/Berlin")


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_benchmark_20k_runs_under_budget(data):
    """aggregate, series and page_runs each answer within the budget (p95) on
    the 20k-run fixture. Opt-in (EKTE_BENCH=1): timings need a quiet machine;
    EKTE_BENCH_BUDGET_MS overrides the 50 ms budget."""
    import os

    if os.environ.get("EKTE_BENCH") != "1":
        pytest.skip("set EKTE_BENCH=1 to run the 20k-run benchmark")
    budget = float(os.environ.get("EKTE_BENCH_BUDGET_MS", "50"))
    bench = _bench_module()
    bench.build()
    results = bench.bench()
    slow = {name: round(p95, 1) for name, (_, p95) in results.items() if p95 >= budget}
    assert not slow, f"p95 over {budget} ms: {slow}"
