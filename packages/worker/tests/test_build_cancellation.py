import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest

from builds import build_execution
from builds.build_live import RuntimeBuild
from dataforge_protocol import enums_pb2
from runtime import compute_service, executors
from runtime.build_events import BuildCancelledError
from runtime.compute_manager import ProcessManager
from runtime.domain.compute import schemas
from runtime.worker_runtime_client import ClaimedBuildJob


def _build() -> RuntimeBuild:
    return RuntimeBuild(
        build_id="build-rid",
        analysis_id="analysis-rid",
        analysis_name="Analysis",
        namespace="tenant-a",
        starter=schemas.BuildStarter(triggered_by="user"),
        started_at=datetime.now(UTC),
    )


def _pipeline() -> dict:
    return {
        "analysis_id": "analysis-rid",
        "tab_id": "tab-1",
        "tabs": [
            {
                "id": "tab-1",
                "name": "Output",
                "datasource": {"id": "source-rid"},
                "steps": [],
                "output": {
                    "filename": "output",
                    "build_mode": "full",
                    "iceberg": {"table_name": "output", "namespace": "outputs", "branch": "main"},
                },
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_before_callback", [False, True])
async def test_build_cancellation_hands_off_exact_job_before_joining_thread(monkeypatch, cancel_before_callback: bool) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = executors._ExecutorLane(executor, max_pending=1)
    monkeypatch.setattr(executors, "COMPUTE_LANE", lane)
    monkeypatch.setattr(compute_service, "_start_stream_tasks", lambda *_args, **_kwargs: (None, None))
    manager = create_autospec(ProcessManager, instance=True)
    ready = threading.Event()
    allow_callback = threading.Event()
    cancellation_requested = threading.Event()
    real_work_stop_requested = threading.Event()
    release_work = threading.Event()
    loop_errors = []
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    original_run_compute = compute_service.run_compute_in_thread

    async def run_compute(function, *, cancel_work, expected_cancel_errors):
        def record_cancellation() -> None:
            cancel_work()
            cancellation_requested.set()

        return await original_run_compute(function, cancel_work=record_cancellation, expected_cancel_errors=expected_cancel_errors)

    monkeypatch.setattr(compute_service, "run_compute_in_thread", run_compute)

    def cancel_engine_job(identity, *, namespace=None, job_id):
        assert identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_BUILD
        assert identity.resource_id == "build-rid"
        assert namespace == "tenant-a"
        assert job_id == "engine-job-id"
        real_work_stop_requested.set()
        return True

    manager.cancel_engine_job.side_effect = cancel_engine_job

    def export_data(*, job_started, **_kwargs):
        try:
            if cancel_before_callback:
                ready.set()
                assert allow_callback.wait(timeout=5)
            job_started({"job_id": "engine-job-id", "engine": object()})
            ready.set()
            assert real_work_stop_requested.wait(timeout=5)
            raise BuildCancelledError("build-rid")
        finally:
            assert release_work.wait(timeout=5)

    monkeypatch.setattr(compute_service, "export_data", export_data)

    async def run_build(*, manager, worker_id, claim, work_semaphore):
        await compute_service.run_analysis_build_stream(None, manager, _pipeline(), build=_build(), emitter=None)

    monkeypatch.setattr(build_execution, "_run_queued_build_job", run_build)
    claim = ClaimedBuildJob(
        job_id="durable-job-id",
        build_id="build-rid",
        namespace="tenant-a",
        claim_token="claim-token",
        lease_generation=1,
        lease_expires_at=datetime.now(UTC),
        attempt=1,
        lease_ttl_seconds=300,
    )
    task = asyncio.create_task(build_execution.run_queued_build_job(manager=manager, worker_id="worker-id", claim=claim))
    try:
        assert await asyncio.to_thread(ready.wait, 5)
        task.cancel()
        assert await asyncio.to_thread(cancellation_requested.wait, 5)
        if cancel_before_callback:
            manager.cancel_engine_job.assert_not_called()
            allow_callback.set()
        assert await asyncio.to_thread(real_work_stop_requested.wait, 5)
        assert not task.done()
        assert lane._semaphore(loop)._value == 0
        manager.shutdown_compute_worker.assert_not_called()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_work.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        manager.cancel_engine_job.assert_called_once()
        manager.shutdown_compute_worker.assert_called_once()
        shutdown_identity = manager.shutdown_compute_worker.call_args.args[0]
        assert shutdown_identity.resource_id == "build-rid"
        assert shutdown_identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_BUILD
        assert shutdown_identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE
        assert manager.shutdown_compute_worker.call_args.kwargs == {"namespace": "tenant-a"}
        await asyncio.sleep(0)
        assert lane._semaphore(loop)._value == 1
        assert loop_errors == []
    finally:
        allow_callback.set()
        release_work.set()
        real_work_stop_requested.set()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown(wait=True)
        loop.set_exception_handler(original_handler)


@pytest.mark.asyncio
async def test_build_cancelled_before_executor_starts_never_submits_engine_work(monkeypatch) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    lane = executors._ExecutorLane(executor, max_pending=1)
    monkeypatch.setattr(executors, "COMPUTE_LANE", lane)
    manager = create_autospec(ProcessManager, instance=True)
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    cancellation_requested = threading.Event()
    original_run_compute = compute_service.run_compute_in_thread

    def block_executor() -> None:
        blocker_started.set()
        assert release_blocker.wait(timeout=5)

    blocker = executor.submit(block_executor)

    async def run_compute(function, *, cancel_work, expected_cancel_errors):
        def record_cancellation() -> None:
            cancel_work()
            cancellation_requested.set()

        return await original_run_compute(function, cancel_work=record_cancellation, expected_cancel_errors=expected_cancel_errors)

    monkeypatch.setattr(compute_service, "run_compute_in_thread", run_compute)
    export = create_autospec(compute_service.export_data)
    monkeypatch.setattr(compute_service, "export_data", export)
    task = asyncio.create_task(compute_service.run_analysis_build_stream(None, manager, _pipeline(), build=_build(), emitter=None))
    try:
        assert await asyncio.to_thread(blocker_started.wait, 5)
        async with asyncio.timeout(5):
            while executor._work_queue.qsize() == 0:
                await asyncio.sleep(0)
        task.cancel()
        assert await asyncio.to_thread(cancellation_requested.wait, 5)
        assert not task.done()
        release_blocker.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        export.assert_not_called()
        manager.cancel_engine_job.assert_not_called()
        blocker.result()
    finally:
        release_blocker.set()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown(wait=True)
