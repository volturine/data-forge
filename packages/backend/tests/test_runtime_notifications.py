import asyncio
import json
import os
import threading
from types import SimpleNamespace
from typing import cast

import pytest
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


@pytest.mark.asyncio
async def test_runtime_listener_owns_sync_connection_on_dedicated_thread(monkeypatch) -> None:
    from backend_core import runtime_ipc

    class Connection:
        def __init__(self) -> None:
            self.closed = False
            self.operation_threads: list[int] = []
            self.finished = threading.Event()

        def execute(self, query: str) -> None:
            assert query == 'LISTEN runtime_events'
            self.operation_threads.append(threading.get_ident())

        def notifies(self, *, timeout: float, stop_after: int):
            del stop_after
            self.finished.wait(timeout)
            return []

        def close(self) -> None:
            self.closed = True
            self.operation_threads.append(threading.get_ident())
            self.finished.set()

    connection = Connection()
    connect_threads: list[int] = []
    loop_thread = threading.get_ident()

    def connect(*args, **kwargs) -> Connection:
        connect_threads.append(threading.get_ident())
        return connection

    monkeypatch.setattr(runtime_ipc, 'psycopg', SimpleNamespace(connect=connect))

    listener = await runtime_ipc.start_api_server()

    assert connect_threads and connect_threads[0] != loop_thread
    assert connection.operation_threads[0] != loop_thread
    await runtime_ipc.stop_api_server(listener)
    assert connection.closed
    assert connection.operation_threads[-1] == connect_threads[0]


@pytest.mark.asyncio
async def test_runtime_listener_reconnects_and_delivers_notifications(monkeypatch) -> None:
    from backend_core import runtime_ipc

    stop_event = asyncio.Event()
    received: list[dict[str, object]] = []
    loop_thread = threading.get_ident()
    operation_threads: list[int] = []

    class Connection:
        def __init__(self, *, fail_first_poll: bool = False) -> None:
            self.fail_first_poll = fail_first_poll
            self.emitted = False
            self.closed = False
            self.closed_event = threading.Event()

        def execute(self, query: str) -> None:
            del query
            operation_threads.append(threading.get_ident())

        def notifies(self, *, timeout: float, stop_after: int):
            del timeout, stop_after
            operation_threads.append(threading.get_ident())
            if self.fail_first_poll:
                self.fail_first_poll = False
                raise runtime_ipc.psycopg.OperationalError('connection lost')
            if not self.emitted:
                self.emitted = True
                return [SimpleNamespace(payload='{"kind":"reconnected"}')]
            self.closed_event.wait(timeout=0.01)
            return []

        def close(self) -> None:
            self.closed = True
            self.closed_event.set()
            operation_threads.append(threading.get_ident())

    connections = [Connection(fail_first_poll=True), Connection()]
    opened_connections: list[Connection] = []

    def connect(*args, **kwargs) -> Connection:
        del args, kwargs
        connection = connections[min(len(opened_connections), len(connections) - 1)]
        opened_connections.append(connection)
        return connection

    async def handle(payload: dict[str, object]) -> None:
        assert threading.get_ident() == loop_thread
        received.append(payload)
        stop_event.set()

    psycopg = runtime_ipc.psycopg
    monkeypatch.setattr(
        runtime_ipc,
        'psycopg',
        SimpleNamespace(connect=connect, OperationalError=psycopg.OperationalError),
    )
    listener = await runtime_ipc.start_api_server()

    await asyncio.wait_for(runtime_ipc.serve_api_notifications(listener, stop_event, handle), timeout=2)
    await runtime_ipc.stop_api_server(listener)

    assert len(opened_connections) == 2
    assert all(connection.closed for connection in opened_connections)
    assert operation_threads and all(thread_id != loop_thread for thread_id in operation_threads)
    assert received == [{'kind': 'reconnected'}]


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
