from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Session

from backend_contracts.build_jobs.models import BuildJobStatus
from backend_contracts.build_runs.models import BuildRunStatus
from backend_contracts.compute import schemas as compute_schemas
from backend_contracts.compute_requests.models import ComputeRequestKind, ComputeRequestStatus
from backend_contracts.datasource.source_types import DataSourceType
from backend_core import build_jobs_service, build_runs_service, compute_requests_service
from backend_core.config import settings
from backend_core.database import run_settings_db
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_workers.models import RuntimeWorker


def _set_internal_token(monkeypatch) -> str:
    token = 'test-internal-token'
    monkeypatch.setattr(settings, 'internal_api_token', token)
    return token


def _headers(token: str) -> dict[str, str]:
    return {'X-Internal-Token': token}


def test_internal_worker_registers_heartbeats_and_stops(client, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'

    response = client.post(
        '/api/v1/internal/worker/register',
        headers=_headers(token),
        json={
            'worker_id': worker_id,
            'kind': 'build_worker',
            'hostname': 'worker-host',
            'pid': 123,
            'capacity': 1,
        },
    )
    assert response.status_code == 200

    response = client.post(
        '/api/v1/internal/worker/heartbeat',
        headers=_headers(token),
        json={'worker_id': worker_id, 'active_jobs': 1},
    )
    assert response.status_code == 200
    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.active_jobs == 1

    response = client.post('/api/v1/internal/worker/stop', headers=_headers(token), json={'worker_id': worker_id})
    assert response.status_code == 200
    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.stopped_at is not None


def test_internal_worker_claims_and_finalizes_build_job(client, test_db_session: Session, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=str(uuid.uuid4()),
        analysis_name='RPC boundary test',
        request_json={'analysis_pipeline': {'analysis_id': str(uuid.uuid4()), 'tabs': []}, 'tab_id': 'tab-1'},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.COMPLETED,
        created_at=datetime.now(UTC),
    )
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')

    response = client.post('/api/v1/internal/worker/claim-build-job', headers=_headers(token), json={'worker_id': worker_id})
    assert response.status_code == 200
    data = response.json()
    assert data['job'] == {'job_id': job.id, 'build_id': build_id, 'namespace': 'default'}

    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.RUNNING
    assert job.lease_owner == worker_id

    response = client.post(
        '/api/v1/internal/worker/finalize-build-job',
        headers=_headers(token),
        json={'job_id': job.id, 'build_id': build_id, 'namespace': 'default'},
    )
    assert response.status_code == 200
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.COMPLETED
    assert job.lease_owner is None


def test_internal_worker_counts_and_releases_jobs(client, test_db_session: Session, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')

    response = client.post('/api/v1/internal/worker/queued-build-job-count', headers=_headers(token), json={})
    assert response.status_code == 200
    assert response.json()['queued'] >= 1

    response = client.post('/api/v1/internal/worker/claim-build-job', headers=_headers(token), json={'worker_id': worker_id})
    assert response.status_code == 200

    response = client.post('/api/v1/internal/worker/release-build-worker-jobs', headers=_headers(token), json={'worker_id': worker_id})
    assert response.status_code == 200
    assert response.json()['released'] == 1
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.QUEUED
    assert job.lease_owner is None


def test_internal_worker_claims_completes_and_fails_compute_requests(client, test_db_session: Session, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    worker_id = f'build-manager:{uuid.uuid4()}'
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.SHUTDOWN_ENGINE,
        request_json={'analysis_id': 'analysis-1'},
    )

    response = client.post('/api/v1/internal/worker/claim-compute-request', headers=_headers(token), json={'worker_id': worker_id})
    assert response.status_code == 200
    data = response.json()
    assert data['request'] == {
        'id': request.id,
        'namespace': 'default',
        'kind': ComputeRequestKind.SHUTDOWN_ENGINE.value,
        'request_json': {'analysis_id': 'analysis-1'},
    }
    test_db_session.refresh(request)
    assert request.status == ComputeRequestStatus.RUNNING
    assert request.lease_owner == worker_id

    response = client.post(
        '/api/v1/internal/worker/complete-compute-request',
        headers=_headers(token),
        json={'namespace': 'default', 'request_id': request.id, 'response_json': {'success': True}},
    )
    assert response.status_code == 200
    test_db_session.refresh(request)
    assert request.status == ComputeRequestStatus.COMPLETED

    failed_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.SCHEMA,
        request_json={'analysis_id': 'analysis-2'},
    )
    response = client.post('/api/v1/internal/worker/claim-compute-request', headers=_headers(token), json={'worker_id': worker_id})
    assert response.status_code == 200
    assert response.json()['request']['id'] == failed_request.id

    response = client.post(
        '/api/v1/internal/worker/fail-compute-request',
        headers=_headers(token),
        json={
            'namespace': 'default',
            'request_id': failed_request.id,
            'error_message': 'boom',
            'response_json': {'error': 'boom', 'status_code': 500},
        },
    )
    assert response.status_code == 200
    test_db_session.refresh(failed_request)
    assert failed_request.status == ComputeRequestStatus.FAILED


def test_internal_worker_executes_datasource_request(client, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)

    class _Response:
        def model_dump(self, *, mode: str):
            assert mode == 'json'
            return {'id': 'ds-1', 'name': 'Created'}

    def fake_create_database_datasource(**kwargs):
        assert kwargs['name'] == 'Created'
        assert kwargs['connection_string'] == 'postgresql://example/db'
        assert kwargs['query'] == 'SELECT 1'
        return _Response()

    monkeypatch.setattr('modules.datasource.runtime_service.create_database_datasource', fake_create_database_datasource)

    response = client.post(
        '/api/v1/internal/worker/execute-datasource-request',
        headers=_headers(token),
        json={
            'namespace': 'default',
            'kind': ComputeRequestKind.CREATE_DATABASE_DATASOURCE.value,
            'request_json': {
                'name': 'Created',
                'description': None,
                'connection_string': 'postgresql://example/db',
                'query': 'SELECT 1',
                'branch': 'main',
                'owner_id': None,
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {'response_json': {'id': 'ds-1', 'name': 'Created'}}


def test_internal_worker_persists_build_event_with_backend_contracts(client, test_db_session: Session, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    build_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Event RPC boundary test',
        request_json={'analysis_pipeline': {'analysis_id': analysis_id, 'tabs': []}, 'tab_id': 'tab-1'},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.RUNNING,
        created_at=datetime.now(UTC),
    )
    event = compute_schemas.BuildCompleteEvent(
        build_id=build_id,
        analysis_id=analysis_id,
        emitted_at=datetime.now(UTC),
        elapsed_ms=12,
        total_steps=0,
        tabs_built=1,
        results=[],
        duration_ms=12,
    )

    response = client.post(
        '/api/v1/internal/worker/persist-build-event',
        headers=_headers(token),
        json={
            'namespace': 'default',
            'build_id': build_id,
            'event': event.model_dump(mode='json'),
        },
    )

    assert response.status_code == 200
    assert response.json()['sequence'] == 1
    run = build_runs_service.get_build_run(test_db_session, build_id)
    assert run is not None
    assert run.status == BuildRunStatus.COMPLETED


def test_internal_worker_starts_build_run_and_returns_payload(client, test_db_session: Session, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    build_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Start RPC boundary test',
        request_json={'analysis_pipeline': {'analysis_id': analysis_id, 'tabs': []}, 'tab_id': 'tab-1'},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.QUEUED,
        created_at=datetime.now(UTC),
    )

    response = client.post(
        '/api/v1/internal/worker/start-build-run',
        headers=_headers(token),
        json={'namespace': 'default', 'build_id': build_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data['run']['id'] == build_id
    assert data['run']['analysis_id'] == analysis_id
    run = build_runs_service.get_build_run(test_db_session, build_id)
    assert run is not None
    assert run.status == BuildRunStatus.RUNNING


def test_internal_worker_lists_and_finalizes_datasource_delete(client, test_db_session: Session, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Pending delete datasource',
            source_type=DataSourceType.FILE.value,
            config={'file_path': 's3://external-bucket/source.csv', 'file_type': 'csv'},
            is_hidden=True,
            is_pending_delete=True,
            created_at=datetime.now(UTC),
            delete_requested_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    response = client.post('/api/v1/internal/worker/pending-datasource-deletes', headers=_headers(token), json={})
    assert response.status_code == 200
    assert {'namespace': 'default', 'datasource_id': datasource_id} in response.json()['deletes']

    response = client.post(
        '/api/v1/internal/worker/finalize-datasource-delete',
        headers=_headers(token),
        json={'namespace': 'default', 'datasource_id': datasource_id},
    )
    assert response.status_code == 200
    assert response.json() == {'deleted': True}
    test_db_session.expire_all()
    assert test_db_session.get(DataSource, datasource_id) is None
