from __future__ import annotations

import asyncio

import pytest

import backend_core.compute_worker_live as engine_live
from backend_core.compute_worker_live import ComputeWorkerRegistry
from backend_core.domain.compute import schemas


@pytest.mark.asyncio
async def test_engine_snapshot_load_is_single_flight_and_versioned() -> None:
    registry = ComputeWorkerRegistry()
    snapshot = schemas.EngineListSnapshotMessage(engines=[], total=0)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def load() -> schemas.EngineListSnapshotMessage:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return snapshot

    tasks = [asyncio.create_task(registry.load_snapshot('tenant-a', load)) for _ in range(50)]
    await started.wait()
    await asyncio.sleep(0)
    assert calls == 1

    release.set()
    assert await asyncio.gather(*tasks) == [snapshot] * 50
    assert calls == 1

    await registry.publish_namespace('tenant-a')
    await registry.load_snapshot('tenant-a', load)
    assert calls == 2


@pytest.mark.asyncio
async def test_serialized_engine_snapshot_is_shared_per_version(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ComputeWorkerRegistry()
    snapshot = schemas.EngineListSnapshotMessage(engines=[], total=0)
    loads = 0
    serializations = 0

    async def load() -> schemas.EngineListSnapshotMessage:
        nonlocal loads
        loads += 1
        await asyncio.sleep(0)
        return snapshot

    async def serialize(payload: schemas.EngineListSnapshotMessage) -> str:
        nonlocal serializations
        serializations += 1
        await asyncio.sleep(0)
        return f'engine-snapshot:{payload.total}'

    monkeypatch.setattr(engine_live, 'serialize_json', serialize)

    results = await asyncio.gather(*(registry.load_serialized_snapshot('tenant-a', load) for _ in range(50)))
    assert results == [(0, 'engine-snapshot:0')] * 50
    assert loads == 1
    assert serializations == 1

    await registry.publish_namespace('tenant-a')
    assert await registry.load_serialized_snapshot('tenant-a', load) == (1, 'engine-snapshot:0')
    assert loads == 2
    assert serializations == 2


@pytest.mark.asyncio
async def test_stale_engine_snapshot_load_does_not_replace_new_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ComputeWorkerRegistry()
    stale_snapshot = schemas.EngineListSnapshotMessage(engines=[], total=0)
    current_snapshot = schemas.EngineListSnapshotMessage(engines=[], total=1)
    stale_started = asyncio.Event()
    release_stale = asyncio.Event()
    loads = 0

    async def load() -> schemas.EngineListSnapshotMessage:
        nonlocal loads
        loads += 1
        if loads == 1:
            stale_started.set()
            await release_stale.wait()
            return stale_snapshot
        return current_snapshot

    async def serialize(payload: schemas.EngineListSnapshotMessage) -> str:
        return f'engine-snapshot:{payload.total}'

    monkeypatch.setattr(engine_live, 'serialize_json', serialize)

    stale_result = asyncio.create_task(registry.load_serialized_snapshot('tenant-a', load))
    await stale_started.wait()
    await registry.publish_namespace('tenant-a')

    assert await registry.load_serialized_snapshot('tenant-a', load) == (1, 'engine-snapshot:1')
    release_stale.set()
    assert await stale_result == (0, 'engine-snapshot:0')
    assert await registry.load_serialized_snapshot('tenant-a', load) == (1, 'engine-snapshot:1')
    assert loads == 2
