"""Embedding and rerank auditor tests.

These cover the non-chat surfaces: ``zing.embed_audit.run_embedding_audit`` and
``run_rerank_audit`` plus the OpenAI-compatible client's ``embeddings``/``rerank``
methods. We inject an ``httpx.MockTransport`` into the real client (mirroring the
mock-client style in ``tests/test_anthropic.py``) so no network is touched, and
patch the runner's ``make_client`` so the audit uses our transport-backed client.

Scenarios:
  * /embeddings through ``run_embedding_audit`` — correct dims => PASS; wrong
    dims => high-severity mismatch; runs saved to history feed vector drift.
  * /rerank through ``run_rerank_audit`` and ``zing rerank`` — the rerank
    surface, saved to history, the previous rerank run as drift reference.
  * ``--dry-run`` — the non-chat performance probes get real call estimates.
"""

from __future__ import annotations

import hashlib
import json
import math

import httpx
import pytest

from zing.clients import OpenAICompatibleClient
from zing.embed_audit import cosine_similarity, run_embedding_audit, run_rerank_audit, tool_verdict
from zing.models import TargetConfig

BASE = "https://relay.embed.test/v1"
MODEL = "text-embedding-3-large"
SECRET = "sk-embed-secret-key-123456"


def _stable_key(text: str) -> int:
    """A process-stable integer key for ``text`` (NOT the salted builtin ``hash``)."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)


def _unit_vector(dim: int, key: int) -> list[float]:
    """Deterministic vector of length ``dim``.

    A dominant spike at a key-determined index makes *distinct* keys near-orthogonal
    (low cosine, so distinctness PASSES), while an *identical* key yields an identical
    vector (determinism is exact). Independent of ``PYTHONHASHSEED`` — same key in,
    same vector out, every process — so the distinctness check can never flake.
    """
    v = [0.001 * math.sin(key % 997 + i) for i in range(dim)]
    v[key % dim] += 10.0
    return v


class EmbedMock:
    """A minimal OpenAI-shaped /embeddings + /rerank endpoint via MockTransport."""

    def __init__(
        self,
        *,
        dim: int = 3072,
        served_model: str = MODEL,
        status: int = 200,
        # When True, every input returns the SAME vector (the distinctness tell).
        collapse: bool = False,
        # Rerank: which document index the relay ranks first.
        rerank_top: int = 2,
    ):
        self.dim = dim
        self.served_model = served_model
        self.status = status
        self.collapse = collapse
        self.rerank_top = rerank_top
        self.requests: list[dict] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else {}
        self.requests.append(body)
        if request.url.path.endswith("/embeddings"):
            return self._embeddings(body)
        if request.url.path.endswith("/rerank"):
            return self._rerank(body)
        return httpx.Response(404, json={"error": {"message": "no route"}})

    def _embeddings(self, body: dict) -> httpx.Response:
        if self.status >= 400:
            return httpx.Response(
                self.status,
                json={"error": {"message": f"bad key {SECRET}", "type": "invalid_request_error"}},
            )
        inputs = body.get("input") or []
        data = []
        for i, text in enumerate(inputs):
            # Identical vector for every input when collapsed; otherwise a vector
            # that is identical for identical text (determinism) but distinct for
            # distinct text (distinctness).
            key = 0 if self.collapse else _stable_key(text)
            data.append({"object": "embedding", "index": i, "embedding": _unit_vector(self.dim, key)})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": self.served_model,
                "data": data,
                "usage": {"prompt_tokens": 10, "total_tokens": 10},
            },
        )

    def _rerank(self, body: dict) -> httpx.Response:
        if self.status >= 400:
            return httpx.Response(self.status, json={"error": {"message": "boom"}})
        docs = body.get("documents") or []
        results = []
        for i in range(len(docs)):
            score = 0.99 if i == self.rerank_top else 0.10 + i * 0.01
            results.append({"index": i, "relevance_score": score})
        # Return them deliberately UNSORTED to exercise the client's sort.
        return httpx.Response(200, json={"model": self.served_model, "results": results})


def _target(**kw) -> TargetConfig:
    return TargetConfig(name="t", kind="target", base_url=BASE, api_key=SECRET, model=MODEL, **kw)


# --------------------------------------------------------------------------- #
# Pure math
# --------------------------------------------------------------------------- #
def test_cosine_similarity_basics():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# --------------------------------------------------------------------------- #
# Client methods directly
# --------------------------------------------------------------------------- #
async def test_client_embeddings_shape():
    mock = EmbedMock(dim=8)
    async with OpenAICompatibleClient(_target(), transport=mock.transport) as c:
        outcome, vectors = await c.embeddings(["a", "b"])
    assert outcome.ok
    assert outcome.model_returned == MODEL
    assert len(vectors) == 2
    assert all(len(v) == 8 for v in vectors)


async def test_client_embeddings_error_is_redacted():
    mock = EmbedMock(status=401)
    async with OpenAICompatibleClient(_target(), transport=mock.transport) as c:
        outcome, vectors = await c.embeddings(["a"])
    assert not outcome.ok and outcome.status_code == 401
    assert vectors == []
    assert SECRET not in (outcome.error_message or "")
    assert SECRET not in json.dumps(outcome.raw_error or {})


async def test_client_rerank_is_sorted():
    mock = EmbedMock(rerank_top=2)
    async with OpenAICompatibleClient(_target(), transport=mock.transport) as c:
        outcome, results = await c.rerank("q", ["a", "b", "c", "d"])
    assert outcome.ok
    assert results[0]["index"] == 2
    scores = [r["relevance_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------- #
# Embedding audit (the runner's embedding surface, saved to history)
# --------------------------------------------------------------------------- #
@pytest.fixture
def patch_runner(monkeypatch):
    def _install(mock: EmbedMock) -> None:
        monkeypatch.setattr(
            "zing.runner.make_client",
            lambda target, **_: OpenAICompatibleClient(target, transport=mock.transport),
        )

    return _install


async def test_embed_correct_dims_pass(patch_runner):
    patch_runner(EmbedMock(dim=3072))
    report, rid = await run_embedding_audit(_target(), claimed_dimensions=3072, save=False)
    verdict = tool_verdict(report, rid)
    assert verdict["risk_level"] == "clean" and verdict["score"] == 100.0
    assert verdict["surface"] == "embedding" and verdict["report_id"] is None
    assert _finding(verdict, "embed.dimension")["status"] == "pass"
    assert SECRET not in json.dumps(verdict)


async def test_embed_wrong_dims_is_high_severity_mismatch(patch_runner):
    # Claim 3072-d (text-embedding-3-large) but the relay returns 1536-d.
    patch_runner(EmbedMock(dim=1536))
    report, _ = await run_embedding_audit(_target(), claimed_dimensions=3072, save=False)
    verdict = tool_verdict(report)
    assert verdict["risk_level"] == "high"
    dim = _finding(verdict, "embed.dimension")
    assert (dim["status"], dim["severity"]) == ("fail", "high")
    assert dim["evidence"] == {"returned": 1536, "claimed": 3072}


async def test_embed_kb_dimension_and_connectivity_error(patch_runner):
    # No override: the KB knows text-embedding-3-large's length.
    patch_runner(EmbedMock(dim=1536))
    report, _ = await run_embedding_audit(_target(), save=False)
    assert _finding(tool_verdict(report), "embed.dimension")["evidence"]["claimed"] == 3072
    patch_runner(EmbedMock(status=500))
    report, _ = await run_embedding_audit(_target(), claimed_dimensions=3072, save=False)
    verdict = tool_verdict(report)
    assert _finding(verdict, "embed.connectivity")["status"] == "fail"
    assert verdict["risk_level"] != "clean"


async def test_embed_runs_are_saved_and_drift_uses_the_previous_one(patch_runner):
    from zing.web import history

    patch_runner(EmbedMock(dim=3072))
    first, rid = await run_embedding_audit(_target(), claimed_dimensions=3072)
    assert rid is not None
    saved = history.get(rid)
    assert saved["surface"] == "embedding"
    assert _finding(tool_verdict(first), "embed.drift")["evidence"]["sample"]
    second, rid2 = await run_embedding_audit(_target(), claimed_dimensions=3072)
    assert rid2 != rid
    drift = _finding(tool_verdict(second), "embed.drift")
    assert drift["status"] == "pass" and drift["evidence"]["cosine"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Rerank audit (the runner's rerank surface, saved to history)
# --------------------------------------------------------------------------- #
# These hold whichever rerank detectors are registered (none, on their own).
RR_MODEL = "stub-rerank"


def _rr_target(base_url: str = BASE) -> TargetConfig:
    return TargetConfig(name="t", kind="target", base_url=base_url, api_key=SECRET, model=RR_MODEL)


@pytest.fixture
def spy_previous(monkeypatch):
    """Record the ``previous_report`` each run_audit call gets."""
    import zing.runner

    seen: list = []
    real = zing.runner.run_audit

    async def spy(*args, **kwargs):
        seen.append(kwargs.get("previous_report"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(zing.runner, "run_audit", spy)
    return seen


async def test_rerank_runs_the_rerank_surface_and_saves_it(patch_runner, spy_previous):
    from zing.web import history

    patch_runner(EmbedMock(rerank_top=2, served_model=RR_MODEL))
    target = _rr_target("https://relay.rerank-runs.test/v1")  # no saved runs yet
    first, rid = await run_rerank_audit(target, suite="smoke")
    assert first.surface == "rerank" and first.suite == "smoke"
    assert all(d.id.startswith(("rerank.", "performance.rerank")) for d in first.detectors)
    assert rid is not None and history.get(rid)["surface"] == "rerank"
    verdict = tool_verdict(first, rid)
    assert {"risk_level", "score", "findings", "target", "report_id", "rating", "headline"} <= set(verdict)
    assert verdict["surface"] == "rerank" and SECRET not in json.dumps(verdict)
    # The second run gets the first as its drift reference; an unsaved run
    # still compares with the newest saved one, but is not saved itself.
    _, rid2 = await run_rerank_audit(target, suite="smoke")
    assert rid2 != rid
    assert spy_previous[0] is None and spy_previous[1]["surface"] == "rerank"
    _, rid3 = await run_rerank_audit(target, suite="smoke", save=False)
    assert rid3 is None and spy_previous[2]["generated_at"] == history.get(rid2)["generated_at"]
    assert history.latest_for(target.base_url, RR_MODEL, surface="rerank")["generated_at"] == (
        history.get(rid2)["generated_at"]
    )


async def test_rerank_drift_reference_is_never_an_embedding_run(patch_runner, spy_previous):
    # Same target and model, but the saved run is an embedding one.
    patch_runner(EmbedMock(dim=8, served_model=RR_MODEL))
    target = _rr_target("https://relay.mixed.test/v1")
    await run_embedding_audit(target, claimed_dimensions=8, suite="smoke")
    await run_rerank_audit(target, suite="smoke")
    assert spy_previous[-1] is None


# --------------------------------------------------------------------------- #
# The audit page's background jobs (POST /api/jobs with a surface)
# --------------------------------------------------------------------------- #
async def _job(ac, body: dict) -> dict:
    from zing.web import jobs

    created = await ac.post("/api/jobs", json=body)
    assert created.status_code == 200, created.text
    info = created.json()
    job = jobs.manager.get(info["id"])
    assert job is not None and job.task is not None
    await job.task
    assert job.status == "done", job.error
    return {**info, "report_id": job.report_id, "events": job.events}


async def test_jobs_run_the_embedding_and_rerank_surfaces(patch_runner, spy_previous):
    import httpx

    from zing.web import history
    from zing.web.server import create_app

    patch_runner(EmbedMock(dim=3072, served_model=MODEL))
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        for surface, url, model, extra in (
            ("embedding", "https://relay.job-embed.test/v1", MODEL, {"embedding_dimensions": 3072}),
            ("rerank", "https://relay.job-rerank.test/v1", RR_MODEL, {}),
        ):
            body = {"base_url": url, "api_key": SECRET, "model": model, "suite": "smoke",
                    "surface": surface, "performance_streaming": True, **extra}
            first = await _job(ac, body)
            assert first["surface"] == surface and first["stream_mode"] is None
            saved = history.get(first["report_id"])
            assert saved["surface"] == surface and saved["stream_mode"] == "non_stream"
            assert any(e.get("type") == "detector_done" for e in first["events"])
            # The second job gets the first saved run of the surface as its drift reference.
            second = await _job(ac, body)
            assert second["report_id"] != first["report_id"]
            assert spy_previous[-2] is None
            assert spy_previous[-1]["generated_at"] == saved["generated_at"]
            assert spy_previous[-1]["surface"] == surface
        # The claimed vector length reaches the dimension check.
        embed = await _job(ac, {"base_url": "https://relay.job-embed.test/v1", "api_key": SECRET,
                                "model": MODEL, "suite": "smoke", "surface": "embedding",
                                "embedding_dimensions": 1536})
        rep = history.get(embed["report_id"])
        found = [f for d in rep["detectors"] for f in d["findings"] if f["id"] == "embed.dimension"]
        assert found and found[0]["evidence"]["claimed"] == 1536
        bad = await ac.post("/api/jobs", json={"base_url": BASE, "model": MODEL, "surface": "audio"})
        assert bad.status_code == 400
        bad = await ac.post("/api/jobs", json={"base_url": BASE, "model": MODEL, "surface": "rerank",
                                               "suite": "custom", "dimensions": ["streaming"]})
        assert bad.status_code == 400 and "streaming" in bad.json()["error"]


def _finding(verdict: dict, finding_id: str) -> dict:
    for f in verdict["findings"]:
        if f["id"] == finding_id:
            return f
    raise AssertionError(f"finding {finding_id!r} not found in {[f['id'] for f in verdict['findings']]}")


def test_cli_embed_runs_the_embedding_surface(patch_runner):
    from typer.testing import CliRunner

    from zing.cli import app

    patch_runner(EmbedMock(dim=1536))
    result = CliRunner().invoke(app, [
        "embed", "--base-url", BASE, "--api-key", SECRET, "--model", MODEL,
        "--claimed-dimensions", "3072", "--no-save", "--json", "--fail-on-risk", "high",
    ])
    assert result.exit_code == 1, result.output
    verdict = json.loads(result.stdout)
    assert verdict["surface"] == "embedding" and verdict["risk_level"] == "high"
    assert verdict["report_id"] is None
    assert SECRET not in result.stdout


def test_cli_rerank_runs_the_rerank_surface_and_saves(patch_runner):
    from typer.testing import CliRunner

    from zing.cli import app
    from zing.web import history

    patch_runner(EmbedMock(rerank_top=2, served_model=RR_MODEL))
    args = ["rerank", "--base-url", BASE, "--api-key", SECRET, "--model", RR_MODEL,
            "--suite", "smoke", "--json"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    verdict = json.loads(result.stdout)
    assert verdict["surface"] == "rerank" and verdict["suite"] == "smoke"
    assert verdict["report_id"] is not None
    assert history.get(verdict["report_id"])["surface"] == "rerank"
    assert SECRET not in result.stdout
    result = CliRunner().invoke(app, [*args, "--no-save"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["report_id"] is None
    # An unknown suite is a config error.
    bad = CliRunner().invoke(app, [*args[:-3], "--suite", "nope"])
    assert bad.exit_code == 2


def test_cli_rerank_and_embed_dry_run_make_no_requests(monkeypatch):
    from typer.testing import CliRunner

    from zing.cli import app

    def boom(*_a, **_k):
        raise AssertionError("a dry run must not build a client")

    monkeypatch.setattr("zing.runner.make_client", boom)
    for cmd in ("rerank", "embed"):
        result = CliRunner().invoke(app, [cmd, "--base-url", BASE, "--model", RR_MODEL,
                                          "--suite", "deep", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        plan = json.loads(result.stdout)
        assert plan["dry_run"] is True and plan["suite"] == "deep"
        assert plan["estimated_api_calls"] == sum(d["est_calls"] for d in plan["detectors"])


def test_dry_run_estimates_the_non_chat_performance_probes():
    from zing.cli import _build_dry_run_plan, _surface_probe_calls
    from zing.config import AuditOptions
    from zing.detectors.perf_probe import PINGS, burst_size

    target = _rr_target()
    opts = AuditOptions(suite="deep", surface="embedding", performance_requests=10)
    plan = _build_dry_run_plan(target, opts, None, None, "check")
    perf = next(d for d in plan["detectors"] if d["id"] == "performance.embed")
    # pings + warm-up + 10 rounds of (single, batch) + a burst of singles —
    # not the detector's static cost_hint.
    assert perf["est_calls"] == PINGS + 1 + 10 * 2 + burst_size(opts, 10)
    off = AuditOptions(suite="deep", surface="embedding", performance_requests=0)
    plan = _build_dry_run_plan(target, off, None, None, "check")
    assert next(d for d in plan["detectors"] if d["id"] == "performance.embed")["est_calls"] == 0
    smoke = AuditOptions(suite="smoke", surface="embedding")
    plan = _build_dry_run_plan(target, smoke, None, None, "check")
    assert all(d["id"] != "performance.embed" for d in plan["detectors"])

    # The rerank probe: the same shape, unless the detector declares its own.
    class Rerank:
        id = "performance.rerank"

    class Declared(Rerank):
        @staticmethod
        def estimated_calls(options, *, has_baseline):
            return 7

    rr = AuditOptions(suite="deep", surface="rerank", performance_requests=10)
    assert _surface_probe_calls(Rerank, rr, has_baseline=False) == PINGS + 1 + 20 + burst_size(rr, 10)
    assert _surface_probe_calls(Rerank, rr, has_baseline=True) == 2 * (PINGS + 1 + 20 + burst_size(rr, 10))
    assert _surface_probe_calls(Declared, rr, has_baseline=False) == 7
