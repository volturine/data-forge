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

from sqlmodel import Session


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


_BOOTSTRAP_RUNTIMES: WeakKeyDictionary[asyncio.AbstractEventLoop, _BootstrapRuntime] = WeakKeyDictionary()
_BOOTSTRAP_RUNTIMES_LOCK = threading.Lock()


def install_bootstrap_executor(loop: asyncio.AbstractEventLoop, executor: ThreadPoolExecutor, workers: int) -> None:
    with _BOOTSTRAP_RUNTIMES_LOCK:
        _BOOTSTRAP_RUNTIMES[loop] = _BootstrapRuntime(executor, asyncio.Semaphore(workers))


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
) -> None:
    """Install a per-loop bootstrap executor with off-loop stack cleanup."""

    async def shutdown() -> None:
        remove_bootstrap_executor(loop)
        await loop.run_in_executor(shutdown_executor, executor.shutdown, True)
        if after_shutdown is not None:
            await after_shutdown()

    cleanup.push_async_callback(shutdown)
    install_bootstrap_executor(loop, executor, workers)


async def run_bootstrap_db[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Admit protected API database work before submitting it to its own executor."""
    loop = asyncio.get_running_loop()
    with _BOOTSTRAP_RUNTIMES_LOCK:
        runtime = _BOOTSTRAP_RUNTIMES.get(loop)
    if runtime is None:
        raise RuntimeError('Protected API database executor is not active for this event loop')

    requested_at = time.perf_counter()
    await runtime.admission.acquire()
    admission_wait_ms = (time.perf_counter() - requested_at) * 1000
    try:
        from backend_core.database import record_database_admission_wait

        record_database_admission_wait(admission_wait_ms)
        context = contextvars.copy_context()
        work = partial(function, *args, **kwargs)
        actual_future: Future[T] = runtime.executor.submit(context.run, work)
    except BaseException:
        runtime.admission.release()
        raise

    wrapped_future = asyncio.wrap_future(actual_future, loop=loop)

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
            if exception is not None and wrapped_future.cancelled():
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
        return await wrapped_future
    except asyncio.CancelledError:
        actual_future.cancel()
        raise


async def run_bootstrap_settings_db[**P, T](function: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run one complete settings-session operation on a protected API thread."""
    from backend_core.database import run_settings_db

    work = partial(run_settings_db, function, *args, **kwargs)
    return await run_bootstrap_db(work)
