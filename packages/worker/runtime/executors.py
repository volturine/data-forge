from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from runtime.config import settings

logger = logging.getLogger(__name__)

# Durable previews, datasource operations, and builds share the same admitted
# work budget. Blocking orchestration/RPC calls have their own bounded pool so
# engine event polling cannot consume the threads needed to renew leases or
# discover newly queued work.
COMPUTE_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.compute_workers,
    thread_name_prefix="compute-work",
)
CONTROL_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.compute_workers,
    thread_name_prefix="runtime-control",
)
LEASE_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.compute_workers,
    thread_name_prefix="runtime-lease",
)
ENGINE_IO_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.compute_workers,
    thread_name_prefix="engine-io",
)


async def run_compute_in_thread[T](
    function: Callable[..., T],
    /,
    *args: Any,
    cancel_work: Callable[[], object] | None = None,
    **kwargs: Any,
) -> T:
    return await _run_in_executor(COMPUTE_EXECUTOR, "compute-work", function, True, cancel_work, *args, **kwargs)


async def run_control_in_thread[T](function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await _run_in_executor(CONTROL_EXECUTOR, "runtime-control", function, True, None, *args, **kwargs)


async def run_lease_in_thread[T](function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await _run_in_executor(LEASE_EXECUTOR, "runtime-lease", function, True, None, *args, **kwargs)


async def run_engine_io_in_thread[T](function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    return await _run_in_executor(ENGINE_IO_EXECUTOR, "engine-io", function, True, None, *args, **kwargs)


async def _run_in_executor[T](
    executor: ThreadPoolExecutor,
    executor_name: str,
    function: Callable[..., T],
    diagnose_queue: bool,
    cancel_work: Callable[[], object] | None,
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    loop = asyncio.get_running_loop()
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

    future = loop.run_in_executor(executor, invoke)
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
            await run_control_in_thread(cancel_work)
        except Exception:
            logger.warning("Runtime compute cancellation callback failed", exc_info=True)
    with contextlib.suppress(BaseException):
        await asyncio.shield(future)
