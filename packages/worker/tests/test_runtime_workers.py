import asyncio
import importlib.util
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from runtime.worker_runtime_client import ClaimedBuildJob, WorkerRuntimeClient
from runtime.worker_runtime import build_worker_loop


class FakeWorkerRuntimeClient:
    def __init__(self, jobs: list[ClaimedBuildJob] | None = None) -> None:
        self.jobs = list(jobs or [])
        self.calls: list[tuple[str, object]] = []
        self.lease_active = True
        self.renewal_errors = 0
        self.claim_delay_seconds = 0.0

    def register_worker(self, **kwargs) -> None:
        self.calls.append(("register_worker", kwargs))

    def heartbeat_worker(self, **kwargs) -> None:
        self.calls.append(("heartbeat_worker", kwargs))

    def stop_worker(self, **kwargs) -> None:
        self.calls.append(("stop_worker", kwargs))

    def claim_build_job(self, *, worker_id: str) -> ClaimedBuildJob | None:
        self.calls.append(("claim_build_job", worker_id))
        time.sleep(self.claim_delay_seconds)
        return self.jobs.pop(0) if self.jobs else None

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

    def queued_build_job_count(self) -> int:
        self.calls.append(("queued_build_job_count", None))
        return 0

    def dispatch_runtime_outbox(self) -> int:
        self.calls.append(("dispatch_runtime_outbox", None))
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
async def test_build_worker_loop_tracks_runtime_worker_lifecycle() -> None:
    job = _job()
    client = FakeWorkerRuntimeClient([job])
    stop_event = asyncio.Event()
    seen: list[tuple[str, str]] = []

    async def run_job(claim: ClaimedBuildJob) -> None:
        seen.append((claim.build_id, claim.namespace))
        await asyncio.sleep(0.05)
        stop_event.set()

    task = asyncio.create_task(
        build_worker_loop(
            stop_event,
            "worker-1",
            run_job,
            client=cast(WorkerRuntimeClient, client),
            heartbeat_seconds=0.01,
        )
    )
    await asyncio.gather(task)

    assert seen == [(job.build_id, "default")]
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
    assert any(name == "stop_worker" for name, _ in client.calls)


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


def test_wait_for_child_stop_joins_once_after_ack(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 123
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            calls.append(("join", timeout))
            self._alive = False

    class FakeStoppedSignal:
        def wait(self, timeout=None) -> bool:
            calls.append(("wait", timeout))
            return True

    monotonic_values = iter([10.0, 10.0, 10.0])
    monkeypatch.setattr(runtime_process.time, "monotonic", lambda: next(monotonic_values))

    child = runtime_process.ManagedWorkerProcess(
        process=FakeProcess(),
        stop_signal=SimpleNamespace(),
        stopped_signal=FakeStoppedSignal(),
    )

    assert runtime_process._wait_for_child_stop(child, timeout_seconds=5.0, require_ack=True) is True
    assert calls == [("wait", 5.0), ("join", 5.0), ("join", None)]


def test_stop_worker_process_escalates_when_child_does_not_ack() -> None:
    calls: list[tuple[str, object]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 321
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            calls.append(("join", timeout))

        def terminate(self) -> None:
            calls.append(("terminate", None))
            self._alive = False

        def kill(self) -> None:
            calls.append(("kill", None))
            self._alive = False

    class FakeStopSignal:
        def set(self) -> None:
            calls.append(("stop", None))

    class FakeStoppedSignal:
        def wait(self, timeout=None) -> bool:
            calls.append(("wait", timeout))
            return False

    child = runtime_process.ManagedWorkerProcess(
        process=FakeProcess(),
        stop_signal=FakeStopSignal(),
        stopped_signal=FakeStoppedSignal(),
    )

    runtime_process._stop_worker_process(child)

    names = [name for name, _ in calls]
    assert names[0] == "stop"
    assert calls[1][0] == "wait"
    assert calls[1][1] == pytest.approx(runtime_process._CHILD_COOPERATIVE_STOP_SECONDS, abs=1e-3)
    terminate_join = next(timeout for name, timeout in calls if name == "join" and timeout is not None)
    assert terminate_join == pytest.approx(runtime_process._CHILD_TERMINATE_SECONDS, abs=1e-3)
    assert ("join", None) in calls
    assert "terminate" in names
    assert "kill" not in names


def test_next_idle_child_pid_skips_busy_workers(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def is_alive(self) -> bool:
            return True

        def join(self, timeout=None) -> None:
            del timeout

    children = {
        101: runtime_process.ManagedWorkerProcess(
            process=FakeProcess(101),
            stop_signal=SimpleNamespace(),
            stopped_signal=SimpleNamespace(),
        ),
        202: runtime_process.ManagedWorkerProcess(
            process=FakeProcess(202),
            stop_signal=SimpleNamespace(),
            stopped_signal=SimpleNamespace(),
        ),
    }

    client = FakeWorkerRuntimeClient()
    monkeypatch.setattr(client, "idle_build_worker_pids", lambda: {202})

    assert runtime_process._next_idle_child_pid(children, client=client) == 202

    monkeypatch.setattr(client, "idle_build_worker_pids", set)

    assert runtime_process._next_idle_child_pid(children, client=client) is None


@pytest.mark.asyncio
async def test_run_build_worker_process_passes_worker_runtime_client(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    stop_event = asyncio.Event()
    client = FakeWorkerRuntimeClient()

    async def fake_build_worker_loop(local_stop: asyncio.Event, worker_id: str, run_job, **kwargs) -> None:
        calls.append(("build_worker_loop", worker_id))
        assert local_stop is stop_event
        assert callable(run_job)
        assert kwargs["client"] is client
        assert kwargs["max_jobs"] is None
        local_stop.set()

    monkeypatch.setattr(
        runtime_process.settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)
    monkeypatch.setattr(runtime_process, "worker_runtime_client", lambda: client)
    monkeypatch.setattr(runtime_process, "build_worker_loop", fake_build_worker_loop)
    monkeypatch.setattr(runtime_process, "build_worker_id", lambda: "worker-1")
    monkeypatch.setattr(
        runtime_process,
        "ProcessManager",
        lambda **kwargs: SimpleNamespace(shutdown_all=lambda: calls.append(("shutdown_all", None))),
    )

    await runtime_process.run_build_worker_process(stop_event=stop_event)

    names = [name for name, _ in calls]

    assert "build_worker_loop" in names
    assert names[-1:] == ["shutdown_all"]


@pytest.mark.asyncio
async def test_run_build_worker_process_runs_without_runtime_listener(
    monkeypatch,
) -> None:
    calls: list[str] = []
    stop_event = asyncio.Event()
    client = FakeWorkerRuntimeClient()

    async def fake_build_worker_loop(local_stop: asyncio.Event, worker_id: str, run_job, **kwargs) -> None:
        calls.append("build_worker_loop")
        assert local_stop is stop_event
        assert worker_id == "worker-1"
        assert callable(run_job)
        assert kwargs["client"] is client
        assert kwargs["max_jobs"] is None
        local_stop.set()

    monkeypatch.setattr(
        runtime_process.settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)
    monkeypatch.setattr(runtime_process, "worker_runtime_client", lambda: client)

    monkeypatch.setattr(runtime_process, "build_worker_loop", fake_build_worker_loop)
    monkeypatch.setattr(runtime_process, "build_worker_id", lambda: "worker-1")
    monkeypatch.setattr(
        runtime_process,
        "ProcessManager",
        lambda **kwargs: SimpleNamespace(shutdown_all=lambda: calls.append("shutdown_all")),
    )

    await runtime_process.run_build_worker_process(stop_event=stop_event)

    assert calls == ["build_worker_loop", "shutdown_all"]


@pytest.mark.asyncio
async def test_run_build_manager_process_tracks_manager_and_spawns_workers(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []
    stop_event = asyncio.Event()
    client = FakeWorkerRuntimeClient()
    monkeypatch.setattr(client, "queued_build_job_count", lambda: 1)

    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 123
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            calls.append(("child_join", timeout))
            self._alive = False

        def terminate(self) -> None:
            self._alive = False
            calls.append(("child_terminate", None))

        def kill(self) -> None:
            self._alive = False
            calls.append(("child_kill", None))

    class FakeStopSignal:
        def __init__(self) -> None:
            self.set_calls = 0

        def set(self) -> None:
            self.set_calls += 1
            calls.append(("child_stop_signal", self.set_calls))

    class FakeStoppedSignal:
        def __init__(self, stop_signal: FakeStopSignal) -> None:
            self._stop_signal = stop_signal

        def is_set(self) -> bool:
            return self._stop_signal.set_calls > 0

        def wait(self, _timeout=None) -> bool:
            return self.is_set()

    def fake_spawn_worker_process():
        calls.append(("child_start", None))
        stop_event.set()
        stop_signal = FakeStopSignal()
        return runtime_process.ManagedWorkerProcess(
            process=FakeProcess(),
            stop_signal=stop_signal,
            stopped_signal=FakeStoppedSignal(stop_signal),
        )

    monkeypatch.setattr(runtime_process, "worker_runtime_client", lambda: client)
    monkeypatch.setattr(runtime_process, "manager_id", lambda: "manager-1")
    monkeypatch.setattr(runtime_process, "_spawn_worker_process", fake_spawn_worker_process)
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)

    class FakeDataPlaneServer:
        async def stop(self, *, grace: float | None = None) -> None:
            calls.append(("data_plane_stop", grace))

    monkeypatch.setattr(
        runtime_process,
        "start_data_plane_grpc_server_in_thread",
        lambda: FakeDataPlaneServer(),
    )

    async def fake_compute_request_loop(*args, **kwargs) -> None:
        calls.append(("compute_request_loop", None))

    monkeypatch.setattr(runtime_process, "compute_request_loop", fake_compute_request_loop)
    monkeypatch.setattr(runtime_process, "compute_request_worker_count", lambda: 1)
    monkeypatch.setattr(runtime_process, "datasource_delete_loop", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(
        runtime_process,
        "ProcessManager",
        lambda **kwargs: SimpleNamespace(shutdown_all=lambda: calls.append(("shutdown_all", None))),
    )
    monkeypatch.setattr(runtime_process.settings, "build_worker_min_processes", 0, raising=False)
    monkeypatch.setattr(runtime_process.settings, "build_worker_max_processes", 2, raising=False)

    await runtime_process.run_build_manager_process(stop_event=stop_event)

    names = [name for name, _ in calls]
    assert "child_start" in names
    assert "child_stop_signal" in names
    assert "child_terminate" not in names
    assert "child_kill" not in names
    register_calls = [payload for name, payload in client.calls if name == "register_worker"]
    assert register_calls
    register_payload = register_calls[0]
    assert isinstance(register_payload, dict)
    assert register_payload["worker_id"] == "manager-1"
    assert register_payload["kind"] == "build_manager"
    assert register_payload["capacity"] == 2
    assert names.count("compute_request_loop") == 1
    assert ("stop_worker", {"worker_id": "manager-1"}) in client.calls
