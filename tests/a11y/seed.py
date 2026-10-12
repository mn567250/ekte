"""Run history for the Analytics page (/v2/analytics) in the a11y servers.

:func:`seed_analytics` saves a relay in the knowledge base and a dozen runs
over the last week before ``end``: two relays (the saved one and a long URL
the knowledge base does not know), two models, manual and monitor runs,
buckets with three runs and buckets with fewer (drawn faded), and a zing
version and knowledge-base profile change (annotation markers). Times are
relative to ``end``, so a server with a fixed clock renders the same page on
every run.
"""

from __future__ import annotations

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
        "tool_version": "0.20.0" if newer else "0.19.2",
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
    if saved:  # billing evidence for some runs only: the page shows coverage
        report["detectors"].append({
            "id": "billing", "status": "pass", "findings": [], "duration_ms": 1000,
            "evidence": {"ratio_prompt": 1.0 + (90 - score) / 200, "ratio_completion": 1.02},
        })
    return report


def seed_analytics(end: datetime, watch_id: int | None) -> None:
    """Save the relay and the runs (call with ZING_DATA_DIR set, after history.init())."""
    from zing.knowledge.relays import RelayError, add_relay
    from zing.web import history

    try:
        add_relay(*SAVED_RELAY)
    except RelayError:
        pass  # already saved
    for days, hours, relay, model, by_monitor, score in RUNS:
        started = end - timedelta(days=days, hours=hours)
        saved = relay == "saved"
        report = _report(started, SAVED_RELAY[1] if saved else URL_RELAY, model, score, saved, newer=days <= 2)
        history.save(report, watch_id=watch_id if by_monitor else None)
