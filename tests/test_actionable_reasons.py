"""Findings that could not judge say what to change (issue #204).

A check that is not counted because a request failed, too few samples were
left or a dimension did not run must carry a fixed, translated recommendation;
sample-based findings count what they left out and name the requests they rest
on.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ekte import i18n
from ekte.config import AuditOptions
from ekte.detectors import REGISTRY, advice, perf_probe
from ekte.detectors.base import not_run_reason
from ekte.detectors.performance import SCALE as PERF_SCALE
from ekte.detectors.performance import PerformanceDetector
from ekte.detectors.scale import Scale
from ekte.models import CompletionOutcome, DetectorResult, Dimension, Status
from ekte.scoring import build_dimensions

_DETECTORS = Path(__file__).resolve().parent.parent / "ekte" / "detectors"
# Outcome keys that mean "could not judge": each needs a recommendation.
_CANNOT_JUDGE = {"few_samples", "not_assessed", "unavailable", "inconclusive", "failed"}


def _scale_outcomes() -> dict[tuple[str, str], object]:
    out = {}
    for path in sorted(_DETECTORS.glob("*.py")):
        mod = importlib.import_module(f"ekte.detectors.{path.stem}")
        for value in vars(mod).values():
            if isinstance(value, Scale):
                out.update({(o.check, o.outcome): o for o in value.outcomes})
    return out


def _needs_advice(o) -> bool:
    not_counted = o.score is None and o.deduction is None and o.max_deduction is None and o.cap is None
    # Informational outcomes (nothing claimed, nothing declared) need none.
    return not_counted and (o.status == Status.INCONCLUSIVE or o.outcome in _CANNOT_JUDGE)


def _literals(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _literals(node.body) + _literals(node.orelse)
    return []


def _finding_calls():
    """(file:line, check, outcome keys, has recommendation) of every
    ``<scale>.finding(check, key, …)`` in the detectors."""
    for path in sorted(_DETECTORS.glob("*.py")):
        mod = importlib.import_module(f"ekte.detectors.{path.stem}")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "finding"
                    and len(node.args) >= 2):
                continue
            check = node.args[0]
            names = _literals(check) or (
                [getattr(mod, check.id)] if isinstance(check, ast.Name)
                and isinstance(getattr(mod, check.id, None), str) else []
            )
            rec = next((k.value for k in node.keywords if k.arg == "recommendation"), None)
            has = rec is not None and not (isinstance(rec, ast.Constant) and rec.value is None)
            for name in names:
                yield f"{path.name}:{node.lineno}", name, _literals(node.args[1]), has


def test_every_cannot_judge_finding_says_what_to_change():
    outcomes = _scale_outcomes()
    missing = [
        f"{where} {check} {key}"
        for where, check, keys, has in _finding_calls() if not has
        for key in keys
        if (o := outcomes.get((check, key))) is not None and _needs_advice(o)
    ]
    assert missing == []


def test_consistency_few_samples_is_always_advised():
    # perf_probe builds the check name from a variable: cover it directly.
    src = (_DETECTORS / "perf_probe.py").read_text(encoding="utf-8")
    call = src[src.index('check, "few_samples",'):src.index("return\n", src.index('check, "few_samples",'))]
    assert "recommendation=advice.few_samples_advice(" in call and "calls=" in call


def _advice_sentences() -> list[str]:
    fixed = [v for k, v in vars(advice).items() if k.isupper() and isinstance(v, str)]
    return [*advice.FAILURE_ADVICE.values(), *advice.NOT_RUN_REASONS.values(), *fixed,
            perf_probe.ENABLE_PROBE]


def test_every_recommendation_is_translated_in_every_language():
    data = i18n._load()
    sentences = _advice_sentences()
    assert len(sentences) > 30
    for code in i18n.codes():
        if code == "en":
            continue
        strings = data[code]["strings"]
        assert [s for s in sentences if not strings.get(s) or strings[s] == s] == [], code
        # option names stay as they are in every language
        for s in sentences:
            for flag in (w.strip(".,;:()") for w in s.split() if w.startswith("--")):
                assert flag in strings[s], (code, flag, s)


# --------------------------------------------------------------------------- #
# failure advice
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("outcome", "kind"),
    [
        (CompletionOutcome(ok=False, error_type="ReadTimeout"), "timeout"),
        (CompletionOutcome(ok=False, error_type="DeadlineTimeout"), "timeout"),
        (CompletionOutcome(ok=False, status_code=429), "rate_limited"),
        (CompletionOutcome(ok=False, status_code=400), "rejected"),
        (CompletionOutcome(ok=False, status_code=422), "rejected"),
        (CompletionOutcome(ok=False, status_code=401), "auth"),
        (CompletionOutcome(ok=False, status_code=403), "auth"),
        (CompletionOutcome(ok=False, status_code=404), "not_found"),
        (CompletionOutcome(ok=False, status_code=502), "upstream"),
        (CompletionOutcome(ok=False, error_type="ConnectError"), "network"),
        (CompletionOutcome(ok=False, error_type="ConnectTimeout"), "network"),
        (CompletionOutcome(ok=False, error_type="PoolTimeout"), "local"),
        (CompletionOutcome(ok=False, error_type="Unsupported"), "unsupported"),
        (CompletionOutcome(ok=True, content=""), "empty"),
        (CompletionOutcome(ok=False, status_code=418), "other"),
        (None, "other"),
    ],
)
def test_failure_kind(outcome, kind):
    assert advice.failure_kind(outcome) == kind
    assert advice.failure_advice(outcome) == advice.FAILURE_ADVICE[kind]


def test_failure_kind_reads_request_records():
    rec = SimpleNamespace(ok=False, status_code=None, error_type="ReadTimeout", timeout=True,
                          rate_limited=False, error_class="relay")
    assert advice.failure_kind(rec) == "timeout"


# --------------------------------------------------------------------------- #
# consistency findings
# --------------------------------------------------------------------------- #
def _rec(seq, *, ok=True, cached=False, ttft=None, duration=1000.0):
    return SimpleNamespace(seq=seq, ok=ok, cached=cached, retried=False, ttft_ms=ttft,
                           duration_ms=duration)


def _consistency(pool, value, **kw) -> DetectorResult:
    result = DetectorResult(id="performance", name="x", dimension=Dimension.PERFORMANCE)
    perf_probe.consistency_finding(
        PERF_SCALE, result, "performance.ttft_consistency", "Time to first token", "ms",
        pool, value, False, **kw,
    )
    return result


def test_no_stream_deltas_is_explained_and_names_its_requests():
    pool = [_rec(i) for i in range(1, 13)] + [_rec(20, ok=False), _rec(21, cached=True)]
    f = _consistency(pool, lambda r: r.ttft_ms, missing_advice=advice.NO_STREAM_DELTAS).findings[0]
    assert f.outcome == "few_samples"
    assert {k: f.evidence[k] for k in ("samples", "requests", "failed", "cached", "missing")} == {
        "samples": 0, "requests": 14, "failed": 1, "cached": 1, "missing": 12,
    }
    assert f.recommendation == advice.NO_STREAM_DELTAS
    assert f.evidence_seqs == sorted(r.seq for r in pool)
    assert "12 without a usable value" in f.summary


def test_scored_consistency_names_only_the_requests_it_used():
    pool = [_rec(i, ttft=100.0 + i) for i in range(1, 13)] + [_rec(30, ok=False)]
    f = _consistency(pool, lambda r: r.ttft_ms).findings[0]
    assert f.outcome == "steady" and f.recommendation is None
    assert f.evidence_seqs == list(range(1, 13))


@pytest.mark.parametrize(
    ("pool", "capped", "expected"),
    [
        ([_rec(i) for i in range(5)], True, advice.STANDARD_PROBE_CAP),
        ([_rec(i) for i in range(5)], False, advice.MORE_PROBE_REQUESTS),
        ([_rec(i, ok=False) for i in range(12)], False, advice.PROBE_FAILURES),
        ([_rec(i, cached=True) for i in range(12)], False, advice.PROBE_CACHED),
    ],
)
def test_few_samples_advice_picks_the_main_reason(pool, capped, expected):
    f = _consistency(pool, lambda r: r.ttft_ms, capped=capped).findings[0]
    assert f.recommendation == expected


def test_standard_with_baseline_is_capped_below_the_minimum():
    opts = AuditOptions(suite="standard")
    assert perf_probe.probe_capped(opts, has_baseline=True)
    assert not perf_probe.probe_capped(AuditOptions(suite="deep"), has_baseline=False)


async def test_relay_that_ignores_stream_true_is_explained(audit_context, mock_server):
    # The reported case: stream=true answered with a plain JSON body, so no
    # streamed content delta and no time to first token.
    plain = mock_server._chat_response
    mock_server._chat_response = lambda body: plain({**body, "stream": False})
    audit_context.options = AuditOptions(suite="deep", performance_requests=12)
    result = await PerformanceDetector().run(audit_context)
    by = {f.scale_check: f for f in result.findings}
    ttft, decode = by["performance.ttft_consistency"], by["performance.throughput_consistency"]
    for f in (ttft, decode):
        assert f.outcome == "few_samples"
        assert f.recommendation == advice.NO_STREAM_DELTAS
        assert f.evidence["requests"] == 12 and f.evidence["missing"] == 12
        assert f.evidence_seqs and len(f.evidence_seqs) == 12
    latency = by["performance.latency_consistency"]
    assert latency.outcome != "few_samples" and len(latency.evidence_seqs) == 12
    assert by["performance.load_stability"].evidence_seqs


# --------------------------------------------------------------------------- #
# dimensions that did not run
# --------------------------------------------------------------------------- #
def _why(dim: str, suite: str, **kw) -> str | None:
    kw.setdefault("has_judge", False)
    kw.setdefault("has_baseline", False)
    kw.setdefault("enabled", lambda _id: True)
    return not_run_reason(dim, suite, **kw)


def test_not_run_reasons_name_what_would_make_a_dimension_run():
    reasons = advice.NOT_RUN_REASONS
    assert _why("performance", "standard") == reasons["baseline"]
    assert _why("performance", "standard", has_baseline=True) is None
    assert _why("performance", "smoke") == reasons["suite_deep"]
    assert _why("context_window", "standard") == reasons["suite_deep"]
    assert _why("protocol", "smoke") == reasons["suite_standard"]
    assert _why("performance", "deep") is None
    assert _why("performance", "deep", enabled=lambda _id: False) == reasons["disabled"]


def test_judge_reason():
    # Only the judge check enabled, and no judge: the judge is what is missing.
    dim = REGISTRY["quality_judge"].dimension.value
    reason = _why(dim, "full", enabled=lambda i: i == "quality_judge")
    assert reason == advice.NOT_RUN_REASONS["judge"]


def test_dimension_reason_carries_the_not_run_reason():
    dims = build_dimensions([], None, not_run={"performance": advice.NOT_RUN_REASONS["baseline"]})
    by = {d.dimension.value: d for d in dims}
    assert by["performance"].reason == advice.NOT_RUN_REASONS["baseline"]
    assert by["streaming"].reason == "Not run in this suite."
