"""The shared part of the performance budget tests (``@pytest.mark.slow``).

Every budget test reads its budget with :func:`budget` and hands each case's
p50 / p95 to :func:`record` before it asserts. With ``EKTE_BENCH_REPORT=<path>``
set, :func:`record` adds the cases to that JSON file, which
``scripts/bench_report.py`` renders as a Markdown table (the "performance
budget" CI job puts it in the job summary); without it, it does nothing.

The 20k-run fixture of ``scripts/bench_fixture.py`` is built once per pytest
session by the ``bench_data`` fixture (``tests/conftest.py``, :func:`build_fixture`)
and shared by the tests, which only read it.
"""

from __future__ import annotations

import json
import os
import statistics
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

REPORT_ENV = "EKTE_BENCH_REPORT"
# the local budgets (the reference machine of #117); CI sets its own
DEFAULT_BUDGET_MS = 50.0


def enabled() -> bool:
    """Whether the budget tests run (``EKTE_BENCH=1``)."""
    return os.environ.get("EKTE_BENCH") == "1"


def budget(default_ms: float = DEFAULT_BUDGET_MS, env: str = "EKTE_BENCH_BUDGET_MS") -> float:
    """The p95 budget in ms: ``$env`` if set, else ``default_ms``. A case with
    its own budget passes its own variable, e.g.
    ``budget(5, "EKTE_BENCH_VERSION_BUDGET_MS")`` for ``/api/version``."""
    return float(os.environ.get(env) or default_ms)


def p50(times: Iterable[float]) -> float:
    return statistics.median(times)


def measure(fn: Callable[[], Any], repeat: int = 40) -> tuple[float, float]:
    """p50 and p95 (ms, nearest rank) of ``repeat`` calls of ``fn`` after one
    warm-up call, with the garbage collector prepared as
    ``scripts/bench_fixture.py`` does (``times()``): every budget test measures
    the same way."""
    from tests.test_query import _bench_module

    bench = _bench_module()
    t = bench.times(fn, repeat)
    return p50(t), bench.p95(t)


def record(suite: str, results: Mapping[str, tuple[float, float]], budget_ms: float) -> None:
    """Add ``{case: (p50 ms, p95 ms)}`` of ``suite`` (the test module) to the
    report file of ``$EKTE_BENCH_REPORT``; a case recorded before is replaced.
    A case is over budget when its p95 is not below ``budget_ms``, as the
    tests assert."""
    path = os.environ.get(REPORT_ENV)
    if not path:
        return
    file = Path(path)
    try:
        cases = json.loads(file.read_text(encoding="utf-8"))["cases"]
    except (OSError, ValueError, KeyError, TypeError):
        cases = []
    new = {(suite, case) for case in results}
    cases = [c for c in cases if (c.get("suite"), c.get("case")) not in new]
    cases += [{"suite": suite, "case": case, "p50_ms": round(p50_ms, 2), "p95_ms": round(p95_ms, 2),
               "budget_ms": budget_ms, "ok": p95_ms < budget_ms}
              for case, (p50_ms, p95_ms) in results.items()]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"cases": cases}, indent=2) + "\n", encoding="utf-8")


def build_fixture(directory: Path) -> Path:
    """Build the 20k-run fixture of ``scripts/bench_fixture.py`` into
    ``directory`` (as ``EKTE_DATA_DIR``) and return it."""
    from ekte import datadir
    from tests.test_query import _bench_module

    saved = os.environ.get("EKTE_DATA_DIR")
    os.environ["EKTE_DATA_DIR"] = str(directory)
    try:
        _bench_module().build()
    finally:
        datadir.close_read_connections()
        if saved is None:
            os.environ.pop("EKTE_DATA_DIR", None)
        else:
            os.environ["EKTE_DATA_DIR"] = saved
    return directory
