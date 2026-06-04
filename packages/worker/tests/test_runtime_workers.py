import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from backend_contracts.compute import schemas as backend_compute_schemas
from backend_core import (
    build_event_service as backend_build_event_service,
)
from backend_core import (
    build_jobs_service as build_job_service,
)
from backend_core import (
    build_runs_service as build_run_service,
)
from backend_core import (
    runtime_workers_service as runtime_worker_service,
)
from backend_core.database import get_db, run_settings_db
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.scheduler.models import Schedule
from modules.scheduler.service import reconcile_schedule_run

from builds import build_execution
from runtime.internal_api import ClaimedBuildJob, StartedBuildRun
from runtime.worker_runtime import build_worker_loop
from worker_contracts.build_jobs.models import BuildJobStatus
from worker_contracts.build_runs.models import BuildRunStatus
from worker_contracts.runtime_workers.models import RuntimeWorkerKind


class FakeWorkerInternalApiClient:
    def __init__(self, jobs: list[ClaimedBuildJob] | None = None) -> None:
        self.jobs = list(jobs or [])
        self.calls: list[tuple[str, object]] = []

    def register_worker(self, **kwargs) -> None:
        self.calls.append(("register_worker", kwargs))

    def heartbeat_worker(self, **kwargs) -> None:
        self.calls.append(("heartbeat_worker", kwargs))

    def stop_worker(self, **kwargs) -> None:
        self.calls.append(("stop_worker", kwargs))

    def claim_build_job(self, *, worker_id: str) -> ClaimedBuildJob | None:
        self.calls.append(("claim_build_job", worker_id))
        return self.jobs.pop(0) if self.jobs else None

    def fail_build_job(self, **kwargs) -> None:
        self.calls.append(("fail_build_job", kwargs))

    def finalize_build_job(self, **kwargs) -> None:
        self.calls.append(("finalize_build_job", kwargs))

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


class PersistingBuildEventClient:
    def schedule_ingest_datasource(self, *, namespace: str, datasource_id: str) -> dict[str, object]:
        from modules.datasource import runtime_service

        token = build_execution.set_namespace_context(namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            response = runtime_service.ingest_datasource_for_schedule(session, datasource_id)
            if hasattr(response, "model_dump"):
                return response.model_dump(mode="json")
            return dict(response.__dict__)
        finally:
            session.close()
            session_gen.close()
            build_execution.reset_namespace(token)

    def start_build_run(self, *, namespace: str, build_id: str) -> StartedBuildRun | None:
        token = build_execution.set_namespace_context(namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            run = build_run_service.mark_build_running(session, build_id)
            if run is None or run.status != BuildRunStatus.RUNNING:
                return None
            asyncio.run(backend_build_event_service.publish_build_notification(run.namespace, run.id, latest_sequence=0))
            return StartedBuildRun(
                id=run.id,
                namespace=run.namespace,
                analysis_id=run.analysis_id,
                analysis_name=run.analysis_name,
                request_json=dict(run.request_json),
                starter_json=dict(run.starter_json),
                resource_config_json=dict(run.resource_config_json) if isinstance(run.resource_config_json, dict) else None,
                current_kind=run.current_kind,
                current_datasource_id=run.current_datasource_id,
                current_tab_id=run.current_tab_id,
                current_tab_name=run.current_tab_name,
                current_output_id=run.current_output_id,
                current_output_name=run.current_output_name,
                started_at=run.started_at,
                total_tabs=run.total_tabs,
            )
        finally:
            session.close()
            session_gen.close()
            build_execution.reset_namespace(token)

    def persist_build_event(
        self,
        *,
        namespace: str,
        build_id: str,
        event: dict[str, object],
        resource_config_json: dict[str, object] | None = None,
    ) -> int | None:
        parsed = backend_compute_schemas.BuildEventAdapter.validate_python(event)
        token = build_execution.set_namespace_context(namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            result = asyncio.run(
                backend_build_event_service.persist_build_event(
                    session,
                    namespace=namespace,
                    build_id=build_id,
                    event=parsed,
                    resource_config_json=resource_config_json,
                )
            )
        finally:
            session.close()
            session_gen.close()
            build_execution.reset_namespace(token)
        if result is None:
            return None
        _, sequence = result
        return sequence


def _load_runtime_process():
    path = Path(__file__).resolve().parents[2] / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("worker_main_for_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load worker runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_process = _load_runtime_process()


def test_register_heartbeat_and_stop_worker(test_db_session) -> None:
    del test_db_session
    worker = run_settings_db(
        runtime_worker_service.register_worker,
        worker_id="worker-1",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="host",
        pid=123,
        capacity=2,
    )

    assert worker.active_jobs == 0
    assert worker.stopped_at is None

    heartbeat = run_settings_db(
        runtime_worker_service.heartbeat_worker,
        worker_id="worker-1",
        active_jobs=1,
    )

    assert heartbeat.active_jobs == 1
    assert heartbeat.last_heartbeat_at >= worker.last_heartbeat_at

    stopped = run_settings_db(runtime_worker_service.mark_worker_stopped, worker_id="worker-1")

    assert stopped.active_jobs == 0
    assert stopped.stopped_at is not None


def test_claim_next_job_reclaims_stopped_worker_job(test_db_session) -> None:
    run_settings_db(
        runtime_worker_service.register_worker,
        worker_id="dead-worker",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="host",
        pid=100,
        capacity=1,
    )
    run_settings_db(runtime_worker_service.mark_worker_stopped, worker_id="dead-worker")
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

    reclaimable = run_settings_db(
        runtime_worker_service.reclaimable_worker_ids,
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
    assert claimed.lease_expires_at is not None


def test_claim_next_job_reclaims_stale_running_job(test_db_session) -> None:
    stale_at = datetime.now(UTC) - timedelta(seconds=30)
    run_settings_db(
        runtime_worker_service.register_worker,
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

    reclaimable = run_settings_db(
        runtime_worker_service.reclaimable_worker_ids,
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
    run_settings_db(
        runtime_worker_service.register_worker,
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

    reclaimable = run_settings_db(
        runtime_worker_service.reclaimable_worker_ids,
        kind=RuntimeWorkerKind.BUILD_WORKER,
    )
    claimed = build_job_service.claim_next_job(
        test_db_session,
        worker_id="worker-1",
        reclaimable_owner_ids=reclaimable,
    )

    assert claimed is None


def test_claim_next_job_reclaims_expired_lease(test_db_session) -> None:
    job = build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
    )
    job.status = BuildJobStatus.RUNNING
    job.lease_owner = "live-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    job.attempts = 0
    test_db_session.add(job)
    test_db_session.commit()

    claimed = build_job_service.claim_next_job(
        test_db_session,
        worker_id="worker-2",
        reclaimable_owner_ids=set(),
    )

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.lease_owner == "worker-2"
    assert claimed.lease_expires_at is not None


@pytest.mark.asyncio
async def test_build_worker_loop_tracks_runtime_worker_lifecycle(
    test_db_session,
) -> None:
    build_id = str(uuid.uuid4())
    job = ClaimedBuildJob(job_id=str(uuid.uuid4()), build_id=build_id, namespace="default")
    client = FakeWorkerInternalApiClient([job])
    stop_event = asyncio.Event()
    seen: list[tuple[str, str]] = []

    async def run_job(job_build_id: str, namespace: str) -> None:
        seen.append((job_build_id, namespace))
        await asyncio.sleep(0.05)
        stop_event.set()

    task = asyncio.create_task(
        build_worker_loop(
            stop_event,
            "worker-1",
            run_job,
            client=client,  # type: ignore[arg-type]
            heartbeat_seconds=0.01,
        )
    )
    await asyncio.gather(task)

    assert seen == [(build_id, "default")]
    assert ("finalize_build_job", {"job_id": job.job_id, "build_id": job.build_id, "namespace": job.namespace}) in client.calls
    assert any(name == "stop_worker" for name, _ in client.calls)


def test_reconcile_schedule_run_persists_last_run_and_next_run(test_db_session) -> None:
    datasource = DataSource(
        id=str(uuid.uuid4()),
        name="Ingestable raw",
        source_type="iceberg",
        config={
            "metadata_path": "/tmp/raw-path",
            "branch": "master",
            "source": {
                "source_type": "file",
                "file_path": "/tmp/source.csv",
                "file_type": "csv",
                "options": {},
            },
        },
        created_by="import",
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    schedule = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=datasource.id,
        cron_expression="0 * * * *",
        enabled=True,
        created_at=datetime.now(UTC),
        lease_owner="scheduler:test",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    test_db_session.add(schedule)
    test_db_session.commit()

    build = build_run_service.create_build_run(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
        schedule_id=schedule.id,
        analysis_id=schedule.id,
        analysis_name="Schedule ingest",
        request_json={"analysis_pipeline": {"analysis_id": schedule.id, "tabs": []}, "tab_id": schedule.id},
        starter_json={"triggered_by": f"schedule:{schedule.id}"},
        status=BuildRunStatus.COMPLETED,
        current_kind="build",
        current_datasource_id=datasource.id,
        current_tab_id=schedule.id,
        current_tab_name="Scheduled ingest",
        current_output_id=datasource.id,
        current_output_name=datasource.name,
        total_tabs=1,
    )
    build.completed_at = datetime.now(UTC)
    test_db_session.add(build)
    test_db_session.commit()

    reconcile_schedule_run(test_db_session, build_id=build.id)

    refreshed = test_db_session.get(Schedule, schedule.id)
    assert refreshed is not None
    assert refreshed.last_run is not None
    assert refreshed.last_success_at is not None
    assert refreshed.next_run is not None
    assert refreshed.last_successful_build_id == build.id
    assert refreshed.lease_owner is None


@pytest.mark.asyncio
async def test_run_queued_build_job_uses_schedule_ingest_path_for_schedule_ingest_request(
    test_db_session,
    monkeypatch,
) -> None:
    datasource = DataSource(
        id=str(uuid.uuid4()),
        name="Ingestable raw",
        source_type="iceberg",
        config={
            "metadata_path": "/tmp/raw-path",
            "branch": "master",
            "source": {
                "source_type": "file",
                "file_path": "/tmp/source.csv",
                "file_type": "csv",
                "options": {},
            },
        },
        created_by="import",
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    schedule = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=datasource.id,
        cron_expression="0 * * * *",
        enabled=True,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(schedule)
    test_db_session.commit()

    build = build_run_service.create_build_run(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
        schedule_id=schedule.id,
        analysis_id=schedule.id,
        analysis_name="Schedule ingest",
        request_json={
            "analysis_pipeline": {
                "analysis_id": schedule.id,
                "tabs": [
                    {
                        "id": schedule.id,
                        "name": "Scheduled ingest",
                        "datasource": {
                            "id": datasource.id,
                            "analysis_tab_id": None,
                            "source_type": "schedule",
                            "config": {"branch": "master"},
                        },
                        "output": {
                            "result_id": datasource.id,
                            "datasource_type": "iceberg",
                            "format": "parquet",
                            "filename": f"schedule_{schedule.id}",
                        },
                        "steps": [],
                    }
                ],
            },
            "tab_id": schedule.id,
        },
        starter_json={"triggered_by": f"schedule:{schedule.id}"},
        status=BuildRunStatus.QUEUED,
        current_kind="build",
        current_datasource_id=datasource.id,
        current_tab_id=schedule.id,
        current_tab_name="Scheduled ingest",
        current_output_id=datasource.id,
        current_output_name=datasource.name,
        total_tabs=1,
    )

    refreshed = SimpleNamespace(name=datasource.name)
    publish_notification = AsyncMock()
    run_analysis_build = AsyncMock()
    ingest_calls: list[str] = []

    def fake_ingest(_session, datasource_id: str):
        ingest_calls.append(datasource_id)
        return refreshed

    monkeypatch.setattr(backend_build_event_service, "publish_build_notification", publish_notification)
    monkeypatch.setattr(build_execution, "_run_active_build_task", run_analysis_build)
    monkeypatch.setattr("modules.datasource.runtime_service.ingest_datasource_for_schedule", fake_ingest)
    monkeypatch.setattr(build_execution, "worker_internal_api_client", PersistingBuildEventClient)

    manager = cast(Any, SimpleNamespace())
    await build_execution.run_queued_build_job(manager=manager, build_id=build.id)

    assert ingest_calls == [datasource.id]
    run_analysis_build.assert_not_awaited()
    test_db_session.expire_all()
    persisted = build_run_service.get_build_run(test_db_session, build.id)
    assert persisted is not None
    assert persisted.status == BuildRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_run_queued_build_job_keeps_analysis_schedule_on_analysis_build_path(
    test_db_session,
    monkeypatch,
) -> None:
    datasource = DataSource(
        id=str(uuid.uuid4()),
        name="Source",
        source_type="iceberg",
        config={"metadata_path": "/tmp/source/master", "branch": "master"},
        created_by="import",
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    schedule = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=str(uuid.uuid4()),
        cron_expression="0 * * * *",
        enabled=True,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(schedule)
    test_db_session.commit()

    build = build_run_service.create_build_run(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace="default",
        schedule_id=schedule.id,
        analysis_id="analysis-1",
        analysis_name="Scheduled analysis",
        request_json={
            "analysis_pipeline": {
                "analysis_id": "analysis-1",
                "tabs": [
                    {
                        "id": "tab-1",
                        "name": "Export",
                        "datasource": {
                            "id": datasource.id,
                            "analysis_tab_id": None,
                            "source_type": "iceberg",
                            "config": {"metadata_path": "/tmp/source/master", "branch": "master"},
                        },
                        "output": {
                            "result_id": schedule.datasource_id,
                            "datasource_type": "iceberg",
                            "format": "parquet",
                            "filename": "scheduled_output",
                            "iceberg": {"namespace": "outputs", "table_name": "scheduled_output"},
                        },
                        "steps": [],
                    }
                ],
            },
            "tab_id": "tab-1",
        },
        starter_json={"triggered_by": f"schedule:{schedule.id}"},
        status=BuildRunStatus.QUEUED,
        current_kind="build",
        current_datasource_id=schedule.datasource_id,
        current_tab_id="tab-1",
        current_tab_name="Export",
        current_output_id=schedule.datasource_id,
        current_output_name="scheduled_output",
        total_tabs=1,
    )

    publish_notification = AsyncMock()
    run_analysis_build = AsyncMock()

    def fail_ingest(*_args, **_kwargs):
        raise AssertionError("analysis schedule should not use datasource ingest path")

    monkeypatch.setattr(backend_build_event_service, "publish_build_notification", publish_notification)
    monkeypatch.setattr(build_execution, "_run_active_build_task", run_analysis_build)
    monkeypatch.setattr("modules.datasource.runtime_service.ingest_datasource_for_schedule", fail_ingest)
    monkeypatch.setattr(build_execution, "worker_internal_api_client", PersistingBuildEventClient)

    manager = cast(Any, SimpleNamespace())
    await build_execution.run_queued_build_job(manager=manager, build_id=build.id)

    run_analysis_build.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_worker_loop_exits_after_one_job_when_max_jobs_set(
    test_db_session,
) -> None:
    first = ClaimedBuildJob(job_id=str(uuid.uuid4()), build_id=str(uuid.uuid4()), namespace="default")
    second = ClaimedBuildJob(job_id=str(uuid.uuid4()), build_id=str(uuid.uuid4()), namespace="default")
    client = FakeWorkerInternalApiClient([first, second])
    stop_event = asyncio.Event()
    seen: list[str] = []

    async def run_job(job_build_id: str, namespace: str) -> None:
        assert namespace == "default"
        seen.append(job_build_id)

    await build_worker_loop(stop_event, "worker-once", run_job, client=client, max_jobs=1)  # type: ignore[arg-type]

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

    client = FakeWorkerInternalApiClient()
    monkeypatch.setattr(client, "idle_build_worker_pids", lambda: {202})

    assert runtime_process._next_idle_child_pid(children, client=client) == 202

    monkeypatch.setattr(client, "idle_build_worker_pids", lambda: set())

    assert runtime_process._next_idle_child_pid(children, client=client) is None


@pytest.mark.asyncio
async def test_run_build_worker_process_passes_internal_api_client(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    stop_event = asyncio.Event()
    client = FakeWorkerInternalApiClient()

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
    monkeypatch.setattr(runtime_process, "worker_internal_api_client", lambda: client)
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
    client = FakeWorkerInternalApiClient()

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
    monkeypatch.setattr(runtime_process, "worker_internal_api_client", lambda: client)

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
    client = FakeWorkerInternalApiClient()
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

    monkeypatch.setattr(runtime_process, "worker_internal_api_client", lambda: client)
    monkeypatch.setattr(runtime_process, "manager_id", lambda: "manager-1")
    monkeypatch.setattr(runtime_process, "_spawn_worker_process", fake_spawn_worker_process)
    monkeypatch.setattr(runtime_process, "configure_logging", lambda: None)

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
