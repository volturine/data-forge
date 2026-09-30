from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import threading
import time
import weakref
from collections.abc import Callable
from concurrent.futures import Future as ConcurrentFuture, ThreadPoolExecutor
from functools import partial
from typing import Any

from runtime.config import settings

logger = logging.getLogger(__name__)

# Durable previews, datasource operations, and builds share the configured
# compute budget. Engine polling keeps that same width because each active
# engine has a synchronous progress stream to service.
_CONTROL_WORKERS = min(4, settings.compute_workers)
_LEASE_WORKERS = min(2, settings.compute_workers)
_CLEANUP_WORKERS = min(2, settings.compute_workers)

COMPUTE_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.compute_workers,
    thread_name_prefix="compute-work",
)
CONTROL_EXECUTOR = ThreadPoolExecutor(
    max_workers=_CONTROL_WORKERS,
    thread_name_prefix="runtime-control",
)
LEASE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_LEASE_WORKERS,
    thread_name_prefix="runtime-lease",
)
CLEANUP_EXECUTOR = ThreadPoolExecutor(
    max_workers=_CLEANUP_WORKERS,
    thread_name_prefix="runtime-cleanup",
)
ENGINE_IO_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.compute_workers,
    thread_name_prefix="engine-io",
)


class _ExecutorLane:
    def __init__(self, executor: ThreadPoolExecutor, max_pending: int) -> None:
        self.executor = executor
        self.max_pending = max_pending
        self._semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()

    def _semaphore(self, loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
        with self._lock:
            semaphore = self._semaphores.get(loop)
            if semaphore is None:
                semaphore = asyncio.Semaphore(self.max_pending)
                self._semaphores[loop] = semaphore
            return semaphore


COMPUTE_LANE = _ExecutorLane(COMPUTE_EXECUTOR, settings.compute_workers * 2)
CONTROL_LANE = _ExecutorLane(CONTROL_EXECUTOR, _CONTROL_WORKERS * 2)
LEASE_LANE = _ExecutorLane(LEASE_EXECUTOR, _LEASE_WORKERS * 2)
CLEANUP_LANE = _ExecutorLane(CLEANUP_EXECUTOR, _CLEANUP_WORKERS * 2)
ENGINE_IO_LANE = _ExecutorLane(ENGINE_IO_EXECUTOR, settings.compute_workers * 2)


async def run_compute_in_thread[T](
    function: Callable[..., T],
    /,
    *args: Any,
    cancel_work: Callable[[], object] | None = None,
    **kwargs: Any,
) -> T:
    return await _run_in_executor(COMPUTE_LANE, "compute-work", function, True, cancel_work, *args, **kwargs)


async def run_control_in_thread[T](function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await _run_in_executor(CONTROL_LANE, "runtime-control", function, True, None, *args, **kwargs)


async def run_lease_in_thread[T](function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await _run_in_executor(LEASE_LANE, "runtime-lease", function, True, None, *args, **kwargs)


async def _run_cleanup_in_thread[T](function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await _run_in_executor(CLEANUP_LANE, "runtime-cleanup", function, True, None, *args, **kwargs)


async def run_engine_io_in_thread[T](function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await _run_in_executor(ENGINE_IO_LANE, "engine-io", function, True, None, *args, **kwargs)


async def _run_in_executor[T](
    lane: _ExecutorLane,
    executor_name: str,
    function: Callable[..., T],
    diagnose_queue: bool,
    cancel_work: Callable[[], object] | None,
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    loop = asyncio.get_running_loop()
    semaphore = lane._semaphore(loop)
    await semaphore.acquire()
    submitted_at = time.perf_counter()
    context = contextvars.copy_context()
    call = partial(function, *args, **kwargs)

    def invoke() -> T:
        started_at = time.perf_counter()
        try:
            return context.run(call)
        finally:
            queue_ms = (started_at - submitted_at) * 1000
            if diagnose_queue and queue_ms >= 100:
                logger.warning(
                    "Runtime executor queue delay executor=%s operation=%s queue_ms=%.1f",
                    executor_name,
                    getattr(function, "__qualname__", type(function).__name__),
                    queue_ms,
                )

    try:
        concurrent_future = lane.executor.submit(invoke)
    except BaseException:
        semaphore.release()
        raise

    def release_admission(_future: ConcurrentFuture[T]) -> None:
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(semaphore.release)

    concurrent_future.add_done_callback(release_admission)
    future = asyncio.wrap_future(concurrent_future, loop=loop)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        cleanup = asyncio.create_task(_settle_cancelled_work(future, cancel_work))
        while True:
            try:
                await asyncio.shield(cleanup)
                break
            except asyncio.CancelledError:
                continue
        raise


async def _settle_cancelled_work[T](
    future: asyncio.Future[T],
    cancel_work: Callable[[], object] | None,
) -> None:
    if cancel_work is not None:
        try:
            await _run_cleanup_in_thread(cancel_work)
        except Exception:
            logger.warning("Runtime compute cancellation callback failed", exc_info=True)
    with contextlib.suppress(BaseException):
        await asyncio.shield(future)
