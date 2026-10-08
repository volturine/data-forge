import asyncio
import concurrent.futures
import logging
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote

import anyio
from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlmodel import Session

from backend_core import (
    build_event_service,
    build_runs_service as build_run_service,
    engine_runs_service as engine_run_service,
    runtime_ipc,
)
from backend_core.api_execution_budget import run_api_blocking
from backend_core.auth_config import settings as auth_settings
from backend_core.compute_worker_live import load_compute_worker_snapshot, registry as compute_worker_registry
from backend_core.config import settings
from backend_core.data_plane_client import client_from_settings
from backend_core.database import run_db, run_settings_db
from backend_core.dependencies import (
    RuntimeAvailabilityProbe,
    get_manager,
    get_runtime_availability_probe,
)
from backend_core.domain.build_runs.live import BuildNotification, hub as build_hub
from backend_core.domain.compute import schemas
from backend_core.domain.engine_runs.schemas import EngineRunKind
from backend_core.error_handlers import handle_errors
from backend_core.exceptions import engine_not_found
from backend_core.namespace import get_namespace, reset_namespace, set_namespace_context
from backend_core.persistence.analysis.models import Analysis
from backend_core.time import utc_now as _utcnow
from backend_core.validation import (
    AnalysisId,
    DataSourceId,
    parse_datasource_id,
)
from backend_core.websocket import (
    is_disconnect_runtime_error,
    resolve_websocket_session_token,
    safe_close_websocket,
    safe_send_json,
    safe_send_json_error,
    safe_send_serialized_json,
    websocket_disconnected,
)
from dataforge_protocol import compute_pb2, enums_pb2
from modules.analysis.step_schemas import normalize_pipeline_step_configs_for_protocol
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.compute import commands, executor_client, representations
from modules.compute.iceberg_service import (
    delete_iceberg_snapshot as delete_iceberg_snapshot_info,
    list_iceberg_snapshots as list_iceberg_snapshots_info,
)
from modules.datasource import service as datasource_service
from modules.mcp.router import MCPRouter
from modules.scheduler import service as scheduler_service

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/compute', tags=['compute'], dependencies=[Depends(get_current_user)])


async def _parse_preview_request(request: Request) -> schemas.StepPreviewRequest:
    return await executor_client.parse_request_model(request, schemas.StepPreviewRequest)


async def _parse_schema_request(request: Request) -> schemas.StepSchemaRequest:
    return await executor_client.parse_request_model(request, schemas.StepSchemaRequest)


async def _parse_row_count_request(request: Request) -> schemas.StepRowCountRequest:
    return await executor_client.parse_request_model(request, schemas.StepRowCountRequest)


async def _parse_export_request(request: Request) -> schemas.ExportRequest:
    return await executor_client.parse_request_model(request, schemas.ExportRequest)


async def _parse_download_request(request: Request) -> schemas.DownloadRequest:
    return await executor_client.parse_request_model(request, schemas.DownloadRequest)


async def _parse_build_request(request: Request) -> schemas.BuildRequest:
    return await executor_client.parse_request_model(request, schemas.BuildRequest)


async def _wait_for_websocket_disconnect(websocket: WebSocket) -> None:
    while not websocket_disconnected(websocket):
        try:
            message = await websocket.receive()
        except WebSocketDisconnect:
            return
        except RuntimeError as exc:
            if websocket_disconnected(websocket) or is_disconnect_runtime_error(exc):
                return
            raise
        if message.get('type') == 'websocket.disconnect':
            return


def _override_manager(container) -> Any | None:
    overrides = getattr(container.app, 'dependency_overrides', None)
    if not isinstance(overrides, dict):
        return None
    override = overrides.get(get_manager)
    if override is None:
        return None
    return override()


def _override_compute_executor(container) -> Any | None:
    return getattr(container.app.state, 'compute_override_executor', None)


def _run_compute_override[T](session: Session, execute: Callable[..., T], **kwargs: object) -> T:
    return execute(session=session, **kwargs)


def _resolve_websocket_user(websocket: WebSocket) -> User | None:
    override = websocket.app.dependency_overrides.get(get_current_user)
    if override is not None:
        return override()

    from backend_core.database import run_settings_db
    from modules.auth.service import ensure_default_user, validate_session

    token = resolve_websocket_session_token(websocket)

    def _lookup(session: Session) -> User | None:
        if token:
            return validate_session(session, token)

        if not auth_settings.auth_required:
            return ensure_default_user(session)
        return None

    return run_settings_db(_lookup)


def _get_durable_build_detail(session: Session, build_id: str) -> schemas.BuildRunDetail | None:
    build_run = build_run_service.get_build_run(session, build_id)
    if build_run is None or build_run.namespace != get_namespace():
        return None
    return build_run_service.fold_build_detail(session, build_run)


class _BuildNotActive(RuntimeError):
    pass


def _start_build_in_new_session(command: commands.StartBuildCommand) -> schemas.BuildRunDetail | None:
    """Commit and read a build using one session owned by one worker thread."""
    token = set_namespace_context(command.namespace)
    try:

        def _work(session: Session) -> schemas.BuildRunDetail | None:
            commands.start_build(session, command)
            detail = _get_durable_build_detail(session, command.build_id)
            return detail

        return run_db(_work)
    finally:
        reset_namespace(token)


def _cancel_build_in_new_session(
    *,
    namespace: str,
    build_id: str,
    cancelled_by: str,
    cancelled_at: datetime,
) -> tuple[schemas.BuildRunDetail, int, int]:
    """Cancel a build without sharing the request dependency session cross-thread."""
    token = set_namespace_context(namespace)
    try:

        def _work(session: Session) -> tuple[schemas.BuildRunDetail, int, int]:
            detail = _get_durable_build_detail(session, build_id)
            if detail is None:
                raise LookupError('Build not found')
            if detail.status not in {
                schemas.BuildLifecycleStatus.QUEUED,
                schemas.BuildLifecycleStatus.RUNNING,
            }:
                raise _BuildNotActive('Only active builds can be cancelled')

            duration_ms = detail.cancel_duration_ms(cancelled_at=cancelled_at)
            cancellation_event = detail.cancelled_event(
                cancelled_at=cancelled_at,
                cancelled_by=cancelled_by,
                duration_ms=duration_ms,
                emitted_at=_utcnow(),
            )
            event_row = commands.cancel_build(session, detail=detail, event=cancellation_event)
            if detail.starter.is_schedule_trigger():
                try:
                    scheduler_service.reconcile_schedule_run(session, build_id=build_id)
                except Exception:
                    logger.warning(
                        'Schedule reconciliation deferred after durable build cancellation build_id=%s',
                        build_id,
                        exc_info=True,
                    )
            # Read the primitive before run_db closes and expires the ORM row.
            return detail, event_row.sequence, duration_ms

        return run_db(_work)
    finally:
        reset_namespace(token)


def _list_durable_build_runs(session: Session, namespace: str) -> list[schemas.BuildRunSummary]:
    runs = build_run_service.list_build_runs(session)
    visible = [run for run in runs if run.namespace == namespace]
    return [
        build_run_service.build_summary(run)
        for run in visible
        if run.status
        in {
            build_run_service.BuildRunStatus.QUEUED,
            build_run_service.BuildRunStatus.RUNNING,
        }
    ]


def _build_snapshot_message(session: Session, build_id: str) -> schemas.BuildSnapshotMessage | None:
    detail = _get_durable_build_detail(session, build_id)
    if detail is None:
        return None
    return schemas.BuildSnapshotMessage(
        build=detail,
        last_sequence=build_run_service.get_latest_sequence(session, build_id),
    )


def _build_list_snapshot_message(session: Session, namespace: str) -> schemas.BuildListSnapshotMessage:
    return schemas.BuildListSnapshotMessage(builds=_list_durable_build_runs(session, namespace))


async def _replay_build_events(websocket: WebSocket, build_id: str, after_sequence: int) -> int | None:
    rows = await run_api_blocking(run_db, lambda session: build_run_service.list_build_events_after(session, build_id, after_sequence))
    latest = after_sequence
    for row in rows:
        # Protobuf/Pydantic conversion walks the event payload and can be
        # expensive for replayed build streams. Keep it on the bounded sync
        # lane so it cannot stall this API event loop.
        payload = await run_api_blocking(build_run_service.serialize_event_row, row)
        if not await safe_send_json(websocket, payload):
            return None
        latest = row.sequence
    return latest


async def _wait_for_build_notification(websocket: WebSocket, build_id: str, last_sequence: int = 0) -> BuildNotification | None:
    receive_task = asyncio.create_task(_wait_for_websocket_disconnect(websocket))
    notify_task = asyncio.create_task(build_hub.wait_for_build(build_id, last_sequence))
    done, pending = await asyncio.wait({receive_task, notify_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if receive_task in done:
        return None
    return await notify_task


async def _wait_for_namespace_build_update(websocket: WebSocket, namespace: str, last_seen: str | None) -> str | None:
    last_version = int(last_seen) if last_seen and last_seen.isdigit() else 0
    receive_task = asyncio.create_task(_wait_for_websocket_disconnect(websocket))
    notify_task = asyncio.create_task(build_hub.wait_for_namespace(namespace, last_version))
    done, pending = await asyncio.wait({receive_task, notify_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if receive_task in done:
        return None
    _ = await notify_task
    latest_version = build_hub.latest_namespace_sequence(namespace)
    if latest_version > last_version:
        return str(latest_version)
    return last_seen


def _get_durable_build_detail_by_engine_run(session: Session, engine_run_id: str) -> schemas.BuildRunDetail | None:
    build_run = build_run_service.get_build_run_by_engine_run(session, engine_run_id)
    if build_run is None or build_run.namespace != get_namespace():
        return None
    return build_run_service.fold_build_detail(session, build_run)


async def _require_websocket_user(websocket: WebSocket) -> User:
    user = await run_api_blocking(_resolve_websocket_user, websocket)
    if user is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return user


def _analysis_name(session: Session, analysis_id: str | None) -> str:
    if not analysis_id:
        return 'Build'
    analysis = session.get(Analysis, analysis_id)
    if analysis and analysis.name:
        return analysis.name
    return analysis_id


def _build_analysis_name(session: Session, pipeline: dict) -> str:
    analysis_id = pipeline.get('analysis_id')
    if not isinstance(analysis_id, str) or not analysis_id:
        return 'Build'
    return _analysis_name(session, analysis_id)


def _normalize_build_pipeline(request: schemas.BuildRequest) -> dict[str, object]:
    """Normalize a complete build payload outside the API event loop."""
    return normalize_pipeline_step_configs_for_protocol(request.pipeline_payload())


def _build_triggered_by(user: User | None) -> str:
    if user is None:
        return 'user'
    return user.id


async def _send_build_snapshot(websocket: WebSocket, build_id: str) -> None:
    message = await run_api_blocking(run_db, lambda session: _build_snapshot_message(session, build_id))
    if message is None:
        raise HTTPException(status_code=404, detail='Build not found')
    await safe_send_json(websocket, message)


async def _send_build_list_snapshot(websocket: WebSocket, namespace: str) -> None:
    message = await run_api_blocking(run_db, lambda session: _build_list_snapshot_message(session, namespace))
    await safe_send_json(websocket, message)


def _resolved_default_max_threads() -> int:
    """Default engine threads when an analysis does not set max_threads.

    POLARS_CORES_AVAILABLE is the platform budget (0 = all logical CPUs on host).
    """
    if settings.polars_cores_available > 0:
        return settings.polars_cores_available
    return os.cpu_count() or 1


def _resolved_system_memory_mb() -> int:
    try:
        pages = os.sysconf('SC_PHYS_PAGES')
        page_size = os.sysconf('SC_PAGE_SIZE')
    except AttributeError, OSError, ValueError:
        return 0
    if not isinstance(pages, int) or not isinstance(page_size, int):
        return 0
    total_bytes = pages * page_size
    if total_bytes <= 0:
        return 0
    return total_bytes // (1024 * 1024)


def _resolved_default_max_memory_mb() -> int:
    if settings.polars_max_memory_mb > 0:
        return settings.polars_max_memory_mb
    return _resolved_system_memory_mb()


async def _send_engine_snapshot(websocket: WebSocket) -> str:
    namespace = get_namespace()

    defaults: dict[str, object] = {
        'max_threads': settings.polars_cores_available,
        'max_memory_mb': settings.polars_max_memory_mb,
        'streaming_chunk_size': settings.polars_streaming_chunk_size,
    }

    version, serialized = await compute_worker_registry.load_serialized_snapshot(
        namespace,
        lambda: run_api_blocking(run_settings_db, lambda session: load_compute_worker_snapshot(session, namespace=namespace, defaults=defaults)),
    )
    await safe_send_serialized_json(websocket, serialized)
    return str(version)


async def _wait_for_engine_notification(websocket: WebSocket, namespace: str, last_seen: str | None) -> str | None:
    receive_task = asyncio.create_task(_wait_for_websocket_disconnect(websocket))
    notify_task = asyncio.create_task(compute_worker_registry.wait_for_namespace(namespace, last_seen))
    done, pending = await asyncio.wait({receive_task, notify_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if receive_task in done:
        return None
    return await notify_task


@router.post('/preview', response_model=None, mcp=True)
@handle_errors(operation='preview step')
async def preview_step(
    http_request: Request,
    request: schemas.StepPreviewRequest = Depends(_parse_preview_request),
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Preview the result of a pipeline step with pagination.

    Requires analysis_pipeline (full pipeline payload with tabs and steps) and target_step_id
    (the step to preview, or 'source' for raw data). Returns column names, types, data rows,
    and total row count. Use row_limit and page for pagination.
    """
    analysis_id = request.analysis_id
    if analysis_id is None and request.datasource_id is None:
        analysis_id = request.analysis_pipeline.analysis_id
    normalized = request.model_copy(update={'analysis_id': analysis_id})
    engine_identity = schemas.default_preview_engine_identity(normalized)
    manager = _override_manager(http_request)
    if manager is not None:
        executor = _override_compute_executor(http_request)
        if executor is None:
            raise RuntimeError('Missing compute override executor for manager override')

        response = await run_api_blocking(
            run_db,
            _run_compute_override,
            executor.preview_step,
            manager=manager,
            target_step_id=normalized.target_step_id,
            analysis_pipeline=await executor_client.model_payload(normalized.analysis_pipeline, mode='json'),
            row_limit=normalized.row_limit,
            page=normalized.page,
            analysis_id=analysis_id,
            engine_identity=engine_identity,
            resource_config=await executor_client.model_payload(normalized.resource_config) if normalized.resource_config else None,
            tab_id=normalized.tab_id,
            request_json=await executor_client.model_payload(normalized, mode='json'),
        )
        return await executor_client.json_response(response)
    response = await executor_client.preview_step(normalized, runtime_probe=runtime_probe, http_request=http_request)
    return await executor_client.json_response(response)


@router.post('/schema', response_model=None, mcp=True)
@handle_errors(operation='get step schema')
async def get_step_schema(
    http_request: Request,
    request: schemas.StepSchemaRequest = Depends(_parse_schema_request),
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Get the output column schema of a pipeline step without fetching data.

    Useful for configuring downstream steps that need to know available columns
    (e.g., pivot, unpivot, select). Returns column names and their Polars dtypes.
    """
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id
    normalized = request.model_copy(update={'analysis_id': analysis_id})
    manager = _override_manager(http_request)
    if manager is not None:
        executor = _override_compute_executor(http_request)
        if executor is None:
            raise RuntimeError('Missing compute override executor for manager override')

        response = await run_api_blocking(
            run_db,
            _run_compute_override,
            executor.get_step_schema,
            manager=manager,
            target_step_id=normalized.target_step_id,
            analysis_id=analysis_id,
            analysis_pipeline=await executor_client.model_payload(normalized.analysis_pipeline, mode='json'),
            tab_id=normalized.tab_id,
        )
        return await executor_client.json_response(response)
    response = await executor_client.get_step_schema(normalized, runtime_probe=runtime_probe, http_request=http_request)
    return await executor_client.json_response(response)


@router.post('/row-count', response_model=None, mcp=True)
@handle_errors(operation='get step row count')
async def get_step_row_count(
    http_request: Request,
    request: schemas.StepRowCountRequest = Depends(_parse_row_count_request),
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Get the row count of a pipeline step result without fetching data. Faster than a full preview."""
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id
    normalized = request.model_copy(update={'analysis_id': analysis_id})
    manager = _override_manager(http_request)
    if manager is not None:
        executor = _override_compute_executor(http_request)
        if executor is None:
            raise RuntimeError('Missing compute override executor for manager override')

        response = await run_api_blocking(
            run_db,
            _run_compute_override,
            executor.get_step_row_count,
            manager=manager,
            target_step_id=normalized.target_step_id,
            analysis_id=analysis_id,
            analysis_pipeline=await executor_client.model_payload(normalized.analysis_pipeline, mode='json'),
            tab_id=normalized.tab_id,
            request_json=await executor_client.model_payload(normalized, mode='json'),
        )
        return await executor_client.json_response(response)
    response = await executor_client.get_step_row_count(normalized, runtime_probe=runtime_probe, http_request=http_request)
    return await executor_client.json_response(response)


@router.get(
    '/iceberg/{datasource_id}/snapshots',
    response_model=schemas.IcebergSnapshotsResponse,
    mcp=True,
)
@handle_errors(operation='list iceberg snapshots')
async def list_iceberg_snapshots(
    datasource_id: DataSourceId,
    branch: str | None = None,
    build_results_only: bool = False,
):
    """List Iceberg table snapshots for time-travel selection.

    Each snapshot has a snapshot_id, timestamp, and operation type.
    Optionally filter by branch. Set build_results_only=true to return only
    snapshots produced by completed builds for this datasource.
    """
    return await run_api_blocking(
        run_db,
        list_iceberg_snapshots_info,
        parse_datasource_id(datasource_id),
        branch=branch,
        build_results_only=build_results_only,
    )


@router.delete(
    '/iceberg/{datasource_id}/snapshots/{snapshot_id}',
    response_model=schemas.IcebergSnapshotDeleteResponse,
    mcp=True,
)
@handle_errors(operation='delete iceberg snapshot')
async def delete_iceberg_snapshot(
    datasource_id: DataSourceId,
    snapshot_id: int,
):
    """Delete an Iceberg snapshot by ID. Use GET /compute/iceberg/{id}/snapshots to find snapshot IDs.

    Warning: deleting snapshots removes the ability to time-travel to that point.
    """
    return await run_api_blocking(
        run_db,
        delete_iceberg_snapshot_info,
        parse_datasource_id(datasource_id),
        str(snapshot_id),
    )


@router.post('/builds', response_model=schemas.BuildRunDetail)
@handle_errors(operation='start build')
async def start_build(
    request: schemas.BuildRequest = Depends(_parse_build_request),
    user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    # Build jobs are durable queue entries too. Do not turn a momentarily stale
    # worker heartbeat into a lost build; dispatch below will wake the manager
    # when it is available.
    del runtime_probe

    pipeline = await run_api_blocking(_normalize_build_pipeline, request)
    analysis_id = str(pipeline.get('analysis_id') or '')
    analysis_name = await run_api_blocking(run_db, _build_analysis_name, pipeline)
    namespace = get_namespace()
    started_at = _utcnow()
    build_id = str(uuid.uuid4())
    raw_tabs = pipeline.get('tabs')
    tabs = raw_tabs if isinstance(raw_tabs, list) else []
    selected_tab = next(
        (tab for tab in tabs if isinstance(tab, dict) and isinstance(tab.get('id'), str) and tab.get('id') == request.tab_id),
        None,
    )
    if not isinstance(selected_tab, dict):
        raise HTTPException(status_code=404, detail=f'Build request tab {request.tab_id} not found in analysis pipeline')
    active_tab = selected_tab
    current_kind = EngineRunKind.BUILD.value
    current_datasource_id: str | None = None
    current_tab_id: str | None = None
    current_tab_name: str | None = None
    current_output_id: str | None = None
    current_output_name: str | None = None
    data_plane = None
    if isinstance(active_tab, dict):
        datasource = active_tab.get('datasource')
        if isinstance(datasource, dict) and isinstance(datasource.get('id'), str):
            current_datasource_id = datasource.get('id')
        if isinstance(active_tab.get('id'), str):
            current_tab_id = active_tab.get('id')
        if isinstance(active_tab.get('name'), str):
            current_tab_name = active_tab.get('name')
    starter = schemas.BuildStarter.for_user(user)
    placeholders: list[commands.OutputPlaceholder] = []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        tab_id = tab.get('id')
        output = tab.get('output')
        if not isinstance(tab_id, str) or not isinstance(output, dict):
            continue
        result_id = output.get('result_id')
        if not isinstance(result_id, str):
            continue
        iceberg = output.get('iceberg')
        table_name = iceberg.get('table_name') if isinstance(iceberg, dict) else None
        filename = output.get('filename')
        output_name = table_name if isinstance(table_name, str) and table_name.strip() else filename
        branch_name = iceberg.get('branch') if isinstance(iceberg, dict) else None
        namespace_name = iceberg.get('namespace') if isinstance(iceberg, dict) else None
        placeholder_config: dict[str, object] | None = None
        placeholder_source_type = datasource_service.DataSourceType.ANALYSIS
        if isinstance(branch_name, str) and branch_name.strip():
            safe_branch = re.sub(r'[^a-zA-Z0-9_]+', '_', branch_name).strip('_')
            table_name = f'{result_id}_{safe_branch}'
            namespace = get_namespace()
            if data_plane is None:
                data_plane = await run_api_blocking(client_from_settings)
            warehouse_path = await run_api_blocking(data_plane.build_object_url, 'exports', namespace=namespace)
            placeholder_source_type = datasource_service.DataSourceType.ICEBERG
            placeholder_config = {
                'catalog_type': 'sql',
                'warehouse': warehouse_path,
                'namespace': namespace_name if isinstance(namespace_name, str) and namespace_name.strip() else 'outputs',
                'table': table_name,
                'table_name': output_name if isinstance(output_name, str) and output_name.strip() else table_name,
                'metadata_path': await run_api_blocking(data_plane.build_object_url, 'exports', str(result_id), namespace=namespace),
                'branch': branch_name,
                'namespace_name': namespace,
                'reader': 'native',
            }
        placeholders.append(
            commands.OutputPlaceholder(
                result_id=result_id,
                tab_id=tab_id,
                name=output_name if isinstance(output_name, str) else None,
                source_type=placeholder_source_type,
                config=placeholder_config,
            )
        )
    command = commands.StartBuildCommand(
        build_id=build_id,
        namespace=namespace,
        analysis_id=analysis_id,
        analysis_name=analysis_name,
        request_json={'analysis_pipeline': {'analysis_id': pipeline['analysis_id'], 'tabs': pipeline['tabs']}, 'tab_id': request.tab_id},
        starter_json=await executor_client.model_payload(starter, mode='json'),
        current_kind=current_kind,
        current_datasource_id=current_datasource_id,
        current_tab_id=current_tab_id,
        current_tab_name=current_tab_name,
        current_output_id=current_output_id,
        current_output_name=current_output_name,
        total_tabs=1,
        started_at=started_at,
        placeholders=placeholders,
    )
    detail = await run_api_blocking(_start_build_in_new_session, command)
    if detail is None:
        raise HTTPException(status_code=500, detail='Failed to create build')
    try:
        # The durable outbox is the recovery path. This committed wake keeps a
        # new build out of the namespace recovery cursor when the coordinator
        # is already draining another tenant.
        await run_api_blocking(runtime_ipc.notify_build_job, namespace)
    except Exception:
        logger.warning('Direct build wake failed build_id=%s; durable outbox will recover it', build_id, exc_info=True)
    await build_hub.publish(BuildNotification(namespace=namespace, build_id=build_id, latest_sequence=0))
    from backend_core.domain.build_jobs.live import hub as build_job_hub

    build_job_hub.publish()
    return detail


@router.post('/builds/{build_id}/cancel', response_model=schemas.CancelBuildResponse, mcp=True)
@handle_errors(operation='cancel build')
async def cancel_build(
    build_id: str,
    user: User = Depends(get_current_user),
):
    cancelled_by = user.email or user.display_name or user.id
    cancelled_at = _utcnow()
    try:
        detail, event_sequence, duration_ms = await run_api_blocking(
            _cancel_build_in_new_session,
            namespace=get_namespace(),
            build_id=build_id,
            cancelled_by=cancelled_by,
            cancelled_at=cancelled_at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except _BuildNotActive as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except commands.BuildCancellationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await build_event_service.publish_build_notification(detail.namespace, detail.build_id, latest_sequence=event_sequence)

    return schemas.CancelBuildResponse(
        id=detail.build_id,
        build_id=detail.build_id,
        engine_run_id=detail.current_engine_run_id,
        status='cancelled',
        duration_ms=duration_ms,
        cancelled_at=cancelled_at,
        cancelled_by=cancelled_by,
    )


@router.get('/builds', response_model=schemas.BuildRunListResponse, mcp=True)
@handle_errors(operation='list builds')
async def list_builds(
    request: Request,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: schemas.BuildLifecycleStatus | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _user: User = Depends(get_current_user),
):
    del request
    namespace = get_namespace()
    fetch_limit = limit + offset

    def _list(session: Session) -> schemas.BuildRunListResponse:
        normalized_analysis_id = analysis_id.strip() if analysis_id else None
        normalized_datasource_id = parse_datasource_id(datasource_id) if datasource_id else None
        runs = build_run_service.list_build_runs(
            session,
            analysis_id=normalized_analysis_id,
            datasource_id=normalized_datasource_id,
            kind=kind,
            status=status,
            search=search,
            limit=fetch_limit,
            offset=0,
        )
        build_rows = [build_run_service.build_summary(run) for run in runs if run.namespace == namespace]
        engine_rows: list[schemas.BuildRunSummary] = []
        if status != schemas.BuildLifecycleStatus.QUEUED:
            engine_runs = engine_run_service.list_engine_runs(
                session,
                analysis_id=normalized_analysis_id,
                datasource_id=normalized_datasource_id,
                kind=representations.engine_run_kind_filter(kind),
                status=representations.engine_run_status_filter(status),
                search=search,
                limit=fetch_limit,
                offset=0,
            )
            engine_rows = [representations.engine_run_summary(run, namespace=namespace) for run in engine_runs]
        visible = sorted([*build_rows, *engine_rows], key=lambda run: run.started_at, reverse=True)
        return schemas.BuildRunListResponse(builds=visible[offset : offset + limit], total=len(visible))

    return await run_api_blocking(run_db, _list)


@router.get('/builds/{build_id}', response_model=schemas.BuildRunDetail, mcp=True)
@handle_errors(operation='get build')
async def get_build(
    build_id: str,
    _user: User = Depends(get_current_user),
):
    namespace = get_namespace()

    def _get(session: Session) -> schemas.BuildRunDetail:
        detail = _get_durable_build_detail(session, build_id)
        if detail is not None:
            return detail
        engine_run = engine_run_service.get_engine_run(session, build_id)
        if engine_run is not None:
            return representations.engine_run_detail(engine_run, namespace=namespace)
        raise HTTPException(status_code=404, detail='Build not found')

    return await run_api_blocking(run_db, _get)


# Engine lifecycle endpoints


async def _spawn_engine_identity(
    identity,
    http_request: Request,
    request: schemas.SpawnEngineRequest | None,
    runtime_probe: RuntimeAvailabilityProbe,
):
    resource_config = await executor_client.model_payload(request.resource_config) if request and request.resource_config else None
    manager = _override_manager(http_request)
    if manager is not None:

        def spawn_and_read_status():
            manager.spawn_compute_worker(identity, resource_config=resource_config)
            return manager.get_engine_status(identity)

        return await run_api_blocking(spawn_and_read_status)
    return await executor_client.spawn_compute_worker(
        identity=identity,
        resource_config=resource_config,
        runtime_probe=runtime_probe,
    )


async def _configure_engine_identity(
    identity,
    request: schemas.EngineResourceConfig,
    http_request: Request,
    runtime_probe: RuntimeAvailabilityProbe,
):
    resource_config = await executor_client.model_payload(request)
    manager = _override_manager(http_request)
    if manager is not None:

        def configure_and_read_status():
            manager.restart_engine_with_config(identity, resource_config)
            return manager.get_engine_status(identity)

        return await run_api_blocking(configure_and_read_status)
    return await executor_client.configure_engine(
        identity=identity,
        resource_config=resource_config,
        runtime_probe=runtime_probe,
    )


async def _shutdown_engine_identity(
    identity,
    http_request: Request,
    runtime_probe: RuntimeAvailabilityProbe,
) -> None:
    """Queue engine shutdown after cancelling any active job.

    The in-process override manager may perform synchronous container work, so
    keep it off the ASGI event loop too. The production worker path queues a
    durable shutdown command and returns without waiting for container teardown.
    """
    manager = _override_manager(http_request)
    if manager is not None:

        def shutdown_override_engine() -> None:
            engine = manager.get_engine(identity)
            if not engine:
                raise engine_not_found(identity.resource_id)
            # Cancel the active job before tearing down so shutdown never blocks on
            # "busy". Container/process shutdown is the hard cancel for jobs.
            if engine.current_job_id and engine.is_process_alive():
                cancel = getattr(engine, 'cancel_current_job', None)
                if callable(cancel):
                    cancel()
                else:
                    # Stub / lightweight engines: clear the job marker so shutdown
                    # is allowed. Production Docker engines cancel via container stop.
                    engine.current_job_id = None
            manager.shutdown_engine(identity)

        await run_api_blocking(shutdown_override_engine)
        return
    await run_api_blocking(
        run_db,
        executor_client.request_engine_shutdown,
        identity=identity,
        runtime_probe=runtime_probe,
    )


@router.post('/engine/spawn/analysis/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='spawn analysis engine')
async def spawn_analysis_engine(
    analysis_id: AnalysisId,
    http_request: Request,
    request: schemas.SpawnEngineRequest | None = None,
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    return await _spawn_engine_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            analysis_id=analysis_id,
            resource_id=analysis_id,
        ),
        http_request,
        request,
        runtime_probe,
    )


@router.post('/engine/spawn/datasource-preview/{datasource_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='spawn datasource preview engine')
async def spawn_datasource_preview_engine(
    datasource_id: DataSourceId,
    http_request: Request,
    request: schemas.SpawnEngineRequest | None = None,
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    datasource_id_value = parse_datasource_id(datasource_id)
    return await _spawn_engine_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            datasource_id=datasource_id_value,
            resource_id=datasource_id_value,
        ),
        http_request,
        request,
        runtime_probe,
    )


@router.post('/engine/configure/analysis/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='configure analysis engine')
async def configure_analysis_engine(
    analysis_id: AnalysisId,
    request: schemas.EngineResourceConfig,
    http_request: Request,
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    return await _configure_engine_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            analysis_id=analysis_id,
            resource_id=analysis_id,
        ),
        request,
        http_request,
        runtime_probe,
    )


@router.post('/engine/configure/datasource-preview/{datasource_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='configure datasource preview engine')
async def configure_datasource_preview_engine(
    datasource_id: DataSourceId,
    request: schemas.EngineResourceConfig,
    http_request: Request,
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    datasource_id_value = parse_datasource_id(datasource_id)
    return await _configure_engine_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            datasource_id=datasource_id_value,
            resource_id=datasource_id_value,
        ),
        request,
        http_request,
        runtime_probe,
    )


@router.delete('/engine/analysis/{analysis_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown analysis engine')
async def shutdown_analysis_engine(
    analysis_id: AnalysisId,
    http_request: Request,
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    await _shutdown_engine_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            analysis_id=analysis_id,
            resource_id=analysis_id,
        ),
        http_request,
        runtime_probe,
    )


@router.delete('/engine/datasource-preview/{datasource_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown datasource preview engine')
async def shutdown_datasource_preview_engine(
    datasource_id: DataSourceId,
    http_request: Request,
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    datasource_id_value = parse_datasource_id(datasource_id)
    await _shutdown_engine_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            datasource_id=datasource_id_value,
            resource_id=datasource_id_value,
        ),
        http_request,
        runtime_probe,
    )


@router.delete('/engine/build/{build_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown build engine')
async def shutdown_build_engine(
    build_id: str,
    http_request: Request,
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    await _shutdown_engine_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
            build_id=build_id,
            resource_id=build_id,
        ),
        http_request,
        runtime_probe,
    )


@router.websocket('/ws/engines')
async def engine_list_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    subscribed = False
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        await compute_worker_registry.subscribe(namespace)
        subscribed = True
        last_seen = await _send_engine_snapshot(websocket)
        while True:
            updated = await _wait_for_engine_notification(websocket, namespace, last_seen)
            if updated is None:
                return
            last_seen = await _send_engine_snapshot(websocket)
            # One snapshot is authoritative for all intermediate lifecycle
            # notifications. A burst of starts/stops should not make every
            # browser socket issue one database read per version.
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError, concurrent.futures.CancelledError:
        return
    except HTTPException as exc:
        await safe_send_json_error(
            websocket,
            schemas.EngineWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code),
        )
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        logger.error('Engine websocket error: %s', exc, exc_info=True)
        await safe_send_json_error(
            websocket,
            schemas.EngineWebsocketErrorMessage(error='An internal error occurred'),
        )
    except Exception as exc:
        logger.error('Engine websocket error: %s', exc, exc_info=True)
        await safe_send_json_error(
            websocket,
            schemas.EngineWebsocketErrorMessage(error='An internal error occurred'),
        )
    finally:
        if subscribed:
            with anyio.CancelScope(shield=True):
                await compute_worker_registry.unsubscribe(namespace)
        reset_namespace(token)
        await safe_close_websocket(websocket)


@router.websocket('/ws/builds')
async def build_list_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    subscribed = False
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        last_seen = str(build_hub.subscribe_namespace(namespace))
        subscribed = True
        await _send_build_list_snapshot(websocket, namespace)
        while True:
            updated = await _wait_for_namespace_build_update(websocket, namespace, last_seen)
            if updated is None:
                return

            payload = await run_api_blocking(run_db, lambda session: _build_list_snapshot_message(session, namespace).model_dump(mode='json'))
            sent = await safe_send_json(websocket, payload)
            if not sent:
                return
            last_seen = updated
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError, concurrent.futures.CancelledError:
        return
    except HTTPException as exc:
        await safe_send_json_error(
            websocket,
            schemas.BuildWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code),
        )
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        logger.error('Build list websocket error: %s', exc, exc_info=True)
        await safe_send_json_error(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred'),
        )
    except Exception as exc:
        logger.error('Build list websocket error: %s', exc, exc_info=True)
        await safe_send_json_error(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred'),
        )
    finally:
        if subscribed:
            build_hub.unsubscribe_namespace(namespace)
        reset_namespace(token)
        await safe_close_websocket(websocket)


@router.websocket('/ws/builds/{build_id}')
async def build_stream(websocket: WebSocket, build_id: str) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    subscribed = False
    raw_last_sequence = websocket.query_params.get('last_sequence')
    last_sequence = int(raw_last_sequence) if raw_last_sequence and raw_last_sequence.isdigit() else 0
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        build_hub.subscribe_build(namespace, build_id)
        subscribed = True
        while True:
            message = await run_api_blocking(
                run_db,
                lambda session: _build_snapshot_message(session, build_id),
            )
            if message is None or message.build.namespace != get_namespace():
                raise HTTPException(status_code=404, detail='Build not found')
            if message.last_sequence <= last_sequence:
                break
            if last_sequence > 0:
                replayed_sequence = await _replay_build_events(websocket, build_id, last_sequence)
                if replayed_sequence is None:
                    return
                last_sequence = replayed_sequence
                continue
            break
        sent = await safe_send_json(websocket, message)
        if not sent:
            return
        last_sequence = max(last_sequence, message.last_sequence)
        while True:
            notification = await _wait_for_build_notification(websocket, build_id, last_sequence)
            if notification is None:
                return
            replayed_sequence = await _replay_build_events(websocket, build_id, last_sequence)
            if replayed_sequence is None:
                return
            last_sequence = max(replayed_sequence, notification.latest_sequence)
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError, concurrent.futures.CancelledError:
        return
    except HTTPException as exc:
        await safe_send_json_error(
            websocket,
            schemas.BuildWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code),
        )
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        logger.error('Active build websocket error: %s', exc, exc_info=True)
        await safe_send_json_error(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred'),
        )
    except Exception as exc:
        logger.error('Active build websocket error: %s', exc, exc_info=True)
        await safe_send_json_error(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred'),
        )
    finally:
        if subscribed:
            build_hub.unsubscribe_build(namespace, build_id)
        reset_namespace(token)
        await safe_close_websocket(websocket)


@router.get('/defaults', response_model=schemas.EngineDefaults, mcp=True)
@handle_errors(operation='get engine defaults')
async def get_engine_defaults():
    """Get resolved default engine resource settings for the UI."""
    return schemas.EngineDefaults(
        max_threads=_resolved_default_max_threads(),
        max_memory_mb=_resolved_default_max_memory_mb(),
        streaming_chunk_size=settings.polars_streaming_chunk_size,
    )


@router.post('/export', mcp=True)
@handle_errors(operation='export data')
async def export_data(
    http_request: Request,
    request: schemas.ExportRequest = Depends(_parse_export_request),
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Export pipeline results to a file download or output datasource.

    For destination='download': returns file bytes in the requested format (csv, parquet, json, etc.).
    For destination='datasource': writes to an Iceberg output datasource (requires result_id and iceberg_options).
    """
    if request.destination == schemas.ExportDestination.DOWNLOAD:
        download_request = schemas.DownloadRequest(
            analysis_id=request.analysis_id,
            target_step_id=request.target_step_id,
            analysis_pipeline=request.analysis_pipeline,
            tab_id=request.tab_id,
            format=request.format,
            filename=request.filename,
        )
        manager = _override_manager(http_request)
        if manager is not None:
            executor = _override_compute_executor(http_request)
            if executor is None:
                raise RuntimeError('Missing compute override executor for manager override')

            file_bytes, filename, content_type = await run_api_blocking(
                run_db,
                _run_compute_override,
                executor.download_step,
                manager=manager,
                target_step_id=download_request.target_step_id,
                analysis_pipeline=await executor_client.model_payload(download_request.analysis_pipeline, mode='json'),
                export_format=download_request.format.value,
                filename=download_request.filename,
                analysis_id=download_request.analysis_id,
                tab_id=download_request.tab_id,
            )
        else:
            file_bytes, filename, content_type = await executor_client.download_step(
                download_request,
                runtime_probe=runtime_probe,
            )
        safe_name = quote(filename)
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={'Content-Disposition': f'attachment; filename="{safe_name}"'},
        )

    manager = _override_manager(http_request)
    if manager is not None:
        executor = _override_compute_executor(http_request)
        if executor is None:
            raise RuntimeError('Missing compute override executor for manager override')

        result = await run_api_blocking(
            run_db,
            _run_compute_override,
            executor.export_data,
            manager=manager,
            target_step_id=request.target_step_id,
            analysis_pipeline=await executor_client.model_payload(request.analysis_pipeline, mode='json'),
            filename=request.filename,
            iceberg_options=await executor_client.model_payload(request.iceberg_options) if request.iceberg_options else None,
            analysis_id=request.analysis_id,
            tab_id=request.tab_id,
            request_json=await executor_client.model_payload(request, mode='json'),
            result_id=request.result_id,
        )
        return schemas.ExportResponse(
            success=True,
            filename=result.datasource_name,
            format='iceberg',
            destination=request.destination.value,
            message=f'Created datasource {result.datasource_name}',
            datasource_id=result.datasource_id,
            datasource_name=result.result_meta.get('datasource_name') if isinstance(result.result_meta, dict) else None,
        )
    response = await executor_client.export_data(request, runtime_probe=runtime_probe)
    return await executor_client.json_response(response)


@router.post('/download', mcp=True)
@handle_errors(operation='download step')
async def download_step(
    http_request: Request,
    request: schemas.DownloadRequest = Depends(_parse_download_request),
    _user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Download pipeline step result as a file.

    Returns the file bytes with appropriate Content-Type header.
    Supported formats: csv, parquet, json, ndjson, duckdb, excel.
    """
    manager = _override_manager(http_request)
    if manager is not None:
        executor = _override_compute_executor(http_request)
        if executor is None:
            raise RuntimeError('Missing compute override executor for manager override')

        file_bytes, filename, content_type = await run_api_blocking(
            run_db,
            _run_compute_override,
            executor.download_step,
            manager=manager,
            target_step_id=request.target_step_id,
            analysis_pipeline=await executor_client.model_payload(request.analysis_pipeline, mode='json'),
            export_format=request.format.value,
            filename=request.filename,
            analysis_id=request.analysis_id,
            tab_id=request.tab_id,
        )
    else:
        file_bytes, filename, content_type = await executor_client.download_step(
            request,
            runtime_probe=runtime_probe,
        )

    if file_bytes is None or filename is None or content_type is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail='Download file content not available')

    safe_name = quote(filename)
    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={'Content-Disposition': f'attachment; filename="{safe_name}"'},
    )
