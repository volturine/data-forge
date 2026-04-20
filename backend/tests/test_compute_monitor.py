import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast

from modules.compute.core.base import ComputeEngine
from modules.compute.monitor import monitor_engine_resources


class _StubProcess:
    def __init__(self, cpu_percent: float, memory_mb: float, threads: int) -> None:
        self._cpu_percent = cpu_percent
        self._memory_mb = memory_mb
        self._threads = threads
        self._primed = False

    @contextmanager
    def oneshot(self):
        yield self

    def cpu_percent(self, interval=None) -> float:  # noqa: ANN001
        if not self._primed:
            self._primed = True
            return 0.0
        return self._cpu_percent

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=self._memory_mb * 1024 * 1024)

    def num_threads(self) -> int:
        return self._threads


class _StubEngine:
    def __init__(self) -> None:
        self.process_id = 123
        self.effective_resources = {'max_threads': 4, 'max_memory_mb': 1024}
        self._alive_checks = 0

    def is_process_alive(self) -> bool:
        self._alive_checks += 1
        return self._alive_checks == 1


def test_monitor_engine_resources_normalizes_cpu_to_allocated_capacity(monkeypatch) -> None:
    process = _StubProcess(cpu_percent=200.0, memory_mb=256.0, threads=3)
    monkeypatch.setattr('modules.compute.monitor.psutil.Process', lambda pid: process)
    monkeypatch.setattr('modules.compute.monitor.psutil.cpu_count', lambda: 8)

    engine = _StubEngine()

    async def collect() -> list[dict[str, float | int | None]]:
        return [item async for item in monitor_engine_resources(cast(ComputeEngine, engine), interval=0)]

    snapshots = asyncio.run(collect())

    assert snapshots == [
        {
            'cpu_percent': 50.0,
            'memory_mb': 256.0,
            'memory_limit_mb': 1024,
            'active_threads': 3,
            'max_threads': 4,
        }
    ]
