from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session

from backend_core import compute_requests_service, runtime_outbox_service
from backend_core.data_plane_client import client_from_settings
from backend_core.dependencies import RuntimeAvailabilityProbe
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute_requests.live import response_hub
from backend_core.domain.compute_requests.models import command_from_payload
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.exceptions import PipelineExecutionError
from backend_core.namespace import get_namespace
from backend_core.object_store_paths import is_object_store_url
from dataforge_protocol import compute_pb2, enums_pb2
from modules.datasource import schemas as datasource_schemas

EngineIdentity = compute_pb2.EngineIdentity


def _ensure_runtime_available(runtime_probe: RuntimeAvailabilityProbe) -> None:
    if runtime_probe.available(kind=RuntimeWorkerKind.BUILD_MANAGER):
        return
    raise HTTPException(status_code=503, detail='Compute runtime unavailable')


async def _submit_and_wait(
    session: Session,
    *,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    runtime_probe: RuntimeAvailabilityProbe,
):
    _ensure_runtime_available(runtime_probe)
    try:
        request = compute_requests_service.create_request(
            session,
            namespace=get_namespace(),
            kind=kind,
            command=command,
            commit=False,
        )
        runtime_outbox_service.enqueue_compute_request_notification(session, request_id=request.id, commit=False)
        session.commit()
        session.refresh(request)
    except Exception:
        session.rollback()
        raise
    wait_task = asyncio.create_task(response_hub.wait(request.id))
    runtime_outbox_service.dispatch_pending_events(session)
    while True:
        session.expire_all()
        completed = compute_requests_service.get_request(session, request.id)
        if completed is None:
            wait_task.cancel()
            raise PipelineExecutionError(f'Compute request {request.id} disappeared')
        if completed.status in {enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED, enums_pb2.COMPUTE_REQUEST_STATUS_FAILED}:
            wait_task.cancel()
            break
        session.rollback()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(wait_task), timeout=0.05)
        if wait_task.done():
            wait_task = asyncio.create_task(response_hub.wait(request.id))
    if completed.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED:
        return completed
    payload = compute_requests_service.response_payload(completed)
    message = str(payload.get('error') or completed.error_message or 'Compute request failed')
    status_code = payload.get('status_code')
    if isinstance(status_code, int):
        raise HTTPException(status_code=status_code, detail=message)
    raise PipelineExecutionError(message)


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
) -> compute_schemas.StepPreviewResponse:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, request.model_dump(mode='json')),
        runtime_probe=runtime_probe,
    )
    return compute_schemas.StepPreviewResponse.model_validate(compute_requests_service.response_payload(completed))


async def get_step_schema(
    session: Session,
    request: compute_schemas.StepSchemaRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
) -> compute_schemas.StepSchemaResponse:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA, request.model_dump(mode='json')),
        runtime_probe=runtime_probe,
    )
    return compute_schemas.StepSchemaResponse.model_validate(compute_requests_service.response_payload(completed))


async def get_step_row_count(
    session: Session,
    request: compute_schemas.StepRowCountRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
) -> compute_schemas.StepRowCountResponse:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT, request.model_dump(mode='json')),
        runtime_probe=runtime_probe,
    )
    return compute_schemas.StepRowCountResponse.model_validate(compute_requests_service.response_payload(completed))


async def download_step(
    session: Session,
    request: compute_schemas.DownloadRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
) -> tuple[bytes, str, str]:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD, request.model_dump(mode='json')),
        runtime_probe=runtime_probe,
    )
    if not completed.artifact_path or not completed.artifact_name or not completed.artifact_content_type:
        raise PipelineExecutionError('Download artifact missing from compute response')
    if is_object_store_url(completed.artifact_path):
        data_plane = client_from_settings()
        data = data_plane.download_object_bytes(completed.artifact_path)
        data_plane.delete_object(completed.artifact_path)
        return data, completed.artifact_name, completed.artifact_content_type
    path = Path(completed.artifact_path)
    data = path.read_bytes()
    path.unlink(missing_ok=True)
    return data, completed.artifact_name, completed.artifact_content_type


async def export_data(
    session: Session,
    request: compute_schemas.ExportRequest,
    *,
    runtime_probe: RuntimeAvailabilityProbe,
) -> compute_schemas.ExportResponse:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_EXPORT,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_EXPORT, request.model_dump(mode='json')),
        runtime_probe=runtime_probe,
    )
    return compute_schemas.ExportResponse.model_validate(compute_requests_service.response_payload(completed))


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
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        runtime_probe=runtime_probe,
        command=command_from_payload(
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
        ),
    )
    return datasource_schemas.DataSourceResponse.model_validate(compute_requests_service.response_payload(completed))


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
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        runtime_probe=runtime_probe,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
            {
                'name': name,
                'description': description,
                'connection_string': connection_string,
                'query': query,
                'branch': branch,
                'owner_id': owner_id,
            },
        ),
    )
    return datasource_schemas.DataSourceResponse.model_validate(compute_requests_service.response_payload(completed))


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
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        runtime_probe=runtime_probe,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
            {
                'name': name,
                'description': description,
                'source': source,
                'branch': branch,
                'owner_id': owner_id,
            },
        ),
    )
    return datasource_schemas.DataSourceResponse.model_validate(compute_requests_service.response_payload(completed))


async def ingest_datasource(
    session: Session,
    *,
    datasource_id: str,
    runtime_probe: RuntimeAvailabilityProbe,
) -> datasource_schemas.DataSourceResponse:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE, {'datasource_id': datasource_id}),
        runtime_probe=runtime_probe,
    )
    return datasource_schemas.DataSourceResponse.model_validate(compute_requests_service.response_payload(completed))


async def get_datasource_schema(
    session: Session,
    *,
    datasource_id: str,
    sheet_name: str | None,
    refresh: bool,
    runtime_probe: RuntimeAvailabilityProbe,
) -> datasource_schemas.SchemaInfo:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
            {
                'datasource_id': datasource_id,
                'sheet_name': sheet_name,
                'refresh': refresh,
            },
        ),
        runtime_probe=runtime_probe,
    )
    return datasource_schemas.SchemaInfo.model_validate(compute_requests_service.response_payload(completed))


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
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
            {
                'datasource_id': datasource_id,
                'column_name': column_name,
                'use_sample': use_sample,
                'sample_size': sample_size,
                'datasource_config': datasource_config or {},
            },
        ),
        runtime_probe=runtime_probe,
    )
    return datasource_schemas.ColumnStatsResponse.model_validate(compute_requests_service.response_payload(completed))


async def compare_iceberg_snapshots(
    session: Session,
    *,
    datasource_id: str,
    snapshot_a: str,
    snapshot_b: str,
    row_limit: int,
    runtime_probe: RuntimeAvailabilityProbe,
) -> datasource_schemas.SnapshotCompareResponse:
    completed = await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
            {
                'datasource_id': datasource_id,
                'snapshot_a': snapshot_a,
                'snapshot_b': snapshot_b,
                'row_limit': row_limit,
            },
        ),
        runtime_probe=runtime_probe,
    )
    return datasource_schemas.SnapshotCompareResponse.model_validate(compute_requests_service.response_payload(completed))


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
    return compute_schemas.EngineStatusSchema.model_validate(compute_requests_service.response_payload(completed))


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
    return compute_schemas.EngineStatusSchema.model_validate(compute_requests_service.response_payload(completed))


async def shutdown_engine(
    session: Session,
    *,
    identity: EngineIdentity,
    runtime_probe: RuntimeAvailabilityProbe,
) -> None:
    await _submit_and_wait(
        session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        command=_lifecycle_command('shutdown_engine', identity),
        runtime_probe=runtime_probe,
    )
