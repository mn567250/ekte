"""Findings that rest on requests the relay never answered or failed.

A check whose requests all failed in ekte or on the network path to the relay
(``local`` / ``network`` in :mod:`ekte.errorclass`, after the client's
repeats) has no answer of the relay to judge. Its finding is not a verdict
on the relay: :func:`neutralize` turns it inconclusive and takes it out of the
detector's score, which is worked out again from the remaining findings.
"""

from __future__ import annotations

from collections.abc import Sequence

from ekte.detectors.scale import DeductionScale, Scale
from ekte.errorclass import is_impaired, is_relay_failure
from ekte.models import DetectorResult, Finding, RequestRecord, Severity, Status

_JUDGED = (Status.PASS, Status.WARN, Status.FAIL)
NOTE = (
    "Not judged: every request this check rests on failed in ekte or on the network path "
    "to the relay, so there is no answer of the relay to judge."
)


def _recompute(result: DetectorResult) -> tuple[float | None, Status] | None:
    """The detector's score and status by its published scale, or None when it
    has none (its own rules cannot be repeated here)."""
    if result.scoring is None:
        return None
    if result.scoring.method == DeductionScale.method:
        score: float | None = DeductionScale.total(result.findings)
    elif result.scoring.method == Scale.method:
        score = Scale.mean(result.findings)
    else:
        return None
    status = Scale.roll_up(result.findings)
    if score is None and status == Status.PASS:
        status = Status.INCONCLUSIVE  # nothing left that was judged
    return score, status


def _cited(finding: Finding, by_seq: dict[int, RequestRecord],
           own: list[RequestRecord]) -> list[RequestRecord]:
    if finding.evidence_seqs is None:
        return own
    return [by_seq[s] for s in finding.evidence_seqs if s in by_seq]


def neutralize(result: DetectorResult, records: Sequence[RequestRecord]) -> int:
    """Turn every judged finding of ``result`` whose requests all failed in
    ekte or on the network path (none answered, none failed at the relay)
    inconclusive and uncounted; returns how many changed. The detector's
    score and status follow when they come from its published scale (and
    agree with it before the change); otherwise they stay as the detector
    set them."""
    if not records or not result.findings:
        return 0
    by_seq = {r.seq: r for r in records}
    own = [r for r in records if r.detector == result.id]
    hits: list[tuple[Finding, list[int]]] = []
    for f in result.findings:
        if f.status not in _JUDGED:
            continue
        cited = _cited(f, by_seq, own)
        # an answer of the relay, or a failure of its own, is something to judge
        if not cited or any(r.ok or is_relay_failure(r) for r in cited):
            continue
        lost = [r.seq for r in cited if is_impaired(r)]
        if lost:
            hits.append((f, lost))
    if not hits:
        return 0
    before = _recompute(result)
    follows = before is not None and before == (result.score, result.status)
    for f, lost in hits:
        f.status = Status.INCONCLUSIVE
        f.severity = Severity.INFO
        f.outcome = None
        f.score = None
        f.deduction = None
        f.cap = None
        f.summary = f"{NOTE} {f.summary}".strip()
        f.evidence = {**f.evidence, "impaired_requests": lost}
    if follows:
        after = _recompute(result)
        assert after is not None
        result.score, result.status = after
    return len(hits)
