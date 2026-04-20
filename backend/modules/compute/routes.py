import asyncio
import logging
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlmodel import Session
from starlette.websockets import WebSocketState

from core.database import get_db
from core.dependencies import get_manager
from core.error_handlers import handle_errors
from core.exceptions import EngineNotFoundError
from core.namespace import get_namespace, reset_namespace, set_namespace_context
from core.validation import AnalysisId, DataSourceId, EngineRunId, parse_analysis_id, parse_datasource_id, parse_engine_run_id
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.compute import schemas, service
from modules.compute.engine_live import registry as engine_registry
from modules.compute.live import ActiveBuildContext, registry as build_registry
from modules.compute.manager import ProcessManager
from modules.engine_runs import service as engine_run_service
from modules.engine_runs.schemas import EngineRunKind, EngineRunStatus
from modules.mcp.router import MCPRouter

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/compute', tags=['compute'])


def _websocket_disconnected(websocket: WebSocket) -> bool:
    return websocket.client_state is WebSocketState.DISCONNECTED or websocket.application_state is WebSocketState.DISCONNECTED


def _is_disconnect_runtime_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return (
        'Cannot call "receive" once a disconnect message has been received' in message
        or 'Cannot call "send" once a close message has been sent' in message
        or ('Unexpected ASGI message' in message and 'websocket.close' in message)
    )


async def _safe_close_websocket(websocket: WebSocket) -> None:
    if _websocket_disconnected(websocket):
        return
    try:
        await websocket.close()
    except RuntimeError as exc:
        if _is_disconnect_runtime_error(exc):
            return
        raise


async def _safe_send_json(websocket: WebSocket, payload: dict) -> bool:
    if _websocket_disconnected(websocket):
        return False
    try:
        await websocket.send_json(payload)
    except RuntimeError as exc:
        if _websocket_disconnected(websocket) or _is_disconnect_runtime_error(exc):
            return False
        raise
    except WebSocketDisconnect:
        return False
    return True


async def _wait_for_websocket_disconnect(websocket: WebSocket) -> None:
    while not _websocket_disconnected(websocket):
        try:
            message = await websocket.receive()
        except WebSocketDisconnect:
            return
        except RuntimeError as exc:
            if _websocket_disconnected(websocket) or _is_disconnect_runtime_error(exc):
                return
            raise
        if message.get('type') == 'websocket.disconnect':
            return


def _get_websocket_manager(websocket: WebSocket) -> ProcessManager:
    override = websocket.app.dependency_overrides.get(get_manager)
    if override is not None:
        return override()
    return websocket.app.state.manager


def _resolve_websocket_session_token(websocket: WebSocket) -> str | None:
    cookie_token = websocket.cookies.get('session_token')
    if cookie_token:
        return cookie_token
    header_token = websocket.headers.get('X-Session-Token')
    if header_token:
        return header_token
    return None


def _resolve_websocket_user(websocket: WebSocket) -> User | None:
    override = websocket.app.dependency_overrides.get(get_current_user)
    if override is not None:
        return override()

    from core.database import run_settings_db
    from modules.auth.service import ensure_default_user, validate_session

    token = _resolve_websocket_session_token(websocket)

    def _lookup(session: Session) -> User | None:
        if token:
            return validate_session(session, token)
        from core.config import settings

        if not settings.auth_required:
            return ensure_default_user(session)
        return None

    return run_settings_db(_lookup)


async def _emit_active_build_event(build_id: str, analysis_id: str, payload: dict[str, object]) -> None:
    emitted_at = payload.get('emitted_at')
    if not isinstance(emitted_at, str):
        emitted_at = service._utcnow().isoformat()
    normalized = {'build_id': build_id, 'analysis_id': analysis_id, 'emitted_at': emitted_at, **payload}
    context = await build_registry.apply_event(build_id, normalized)
    if context is None:
        return
    normalized.update(context.payload())
    await build_registry.publish(build_id, normalized)


async def _require_websocket_user(websocket: WebSocket) -> User:
    user = await run_in_threadpool(_resolve_websocket_user, websocket)
    if user is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return user


def _build_analysis_name(pipeline: dict) -> str:
    analysis_id = pipeline.get('analysis_id')
    if not isinstance(analysis_id, str) or not analysis_id:
        return 'Build'
    session_gen = get_db()
    session = next(session_gen)
    try:
        return service._analysis_name(session, analysis_id)
    finally:
        session.close()
        session_gen.close()


def _build_triggered_by(user: User | None) -> str:
    if user is None:
        return 'user'
    return user.id


async def _send_build_snapshot(websocket: WebSocket, build_id: str) -> None:
    build = await build_registry.get_build(build_id)
    if build is None:
        raise HTTPException(status_code=404, detail='Active build not found')
    await _safe_send_json(websocket, schemas.BuildSnapshotMessage(build=build.detail()).model_dump(mode='json'))


async def _send_build_list_snapshot(websocket: WebSocket, namespace: str) -> None:
    builds = await build_registry.list_builds(status=schemas.ActiveBuildStatus.RUNNING)
    visible = [build for build in builds if build.namespace == namespace]
    await _safe_send_json(websocket, schemas.BuildListSnapshotMessage(builds=visible).model_dump(mode='json'))


async def _send_engine_snapshot(websocket: WebSocket, manager: ProcessManager) -> None:
    statuses = manager.list_all_engine_statuses()
    await _safe_send_json(
        websocket,
        schemas.EngineListSnapshotMessage(
            engines=[schemas.EngineStatusSchema.model_validate(status) for status in statuses],
            total=len(statuses),
        ).model_dump(mode='json'),
    )


def _build_pipeline_payload(request: schemas.BuildRequest) -> dict:
    pipeline = request.analysis_pipeline.model_dump(mode='json') if request.analysis_pipeline else None
    if not isinstance(pipeline, dict):
        raise ValueError('analysis_pipeline is required')
    return {**pipeline, 'tab_id': request.tab_id}


async def _run_active_build_task(
    *,
    manager: ProcessManager,
    build_id: str,
    analysis_id: str,
    namespace: str,
    pipeline: dict,
    triggered_by: str | None,
) -> None:
    token = set_namespace_context(namespace)
    session_gen = None
    session = None
    try:
        build = await build_registry.get_build(build_id)
        if build is None:
            return
        active_build = build
        session_gen = get_db()
        session = next(session_gen)
        await service.run_analysis_build_stream(
            session=session,
            manager=manager,
            pipeline=pipeline,
            build=active_build,
            emitter=lambda payload: _emit_active_build_event(active_build.build_id, analysis_id, payload),
            triggered_by=triggered_by,
        )
    except Exception as exc:
        logger.error('Active build task error: %s', exc, exc_info=True)
        build = await build_registry.get_build(build_id)
        if build is not None and build.status == schemas.ActiveBuildStatus.RUNNING:
            await _emit_active_build_event(
                build.build_id,
                analysis_id,
                {
                    'type': 'failed',
                    'progress': build.progress,
                    'elapsed_ms': build.elapsed_ms,
                    'total_steps': build.total_steps,
                    'tabs_built': len(build.results),
                    'results': [result.model_dump(mode='json') for result in build.results],
                    'duration_ms': build.elapsed_ms,
                    'error': 'Build failed due to an internal error',
                    'current_output_id': build.current_output_id,
                    'current_output_name': build.current_output_name,
                },
            )
    finally:
        if session is not None:
            session.close()
        if session_gen is not None:
            session_gen.close()
        reset_namespace(token)


@router.post('/preview', response_model=schemas.StepPreviewResponse, mcp=True)
@handle_errors(operation='preview step')
def preview_step(
    request: schemas.StepPreviewRequest,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Preview the result of a pipeline step with pagination.

    Requires analysis_pipeline (full pipeline payload with tabs and steps) and target_step_id
    (the step to preview, or 'source' for raw data). Returns column names, types, data rows,
    and total row count. Use row_limit and page for pagination.
    """
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id

    return service.preview_step(
        session=session,
        manager=manager,
        target_step_id=request.target_step_id,
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        row_limit=request.row_limit,
        page=request.page,
        analysis_id=analysis_id,
        resource_config=request.resource_config.model_dump() if request.resource_config else None,
        tab_id=request.tab_id,
        request_json=request.model_dump(mode='json'),
    )


@router.post('/schema', response_model=schemas.StepSchemaResponse, mcp=True)
@handle_errors(operation='get step schema')
def get_step_schema(
    request: schemas.StepSchemaRequest,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Get the output column schema of a pipeline step without fetching data.

    Useful for configuring downstream steps that need to know available columns
    (e.g., pivot, unpivot, select). Returns column names and their Polars dtypes.
    """
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id

    return service.get_step_schema(
        session=session,
        manager=manager,
        target_step_id=request.target_step_id,
        analysis_id=analysis_id,
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        tab_id=request.tab_id,
    )


@router.post('/row-count', response_model=schemas.StepRowCountResponse, mcp=True)
@handle_errors(operation='get step row count')
def get_step_row_count(
    request: schemas.StepRowCountRequest,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Get the row count of a pipeline step result without fetching data. Faster than a full preview."""
    analysis_id = request.analysis_id if request.analysis_id is not None else request.analysis_pipeline.analysis_id

    return service.get_step_row_count(
        session=session,
        manager=manager,
        target_step_id=request.target_step_id,
        analysis_id=analysis_id,
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        tab_id=request.tab_id,
        request_json=request.model_dump(mode='json'),
    )


@router.get('/iceberg/{datasource_id}/snapshots', response_model=schemas.IcebergSnapshotsResponse, mcp=True)
@handle_errors(operation='list iceberg snapshots')
def list_iceberg_snapshots(
    datasource_id: DataSourceId,
    branch: str | None = None,
    session: Session = Depends(get_db),
):
    """List Iceberg table snapshots for time-travel selection.

    Each snapshot has a snapshot_id, timestamp, and operation type.
    Optionally filter by branch. Use snapshot_id with compare-snapshots.
    """
    return service.list_iceberg_snapshots(session, parse_datasource_id(datasource_id), branch=branch)


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
    return service.delete_iceberg_snapshot(session, parse_datasource_id(datasource_id), str(snapshot_id))


@router.post('/builds/active', response_model=schemas.ActiveBuildDetail)
@handle_errors(operation='start active build')
async def start_active_build(
    request: schemas.BuildRequest,
    manager: ProcessManager = Depends(get_manager),
    user: User = Depends(get_current_user),
):
    pipeline = _build_pipeline_payload(request)
    analysis_id = str(pipeline.get('analysis_id') or '')
    analysis_name = await run_in_threadpool(_build_analysis_name, pipeline)
    namespace = get_namespace()
    raw_tabs = pipeline.get('tabs')
    tabs = raw_tabs if isinstance(raw_tabs, list) else []
    selected_tab = next(
        (tab for tab in tabs if isinstance(tab, dict) and isinstance(tab.get('id'), str) and tab.get('id') == request.tab_id),
        None,
    )
    active_tab = selected_tab if isinstance(selected_tab, dict) else next((tab for tab in tabs if isinstance(tab, dict)), None)
    context = ActiveBuildContext(
        current_kind=EngineRunKind.PREVIEW.value,
        current_datasource_id=None,
        current_tab_id=None,
        current_tab_name=None,
        current_output_id=None,
        current_output_name=None,
    )
    if isinstance(active_tab, dict):
        datasource = active_tab.get('datasource')
        if isinstance(datasource, dict) and isinstance(datasource.get('id'), str):
            context.current_datasource_id = datasource.get('id')
        if isinstance(active_tab.get('id'), str):
            context.current_tab_id = active_tab.get('id')
        if isinstance(active_tab.get('name'), str):
            context.current_tab_name = active_tab.get('name')
    build = await build_registry.create_build(
        analysis_id=analysis_id,
        analysis_name=analysis_name,
        namespace=namespace,
        starter=service._build_starter(user),
        total_tabs=len(pipeline.get('tabs', [])) if isinstance(pipeline.get('tabs'), list) else 0,
        context=context,
    )
    await build_registry.publish_list_snapshot(namespace)
    task = asyncio.create_task(
        _run_active_build_task(
            manager=manager,
            build_id=build.build_id,
            analysis_id=analysis_id,
            namespace=namespace,
            pipeline=pipeline,
            triggered_by=_build_triggered_by(user),
        ),
        name=f'active-build:{build.build_id}',
    )
    await build_registry.track_task(build.build_id, task)
    return build.detail()


@router.post('/cancel/{engine_run_id}', response_model=schemas.CancelBuildResponse, mcp=True)
@handle_errors(operation='cancel build')
async def cancel_build(
    engine_run_id: EngineRunId,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
    user: User = Depends(get_current_user),
):
    run_id = parse_engine_run_id(engine_run_id)
    run = engine_run_service.get_engine_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail='Engine run not found')
    if run.status != EngineRunStatus.RUNNING:
        raise HTTPException(status_code=400, detail='Only running builds can be cancelled')

    cancelled_by = user.email or user.display_name or user.id
    cancelled = service.cancel_engine_run(
        session,
        manager,
        run_id,
        cancelled_by=cancelled_by,
    )

    active = await build_registry.list_builds()
    match = next(
        (
            item
            for item in active
            if item.namespace == get_namespace()
            and item.current_engine_run_id == run_id
            and item.status == schemas.ActiveBuildStatus.RUNNING
        ),
        None,
    )
    if match is not None:
        await _emit_active_build_event(
            match.build_id,
            match.analysis_id,
            {
                'type': 'cancelled',
                'engine_run_id': run_id,
                'progress': match.progress,
                'elapsed_ms': cancelled.duration_ms or match.elapsed_ms,
                'total_steps': match.total_steps,
                'tabs_built': 0,
                'results': [],
                'duration_ms': cancelled.duration_ms or match.elapsed_ms,
                'cancelled_at': cancelled.cancelled_at.isoformat(),
                'cancelled_by': cancelled.cancelled_by,
                'current_output_id': match.current_output_id,
                'current_output_name': match.current_output_name,
            },
        )

    return cancelled


@router.get('/builds/active', response_model=schemas.ActiveBuildListResponse, mcp=True)
@handle_errors(operation='list active builds')
async def list_active_builds(
    request: Request,
    status: schemas.ActiveBuildStatus | None = None,
    _user: User = Depends(get_current_user),
):
    del request
    builds = await build_registry.list_builds(status=status or schemas.ActiveBuildStatus.RUNNING)
    namespace = get_namespace()
    visible = [build for build in builds if build.namespace == namespace]
    return schemas.ActiveBuildListResponse(builds=visible, total=len(visible))


@router.get('/builds/active/{build_id}', response_model=schemas.ActiveBuildDetail, mcp=True)
@handle_errors(operation='get active build')
async def get_active_build(
    build_id: str,
    _user: User = Depends(get_current_user),
):
    build = await build_registry.get_build(build_id)
    if build is None or build.namespace != get_namespace():
        raise HTTPException(status_code=404, detail='Active build not found')
    return build.detail()


@router.get('/builds/active/by-engine-run/{engine_run_id}', response_model=schemas.ActiveBuildDetail, mcp=True)
@handle_errors(operation='get active build by engine run')
async def get_active_build_by_engine_run(
    engine_run_id: EngineRunId,
    _user: User = Depends(get_current_user),
):
    run_id = parse_engine_run_id(engine_run_id)
    builds = await build_registry.list_builds(status=schemas.ActiveBuildStatus.RUNNING)
    namespace = get_namespace()
    match = next(
        (build for build in builds if build.namespace == namespace and build.current_engine_run_id == run_id),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail='Active build not found')
    build = await build_registry.get_build(match.build_id)
    if build is None or build.namespace != namespace:
        raise HTTPException(status_code=404, detail='Active build not found')
    return build.detail()


# Engine lifecycle endpoints


@router.post('/engine/spawn/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='spawn engine')
def spawn_engine(
    analysis_id: AnalysisId,
    request: schemas.SpawnEngineRequest | None = None,
    manager: ProcessManager = Depends(get_manager),
):
    """Spawn a compute engine for an analysis (called when analysis page opens).

    Optionally accepts resource configuration overrides.
    """
    resource_config = request.resource_config.model_dump() if request and request.resource_config else None
    analysis_id_value = parse_analysis_id(analysis_id)
    manager.spawn_engine(analysis_id_value, resource_config=resource_config)
    return manager.get_engine_status(analysis_id_value)


@router.post('/engine/keepalive/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='keepalive engine')
def keepalive(analysis_id: AnalysisId, manager: ProcessManager = Depends(get_manager)):
    """Send keepalive ping for an analysis engine."""
    analysis_id_value = parse_analysis_id(analysis_id)
    info = manager.keepalive(analysis_id_value)
    if not info:
        raise EngineNotFoundError(analysis_id_value)
    return manager.get_engine_status(analysis_id_value)


@router.post('/engine/configure/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='configure engine')
def configure_engine(
    analysis_id: AnalysisId,
    request: schemas.EngineResourceConfig,
    manager: ProcessManager = Depends(get_manager),
):
    """Update engine resource configuration (restarts the engine).

    This will terminate any running jobs and restart the engine with the new
    resource configuration. Values set to null will use the default from settings.
    """
    resource_config = request.model_dump()
    analysis_id_value = parse_analysis_id(analysis_id)
    manager.restart_engine_with_config(analysis_id_value, resource_config)
    return manager.get_engine_status(analysis_id_value)


@router.delete('/engine/{analysis_id}', status_code=204, mcp=True)
@handle_errors(operation='shutdown engine')
def shutdown_engine(analysis_id: AnalysisId, manager: ProcessManager = Depends(get_manager)):
    """Shutdown an analysis engine."""
    analysis_id_value = parse_analysis_id(analysis_id)
    engine = manager.get_engine(analysis_id_value)
    if not engine:
        raise EngineNotFoundError(analysis_id_value)
    if engine.current_job_id and engine.is_process_alive():
        raise HTTPException(status_code=409, detail='Engine has an active job')
    manager.shutdown_engine(analysis_id_value)


@router.websocket('/ws/engines')
async def engine_list_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    manager = _get_websocket_manager(websocket)
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        await engine_registry.add_watcher(namespace, websocket)
        await _send_engine_snapshot(websocket, manager)
        await _wait_for_websocket_disconnect(websocket)
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await _safe_send_json(
            websocket,
            schemas.EngineWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code).model_dump(mode='json'),
        )
    except RuntimeError as exc:
        if _is_disconnect_runtime_error(exc):
            return
        logger.error('Engine websocket error: %s', exc, exc_info=True)
        await _safe_send_json(
            websocket,
            schemas.EngineWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    except Exception as exc:
        logger.error('Engine websocket error: %s', exc, exc_info=True)
        await _safe_send_json(
            websocket,
            schemas.EngineWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    finally:
        await engine_registry.remove_watcher(namespace, websocket)
        reset_namespace(token)
        await _safe_close_websocket(websocket)


@router.websocket('/ws/builds')
async def build_list_stream(websocket: WebSocket) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    namespace = get_namespace()
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        await build_registry.add_list_watcher(namespace, websocket)
        await _send_build_list_snapshot(websocket, namespace)
        await _wait_for_websocket_disconnect(websocket)
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await _safe_send_json(
            websocket, schemas.BuildWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code).model_dump(mode='json')
        )
    except RuntimeError as exc:
        if _is_disconnect_runtime_error(exc):
            return
        logger.error('Build list websocket error: %s', exc, exc_info=True)
        await _safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    except Exception as exc:
        logger.error('Build list websocket error: %s', exc, exc_info=True)
        await _safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    finally:
        await build_registry.remove_list_watcher(namespace, websocket)
        reset_namespace(token)
        await _safe_close_websocket(websocket)


@router.websocket('/ws/builds/{build_id}')
async def active_build_stream(websocket: WebSocket, build_id: str) -> None:
    token = set_namespace_context(websocket.headers.get('X-Namespace') or websocket.query_params.get('namespace'))
    await websocket.accept()
    try:
        await _require_websocket_user(websocket)
        build = await build_registry.get_build(build_id)
        if build is None or build.namespace != get_namespace():
            raise HTTPException(status_code=404, detail='Active build not found')
        await build_registry.add_watcher(build_id, websocket)
        await _send_build_snapshot(websocket, build_id)
        await _wait_for_websocket_disconnect(websocket)
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await _safe_send_json(
            websocket, schemas.BuildWebsocketErrorMessage(error=str(exc.detail), status_code=exc.status_code).model_dump(mode='json')
        )
    except RuntimeError as exc:
        if _is_disconnect_runtime_error(exc):
            return
        logger.error('Active build websocket error: %s', exc, exc_info=True)
        await _safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    except Exception as exc:
        logger.error('Active build websocket error: %s', exc, exc_info=True)
        await _safe_send_json(
            websocket,
            schemas.BuildWebsocketErrorMessage(error='An internal error occurred').model_dump(mode='json'),
        )
    finally:
        await build_registry.remove_watcher(build_id, websocket)
        reset_namespace(token)
        await _safe_close_websocket(websocket)


@router.get('/defaults', response_model=schemas.EngineDefaults, mcp=True)
@handle_errors(operation='get engine defaults')
def get_engine_defaults():
    """Get default engine resource settings from environment configuration."""
    from core.config import settings

    return schemas.EngineDefaults(
        max_threads=settings.polars_max_threads,
        max_memory_mb=settings.polars_max_memory_mb,
        streaming_chunk_size=settings.polars_streaming_chunk_size,
    )


@router.post('/export', mcp=True)
@handle_errors(operation='export data')
def export_data(
    request: schemas.ExportRequest,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Export pipeline results to a file download or output datasource.

    For destination='download': returns file bytes in the requested format (csv, parquet, json, etc.).
    For destination='datasource': writes to an Iceberg output datasource (requires result_id and iceberg_options).
    """
    if request.destination == schemas.ExportDestination.DOWNLOAD:
        file_bytes, filename, content_type = service.download_step(
            session=session,
            manager=manager,
            target_step_id=request.target_step_id,
            analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
            export_format=request.format.value,
            filename=request.filename,
            analysis_id=request.analysis_id,
            tab_id=request.tab_id,
        )
        safe_name = quote(filename)
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={'Content-Disposition': f'attachment; filename="{safe_name}"'},
        )

    result = service.export_data(
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


@router.post('/download', mcp=True)
@handle_errors(operation='download step')
def download_step(
    request: schemas.DownloadRequest,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Download pipeline step result as a file.

    Returns the file bytes with appropriate Content-Type header.
    Supported formats: csv, parquet, json, ndjson, duckdb, excel.
    """
    file_bytes, filename, content_type = service.download_step(
        session=session,
        manager=manager,
        target_step_id=request.target_step_id,
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        export_format=request.format.value,
        filename=request.filename,
        analysis_id=request.analysis_id,
        tab_id=request.tab_id,
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
