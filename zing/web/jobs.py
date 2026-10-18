"""Background audit jobs for `zing serve` — audits that outlive the page.

An audit started from the UI runs here as a job owned by the server, not by
the browser tab: the page that started it only *subscribes* to its events.
Switching pages, reloading or closing the tab detaches the subscriber and the
audit carries on; any page can re-attach later and gets the whole event log
replayed, then the live tail.

Relay gate: audits against the same relay never run at the same time. A
second audit for a relay that is busy is queued until the first one finishes,
so concurrency from zing itself never skews latency, throughput or
reliability results (and a locally hosted model is not asked to serve two
audits at once). Audits against different relays run in parallel, up to
:data:`MAX_PARALLEL`. Monitors (scheduled re-audits) take the same gate.

A relay is identified by host name (any port): two models served from one
machine usually share its GPU. Every loopback name counts as one host.
Waiters are served in arrival order; a later audit only overtakes one that
waits on a relay it does not use.

Jobs live in memory only. A finished job's report is in the history store;
the job itself is kept a little while so a re-attaching page still gets its
final event, then dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any, TypeVar

from zing.perf.trend import attach_trends
from zing.utils.net import is_loopback_host, url_host

_T = TypeVar("_T")

# How many audits may run at once across all relays.
MAX_PARALLEL = max(1, int(os.environ.get("ZING_MAX_PARALLEL_AUDITS", "4") or 4))

# Finished jobs are kept this long (and at most this many) for re-attaching pages.
_KEEP_FINISHED_SEC = 15 * 60
_KEEP_FINISHED_MAX = 20

Emit = Callable[[dict[str, Any]], None]
Runner = Callable[[Emit], Awaitable[dict[str, Any]]]


def relay_key(base_url: str | None) -> str:
    """The gate key of a relay URL: its lower-cased host name, any port."""
    host = url_host(base_url)
    return "localhost" if is_loopback_host(host) else host


# --------------------------------------------------------------------------- #
# Progress counters (shared with monitors)
# --------------------------------------------------------------------------- #


def track_progress(state: dict[str, Any], event: dict[str, Any]) -> None:
    """Fold one run_audit event into the progress counters of ``state``."""
    kind = event.get("type")
    if kind == "start":
        state["total"] = int(event.get("total") or 0)
        state["probe_planned"] = int(event.get("probe_requests") or 0)
    elif kind == "detector_start":
        state["current"] = event.get("id")
    elif kind == "detector_done":
        state["done"] = int(event.get("index", 0)) + 1
        state["current"] = None
    elif kind == "request_done":
        rec = event.get("record") or {}
        if rec.get("detector") == "performance" and rec.get("endpoint") == "target":
            state["probe_done"] = state.get("probe_done", 0) + 1


def progress_pct(state: dict[str, Any]) -> int:
    """Rough percent done of a run: finished detectors, plus how far the
    performance probe (by far the longest detector) is through its requests."""
    total = state.get("total") or 0
    if not total:
        return 0
    done = float(state.get("done") or 0)
    planned = state.get("probe_planned") or 0
    if state.get("current") == "performance" and planned:
        done += min(state.get("probe_done", 0) / planned, 1.0)
    return max(0, min(99, int(done * 100 / total)))


# --------------------------------------------------------------------------- #
# Relay gate
# --------------------------------------------------------------------------- #


class RelayGate:
    """At most one holder per relay key, at most ``limit`` holders overall.

    Loop-agnostic on purpose (no asyncio primitive is created up front), so a
    module-level gate works under any event loop, test loops included.
    """

    def __init__(self, limit: int = MAX_PARALLEL) -> None:
        self.limit = limit
        self._busy: dict[str, str] = {}  # relay key -> holder label
        self._holders = 0
        self._waiting: list[tuple[frozenset[str], asyncio.Future[None], str]] = []

    def busy_with(self, keys: Iterable[str]) -> list[str]:
        """The keys among ``keys`` another holder has right now."""
        return sorted(k for k in set(keys) if k in self._busy)

    def would_wait(self, keys: Iterable[str]) -> bool:
        keys = frozenset(keys)
        return (
            self._holders >= self.limit
            or bool(self.busy_with(keys))
            or any(keys & w[0] for w in self._waiting)
        )

    def _grant(self) -> None:
        claimed: set[str] = set()  # keys an earlier waiter still waits for
        for entry in list(self._waiting):
            keys, fut, label = entry
            if fut.done():  # cancelled while waiting
                self._waiting.remove(entry)
                continue
            if self._holders >= self.limit:
                return
            if keys & claimed or any(k in self._busy for k in keys):
                claimed |= keys
                continue
            self._waiting.remove(entry)
            self._take(keys, label)
            fut.set_result(None)

    def _take(self, keys: frozenset[str], label: str) -> None:
        for k in keys:
            self._busy[k] = label
        self._holders += 1

    def _release(self, keys: frozenset[str]) -> None:
        for k in keys:
            self._busy.pop(k, None)
        self._holders -= 1
        self._grant()

    @contextlib.asynccontextmanager
    async def hold(self, keys: Iterable[str], label: str = "") -> AsyncIterator[None]:
        """Wait until every key is free (and a slot is), hold them for the block."""
        keys = frozenset(keys)
        if not self.would_wait(keys):
            self._take(keys, label)
        else:
            fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            entry = (keys, fut, label)
            self._waiting.append(entry)
            try:
                await fut
            except BaseException:
                if entry in self._waiting:
                    self._waiting.remove(entry)
                if fut.done() and not fut.cancelled():
                    self._release(keys)  # granted just as we were cancelled
                else:
                    self._grant()  # we may have been holding back later waiters
                raise
        try:
            yield
        finally:
            self._release(keys)


gate = RelayGate()


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


_ACTIVE = ("queued", "running")


class Job:
    """One background audit: its state, its event log and its subscribers."""

    def __init__(self, summary: dict[str, Any], keys: frozenset[str]) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.summary = summary
        self.keys = keys
        self.status = "queued"
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.progress: dict[str, Any] = {}
        self.waiting_for: list[str] = []
        self.report_id: int | None = None
        self.error: str | None = None
        self.events: list[dict[str, Any]] = []
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.task: asyncio.Task[None] | None = None
        self.cancel_requested = False
        # Set while a finished audit is being saved: too late to cancel then.
        self.finishing = False

    @property
    def active(self) -> bool:
        return self.status in _ACTIVE

    def emit(self, event: dict[str, Any]) -> None:
        if event.get("type") == "detector_start":
            # When the check started (wall clock, like ``started``): a page
            # re-attaching mid-check times it from here, not from the replay.
            event.setdefault("at", time.time())
        track_progress(self.progress, event)
        self.events.append(event)
        for q in self._subscribers:
            q.put_nowait(event)

    def close(self, status: str, error: str | None = None) -> None:
        """End a job that is not driven by :class:`JobManager` (a running monitor)."""
        if not self.active:
            return
        self.status = status
        self.error = error
        self.finished = time.time()
        if status == "cancelled":
            self.emit({"type": "cancelled"})
        elif status == "error":
            self.emit({"type": "error", "message": error or "error"})
        self.emit({"type": "done"})
        self._subscribers.clear()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """A queue holding the log so far, then every new event until "done"."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for ev in self.events:
            q.put_nowait(ev)
        if self.active:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def info(self) -> dict[str, Any]:
        """What the history page shows for a job (no secrets: no keys, no events)."""
        return {
            "id": self.id,
            "kind": "audit",
            **self.summary,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "progress": progress_pct(self.progress) if self.status == "running" else None,
            "done": self.progress.get("done", 0),
            "total": self.progress.get("total", 0),
            "current": self.progress.get("current"),
            "waiting_for": list(self.waiting_for) if self.status == "queued" else [],
            "report_id": self.report_id,
            "error": self.error,
        }


class JobManager:
    def __init__(self, relay_gate: RelayGate = gate) -> None:
        self.gate = relay_gate
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        self._prune()
        return sorted(self._jobs.values(), key=lambda j: j.created)

    def submit(self, summary: dict[str, Any], urls: Iterable[str | None], run: Runner) -> Job:
        """Queue an audit; it starts as soon as its relays (and a slot) are free."""
        self._prune()
        keys = frozenset(relay_key(u) for u in urls if u)
        job = Job(summary, keys)
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._drive(job, run))
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if (
            job is None or not job.active or job.finishing
            or job.task is None or job.task.done()
        ):
            return False
        job.cancel_requested = True
        job.task.cancel()
        return True

    async def shutdown(self) -> None:
        """Stop every queued or running job (server shutdown)."""
        tasks = [j.task for j in self._jobs.values() if j.task is not None and not j.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _drive(self, job: Job, run: Runner) -> None:
        try:
            if self.gate.would_wait(job.keys):
                job.waiting_for = self.gate.busy_with(job.keys)
                job.emit({"type": "queued", "job": job.id, "waiting_for": job.waiting_for})
            async with self.gate.hold(job.keys, label=job.id):
                job.status = "running"
                job.started = time.time()
                job.waiting_for = []
                job.emit({"type": "running", "job": job.id})
                report = await run(job.emit)
                # The audit is over: store and report it as one step, even if
                # a cancel arrives while the save runs (off the loop).
                await settle(self._finish(job, report))
        except asyncio.CancelledError:
            if job.status != "done":  # else the save finished first (shutdown)
                job.status = "cancelled"
                job.emit({"type": "cancelled"})
            if not job.cancel_requested:
                raise  # server shutdown: let it propagate
        except Exception as exc:  # surface any audit failure to the client
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.emit({"type": "error", "message": job.error})
        finally:
            job.finished = time.time()
            job.emit({"type": "done"})
            job._subscribers.clear()

    @staticmethod
    async def _finish(job: Job, report: dict[str, Any]) -> None:
        job.finishing = True
        job.report_id = await asyncio.to_thread(_save, report)
        perf = report.get("performance")
        if isinstance(perf, dict) and isinstance(perf.get("requests"), list):
            attach_trends(perf["requests"])  # the chart's trend line (after saving: never stored)
        job.status = "done"
        job.emit({"type": "report", "report": report, "report_id": job.report_id})

    def _prune(self) -> None:
        now = time.time()
        finished = [j for j in self._jobs.values() if not j.active and j.finished is not None]
        finished.sort(key=lambda j: j.finished or 0)
        excess = len(finished) - _KEEP_FINISHED_MAX
        for i, j in enumerate(finished):
            if i < excess or now - (j.finished or now) > _KEEP_FINISHED_SEC:
                self._jobs.pop(j.id, None)


async def settle(aw: Awaitable[_T]) -> _T:
    """Await ``aw`` to the end even if the calling task is cancelled meanwhile.

    For a blocking write moved off the event loop (``asyncio.to_thread``) and
    the bookkeeping that belongs with it: a cancellation must not abandon the
    sequence half-way (a report saved but never recorded, a monitor dropped
    from the running set before its run is marked). The cancellation is not
    lost, only delayed: it is raised once ``aw`` has finished (and wins over
    an exception from it), so a server shutdown still propagates.
    """
    inner = asyncio.ensure_future(aw)
    cancelled = False
    while not inner.done():
        try:
            await asyncio.shield(inner)
        except asyncio.CancelledError:
            if inner.cancelled():
                raise
            cancelled = True
        except Exception:
            break  # inner failed: raised below, unless a cancel came first
    if cancelled:
        exc = None if inner.cancelled() else inner.exception()
        raise asyncio.CancelledError from exc
    return inner.result()


def _save(report: dict[str, Any]) -> int | None:
    """Best-effort persist to history; never let the store break the job."""
    try:
        from zing.web import history

        rid = history.save(report)
    except Exception:
        return None
    return rid if isinstance(rid, int) and rid >= 0 else None


manager = JobManager()


def sse(event: dict[str, Any]) -> str:
    # default=str so any unexpected evidence value can't break the stream.
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def stream(job: Job, batch_sec: float) -> AsyncIterator[str]:
    """SSE text for a subscriber: the replayed log, then live events to "done".

    Per-request records arrive in bursts (the reliability and probe bursts,
    or a whole replayed log); they are batched into one "requests" event per
    ``batch_sec`` window.
    """
    queue = job.subscribe()
    loop = asyncio.get_running_loop()
    pending: list[dict[str, Any]] = []
    flush_at = 0.0
    try:
        while True:
            timeout = max(0.0, flush_at - loop.time()) if pending else None
            try:
                event = await asyncio.wait_for(queue.get(), timeout)
            except asyncio.TimeoutError:
                yield sse({"type": "requests", "records": pending})
                pending = []
                continue
            if event.get("type") == "request_done":
                if not pending:
                    flush_at = loop.time() + batch_sec
                pending.append(event["record"])
                continue
            if pending:
                yield sse({"type": "requests", "records": pending})
                pending = []
            yield sse(event)
            if event.get("type") == "done":
                break
    finally:
        job.unsubscribe(queue)
