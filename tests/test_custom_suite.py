"""The custom suite: run only the dimensions the user selects.

Covers validation, detector selection (deep depth, dimension filter), the CLI
flag, the scoring of the selected dimensions only, and the web/watch plumbing.
"""

from __future__ import annotations

import json

import pytest
from conftest import BASE_URL, DEFAULT_MODEL
from typer.testing import CliRunner

import zing.detectors  # noqa: F401  -- populate the registry
from zing.cli import _build_options, app
from zing.config import DIMENSIONS, AuditOptions, ConfigError, validate_dimensions
from zing.detectors.base import REGISTRY, select_detectors
from zing.models import DetectorResult, Dimension, RiskLevel, Status, TargetConfig
from zing.scoring import DIMENSION_WEIGHTS, build_dimensions, build_verdict, overall_score


def _ids(dims: list[str], *, has_baseline: bool = False) -> set[str]:
    return {
        d.id
        for d in select_detectors(
            "custom", has_judge=False, has_baseline=has_baseline, enabled=lambda _: True,
            dimensions=dims,
        )
    }


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_every_dimension_is_selectable():
    assert set(DIMENSIONS) == {d.value for d in Dimension}
    assert "performance" in DIMENSIONS


def test_validate_dimensions_normalizes():
    assert validate_dimensions("custom", ["security, Protocol", "protocol"]) == ["protocol", "security"]
    assert validate_dimensions("custom", "performance") == ["performance"]
    assert validate_dimensions("deep", None) == []


@pytest.mark.parametrize(
    ("suite", "dims", "match"),
    [
        ("custom", [], "at least one"),
        ("custom", ["latency"], "Unknown dimension"),
        ("standard", ["protocol"], "only be selected with the custom suite"),
    ],
)
def test_validate_dimensions_errors(suite, dims, match):
    with pytest.raises(ConfigError, match=match):
        validate_dimensions(suite, dims)


def test_build_options_dimension_implies_custom():
    assert _build_options({}, dimensions=["billing"]).suite == "custom"
    # the config file's suite does not override an explicit --dimension
    cfg = {"run": {"suite": "standard"}}
    assert _build_options(cfg, dimensions=["billing"]).dimensions == ["billing"]
    # config-file dimensions alone also mean custom
    assert _build_options({"run": {"dimensions": ["security"]}}).suite == "custom"
    # compare's default suite stays deep without a selection
    assert _build_options({}, default_suite="deep").suite == "deep"
    with pytest.raises(ConfigError):
        _build_options({}, suite="standard", dimensions=["billing"])


# --------------------------------------------------------------------------- #
# detector selection
# --------------------------------------------------------------------------- #
def test_custom_runs_every_detector_of_the_selected_dimension_at_deep_depth():
    security = {i for i, cls in REGISTRY.items() if cls.dimension == Dimension.SECURITY}
    assert _ids(["security"]) == security
    assert {"injected_prompt", "integrity", "prompt_cache"} <= security  # deep-only ones


def test_custom_performance_runs_only_the_probe():
    assert _ids(["performance"]) == {"performance"}
    assert "performance" not in _ids(["reliability"])
    assert _ids(["reliability"]) == {"reliability"}


def test_custom_respects_only_and_skip():
    opts = AuditOptions(suite="custom", dimensions=["protocol"], skip=["determinism"])
    chosen = {
        d.id for d in select_detectors(
            opts.suite, has_judge=False, has_baseline=False, enabled=opts.enabled,
            dimensions=opts.dimensions,
        )
    }
    assert "determinism" not in chosen and "protocol" in chosen
    assert all(REGISTRY[i].dimension == Dimension.PROTOCOL for i in chosen)


def test_cli_dry_run_lists_only_the_selected_dimensions():
    out = CliRunner().invoke(
        app,
        ["check", "--base-url", "https://relay.test/v1", "--model", "gpt-4o",
         "-D", "protocol,performance", "--dry-run", "--json"],
    )
    assert out.exit_code == 0, out.output
    plan = json.loads(out.output)
    assert plan["suite"] == "custom" and plan["dimensions"] == ["protocol", "performance"]
    assert {d["dimension"] for d in plan["detectors"]} == {"protocol", "performance"}


def test_cli_rejects_an_unknown_dimension():
    out = CliRunner().invoke(
        app,
        ["check", "--base-url", "https://relay.test/v1", "--model", "gpt-4o",
         "-D", "speed", "--dry-run", "--json"],
    )
    assert out.exit_code == 2 and "Unknown dimension" in out.output


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def _det(dim: Dimension, score: float) -> DetectorResult:
    return DetectorResult(id=f"{dim.value}-det", name=dim.value, dimension=dim,
                          score=score, status=Status.PASS)


def test_weights_sum_to_100_and_include_performance():
    assert sum(DIMENSION_WEIGHTS.values()) == 100.0
    assert DIMENSION_WEIGHTS[Dimension.PERFORMANCE] == 6.0


def test_overall_score_uses_only_the_selected_dimensions():
    dets = [_det(Dimension.PROTOCOL, 60.0), _det(Dimension.PERFORMANCE, 90.0)]
    selected = ["protocol", "performance"]
    dims = build_dimensions(dets, None, selected=selected)
    # protocol weighs 8, performance 6
    assert overall_score(dims) == round((60 * 8 + 90 * 6) / 14, 1)
    reasons = {d.dimension.value: d.reason for d in dims}
    assert reasons["model_identity"] == "Not selected in this custom run."
    assert reasons["protocol"] != "Not selected in this custom run."


def test_verdict_without_model_identity_is_judged_on_the_selection():
    # A custom run is judged on the dimensions it checked, and says it does
    # not speak to which model is served.
    dets = [_det(Dimension.PROTOCOL, 100.0)]
    dims = build_dimensions(dets, None, selected=["protocol"])
    v = build_verdict(dets, dims, profile_matched=True, used_judge=False, used_baseline=False,
                      selected=["protocol"])
    assert v.risk_level == RiskLevel.CLEAN and v.checked == ["protocol"]
    assert v.overall_score == 100.0
    assert v.headline.startswith("No problems found in the checked dimensions")
    assert "Custom run: 1 of 1 selected dimensions scored." in v.summary
    assert "Model identity was not selected" in v.summary


async def test_custom_audit_reports_its_selection(monkeypatch):
    from conftest import MockServer

    from zing.clients import make_client as real
    from zing.runner import run_audit

    server = MockServer()
    monkeypatch.setattr(
        "zing.runner.make_client", lambda config, **_: real(config, transport=server.transport)
    )
    events: list[dict] = []
    report = await run_audit(
        TargetConfig(name="t", kind="target", base_url=BASE_URL, model=DEFAULT_MODEL),
        AuditOptions(suite="custom", dimensions=["connectivity", "protocol"]),
        on_event=events.append,
    )
    assert report.suite == "custom" and report.dimensions_selected == ["connectivity", "protocol"]
    assert {d.dimension.value for d in report.detectors} == {"connectivity", "protocol"}
    assert next(e for e in events if e["type"] == "start")["dimensions"] == ["connectivity", "protocol"]
    scored = [d for d in report.dimensions if d.score is not None]
    assert {d.dimension.value for d in scored} <= {"connectivity", "protocol"}
    assert report.verdict.overall_score == overall_score(report.dimensions)


# --------------------------------------------------------------------------- #
# web + watches
# --------------------------------------------------------------------------- #
def test_audit_stream_custom_without_dimensions_errors():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from zing.web.server import create_app

    client = TestClient(create_app(), base_url="http://localhost")
    r = client.post(
        "/api/audit/stream",
        json={"base_url": "https://x.example/v1", "model": "gpt-4o", "suite": "custom"},
    )
    assert '"type": "error"' in r.text and "at least one dimension" in r.text


def test_watch_stores_its_dimensions(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    from zing.web import watches

    wid = watches.create({
        "base_url": "https://relay.test/v1", "model": "gpt-4o",
        "suite": "custom", "dimensions": ["billing", "performance"],
    })
    assert watches.get(wid)["dimensions"] == ["billing", "performance"]
    other = watches.create({"base_url": "https://relay.test/v1", "model": "gpt-4o"})
    assert watches.list_all()[0]["id"] == other and watches.get(other)["dimensions"] == []


def test_watches_api_validates_dimensions(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from zing.web.server import create_app

    client = TestClient(create_app(), base_url="http://localhost")
    base = {"base_url": "https://relay.test/v1", "model": "gpt-4o", "suite": "custom"}
    assert client.post("/api/watches", json=base).status_code == 400
    r = client.post("/api/watches", json={**base, "dimensions": ["security"]})
    assert r.status_code == 201
    row = next(w for w in client.get("/api/watches").json() if w["id"] == r.json()["id"])
    assert row["dimensions"] == ["security"]
