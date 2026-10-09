from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, cast

import grpc
import pytest

import runtime_coordinator
from backend_core.database import RuntimeCoordinatorFenced
from backend_grpc import server as grpc_server
from dataforge_protocol import common_pb2, runtime_coordinator_pb2


class _Result:
    def __init__(self, value: object | tuple[object, ...]) -> None:
        self._value = value

    def fetchone(self) -> tuple[object, ...]:
        return self._value if isinstance(self._value, tuple) else (self._value,)

    def first(self) -> tuple[object, ...]:
        return self.fetchone()


class _Connection:
    def __init__(self, *, acquired: bool) -> None:
        self.acquired = acquired
        self.closed = False
        self.statements: list[tuple[str, tuple[object, ...] | None]] = []
        self.generation = 0
        self.select_hook: Callable[[], None] | None = None
        self.cancel_select = False

    def execute(self, statement: str, params: tuple[object, ...] | None = None) -> _Result:
        self.statements.append((statement, params))
        if 'pg_try_advisory_lock' in statement:
            return _Result(self.acquired)
        if 'UPDATE public.runtime_coordinator_state' in statement:
            self.generation += 1
            return _Result(self.generation)
        if statement == 'SELECT 1' and self.cancel_select:
            raise runtime_coordinator.psycopg.errors.QueryCanceled('statement timeout')
        if statement == 'SELECT 1' and self.select_hook is not None:
            self.select_hook()
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
    lease.check()
    assert lease.activate_generation() == 1
    lease.check()
    lease.release()

    assert any('pg_try_advisory_lock' in statement for statement, _params in connection.statements)
    assert any('UPDATE public.runtime_coordinator_state' in statement for statement, _params in connection.statements)
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 1
    assert any('pg_advisory_unlock' in statement for statement, _params in connection.statements)
    assert connection.closed


def test_runtime_coordinator_lease_guard_does_not_use_the_shared_settings_pool(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    monkeypatch.setattr(
        runtime_coordinator,
        'run_settings_db',
        lambda *_args, **_kwargs: pytest.fail('lease guard borrowed the shared database pool'),
        raising=False,
    )
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    lease.check()

    lease.release()


def test_runtime_coordinator_lease_rejects_a_closed_lock_session(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    connection.closed = True

    with pytest.raises(RuntimeError, match='PostgreSQL lease connection is closed'):
        lease.check()

    lease.release()


def test_runtime_coordinator_lease_rejects_a_released_local_lock(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    lease._owns_lock = False

    with pytest.raises(RuntimeError, match='advisory lease is not held'):
        lease.check()

    lease.release()


def test_runtime_coordinator_lease_ping_timeout_retains_lock_without_caching(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    connection.cancel_select = True

    lease.check(force=True)

    assert not connection.closed
    assert lease.generation == 1
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 1

    connection.cancel_select = False
    lease.check()
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 2
    lease.release()


def test_runtime_coordinator_lease_reuses_only_a_fixed_freshness_window(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    clock = [0.0]
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    monkeypatch.setattr(runtime_coordinator, '_LEASE_CHECK_FRESHNESS_SECONDS', 0.25)
    monkeypatch.setattr(runtime_coordinator, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)

    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    lease.check()
    for _ in range(5):
        lease.check()
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 1

    clock[0] = 0.15
    lease.check()
    clock[0] = 0.30
    lease.check()
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 2
    clock[0] = 0.54
    lease.check()
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 2
    clock[0] = 0.56
    lease.check()
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 3
    lease.release()


@pytest.mark.asyncio
async def test_lease_monitor_forces_fresh_probe_and_stops_on_closed_session(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    monkeypatch.setattr(runtime_coordinator, '_LEASE_CHECK_SECONDS', 0.01)
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)
    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    lease.check()
    assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 1

    process_stop = asyncio.Event()
    owner_stop = asyncio.Event()
    monitor = asyncio.create_task(runtime_coordinator._lease_monitor(process_stop, owner_stop, lease))
    try:
        for _ in range(100):
            if sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 2:
                break
            await asyncio.sleep(0.005)
        assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 2

        connection.closed = True
        await asyncio.wait_for(owner_stop.wait(), timeout=0.2)
        assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 2
    finally:
        process_stop.set()
        await monitor
        lease.release()


def test_runtime_coordinator_lease_coalesces_concurrent_lock_session_checks(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    query_started = threading.Event()
    release_query = threading.Event()
    all_followers_waiting = threading.Event()
    follower_count = 0
    follower_lock = threading.Lock()

    class ObservableFuture(Future):
        def result(self, timeout=None):
            nonlocal follower_count
            with follower_lock:
                follower_count += 1
                if follower_count == 3:
                    all_followers_waiting.set()
            return super().result(timeout)

    def block_query() -> None:
        query_started.set()
        if not release_query.wait(timeout=3):
            raise TimeoutError('coalesced coordinator check was not released')

    connection.select_hook = block_query
    monkeypatch.setattr(runtime_coordinator, 'Future', ObservableFuture)
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)
    assert lease.acquire() is True
    assert lease.activate_generation() == 1
    barrier = threading.Barrier(5)

    def check_together() -> None:
        barrier.wait(timeout=2)
        lease.check()

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            checks = [executor.submit(check_together) for _ in range(4)]
            barrier.wait(timeout=2)
            assert query_started.wait(timeout=1)
            assert all_followers_waiting.wait(timeout=1)
            release_query.set()
            for check in checks:
                check.result(timeout=3)
        assert sum(statement == 'SELECT 1' for statement, _params in connection.statements) == 1
    finally:
        release_query.set()
        lease.release()


def test_runtime_coordinator_lease_release_waits_for_owner_session_check(monkeypatch) -> None:
    connection = _Connection(acquired=True)
    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    query_started = threading.Event()
    finish_query = threading.Event()

    def block_query() -> None:
        query_started.set()
        if not finish_query.wait(timeout=3):
            raise TimeoutError('coordinator owner-session query was not released')

    connection.select_hook = block_query
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=lambda *_args, **_kwargs: connection)
    assert lease.acquire() is True
    assert lease.activate_generation() == 1

    with ThreadPoolExecutor(max_workers=1) as executor:
        check = executor.submit(lease.check)
        assert query_started.wait(timeout=1)
        release = executor.submit(lease.release)
        assert not release.done()
        finish_query.set()
        check.result(timeout=2)
        release.result(timeout=2)

    with pytest.raises(RuntimeError, match='lease connection is closed'):
        lease.check()


@pytest.mark.asyncio
async def test_coordinator_retains_generation_and_lease_until_actor_work_settles(monkeypatch) -> None:
    monkeypatch.setattr(runtime_coordinator, '_ACTOR_SHUTDOWN_GRACE_SECONDS', 0.01)
    active_generation: int | None = 41
    lease_released = False
    cleanup_started = threading.Event()
    finish_actor_work = threading.Event()
    actor_work_settled = threading.Event()

    def set_generation(generation: int | None) -> None:
        nonlocal active_generation
        active_generation = generation

    class Lease:
        def release(self) -> None:
            nonlocal lease_released
            assert actor_work_settled.is_set()
            lease_released = True

    monkeypatch.setattr(runtime_coordinator, 'set_active_runtime_coordinator_generation', set_generation)

    async def actor() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            await asyncio.to_thread(finish_actor_work.wait)
            actor_work_settled.set()
            raise

    actor_task = asyncio.create_task(actor(), name='blocked-db-actor')
    await asyncio.sleep(0)
    teardown = asyncio.create_task(runtime_coordinator._settle_epoch_ownership([actor_task], cast(Any, Lease())))
    try:
        assert await asyncio.to_thread(cleanup_started.wait, 1)
        assert active_generation == 41
        assert not lease_released
        assert not teardown.done()

        finish_actor_work.set()
        assert await asyncio.wait_for(teardown, timeout=1) is False
        assert actor_work_settled.is_set()
        assert active_generation is None
        assert lease_released
    finally:
        finish_actor_work.set()
        if not teardown.done():
            teardown.cancel()
            await asyncio.gather(teardown, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_during_grpc_shutdown_still_settles_actors_before_release(monkeypatch) -> None:
    active_generation: int | None = 73
    lease_released = False
    grpc_shutdown_started = threading.Event()
    finish_grpc_shutdown = threading.Event()
    actor_stopped = threading.Event()

    def set_generation(generation: int | None) -> None:
        nonlocal active_generation
        active_generation = generation

    class Lease:
        def release(self) -> None:
            nonlocal lease_released
            assert actor_stopped.is_set()
            lease_released = True

    class GrpcServer:
        async def stop(self, *, grace: float) -> None:
            assert grace == 0.5
            grpc_shutdown_started.set()
            await asyncio.to_thread(finish_grpc_shutdown.wait)

    async def stop_listener(_listener, *, listener) -> None:
        assert listener is runtime_coordinator.RuntimeListenerKind.JOB

    monkeypatch.setattr(runtime_coordinator, 'set_active_runtime_coordinator_generation', set_generation)
    monkeypatch.setattr(runtime_coordinator.runtime_ipc, 'stop_api_server', stop_listener)

    async def actor() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            actor_stopped.set()

    actor_task = asyncio.create_task(actor(), name='epoch-actor')
    await asyncio.sleep(0)

    async def control_wait() -> bool:
        return False

    shutdown = asyncio.create_task(
        runtime_coordinator._finish_epoch_shutdown(
            asyncio.Event(),
            (asyncio.create_task(control_wait()), asyncio.create_task(control_wait())),
            GrpcServer(),
            object(),
            [actor_task],
            cast(Any, Lease()),
        )
    )
    try:
        assert await asyncio.to_thread(grpc_shutdown_started.wait, 1)
        shutdown.cancel()
        await asyncio.sleep(0.05)
        assert not shutdown.done()
        assert active_generation == 73
        assert not lease_released

        finish_grpc_shutdown.set()
        assert await asyncio.wait_for(shutdown, timeout=1) is True
        assert actor_stopped.is_set()
        assert active_generation is None
        assert lease_released
    finally:
        finish_grpc_shutdown.set()
        if not shutdown.done():
            shutdown.cancel()
            await asyncio.gather(shutdown, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_endpoint_shutdown_joins_actors_and_retains_lease(monkeypatch) -> None:
    active_generation: int | None = 89
    lease_released = False
    actor_stopped = threading.Event()

    def set_generation(generation: int | None) -> None:
        nonlocal active_generation
        active_generation = generation

    class Lease:
        def release(self) -> None:
            nonlocal lease_released
            lease_released = True

    class FailedGrpcServer:
        async def stop(self, *, grace: float) -> None:
            raise RuntimeError('gRPC endpoint did not stop')

    async def stop_listener(_listener, *, listener) -> None:
        assert listener is runtime_coordinator.RuntimeListenerKind.JOB

    monkeypatch.setattr(runtime_coordinator, 'set_active_runtime_coordinator_generation', set_generation)
    monkeypatch.setattr(runtime_coordinator.runtime_ipc, 'stop_api_server', stop_listener)

    async def actor() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            actor_stopped.set()

    actor_task = asyncio.create_task(actor(), name='epoch-actor')
    await asyncio.sleep(0)

    async def control_wait() -> bool:
        return False

    with pytest.raises(RuntimeError, match='retaining its lease'):
        await runtime_coordinator._finish_epoch_shutdown(
            asyncio.Event(),
            (asyncio.create_task(control_wait()), asyncio.create_task(control_wait())),
            FailedGrpcServer(),
            object(),
            [actor_task],
            cast(Any, Lease()),
        )

    assert actor_stopped.is_set()
    assert active_generation == 89
    assert not lease_released


@pytest.mark.asyncio
async def test_coordinator_finalizer_exits_without_releasing_unsafe_endpoint_lease(monkeypatch) -> None:
    lease_released = False
    exit_codes: list[int] = []

    class ProcessExit(Exception):
        pass

    class Lease:
        def release(self) -> None:
            nonlocal lease_released
            lease_released = True

    def process_exit(code: int) -> None:
        exit_codes.append(code)
        raise ProcessExit

    monkeypatch.setattr(runtime_coordinator, 'active_runtime_coordinator_generation', lambda: 89)
    monkeypatch.setattr(runtime_coordinator.os, '_exit', process_exit)

    with pytest.raises(ProcessExit):
        await runtime_coordinator._release_coordinator_lease(cast(Any, Lease()))

    assert exit_codes == [1]
    assert not lease_released


@pytest.mark.asyncio
async def test_coordinator_finalizer_releases_after_safe_epoch_settlement(monkeypatch) -> None:
    lease_released = False

    class Lease:
        def release(self) -> None:
            nonlocal lease_released
            lease_released = True

    monkeypatch.setattr(runtime_coordinator, 'active_runtime_coordinator_generation', lambda: None)
    await runtime_coordinator._release_coordinator_lease(cast(Any, Lease()))

    assert lease_released


@pytest.mark.asyncio
async def test_owner_epoch_failure_fail_stops_before_main_can_return_to_standby(monkeypatch) -> None:
    exit_codes: list[int] = []
    lease_released = False

    class ProcessExit(BaseException):
        pass

    class Lease:
        def release(self) -> None:
            nonlocal lease_released
            lease_released = True

    lease = Lease()

    def process_exit(code: int) -> None:
        exit_codes.append(code)
        raise ProcessExit

    async def acquire_lease(_stop_event, _lease) -> bool:
        return True

    async def failed_epoch(_stop_event, _lease) -> None:
        raise RuntimeError('endpoint shutdown failed; lease retained')

    monkeypatch.setattr(runtime_coordinator.settings, 'distributed_runtime_enabled', True)
    monkeypatch.setattr(runtime_coordinator, 'configure_runtime_critical_database_budget', lambda: 0)
    monkeypatch.setattr(runtime_coordinator, 'configure_logging_off_loop', lambda: asyncio.sleep(0))
    monkeypatch.setattr(runtime_coordinator, '_install_stop_handlers', lambda _event: None)
    monkeypatch.setattr(runtime_coordinator, 'RuntimeCoordinatorLease', lambda: lease)
    monkeypatch.setattr(runtime_coordinator, '_wait_for_lease', acquire_lease)
    monkeypatch.setattr(runtime_coordinator, '_run_owned_epoch', failed_epoch)
    monkeypatch.setattr(runtime_coordinator, 'active_runtime_coordinator_generation', lambda: 89)
    monkeypatch.setattr(runtime_coordinator.os, '_exit', process_exit)

    with pytest.raises(ProcessExit):
        await runtime_coordinator.main()

    assert exit_codes == [1, 1]
    assert not lease_released


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
async def test_coordinator_listener_recovery_wakes_all_durable_consumers(monkeypatch) -> None:
    published: list[object] = []
    wakes: list[str] = []
    monkeypatch.setattr(runtime_coordinator.OUTBOX_WAKE_HUB, 'publish', published.append)

    await runtime_coordinator._recover_coordinator_notifications(chat_wake=lambda: wakes.append('chat'), telegram_wake=lambda: wakes.append('telegram'))

    assert published == [None]
    assert wakes == ['chat', 'telegram']


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
async def test_chat_database_connection_failure_restarts_only_the_chat_actor() -> None:
    stop = asyncio.Event()
    chat_recovered = asyncio.Event()
    attempts = 0

    class ChatConsumer:
        async def run(self, stop_event: asyncio.Event) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise runtime_coordinator.SQLAlchemyOperationalError('SELECT', {}, RuntimeError('temporary database DNS failure'))
            chat_recovered.set()
            await stop_event.wait()

    chat_task = asyncio.create_task(
        runtime_coordinator._run_chat_turn_consumer(ChatConsumer().run, stop),
        name='chat-turn-consumer',
    )

    async def grpc_actor() -> None:
        await stop.wait()

    grpc_task = asyncio.create_task(grpc_actor(), name='runtime-grpc')
    process_stop = asyncio.create_task(stop.wait(), name='runtime-process-stop')
    owner_stop = asyncio.create_task(stop.wait(), name='runtime-owner-stop')
    supervisor = asyncio.create_task(runtime_coordinator._supervise_epoch([chat_task, grpc_task], process_stop, owner_stop))
    try:
        await asyncio.wait_for(chat_recovered.wait(), timeout=2)
        assert attempts == 2
        assert not supervisor.done()
        assert not grpc_task.done()
    finally:
        stop.set()
        await asyncio.wait_for(supervisor, timeout=2)
        await asyncio.gather(chat_task, grpc_task, process_stop, owner_stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_chat_coordinator_fencing_failure_still_fails_the_epoch() -> None:
    stop = asyncio.Event()

    class FencedChatConsumer:
        async def run(self, _stop_event: asyncio.Event) -> None:
            raise RuntimeCoordinatorFenced('stale coordinator generation')

    chat_task = asyncio.create_task(
        runtime_coordinator._run_chat_turn_consumer(FencedChatConsumer().run, stop),
        name='chat-turn-consumer',
    )
    process_stop = asyncio.create_task(stop.wait(), name='runtime-process-stop')
    owner_stop = asyncio.create_task(stop.wait(), name='runtime-owner-stop')
    try:
        with pytest.raises(RuntimeError, match='Coordinator actor chat-turn-consumer failed') as failure:
            await runtime_coordinator._supervise_epoch([chat_task], process_stop, owner_stop)
        assert failure.value.__cause__ is not None
        assert isinstance(failure.value.__cause__, RuntimeCoordinatorFenced)
    finally:
        stop.set()
        await asyncio.gather(chat_task, process_stop, owner_stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_coordinator_resets_standby_backoff_after_a_successful_epoch(monkeypatch) -> None:
    monkeypatch.setattr(runtime_coordinator.settings, 'distributed_runtime_enabled', True)
    monkeypatch.setattr(runtime_coordinator, '_LEASE_RETRY_SECONDS', 0.001)
    monkeypatch.setattr(runtime_coordinator, 'configure_runtime_critical_database_budget', lambda: 0)
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


def test_runtime_coordinator_lease_session_asks_postgres_to_notice_a_vanished_owner(monkeypatch) -> None:
    kwargs: dict[str, object] = {}
    connection = _Connection(acquired=True)

    def connect(_conninfo: str, **options):
        kwargs.update(options)
        return connection

    monkeypatch.setattr(runtime_coordinator, '_database_conninfo', lambda: 'postgresql://test')
    lease = runtime_coordinator.RuntimeCoordinatorLease(connection_factory=connect)
    assert lease.acquire() is True
    lease.release()

    options = str(kwargs['options'])
    assert options == runtime_coordinator._LEASE_SESSION_OPTIONS
    # A coordinator whose machine dies never closes this session. Server-side
    # keepalives are what drop it, and the advisory lock with it, within
    # seconds so a standby elsewhere can take over.
    assert 'tcp_keepalives_idle=5' in options
    assert 'tcp_keepalives_interval=2' in options
    assert 'tcp_keepalives_count=3' in options
    assert 'statement_timeout=3000' in options


@pytest.mark.asyncio
async def test_coordinator_roles_report_standby_then_active_then_standby(monkeypatch) -> None:
    states: list[str] = []
    stop = asyncio.Event()

    class Health:
        def standby(self) -> None:
            states.append('standby')

        def active(self, generation: int) -> None:
            states.append(f'active:{generation}')

    async def wait_for_lease(_stop: asyncio.Event, _lease) -> bool:
        states.append('lease')
        return True

    async def owned_epoch(_stop: asyncio.Event, _lease, *, health) -> None:
        health.active(3)
        stop.set()

    monkeypatch.setattr(runtime_coordinator, '_wait_for_lease', wait_for_lease)
    monkeypatch.setattr(runtime_coordinator, '_run_owned_epoch', owned_epoch)

    await runtime_coordinator._run_coordinator_roles(stop, cast(Any, object()), cast(Any, Health()), 0.001)
    assert states == ['standby', 'lease', 'active:3']
