"""Analytics tables of ``history.db``: per-run metrics and request records.

:mod:`ekte.web.history` owns the database; this module defines the three
tables it creates for the analytics views, the pure extraction that fills
them, and the small read/write helpers both ``history.save`` and the
backfill use (the same split as :mod:`ekte.knowledge.snapshot`).

``history_metrics`` — one row per run (``history_id``), every value nullable
(NULL = not measured in that run, never 0):

* ``started_at`` — when the run started, ISO UTC in one fixed-width form
  (``YYYY-MM-DDTHH:MM:SS.ffffff+00:00``, so strings sort by time).
  ``started_at_estimated`` is 1 for reports from before ``started_at`` was
  recorded: ``generated_at`` minus the span of the request records
  (``max(start_ms + duration_ms)``), else ``generated_at`` itself.
* ``tool_version``, ``kb_profile_hash``, ``kb_provider``, ``kb_model_id`` —
  the ekte version and knowledge-base profile the run was scored with.
* ``base_url_norm`` — the target base URL as
  :func:`ekte.knowledge.relays.normalize_url` gives it (relay grouping).
* ``duration_sec`` — summed detector durations (as ``history.run_duration_sec``).
* ``success_rate``, ``error_rate``, ``timeout_rate``, ``rate_limited_rate`` —
  over every target completion call (``performance.target``).
* ``latency_p50_ms``, ``latency_p95_ms``, ``ttft_p50_ms``, ``ttft_p95_ms``,
  ``decode_tps_p50`` (local count, else the reported one), ``decode_tps_p5``
  and ``decode_tps_p95`` (the slow and the fast end, from the same requests:
  :func:`ekte.perf.summary.decode_tps_tails`), ``itl_jitter_p50_ms``,
  ``relay_processing_p50_ms``, ``network_rtt_p50_ms``, ``cold_start_ms``,
  ``concurrency_tps`` (the burst's aggregate output tokens/s, local count first)
  — the target's headline performance.
* ``billing_ratio_prompt``, ``billing_ratio_completion`` — reported / estimated
  tokens of the billing detector.
* ``reasoning_share`` — reasoning tokens / reported output tokens, and
  ``cached_input_share`` — cached / reported input tokens, summed over the
  target's request records that report both.
* ``model_mismatch`` — 1 when the echoed ``model`` field differs from the
  requested one, 0 when it matches (model_identity detector; embed.identity
  for an embedding run).
* ``identity_status`` — that detector's status.
* ``context_claimed_tokens``, ``context_effective_tokens`` — declared and
  measured context window (context_window detector).
* ``findings_high`` (high + critical), ``findings_medium``, ``findings_low`` —
  finding counts of the target's detectors.
* ``extract_version`` — :data:`EXTRACT_VERSION` of the extraction that wrote
  the row; rows below it are extracted again by the backfill.

``history_dimensions`` — ``(history_id, kind, key)``: the score, status and
weight of each dimension (``kind='dimension'``) and the score and status of each
target detector (``kind='detector'``, weight NULL).

``history_requests`` — the run's ``performance.requests`` (target and
baseline records), one row per record in list order (``ord``), one column per
:class:`~ekte.models.RequestRecord` field, and ``extra``: a JSON object, NULL
for an ordinary record, that holds whatever the columns cannot reproduce
exactly (unknown keys, values of another type, missing keys, key order). The
saved report keeps an empty ``requests`` list in their place and
``history.requests_split`` marks the row; reading puts the records back, so a
report reads back identical to the one saved.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from ekte.knowledge.relays import normalize_url
from ekte.models import RequestRecord
from ekte.perf.summary import decode_tps_tails

# Bump when extract_metrics() changes what it extracts: the backfill then
# re-extracts every row written by an older version, without a schema change.
EXTRACT_VERSION = 3  # 2: decode_tps_p5, decode_tps_p95; 3: model_mismatch of embedding runs

# Column name -> SQL type of history_metrics (after history_id), in order.
METRIC_COLS: dict[str, str] = {
    "started_at": "TEXT",
    "started_at_estimated": "INTEGER",
    "tool_version": "TEXT",
    "kb_profile_hash": "TEXT",
    "kb_provider": "TEXT",
    "kb_model_id": "TEXT",
    "base_url_norm": "TEXT",
    "duration_sec": "REAL",
    "success_rate": "REAL",
    "error_rate": "REAL",
    "timeout_rate": "REAL",
    "rate_limited_rate": "REAL",
    "latency_p50_ms": "REAL",
    "latency_p95_ms": "REAL",
    "ttft_p50_ms": "REAL",
    "ttft_p95_ms": "REAL",
    "decode_tps_p50": "REAL",
    "decode_tps_p5": "REAL",
    "decode_tps_p95": "REAL",
    "itl_jitter_p50_ms": "REAL",
    "relay_processing_p50_ms": "REAL",
    "network_rtt_p50_ms": "REAL",
    "cold_start_ms": "REAL",
    "concurrency_tps": "REAL",
    "billing_ratio_prompt": "REAL",
    "billing_ratio_completion": "REAL",
    "reasoning_share": "REAL",
    "cached_input_share": "REAL",
    "model_mismatch": "INTEGER",
    "identity_status": "TEXT",
    "context_claimed_tokens": "INTEGER",
    "context_effective_tokens": "INTEGER",
    "findings_high": "INTEGER",
    "findings_medium": "INTEGER",
    "findings_low": "INTEGER",
    "extract_version": "INTEGER",
}

# RequestRecord field -> value kind, in model order. A field added to
# RequestRecord needs a column here (and in the migration); until then it is
# kept in ``extra``, so nothing is lost.
REQUEST_FIELDS: dict[str, str] = {
    "seq": "int",
    "endpoint": "str",
    "detector": "str",
    "phase": "str",
    "op": "str",
    "stream": "bool",
    "start_ms": "float",
    "ok": "bool",
    "status_code": "int",
    "error_type": "str",
    "timeout": "bool",
    "rate_limited": "bool",
    "duration_ms": "float",
    "ttft_ms": "float",
    "chunk_count": "int",
    "itl_mean_ms": "float",
    "itl_p50_ms": "float",
    "itl_p95_ms": "float",
    "itl_jitter_ms": "float",
    "input_tokens_reported": "int",
    "output_tokens_reported": "int",
    "input_tokens_local": "int",
    "output_tokens_local": "int",
    "tokens_exact": "bool",
    "reasoning_tokens": "int",
    "cached_input_tokens": "int",
    "decode_tps_reported": "float",
    "decode_tps_local": "float",
    "e2e_tps_reported": "float",
    "e2e_tps_local": "float",
    "connect_ms": "float",
    "tls_ms": "float",
    "headers_ms": "float",
    "server_ms": "float",
    "relay_processing_ms": "float",
    "cached": "bool",
}
_SQL_TYPE = {"int": "INTEGER", "bool": "INTEGER", "float": "REAL", "str": "TEXT"}
_INT64 = 2**63


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the analytics tables and their indexes (idempotent)."""
    metric_cols = ",\n".join(f"{c} {t}" for c, t in METRIC_COLS.items())
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS history_metrics (
            history_id INTEGER PRIMARY KEY,
            {metric_cols}
        )"""
    )
    # Time-range filters of every analytics query.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_metrics_started "
        "ON history_metrics (started_at)"
    )
    # Finds rows the backfill must (re-)extract.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_metrics_version "
        "ON history_metrics (extract_version)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS history_dimensions (
            history_id INTEGER NOT NULL,
            kind       TEXT NOT NULL,
            key        TEXT NOT NULL,
            score      REAL,
            status     TEXT,
            weight     REAL,
            PRIMARY KEY (history_id, kind, key)
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_dimensions_key "
        "ON history_dimensions (kind, key)"
    )
    request_cols = ",\n".join(f"{c} {_SQL_TYPE[k]}" for c, k in REQUEST_FIELDS.items())
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS history_requests (
            history_id INTEGER NOT NULL,
            ord        INTEGER NOT NULL,
            {request_cols},
            extra      TEXT,
            PRIMARY KEY (history_id, ord)
        )"""
    )


def delete_for(conn: sqlite3.Connection, rid: int | None = None) -> None:
    """Delete the analytics rows of one run, or of every run (``rid`` None)."""
    for table in ("history_metrics", "history_dimensions", "history_requests"):
        if rid is None:
            conn.execute(f"DELETE FROM {table}")
        else:
            conn.execute(f"DELETE FROM {table} WHERE history_id = ?", (int(rid),))


# --------------------------------------------------------------------------- #
# Request records: out of report_json and back
# --------------------------------------------------------------------------- #
def _exact(kind: str, value: Any) -> bool:
    """True if a column of ``kind`` gives ``value`` back with the same type."""
    if value is None:
        return True
    if kind == "bool":
        return type(value) is bool
    if kind == "int":
        return type(value) is int and -_INT64 <= value < _INT64
    if kind == "float":
        # SQLite stores NaN as NULL and may drop the sign of -0.0.
        return (
            type(value) is float and math.isfinite(value)
            and not (value == 0 and math.copysign(1.0, value) < 0)
        )
    return type(value) is str


def _column(kind: str, value: Any) -> Any:
    """What goes into the column: the value, or the nearest one the column can
    hold (``extra`` then keeps the exact one), or NULL."""
    if value is None:
        return None
    if kind == "bool":
        return int(value) if type(value) is bool else None
    if kind == "str":
        return value if type(value) is str else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if kind == "int":
        whole = _int(value)
        return whole if whole is not None and -_INT64 <= whole < _INT64 else None
    try:
        number = float(value) + 0.0  # + 0.0: never -0.0
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def encode_request(rec: dict[str, Any]) -> tuple[Any, ...]:
    """One record as its column values, ``extra`` last (see the module docstring)."""
    fields: dict[str, Any] = {}
    absent = [name for name in REQUEST_FIELDS if name not in rec]
    values = []
    for name, kind in REQUEST_FIELDS.items():
        value = rec.get(name)
        if name in rec and not _exact(kind, value):
            fields[name] = value
        values.append(_column(kind, value))
    for key, value in rec.items():
        if key not in REQUEST_FIELDS:
            fields[key] = value
    extra: dict[str, Any] = {}
    if fields:
        extra["fields"] = fields
    if absent:
        extra["absent"] = absent
    if list(_assemble(values, extra)) != list(rec):
        extra["order"] = list(rec)
    values.append(json.dumps(extra, ensure_ascii=False) if extra else None)
    return tuple(values)


def _assemble(values: list[Any] | tuple[Any, ...], extra: dict[str, Any]) -> dict[str, Any]:
    fields = extra.get("fields") or {}
    absent = set(extra.get("absent") or ())
    rec: dict[str, Any] = {}
    for (name, kind), value in zip(REQUEST_FIELDS.items(), values, strict=False):
        if name in absent:
            continue
        if name in fields:
            rec[name] = fields[name]
        else:
            rec[name] = bool(value) if kind == "bool" and value is not None else value
    for key, value in fields.items():
        rec.setdefault(key, value)
    order = extra.get("order")
    if order:
        rec = {key: rec[key] for key in order if key in rec}
    return rec


def decode_request(row: tuple[Any, ...] | sqlite3.Row) -> dict[str, Any]:
    """The record a :func:`encode_request` tuple (as read back) stands for."""
    values = tuple(row)
    raw = values[len(REQUEST_FIELDS)]
    try:
        extra = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        extra = {}  # damaged: the columns are still the best answer
    return _assemble(values[: len(REQUEST_FIELDS)], extra if isinstance(extra, dict) else {})


def split_requests(
    report: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[Any, ...]] | None]:
    """Take ``performance.requests`` out of a JSON-ready report.

    Returns the report with an empty ``requests`` list in their place (a
    shallow copy; ``report`` is left alone) and the encoded records, or
    ``report`` itself and None when there is nothing to move, or the records
    would not read back exactly (they then stay inline).
    """
    perf = report.get("performance")
    records = perf.get("requests") if isinstance(perf, dict) else None
    if not isinstance(perf, dict) or not isinstance(records, list) or not records:
        return report, None
    if not all(isinstance(r, dict) for r in records):
        return report, None
    rows = [encode_request(r) for r in records]
    # Belt and braces: only move what demonstrably reads back the same.
    if json.dumps([decode_request(r) for r in rows]) != json.dumps(records):
        return report, None
    return {**report, "performance": {**perf, "requests": []}}, rows


def put_requests(conn: sqlite3.Connection, rid: int, rows: list[tuple[Any, ...]]) -> None:
    """Store a run's encoded records (replacing any it had)."""
    conn.execute("DELETE FROM history_requests WHERE history_id = ?", (int(rid),))
    cols = ("history_id", "ord", *REQUEST_FIELDS, "extra")
    conn.executemany(
        f"INSERT INTO history_requests ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' * len(cols))})",
        [(int(rid), i, *row) for i, row in enumerate(rows)],
    )


def get_requests(conn: sqlite3.Connection, rid: int) -> list[dict[str, Any]]:
    """A run's request records in their original order."""
    cols = ", ".join((*REQUEST_FIELDS, "extra"))
    rows = conn.execute(
        f"SELECT {cols} FROM history_requests WHERE history_id = ? ORDER BY ord",
        (int(rid),),
    ).fetchall()
    return [decode_request(r) for r in rows]


def restore_requests(report: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """Put stored records back into a report read from ``report_json``."""
    perf = report.get("performance")
    if isinstance(perf, dict):
        perf["requests"] = records


# --------------------------------------------------------------------------- #
# Metric extraction
# --------------------------------------------------------------------------- #
def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and -_INT64 <= value < _INT64:
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_ts(value: Any) -> datetime | None:
    """An ISO timestamp as an aware UTC datetime (naive ones are taken as UTC)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    try:
        return dt.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def format_ts(dt: datetime) -> str:
    """The fixed-width UTC form ``started_at`` is stored in."""
    utc = dt.astimezone(UTC).replace(tzinfo=None)
    return utc.isoformat(timespec="microseconds") + "+00:00"


def _requests_span_ms(records: list[Any]) -> float | None:
    """How long after the audit's start the last request ended, in ms."""
    span = None
    for rec in records:
        if not isinstance(rec, dict):
            continue
        start = _num(rec.get("start_ms"))
        if start is None:
            continue
        end = start + (_num(rec.get("duration_ms")) or 0.0)
        span = end if span is None else max(span, end)
    return span


def started_at(report: dict[str, Any]) -> tuple[str | None, int | None]:
    """``(started_at, estimated)`` of a report (see the module docstring)."""
    dt = parse_ts(report.get("started_at"))
    if dt is not None:
        return format_ts(dt), 0
    generated = parse_ts(report.get("generated_at"))
    if generated is None:
        return None, None
    span = _requests_span_ms(_list(_dict(report.get("performance")).get("requests")))
    if span is not None and span > 0:
        try:
            generated -= timedelta(milliseconds=span)
        except OverflowError:
            return None, None
    return format_ts(generated), 1


def _p(stats: Any, key: str) -> float | None:
    return _num(_dict(stats).get(key))


def _rate(part: Any, whole: Any) -> float | None:
    n, total = _int(part), _int(whole)
    return n / total if n is not None and total else None


def _share(records: list[Any], part: str, whole: str) -> float | None:
    """Summed ``part`` / summed ``whole`` over the target records reporting both."""
    num = den = 0
    for rec in records:
        if not isinstance(rec, dict) or rec.get("endpoint", "target") != "target":
            continue
        a, b = _int(rec.get(part)), _int(rec.get(whole))
        if a is None or b is None or b <= 0:
            continue
        num += a
        den += b
    return num / den if den else None


def _detector(detectors: list[Any], det_id: str) -> dict[str, Any]:
    for det in detectors:
        if isinstance(det, dict) and det.get("id") == det_id:
            return det
    return {}


def _model_mismatch(identity: dict[str, Any]) -> int | None:
    """1 / 0 from the echoed-model-field check, None when it was not usable."""
    for f in _list(identity.get("findings")):
        if not isinstance(f, dict):
            continue
        check = f.get("check") or f.get("id")
        outcome = f.get("outcome")
        if check == "embed.model_field":  # the embedding surface's echoed model
            return 1 if outcome == "differs" else 0 if outcome == "matches" else None
        if check != "model_identity.model_field":
            continue
        if outcome == "diverges":
            return 1
        if outcome == "consistent":
            return 0
        if outcome is None:  # reports from before scoring outcomes were recorded
            ev = _dict(f.get("evidence"))
            if not _str(ev.get("returned")):
                return None
            status = f.get("status")
            return 1 if status in ("fail", "warn") else 0 if status == "pass" else None
        return None
    return None


def _duration_sec(detectors: list[Any]) -> float | None:
    total = 0.0
    for det in detectors:
        ms = _num(det.get("duration_ms")) if isinstance(det, dict) else None
        if ms is not None:
            total += ms
    return round(total / 1000, 1) if total > 0 else None


def _decode_tails(records: list[Any]) -> tuple[float | None, float | None]:
    """Decode speed p5 / p95 of the report's request records (records that do
    not parse are left out)."""
    parsed = []
    for rec in records:
        if isinstance(rec, dict):
            try:
                parsed.append(RequestRecord.model_validate(rec))
            except ValueError:
                continue
    try:
        return decode_tps_tails(parsed)
    except Exception:
        return None, None


def extract_metrics(report: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The ``history_metrics`` row (by column) and ``history_dimensions`` rows
    of one report dict. Pure; any shape of input gives NULLs, never an error."""
    report = _dict(report)
    target = _dict(report.get("target"))
    knowledge = _dict(report.get("knowledge"))
    perf = _dict(report.get("performance"))
    side = _dict(perf.get("target"))
    detectors = _list(report.get("detectors"))
    records = _list(perf.get("requests"))

    start, estimated = started_at(report)
    base_url = target.get("base_url")
    billing = _dict(_detector(detectors, "billing").get("evidence"))
    identity = _detector(detectors, "model_identity") or _detector(detectors, "embed.identity")
    context = _dict(_detector(detectors, "context_window").get("evidence"))
    decode = _p(side.get("decode_tps_local"), "p50")
    decode_p5, decode_p95 = _decode_tails(records)
    burst = _dict(side.get("concurrency"))
    burst_tps = _num(burst.get("aggregate_tps_local"))

    counts = {"high": 0, "medium": 0, "low": 0}
    for det in detectors:
        for f in _list(_dict(det).get("findings")):
            sev = _dict(f).get("severity")
            sev = "high" if sev == "critical" else sev
            if sev in counts:
                counts[sev] += 1
    has_findings = any(isinstance(d, dict) for d in detectors)

    metrics: dict[str, Any] = {
        "started_at": start,
        "started_at_estimated": estimated,
        "tool_version": _str(report.get("tool_version")),
        "kb_profile_hash": _str(knowledge.get("profile_hash")),
        "kb_provider": _str(knowledge.get("provider")),
        "kb_model_id": _str(knowledge.get("model_id")),
        "base_url_norm": normalize_url(base_url) if isinstance(base_url, str) else None,
        "duration_sec": _duration_sec(detectors),
        "success_rate": _rate(side.get("successes"), side.get("requests")),
        "error_rate": _num(side.get("error_rate")),
        "timeout_rate": _num(side.get("timeout_rate")),
        "rate_limited_rate": _num(side.get("rate_limited_rate")),
        "latency_p50_ms": _p(side.get("latency_ms"), "p50"),
        "latency_p95_ms": _p(side.get("latency_ms"), "p95"),
        "ttft_p50_ms": _p(side.get("ttft_ms"), "p50"),
        "ttft_p95_ms": _p(side.get("ttft_ms"), "p95"),
        "decode_tps_p50": decode if decode is not None else _p(side.get("decode_tps_reported"), "p50"),
        "decode_tps_p5": decode_p5,
        "decode_tps_p95": decode_p95,
        "itl_jitter_p50_ms": _p(side.get("itl_jitter_ms"), "p50"),
        "relay_processing_p50_ms": _p(side.get("relay_processing_ms"), "p50"),
        "network_rtt_p50_ms": _p(side.get("network_rtt_ms"), "p50"),
        "cold_start_ms": _num(side.get("cold_start_ms")),
        "concurrency_tps": (
            burst_tps if burst_tps is not None else _num(burst.get("aggregate_tps_reported"))
        ),
        "billing_ratio_prompt": _num(billing.get("ratio_prompt")),
        "billing_ratio_completion": _num(billing.get("ratio_completion")),
        "reasoning_share": _share(records, "reasoning_tokens", "output_tokens_reported"),
        "cached_input_share": _share(records, "cached_input_tokens", "input_tokens_reported"),
        "model_mismatch": _model_mismatch(identity),
        "identity_status": _str(identity.get("status")),
        "context_claimed_tokens": _int(context.get("declared")),
        "context_effective_tokens": _int(context.get("effective_window")),
        "findings_high": counts["high"] if has_findings else None,
        "findings_medium": counts["medium"] if has_findings else None,
        "findings_low": counts["low"] if has_findings else None,
        "extract_version": EXTRACT_VERSION,
    }

    dims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, key: Any, item: dict[str, Any], weight: float | None) -> None:
        if not isinstance(key, str) or not key or (kind, key) in seen:
            return
        seen.add((kind, key))
        dims.append({
            "kind": kind, "key": key, "score": _num(item.get("score")),
            "status": _str(item.get("status")), "weight": weight,
        })

    for dim in _list(report.get("dimensions")):
        dim = _dict(dim)
        add("dimension", dim.get("dimension"), dim, _num(dim.get("weight")))
    for det in detectors:
        det = _dict(det)
        add("detector", det.get("id"), det, None)
    return metrics, dims


def put_metrics(
    conn: sqlite3.Connection, rid: int, metrics: dict[str, Any], dims: Iterable[dict[str, Any]]
) -> None:
    """Store (or replace) one run's extracted metrics — only while the run exists."""
    rid = int(rid)
    cols = ("history_id", *METRIC_COLS)
    conn.execute(
        f"INSERT OR REPLACE INTO history_metrics ({', '.join(cols)}) "
        f"SELECT {', '.join('?' * len(cols))} WHERE EXISTS (SELECT 1 FROM history WHERE id = ?)",
        (rid, *(metrics.get(c) for c in METRIC_COLS), rid),
    )
    conn.execute("DELETE FROM history_dimensions WHERE history_id = ?", (rid,))
    conn.executemany(
        "INSERT INTO history_dimensions (history_id, kind, key, score, status, weight) "
        "SELECT ?, ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM history WHERE id = ?)",
        [(rid, d["kind"], d["key"], d["score"], d["status"], d["weight"], rid) for d in dims],
    )
