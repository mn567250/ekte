"""Re-scoring saved runs with this ekte version (#168).

A saved run that kept a usable evidence file is re-scored by replaying it
(:mod:`ekte.replay`); the new report **replaces** the stored one in place
(:func:`ekte.web.history.replace`): the run keeps its id, time, monitor and
evidence file. A run without a usable evidence file is never re-scored: it
keeps its verdict, and a bulk re-score records the reason
(:func:`ekte.replay.refusal`) with it (:func:`ekte.web.history.record_refusal`).
A re-score that ends without an overall score (every check lacked recorded
answers, #304), or without a grade for a run that had one (too few checks had
recorded answers, #312), is not stored either (:func:`require_verdict`): the
run keeps its verdict and the reason (:data:`ekte.replay.NO_SCORE`,
:data:`ekte.replay.NO_RATING`) is recorded the same way; a job ends refused
with it, and a bulk re-score counts it skipped.

Monitors follow the latest scoring. When the re-scored run is its monitor's
last run (``last_report_id``), the monitor card's ``last_risk`` /
``last_score`` take the new verdict (its run time stays). When it is the
monitor's newest saved run and the monitor is enabled, its alert rules are
evaluated on the new verdict (threshold reached, or worse than before the
re-score) and its webhooks get an alert marked ``"rescored": true`` with the
audit and scoring versions. Re-scoring an older run of a monitor sends nothing.

Bulk re-scores (:class:`Bulk`) look at every saved run scored by another ekte
version, one after another; on the web server each run is a background job
(:mod:`ekte.web.jobs`) like a single re-score. :func:`start_upgrade` starts
one automatically on the first start of a new ekte version (runs scored by an
older version only); it is recorded as finished in ``meta``
(``rescore_version``) only when it went through every run, so a server
stopped part-way resumes it on its next start (runs already re-scored carry
this version and are not looked at again). ``EKTE_AUTO_RESCORE=0`` turns the
automatic re-score off.

Nothing here contacts a relay: a replay answers every request from the file,
so no job waits for a relay gate.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ekte import __version__, legacy
from ekte.web.jobs import PublicRefusal

_log = logging.getLogger("ekte.web")

# meta key: the ekte version whose automatic re-score after an upgrade finished
META_KEY = "rescore_version"

NOT_FOUND = "no such saved run"


class Refused(PublicRefusal, ValueError):
    """The run cannot be re-scored (the reason is one of replay's fixed texts)."""


def version_key(version: str | None) -> tuple[int, ...] | None:
    """A comparable key of an ekte version ("0.35.0" -> (0, 35, 0)); None
    when it does not start with a number."""
    m = re.match(r"\d+(?:\.\d+)*", str(version or ""))
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def older(version: str | None, than: str = __version__) -> bool:
    """Whether ``version`` is older than ``than`` (an unknown one counts as older)."""
    a, b = version_key(version), version_key(than)
    if b is None:
        return version != than
    return a is None or a < b


def auto_enabled() -> bool:
    """Whether the automatic re-score after an upgrade is on (``EKTE_AUTO_RESCORE``)."""
    return str(legacy.getenv("EKTE_AUTO_RESCORE", "1") or "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


# --------------------------------------------------------------------------- #
# One run
# --------------------------------------------------------------------------- #
def load(rid: int) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    """``(report, evidence path, refusal)`` of saved run ``rid`` (blocking):
    the refusal is None when the run can be re-scored."""
    from ekte import replay
    from ekte.web import history

    report = history.get(rid)
    if report is None:
        return None, None, NOT_FOUND
    path = history.evidence_path(rid)
    if path is None:
        return report, None, replay.NO_EVIDENCE
    return report, path, replay.refusal(report, path)


def _verdict(report: dict[str, Any]) -> tuple[str | None, float | None]:
    v = report.get("verdict") or {}
    risk, score = v.get("risk_level"), v.get("overall_score")
    return (
        risk if isinstance(risk, str) else None,
        float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
    )


def _apply(rid: int, new: dict[str, Any]) -> dict[str, Any] | None:
    """Replace run ``rid`` with its re-score ``new`` and bring its monitor's
    card up to date (blocking). Returns the monitor's settings when the run
    is that monitor's newest run (its alert rules apply), else None."""
    from ekte.web import history, watches

    if not history.replace(rid, new):
        raise Refused(NOT_FOUND)
    wid = history.watch_of(rid)
    if wid is None:
        return None
    risk, score = _verdict(new)
    with contextlib.suppress(Exception):
        watches.update_last(wid, rid, risk, score)
    if history.newest_of_watch(wid) != rid:
        return None
    return watches.get_settings(wid)


async def alert(watch: dict[str, Any], old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Evaluate ``watch``'s alert rules on the re-scored verdict ``new`` (the
    threshold, or worse than ``old``, the verdict before the re-score) and
    send its webhooks an alert marked as a re-score; True when one was sent."""
    from ekte.notify import regressed, send
    from ekte.web import watches

    if not watch.get("enabled"):
        return False
    risk, _ = _verdict(new)
    crossed = watches.risk_meets(risk, str(watch.get("alert_on") or "medium"))
    if not (crossed or regressed(new, old)):
        return False
    urls = dict.fromkeys(
        u.strip() for u in watch.get("webhooks") or [] if isinstance(u, str) and u.strip()
    )
    if not urls:
        return False
    await asyncio.gather(
        *(send(u, new, previous=old, lang=watch.get("language"), rescored=True) for u in urls),
        return_exceptions=True,
    )
    return True


async def store(rid: int, old: dict[str, Any], new: dict[str, Any]) -> int:
    """Replace run ``rid`` (whose report was ``old``) with its re-score
    ``new``, update its monitor and alert as the module docstring says;
    returns ``rid``."""
    watch = await asyncio.to_thread(_apply, rid, new)
    if watch is not None:
        try:
            await alert(watch, old, new)
        except Exception:  # an alert never undoes the re-score
            _log.warning("re-score alert of run %s failed", rid, exc_info=True)
    return rid


def _rating(report: dict[str, Any] | None) -> str | None:
    rating = ((report or {}).get("verdict") or {}).get("rating")
    return rating if isinstance(rating, str) and rating else None


def unstored(old: dict[str, Any] | None, new: dict[str, Any]) -> str | None:
    """Why re-score ``new`` of a run whose report was ``old`` must not replace
    it, or None when it may: it has no overall score (every check lacked
    recorded answers, #304), or the run had a grade and the re-score has none
    (too few checks had recorded answers to grade it, #312). A run that had
    no grade before may be re-scored without one."""
    from ekte import replay

    if _verdict(new)[1] is None:
        return replay.NO_SCORE
    if _rating(old) is not None and _rating(new) is None:
        return replay.NO_RATING
    return None


def require_verdict(
    rid: int, old: dict[str, Any] | None, new: dict[str, Any], version: str = __version__
) -> None:
    """Refuse to store re-score ``new`` of run ``rid`` (whose report was
    ``old``) when it would lose the run's score or grade (:func:`unstored`):
    the run keeps its verdict, and the reason is recorded with it (blocking)."""
    from ekte.web import history

    reason = unstored(old, new)
    if reason is None:
        return
    history.record_refusal(rid, version, reason)
    _log.warning("re-score of run %s not stored: %s", rid, reason)
    raise Refused(reason)


def log_missing(rid: int, new: Any) -> None:
    """Log one line when the re-score of run ``rid`` (``new``: its
    AuditReport) had requests without a recorded answer (#302)."""
    from ekte import replay

    line = replay.missing_summary(new.rescored_from)
    if line is not None:
        _log.warning("re-score of run %s: %s", rid, line)


async def rescore_run(rid: int, *, on_event: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-score saved run ``rid`` and replace it; ``(old report, new report)``.
    Raises :class:`Refused` when it cannot be re-scored."""
    from ekte import replay

    old, path, reason = await asyncio.to_thread(load, rid)
    if reason is not None or old is None or path is None:
        raise Refused(reason or NOT_FOUND)
    out = await replay.rescore(old, path, report_id=rid, on_event=on_event)
    new = json.loads(out.model_dump_json())
    await asyncio.to_thread(require_verdict, rid, old, new)
    log_missing(rid, out)
    await store(rid, old, new)
    return old, new


def job_summary(rid: int, report: dict[str, Any]) -> dict[str, Any]:
    """What the job list shows for the re-score of run ``rid``."""
    t = report.get("target") or {}
    return {
        "base_url": t.get("base_url"),
        "model": t.get("model"),
        "claimed_model": t.get("claimed_model") or t.get("model"),
        "suite": report.get("suite"),
        "surface": report.get("surface") or "chat",
        "dimensions": list(report.get("dimensions_selected") or []),
        "baseline_url": (report.get("baseline") or {}).get("base_url"),
        "api": t.get("api"),
        "api_auto": t.get("api_auto"),
        "stream_mode": report.get("stream_mode"),
        "rescore_of": rid,
    }


# The deprecated behavior of ``POST /api/v1/history/{id}/rescore`` without
# ``replace`` and of ``ekte rescore --save`` without ``--replace``.
NEW_RUN_DEPRECATED = (
    "saving a re-score as a new run is deprecated; a later ekte (0.37.0 at the "
    "earliest) replaces the saved run in place by default. Replace it now with "
    "--replace (CLI) or replace=true (POST /api/v1/history/{id}/rescore)"
)


def submit_job(rid: int, report: dict[str, Any], path: Path, *, replace: bool = True) -> Any:
    """Queue the re-score of run ``rid`` as a background job (no relay gate:
    nothing is contacted); the job's report replaces the run, and the job
    reports ``report_id`` = ``rid``. ``replace=False`` saves it as a new run
    instead (deprecated, see :data:`NEW_RUN_DEPRECATED`)."""
    from ekte import replay
    from ekte.web import jobs

    async def run(emit: jobs.Emit) -> dict[str, Any]:
        out = await replay.rescore(report, path, report_id=rid, on_event=emit)
        new = json.loads(out.model_dump_json())
        await asyncio.to_thread(require_verdict, rid, report, new)  # the job ends refused
        log_missing(rid, out)
        return new

    async def save(new: dict[str, Any]) -> int:
        return await store(rid, report, new)

    return jobs.manager.submit(job_summary(rid, report), [], run, save=save if replace else None)


# --------------------------------------------------------------------------- #
# Bulk
# --------------------------------------------------------------------------- #
class Bulk:
    """One bulk re-score at a time: its progress, for ``GET /api/rescore``."""

    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None
        self.state: dict[str, Any] = {"active": False}

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()

    def info(self) -> dict[str, Any]:
        return {**self.state, "active": self.active}

    def start(self, trigger: str = "manual") -> bool:
        """Start a bulk re-score on the running loop (False: one is running)."""
        if self.active:
            return False
        self.state = {
            "active": True, "trigger": trigger, "version": __version__, "total": None,
            "done": 0, "rescored": 0, "skipped": 0, "failed": 0, "current": None,
            "job": None, "started": time.time(), "finished": None,
        }
        self.task = asyncio.create_task(self._run(trigger))
        return True

    async def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task

    async def _run(self, trigger: str) -> None:
        from ekte.web import history, jobs

        st = self.state
        version = __version__
        try:
            pairs = await asyncio.to_thread(history.rescore_candidates, version)
            if trigger == "upgrade":  # runs scored by an older version only
                pairs = [p for p in pairs if older(p[1], version)]
            st["total"] = len(pairs)
            jobs.bump_live()
            for rid, _ in pairs:
                st["current"] = rid
                report, path, reason = await asyncio.to_thread(load, rid)
                if report is None:
                    pass  # deleted meanwhile
                elif reason is not None or path is None:
                    await asyncio.to_thread(
                        history.record_refusal, rid, version, reason or NOT_FOUND
                    )
                    st["skipped"] += 1
                else:
                    job = submit_job(rid, report, path)
                    st["job"] = job.id
                    try:
                        if job.task is not None:
                            await asyncio.shield(job.task)
                    except asyncio.CancelledError:
                        manager = jobs.manager
                        manager.cancel(job.id)
                        raise
                    except Exception:
                        pass
                    st["job"] = None
                    if job.status == "done":
                        st["rescored"] += 1
                    elif job.refused:  # no score: recorded with the run
                        st["skipped"] += 1
                    else:
                        st["failed"] += 1
                st["done"] += 1
                jobs.bump_live()
            st["current"] = None
            if not st["failed"]:
                await asyncio.to_thread(history.set_meta, META_KEY, version)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("bulk re-score failed")
            st["error"] = "the bulk re-score failed; see the ekte serve log for details"
        finally:
            st["finished"] = time.time()
            st["current"] = None
            jobs.bump_live()


bulk = Bulk()


def upgrade_pending() -> bool:
    """Whether the automatic re-score after an upgrade has yet to finish for
    this ekte version (blocking)."""
    from ekte.web import history

    return history.get_meta(META_KEY) != __version__


async def start_upgrade() -> bool:
    """On server start: begin the automatic re-score of runs scored by an
    older ekte version, unless it finished for this version or is turned
    off. True when it was started."""
    if not auto_enabled() or bulk.active:
        return False
    try:
        pending = await asyncio.to_thread(upgrade_pending)
    except Exception:
        _log.warning("could not check for the re-score after an upgrade", exc_info=True)
        return False
    return pending and bulk.start("upgrade")


# --------------------------------------------------------------------------- #
# CLI (ekte rescore --all)
# --------------------------------------------------------------------------- #
async def rescore_all(
    on_run: Callable[[int, dict[str, Any] | None, dict[str, Any] | None, str | None], None],
    version: str = __version__,
) -> dict[str, int]:
    """Re-score every saved run scored by another ekte version, one after
    another, without jobs (``ekte rescore --all``). ``on_run(rid, old, new,
    refusal)`` is told about each run (``new`` None: skipped for
    ``refusal``). Returns the counts."""
    from ekte.web import history

    counts = {"rescored": 0, "skipped": 0, "failed": 0}
    pairs = await asyncio.to_thread(history.rescore_candidates, version)
    for rid, _ in pairs:
        report, path, reason = await asyncio.to_thread(load, rid)
        if report is None:
            continue
        if reason is not None or path is None:
            await asyncio.to_thread(history.record_refusal, rid, version, reason or NOT_FOUND)
            counts["skipped"] += 1
            on_run(rid, report, None, reason)
            continue
        try:
            old, new = await rescore_run(rid)
        except Refused as exc:
            counts["skipped"] += 1
            on_run(rid, report, None, str(exc))
            continue
        except Exception as exc:
            _log.warning("re-score of run %s failed", rid, exc_info=True)
            counts["failed"] += 1
            on_run(rid, report, None, f"failed: {type(exc).__name__}")
            continue
        counts["rescored"] += 1
        on_run(rid, old, new, None)
    return counts
