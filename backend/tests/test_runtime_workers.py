import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from core.database import run_db, run_settings_db
from core.namespace import reset_namespace, set_namespace_context
from modules.build_jobs import service as build_job_service
from modules.build_jobs.models import BuildJobStatus
from modules.runtime import process as runtime_process
from modules.runtime.worker import build_worker_loop, next_job
from modules.runtime_workers import service as runtime_worker_service
from modules.runtime_workers.models import RuntimeWorkerKind


def test_register_heartbeat_and_stop_worker(test_db_session) -> None:
    worker = runtime_worker_service.register_worker(
        test_db_session,
        worker_id='worker-1',
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname='host',
        pid=123,
        capacity=2,
    )

    assert worker.active_jobs == 0
    assert worker.stopped_at is None

    heartbeat = runtime_worker_service.heartbeat_worker(
        test_db_session,
        worker_id='worker-1',
        active_jobs=1,
    )

    assert heartbeat.active_jobs == 1
    assert heartbeat.last_heartbeat_at >= worker.last_heartbeat_at

    stopped = runtime_worker_service.mark_worker_stopped(test_db_session, worker_id='worker-1')

    assert stopped.active_jobs == 0
    assert stopped.stopped_at is not None


def test_claim_next_job_reclaims_expired_lease(test_db_session) -> None:
    job = build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    job.status = BuildJobStatus.LEASED
    job.lease_owner = 'dead-worker'
    job.lease_expires_at = expired_at
    job.attempts = 0
    test_db_session.add(job)
    test_db_session.commit()
    test_db_session.refresh(job)

    claimed = build_job_service.claim_next_job(test_db_session, worker_id='worker-2', lease_seconds=10)

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == BuildJobStatus.LEASED
    assert claimed.lease_owner == 'worker-2'
    assert claimed.attempts == 1
    assert claimed.lease_expires_at is not None
    assert claimed.lease_expires_at > expired_at.replace(tzinfo=None)


def test_claim_next_job_reclaims_expired_running_job(test_db_session) -> None:
    job = build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    job.status = BuildJobStatus.RUNNING
    job.lease_owner = 'dead-worker'
    job.lease_expires_at = expired_at
    job.attempts = 0
    test_db_session.add(job)
    test_db_session.commit()
    test_db_session.refresh(job)

    claimed = build_job_service.claim_next_job(test_db_session, worker_id='worker-2', lease_seconds=10)

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == BuildJobStatus.LEASED
    assert claimed.lease_owner == 'worker-2'


def test_claim_next_job_skips_already_leased_job(test_db_session) -> None:
    build_id = str(uuid.uuid4())
    build_job_service.create_job(
        test_db_session,
        build_id=build_id,
        namespace='default',
    )

    first = build_job_service.claim_next_job(test_db_session, worker_id='worker-1', lease_seconds=30)
    second = build_job_service.claim_next_job(test_db_session, worker_id='worker-2', lease_seconds=30)

    assert first is not None
    assert second is None
    stored = build_job_service.get_job_by_build_id(test_db_session, build_id)
    assert stored is not None
    assert stored.lease_owner == 'worker-1'


def test_renew_job_lease_requires_owner_and_active_status(test_db_session) -> None:
    build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
    )
    claimed = build_job_service.claim_next_job(test_db_session, worker_id='worker-1', lease_seconds=1)

    assert claimed is not None
    previous_expiry = claimed.lease_expires_at
    renewed = build_job_service.renew_job_lease(test_db_session, claimed.id, worker_id='worker-1', lease_seconds=30)

    assert renewed is not None
    assert renewed.lease_expires_at is not None
    assert previous_expiry is not None
    assert renewed.lease_expires_at > previous_expiry
    assert build_job_service.renew_job_lease(test_db_session, claimed.id, worker_id='worker-2', lease_seconds=30) is None

    build_job_service.mark_job_completed(test_db_session, claimed.id)

    assert build_job_service.renew_job_lease(test_db_session, claimed.id, worker_id='worker-1', lease_seconds=30) is None


@pytest.mark.asyncio
async def test_build_worker_loop_tracks_runtime_worker_lifecycle(test_db_session) -> None:
    build_id = str(uuid.uuid4())
    build_job_service.create_job(
        test_db_session,
        build_id=build_id,
        namespace='default',
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
            'worker-1',
            run_job,
            heartbeat_seconds=0.01,
            lease_seconds=1,
        )
    )
    await task

    assert seen == [build_id]
    stored = run_settings_db(lambda session: runtime_worker_service.get_worker(session, 'worker-1'))
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
async def test_build_worker_loop_exits_after_one_job_when_max_jobs_set(test_db_session) -> None:
    build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
    )
    build_job_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
    )
    stop_event = asyncio.Event()
    seen: list[str] = []

    async def run_job(job_build_id: str) -> None:
        seen.append(job_build_id)

    await build_worker_loop(stop_event, 'worker-once', run_job, max_jobs=1)

    assert len(seen) == 1


def test_expire_worker_jobs_releases_owned_running_jobs(test_db_session) -> None:
    build_id = str(uuid.uuid4())
    build_job_service.create_job(
        test_db_session,
        build_id=build_id,
        namespace='default',
    )
    claimed = build_job_service.claim_next_job(test_db_session, worker_id='worker-1', lease_seconds=30)

    assert claimed is not None
    running = build_job_service.mark_job_running(test_db_session, claimed.id)
    expired = build_job_service.expire_worker_jobs(test_db_session, worker_id='worker-1')

    assert [job.id for job in expired] == [running.id]
    refreshed = build_job_service.get_job_by_build_id(test_db_session, build_id)
    assert refreshed is not None
    assert refreshed.status == BuildJobStatus.QUEUED
    assert refreshed.lease_owner is None
    assert refreshed.lease_expires_at is None


def test_next_job_claims_from_non_default_namespace() -> None:
    token = set_namespace_context('beta')
    try:
        build_id = str(uuid.uuid4())
        run_db(build_job_service.create_job, build_id=build_id, namespace='beta')
    finally:
        reset_namespace(token)

    claimed = next_job('worker-1', lease_seconds=10)

    assert claimed is not None
    assert claimed.namespace == 'beta'
    assert claimed.build_id == build_id


@pytest.mark.asyncio
async def test_run_build_worker_process_starts_runtime_listener(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    stop_event = asyncio.Event()

    async def fake_init_db() -> None:
        calls.append(('init_db', None))

    async def fake_start_api_server() -> object:
        server = object()
        calls.append(('start_api_server', server))
        return server

    async def fake_serve_api_notifications(server: object, local_stop: asyncio.Event, handler) -> None:
        calls.append(('serve_api_notifications', server))
        assert local_stop is stop_event
        assert handler is runtime_process.runtime_ipc.handle_api_payload
        await local_stop.wait()

    async def fake_stop_api_server(server: object) -> None:
        calls.append(('stop_api_server', server))

    async def fake_build_worker_loop(local_stop: asyncio.Event, worker_id: str, run_job, **kwargs) -> None:
        calls.append(('build_worker_loop', worker_id))
        assert local_stop is stop_event
        assert callable(run_job)
        assert kwargs['max_jobs'] is None
        local_stop.set()

    monkeypatch.setattr(
        runtime_process.settings,
        'database_url',
        'postgresql+psycopg://user:pass@host:5432/db',
        raising=False,
    )
    monkeypatch.setattr(runtime_process, 'init_db', fake_init_db)
    monkeypatch.setattr(runtime_process, 'build_worker_loop', fake_build_worker_loop)
    monkeypatch.setattr(runtime_process, 'build_worker_id', lambda: 'worker-1')
    monkeypatch.setattr(
        runtime_process, 'ProcessManager', lambda **kwargs: SimpleNamespace(shutdown_all=lambda: calls.append(('shutdown_all', None)))
    )

    await runtime_process.run_build_worker_process(stop_event=stop_event)

    names = [name for name, _ in calls]

    assert names[0:1] == ['init_db']
    assert 'build_worker_loop' in names
    assert names[-1:] == ['shutdown_all']


@pytest.mark.asyncio
async def test_run_build_worker_process_skips_runtime_listener_outside_postgres(monkeypatch) -> None:
    calls: list[str] = []
    stop_event = asyncio.Event()

    async def fake_init_db() -> None:
        calls.append('init_db')

    async def fake_build_worker_loop(local_stop: asyncio.Event, worker_id: str, run_job, **kwargs) -> None:
        calls.append('build_worker_loop')
        assert local_stop is stop_event
        assert worker_id == 'worker-1'
        assert callable(run_job)
        assert kwargs['max_jobs'] is None
        local_stop.set()

    monkeypatch.setattr(runtime_process.settings, 'database_url', 'sqlite:////tmp/test.db', raising=False)
    monkeypatch.setattr(runtime_process, 'init_db', fake_init_db)
    monkeypatch.setattr(
        runtime_process.runtime_ipc,
        'start_api_server',
        lambda: pytest.fail('runtime IPC server should not start outside Postgres'),
    )
    monkeypatch.setattr(runtime_process, 'build_worker_loop', fake_build_worker_loop)
    monkeypatch.setattr(runtime_process, 'build_worker_id', lambda: 'worker-1')
    monkeypatch.setattr(
        runtime_process, 'ProcessManager', lambda **kwargs: SimpleNamespace(shutdown_all=lambda: calls.append('shutdown_all'))
    )

    await runtime_process.run_build_worker_process(stop_event=stop_event)

    assert calls == ['init_db', 'build_worker_loop', 'shutdown_all']


@pytest.mark.asyncio
async def test_run_build_manager_process_tracks_manager_and_spawns_workers(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    stop_event = asyncio.Event()

    class FakeProcess:
        def __init__(self, target) -> None:
            self.target = target
            self.pid = 123
            self._alive = False

        def start(self) -> None:
            self._alive = True
            calls.append(('child_start', self.target))
            stop_event.set()

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            del timeout
            self._alive = False

        def terminate(self) -> None:
            self._alive = False
            calls.append(('child_terminate', None))

        def kill(self) -> None:
            self._alive = False
            calls.append(('child_kill', None))

    async def fake_init_db() -> None:
        calls.append(('init_db', None))

    async def fake_start_api_server(listener='api') -> object:
        calls.append(('start_api_server', listener))
        return object()

    async def fake_serve_api_notifications(server: object, local_stop: asyncio.Event, handler) -> None:
        del server, handler
        calls.append(('serve_api_notifications', None))
        await local_stop.wait()

    async def fake_stop_api_server(server: object, *, listener='api') -> None:
        del server
        calls.append(('stop_api_server', listener))

    monkeypatch.setattr(runtime_process, 'init_db', fake_init_db)
    monkeypatch.setattr(runtime_process.runtime_ipc, 'start_api_server', fake_start_api_server)
    monkeypatch.setattr(runtime_process.runtime_ipc, 'serve_api_notifications', fake_serve_api_notifications)
    monkeypatch.setattr(runtime_process.runtime_ipc, 'stop_api_server', fake_stop_api_server)
    monkeypatch.setattr(runtime_process, '_register_manager', lambda worker_id: calls.append(('register_manager', worker_id)))
    monkeypatch.setattr(runtime_process, '_stop_manager', lambda worker_id: calls.append(('stop_manager', worker_id)))
    monkeypatch.setattr(runtime_process, '_heartbeat_manager', lambda worker_id, active_jobs=0: calls.append(('heartbeat', active_jobs)))
    monkeypatch.setattr(runtime_process, 'manager_id', lambda: 'manager-1')
    monkeypatch.setattr(runtime_process, 'queued_job_count', lambda: 1)
    monkeypatch.setattr(runtime_process._SPAWN, 'Process', FakeProcess)
    monkeypatch.setattr(runtime_process.settings, 'build_worker_min_processes', 0, raising=False)
    monkeypatch.setattr(runtime_process.settings, 'build_worker_max_processes', 2, raising=False)

    await runtime_process.run_build_manager_process(stop_event=stop_event)

    names = [name for name, _ in calls]
    assert names[0:3] == ['init_db', 'start_api_server', 'register_manager']
    assert 'child_start' in names
    assert any(name == 'stop_api_server' for name, _ in calls)
    assert ('stop_manager', 'manager-1') in calls
