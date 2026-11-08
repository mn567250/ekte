"""Run history for the Analytics page (/analytics) in the a11y servers.

:func:`seed_analytics` saves a relay in the knowledge base and a dozen runs
over the last week before ``end``: two relays (the saved one and a long URL
the knowledge base does not know), two models, manual and monitor runs,
buckets with three runs and buckets with fewer (drawn faded), a ekte
version and knowledge-base profile change (annotation markers), request
records with rate limits, server errors and timeouts (errors panel),
identity / context-window / capability detector results (integrity panel),
token shares and relay / network timings. Times are
relative to ``end``, so a server with a fixed clock renders the same page on
every run.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from typing import Any

SAVED_RELAY = ("Example Relay", "https://relay.example.com/v1")
URL_RELAY = "https://gateway.a-very-long-relay-hostname.example.org/openai/compatible/v1"

# (days, hours before end, relay, model, by monitor, score)
RUNS = [
    (1, 1, "saved", "model-a", False, 82.0),
    (1, 2, "saved", "model-a", False, 85.0),
    (1, 3, "saved", "model-a", False, 88.0),
    (3, 2, "saved", "model-a", False, 78.0),
    (3, 3, "saved", "model-a", False, 80.0),
    (3, 5, "saved", "model-a", False, 84.0),
    (5, 4, "saved", "model-a", True, 70.0),
    (1, 4, "url", "model-a", False, 64.0),
    (2, 1, "url", "model-a", True, 60.0),
    (2, 2, "url", "model-a", True, 66.0),
    (2, 3, "url", "model-a", True, 58.0),
    (2, 5, "saved", "model-b", False, 91.0),
    (2, 6, "saved", "model-b", False, 89.0),
    (4, 2, "url", "model-b", False, 72.0),
]


def _report(started: datetime, base_url: str, model: str, score: float, saved: bool, newer: bool) -> dict[str, Any]:
    risk = "high" if score < 65 else "low" if score < 80 else "clean"
    report: dict[str, Any] = {
        "tool_version": "0.11.0" if newer else "0.10.0",
        "mode": "check",
        "started_at": started.isoformat(),
        "generated_at": (started + timedelta(minutes=2)).isoformat(),
        "suite": "standard",
        "stream_mode": "stream",
        "target": {"base_url": base_url, "model": model, "claimed_model": model, "api": "openai"},
        "verdict": {"overall_score": score, "risk_level": risk, "rating": "B" if score >= 80 else "D"},
        "dimensions": [{"dimension": "protocol", "score": score, "weight": 8.0, "status": "pass"}],
        "detectors": [],
        "knowledge": {"profile_hash": "kb2" if newer else "kb1", "model_id": model},
        "performance": {
            "target": {
                "requests": 10,
                "successes": 10 if score >= 70 else 8,
                "latency_ms": {"p50": 1500.0 + (100 - score) * 20, "p95": 2600.0 + (100 - score) * 30},
                "ttft_ms": {"p50": (380.0 if saved else 900.0) + (100 - score) * 4},
                "decode_tps_local": {"p50": (55.0 if saved else 38.0) + score / 10},
            },
            "requests": [],
        },
    }
    side = report["performance"]["target"]
    side["relay_processing_ms"] = {"p50": 140.0 + (100 - score) * 3 if saved else 420.0}
    side["network_rtt_ms"] = {"p50": 60.0 if saved else 180.0}
    report["performance"]["requests"] = _requests(score, saved)
    report["detectors"].extend(_integrity(model, score, saved))
    if saved:  # billing evidence for some runs only: the page shows coverage
        report["detectors"].append({
            "id": "billing", "status": "pass", "findings": [], "duration_ms": 1000,
            "evidence": {"ratio_prompt": 1.0 + (90 - score) / 200, "ratio_completion": 1.02},
        })
    return report


def _requests(score: float, saved: bool) -> list[dict[str, Any]]:
    """Ten completion calls a few seconds apart: the URL relay hits rate
    limits and server errors, the saved relay times out now and then; two
    of its calls fail before reaching it (an ekte and a network failure,
    no status code)."""
    out = []
    for seq in range(10):
        status: int | None = 200
        error_type = None
        if not saved and seq in (3, 7) and score < 70:
            status, error_type = 429, "http_error"
        elif not saved and seq == 5:
            status, error_type = 502, "http_error"
        elif saved and seq == 9 and score < 85:
            status, error_type = None, "ReadTimeout"
        elif saved and seq == 8 and score in (89.0, 91.0):
            # never reached the relay: ekte's own pool, then the network
            status, error_type = None, "PoolTimeout" if score == 91.0 else "ConnectError"
        out.append({
            "seq": seq, "endpoint": "target", "phase": "passive", "op": "complete", "stream": True,
            "start_ms": seq * 6000.0, "ok": status == 200, "status_code": status,
            "error_type": error_type, "timeout": error_type == "ReadTimeout",
            "rate_limited": status == 429, "duration_ms": 1200.0 if status == 200 else 300.0,
            "input_tokens_reported": 400 if status == 200 else None,
            "output_tokens_reported": 200 if status == 200 else None,
            "reasoning_tokens": (60 if saved else 20) if status == 200 else None,
            "cached_input_tokens": (100 if saved else 0) if status == 200 else None,
        })
    return out


def _integrity(model: str, score: float, saved: bool) -> list[dict[str, Any]]:
    """Identity (echoed model field), context window and capability results."""
    diverges = not saved and score < 65
    identity = {
        "id": "model_identity", "status": "warn" if diverges else "pass", "score": 60.0 if diverges else 95.0,
        "duration_ms": 800, "evidence": {},
        "findings": [{
            "id": "model_identity.model_field", "check": "model_identity.model_field",
            "status": "warn" if diverges else "pass", "outcome": "diverges" if diverges else "consistent",
            "severity": "medium" if diverges else "info", "evidence": {"returned": model + "-mini" if diverges else model},
        }],
    }
    declared = 128_000
    context = {
        "id": "context_window", "status": "pass" if saved else "warn", "findings": [], "duration_ms": 3000,
        "evidence": {"declared": declared, "effective_window": declared if saved else 32_000},
    }
    checks = [identity, context]
    for det_id, status in (
        ("capability", "pass"), ("streaming", "pass"),
        ("vision", "pass" if saved else "fail" if score < 65 else "inconclusive"),
        ("protocol_response", "pass" if score >= 70 else "warn"),
    ):
        checks.append({"id": det_id, "status": status, "findings": [], "evidence": {}, "duration_ms": 500})
    return checks


def seed_analytics(end: datetime, watch_id: int | None) -> None:
    """Save the relay and the runs (call with EKTE_DATA_DIR set, after history.init())."""
    from ekte.knowledge.relays import RelayError, add_relay
    from ekte.web import history

    with contextlib.suppress(RelayError):  # already saved
        add_relay(*SAVED_RELAY)
    for days, hours, relay, model, by_monitor, score in RUNS:
        started = end - timedelta(days=days, hours=hours)
        saved = relay == "saved"
        report = _report(started, SAVED_RELAY[1] if saved else URL_RELAY, model, score, saved, newer=days <= 2)
        history.save(report, watch_id=watch_id if by_monitor else None)


# --------------------------------------------------------------------------- #
# History's own tests (test_history_controls.py, test_history_paging.py)
# --------------------------------------------------------------------------- #
HISTORY_RELAY = "https://history.example.com/v1"
# (model, minutes before end, score, grade, risk): two groups of three runs
HISTORY_CONTROLS = [
    ("model-a", 10, 70.0, "C", "medium"),
    ("model-b", 20, 95.0, "A", "clean"),
    ("model-a", 30, 40.0, "F", "high"),
    ("model-b", 40, 85.0, "B", "low"),
    ("model-a", 50, 90.0, "A", "clean"),
    ("model-b", 60, 60.0, "D", "medium"),
]
# one group of 45 runs (pages of 20, 20 and 5), newest first: scores 90, 89, …
HISTORY_PAGED = ("model-p", 45)
# the bulk: 2,000 runs over 4 relays and 8 models (32 groups: 2 pages of groups)
HISTORY_BULK = {"runs": 2000, "relays": 4, "requests": 10, "report_bytes": 64}


def _history_report(started: datetime, model: str, score: float, grade: str, risk: str) -> dict[str, Any]:
    return {
        "mode": "check", "suite": "standard", "stream_mode": "stream",
        "started_at": started.isoformat(), "generated_at": (started + timedelta(minutes=1)).isoformat(),
        "target": {"base_url": HISTORY_RELAY, "model": model, "claimed_model": model, "api": "openai"},
        "verdict": {"overall_score": score, "risk_level": risk, "rating": grade},
        "performance": {
            "target": {"requests": 4, "successes": 4 if score >= 80 else 3, "latency_ms": {"p50": 900.0 + (100 - score) * 10},
                       "decode_tps_local": {"p50": 40.0 + score / 10}},
            # four calls; a run below 80 has one server error (its error rate: 25 %)
            "requests": [{
                "seq": seq, "endpoint": "target", "phase": "passive", "op": "complete", "stream": True,
                "start_ms": seq * 1000.0, "ok": not (score < 80 and seq == 3),
                "status_code": 502 if score < 80 and seq == 3 else 200, "duration_ms": 800.0,
            } for seq in range(4)],
        },
    }


def seed_history_views(end: datetime) -> None:
    """The runs History's view tests filter for (by model), plus the bulk of
    scripts/bench_fixture.py to page through 2,000 runs."""
    import importlib.util
    from pathlib import Path

    from ekte.web import history

    for model, ago, score, grade, risk in HISTORY_CONTROLS:
        history.save(_history_report(end - timedelta(minutes=ago), model, score, grade, risk))
    model, n = HISTORY_PAGED
    for i in reversed(range(n)):  # oldest first: run i is the i-th newest
        history.save(_history_report(end - timedelta(hours=2, minutes=i), model, 90.0 - i, "B", "clean"))
    path = Path(__file__).resolve().parents[2] / "scripts" / "bench_fixture.py"
    spec = importlib.util.spec_from_file_location("bench_fixture", path)
    assert spec and spec.loader
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    bench.build(**HISTORY_BULK)
