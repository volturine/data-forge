import asyncio
import json
import os
import threading
from collections.abc import AsyncGenerator, Iterable
from types import SimpleNamespace
from typing import cast

import pytest
from psycopg import Notify
from sqlalchemy import Engine
from sqlmodel import Session as SqlModelSession


@pytest.mark.asyncio
async def test_lock_notification_fans_out_to_watchers_from_another_api_process(monkeypatch) -> None:
    from backend_core import runtime_notifications

    received = []

    async def notify_watchers(namespace, resource_type, resource_id, payload) -> None:
        received.append((namespace, resource_type, resource_id, payload))

    monkeypatch.setattr(runtime_notifications.lock_watchers, 'notify_watchers', notify_watchers)
    status = {'type': 'status', 'resource_type': 'analysis', 'resource_id': 'analysis-1', 'lock': None}

    await runtime_notifications.handle_runtime_payload(
        {
            'kind': 'lock',
            'namespace': 'default',
            'resource_type': 'analysis',
            'resource_id': 'analysis-1',
            'status': status,
            'source_pid': os.getpid() + 1,
        }
    )

    assert received == [('default', 'analysis', 'analysis-1', status)]


@pytest.mark.asyncio
async def test_lock_notification_does_not_echo_to_the_publishing_api_process(monkeypatch) -> None:
    from backend_core import runtime_notifications

    async def fail_notify(*args) -> None:
        raise AssertionError('same-process lock notification should be handled locally')

    monkeypatch.setattr(runtime_notifications.lock_watchers, 'notify_watchers', fail_notify)

    await runtime_notifications.handle_runtime_payload(
        {
            'kind': 'lock',
            'namespace': 'default',
            'resource_type': 'analysis',
            'resource_id': 'analysis-1',
            'status': {'lock': None},
            'source_pid': os.getpid(),
        }
    )


def test_notify_api_lock_includes_process_identity(monkeypatch) -> None:
    from backend_core import runtime_ipc

    sent = []
    monkeypatch.setattr(
        runtime_ipc,
        '_send_api_message',
        lambda payload, *, listener: sent.append((payload, listener)),
    )
    status: dict[str, object] = {'type': 'status', 'lock': None}

    runtime_ipc.notify_api_lock('default', 'analysis', 'analysis-1', status)

    assert sent == [
        (
            {
                'kind': 'lock',
                'namespace': 'default',
                'resource_type': 'analysis',
                'resource_id': 'analysis-1',
                'status': status,
                'source_pid': os.getpid(),
            },
            runtime_ipc.RuntimeListenerKind.API,
        )
    ]


def test_notify_api_lock_converts_pydantic_payload_to_json_value(monkeypatch) -> None:
    from backend_core import runtime_ipc
    from modules.locks.schemas import LockWebsocketStatusMessage

    sent = []
    monkeypatch.setattr(
        runtime_ipc,
        '_send_api_message',
        lambda payload, *, listener: sent.append((payload, listener)),
    )
    status = LockWebsocketStatusMessage(
        resource_type='analysis',
        resource_id='analysis-1',
        lock=None,
    )

    runtime_ipc.notify_api_lock('default', 'analysis', 'analysis-1', status)

    assert sent == [
        (
            {
                'kind': 'lock',
                'namespace': 'default',
                'resource_type': 'analysis',
                'resource_id': 'analysis-1',
                'status': {
                    'type': 'status',
                    'resource_type': 'analysis',
                    'resource_id': 'analysis-1',
                    'lock': None,
                },
                'source_pid': os.getpid(),
            },
            runtime_ipc.RuntimeListenerKind.API,
        )
    ]


def test_compute_wakes_use_transactional_postgres_notifications() -> None:
    from backend_core import runtime_ipc

    class Session:
        def __init__(self, dialect: str) -> None:
            self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
            self.statements: list[tuple[str, dict[str, str]]] = []

        def get_bind(self) -> Engine:
            return self.bind  # type: ignore[return-value]

        def execute(self, statement, parameters) -> None:
            self.statements.append((str(statement), parameters))

    session = Session('postgresql')
    sqlmodel_session = cast(SqlModelSession, session)
    runtime_ipc.notify_compute_request_on_commit(sqlmodel_session, request_id='request-1', namespace='tenant-a', compute_kind=14)
    runtime_ipc.notify_compute_response_on_commit(sqlmodel_session, request_id='request-1', namespace='tenant-a')

    assert len(session.statements) == 2
    for statement, parameters in session.statements:
        assert 'pg_notify' in statement
        assert parameters['channel'] == 'runtime_events'
    assert json.loads(session.statements[0][1]['payload']) == {
        'kind': 'compute_request',
        'request_id': 'request-1',
        'namespace': 'tenant-a',
        'compute_kind': 14,
    }
    assert json.loads(session.statements[1][1]['payload']) == {
        'kind': 'compute_response',
        'request_id': 'request-1',
        'namespace': 'tenant-a',
    }


def test_compute_wakes_skip_postgres_notification_for_sqlite() -> None:
    from backend_core import runtime_ipc

    class Session:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))

        def execute(self, *_args, **_kwargs) -> None:
            raise AssertionError('SQLite should not execute PostgreSQL notification SQL')

    runtime_ipc.notify_compute_request_on_commit(Session(), request_id='request-1', namespace='tenant-a', compute_kind=14)  # type: ignore[arg-type]
    runtime_ipc.notify_compute_response_on_commit(Session(), request_id='request-1', namespace='tenant-a')  # type: ignore[arg-type]


class _NotificationConnection:
    def __init__(self, payloads: Iterable[str] = (), *, fail_receive: bool = False, end_receive: bool = False) -> None:
        self.payloads = payloads
        self.fail_receive = fail_receive
        self.end_receive = end_receive
        self.closed = False
        self.emitted = 0
        self.operation_threads: list[int] = []
        self.entered = asyncio.Event()
        self.generator_closed = asyncio.Event()
        self.listen_started = asyncio.Event()
        self.listen_ready = asyncio.Event()
        self.listen_ready.set()

    async def execute(self, query: str) -> None:
        assert query == 'LISTEN runtime_events'
        self.operation_threads.append(threading.get_ident())
        self.listen_started.set()
        await self.listen_ready.wait()

    async def notifies(self) -> AsyncGenerator[Notify]:
        from backend_core import runtime_ipc

        self.operation_threads.append(threading.get_ident())
        self.entered.set()
        try:
            if self.fail_receive:
                raise runtime_ipc.psycopg.OperationalError('connection lost')
            for payload in self.payloads:
                self.emitted += 1
                yield Notify('runtime_events', payload, 1)
            if not self.end_receive:
                await asyncio.Event().wait()
        finally:
            self.generator_closed.set()

    async def close(self) -> None:
        self.operation_threads.append(threading.get_ident())
        self.closed = True


def _install_connections(monkeypatch: pytest.MonkeyPatch, *connections: _NotificationConnection) -> None:
    from backend_core import runtime_ipc

    pending = iter(connections)

    async def connect(conninfo: str, *, autocommit: bool, connect_timeout: int) -> _NotificationConnection:
        assert conninfo
        assert autocommit and connect_timeout == 5
        return next(pending)

    monkeypatch.setattr(runtime_ipc.psycopg.AsyncConnection, 'connect', connect)


async def _recover_nothing() -> None:
    return None


@pytest.mark.asyncio
async def test_runtime_listener_owns_async_connection_on_the_event_loop(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection()
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()
    await runtime_ipc.stop_api_server(listener)

    assert connection.closed
    assert connection.operation_threads == [threading.get_ident(), threading.get_ident()]


@pytest.mark.parametrize('server_mode', ['closes', 'raises', 'missing'])
@pytest.mark.asyncio
async def test_stopping_runtime_listener_resets_sync_notify_connection(monkeypatch, server_mode: str) -> None:
    from backend_core import runtime_ipc

    class CachedConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    class Listener:
        async def close(self) -> None:
            if server_mode == 'raises':
                raise RuntimeError('listener close failed')

    connection = CachedConnection()
    monkeypatch.setattr(runtime_ipc, '_notify_connection_state', (connection, 'postgresql://test'))
    listener = None if server_mode == 'missing' else cast(runtime_ipc.RuntimeNotificationListener, Listener())

    if server_mode == 'raises':
        with pytest.raises(RuntimeError, match='listener close failed'):
            await runtime_ipc.stop_api_server(listener)
    else:
        await runtime_ipc.stop_api_server(listener)

    assert connection.closed
    assert runtime_ipc._notify_connection_state is None


def test_configuring_runtime_database_url_resets_sync_notify_connection(monkeypatch) -> None:
    from backend_core import runtime_ipc

    class CachedConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    connection = CachedConnection()
    monkeypatch.setattr(runtime_ipc, '_notify_connection_state', (connection, 'postgresql://old'))
    monkeypatch.setattr(runtime_ipc, '_database_url_provider', runtime_ipc._database_url_provider)
    runtime_ipc.configure_database_url_provider(lambda: 'postgresql://new')

    assert connection.closed
    assert runtime_ipc._notify_connection_state is None
    assert runtime_ipc._psycopg_conninfo() == 'postgresql://new'


@pytest.mark.asyncio
async def test_runtime_listener_cancelled_readiness_closes_connection(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection()
    connection.listen_ready.clear()
    _install_connections(monkeypatch, connection)
    startup = asyncio.create_task(runtime_ipc.start_api_server())
    await asyncio.wait_for(connection.listen_started.wait(), timeout=1)
    assert not startup.done()
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert connection.closed


@pytest.mark.asyncio
async def test_runtime_listener_reconnect_requests_recovery_without_a_new_notification(monkeypatch) -> None:
    from backend_core import runtime_ipc

    first = _NotificationConnection(fail_receive=True)
    second = _NotificationConnection()
    _install_connections(monkeypatch, first, second)
    listener = await runtime_ipc.start_api_server()
    stop = asyncio.Event()
    recovered = asyncio.Event()

    async def handle(_payload: dict[str, object]) -> None:
        pytest.fail('A reconnect must recover even when no further NOTIFY arrives')

    async def recover() -> None:
        if second.entered.is_set():
            recovered.set()

    task = asyncio.create_task(runtime_ipc.serve_api_notifications(listener, stop, handle, recover=recover))
    try:
        await asyncio.wait_for(recovered.wait(), timeout=2)
        assert first.closed and first.generator_closed.is_set()
    finally:
        stop.set()
        await task
        await listener.close()
    assert second.closed and second.generator_closed.is_set()


@pytest.mark.asyncio
async def test_runtime_listener_reconnects_after_normal_notification_stream_end(monkeypatch) -> None:
    from backend_core import runtime_ipc

    first = _NotificationConnection(end_receive=True)
    second = _NotificationConnection([json.dumps({'kind': 'live'})])
    _install_connections(monkeypatch, first, second)
    listener = await runtime_ipc.start_api_server()
    stop = asyncio.Event()
    recovered = asyncio.Event()
    handled = asyncio.Event()
    recoveries = 0
    received: list[dict[str, object]] = []

    async def handle(payload: dict[str, object]) -> None:
        received.append(payload)
        handled.set()

    async def recover() -> None:
        nonlocal recoveries
        if second.entered.is_set():
            recoveries += 1
            recovered.set()

    task = asyncio.create_task(runtime_ipc.serve_api_notifications(listener, stop, handle, recover=recover))
    try:
        await asyncio.wait_for(asyncio.gather(recovered.wait(), handled.wait()), timeout=2)
        assert first.closed and first.generator_closed.is_set()
        assert received == [{'kind': 'live'}]
    finally:
        stop.set()
        await task
        await listener.close()
    assert second.closed and second.generator_closed.is_set()
    assert recoveries >= 1


@pytest.mark.asyncio
async def test_runtime_listener_burst_has_one_inflight_hint_and_no_threadsafe_callbacks(monkeypatch) -> None:
    from backend_core import runtime_ipc

    burst_size = 50_000
    connection = _NotificationConnection(json.dumps({'kind': 'compute_response', 'request_id': str(index)}) for index in range(burst_size))
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()
    loop = asyncio.get_running_loop()
    original_schedule = loop.call_soon_threadsafe
    scheduled = 0

    def schedule(callback, *args, context=None):
        nonlocal scheduled
        scheduled += 1
        return original_schedule(callback, *args, context=context)

    monkeypatch.setattr(loop, 'call_soon_threadsafe', schedule)
    stop = asyncio.Event()
    entered = asyncio.Event()
    release = asyncio.Event()
    received = 0
    maximum_inflight = 0

    async def handle(payload: dict[str, object]) -> None:
        nonlocal received, maximum_inflight
        assert payload['request_id'] == str(received)
        maximum_inflight = max(maximum_inflight, connection.emitted - received)
        entered.set()
        await release.wait()
        received += 1
        if received == burst_size:
            stop.set()

    tasks_before = asyncio.all_tasks()
    task = asyncio.create_task(runtime_ipc.serve_api_notifications(listener, stop, handle, recover=_recover_nothing))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        for _ in range(5):
            await asyncio.sleep(0)
        assert connection.emitted == 1
        assert len(asyncio.all_tasks() - tasks_before) == 4
        release.set()
        await asyncio.wait_for(task, timeout=5)
        assert received == burst_size and maximum_inflight == 1
        assert scheduled == 0
        assert connection.generator_closed.is_set()
    finally:
        await listener.close()


@pytest.mark.asyncio
async def test_runtime_listener_stop_cancels_slow_handler_and_closes_generator(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection(['{"kind":"lock"}'])
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()
    stop = asyncio.Event()
    entered = asyncio.Event()
    exited = asyncio.Event()

    async def handle(_payload: dict[str, object]) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    task = asyncio.create_task(runtime_ipc.serve_api_notifications(listener, stop, handle, recover=_recover_nothing))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert exited.is_set() and connection.generator_closed.is_set()
    finally:
        await listener.close()


@pytest.mark.asyncio
async def test_runtime_listener_close_joins_receive_and_recovery_tasks(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection()
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()
    recovering = asyncio.Event()
    recovered = asyncio.Event()

    async def handle(_payload: dict[str, object]) -> None:
        return None

    async def recover() -> None:
        recovering.set()
        try:
            await asyncio.Event().wait()
        finally:
            recovered.set()

    task = asyncio.create_task(runtime_ipc.serve_api_notifications(listener, asyncio.Event(), handle, recover=recover))
    await asyncio.wait_for(recovering.wait(), timeout=1)
    await asyncio.wait_for(listener.close(), timeout=1)
    assert task.cancelled()
    assert connection.closed and connection.generator_closed.is_set() and recovered.is_set()


@pytest.mark.asyncio
async def test_runtime_listener_coalesces_recovery_requests_during_a_slow_pass(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection()
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()
    started = asyncio.Event()
    release = asyncio.Event()
    stop = asyncio.Event()
    calls = 0

    async def handle(_payload: dict[str, object]) -> None:
        return None

    async def recover() -> None:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        if calls == 2:
            stop.set()

    task = asyncio.create_task(runtime_ipc.serve_api_notifications(listener, stop, handle, recover=recover))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        for _ in range(50_000):
            listener._recovery_requested.set()
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert calls == 2
    finally:
        await listener.close()


@pytest.mark.asyncio
async def test_runtime_listener_handler_failure_requests_recovery_and_keeps_receiving(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection(['{"kind":"failed"}', '{"kind":"next"}'])
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()
    failed = False
    recovered = asyncio.Event()
    stop = asyncio.Event()
    received: list[str] = []

    async def handle(payload: dict[str, object]) -> None:
        nonlocal failed
        if payload['kind'] == 'failed':
            failed = True
            raise ValueError('handler failed')
        await recovered.wait()
        received.append(str(payload['kind']))
        stop.set()

    async def recover() -> None:
        if failed:
            recovered.set()

    try:
        await asyncio.wait_for(runtime_ipc.serve_api_notifications(listener, stop, handle, recover=recover), timeout=1)
        assert received == ['next']
    finally:
        await listener.close()


@pytest.mark.asyncio
async def test_runtime_listener_initial_ready_connection_requests_recovery(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection()
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()
    stop = asyncio.Event()
    recovered = asyncio.Event()

    async def handle(_payload: dict[str, object]) -> None:
        pytest.fail('Initial recovery must not require a subsequent NOTIFY')

    async def recover() -> None:
        assert connection.entered.is_set()
        recovered.set()
        stop.set()

    try:
        await asyncio.wait_for(runtime_ipc.serve_api_notifications(listener, stop, handle, recover=recover), timeout=1)
        assert recovered.is_set()
    finally:
        await listener.close()


@pytest.mark.asyncio
async def test_runtime_listener_rejects_cross_loop_connection_use(monkeypatch) -> None:
    from backend_core import runtime_ipc

    connection = _NotificationConnection()
    _install_connections(monkeypatch, connection)
    listener = await runtime_ipc.start_api_server()

    def close_from_another_loop() -> None:
        asyncio.run(listener.close())

    try:
        with pytest.raises(RuntimeError, match='owning event loop'):
            await asyncio.to_thread(close_from_another_loop)
        assert not connection.closed
    finally:
        await listener.close()


@pytest.mark.asyncio
async def test_api_recovery_requests_all_durable_projection_lanes_even_if_one_fails(monkeypatch) -> None:
    from backend_core import runtime_notifications
    from modules.chat.store import chat_stream_recovery

    called: list[str] = []
    monkeypatch.setattr(runtime_notifications.response_recovery, 'request_poll', lambda: called.append('compute'))
    monkeypatch.setattr(chat_stream_recovery, 'wake', lambda: called.append('chat'))
    monkeypatch.setattr(runtime_notifications.OUTBOX_WAKE_HUB, 'publish', lambda payload: called.append('outbox'))

    async def builds() -> None:
        called.append('builds')
        raise ValueError('build database unavailable')

    async def engines() -> None:
        called.append('engines')

    async def locks() -> None:
        called.append('locks')

    with pytest.raises(ExceptionGroup, match='Runtime projection recovery failed'):
        await runtime_notifications.recover_runtime_notifications(refresh_builds=builds, refresh_engines=engines, refresh_locks=locks)
    assert called == ['compute', 'chat', 'outbox', 'builds', 'engines', 'locks']


@pytest.mark.asyncio
async def test_compute_response_notification_wakes_registered_waiters(monkeypatch) -> None:
    from backend_core import runtime_notifications
    from backend_core.compute_response_recovery import ComputeResponseRecovery
    from backend_core.domain.runtime.events import RuntimePayloadKind

    recovery = ComputeResponseRecovery()
    request_id = 'durable-request-1'
    await recovery.register(request_id, 'default')
    monkeypatch.setattr(runtime_notifications, 'response_recovery', recovery)
    previous_version = await recovery.wake_version(request_id)

    await runtime_notifications.handle_runtime_payload(
        {
            'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value,
            'request_id': request_id,
            'namespace': 'default',
        }
    )

    assert await recovery.wait_for_wake(request_id, previous_version) == previous_version + 1
    await recovery.unregister(request_id)
