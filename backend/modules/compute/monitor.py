from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import psutil  # type: ignore[import-untyped]  # psutil does not ship type hints in this environment.

from modules.compute.core.base import ComputeEngine


async def monitor_engine_resources(engine: ComputeEngine, interval: float = 1.0) -> AsyncIterator[dict[str, float | int | None]]:
    pid = engine.process_id
    if pid is None:
        return

    process = psutil.Process(pid)
    logical_cpu_count = psutil.cpu_count() or 1
    configured_max_threads = engine.effective_resources.get('max_threads') if engine.effective_resources else None
    cpu_capacity = configured_max_threads if isinstance(configured_max_threads, int) and configured_max_threads > 0 else logical_cpu_count
    process.cpu_percent(interval=None)
    while engine.is_process_alive():
        try:
            with process.oneshot():
                memory_mb = process.memory_info().rss / (1024 * 1024)
                active_threads = process.num_threads()
                raw_cpu_percent = process.cpu_percent(interval=None)
        except (psutil.Error, OSError):
            return

        yield {
            'cpu_percent': round(min(max(raw_cpu_percent / cpu_capacity, 0.0), 100.0), 2),
            'memory_mb': round(memory_mb, 2),
            'memory_limit_mb': engine.effective_resources.get('max_memory_mb') if engine.effective_resources else None,
            'active_threads': active_threads,
            'max_threads': engine.effective_resources.get('max_threads') if engine.effective_resources else None,
        }
        await asyncio.sleep(interval)
