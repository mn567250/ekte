"""Run windows (ekte.runwindow): pure schedule logic."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ekte import runwindow as rw

BER = ZoneInfo("Europe/Berlin")


def ts(y, m, d, h, mi=0, tz=BER):
    return datetime(y, m, d, h, mi, tzinfo=tz).timestamp()


def win(days, start, end, tz="Europe/Berlin"):
    return rw.parse({"tz": tz, "days": days, "start": start, "end": end})


WEEKDAYS = [0, 1, 2, 3, 4]


def test_edges_and_days():
    w = win(WEEKDAYS, "07:00", "19:00")
    assert not rw.in_window(w, ts(2026, 11, 9, 6, 59))  # Monday
    assert rw.in_window(w, ts(2026, 11, 9, 7, 0))  # start is inside
    assert rw.in_window(w, ts(2026, 11, 9, 18, 59))
    assert not rw.in_window(w, ts(2026, 11, 9, 19, 0))  # end is outside
    assert not rw.in_window(w, ts(2026, 11, 14, 12))  # Saturday


def test_none_is_always():
    assert rw.in_window(None, 0)
    assert rw.hours_per_week(None) == 168
    assert rw.next_window_start(None, 0) is None


def test_overnight_belongs_to_start_day():
    w = win([4], "22:00", "06:00")  # Fridays
    assert rw.in_window(w, ts(2026, 11, 13, 23))  # Fri 23:00
    assert rw.in_window(w, ts(2026, 11, 14, 3))  # Sat 03:00
    assert not rw.in_window(w, ts(2026, 11, 14, 6))
    assert not rw.in_window(w, ts(2026, 11, 13, 3))  # Fri 03:00 belongs to Thu
    assert not rw.in_window(w, ts(2026, 11, 14, 23))
    assert rw.hours_per_week(w) == 8


def test_overnight_wraps_sunday_to_monday():
    w = win([6], "22:00", "06:00")
    assert rw.in_window(w, ts(2026, 11, 9, 2))  # Monday 02:00


def test_all_day():
    w = win(list(range(7)), "00:00", "24:00")
    assert rw.hours_per_week(w) == 168
    assert rw.in_window(w, ts(2026, 11, 14, 23, 59))
    assert rw.next_window_start(w, ts(2026, 11, 14, 5)) is None
    w = win([0], "00:00", "24:00")
    assert rw.in_window(w, ts(2026, 11, 9, 23, 59))
    assert not rw.in_window(w, ts(2026, 11, 10, 0))


@pytest.mark.parametrize(
    ("tz", "day_before", "day_after"),
    [
        (BER, (2026, 3, 28), (2026, 3, 30)),
        (BER, (2026, 10, 24), (2026, 10, 26)),
        (ZoneInfo("America/New_York"), (2026, 3, 7), (2026, 3, 9)),
        (ZoneInfo("America/New_York"), (2026, 10, 31), (2026, 11, 2)),
    ],
)
def test_dst_uses_wall_clock(tz, day_before, day_after):
    w = win(list(range(7)), "09:00", "10:00", tz=tz.key)
    for day in (day_before, day_after):
        assert rw.in_window(w, ts(*day, 9, 30, tz=tz))
        assert not rw.in_window(w, ts(*day, 10, 0, tz=tz))
        assert not rw.in_window(w, ts(*day, 8, 59, tz=tz))


def test_dst_change_day_itself():
    w = win(list(range(7)), "00:00", "24:00")
    assert rw.in_window(w, ts(2026, 3, 29, 3, 30))
    assert rw.hours_per_week(w) == 168
    w = win(WEEKDAYS, "07:00", "19:00")
    # Sunday 2026-10-25 (25 h long) is outside; Monday morning is wall-clock 07:00
    assert not rw.in_window(w, ts(2026, 10, 25, 12))
    assert rw.next_window_start(w, ts(2026, 10, 25, 12)) == ts(2026, 10, 26, 7)


def test_next_window_start_across_weekend():
    w = win(WEEKDAYS, "07:00", "19:00")
    assert rw.next_window_start(w, ts(2026, 11, 13, 20)) == ts(2026, 11, 16, 7)  # Fri night
    assert rw.next_window_start(w, ts(2026, 11, 13, 10)) == ts(2026, 11, 16, 7)  # inside: next edge
    assert rw.next_window_start(w, ts(2026, 11, 9, 5, 30)) == ts(2026, 11, 9, 7)


def test_hours_per_week():
    assert rw.hours_per_week(win(WEEKDAYS, "07:00", "19:00")) == 60
    assert rw.hours_per_week(win(WEEKDAYS, "00:00", "24:00")) == 120


def test_validate_normalises():
    raw = {"tz": "UTC", "days": [2, 0, 0], "start": "07:00", "end": "24:00"}
    assert rw.validate(raw) == {"tz": "UTC", "days": [0, 2], "start": "07:00", "end": "24:00"}
    assert rw.validate(None) is None


@pytest.mark.parametrize(
    "patch",
    [
        {"days": []},
        {"days": [7]},
        {"days": [True]},
        {"start": "08:00", "end": "08:00"},
        {"tz": "Mars/Base"},
        {"tz": ""},
        {"start": "07:30"},
        {"start": "24:00"},
        {"end": "25:00"},
        {"start": "7:00"},
        {"extra": 1},
    ],
)
def test_validate_rejects(patch):
    raw = {"tz": "UTC", "days": [0], "start": "07:00", "end": "19:00", **patch}
    with pytest.raises(ValueError):
        rw.validate(raw)


def test_validate_rejects_non_object():
    with pytest.raises(ValueError):
        rw.validate("always")


@pytest.mark.parametrize("bad", ["{not json", '{"tz": "Mars/Base"}', "[]", 5, {"days": []}])
def test_malformed_reads_as_always(bad):
    assert rw.parse(bad) is None


def test_parse_json_string():
    w = rw.parse('{"tz": "UTC", "days": [0], "start": "07:00", "end": "19:00"}')
    assert w is not None and w.days == frozenset({0})
