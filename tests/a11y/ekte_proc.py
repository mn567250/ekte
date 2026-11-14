"""A private ekte web server in a subprocess, for tests that change state.

The session server of harness.py is shared by every a11y test of a worker, so
flows that create monitors, set a master key or run audits get a server of
their own: a separate process (the data directory is process-wide state) with
a throwaway ``EKTE_DATA_DIR`` that holds the saved report fixture and,
optionally, the monitor scheduled from it and a week of runs for the Analytics
page (seed.py), with fixed timestamps so pages
render the same on every run.

``seed`` names a function of seed.py (``"seed_history_views"``) that adds runs
before the server starts (the History page's own tests).

``python -m tests.a11y.ekte_proc PORT DATA_DIR SEED_MONITOR [SEED]`` is what the
subprocess runs; :class:`EkteProc` starts and stops it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT_FIXTURE = ROOT / "tests" / "fixtures" / "web_report.json"
# 2026-10-01 12:00 UTC: the monitor's creation / profile pin time
FIXED_TS = 1790856000.0


def _wait_health(url: str, proc: subprocess.Popen[Any] | None = None, timeout: float = 30) -> None:
    import httpx

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"ekte server exited with {proc.returncode}")
        try:
            if httpx.get(url + "/api/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise RuntimeError("ekte server did not start")


class EkteProc:
    """``with EkteProc(tmp_path) as z: z.url``: a fresh ekte server."""

    def __init__(self, data_dir: Path, seed_monitor: bool = False, seed: str = "") -> None:
        from tests.a11y.harness import _free_port

        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.data_dir = data_dir
        self.seed_monitor = seed_monitor
        self.seed = seed
        self.proc: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> EkteProc:
        env = dict(os.environ, EKTE_DATA_DIR=str(self.data_dir), PYTHONPATH=str(ROOT))
        for k in ("EKTE_KB_DIR", "EKTE_NO_USER_KB", "EKTE_SECRET_KEY"):
            env.pop(k, None)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tests.a11y.ekte_proc", str(self.port), str(self.data_dir), str(int(self.seed_monitor)), self.seed],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
        )
        try:
            _wait_health(self.url, self.proc)
            # the subprocess seeds after its server is up; wait for that too
            end = time.monotonic() + 30
            while not (self.data_dir / ".seeded").exists():
                if time.monotonic() > end or self.proc.poll() is not None:
                    raise RuntimeError("ekte server did not finish seeding")
                time.sleep(0.05)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


def _fix_query_clock() -> None:
    """The query core's "now" at FIXED_TS, as the snapshot browsers' clock: a
    relative range (``range=30d``, the default of both pages) is resolved on the
    server, so the seeded week stays inside it and the page reads the same on
    every run."""
    from ekte.web import analytics_widgets, query

    class _Fixed(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return datetime.fromtimestamp(FIXED_TS, tz or UTC)

    query.datetime = _Fixed  # type: ignore[misc]
    analytics_widgets.datetime = _Fixed  # type: ignore[misc]


def _main(port: int, data_dir: Path, seed_monitor: bool, seed: str = "") -> None:
    import httpx
    import uvicorn

    from ekte.web import history, watches
    from ekte.web.server import create_app
    from tests.a11y import seed as seeds
    from tests.a11y.seed import seed_analytics

    history.init()
    rid = history.save(json.loads(REPORT_FIXTURE.read_text(encoding="utf-8")))
    # every server: History defaults to range=30d too (#152), so the saved
    # fixtures must stay inside the range on every run
    _fix_query_clock()
    if seed:
        getattr(seeds, seed)(datetime.fromtimestamp(FIXED_TS, UTC))
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    _wait_health(url)
    if seed_monitor:
        with httpx.Client(base_url=url, headers={"Origin": url}, timeout=30) as c:
            wid = c.post(f"/api/watches/from-history/{rid}", json={}).json()["id"]
        with watches._connect() as conn:
            conn.execute("UPDATE watches SET created_ts = ?, kb_pinned_ts = ? WHERE id = ?", (FIXED_TS, FIXED_TS, wid))
        # runs for /analytics, in the week before the snapshots' fixed clock
        seed_analytics(datetime.fromtimestamp(FIXED_TS, UTC), wid)
    (data_dir / ".seeded").write_text("ok", encoding="utf-8")
    thread.join()


if __name__ == "__main__":
    _main(int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "1", sys.argv[4] if len(sys.argv) > 4 else "")
