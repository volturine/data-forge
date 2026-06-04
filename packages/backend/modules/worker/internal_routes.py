from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select

from backend_contracts.build_runs.models import BuildRunStatus
from backend_contracts.compute import schemas as compute_schemas
from backend_contracts.compute.base import EngineStatusInfo
from backend_contracts.compute_requests.models import ComputeRequestKind
from backend_contracts.datasource.models import DataSourceCreatedBy
from backend_contracts.runtime_workers.models import RuntimeWorkerKind
from backend_contracts.step_config_enums import AIProvider
from backend_core import (
    build_event_service,
    build_jobs_service as build_job_service,
    build_runs_service as build_run_service,
    compute_requests_service,
    datasource_delete_service,
    engine_instances_service as engine_instance_service,
    engine_runs_service as engine_run_service,
    http as http_client,
    runtime_ipc,
    runtime_outbox_service,
    runtime_workers_service as runtime_worker_service,
)
from backend_core.ai_clients import get_ai_client
from backend_core.config import settings
from backend_core.database import get_db, run_db, run_settings_db
from backend_core.datasource_storage import cleanup_datasource_storage
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.namespaces_service import list_runtime_namespaces
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult
from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
from backend_core.persistence.udfs.models import Udf
from backend_core.settings_projection import get_resolved_smtp, get_resolved_telegram_settings, get_resolved_telegram_token
from backend_core.smtp import send_smtp_message
from modules.datasource import runtime_service as datasource_runtime_service
from modules.scheduler import service as scheduler_service
from modules.worker.internal_schemas import (
    RuntimeWorkerHeartbeatRequest,
    RuntimeWorkerRegisterRequest,
    RuntimeWorkerRequest,
    RuntimeWorkerResponse,
    WorkerAnalysisMetadataRequest,
    WorkerAnalysisMetadataResponse,
    WorkerBuildCancelStatusRequest,
    WorkerBuildCancelStatusResponse,
    WorkerBuildRunPayload,
    WorkerClaimBuildJobRequest,
    WorkerClaimBuildJobResponse,
    WorkerClaimComputeRequestRequest,
    WorkerClaimComputeRequestResponse,
    WorkerClaimedBuildJob,
    WorkerClaimedComputeRequest,
    WorkerCompleteComputeRequestRequest,
    WorkerCreateEngineRunRequest,
    WorkerDatasourceMetadataRequest,
    WorkerDatasourceMetadataResponse,
    WorkerDispatchOutboxResponse,
    WorkerEngineRunResponse,
    WorkerEngineRunStateRequest,
    WorkerEngineRunStateResponse,
    WorkerExecuteDatasourceRequest,
    WorkerExecuteDatasourceResponse,
    WorkerFailBuildJobRequest,
    WorkerFailComputeRequestRequest,
    WorkerFinalizeBuildJobRequest,
    WorkerFinalizeDatasourceDeleteRequest,
    WorkerFinalizeDatasourceDeleteResponse,
    WorkerGenerateAIRequest,
    WorkerGenerateAIResponse,
    WorkerHealthCheckSpec,
    WorkerIdlePidsResponse,
    WorkerListHealthChecksRequest,
    WorkerListHealthChecksResponse,
    WorkerNamespacesResponse,
    WorkerNotificationResponse,
    WorkerPendingDatasourceDelete,
    WorkerPendingDatasourceDeletesResponse,
    WorkerPersistBuildEventRequest,
    WorkerPersistBuildEventResponse,
    WorkerPersistEngineSnapshotRequest,
    WorkerPersistEngineSnapshotResponse,
    WorkerQueueCountResponse,
    WorkerRecordHealthCheckResultsRequest,
    WorkerRecordHealthCheckResultsResponse,
    WorkerReleaseComputeRequestsResponse,
    WorkerReleaseJobsResponse,
    WorkerScheduleIngestDatasourceRequest,
    WorkerSendEmailRequest,
    WorkerSendTelegramRequest,
    WorkerStartBuildRunRequest,
    WorkerStartBuildRunResponse,
    WorkerTelegramSettingsResponse,
    WorkerTelegramTarget,
    WorkerTelegramTargetsRequest,
    WorkerTelegramTargetsResponse,
    WorkerUdfCodesRequest,
    WorkerUdfCodesResponse,
    WorkerUpdateBuildResultRequest,
    WorkerUpdateEngineRunRequest,
    WorkerUpsertOutputDatasourceRequest,
    WorkerUpsertOutputDatasourceResponse,
)

router = APIRouter(prefix='/internal/worker', tags=['internal-worker'])
_TELEGRAM_BASE_URL = 'https://api.telegram.org'


def _require_internal_token(x_internal_token: Annotated[str | None, Header(alias='X-Internal-Token')] = None) -> None:
    if not settings.internal_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='INTERNAL_API_TOKEN must be configured before internal runtime endpoints can be used',
        )
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid internal runtime token')


def _parse_worker_kind(value: str) -> RuntimeWorkerKind:
    try:
        return RuntimeWorkerKind(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f'Unsupported runtime worker kind: {value}') from exc


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return str(value) if value is not None else None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return int(value) if value is not None and isinstance(value, (str, int)) else None


def _read_optional_dict(payload: dict[str, object], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else None


def _parse_optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


@router.post('/register', response_model=RuntimeWorkerResponse)
def register_worker(payload: RuntimeWorkerRegisterRequest, _: None = Depends(_require_internal_token)) -> RuntimeWorkerResponse:
    def _register(session):
        runtime_worker_service.register_worker(
            session,
            worker_id=payload.worker_id,
            kind=_parse_worker_kind(payload.kind),
            hostname=payload.hostname,
            pid=payload.pid,
            capacity=payload.capacity,
            active_jobs=payload.active_jobs,
        )

    run_settings_db(_register)
    return RuntimeWorkerResponse(worker_id=payload.worker_id)


@router.post('/heartbeat', response_model=RuntimeWorkerResponse)
def heartbeat_worker(payload: RuntimeWorkerHeartbeatRequest, _: None = Depends(_require_internal_token)) -> RuntimeWorkerResponse:
    def _heartbeat(session):
        runtime_worker_service.heartbeat_worker(session, worker_id=payload.worker_id, active_jobs=payload.active_jobs)

    run_settings_db(_heartbeat)
    return RuntimeWorkerResponse(worker_id=payload.worker_id)


@router.post('/stop', response_model=RuntimeWorkerResponse)
def stop_worker(payload: RuntimeWorkerRequest, _: None = Depends(_require_internal_token)) -> RuntimeWorkerResponse:
    def _stop(session):
        runtime_worker_service.mark_worker_stopped(session, worker_id=payload.worker_id)

    run_settings_db(_stop)
    return RuntimeWorkerResponse(worker_id=payload.worker_id)


@router.post('/claim-build-job', response_model=WorkerClaimBuildJobResponse)
def claim_build_job(payload: WorkerClaimBuildJobRequest, _: None = Depends(_require_internal_token)) -> WorkerClaimBuildJobResponse:
    reclaimable_owner_ids = run_settings_db(
        runtime_worker_service.reclaimable_worker_ids,
        kind=RuntimeWorkerKind.BUILD_WORKER,
    )
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            job = run_db(
                build_job_service.claim_next_job,
                worker_id=payload.worker_id,
                reclaimable_owner_ids=reclaimable_owner_ids,
            )
        finally:
            reset_namespace(token)
        if job is not None:
            return WorkerClaimBuildJobResponse(job=WorkerClaimedBuildJob(job_id=job.id, build_id=job.build_id, namespace=job.namespace))
    return WorkerClaimBuildJobResponse(job=None)


@router.post('/claim-compute-request', response_model=WorkerClaimComputeRequestResponse)
def claim_compute_request(
    payload: WorkerClaimComputeRequestRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerClaimComputeRequestResponse:
    reclaimable_owner_ids = run_settings_db(
        runtime_worker_service.reclaimable_worker_ids,
        kind=RuntimeWorkerKind.BUILD_MANAGER,
    )
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            request = run_db(
                compute_requests_service.claim_next_request,
                worker_id=payload.worker_id,
                reclaimable_owner_ids=reclaimable_owner_ids,
            )
            if request is None:
                continue
            return WorkerClaimComputeRequestResponse(
                request=WorkerClaimedComputeRequest(
                    id=request.id,
                    namespace=request.namespace,
                    kind=request.kind.value,
                    request_json=compute_requests_service.command_payload(request),
                )
            )
        finally:
            reset_namespace(token)
    return WorkerClaimComputeRequestResponse(request=None)


@router.post('/complete-compute-request', response_model=RuntimeWorkerResponse)
def complete_compute_request(
    payload: WorkerCompleteComputeRequestRequest,
    _: None = Depends(_require_internal_token),
) -> RuntimeWorkerResponse:
    token = set_namespace_context(payload.namespace)
    try:
        run_db(
            compute_requests_service.mark_request_completed,
            payload.request_id,
            response_json=payload.response_json,
            artifact_path=payload.artifact_path,
            artifact_name=payload.artifact_name,
            artifact_content_type=payload.artifact_content_type,
        )
        return RuntimeWorkerResponse(worker_id=payload.request_id)
    finally:
        reset_namespace(token)


@router.post('/fail-compute-request', response_model=RuntimeWorkerResponse)
def fail_compute_request(payload: WorkerFailComputeRequestRequest, _: None = Depends(_require_internal_token)) -> RuntimeWorkerResponse:
    token = set_namespace_context(payload.namespace)
    try:
        run_db(
            compute_requests_service.mark_request_failed,
            payload.request_id,
            error_message=payload.error_message,
            response_json=payload.response_json,
        )
        return RuntimeWorkerResponse(worker_id=payload.request_id)
    finally:
        reset_namespace(token)


@router.post('/release-compute-requests', response_model=WorkerReleaseComputeRequestsResponse)
def release_compute_requests(payload: RuntimeWorkerRequest, _: None = Depends(_require_internal_token)) -> WorkerReleaseComputeRequestsResponse:
    released = 0
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            released += len(run_db(compute_requests_service.release_worker_requests, worker_id=payload.worker_id))
        finally:
            reset_namespace(token)
    return WorkerReleaseComputeRequestsResponse(released=released)


@router.post('/execute-datasource-request', response_model=WorkerExecuteDatasourceResponse)
def execute_datasource_request(
    payload: WorkerExecuteDatasourceRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerExecuteDatasourceResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        kind = ComputeRequestKind(payload.kind)
        request_json = payload.request_json
        response: Any
        if kind == ComputeRequestKind.CREATE_FILE_DATASOURCE:
            raw_csv_options = request_json.get('csv_options')
            csv_options = datasource_runtime_service.CSVOptions.model_validate(raw_csv_options) if isinstance(raw_csv_options, dict) else None
            response = datasource_runtime_service.create_file_datasource(
                session=session,
                name=str(request_json['name']),
                description=str(request_json['description']) if request_json.get('description') is not None else None,
                file_path=str(request_json['file_path']),
                file_type=str(request_json['file_type']),
                options=_read_optional_dict(request_json, 'options'),
                csv_options=csv_options,
                sheet_name=_read_optional_str(request_json, 'sheet_name'),
                start_row=_read_optional_int(request_json, 'start_row'),
                start_col=_read_optional_int(request_json, 'start_col'),
                end_col=_read_optional_int(request_json, 'end_col'),
                end_row=_read_optional_int(request_json, 'end_row'),
                has_header=bool(request_json['has_header']) if request_json.get('has_header') is not None else None,
                table_name=_read_optional_str(request_json, 'table_name'),
                named_range=_read_optional_str(request_json, 'named_range'),
                cell_range=_read_optional_str(request_json, 'cell_range'),
                owner_id=_read_optional_str(request_json, 'owner_id'),
            )
        elif kind == ComputeRequestKind.CREATE_DATABASE_DATASOURCE:
            response = datasource_runtime_service.create_database_datasource(
                session=session,
                name=str(request_json['name']),
                description=str(request_json['description']) if request_json.get('description') is not None else None,
                connection_string=str(request_json['connection_string']),
                query=str(request_json['query']),
                branch=str(request_json['branch']),
                owner_id=str(request_json['owner_id']) if request_json.get('owner_id') is not None else None,
            )
        elif kind == ComputeRequestKind.CREATE_ICEBERG_DATASOURCE:
            raw_source = request_json.get('source')
            if not isinstance(raw_source, dict):
                raise ValueError('source is required')
            response = datasource_runtime_service.create_iceberg_datasource(
                session=session,
                name=str(request_json['name']),
                description=str(request_json['description']) if request_json.get('description') is not None else None,
                source=dict(raw_source),
                branch=str(request_json['branch']),
                owner_id=str(request_json['owner_id']) if request_json.get('owner_id') is not None else None,
            )
        elif kind == ComputeRequestKind.INGEST_DATASOURCE:
            response = datasource_runtime_service.ingest_external_datasource(session, str(request_json['datasource_id']))
        elif kind == ComputeRequestKind.DATASOURCE_SCHEMA:
            response = datasource_runtime_service.get_datasource_schema(
                session,
                str(request_json['datasource_id']),
                sheet_name=_read_optional_str(request_json, 'sheet_name'),
                refresh=bool(request_json.get('refresh', False)),
            )
        elif kind == ComputeRequestKind.DATASOURCE_COLUMN_STATS:
            response = datasource_runtime_service.get_column_stats(
                session=session,
                datasource_id=str(request_json['datasource_id']),
                column_name=str(request_json['column_name']),
                use_sample=bool(request_json.get('use_sample', True)),
                sample_size=_read_optional_int(request_json, 'sample_size') or 10000,
                datasource_config=_read_optional_dict(request_json, 'datasource_config'),
            )
        elif kind == ComputeRequestKind.COMPARE_ICEBERG_SNAPSHOTS:
            response = datasource_runtime_service.compare_iceberg_snapshots(
                session,
                str(request_json['datasource_id']),
                str(request_json['snapshot_a']),
                str(request_json['snapshot_b']),
                _read_optional_int(request_json, 'row_limit') or 10,
            )
        else:
            raise ValueError(f'Unsupported datasource request kind: {kind.value}')
        return WorkerExecuteDatasourceResponse(response_json=response.model_dump(mode='json'))
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/schedule-ingest-datasource', response_model=WorkerExecuteDatasourceResponse)
def schedule_ingest_datasource(
    payload: WorkerScheduleIngestDatasourceRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerExecuteDatasourceResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        response = datasource_runtime_service.ingest_datasource_for_schedule(session, payload.datasource_id)
        return WorkerExecuteDatasourceResponse(response_json=response.model_dump(mode='json'))
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/datasource-metadata', response_model=WorkerDatasourceMetadataResponse)
def datasource_metadata(
    payload: WorkerDatasourceMetadataRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerDatasourceMetadataResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        datasource = session.get(DataSource, payload.datasource_id)
        if datasource is None:
            return WorkerDatasourceMetadataResponse(found=False)
        return WorkerDatasourceMetadataResponse(
            found=True,
            id=datasource.id,
            name=datasource.name,
            source_type=datasource.source_type,
            config=dict(datasource.config),
            schema_cache=dict(datasource.schema_cache) if isinstance(datasource.schema_cache, dict) else None,
            is_hidden=datasource.is_hidden,
        )
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/udf-codes', response_model=WorkerUdfCodesResponse)
def udf_codes(payload: WorkerUdfCodesRequest, _: None = Depends(_require_internal_token)) -> WorkerUdfCodesResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        ids = [udf_id for udf_id in payload.udf_ids if udf_id]
        if not ids:
            return WorkerUdfCodesResponse(codes={})
        stmt = select(Udf).where(Udf.id.in_(ids))  # type: ignore[attr-defined]
        codes = {udf.id: udf.code for udf in session.execute(stmt).scalars().all()}
        return WorkerUdfCodesResponse(codes=codes)
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/analysis-metadata', response_model=WorkerAnalysisMetadataResponse)
def analysis_metadata(
    payload: WorkerAnalysisMetadataRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerAnalysisMetadataResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        analysis = session.get(Analysis, payload.analysis_id)
        if analysis is None:
            return WorkerAnalysisMetadataResponse(found=False)
        return WorkerAnalysisMetadataResponse(found=True, name=analysis.name)
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/build-cancel-status', response_model=WorkerBuildCancelStatusResponse)
def build_cancel_status(
    payload: WorkerBuildCancelStatusRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerBuildCancelStatusResponse:
    token = set_namespace_context(payload.namespace)
    try:
        run = run_db(build_run_service.get_build_run, payload.build_id)
        if run is None or run.status != BuildRunStatus.CANCELLED:
            return WorkerBuildCancelStatusResponse(cancelled=False)
        cancelled_at = run.cancelled_at.isoformat() if isinstance(run.cancelled_at, datetime) else None
        cancelled_by = run.cancelled_by if isinstance(run.cancelled_by, str) else None
        return WorkerBuildCancelStatusResponse(cancelled=True, cancelled_at=cancelled_at, cancelled_by=cancelled_by)
    finally:
        reset_namespace(token)


@router.post('/update-build-result', response_model=RuntimeWorkerResponse)
def update_build_result(
    payload: WorkerUpdateBuildResultRequest,
    _: None = Depends(_require_internal_token),
) -> RuntimeWorkerResponse:
    token = set_namespace_context(payload.namespace)
    try:
        run_db(build_run_service.update_build_result_json, payload.build_id, payload.result_json)
        return RuntimeWorkerResponse(worker_id=payload.build_id)
    finally:
        reset_namespace(token)


@router.post('/upsert-output-datasource', response_model=WorkerUpsertOutputDatasourceResponse)
def upsert_output_datasource(
    payload: WorkerUpsertOutputDatasourceRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerUpsertOutputDatasourceResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        existing = session.get(DataSource, payload.result_id)
        if existing is not None:
            existing.name = payload.name
            existing.source_type = payload.source_type
            existing.config = payload.config
            if not payload.keep_schema_cache:
                existing.schema_cache = payload.schema_cache
            existing.created_by_analysis_id = payload.analysis_id
            existing.created_by = DataSourceCreatedBy.ANALYSIS.value
            if payload.is_hidden is not None:
                existing.is_hidden = payload.is_hidden
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return WorkerUpsertOutputDatasourceResponse(
                datasource_id=existing.id,
                datasource_name=existing.name,
                is_hidden=existing.is_hidden,
            )
        datasource = DataSource(
            id=payload.result_id,
            name=payload.name,
            source_type=payload.source_type,
            config=payload.config,
            schema_cache=payload.schema_cache,
            created_by_analysis_id=payload.analysis_id,
            created_by=DataSourceCreatedBy.ANALYSIS.value,
            is_hidden=payload.is_hidden if payload.is_hidden is not None else True,
            created_at=datetime.now(UTC),
        )
        session.add(datasource)
        session.commit()
        session.refresh(datasource)
        return WorkerUpsertOutputDatasourceResponse(
            datasource_id=datasource.id,
            datasource_name=datasource.name,
            is_hidden=datasource.is_hidden,
        )
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/list-healthchecks', response_model=WorkerListHealthChecksResponse)
def list_healthchecks(
    payload: WorkerListHealthChecksRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerListHealthChecksResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        stmt = select(HealthCheck).where(HealthCheck.datasource_id == payload.datasource_id)  # type: ignore[arg-type]
        checks = [check for check in session.execute(stmt).scalars().all() if check.enabled]
        return WorkerListHealthChecksResponse(
            checks=[
                WorkerHealthCheckSpec(
                    id=check.id,
                    name=check.name,
                    check_type=check.check_type,
                    config=dict(check.config),
                    critical=check.critical,
                )
                for check in checks
            ]
        )
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/record-healthcheck-results', response_model=WorkerRecordHealthCheckResultsResponse)
def record_healthcheck_results(
    payload: WorkerRecordHealthCheckResultsRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerRecordHealthCheckResultsResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        for result in payload.results:
            session.add(
                HealthCheckResult(
                    id=str(uuid.uuid4()),
                    healthcheck_id=result.healthcheck_id,
                    passed=result.passed,
                    message=result.message,
                    details=result.details,
                    checked_at=datetime.fromisoformat(result.checked_at),
                )
            )
        session.commit()
        return WorkerRecordHealthCheckResultsResponse(recorded=len(payload.results))
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/create-engine-run', response_model=WorkerEngineRunResponse)
def create_engine_run(
    payload: WorkerCreateEngineRunRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerEngineRunResponse:
    token = set_namespace_context(payload.namespace)
    try:
        run = run_db(
            engine_run_service.create_engine_run,
            engine_run_service.create_engine_run_payload(
                analysis_id=payload.analysis_id,
                datasource_id=payload.datasource_id,
                kind=payload.kind,
                status=payload.status,
                request_json=payload.request_json,
                result_json=payload.result_json,
                error_message=payload.error_message,
                created_at=_parse_optional_datetime(payload.created_at),
                completed_at=_parse_optional_datetime(payload.completed_at),
                duration_ms=payload.duration_ms,
                step_timings=payload.step_timings,
                query_plan=payload.query_plan,
                execution_entries=payload.execution_entries,
                progress=payload.progress,
                current_step=payload.current_step,
                triggered_by=payload.triggered_by,
            ),
        )
        return WorkerEngineRunResponse(id=run.id)
    finally:
        reset_namespace(token)


@router.post('/update-engine-run', response_model=WorkerEngineRunResponse)
def update_engine_run(
    payload: WorkerUpdateEngineRunRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerEngineRunResponse:
    fields = dict(payload.fields)
    kwargs: dict[str, Any] = {'merge_result_json': payload.merge_result_json}
    for key in (
        'analysis_id',
        'datasource_id',
        'kind',
        'status',
        'request_json',
        'result_json',
        'error_message',
        'duration_ms',
        'step_timings',
        'query_plan',
        'execution_entries',
        'progress',
        'current_step',
        'triggered_by',
    ):
        if key in fields:
            kwargs[key] = fields[key]
    for key in ('completed_at',):
        if key in fields:
            value = fields[key]
            kwargs[key] = datetime.fromisoformat(value) if isinstance(value, str) else None
    token = set_namespace_context(payload.namespace)
    try:
        run = run_db(lambda session: engine_run_service.update_engine_run(session, payload.run_id, **kwargs))
        return WorkerEngineRunResponse(id=run.id)
    finally:
        reset_namespace(token)


@router.post('/engine-run-state', response_model=WorkerEngineRunStateResponse)
def engine_run_state(
    payload: WorkerEngineRunStateRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerEngineRunStateResponse:
    token = set_namespace_context(payload.namespace)
    try:
        run = run_db(engine_run_service.get_engine_run, payload.run_id)
        if run is None:
            return WorkerEngineRunStateResponse(found=False)
        result_json = dict(run.result_json) if isinstance(run.result_json, dict) else {}
        cancelled_at = result_json.get('cancelled_at')
        cancelled_by = result_json.get('cancelled_by')
        return WorkerEngineRunStateResponse(
            found=True,
            status=run.status,
            result_json=result_json,
            cancelled_at=cancelled_at if isinstance(cancelled_at, str) else None,
            cancelled_by=cancelled_by if isinstance(cancelled_by, str) else None,
        )
    finally:
        reset_namespace(token)


@router.post('/fail-build-job', response_model=RuntimeWorkerResponse)
def fail_build_job(payload: WorkerFailBuildJobRequest, _: None = Depends(_require_internal_token)) -> RuntimeWorkerResponse:
    token = set_namespace_context(payload.namespace)
    try:
        run_db(lambda session: build_job_service.mark_job_failed(session, payload.job_id, error=payload.error))
    finally:
        reset_namespace(token)
    return RuntimeWorkerResponse(worker_id=payload.job_id)


@router.post('/finalize-build-job', response_model=RuntimeWorkerResponse)
def finalize_build_job(payload: WorkerFinalizeBuildJobRequest, _: None = Depends(_require_internal_token)) -> RuntimeWorkerResponse:
    def _finalize(session):
        run = build_run_service.get_build_run(session, payload.build_id)
        if run is None:
            return build_job_service.mark_job_failed(session, payload.job_id, error='Build run missing')
        if run.status == BuildRunStatus.CANCELLED:
            result = build_job_service.mark_job_cancelled(session, payload.job_id)
        elif run.status == BuildRunStatus.COMPLETED:
            result = build_job_service.mark_job_completed(session, payload.job_id)
        elif run.status in {BuildRunStatus.FAILED, BuildRunStatus.ORPHANED}:
            result = build_job_service.mark_job_failed(session, payload.job_id, error=run.error_message)
        else:
            result = build_job_service.mark_job_failed(session, payload.job_id, error=f'Unexpected build status: {run.status.value}')
        scheduler_service.reconcile_schedule_run(session, build_id=payload.build_id)
        return result

    token = set_namespace_context(payload.namespace)
    try:
        run_db(_finalize)
    finally:
        reset_namespace(token)
    return RuntimeWorkerResponse(worker_id=payload.job_id)


@router.post('/release-build-worker-jobs', response_model=WorkerReleaseJobsResponse)
def release_build_worker_jobs(payload: RuntimeWorkerRequest, _: None = Depends(_require_internal_token)) -> WorkerReleaseJobsResponse:
    released = 0
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            released += len(run_db(build_job_service.release_worker_jobs, worker_id=payload.worker_id))
        finally:
            reset_namespace(token)
    return WorkerReleaseJobsResponse(released=released)


@router.post('/queued-build-job-count', response_model=WorkerQueueCountResponse)
def queued_build_job_count(_: None = Depends(_require_internal_token)) -> WorkerQueueCountResponse:
    count = 0
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            count += run_db(build_job_service.queued_job_count)
        finally:
            reset_namespace(token)
    return WorkerQueueCountResponse(queued=count)


@router.post('/dispatch-runtime-outbox', response_model=WorkerDispatchOutboxResponse)
def dispatch_runtime_outbox(_: None = Depends(_require_internal_token)) -> WorkerDispatchOutboxResponse:
    dispatched = 0
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            dispatched += run_db(runtime_outbox_service.dispatch_pending_events)
        finally:
            reset_namespace(token)
    return WorkerDispatchOutboxResponse(dispatched=dispatched)


@router.post('/idle-build-worker-pids', response_model=WorkerIdlePidsResponse)
def idle_build_worker_pids(_: None = Depends(_require_internal_token)) -> WorkerIdlePidsResponse:
    workers = run_settings_db(runtime_worker_service.list_workers, kind=RuntimeWorkerKind.BUILD_WORKER)
    pids = [worker.pid for worker in workers if worker.stopped_at is None and worker.active_jobs == 0]
    return WorkerIdlePidsResponse(pids=pids)


@router.post('/runtime-namespaces', response_model=WorkerNamespacesResponse)
def runtime_namespaces(_: None = Depends(_require_internal_token)) -> WorkerNamespacesResponse:
    return WorkerNamespacesResponse(namespaces=run_settings_db(list_runtime_namespaces))


@router.post('/persist-build-event', response_model=WorkerPersistBuildEventResponse)
async def persist_build_event(payload: WorkerPersistBuildEventRequest, _: None = Depends(_require_internal_token)) -> WorkerPersistBuildEventResponse:
    event = compute_schemas.BuildEventAdapter.validate_python(payload.event)
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        result: tuple[object, int] | None = await build_event_service.persist_build_event(
            session,
            namespace=payload.namespace,
            build_id=payload.build_id,
            event=event,
            resource_config_json=payload.resource_config_json,
        )
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)
    if result is None:
        return WorkerPersistBuildEventResponse(sequence=None)
    sequence = int(result[1])
    return WorkerPersistBuildEventResponse(sequence=sequence)


@router.post('/start-build-run', response_model=WorkerStartBuildRunResponse)
async def start_build_run(payload: WorkerStartBuildRunRequest, _: None = Depends(_require_internal_token)) -> WorkerStartBuildRunResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        run = build_run_service.mark_build_running(session, payload.build_id)
        if run is None or run.status != BuildRunStatus.RUNNING:
            return WorkerStartBuildRunResponse(run=None)
        await build_event_service.publish_build_notification(run.namespace, run.id, latest_sequence=0)
        return WorkerStartBuildRunResponse(
            run=WorkerBuildRunPayload(
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
                started_at=run.started_at.isoformat(),
                total_tabs=run.total_tabs,
            )
        )
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/persist-engine-snapshot', response_model=WorkerPersistEngineSnapshotResponse)
def persist_engine_snapshot(payload: WorkerPersistEngineSnapshotRequest, _: None = Depends(_require_internal_token)) -> WorkerPersistEngineSnapshotResponse:
    statuses = [EngineStatusInfo(**cast(dict[str, Any], status)) for status in payload.statuses]

    def _write(session) -> None:
        engine_instance_service.persist_engine_snapshot(
            session,
            worker_id=payload.worker_id,
            namespace=payload.namespace,
            statuses=statuses,
        )

    run_settings_db(_write)
    runtime_ipc.notify_api_engine(payload.namespace)
    return WorkerPersistEngineSnapshotResponse(persisted=len(statuses))


@router.post('/pending-datasource-deletes', response_model=WorkerPendingDatasourceDeletesResponse)
def pending_datasource_deletes(_: None = Depends(_require_internal_token)) -> WorkerPendingDatasourceDeletesResponse:
    deletes: list[WorkerPendingDatasourceDelete] = []
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            datasource_ids = run_db(lambda session: [datasource.id for datasource in datasource_delete_service.list_pending_deletes(session)])
        finally:
            reset_namespace(token)
        deletes.extend(WorkerPendingDatasourceDelete(namespace=namespace, datasource_id=datasource_id) for datasource_id in datasource_ids)
    return WorkerPendingDatasourceDeletesResponse(deletes=deletes)


@router.post('/finalize-datasource-delete', response_model=WorkerFinalizeDatasourceDeleteResponse)
def finalize_datasource_delete(
    payload: WorkerFinalizeDatasourceDeleteRequest,
    _: None = Depends(_require_internal_token),
) -> WorkerFinalizeDatasourceDeleteResponse:
    token = set_namespace_context(payload.namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        datasource = datasource_delete_service.get_datasource(session, payload.datasource_id)
        if datasource is None:
            return WorkerFinalizeDatasourceDeleteResponse(deleted=False)
        cleanup_datasource_storage(datasource)
        session.delete(datasource)
        session.commit()
        return WorkerFinalizeDatasourceDeleteResponse(deleted=True)
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


@router.post('/telegram-settings', response_model=WorkerTelegramSettingsResponse)
def telegram_settings(_: None = Depends(_require_internal_token)) -> WorkerTelegramSettingsResponse:
    resolved = get_resolved_telegram_settings()
    return WorkerTelegramSettingsResponse(enabled=bool(resolved.get('enabled')))


@router.post('/send-email', response_model=WorkerNotificationResponse)
def send_email(payload: WorkerSendEmailRequest, _: None = Depends(_require_internal_token)) -> WorkerNotificationResponse:
    if not payload.to:
        return WorkerNotificationResponse(sent=False)
    smtp = get_resolved_smtp()
    host = str(smtp.get('host', ''))
    port = int(str(smtp.get('port', 587)))
    user = str(smtp.get('user', ''))
    password = str(smtp.get('password', ''))
    if not host:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='SMTP not configured (host missing)')
    if not user:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='SMTP not configured (user missing)')

    message = EmailMessage()
    message['From'] = user
    message['To'] = payload.to
    message['Subject'] = payload.subject
    message.set_content(payload.body)
    message.add_alternative(payload.body, subtype='html')
    for attachment in payload.attachments:
        parts = attachment.content_type.partition('/')
        maintype: str = parts[0]
        subtype: str = parts[2]
        if not maintype or not subtype:
            maintype = 'text'
            subtype = 'plain'
        message.add_attachment(
            base64.b64decode(attachment.content_base64),
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
    send_smtp_message(host, port, user, password, message)
    return WorkerNotificationResponse(sent=True)


@router.post('/send-telegram', response_model=WorkerNotificationResponse)
def send_telegram(payload: WorkerSendTelegramRequest, _: None = Depends(_require_internal_token)) -> WorkerNotificationResponse:
    resolved = get_resolved_telegram_settings()
    if not resolved['enabled']:
        return WorkerNotificationResponse(sent=False)
    token = payload.bot_token or str(resolved['token']) or get_resolved_telegram_token()
    if not token:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Telegram bot token not configured')
    base = f'{_TELEGRAM_BASE_URL}/bot{token}'
    response = http_client.post(
        f'{base}/sendMessage',
        json={'chat_id': payload.chat_id, 'text': payload.message, 'parse_mode': 'HTML'},
        timeout=20,
    )
    response.raise_for_status()
    for attachment in payload.attachments:
        file_response = http_client.post(
            f'{base}/sendDocument',
            data={'chat_id': payload.chat_id},
            files={
                'document': (
                    attachment.filename,
                    base64.b64decode(attachment.content_base64),
                    attachment.content_type,
                )
            },
            timeout=30,
        )
        file_response.raise_for_status()
    return WorkerNotificationResponse(sent=True)


@router.post('/generate-ai', response_model=WorkerGenerateAIResponse)
def generate_ai(payload: WorkerGenerateAIRequest, _: None = Depends(_require_internal_token)) -> WorkerGenerateAIResponse:
    client = get_ai_client(
        AIProvider(payload.provider),
        endpoint_url=payload.endpoint_url,
        api_key=payload.api_key,
    )
    outputs = client.generate_batch(payload.prompts, model=payload.model, options=payload.options)
    return WorkerGenerateAIResponse(outputs=outputs)


@router.post('/telegram-targets', response_model=WorkerTelegramTargetsResponse)
def telegram_targets(payload: WorkerTelegramTargetsRequest, _: None = Depends(_require_internal_token)) -> WorkerTelegramTargetsResponse:
    def _list_targets(session):
        if payload.active_subscribers:
            rows = (
                session.execute(
                    select(TelegramSubscriber).where(TelegramSubscriber.is_active == True)  # type: ignore[arg-type]  # noqa: E712
                )
                .scalars()
                .all()
            )
            return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]
        if not payload.datasource_id:
            return []
        listeners = (
            session.execute(
                select(TelegramListener).where(TelegramListener.datasource_id == payload.datasource_id),  # type: ignore[arg-type]
            )
            .scalars()
            .all()
        )
        subscriber_ids = {listener.subscriber_id for listener in listeners}
        if not subscriber_ids:
            return []
        rows = (
            session.execute(
                select(TelegramSubscriber)
                .where(TelegramSubscriber.id.in_(subscriber_ids))  # type: ignore[union-attr]
                .where(TelegramSubscriber.is_active == True),  # type: ignore[arg-type]  # noqa: E712
            )
            .scalars()
            .all()
        )
        return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]

    token = set_namespace_context(payload.namespace)
    try:
        targets = run_db(_list_targets)
    finally:
        reset_namespace(token)
    return WorkerTelegramTargetsResponse(targets=[WorkerTelegramTarget(chat_id=chat_id, bot_token=bot_token) for chat_id, bot_token in targets])
