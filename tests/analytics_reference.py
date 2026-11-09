"""A plain-Python reference for the query core's SQL (tests only).

The Python Analytics path that ``ekte/web/analytics.py`` served before the
query core (#121) took over, kept here as an independent oracle: it loads
every run and computes medians, shares and buckets in Python, so
``tests/test_query.py`` can check the SQL against it on the same database.
Nothing in ``ekte/`` uses it (#128 removed the server copy). Pooled outcome
rates are on purpose not reproduced (the old path took the median of per-run
rates; see ``test_aggregate_matches_the_python_path``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from datetime import tzinfo
from typing import Any

from ekte.web import analytics_store, history
from ekte.web.analytics import (
    _T_MAX,
    _T_MIN,
    ALL_KEY,
    DIM_PREFIX,
    FOLD_MIN_DAYS,
    MAX_KEYS,
    MIN_RUNS,
    UNKNOWN_RELAY,
    Group,
    Metric,
    RelayResolver,
    _bucket,
    metric,
    percentile,
)
from ekte.web.metrics import grade_value

_SUMMARY_COLS = (
    "id", "ts", "base_url", "claimed_model", "model", "mode", "suite", "risk_level", "score",
    "rating", "kb_match", "watch_id", "api", "api_auto", "stream_mode", "surface",
)


def runs() -> list[dict[str, Any]]:
    """Every run with its extracted metrics, oldest first by ``started_at``."""
    cols = (*(f"h.{c}" for c in _SUMMARY_COLS), *(f"m.{c}" for c in analytics_store.METRIC_COLS))
    conn = history.query_connection()
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM history h JOIN history_metrics m ON m.history_id = h.id"
        " ORDER BY m.started_at, h.id"
    ).fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["surface"] = r.get("surface") or "chat"
    return out


def dimensions(ids: Iterable[int], kind: str) -> dict[int, dict[str, Any]]:
    wanted = {int(i) for i in ids}
    out: dict[int, dict[str, Any]] = {}
    for rid, key, score in history.query_connection().execute(
        "SELECT history_id, key, score FROM history_dimensions WHERE kind = ?", (kind,)
    ):
        if int(rid) in wanted:
            out.setdefault(int(rid), {})[key] = score
    return out


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def run_value(m: Metric, run: Mapping[str, Any]) -> float | None:
    """One run's value of a metric, None when the run did not measure it."""
    if m.id.startswith(DIM_PREFIX):
        return _number((run.get("_dims") or {}).get(m.id[len(DIM_PREFIX):]))
    if m.id == "risk_high_share":
        level = run.get("risk_level")
        return None if not level else 1.0 if level == "high" else 0.0
    if m.id == "grade":
        return grade_value(run.get(m.column))
    value = _number(run.get(m.column))
    if m.agg == "share" and value is not None:
        return 1.0 if value else 0.0
    return value


def aggregate(m: Metric, values: Iterable[float | None]) -> dict[str, Any]:
    ordered = sorted(v for v in values if v is not None)
    n = len(ordered)
    if m.agg == "share":
        return {"value": sum(ordered) / n if n else None, "median": None, "p25": None, "p75": None,
                "n": n}
    median = percentile(ordered, 0.5)
    return {"value": median, "median": median, "p25": percentile(ordered, 0.25),
            "p75": percentile(ordered, 0.75), "n": n}


def _coverage(n: int, total: int) -> float | None:
    return n / total if total else None


def _load(surface: str, resolver: RelayResolver | None = None) -> list[dict[str, Any]]:
    resolver = resolver or RelayResolver()
    out = []
    for run in runs():
        if run["surface"] != surface:
            continue
        t = analytics_store.parse_ts(run.get("started_at"))
        run["_t"] = t if t is not None and _T_MIN <= t < _T_MAX else None
        run["_group"] = resolver.resolve(run)
        out.append(run)
    return out


def _attach_dims(rows: list[dict[str, Any]]) -> None:
    by_run = dimensions((r["id"] for r in rows), "dimension")
    for run in rows:
        run["_dims"] = by_run.get(int(run["id"]), {})


def group_of(group: str) -> Callable[[Mapping[str, Any]], tuple[str, dict[str, Any]]]:
    """The series key and its public description for a run, by ``group``
    (runs carry ``_group``: their :class:`RelayResolver` group)."""
    def relay(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        g: Group = run["_group"]
        return g.key, g.public()

    def model(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        name = run.get("claimed_model") or UNKNOWN_RELAY
        return name, {"key": name, "label": name, "in_kb": run.get("kb_model_id") is not None,
                      "kind": "model"}

    def both(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        g: Group = run["_group"]
        name = run.get("claimed_model") or UNKNOWN_RELAY
        key = f"{g.key}|{name}"
        return key, {"key": key, "label": f"{g.label} · {name}", "in_kb": g.in_kb,
                     "kind": "relay_model", "relay": g.key, "model": name}

    def everything(run: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        return ALL_KEY, {"key": ALL_KEY, "label": ALL_KEY, "in_kb": False, "kind": "all"}

    return {"relay": relay, "model": model, "relay_model": both, "all": everything}[group]


def _grouped(rows: list[dict[str, Any]], group: str):
    key_of = group_of(group)
    by_key: dict[str, list[dict[str, Any]]] = {}
    info: dict[str, dict[str, Any]] = {}
    for run in rows:
        key, desc = key_of(run)
        by_key.setdefault(key, []).append(run)
        if key not in info:
            info[key] = desc
        elif group == "model" and desc["in_kb"]:
            info[key]["in_kb"] = True
    return by_key, info


def breakdown(metrics: Iterable[str], group: str, surface: str = "chat") -> list[dict[str, Any]]:
    """Some metrics over every run of ``surface``, one row per group, busiest first."""
    wanted = [metric(mid, surface) for mid in metrics]
    rows_in = _load(surface)
    if any(m.id.startswith(DIM_PREFIX) for m in wanted):
        _attach_dims(rows_in)
    by_key, info = _grouped(rows_in, group)
    rows = []
    for key, members in by_key.items():
        cells = {}
        for m in wanted:
            agg = aggregate(m, (run_value(m, r) for r in members))
            cells[m.id] = {**agg, "coverage": _coverage(agg["n"], len(members)),
                           "low_n": agg["n"] < MIN_RUNS}
        rows.append({**info[key], "runs": len(members), "low_n": len(members) < MIN_RUNS,
                     "metrics": cells})
    rows.sort(key=lambda r: (-r["runs"], r["label"].lower(), r["key"]))
    return rows


def series(mid: str, group: str, size: str, zone: tzinfo, zone_name: str, *, block: int = 1,
           fold: str = "week", keys: Iterable[str] = (), surface: str = "chat") -> dict[str, Any]:
    """One metric over time per group (default: the busiest :data:`MAX_KEYS` groups)."""
    m = metric(mid, surface)
    rows_in = [r for r in _load(surface) if r["_t"] is not None]
    if m.id.startswith(DIM_PREFIX):
        _attach_dims(rows_in)
    by_key, info = _grouped(rows_in, group)
    wanted = list(dict.fromkeys(keys)) or sorted(
        by_key, key=lambda k: (-len(by_key[k]), info[k]["label"].lower(), k))[:MAX_KEYS]
    days = sorted({r["_t"].astimezone(zone).date() for key in wanted for r in by_key.get(key, [])})
    span_days = (days[-1] - days[0]).days + 1 if days else 0
    used = fold if size == "dow_hour" and span_days >= FOLD_MIN_DAYS.get(fold, 0) else "week"
    out = []
    for key in wanted:
        members = by_key.get(key, [])
        buckets: dict[str, tuple[float, dict[str, Any], list[float | None]]] = {}
        for run in members:
            pos, bkey, extra = _bucket(run["_t"], zone, size, block, used)
            buckets.setdefault(bkey, (pos, extra, []))[2].append(run_value(m, run))
        points = []
        for bkey, (_, extra, values) in sorted(buckets.items(), key=lambda i: i[1][0]):
            agg = aggregate(m, values)
            if agg["n"]:
                points.append({"bucket": bkey, **extra, "runs": len(values), **agg,
                               "low_n": agg["n"] < MIN_RUNS})
        n = sum(1 for r in members if run_value(m, r) is not None)
        out.append({
            **(info.get(key) or {"key": key, "label": key, "in_kb": False, "kind": group}),
            "runs": len(members), "n": n, "coverage": _coverage(n, len(members)), "points": points,
            "annotations": [] if size == "dow_hour" else _annotations(members, zone, size),
            "mixed": {col: len({r.get(col) for r in members if r.get(col)}) > 1
                      for col in ("suite", "stream_mode", "api")},
        })
    return {"metric": m.public(), "group": group, "bucket": size, "block": block, "fold": used,
            "fold_requested": fold, "span_days": span_days, "tz": zone_name, "series": out}


def _annotations(members: list[dict[str, Any]], zone: tzinfo, size: str) -> list[dict[str, Any]]:
    out = []
    for kind, column in (("tool_version", "tool_version"), ("kb_profile", "kb_profile_hash")):
        last = None
        for run in members:
            value = run.get(column)
            if not value:
                continue
            if last is not None and value != last:
                out.append({"bucket": _bucket(run["_t"], zone, size)[1], "kind": kind, "from": last,
                            "to": value, "run_id": run["id"], "started_at": run["started_at"]})
            last = value
    out.sort(key=lambda a: (a["started_at"], a["kind"]))
    return out
