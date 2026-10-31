"""The rerank surface through the runner: detectors and ranking drift, against
an in-process mock /rerank endpoint."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from ekte import prompts
from ekte.config import AuditOptions
from ekte.detectors.base import select_detectors
from ekte.detectors.rerank import KNOWN_ANSWER_TOP, max_score_delta, order_flips, score_delta
from ekte.detectors.rerank_drift import previous_drift
from ekte.models import Dimension, RiskLevel, Status, TargetConfig
from ekte.runner import run_audit

BASE = "https://relay.rerank.test/v1"
MODEL = "acme-rerank-v2"
RERANK_IDS = {"rerank.connectivity", "rerank.known_answer", "rerank.identity",
              "rerank.determinism", "rerank.drift"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


class RerankServer:
    """Relevance = word overlap with the query. ``reverse`` ranks backwards (a
    swapped or broken model), ``scale`` rescales the scores, ``noise`` adds
    jitter that alternates between calls (every other call scores ``noise``
    higher, so two calls always differ by exactly that much), ``status`` fails
    every call."""

    def __init__(self, *, served: str | None = MODEL, reverse: bool = False, scale: float = 1.0,
                 noise: float = 0.0, status: int = 200, drop: bool = False):
        self.served, self.reverse, self.scale, self.noise = served, reverse, scale, noise
        self.status, self.drop = status, drop
        self.calls = 0

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        assert request.url.path.endswith("/rerank")
        self.calls += 1
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "boom"}})
        body = json.loads(request.content or b"{}")
        query = _words(body["query"])
        results = []
        for i, doc in enumerate(body["documents"]):
            words = _words(doc)
            score = len(query & words) / (len(words) or 1) * self.scale
            if self.reverse:
                score = 1.0 - score
            score += self.noise * (self.calls % 2) + 0.001 * i  # no ties
            results.append({"index": i, "relevance_score": score})
        if self.drop:
            results = results[:1]
        out = {"results": results, "usage": {"total_tokens": 9}}
        if self.served:
            out["model"] = self.served
        return httpx.Response(200, json=out)


@pytest.fixture
def serve(monkeypatch):
    def install(server: RerankServer) -> RerankServer:
        from ekte.clients import make_client as real

        monkeypatch.setattr(
            "ekte.runner.make_client", lambda config, **_: real(config, transport=server.transport)
        )
        return server

    return install


def _target() -> TargetConfig:
    return TargetConfig(name="r", kind="target", base_url=BASE, api_key="sk-x", model=MODEL)


def _opts(**kw) -> AuditOptions:
    return AuditOptions(surface="rerank", **kw)


def _finding(report, fid):
    return next(f for d in report.detectors for f in d.findings if f.id == fid)


def test_rerank_surface_selects_its_own_detectors():
    def ids(surface, suite="full"):
        return {d.id for d in select_detectors(suite, has_judge=True, has_baseline=True,
                                               enabled=lambda _: True, surface=surface)}

    rerank = ids("rerank")
    assert rerank >= RERANK_IDS
    assert all(i.startswith(("rerank.", "performance.")) for i in rerank)
    assert not rerank & ids("chat") and not rerank & ids("embedding")
    assert ids("rerank", "smoke") >= RERANK_IDS


def test_known_answer_probe_points_at_the_obvious_document():
    docs = prompts.get("rerank.web.documents")
    assert "capital" in docs[KNOWN_ANSWER_TOP].lower()


async def test_clean_rerank_audit(serve):
    serve(RerankServer())
    report = await run_audit(_target(), _opts(suite="deep"))
    assert report.surface == "rerank"
    assert {d.id for d in report.detectors} >= RERANK_IDS
    # The performance probe judges wall-clock timings, which a busy runner can
    # push to WARN; it has its own timing-independent tests (test_rerank_perf).
    functional = [d for d in report.detectors if d.id in RERANK_IDS]
    assert all(d.status in (Status.PASS, Status.INFO) for d in functional), [
        (d.id, d.status, d.error) for d in functional]
    assert report.verdict.risk_level == RiskLevel.CLEAN
    assert {d.dimension for d in report.detectors if d.id in RERANK_IDS} == {
        Dimension.CONNECTIVITY, Dimension.CAPABILITY, Dimension.MODEL_IDENTITY,
        Dimension.RELIABILITY}
    assert _finding(report, "rerank.connectivity").evidence["results"] == 4
    known = _finding(report, "rerank.known_answer")
    assert known.outcome == "first" and known.evidence["top_index"] == KNOWN_ANSWER_TOP
    assert _finding(report, "rerank.model_field").outcome == "matches"
    assert _finding(report, "rerank.determinism").outcome == "deterministic"
    drift = _finding(report, "rerank.drift")
    assert drift.outcome == "baseline" and drift.status == Status.INFO
    assert len(drift.evidence["scores"]) == len(prompts.get("rerank.drift.documents"))


async def test_wrong_ranking_and_echoed_model_are_high_risk(serve):
    serve(RerankServer(reverse=True, served="other-rerank-model"))
    report = await run_audit(_target(), _opts(suite="smoke"))
    known = _finding(report, "rerank.known_answer")
    assert known.outcome == "missed" and known.severity.value == "high"
    assert _finding(report, "rerank.model_field").outcome == "differs"
    assert report.verdict.risk_level == RiskLevel.HIGH


async def test_missing_model_field_is_info(serve):
    serve(RerankServer(served=None))
    report = await run_audit(_target(), _opts(suite="smoke"))
    assert _finding(report, "rerank.model_field").outcome == "missing"


async def test_noisy_scores_are_not_deterministic(serve):
    serve(RerankServer(noise=0.0005))
    report = await run_audit(_target(), _opts(suite="smoke"))
    det = _finding(report, "rerank.determinism")
    assert det.outcome == "drifting" and det.evidence["max_score_delta"] > 1e-4


async def test_failed_and_malformed_endpoint(serve):
    serve(RerankServer(status=500))
    report = await run_audit(_target(), _opts(suite="smoke"))
    assert _finding(report, "rerank.connectivity").outcome == "failed"
    for fid, key in (("rerank.known_answer", "no_ranking"), ("rerank.model_field", "no_response"),
                     ("rerank.determinism", "no_ranking"), ("rerank.drift", "no_ranking")):
        assert _finding(report, fid).outcome == key, fid

    serve(RerankServer(drop=True))
    report = await run_audit(_target(), _opts(suite="smoke"))
    assert _finding(report, "rerank.connectivity").outcome == "malformed"
    assert _finding(report, "rerank.known_answer").outcome == "no_ranking"


async def test_ranking_drift_against_the_previous_run(serve):
    serve(RerankServer())
    first = await run_audit(_target(), _opts(suite="smoke"))
    saved = json.loads(first.model_dump_json())  # as history stores it
    assert previous_drift(saved)["ranking"]

    same = await run_audit(_target(), _opts(suite="smoke"), previous_report=saved)
    assert _finding(same, "rerank.drift").outcome == "stable"

    serve(RerankServer(scale=0.8))
    shifted = await run_audit(_target(), _opts(suite="smoke"), previous_report=saved)
    assert _finding(shifted, "rerank.drift").outcome == "shifted"

    serve(RerankServer(reverse=True))
    swapped = await run_audit(_target(), _opts(suite="smoke"), previous_report=saved)
    drift = _finding(swapped, "rerank.drift")
    assert drift.outcome == "swapped" and drift.severity.value == "high"
    assert drift.evidence["same_ranking"] is False
    assert swapped.verdict.risk_level == RiskLevel.HIGH


def test_previous_drift_and_score_deltas():
    assert previous_drift(None) is None
    assert previous_drift({"detectors": [{"id": "rerank.drift", "findings": [{"evidence": {}}]}]}) is None
    # logit-like scores are judged relative to their magnitude
    assert score_delta(10.0, 10.5) == pytest.approx(0.5 / 10.5)
    assert score_delta(0.2, 0.3) == pytest.approx(0.1)
    assert max_score_delta({0: 0.1, 1: 0.5}, {0: 0.1, 1: 0.45, 2: 9.0}) == pytest.approx(0.05)
    assert max_score_delta({}, {}) == 0.0


def test_order_flips_ignore_near_ties():
    assert order_flips({0: 0.9, 1: 0.5}, {0: 0.9, 1: 0.5}, 1e-4) == 0
    # two near-tied documents trading places from jitter: not a flip
    assert order_flips({0: 0.50001, 1: 0.50000}, {0: 0.50000, 1: 0.50001}, 1e-4) == 0
    assert order_flips({0: 0.9, 1: 0.5, 2: 0.1}, {0: 0.1, 1: 0.5, 2: 0.9}, 1e-4) == 3


async def test_a_tie_with_the_known_answer_counts_as_first(serve):
    class Saturated(RerankServer):
        def _handle(self, request):
            if not request.url.path.endswith("/rerank"):
                return super()._handle(request)
            docs = json.loads(request.content)["documents"]
            results = [{"index": i, "relevance_score": 1.0 if i in (0, KNOWN_ANSWER_TOP) else 0.1}
                       for i in range(len(docs))]
            return httpx.Response(200, json={"model": MODEL, "results": results})

    serve(Saturated())
    report = await run_audit(_target(), _opts(suite="smoke"))
    known = _finding(report, "rerank.known_answer")
    assert known.outcome == "first" and known.evidence["top_index"] == 0
