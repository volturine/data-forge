from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError as PydanticValidationError
from sqlmodel import Session

from backend_core import compute_requests_service, datasource_delete_service, runtime_ipc
from backend_core.compute_response_recovery import response_recovery
from backend_core.data_plane_client import client_from_settings
from backend_core.database import run_db
from backend_core.datasource_lifecycle import lock_datasource_lifecycle, uses_postgres_advisory_locks
from backend_core.dependencies import RuntimeAvailabilityProbe
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute_requests.models import command_from_payload
from backend_core.exceptions import ClientDisconnectedError, PipelineExecutionCancelledError, PipelineExecutionError
from backend_core.namespace import get_namespace, reset_namespace, set_namespace_context
from dataforge_protocol import compute_pb2, datasource_pb2, enums_pb2
from modules.analysis.step_schemas import normalize_step_config_for_protocol
from modules.datasource import schemas as datasource_schemas
from modules.datasource.schema_protocol import schema_info_proto

EngineIdentity = compute_pb2.EngineIdentity
_ENGINE_SHUTDOWN_CANCELLATION = 'Compute request cancelled because its engine was shut down'
_HTTP_DISCONNECT_POLL_SECONDS = 0.5
logger = logging.getLogger(__name__)

# Pipeline-to-protobuf conversion walks the complete analysis tree and can
# include every tab, step, and nested config. Keep it off Uvicorn's event loop
# and bound the CPU fan-out so a burst of browser previews cannot create one
# executor thread per request or compete with the durable DB work.
_COMPUTE_SERIALIZATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix='compute-serialization',
)


def _command_fingerprint(command: compute_pb2.ComputeCommand) -> str:
    return hashlib.sha256(command.SerializeToString(deterministic=True)).hexdigest()


async def _run_compute_serialization[T](function: Callable[..., T], *args: object, **kwargs: object) -> T:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _COMPUTE_SERIALIZATION_EXECUTOR,
        partial(function, *args, **kwargs),
    )


async def model_payload(model: BaseModel, *, mode: str = 'python') -> dict[str, object]:
    """Dump a potentially large request model without occupying the API loop."""
    return await _run_compute_serialization(model.model_dump, mode=mode)


async def parse_request_model[T: BaseModel](request: Request, model_type: type[T]) -> T:
    """Validate a large JSON request without running Pydantic on Uvicorn's loop."""
    body = await request.body()
    try:
        return await _run_compute_serialization(model_type.model_validate_json, body)
    except PydanticValidationError as exc:
        raise RequestValidationError(exc.errors(), body=body) from exc


def _json_response_content(value: object) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json(by_alias=True, ensure_ascii=False)
    return json.dumps(
        jsonable_encoder(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(',', ':'),
    )


async def json_response(value: object, *, headers: Mapping[str, str] | None = None) -> Response:
    """Serialize a potentially large response without occupying the API loop."""
    content = await _run_compute_serialization(_json_response_content, value)
    return Response(content=content, media_type='application/json', headers=headers)


def json_response_sync(value: object, *, headers: Mapping[str, str] | None = None) -> Response:
    """Serialize from a synchronous route's worker thread, not the API loop."""
    return Response(content=_json_response_content(value), media_type='application/json', headers=headers)


async def _response_payload(completed) -> dict[str, object]:
    """Decode the protobuf response outside the API event loop."""
    return await _run_compute_serialization(compute_requests_service.response_payload, completed)


async def _validated_response[T: BaseModel](model_type: type[T], completed) -> T:
    payload = await _response_payload(completed)
    # Pydantic validation can walk thousands of preview cells. Keep that work
    # on the bounded compute serialization pool so response assembly cannot
    # starve Uvicorn's health ping or create a second unbounded CPU burst.
    return await _run_compute_serialization(model_type.model_validate, payload)


async def _wait_for_http_disconnect(http_request: Request) -> None:
    while not await http_request.is_disconnected():
        await asyncio.sleep(_HTTP_DISCONNECT_POLL_SECONDS)
    raise ClientDisconnectedError


async def _wait_for_response_or_disconnect(
    request_id: str,
    last_seen: int,
    http_request: Request | None,
) -> int:
    response_task = asyncio.create_task(response_recovery.wait_for_wake(request_id, last_seen))
    if http_request is None:
        return await response_task

    disconnect_task = asyncio.create_task(_wait_for_http_disconnect(http_request))
    try:
        done, _pending = await asyncio.wait(
            {response_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if disconnect_task in done:
            await disconnect_task
        return response_task.result()
    finally:
        for task in (response_task, disconnect_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(response_task, disconnect_task, return_exceptions=True)


def _require_active_pipeline_datasources(session: Session, pipeline: compute_schemas.AnalysisPipelinePayload) -> None:
    """Reject stale pipeline snapshots before they enter the durable queue."""
    tab_ids = {tab.id for tab in pipeline.tabs}
    output_ids = {result_id for tab in pipeline.tabs if isinstance((result_id := tab.output.get('result_id')), str)}
    local_ids = tab_ids | output_ids
    external_ids: set[str] = set()
    for tab in pipeline.tabs:
        datasource = tab.datasource
        if datasource.analysis_tab_id is None and datasource.id not in local_ids:
            external_ids.add(datasource.id)
        for step in tab.steps:
            config = step.get('config')
            if not isinstance(config, dict):
                continue
            right_source = config.get('right_source')
            if isinstance(right_source, str) and right_source not in local_ids:
                external_ids.add(right_source)
            sources = config.get('sources')
            if isinstance(sources, list):
                external_ids.update(source for source in sources if isinstance(source, str) and source not in local_ids)
    for datasource_id in sorted(external_ids):
        _require_active_datasource_for_enqueue(session, datasource_id)


def _require_active_datasource_for_enqueue(session: Session, datasource_id: str) -> None:
    # PostgreSQL uses a short transaction-scoped lifecycle fence shared with
    # datasource deletion. Keeping the row lock only for SQLite preserves the
    # in-process test database's race semantics without creating a production
    # row-lock convoy for every preview that shares one source.
    lock_datasource_lifecycle(session, namespace=get_namespace(), datasource_id=datasource_id, shared=True)
    datasource_delete_service.get_active_datasource(
        session,
        datasource_id,
        for_update=not uses_postgres_advisory_locks(session),
    )


def _protocol_request_payload(request: BaseModel) -> dict[str, object]:
    payload = cast(dict[str, object], request.model_dump(mode='json'))
    pipeline = payload.get('analysis_pipeline')
    if not isinstance(pipeline, dict):
        return payload
    tabs = pipeline.get('tabs')
    if not isinstance(tabs, list):
        return payload
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        steps = tab.get('steps')
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_type = step.get('type')
            config = step.get('config')
            if isinstance(step_type, str) and isinstance(config, dict):
                step['config'] = normalize_step_config_for_protocol(step_type, config)
    return payload


def _command_from_request(
    kind: enums_pb2.ComputeRequestKind,
    request: BaseModel,
) -> compute_pb2.ComputeCommand:
    return command_from_payload(kind, _protocol_request_payload(request))


async def _request_command(
    kind: enums_pb2.ComputeRequestKind,
    request: BaseModel,
) -> compute_pb2.ComputeCommand:
    return await _run_compute_serialization(_command_from_request, kind, request)


async def _payload_command(
    kind: enums_pb2.ComputeRequestKind,
    payload: dict[str, object],
) -> compute_pb2.ComputeCommand:
    return await _run_compute_serialization(command_from_payload, kind, payload)


def _ensure_runtime_available(runtime_probe: RuntimeAvailabilityProbe) -> None:
    # Compute requests are durable queue entries. A heartbeat is only a
    # liveness observation and can become stale between this check and the
    # enqueue, so rejecting here turns a transient observation into a lost
    # user operation. The worker claims the request when it is available and
    # the response wait already covers that queueing period.
    del runtime_probe


def _submit(
    session: Session,
    *,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    runtime_probe: RuntimeAvailabilityProbe,
    validate: Callable[[], None] | None = None,
):
    _ensure_runtime_available(runtime_probe)
    try:
        if kind in compute_requests_service.SHARED_FLIGHT_REQUEST_KINDS:
            request, created = compute_requests_service.stage_shared_flight_request(
                session,
                namespace=get_namespace(),
                kind=kind,
                command=command,
                validate=validate,
            )
        else:
            if validate is not None:
                validate()
            request = compute_requests_service.stage_request(
                session,
                namespace=get_namespace(),
                kind=kind,
                command=command,
            )
            created = True
        if created:
            runtime_ipc.notify_compute_request_on_commit(
                session,
                request_id=request.id,
                namespace=request.namespace,
                compute_kind=request.kind,
            )
        session.commit()
        # The transaction delivers the wake only after the durable request and
        # its namespace recovery marker commit together.
        session.refresh(request)
    except Exception:
        session.rollback()
        raise
    return request


def _stage_validated_request(
    session: Session,
    *,
    pipeline: compute_schemas.AnalysisPipelinePayload | None,
    datasource_ids: tuple[str, ...],
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    runtime_probe: RuntimeAvailabilityProbe,
):
    """Validate referenced datasources and enqueue in one short DB task.

    Keep validation in the same worker task as ``_submit``. PostgreSQL uses a
    short datasource lifecycle advisory fence at the enqueue boundary; SQLite
    retains row-lock behavior for the in-process race tests. Dispatching
    validation and enqueue as separate thread-pool jobs would let a burst fill
    every thread with blocked lifecycle work and leave the first enqueue
    behind the blocked reads.
    """

    def validate() -> None:
        if pipeline is not None:
            _require_active_pipeline_datasources(session, pipeline)
        for datasource_id in sorted(set(datasource_ids)):
            # Direct datasource requests do not carry an analysis pipeline,
            # but still need the same deletion-to-enqueue fence as previews.
            _require_active_datasource_for_enqueue(session, datasource_id)

    return _submit(
        session,
        kind=kind,
        command=command,
        runtime_probe=runtime_probe,
        validate=validate,
    )


def _stage_validated_request_in_new_session(
    *,
    namespace: str,
    pipeline: compute_schemas.AnalysisPipelinePayload | None,
    datasource_ids: tuple[str, ...],
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    runtime_probe: RuntimeAvailabilityProbe,
):
    """Stage a request with a session owned by the blocking DB thread.

    FastAPI's synchronous ``Session`` dependency is created and finalized by
    AnyIO, while this async client performs its queue work in ``to_thread``.
    Passing that Session between executor threads is not safe. Each durable
    queue transaction therefore gets its own short-lived session.
    """
    token = set_namespace_context(namespace)
    try:
        return run_db(
            _stage_validated_request,
            pipeline=pipeline,
            datasource_ids=datasource_ids,
            kind=kind,
            command=command,
            runtime_probe=runtime_probe,
        )
    finally:
        reset_namespace(token)


async def _stage_shared_request_without_waiting_on_a_database_lock(stage: Callable[[], Any]) -> Any:
    """Retry single-flight admission without holding a DB connection while queued."""
    delay_seconds = 0.01
    while True:
        try:
            return await asyncio.to_thread(stage)
        except compute_requests_service.ComputeFlightLockBusy:
            await asyncio.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, 0.1)


async def _submit_and_wait(
    session: Session,
    *,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    runtime_probe: RuntimeAvailabilityProbe,
    pipeline: compute_schemas.AnalysisPipelinePayload | None = None,
    datasource_ids: tuple[str, ...] = (),
    http_request: Request | None = None,
):
    del session
    namespace = get_namespace()
    process_id = os.getpid()
    wait_started = time.monotonic()
    slow_wait_reported = False
    last_wake_wait_ms: float | None = None
    command_hash = await _run_compute_serialization(_command_fingerprint, command)
    stage = partial(
        _stage_validated_request_in_new_session,
        namespace=namespace,
        pipeline=pipeline,
        datasource_ids=datasource_ids,
        kind=kind,
        command=command,
        runtime_probe=runtime_probe,
    )
    if kind in compute_requests_service.SHARED_FLIGHT_REQUEST_KINDS:
        request = await _stage_shared_request_without_waiting_on_a_database_lock(stage)
    else:
        request = await asyncio.to_thread(stage)
    await response_recovery.register(request.id, request.namespace)
    request_state = http_request.scope.get('state', {}) if http_request is not None else {}
    http_request_id = request_state.get('request_id', '-')
    logger.debug(
        'Compute request staged durable_request_id=%s http_request_id=%s kind=%s namespace=%s resource_id=%s process_id=%s command_hash=%s',
        request.id,
        http_request_id,
        kind,
        request.namespace,
        request.engine_resource_id or '-',
        process_id,
        command_hash,
    )
    seen_version = await response_recovery.wake_version(request.id)
    try:
        while True:
            completed = await response_recovery.terminal_request(request.id)
            if completed is None:
                completed = await asyncio.to_thread(_read_request_in_new_session, request.id, request.namespace)
            if completed is None:
                raise PipelineExecutionError(f'Compute request {request.id} disappeared')
            if not slow_wait_reported and time.monotonic() - wait_started >= 5.0:
                slow_wait_reported = True
                logger.warning(
                    'Compute request still waiting durable_request_id=%s http_request_id=%s kind=%s '
                    'namespace=%s resource_id=%s process_id=%s command_hash=%s wait_ms=%.1f '
                    'wake_wait_ms=%s wake_version=%s',
                    request.id,
                    http_request_id,
                    kind,
                    request.namespace,
                    request.engine_resource_id or '-',
                    process_id,
                    command_hash,
                    (time.monotonic() - wait_started) * 1000,
                    f'{last_wake_wait_ms:.1f}' if last_wake_wait_ms is not None else '-',
                    seen_version,
                )
            if completed.status in {enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED, enums_pb2.COMPUTE_REQUEST_STATUS_FAILED}:
                # The request was loaded in a short-lived session, so this
                # terminal result does not keep a tenant connection checked
                # out while FastAPI serializes the response.
                logger.debug(
                    'Compute request terminal durable_request_id=%s http_request_id=%s namespace=%s resource_id=%s command_hash=%s status=%s wait_ms=%.1f',
                    request.id,
                    http_request_id,
                    request.namespace,
                    request.engine_resource_id or '-',
                    command_hash,
                    completed.status,
                    (time.monotonic() - wait_started) * 1000,
                )
                break
            # PostgreSQL NOTIFY wakes this exact request immediately. The
            # shared recovery task checks all pending IDs in one query every
            # five seconds when a notification is lost; do not add a private
            # database polling loop for every browser tab.
            previous_version = seen_version
            wake_wait_started = time.monotonic()
            if kind in compute_requests_service.SHARED_FLIGHT_REQUEST_KINDS:
                # A shared request belongs to its durable command, not to the
                # browser that first submitted it. Do not add one disconnect
                # poller per viewer or let a disconnected leader retire work
                # that followers may be awaiting.
                seen_version = await response_recovery.wait_for_wake(request.id, seen_version)
            else:
                seen_version = await _wait_for_response_or_disconnect(request.id, seen_version, http_request)
            last_wake_wait_ms = (time.monotonic() - wake_wait_started) * 1000
            wake_logger = logger.warning if last_wake_wait_ms >= 5_000 else logger.debug
            wake_logger(
                'Compute response waiter woke durable_request_id=%s http_request_id=%s process_id=%s previous_version=%s wake_version=%s wake_wait_ms=%.1f',
                request.id,
                http_request_id,
                process_id,
                previous_version,
                seen_version,
                last_wake_wait_ms,
            )
    except asyncio.CancelledError, ClientDisconnectedError:
        if kind not in compute_requests_service.SHARED_FLIGHT_REQUEST_KINDS:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    _cancel_disconnected_request_in_new_session,
                    request.id,
                    request.namespace,
                    'Compute request cancelled because the HTTP client disconnected',
                )
        raise
    finally:
        await response_recovery.unregister(request.id)
    if completed.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED:
        return completed
    payload = await _response_payload(completed)
    message = str(payload.get('error') or completed.error_message or 'Compute request failed')
    status_code = payload.get('status_code')
    request_state = http_request.scope.get('state', {}) if http_request is not None else {}
    logger.warning(
        'Durable compute request failed durable_request_id=%s http_request_id=%s kind=%s namespace=%s status_code=%s error_code=%s',
        request.id,
        request_state.get('request_id', '-'),
        kind,
        request.namespace,
        status_code if isinstance(status_code, int) else '-',
        payload.get('error_code', '-'),
    )
    if isinstance(status_code, int):
        raise HTTPException(status_code=status_code, detail=message)
    if message == _ENGINE_SHUTDOWN_CANCELLATION:
        raise PipelineExecutionCancelledError(message)
    raise PipelineExecutionError(message)


def _read_request(session: Session, request_id: str):
    """Read a durable compute request without blocking the API event loop."""
    session.expire_all()
    return compute_requests_service.get_request(session, request_id)


def _read_request_in_new_session(request_id: str, namespace: str):
    token = set_namespace_context(namespace)
    try:
        return run_db(_read_request, request_id)
    finally:
        reset_namespace(token)


def _cancel_disconnected_request_in_new_session(request_id: str, namespace: str, reason: str):
    token = set_namespace_context(namespace)
    try:
        return run_db(
            compute_requests_service.cancel_disconnected_request,
            request_id,
            reason=reason,
        )
    finally:
        reset_namespace(token)


def _cancel_active_requests_for_engine_in_new_session(identity: EngineIdentity) -> int:
    return run_db(
        compute_requests_service.cancel_active_requests_for_engine,
        namespace=get_namespace(),
        identity=identity,
        reason=_ENGINE_SHUTDOWN_CANCELLATION,
    )


def _resource_config_message(resource_config: dict[str, object]) -> compute_pb2.EngineResourceConfig:
    config = compute_pb2.EngineResourceConfig()
    for key in ('max_threads', 'max_memory_mb', 'streaming_chunk_size'):
        value = resource_config.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            setattr(config, key, value)
    return config


def _lifecycle_command(field_name: str, identity: EngineIdentity, resource_config: dict[str, object] | None = None) -> compute_pb2.ComputeCommand:
    command = compute_pb2.ComputeCommand()
    lifecycle = compute_pb2.EngineLifecycleCommand(engine_identity=identity)
    if resource_config is not None:
        lifecycle.resource_config.CopyFrom(_resource_config_message(resource_config))
    getattr(command, field_name).CopyFrom(lifecycle)
    return command


async def preview_step(
    session: Session,
    request: compute_schemas.StepPreviewRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
    http_request: Request | None = None,
) -> compute_schemas.StepPreviewResponse:
    normalized = request.model_copy(update={'engine_identity': compute_schemas.default_preview_engine_identity(request)})
    command = await _request_command(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, normalized)
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
        runtime_probe=runtime_probe,
        pipeline=normalized.analysis_pipeline,
        http_request=http_request,
    )
    return await _validated_response(compute_schemas.StepPreviewResponse, completed)


async def get_step_schema(
    session: Session,
    request: compute_schemas.StepSchemaRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
    http_request: Request | None = None,
) -> compute_schemas.StepSchemaResponse:
    command = await _request_command(enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA, request)
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        command=command,
        runtime_probe=runtime_probe,
        pipeline=request.analysis_pipeline,
        http_request=http_request,
    )
    return await _validated_response(compute_schemas.StepSchemaResponse, completed)


async def get_step_row_count(
    session: Session,
    request: compute_schemas.StepRowCountRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
    http_request: Request | None = None,
) -> compute_schemas.StepRowCountResponse:
    command = await _request_command(enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT, request)
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
        command=command,
        runtime_probe=runtime_probe,
        pipeline=request.analysis_pipeline,
        http_request=http_request,
    )
    return await _validated_response(compute_schemas.StepRowCountResponse, completed)


async def download_step(
    session: Session,
    request: compute_schemas.DownloadRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
) -> tuple[bytes, str, str]:
    command = await _request_command(enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD, request)
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD,
        command=command,
        runtime_probe=runtime_probe,
        pipeline=request.analysis_pipeline,
    )
    if not completed.artifact_path or not completed.artifact_name or not completed.artifact_content_type:
        raise PipelineExecutionError('Download artifact missing from compute response')
    data_plane = await asyncio.to_thread(client_from_settings)
    classification = await asyncio.to_thread(data_plane.classify_object_url, completed.artifact_path)
    if classification.is_object_store:
        data = await asyncio.to_thread(data_plane.download_object_bytes, completed.artifact_path)
        await asyncio.to_thread(data_plane.delete_object, completed.artifact_path)
        return data, completed.artifact_name, completed.artifact_content_type
    path = Path(completed.artifact_path)
    data = await asyncio.to_thread(path.read_bytes)
    await asyncio.to_thread(path.unlink, missing_ok=True)
    return data, completed.artifact_name, completed.artifact_content_type


async def export_data(
    session: Session,
    request: compute_schemas.ExportRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
) -> compute_schemas.ExportResponse:
    command = await _request_command(enums_pb2.COMPUTE_REQUEST_KIND_EXPORT, request)
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_EXPORT,
        command=command,
        runtime_probe=runtime_probe,
        pipeline=request.analysis_pipeline,
    )
    return await _validated_response(compute_schemas.ExportResponse, completed)


async def create_file_datasource(
    session: Session,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
    name: str,
    description: str | None,
    file_path: str,
    file_type: str,
    options: dict | None = None,
    csv_options: dict[str, object] | None = None,
    sheet_name: str | None = None,
    start_row: int | None = None,
    start_col: int | None = None,
    end_col: int | None = None,
    end_row: int | None = None,
    has_header: bool | None = None,
    table_name: str | None = None,
    named_range: str | None = None,
    cell_range: str | None = None,
    owner_id: str | None = None,
) -> datasource_schemas.DataSourceResponse:
    command = await _payload_command(
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        {
            'name': name,
            'description': description,
            'file_path': file_path,
            'file_type': file_type,
            'options': options or {},
            'csv_options': csv_options,
            'sheet_name': sheet_name,
            'start_row': start_row,
            'start_col': start_col,
            'end_col': end_col,
            'end_row': end_row,
            'has_header': has_header,
            'table_name': table_name,
            'named_range': named_range,
            'cell_range': cell_range,
            'owner_id': owner_id,
        },
    )
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        runtime_probe=runtime_probe,
        command=command,
    )
    return await _validated_response(datasource_schemas.DataSourceResponse, completed)


async def create_database_datasource(
    session: Session,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
    name: str,
    description: str | None,
    connection_string: str,
    query: str,
    branch: str,
    owner_id: str | None = None,
) -> datasource_schemas.DataSourceResponse:
    command = await _payload_command(
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        {
            'name': name,
            'description': description,
            'connection_string': connection_string,
            'query': query,
            'branch': branch,
            'owner_id': owner_id,
        },
    )
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        runtime_probe=runtime_probe,
        command=command,
    )
    return await _validated_response(datasource_schemas.DataSourceResponse, completed)


async def create_iceberg_datasource(
    session: Session,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
    name: str,
    description: str | None,
    source: dict[str, object],
    branch: str,
    owner_id: str | None = None,
) -> datasource_schemas.DataSourceResponse:
    command = await _payload_command(
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        {
            'name': name,
            'description': description,
            'source': source,
            'branch': branch,
            'owner_id': owner_id,
        },
    )
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        runtime_probe=runtime_probe,
        command=command,
    )
    return await _validated_response(datasource_schemas.DataSourceResponse, completed)


async def ingest_datasource(
    session: Session,
    *,
    datasource_id: str,
    runtime_probe: RuntimeAvailabilityProbe,
) -> datasource_schemas.DataSourceResponse:
    command = await _payload_command(
        enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        {'datasource_id': datasource_id},
    )
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        command=command,
        runtime_probe=runtime_probe,
        datasource_ids=(datasource_id,),
    )
    return await _validated_response(datasource_schemas.DataSourceResponse, completed)


async def get_datasource_schema(
    session: Session,
    *,
    datasource_id: str,
    sheet_name: str | None,
    refresh: bool,
    runtime_probe: RuntimeAvailabilityProbe,
) -> datasource_pb2.SchemaInfo:
    command = await _payload_command(
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        {
            'datasource_id': datasource_id,
            'sheet_name': sheet_name,
            'refresh': refresh,
        },
    )
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command,
        runtime_probe=runtime_probe,
        datasource_ids=(datasource_id,),
    )
    return await asyncio.to_thread(schema_info_proto, await _response_payload(completed))


async def get_column_stats(
    session: Session,
    *,
    datasource_id: str,
    column_name: str,
    use_sample: bool,
    sample_size: int,
    datasource_config: dict[str, object] | None,
    runtime_probe: RuntimeAvailabilityProbe,
) -> datasource_schemas.ColumnStatsResponse:
    command = await _payload_command(
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        {
            'datasource_id': datasource_id,
            'column_name': column_name,
            'use_sample': use_sample,
            'sample_size': sample_size,
            'datasource_config': datasource_config or {},
        },
    )
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        command=command,
        runtime_probe=runtime_probe,
        datasource_ids=(datasource_id,),
    )
    return await _validated_response(datasource_schemas.ColumnStatsResponse, completed)


async def compare_iceberg_snapshots(
    session: Session,
    *,
    datasource_id: str,
    snapshot_a: str,
    snapshot_b: str,
    row_limit: int,
    runtime_probe: RuntimeAvailabilityProbe,
) -> datasource_schemas.SnapshotCompareResponse:
    command = await _payload_command(
        enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
        {
            'datasource_id': datasource_id,
            'snapshot_a': snapshot_a,
            'snapshot_b': snapshot_b,
            'row_limit': row_limit,
        },
    )
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
        command=command,
        runtime_probe=runtime_probe,
        datasource_ids=(datasource_id,),
    )
    return await _validated_response(datasource_schemas.SnapshotCompareResponse, completed)


async def spawn_engine(
    session: Session,
    *,
    identity: EngineIdentity,
    runtime_probe: RuntimeAvailabilityProbe,
    resource_config: dict[str, object] | None,
) -> compute_schemas.EngineStatusSchema:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        command=_lifecycle_command('spawn_engine', identity, resource_config or {}),
        runtime_probe=runtime_probe,
    )
    return await _validated_response(compute_schemas.EngineStatusSchema, completed)


async def configure_engine(
    session: Session,
    *,
    identity: EngineIdentity,
    runtime_probe: RuntimeAvailabilityProbe,
    resource_config: dict[str, object],
) -> compute_schemas.EngineStatusSchema:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE,
        command=_lifecycle_command('configure_engine', identity, resource_config),
        runtime_probe=runtime_probe,
    )
    return await _validated_response(compute_schemas.EngineStatusSchema, completed)


async def shutdown_engine(
    session: Session,
    *,
    identity: EngineIdentity,
    runtime_probe: RuntimeAvailabilityProbe,
) -> None:
    await asyncio.to_thread(
        _cancel_active_requests_for_engine_in_new_session,
        identity,
    )
    await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        command=_lifecycle_command('shutdown_engine', identity),
        runtime_probe=runtime_probe,
    )


def request_engine_shutdown(
    session: Session,
    *,
    identity: EngineIdentity,
    runtime_probe: RuntimeAvailabilityProbe,
) -> None:
    """Durably queue engine shutdown without coupling an API response to its completion."""
    compute_requests_service.cancel_active_requests_for_engine(
        session,
        namespace=get_namespace(),
        identity=identity,
        reason=_ENGINE_SHUTDOWN_CANCELLATION,
    )
    _submit(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        command=_lifecycle_command('shutdown_engine', identity),
        runtime_probe=runtime_probe,
    )
