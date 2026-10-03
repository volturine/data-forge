import asyncio
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import event, text
from sqlalchemy.pool import QueuePool, StaticPool
from sqlmodel import Session, create_engine

from backend_core import database
from backend_core.api_execution_budget import (
    ApiDatabaseBudget,
    ApiWorkAdmissionFull,
    BoundedThreadPoolExecutor,
    install_api_blocking_executor,
    install_bootstrap_executor,
    register_bootstrap_executor_lifecycle,
    remove_api_blocking_executor,
    remove_bootstrap_executor,
    run_api_blocking,
    run_bootstrap_db,
    run_bootstrap_settings_db,
)
from backend_core.namespace import get_namespace, reset_namespace, set_namespace_context


def test_budget_uses_the_smaller_engine_capacity_and_api_upper_bound() -> None:
    budget = ApiDatabaseBudget.derive(
        settings_pool_capacity=24,
        tenant_pool_capacity=16,
        api_thread_upper_bound=12,
    )

    assert budget == ApiDatabaseBudget(12, 6, 4, 2)
    assert budget.general_workers + budget.sync_workers + budget.bootstrap_workers == budget.database_capacity


@pytest.mark.asyncio
async def test_bounded_executor_rejects_overflow_and_queued_cancel_releases_capacity() -> None:
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=1, thread_name_prefix='bounded-queue-test')
    started = threading.Event()
    release = threading.Event()

    def block() -> str:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError('bounded executor test was not released')
        return 'done'

    try:
        running = executor.submit(block)
        assert await asyncio.to_thread(started.wait, 1)
        queued = executor.submit(lambda: 'cancelled')
        with pytest.raises(ApiWorkAdmissionFull, match='API execution capacity is full'):
            executor.submit(lambda: 'overflow')

        assert queued.cancel()
        replacement = executor.submit(lambda: 'replacement')
        release.set()
        assert running.result(timeout=2) == 'done'
        assert replacement.result(timeout=2) == 'replacement'
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_api_blocking_records_admission_executor_queue_and_work_timings() -> None:
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='api-lane-metrics-test')
    install_api_blocking_executor(loop, executor, workers=1, max_pending=0)
    work_started = threading.Event()
    release_work = threading.Event()
    metrics: dict[str, object] = {}

    def blocking_work() -> str:
        work_started.set()
        if not release_work.wait(timeout=5):
            raise TimeoutError('API lane metrics work was not released')
        return 'done'

    try:
        with database.database_statement_timing(metrics):
            first = asyncio.create_task(run_api_blocking(blocking_work))
            assert await asyncio.to_thread(work_started.wait, 1)
            second = asyncio.create_task(run_api_blocking(lambda: 'second'))
            await asyncio.sleep(0.02)
            assert not second.done()
            release_work.set()
            assert await asyncio.gather(first, second) == ['done', 'second']

        admission_wait = metrics['api_general_admission_wait_ms']
        executor_queue = metrics['api_general_executor_queue_ms']
        work_duration = metrics['api_general_work_ms']
        assert isinstance(admission_wait, (int, float)) and admission_wait > 0
        assert isinstance(executor_queue, (int, float)) and executor_queue >= 0
        assert isinstance(work_duration, (int, float)) and work_duration > 0
    finally:
        release_work.set()
        remove_api_blocking_executor(loop)
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_bootstrap_lane_records_its_own_admission_executor_queue_and_work_timings() -> None:
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bootstrap-lane-metrics-test')
    install_bootstrap_executor(loop, executor, workers=1, max_pending=0)
    metrics: dict[str, object] = {}

    try:
        with database.database_statement_timing(metrics):
            assert await run_bootstrap_db(lambda: 'done') == 'done'

        admission_wait = metrics['api_blocking_admission_wait_ms']
        bootstrap_admission = metrics['api_bootstrap_admission_wait_ms']
        executor_queue = metrics['api_bootstrap_executor_queue_ms']
        work_duration = metrics['api_bootstrap_work_ms']
        assert isinstance(admission_wait, (int, float)) and admission_wait >= 0
        assert isinstance(bootstrap_admission, (int, float)) and bootstrap_admission >= 0
        assert isinstance(executor_queue, (int, float)) and executor_queue >= 0
        assert isinstance(work_duration, (int, float)) and work_duration > 0
    finally:
        remove_bootstrap_executor(loop)
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_bounded_executor_keeps_started_cancelled_work_admitted_until_settlement() -> None:
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=0, thread_name_prefix='bounded-running-test')
    started = threading.Event()
    release = threading.Event()

    def block() -> None:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError('bounded running test was not released')

    try:
        task = asyncio.ensure_future(asyncio.wrap_future(executor.submit(block)))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ApiWorkAdmissionFull):
            executor.submit(lambda: None)

        release.set()
        deadline = asyncio.get_running_loop().time() + 2
        while True:
            try:
                completed = executor.submit(lambda: 'released')
                break
            except ApiWorkAdmissionFull:
                if asyncio.get_running_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.01)
        assert completed.result(timeout=2) == 'released'
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_api_admission_overflow_maps_to_retryable_http_503() -> None:
    from starlette.requests import Request

    from backend_core.error_handlers import handle_errors
    from main import api_work_admission_full_handler, app

    @handle_errors(operation='test bounded API work')
    async def route():
        raise ApiWorkAdmissionFull()

    with pytest.raises(ApiWorkAdmissionFull):
        asyncio.run(route())

    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []})
    capacity_error = ApiWorkAdmissionFull()
    response = asyncio.run(api_work_admission_full_handler(request, capacity_error))

    assert app.exception_handlers[ApiWorkAdmissionFull] is api_work_admission_full_handler
    assert response.status_code == 503
    assert response.headers['retry-after'] == '1'
    assert response.body == b'{"detail":"API execution capacity is full"}'


def test_api_blocking_work_queue_is_independent_of_socket_limit(monkeypatch) -> None:
    from backend_core.config import settings
    from main import _api_blocking_pending_limit

    for connection_limit in (1_000, 2_500, 0):
        monkeypatch.setattr(settings, 'worker_connections', connection_limit)
        assert _api_blocking_pending_limit(6) == 96

    assert _api_blocking_pending_limit(2) == 32
    assert _api_blocking_pending_limit(0) == 0


@pytest.mark.asyncio
async def test_config_and_auth_db_adapters_progress_while_general_executor_is_blocked(monkeypatch) -> None:
    from starlette.requests import Request

    from modules.auth import dependencies as auth_dependencies, routes as auth_routes
    from modules.config import routes as config_routes

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    database.set_settings_engine_override(engine)
    checkout_threads: list[int] = []
    checkin_threads: list[int] = []
    event.listen(engine, 'checkout', lambda *_args: checkout_threads.append(threading.get_ident()))
    event.listen(engine, 'checkin', lambda *_args: checkin_threads.append(threading.get_ident()))

    general_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='general-test')
    bootstrap_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bootstrap-test')
    general_release = threading.Event()
    general_started = threading.Event()
    validation_started = threading.Event()
    loop = asyncio.get_running_loop()
    loop.set_default_executor(general_executor)
    install_bootstrap_executor(loop, bootstrap_executor, 1)

    def block_general() -> None:
        general_started.set()
        if not general_release.wait(timeout=5):
            raise TimeoutError('general executor test work was not released')

    def bootstrap_me(session: Session, token: str | None) -> tuple[int, str, str | None]:
        session.execute(text('SELECT 1'))
        return threading.get_ident(), get_namespace(), token

    def validate_session(_session: Session, token: str) -> None:
        validation_started.set()
        return None

    def run_test_settings_db(function, *args, **kwargs):
        return function(None, *args, **kwargs)

    monkeypatch.setattr(config_routes, 'get_settings', lambda session: (session.execute(text('SELECT 1')), get_namespace())[1])
    monkeypatch.setattr(config_routes, '_build_frontend_config', lambda namespace: namespace)
    monkeypatch.setattr(auth_routes, '_resolve_me', bootstrap_me)
    monkeypatch.setattr(auth_dependencies, 'validate_session', validate_session)
    monkeypatch.setattr(auth_dependencies, 'run_settings_db', run_test_settings_db)
    monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
    auth_request = Request(
        {
            'type': 'http',
            'method': 'GET',
            'path': '/api/v1/auth/me',
            'query_string': b'',
            'headers': [(b'cookie', b'session_token=ordinary-token')],
        }
    )
    loop_thread = threading.get_ident()
    namespace_token = set_namespace_context('protected-api-test')
    general_future = loop.run_in_executor(general_executor, block_general)

    try:
        general_start_deadline = loop.time() + 1
        while not general_started.is_set() and loop.time() < general_start_deadline:
            await asyncio.sleep(0.01)
        assert general_started.is_set()
        ordinary_auth = asyncio.create_task(auth_dependencies._resolve_user(auth_request))
        await asyncio.sleep(0.02)
        assert not ordinary_auth.done()
        assert not validation_started.is_set()
        config_result, bootstrap_me_result = await asyncio.wait_for(
            asyncio.gather(
                config_routes.get_config(),
                auth_routes.me(auth_request),
            ),
            timeout=1,
        )
        assert config_result == 'protected-api-test'
        me_thread_id, me_namespace, me_token = bootstrap_me_result
        assert me_thread_id != loop_thread
        assert me_namespace == 'protected-api-test'
        assert me_token == 'ordinary-token'
        assert checkout_threads and checkout_threads == checkin_threads
        assert all(thread_id != loop_thread for thread_id in checkout_threads)
        assert not ordinary_auth.done()
        assert not validation_started.is_set()
        general_release.set()
        assert await ordinary_auth is None
        assert validation_started.is_set()
    finally:
        general_release.set()
        await general_future
        reset_namespace(namespace_token)
        remove_bootstrap_executor(loop)
        general_executor.shutdown(wait=True)
        bootstrap_executor.shutdown(wait=True)
        database.clear_settings_engine_override()
        engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_admission_waits_asynchronously_when_running_and_pending_window_is_full() -> None:
    class RecordingExecutor(ThreadPoolExecutor):
        def __init__(self) -> None:
            super().__init__(max_workers=1, thread_name_prefix='bootstrap-admission-test')
            self.submissions = 0

        def submit(self, function, /, *args, **kwargs):
            self.submissions += 1
            return super().submit(function, *args, **kwargs)

    executor = RecordingExecutor()
    loop = asyncio.get_running_loop()
    install_bootstrap_executor(loop, executor, 1, max_pending=1)
    first_started = threading.Event()
    release_first = threading.Event()

    def first_operation() -> str:
        first_started.set()
        if not release_first.wait(timeout=5):
            raise TimeoutError('bootstrap admission test operation was not released')
        return 'first'

    try:
        first = asyncio.create_task(run_bootstrap_db(first_operation))
        assert await asyncio.to_thread(first_started.wait, 1)
        second = asyncio.create_task(run_bootstrap_db(lambda: 'second'))
        await asyncio.sleep(0)
        assert executor.submissions == 2
        third = asyncio.create_task(run_bootstrap_db(lambda: 'third'))
        await asyncio.sleep(0)
        assert executor.submissions == 2
        assert not third.done()
        # Waiting for capacity is async: unrelated loop work still runs.
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        release_first.set()
        assert await asyncio.gather(first, second, third) == ['first', 'second', 'third']
        assert await run_bootstrap_db(lambda: 'after-settlement') == 'after-settlement'
        assert executor.submissions == 4
    finally:
        release_first.set()
        remove_bootstrap_executor(loop)
        executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_cancelled_bootstrap_caller_keeps_running_thread_admitted_until_settlement() -> None:
    class RecordingExecutor(ThreadPoolExecutor):
        def __init__(self) -> None:
            super().__init__(max_workers=1, thread_name_prefix='bootstrap-cancel-test')
            self.submissions = 0

        def submit(self, function, /, *args, **kwargs):
            self.submissions += 1
            return super().submit(function, *args, **kwargs)

    loop = asyncio.get_running_loop()
    executor = RecordingExecutor()
    install_bootstrap_executor(loop, executor, 1, max_pending=1)
    operation_started = threading.Event()
    release_operation = threading.Event()
    late_errors: list[dict[str, object]] = []
    previous_exception_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: late_errors.append(context))

    def fail_after_release() -> str:
        operation_started.set()
        if not release_operation.wait(timeout=5):
            raise TimeoutError('cancelled bootstrap operation was not released')
        raise RuntimeError('late protected database failure')

    first = asyncio.create_task(run_bootstrap_db(fail_after_release))
    second: asyncio.Task[str] | None = None

    try:
        start_deadline = loop.time() + 1
        while not operation_started.is_set() and loop.time() < start_deadline:
            await asyncio.sleep(0.01)
        assert operation_started.is_set()
        second = asyncio.create_task(run_bootstrap_db(lambda: 'second'))
        await asyncio.sleep(0.02)
        assert executor.submissions == 2
        waiting = asyncio.create_task(run_bootstrap_db(lambda: 'cancelled-while-waiting'))
        await asyncio.sleep(0)
        assert executor.submissions == 2

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        await asyncio.sleep(0.02)
        assert executor.submissions == 2
        assert not second.done()

        release_operation.set()
        assert second is not None
        assert await asyncio.wait_for(second, timeout=2) == 'second'
        assert await run_bootstrap_db(lambda: 'after-settlement') == 'after-settlement'
        await asyncio.sleep(0)
        assert executor.submissions == 3
        assert any(str(context.get('exception')) == 'late protected database failure' for context in late_errors)
    finally:
        release_operation.set()
        if second is not None:
            await asyncio.gather(second, return_exceptions=True)
        remove_bootstrap_executor(loop)
        loop.set_exception_handler(previous_exception_handler)
        await loop.run_in_executor(None, executor.shutdown, True)


@pytest.mark.asyncio
async def test_cancel_before_thread_start_cancels_queued_future_and_releases_its_admission() -> None:
    class RecordingExecutor(ThreadPoolExecutor):
        def __init__(self) -> None:
            super().__init__(max_workers=1, thread_name_prefix='bootstrap-queued-cancel-test')
            self.futures: list[Future[object]] = []

        def submit(self, function, /, *args, **kwargs):
            future = super().submit(function, *args, **kwargs)
            self.futures.append(future)
            return future

    loop = asyncio.get_running_loop()
    executor = RecordingExecutor()
    install_bootstrap_executor(loop, executor, 1, max_pending=2)
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    def first_operation() -> str:
        first_started.set()
        if not release_first.wait(timeout=5):
            raise TimeoutError('queued cancellation test operation was not released')
        return 'first'

    def second_operation() -> str:
        second_started.set()
        return 'second'

    first = asyncio.create_task(run_bootstrap_db(first_operation))
    second: asyncio.Task[str] | None = None
    third: asyncio.Task[str] | None = None
    fourth: asyncio.Task[str] | None = None
    try:
        start_deadline = loop.time() + 1
        while not first_started.is_set() and loop.time() < start_deadline:
            await asyncio.sleep(0.01)
        assert first_started.is_set()

        second = asyncio.create_task(run_bootstrap_db(second_operation))
        await asyncio.sleep(0.02)
        assert len(executor.futures) == 2
        assert not second_started.is_set()

        third = asyncio.create_task(run_bootstrap_db(lambda: 'third'))
        await asyncio.sleep(0)
        assert len(executor.futures) == 3
        fourth = asyncio.create_task(run_bootstrap_db(lambda: 'fourth'))
        await asyncio.sleep(0)
        assert len(executor.futures) == 3
        assert not fourth.done()

        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert executor.futures[1].cancelled()
        assert not second_started.is_set()

        await asyncio.sleep(0.02)
        assert len(executor.futures) == 4
        release_first.set()
        assert await first == 'first'
        assert await asyncio.wait_for(third, timeout=2) == 'third'
        assert await asyncio.wait_for(fourth, timeout=2) == 'fourth'
    finally:
        release_first.set()
        for task in (first, second, third, fourth):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second, third, fourth) if task is not None), return_exceptions=True)
        remove_bootstrap_executor(loop)
        await loop.run_in_executor(None, executor.shutdown, True)


@pytest.mark.asyncio
async def test_api_blocking_burst_waits_without_stalling_the_event_loop() -> None:
    class RecordingExecutor(BoundedThreadPoolExecutor):
        def __init__(self) -> None:
            super().__init__(max_workers=1, max_pending=1, thread_name_prefix='api-blocking-burst-test')
            self.submissions = 0

        def submit(self, function, /, *args, **kwargs):
            self.submissions += 1
            return super().submit(function, *args, **kwargs)

    loop = asyncio.get_running_loop()
    executor = RecordingExecutor()
    install_api_blocking_executor(loop, executor, 1, max_pending=1)
    first_started = threading.Event()
    release_first = threading.Event()

    def first_operation() -> str:
        first_started.set()
        if not release_first.wait(timeout=5):
            raise TimeoutError('API blocking burst test was not released')
        return 'first'

    try:
        first = asyncio.create_task(run_api_blocking(first_operation))
        assert await asyncio.to_thread(first_started.wait, 1)
        second = asyncio.create_task(run_api_blocking(lambda: 'second'))
        await asyncio.sleep(0.02)
        assert executor.submissions == 2
        third = asyncio.create_task(run_api_blocking(lambda: 'third'))
        await asyncio.sleep(0)
        assert not third.done()
        assert executor.submissions == 2
        # This deadline can only be met if admission wait yields to the loop.
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        release_first.set()
        assert await asyncio.gather(first, second, third) == ['first', 'second', 'third']
        assert executor.submissions == 3
    finally:
        release_first.set()
        remove_api_blocking_executor(loop)
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_api_blocking_cancellation_while_queued_releases_only_settled_capacity() -> None:
    class RecordingExecutor(BoundedThreadPoolExecutor):
        def __init__(self) -> None:
            super().__init__(max_workers=1, max_pending=1, thread_name_prefix='api-blocking-cancel-queued-test')
            self.futures: list[Future[object]] = []

        def submit(self, function, /, *args, **kwargs):
            future = super().submit(function, *args, **kwargs)
            self.futures.append(future)
            return future

    loop = asyncio.get_running_loop()
    executor = RecordingExecutor()
    install_api_blocking_executor(loop, executor, 1, max_pending=1)
    first_started = threading.Event()
    release_first = threading.Event()

    def block() -> str:
        first_started.set()
        if not release_first.wait(timeout=5):
            raise TimeoutError('API queued-cancellation test was not released')
        return 'first'

    try:
        first = asyncio.create_task(run_api_blocking(block))
        assert await asyncio.to_thread(first_started.wait, 1)
        queued = asyncio.create_task(run_api_blocking(lambda: 'cancelled'))
        await asyncio.sleep(0.02)
        assert len(executor.futures) == 2
        waiting = asyncio.create_task(run_api_blocking(lambda: 'waiting'))
        await asyncio.sleep(0)
        assert len(executor.futures) == 2

        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert executor.futures[1].cancelled()
        release_first.set()
        assert await first == 'first'
        assert await asyncio.wait_for(waiting, timeout=1) == 'waiting'
    finally:
        release_first.set()
        remove_api_blocking_executor(loop)
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_api_blocking_cancelled_running_thread_retains_admission_until_done() -> None:
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=0, thread_name_prefix='api-blocking-running-cancel-test')
    loop = asyncio.get_running_loop()
    install_api_blocking_executor(loop, executor, 1, max_pending=0)
    started = threading.Event()
    release = threading.Event()

    def block() -> str:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError('API running-cancellation test was not released')
        return 'finished'

    try:
        cancelled = asyncio.create_task(run_api_blocking(block))
        assert await asyncio.to_thread(started.wait, 1)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled

        next_call = asyncio.create_task(run_api_blocking(lambda: 'next'))
        await asyncio.sleep(0.02)
        assert not next_call.done()
        release.set()
        assert await asyncio.wait_for(next_call, timeout=1) == 'next'
    finally:
        release.set()
        remove_api_blocking_executor(loop)
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_bootstrap_submit_failure_releases_admission_for_the_next_call() -> None:
    class FailOnceExecutor(ThreadPoolExecutor):
        def __init__(self) -> None:
            super().__init__(max_workers=1, thread_name_prefix='bootstrap-submit-failure-test')
            self.fail_next = True

        def submit(self, function, /, *args, **kwargs):
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError('simulated executor submit failure')
            return super().submit(function, *args, **kwargs)

    loop = asyncio.get_running_loop()
    executor = FailOnceExecutor()
    install_bootstrap_executor(loop, executor, 1)
    try:
        with pytest.raises(RuntimeError, match='simulated executor submit failure'):
            await run_bootstrap_db(lambda: 'unsubmitted')
        assert await run_bootstrap_db(lambda: 'submitted') == 'submitted'
    finally:
        remove_bootstrap_executor(loop)
        await loop.run_in_executor(None, executor.shutdown, True)


def test_three_api_lanes_fit_the_real_pool_capacity_and_own_their_sessions(tmp_path) -> None:
    budget = ApiDatabaseBudget.derive(settings_pool_capacity=3, tenant_pool_capacity=3, api_thread_upper_bound=12)
    engine = create_engine(f'sqlite:///{tmp_path / "api-budget.sqlite"}', pool_size=3, max_overflow=0)
    database.set_settings_engine_override(engine)
    state_lock = threading.Lock()
    active_connections = 0
    peak_connections = 0
    checkout_threads: list[int] = []
    checkin_threads: list[int] = []
    barrier = threading.Barrier(budget.database_capacity + 1)

    def checkout(*_args) -> None:
        nonlocal active_connections, peak_connections
        with state_lock:
            active_connections += 1
            peak_connections = max(peak_connections, active_connections)
            checkout_threads.append(threading.get_ident())

    def checkin(*_args) -> None:
        nonlocal active_connections
        with state_lock:
            active_connections -= 1
            checkin_threads.append(threading.get_ident())

    event.listen(engine, 'checkout', checkout)
    event.listen(engine, 'checkin', checkin)

    def occupy_connection(session: Session) -> int:
        session.execute(text('SELECT 1'))
        barrier.wait(timeout=5)
        return threading.get_ident()

    try:
        with (
            ThreadPoolExecutor(max_workers=budget.general_workers, thread_name_prefix='api-general-test') as general,
            ThreadPoolExecutor(max_workers=budget.sync_workers, thread_name_prefix='api-sync-test') as sync,
            ThreadPoolExecutor(max_workers=budget.bootstrap_workers, thread_name_prefix='api-bootstrap-test') as bootstrap,
        ):
            futures = [
                general.submit(database.run_settings_db, occupy_connection),
                sync.submit(database.run_settings_db, occupy_connection),
                bootstrap.submit(database.run_settings_db, occupy_connection),
            ]
            barrier.wait(timeout=5)
            worker_threads = [future.result(timeout=5) for future in futures]

        assert peak_connections == budget.database_capacity == 3
        assert Counter(checkout_threads) == Counter(checkin_threads)
        assert set(checkout_threads) == set(worker_threads)
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.checkedout() == 0
        assert engine.pool.overflow() == 0
    finally:
        database.clear_settings_engine_override()
        engine.dispose()


def test_bootstrap_executor_registration_is_isolated_across_event_loop_restarts() -> None:
    for _ in range(2):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bootstrap-restart-test')

        async def use_executor(bootstrap_executor: ThreadPoolExecutor = executor) -> None:
            loop = asyncio.get_running_loop()
            install_bootstrap_executor(loop, bootstrap_executor, 1)
            try:

                def current_thread(_session: Session) -> int:
                    return threading.get_ident()

                result = await run_bootstrap_settings_db(current_thread)
                assert result != threading.get_ident()
            finally:
                remove_bootstrap_executor(loop)

        try:
            asyncio.run(use_executor())
        finally:
            executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_bootstrap_executor_is_removed_and_shutdown_off_loop_on_startup_failure() -> None:
    class RecordingExecutor(ThreadPoolExecutor):
        def __init__(self, name: str) -> None:
            super().__init__(max_workers=1, thread_name_prefix=name)
            self.shutdown_threads: list[int] = []

        def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
            self.shutdown_threads.append(threading.get_ident())
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    executor = RecordingExecutor('bootstrap-failed-startup-test')
    shutdown_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bootstrap-cleanup-test')
    operation_started = threading.Event()
    release_operation = threading.Event()

    def blocked_operation(_session: Session) -> int:
        operation_started.set()
        if not release_operation.wait(timeout=5):
            raise TimeoutError('startup cleanup test did not release its DB thread')
        return threading.get_ident()

    async def fail_after_install() -> None:
        async with AsyncExitStack() as cleanup:
            register_bootstrap_executor_lifecycle(loop, executor, 1, cleanup, shutdown_executor)
            operation = asyncio.create_task(run_bootstrap_settings_db(blocked_operation))
            operation_started_deadline = loop.time() + 1
            while not operation_started.is_set() and loop.time() < operation_started_deadline:
                await asyncio.sleep(0.01)
            assert operation_started.is_set()
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
            cleanup.callback(release_operation.set)
            raise RuntimeError('simulated later startup failure')

    try:
        with pytest.raises(RuntimeError, match='simulated later startup failure'):
            await fail_after_install()
        with pytest.raises(RuntimeError, match='not active'):
            await run_bootstrap_db(lambda: None)
        assert executor.shutdown_threads[0] != loop_thread
        with pytest.raises(RuntimeError, match='cannot schedule new futures'):
            executor.submit(lambda: None)
    finally:
        release_operation.set()
        executor.shutdown(wait=True)
        shutdown_executor.shutdown(wait=True)
