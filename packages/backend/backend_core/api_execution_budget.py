"""API-only blocking database execution capacity."""

from __future__ import annotations

import asyncio
import contextvars
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import CancelledError as ConcurrentCancelledError, Future, ThreadPoolExecutor
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import partial
from typing import Concatenate
from weakref import WeakKeyDictionary

from fastapi import HTTPException
from sqlmodel import Session


class ApiWorkAdmissionFull(HTTPException):
    """HTTP overload response raised when a bounded API work lane is full."""

    def __init__(self, detail: str = 'API execution capacity is full') -> None:
        super().__init__(status_code=503, detail=detail, headers={'Retry-After': '1'})


class BoundedThreadPoolExecutor(ThreadPoolExecutor):
    """Thread pool with bounded running-plus-pending submissions."""

    def __init__(self, max_workers: int, *, max_pending: int, thread_name_prefix: str = '') -> None:
        if max_pending < 0:
            raise ValueError('max_pending must be non-negative')
        super().__init__(max_workers=max_workers, thread_name_prefix=thread_name_prefix)
        self.max_workers = max_workers
        self.max_pending = max_pending
        self._admission = threading.BoundedSemaphore(max_workers + max_pending)

    def submit(self, fn, /, *args, **kwargs):
        if not self._admission.acquire(blocking=False):
            raise ApiWorkAdmissionFull('API execution capacity is full')
        try:
            future = super().submit(fn, *args, **kwargs)
        except BaseException:
            self._admission.release()
            raise
        future.add_done_callback(lambda _completed: self._admission.release())
        return future


@dataclass(frozen=True)
class ApiDatabaseBudget:
    """Worker allocations bounded by the API's SQLAlchemy pool capacities."""

    database_capacity: int
    general_workers: int
    sync_workers: int
    bootstrap_workers: int

    @classmethod
    def derive(
        cls,
        *,
        settings_pool_capacity: int,
        tenant_pool_capacity: int,
        api_thread_upper_bound: int,
        sync_worker_upper_bound: int = 4,
        bootstrap_worker_upper_bound: int = 2,
    ) -> ApiDatabaseBudget:
        capacity = min(settings_pool_capacity, tenant_pool_capacity, api_thread_upper_bound)
        if capacity < 3:
            raise ValueError(
                'The API requires at least 3 pooled database connections for its general, '
                'synchronous-handler, and protected bootstrap lanes. Increase '
                'DATABASE_POOL_SIZE and/or DATABASE_MAX_OVERFLOW.'
            )

        bootstrap_workers = min(bootstrap_worker_upper_bound, max(1, capacity // 6))
        sync_workers = min(sync_worker_upper_bound, max(1, capacity // 3))
        general_workers = capacity - bootstrap_workers - sync_workers
        return cls(
            database_capacity=capacity,
            general_workers=general_workers,
            sync_workers=sync_workers,
            bootstrap_workers=bootstrap_workers,
        )


@dataclass(frozen=True)
class _BootstrapRuntime:
    executor: ThreadPoolExecutor
    admission: asyncio.Semaphore


@dataclass(frozen=True)
class _ApiBlockingRuntime:
    executor: ThreadPoolExecutor
    admission: asyncio.Semaphore


_BOOTSTRAP_RUNTIMES: WeakKeyDictionary[asyncio.AbstractEventLoop, _BootstrapRuntime] = WeakKeyDictionary()
_BOOTSTRAP_RUNTIMES_LOCK = threading.Lock()
_API_BLOCKING_RUNTIMES: WeakKeyDictionary[asyncio.AbstractEventLoop, _ApiBlockingRuntime] = WeakKeyDictionary()
_API_BLOCKING_RUNTIMES_LOCK = threading.Lock()
_BOUNDED_EXECUTOR_ADMISSIONS: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    WeakKeyDictionary[ThreadPoolExecutor, asyncio.Semaphore],
] = WeakKeyDictionary()
_BOUNDED_EXECUTOR_ADMISSIONS_LOCK = threading.Lock()


def install_api_blocking_executor(
    loop: asyncio.AbstractEventLoop,
    executor: ThreadPoolExecutor,
    workers: int,
    *,
    max_pending: int,
) -> None:
    if workers <= 0 or max_pending < 0:
        raise ValueError('API blocking executor capacity must have positive workers and non-negative pending slots')
    with _API_BLOCKING_RUNTIMES_LOCK:
        _API_BLOCKING_RUNTIMES[loop] = _ApiBlockingRuntime(executor, asyncio.Semaphore(workers + max_pending))


def remove_api_blocking_executor(loop: asyncio.AbstractEventLoop) -> None:
    with _API_BLOCKING_RUNTIMES_LOCK:
        _API_BLOCKING_RUNTIMES.pop(loop, None)


def register_api_blocking_executor_lifecycle(
    loop: asyncio.AbstractEventLoop,
    executor: BoundedThreadPoolExecutor,
    workers: int,
    max_pending: int,
    cleanup: AsyncExitStack,
    shutdown_executor: ThreadPoolExecutor,
) -> None:
    async def shutdown() -> None:
        remove_api_blocking_executor(loop)
        await loop.run_in_executor(shutdown_executor, executor.shutdown, True)

    cleanup.push_async_callback(shutdown)
    install_api_blocking_executor(loop, executor, workers, max_pending=max_pending)


def install_bootstrap_executor(
    loop: asyncio.AbstractEventLoop,
    executor: ThreadPoolExecutor,
    workers: int,
    *,
    max_pending: int | None = None,
) -> None:
    pending_limit = 2 * workers if max_pending is None else max_pending
    if pending_limit < 0:
        raise ValueError('max_pending must be non-negative')
    with _BOOTSTRAP_RUNTIMES_LOCK:
        _BOOTSTRAP_RUNTIMES[loop] = _BootstrapRuntime(executor, asyncio.Semaphore(workers + pending_limit))


def remove_bootstrap_executor(loop: asyncio.AbstractEventLoop) -> None:
    with _BOOTSTRAP_RUNTIMES_LOCK:
        _BOOTSTRAP_RUNTIMES.pop(loop, None)


def register_bootstrap_executor_lifecycle(
    loop: asyncio.AbstractEventLoop,
    executor: ThreadPoolExecutor,
    workers: int,
    cleanup: AsyncExitStack,
    shutdown_executor: ThreadPoolExecutor,
    after_shutdown: Callable[[], Awaitable[None]] | None = None,
    *,
    max_pending: int | None = None,
) -> None:
    """Install a per-loop bootstrap executor with off-loop stack cleanup."""

    async def shutdown() -> None:
        remove_bootstrap_executor(loop)
        await loop.run_in_executor(shutdown_executor, executor.shutdown, True)
        if after_shutdown is not None:
            await after_shutdown()

    cleanup.push_async_callback(shutdown)
    install_bootstrap_executor(loop, executor, workers, max_pending=max_pending)


async def run_bootstrap_db[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Queue protected API database work without blocking or rejecting callers."""
    loop = asyncio.get_running_loop()
    with _BOOTSTRAP_RUNTIMES_LOCK:
        runtime = _BOOTSTRAP_RUNTIMES.get(loop)
    if runtime is None:
        raise RuntimeError('Protected API database executor is not active for this event loop')

    requested_at = time.perf_counter()
    await runtime.admission.acquire()
    admission_wait_ms = (time.perf_counter() - requested_at) * 1000
    try:
        from backend_core.database import (
            record_api_blocking_admission_wait,
            record_api_blocking_executor_queue,
            record_api_blocking_work,
        )

        record_api_blocking_admission_wait(admission_wait_ms, lane='bootstrap')
        context = contextvars.copy_context()
        work = partial(function, *args, **kwargs)
        submitted_at = time.perf_counter()

        def invoke() -> T:
            started_at = time.perf_counter()
            record_api_blocking_executor_queue((started_at - submitted_at) * 1000, lane='bootstrap')
            try:
                return work()
            finally:
                record_api_blocking_work((time.perf_counter() - started_at) * 1000, lane='bootstrap')

        actual_future: Future[T] = runtime.executor.submit(context.run, invoke)
    except BaseException:
        runtime.admission.release()
        raise

    wrapped_future = asyncio.wrap_future(actual_future, loop=loop)
    caller_cancelled = threading.Event()

    def settle(completed: Future[T]) -> None:
        try:
            completed.result()
        except ConcurrentCancelledError:
            exception = None
        except BaseException as exc:
            exception = exc
        else:
            exception = None

        def release_admission() -> None:
            runtime.admission.release()
            if exception is not None and caller_cancelled.is_set():
                loop.call_exception_handler(
                    {
                        'message': 'Protected API database work failed after its caller was cancelled',
                        'exception': exception,
                        'future': wrapped_future,
                    }
                )

        loop.call_soon_threadsafe(release_admission)

    actual_future.add_done_callback(settle)

    try:
        return await asyncio.shield(wrapped_future)
    except asyncio.CancelledError:
        caller_cancelled.set()
        actual_future.cancel()
        raise


async def run_api_blocking[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run API work through its bounded lane, or the caller loop's lane if uninstalled.

    API lifespan installs the bounded runtime before accepting work. Other
    backend loops, such as the runtime coordinator, retain their independent
    default-executor ownership.
    """
    loop = asyncio.get_running_loop()
    with _API_BLOCKING_RUNTIMES_LOCK:
        runtime = _API_BLOCKING_RUNTIMES.get(loop)
    if runtime is None:
        context = contextvars.copy_context()
        return await loop.run_in_executor(None, context.run, partial(function, *args, **kwargs))

    requested_at = time.perf_counter()
    await runtime.admission.acquire()
    admission_wait_ms = (time.perf_counter() - requested_at) * 1000
    try:
        from backend_core.database import (
            record_api_blocking_admission_wait,
            record_api_blocking_executor_queue,
            record_api_blocking_work,
        )

        record_api_blocking_admission_wait(admission_wait_ms, lane='general')
        context = contextvars.copy_context()
        work = partial(function, *args, **kwargs)
        submitted_at = time.perf_counter()

        def invoke() -> T:
            started_at = time.perf_counter()
            record_api_blocking_executor_queue((started_at - submitted_at) * 1000, lane='general')
            try:
                return work()
            finally:
                record_api_blocking_work((time.perf_counter() - started_at) * 1000, lane='general')

        actual_future: Future[T] = runtime.executor.submit(context.run, invoke)
    except BaseException:
        runtime.admission.release()
        raise

    wrapped_future = asyncio.wrap_future(actual_future, loop=loop)
    caller_cancelled = threading.Event()

    def settle(completed: Future[T]) -> None:
        try:
            completed.result()
        except ConcurrentCancelledError:
            exception = None
        except BaseException as exc:
            exception = exc
        else:
            exception = None

        def release_admission() -> None:
            runtime.admission.release()
            if exception is not None and caller_cancelled.is_set():
                loop.call_exception_handler(
                    {
                        'message': 'API blocking work failed after its caller was cancelled',
                        'exception': exception,
                        'future': wrapped_future,
                    }
                )

        loop.call_soon_threadsafe(release_admission)

    actual_future.add_done_callback(settle)

    try:
        return await asyncio.shield(wrapped_future)
    except asyncio.CancelledError:
        caller_cancelled.set()
        actual_future.cancel()
        raise


async def run_in_bounded_executor[**P, T](
    executor: BoundedThreadPoolExecutor,
    *,
    work: Callable[[], T],
) -> T:
    """Run work in a bounded executor after asynchronously waiting for admission."""
    loop = asyncio.get_running_loop()
    with _BOUNDED_EXECUTOR_ADMISSIONS_LOCK:
        per_loop = _BOUNDED_EXECUTOR_ADMISSIONS.get(loop)
        if per_loop is None:
            per_loop = WeakKeyDictionary()
            _BOUNDED_EXECUTOR_ADMISSIONS[loop] = per_loop
        admission = per_loop.get(executor)
        if admission is None:
            admission = asyncio.Semaphore(executor.max_workers + executor.max_pending)
            per_loop[executor] = admission

    await admission.acquire()
    try:
        context = contextvars.copy_context()
        actual_future: Future[T] = executor.submit(context.run, work)
    except BaseException:
        admission.release()
        raise

    wrapped_future = asyncio.wrap_future(actual_future, loop=loop)
    caller_cancelled = threading.Event()

    def settle(completed: Future[T]) -> None:
        try:
            completed.result()
        except ConcurrentCancelledError:
            exception = None
        except BaseException as exc:
            exception = exc
        else:
            exception = None

        def release_admission() -> None:
            admission.release()
            if exception is not None and caller_cancelled.is_set():
                loop.call_exception_handler(
                    {
                        'message': 'Bounded executor work failed after its caller was cancelled',
                        'exception': exception,
                        'future': wrapped_future,
                    }
                )

        loop.call_soon_threadsafe(release_admission)

    actual_future.add_done_callback(settle)

    try:
        return await asyncio.shield(wrapped_future)
    except asyncio.CancelledError:
        caller_cancelled.set()
        actual_future.cancel()
        raise


async def run_bootstrap_settings_db[**P, T](function: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run one complete settings-session operation on a protected API thread."""
    from backend_core.database import run_settings_db

    work = partial(run_settings_db, function, *args, **kwargs)
    return await run_bootstrap_db(work)
