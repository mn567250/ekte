"""How old the bundled knowledge base is, and the warning when it is too old.

Every packaged provider profile carries ``last_verified`` (an ISO date). The
knowledge-base date of a run is the *oldest* of them: the date up to which all
bundled data was checked. A stale date never changes a verdict; it only adds a
warning (see docs/STABILITY.md and the developer guide, "Keeping the knowledge
base current").
"""

from __future__ import annotations

from datetime import date

# Documented threshold: bundled data older than this many days is "stale".
STALE_AFTER_DAYS = 180


def _parse(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def bundled_date() -> str | None:
    """The oldest ``last_verified`` of the packaged profiles (ISO date), or None."""
    from ekte.knowledge.loader import _load_packaged

    dates = [d for prof, _src in _load_packaged().values() if (d := _parse(prof.last_verified))]
    return min(dates).isoformat() if dates else None


def age_days(kb_date: str | None, today: date | None = None) -> int | None:
    parsed = _parse(kb_date)
    if parsed is None:
        return None
    return ((today or date.today()) - parsed).days


def stale_warning(kb_date: str | None, today: date | None = None) -> str | None:
    """A warning when ``kb_date`` is older than the threshold, else None."""
    days = age_days(kb_date, today)
    if days is None or days <= STALE_AFTER_DAYS:
        return None
    return (
        f"The bundled knowledge base was last verified on {kb_date} ({days} days ago; "
        f"older than {STALE_AFTER_DAYS} days). Model names, limits and deprecations may "
        "have changed: update ekte, or add your own entries with `ekte kb-import`. "
        "The verdict is not changed by this."
    )
