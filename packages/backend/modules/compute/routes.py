import asyncio
import concurrent.futures
import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Any
from urllib.parse import quote

import anyio
from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from backend_core import (
    build_runs_service as build_run_service,
    compute_worker_runs_service as compute_worker_run_service,
    runtime_ipc,
)
from backend_core.api_execution_budget import run_api_blocking
from backend_core.auth_config import settings as auth_settings
from backend_core.compute_worker_live import load_compute_worker_snapshot, registry as compute_worker_registry
from backend_core.config import settings
from backend_core.data_plane_client import client_from_settings
from backend_core.database import run_db, run_settings_db
from backend_core.domain.build_runs.live import BuildNotification, hub as build_hub
from backend_core.domain.compute import schemas
from backend_core.domain.compute_worker_runs.schemas import ComputeWorkerRunKind
from backend_core.error_handlers import handle_errors
from backend_core.namespace import get_namespace, namespace_scope, reset_namespace, set_namespace_context
from backend_core.persistence.analysis.models import Analysis
from backend_core.time import utc_now as _utcnow
from backend_core.validation import (
    AnalysisId,
    DataSourceId,
    parse_datasource_id,
)
from backend_core.websocket import (
    is_disconnect_runtime_error,
    safe_close_websocket,
    safe_send_json,
    safe_send_json_error,
    safe_send_serialized_json,
    websocket_disconnected,
)
from dataforge_protocol import compute_pb2, enums_pb2
from modules.auth.dependencies import get_current_user, resolve_session_token
from modules.auth.models import User
from modules.compute import commands, executor_client, iceberg_service, representations
from modules.datasource import service as datasource_service
from modules.mcp.router import MCPRouter
from modules.scheduler import service as scheduler_service

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/compute', tags=['compute'], dependencies=[Depends(get_current_user)])


def _json_body[T: BaseModel](model_type: type[T]) -> Callable[[Request], Awaitable[T]]:
    async def parse(request: Request) -> T:
        return await executor_client.parse_request_model(request, model_type)

    return parse


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


def _resolve_websocket_user(websocket: WebSocket) -> User | None:
    override = websocket.app.dependency_overrides.get(get_current_user)
    if override is not None:
        return override()

    from modules.auth.service import get_or_seed_default_user, validate_session

    token = resolve_session_token(websocket)

    def _lookup(session: Session) -> User | None:
        if token:
            return validate_session(session, token)

        if not auth_settings.auth_required:
            return get_or_seed_default_user(session)
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
    with namespace_scope(command.namespace):

        def _work(session: Session) -> schemas.BuildRunDetail | None:
            commands.start_build(session, command)
            return _get_durable_build_detail(session, command.build_id)

        return run_db(_work)


def _cancel_build_in_new_session(
    *,
    namespace: str,
    build_id: str,
    cancelled_by: str,
    cancelled_at: datetime,
) -> tuple[schemas.BuildRunDetail, int, int]:
    """Cancel a build without sharing the request dependency session cross-thread."""
    with namespace_scope(namespace):

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


def _build_snapshot_message(session: Session, build_id: str) -> schemas.BuildSnapshotMessage | None:
    detail = _get_durable_build_detail(session, build_id)
    if detail is None:
        return None
    return schemas.BuildSnapshotMessage(
        build=detail,
        last_sequence=build_run_service.get_latest_sequence(session, build_id),
    )


def _build_list_snapshot_message(session: Session, namespace: str) -> schemas.BuildListSnapshotMessage:
    active = {build_run_service.BuildRunStatus.QUEUED, build_run_service.BuildRunStatus.RUNNING}
    runs = build_run_service.list_build_runs(session)
    return schemas.BuildListSnapshotMessage(
        builds=[build_run_service.build_summary(run) for run in runs if run.namespace == namespace and run.status in active]
    )


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


async def _wait_unless_disconnected[T](websocket: WebSocket, notification: Coroutine[Any, Any, T]) -> T | None:
    """Await a live notification, or return None once the client disconnects."""
    receive_task = asyncio.create_task(_wait_for_websocket_disconnect(websocket))
    notify_task = asyncio.create_task(notification)
    done, pending = await asyncio.wait({receive_task, notify_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if receive_task in done:
        return None
    return await notify_task


async def _require_websocket_user(websocket: WebSocket) -> User:
    user = await run_api_blocking(_resolve_websocket_user, websocket)
    if user is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return user


def _analysis_name(session: Session, analysis_id: str) -> str:
    analysis = session.get(Analysis, analysis_id)
    return analysis.name if analysis and analysis.name else analysis_id


async def _send_build_list_snapshot(websocket: WebSocket, namespace: str) -> None:
    message = await run_api_blocking(run_db, lambda session: _build_list_snapshot_message(session, namespace))
    await safe_send_json(websocket, message)


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


async def _send_compute_worker_snapshot(websocket: WebSocket) -> str:
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


@router.post('/preview', response_model=None, mcp=True)
@handle_errors(operation='preview step')
async def preview_step(
    http_request: Request,
    request: schemas.StepPreviewRequest = Depends(_json_body(schemas.StepPreviewRequest)),
    _user: User = Depends(get_current_user),
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
    response = await executor_client.preview_step(normalized, http_request=http_request)
    return await executor_client.json_response(response)


@router.post('/schema', response_model=None, mcp=True)
@handle_errors(operation='get step schema')
async def get_step_schema(
    http_request: Request,
    request: schemas.StepSchemaRequest = Depends(_json_body(schemas.StepSchemaRequest)),
    _user: User = Depends(get_current_user),
):
    """Get the output column schema of a pipeline step without fetching data.

    Useful for configuring downstream steps that need to know available columns
    (e.g., pivot, unpivot, select). Returns column names and their Polars dtypes.
    """
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id
    normalized = request.model_copy(update={'analysis_id': analysis_id})
    response = await executor_client.get_step_schema(normalized, http_request=http_request)
    return await executor_client.json_response(response)


@router.post('/row-count', response_model=None, mcp=True)
@handle_errors(operation='get step row count')
async def get_step_row_count(
    http_request: Request,
    request: schemas.StepRowCountRequest = Depends(_json_body(schemas.StepRowCountRequest)),
    _user: User = Depends(get_current_user),
):
    """Get the row count of a pipeline step result without fetching data. Faster than a full preview."""
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id
    normalized = request.model_copy(update={'analysis_id': analysis_id})
    response = await executor_client.get_step_row_count(normalized, http_request=http_request)
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
        iceberg_service.list_iceberg_snapshots,
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
    return await run_api_blocking(run_db, iceberg_service.delete_iceberg_snapshot, parse_datasource_id(datasource_id), snapshot_id)


@router.post('/builds', response_model=schemas.BuildRunDetail)
@handle_errors(operation='start build')
async def start_build(
    request: schemas.BuildRequest = Depends(_json_body(schemas.BuildRequest)),
    user: User = Depends(get_current_user),
):
    # Build jobs are durable queue entries too. Do not turn a momentarily stale
    # worker heartbeat into a lost build; dispatch below will wake the manager
    # when it is available.
    # Normalizing the complete build payload is CPU work; keep it off the API event loop.
    request_json = await run_api_blocking(scheduler_service.build_request_json, request)
    analysis_id = request.analysis_pipeline.analysis_id
    analysis_name = await run_api_blocking(run_db, _analysis_name, analysis_id)
    namespace = get_namespace()
    started_at = _utcnow()
    build_id = str(uuid.uuid4())
    selected_tab = next((tab for tab in request.analysis_pipeline.tabs if tab.id == request.tab_id), None)
    if selected_tab is None:
        raise HTTPException(status_code=404, detail=f'Build request tab {request.tab_id} not found in analysis pipeline')
    data_plane = None
    placeholders: list[commands.OutputPlaceholder] = []
    for tab in request.analysis_pipeline.tabs:
        output = tab.output
        result_id = output['result_id']
        iceberg = output.get('iceberg')
        table_name = iceberg.get('table_name') if isinstance(iceberg, dict) else None
        output_name = table_name if isinstance(table_name, str) and table_name.strip() else output['filename']
        branch_name = iceberg.get('branch') if isinstance(iceberg, dict) else None
        namespace_name = iceberg.get('namespace') if isinstance(iceberg, dict) else None
        placeholder_config: dict[str, object] | None = None
        placeholder_source_type = datasource_service.DataSourceType.ANALYSIS
        if isinstance(branch_name, str) and branch_name.strip():
            safe_branch = re.sub(r'[^a-zA-Z0-9_]+', '_', branch_name).strip('_')
            table_name = f'{result_id}_{safe_branch}'
            if data_plane is None:
                data_plane = await run_api_blocking(client_from_settings)
            warehouse_path = await run_api_blocking(data_plane.build_object_url, 'exports', namespace=namespace)
            placeholder_source_type = datasource_service.DataSourceType.ICEBERG
            placeholder_config = {
                'catalog_type': 'sql',
                'warehouse': warehouse_path,
                'namespace': namespace_name if isinstance(namespace_name, str) and namespace_name.strip() else 'outputs',
                'table': table_name,
                'table_name': output_name,
                'metadata_path': await run_api_blocking(data_plane.build_object_url, 'exports', str(result_id), namespace=namespace),
                'branch': branch_name,
                'namespace_name': namespace,
                'reader': 'native',
            }
        placeholders.append(
            commands.OutputPlaceholder(
                result_id=result_id,
                tab_id=tab.id,
                name=output_name,
                source_type=placeholder_source_type,
                config=placeholder_config,
            )
        )
    command = commands.StartBuildCommand(
        build_id=build_id,
        namespace=namespace,
        analysis_id=analysis_id,
        analysis_name=analysis_name,
        request_json=request_json,
        starter_json=await executor_client.model_payload(schemas.BuildStarter.for_user(user), mode='json'),
        current_kind=ComputeWorkerRunKind.BUILD.value,
        current_datasource_id=selected_tab.datasource.id,
        current_tab_id=request.tab_id,
        current_tab_name=selected_tab.name,
        current_output_id=None,
        current_output_name=None,
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

    await build_hub.publish(BuildNotification(namespace=detail.namespace, build_id=detail.build_id, latest_sequence=event_sequence))

    return schemas.CancelBuildResponse(
        id=detail.build_id,
        build_id=detail.build_id,
        compute_worker_run_id=detail.current_compute_worker_run_id,
        status='cancelled',
        duration_ms=duration_ms,
        cancelled_at=cancelled_at,
        cancelled_by=cancelled_by,
    )


@router.get('/builds', response_model=schemas.BuildRunListResponse, mcp=True)
@handle_errors(operation='list builds')
async def list_builds(
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: schemas.BuildLifecycleStatus | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _user: User = Depends(get_current_user),
):
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
            compute_worker_runs = compute_worker_run_service.list_compute_worker_runs(
                session,
                analysis_id=normalized_analysis_id,
                datasource_id=normalized_datasource_id,
                kind=representations.compute_worker_run_kind_filter(kind),
                status=representations.compute_worker_run_status_filter(status),
                search=search,
                limit=fetch_limit,
                offset=0,
            )
            engine_rows = [representations.compute_worker_run_summary(run, namespace=namespace) for run in compute_worker_runs]
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
        compute_worker_run = compute_worker_run_service.get_compute_worker_run(session, build_id)
        if compute_worker_run is not None:
            return representations.compute_worker_run_detail(compute_worker_run, namespace=namespace)
        raise HTTPException(status_code=404, detail='Build not found')

    return await run_api_blocking(run_db, _get)


# Engine lifecycle endpoints


def _analysis_identity(analysis_id: str) -> compute_pb2.ComputeWorkerIdentity:
    return compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        analysis_id=analysis_id,
        resource_id=analysis_id,
    )


def _datasource_preview_identity(datasource_id: DataSourceId) -> compute_pb2.ComputeWorkerIdentity:
    datasource_id_value = parse_datasource_id(datasource_id)
    return compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        datasource_id=datasource_id_value,
        resource_id=datasource_id_value,
    )


async def _spawn_compute_worker_identity(
    identity: compute_pb2.ComputeWorkerIdentity,
    request: schemas.SpawnComputeWorkerRequest | None,
):
    resource_config = await executor_client.model_payload(request.resource_config) if request and request.resource_config else None
    return await executor_client.spawn_compute_worker(identity=identity, resource_config=resource_config)


async def _configure_compute_worker_identity(
    identity: compute_pb2.ComputeWorkerIdentity,
    request: schemas.ComputeWorkerResourceConfig,
):
    resource_config = await executor_client.model_payload(request)
    return await executor_client.configure_compute_worker(identity=identity, resource_config=resource_config)


async def _shutdown_compute_worker_identity(identity: compute_pb2.ComputeWorkerIdentity) -> None:
    await run_api_blocking(run_db, executor_client.request_compute_worker_shutdown, identity=identity)


@router.post('/compute-worker/spawn/analysis/{analysis_id}', response_model=schemas.ComputeWorkerStatusSchema, mcp=True)
@handle_errors(operation='spawn analysis compute worker')
async def spawn_analysis_compute_worker(
    analysis_id: AnalysisId,
    request: schemas.SpawnComputeWorkerRequest | None = None,
    _user: User = Depends(get_current_user),
):
    return await _spawn_compute_worker_identity(_analysis_identity(analysis_id), request)


@router.post('/compute-worker/spawn/datasource-preview/{datasource_id}', response_model=schemas.ComputeWorkerStatusSchema, mcp=True)
@handle_errors(operation='spawn datasource preview compute worker')
async def spawn_datasource_preview_compute_worker(
    datasource_id: DataSourceId,
    request: schemas.SpawnComputeWorkerRequest | None = None,
    _user: User = Depends(get_current_user),
):
    return await _spawn_compute_worker_identity(_datasource_preview_identity(datasource_id), request)


@router.post('/compute-worker/configure/analysis/{analysis_id}', response_model=schemas.ComputeWorkerStatusSchema, mcp=True)
@handle_errors(operation='configure analysis compute worker')
async def configure_analysis_compute_worker(
    analysis_id: AnalysisId,
    request: schemas.ComputeWorkerResourceConfig,
    _user: User = Depends(get_current_user),
):
    return await _configure_compute_worker_identity(_analysis_identity(analysis_id), request)


@router.post('/compute-worker/configure/datasource-preview/{datasource_id}', response_model=schemas.ComputeWorkerStatusSchema, mcp=True)
@handle_errors(operation='configure datasource preview compute worker')
async def configure_datasource_preview_compute_worker(
    datasource_id: DataSourceId,
    request: schemas.ComputeWorkerResourceConfig,
    _user: User = Depends(get_current_user),
):
    return await _configure_compute_worker_identity(_datasource_preview_identity(datasource_id), request)


@router.delete('/compute-worker/analysis/{analysis_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown analysis compute worker')
async def shutdown_analysis_compute_worker(
    analysis_id: AnalysisId,
    _user: User = Depends(get_current_user),
):
    await _shutdown_compute_worker_identity(_analysis_identity(analysis_id))


@router.delete('/compute-worker/datasource-preview/{datasource_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown datasource preview compute worker')
async def shutdown_datasource_preview_compute_worker(
    datasource_id: DataSourceId,
    _user: User = Depends(get_current_user),
):
    await _shutdown_compute_worker_identity(_datasource_preview_identity(datasource_id))


@router.delete('/compute-worker/build/{build_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown build compute worker')
async def shutdown_build_compute_worker(
    build_id: str,
    _user: User = Depends(get_current_user),
):
    await _shutdown_compute_worker_identity(
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
            build_id=build_id,
            resource_id=build_id,
        ),
    )


async def _send_websocket_failure(
    websocket: WebSocket,
    exc: Exception,
    error_message: type[schemas.ComputeWorkersWebsocketErrorMessage] | type[schemas.BuildWebsocketErrorMessage],
    label: str,
) -> None:
    """Report a stream failure to the client; client disconnects end the stream quietly."""
    if isinstance(exc, HTTPException):
        await safe_send_json_error(websocket, error_message(error=str(exc.detail), status_code=exc.status_code))
        return
    if isinstance(exc, RuntimeError) and is_disconnect_runtime_error(exc):
        return
    logger.error('%s websocket error: %s', label, exc, exc_info=exc)
    await safe_send_json_error(websocket, error_message(error='An internal error occurred'))


@router.websocket('/ws/compute-workers')
async def compute_workers_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    subscribed = False
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        await compute_worker_registry.subscribe(namespace)
        subscribed = True
        last_seen = await _send_compute_worker_snapshot(websocket)
        while True:
            updated = await _wait_unless_disconnected(websocket, compute_worker_registry.wait_for_namespace(namespace, last_seen))
            if updated is None:
                return
            last_seen = await _send_compute_worker_snapshot(websocket)
            # One snapshot is authoritative for all intermediate lifecycle
            # notifications. A burst of starts/stops should not make every
            # browser socket issue one database read per version.
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError, concurrent.futures.CancelledError:
        return
    except Exception as exc:
        await _send_websocket_failure(websocket, exc, schemas.ComputeWorkersWebsocketErrorMessage, 'Compute worker')
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
        last_version = build_hub.subscribe_namespace(namespace)
        subscribed = True
        await _send_build_list_snapshot(websocket, namespace)
        while True:
            if await _wait_unless_disconnected(websocket, build_hub.wait_for_namespace(namespace, last_version)) is None:
                return
            # Capture the version before reading so a racing update triggers another snapshot.
            updated_version = max(last_version, build_hub.latest_namespace_sequence(namespace))
            payload = await run_api_blocking(run_db, lambda session: _build_list_snapshot_message(session, namespace).model_dump(mode='json'))
            if not await safe_send_json(websocket, payload):
                return
            last_version = updated_version
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError, concurrent.futures.CancelledError:
        return
    except Exception as exc:
        await _send_websocket_failure(websocket, exc, schemas.BuildWebsocketErrorMessage, 'Build list')
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
        if not await safe_send_json(websocket, message):
            return
        last_sequence = max(last_sequence, message.last_sequence)
        while True:
            notification = await _wait_unless_disconnected(websocket, build_hub.wait_for_build(build_id, last_sequence))
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
    except Exception as exc:
        await _send_websocket_failure(websocket, exc, schemas.BuildWebsocketErrorMessage, 'Active build')
    finally:
        if subscribed:
            build_hub.unsubscribe_build(namespace, build_id)
        reset_namespace(token)
        await safe_close_websocket(websocket)


@router.get('/defaults', response_model=schemas.ComputeWorkerDefaults, mcp=True)
@handle_errors(operation='get compute worker defaults')
async def get_compute_worker_defaults():
    """Get resolved default engine resource settings for the UI."""
    # POLARS_CORES_AVAILABLE is the platform budget (0 = all logical CPUs on host).
    return schemas.ComputeWorkerDefaults(
        max_threads=settings.polars_cores_available if settings.polars_cores_available > 0 else os.cpu_count() or 1,
        max_memory_mb=settings.polars_max_memory_mb if settings.polars_max_memory_mb > 0 else _resolved_system_memory_mb(),
        streaming_chunk_size=settings.polars_streaming_chunk_size,
    )


async def _download_response(request: schemas.DownloadRequest) -> Response:
    file_bytes, filename, content_type = await executor_client.download_step(request)
    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={'Content-Disposition': f'attachment; filename="{quote(filename)}"'},
    )


@router.post('/export', mcp=True)
@handle_errors(operation='export data')
async def export_data(
    request: schemas.ExportRequest = Depends(_json_body(schemas.ExportRequest)),
    _user: User = Depends(get_current_user),
):
    """Export pipeline results to a file download or output datasource.

    For destination='download': returns file bytes in the requested format (csv, parquet, json, etc.).
    For destination='datasource': writes to an Iceberg output datasource (requires result_id and iceberg_options).
    """
    if request.destination == schemas.ExportDestination.DOWNLOAD:
        return await _download_response(
            schemas.DownloadRequest(
                analysis_id=request.analysis_id,
                target_step_id=request.target_step_id,
                analysis_pipeline=request.analysis_pipeline,
                tab_id=request.tab_id,
                format=request.format,
                filename=request.filename,
            )
        )

    response = await executor_client.export_data(request)
    return await executor_client.json_response(response)


@router.post('/download', mcp=True)
@handle_errors(operation='download step')
async def download_step(
    request: schemas.DownloadRequest = Depends(_json_body(schemas.DownloadRequest)),
    _user: User = Depends(get_current_user),
):
    """Download pipeline step result as a file.

    Returns the file bytes with appropriate Content-Type header.
    Supported formats: csv, parquet, json, ndjson, duckdb, excel.
    """
    return await _download_response(request)
