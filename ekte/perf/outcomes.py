"""Per-run outcome counts and rates: the one definition of the success, error
and 429 rates that the report, History and Analytics share.

Every request record of the run on the ``target`` endpoint counts, whatever
its op and phase, with exactly one outcome (:func:`ekte.errorclass.outcome`);
repeated attempts and ekte's ``param_retry`` calls never count. The rates:

* ``requests_judged`` = total − network − local
* ``success_rate`` = success ÷ judged
* ``error_rate`` = (relay_timeout + relay_5xx + relay_4xx + relay_other) ÷ judged
* ``rate_limited_rate`` = rate_limited ÷ judged
* ``timeout_rate`` = relay_timeout ÷ judged
* ``impaired_rate`` = (network + local) ÷ total, the run's validity, not the relay's

so ``success_rate + error_rate + rate_limited_rate == 1`` whenever judged > 0.
Aggregating over runs pools the counts (Σ counts ÷ Σ base), never the rates.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from ekte.errorclass import (
    IMPAIRED,
    OUTCOMES,
    RATE_LIMITED,
    RELAY_ERRORS,
    RELAY_TIMEOUT,
    SUCCESS,
    outcome,
)
from ekte.models import RunOutcomes

__all__ = ["from_counts", "run_outcomes"]


def _endpoint(rec: object) -> object:
    if isinstance(rec, dict):
        return rec.get("endpoint", "target")
    return getattr(rec, "endpoint", "target")


def _op(rec: object) -> str:
    op = rec.get("op", "complete") if isinstance(rec, dict) else getattr(rec, "op", "complete")
    return op if isinstance(op, str) and op else "complete"


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def from_counts(by_op: Mapping[str, Mapping[str, int]]) -> RunOutcomes:
    """The run's outcomes from its counts per (op, outcome); zero counts and
    unknown outcomes are dropped."""
    ops: dict[str, dict[str, int]] = {}
    for op, counts in sorted(by_op.items()):
        kept = {o: int(counts[o]) for o in OUTCOMES if int(counts.get(o, 0) or 0) > 0}
        if kept:
            ops[op] = kept
    totals = {o: sum(c.get(o, 0) for c in ops.values()) for o in OUTCOMES}
    total = sum(totals.values())
    judged = total - sum(totals[o] for o in IMPAIRED)
    return RunOutcomes(
        requests_total=total,
        requests_judged=judged,
        counts=totals,
        by_op=ops,
        success_rate=_ratio(totals[SUCCESS], judged),
        error_rate=_ratio(sum(totals[o] for o in RELAY_ERRORS), judged),
        rate_limited_rate=_ratio(totals[RATE_LIMITED], judged),
        timeout_rate=_ratio(totals[RELAY_TIMEOUT], judged),
        impaired_rate=_ratio(total - judged, total),
    )


def run_outcomes(records: Iterable[object]) -> RunOutcomes:
    """Outcome counts and rates of one run's request records
    (:class:`~ekte.models.RequestRecord` objects or their dicts, including
    records saved before ``error_class`` existed)."""
    counts: dict[str, Counter[str]] = {}
    for rec in records:
        if _endpoint(rec) != "target":
            continue
        kind = outcome(rec)
        if kind is not None:
            counts.setdefault(_op(rec), Counter())[kind] += 1
    return from_counts(counts)
