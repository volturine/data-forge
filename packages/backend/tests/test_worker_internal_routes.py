from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from backend_core import build_jobs_service, build_runs_service, compute_requests_service
from backend_core.config import settings
from backend_core.database import run_settings_db
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute_requests.models import ComputeRequestKind, ComputeRequestStatus
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.domain.engine_runs.schemas import EngineRunKind
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_workers.models import RuntimeWorker
from backend_grpc.codec import dict_to_struct, struct_to_dict
from backend_grpc.server import WorkerRuntimeServicer
from dataforge_protocol import common_pb2, enums_pb2, worker_runtime_pb2


class FakeGrpcContext:
    def __init__(self, token: str) -> None:
        self._metadata = (('x-internal-token', token),)

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._metadata

    async def abort(self, _code, details: str) -> None:
        raise RuntimeError(details)


def _context(monkeypatch: pytest.MonkeyPatch) -> FakeGrpcContext:
    token = 'test-internal-token'
    monkeypatch.setattr(settings, 'internal_api_token', token)
    return FakeGrpcContext(token)


@pytest.mark.asyncio
async def test_internal_worker_grpc_registers_heartbeats_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    servicer = WorkerRuntimeServicer()

    await servicer.RegisterWorker(
        worker_runtime_pb2.RuntimeWorkerRegisterRequest(
            worker_id=worker_id,
            kind=enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER,
            hostname='worker-host',
            pid=123,
            capacity=1,
        ),
        context,  # type: ignore[arg-type]
    )
    await servicer.HeartbeatWorker(worker_runtime_pb2.RuntimeWorkerHeartbeatRequest(worker_id=worker_id, active_jobs=1), context)  # type: ignore[arg-type]

    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.active_jobs == 1

    await servicer.StopWorker(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)  # type: ignore[arg-type]
    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.stopped_at is not None


@pytest.mark.asyncio
async def test_internal_worker_grpc_claims_and_finalizes_build_job(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=str(uuid.uuid4()),
        analysis_name='gRPC boundary test',
        request_json={'analysis_pipeline': {'analysis_id': str(uuid.uuid4()), 'tabs': []}, 'tab_id': 'tab-1'},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.COMPLETED,
        created_at=datetime.now(UTC),
    )
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    servicer = WorkerRuntimeServicer()

    response = await servicer.ClaimBuildJob(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)  # type: ignore[arg-type]

    assert response.HasField('job')
    assert response.job.job_id == job.id
    assert response.job.build_id == build_id
    assert response.job.namespace == 'default'
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.RUNNING
    assert job.lease_owner == worker_id

    await servicer.FinalizeBuildJob(
        worker_runtime_pb2.WorkerFinalizeBuildJobRequest(job_id=job.id, build_id=build_id, namespace='default'),
        context,  # type: ignore[arg-type]
    )
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.COMPLETED
    assert job.lease_owner is None


@pytest.mark.asyncio
async def test_internal_worker_grpc_counts_and_releases_jobs(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    servicer = WorkerRuntimeServicer()

    queued = await servicer.GetQueuedBuildJobCount(common_pb2.EmptyRequest(), context)  # type: ignore[arg-type]
    assert queued.count >= 1

    await servicer.ClaimBuildJob(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)  # type: ignore[arg-type]
    released = await servicer.ReleaseBuildWorkerJobs(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)  # type: ignore[arg-type]
    assert released.count == 1
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.QUEUED
    assert job.lease_owner is None


@pytest.mark.asyncio
async def test_internal_worker_grpc_claims_completes_and_fails_compute_requests(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'build-manager:{uuid.uuid4()}'
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.SHUTDOWN_ENGINE,
        request_json={'analysis_id': 'analysis-1'},
    )
    servicer = WorkerRuntimeServicer()

    response = await servicer.ClaimComputeRequest(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)  # type: ignore[arg-type]

    assert response.HasField('request')
    assert response.request.id == request.id
    assert response.request.namespace == 'default'
    assert response.request.kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE
    assert struct_to_dict(response.request.request) == {'analysis_id': 'analysis-1'}
    test_db_session.refresh(request)
    assert request.status == ComputeRequestStatus.RUNNING
    assert request.lease_owner == worker_id

    await servicer.CompleteComputeRequest(
        worker_runtime_pb2.WorkerCompleteComputeRequestRequest(
            namespace='default',
            request_id=request.id,
            response=dict_to_struct({'success': True}),
        ),
        context,  # type: ignore[arg-type]
    )
    test_db_session.refresh(request)
    assert request.status == ComputeRequestStatus.COMPLETED

    failed_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.SCHEMA,
        request_json={'analysis_id': 'analysis-2'},
    )
    response = await servicer.ClaimComputeRequest(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)  # type: ignore[arg-type]
    assert response.request.id == failed_request.id

    await servicer.FailComputeRequest(
        worker_runtime_pb2.WorkerFailComputeRequestRequest(
            namespace='default',
            request_id=failed_request.id,
            error_message='boom',
            response=dict_to_struct({'error': 'boom', 'status_code': 500}),
        ),
        context,  # type: ignore[arg-type]
    )
    test_db_session.refresh(failed_request)
    assert failed_request.status == ComputeRequestStatus.FAILED


@pytest.mark.asyncio
async def test_internal_worker_grpc_executes_datasource_request(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)

    class _Response:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == 'json'
            return {'id': 'ds-1', 'name': 'Created'}

    def fake_create_database_datasource(**kwargs):
        assert kwargs['name'] == 'Created'
        assert kwargs['connection_string'] == 'postgresql://example/db'
        assert kwargs['query'] == 'SELECT 1'
        return _Response()

    monkeypatch.setattr('modules.datasource.runtime_service.create_database_datasource', fake_create_database_datasource)

    response = await WorkerRuntimeServicer().ExecuteDatasourceRequest(
        worker_runtime_pb2.WorkerExecuteDatasourceRequest(
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
            request=dict_to_struct(
                {
                    'name': 'Created',
                    'description': None,
                    'connection_string': 'postgresql://example/db',
                    'query': 'SELECT 1',
                    'branch': 'main',
                    'owner_id': None,
                }
            ),
        ),
        context,  # type: ignore[arg-type]
    )

    assert struct_to_dict(response.response) == {'id': 'ds-1', 'name': 'Created'}


@pytest.mark.asyncio
async def test_internal_worker_grpc_persists_build_event(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    build_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Event gRPC boundary test',
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

    response = await WorkerRuntimeServicer().PersistBuildEvent(
        worker_runtime_pb2.WorkerPersistBuildEventRequest(namespace='default', build_id=build_id, event=dict_to_struct(event.model_dump(mode='json'))),
        context,  # type: ignore[arg-type]
    )

    assert response.sequence == 1
    run = build_runs_service.get_build_run(test_db_session, build_id)
    assert run is not None
    assert run.status == BuildRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_internal_worker_grpc_starts_build_run_and_returns_payload(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    build_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Start gRPC boundary test',
        request_json={'analysis_pipeline': {'analysis_id': analysis_id, 'tabs': []}, 'tab_id': 'tab-1'},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.QUEUED,
        current_kind=EngineRunKind.BUILD.value,
        created_at=datetime.now(UTC),
    )

    response = await WorkerRuntimeServicer().StartBuildRun(
        worker_runtime_pb2.WorkerStartBuildRunRequest(namespace='default', build_id=build_id),
        context,  # type: ignore[arg-type]
    )

    assert response.HasField('run')
    assert response.run.id == build_id
    assert response.run.analysis_id == analysis_id
    assert response.run.current_kind == enums_pb2.ENGINE_RUN_KIND_BUILD
    run = build_runs_service.get_build_run(test_db_session, build_id)
    assert run is not None
    assert run.status == BuildRunStatus.RUNNING
    assert run.current_kind == EngineRunKind.BUILD.value


@pytest.mark.asyncio
async def test_internal_worker_grpc_lists_and_finalizes_datasource_delete(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
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
    servicer = WorkerRuntimeServicer()

    response = await servicer.ListPendingDatasourceDeletes(common_pb2.EmptyRequest(), context)  # type: ignore[arg-type]
    assert (datasource_id, 'default') in {(item.datasource_id, item.namespace) for item in response.deletes}

    finalized = await servicer.FinalizeDatasourceDelete(
        worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest(namespace='default', datasource_id=datasource_id),
        context,  # type: ignore[arg-type]
    )
    assert finalized.deleted is True
    test_db_session.expire_all()
    assert test_db_session.get(DataSource, datasource_id) is None
