from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import pytest

from builds import build_execution
from dataforge_protocol import analysis_pb2, compute_pb2, enums_pb2
from runtime import compute_request_runtime, executors
from runtime.compute_manager import ProcessManager
from runtime.executors import _ExecutorLane, run_compute_in_thread


class _JobTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._started: dict[str, threading.Event] = {}
        self._finished: dict[str, threading.Event] = {}
        self._release: dict[str, threading.Event] = {}
        self.cancelled_jobs: list[str] = []
        self.thread_ids: set[int] = set()
        self.peak_active = 0

    def started_event(self, job_id: str) -> threading.Event:
        with self._lock:
            return self._started.setdefault(job_id, threading.Event())

    def finished_event(self, job_id: str) -> threading.Event:
        with self._lock:
            return self._finished.setdefault(job_id, threading.Event())

    def start(self, job_id: str, release: threading.Event) -> None:
        with self._lock:
            self._active.add(job_id)
            self._release[job_id] = release
            self.thread_ids.add(threading.get_ident())
            self.peak_active = max(self.peak_active, len(self._active))
            self._started.setdefault(job_id, threading.Event()).set()

    def finish(self, job_id: str) -> None:
        with self._lock:
            self._active.discard(job_id)
            self._release.pop(job_id, None)
            self._finished.setdefault(job_id, threading.Event()).set()

    def record_cancel(self, job_id: str) -> None:
        with self._lock:
            self.cancelled_jobs.append(job_id)

    def release(self, job_id: str) -> None:
        with self._lock:
            event = self._release.get(job_id)
        if event is not None:
            event.set()

    def release_all(self) -> None:
        with self._lock:
            events = list(self._release.values())
        for event in events:
            event.set()


class _GatedComputeWorker:
    def __init__(self, tracker: _JobTracker, resource_config: dict[str, object] | None = None) -> None:
        self.resource_config = resource_config or {}
        self.effective_resources = {"max_threads": 1}
        self._tracker = tracker
        self._lock = threading.Lock()
        self._alive = False
        self._current_job_id: str | None = None
        self._job_release: threading.Event | None = None

    @property
    def current_job_id(self) -> str | None:
        with self._lock:
            return self._current_job_id

    @property
    def last_known_alive(self) -> bool:
        return self._alive

    @property
    def process_id(self) -> None:
        return None

    def bind_capacity_notifier(self, _notifier: Callable[[], None]) -> None:
        return None

    def start(self) -> None:
        self._alive = True

    def is_process_alive(self) -> bool:
        return self._alive

    def check_health(self) -> bool:
        return self._alive

    def run_job(self, job_id: str) -> None:
        release = threading.Event()
        with self._lock:
            if self._current_job_id is not None:
                raise AssertionError("one compute worker cannot execute two jobs at once")
            self._current_job_id = job_id
            self._job_release = release
        self._tracker.start(job_id, release)
        released = release.wait(timeout=10)
        with self._lock:
            self._current_job_id = None
            self._job_release = None
        self._tracker.finish(job_id)
        if not released:
            raise AssertionError(f"compute job {job_id} was not released")

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            if self._current_job_id != job_id or self._job_release is None:
                return False
            self._tracker.record_cancel(job_id)
            self._job_release.set()
            return True

    def cancel_current_job(self) -> None:
        with self._lock:
            if self._job_release is not None:
                self._job_release.set()

    def shutdown(self) -> None:
        job_id = self.current_job_id
        self._alive = False
        self.cancel_current_job()
        if job_id is not None and not self._tracker.finished_event(job_id).wait(timeout=2):
            raise AssertionError(f"compute job {job_id} did not stop during worker shutdown")


def _pipeline(analysis_id: str, datasource_id: str = "datasource-1") -> analysis_pb2.AnalysisPipelinePayload:
    pipeline = analysis_pb2.AnalysisPipelinePayload(analysis_id=analysis_id)
    tab = pipeline.tabs.add(id="tab-1")
    tab.datasource.id = datasource_id
    tab.output.result_id = "output-1"
    tab.output.filename = "output.parquet"
    tab.output.format = enums_pb2.EXPORT_FORMAT_PARQUET
    return pipeline


def _preview_claim(request_id: str, analysis_id: str) -> compute_request_runtime.ClaimedComputeRequest:
    command = compute_pb2.ComputeCommand(
        preview=compute_pb2.StepPreviewCommand(
            analysis_id=analysis_id,
            target_step_id="source",
            analysis_pipeline=_pipeline(analysis_id),
            row_limit=100,
            page=1,
        )
    )
    return compute_request_runtime.ClaimedComputeRequest(
        id=request_id,
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command_envelope=compute_pb2.ComputeCommandEnvelope(command=command),
        worker_id="worker-test",
        claim_token=f"claim-{request_id}",
        lease_generation=1,
        lease_ttl_seconds=300,
    )


def _datasource_preview_claim(request_id: str, datasource_id: str) -> compute_request_runtime.ClaimedComputeRequest:
    identity = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        datasource_id=datasource_id,
        resource_id=datasource_id,
    )
    command = compute_pb2.ComputeCommand(
        preview=compute_pb2.StepPreviewCommand(
            target_step_id="source",
            analysis_pipeline=_pipeline("analysis-for-tab", datasource_id),
            engine_identity=identity,
            row_limit=100,
            page=1,
        )
    )
    return compute_request_runtime.ClaimedComputeRequest(
        id=request_id,
        namespace="default",
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command_envelope=compute_pb2.ComputeCommandEnvelope(command=command),
        worker_id="worker-test",
        claim_token=f"claim-{request_id}",
        lease_generation=1,
        lease_ttl_seconds=300,
    )


def _manager(tracker: _JobTracker) -> ProcessManager:
    return ProcessManager(
        engine_factory=lambda _identity, config: cast(Any, _GatedComputeWorker(tracker, config)),
        warm_worker_target=0,
        reconcile_docker_containers=False,
    )


async def _keep_lease_alive(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
    lease_confirmed.set()
    await stop_event.wait()


async def _wait_for_thread_event(event: threading.Event) -> None:
    await asyncio.wait_for(asyncio.to_thread(event.wait, 3), timeout=4)


async def _wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_request_and_build_jobs_share_manager_capacity_and_shutdown_bypasses_it(monkeypatch) -> None:
    monkeypatch.setattr(compute_request_runtime.settings, "compute_workers", 2)
    compute_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="capacity-test")
    monkeypatch.setattr(executors, "COMPUTE_LANE", _ExecutorLane(compute_executor, max_pending=2))
    tracker = _JobTracker()
    manager = _manager(tracker)
    real_execute_sync = compute_request_runtime._execute_request_sync
    real_run_compute = compute_request_runtime.run_compute_in_thread
    real_run_shutdown = compute_request_runtime.run_shutdown_in_thread
    compute_submissions: list[str] = []
    shutdown_submissions: list[str] = []

    async def track_request_submission(function, *args, **kwargs):
        compute_submissions.append(cast(compute_request_runtime.ClaimedComputeRequest, args[0]).id)
        return await real_run_compute(function, *args, **kwargs)

    async def track_shutdown_submission(function, *args, **kwargs):
        if getattr(function, "__name__", None) == "execute_and_record_terminal":
            shutdown_submissions.append(cast(compute_request_runtime.ClaimedComputeRequest, args[0]).id)
        return await real_run_shutdown(function, *args, **kwargs)

    def execute_sync(claim, process_manager, terminal_publication_started=None) -> bool:
        if claim.kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE:
            return real_execute_sync(claim, process_manager, terminal_publication_started)
        identity = compute_request_runtime._compute_worker_identity_for_claimed(claim)
        assert identity is not None
        with process_manager.acquire_engine(identity) as engine:
            cast(_GatedComputeWorker, engine).run_job(claim.id)
        return False

    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", _keep_lease_alive)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", execute_sync)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", track_request_submission)
    monkeypatch.setattr(compute_request_runtime, "run_shutdown_in_thread", track_shutdown_submission)
    completed: list[compute_pb2.ComputeResponse] = []

    class Client:
        def close(self) -> None:
            return None

        def complete_compute_request(self, **kwargs: object) -> None:
            completed.append(cast(compute_pb2.ComputeResponse, kwargs["response"]))

    monkeypatch.setattr(compute_request_runtime, "worker_runtime_client", Client)
    request_a = _preview_claim("request-a", "analysis-a")
    request_a_again = _preview_claim("request-a-again", "analysis-a")
    request_b = _preview_claim("request-b", "analysis-b")
    tasks: list[asyncio.Task[object]] = []
    build_identity = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
        build_id="build-c",
        resource_id="build-c",
    )

    async def execute_build() -> None:
        async with build_execution._admitted_build_work_slot(manager, build_identity, namespace="default"):

            def build_job() -> None:
                with manager.acquire_engine(build_identity) as engine:
                    cast(_GatedComputeWorker, engine).run_job("build-c")

            await run_compute_in_thread(build_job)

    try:
        tasks.append(asyncio.create_task(compute_request_runtime._execute_request(request_a, manager)))
        await _wait_for_thread_event(tracker.started_event(request_a.id))

        tasks.append(asyncio.create_task(compute_request_runtime._execute_request(request_a_again, manager)))
        identity_a = compute_request_runtime._compute_worker_identity_for_claimed(request_a)
        assert identity_a is not None
        key_a = manager._key(identity_a)
        await _wait_until(lambda: (slot := manager._engine_job_slots.get(key_a)) is not None and slot.references == 2)
        assert not tracker.started_event(request_a_again.id).is_set()
        assert compute_submissions == [request_a.id]

        tasks.append(asyncio.create_task(compute_request_runtime._execute_request(request_b, manager)))
        await _wait_for_thread_event(tracker.started_event(request_b.id))
        assert compute_submissions == [request_a.id, request_b.id]
        assert len(tracker.thread_ids) == 2
        assert tracker.peak_active == 2

        build_task = asyncio.create_task(execute_build())
        tasks.append(build_task)
        build_key = manager._key(build_identity)

        def build_is_waiting() -> bool:
            with manager._capacity_changed:
                return any(waiter.key == build_key for waiter in manager._spawn_waiters)

        await _wait_until(build_is_waiting)
        assert not tracker.started_event("build-c").is_set()

        shutdown_command = compute_pb2.ComputeCommand(
            shutdown_engine=compute_pb2.ComputeWorkerLifecycleCommand(engine_identity=compute_request_runtime._compute_worker_identity_for_claimed(request_b))
        )
        shutdown_claim = compute_request_runtime.ClaimedComputeRequest(
            id="shutdown-b",
            namespace="default",
            kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
            command_envelope=compute_pb2.ComputeCommandEnvelope(command=shutdown_command),
            worker_id="worker-test",
            claim_token="claim-shutdown-b",
            lease_generation=1,
            lease_ttl_seconds=300,
        )
        tasks.append(asyncio.create_task(compute_request_runtime._execute_request(shutdown_claim, manager)))
        await _wait_for_thread_event(tracker.started_event("build-c"))
        await _wait_until(tasks[2].done)
        await asyncio.wait_for(tasks[-1], timeout=3)
        assert completed and completed[-1].WhichOneof("response") == "ack"
        assert shutdown_claim.id not in compute_submissions
        assert shutdown_submissions == [shutdown_claim.id]
        assert tracker.peak_active == 2

        tracker.release(request_a.id)
        await _wait_for_thread_event(tracker.started_event(request_a_again.id))
        assert tracker.peak_active == 2

        tracker.release("build-c")
        tracker.release(request_a_again.id)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
        assert tracker.peak_active == 2
    finally:
        tracker.release_all()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        manager.shutdown_all()
        compute_executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_queued_same_datasource_build_releases_only_its_rid_slot_when_cancelled(monkeypatch) -> None:
    monkeypatch.setattr(compute_request_runtime.settings, "compute_workers", 2)
    compute_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shared-rid-test")
    monkeypatch.setattr(executors, "COMPUTE_LANE", _ExecutorLane(compute_executor, max_pending=2))
    tracker = _JobTracker()
    manager = _manager(tracker)
    real_run_compute = compute_request_runtime.run_compute_in_thread
    real_run_build_compute = build_execution.run_compute_in_thread
    compute_submissions: list[str] = []
    build_submissions: list[str] = []

    async def track_request_submission(function, *args, **kwargs):
        compute_submissions.append(cast(compute_request_runtime.ClaimedComputeRequest, args[0]).id)
        return await real_run_compute(function, *args, **kwargs)

    async def track_build_submission(function, *args, **kwargs):
        build_submissions.append("build")
        return await real_run_build_compute(function, *args, **kwargs)

    def execute_sync(claim, process_manager, _terminal_publication_started=None) -> bool:
        identity = compute_request_runtime._compute_worker_identity_for_claimed(claim)
        assert identity is not None
        with process_manager.acquire_engine(identity) as engine:
            cast(_GatedComputeWorker, engine).run_job(claim.id)
        return False

    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", _keep_lease_alive)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", execute_sync)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", track_request_submission)
    monkeypatch.setattr(build_execution, "run_compute_in_thread", track_build_submission)

    shared_claim = _datasource_preview_claim("request-shared-datasource", "datasource-shared")
    other_claim = _preview_claim("request-other-rid", "analysis-other")
    shared_identity = compute_request_runtime._compute_worker_identity_for_claimed(shared_claim)
    assert shared_identity is not None
    build_identity = shared_identity
    shared_key = manager._key(shared_identity)
    tasks: list[asyncio.Task[None]] = []

    async def execute_build() -> None:
        async with build_execution._admitted_build_work_slot(manager, build_identity, namespace="default"):

            def build_job() -> None:
                with manager.acquire_engine(build_identity) as engine:
                    cast(_GatedComputeWorker, engine).run_job("queued-build")

            await build_execution.run_compute_in_thread(build_job)

    try:
        tasks.append(asyncio.create_task(compute_request_runtime._execute_request(shared_claim, manager)))
        await _wait_for_thread_event(tracker.started_event(shared_claim.id))

        build_task = asyncio.create_task(execute_build())
        tasks.append(build_task)
        await _wait_until(lambda: (slot := manager._engine_job_slots.get(shared_key)) is not None and slot.references == 2)
        assert build_submissions == []

        tasks.append(asyncio.create_task(compute_request_runtime._execute_request(other_claim, manager)))
        await _wait_for_thread_event(tracker.started_event(other_claim.id))
        assert compute_submissions == [shared_claim.id, other_claim.id]
        assert build_submissions == []

        build_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await build_task

        slot = manager._engine_job_slots[shared_key]
        assert slot.lock.locked()
        assert slot.references == 1
        assert manager._request_reservations[shared_key] == 1
        assert tracker.cancelled_jobs == []
        assert manager.get_engine_info(shared_identity) is not None
        assert build_submissions == []

        tracker.release(shared_claim.id)
        tracker.release(other_claim.id)
        await asyncio.wait_for(asyncio.gather(tasks[0], tasks[2]), timeout=3)
    finally:
        tracker.release_all()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        manager.shutdown_all()
        compute_executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_lease_loss_cancels_exact_job_and_joins_before_releasing_manager_slots(monkeypatch) -> None:
    monkeypatch.setattr(compute_request_runtime.settings, "compute_workers", 1)
    tracker = _JobTracker()
    execution_joined = threading.Event()

    class JoinCheckingManager(ProcessManager):
        def release_engine_job_slot(self, identity, *, namespace=None) -> None:
            assert execution_joined.is_set()
            super().release_engine_job_slot(identity, namespace=namespace)

        def release_engine_request(self, identity, *, namespace=None) -> None:
            assert execution_joined.is_set()
            super().release_engine_request(identity, namespace=namespace)

    manager = JoinCheckingManager(
        engine_factory=lambda _identity, config: cast(Any, _GatedComputeWorker(tracker, config)),
        warm_worker_target=0,
        reconcile_docker_containers=False,
    )
    lease_loss = asyncio.Event()
    real_run_compute_in_thread = compute_request_runtime.run_compute_in_thread

    async def track_executor_join(function, *args, **kwargs):
        def record_join(*inner_args, **inner_kwargs):
            try:
                return function(*inner_args, **inner_kwargs)
            finally:
                execution_joined.set()

        return await real_run_compute_in_thread(record_join, *args, **kwargs)

    async def lose_lease(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        lease_confirmed.set()
        await lease_loss.wait()
        raise compute_request_runtime.ComputeRequestLeaseLost("request lease expired")

    def execute_sync(claim, process_manager, _terminal_publication_started=None) -> bool:
        identity = compute_request_runtime._compute_worker_identity_for_claimed(claim)
        assert identity is not None
        with process_manager.acquire_engine(identity) as engine:
            cast(_GatedComputeWorker, engine).run_job(claim.id)
        return False

    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", lose_lease)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", track_executor_join)
    monkeypatch.setattr(compute_request_runtime, "_execute_request_sync", execute_sync)
    claim = _preview_claim("request-lease-loss", "analysis-lease-loss")
    identity = compute_request_runtime._compute_worker_identity_for_claimed(claim)
    assert identity is not None

    try:
        task = asyncio.create_task(compute_request_runtime._execute_request(claim, manager))
        await _wait_for_thread_event(tracker.started_event(claim.id))
        lease_loss.set()
        with pytest.raises(compute_request_runtime.ComputeRequestLeaseLost, match="request lease expired"):
            await asyncio.wait_for(task, timeout=3)

        assert tracker.cancelled_jobs == [claim.id]
        assert execution_joined.is_set()
        assert manager.get_engine_info(identity) is not None
        assert manager._request_reservations == {}
        assert manager._engine_job_slots == {}
    finally:
        tracker.release_all()
        manager.shutdown_all()
