"""Wall-time and peak-memory measurement (includes native allocations via RSS sampling)."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psutil


@dataclass
class ResourceUsage:
    wall_seconds: float = 0.0
    peak_rss_mb: float = 0.0
    peak_rss_increase_mb: float = 0.0


@contextmanager
def track_resources(interval_s: float = 0.05) -> Iterator[ResourceUsage]:
    """Measure elapsed time and peak resident memory of this process during the block."""
    proc = psutil.Process()
    usage = ResourceUsage()
    base = proc.memory_info().rss
    peak = [base]
    stop = threading.Event()

    def _sample() -> None:
        while not stop.is_set():
            with contextlib.suppress(psutil.Error):
                peak[0] = max(peak[0], proc.memory_info().rss)
            stop.wait(interval_s)

    thread = threading.Thread(target=_sample, daemon=True)
    t0 = time.perf_counter()
    thread.start()
    try:
        yield usage
    finally:
        stop.set()
        thread.join()
        peak[0] = max(peak[0], proc.memory_info().rss)
        usage.wall_seconds = time.perf_counter() - t0
        usage.peak_rss_mb = peak[0] / 2**20
        usage.peak_rss_increase_mb = (peak[0] - base) / 2**20
