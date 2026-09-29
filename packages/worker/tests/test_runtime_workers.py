import asyncio
import importlib.util
import threading
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from typing import Any, cast

import pytest

from builds import build_execution
from dataforge_protocol import compute_pb2, enums_pb2, worker_runtime_pb2
from runtime import compute_request_runtime
from runtime.compute_request_runtime import _lease_renewal_delay
from runtime.datasource_delete_runtime import datasource_delete_hub
from runtime.domain.compute_requests.live import ComputeRequestWake, request_hub
from runtime.live_hubs import VersionHub
from runtime.protocol_mapping import datetime_to_timestamp
from runtime.worker_runtime import NamespaceRecovery, RuntimeNamespaceDirectory, build_worker_loop
from runtime.worker_runtime_client import BackendWorkerRpcError, ClaimedBuildJob, WorkerRuntimeClient, _claim_lease_timing, run_worker_heartbeat_loop


@pytest.fixture(autouse=True)
def active_runtime_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNTIME_COORDINATOR_GENERATION", "1")


def test_runtime_notification_hub_preserves_distinct_namespace_targets() -> None:
    hub = VersionHub()
    hub.publish("default")
    hub.publish("other")
    hub.publish("default")

    assert hub.payloads_since(0) == ["default", "other"]


@pytest.mark.asyncio
async def test_datasource_delete_wakeup_returns_without_recovery_delay() -> None:
    from runtime.datasource_delete_runtime import _wait_for_delete_wakeup_or_recovery

    await datasource_delete_hub.clear()
    stop_event = asyncio.Event()
    wake_version = datasource_delete_hub.version()
    task = asyncio.create_task(_wait_for_delete_wakeup_or_recovery(stop_event, wake_version))
    await asyncio.sleep(0)
    datasource_delete_hub.publish("default")

    assert await asyncio.wait_for(task, timeout=1) == (wake_version + 1, False)


def test_worker_heartbeat_reregisters_and_resynchronizes_after_api_loss() -> None:
    class StopSignal:
        def __init__(self) -> None:
            self.waits = 0

        def wait(self, _timeout: float) -> bool:
            self.waits += 1
            return self.waits >= 3

    class Client:
        def __init__(self) -> None:
            self.heartbeats = 0
            self.registrations: list[dict[str, object]] = []

        def heartbeat_worker(self, **_kwargs) -> None:
            self.heartbeats += 1
            if self.heartbeats == 1:
                raise RuntimeError("API process restarted")

        def register_worker(self, **kwargs) -> None:
            self.registrations.append(kwargs)

    client = Client()
    resynchronized = threading.Event()
    run_worker_heartbeat_loop(
        client=cast(WorkerRuntimeClient, client),
        stop_signal=cast(threading.Event, StopSignal()),
        worker_id="manager-1",
        kind="BUILD_MANAGER",
        hostname="test-host",
        pid=123,
        capacity=8,
        heartbeat_seconds=0.001,
        on_reconnected=resynchronized.set,
    )

    assert resynchronized.wait(1.0)
    assert client.heartbeats == 2
    assert client.registrations[0]["worker_id"] == "manager-1"


def test_engine_run_creation_retries_only_when_idempotency_key_is_present() -> None:
    class Stub:
        def __init__(self) -> None:
            self.requests = []

        def CreateEngineRun(self, request, *, timeout: float, metadata):
            self.requests.append((request, timeout, metadata))
            return SimpleNamespace(id="run-id")

    client = object.__new__(WorkerRuntimeClient)
    client._target = "runtime.example:50051"
    client._token = "test-token"
    client._timeout_seconds = 120.0
    client._stub = Stub()
    calls: list[object] = []

    def call(fn):
        calls.append("call")
        return fn()

    def call_with_reconnect(fn, *, operation):
        calls.append(("reconnect", operation))
        return fn()

    client._call = call
    client._call_with_reconnect = call_with_reconnect

    common = {
        "namespace": "default",
        "analysis_id": "analysis-1",
        "datasource_id": "datasource-1",
        "kind": "preview",
        "status": "running",
        "request_json": {"target_step_id": "source"},
    }
    assert client.create_engine_run(**common, idempotency_key="request-1") == "run-id"
    assert calls == [("reconnect", "CreateEngineRun")]
    request, timeout, _metadata = client._stub.requests[-1]
    assert request.idempotency_key == "request-1"
    assert timeout == 15.0

    calls.clear()
    assert client.create_engine_run(**common) == "run-id"
    assert calls == ["call"]
    request, _timeout, _metadata = client._stub.requests[-1]
    assert not request.HasField("idempotency_key")


def test_compute_lease_renewal_delay_is_bounded() -> None:
    assert _lease_renewal_delay(300) == 10.0
    assert _lease_renewal_delay(9) == 3.0
    assert _lease_renewal_delay(1) == pytest.approx(1 / 3)
    assert _lease_renewal_delay(0.005) < 0.005


def test_compute_lease_renewals_are_deterministically_spread() -> None:
    request_ids = [f"compute-request-{index}" for index in range(32)]
    delays = [_lease_renewal_delay(300, request_id) for request_id in request_ids]

    assert len(set(delays)) == len(request_ids)
    assert min(delays) >= 5.0
    assert max(delays) <= 10.0
    assert delays == [_lease_renewal_delay(300, request_id) for request_id in request_ids]


@pytest.mark.asyncio
async def test_namespace_recovery_deduplicates_concurrent_attempts() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def reconcile_expired_compute_requests(self, *, namespace: str) -> int:
            self.calls.append(namespace)
            return 0

    client = Client()
    recovery = NamespaceRecovery(
        client.reconcile_expired_compute_requests,
        work_name="compute requests",
        interval_seconds=5.0,
    )

    await asyncio.gather(*(recovery.reconcile("default") for _ in range(8)))

    assert client.calls == ["default"]


@pytest.mark.asyncio
async def test_compute_dispatch_fans_out_same_namespace_requests_within_budget(monkeypatch) -> None:
    await request_hub.clear()
    active = 0
    peak_active = 0
    calls = 0
    all_started = asyncio.Event()
    release = asyncio.Event()
    all_finished = asyncio.Event()

    async def fake_run_once(**_kwargs) -> bool:
        nonlocal active, peak_active, calls
        calls += 1
        if calls == 7:
            all_finished.set()
        if calls <= 6:
            active += 1
            peak_active = max(peak_active, active)
            if active == 4:
                all_started.set()
            await release.wait()
            active -= 1
        return False

    class Directory:
        async def next_namespace(self) -> None:
            return None

    monkeypatch.setattr(compute_request_runtime, "_run_once", fake_run_once)
    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(
        compute_request_runtime.compute_request_loop(
            stop_event,
            worker_id="coordinator",
            manager=cast(Any, object()),
            allowed_kinds=compute_request_runtime.ACTIVE_REQUEST_KINDS,
            poll_for_work=False,
            max_concurrency=4,
            namespace_directory=cast(Any, Directory()),
        )
    )
    await asyncio.sleep(0)
    duplicate = ComputeRequestWake("request-0", "default", enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW)
    request_hub.publish(duplicate)
    request_hub.publish(duplicate)  # direct wake plus outbox delivery
    for index in range(1, 6):
        request_hub.publish(ComputeRequestWake(f"request-{index}", "default", enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW))

    await asyncio.wait_for(all_started.wait(), timeout=1)
    assert peak_active == 4
    release.set()
    await asyncio.wait_for(all_finished.wait(), timeout=1)
    stop_event.set()
    await asyncio.wait_for(loop_task, timeout=1)
    assert calls == 7  # six unique requests and one final queue-drain claim


@pytest.mark.asyncio
async def test_compute_response_wake_drains_queued_namespace_immediately(monkeypatch) -> None:
    await request_hub.clear()
    calls: list[dict[str, object]] = []
    stop_event = asyncio.Event()

    async def fake_run_once(**kwargs) -> bool:
        calls.append(kwargs)
        stop_event.set()
        return False

    class Directory:
        async def next_namespace(self) -> None:
            return None

    monkeypatch.setattr(compute_request_runtime, "_run_once", fake_run_once)
    loop_task = asyncio.create_task(
        compute_request_runtime.compute_request_loop(
            stop_event,
            worker_id="coordinator",
            manager=cast(Any, object()),
            allowed_kinds=compute_request_runtime.ACTIVE_REQUEST_KINDS,
            poll_for_work=False,
            max_concurrency=1,
            namespace_directory=cast(Any, Directory()),
        )
    )
    await asyncio.sleep(0)
    request_hub.publish(ComputeRequestWake(None, "tenant-a", None))

    await asyncio.wait_for(loop_task, timeout=1)

    assert len(calls) == 1
    assert calls[0]["namespace"] == "tenant-a"


@pytest.mark.asyncio
async def test_compute_recovery_drains_all_pending_namespaces_in_one_poll(monkeypatch) -> None:
    await request_hub.clear()
    stop_event = asyncio.Event()
    recovered: list[str] = []
    snapshots = 0

    async def fake_run_once(*, namespace: str, **_kwargs) -> bool:
        recovered.append(namespace)
        if len(recovered) == 2:
            stop_event.set()
        return False

    class Directory:
        async def snapshot(self) -> list[str]:
            nonlocal snapshots
            snapshots += 1
            return ["tenant-a", "tenant-b"]

    monkeypatch.setattr(compute_request_runtime, "_run_once", fake_run_once)
    loop_task = asyncio.create_task(
        compute_request_runtime.compute_request_loop(
            stop_event,
            worker_id="coordinator",
            manager=cast(Any, object()),
            allowed_kinds=compute_request_runtime.ACTIVE_REQUEST_KINDS,
            poll_for_work=True,
            max_concurrency=2,
            namespace_directory=cast(Any, Directory()),
        )
    )

    await asyncio.wait_for(loop_task, timeout=1)

    assert snapshots == 1
    assert set(recovered) == {"tenant-a", "tenant-b"}


def test_worker_control_rpcs_have_a_short_deadline() -> None:
    calls: list[tuple[str, float]] = []
    pending_kinds: list[tuple[str, ...]] = []

    class Stub:
        def ClaimBuildJob(self, _request, *, timeout, metadata):  # noqa: N802
            del metadata
            calls.append(("claim-build", timeout))
            return worker_runtime_pb2.WorkerClaimBuildJobResponse()

        def ClaimComputeRequest(self, _request, *, timeout, metadata):  # noqa: N802
            del metadata
            calls.append(("claim-compute", timeout))
            return worker_runtime_pb2.WorkerClaimComputeRequestResponse()

        def GetQueuedBuildJobCount(self, _request, *, timeout, metadata):  # noqa: N802
            del metadata
            calls.append(("queued-count", timeout))
            return worker_runtime_pb2.CountResponse()

        def ReconcileExpiredBuildJobs(self, _request, *, timeout, metadata):  # noqa: N802
            del metadata
            calls.append(("reconcile-build", timeout))
            return worker_runtime_pb2.CountResponse()

        def ListPendingRuntimeWorkNamespaces(self, request, *, timeout, metadata):  # noqa: N802
            del metadata
            calls.append(("pending-namespaces", timeout))
            pending_kinds.append(tuple(request.kinds))
            return worker_runtime_pb2.WorkerNamespacesResponse()

    client = WorkerRuntimeClient(target="unused:50051", token="token", timeout_seconds=120.0)
    client._stub = Stub()  # type: ignore[assignment]

    assert client.claim_build_job(worker_id="worker", namespace="default") is None
    assert (
        client.claim_compute_request(
            worker_id="worker",
            allowed_kinds=frozenset({enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW}),
            namespace="default",
        )
        is None
    )
    assert client.queued_build_job_count(namespace="default") == 0
    assert client.reconcile_expired_build_jobs(namespace="default") == 0
    assert client.pending_runtime_work_namespaces() == []
    assert client.pending_runtime_work_namespaces(work_kinds=("build",)) == []

    assert calls == [
        ("claim-build", 15.0),
        ("claim-compute", 15.0),
        ("queued-count", 15.0),
        ("reconcile-build", 15.0),
        ("pending-namespaces", 15.0),
        ("pending-namespaces", 15.0),
    ]
    assert pending_kinds == [(), ("build",)]


def test_claim_lease_deadline_uses_remaining_database_expiry() -> None:
    claim_time = datetime(2030, 1, 1, tzinfo=UTC)
    expiry = claim_time + timedelta(seconds=20)

    remaining, deadline = _claim_lease_timing(
        expiry,
        20,
        wall_now=claim_time + timedelta(seconds=17),
        monotonic_now=100.0,
    )

    assert remaining == pytest.approx(3.0)
    assert deadline == pytest.approx(103.0)
    with pytest.raises(ValueError, match="expired before it reached the worker"):
        _claim_lease_timing(expiry, 20, wall_now=expiry, monotonic_now=100.0)


def test_build_claim_client_accounts_for_time_spent_in_claim_rpc() -> None:
    class Stub:
        def ClaimBuildJob(self, _request, *, timeout, metadata):  # noqa: N802 - generated gRPC method
            del timeout, metadata
            return worker_runtime_pb2.WorkerClaimBuildJobResponse(
                job=worker_runtime_pb2.WorkerClaimedBuildJob(
                    job_id="job-1",
                    build_id="build-1",
                    namespace="default",
                    claim_token="token",
                    lease_generation=1,
                    lease_expires_at=datetime_to_timestamp(datetime.now(UTC) + timedelta(seconds=3)),
                    attempt=1,
                    lease_ttl_seconds=20,
                )
            )

    client = WorkerRuntimeClient(target="unused:50051", token="token")
    client._stub = Stub()  # type: ignore[assignment]

    claim = client.claim_build_job(worker_id="worker", namespace="default")

    assert claim is not None
    assert 0 < claim.lease_ttl_seconds <= 3
    assert claim.lease_deadline_monotonic is not None
    assert 0 < claim.lease_deadline_monotonic - time.monotonic() <= claim.lease_ttl_seconds


def test_compute_claim_client_accounts_for_time_spent_in_claim_rpc() -> None:
    class Stub:
        def ClaimComputeRequest(self, _request, *, timeout, metadata):  # noqa: N802 - generated gRPC method
            del timeout, metadata
            return worker_runtime_pb2.WorkerClaimComputeRequestResponse(
                request=worker_runtime_pb2.WorkerClaimedComputeRequest(
                    id="request-1",
                    namespace="default",
                    command=compute_pb2.ComputeCommandEnvelope(kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW),
                    claim_token="token",
                    lease_generation=1,
                    lease_expires_at=datetime_to_timestamp(datetime.now(UTC) + timedelta(seconds=3)),
                    attempt=1,
                    lease_ttl_seconds=20,
                )
            )

    client = WorkerRuntimeClient(target="unused:50051", token="token")
    client._stub = Stub()  # type: ignore[assignment]

    claim = client.claim_compute_request(
        worker_id="worker",
        allowed_kinds=frozenset({enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW}),
        namespace="default",
    )

    assert claim is not None
    assert 0 < claim.lease_ttl_seconds <= 3
    assert claim.lease_deadline_monotonic is not None
    assert 0 < claim.lease_deadline_monotonic - time.monotonic() <= claim.lease_ttl_seconds


class FakeWorkerRuntimeClient:
    def __init__(self, jobs: list[ClaimedBuildJob] | None = None) -> None:
        self.jobs = list(jobs or [])
        self.calls: list[tuple[str, object]] = []
        self.call_threads: list[tuple[str, int]] = []
        self.lease_active = True
        self.renewal_errors = 0
        self.claim_delay_seconds = 0.0

    def register_worker(self, **kwargs) -> None:
        self.calls.append(("register_worker", kwargs))
        self.call_threads.append(("register_worker", threading.get_ident()))

    def heartbeat_worker(self, **kwargs) -> None:
        self.calls.append(("heartbeat_worker", kwargs))

    def stop_worker(self, **kwargs) -> None:
        self.calls.append(("stop_worker", kwargs))
        self.call_threads.append(("stop_worker", threading.get_ident()))

    def claim_build_job(self, *, worker_id: str, namespace: str) -> ClaimedBuildJob | None:
        self.calls.append(("claim_build_job", {"worker_id": worker_id, "namespace": namespace}))
        time.sleep(self.claim_delay_seconds)
        return self.jobs.pop(0) if self.jobs else None

    def pending_runtime_work_namespaces(self, *, work_kinds: tuple[str, ...] = ()) -> list[str]:
        self.calls.append(("pending_runtime_work_namespaces", work_kinds))
        return ["default"]

    def fail_build_job(self, **kwargs) -> bool:
        self.calls.append(("fail_build_job", kwargs))
        return True

    def finalize_build_job(self, **kwargs) -> bool:
        self.calls.append(("finalize_build_job", kwargs))
        return True

    def renew_build_job_lease(self, **kwargs) -> int | None:
        self.calls.append(("renew_build_job_lease", kwargs))
        if self.renewal_errors > 0:
            self.renewal_errors -= 1
            raise ConnectionError("temporary renewal failure")
        if not self.lease_active:
            return None
        return 300

    def release_build_worker_jobs(self, **kwargs) -> int:
        self.calls.append(("release_build_worker_jobs", kwargs))
        return 0

    def queued_build_job_count(self, **kwargs) -> int:
        self.calls.append(("queued_build_job_count", kwargs))
        return 0

    def reconcile_expired_build_jobs(self, **kwargs) -> int:
        self.calls.append(("reconcile_expired_build_jobs", kwargs))
        return 0

    def reconcile_expired_compute_requests(self, **kwargs) -> int:
        self.calls.append(("reconcile_expired_compute_requests", kwargs))
        return 0

    def idle_build_worker_pids(self) -> set[int]:
        self.calls.append(("idle_build_worker_pids", None))
        return set()


def _load_runtime_process():
    path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("worker_main_for_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load worker runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_process = _load_runtime_process()


@pytest.mark.asyncio
async def test_worker_runtime_stops_old_generation_when_coordinator_fences_it(monkeypatch) -> None:
    class Client:
        def get_coordinator_generation(self) -> int:
            return 8

    process_stop_event = asyncio.Event()
    generation_stop_event = asyncio.Event()
    monkeypatch.setattr(runtime_process, "_COORDINATOR_GENERATION_POLL_SECONDS", 0.001)

    await asyncio.wait_for(
        runtime_process._watch_coordinator_generation(
            process_stop_event,
            generation_stop_event,
            cast(WorkerRuntimeClient, Client()),
            generation=7,
        ),
        timeout=1.0,
    )

    assert generation_stop_event.is_set()


@pytest.mark.asyncio
async def test_worker_generation_waits_for_runtime_teardown_after_monitor_error(monkeypatch) -> None:
    teardown_finished = asyncio.Event()

    async def runtime(stop_event: asyncio.Event, **_kwargs) -> None:
        await stop_event.wait()
        await asyncio.sleep(0.01)
        teardown_finished.set()

    async def failing_monitor(*_args) -> None:
        raise RuntimeError("generation monitor failed")

    monkeypatch.setattr(runtime_process, "run_runtime_coordinator", runtime)
    monkeypatch.setattr(runtime_process, "_watch_coordinator_generation", failing_monitor)

    with pytest.raises(RuntimeError, match="generation monitor failed"):
        await runtime_process._run_worker_generation(asyncio.Event(), cast(WorkerRuntimeClient, object()), 7)

    assert teardown_finished.is_set()


@pytest.mark.asyncio
async def test_supervised_runtime_loop_restarts_after_transient_failure(caplog) -> None:
    stop_event = asyncio.Event()
    restarted = asyncio.Event()
    attempts = 0

    async def run() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary runtime RPC failure")
        restarted.set()
        await stop_event.wait()

    task = asyncio.create_task(runtime_process._supervise_runtime_loop(stop_event, "test-loop", run))
    await asyncio.wait_for(restarted.wait(), timeout=2)
    stop_event.set()
    await task

    assert attempts == 2
    assert "Runtime loop test-loop failed; restarting" in caplog.text


def _job() -> ClaimedBuildJob:
    return ClaimedBuildJob(
        job_id=str(uuid.uuid4()),
        build_id=str(uuid.uuid4()),
        namespace="default",
        claim_token=str(uuid.uuid4()),
        lease_generation=1,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        attempt=1,
        lease_ttl_seconds=300,
    )


@pytest.mark.asyncio
async def test_cancelled_build_only_stops_its_exclusive_engine(monkeypatch) -> None:
    claim = _job()
    calls: list[tuple[str, object]] = []

    class Manager:
        def cancel_engine_job(self, identity, **kwargs) -> bool:
            calls.append(("cancel_engine_job", (identity, kwargs)))
            return True

        def shutdown_engine(self, identity, **kwargs) -> None:
            calls.append(("shutdown_engine", (identity, kwargs)))

        def shutdown_all(self) -> None:
            calls.append(("shutdown_all", None))

    async def cancelled_job(**_kwargs) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(build_execution, "_run_queued_build_job", cancelled_job)

    with pytest.raises(asyncio.CancelledError):
        await build_execution.run_queued_build_job(manager=cast(Any, Manager()), worker_id="worker-1", claim=claim)

    assert [name for name, _ in calls] == ["cancel_engine_job", "shutdown_engine"]
    assert calls[0][1][1] == {"namespace": claim.namespace}
    assert calls[1][1][1] == {"namespace": claim.namespace}


@pytest.mark.asyncio
async def test_build_waiting_for_worker_admission_does_not_hold_execution_permit() -> None:
    admission_started = asyncio.Event()
    release_admission = asyncio.Event()
    execution_started = asyncio.Event()
    work_semaphore = asyncio.Semaphore(1)

    class Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "default"
            assert priority == build_execution.ENGINE_ADMISSION_PRIORITY_LIFECYCLE
            admission_started.set()
            await release_admission.wait()
            return True

        def reserve_engine_request(self, _identity, *, namespace):
            assert namespace == "default"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "default"

        def release_spawn_admission(self, _identity, *, namespace, owned):
            assert namespace == "default"
            assert owned is True

    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_BUILD,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
        build_id="build-gated",
        resource_id="build-gated",
    )

    async def execute_after_admission() -> None:
        async with build_execution._admitted_build_work_slot(
            cast(Any, Manager()),
            identity,
            namespace="default",
            work_semaphore=work_semaphore,
        ):
            execution_started.set()

    task = asyncio.create_task(execute_after_admission())
    await asyncio.wait_for(admission_started.wait(), timeout=1)

    # A build parked on worker admission leaves the shared running-work budget
    # available to unrelated work.
    assert await asyncio.wait_for(work_semaphore.acquire(), timeout=0.1)
    work_semaphore.release()
    release_admission.set()
    await asyncio.wait_for(execution_started.wait(), timeout=1)
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_engine_build_does_not_wait_for_duplicate_execution_permit() -> None:
    execution_started = asyncio.Event()
    work_semaphore = asyncio.Semaphore(0)

    class Manager:
        async def await_engine_request_admission(self, _identity, *, namespace, priority):
            assert namespace == "default"
            assert priority == build_execution.ENGINE_ADMISSION_PRIORITY_LIFECYCLE
            return True

        def reserve_engine_request(self, _identity, *, namespace):
            assert namespace == "default"

        def release_engine_request(self, _identity, *, namespace):
            assert namespace == "default"

        def release_spawn_admission(self, _identity, *, namespace, owned):
            assert namespace == "default"
            assert owned is True

    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_BUILD,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
        build_id="build-with-manager-capacity",
        resource_id="build-with-manager-capacity",
    )

    async def execute_engine_build() -> None:
        async with build_execution._admitted_build_work_slot(
            cast(Any, Manager()),
            identity,
            namespace="default",
            work_semaphore=work_semaphore,
        ):
            execution_started.set()

    task = asyncio.create_task(execute_engine_build())
    await asyncio.wait_for(execution_started.wait(), timeout=1)
    assert work_semaphore.locked()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_build_worker_loop_tracks_runtime_worker_lifecycle() -> None:
    job = _job()
    client = FakeWorkerRuntimeClient([job])
    recovery = NamespaceRecovery(
        client.reconcile_expired_build_jobs,
        work_name="expired build jobs",
        interval_seconds=5.0,
    )
    stop_event = asyncio.Event()
    seen: list[tuple[str, str]] = []
    process_idle_states: list[bool] = []

    async def run_job(claim: ClaimedBuildJob) -> None:
        seen.append((claim.build_id, claim.namespace))
        assert process_idle_states[-1] is False
        await asyncio.sleep(0.05)
        stop_event.set()

    task = asyncio.create_task(
        build_worker_loop(
            stop_event,
            "worker-1",
            run_job,
            client=cast(WorkerRuntimeClient, client),
            heartbeat_seconds=0.01,
            process_idle_signal=process_idle_states.append,
            recovery=recovery,
        )
    )
    await asyncio.gather(task)

    assert seen == [(job.build_id, "default")]
    assert process_idle_states[0] is False
    assert process_idle_states[-1] is True
    assert (
        "finalize_build_job",
        {
            "job_id": job.job_id,
            "build_id": job.build_id,
            "namespace": job.namespace,
            "worker_id": "worker-1",
            "claim_token": job.claim_token,
            "lease_generation": job.lease_generation,
        },
    ) in client.calls
    assert any(name == "renew_build_job_lease" for name, _ in client.calls)
    assert any(name == "reconcile_expired_build_jobs" for name, _ in client.calls)
    assert any(name == "stop_worker" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_build_claim_rpc_does_not_block_the_runtime_event_loop() -> None:
    client = FakeWorkerRuntimeClient()
    client.claim_delay_seconds = 0.2

    async def run_job(_job: ClaimedBuildJob) -> None:
        raise AssertionError("No build job should be claimed")

    class Directory:
        async def next_namespace(self) -> str:
            return "default"

    loop = asyncio.get_running_loop()
    tick_scheduled = loop.time()
    tick_ran = asyncio.Event()
    loop.call_later(0.005, tick_ran.set)
    task = asyncio.create_task(
        build_worker_loop(
            asyncio.Event(),
            "manager",
            run_job,
            client=cast(WorkerRuntimeClient, client),
            namespace_directory=cast(Any, Directory()),
            idle_exit_seconds=0.1,
            poll_interval_seconds=0.05,
            announce_worker=False,
        )
    )
    await asyncio.wait_for(tick_ran.wait(), timeout=0.1)
    assert loop.time() - tick_scheduled < 0.1
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_build_worker_loop_exits_after_one_job_when_max_jobs_set() -> None:
    first = _job()
    second = _job()
    client = FakeWorkerRuntimeClient([first, second])
    stop_event = asyncio.Event()
    seen: list[str] = []

    async def run_job(claim: ClaimedBuildJob) -> None:
        assert claim.namespace == "default"
        seen.append(claim.build_id)

    await build_worker_loop(stop_event, "worker-once", run_job, client=cast(WorkerRuntimeClient, client), max_jobs=1)

    assert len(seen) == 1


@pytest.mark.asyncio
async def test_build_dispatcher_runs_jobs_concurrently_without_parallel_claimers() -> None:
    jobs = [replace(_job(), job_id=f"job-{index}", build_id=f"build-{index}") for index in range(3)]
    client = FakeWorkerRuntimeClient(jobs)
    all_started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak_active = 0

    async def run_job(_claim: ClaimedBuildJob) -> None:
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        if active == 3:
            all_started.set()
        await release.wait()
        active -= 1

    task = asyncio.create_task(
        build_worker_loop(
            asyncio.Event(),
            "worker-pool",
            run_job,
            client=cast(WorkerRuntimeClient, client),
            capacity=3,
            max_jobs=3,
            poll_interval_seconds=0.01,
        )
    )

    await asyncio.wait_for(all_started.wait(), timeout=1)
    assert sum(name == "claim_build_job" for name, _ in client.calls) == 3
    release.set()
    await asyncio.wait_for(task, timeout=1)

    assert peak_active == 3
    assert sum(name == "claim_build_job" for name, _ in client.calls) == 3


@pytest.mark.asyncio
async def test_build_worker_dispatches_claimed_work_to_its_capacity_gate() -> None:
    job = _job()
    client = FakeWorkerRuntimeClient([job])
    stop_event = asyncio.Event()
    seen: list[str] = []
    release = asyncio.Event()

    async def run_job(claim: ClaimedBuildJob) -> None:
        seen.append(claim.build_id)
        await release.wait()

    task = asyncio.create_task(
        build_worker_loop(
            stop_event,
            "worker-capacity",
            run_job,
            client=cast(WorkerRuntimeClient, client),
            max_jobs=1,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.001)
    assert seen == [job.build_id]
    assert any(name == "claim_build_job" for name, _ in client.calls)
    release.set()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_build_worker_cancels_claimed_dispatch_when_stopping() -> None:
    client = FakeWorkerRuntimeClient([_job()])
    stop_event = asyncio.Event()
    started = asyncio.Event()

    async def run_job(_claim: ClaimedBuildJob) -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        build_worker_loop(
            stop_event,
            "worker-capacity-stop",
            run_job,
            client=cast(WorkerRuntimeClient, client),
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1)

    assert any(name == "claim_build_job" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_build_worker_loop_uses_manager_namespace_hints_without_scanning() -> None:
    job = replace(_job(), namespace="tenant-a")
    client = FakeWorkerRuntimeClient([job])
    namespace_hints = Queue()
    namespace_hints.put("tenant-a")
    seen: list[str] = []

    async def run_job(claim: ClaimedBuildJob) -> None:
        seen.append(claim.namespace)

    await build_worker_loop(
        asyncio.Event(),
        "worker-hinted",
        run_job,
        client=cast(WorkerRuntimeClient, client),
        max_jobs=1,
        namespace_hint_queue=namespace_hints,
    )

    assert seen == ["tenant-a"]
    assert not any(name == "runtime_namespaces" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_runtime_namespace_directory_requests_only_its_work_kind() -> None:
    requested_kinds: list[tuple[str, ...]] = []

    class FilteredClient:
        def pending_runtime_work_namespaces(self, *, work_kinds: tuple[str, ...]) -> list[str]:
            requested_kinds.append(work_kinds)
            return ["build-namespace"]

    directory = RuntimeNamespaceDirectory(
        cast(WorkerRuntimeClient, FilteredClient()),
        work_kinds=("build",),
    )

    assert await directory.next_namespace() == "build-namespace"
    assert requested_kinds == [("build",)]


@pytest.mark.asyncio
async def test_build_worker_loop_stops_execution_when_lease_is_lost() -> None:
    job = _job()
    client = FakeWorkerRuntimeClient([job])
    stop_event = asyncio.Event()
    execution_stopped = asyncio.Event()
    client.lease_active = False

    async def run_job(_claim: ClaimedBuildJob) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            execution_stopped.set()

    await build_worker_loop(
        stop_event,
        "worker-lost",
        run_job,
        client=cast(WorkerRuntimeClient, client),
        heartbeat_seconds=0.001,
        max_jobs=1,
    )

    assert execution_stopped.is_set()
    assert any(name == "renew_build_job_lease" for name, _ in client.calls)
    assert not any(name == "finalize_build_job" for name, _ in client.calls)
    assert not any(name == "fail_build_job" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_build_worker_loop_finishes_claimed_job_when_parent_requests_shutdown() -> None:
    job = _job()
    client = FakeWorkerRuntimeClient([job])
    stop_event = asyncio.Event()
    execution_started = asyncio.Event()
    execution_stopped = asyncio.Event()

    async def run_job(_claim: ClaimedBuildJob) -> None:
        execution_started.set()
        await stop_event.wait()
        execution_stopped.set()

    task = asyncio.create_task(
        build_worker_loop(
            stop_event,
            "worker-shutdown",
            run_job,
            client=cast(WorkerRuntimeClient, client),
            heartbeat_seconds=0.01,
        )
    )
    await asyncio.wait_for(execution_started.wait(), timeout=1)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1)

    assert execution_stopped.is_set()
    assert (
        "finalize_build_job",
        {
            "job_id": job.job_id,
            "build_id": job.build_id,
            "namespace": job.namespace,
            "worker_id": "worker-shutdown",
            "claim_token": job.claim_token,
            "lease_generation": job.lease_generation,
        },
    ) in client.calls


@pytest.mark.asyncio
async def test_build_worker_loop_retries_renewal_transport_error_before_expiry() -> None:
    job = replace(_job(), lease_ttl_seconds=1)
    client = FakeWorkerRuntimeClient([job])
    client.renewal_errors = 1
    stop_event = asyncio.Event()

    async def run_job(_claim: ClaimedBuildJob) -> None:
        await asyncio.sleep(0.5)
        stop_event.set()

    await build_worker_loop(
        stop_event,
        "worker-retry",
        run_job,
        client=cast(WorkerRuntimeClient, client),
        heartbeat_seconds=0.005,
    )

    renewals = [call for call in client.calls if call[0] == "renew_build_job_lease"]
    assert len(renewals) >= 2
    assert any(name == "finalize_build_job" for name, _ in client.calls)
    assert not any(name == "fail_build_job" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_build_worker_loop_does_not_start_after_claim_deadline() -> None:
    job = replace(_job(), lease_ttl_seconds=1)
    client = FakeWorkerRuntimeClient([job])
    client.claim_delay_seconds = 1.05
    started = False

    async def run_job(_claim: ClaimedBuildJob) -> None:
        nonlocal started
        started = True

    await build_worker_loop(
        asyncio.Event(),
        "worker-expired-claim",
        run_job,
        client=cast(WorkerRuntimeClient, client),
        max_jobs=1,
    )

    assert started is False
    assert not any(name == "finalize_build_job" for name, _ in client.calls)
    assert not any(name == "fail_build_job" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_run_runtime_coordinator_shares_compute_budget_across_lanes(
    monkeypatch,
) -> None:
    coordinator_thread_id = threading.get_ident()
    calls: list[tuple[str, object]] = []
    manager_kwargs: dict[str, object] = {}
    stop_event = asyncio.Event()
    client = FakeWorkerRuntimeClient()

    monkeypatch.setattr(runtime_process, "worker_runtime_client", lambda: client)
    monkeypatch.setattr(runtime_process, "coordinator_id", lambda: "manager-1")
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)
    monkeypatch.setattr(runtime_process, "validate_engine_runtime_readiness", lambda: None)
    monkeypatch.setattr(runtime_process, "reconcile_deployment_containers", lambda **_kwargs: 0)

    class FakeDataPlaneServer:
        async def stop(self, *, grace: float | None = None) -> None:
            calls.append(("data_plane_stop", grace))

    monkeypatch.setattr(
        runtime_process,
        "start_data_plane_grpc_server_in_thread",
        lambda: FakeDataPlaneServer(),
    )

    async def fake_compute_request_loop(local_stop, **kwargs) -> None:
        calls.append(("compute_request_loop", kwargs))
        await local_stop.wait()

    monkeypatch.setattr(runtime_process, "compute_request_loop", fake_compute_request_loop)
    monkeypatch.setattr(runtime_process, "compute_request_worker_count", lambda: 4)

    async def capture_build_execution(claim, **execution_kwargs):
        calls.append(("run_queued_build_job", {"claim": claim, **execution_kwargs}))

    monkeypatch.setattr(build_execution, "run_queued_build_job", capture_build_execution)

    async def fake_datasource_delete_loop(local_stop, **_kwargs) -> None:
        await local_stop.wait()

    monkeypatch.setattr(runtime_process, "datasource_delete_loop", fake_datasource_delete_loop)
    monkeypatch.setattr(
        runtime_process,
        "ProcessManager",
        lambda **kwargs: (
            manager_kwargs.update(kwargs)
            or SimpleNamespace(
                wait_for_warm_workers_ready=lambda **_kwargs: True,
                _warm_workers=[],
                shutdown_all=lambda: calls.append(("shutdown_all", None)),
            )
        ),
    )

    async def fake_build_worker_loop(local_stop, worker_id, run_job, **kwargs) -> None:
        calls.append(("build_worker_loop", {"worker_id": worker_id, **kwargs}))
        assert callable(run_job)
        await run_job(_job())
        local_stop.set()

    monkeypatch.setattr(runtime_process, "build_worker_loop", fake_build_worker_loop)

    await runtime_process.run_runtime_coordinator(stop_event=stop_event)

    build_calls = [payload for name, payload in calls if name == "build_worker_loop"]
    assert [payload["worker_id"] for payload in build_calls] == ["manager-1"]
    assert all(payload["capacity"] == 4 for payload in build_calls)
    assert all(payload["announce_worker"] is False for payload in build_calls)
    register_calls = [payload for name, payload in client.calls if name == "register_worker"]
    assert register_calls
    register_payload = register_calls[0]
    assert isinstance(register_payload, dict)
    assert register_payload["worker_id"] == "manager-1"
    assert register_payload["kind"] == "coordinator"
    assert register_payload["capacity"] == runtime_process.settings.compute_workers
    registration_thread = next(thread_id for name, thread_id in client.call_threads if name == "register_worker")
    assert registration_thread != coordinator_thread_id
    assert manager_kwargs["warm_worker_target"] == runtime_process.settings.compute_warm_workers
    request_lane_kwargs = [payload for name, payload in calls if name == "compute_request_loop"]
    assert [payload["allowed_kinds"] for payload in request_lane_kwargs] == [
        runtime_process.ACTIVE_REQUEST_KINDS,
        runtime_process.ENGINE_SHUTDOWN_REQUEST_KINDS,
    ]
    assert [payload["poll_for_work"] for payload in request_lane_kwargs] == [True, True]
    assert [payload["max_concurrency"] for payload in request_lane_kwargs] == [4, 4]
    assert len({id(payload["claim_semaphore"]) for payload in request_lane_kwargs}) == 2
    shared_compute_budget = request_lane_kwargs[0]["work_semaphore"]
    assert request_lane_kwargs[1]["work_semaphore"] is None
    assert "work_semaphore" not in build_calls[0]
    build_execution_calls = [payload for name, payload in calls if name == "run_queued_build_job"]
    assert build_execution_calls[0]["work_semaphore"] is shared_compute_budget
    assert ("stop_worker", {"worker_id": "manager-1", "timeout_seconds": 2.0}) in client.calls
    stop_thread = next(thread_id for name, thread_id in client.call_threads if name == "stop_worker")
    assert stop_thread != coordinator_thread_id


@pytest.mark.asyncio
async def test_runtime_coordinator_cleans_up_when_registration_fails(monkeypatch) -> None:
    cleanup: list[str] = []
    client = FakeWorkerRuntimeClient()

    def fail_registration(**kwargs) -> None:
        client.calls.append(("register_worker", kwargs))
        raise ConnectionError("coordinator unavailable")

    client.register_worker = fail_registration
    monkeypatch.setattr(runtime_process, "worker_runtime_client", lambda: client)
    monkeypatch.setattr(runtime_process, "coordinator_id", lambda: "manager-1")
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)
    monkeypatch.setattr(runtime_process, "validate_engine_runtime_readiness", lambda: None)
    monkeypatch.setattr(runtime_process, "reconcile_deployment_containers", lambda **_kwargs: 0)
    monkeypatch.setattr(
        runtime_process,
        "create_snapshot_notifier",
        lambda **_kwargs: SimpleNamespace(close=lambda: cleanup.append("notifier")),
    )

    class FakeDataPlaneServer:
        async def stop(self, *, grace: float | None = None) -> None:
            cleanup.append("data-plane")

    monkeypatch.setattr(
        runtime_process,
        "start_data_plane_grpc_server_in_thread",
        lambda: FakeDataPlaneServer(),
    )

    async def start_listener():
        return object()

    async def stop_listener(_listener) -> None:
        cleanup.append("listener")

    async def serve_notifications(_listener, stop_event, _handler) -> None:
        await stop_event.wait()

    monkeypatch.setattr(runtime_process, "start_runtime_listener", start_listener)
    monkeypatch.setattr(runtime_process, "stop_runtime_listener", stop_listener)
    monkeypatch.setattr(runtime_process, "serve_runtime_notifications", serve_notifications)

    class FakeManager:
        warm_worker_count = 0

        def __init__(self, **_kwargs) -> None:
            pass

        def wait_for_warm_workers_ready(self, **_kwargs) -> bool:
            return True

        def shutdown_all(self) -> None:
            cleanup.append("manager")

    monkeypatch.setattr(runtime_process, "ProcessManager", FakeManager)

    with pytest.raises(ConnectionError, match="coordinator unavailable"):
        await runtime_process.run_runtime_coordinator(stop_event=asyncio.Event())

    assert cleanup == ["listener", "data-plane", "manager", "notifier"]


def test_runtime_clients_share_one_channel_per_target(monkeypatch) -> None:
    """Creating a client per hop must not create a connection per hop."""
    from runtime import worker_runtime_client as client_module

    monkeypatch.setattr(client_module, "_channels", {})
    monkeypatch.setenv("INTERNAL_GRPC_TARGET", "api:50051")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "token")

    first = client_module.client_from_env()
    second = client_module.client_from_env()

    assert first._channel is second._channel
    monkeypatch.delenv("RUNTIME_COORDINATOR_GENERATION", raising=False)
    with pytest.raises(RuntimeError, match="active RUNTIME_COORDINATOR_GENERATION"):
        first._metadata()
    monkeypatch.setenv("RUNTIME_COORDINATOR_GENERATION", "7")
    assert ("x-runtime-coordinator-generation", "7") in first._metadata()

    # Releasing a client leaves the shared channel usable for the next hop.
    first.close()
    assert client_module.client_from_env()._channel is second._channel


def test_coordinator_generation_rpc_bootstraps_and_validates_generation(monkeypatch) -> None:
    class CoordinatorStub:
        def __init__(self) -> None:
            self.active_generation = 7
            self.bootstrap_metadata = None
            self.assertion: tuple[int, tuple[tuple[str, str], ...]] | None = None

        def GetCoordinatorGeneration(self, _request, *, timeout: float, metadata):
            self.bootstrap_metadata = metadata
            return SimpleNamespace(generation=self.active_generation)

        def AssertCoordinatorGeneration(self, request, *, timeout: float, metadata):
            self.assertion = (request.generation, metadata)
            return SimpleNamespace(generation=self.active_generation)

    client = object.__new__(WorkerRuntimeClient)
    client._target = "runtime:50051"
    client._token = "internal-token"
    client._timeout_seconds = 15.0
    client._coordinator_stub = CoordinatorStub()
    client._call = lambda operation: operation()
    monkeypatch.delenv("RUNTIME_COORDINATOR_GENERATION", raising=False)

    assert client.get_coordinator_generation() == 7
    assert client._coordinator_stub.bootstrap_metadata == (("x-internal-token", "internal-token"),)

    client.assert_coordinator_generation(7)
    assert client._coordinator_stub.assertion == (
        7,
        (("x-internal-token", "internal-token"), ("x-runtime-coordinator-generation", "7")),
    )

    client._coordinator_stub.active_generation = 8
    with pytest.raises(BackendWorkerRpcError, match="fenced by 8"):
        client.assert_coordinator_generation(7)
