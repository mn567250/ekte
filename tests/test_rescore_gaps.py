"""Re-scoring runs whose evidence does not answer every request of this ekte
version (#302, #303, #304)."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
import zstandard

from ekte import evidence, replay
from ekte.models import RescoreRef
from tests.test_replay import _record


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(evidence.ENV_OFF, raising=False)
    return tmp_path


def _rewrite(path, report, edit):
    """Rewrite evidence file ``path`` with ``edit(lines)`` (as an older ekte
    would have written it) and point ``report`` at the new file's hash."""
    lines = edit(list(evidence.iter_lines(path)))
    data = "".join(json.dumps(x) + "\n" for x in lines).encode("utf-8")
    path.write_bytes(zstandard.ZstdCompressor(level=evidence.LEVEL).compress(data))
    report["evidence"]["sha256"] = evidence.sha256_of(path)
    return report


def _without(detector):
    """An edit dropping every exchange of ``detector``: requests the recorded
    run never sent, as for a check added after it."""
    return lambda lines: [x for x in lines if x.get("type") != "exchange" or x.get("detector") != detector]


def _saved_chat(monkeypatch, suite="standard", edit=None, tool_version="0.1.0"):
    from ekte.web import history

    path = evidence.data_dir_path(evidence.new_run_id())
    report = _record(monkeypatch, path, suite=suite)
    if edit is not None:
        report = _rewrite(path, report, edit)
    report["tool_version"] = tool_version
    return history.save(report)


# --------------------------------------------------------------------------- #
# #302: a replay miss is logged once per run, without a traceback
# --------------------------------------------------------------------------- #
def test_missing_summary():
    ref = RescoreRef(run_id="r", evidence_sha256="x", missing={"security": 1, "billing": 3})
    assert replay.missing_summary(ref) == (
        "4 request(s) had no recorded answer (billing 3, security 1); those checks read inconclusive"
    )
    assert replay.missing_summary(RescoreRef(run_id="r", evidence_sha256="x")) is None
    assert replay.missing_summary(None) is None


def test_replay_misses_log_one_line_per_run_and_no_traceback(data, monkeypatch, caplog):
    from ekte.web import history, rescore

    rid = _saved_chat(monkeypatch, edit=_without("billing"))
    with caplog.at_level(logging.WARNING):
        _, new = asyncio.run(rescore.rescore_run(rid))
    assert new["rescored_from"]["missing"] == {"billing": 3}
    text = caplog.text
    assert "ekte failed on a request" not in text and "Traceback" not in text
    assert "ReplayMiss" not in text
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("re-score of run")]
    assert lines == [
        f"re-score of run {rid}: 3 request(s) had no recorded answer (billing 3); "
        "those checks read inconclusive"
    ]
    assert history.get(rid)["tool_version"] != "0.1.0"  # still re-scored


def test_a_complete_replay_logs_nothing(data, monkeypatch, caplog):
    from ekte.web import rescore

    rid = _saved_chat(monkeypatch, suite="smoke")
    with caplog.at_level(logging.WARNING):
        asyncio.run(rescore.rescore_run(rid))
    assert not [r for r in caplog.records if r.getMessage().startswith("re-score of run")]


def test_a_real_local_failure_keeps_its_traceback(caplog):
    import time

    from ekte.clients.base import BaseHTTPClient

    try:
        raise KeyError("boom")
    except KeyError as exc:
        err = exc
    with caplog.at_level(logging.WARNING):
        BaseHTTPClient._exception_outcome(_Bare(), err, time.perf_counter())
    assert "ekte failed on a request (KeyError)" in caplog.text


class _Bare:
    """Just enough of a client for ``_exception_outcome``."""

    def _extra_secrets(self):
        return []


# --------------------------------------------------------------------------- #
# #303: an embedding or rerank run's old "reliability" selection is "integrity"
# --------------------------------------------------------------------------- #
def _surface(name):
    if name == "embedding":
        from tests import test_embed_surface as m

        return m.EmbedServer(), m._target(), m._opts
    from tests import test_rerank_surface as m

    return m.RerankServer(), m._target(), m._opts


def _set_dimensions(dims):
    def edit(lines):
        lines[0]["options"]["dimensions"] = dims
        return lines

    return edit


@pytest.mark.parametrize("surface", ["embedding", "rerank"])
def test_an_old_reliability_selection_is_rescored_as_integrity(data, monkeypatch, surface):
    from ekte.clients import make_client as real
    from ekte.runner import run_audit
    from ekte.web import history, rescore

    server, target, opts = _surface(surface)
    path = evidence.data_dir_path(evidence.new_run_id())
    with pytest.MonkeyPatch.context() as mp:  # afterwards the replay answers from the file only
        mp.setattr("ekte.runner.make_client",
                   lambda config, **_: real(config, transport=server.transport))
        report = json.loads(asyncio.run(run_audit(
            target, opts(suite="custom", dimensions=["integrity"]), evidence=path)).model_dump_json())
    before = {d["id"]: (d["status"], d["score"]) for d in report["detectors"]}
    assert before and report["verdict"]["overall_score"] is not None
    # as an ekte before the integrity dimension recorded it
    report = _rewrite(path, report, _set_dimensions(["reliability"]))
    report["dimensions_selected"] = ["reliability"]
    report["tool_version"] = "0.1.0"
    rid = history.save(report)

    _, new = asyncio.run(rescore.rescore_run(rid))
    assert new["dimensions_selected"] == ["integrity"]
    assert {d["id"]: (d["status"], d["score"]) for d in new["detectors"]} == before
    integrity = next(d for d in new["dimensions"] if d["dimension"] == "integrity")
    assert integrity["status"] != "not_run" and integrity["score"] is not None
    assert new["verdict"]["overall_score"] == report["verdict"]["overall_score"]
    r = new["rescored_from"]
    assert r["missing"] == {} and r["unused"] == 0



# --------------------------------------------------------------------------- #
# #304: a re-score without a score is skipped with a refusal reason
# --------------------------------------------------------------------------- #
def _header_only(lines):
    """No exchange at all: every request of the re-score lacks an answer."""
    return lines[:1]


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    async def fake_send(url, report, **kw):
        calls.append({"url": url, "report": report, **kw})
        return True

    monkeypatch.setattr("ekte.notify.send", fake_send)
    return calls


def _unscored_on_a_monitor(monkeypatch):
    """A saved run of a monitor whose evidence answers nothing this ekte asks."""
    import time

    from ekte.web import history, watches

    wid = watches.create({"name": "w", "base_url": "http://relay/v1", "api_key": "", "model": "m",
                          "alert_on": "low", "webhooks": ["https://hooks.example/x"]})
    path = evidence.data_dir_path(evidence.new_run_id())
    report = _rewrite(path, _record(monkeypatch, path, suite="smoke"), _header_only)
    report["tool_version"] = "0.1.0"
    rid = history.save(report, watch_id=wid)
    risk, score = report["verdict"]["risk_level"], report["verdict"]["overall_score"]
    assert score is not None
    ran = time.time()
    watches.mark_run(wid, risk, score, rid, ran)
    return rid, wid, history.get(rid), (risk, score, ran)


def _unchanged(rid, wid, stored, card):
    from ekte.web import history, watches

    assert history.get(rid) == stored
    w = watches.get_settings(wid)
    assert (w["last_risk"], w["last_score"], w["last_run_ts"]) == card
    assert history.refusals()[rid]["refusal"] == replay.NO_SCORE


def test_rescore_all_skips_a_run_that_would_have_no_score(data, monkeypatch, sent):
    from ekte.web import rescore

    rid, wid, stored, card = _unscored_on_a_monitor(monkeypatch)
    seen = {}

    def on_run(r, old, new, refusal):
        seen[r] = (new, refusal)

    counts = asyncio.run(rescore.rescore_all(on_run))
    assert counts == {"rescored": 0, "skipped": 1, "failed": 0}
    assert seen == {rid: (None, replay.NO_SCORE)}
    _unchanged(rid, wid, stored, card)
    assert sent == []
    # recorded for this version: not looked at again
    assert asyncio.run(rescore.rescore_all(on_run)) == {"rescored": 0, "skipped": 0, "failed": 0}


def test_the_upgrade_rescore_counts_it_skipped_and_finishes(data, monkeypatch, sent, caplog):
    import time

    from fastapi.testclient import TestClient

    from ekte.web import history, rescore
    from ekte.web.server import create_app

    rid, wid, stored, card = _unscored_on_a_monitor(monkeypatch)
    scored = _saved_chat(monkeypatch, suite="smoke")
    monkeypatch.setenv("EKTE_AUTO_RESCORE", "1")
    with caplog.at_level(logging.WARNING), \
            TestClient(create_app(), base_url="http://localhost") as client:
        end = time.time() + 60
        while time.time() < end:
            info = client.get("/api/rescore").json()
            if not info["active"] and info.get("finished"):
                break
            time.sleep(0.1)
    assert (info["rescored"], info["skipped"], info["failed"]) == (1, 1, 0)
    assert "audit job" not in caplog.text and "Traceback" not in caplog.text
    msgs = [r.getMessage() for r in caplog.records]
    assert f"re-score of run {rid} not stored: {replay.NO_SCORE}" in msgs
    assert not [m for m in msgs if m.startswith(f"re-score of run {rid}: ")]
    _unchanged(rid, wid, stored, card)
    assert history.get(scored)["rescored_from"] is not None
    assert history.get_meta(rescore.META_KEY) is not None  # finished for this version
    assert sent == []


def test_a_single_rescore_job_is_refused_with_the_reason(data, monkeypatch):
    from fastapi.testclient import TestClient

    from ekte.web.server import create_app

    rid, wid, stored, card = _unscored_on_a_monitor(monkeypatch)
    monkeypatch.setenv("EKTE_AUTO_RESCORE", "0")
    with TestClient(create_app(), base_url="http://localhost") as client:
        job = client.post(f"/api/v1/history/{rid}/rescore?replace=true").json()
        client.get(f"/api/v1/jobs/{job['id']}/events")  # until it ends
        got = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert got["status"] == "error" and got["error"] == replay.NO_SCORE
    assert got["refused"] is True  # the UI shows it as a refusal, not a failure (#306)
    assert got["report_id"] is None
    _unchanged(rid, wid, stored, card)


def test_cli_rescore_refuses_to_store_a_run_without_a_score(data, monkeypatch):
    from typer.testing import CliRunner

    from ekte.cli import app

    rid, wid, stored, card = _unscored_on_a_monitor(monkeypatch)
    res = CliRunner().invoke(app, ["rescore", str(rid), "--replace"])
    assert res.exit_code == 2, res.output
    assert "not re-scored" in res.output
    _unchanged(rid, wid, stored, card)
    # only printed, nothing stored: shown as it is
    res = CliRunner().invoke(app, ["rescore", str(rid), "--no-save"])
    assert res.exit_code == 0, res.output


def test_the_refusal_text_is_translated():
    from ekte import i18n

    for lang, d in i18n._load().items():
        assert replay.NO_SCORE in d.get("strings", {}), lang


def test_job_info_tells_a_refusal_from_a_failure():
    """``refused`` in a job's info (#306): True only for a PublicRefusal."""
    from ekte.web import jobs

    async def go(exc):
        manager = jobs.JobManager(jobs.RelayGate())

        async def run(emit):
            raise exc

        job = manager.submit({"kind": "audit"}, [], run)
        await job.task
        return job.info()

    refused = asyncio.run(go(jobs.PublicRefusal("a fixed reason")))
    assert (refused["status"], refused["error"], refused["refused"]) == ("error", "a fixed reason", True)
    failed = asyncio.run(go(RuntimeError("internal detail")))
    assert failed["status"] == "error" and failed["refused"] is False
    assert "internal detail" not in failed["error"]  # a failure still shows only its type
