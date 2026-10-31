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
    limits and server errors, the saved relay times out now and then."""
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
