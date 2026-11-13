#!/usr/bin/env python3
"""A synthetic ``history.db`` for benchmarking the query core (ekte/web/query.py).

Writes ``--runs`` runs (default 20,000) over ``--relays`` relays (default 50)
and a year of start times into the history database of ``--data-dir`` (or
``$EKTE_DATA_DIR``), straight into the tables (``history``,
``history_metrics``, ``history_outcomes``, ``history_dimensions``) as the
analytics extraction leaves them, so nothing needs backfilling. Every run has
``--requests`` target requests (default 100) with an outcome mix like real
runs (mostly successes, a few 429s, relay errors and network failures).
Deterministic for a ``--seed``. It also writes ``--monitors`` monitors
(default 200; ``--watches`` is the old name) into ``watches.db``, over the
same relays and models, with mixed states, thresholds and last risks.

With ``--bench`` it then times :func:`ekte.web.query.aggregate`,
:func:`~ekte.web.query.series` and :func:`~ekte.web.query.page_runs` and
prints each one's p50 / p95 in milliseconds (``tests/test_query.py``
checks the 50 ms p95 budget)::

    python scripts/bench_fixture.py --data-dir /tmp/bench --bench
"""

from __future__ import annotations

import argparse
import gc
import math
import os
import random
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# fixed: the fixture is the same whenever it is built
END = datetime(2026, 11, 1, tzinfo=UTC)
MODELS = ("gpt-4o", "gpt-4o-mini", "claude-sonnet", "claude-haiku", "gemini-pro", "deepseek-v3",
          "qwen-max", "llama-70b")
SUITES = ("standard", "quick", "deep")
APIS = ("openai", "anthropic", "responses")
STREAMS = ("stream", "non_stream", "both")
# bytes of each run's report_json
REPORT_BYTES = 16_000
# outcome -> weight per request (success dominates, as in real runs)
MIX = {"success": 0.93, "rate_limited": 0.02, "relay_5xx": 0.02, "relay_timeout": 0.01,
       "relay_4xx": 0.01, "relay_other": 0.002, "network": 0.006, "local": 0.002}


def _outcomes(rng: random.Random, requests: int, flaky: float) -> dict[str, int]:
    """Outcome counts of one run; ``flaky`` scales the failures of a relay."""
    weights = [w if o == "success" else w * flaky for o, w in MIX.items()]
    counts = dict.fromkeys(MIX, 0)
    for o in rng.choices(list(MIX), weights=weights, k=requests):
        counts[o] += 1
    return counts


# a new ekte version every RELEASE (at 13:37 UTC), every ROLLBACK_EVERY-th
# one taken back for its second day; a knowledge-base profile change every
# KB_EVERY; KB_UNKNOWN of the runs have no profile hash
RELEASE = timedelta(days=21)
ROLLBACK_EVERY = 4
KB_EVERY = timedelta(days=45)
KB_UNKNOWN = 0.02
_SINCE = END - timedelta(days=365, hours=13, minutes=37)


def _version(started: datetime) -> str:
    """The ekte version of a run started at ``started`` (annotated changes)."""
    n, into = divmod(started - _SINCE, RELEASE)
    if n % ROLLBACK_EVERY == 1 and timedelta(days=1) <= into < timedelta(days=2):
        n -= 1
    return f"0.{20 + n}.0"


def _kb_hash(rng: random.Random, started: datetime) -> str | None:
    if rng.random() < KB_UNKNOWN:
        return None
    return f"kb{(started - _SINCE) // KB_EVERY}"


# monitor states of the fixture (ekte/web/watches_api.py): active, paused,
# draft (scheduled from History: no interval, never run, not enabled)
MONITOR_STATES = {"active": 0.7, "paused": 0.2, "draft": 0.1}
# alert thresholds and last risks (None: not run yet, or no result)
THRESHOLDS = {"low": 0.2, "medium": 0.6, "high": 0.2}
LAST_RISKS = {"clean": 0.5, "low": 0.15, "medium": 0.12, "high": 0.08, "inconclusive": 0.05, None: 0.1}
# a run window on some monitors (weekdays, office hours)
WINDOW = '{"tz": "Europe/Berlin", "days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00"}'


def build_watches(watches: int = 200, relays: int = 50, seed: int = 0) -> int:
    """Write ``watches`` monitors into ``$EKTE_DATA_DIR``'s ``watches.db``
    (adding to what is there), straight into the table as
    :func:`ekte.web.watches.create` leaves it, spread over the relays and
    models of the runs, with mixed states (:data:`MONITOR_STATES`), alert
    thresholds and last risks; deterministic for ``seed``. Returns the number
    written. Their API keys are ``env:`` references (no secret)."""
    from ekte import datadir
    from ekte.web import watches as store

    rng = random.Random(seed + 1)
    t_end = END.timestamp()
    rows = []
    for i in range(watches):
        r = rng.randrange(relays)
        model = MODELS[rng.randrange(len(MODELS))]
        state = rng.choices(list(MONITOR_STATES), list(MONITOR_STATES.values()))[0]
        alert_on = rng.choices(list(THRESHOLDS), list(THRESHOLDS.values()))[0]
        surface = rng.choices(("chat", "embedding", "rerank"), (0.9, 0.07, 0.03))[0]
        draft = state == "draft"
        risk = None if draft else rng.choices(list(LAST_RISKS), list(LAST_RISKS.values()))[0]
        rows.append((
            f"monitor {i:03d}", f"https://relay-{r:02d}.example/v1",
            "" if draft else "env:EKTE_BENCH_KEY", model, model,
            APIS[rng.randrange(len(APIS))] if rng.random() < 0.3 else "auto",
            SUITES[rng.randrange(len(SUITES))],
            None if draft else rng.choice((1800, 3600, 21600, 86400)), alert_on, "[]",
            int(state == "active"), t_end - 86400 * 30,
            None if draft else t_end - rng.randrange(86400), risk,
            None if risk is None else round(rng.uniform(40, 100), 1), surface,
            int(rng.random() < 0.8), 1, i + 1 if draft else None,
            WINDOW if not draft and rng.random() < 0.1 else None,
        ))
    with datadir.connect("watches.db", store.MIGRATIONS) as conn:
        conn.executemany(
            "INSERT INTO watches (name, base_url, api_key, model, claimed_model, api, suite,"
            " interval_sec, alert_on, webhooks, enabled, created_ts, last_run_ts, last_risk,"
            " last_score, surface, performance_streaming, evidence, source_report_id, run_window)"
            f" VALUES ({', '.join('?' * 20)})", rows)
        conn.execute(store._BUMP_SQL)
    return watches


def build(runs: int = 20_000, relays: int = 50, requests: int = 100, seed: int = 0,
          report_bytes: int = REPORT_BYTES, watches: int = 200) -> int:
    """Write the fixture into ``$EKTE_DATA_DIR``'s ``history.db`` (adding to
    what is there), and ``watches`` monitors into its ``watches.db``
    (:func:`build_watches`); returns the number of runs written.
    ``report_bytes``: the size of each stored report (real ones, request
    records split off, are 15-50 kB, so most of a run's row lives in overflow
    pages)."""
    from ekte import datadir
    from ekte.knowledge.relays import normalize_url
    from ekte.perf.outcomes import from_counts
    from ekte.web import analytics_store, history

    rng = random.Random(seed)
    urls = [f"https://relay-{i:02d}.example/v1" for i in range(relays)]
    flaky = [rng.uniform(0.2, 4.0) for _ in urls]
    speed = [rng.uniform(0.6, 1.6) for _ in urls]
    h_rows, m_rows, o_rows, d_rows = [], [], [], []
    span = 365 * 86400
    report = '{"pad": "' + "x" * max(0, report_bytes - 11) + '"}'
    with datadir.connect("history.db", history.MIGRATIONS) as conn:
        first = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM history").fetchone()[0]) + 1
        for rid in range(first, first + runs):
            r = rng.randrange(relays)
            url = urls[r]
            model = MODELS[rng.randrange(len(MODELS))]
            surface = rng.choices(("chat", "embedding", "rerank"), (0.9, 0.07, 0.03))[0]
            started = END - timedelta(seconds=rng.randrange(span))
            score = round(min(100.0, max(0.0, rng.gauss(82, 9))), 1)
            risk = rng.choices(("clean", "low", "medium", "high", "inconclusive"),
                               (0.6, 0.2, 0.1, 0.05, 0.05))[0]
            rating = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else \
                "D" if score >= 60 else "F"
            watch = rng.randrange(1, 6) if rng.random() < 0.3 else None
            chat = surface == "chat"
            latency = rng.lognormvariate(6.5, 0.4) * speed[r]
            ttft = rng.lognormvariate(5.8, 0.4) * speed[r] if chat else None
            tps = rng.uniform(20, 120) / speed[r] if chat else None
            out = from_counts({"complete": _outcomes(rng, requests, flaky[r])})
            api = APIS[rng.randrange(len(APIS))] if rng.random() > 0.05 else None
            h_rows.append((
                rid, (started + timedelta(minutes=3)).isoformat(), url, model, model, "check",
                SUITES[rng.randrange(len(SUITES))], risk, score, rating, report, "match", watch, api,
                None if api is None else int(rng.random() < 0.7), STREAMS[rng.randrange(3)],
                surface, 0,
            ))
            m_rows.append((
                rid, analytics_store.format_ts(started), 0, _version(started),
                _kb_hash(rng, started), None, model,
                normalize_url(url), rng.uniform(60, 600), out.success_rate, out.error_rate,
                out.timeout_rate, out.rate_limited_rate, out.impaired_rate, out.requests_total,
                out.requests_judged, latency, latency * 1.8, ttft, ttft and ttft * 2.0, tps,
                tps and tps * 0.7, tps and tps * 1.2,
                rng.uniform(1, 2.0) if chat else None, rng.uniform(5, 50), rng.uniform(5, 80),
                rng.uniform(100, 2000), tps and tps * 4,
                rng.uniform(0.95, 1.3) if chat else None, rng.uniform(0.95, 1.3) if chat else None,
                None, None, int(rng.random() < 0.04), "pass", None, None,
                rng.randrange(0, 2), rng.randrange(0, 3), rng.randrange(0, 5),
                analytics_store.EXTRACT_VERSION,
            ))
            o_rows.extend((rid, op, kind, n) for op, c in out.by_op.items() for kind, n in c.items())
            d_rows.append((rid, "dimension", "protocol", round(rng.uniform(60, 100), 1), "pass", 8.0))
            d_rows.append((rid, "dimension", "identity", round(rng.uniform(40, 100), 1), "pass", 10.0))
        h_cols = ("id, ts, base_url, claimed_model, model, mode, suite, risk_level, score, rating,"
                  " report_json, kb_match, watch_id, api, api_auto, stream_mode, surface,"
                  " requests_split")
        conn.executemany(f"INSERT INTO history ({h_cols}) VALUES ({', '.join('?' * 18)})", h_rows)
        m_cols = ("history_id", *analytics_store.METRIC_COLS)
        assert len(m_cols) == len(m_rows[0]) if m_rows else True
        conn.executemany(
            f"INSERT INTO history_metrics ({', '.join(m_cols)}) VALUES ({', '.join('?' * len(m_cols))})",
            m_rows)
        conn.executemany("INSERT INTO history_outcomes VALUES (?, ?, ?, ?)", o_rows)
        conn.executemany("INSERT INTO history_dimensions VALUES (?, ?, ?, ?, ?, ?)", d_rows)
        conn.execute(history._BUMP_SQL)
    if watches:
        build_watches(watches, relays, seed)
    return runs


def times(fn: Callable[[], Any], repeat: int = 40) -> list[float]:
    """The times (ms, sorted) of ``repeat`` calls after one warm-up call.

    Before the calls every object is collected and the survivors frozen
    (``gc.freeze()``), so a full collection during the calls does not scan the
    caller's long-lived objects (a test session's heap): its pause, not the
    code, set the p95 of the slowest cases. The garbage collector stays on, so
    collections of the call's own objects are still timed."""
    gc.collect()
    gc.freeze()
    try:
        fn()
        out = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            fn()
            out.append((time.perf_counter() - t0) * 1000)
    finally:
        gc.unfreeze()
    return sorted(out)


def p95(sorted_ms: list[float]) -> float:
    """Nearest rank: the smallest time at least 95 % of the calls took no longer than."""
    return sorted_ms[math.ceil(len(sorted_ms) * 0.95) - 1]


def _time(fn: Callable[[], Any], repeat: int) -> tuple[float, float]:
    """p50 and p95 (ms) of ``repeat`` calls after one warm-up call."""
    t = times(fn, repeat)
    return statistics.median(t), p95(t)


def cases(conn: Any) -> dict[str, Callable[[Any], Any]]:
    """The benchmarked calls, by name: each takes a query connection."""
    from ekte.web import query

    deep = [_after(conn, query.Query(), "-time", 49)]
    every = query.Query()
    chat = query.Query(surface="chat")
    kpis = ("score", "risk_high_share", "success_rate", "error_rate", "rate_limited_rate",
            "latency_p50", "ttft_p50", "decode_tps", "billing_ratio_prompt",
            "billing_ratio_completion")
    return {
        "aggregate kpis, all": lambda c: query.aggregate(c, chat, kpis, "all"),
        "aggregate kpis, by relay": lambda c: query.aggregate(c, chat, kpis, "relay"),
        "aggregate kpis, by relay x model": lambda c: query.aggregate(c, chat, kpis, "relay_model"),
        "aggregate 30d, filtered": lambda c: query.aggregate(
            c, query.parse_query({"range": "30d", "surface": "chat", "exec": "manual",
                                  "q": "relay-0"}, now=END), kpis),
        "series score, day, 4 relays": lambda c: query.series(c, chat, "score", "relay", "day",
                                                               "Europe/Berlin"),
        "series error_rate, week": lambda c: query.series(c, chat, "error_rate", "model", "week",
                                                          "America/New_York"),
        "series latency, dow_hour": lambda c: query.series(c, chat, "latency_p50", "all",
                                                           "dow_hour", "Asia/Shanghai", block=2),
        "page_runs -time": lambda c: query.page_runs(c, every, "-time"),
        "page_runs -time, page 50": lambda c: query.page_runs(c, every, "-time", deep[0]),
        "page_runs score, filtered": lambda c: query.page_runs(
            c, query.parse_query({"surface": "chat", "risk": "clean"}), "score"),
        "page_runs -grade": lambda c: query.page_runs(c, every, "-grade"),
    }


def _after(conn: Any, q: Any, sort: str, pages: int) -> str | None:
    from ekte.web import query

    after = None
    for _ in range(pages):
        after = query.page_runs(conn, q, sort, after).after
    return after


def bench(repeat: int = 40) -> dict[str, tuple[float, float]]:
    """``{case: (p50 ms, p95 ms)}`` over the database of ``$EKTE_DATA_DIR``."""
    from ekte.web import history

    conn = history.query_connection()
    return {name: _time(lambda fn=fn: fn(conn), repeat) for name, fn in cases(conn).items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, help="data directory (default $EKTE_DATA_DIR)")
    parser.add_argument("--runs", type=int, default=20_000)
    parser.add_argument("--relays", type=int, default=50)
    parser.add_argument("--requests", type=int, default=100, help="requests per run")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--report-bytes", type=int, default=REPORT_BYTES,
                        help="size of each stored report")
    parser.add_argument("--monitors", "--watches", dest="monitors", type=int, default=200,
                        help="monitors in watches.db (mixed states, thresholds and last risks)")
    parser.add_argument("--bench", action="store_true", help="time the query core afterwards")
    args = parser.parse_args(argv)
    if args.data_dir is not None:
        os.environ["EKTE_DATA_DIR"] = str(args.data_dir)
    t0 = time.perf_counter()
    n = build(args.runs, args.relays, args.requests, args.seed, args.report_bytes, args.monitors)
    print(f"wrote {n} runs in {time.perf_counter() - t0:.1f} s")
    if args.bench:
        for name, (p50, p95) in bench().items():
            print(f"{name:40s} p50 {p50:7.1f} ms   p95 {p95:7.1f} ms")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
