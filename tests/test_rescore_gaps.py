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
