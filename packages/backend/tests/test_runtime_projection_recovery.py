from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from backend_core import runtime_notifications
from backend_core.compute_worker_live import ComputeWorkerRegistry
from backend_core.domain.build_runs.live import BuildNotification, BuildNotificationHub
from backend_core.domain.compute.schemas import ComputeWorkersSnapshotMessage
from backend_core.namespace import get_namespace
from backend_core.persistence.locks.models import ResourceLock
from modules.compute import routes as compute_routes
from modules.locks import routes as lock_routes, watchers
from modules.locks.schemas import LockStatusResponse


@pytest.fixture
def projection_socket(monkeypatch) -> WebSocket:
    class Socket:
        headers = {'X-Namespace': 'alpha'}
        query_params: dict[str, str] = {}

        async def accept(self) -> None:
            return None

    async def wait_for_disconnect(_socket: WebSocket) -> None:
        await asyncio.Event().wait()

    def database(function, *args, **kwargs):
        return function(SimpleNamespace(), *args, **kwargs)

    monkeypatch.setattr(compute_routes, '_require_websocket_user', AsyncMock())
    monkeypatch.setattr(compute_routes, '_wait_for_websocket_disconnect', wait_for_disconnect)
    monkeypatch.setattr(compute_routes, 'safe_close_websocket', AsyncMock())
    monkeypatch.setattr(compute_routes, 'run_db', database)
    return cast(WebSocket, Socket())


@pytest.mark.asyncio
async def test_build_list_registers_before_snapshot_and_retains_recovery_version(monkeypatch, projection_socket) -> None:
    hub = BuildNotificationHub()
    monkeypatch.setattr(compute_routes, 'build_hub', hub)

    async def snapshot(_socket: WebSocket, namespace: str) -> None:
        await hub.recover_namespaces()
        assert hub.latest_namespace_sequence(namespace) == 1

    monkeypatch.setattr(compute_routes, '_send_build_list_snapshot', snapshot)
    monkeypatch.setattr(
        compute_routes, '_build_list_snapshot_message', lambda _session, _namespace: SimpleNamespace(model_dump=lambda **_kwargs: {'fresh': True})
    )
    sent = AsyncMock(return_value=False)
    monkeypatch.setattr(compute_routes, 'safe_send_json', sent)
    await asyncio.wait_for(compute_routes.build_list_stream(projection_socket), timeout=1)
    sent.assert_awaited_once_with(projection_socket, {'fresh': True})
    await hub.recover_namespaces()
    assert hub.latest_namespace_sequence('alpha') == 1


@pytest.mark.asyncio
async def test_build_detail_registers_before_snapshot_and_replays_notification_racing_read(monkeypatch, projection_socket) -> None:
    hub = BuildNotificationHub()
    monkeypatch.setattr(compute_routes, 'build_hub', hub)
    replayed: list[int] = []

    def snapshot(_session, build_id: str):
        assert ('alpha', build_id) in hub.active_builds()
        asyncio.run(hub.publish(BuildNotification(namespace='alpha', build_id=build_id, latest_sequence=5)))
        return SimpleNamespace(build=SimpleNamespace(namespace='alpha'), last_sequence=0)

    async def replay(_socket: WebSocket, _build_id: str, sequence: int) -> int:
        replayed.append(sequence)
        raise WebSocketDisconnect

    monkeypatch.setattr(compute_routes, '_build_snapshot_message', snapshot)
    monkeypatch.setattr(compute_routes, '_replay_build_events', replay)
    monkeypatch.setattr(compute_routes, 'safe_send_json', AsyncMock(return_value=True))
    await asyncio.wait_for(compute_routes.build_stream(projection_socket, 'build'), timeout=1)
    assert replayed == [0]
    assert hub.active_builds() == []


@pytest.mark.asyncio
async def test_engine_stream_registers_before_snapshot_and_refreshes_on_racing_recovery(monkeypatch, projection_socket) -> None:
    registry = ComputeWorkerRegistry()
    monkeypatch.setattr(compute_routes, 'compute_worker_registry', registry)
    snapshots = 0

    async def snapshot(_socket: WebSocket) -> str:
        nonlocal snapshots
        snapshots += 1
        if snapshots > 1:
            raise WebSocketDisconnect
        before = await registry.current_version('alpha')
        assert before is not None
        await registry.recover_active()
        return before

    monkeypatch.setattr(compute_routes, '_send_compute_worker_snapshot', snapshot)
    await asyncio.wait_for(compute_routes.compute_workers_stream(projection_socket), timeout=1)
    assert snapshots == 2
    version = await registry.current_version('alpha')
    await registry.recover_active()
    assert await registry.current_version('alpha') == version


@pytest.mark.asyncio
async def test_build_recovery_batches_only_active_exact_ids_and_retains_a_newer_notification(monkeypatch) -> None:
    hub = BuildNotificationHub()
    monkeypatch.setattr(runtime_notifications, 'build_hub', hub)
    for index in range(260):
        hub.subscribe_build('alpha', str(index))
        hub.subscribe_build('alpha', str(index))
    hub.subscribe_build('beta', 'other')
    hub.subscribe_build('idle', 'unsubscribed')
    hub.unsubscribe_build('idle', 'unsubscribed')
    baseline = hub.subscribe_namespace('alpha')
    hub.subscribe_namespace('empty-active-namespace')
    batches: list[tuple[str, tuple[str, ...]]] = []
    loop_thread = threading.get_ident()

    def read(namespace: str, ids: list[str]) -> dict[str, int]:
        assert threading.get_ident() != loop_thread
        batches.append((namespace, tuple(ids)))
        if '0' in ids:
            asyncio.run(hub.publish(BuildNotification(namespace='alpha', build_id='0', latest_sequence=99)))
        return dict.fromkeys(ids, 8)

    monkeypatch.setattr(runtime_notifications, '_read_build_sequences', read)
    await runtime_notifications.refresh_build_projections()

    assert [(namespace, len(ids)) for namespace, ids in batches] == [('alpha', 128), ('alpha', 128), ('alpha', 4), ('beta', 1)]
    assert await asyncio.wait_for(hub.wait_for_build('0', 8), timeout=1) == BuildNotification(namespace='alpha', build_id='0', latest_sequence=99)
    assert (await asyncio.wait_for(hub.wait_for_namespace('alpha', baseline), timeout=1)).namespace == 'alpha'
    assert hub.latest_namespace_sequence('empty-active-namespace') == 1
    assert hub.latest_namespace_sequence('idle') == 0
    hub.unsubscribe_build('beta', 'other')
    assert ('beta', 'other') not in hub.active_builds()
    hub.unsubscribe_build('alpha', '0')
    assert ('alpha', '0') in hub.active_builds()
    hub.unsubscribe_build('alpha', '0')
    assert ('alpha', '0') not in hub.active_builds()


@pytest.mark.asyncio
async def test_engine_recovery_during_initial_snapshot_retains_before_read_version_and_one_load_per_namespace() -> None:
    registry = ComputeWorkerRegistry()
    before = ComputeWorkersSnapshotMessage(compute_workers=[], total=0)
    after = ComputeWorkersSnapshotMessage(compute_workers=[], total=1)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def load() -> ComputeWorkersSnapshotMessage:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            return before
        return after

    async def idle_load() -> ComputeWorkersSnapshotMessage:
        return before

    await registry.load_snapshot('inactive', idle_load)
    for _ in range(50):
        await registry.subscribe('active')
    first = asyncio.create_task(registry.load_serialized_snapshot('active', load))
    await started.wait()
    await registry.recover_active()
    release.set()
    old_version, _snapshot = await first
    current = await asyncio.wait_for(registry.wait_for_namespace('active', str(old_version)), timeout=1)
    assert int(current) > old_version
    results = await asyncio.gather(*(registry.load_snapshot('active', load) for _ in range(50)))
    assert results == [after] * 50 and calls == 2
    assert await registry.load_snapshot('inactive', idle_load) is before
    assert await registry.current_version('inactive') is None
    for _ in range(50):
        await registry.unsubscribe('active')
    await registry.recover_active()
    assert await registry.current_version('active') == current
    await registry.clear()


@pytest.mark.asyncio
async def test_lock_recovery_batches_active_keys_and_rejects_snapshot_older_than_a_publication(monkeypatch) -> None:
    registry = watchers.LockWatcherRegistry()
    monkeypatch.setattr(watchers, 'registry', registry)
    socket = cast(WebSocket, object())
    for index in range(260):
        await registry.add(socket, 'alpha', 'analysis', str(index))
    await registry.add(socket, 'idle', 'analysis', 'unsubscribed')
    await registry.discard(socket, 'idle', 'analysis', 'unsubscribed')
    batches: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    started = threading.Event()
    release = threading.Event()
    sent: list[dict[str, object]] = []

    def read(namespace: str, keys: list[tuple[str, str]]) -> dict[tuple[str, str], LockStatusResponse]:
        batches.append((namespace, tuple(keys)))
        if ('analysis', '0') in keys:
            started.set()
            if not release.wait(2):
                raise TimeoutError('Test did not release lock recovery read')
        return {}

    async def send(_socket: WebSocket, serialized: str) -> bool:
        sent.append(json.loads(serialized))
        return True

    monkeypatch.setattr(runtime_notifications, '_read_lock_statuses', read)
    monkeypatch.setattr(watchers, 'safe_send_serialized_json', send)
    task = asyncio.create_task(runtime_notifications.refresh_lock_projections())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await watchers.notify_watchers('alpha', 'analysis', '0', {'resource_id': '0', 'lock': {'owner_id': 'new'}})
        release.set()
        await task
        assert [len(keys) for _namespace, keys in batches] == [128, 128, 4]
        assert all(namespace == 'alpha' for namespace, _keys in batches)
        assert [payload for payload in sent if payload['resource_id'] == '0'] == [{'resource_id': '0', 'lock': {'owner_id': 'new'}}]
    finally:
        release.set()
        await registry.clear()


@pytest.mark.asyncio
async def test_old_lock_recovery_cannot_overwrite_a_new_subscription_for_the_same_key(monkeypatch) -> None:
    registry = watchers.LockWatcherRegistry()
    monkeypatch.setattr(watchers, 'registry', registry)
    socket = cast(WebSocket, object())
    await registry.add(socket, 'alpha', 'analysis', 'id')
    old = await registry.current_version('alpha', 'analysis', 'id')
    await registry.discard(socket, 'alpha', 'analysis', 'id')
    await registry.add(socket, 'alpha', 'analysis', 'id')
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(watchers, 'safe_send_serialized_json', sent)
    assert not await watchers.refresh_watchers('alpha', 'analysis', 'id', {'lock': None}, expected_version=old)
    sent.assert_not_awaited()
    await registry.clear()


@pytest.mark.asyncio
async def test_lock_initial_subscription_precedes_read_and_new_notification_wins(monkeypatch) -> None:
    registry = watchers.LockWatcherRegistry()
    monkeypatch.setattr(watchers, 'registry', registry)
    seen: list[dict[str, object]] = []
    now = datetime.now(UTC)
    fresh = LockStatusResponse(
        resource_type='analysis',
        resource_id='id',
        owner_id='fresh',
        lock_token='token',
        acquired_at=now,
        expires_at=now + timedelta(minutes=1),
        last_heartbeat=now,
        is_expired=False,
    )

    class Socket:
        headers: dict[str, str] = {}
        query_params: dict[str, str] = {}
        reads = 0

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict[str, str]:
            self.reads += 1
            if self.reads > 1:
                raise WebSocketDisconnect
            return {'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'id'}

    async def lookup(resource_type: str, resource_id: str) -> tuple[None, bool]:
        assert len(await registry.active_keys()) == 1
        await watchers.notify_watchers(get_namespace(), resource_type, resource_id, lock_routes._status_message(resource_type, resource_id, fresh))
        return None, False

    async def send(_socket: WebSocket, serialized: str) -> bool:
        seen.append(json.loads(serialized))
        return True

    monkeypatch.setattr(lock_routes, '_require_websocket_user', AsyncMock(return_value='owner'))
    monkeypatch.setattr(lock_routes, '_lookup_lock_status', lookup)
    monkeypatch.setattr(lock_routes, 'safe_send_json', AsyncMock(return_value=True))
    monkeypatch.setattr(lock_routes, 'safe_close_websocket', AsyncMock())
    monkeypatch.setattr(watchers, 'safe_send_serialized_json', send)
    await lock_routes.lock_websocket(cast(WebSocket, Socket()))
    assert len(seen) == 1 and cast(dict[str, object], seen[0]['lock'])['owner_id'] == 'fresh'
    assert await registry.active_keys() == []


@pytest.mark.asyncio
async def test_recovery_read_racing_watch_heartbeat_does_not_drop_committed_mutation_or_cross_process_wake(monkeypatch) -> None:
    registry = watchers.LockWatcherRegistry()
    monkeypatch.setattr(watchers, 'registry', registry)
    now = datetime.now(UTC)
    original = LockStatusResponse(
        resource_type='analysis',
        resource_id='id',
        owner_id='owner',
        lock_token='token',
        acquired_at=now,
        expires_at=now + timedelta(seconds=30),
        last_heartbeat=now,
        is_expired=False,
    )
    committed = original.model_copy(update={'expires_at': now + timedelta(seconds=90), 'last_heartbeat': now + timedelta(seconds=1)})
    heartbeat_started = asyncio.Event()
    commit = asyncio.Event()
    disconnect = asyncio.Event()
    published = threading.Event()
    local: list[dict[str, object]] = []
    remote: list[dict[str, object]] = []

    class Socket:
        headers = {'X-Namespace': 'alpha'}
        query_params: dict[str, str] = {}
        reads = 0

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict[str, str]:
            self.reads += 1
            if self.reads == 1:
                return {'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'id', 'lock_token': 'token'}
            await disconnect.wait()
            raise WebSocketDisconnect

    async def heartbeat(*_args) -> LockStatusResponse:
        heartbeat_started.set()
        await commit.wait()
        return committed

    def read(namespace: str, keys: list[tuple[str, str]]) -> dict[tuple[str, str], LockStatusResponse]:
        assert namespace == 'alpha' and keys == [('analysis', 'id')]
        return {('analysis', 'id'): original}

    async def send(_socket: WebSocket, serialized: str) -> bool:
        local.append(json.loads(serialized))
        return True

    def broadcast(namespace: str, resource_type: str, resource_id: str, payload) -> None:
        assert namespace == 'alpha' and (resource_type, resource_id) == ('analysis', 'id')
        remote.append(payload.model_dump(mode='json'))
        published.set()

    monkeypatch.setattr(lock_routes, '_require_websocket_user', AsyncMock(return_value='owner'))
    monkeypatch.setattr(lock_routes, '_heartbeat_lock', heartbeat)
    monkeypatch.setattr(lock_routes, '_release_lock', AsyncMock(return_value=False))
    monkeypatch.setattr(lock_routes, 'safe_send_json', AsyncMock(return_value=True))
    monkeypatch.setattr(lock_routes, 'safe_close_websocket', AsyncMock())
    monkeypatch.setattr(runtime_notifications, '_read_lock_statuses', read)
    monkeypatch.setattr(watchers, 'safe_send_serialized_json', send)
    monkeypatch.setattr(lock_routes.runtime_ipc, 'notify_api_lock', broadcast)
    task = asyncio.create_task(lock_routes.lock_websocket(cast(WebSocket, Socket())))
    try:
        await asyncio.wait_for(heartbeat_started.wait(), timeout=1)
        version = await registry.current_version('alpha', 'analysis', 'id')
        await runtime_notifications.refresh_lock_projections()
        assert await registry.current_version('alpha', 'analysis', 'id') > version
        commit.set()
        assert await asyncio.to_thread(published.wait, 1)
        expected = lock_routes._status_message('analysis', 'id', committed).model_dump(mode='json')
        assert local[-1] == expected and remote == [expected]
    finally:
        commit.set()
        disconnect.set()
        await asyncio.wait_for(task, timeout=1)
    assert await registry.active_keys() == []


@pytest.mark.asyncio
async def test_failed_lock_watch_switch_retains_previous_ownership_for_disconnect_cleanup(monkeypatch) -> None:
    registry = watchers.LockWatcherRegistry()
    monkeypatch.setattr(watchers, 'registry', registry)
    now = datetime.now(UTC)
    lock = LockStatusResponse(
        resource_type='analysis',
        resource_id='old',
        owner_id='owner',
        lock_token='old-token',
        acquired_at=now,
        expires_at=now + timedelta(minutes=1),
        last_heartbeat=now,
        is_expired=False,
    )

    class Socket:
        headers: dict[str, str] = {}
        query_params: dict[str, str] = {}
        messages = iter(
            [
                {'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'old', 'lock_token': 'old-token'},
                {'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'new', 'lock_token': 'invalid'},
            ]
        )

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict[str, str]:
            message = next(self.messages, None)
            if message is None:
                assert [(key[1], key[2]) for key, _version in await registry.active_keys()] == [('analysis', 'old')]
                raise WebSocketDisconnect
            return message

    async def heartbeat(_type, resource_id, *_args):
        if resource_id == 'new':
            raise HTTPException(status_code=409, detail='Invalid token')
        return lock

    release = AsyncMock(return_value=True)
    monkeypatch.setattr(lock_routes, '_require_websocket_user', AsyncMock(return_value='owner'))
    monkeypatch.setattr(lock_routes, '_heartbeat_lock', heartbeat)
    monkeypatch.setattr(lock_routes, '_release_lock', release)
    monkeypatch.setattr(lock_routes, '_notify_watchers', AsyncMock())
    monkeypatch.setattr(lock_routes, 'safe_send_json', AsyncMock(return_value=True))
    monkeypatch.setattr(lock_routes, 'safe_close_websocket', AsyncMock())
    await lock_routes.lock_websocket(cast(WebSocket, Socket()))
    release.assert_awaited_once_with('analysis', 'old', 'owner', 'old-token')
    assert await registry.active_keys() == []


@pytest.mark.asyncio
async def test_recovery_db_session_creation_use_and_close_stay_in_worker_thread(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    operations: list[tuple[str, int, str]] = []
    now = datetime.now(UTC)
    row = ResourceLock(resource_type='analysis', resource_id='id', owner_id='owner', expires_at=now + timedelta(minutes=1))

    class Result:
        def __init__(self, rows) -> None:
            self.rows = rows

        def all(self):
            return self.rows

    class Database:
        def __init__(self) -> None:
            operations.append(('create', threading.get_ident(), get_namespace()))

        def exec(self, statement):
            operations.append(('use', threading.get_ident(), get_namespace()))
            assert 'WHERE' in str(statement) and ' IN ' in str(statement)
            return Result([('build', 9)] if 'build_runs' in str(statement) else [row])

        def close(self) -> None:
            operations.append(('close', threading.get_ident(), get_namespace()))

    def run(function):
        session = Database()
        try:
            return function(cast(Session, session))
        finally:
            session.close()

    monkeypatch.setattr(runtime_notifications, 'run_db', run)
    assert await asyncio.to_thread(runtime_notifications._read_build_sequences, 'alpha', ['build']) == {'build': 8}
    locks = await asyncio.to_thread(runtime_notifications._read_lock_statuses, 'beta', [('analysis', 'id')])
    assert locks['analysis', 'id'].owner_id == 'owner'
    assert [operation for operation, _thread, _namespace in operations] == ['create', 'use', 'close'] * 2
    assert all(thread != loop_thread for _operation, thread, _namespace in operations)
    assert len({thread for _operation, thread, _namespace in operations[:3]}) == 1
    assert len({thread for _operation, thread, _namespace in operations[3:]}) == 1
    assert [namespace for _operation, _thread, namespace in operations] == ['alpha'] * 3 + ['beta'] * 3


@pytest.mark.asyncio
async def test_main_api_listener_recovery_wiring_has_mandatory_projection_callbacks(monkeypatch) -> None:
    import main

    recover = AsyncMock()
    monkeypatch.setattr(main, 'recover_runtime_notifications', recover)
    await main._recover_api_notifications()
    recover.assert_awaited_once_with(
        refresh_builds=main.refresh_build_projections, refresh_engines=main.compute_worker_registry.recover_active, refresh_locks=main.refresh_lock_projections
    )
