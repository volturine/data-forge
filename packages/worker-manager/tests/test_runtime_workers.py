import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from contracts.build_jobs.models import BuildJobStatus
from contracts.runtime_workers.models import RuntimeWorkerKind
from core import (
    build_jobs_service as build_job_service,
)
from core import (
    runtime_workers_service as runtime_worker_service,
)
from core.database import run_db, run_settings_db
from core.namespace import reset_namespace, set_namespace_context
from core.namespaces_service import register_namespace

from runtime.worker_runtime import build_worker_loop, next_job


def _load_runtime_process():
    path = Path(__file__).resolve().parents[2] / "worker-manager" / "main.py"
    spec = importlib.util.spec_from_file_location("worker_manager_main_for_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load worker-manager runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_process = _load_runtime_process()


def test_register_heartbeat_and_stop_worker(test_db_session) -> None:
    worker = runtime_worker_service.register_worker(
        test_db_session,
        worker_id="worker-1",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="host",
        pid=123,
        capacity=2,
    )

    assert worker.active_jobs == 0
    assert worker.stopped_at is None

    heartbeat = runtime_worker_service.heartbeat_worker(
        test_db_session,
        worker_id="worker-1",
        active_jobs=1,
    )

    assert heartbeat.active_jobs == 1
    assert heartbeat.last_heartbeat_at >= worker.last_heartbeat_at

    stopped = runtime_worker_service.mark_worker_stopped(test_db_session, worker_id="worker-1")

    assert stopped.active_jobs == 0
    assert stopped.stopped_at is not None


def test_claim_next_job_reclaims_stopped_worker_job(test_db_session) -> None:
    runtime_worker_service.register_worker(
        test_db_session,
        worker_id="dead-worker",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="host",
        pid=100,
        capacity=1,
    )
    runtime_worker_service.mark_worker_stopped(test_db_session, worker_id="dead-worker")
    job = build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
    )
    job.status = BuildJobStatus.RUNNING
    job.lease_owner = "dead-worker"
    job.attempts = 0
    test_db_session.add(job)
    test_db_session.commit()
    test_db_session.refresh(job)

    reclaimable = runtime_worker_service.reclaimable_worker_ids(
        test_db_session,
        kind=RuntimeWorkerKind.BUILD_WORKER,
    )
    claimed = build_job_service.claim_next_job(
        test_db_session,
        worker_id="worker-2",
        reclaimable_owner_ids=reclaimable,
    )

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == BuildJobStatus.RUNNING
    assert claimed.lease_owner == "worker-2"
    assert claimed.attempts == 1
    assert claimed.lease_expires_at is None


def test_claim_next_job_reclaims_stale_running_job(test_db_session) -> None:
    stale_at = datetime.now(UTC) - timedelta(seconds=30)
    runtime_worker_service.register_worker(
        test_db_session,
        worker_id="dead-worker",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="host",
        pid=101,
        capacity=1,
        now=stale_at,
    )
    job = build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
    )
    job.status = BuildJobStatus.RUNNING
    job.lease_owner = "dead-worker"
    job.attempts = 0
    test_db_session.add(job)
    test_db_session.commit()
    test_db_session.refresh(job)

    reclaimable = runtime_worker_service.reclaimable_worker_ids(
        test_db_session,
        kind=RuntimeWorkerKind.BUILD_WORKER,
    )
    claimed = build_job_service.claim_next_job(
        test_db_session,
        worker_id="worker-2",
        reclaimable_owner_ids=reclaimable,
    )

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == BuildJobStatus.RUNNING
    assert claimed.lease_owner == "worker-2"


def test_claim_next_job_skips_already_leased_job(test_db_session) -> None:
    build_id = str(uuid.uuid4())
    build_job_service.create_job(
        test_db_session,
        build_id=build_id,
        namespace="default",
    )

    first = build_job_service.claim_next_job(test_db_session, worker_id="worker-1")
    second = build_job_service.claim_next_job(test_db_session, worker_id="worker-2")

    assert first is not None
    assert second is None
    stored = build_job_service.get_job_by_build_id(test_db_session, build_id)
    assert stored is not None
    assert stored.lease_owner == "worker-1"


def test_claim_next_job_does_not_reclaim_live_running_job(test_db_session) -> None:
    runtime_worker_service.register_worker(
        test_db_session,
        worker_id="live-worker",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="host",
        pid=102,
        capacity=1,
    )
    job = build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
    )
    job.status = BuildJobStatus.RUNNING
    job.lease_owner = "live-worker"
    test_db_session.add(job)
    test_db_session.commit()

    reclaimable = runtime_worker_service.reclaimable_worker_ids(
        test_db_session,
        kind=RuntimeWorkerKind.BUILD_WORKER,
    )
    claimed = build_job_service.claim_next_job(
        test_db_session,
        worker_id="worker-1",
        reclaimable_owner_ids=reclaimable,
    )

    assert claimed is None


@pytest.mark.asyncio
async def test_build_worker_loop_tracks_runtime_worker_lifecycle(
    test_db_session,
) -> None:
    build_id = str(uuid.uuid4())
    build_job_service.create_job(
        test_db_session,
        build_id=build_id,
        namespace="default",
    )
    stop_event = asyncio.Event()
    seen: list[str] = []

    async def run_job(job_build_id: str) -> None:
        seen.append(job_build_id)
        await asyncio.sleep(0.05)
        stop_event.set()

    task = asyncio.create_task(
        build_worker_loop(
            stop_event,
            "worker-1",
            run_job,
            heartbeat_seconds=0.01,
        )
    )
    await asyncio.gather(task)

    assert seen == [build_id]
    stored = run_settings_db(lambda session: runtime_worker_service.get_worker(session, "worker-1"))
    assert stored is not None
    assert stored.kind == RuntimeWorkerKind.BUILD_WORKER
    assert stored.active_jobs == 0
    assert stored.stopped_at is not None

    refreshed = build_job_service.get_job_by_build_id(test_db_session, build_id)
    assert refreshed is not None
    assert refreshed.status == BuildJobStatus.FAILED
    assert refreshed.lease_owner is None
    assert refreshed.lease_expires_at is None


@pytest.mark.asyncio
async def test_build_worker_loop_exits_after_one_job_when_max_jobs_set(
    test_db_session,
) -> None:
    build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
    )
    build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
    )
    stop_event = asyncio.Event()
    seen: list[str] = []

    async def run_job(job_build_id: str) -> None:
        seen.append(job_build_id)

    await build_worker_loop(stop_event, "worker-once", run_job, max_jobs=1)

    assert len(seen) == 1


def test_expire_worker_jobs_releases_owned_running_jobs(test_db_session) -> None:
    build_id = str(uuid.uuid4())
    build_job_service.create_job(
        test_db_session,
        build_id=build_id,
        namespace="default",
    )
    claimed = build_job_service.claim_next_job(test_db_session, worker_id="worker-1")

    assert claimed is not None
    released = build_job_service.release_worker_jobs(test_db_session, worker_id="worker-1")

    assert [job.id for job in released] == [claimed.id]
    refreshed = build_job_service.get_job_by_build_id(test_db_session, build_id)
    assert refreshed is not None
    assert refreshed.status == BuildJobStatus.QUEUED
    assert refreshed.lease_owner is None
    assert refreshed.lease_expires_at is None


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
    assert calls[1][1] == pytest.approx(runtime_process._CHILD_COOPERATIVE_STOP_SECONDS)
    terminate_join = next(timeout for name, timeout in calls if name == "join" and timeout is not None)
    assert terminate_join == pytest.approx(runtime_process._CHILD_TERMINATE_SECONDS)
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

    monkeypatch.setattr(
        runtime_process,
        "run_settings_db",
        lambda fn, **kwargs: [
            SimpleNamespace(pid=101, active_jobs=1, stopped_at=None),
            SimpleNamespace(pid=202, active_jobs=0, stopped_at=None),
        ],
    )

    assert runtime_process._next_idle_child_pid(children) == 202

    monkeypatch.setattr(
        runtime_process,
        "run_settings_db",
        lambda fn, **kwargs: [SimpleNamespace(pid=101, active_jobs=1, stopped_at=None)],
    )

    assert runtime_process._next_idle_child_pid(children) is None


def test_next_job_claims_from_non_default_namespace() -> None:
    token = set_namespace_context("beta")
    try:
        build_id = str(uuid.uuid4())
        run_settings_db(register_namespace, "beta")
        run_db(build_job_service.create_job, build_id=build_id, namespace="beta")
    finally:
        reset_namespace(token)

    claimed = next_job("worker-1")

    assert claimed is not None
    assert claimed.namespace == "beta"
    assert claimed.build_id == build_id


@pytest.mark.asyncio
async def test_run_build_worker_process_starts_runtime_listener(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    stop_event = asyncio.Event()

    async def fake_init_db() -> None:
        calls.append(("init_db", None))

    async def fake_serve_api_notifications(server: object, local_stop: asyncio.Event, handler) -> None:
        calls.append(("serve_api_notifications", server))
        assert local_stop is stop_event
        assert handler is runtime_process.handle_runtime_payload
        await local_stop.wait()

    async def fake_stop_api_server(server: object) -> None:
        calls.append(("stop_api_server", server))

    async def fake_build_worker_loop(local_stop: asyncio.Event, worker_id: str, run_job, **kwargs) -> None:
        calls.append(("build_worker_loop", worker_id))
        assert local_stop is stop_event
        assert callable(run_job)
        assert kwargs["max_jobs"] is None
        local_stop.set()

    monkeypatch.setattr(
        runtime_process.settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )
    monkeypatch.setattr(runtime_process, "init_db", fake_init_db)
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)
    monkeypatch.setattr(
        runtime_process.runtime_ipc,
        "serve_api_notifications",
        fake_serve_api_notifications,
    )
    monkeypatch.setattr(runtime_process.runtime_ipc, "stop_api_server", fake_stop_api_server)
    monkeypatch.setattr(runtime_process, "build_worker_loop", fake_build_worker_loop)
    monkeypatch.setattr(runtime_process, "build_worker_id", lambda: "worker-1")
    monkeypatch.setattr(
        runtime_process,
        "ProcessManager",
        lambda **kwargs: SimpleNamespace(shutdown_all=lambda: calls.append(("shutdown_all", None))),
    )

    await runtime_process.run_build_worker_process(stop_event=stop_event)

    names = [name for name, _ in calls]

    assert names[0:1] == ["init_db"]
    assert "build_worker_loop" in names
    assert names[-1:] == ["shutdown_all"]


@pytest.mark.asyncio
async def test_run_build_worker_process_runs_without_runtime_listener(
    monkeypatch,
) -> None:
    calls: list[str] = []
    stop_event = asyncio.Event()

    async def fake_init_db() -> None:
        calls.append("init_db")

    async def fake_build_worker_loop(local_stop: asyncio.Event, worker_id: str, run_job, **kwargs) -> None:
        calls.append("build_worker_loop")
        assert local_stop is stop_event
        assert worker_id == "worker-1"
        assert callable(run_job)
        assert kwargs["max_jobs"] is None
        local_stop.set()

    monkeypatch.setattr(
        runtime_process.settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )
    monkeypatch.setattr(runtime_process, "init_db", fake_init_db)
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)

    monkeypatch.setattr(runtime_process, "build_worker_loop", fake_build_worker_loop)
    monkeypatch.setattr(runtime_process, "build_worker_id", lambda: "worker-1")
    monkeypatch.setattr(
        runtime_process,
        "ProcessManager",
        lambda **kwargs: SimpleNamespace(shutdown_all=lambda: calls.append("shutdown_all")),
    )

    await runtime_process.run_build_worker_process(stop_event=stop_event)

    assert calls == ["init_db", "build_worker_loop", "shutdown_all"]


@pytest.mark.asyncio
async def test_run_build_manager_process_tracks_manager_and_spawns_workers(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []
    stop_event = asyncio.Event()

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

    async def fake_init_db() -> None:
        calls.append(("init_db", None))

    async def fake_start_api_server(listener="api") -> object:
        calls.append(("start_api_server", listener))
        return object()

    async def fake_serve_api_notifications(server: object, local_stop: asyncio.Event, handler) -> None:
        del server, handler
        calls.append(("serve_api_notifications", None))
        await local_stop.wait()

    async def fake_stop_api_server(server: object, *, listener="api") -> None:
        del server
        calls.append(("stop_api_server", listener))

    def fake_spawn_worker_process():
        calls.append(("child_start", None))
        stop_event.set()
        stop_signal = FakeStopSignal()
        return runtime_process.ManagedWorkerProcess(
            process=FakeProcess(),
            stop_signal=stop_signal,
            stopped_signal=FakeStoppedSignal(stop_signal),
        )

    monkeypatch.setattr(runtime_process, "init_db", fake_init_db)
    monkeypatch.setattr(runtime_process.runtime_ipc, "start_api_server", fake_start_api_server)
    monkeypatch.setattr(
        runtime_process.runtime_ipc,
        "serve_api_notifications",
        fake_serve_api_notifications,
    )
    monkeypatch.setattr(runtime_process.runtime_ipc, "stop_api_server", fake_stop_api_server)
    monkeypatch.setattr(
        runtime_process,
        "_register_manager",
        lambda worker_id: calls.append(("register_manager", worker_id)),
    )
    monkeypatch.setattr(
        runtime_process,
        "_stop_manager",
        lambda worker_id: calls.append(("stop_manager", worker_id)),
    )
    monkeypatch.setattr(
        runtime_process,
        "_heartbeat_manager",
        lambda worker_id, active_jobs=0: calls.append(("heartbeat", active_jobs)),
    )
    monkeypatch.setattr(runtime_process, "manager_id", lambda: "manager-1")
    monkeypatch.setattr(runtime_process, "queued_job_count", lambda: 1)
    monkeypatch.setattr(runtime_process, "_spawn_worker_process", fake_spawn_worker_process)
    monkeypatch.setattr(runtime_process.settings, "build_worker_min_processes", 0, raising=False)
    monkeypatch.setattr(runtime_process.settings, "build_worker_max_processes", 2, raising=False)

    await runtime_process.run_build_manager_process(stop_event=stop_event)

    names = [name for name, _ in calls]
    assert names[0:3] == ["init_db", "start_api_server", "register_manager"]
    assert "child_start" in names
    assert "child_stop_signal" in names
    assert "child_terminate" not in names
    assert "child_kill" not in names
    assert any(name == "stop_api_server" for name, _ in calls)
    assert ("stop_manager", "manager-1") in calls
