import pytest

from ekte.web import jobs


def test_running_monitor_is_followable_as_a_job():
    pytest.importorskip("fastapi")
    from ekte.web import server

    job = jobs.Job({"kind": "monitor", "watch_id": 7}, frozenset())
    job.id = "monitor-7"
    server._running_watches[7] = {"job": job}
    try:
        assert server._find_job("monitor-7") is job
        assert server._find_job("monitor-x") is None
        q = job.subscribe()
        job.close("done")
        assert [q.get_nowait()["type"] for _ in range(q.qsize())] == ["done"]
        assert job.info()["kind"] == "monitor"
    finally:
        server._running_watches.pop(7, None)
