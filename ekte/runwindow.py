"""Run window of a monitor: the days and hours in which the scheduler may start it.

A window is one rule, stored as JSON on the monitor::

    {"tz": "Europe/Berlin", "days": [0, 1, 2, 3, 4], "start": "07:00", "end": "19:00"}

``days`` are weekdays (0 = Monday), ``start`` and ``end`` whole hours (``end``
may be ``24:00``), ``tz`` an IANA zone name. ``end <= start`` is an overnight
window: it ends the next morning and belongs to the day it starts on. No rule
(``None``) means always.

Whether *now* is inside the window is always decided from the wall clock in the
window's own zone; no "next fire time" is ever stored, so DST changes cannot
leave a stale schedule behind. Pure functions, standard library only, no I/O.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_log = logging.getLogger(__name__)

class InvalidWindow(ValueError):
    """An invalid rule; ``code`` indexes :data:`MESSAGES`."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


# The fixed English messages of the API (never derived from exception text).
MESSAGES = (
    "Times must be given as HH:00.",
    "Only whole hours are supported.",
    "Time is out of range.",
    "The run window must be an object.",
    "The run window has unknown fields.",
    "Time zone is not valid.",
    "Choose at least one day.",
    "Days must be numbers from 0 (Monday) to 6 (Sunday).",
    "Start and end must differ; use 00:00 to 24:00 for all day.",
)


def problem(raw: Any) -> str | None:
    """The fixed message for an invalid rule, ``None`` when it is valid."""
    try:
        validate(raw)
    except InvalidWindow as exc:
        return MESSAGES[exc.code]
    return None


_KEYS = frozenset({"tz", "days", "start", "end"})
_TIME = re.compile(r"^(\d{2}):(\d{2})$")
_SEARCH_HOURS = 8 * 24


@dataclass(frozen=True)
class RunWindow:
    tz: str
    days: frozenset[int]
    start: int  # hour, 0..23
    end: int  # hour, 0..24

    @property
    def overnight(self) -> bool:
        return self.end <= self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "tz": self.tz,
            "days": sorted(self.days),
            "start": f"{self.start:02d}:00",
            "end": f"{self.end:02d}:00",
        }


def _hour(value: Any, *, maximum: int) -> int:
    m = _TIME.match(value) if isinstance(value, str) else None
    if not m:
        raise InvalidWindow(0)
    hour, minute = int(m.group(1)), int(m.group(2))
    if minute != 0:
        raise InvalidWindow(1)
    if hour > maximum:
        raise InvalidWindow(2)
    return hour


def _build(raw: Any) -> RunWindow:
    if not isinstance(raw, dict):
        raise InvalidWindow(3)
    if set(raw) - _KEYS:
        raise InvalidWindow(4)
    tz = raw.get("tz")
    if not isinstance(tz, str) or not tz.strip():
        raise InvalidWindow(5)
    try:
        ZoneInfo(tz)
    except (KeyError, ValueError, OSError):
        raise InvalidWindow(5) from None
    days = raw.get("days")
    if not isinstance(days, list) or not days:
        raise InvalidWindow(6)
    if any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days):
        raise InvalidWindow(7)
    start = _hour(raw.get("start"), maximum=23)
    end = _hour(raw.get("end"), maximum=24)
    if start == end:
        raise InvalidWindow(8)
    return RunWindow(tz, frozenset(days), start, end)


def validate(raw: Any) -> dict[str, Any] | None:
    """The normalised rule for an API value, ``None`` for "always".

    Raises ``ValueError`` with a fixed English message for an invalid rule.
    """
    if raw is None:
        return None
    return _build(raw).to_dict()


def parse(raw: str | dict[str, Any] | None) -> RunWindow | None:
    """A stored value as a window. Malformed values read as ``None`` (always)."""
    if raw is None or raw == "":
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if data is None:
            return None
        return _build(data)
    except (ValueError, TypeError) as exc:
        _log.warning("ignoring malformed run window %r: %s", raw, exc)
        return None


def _on(w: RunWindow, day: int, hour: int) -> bool:
    if not w.overnight:
        return day in w.days and w.start <= hour < w.end
    return (day in w.days and hour >= w.start) or ((day - 1) % 7 in w.days and hour < w.end)


def _local(w: RunWindow, ts: float) -> datetime:
    return datetime.fromtimestamp(ts, ZoneInfo(w.tz))


def in_window(w: RunWindow | None, ts: float) -> bool:
    """Whether ``ts`` is inside the window (``None`` is always)."""
    if w is None:
        return True
    local = _local(w, ts)
    return _on(w, local.weekday(), local.hour)


def next_window_start(w: RunWindow | None, ts: float) -> float | None:
    """The next moment the window opens after ``ts`` (an off to on edge within
    the next 8 days), or ``None`` for an always-open window."""
    if w is None:
        return None
    local = _local(w, ts)
    base = ts - local.minute * 60 - local.second - local.microsecond / 1e6
    prev = in_window(w, base)
    for i in range(1, _SEARCH_HOURS + 1):
        t = base + i * 3600
        cur = in_window(w, t)
        if cur and not prev:
            return t
        prev = cur
    return None


def hours_per_week(w: RunWindow | None) -> int:
    """How many of the 168 weekly hours are inside the window."""
    if w is None:
        return 168
    return sum(_on(w, d, h) for d in range(7) for h in range(24))
