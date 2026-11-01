"""FastAPI app for `ekte serve` — serves the SPA and streams live audits over SSE.

Endpoints:
  GET  /, /history, /watches, /analytics, /kb, /accessibility
                             the web UI pages (audit page at /); assets under /static/
  GET  /tools, /console      addresses of the removed classic UI: redirect (308)
                             to the audit page, keeping the query string
                             (deprecated, removed in 1.0.0)
  GET  /v2, /v2/…            the former page addresses: redirect (308) to the
                             page at the root, keeping the query string
                             (deprecated, removed in 1.0.0)
  GET  /api/health          {ok, version}
  GET  /api/kb               providers (base URLs, saved relays) and their models
  POST /api/kb/relays        save a relay {name, base_url} in kb.db
  GET  /api/kb/profiles      models, providers and relays (complete sets, sources,
                             on/off state) + your kb.db entries
  PUT  /api/kb/enabled       switch one model, provider or relay on or off {key, enabled}
  GET  /api/kb/prompt        research prompt for an external AI (?model=&provider=)
  POST /api/kb/scan          check uploaded profile YAML (writes nothing)
  POST /api/kb/import        check + store profile YAML in kb.db
  GET  /api/kb/export        your kb.db entries as YAML
  POST /api/models           list a relay's /models (connection check + model ids)
  POST /api/jobs             queue an audit (any surface: chat, embedding, rerank)
                             as a background job; it runs on whatever page is open
  GET  /api/jobs             queued and running audits (and running monitors),
                             recently finished ones too, with progress
  GET  /api/jobs/{id}/events the job's events as SSE: the log so far, then live
  POST /api/jobs/{id}/cancel stop a queued or running job
  POST /api/report/export    a report (JSON body) rendered as a download
                             (?format=json|md|html|pdf)
  GET  /api/analytics/options      filter values in the run history (relays,
                                   models, suites, stream modes, APIs, dates)
  GET  /api/analytics/summary      KPIs of a range vs. the previous range
  GET  /api/analytics/series       one metric per relay / model over time buckets
  GET  /api/analytics/leaderboard  relays of a model, or models of a relay
  GET  /api/analytics/breakdown    some metrics per relay / model over the range
  GET  /api/analytics/errors       request outcomes (429, 5xx, timeouts, …) per
                                   relay / model and over time buckets
  GET  /api/analytics/integrity    identity, context window and capability
                                   checks per relay x model
                                   (parameters: ekte/web/analytics.py)
  GET  /api/secret           the monitors' master key: state, fingerprint,
                             allowed actions (never the key)
  POST /api/secret/new       a new master key, shown once …
  POST /api/secret/new/confirm  … and adopted once typed back {key}
  POST /api/secret/unlock    enter the master key {key} after a restart
  POST /api/secret/lock      forget it; monitors pause
  POST /api/secret/reset     the key is lost: drop the encrypted API keys
  POST /api/secret/storage   {mode: "memory" | "encrypted"}: store no API key
                             (held in memory until a restart) or store them
                             encrypted; moves the keys along

Public API (docs/reference/stability.md#surface-http-api): the same handlers also answer
under /api/v1/ (POST /jobs, GET /jobs/{id}, GET /jobs/{id}/events, GET /history,
GET /history/{id}); responses there carry `X-Ekte-API: v1`. Every other /api/
response carries `X-Ekte-API: internal`.

The audit runs in-process with the same `run_audit` the CLI uses; a progress
callback pushes per-detector events into a queue the SSE generator drains. The
final report is the model's own redacted `model_dump` (API key fingerprinted,
relay text scrubbed), so nothing secret crosses to the browser.

Every audit runs as a job (ekte/web/jobs.py): audits of the same relay are
queued one after another so they never skew each other's measurements;
different relays run in parallel. A job is detached from the page that queued it.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# fastapi is the optional [web] extra. This module is only imported when serving
# (CLI `serve`) or by the web tests, both of which handle a missing dependency.
from fastapi import FastAPI, Request
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from ekte import __version__
from ekte.clients import detect_api
from ekte.config import (
    AuditOptions,
    ConfigError,
    build_target,
    validate_api,
    validate_dimensions,
    validate_suite,
    validate_surface,
)
from ekte.detectors.performance import stream_mode
from ekte.models import KnowledgeUsage, TargetConfig
from ekte.perf.trend import attach_trends
from ekte.runner import run_audit
from ekte.scoring import weights_for
from ekte.web import jobs
from ekte.web.caching import (
    GZIP_MINIMUM_SIZE,
    CachedStaticFiles,
    CompressionMiddleware,
    encoded_response,
    html_page,
)
from ekte.web.security import LocalOnlyMiddleware

_STATIC = Path(__file__).parent / "static"
_STATIC_UI = _STATIC / "v2"  # the pages and their assets, served at / and /static/

# Removal version of the compatibility redirects below (docs/reference/stability.md).
_REMOVED_IN = "1.0.0"
_DEPRECATION_WARNING = (
    '299 ekte "this address is deprecated and will stop redirecting in ekte ' + _REMOVED_IN + '"'
)

# The classic UI was removed: its addresses (bookmarks, old links) redirect to
# the matching page, keeping the query string (e.g. ?rerun=<id>). The console
# had no counterpart; the audit page took over its advanced options. (/, /history
# and /watches are pages again, at the same addresses.) Deprecated: removed in
# 1.0.0 (#26).
_CLASSIC_REDIRECTS: dict[str, str] = {
    # there is no Tools page: embedding and rerank audits start on the audit
    # page through its endpoint-type selector.
    "/tools": "/?surface=embedding",
    "/console": "/",
}

# The pages, served at the root, and the file each one is.
_PAGE_FILES: dict[str, str] = {
    "/": "index.html",
    "/history": "history.html",
    "/watches": "watches.html",
    "/kb": "kb.html",
    "/analytics": "analytics.html",
    "/accessibility": "accessibility.html",
}

# Until 1.0.0 (#28) the pages were served under /v2/. Those addresses redirect
# permanently to the page at the root, keeping the query string. /v2/tools was
# retired earlier for the audit page's endpoint-type selector; the old page
# picked its rerank tab by the URL fragment (#rerank), which the browser keeps
# across the redirect and the audit page reads.
_V2_REDIRECTS: dict[str, str] = {
    "/v2": "/",
    "/v2/": "/",
    **{"/v2" + path: path for path in _PAGE_FILES if path != "/"},
    "/v2/tools": "/?surface=embedding",
}

# How often the watch scheduler wakes to look for due re-audits. The interval an
# individual watch runs on is its own (much larger) interval_sec; this is just
# the polling tick.
_SCHEDULER_TICK_SEC = 30.0

# Live per-request events are batched into one SSE message per window.
_REQUEST_BATCH_SEC = 0.25


def _deprecated_redirect(request: Request, target: str) -> Response:
    """A permanent redirect to ``target`` for an address that is deprecated,
    with the request's query string."""
    query = request.url.query
    if query:
        target += ("&" if "?" in target else "?") + query
    return RedirectResponse(target, status_code=308, headers={"Warning": _DEPRECATION_WARNING})


def _page(request: Request, path: str) -> Response:
    return html_page(_STATIC_UI / _PAGE_FILES[path], request.scope)


def check_surface_dimensions(surface: str, dimensions: list[str]) -> None:
    """Refuse a custom suite's dimensions that ``surface`` does not audit.

    The chat dimensions mean nothing to an embedding or rerank audit; /api/jobs
    and /api/watches share this check so both answer 400 the same way.
    Raises ConfigError.
    """
    if surface == "chat":
        return
    own = {d.value for d in weights_for(surface)}
    other = [d for d in dimensions if d not in own]
    if other:
        raise ConfigError(f"Dimensions not audited on the {surface} surface: {', '.join(other)}")


def _coerce_int(value: Any) -> int:
    """Best-effort int from JSON input (str/float/None all tolerated). 0 on failure."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _watch_protocol(row: dict[str, Any]) -> dict[str, Any]:
    """A watch's protocol (what ``auto`` resolves to now), whether it is
    auto-detected, and its probe request mode — for the monitor card and the
    in-progress list."""
    configured = (row.get("api") or "auto").lower()
    try:
        resolved = detect_api(
            TargetConfig(base_url=row.get("base_url") or "", model=row.get("model") or "", api=configured)
        )
    except Exception:
        resolved = None
    if (row.get("surface") or "chat") != "chat":
        # embedding and rerank requests never stream: no probe request mode to show
        return {"api_resolved": resolved, "api_auto": configured == "auto", "stream_mode": None}
    mode = stream_mode(AuditOptions(
        suite=str(row.get("suite") or "standard"),
        performance_streaming=row.get("performance_streaming") is not False,
    ))
    return {"api_resolved": resolved, "api_auto": configured == "auto", "stream_mode": mode}


def _watch_knowledge(row: dict[str, Any], kb: Any = None) -> dict[str, Any]:
    """KnowledgeUsage (with profile snapshot) a watch's claimed model resolves to now."""
    from ekte.knowledge import load_knowledge_base
    from ekte.knowledge.snapshot import knowledge_usage

    claimed = str(row.get("claimed_model") or row.get("model") or "")
    # resolving and describing only read the KB: the shared instance will do
    kb = kb if kb is not None else load_knowledge_base(copy=False)
    resolved = kb.resolve(claimed, row.get("declared_provider") or None)
    return knowledge_usage(kb, resolved, claimed).model_dump(mode="json")


# Watches whose audit is executing right now (scheduler or Run now), keyed by
# id, so the UI can show which monitors run, how far along they are, cancel
# one, and nothing runs twice at once. Each value is the run's live state:
# its asyncio task plus the progress counters fed by run_audit's events.
_running_watches: dict[int, dict[str, Any]] = {}

# Intervals (minutes) a monitor can be scheduled at: never more often than one
# run takes, rounded up to one of these, and at most once every 24 h.
_INTERVAL_STEPS_MIN = (5, 10, 15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440)


def _min_interval_sec(duration_sec: float | None) -> int:
    """The shortest offered interval that is not shorter than one run takes."""
    for step in _INTERVAL_STEPS_MIN:
        if not duration_sec or step * 60 >= duration_sec:
            return step * 60
    return _INTERVAL_STEPS_MIN[-1] * 60


class WatchAlreadyRunning(Exception):
    """Raised when a watch is asked to run while its previous run is still going."""


class WatchCancelled(Exception):
    """Raised when a running watch was stopped with Cancel."""


class WatchKeyUnreadable(Exception):
    """Raised when a watch's stored API key no longer decrypts (master key lost
    or changed); the key must be re-entered before the watch can run."""


class WatchLocked(Exception):
    """Raised when a watch's API key waits for the master key to be entered."""


class WatchKeyMissing(Exception):
    """Raised when a watch's API key is not stored and was lost with a restart;
    the run waits until the user enters it again."""


_log = logging.getLogger("ekte.web")


# Progress counters are shared with background audit jobs (see jobs.py).
_watch_progress = jobs.progress_pct
_track_progress = jobs.track_progress


async def _run_one_watch(row: dict[str, Any]) -> None:
    """Run a watch once, refusing to overlap with a run already in flight.

    The run executes as its own task so Cancel can stop it; a cancelled run
    raises :class:`WatchCancelled` (an ordinary exception, so the scheduler
    loop carries on), while a server shutdown still propagates CancelledError.
    """
    wid = int(row["id"])
    if wid in _running_watches:
        raise WatchAlreadyRunning(wid)
    if row.get("key_locked"):
        # Not a failure: the run waits for the master key, and runs as soon as
        # it is entered (the run time is left alone so it is still due then).
        raise WatchLocked(wid)
    if row.get("key_missing"):
        # Not a failure either: keys are not stored, so the run waits for the
        # user to enter the key again (no alert, the run time is left alone).
        raise WatchKeyMissing(wid)
    if row.get("key_error"):
        # Never audit with a missing key: it would fail and alert falsely.
        # Move the run time on (so the scheduler doesn't retry every tick)
        # and keep the last result on the card.
        from ekte.web import watches

        with contextlib.suppress(Exception):
            await asyncio.to_thread(watches.mark_attempt, wid, time.time())
        raise WatchKeyUnreadable(row["key_error"])
    state: dict[str, Any] = {
        "cancelled": False,
        "name": row.get("name"),
        "base_url": row.get("base_url"),
        "model": row.get("model"),
        "claimed_model": row.get("claimed_model") or row.get("model"),
        "suite": row.get("suite") or "standard",
        "since": time.time(),
        **_watch_protocol(row),
    }
    # The run's event log, so the live view can follow a monitor like an audit.
    job = jobs.Job(
        {
            "kind": "monitor",
            "watch_id": wid,
            "base_url": state["base_url"],
            "model": state["model"],
            "claimed_model": state["claimed_model"],
            "suite": state["suite"],
            "api": state.get("api_resolved"),
            "api_auto": state.get("api_auto"),
            "stream_mode": state.get("stream_mode"),
        },
        frozenset(),
    )
    job.id = f"monitor-{wid}"
    job.created = state["since"]
    state["job"] = job
    _running_watches[wid] = state
    outcome, error = "done", None
    try:
        task = asyncio.create_task(_run_one_watch_inner(row, state))
        state["task"] = task
        try:
            await task
        except asyncio.CancelledError:
            outcome = "cancelled"
            if state["cancelled"]:
                raise WatchCancelled(wid) from None
            raise
        except Exception as exc:
            outcome, error = "error", f"{type(exc).__name__}: {exc}"
            raise
    finally:
        job.close(outcome, error)
        _running_watches.pop(wid, None)


def _find_job(job_id: str) -> jobs.Job | None:
    """A background audit job, or the live job of a running monitor (``monitor-<id>``)."""
    job = jobs.manager.get(job_id)
    if job is None and job_id.startswith("monitor-"):
        try:
            state = _running_watches.get(int(job_id[len("monitor-"):]))
        except ValueError:
            state = None
        job = state.get("job") if state else None
    return job


def _cancel_watch(wid: int) -> bool:
    """Stop a running watch; False when it is not running."""
    state = _running_watches.get(wid)
    task = state.get("task") if state else None
    if state is None or task is None or task.done() or state.get("saving"):
        return False  # not running, or saving its report: too late to cancel
    state["cancelled"] = True
    task.cancel()
    return True


async def _run_one_watch_inner(row: dict[str, Any], state: dict[str, Any] | None = None) -> None:
    """Run a single due watch once: audit, persist, alert on regression/threshold.

    Always best-effort — any exception is swallowed by the caller so one bad
    watch can never kill the scheduler loop. The watch's run timestamp is
    recorded even on failure so a permanently broken target doesn't get retried
    every tick.
    """
    from ekte.web import history, watches

    wid = int(row["id"])
    now = time.time()
    risk: str | None = None
    score: float | None = None
    report_id: int | None = None
    duration: float | None = None
    cancelled = False
    saved = False  # a run whose report is stored is recorded with it, even if cancelled
    try:
        suite = validate_suite(str(row.get("suite") or "standard"))
        dimensions = validate_dimensions(suite, row.get("dimensions"))
        target = build_target(
            kind="target",
            name=row.get("name") or "watch",
            base_url=row.get("base_url"),
            api_key=row.get("api_key"),
            model=row.get("model"),
            claimed_model=row.get("claimed_model") or None,
            declared_provider=row.get("declared_provider") or None,
            api=validate_api(row.get("api")),
        )
        surface = validate_surface(row.get("surface"))
        options = AuditOptions(
            suite=suite,
            dimensions=dimensions,
            performance_streaming=row.get("performance_streaming") is not False,
            surface=surface,
            embedding_dimensions=(
                max(0, _coerce_int(row.get("embedding_dimensions"))) if surface == "embedding" else 0
            ),
        )
        claimed = target.claimed_model or target.model
        # A non-chat run's drift check (vectors, rankings) compares with the
        # previous saved run of the same surface, target and model (best-effort).
        drift_ref: dict[str, Any] | None = None
        if surface != "chat":
            with contextlib.suppress(Exception):
                drift_ref = await asyncio.to_thread(
                    history.latest_for, target.base_url, claimed, surface
                )

        # Audit against the profile pinned when the watch was created, so a
        # knowledge-base edit cannot silently change what the monitor measures.
        # A blocking SQLite read: run in a worker thread, off the loop.
        pinned_raw = await asyncio.to_thread(watches.pinned_knowledge, wid)
        pinned = KnowledgeUsage(**pinned_raw) if pinned_raw else None

        job = state.get("job") if state is not None else None

        def on_event(ev: dict[str, Any]) -> None:
            if state is not None:
                _track_progress(state, ev)
            if job is not None:
                job.emit(ev)

        # One audit per relay at a time: wait while another audit uses it.
        keys = [jobs.relay_key(target.base_url)]
        if state is not None:
            state["waiting_for"] = jobs.gate.busy_with(keys)
        if job is not None and state is not None and jobs.gate.would_wait(keys):
            job.waiting_for = list(state["waiting_for"])
            job.emit({"type": "queued", "job": job.id, "waiting_for": job.waiting_for})
        async with jobs.gate.hold(keys, label=f"monitor:{wid}"):
            # The run's time is when its audit starts, not when it was due:
            # a monitor that waited for its relay must not come due again at once.
            now = time.time()
            if state is not None:
                state["waiting_for"] = []
                state["started"] = True
            if job is not None:
                job.status = "running"
                job.started = time.time()
                job.waiting_for = []
                job.emit({"type": "running", "job": job.id})
            started = time.perf_counter()
            report = await run_audit(
                target,
                options,
                baseline=None,
                mode="check",
                pinned=pinned,
                on_event=on_event,
                previous_report=drift_ref,
            )
            duration = time.perf_counter() - started
        report_dict = json.loads(report.model_dump_json())
        previous: dict[str, Any] | None = None

        def save() -> int:
            # Blocking SQLite: run in a worker thread, off the loop.
            nonlocal previous
            # Previous saved run for this target+model — used for the regression
            # check and the "since last run" delta in the alert (notify.send needs
            # the full report). Read after the audit, so a run of the same target
            # that queued ahead of this one on the relay counts; one indexed
            # lookup, found however many runs of other targets were saved since.
            # Best-effort, like save: a failed read must not lose the report.
            with contextlib.suppress(Exception):
                # chat looks up as before; another surface only among its own runs
                previous = history.latest_for(
                    target.base_url, claimed, surface=None if surface == "chat" else surface
                )
            return history.save(report_dict, watch_id=wid)

        async def store() -> None:
            # Save off the loop and report it, as one step (see jobs.settle).
            nonlocal report_id, saved
            rid = await asyncio.to_thread(save)
            report_id = rid if rid is not None and rid >= 0 else None
            saved = True
            if job is not None:
                job.report_id = report_id
                job.emit({"type": "report", "report": report_dict, "report_id": report_id})

        if state is not None:
            state["saving"] = True  # Cancel is refused meanwhile
        try:
            await jobs.settle(store())
        finally:
            if state is not None:
                state["saving"] = False

        verdict = report_dict.get("verdict") or {}
        # report_dict came through model_dump_json, so risk_level is a plain str.
        raw_risk = verdict.get("risk_level")
        risk = raw_risk if isinstance(raw_risk, str) else None
        raw_score = verdict.get("overall_score")
        score = float(raw_score) if isinstance(raw_score, (int, float)) else None

        # Decide whether to alert: risk crossed the configured threshold, OR it
        # regressed versus the previous saved run.
        from ekte.notify import regressed, send

        alert_on = str(row.get("alert_on") or "medium")
        crossed = _risk_meets(risk, alert_on)
        went_worse = regressed(report_dict, previous)
        if crossed or went_worse:
            # All webhooks at once: a dead one (10 s timeout) must not hold up
            # the others or the run's completion. send never raises; any
            # exception that slips through is returned by gather and dropped.
            urls = dict.fromkeys(
                url.strip()
                for url in row.get("webhooks") or []
                if isinstance(url, str) and url.strip()
            )
            await asyncio.gather(
                *(
                    send(url, report_dict, previous=previous, lang=row.get("language"))
                    for url in urls
                ),
                return_exceptions=True,
            )
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        # Record the run no matter what so cadence stays honest. A run
        # cancelled before its report was stored keeps the previous result on
        # the card, only its time moves on.
        def mark() -> None:
            if cancelled and not saved:
                watches.mark_attempt(wid, now)
            else:
                watches.mark_run(wid, risk, score, report_id, now, duration_sec=duration)

        # Off the loop, but finished before the caller drops the watch from
        # _running_watches (else the scheduler could see it due again); a
        # cancel meanwhile is raised once the run is recorded.
        with contextlib.suppress(Exception):
            await jobs.settle(asyncio.to_thread(mark))


def _risk_meets(risk: str | None, threshold: str) -> bool:
    """True when ``risk`` is at or above the ``threshold`` risk level."""
    from ekte.models import RiskLevel

    order = {
        RiskLevel.CLEAN.value: 0,
        RiskLevel.INCONCLUSIVE.value: 1,
        RiskLevel.LOW.value: 2,
        RiskLevel.MEDIUM.value: 3,
        RiskLevel.HIGH.value: 4,
    }
    if not risk:
        return False
    return order.get(risk, 0) >= order.get(threshold, order[RiskLevel.MEDIUM.value])


# Runs the scheduler started, keyed by watch id: an entry exists from the
# moment its task is created until it finishes, so a watch whose task has not
# yet reached _running_watches is not started again on the next tick. Loop-owned
# (only touched on the event loop); _lifespan cancels what is left on shutdown.
_scheduled_watch_tasks: dict[int, asyncio.Task[None]] = {}


async def _scheduled_watch_run(row: dict[str, Any]) -> None:
    """One scheduler-started run: every failure is swallowed so it stays local
    to its watch; cancellation (server shutdown) propagates."""
    try:
        await _run_one_watch(row)
    except asyncio.CancelledError:
        raise
    except Exception:
        # One bad watch must never take down the others or the loop.
        pass


def _start_scheduled_watch(row: dict[str, Any]) -> None:
    """Start a due watch as its own task unless it is already running or started."""
    wid = int(row["id"])
    if wid in _running_watches or wid in _scheduled_watch_tasks:
        return
    task = asyncio.create_task(_scheduled_watch_run(row), name=f"ekte-monitor-{wid}")
    _scheduled_watch_tasks[wid] = task

    def done(t: asyncio.Task[None]) -> None:
        if _scheduled_watch_tasks.get(wid) is t:
            del _scheduled_watch_tasks[wid]

    task.add_done_callback(done)


async def _cancel_scheduled_watches() -> None:
    """Cancel the scheduler's runs (server shutdown) and wait until they ended."""
    tasks = list(_scheduled_watch_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _scheduler_loop() -> None:
    """Poll for due watches every tick and start each one (best-effort, idle-quiet).

    If nothing is due, the loop does nothing and the server stays silent. Each
    due watch runs as its own task, so monitors on different relays audit at
    the same time; the relay gate (jobs.gate) still runs one audit per relay
    and caps how many run at once. A failure stays inside its watch's task.
    Cancellation (on server shutdown) propagates cleanly; _lifespan cancels
    the runs themselves.
    """
    from ekte.web import watches
    from ekte.web.masterkey import vault

    def due_now() -> list[dict[str, Any]]:
        # Notice another process changing the master key. While it is
        # locked, watches that need it raise WatchLocked and wait; keyless
        # and env:/file: ones run as usual.
        vault.verify()
        return watches.due(time.time())

    while True:
        try:
            # SQLite reads (and the key check): off the loop.
            due = await asyncio.to_thread(due_now)
        except Exception:
            due = []
        for row in due:
            _start_scheduled_watch(row)
        await asyncio.sleep(_SCHEDULER_TICK_SEC)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Spawn the watch scheduler on startup; cancel it cleanly on shutdown."""
    from ekte.web.masterkey import vault

    try:
        _log_secret_key(vault.startup())
        vault.take_stored_keys()
    except Exception as exc:
        _log.warning("watch store: %s", exc)
    task = asyncio.create_task(_scheduler_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        # The loop is stopped, so no new runs start; end the ones in flight.
        with contextlib.suppress(Exception):
            await _cancel_scheduled_watches()
        with contextlib.suppress(Exception):
            await jobs.manager.shutdown()


def _log_secret_key(status: dict[str, Any]) -> None:
    """Say once at startup whether the monitors' master key is loaded."""
    state = status.get("state")
    if status.get("storage") == "memory":
        _log.warning(
            "monitor API keys are not stored: they stay in memory until ekte serve stops "
            "(choose on the Monitors page)"
        )
    elif state == "unlocked":
        _log.warning(
            "monitor API keys are encrypted with the master key from %s (fingerprint %s)",
            status.get("source"), status.get("fingerprint"),
        )
    elif state == "locked":
        _log.warning("master key locked: monitors are paused until it is entered at /watches")
    elif state == "env_mismatch":
        _log.error("master key: %s", status.get("error"))
    if "legacy_key_file" in status.get("warnings", []):
        _log.warning(
            "the master key is still stored next to the databases (secret.key): "
            "move it out on the Monitors page"
        )
    if "env_in_data_dir" in status.get("warnings", []):
        _log.warning("EKTE_SECRET_KEY points into the data directory: keep the key elsewhere")


def _key_storage_override(body: Any) -> str | None:
    """``memory`` when the request asks for its key not to be stored;
    never a way to store a key against the setting."""
    if isinstance(body, dict) and body.get("key_storage") == "memory":
        return "memory"
    return None


def _missing_key_response() -> JSONResponse:
    return JSONResponse(
        {"error": "the API key is not stored and ekte serve restarted: enter it again",
         "key_missing": True},
        status_code=409,
    )


def _locked_response(_exc: Exception | None = None) -> JSONResponse:
    """423: the master key has to be entered (or created) first."""
    from ekte.web.masterkey import vault

    st = vault.status()
    return JSONResponse(
        {"error": "the master key is locked: enter it first" if st["state"] != "uninitialized"
         else "create a master key first", "locked": True, "state": st["state"]},
        status_code=423,
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="ekte",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    # Local-only: Host allowlist (DNS rebinding), Origin + JSON checks (CSRF),
    # security headers. See ekte/web/security.py. Added last, so it runs first:
    # refused requests never reach the gzip layer below it.
    app.add_middleware(CompressionMiddleware)  # gzip >= 1 KiB, never for SSE
    app.add_middleware(LocalOnlyMiddleware)

    @app.get("/api/health")
    async def health() -> Any:
        return {"ok": True, "version": __version__, "name": "ekte"}

    # ----- the web UI ---------------------------------------------------- #
    def _add_page(path: str) -> None:
        async def page(request: Request) -> Any:
            return _page(request, path)

        app.get(path, name="page" + (path.replace("/", "-") or "-audit"))(page)

    for _path in _PAGE_FILES:
        _add_page(_path)

    # Deprecated addresses, removed in 1.0.0: the classic UI's and the /v2/ ones.
    def _add_redirect(path: str, target: str) -> None:
        async def redirect(request: Request) -> Any:
            return _deprecated_redirect(request, target)

        app.get(path, name="redirect" + path.replace("/", "-"))(redirect)

    for _path, _target in {**_CLASSIC_REDIRECTS, **_V2_REDIRECTS}.items():
        _add_redirect(_path, _target)

    # stylesheets / scripts, e.g. /static/ekte.css
    # `?v=<hash>` URLs (written into pages by html_page) are cached immutably.
    app.mount("/static", CachedStaticFiles(directory=str(_STATIC_UI)), name="static")
    root_assets = CachedStaticFiles(directory=str(_STATIC))

    @app.get("/i18n.js")
    async def i18n_js(request: Request) -> Any:
        return root_assets.asset("i18n.js", request.scope, "application/javascript")

    @app.get("/locales.js")
    async def locales_js(request: Request) -> Any:
        # Translation data (ekte/i18n/locales/*.json) + the lookup logic: one
        # language's for ?lang= or the ekte_lang cookie lang.js writes (the
        # zing_lang cookie of an install from before the rename until lang.js
        # has written ekte_lang), else every language (built and gzipped once,
        # revalidated by ETag; see encoded_response).
        from ekte.i18n import locales_encoded

        q = request.query_params.get("lang")
        lang = q if q is not None else (request.cookies.get("ekte_lang") or request.cookies.get("zing_lang"))
        # A (re)build serializes and compresses up to ~800 KiB: off the event loop.
        body, etag, gz = await asyncio.to_thread(locales_encoded, lang)
        headers = {"Cache-Control": "no-cache"}
        if q is None:
            headers["Vary"] = "Cookie"
        return encoded_response(
            request.scope, body, etag, gz if len(body) >= GZIP_MINIMUM_SIZE else None,
            media_type="application/javascript", headers=headers,
        )

    @app.get("/lang.js")
    async def lang_js(request: Request) -> Any:
        return root_assets.asset("lang.js", request.scope, "application/javascript")

    @app.get("/icons.js")
    async def icons_js(request: Request) -> Any:
        return root_assets.asset("icons.js", request.scope, "application/javascript")

    @app.get("/perf.js")
    async def perf_js(request: Request) -> Any:
        return root_assets.asset("perf.js", request.scope, "application/javascript")

    @app.get("/secretfield.js")
    async def secretfield_js(request: Request) -> Any:
        return root_assets.asset("secretfield.js", request.scope, "application/javascript")

    # Handlers that do blocking work (SQLite, YAML/JSON parsing, the knowledge
    # base load, file reads) are plain `def`: Starlette runs them in its thread
    # pool, so the event loop (live audits timestamp chunks on it) never stalls.
    # Async handlers that must await the request body offload only the blocking
    # part with asyncio.to_thread; anything touching loop-owned state
    # (_running_watches, jobs, tasks) stays on the loop.
    @app.get("/api/kb")
    def kb() -> Any:
        # Public model metadata only — no keys, no secrets. Mirrors the grouping
        # the CLI `kb --json` command uses: providers sorted, each with its models.
        from ekte.knowledge import load_knowledge_base

        # base_urls: the usable base URLs from the provider's hints (the relay
        # configuration fills the first one in); relay: a relay the user saved
        # (or any provider without models); kind: chat or embedding model.
        from ekte.knowledge.relays import base_urls, is_relay

        # only read: the shared cached instance (see load_knowledge_base)
        knowledge = load_knowledge_base(copy=False)
        provs = sorted(knowledge.providers.values(), key=lambda p: p.provider)
        providers = []
        for prov in provs:
            entry = knowledge.entries.get(f"provider:{prov.provider}")
            providers.append({
                "provider": prov.provider,
                "display_name": prov.display_name,
                "base_urls": base_urls(prov),
                "relay": is_relay(prov, entry),
                "entry_id": (entry or {}).get("id"),
                "models": [
                    {"id": m.id, "aliases": list(m.aliases),
                     "kind": "embedding" if m.embedding_dimensions else "chat"}
                    for m in prov.models
                ],
            })
        return JSONResponse({"providers": providers})

    @app.post("/api/kb/relays")
    async def kb_add_relay(request: Request) -> Any:
        # Save a relay (name + base URL) as a provider entry in kb.db.
        from ekte.knowledge.relays import RelayError, add_relay

        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        try:
            saved = await asyncio.to_thread(add_relay, str(body.get("name") or ""), str(body.get("base_url") or ""))
        except RelayError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        return JSONResponse(saved, status_code=201)

    # ----- Knowledge base: browse, research prompt, import/export -------- #
    @app.get("/api/kb/profiles")
    def kb_profiles() -> Any:
        # The Knowledge page: models, providers and relays, each the complete
        # set (packaged, EKTE_KB_DIR and kb.db) with its on/off state — see
        # ekte/knowledge/catalog.py — plus the user's kb.db entries (no bodies).
        from ekte.knowledge import catalog, store

        data = catalog.catalog()
        data["entries"] = [{k: v for k, v in e.items() if k != "body"} for e in store.list_entries()]
        return JSONResponse(data)

    @app.put("/api/kb/enabled")
    async def kb_set_enabled(request: Request) -> Any:
        # Switch one item on or off: {key: "model:p/id" | "provider:p" | "entry:<id>", enabled}.
        from ekte.knowledge import catalog

        body = await request.json()
        if not isinstance(body, dict) or "enabled" not in body or not isinstance(body.get("key"), str):
            return JSONResponse({"error": "expected {key, enabled}"}, status_code=400)
        try:
            await asyncio.to_thread(catalog.set_enabled, body["key"][:300], bool(body["enabled"]))
        except catalog.ToggleError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        return JSONResponse({"ok": True})

    @app.get("/api/kb/prompt")
    def kb_prompt(model: str = "", provider: str = "") -> Any:
        from ekte.knowledge import load_knowledge_base
        from ekte.knowledge.research import research_prompt

        text = research_prompt(model[:200], provider[:64] or None, load_knowledge_base(copy=False))
        return Response(text, media_type="text/plain; charset=utf-8")

    @app.post("/api/kb/resolve")
    async def kb_resolve(request: Request) -> Any:
        from ekte.knowledge import load_knowledge_base

        body = await request.json()
        # resolving only reads: the shared cached instances, no copies
        knowledge = await asyncio.to_thread(load_knowledge_base, copy=False)
        model, hint = str(body.get("model") or "")[:200], body.get("provider") or None
        r = knowledge.resolve(model, hint)
        off = None
        if r is None or r.match_confidence not in ("exact", "alias"):
            # a closer profile that exists but is switched off: name it
            full = await asyncio.to_thread(load_knowledge_base, full=True, copy=False)
            f = full.resolve(model, hint)
            if f is not None and (r is None or f.match_confidence in ("exact", "alias")):
                off = {"provider": f.provider.provider, "model_id": f.model.id}
        if r is None:
            return JSONResponse({"matched": False, **({"switched_off": off} if off else {})})
        key = f"{r.provider.provider}/{r.model.id}"
        return JSONResponse({"matched": True, "provider": r.provider.provider, "model_id": r.model.id,
                             "match_confidence": r.match_confidence,
                             "source": knowledge.model_sources.get(key),
                             **({"switched_off": off} if off else {})})

    async def _yaml_body(request: Request) -> tuple[str, str | None]:
        body = await request.json()
        text = body.get("yaml") if isinstance(body, dict) else None
        name = body.get("filename") if isinstance(body, dict) else None
        return (text if isinstance(text, str) else ""), (str(name)[:120] if name else None)

    @app.post("/api/kb/scan")
    async def kb_scan(request: Request) -> Any:
        # Check uploaded YAML; nothing is written.
        from ekte.knowledge.importer import scan

        text, _name = await _yaml_body(request)
        return JSONResponse((await asyncio.to_thread(scan, text)).to_dict())

    @app.post("/api/kb/import")
    async def kb_import(request: Request) -> Any:
        from ekte.knowledge.importer import import_yaml

        text, name = await _yaml_body(request)
        result, ids = await asyncio.to_thread(
            import_yaml, text, origin=f"import:{name}" if name else "import"
        )
        body = {**result.to_dict(), "entry_ids": ids}
        return JSONResponse(body, status_code=201 if result.ok else 400)

    @app.get("/api/kb/export")
    def kb_export(provider: str = "") -> Any:
        from ekte.knowledge.importer import export_yaml

        text = export_yaml(provider or None)
        fname = f"ekte-kb-{provider or 'mine'}.yaml"
        return Response(text, media_type="application/yaml; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.patch("/api/kb/entries/{entry_id}")
    async def kb_entry_patch(entry_id: int, request: Request) -> Any:
        from ekte.knowledge import store

        body = await request.json()
        if "enabled" not in body:
            return JSONResponse({"error": "nothing to change"}, status_code=400)
        if not await asyncio.to_thread(store.set_enabled, entry_id, bool(body.get("enabled"))):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"ok": True})

    @app.delete("/api/kb/entries/{entry_id}")
    def kb_entry_delete(entry_id: int) -> Any:
        from ekte.knowledge import store

        if not store.delete(entry_id):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"ok": True})

    @app.post("/api/models")
    async def relay_models(request: Request) -> Any:
        # List the relay's own /models so the picker can offer ids it really
        # accepts. The API key is optional: self-hosted relays (Ollama, LM Studio)
        # need none, and an empty key sends no auth header.
        from ekte.clients import make_client

        body = await request.json()
        try:
            target = build_target(
                kind="target",
                name="models",
                base_url=body.get("base_url"),
                api_key=body.get("api_key"),
                model="-",  # required by build_target; unused by GET /models
                api=validate_api(body.get("api")),
            )
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Error text is already redacted by the client (key scrubbed).
        outcome, ids = await make_client(target).list_models()
        if not outcome.ok:
            return JSONResponse(
                {
                    "ok": False,
                    "status_code": outcome.status_code,
                    "error": outcome.error_message or outcome.error_type or "error",
                }
            )
        return JSONResponse(
            {
                "ok": True,
                "api": detect_api(target),
                "models": sorted(set(ids)),
                "duration_ms": round(outcome.duration_ms or 0.0, 1),
            }
        )

    def _audit_job(body: dict[str, Any]) -> jobs.Job:
        """Validate an audit request and queue it as a background job.

        Raises ConfigError on bad input, before anything is queued.
        """
        bl = body.get("baseline") or {}
        has_baseline = bool(bl.get("base_url") and bl.get("model"))
        surface = validate_surface(body.get("surface"))
        suite = validate_suite(str(body.get("suite") or "standard"))
        dimensions = validate_dimensions(suite, body.get("dimensions"))
        # a custom suite on another surface picks among that surface's dimensions
        check_surface_dimensions(surface, dimensions)
        target = build_target(
            kind="target",
            name=body.get("name") or "target",
            base_url=body.get("base_url"),
            api_key=body.get("api_key"),
            model=body.get("model"),
            claimed_model=body.get("claimed_model") or None,
            declared_provider=body.get("declared_provider") or None,
            api=validate_api(body.get("api")),
        )
        baseline = None
        if has_baseline:
            baseline = build_target(
                kind="baseline",
                name=bl.get("name") or "baseline",
                base_url=bl.get("base_url"),
                api_key=bl.get("api_key"),
                model=bl.get("model"),
                api=validate_api(bl.get("api")),
            )
        options = AuditOptions(
            suite=suite,
            dimensions=dimensions,
            # probe request mode (standard/deep; the full suite measures both);
            # a chat setting: the other surfaces' requests never stream
            performance_streaming=surface != "chat" or body.get("performance_streaming") is not False,
            surface=surface,
            # embedding: the claimed vector length (0 = from the knowledge base)
            embedding_dimensions=(
                max(0, _coerce_int(body.get("embedding_dimensions"))) if surface == "embedding" else 0
            ),
        )

        async def run(emit: jobs.Emit) -> dict[str, Any]:
            if surface != "chat":
                # The Tools' run (the surface's previous saved run as the drift
                # reference), unsaved: the job saves it like a chat audit.
                from ekte.embed_audit import _run_surface

                report, _ = await _run_surface(
                    target, options, kb_dirs=None, command=None, save=False,
                    baseline=baseline, on_event=emit,
                )
            else:
                report = await run_audit(
                    target,
                    options,
                    baseline=baseline,
                    mode="compare" if baseline is not None else "check",
                    on_event=emit,
                )
            return json.loads(report.model_dump_json())

        # What the history page lists for the job: no key, nothing secret.
        summary = {
            "base_url": target.base_url,
            "model": target.model,
            "claimed_model": target.claimed_model or target.model,
            "suite": suite,
            "surface": surface,
            "dimensions": list(dimensions or []),
            "baseline_url": baseline.base_url if baseline is not None else None,
            # protocol and probe request mode are chat settings
            "api": detect_api(target) if surface == "chat" else None,
            "api_auto": target.api == "auto",
            "stream_mode": stream_mode(options) if surface == "chat" else None,
        }
        urls = [target.base_url, baseline.base_url if baseline is not None else None]
        return jobs.manager.submit(summary, urls, run)

    def _job_stream(job: jobs.Job) -> StreamingResponse:
        async def gen() -> AsyncIterator[str]:
            async for chunk in jobs.stream(job, _REQUEST_BATCH_SEC):
                yield chunk

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ----- Background audits (v2): run on, whatever page is open ----------- #
    @app.post("/api/v1/jobs")
    @app.post("/api/jobs")
    async def jobs_create(request: Request) -> Any:
        try:
            job = _audit_job(await request.json())
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(job.info())

    @app.get("/api/jobs")
    async def jobs_list() -> Any:
        # Audits started from the UI, plus monitors running right now: the
        # history page shows them all as "in progress".
        out = [j.info() for j in jobs.manager.list()]
        for wid, state in list(_running_watches.items()):
            started = bool(state.get("started"))
            out.append({
                "id": f"monitor-{wid}",
                "kind": "monitor",
                "watch_id": wid,
                "name": state.get("name"),
                "base_url": state.get("base_url"),
                "model": state.get("model"),
                "claimed_model": state.get("claimed_model"),
                "suite": state.get("suite"),
                "api": state.get("api_resolved"),
                "api_auto": state.get("api_auto"),
                "stream_mode": state.get("stream_mode"),
                "status": "running" if started else "queued",
                "created": state.get("since"),
                "progress": _watch_progress(state) if started else None,
                "done": state.get("done", 0),
                "total": state.get("total", 0),
                "current": state.get("current"),
                "waiting_for": [] if started else list(state.get("waiting_for") or []),
            })
        return JSONResponse({"jobs": out, "max_parallel": jobs.gate.limit})

    @app.get("/api/v1/jobs/{job_id}")
    @app.get("/api/jobs/{job_id}")
    async def jobs_get(job_id: str) -> Any:
        job = _find_job(job_id)
        if job is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(job.info())

    @app.get("/api/v1/jobs/{job_id}/events")
    @app.get("/api/jobs/{job_id}/events")
    async def jobs_events(job_id: str) -> Any:
        # Replays the job's whole log, then follows it live. Disconnecting
        # only detaches this page: the audit runs on.
        job = _find_job(job_id)
        if job is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return _job_stream(job)

    @app.post("/api/jobs/{job_id}/cancel")
    async def jobs_cancel(job_id: str) -> Any:
        if job_id.startswith("monitor-"):
            try:
                stopped = _cancel_watch(int(job_id[len("monitor-"):]))
            except ValueError:
                stopped = False
        else:
            stopped = jobs.manager.cancel(job_id)
        if not stopped:
            return JSONResponse({"error": "not running"}, status_code=409)
        return JSONResponse({"ok": True})

    @app.post("/api/report/export")
    async def report_export(request: Request, format: str = "json") -> Any:
        # Render a report the browser already holds (a fresh run, a history entry,
        # possibly with its text localized) into a downloadable file.
        from pydantic import ValidationError

        from ekte.models import AuditReport
        from ekte.report import render_pdf, report_stem
        from ekte.report.render import render_html, render_json, render_markdown

        media = {
            "json": "application/json",
            "md": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
            "pdf": "application/pdf",
        }
        if format not in media:
            return JSONResponse(
                {"error": f"unknown format {format!r}; choose from: {', '.join(media)}"},
                status_code=400,
            )
        raw = await request.body()
        try:
            # Decoding and validating a large report is CPU work: off the loop.
            report = await asyncio.to_thread(
                lambda: AuditReport.model_validate(json.loads(raw))
            )
        except (ValueError, ValidationError) as exc:
            return JSONResponse({"error": f"not a ekte report: {exc}"[:500]}, status_code=400)

        body: str | bytes
        if format == "pdf":
            try:
                # CPU-bound typesetting: keep the event loop (and live audits) responsive.
                body = await asyncio.to_thread(render_pdf, report)
            except Exception as exc:  # a layout failure must still reach the UI as JSON
                # The traceback goes to the server log only: the renderer's
                # exception text can carry internal details, so the client
                # gets just its type.
                _log.exception("PDF rendering failed")
                return JSONResponse(
                    {"error": f"PDF rendering failed ({type(exc).__name__}); see the ekte serve log for details."},
                    status_code=500,
                )
        else:
            render = {"json": render_json, "md": render_markdown, "html": render_html}[format]
            body = await asyncio.to_thread(render, report)
        fname = f"{report_stem(report)}.{format}"
        return Response(body, media_type=media[format],
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.get("/api/v1/history")
    @app.get("/api/history")
    def history_list(limit: int = 50, perf: bool = False) -> Any:
        from ekte.web import history

        return JSONResponse(history.recent(limit, perf=perf))

    @app.get("/api/v1/history/{rid}")
    def history_get_v1(rid: int) -> Any:
        """The public form of ``GET /api/history/{rid}``: a saved report as stored."""
        from ekte.web import history

        report = history.get(rid)
        if report is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(report)

    @app.get("/api/history/status")
    def history_status() -> Any:
        """The history as a whole, for the pages' notices (history.status)."""
        from ekte.web import history

        return JSONResponse(history.status())

    @app.get("/api/history/{rid}")
    def history_get(rid: int, trend: int = 0) -> Any:
        """A saved report as stored; ``trend=1`` (the pages that show it) adds
        each request's running medians and their p25–p75 bands for the
        performance chart."""
        from ekte.web import history

        report = history.get(rid)
        if report is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        perf = report.get("performance") if trend else None
        if isinstance(perf, dict) and isinstance(perf.get("requests"), list):
            attach_trends(perf["requests"])
        return JSONResponse(report)

    @app.delete("/api/history/{rid}")
    def history_delete(rid: int) -> Any:
        from ekte.web import history

        history.delete(rid)
        return JSONResponse({"ok": True})

    @app.delete("/api/history")
    def history_clear() -> Any:
        from ekte.web import history

        history.clear()
        return JSONResponse({"ok": True})

    # ----- Analytics (ekte/web/analytics.py) ------------------------------ #
    # Plain `def` handlers (SQLite + the knowledge base load run in the thread
    # pool). Every parameter is validated there: a bad one answers 400.
    # Analytics answers are cached briefly: a filter, tab or block change
    # often asks the same question again. The key holds the call and its
    # parameters, the history database and its write count (any saved,
    # deleted or cleared run drops them) and a 30-second time slot (relative
    # ranges such as "last 7 days" move, relay names can change).
    analytics_cache: collections.OrderedDict[str, Any] = collections.OrderedDict()
    analytics_lock = threading.Lock()

    def _analytics(call: Any, *args: Any) -> Any:
        from ekte.web import history
        from ekte.web.analytics import AnalyticsError

        key = json.dumps([call.__name__, args, history.write_mark(), int(time.time() // 30)],
                         sort_keys=True, default=str)
        with analytics_lock:
            body = analytics_cache.get(key)
            if body is not None:
                analytics_cache.move_to_end(key)
        status = 200
        if body is None:
            try:
                body = call(*args)
            except AnalyticsError as exc:
                body, status = {"error": str(exc)}, 400
            else:
                with analytics_lock:
                    analytics_cache[key] = body
                    while len(analytics_cache) > 64:
                        analytics_cache.popitem(last=False)
        # Fresh numbers on every load: the history changes with each run.
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    @app.get("/api/analytics/options")
    def analytics_options(request: Request) -> Any:
        from ekte.web import analytics

        return _analytics(analytics.options, dict(request.query_params))

    @app.get("/api/analytics/summary")
    def analytics_summary(request: Request) -> Any:
        from ekte.web import analytics

        return _analytics(analytics.summary, dict(request.query_params))

    @app.get("/api/analytics/series")
    def analytics_series(request: Request) -> Any:
        from ekte.web import analytics

        params = request.query_params
        return _analytics(analytics.series, dict(params), params.getlist("keys"))

    @app.get("/api/analytics/leaderboard")
    def analytics_leaderboard(request: Request) -> Any:
        from ekte.web import analytics

        return _analytics(analytics.leaderboard, dict(request.query_params))

    @app.get("/api/analytics/breakdown")
    def analytics_breakdown(request: Request) -> Any:
        from ekte.web import analytics

        params = request.query_params
        return _analytics(analytics.breakdown, dict(params), params.getlist("metrics"))

    @app.get("/api/analytics/errors")
    def analytics_errors(request: Request) -> Any:
        from ekte.web import analytics

        return _analytics(analytics.errors, dict(request.query_params))

    @app.get("/api/analytics/integrity")
    def analytics_integrity(request: Request) -> Any:
        from ekte.web import analytics

        return _analytics(analytics.integrity, dict(request.query_params))

    # ----- Scheduled watches (monitoring) -------------------------------- #
    def _watch_rows() -> list[dict[str, Any]]:
        """The stored watches with their schedule floor, protocol and KB drift.

        Blocking (SQLite + knowledge base load): runs in a worker thread.
        Touches no loop-owned state; live run state is added on the loop.
        """
        from ekte.knowledge import load_knowledge_base
        from ekte.web import watches

        # list_all() never returns api_key, so this is safe to send to the browser.
        rows = watches.list_all()
        # Flag pinned profiles that differ from what the knowledge base resolves now.
        try:
            kb = load_knowledge_base(copy=False) if rows else None  # read-only
        except Exception:
            kb = None
        for row in rows:
            row["min_interval_sec"] = _min_interval_sec(row.get("run_duration_sec"))
            row.update(_watch_protocol(row))
            row["kb_current_hash"] = None
            row["kb_changed"] = False
            if kb is None:
                continue
            try:
                current = _watch_knowledge(row, kb).get("profile_hash")
            except Exception:
                continue
            row["kb_current_hash"] = current
            pinned_hash = (row.get("kb") or {}).get("profile_hash")
            row["kb_changed"] = bool(pinned_hash and pinned_hash != current)
        return rows

    @app.get("/api/watches")
    async def watches_list() -> Any:
        rows = await asyncio.to_thread(_watch_rows)
        # Live run state belongs to the event loop: read it here, not in the thread.
        for row in rows:
            state = _running_watches.get(int(row["id"]))
            row["running"] = state is not None
            # waiting for its relay: another audit is using it
            row["queued"] = state is not None and not state.get("started")
            row["progress"] = _watch_progress(state) if state is not None else None
        return JSONResponse(rows)

    @app.post("/api/watches")
    async def watches_create(request: Request) -> Any:
        from ekte.web import watches

        body = await request.json()
        # Validate the target + suite up front so bad input is a clean 400.
        try:
            suite = validate_suite(str(body.get("suite") or "standard"))
            dimensions = validate_dimensions(suite, body.get("dimensions"))
            surface = validate_surface(body.get("surface"))
            check_surface_dimensions(surface, dimensions)
            build_target(
                kind="target",
                name=body.get("name") or "watch",
                base_url=body.get("base_url"),
                api_key=body.get("api_key"),
                model=body.get("model"),
                claimed_model=body.get("claimed_model") or None,
                declared_provider=body.get("declared_provider") or None,
                api=validate_api(body.get("api")),
            )
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        embedding = surface == "embedding"
        cfg = {
            **body,
            "suite": suite,
            "dimensions": dimensions,
            "surface": surface,
            # the streaming mode is a chat setting; non-chat requests never stream
            "performance_streaming": surface != "chat" or body.get("performance_streaming") is not False,
            "embedding_dimensions": _coerce_int(body.get("embedding_dimensions")) if embedding else 0,
        }
        try:
            knowledge = await asyncio.to_thread(_watch_knowledge, cfg)
        except Exception as exc:  # e.g. a broken EKTE_KB_DIR file
            return JSONResponse({"error": f"knowledge base: {exc}"}, status_code=400)
        from ekte.secretbox import SecretLocked

        try:
            wid = await asyncio.to_thread(
                watches.create, cfg, knowledge=knowledge, key_storage=_key_storage_override(body)
            )
        except SecretLocked as exc:
            return _locked_response(exc)
        return JSONResponse({"ok": True, "id": wid}, status_code=201)

    @app.post("/api/watches/from-history/{rid}")
    async def watches_from_history(rid: int, request: Request) -> Any:
        """Schedule a history run: a paused draft watch with the run's config.

        History never stores the API key (only a fingerprint), so the draft has
        no key and no interval; the user sets the interval (and, if the endpoint
        needs one, the key) on the monitors page, then enables it. The run's
        protocol is kept when it was set by hand (``api="auto"`` otherwise, and
        for runs from before it was recorded), and so is its probe request mode.
        A compare run's baseline is dropped: watches run check-only.
        A run a monitor produced is refused: that monitor already exists.
        """
        from ekte.web import history, watches

        report = await asyncio.to_thread(history.get, rid)
        if report is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if await asyncio.to_thread(history.watch_of, rid) is not None:
            return JSONResponse({"error": "this run was produced by a monitor"}, status_code=409)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        tgt = report.get("target") or {}
        # A protocol set by hand stays forced; an auto-detected one is detected
        # again on every run.
        api = tgt.get("api") if tgt.get("api_auto") is False and tgt.get("api") else "auto"
        try:
            suite = validate_suite(str(report.get("suite") or "standard"))
            dimensions = validate_dimensions(suite, report.get("dimensions_selected"))
            build_target(
                kind="target",
                name=tgt.get("name") or "watch",
                base_url=tgt.get("base_url"),
                api_key="",
                model=tgt.get("model"),
                claimed_model=tgt.get("claimed_model") or None,
                declared_provider=tgt.get("declared_provider") or None,
                api=validate_api(api),
            )
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        name = tgt.get("name")
        try:
            surface = validate_surface(report.get("surface"))
            check_surface_dimensions(surface, dimensions)
        except ConfigError as exc:  # a run of a surface this version cannot audit
            return JSONResponse({"error": str(exc)}, status_code=400)
        embedding = surface == "embedding"
        # The Tools page passes the claimed vector length it audited with (the
        # report does not keep it); 0 takes the knowledge base's.
        # the request's claimed vector length, else the one the run claimed
        claimed_dims = _coerce_int(
            (body.get("embedding_dimensions") if isinstance(body, dict) else None)
            or report.get("embedding_dimensions")
        )
        cfg = {
            "name": name if name and name != "target" else (tgt.get("claimed_model") or tgt.get("model")),
            "base_url": tgt.get("base_url"),
            "model": tgt.get("model"),
            "claimed_model": tgt.get("claimed_model") or None,
            "declared_provider": tgt.get("declared_provider") or None,
            "api": api,
            "suite": suite,
            "dimensions": dimensions,
            "performance_streaming": surface != "chat" or report.get("stream_mode") != "non_stream",
            "surface": surface,
            "embedding_dimensions": claimed_dims if embedding else 0,
            "language": (body or {}).get("language") if isinstance(body, dict) else None,
            "source_report_id": rid,
            "run_duration_sec": history.run_duration_sec(report),
        }
        try:
            knowledge = await asyncio.to_thread(_watch_knowledge, cfg)
        except Exception as exc:  # e.g. a broken EKTE_KB_DIR file
            return JSONResponse({"error": f"knowledge base: {exc}"}, status_code=400)
        wid = await asyncio.to_thread(watches.create, cfg, knowledge=knowledge, draft=True)
        return JSONResponse({"ok": True, "id": wid}, status_code=201)

    @app.delete("/api/watches/{wid}")
    def watches_delete(wid: int) -> Any:
        from ekte.web import watches

        watches.delete(wid)
        return JSONResponse({"ok": True})

    @app.patch("/api/watches/{wid}")
    async def watches_patch(wid: int, request: Request) -> Any:
        from ekte.web import watches

        row = await asyncio.to_thread(watches.get, wid)
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        body = await request.json()
        # Validate every field before storing any, so a bad PATCH changes nothing.
        interval = None
        if body.get("interval_sec") is not None:
            raw = body.get("interval_sec")
            if isinstance(raw, bool) or not isinstance(raw, int) or not 60 <= raw <= 86400:
                return JSONResponse(
                    {"error": "interval_sec must be a whole number of seconds (60 to 86400)"},
                    status_code=400,
                )
            floor = _min_interval_sec(row.get("run_duration_sec"))
            if row.get("run_duration_sec") and raw < floor:
                return JSONResponse(
                    {"error": f"interval_sec must be at least {floor}: one run takes longer than that"},
                    status_code=400,
                )
            interval = raw
        key = body.get("api_key")
        key = key.strip() if isinstance(key, str) and key.strip() else None
        alert_on = body.get("alert_on")
        if alert_on is not None and alert_on not in ("low", "medium", "high"):
            return JSONResponse({"error": "alert_on must be low, medium or high"}, status_code=400)
        hooks = body.get("webhooks")
        if hooks is not None:
            if not isinstance(hooks, list) or not all(isinstance(h, str) for h in hooks):
                return JSONResponse({"error": "webhooks must be a list of URLs"}, status_code=400)
            hooks = [h.strip() for h in hooks if h.strip()]
            bad = next((h for h in hooks if not h.lower().startswith(("http://", "https://"))), None)
            if bad is not None:
                return JSONResponse(
                    {"error": f"webhook is not an http(s) URL: {bad}"}, status_code=400
                )
        dims = None
        if body.get("embedding_dimensions") is not None:
            raw = body.get("embedding_dimensions")
            if row.get("surface") != "embedding":
                return JSONResponse(
                    {"error": "embedding_dimensions applies to embedding monitors only"},
                    status_code=400,
                )
            if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 65536:
                return JSONResponse(
                    {"error": "embedding_dimensions must be a whole number (0 to 65536)"},
                    status_code=400,
                )
            dims = raw
        if body.get("dimensions") is not None:
            # an edit's suite and dimensions pass the same checks as on create
            try:
                suite = validate_suite(str(body.get("suite") or row.get("suite") or "standard"))
                picked = validate_dimensions(suite, body.get("dimensions"))
                check_surface_dimensions(validate_surface(row.get("surface")), picked)
            except ConfigError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        if body.get("surface") is not None and body.get("surface") != row.get("surface"):
            # What a monitor audits is fixed; create a new one for another surface.
            return JSONResponse({"error": "a monitor's surface cannot be changed"}, status_code=400)
        if body.get("enabled") and (interval or row.get("interval_sec")) is None:
            # A draft needs its schedule before it may run on its own. The key
            # stays optional, as in the audit: local relays need none.
            return JSONResponse({"error": "set an interval first"}, status_code=400)
        from ekte.secretbox import SecretLocked


        def store() -> JSONResponse:
            # All of the PATCH's writes in one worker-thread call, in order.
            try:
                watches.update(
                    wid,
                    interval_sec=interval,
                    api_key=key,
                    alert_on=alert_on,
                    webhooks=hooks,
                    embedding_dimensions=dims,
                    key_storage=_key_storage_override(body),
                )
            except SecretLocked as exc:
                return _locked_response(exc)
            if "enabled" in body:
                watches.set_enabled(wid, bool(body.get("enabled")))
            if "language" in body:
                watches.set_language(wid, body.get("language"))
            if body.get("repin"):
                # Re-pin to the profile the knowledge base resolves to now.
                try:
                    watches.pin(wid, _watch_knowledge(row))
                except Exception as exc:
                    return JSONResponse({"error": f"knowledge base: {exc}"}, status_code=400)
            return JSONResponse({"ok": True})

        return await asyncio.to_thread(store)

    @app.post("/api/watches/{wid}/run")
    async def watches_run(wid: int) -> Any:
        from ekte.web import watches

        row = await asyncio.to_thread(watches.get, wid)
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if wid in _scheduled_watch_tasks:
            # The scheduler just started it; its run registers on the next step.
            return JSONResponse({"error": "already running"}, status_code=409)
        # Run the same path the scheduler uses (audit + persist + alert + mark).
        try:
            await _run_one_watch(row)
        except WatchAlreadyRunning:
            return JSONResponse({"error": "already running"}, status_code=409)
        except WatchCancelled:
            return JSONResponse({"ok": False, "cancelled": True})
        except WatchLocked as exc:
            return _locked_response(exc)
        except WatchKeyMissing:
            return _missing_key_response()
        except WatchKeyUnreadable:
            return JSONResponse(
                {"error": "the stored API key cannot be decrypted (master key lost or "
                          "changed); enter the key again", "key_error": True},
                status_code=409,
            )
        except Exception as exc:  # surface a clean error, not a 500 stack
            return JSONResponse(
                {"error": f"{type(exc).__name__}: {exc}"}, status_code=500
            )
        # Return the freshly saved report so the UI can show the result.
        from ekte.web import history

        def saved_report() -> dict[str, Any] | None:
            refreshed = watches.get(wid)
            if refreshed and refreshed.get("last_report_id") is not None:
                return history.get(int(refreshed["last_report_id"]))
            return None

        return JSONResponse({"ok": True, "report": await asyncio.to_thread(saved_report)})

    @app.post("/api/watches/{wid}/cancel")
    async def watches_cancel(wid: int) -> Any:
        if not _cancel_watch(wid):
            return JSONResponse({"error": "not running"}, status_code=409)
        return JSONResponse({"ok": True})

    # ----- The master key of the monitors' API keys --------------------- #
    # Key-bearing bodies are read by hand, not with pydantic models: a 422
    # would echo the input (the key) back. Nothing here is ever cached.
    def _secret_json(payload: dict[str, Any], status_code: int = 200) -> JSONResponse:
        return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})

    async def _typed_key(request: Request) -> str:
        try:
            body = await request.json()
        except ValueError:
            body = None
        key = body.get("key") if isinstance(body, dict) else None
        return key if isinstance(key, str) else ""

    def _vault_call(fn: Any, *args: Any) -> JSONResponse:
        from ekte.web.masterkey import VaultError

        try:
            return _secret_json(fn(*args))
        except VaultError as exc:
            return _secret_json({"error": str(exc)}, status_code=exc.status)

    @app.get("/api/secret")
    def secret_status() -> Any:
        from ekte.web.masterkey import vault

        return _secret_json(vault.status())

    @app.post("/api/secret/new")
    def secret_new() -> Any:
        """A new master key, shown once; confirmed by /api/secret/new/confirm."""
        from ekte.secretbox import SecretBox
        from ekte.web.masterkey import PENDING_TTL_SEC, VaultError, vault

        try:
            key = vault.begin_new()
        except VaultError as exc:
            return _secret_json({"error": str(exc)}, status_code=exc.status)
        return _secret_json({
            "key": key,
            "fingerprint": SecretBox([key], "new").fingerprint(),
            "expires_in": int(PENDING_TTL_SEC),
        })

    @app.post("/api/secret/new/confirm")
    async def secret_new_confirm(request: Request) -> Any:
        from ekte.web.masterkey import vault

        typed = await _typed_key(request)
        return await asyncio.to_thread(_vault_call, vault.confirm_new, typed)

    @app.post("/api/secret/unlock")
    async def secret_unlock(request: Request) -> Any:
        from ekte.web.masterkey import vault

        typed = await _typed_key(request)
        return await asyncio.to_thread(_vault_call, vault.unlock, typed)

    @app.post("/api/secret/lock")
    def secret_lock() -> Any:
        # Audits already running finish with the key they decrypted.
        from ekte.web.masterkey import vault

        return _vault_call(vault.lock)

    @app.post("/api/secret/reset")
    async def secret_reset(request: Request) -> Any:
        """The master key is lost: drop the encrypted API keys, start over."""
        from ekte.web.masterkey import VaultError, vault

        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or body.get("confirm") != "RESET":
            return _secret_json({"error": 'send {"confirm": "RESET"}'}, status_code=400)
        st = vault.status()
        if "reset" not in st["actions"]:
            return _secret_json(
                {"error": f"cannot reset the master key while it is {st['state']}"}, status_code=409
            )
        # Stays on the loop on purpose: check, cancel the running monitors and
        # reset without yielding, so no monitor can start (and no unlock can
        # land) in between. A rare, deliberate action.
        for wid in list(_running_watches):
            _cancel_watch(wid)
        # Scheduled runs not yet started hold rows with keys decrypted before
        # the reset: they must never start.
        for wid, task in list(_scheduled_watch_tasks.items()):
            if wid not in _running_watches:
                task.cancel()
        try:
            dropped = vault.reset()
        except VaultError as exc:
            return _secret_json({"error": str(exc)}, status_code=exc.status)
        return _secret_json({**vault.status(), "dropped": dropped})

    @app.post("/api/secret/storage")
    async def secret_storage(request: Request) -> Any:
        """Store no API key (``memory``) or store them encrypted; the keys move along."""
        from ekte.secretbox import SecretLocked
        from ekte.web.masterkey import VaultError, vault

        try:
            body = await request.json()
        except ValueError:
            body = None
        mode = body.get("mode") if isinstance(body, dict) else None

        def switch() -> JSONResponse:
            try:
                return _secret_json(vault.set_storage(str(mode or "")))
            except SecretLocked as exc:
                return _locked_response(exc)
            except VaultError as exc:
                return _secret_json({"error": str(exc)}, status_code=exc.status)

        return await asyncio.to_thread(switch)


    # Static assets (e.g. future JS/CSS split-outs) under /assets.
    assets = _STATIC / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    # 404 fallback to the SPA shell so deep links work.
    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: Any) -> Any:  # noqa: ARG001
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        if request.url.path.startswith(("/static/", "/v2/static/")):
            return Response("not found", status_code=404, media_type="text/plain")
        return html_page(_STATIC_UI / "index.html", request.scope)

    return app
