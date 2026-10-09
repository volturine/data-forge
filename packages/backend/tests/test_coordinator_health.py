from __future__ import annotations

import asyncio
import os
import socket
import tempfile
from pathlib import Path

import pytest

from backend_core import coordinator_health as health_module
from backend_core.coordinator_health import CoordinatorHealth


@pytest.fixture
def socket_directory(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='df-runtime-health-', dir='/tmp') as directory:
        monkeypatch.setattr(health_module, '_socket_path', lambda pid: Path(directory) / f'{pid}.sock')
        yield


async def _probe(pid: int, *, grpc_generation: int) -> bool:
    return await asyncio.to_thread(health_module.probe, pid, grpc_generation=lambda: grpc_generation)


async def test_standby_coordinator_is_healthy_without_grpc(socket_directory) -> None:
    health = CoordinatorHealth()
    async with health.serve():
        assert not await _probe(os.getpid(), grpc_generation=0)  # still starting
        health.standby()
        assert await _probe(os.getpid(), grpc_generation=0)
        assert not await _probe(os.getpid() + 1, grpc_generation=0)


async def test_active_coordinator_must_answer_grpc_with_its_generation(socket_directory) -> None:
    health = CoordinatorHealth()
    async with health.serve():
        health.active(4)
        assert await _probe(os.getpid(), grpc_generation=4)
        assert not await _probe(os.getpid(), grpc_generation=0)
        assert not await _probe(os.getpid(), grpc_generation=3)
        health.standby()
        assert await _probe(os.getpid(), grpc_generation=0)
    assert not await _probe(os.getpid(), grpc_generation=4)


async def test_stopped_coordinator_is_unhealthy(socket_directory) -> None:
    health = CoordinatorHealth()
    async with health.serve():
        health.active(1)
        health.stopped()
        assert health.snapshot() == {'pid': os.getpid(), 'state': 'stopped', 'generation': None, 'healthy': False}
        assert not await _probe(os.getpid(), grpc_generation=1)


def test_probe_rejects_stale_socket_from_previous_process(socket_directory) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as old_process:
        old_process.bind(str(health_module._socket_path(os.getpid())))
    assert not health_module.probe(os.getpid(), grpc_generation=lambda: 1)
