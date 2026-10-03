from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend_core import (
    build_jobs_service as build_job_service,
    engine_instances_service as engine_instance_service,
    runtime_workers_service as runtime_worker_service,
)
from backend_core.database import run_db, run_settings_db
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.domain.compute.base import EngineStatusInfo
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.namespace import namespace_paths


def test_runtime_overview_reports_runtime_state(client, monkeypatch) -> None:
    from backend_core.config import settings

    monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
    monkeypatch.setattr(
        settings,
        'database_url',
        'postgresql+psycopg://user:pass@host:5432/db',
        raising=False,
    )

    run_settings_db(
        runtime_worker_service.register_worker,
        worker_id='build-manager-1',
        kind=RuntimeWorkerKind.BUILD_MANAGER,
        hostname='manager-host',
        pid=111,
        capacity=4,
        active_jobs=0,
    )
    run_settings_db(
        runtime_worker_service.register_worker,
        worker_id='build-worker-1',
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname='worker-host',
        pid=222,
        capacity=1,
        active_jobs=1,
    )
    run_settings_db(
        engine_instance_service.upsert_engine_status,
        worker_id='build-worker-1',
        namespace='default',
        status=EngineStatusInfo(
            analysis_id='',
            resource_id='preview-ds',
            status='healthy',
            container_id='container-preview',
            image_digest='sha256:preview',
            lifecycle_status='running',
            termination_reason=None,
            exit_code=None,
            oom_killed=None,
            supervisor_id='build-worker-1',
            owner_id='build-worker-1',
            last_activity=datetime.now(UTC).isoformat(),
            current_job_id='job-live',
            resource_config={'max_threads': 2},
            effective_resources={'max_threads': 2},
            defaults={'max_threads': 2},
            scope='datasource_preview',
            reuse_policy='shared',
            datasource_id='preview-ds',
        ),
    )
    run_settings_db(
        engine_instance_service.upsert_engine_status,
        worker_id='build-worker-1',
        namespace='default',
        status=EngineStatusInfo(
            analysis_id='',
            resource_id='build-live',
            status='healthy',
            container_id='container-build',
            image_digest='sha256:build',
            lifecycle_status='running',
            termination_reason=None,
            exit_code=None,
            oom_killed=None,
            supervisor_id='build-worker-1',
            owner_id='build-live',
            last_activity=datetime.now(UTC).isoformat(),
            current_job_id='job-build',
            resource_config=None,
            effective_resources=None,
            defaults={'max_threads': 2},
            scope='build',
            reuse_policy='exclusive',
            build_id='build-live',
            current_build_id='build-live',
            current_engine_run_id='run-live',
        ),
    )

    queued_id = str(uuid.uuid4())
    run_db(build_job_service.create_job, build_id=queued_id, namespace='default')
    running_id = str(uuid.uuid4())
    run_db(build_job_service.create_job, build_id=running_id, namespace='default')
    run_db(_set_running_job_owner, running_id, 'build-worker-1')

    orphaned_id = str(uuid.uuid4())
    run_db(build_job_service.create_job, build_id=orphaned_id, namespace='default')
    run_db(_set_running_job_owner, orphaned_id, 'dead-worker')
    run_settings_db(
        runtime_worker_service.register_worker,
        worker_id='dead-worker',
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname='worker-host',
        pid=333,
        capacity=1,
        now=datetime.now(UTC).replace(year=2024),
    )

    response = client.get('/api/v1/runtime/overview')

    assert response.status_code == 200
    body = response.json()
    assert body['mode'] == 'distributed'
    assert body['api']['worker_id'].startswith('api:')
    assert body['api']['version'] == settings.app_version
    assert any(item['id'] == 'build-manager-1' and item['kind'] == 'build_manager' for item in body['workers'])
    assert any(item['id'] == 'build-worker-1' for item in body['workers'])
    assert any(
        item['resource_id'] == 'preview-ds' and item['scope'] == 'datasource_preview' and item['datasource_id'] == 'preview-ds' for item in body['engines']
    )
    assert any(
        item['resource_id'] == 'build-live'
        and item['scope'] == 'build'
        and item['build_id'] == 'build-live'
        and item['current_build_id'] == 'build-live'
        and item['current_engine_run_id'] == 'run-live'
        for item in body['engines']
    )
    assert body['queue']['totals']['queued'] == 1
    assert body['queue']['totals']['running'] == 1
    assert body['queue']['totals']['orphaned'] == 1
    assert body['queue']['totals']['oldest_queued_age_seconds'] is not None


def _set_running_job_owner(session, build_id: str, worker_id: str) -> None:
    job = build_job_service.get_job_by_build_id(session, build_id)
    assert job is not None
    job.status = BuildJobStatus.RUNNING
    job.lease_owner = worker_id
    session.add(job)
    session.commit()


def test_runtime_overview_includes_filesystem_namespaces(client, monkeypatch) -> None:
    from backend_core.config import settings

    monkeypatch.setattr(settings, 'distributed_runtime_enabled', False, raising=False)
    namespace_paths('beta')

    response = client.get('/api/v1/runtime/overview')

    assert response.status_code == 200
    namespaces = [item['namespace'] for item in response.json()['queue']['namespaces']]
    assert namespaces == ['default', 'beta']


def test_runtime_overview_executes_its_database_unit_on_the_bounded_api_executor(client, monkeypatch) -> None:
    import threading

    from modules.runtime_overview import routes, schemas

    thread_names: list[str] = []
    response_body = schemas.RuntimeOverviewResponse(
        mode='durable_single_node',
        api=schemas.ApiProcessSummary(worker_id='api:test', pid=1, hostname='test', version='test'),
        workers=[],
        engines=[],
        queue=schemas.QueueSummary(
            namespaces=[],
            totals=schemas.QueueTotalsSummary(
                queued=0,
                running=0,
                orphaned=0,
                oldest_queued_at=None,
                oldest_queued_age_seconds=None,
            ),
        ),
    )

    def read_overview(_worker_id: str | None) -> schemas.RuntimeOverviewResponse:
        thread_names.append(threading.current_thread().name)
        return response_body

    monkeypatch.setattr(routes, '_read_runtime_overview', read_overview)

    response = client.get('/api/v1/runtime/overview')

    assert response.status_code == 200
    assert thread_names and thread_names[0].startswith('api-blocking_')


def test_queue_summary_reuses_the_runtime_overview_settings_session(monkeypatch) -> None:
    from typing import cast

    from sqlmodel import Session

    from modules.runtime_overview import schemas, service

    session = cast(Session, object())
    worker_sessions: list[object] = []

    def reclaimable_worker_ids(used_session, *, kind):
        assert kind == RuntimeWorkerKind.BUILD_WORKER
        worker_sessions.append(used_session)
        return set()

    def read_namespace(_function, *, namespace, reclaimable_worker_ids):
        assert reclaimable_worker_ids == set()
        return schemas.QueueNamespaceSummary(
            namespace=namespace,
            queued=0,
            running=0,
            orphaned=0,
            oldest_queued_at=None,
            oldest_queued_age_seconds=None,
        )

    monkeypatch.setattr(service.runtime_workers_service, 'reclaimable_worker_ids', reclaimable_worker_ids)
    monkeypatch.setattr(service, 'run_db', read_namespace)
    monkeypatch.setattr(service, 'list_namespaces', lambda: ['default'])

    summary = service.queue_summary(session)

    assert worker_sessions == [session]
    assert summary.totals.queued == 0
    assert summary.namespaces[0].namespace == 'default'
