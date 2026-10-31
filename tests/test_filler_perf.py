"""Filler/haystack construction: output stability, speed, and event-loop health.

``build_filler`` used to re-join and re-count the whole text every 50 lines —
quadratic, ~6 s at the default 200k-token probe cap, run synchronously inside the
async context-window detector. That froze the event loop and corrupted latency
measured by concurrent audits in ``ekte serve``. These tests pin the linear
rewrite to the old output byte-for-byte and guard against the stall returning.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from ekte.detectors import helpers
from ekte.detectors.context_window import ContextWindowDetector
from ekte.detectors.helpers import build_filler, build_haystack
from ekte.utils.tokenize import estimate_tokens


def _reference_build_filler(target_tokens: int, tokenizer: str | None = None) -> str:
    """The original (quadratic) algorithm, kept verbatim as the output oracle."""
    if target_tokens <= 0:
        return ""
    parts: list[str] = []
    idx = 0
    while True:
        sentence = helpers._FILLER_SENTENCES[idx % len(helpers._FILLER_SENTENCES)]
        parts.append(f"[{idx:05d}] {sentence}")
        idx += 1
        if idx % 50 == 0 and estimate_tokens("\n".join(parts), tokenizer) >= target_tokens:
            break
        if idx > 400_000:  # hard safety stop
            break
    return "\n".join(parts)


@pytest.mark.parametrize("size", [0, 1, 37, 500, 1200, 4000, 16_000, 32_000])
def test_filler_is_byte_identical_to_old_algorithm(size):
    assert build_filler.__wrapped__(size, None) == _reference_build_filler(size, None)


def test_filler_is_memoized():
    build_filler.cache_clear()
    first = build_filler(3000, None)
    assert build_filler(3000, None) is first
    assert build_filler.cache_info().hits >= 1


def test_haystack_leaves_cached_filler_untouched():
    # The haystack inserts the needle into a split copy; the shared filler stays clean.
    build_filler.cache_clear()
    hay = build_haystack(total_tokens=2000, needle="EKTE-NEEDLE", depth=0.5)
    assert "EKTE-NEEDLE" in hay
    assert "EKTE-NEEDLE" not in build_filler(2000, None)


def test_filler_200k_tokens_is_fast():
    start = time.perf_counter()
    text = build_filler.__wrapped__(200_000, None)
    elapsed = time.perf_counter() - start
    assert estimate_tokens(text) >= 200_000
    assert elapsed < 0.5, f"200k-token filler took {elapsed:.2f}s"


async def test_context_window_probe_does_not_stall_event_loop(audit_context):
    """A full context-window run must not block the loop (other audits share it)."""
    build_filler.cache_clear()
    max_stall = 0.0
    stop = asyncio.Event()
    started = asyncio.Event()

    async def monitor() -> None:
        nonlocal max_stall
        interval = 0.005
        started.set()
        while not stop.is_set():
            before = time.perf_counter()
            await asyncio.sleep(interval)
            max_stall = max(max_stall, time.perf_counter() - before - interval)

    task = asyncio.create_task(monitor())
    # The mock transport never really yields, so make sure the monitor is already
    # sleeping when the detector starts — a blocked loop then shows up as a stall.
    await started.wait()
    try:
        await ContextWindowDetector().run(audit_context)
    finally:
        stop.set()
        await task
    assert max_stall < 0.25, f"event loop stalled for {max_stall * 1000:.0f} ms"
