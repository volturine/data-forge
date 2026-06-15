from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any, cast

import grpc
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
from backend_core.exceptions import DataSourceNotFoundError
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.namespaces_service import list_runtime_namespaces
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult
from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
from backend_core.persistence.udfs.models import Udf
from backend_core.settings_projection import get_resolved_smtp, get_resolved_telegram_settings, get_resolved_telegram_token
from backend_core.smtp import send_smtp_message
from backend_grpc.codec import dict_to_struct, repeated_structs_to_dicts, struct_field_to_dict, struct_to_dict
from dataforge_protocol import common_pb2, scheduler_runtime_pb2, scheduler_runtime_pb2_grpc, worker_runtime_pb2, worker_runtime_pb2_grpc
from modules.datasource import runtime_service as datasource_runtime_service
from modules.scheduler import service as scheduler_service

logger = logging.getLogger(__name__)
_TELEGRAM_BASE_URL = 'https://api.telegram.org'
_TOKEN_METADATA_KEY = 'x-internal-token'


async def _require_internal_token(context: grpc.aio.ServicerContext) -> None:
    if not settings.internal_api_token:
        await context.abort(grpc.StatusCode.UNAVAILABLE, 'INTERNAL_API_TOKEN must be configured before internal runtime services can be used')
    metadata = dict(cast(Any, context.invocation_metadata() or ()))
    if metadata.get(_TOKEN_METADATA_KEY) != settings.internal_api_token:
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid internal runtime token')


def _run_async_handler_in_thread(func):
    async def wrapper(self, request, context):
        await _require_internal_token(context)

        def _run():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(func(self, request, context))
            finally:
                loop.close()

        return await asyncio.to_thread(_run)

    return wrapper


def _parse_worker_kind(value: str) -> RuntimeWorkerKind:
    try:
        return RuntimeWorkerKind(value)
    except ValueError as exc:
        raise ValueError(f'Unsupported runtime worker kind: {value}') from exc


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


def _optional_str(message: Any, field: str) -> str | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_bool(message: Any, field: str) -> bool | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_int(message: Any, field: str) -> int | None:
    return getattr(message, field) if message.HasField(field) else None


def _response(worker_id: str) -> common_pb2.RuntimeWorkerResponse:
    return common_pb2.RuntimeWorkerResponse(worker_id=worker_id)


def _count(value: int) -> worker_runtime_pb2.CountResponse:
    return worker_runtime_pb2.CountResponse(count=value)


def _bool(value: bool) -> worker_runtime_pb2.BoolResponse:
    return worker_runtime_pb2.BoolResponse(value=value)


def _id(value: str) -> worker_runtime_pb2.IdResponse:
    return worker_runtime_pb2.IdResponse(id=value)


class WorkerRuntimeServicer(worker_runtime_pb2_grpc.WorkerRuntimeServiceServicer):
    @_run_async_handler_in_thread
    async def RegisterWorker(
        self, request: worker_runtime_pb2.RuntimeWorkerRegisterRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:

        def _register(session: Any) -> None:
            runtime_worker_service.register_worker(
                session,
                worker_id=request.worker_id,
                kind=_parse_worker_kind(request.kind),
                hostname=request.hostname,
                pid=request.pid,
                capacity=request.capacity,
                active_jobs=request.active_jobs,
            )

        run_settings_db(_register)
        return _response(request.worker_id)

    @_run_async_handler_in_thread
    async def HeartbeatWorker(
        self, request: worker_runtime_pb2.RuntimeWorkerHeartbeatRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        active_jobs = _optional_int(request, 'active_jobs')

        def _heartbeat(session: Any) -> None:
            runtime_worker_service.heartbeat_worker(session, worker_id=request.worker_id, active_jobs=active_jobs)

        run_settings_db(_heartbeat)
        return _response(request.worker_id)

    @_run_async_handler_in_thread
    async def StopWorker(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> common_pb2.RuntimeWorkerResponse:
        await _require_internal_token(context)

        def _stop(session: Any) -> None:
            runtime_worker_service.mark_worker_stopped(session, worker_id=request.worker_id)

        run_settings_db(_stop)
        return _response(request.worker_id)

    @_run_async_handler_in_thread
    async def ClaimBuildJob(
        self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerClaimBuildJobResponse:
        reclaimable_owner_ids = run_settings_db(runtime_worker_service.reclaimable_worker_ids, kind=RuntimeWorkerKind.BUILD_WORKER)
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                job = run_db(build_job_service.claim_next_job, worker_id=request.worker_id, reclaimable_owner_ids=reclaimable_owner_ids)
            finally:
                reset_namespace(token)
            if job is not None:
                return worker_runtime_pb2.WorkerClaimBuildJobResponse(
                    job=worker_runtime_pb2.WorkerClaimedBuildJob(job_id=job.id, build_id=job.build_id, namespace=job.namespace)
                )
        return worker_runtime_pb2.WorkerClaimBuildJobResponse()

    @_run_async_handler_in_thread
    async def ClaimComputeRequest(
        self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerClaimComputeRequestResponse:
        reclaimable_owner_ids = run_settings_db(runtime_worker_service.reclaimable_worker_ids, kind=RuntimeWorkerKind.BUILD_MANAGER)
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                compute_request = run_db(
                    compute_requests_service.claim_next_request,
                    worker_id=request.worker_id,
                    reclaimable_owner_ids=reclaimable_owner_ids,
                )
                if compute_request is None:
                    continue
                return worker_runtime_pb2.WorkerClaimComputeRequestResponse(
                    request=worker_runtime_pb2.WorkerClaimedComputeRequest(
                        id=compute_request.id,
                        namespace=compute_request.namespace,
                        kind=compute_request.kind.value,
                        request_json=dict_to_struct(compute_requests_service.command_payload(compute_request)),
                    )
                )
            finally:
                reset_namespace(token)
        return worker_runtime_pb2.WorkerClaimComputeRequestResponse()

    @_run_async_handler_in_thread
    async def CompleteComputeRequest(
        self, request: worker_runtime_pb2.WorkerCompleteComputeRequestRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        try:
            run_db(
                compute_requests_service.mark_request_completed,
                request.request_id,
                response_json=struct_field_to_dict(request, 'response_json'),
                artifact_path=_optional_str(request, 'artifact_path'),
                artifact_name=_optional_str(request, 'artifact_name'),
                artifact_content_type=_optional_str(request, 'artifact_content_type'),
            )
            return _response(request.request_id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def FailComputeRequest(
        self, request: worker_runtime_pb2.WorkerFailComputeRequestRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        try:
            run_db(
                compute_requests_service.mark_request_failed,
                request.request_id,
                error_message=request.error_message,
                response_json=struct_to_dict(request.response_json),
            )
            return _response(request.request_id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def ReleaseComputeRequests(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        released = 0
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                released += len(run_db(compute_requests_service.release_worker_requests, worker_id=request.worker_id))
            finally:
                reset_namespace(token)
        return _count(released)

    @_run_async_handler_in_thread
    async def ExecuteDatasourceRequest(
        self, request: worker_runtime_pb2.WorkerExecuteDatasourceRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.JsonResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            kind = ComputeRequestKind(request.kind)
            request_json = struct_to_dict(request.request_json)
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
            return worker_runtime_pb2.JsonResponse(response_json=dict_to_struct(response.model_dump(mode='json')))
        except DataSourceNotFoundError as exc:
            logger.warning('Datasource not found for %s: %s', kind.value, exc)
            return worker_runtime_pb2.JsonResponse(response_json=dict_to_struct({'error': 'datasource_not_found', 'message': str(exc)}))
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def ScheduleIngestDatasource(
        self, request: worker_runtime_pb2.WorkerScheduleIngestDatasourceRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.JsonResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            response = datasource_runtime_service.ingest_datasource_for_schedule(session, request.datasource_id)
            return worker_runtime_pb2.JsonResponse(response_json=dict_to_struct(response.model_dump(mode='json')))
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetDatasourceMetadata(
        self, request: worker_runtime_pb2.WorkerDatasourceMetadataRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerDatasourceMetadataResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            datasource = session.get(DataSource, request.datasource_id)
            if datasource is None:
                return worker_runtime_pb2.WorkerDatasourceMetadataResponse(found=False)
            response = worker_runtime_pb2.WorkerDatasourceMetadataResponse(
                found=True,
                id=datasource.id,
                name=datasource.name,
                source_type=datasource.source_type,
                config=dict_to_struct(dict(datasource.config)),
                is_hidden=datasource.is_hidden,
            )
            if isinstance(datasource.schema_cache, dict):
                response.schema_cache.CopyFrom(dict_to_struct(dict(datasource.schema_cache)))
            return response
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetUdfCodes(
        self, request: worker_runtime_pb2.WorkerUdfCodesRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerUdfCodesResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            ids = [udf_id for udf_id in request.udf_ids if udf_id]
            if not ids:
                return worker_runtime_pb2.WorkerUdfCodesResponse()
            stmt = select(Udf).where(Udf.id.in_(ids))  # type: ignore[attr-defined]
            codes = {udf.id: udf.code for udf in session.execute(stmt).scalars().all()}
            return worker_runtime_pb2.WorkerUdfCodesResponse(codes=codes)
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetAnalysisMetadata(
        self, request: worker_runtime_pb2.WorkerAnalysisMetadataRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerAnalysisMetadataResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            analysis = session.get(Analysis, request.analysis_id)
            if analysis is None:
                return worker_runtime_pb2.WorkerAnalysisMetadataResponse(found=False)
            return worker_runtime_pb2.WorkerAnalysisMetadataResponse(found=True, name=analysis.name)
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetBuildCancelStatus(
        self, request: worker_runtime_pb2.WorkerBuildCancelStatusRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerBuildCancelStatusResponse:
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(build_run_service.get_build_run, request.build_id)
            if run is None or run.status != BuildRunStatus.CANCELLED:
                return worker_runtime_pb2.WorkerBuildCancelStatusResponse(cancelled=False)
            cancelled_at = run.cancelled_at.isoformat() if isinstance(run.cancelled_at, datetime) else None
            cancelled_by = run.cancelled_by if isinstance(run.cancelled_by, str) else None
            return worker_runtime_pb2.WorkerBuildCancelStatusResponse(cancelled=True, cancelled_at=cancelled_at, cancelled_by=cancelled_by)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def UpdateBuildResult(
        self, request: worker_runtime_pb2.WorkerUpdateBuildResultRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        try:
            run_db(build_run_service.update_build_result_json, request.build_id, struct_to_dict(request.result_json))
            return _response(request.build_id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def UpsertOutputDatasource(
        self, request: worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerUpsertOutputDatasourceResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            config = struct_to_dict(request.config)
            schema_cache = struct_to_dict(request.schema_cache)
            existing = session.get(DataSource, request.result_id)
            if existing is not None:
                existing.name = request.name
                existing.source_type = request.source_type
                existing.config = config
                if not request.keep_schema_cache:
                    existing.schema_cache = schema_cache
                existing.created_by_analysis_id = _optional_str(request, 'analysis_id')
                existing.created_by = DataSourceCreatedBy.ANALYSIS.value
                if request.HasField('is_hidden'):
                    existing.is_hidden = request.is_hidden
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return worker_runtime_pb2.WorkerUpsertOutputDatasourceResponse(
                    datasource_id=existing.id,
                    datasource_name=existing.name,
                    is_hidden=existing.is_hidden,
                )
            datasource = DataSource(
                id=request.result_id,
                name=request.name,
                source_type=request.source_type,
                config=config,
                schema_cache=schema_cache,
                created_by_analysis_id=_optional_str(request, 'analysis_id'),
                created_by=DataSourceCreatedBy.ANALYSIS.value,
                is_hidden=request.is_hidden if request.HasField('is_hidden') else True,
                created_at=datetime.now(UTC),
            )
            session.add(datasource)
            session.commit()
            session.refresh(datasource)
            return worker_runtime_pb2.WorkerUpsertOutputDatasourceResponse(
                datasource_id=datasource.id,
                datasource_name=datasource.name,
                is_hidden=datasource.is_hidden,
            )
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def ListHealthChecks(
        self, request: worker_runtime_pb2.WorkerListHealthChecksRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerListHealthChecksResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            stmt = select(HealthCheck).where(HealthCheck.datasource_id == request.datasource_id)  # type: ignore[arg-type]
            checks = [check for check in session.execute(stmt).scalars().all() if check.enabled]
            return worker_runtime_pb2.WorkerListHealthChecksResponse(
                checks=[
                    worker_runtime_pb2.WorkerHealthCheckSpec(
                        id=check.id,
                        name=check.name,
                        check_type=check.check_type,
                        config=dict_to_struct(dict(check.config)),
                        critical=check.critical,
                    )
                    for check in checks
                ]
            )
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def RecordHealthCheckResults(
        self, request: worker_runtime_pb2.WorkerRecordHealthCheckResultsRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.CountResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            for result in request.results:
                session.add(
                    HealthCheckResult(
                        id=str(uuid.uuid4()),
                        healthcheck_id=result.healthcheck_id,
                        passed=result.passed,
                        message=result.message,
                        details=struct_to_dict(result.details),
                        checked_at=datetime.fromisoformat(result.checked_at),
                    )
                )
            session.commit()
            return _count(len(request.results))
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def CreateEngineRun(
        self, request: worker_runtime_pb2.WorkerCreateEngineRunRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.IdResponse:
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(
                engine_run_service.create_engine_run,
                engine_run_service.create_engine_run_payload(
                    analysis_id=_optional_str(request, 'analysis_id'),
                    datasource_id=request.datasource_id,
                    kind=request.kind,
                    status=request.status,
                    request_json=struct_to_dict(request.request_json),
                    result_json=struct_field_to_dict(request, 'result_json'),
                    error_message=_optional_str(request, 'error_message'),
                    created_at=_parse_optional_datetime(_optional_str(request, 'created_at')),
                    completed_at=_parse_optional_datetime(_optional_str(request, 'completed_at')),
                    duration_ms=_optional_int(request, 'duration_ms'),
                    step_timings=cast(dict[str, float] | None, struct_field_to_dict(request, 'step_timings')),
                    query_plan=_optional_str(request, 'query_plan'),
                    execution_entries=repeated_structs_to_dicts(request.execution_entries) or None,
                    progress=request.progress,
                    current_step=_optional_str(request, 'current_step'),
                    triggered_by=_optional_str(request, 'triggered_by'),
                ),
            )
            return _id(run.id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def UpdateEngineRun(
        self, request: worker_runtime_pb2.WorkerUpdateEngineRunRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.IdResponse:
        fields = struct_to_dict(request.fields)
        kwargs: dict[str, Any] = {'merge_result_json': request.merge_result_json}
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
        if 'completed_at' in fields:
            value = fields['completed_at']
            kwargs['completed_at'] = datetime.fromisoformat(value) if isinstance(value, str) else None
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(lambda session: engine_run_service.update_engine_run(session, request.run_id, **kwargs))
            return _id(run.id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetEngineRunState(
        self, request: worker_runtime_pb2.WorkerEngineRunStateRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerEngineRunStateResponse:
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(engine_run_service.get_engine_run, request.run_id)
            if run is None:
                return worker_runtime_pb2.WorkerEngineRunStateResponse(found=False)
            result_json = dict(run.result_json) if isinstance(run.result_json, dict) else {}
            cancelled_at = result_json.get('cancelled_at')
            cancelled_by = result_json.get('cancelled_by')
            return worker_runtime_pb2.WorkerEngineRunStateResponse(
                found=True,
                status=run.status,
                result_json=dict_to_struct(result_json),
                cancelled_at=cancelled_at if isinstance(cancelled_at, str) else None,
                cancelled_by=cancelled_by if isinstance(cancelled_by, str) else None,
            )
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def FailBuildJob(self, request: worker_runtime_pb2.WorkerFailBuildJobRequest, context: grpc.aio.ServicerContext) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        try:
            run_db(lambda session: build_job_service.mark_job_failed(session, request.job_id, error=request.error))
        finally:
            reset_namespace(token)
        return _response(request.job_id)

    @_run_async_handler_in_thread
    async def FinalizeBuildJob(
        self, request: worker_runtime_pb2.WorkerFinalizeBuildJobRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:

        def _finalize(session: Any) -> Any:
            run = build_run_service.get_build_run(session, request.build_id)
            if run is None:
                return build_job_service.mark_job_failed(session, request.job_id, error='Build run missing')
            if run.status == BuildRunStatus.CANCELLED:
                result = build_job_service.mark_job_cancelled(session, request.job_id)
            elif run.status == BuildRunStatus.COMPLETED:
                result = build_job_service.mark_job_completed(session, request.job_id)
            elif run.status in {BuildRunStatus.FAILED, BuildRunStatus.ORPHANED}:
                result = build_job_service.mark_job_failed(session, request.job_id, error=run.error_message)
            else:
                result = build_job_service.mark_job_failed(session, request.job_id, error=f'Unexpected build status: {run.status.value}')
            scheduler_service.reconcile_schedule_run(session, build_id=request.build_id)
            return result

        token = set_namespace_context(request.namespace)
        try:
            run_db(_finalize)
        finally:
            reset_namespace(token)
        return _response(request.job_id)

    @_run_async_handler_in_thread
    async def ReleaseBuildWorkerJobs(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        released = 0
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                released += len(run_db(build_job_service.release_worker_jobs, worker_id=request.worker_id))
            finally:
                reset_namespace(token)
        return _count(released)

    @_run_async_handler_in_thread
    async def GetQueuedBuildJobCount(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        count = 0
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                count += run_db(build_job_service.queued_job_count)
            finally:
                reset_namespace(token)
        return _count(count)

    @_run_async_handler_in_thread
    async def DispatchRuntimeOutbox(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        dispatched = 0
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                dispatched += run_db(runtime_outbox_service.dispatch_pending_events)
            finally:
                reset_namespace(token)
        return _count(dispatched)

    @_run_async_handler_in_thread
    async def GetIdleBuildWorkerPids(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.WorkerIdlePidsResponse:
        workers = run_settings_db(runtime_worker_service.list_workers, kind=RuntimeWorkerKind.BUILD_WORKER)
        return worker_runtime_pb2.WorkerIdlePidsResponse(pids=[worker.pid for worker in workers if worker.stopped_at is None and worker.active_jobs == 0])

    @_run_async_handler_in_thread
    async def ListRuntimeNamespaces(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.WorkerNamespacesResponse:
        return worker_runtime_pb2.WorkerNamespacesResponse(namespaces=run_settings_db(list_runtime_namespaces))

    @_run_async_handler_in_thread
    async def PersistBuildEvent(
        self, request: worker_runtime_pb2.WorkerPersistBuildEventRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerPersistBuildEventResponse:
        event = compute_schemas.BuildEventAdapter.validate_python(struct_to_dict(request.event))
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            result: tuple[object, int] | None = await build_event_service.persist_build_event(
                session,
                namespace=request.namespace,
                build_id=request.build_id,
                event=event,
                resource_config_json=struct_field_to_dict(request, 'resource_config_json'),
            )
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)
        if result is None:
            return worker_runtime_pb2.WorkerPersistBuildEventResponse()
        return worker_runtime_pb2.WorkerPersistBuildEventResponse(sequence=int(result[1]))

    @_run_async_handler_in_thread
    async def StartBuildRun(
        self, request: worker_runtime_pb2.WorkerStartBuildRunRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerStartBuildRunResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            run = build_run_service.mark_build_running(session, request.build_id)
            if run is None or run.status != BuildRunStatus.RUNNING:
                return worker_runtime_pb2.WorkerStartBuildRunResponse()
            await build_event_service.publish_build_notification(run.namespace, run.id, latest_sequence=0)
            payload = worker_runtime_pb2.WorkerBuildRunPayload(
                id=run.id,
                namespace=run.namespace,
                analysis_id=run.analysis_id,
                analysis_name=run.analysis_name,
                request_json=dict_to_struct(dict(run.request_json)),
                starter_json=dict_to_struct(dict(run.starter_json)),
                current_kind=run.current_kind,
                current_datasource_id=run.current_datasource_id,
                current_tab_id=run.current_tab_id,
                current_tab_name=run.current_tab_name,
                current_output_id=run.current_output_id,
                current_output_name=run.current_output_name,
                started_at=run.started_at.isoformat(),
                total_tabs=run.total_tabs,
            )
            if isinstance(run.resource_config_json, dict):
                payload.resource_config_json.CopyFrom(dict_to_struct(dict(run.resource_config_json)))
            return worker_runtime_pb2.WorkerStartBuildRunResponse(run=payload)
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    async def PersistEngineSnapshot(
        self, request: worker_runtime_pb2.WorkerPersistEngineSnapshotRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.CountResponse:
        statuses = [EngineStatusInfo(**cast(dict[str, Any], status)) for status in repeated_structs_to_dicts(request.statuses)]

        def _write(session: Any) -> None:
            engine_instance_service.persist_engine_snapshot(
                session,
                worker_id=request.worker_id,
                namespace=request.namespace,
                statuses=statuses,
            )

        run_settings_db(_write)
        runtime_ipc.notify_api_engine(request.namespace)
        return _count(len(statuses))

    @_run_async_handler_in_thread
    async def ListPendingDatasourceDeletes(
        self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerPendingDatasourceDeletesResponse:
        deletes: list[worker_runtime_pb2.WorkerPendingDatasourceDelete] = []
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                datasource_ids = run_db(lambda session: [datasource.id for datasource in datasource_delete_service.list_pending_deletes(session)])
            finally:
                reset_namespace(token)
            deletes.extend(
                worker_runtime_pb2.WorkerPendingDatasourceDelete(namespace=namespace, datasource_id=datasource_id) for datasource_id in datasource_ids
            )
        return worker_runtime_pb2.WorkerPendingDatasourceDeletesResponse(deletes=deletes)

    @_run_async_handler_in_thread
    async def FinalizeDatasourceDelete(
        self, request: worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerFinalizeDatasourceDeleteResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            datasource = datasource_delete_service.get_datasource(session, request.datasource_id)
            if datasource is None:
                return worker_runtime_pb2.WorkerFinalizeDatasourceDeleteResponse(deleted=False)
            cleanup_datasource_storage(datasource)
            session.delete(datasource)
            session.commit()
            return worker_runtime_pb2.WorkerFinalizeDatasourceDeleteResponse(deleted=True)
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetTelegramSettings(
        self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerTelegramSettingsResponse:
        resolved = get_resolved_telegram_settings()
        return worker_runtime_pb2.WorkerTelegramSettingsResponse(enabled=bool(resolved.get('enabled')))

    @_run_async_handler_in_thread
    async def SendEmail(self, request: worker_runtime_pb2.WorkerSendEmailRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.BoolResponse:
        if not request.to:
            return _bool(False)
        smtp = get_resolved_smtp()
        host = str(smtp.get('host', ''))
        port = int(str(smtp.get('port', 587)))
        user = str(smtp.get('user', ''))
        password = str(smtp.get('password', ''))
        if not host:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'SMTP not configured (host missing)')
        if not user:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'SMTP not configured (user missing)')

        message = EmailMessage()
        message['From'] = user
        message['To'] = request.to
        message['Subject'] = request.subject
        message.set_content(request.body)
        message.add_alternative(request.body, subtype='html')
        for attachment in request.attachments:
            parts = attachment.content_type.partition('/')
            maintype = parts[0]
            subtype = parts[2]
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
        return _bool(True)

    @_run_async_handler_in_thread
    async def SendTelegram(self, request: worker_runtime_pb2.WorkerSendTelegramRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.BoolResponse:
        resolved = get_resolved_telegram_settings()
        if not resolved['enabled']:
            return _bool(False)
        token = _optional_str(request, 'bot_token') or str(resolved['token']) or get_resolved_telegram_token()
        if not token:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Telegram bot token not configured')
        base = f'{_TELEGRAM_BASE_URL}/bot{token}'
        response = http_client.post(
            f'{base}/sendMessage',
            json={'chat_id': request.chat_id, 'text': request.message, 'parse_mode': 'HTML'},
            timeout=20,
        )
        response.raise_for_status()
        for attachment in request.attachments:
            file_response = http_client.post(
                f'{base}/sendDocument',
                data={'chat_id': request.chat_id},
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
        return _bool(True)

    @_run_async_handler_in_thread
    async def GenerateAI(
        self, request: worker_runtime_pb2.WorkerGenerateAIRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerGenerateAIResponse:
        client = get_ai_client(
            AIProvider(request.provider),
            endpoint_url=_optional_str(request, 'endpoint_url'),
            api_key=_optional_str(request, 'api_key'),
        )
        outputs = client.generate_batch(list(request.prompts), model=request.model, options=struct_to_dict(request.options))
        return worker_runtime_pb2.WorkerGenerateAIResponse(outputs=outputs)

    @_run_async_handler_in_thread
    async def GetTelegramTargets(
        self, request: worker_runtime_pb2.WorkerTelegramTargetsRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerTelegramTargetsResponse:
        datasource_id = _optional_str(request, 'datasource_id')

        def _list_targets(session: Any) -> list[tuple[str, str]]:
            if request.active_subscribers:
                rows = (
                    session.execute(
                        select(TelegramSubscriber).where(TelegramSubscriber.is_active == True)  # type: ignore[arg-type]  # noqa: E712
                    )
                    .scalars()
                    .all()
                )
                return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]
            if not datasource_id:
                return []
            listeners = (
                session.execute(
                    select(TelegramListener).where(TelegramListener.datasource_id == datasource_id),  # type: ignore[arg-type]
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

        token = set_namespace_context(request.namespace)
        try:
            targets = run_db(_list_targets)
        finally:
            reset_namespace(token)
        return worker_runtime_pb2.WorkerTelegramTargetsResponse(
            targets=[worker_runtime_pb2.WorkerTelegramTarget(chat_id=chat_id, bot_token=bot_token) for chat_id, bot_token in targets]
        )


class SchedulerRuntimeServicer(scheduler_runtime_pb2_grpc.SchedulerRuntimeServiceServicer):
    @_run_async_handler_in_thread
    async def RegisterScheduler(
        self, request: scheduler_runtime_pb2.SchedulerRegisterRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:

        def _register(session: Any) -> None:
            runtime_worker_service.register_worker(
                session,
                worker_id=request.worker_id,
                kind=RuntimeWorkerKind.SCHEDULER,
                hostname=request.hostname,
                pid=request.pid,
                capacity=request.capacity,
            )

        run_settings_db(_register)
        return _response(request.worker_id)

    @_run_async_handler_in_thread
    async def HeartbeatScheduler(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> common_pb2.RuntimeWorkerResponse:

        def _heartbeat(session: Any) -> None:
            runtime_worker_service.heartbeat_worker(session, worker_id=request.worker_id)

        run_settings_db(_heartbeat)
        return _response(request.worker_id)

    @_run_async_handler_in_thread
    async def StopScheduler(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> common_pb2.RuntimeWorkerResponse:

        def _stop(session: Any) -> None:
            runtime_worker_service.mark_worker_stopped(session, worker_id=request.worker_id)

        run_settings_db(_stop)
        return _response(request.worker_id)

    @_run_async_handler_in_thread
    async def RunDueSchedules(
        self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext
    ) -> scheduler_runtime_pb2.SchedulerRunDueResponse:
        reclaimable_owner_ids = run_settings_db(runtime_worker_service.reclaimable_worker_ids, kind=RuntimeWorkerKind.SCHEDULER)
        enqueued: list[scheduler_runtime_pb2.SchedulerEnqueuedRun] = []
        failures: list[scheduler_runtime_pb2.SchedulerRunFailure] = []
        for namespace in run_settings_db(list_runtime_namespaces):
            token = set_namespace_context(namespace)
            try:
                claimed = run_db(
                    lambda session: [
                        (schedule.id, schedule.datasource_id)
                        for schedule in scheduler_service.claim_due_schedules(
                            session,
                            worker_id=request.worker_id,
                            reclaimable_owner_ids=reclaimable_owner_ids,
                        )
                    ]
                )
                for schedule_id, datasource_id in claimed:
                    try:

                        def _enqueue(session: Any, target_id: str = schedule_id) -> str:
                            return scheduler_service.enqueue_schedule_run(
                                session,
                                target_id,
                                worker_id=request.worker_id,
                            )

                        build_id = run_db(_enqueue)
                        enqueued.append(
                            scheduler_runtime_pb2.SchedulerEnqueuedRun(
                                namespace=namespace,
                                schedule_id=schedule_id,
                                datasource_id=datasource_id,
                                build_id=build_id,
                            )
                        )
                    except Exception as exc:

                        def _mark_failed(session: Any, target_id: str = schedule_id, error: str = str(exc)) -> None:
                            scheduler_service.mark_schedule_enqueue_failed(
                                session,
                                target_id,
                                error=error,
                            )

                        run_db(_mark_failed)
                        failures.append(
                            scheduler_runtime_pb2.SchedulerRunFailure(
                                namespace=namespace,
                                schedule_id=schedule_id,
                                datasource_id=datasource_id,
                                error=str(exc),
                            )
                        )
            finally:
                reset_namespace(token)
        return scheduler_runtime_pb2.SchedulerRunDueResponse(handled=bool(enqueued or failures), enqueued=enqueued, failures=failures)


async def start_runtime_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server()
    worker_runtime_pb2_grpc.add_WorkerRuntimeServiceServicer_to_server(WorkerRuntimeServicer(), server)
    scheduler_runtime_pb2_grpc.add_SchedulerRuntimeServiceServicer_to_server(SchedulerRuntimeServicer(), server)
    server.add_insecure_port(f'{settings.internal_grpc_host}:{settings.internal_grpc_port}')
    await server.start()
    logger.info('Internal runtime gRPC server listening on %s:%s', settings.internal_grpc_host, settings.internal_grpc_port)
    return server
