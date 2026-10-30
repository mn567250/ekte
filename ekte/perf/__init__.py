"""Performance measurement: per-request recording and the report's performance section.

:mod:`zing.perf.recorder` logs every chat call and ``GET /models`` ping a client
makes during an audit (timing, tokens, transport breakdown — never text);
:mod:`zing.perf.summary` turns those records into the informational
:class:`~zing.models.PerformanceReport`.
"""

from __future__ import annotations

from zing.perf.recorder import (
    NetTrace,
    RequestRecorder,
    current_net_trace,
    detector_scope,
    phase_scope,
)
from zing.perf.summary import build_performance, summarize_endpoint

__all__ = [
    "NetTrace",
    "RequestRecorder",
    "build_performance",
    "current_net_trace",
    "detector_scope",
    "phase_scope",
    "summarize_endpoint",
]
