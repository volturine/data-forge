from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any, cast

import grpc
from google.protobuf import json_format
from sqlalchemy import select

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
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute.base import EngineStatusInfo
from backend_core.domain.compute_requests.models import compute_request_kind_name, datasource_result_from_payload, kind_from_proto
from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.exceptions import AppError
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.namespaces_service import list_runtime_namespaces
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult
from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
from backend_core.persistence.udfs.models import Udf
from backend_core.settings_projection import get_resolved_smtp, get_resolved_telegram_settings, get_resolved_telegram_token
from backend_core.smtp import send_smtp_message
from backend_grpc.codec import (
    datetime_to_timestamp,
    dict_to_struct,
    enum_to_proto_value,
    optional_timestamp_to_datetime,
    proto_value_to_enum_name,
    repeated_structs_to_dicts,
    struct_field_to_dict,
    struct_to_dict,
    timestamp_to_datetime,
)
from backend_grpc.validation import ProtovalidateAioInterceptor
from dataforge_protocol import (
    common_pb2,
    compute_pb2,
    datasource_pb2,
    enums_pb2,
    scheduler_runtime_pb2,
    scheduler_runtime_pb2_grpc,
    worker_runtime_pb2,
    worker_runtime_pb2_grpc,
)
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
        return RuntimeWorkerKind.require(value)
    except ValueError as exc:
        raise ValueError(f'Unsupported runtime worker kind: {value}') from exc


def _proto_runtime_worker_kind(value: int) -> RuntimeWorkerKind:
    return _parse_worker_kind(proto_value_to_enum_name(enums_pb2.RuntimeWorkerKind, 'RUNTIME_WORKER_KIND', value))


def _proto_compute_request_kind(value: int) -> enums_pb2.ComputeRequestKind:
    return kind_from_proto(value)


def _proto_value(prefix: str, value: object) -> Any:
    return enum_to_proto_value(prefix, str(value))


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return str(value) if value is not None else None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return int(value) if value is not None and isinstance(value, (str, int)) else None


def _read_optional_dict(payload: dict[str, object], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else None


def _optional_str(message: Any, field: str) -> str | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_bool(message: Any, field: str) -> bool | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_int(message: Any, field: str) -> int | None:
    return getattr(message, field) if message.HasField(field) else None


def _build_step_kind_token(message: compute_pb2.BuildStepKind) -> str:
    match message.WhichOneof('kind'):
        case 'pipeline':
            return proto_value_to_enum_name(enums_pb2.StepType, 'STEP_TYPE', message.pipeline)
        case 'execution_category':
            return proto_value_to_enum_name(enums_pb2.EngineRunExecutionCategory, 'ENGINE_RUN_EXECUTION_CATEGORY', message.execution_category)
        case _:
            raise ValueError('build step event is missing step_kind')


def _build_tab_result_payload(message: compute_pb2.BuildTabResult) -> dict[str, object]:
    payload: dict[str, object] = {
        'tab_id': message.tab_id,
        'tab_name': message.tab_name,
        'status': proto_value_to_enum_name(enums_pb2.BuildTabStatus, 'BUILD_TAB_STATUS', message.status),
    }
    for field in ('output_id', 'output_name', 'error'):
        if message.HasField(field):
            payload[field] = getattr(message, field)
    return payload


def _build_terminal_event_payload(message: compute_pb2.BuildTerminalEvent) -> dict[str, object]:
    payload: dict[str, object] = {
        'progress': message.progress,
        'elapsed_ms': message.elapsed_ms,
        'total_steps': message.total_steps,
        'tabs_built': message.tabs_built,
        'results': [_build_tab_result_payload(result) for result in message.results],
        'duration_ms': message.duration_ms,
    }
    if message.HasField('error'):
        payload['error'] = message.error
    if message.HasField('cancelled_at'):
        payload['cancelled_at'] = timestamp_to_datetime(message.cancelled_at)
    if message.HasField('cancelled_by'):
        payload['cancelled_by'] = message.cancelled_by
    return payload


def _build_event_payload(message: compute_pb2.BuildEvent) -> dict[str, object]:
    context = message.context
    payload: dict[str, object] = {
        'build_id': context.build_id,
        'analysis_id': context.analysis_id,
        'emitted_at': timestamp_to_datetime(context.emitted_at),
    }
    if context.HasField('sequence'):
        payload['sequence'] = context.sequence
    if context.HasField('current_kind'):
        payload['current_kind'] = proto_value_to_enum_name(enums_pb2.EngineRunKind, 'ENGINE_RUN_KIND', context.current_kind)
    for field in ('current_datasource_id', 'tab_id', 'tab_name', 'current_output_id', 'current_output_name', 'engine_run_id'):
        if context.HasField(field):
            payload[field] = getattr(context, field)

    match message.WhichOneof('event'):
        case 'plan':
            payload.update({'type': 'plan', 'optimized_plan': message.plan.optimized_plan, 'unoptimized_plan': message.plan.unoptimized_plan})
        case 'step_started':
            payload.update(
                {
                    'type': 'step_start',
                    'build_step_index': message.step_started.build_step_index,
                    'step_index': message.step_started.step_index,
                    'step_id': message.step_started.step_id,
                    'step_name': message.step_started.step_name,
                    'step_type': _build_step_kind_token(message.step_started.step_kind),
                    'total_steps': message.step_started.total_steps,
                }
            )
        case 'step_completed':
            payload.update(
                {
                    'type': 'step_complete',
                    'build_step_index': message.step_completed.build_step_index,
                    'step_index': message.step_completed.step_index,
                    'step_id': message.step_completed.step_id,
                    'step_name': message.step_completed.step_name,
                    'step_type': _build_step_kind_token(message.step_completed.step_kind),
                    'duration_ms': message.step_completed.duration_ms,
                    'total_steps': message.step_completed.total_steps,
                }
            )
            if message.step_completed.HasField('row_count'):
                payload['row_count'] = message.step_completed.row_count
        case 'step_failed':
            payload.update(
                {
                    'type': 'step_failed',
                    'build_step_index': message.step_failed.build_step_index,
                    'step_index': message.step_failed.step_index,
                    'step_id': message.step_failed.step_id,
                    'step_name': message.step_failed.step_name,
                    'step_type': _build_step_kind_token(message.step_failed.step_kind),
                    'error': message.step_failed.error,
                    'total_steps': message.step_failed.total_steps,
                }
            )
        case 'progress':
            payload.update(
                {
                    'type': 'progress',
                    'progress': message.progress.progress,
                    'elapsed_ms': message.progress.elapsed_ms,
                    'total_steps': message.progress.total_steps,
                }
            )
            if message.progress.HasField('estimated_remaining_ms'):
                payload['estimated_remaining_ms'] = message.progress.estimated_remaining_ms
            if message.progress.HasField('current_step'):
                payload['current_step'] = message.progress.current_step
            if message.progress.HasField('current_step_index'):
                payload['current_step_index'] = message.progress.current_step_index
        case 'resources':
            payload.update(
                {
                    'type': 'resources',
                    'cpu_percent': message.resources.cpu_percent,
                    'memory_mb': message.resources.memory_mb,
                    'active_threads': message.resources.active_threads,
                }
            )
            if message.resources.HasField('memory_limit_mb'):
                payload['memory_limit_mb'] = message.resources.memory_limit_mb
            if message.resources.HasField('max_threads'):
                payload['max_threads'] = message.resources.max_threads
        case 'log':
            payload.update(
                {
                    'type': 'log',
                    'level': proto_value_to_enum_name(enums_pb2.BuildLogLevel, 'BUILD_LOG_LEVEL', message.log.level),
                    'message': message.log.message,
                }
            )
            for field in ('step_name', 'step_id'):
                if message.log.HasField(field):
                    payload[field] = getattr(message.log, field)
        case 'completed':
            payload.update({'type': 'complete', **_build_terminal_event_payload(message.completed)})
        case 'failed':
            payload.update({'type': 'failed', **_build_terminal_event_payload(message.failed)})
        case 'cancelled':
            payload.update({'type': 'cancelled', **_build_terminal_event_payload(message.cancelled)})
        case _:
            raise ValueError('build event is missing typed event payload')
    return payload


def _build_resource_config_payload(message: compute_pb2.BuildResourceConfigSummary) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field in ('max_threads', 'max_memory_mb', 'streaming_chunk_size'):
        if message.HasField(field):
            payload[field] = getattr(message, field)
    return payload


def _schema_info_proto(payload: dict[str, object] | None) -> datasource_pb2.SchemaInfo:
    if not isinstance(payload, dict):
        return datasource_pb2.SchemaInfo()
    return cast(datasource_pb2.SchemaInfo, json_format.ParseDict(payload, datasource_pb2.SchemaInfo()))


def _schema_info_payload(message: datasource_pb2.SchemaInfo) -> dict[str, object]:
    columns: list[dict[str, object]] = []
    for column in message.columns:
        column_payload: dict[str, object] = {
            'name': column.name,
            'dtype': column.dtype,
            'nullable': column.nullable,
        }
        if column.HasField('sample_value'):
            column_payload['sample_value'] = column.sample_value
        if column.HasField('description'):
            column_payload['description'] = column.description
        columns.append(column_payload)

    payload: dict[str, object] = {}
    if columns:
        payload['columns'] = columns
    if message.HasField('row_count'):
        payload['row_count'] = message.row_count
    if message.sheet_names:
        payload['sheet_names'] = list(message.sheet_names)
    return payload


def _build_starter_proto(payload: dict[str, object]) -> compute_pb2.BuildStarter:
    message = compute_pb2.BuildStarter()
    for field in ('user_id', 'display_name', 'email', 'triggered_by'):
        value = payload.get(field)
        if isinstance(value, str):
            setattr(message, field, value)
    return message


def _build_resource_config_proto(payload: dict[str, object]) -> compute_pb2.BuildResourceConfigSummary:
    message = compute_pb2.BuildResourceConfigSummary()
    for field in ('max_threads', 'max_memory_mb', 'streaming_chunk_size'):
        value = payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            setattr(message, field, value)
    return message


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
                kind=_proto_runtime_worker_kind(request.kind),
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
                        kind=kind_from_proto(compute_request.kind),
                        command=compute_requests_service.command_envelope_for_request(compute_request),
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
                response_json=compute_requests_service.proto_response_payload(request.response_envelope),
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
                response_json=compute_requests_service.proto_response_payload(request.response_envelope),
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
    ) -> worker_runtime_pb2.WorkerDatasourceCommandResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            kind = _proto_compute_request_kind(request.kind)
            command = request.command
            response: Any
            if kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE:
                if command.WhichOneof('command') != 'create_file':
                    raise ValueError('datasource command must contain create_file')
                create_file = command.create_file
                csv_options = None
                if create_file.HasField('csv_options'):
                    csv_options = datasource_runtime_service.CSVOptions(
                        delimiter=create_file.csv_options.delimiter,
                        quote_char=create_file.csv_options.quote_char,
                        has_header=create_file.csv_options.has_header,
                        skip_rows=create_file.csv_options.skip_rows,
                        encoding=create_file.csv_options.encoding,
                    )
                response = datasource_runtime_service.create_file_datasource(
                    session=session,
                    name=create_file.name,
                    description=create_file.description if create_file.HasField('description') else None,
                    file_path=create_file.file_path,
                    file_type=proto_value_to_enum_name(enums_pb2.DataSourceFileType, 'DATA_SOURCE_FILE_TYPE', create_file.file_type),
                    options=struct_to_dict(create_file.options),
                    csv_options=csv_options,
                    sheet_name=create_file.sheet_name if create_file.HasField('sheet_name') else None,
                    start_row=create_file.start_row if create_file.HasField('start_row') else None,
                    start_col=create_file.start_col if create_file.HasField('start_col') else None,
                    end_col=create_file.end_col if create_file.HasField('end_col') else None,
                    end_row=create_file.end_row if create_file.HasField('end_row') else None,
                    has_header=create_file.has_header if create_file.HasField('has_header') else None,
                    table_name=create_file.table_name if create_file.HasField('table_name') else None,
                    named_range=create_file.named_range if create_file.HasField('named_range') else None,
                    cell_range=create_file.cell_range if create_file.HasField('cell_range') else None,
                    owner_id=create_file.owner_id if create_file.HasField('owner_id') else None,
                )
            elif kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE:
                if command.WhichOneof('command') != 'create_database':
                    raise ValueError('datasource command must contain create_database')
                create_database = command.create_database
                response = datasource_runtime_service.create_database_datasource(
                    session=session,
                    name=create_database.name,
                    description=create_database.description if create_database.HasField('description') else None,
                    connection_string=create_database.connection_string,
                    query=create_database.query,
                    branch=create_database.branch,
                    owner_id=create_database.owner_id if create_database.HasField('owner_id') else None,
                )
            elif kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE:
                if command.WhichOneof('command') != 'create_iceberg':
                    raise ValueError('datasource command must contain create_iceberg')
                create_iceberg = command.create_iceberg
                response = datasource_runtime_service.create_iceberg_datasource(
                    session=session,
                    name=create_iceberg.name,
                    description=create_iceberg.description if create_iceberg.HasField('description') else None,
                    source=struct_to_dict(create_iceberg.source),
                    branch=create_iceberg.branch,
                    owner_id=create_iceberg.owner_id if create_iceberg.HasField('owner_id') else None,
                )
            elif kind == enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE:
                if command.WhichOneof('command') != 'ingest':
                    raise ValueError('datasource command must contain ingest')
                response = datasource_runtime_service.ingest_external_datasource(session, command.ingest.datasource_id)
            elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
                if command.WhichOneof('command') != 'schema':
                    raise ValueError('datasource command must contain schema')
                schema = command.schema
                response = datasource_runtime_service.get_datasource_schema(
                    session,
                    schema.datasource_id,
                    sheet_name=schema.sheet_name if schema.HasField('sheet_name') else None,
                    refresh=schema.refresh,
                )
            elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS:
                if command.WhichOneof('command') != 'column_stats':
                    raise ValueError('datasource command must contain column_stats')
                column_stats = command.column_stats
                response = datasource_runtime_service.get_column_stats(
                    session=session,
                    datasource_id=column_stats.datasource_id,
                    column_name=column_stats.column_name,
                    use_sample=column_stats.use_sample,
                    sample_size=column_stats.sample_size,
                    datasource_config=struct_to_dict(column_stats.datasource_config),
                )
            elif kind == enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS:
                if command.WhichOneof('command') != 'compare_iceberg_snapshots':
                    raise ValueError('datasource command must contain compare_iceberg_snapshots')
                compare_snapshots = command.compare_iceberg_snapshots
                response = datasource_runtime_service.compare_iceberg_snapshots(
                    session,
                    compare_snapshots.datasource_id,
                    compare_snapshots.snapshot_a,
                    compare_snapshots.snapshot_b,
                    compare_snapshots.row_limit,
                )
            else:
                raise ValueError(f'Unsupported datasource request kind: {compute_request_kind_name(kind)}')
            response_payload = response.model_dump(mode='json')
            return worker_runtime_pb2.WorkerDatasourceCommandResponse(result=datasource_result_from_payload(kind, response_payload))
        except AppError as exc:
            if exc.error_code != 'DATASOURCE_NOT_FOUND':
                raise
            logger.warning('Datasource not found for %s: %s', compute_request_kind_name(kind), exc)
            response_payload = {'error': 'datasource_not_found', 'message': str(exc)}
            return worker_runtime_pb2.WorkerDatasourceCommandResponse(result=datasource_result_from_payload(kind, response_payload))
        finally:
            session.close()
            session_gen.close()
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def ScheduleIngestDatasource(
        self, request: worker_runtime_pb2.WorkerScheduleIngestDatasourceRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerScheduleIngestDatasourceResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            response = datasource_runtime_service.ingest_datasource_for_schedule(session, request.datasource_id)
            result = datasource_result_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE, response.model_dump(mode='json'))
            if result.WhichOneof('result') != 'datasource':
                raise ValueError('schedule ingest must return a datasource result')
            return worker_runtime_pb2.WorkerScheduleIngestDatasourceResponse(datasource=result.datasource)
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
                source_type=_proto_value('DATA_SOURCE_TYPE', datasource.source_type),
                config=dict_to_struct(dict(datasource.config)),
                is_hidden=datasource.is_hidden,
            )
            if isinstance(datasource.schema_cache, dict):
                response.schema_info.CopyFrom(_schema_info_proto(dict(datasource.schema_cache)))
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
            cancelled_by = run.cancelled_by if isinstance(run.cancelled_by, str) else None
            response = worker_runtime_pb2.WorkerBuildCancelStatusResponse(cancelled=True, cancelled_by=cancelled_by)
            if isinstance(run.cancelled_at, datetime):
                response.cancelled_at.CopyFrom(datetime_to_timestamp(run.cancelled_at))
            return response
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def UpdateBuildResult(
        self, request: worker_runtime_pb2.WorkerUpdateBuildResultRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        try:
            run_db(build_run_service.update_build_result_json, request.build_id, struct_to_dict(request.result))
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
            schema_cache = _schema_info_payload(request.schema_info)
            existing = session.get(DataSource, request.result_id)
            if existing is not None:
                existing.name = request.name
                existing.source_type = proto_value_to_enum_name(enums_pb2.DataSourceType, 'DATA_SOURCE_TYPE', request.source_type)
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
                source_type=proto_value_to_enum_name(enums_pb2.DataSourceType, 'DATA_SOURCE_TYPE', request.source_type),
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
                        check_type=_proto_value('HEALTH_CHECK_TYPE', check.check_type),
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
                        checked_at=timestamp_to_datetime(result.checked_at),
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
                    kind=proto_value_to_enum_name(enums_pb2.EngineRunKind, 'ENGINE_RUN_KIND', request.kind),
                    status=proto_value_to_enum_name(enums_pb2.EngineRunStatus, 'ENGINE_RUN_STATUS', request.status),
                    request_json=struct_to_dict(request.request),
                    result_json=struct_field_to_dict(request, 'result'),
                    error_message=_optional_str(request, 'error_message'),
                    created_at=optional_timestamp_to_datetime(request, 'created_at'),
                    completed_at=optional_timestamp_to_datetime(request, 'completed_at'),
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
        kwargs: dict[str, Any] = {'merge_result_json': request.merge_result}
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
            response = worker_runtime_pb2.WorkerEngineRunStateResponse(
                found=True,
                status=_proto_value('ENGINE_RUN_STATUS', run.status),
                result=dict_to_struct(result_json),
                cancelled_by=cancelled_by if isinstance(cancelled_by, str) else None,
            )
            if isinstance(cancelled_at, str):
                response.cancelled_at.CopyFrom(datetime_to_timestamp(datetime.fromisoformat(cancelled_at)))
            return response
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
        event = compute_schemas.BuildEventAdapter.validate_python(_build_event_payload(request.build_event))
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            result: tuple[object, int] | None = await build_event_service.persist_build_event(
                session,
                namespace=request.namespace,
                build_id=request.build_id,
                event=event,
                resource_config_json=_build_resource_config_payload(request.build_resource_config) if request.HasField('build_resource_config') else None,
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
                request=dict_to_struct(dict(run.request_json)),
                build_starter=_build_starter_proto(dict(run.starter_json)),
                current_datasource_id=run.current_datasource_id,
                current_tab_id=run.current_tab_id,
                current_tab_name=run.current_tab_name,
                current_output_id=run.current_output_id,
                current_output_name=run.current_output_name,
                total_tabs=run.total_tabs,
            )
            if isinstance(run.current_kind, str):
                payload.current_kind = _proto_value('ENGINE_RUN_KIND', run.current_kind)
            payload.started_at.CopyFrom(datetime_to_timestamp(run.started_at))
            if isinstance(run.resource_config_json, dict):
                payload.build_resource_config.CopyFrom(_build_resource_config_proto(dict(run.resource_config_json)))
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
            request.provider,
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
    server = grpc.aio.server(interceptors=(ProtovalidateAioInterceptor(),))
    worker_runtime_pb2_grpc.add_WorkerRuntimeServiceServicer_to_server(WorkerRuntimeServicer(), server)
    scheduler_runtime_pb2_grpc.add_SchedulerRuntimeServiceServicer_to_server(SchedulerRuntimeServicer(), server)
    server.add_insecure_port(f'{settings.internal_grpc_host}:{settings.internal_grpc_port}')
    await server.start()
    logger.info('Internal runtime gRPC server listening on %s:%s', settings.internal_grpc_host, settings.internal_grpc_port)
    return server
