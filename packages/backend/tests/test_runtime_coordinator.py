from __future__ import annotations

import asyncio
from typing import Any, cast

import grpc
import pytest

import runtime_coordinator
from backend_grpc import server as grpc_server
from dataforge_protocol import common_pb2, runtime_coordinator_pb2


class _Result:
    def __init__(self, value: object | tuple[object, ...]) -> None:
        self._value = value

    def fetchone(self) -> tuple[object, ...]:
        return self._value if isinstance(self._value, tuple) else (self._value,)


class _Connection:
    def __init__(self, *, acquired: bool) -> None:
        self.acquired = acquired
        self.closed = False
        self.statements: list[tuple[str, tuple[object, ...] | None]] = []
        self.generation = 0

    def execute(self, statement: str, params: tuple[object, ...] | None = None) -> _Result:
        self.statements.append((statement, params))
        if 'pg_try_advisory_lock' in statement:
            return _Result(self.acquired)
        if 'UPDATE public.runtime_coordinator_state' in statement:
            self.generation += 1
            return _Result(self.generation)
        if 'FROM pg_locks' in statement:
            return _Result((self.acquired, self.generation))
        if 'SELECT generation FROM public.runtime_coordinator_state' in statement:
            return _Result((self.acquired, self.generation))
        return _Result(True)

    def close(self) -> None:
        self.closed = True


class _RpcAbort(Exception):
    def __init__(self, status: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.status = status


class _RpcContext:
    def __init__(self, metadata: tuple[tuple[str, str], ...]) -> None:
        self._metadata = metadata

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._metadata

    async def abort(self, status: grpc.StatusCode, details: str) -> None:
        raise _RpcAbort(status, details)


def test_runtime_coordinator_lease_holds_and_releases_session_lock(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    lease.check()
    lease.release()

    assert any('pg_try_advisory_lock' in statement for statement, _params in connection.statements)
    assert any('UPDATE public.runtime_coordinator_state' in statement for statement, _params in connection.statements)
    assert any('pg_advisory_unlock' in statement for statement, _params in connection.statements)
    assert connection.closed


def test_runtime_coordinator_lease_rejects_a_superseded_generation(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    connection.generation = 2

    with pytest.raises(RuntimeError, match='generation was superseded'):
        lease.check()

    lease.release()


def test_runtime_coordinator_lease_rejects_a_lost_advisory_lock(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    connection.acquired = False

    with pytest.raises(RuntimeError, match='advisory lease was lost'):
        lease.check()

    lease.release()


def test_runtime_coordinator_lease_reports_another_active_owner(monkeypatch) -> None:
    connection = _Connection(acquired=False)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is False
    lease.release()

    assert connection.closed


@pytest.mark.asyncio
async def test_generation_rpc_requires_the_live_postgres_owner(monkeypatch) -> None:
    lease_checks: list[str] = []
    monkeypatch.setattr(grpc_server.settings, 'internal_api_token', 'test-token')
    monkeypatch.setattr(grpc_server, 'active_runtime_coordinator_generation', lambda: 7)
    servicer = grpc_server.RuntimeCoordinatorServicer(lambda: lease_checks.append('checked'))

    response = await servicer.GetCoordinatorGeneration(
        common_pb2.EmptyRequest(),
        _RpcContext((('x-internal-token', 'test-token'),)),
    )
    assert response.generation == 7
    assert lease_checks == ['checked']

    response = await servicer.AssertCoordinatorGeneration(
        runtime_coordinator_pb2.RuntimeCoordinatorGenerationRequest(generation=7),
        _RpcContext((('x-internal-token', 'test-token'), ('x-runtime-coordinator-generation', '7'))),
    )
    assert response.generation == 7
    assert lease_checks == ['checked', 'checked']

    with pytest.raises(_RpcAbort) as abort:
        await servicer.AssertCoordinatorGeneration(
            runtime_coordinator_pb2.RuntimeCoordinatorGenerationRequest(generation=6),
            _RpcContext((('x-internal-token', 'test-token'), ('x-runtime-coordinator-generation', '6'))),
        )
    assert abort.value.status is grpc.StatusCode.FAILED_PRECONDITION
    assert lease_checks == ['checked', 'checked']


def test_runtime_coordinator_standby_reuses_its_database_session(monkeypatch) -> None:
    connection = _Connection(acquired=False)
    connection_count = 0

    def create_connection(*_args, **_kwargs):
        nonlocal connection_count
        connection_count += 1
        return connection

    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=create_connection)

    assert lease.acquire() is False
    connection.acquired = True
    assert lease.acquire() is True
    lease.release()

    assert connection_count == 1
    assert connection.closed


@pytest.mark.asyncio
async def test_runtime_coordinator_standby_waits_until_the_lease_is_free(monkeypatch) -> None:
    attempts = 0

    class Lease:
        def acquire(self) -> bool:
            nonlocal attempts
            attempts += 1
            return attempts == 3

        def release(self) -> None:
            pytest.fail('the acquired standby lease should be retained')

    monkeypatch.setattr(runtime_coordinator, '_LEASE_RETRY_SECONDS', 0.001)
    assert await runtime_coordinator._wait_for_lease(asyncio.Event(), cast(Any, Lease())) is True
    assert attempts == 3


@pytest.mark.asyncio
async def test_coordinator_notification_only_wakes_outbox(monkeypatch) -> None:
    published: list[object] = []
    monkeypatch.setattr(runtime_coordinator.OUTBOX_WAKE_HUB, 'publish', published.append)

    wakes: list[str] = []
    callbacks = {'chat_wake': lambda: wakes.append('chat'), 'telegram_wake': lambda: wakes.append('telegram')}
    await runtime_coordinator._handle_coordinator_notification({'kind': runtime_coordinator.OUTBOX_WAKE_KIND, 'namespace': 'tenant-a'}, **callbacks)
    await runtime_coordinator._handle_coordinator_notification({'kind': 'compute_response', 'request_id': 'request-1'}, **callbacks)
    await runtime_coordinator._handle_coordinator_notification({'kind': 'chat_turn'}, **callbacks)
    await runtime_coordinator._handle_coordinator_notification({'kind': 'settings_changed'}, **callbacks)
    await runtime_coordinator._handle_coordinator_notification({'kind': 'telegram_detection'}, **callbacks)

    assert published == ['tenant-a']
    assert wakes == ['chat', 'telegram', 'telegram']


@pytest.mark.asyncio
async def test_silent_actor_exit_fails_owned_epoch() -> None:
    async def actor() -> None:
        return

    process_stop = asyncio.create_task(asyncio.Event().wait())
    owner_stop = asyncio.create_task(asyncio.Event().wait())
    try:
        with pytest.raises(RuntimeError, match='exited unexpectedly'):
            await runtime_coordinator._supervise_epoch([asyncio.create_task(actor(), name='test-actor')], process_stop, owner_stop)
    finally:
        process_stop.cancel()
        owner_stop.cancel()
        await asyncio.gather(process_stop, owner_stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_coordinator_resets_standby_backoff_after_a_successful_epoch(monkeypatch) -> None:
    monkeypatch.setattr(runtime_coordinator.settings, 'distributed_runtime_enabled', True)
    monkeypatch.setattr(runtime_coordinator, '_LEASE_RETRY_SECONDS', 0.001)
    monkeypatch.setattr(runtime_coordinator, 'configure_logging_off_loop', lambda: asyncio.sleep(0))
    stop_events: list[asyncio.Event] = []
    monkeypatch.setattr(runtime_coordinator, '_install_stop_handlers', stop_events.append)

    class Lease:
        def release(self) -> None:
            return None

    monkeypatch.setattr(runtime_coordinator, 'RuntimeCoordinatorLease', Lease)
    lease_attempts = 0

    async def acquire_lease(_stop_event, _lease) -> bool:
        nonlocal lease_attempts
        lease_attempts += 1
        return True

    epoch_count = 0

    async def run_epoch(_stop_event, _lease) -> None:
        nonlocal epoch_count
        epoch_count += 1
        if epoch_count == 1:
            raise RuntimeError('transient owner startup failure')

    monkeypatch.setattr(runtime_coordinator, '_wait_for_lease', acquire_lease)
    monkeypatch.setattr(runtime_coordinator, '_run_owned_epoch', run_epoch)
    delays: list[float] = []

    async def expire_wait(awaitable, *, timeout: float) -> None:
        delays.append(timeout)
        awaitable.close()
        if len(delays) == 2:
            stop_events[0].set()
        raise TimeoutError

    monkeypatch.setattr(runtime_coordinator.asyncio, 'wait_for', expire_wait)

    await runtime_coordinator.main()

    assert lease_attempts == 2
    assert delays == [0.001, 0.001]
