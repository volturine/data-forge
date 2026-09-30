import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from runtime.build_events import BuildCancelledError
from runtime.executors import _ExecutorLane, _run_in_executor


@pytest.mark.asyncio
async def test_executor_submission_queue_stays_bounded_under_burst() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = _ExecutorLane(executor, max_pending=3)
    started = threading.Event()
    release = threading.Event()

    def blocking_work() -> None:
        started.set()
        assert release.wait(timeout=3)

    tasks = [asyncio.create_task(_run_in_executor(lane, "test", blocking_work, False, None)) for _ in range(20)]
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0.05)
        assert executor._work_queue.qsize() <= 2
        assert lane._semaphore(asyncio.get_running_loop())._value == 0
    finally:
        release.set()
        await asyncio.gather(*tasks)
        executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_cancelled_pending_submission_does_not_consume_admission() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = _ExecutorLane(executor, max_pending=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_work() -> None:
        started.set()
        assert release.wait(timeout=3)

    first = asyncio.create_task(_run_in_executor(lane, "test", blocking_work, False, None))
    pending = asyncio.create_task(_run_in_executor(lane, "test", lambda: None, False, None))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        release.set()
        await first
        assert await _run_in_executor(lane, "test", lambda: "accepted", False, None) == "accepted"
    finally:
        release.set()
        await asyncio.gather(first, pending, return_exceptions=True)
        executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_running_cancellation_keeps_admission_until_thread_settles() -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = _ExecutorLane(executor, max_pending=1)
    started = threading.Event()
    release = threading.Event()
    later_started = threading.Event()

    def blocking_work() -> None:
        started.set()
        assert release.wait(timeout=3)

    def later_work() -> None:
        later_started.set()

    running = asyncio.create_task(_run_in_executor(lane, "test", blocking_work, False, None))
    later = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        running.cancel()
        later = asyncio.create_task(_run_in_executor(lane, "test", later_work, False, None))
        await asyncio.sleep(0.05)
        assert not later_started.is_set()
        assert lane._semaphore(asyncio.get_running_loop())._value == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        await later
        assert later_started.is_set()
    finally:
        release.set()
        await asyncio.gather(running, *(tuple([later]) if later is not None else ()), return_exceptions=True)
        executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_lease_lane_progresses_while_compute_lane_is_full() -> None:
    compute_executor = ThreadPoolExecutor(max_workers=1)
    lease_executor = ThreadPoolExecutor(max_workers=1)
    compute_lane = _ExecutorLane(compute_executor, max_pending=1)
    lease_lane = _ExecutorLane(lease_executor, max_pending=1)
    compute_started = threading.Event()
    release_compute = threading.Event()

    def blocking_compute() -> None:
        compute_started.set()
        assert release_compute.wait(timeout=3)

    compute = asyncio.create_task(_run_in_executor(compute_lane, "compute", blocking_compute, False, None))
    try:
        assert await asyncio.to_thread(compute_started.wait, 1)
        assert await _run_in_executor(lease_lane, "lease", lambda: "renewed", False, None) == "renewed"
    finally:
        release_compute.set()
        await compute
        compute_executor.shutdown(wait=True)
        lease_executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_error", [False, True])
async def test_cancelled_executor_retrieves_work_errors_and_reports_unexpected_failures(caplog, expected_error: bool) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = _ExecutorLane(executor, max_pending=1)
    started = threading.Event()
    stop_requested = threading.Event()
    release = threading.Event()
    loop_errors = []
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    caplog.set_level(logging.WARNING, logger="runtime.executors")

    def work() -> None:
        started.set()
        assert release.wait(timeout=5)
        if expected_error:
            raise BuildCancelledError("build-id")
        raise RuntimeError("Unexpected work failure")

    task = asyncio.create_task(_run_in_executor(lane, "test", work, False, stop_requested.set, expected_cancel_errors=(BuildCancelledError,)))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        assert await asyncio.to_thread(stop_requested.wait, 5)
        assert not task.done()
        assert lane._semaphore(loop)._value == 0
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert lane._semaphore(loop)._value == 1
        assert loop_errors == []
        if expected_error:
            assert caplog.records == []
        else:
            assert "Runtime work failed while cancellation was settling" in caplog.text
            assert "Unexpected work failure" in caplog.text
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown(wait=True)
        loop.set_exception_handler(original_handler)


@pytest.mark.asyncio
async def test_cancel_callback_failure_is_reported_and_work_is_still_joined(caplog) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = _ExecutorLane(executor, max_pending=1)
    started = threading.Event()
    stop_requested = threading.Event()
    release = threading.Event()

    def work() -> None:
        started.set()
        assert release.wait(timeout=5)
        raise BuildCancelledError("build-id")

    def cancel_work() -> None:
        stop_requested.set()
        raise RuntimeError("Stop request failed")

    task = asyncio.create_task(_run_in_executor(lane, "test", work, False, cancel_work, expected_cancel_errors=(BuildCancelledError,)))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        assert await asyncio.to_thread(stop_requested.wait, 5)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "Runtime compute cancellation callback failed" in caplog.text
        assert "Stop request failed" in caplog.text
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown(wait=True)
