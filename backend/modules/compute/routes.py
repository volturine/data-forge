from urllib.parse import quote

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from core.database import get_db
from core.dependencies import get_manager
from core.error_handlers import handle_errors
from core.exceptions import EngineNotFoundError
from core.namespace import reset_namespace, set_namespace_context
from core.validation import AnalysisId, DataSourceId, parse_analysis_id, parse_datasource_id
from modules.compute import schemas, service
from modules.compute.manager import ProcessManager
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/compute', tags=['compute'])


def _get_websocket_manager(websocket: WebSocket) -> ProcessManager:
    override = websocket.app.dependency_overrides.get(get_manager)
    if override is not None:
        return override()
    return websocket.app.state.manager


def _run_compute_websocket_action(
    message: schemas.ComputeWebsocketRequest,
    manager: ProcessManager,
    namespace: str | None,
) -> dict:
    token = set_namespace_context(namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        response: BaseModel
        if message.action == schemas.ComputeWebsocketAction.PREVIEW:
            preview_request = schemas.StepPreviewRequest.model_validate(message.payload)
            response = preview_step(request=preview_request, session=session, manager=manager)
        elif message.action == schemas.ComputeWebsocketAction.SCHEMA:
            schema_request = schemas.StepSchemaRequest.model_validate(message.payload)
            response = get_step_schema(request=schema_request, session=session, manager=manager)
        elif message.action == schemas.ComputeWebsocketAction.ROW_COUNT:
            row_count_request = schemas.StepRowCountRequest.model_validate(message.payload)
            response = get_step_row_count(request=row_count_request, session=session, manager=manager)
        elif message.action == schemas.ComputeWebsocketAction.BUILD:
            build_request = schemas.BuildRequest.model_validate(message.payload)
            response = build_analysis_from_payload(request=build_request, session=session, manager=manager)
        else:
            raise ValueError(f'Unsupported websocket action: {message.action}')
        return response.model_dump(mode='json')
    finally:
        session.close()
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
    analysis_id = request.analysis_id or request.analysis_pipeline.analysis_id

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
    analysis_id = request.analysis_id or request.analysis_pipeline.analysis_id

    return service.get_step_schema(
        session=session,
        manager=manager,
        target_step_id=request.target_step_id,
        analysis_id=analysis_id or '',
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
    analysis_id = request.analysis_id or request.analysis_pipeline.analysis_id

    return service.get_step_row_count(
        session=session,
        manager=manager,
        target_step_id=request.target_step_id,
        analysis_id=analysis_id or '',
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


@router.post('/build', response_model=schemas.BuildResponse, mcp=True)
@handle_errors(operation='build analysis')
def build_analysis_from_payload(
    request: schemas.BuildRequest,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Build (export) an analysis from a pipeline payload.

    Executes the pipeline and writes results to output datasources.
    Requires analysis_pipeline with tabs and optionally tab_id to build a specific tab.
    """
    pipeline = request.analysis_pipeline.model_dump(mode='json') if request.analysis_pipeline else None
    if not isinstance(pipeline, dict):
        raise ValueError('analysis_pipeline is required')
    pipeline = {**pipeline, 'tab_id': request.tab_id}
    result = service.run_analysis_build_from_payload(session, manager, pipeline)
    return schemas.BuildResponse(**result)


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


@router.get('/engine/status/{analysis_id}', response_model=schemas.EngineStatusSchema, mcp=True)
@handle_errors(operation='get engine status')
def get_engine_status(analysis_id: AnalysisId, manager: ProcessManager = Depends(get_manager)):
    """Get the status of an analysis engine."""
    return manager.get_engine_status(parse_analysis_id(analysis_id))


@router.delete('/engine/{analysis_id}', status_code=204, mcp=True)
@handle_errors(operation='shutdown engine')
def shutdown_engine(analysis_id: AnalysisId, manager: ProcessManager = Depends(get_manager)):
    """Shutdown an analysis engine."""
    analysis_id_value = parse_analysis_id(analysis_id)
    engine = manager.get_engine(analysis_id_value)
    if not engine:
        raise EngineNotFoundError(analysis_id_value)
    manager.shutdown_engine(analysis_id_value)
    return None


@router.get('/engines', response_model=schemas.EngineListSchema, mcp=True)
@handle_errors(operation='list engines')
def list_engines(manager: ProcessManager = Depends(get_manager)):
    """List all active engines with their status."""
    statuses = manager.list_all_engine_statuses()
    return {'engines': statuses, 'total': len(statuses)}


@router.websocket('/ws')
async def compute_websocket(
    websocket: WebSocket,
):
    manager = _get_websocket_manager(websocket)
    await websocket.accept()
    action: schemas.ComputeWebsocketAction | None = None
    try:
        raw_message = await websocket.receive_json()
        message = schemas.ComputeWebsocketRequest.model_validate(raw_message)
        action = message.action
        await websocket.send_json(schemas.ComputeWebsocketStartedMessage(action=message.action).model_dump(mode='json'))
        result = await run_in_threadpool(
            _run_compute_websocket_action,
            message,
            manager,
            websocket.query_params.get('namespace'),
        )
        await websocket.send_json(schemas.ComputeWebsocketResultMessage(action=message.action, data=result).model_dump(mode='json'))
    except WebSocketDisconnect:
        return
    except ValidationError as exc:
        await websocket.send_json(
            schemas.ComputeWebsocketErrorMessage(
                error=str(exc),
                status_code=400,
            ).model_dump(mode='json')
        )
    except HTTPException as exc:
        await websocket.send_json(
            schemas.ComputeWebsocketErrorMessage(
                action=action,
                error=str(exc.detail),
                status_code=exc.status_code,
            ).model_dump(mode='json')
        )
    except Exception as exc:
        await websocket.send_json(
            schemas.ComputeWebsocketErrorMessage(
                action=action,
                error=str(exc),
            ).model_dump(mode='json')
        )
    finally:
        await websocket.close()


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
