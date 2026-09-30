from __future__ import annotations

import asyncio
import os
import socket
import tempfile
from pathlib import Path

import pytest

from runtime import dispatcher_health as health_module
from runtime.dispatcher_health import DispatcherHealth

_LANES = ("compute-active", "compute-shutdown", "build", "datasource-delete")


@pytest.fixture
def socket_directory(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="df-health-", dir="/tmp") as directory:
        monkeypatch.setattr(health_module, "_socket_path", lambda pid: Path(directory) / f"{pid}.sock")
        yield


@pytest.mark.asyncio
async def test_probe_requires_own_registration_and_dispatch_progress(socket_directory) -> None:
    health = DispatcherHealth("worker:new", lanes=("dispatch",), max_age_seconds=15)
    async with health.serve():
        assert not await asyncio.to_thread(health_module.probe, os.getpid())
        health.registered()
        assert not await asyncio.to_thread(health_module.probe, os.getpid())
        health.progress("dispatch")
        assert await asyncio.to_thread(health_module.probe, os.getpid())
        assert not await asyncio.to_thread(health_module.probe, os.getpid() + 1)
        health.stopped()
        assert not await asyncio.to_thread(health_module.probe, os.getpid())


@pytest.mark.asyncio
async def test_probe_rejects_hung_dispatch_even_with_live_server(socket_directory) -> None:
    now = 100.0
    health = DispatcherHealth("worker:current", lanes=("dispatch", "cleanup"), max_age_seconds=15, clock=lambda: now)
    health.registered()
    health.progress("dispatch")
    health.progress("cleanup")
    async with health.serve():
        assert await asyncio.to_thread(health_module.probe, os.getpid())
        now += 16
        health.progress("cleanup")
        assert not await asyncio.to_thread(health_module.probe, os.getpid())


def test_probe_rejects_stale_socket_from_previous_process(socket_directory) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as old_process:
        old_process.bind(str(health_module._socket_path(os.getpid())))
    assert not health_module.probe(os.getpid())


@pytest.mark.asyncio
async def test_replacement_instance_does_not_inherit_registration(socket_directory) -> None:
    old = DispatcherHealth("worker:old", lanes=("dispatch",), max_age_seconds=15)
    async with old.serve():
        old.registered()
        old.progress("dispatch")
        assert await asyncio.to_thread(health_module.probe, os.getpid())
    replacement = DispatcherHealth("worker:new", lanes=("dispatch",), max_age_seconds=15)
    async with replacement.serve():
        assert not await asyncio.to_thread(health_module.probe, os.getpid())


def test_registration_loss_requires_reregistration_and_fresh_progress() -> None:
    health = DispatcherHealth("current", lanes=("dispatch",), max_age_seconds=15)
    health.registered()
    health.progress("dispatch")
    assert health.snapshot()["healthy"] is True
    health.registration_changed(False)
    health.progress("dispatch")
    assert health.snapshot()["healthy"] is False
    health.registered()
    assert health.snapshot()["healthy"] is True
    health.stopped()
    health.registered()
    health.progress("dispatch")
    assert health.snapshot()["registered"] is False
    assert health.snapshot()["healthy"] is False


@pytest.mark.parametrize("hung_lane", _LANES)
def test_each_dispatcher_lane_must_make_progress(hung_lane: str) -> None:
    now = 100.0
    health = DispatcherHealth("worker:current", lanes=_LANES, max_age_seconds=15, clock=lambda: now)
    health.registered()
    for lane in _LANES:
        health.progress(lane)
    assert health.snapshot()["healthy"] is True
    now += 16
    for lane in _LANES:
        if lane != hung_lane:
            health.progress(lane)
    assert health.snapshot()["healthy"] is False
    health.progress(hung_lane)
    assert health.snapshot()["healthy"] is True
