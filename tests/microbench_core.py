"""Micro-benchmarking core utilities for CascadeFade."""
import asyncio
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import psutil


@dataclass
class BenchmarkResult:
    """Container for a single benchmark run."""
    name: str
    wall_time_ms: float
    cpu_time_ms: float
    rss_before_mb: float
    rss_after_mb: float
    rss_delta_mb: float
    peak_mem_mb: float
    ctx_switches: int
    io_read_kb: float
    io_write_kb: float
    net_sent_kb: float
    net_recv_kb: float
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "wall_time_ms": round(self.wall_time_ms, 3),
            "cpu_time_ms": round(self.cpu_time_ms, 3),
            "rss_before_mb": round(self.rss_before_mb, 3),
            "rss_after_mb": round(self.rss_after_mb, 3),
            "rss_delta_mb": round(self.rss_delta_mb, 3),
            "peak_mem_mb": round(self.peak_mem_mb, 3),
            "ctx_switches": self.ctx_switches,
            "io_read_kb": round(self.io_read_kb, 3),
            "io_write_kb": round(self.io_write_kb, 3),
            "net_sent_kb": round(self.net_sent_kb, 3),
            "net_recv_kb": round(self.net_recv_kb, 3),
            **self.extra,
        }


class MicroBenchmark:
    """Context manager / decorator that captures system metrics around a call."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.proc = psutil.Process()
        self._start_wall: float = 0.0
        self._start_cpu: float = 0.0
        self._start_mem: int = 0
        self._start_ctx: int = 0
        self._start_io_read: int = 0
        self._start_io_write: int = 0
        self._start_net_sent: int = 0
        self._start_net_recv: int = 0
        self._peak_mem: int = 0

    def _collect(self) -> dict[str, int | float]:
        mem = self.proc.memory_info()
        ctx = self.proc.num_ctx_switches()
        io = self.proc.io_counters() if hasattr(self.proc, "io_counters") else None
        net = psutil.net_io_counters()
        return {
            "rss": mem.rss,
            "vms": mem.vms,
            "cpu_sum": sum(self.proc.cpu_times()[:2]),
            "ctx": ctx.voluntary + ctx.involuntary,
            "io_read": io.read_bytes if io else 0,
            "io_write": io.write_bytes if io else 0,
            "net_sent": net.bytes_sent,
            "net_recv": net.bytes_recv,
        }

    def __enter__(self) -> "MicroBenchmark":
        tracemalloc.start()
        snap = self._collect()
        self._start_wall = time.perf_counter()
        self._start_cpu = snap["cpu_sum"]
        self._start_mem = snap["rss"]
        self._start_ctx = snap["ctx"]
        self._start_io_read = snap["io_read"]
        self._start_io_write = snap["io_write"]
        self._start_net_sent = snap["net_sent"]
        self._start_net_recv = snap["net_recv"]
        return self

    def sample_peak(self) -> None:
        """Manually sample current RSS as peak (for long coroutines)."""
        self._peak_mem = max(self._peak_mem, self.proc.memory_info().rss)

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._start_wall = time.perf_counter() - self._start_wall
        snap = self._collect()
        tracemalloc.stop()
        _, peak = tracemalloc.get_traced_memory()
        self._peak_mem = max(self._peak_mem, peak)
        self._result = BenchmarkResult(
            name=self.name,
            wall_time_ms=self._start_wall * 1000,
            cpu_time_ms=(snap["cpu_sum"] - self._start_cpu) * 1000,
            rss_before_mb=self._start_mem / (1024 * 1024),
            rss_after_mb=snap["rss"] / (1024 * 1024),
            rss_delta_mb=(snap["rss"] - self._start_mem) / (1024 * 1024),
            peak_mem_mb=self._peak_mem / (1024 * 1024),
            ctx_switches=snap["ctx"] - self._start_ctx,
            io_read_kb=(snap["io_read"] - self._start_io_read) / 1024,
            io_write_kb=(snap["io_write"] - self._start_io_write) / 1024,
            net_sent_kb=(snap["net_sent"] - self._start_net_sent) / 1024,
            net_recv_kb=(snap["net_recv"] - self._start_net_recv) / 1024,
        )

    @property
    def result(self) -> BenchmarkResult:
        return self._result


def run_sync(name: str, fn: Callable[[], Any], *, setup: Callable[[], Any] | None = None) -> BenchmarkResult:
    """Benchmark a synchronous callable."""
    if setup:
        setup()
    with MicroBenchmark(name) as bench:
        fn()
    return bench.result


async def run_async(name: str, coro: Coroutine[Any, Any, Any], *, setup: Callable[[], Any] | None = None) -> BenchmarkResult:
    """Benchmark an async coroutine."""
    if setup:
        setup()
    with MicroBenchmark(name) as bench:
        await coro
    return bench.result


def run_perf_stat(cmd: list[str], name: str = "perf") -> dict[str, Any]:
    """Run `perf stat` on a command and return CPI + cycles."""
    import subprocess
    perf_cmd = [
        "perf", "stat", "-e", "cycles,instructions,cache-misses,branch-misses",
        "--", sys.executable, "-c",
        f"import subprocess; subprocess.run({cmd!r})",
    ]
    proc = subprocess.run(perf_cmd, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    metrics: dict[str, Any] = {"name": name, "raw": out}
    for line in out.splitlines():
        # e.g.  "      1,234,567      cycles"
        parts = line.strip().split()
        if len(parts) >= 2:
            val = parts[0].replace(",", "")
            key = parts[1]
            try:
                metrics[key] = int(val)
            except ValueError:
                pass
    return metrics
