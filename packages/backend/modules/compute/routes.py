import asyncio
import concurrent.futures
import logging
import os
import re
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlmodel import Session

from backend_core import (
    build_event_service,
    build_runs_service as build_run_service,
    engine_runs_service as engine_run_service,
    runtime_outbox_service,
)
from backend_core.auth_config import settings as auth_settings
from backend_core.config import settings
from backend_core.data_plane_client import client_from_settings
from backend_core.database import get_db, get_settings_db
from backend_core.dependencies import (
    RuntimeAvailabilityProbe,
    get_manager,
    get_runtime_availability_probe,
)
from backend_core.domain.build_runs.live import BuildNotification, hub as build_hub
from backend_core.domain.compute import schemas
from backend_core.domain.engine_runs.schemas import EngineRunKind
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.engine_live import load_engine_snapshot, registry as engine_registry
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

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/compute', tags=['compute'])


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
    session_gen = get_db()
    session = next(session_gen)
    try:
        rows = build_run_service.list_build_events_after(session, build_id, after_sequence)
    finally:
        session.close()
        session_gen.close()
    latest = after_sequence
    for row in rows:
        if not await safe_send_json(websocket, build_run_service.serialize_event_row(row)):
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
    user = await run_in_threadpool(_resolve_websocket_user, websocket)
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


def _build_analysis_name(pipeline: dict) -> str:
    analysis_id = pipeline.get('analysis_id')
    if not isinstance(analysis_id, str) or not analysis_id:
        return 'Build'
    session_gen = get_db()
    session = next(session_gen)
    try:
        return _analysis_name(session, analysis_id)
    finally:
        session.close()
        session_gen.close()


def _build_triggered_by(user: User | None) -> str:
    if user is None:
        return 'user'
    return user.id


async def _send_build_snapshot(websocket: WebSocket, build_id: str) -> None:
    session_gen = get_db()
    session = next(session_gen)
    try:
        message = _build_snapshot_message(session, build_id)
    finally:
        session.close()
        session_gen.close()
    if message is None:
        raise HTTPException(status_code=404, detail='Build not found')
    await safe_send_json(websocket, message.model_dump(mode='json'))


async def _send_build_list_snapshot(websocket: WebSocket, namespace: str) -> None:
    session_gen = get_db()
    session = next(session_gen)
    try:
        message = _build_list_snapshot_message(session, namespace)
    finally:
        session.close()
        session_gen.close()
    await safe_send_json(websocket, message.model_dump(mode='json'))


def _get_latest_build_namespace_update(namespace: str) -> str | None:
    latest = build_hub.latest_namespace_sequence(namespace)
    if latest <= 0:
        return None
    return str(latest)


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


async def _send_engine_snapshot(websocket: WebSocket) -> None:
    session_gen = get_settings_db()
    session = next(session_gen)
    try:
        defaults: dict[str, object] = {
            'max_threads': settings.polars_cores_available,
            'max_memory_mb': settings.polars_max_memory_mb,
            'streaming_chunk_size': settings.polars_streaming_chunk_size,
        }
        message = load_engine_snapshot(session, namespace=get_namespace(), defaults=defaults)
    finally:
        session.close()
        session_gen.close()
    await safe_send_json(websocket, message.model_dump(mode='json'))


async def _wait_for_engine_notification(websocket: WebSocket, namespace: str, last_seen: str | None) -> str | None:
    receive_task = asyncio.create_task(_wait_for_websocket_disconnect(websocket))
    notify_task = asyncio.create_task(engine_registry.wait_for_namespace(namespace, last_seen))
    done, pending = await asyncio.wait({receive_task, notify_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if receive_task in done:
        return None
    return await notify_task


@router.post('/preview', response_model=schemas.StepPreviewResponse, mcp=True)
@handle_errors(operation='preview step')
async def preview_step(
    request: schemas.StepPreviewRequest,
    http_request: Request,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Preview the result of a pipeline step with pagination.

    Requires analysis_pipeline (full pipeline payload with tabs and steps) and target_step_id
    (the step to preview, or 'source' for raw data). Returns column names, types, data rows,
    and total row count. Use row_limit and page for pagination.
    """
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id
    normalized = request.model_copy(update={'analysis_id': analysis_id})
    engine_identity = (
        normalized.engine_identity
        if normalized.engine_identity is not None
        else compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id=analysis_id,
            resource_id=analysis_id,
        )
    )
    manager = _override_manager(http_request)
    if manager is not None:
        executor = _override_compute_executor(http_request)
        if executor is None:
            raise RuntimeError('Missing compute override executor for manager override')

        return executor.preview_step(
            session=session,
            manager=manager,
            target_step_id=normalized.target_step_id,
            analysis_pipeline=normalized.analysis_pipeline.model_dump(mode='json'),
            row_limit=normalized.row_limit,
            page=normalized.page,
            analysis_id=analysis_id,
            engine_identity=engine_identity,
            resource_config=normalized.resource_config.model_dump() if normalized.resource_config else None,
            tab_id=normalized.tab_id,
            request_json=normalized.model_dump(mode='json'),
        )
    return await executor_client.preview_step(session, normalized, runtime_probe=runtime_probe)


@router.post('/schema', response_model=schemas.StepSchemaResponse, mcp=True)
@handle_errors(operation='get step schema')
async def get_step_schema(
    request: schemas.StepSchemaRequest,
    http_request: Request,
    session: Session = Depends(get_db),
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

        return executor.get_step_schema(
            session=session,
            manager=manager,
            target_step_id=normalized.target_step_id,
            analysis_id=analysis_id,
            analysis_pipeline=normalized.analysis_pipeline.model_dump(mode='json'),
            tab_id=normalized.tab_id,
        )
    return await executor_client.get_step_schema(session, normalized, runtime_probe=runtime_probe)


@router.post('/row-count', response_model=schemas.StepRowCountResponse, mcp=True)
@handle_errors(operation='get step row count')
async def get_step_row_count(
    request: schemas.StepRowCountRequest,
    http_request: Request,
    session: Session = Depends(get_db),
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

        return executor.get_step_row_count(
            session=session,
            manager=manager,
            target_step_id=normalized.target_step_id,
            analysis_id=analysis_id,
            analysis_pipeline=normalized.analysis_pipeline.model_dump(mode='json'),
            tab_id=normalized.tab_id,
            request_json=normalized.model_dump(mode='json'),
        )
    return await executor_client.get_step_row_count(session, normalized, runtime_probe=runtime_probe)


@router.get(
    '/iceberg/{datasource_id}/snapshots',
    response_model=schemas.IcebergSnapshotsResponse,
    mcp=True,
)
@handle_errors(operation='list iceberg snapshots')
def list_iceberg_snapshots(
    datasource_id: DataSourceId,
    branch: str | None = None,
    build_results_only: bool = False,
    session: Session = Depends(get_db),
):
    """List Iceberg table snapshots for time-travel selection.

    Each snapshot has a snapshot_id, timestamp, and operation type.
    Optionally filter by branch. Set build_results_only=true to return only
    snapshots produced by completed builds for this datasource.
    """
    return list_iceberg_snapshots_info(
        session,
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
def delete_iceberg_snapshot(
    datasource_id: DataSourceId,
    snapshot_id: int,
    session: Session = Depends(get_db),
):
    """Delete an Iceberg snapshot by ID. Use GET /compute/iceberg/{id}/snapshots to find snapshot IDs.

    Warning: deleting snapshots removes the ability to time-travel to that point.
    """
    return delete_iceberg_snapshot_info(session, parse_datasource_id(datasource_id), str(snapshot_id))


@router.post('/builds', response_model=schemas.BuildRunDetail)
@handle_errors(operation='start build')
async def start_build(
    request: schemas.BuildRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    if not runtime_probe.available(kind=RuntimeWorkerKind.BUILD_MANAGER):
        raise HTTPException(status_code=503, detail='Compute runtime unavailable')

    pipeline = normalize_pipeline_step_configs_for_protocol(request.pipeline_payload())
    analysis_id = str(pipeline.get('analysis_id') or '')
    analysis_name = await run_in_threadpool(_build_analysis_name, pipeline)
    namespace = get_namespace()
    started_at = _utcnow()
    build_id = str(uuid.uuid4())
    raw_tabs = pipeline.get('tabs')
    tabs = raw_tabs if isinstance(raw_tabs, list) else []
    selected_tab = next(
        (tab for tab in tabs if isinstance(tab, dict) and isinstance(tab.get('id'), str) and tab.get('id') == request.tab_id),
        None,
    )
    active_tab = selected_tab if isinstance(selected_tab, dict) else next((tab for tab in tabs if isinstance(tab, dict)), None)
    current_kind = EngineRunKind.BUILD.value
    current_datasource_id: str | None = None
    current_tab_id: str | None = None
    current_tab_name: str | None = None
    current_output_id: str | None = None
    current_output_name: str | None = None
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
            data_plane = client_from_settings()
            warehouse_path = data_plane.build_object_url('exports', namespace=get_namespace())
            placeholder_source_type = datasource_service.DataSourceType.ICEBERG
            placeholder_config = {
                'catalog_type': 'sql',
                'catalog_uri': settings.database_url,
                'warehouse': warehouse_path,
                'namespace': namespace_name if isinstance(namespace_name, str) and namespace_name.strip() else 'outputs',
                'table': table_name,
                'table_name': output_name if isinstance(output_name, str) and output_name.strip() else table_name,
                'metadata_path': data_plane.build_object_url('exports', str(result_id), namespace=get_namespace()),
                'branch': branch_name,
                'namespace_name': get_namespace(),
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
    commands.start_build(
        session,
        commands.StartBuildCommand(
            build_id=build_id,
            namespace=namespace,
            analysis_id=analysis_id,
            analysis_name=analysis_name,
            request_json={'analysis_pipeline': {'analysis_id': pipeline['analysis_id'], 'tabs': pipeline['tabs']}, 'tab_id': request.tab_id},
            starter_json=starter.model_dump(mode='json'),
            current_kind=current_kind,
            current_datasource_id=current_datasource_id,
            current_tab_id=current_tab_id,
            current_tab_name=current_tab_name,
            current_output_id=current_output_id,
            current_output_name=current_output_name,
            total_tabs=len(tabs),
            started_at=started_at,
            placeholders=placeholders,
        ),
    )
    detail = _get_durable_build_detail(session, build_id)
    if detail is None:
        raise HTTPException(status_code=500, detail='Failed to create build')
    await build_hub.publish(BuildNotification(namespace=namespace, build_id=build_id, latest_sequence=0))
    from backend_core.domain.build_jobs.live import hub as build_job_hub

    build_job_hub.publish()
    runtime_outbox_service.dispatch_pending_events(session)
    return detail


@router.post('/builds/{build_id}/cancel', response_model=schemas.CancelBuildResponse, mcp=True)
@handle_errors(operation='cancel build')
async def cancel_build(
    build_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    detail = _get_durable_build_detail(session, build_id)
    if detail is None:
        raise HTTPException(status_code=404, detail='Build not found')
    if detail.status not in {
        schemas.BuildLifecycleStatus.QUEUED,
        schemas.BuildLifecycleStatus.RUNNING,
    }:
        raise HTTPException(status_code=400, detail='Only active builds can be cancelled')

    cancelled_by = user.email or user.display_name or user.id
    cancelled_at = _utcnow()
    duration_ms = detail.cancel_duration_ms(cancelled_at=cancelled_at)
    cancellation_event = detail.cancelled_event(
        cancelled_at=cancelled_at,
        cancelled_by=cancelled_by,
        duration_ms=duration_ms,
        emitted_at=_utcnow(),
    )
    try:
        event_row = commands.cancel_build(session, detail=detail, event=cancellation_event)
    except commands.BuildCancellationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await build_event_service.publish_build_notification(detail.namespace, detail.build_id, latest_sequence=event_row.sequence)

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
    session: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    del request
    namespace = get_namespace()
    fetch_limit = limit + offset
    runs = build_run_service.list_build_runs(
        session,
        analysis_id=analysis_id.strip() if analysis_id else None,
        datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
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
            analysis_id=analysis_id.strip() if analysis_id else None,
            datasource_id=parse_datasource_id(datasource_id) if datasource_id else None,
            kind=representations.engine_run_kind_filter(kind),
            status=representations.engine_run_status_filter(status),
            search=search,
            limit=fetch_limit,
            offset=0,
        )
        engine_rows = [representations.engine_run_summary(run, namespace=namespace) for run in engine_runs]
    visible = sorted([*build_rows, *engine_rows], key=lambda run: run.started_at, reverse=True)
    paged = visible[offset : offset + limit]
    return schemas.BuildRunListResponse(builds=paged, total=len(visible))


@router.get('/builds/{build_id}', response_model=schemas.BuildRunDetail, mcp=True)
@handle_errors(operation='get build')
async def get_build(
    build_id: str,
    session: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    detail = _get_durable_build_detail(session, build_id)
    if detail is not None:
        return detail
    engine_run = engine_run_service.get_engine_run(session, build_id)
    if engine_run is not None:
        return representations.engine_run_detail(engine_run, namespace=get_namespace())
    raise HTTPException(status_code=404, detail='Build not found')


# Engine lifecycle endpoints


async def _spawn_engine_identity(
    identity,
    http_request: Request,
    request: schemas.SpawnEngineRequest | None,
    session: Session,
    runtime_probe: RuntimeAvailabilityProbe,
):
    resource_config = request.resource_config.model_dump() if request and request.resource_config else None
    manager = _override_manager(http_request)
    if manager is not None:
        manager.spawn_engine(identity, resource_config=resource_config)
        return manager.get_engine_status(identity)
    return await executor_client.spawn_engine(
        session,
        identity=identity,
        resource_config=resource_config,
        runtime_probe=runtime_probe,
    )


async def _configure_engine_identity(
    identity,
    request: schemas.EngineResourceConfig,
    http_request: Request,
    session: Session,
    runtime_probe: RuntimeAvailabilityProbe,
):
    resource_config = request.model_dump()
    manager = _override_manager(http_request)
    if manager is not None:
        manager.restart_engine_with_config(identity, resource_config)
        return manager.get_engine_status(identity)
    return await executor_client.configure_engine(
        session,
        identity=identity,
        resource_config=resource_config,
        runtime_probe=runtime_probe,
    )


async def _shutdown_engine_identity(
    identity,
    http_request: Request,
    session: Session,
    runtime_probe: RuntimeAvailabilityProbe,
) -> None:
    manager = _override_manager(http_request)
    if manager is not None:
        engine = manager.get_engine(identity)
        if not engine:
            raise engine_not_found(identity.resource_id)
        if engine.current_job_id and engine.is_process_alive():
            raise HTTPException(status_code=409, detail='Engine has an active job')
        manager.shutdown_engine(identity)
        return
    await executor_client.shutdown_engine(session, identity=identity, runtime_probe=runtime_probe)


@router.post('/engine/spawn/analysis/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='spawn analysis engine')
async def spawn_analysis_engine(
    analysis_id: AnalysisId,
    http_request: Request,
    request: schemas.SpawnEngineRequest | None = None,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    return await _spawn_engine_identity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id=analysis_id,
            resource_id=analysis_id,
        ),
        http_request,
        request,
        session,
        runtime_probe,
    )


@router.post('/engine/spawn/datasource-preview/{datasource_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='spawn datasource preview engine')
async def spawn_datasource_preview_engine(
    datasource_id: DataSourceId,
    http_request: Request,
    request: schemas.SpawnEngineRequest | None = None,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    datasource_id_value = parse_datasource_id(datasource_id)
    return await _spawn_engine_identity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            datasource_id=datasource_id_value,
            resource_id=datasource_id_value,
        ),
        http_request,
        request,
        session,
        runtime_probe,
    )


@router.post('/engine/configure/analysis/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='configure analysis engine')
async def configure_analysis_engine(
    analysis_id: AnalysisId,
    request: schemas.EngineResourceConfig,
    http_request: Request,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    return await _configure_engine_identity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id=analysis_id,
            resource_id=analysis_id,
        ),
        request,
        http_request,
        session,
        runtime_probe,
    )


@router.post('/engine/configure/datasource-preview/{datasource_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='configure datasource preview engine')
async def configure_datasource_preview_engine(
    datasource_id: DataSourceId,
    request: schemas.EngineResourceConfig,
    http_request: Request,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    datasource_id_value = parse_datasource_id(datasource_id)
    return await _configure_engine_identity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            datasource_id=datasource_id_value,
            resource_id=datasource_id_value,
        ),
        request,
        http_request,
        session,
        runtime_probe,
    )


@router.delete('/engine/analysis/{analysis_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown analysis engine')
async def shutdown_analysis_engine(
    analysis_id: AnalysisId,
    http_request: Request,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    await _shutdown_engine_identity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id=analysis_id,
            resource_id=analysis_id,
        ),
        http_request,
        session,
        runtime_probe,
    )


@router.delete('/engine/datasource-preview/{datasource_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown datasource preview engine')
async def shutdown_datasource_preview_engine(
    datasource_id: DataSourceId,
    http_request: Request,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    datasource_id_value = parse_datasource_id(datasource_id)
    await _shutdown_engine_identity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            datasource_id=datasource_id_value,
            resource_id=datasource_id_value,
        ),
        http_request,
        session,
        runtime_probe,
    )


@router.delete('/engine/build/{build_id}', status_code=204, mcp=True, mcp_confirm_required=True)
@handle_errors(operation='shutdown build engine')
async def shutdown_build_engine(
    build_id: str,
    http_request: Request,
    session: Session = Depends(get_db),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    await _shutdown_engine_identity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_BUILD,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
            build_id=build_id,
            resource_id=build_id,
        ),
        http_request,
        session,
        runtime_probe,
    )


@router.websocket('/ws/engines')
async def engine_list_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    await websocket.accept()
    try:
        await engine_registry.add_watcher(namespace, websocket)
        last_seen = await engine_registry.current_version(namespace)
        await _send_engine_snapshot(websocket)
        while True:
            updated = await _wait_for_engine_notification(websocket, namespace, last_seen)
            if updated is None:
                return
            await _send_engine_snapshot(websocket)
            last_seen = updated
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError, concurrent.futures.CancelledError:
        return
    except HTTPException as exc:
        await safe_send_json(
            websocket,
            schemas.EngineWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code).model_dump(mode='json'),
        )
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        logger.error('Engine websocket error: %s', exc, exc_info=True)
        await safe_send_json(
            websocket,
            schemas.EngineWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    except Exception as exc:
        logger.error('Engine websocket error: %s', exc, exc_info=True)
        await safe_send_json(
            websocket,
            schemas.EngineWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    finally:
        await engine_registry.remove_watcher(namespace, websocket)
        reset_namespace(token)
        await safe_close_websocket(websocket)


@router.websocket('/ws/builds')
async def build_list_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        last_seen = await run_in_threadpool(_get_latest_build_namespace_update, namespace)
        await _send_build_list_snapshot(websocket, namespace)
        while True:
            updated = await _wait_for_namespace_build_update(websocket, namespace, last_seen)
            if updated is None:
                return
            session_gen = get_db()
            session = next(session_gen)
            try:
                payload = _build_list_snapshot_message(session, namespace).model_dump(mode='json')
            finally:
                session.close()
                session_gen.close()
            sent = await safe_send_json(websocket, payload)
            if not sent:
                return
            last_seen = updated
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError, concurrent.futures.CancelledError:
        return
    except HTTPException as exc:
        await safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code).model_dump(mode='json'),
        )
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        logger.error('Build list websocket error: %s', exc, exc_info=True)
        await safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    except Exception as exc:
        logger.error('Build list websocket error: %s', exc, exc_info=True)
        await safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    finally:
        reset_namespace(token)
        await safe_close_websocket(websocket)


@router.websocket('/ws/builds/{build_id}')
async def build_stream(websocket: WebSocket, build_id: str) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    raw_last_sequence = websocket.query_params.get('last_sequence')
    last_sequence = int(raw_last_sequence) if raw_last_sequence and raw_last_sequence.isdigit() else 0
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        while True:
            session_gen = get_db()
            session = next(session_gen)
            try:
                message = _build_snapshot_message(session, build_id)
            finally:
                session.close()
                session_gen.close()
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
        sent = await safe_send_json(websocket, message.model_dump(mode='json'))
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
        await safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code).model_dump(mode='json'),
        )
    except RuntimeError as exc:
        if is_disconnect_runtime_error(exc):
            return
        logger.error('Active build websocket error: %s', exc, exc_info=True)
        await safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    except Exception as exc:
        logger.error('Active build websocket error: %s', exc, exc_info=True)
        await safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    finally:
        reset_namespace(token)
        await safe_close_websocket(websocket)


@router.get('/defaults', response_model=schemas.EngineDefaults, mcp=True)
@handle_errors(operation='get engine defaults')
def get_engine_defaults():
    """Get resolved default engine resource settings for the UI."""
    return schemas.EngineDefaults(
        max_threads=_resolved_default_max_threads(),
        max_memory_mb=_resolved_default_max_memory_mb(),
        streaming_chunk_size=settings.polars_streaming_chunk_size,
    )


@router.post('/export', mcp=True)
@handle_errors(operation='export data')
async def export_data(
    request: schemas.ExportRequest,
    http_request: Request,
    session: Session = Depends(get_db),
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

            file_bytes, filename, content_type = executor.download_step(
                session=session,
                manager=manager,
                target_step_id=download_request.target_step_id,
                analysis_pipeline=download_request.analysis_pipeline.model_dump(mode='json'),
                export_format=download_request.format.value,
                filename=download_request.filename,
                analysis_id=download_request.analysis_id,
                tab_id=download_request.tab_id,
            )
        else:
            file_bytes, filename, content_type = await executor_client.download_step(
                session,
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

        result = executor.export_data(
            session=session,
            manager=manager,
            target_step_id=request.target_step_id,
            analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
            filename=request.filename,
            iceberg_options=request.iceberg_options.model_dump() if request.iceberg_options else None,
            analysis_id=request.analysis_id,
            tab_id=request.tab_id,
            request_json=request.model_dump(mode='json'),
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
    return await executor_client.export_data(session, request, runtime_probe=runtime_probe)


@router.post('/download', mcp=True)
@handle_errors(operation='download step')
async def download_step(
    request: schemas.DownloadRequest,
    http_request: Request,
    session: Session = Depends(get_db),
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

        file_bytes, filename, content_type = executor.download_step(
            session=session,
            manager=manager,
            target_step_id=request.target_step_id,
            analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
            export_format=request.format.value,
            filename=request.filename,
            analysis_id=request.analysis_id,
            tab_id=request.tab_id,
        )
    else:
        file_bytes, filename, content_type = await executor_client.download_step(
            session,
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
