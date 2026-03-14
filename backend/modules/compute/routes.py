from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.exceptions import EngineNotFoundError
from core.validation import AnalysisId, DataSourceId, parse_analysis_id, parse_datasource_id
from modules.compute import schemas, service
from modules.compute.manager import get_manager
from modules.mcp.decorators import deterministic_tool

router = APIRouter(prefix='/compute', tags=['compute'])


@router.post('/preview', response_model=schemas.StepPreviewResponse)
@handle_errors(operation='preview step')
@deterministic_tool
def preview_step(
    request: schemas.StepPreviewRequest,
    session: Session = Depends(get_db),
):
    """Preview the result of a pipeline step with pagination."""
    analysis_id = request.analysis_id or request.analysis_pipeline.analysis_id

    return service.preview_step(
        session=session,
        target_step_id=request.target_step_id,
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        row_limit=request.row_limit,
        page=request.page,
        analysis_id=analysis_id,
        resource_config=request.resource_config.model_dump() if request.resource_config else None,
        tab_id=request.tab_id,
        request_json=request.model_dump(mode='json'),
    )


@router.post('/schema', response_model=schemas.StepSchemaResponse)
@handle_errors(operation='get step schema')
@deterministic_tool
def get_step_schema(
    request: schemas.StepSchemaRequest,
    session: Session = Depends(get_db),
):
    """Get the output schema of a pipeline step (for pivot/unpivot dynamic columns)."""
    analysis_id = request.analysis_id or request.analysis_pipeline.analysis_id

    return service.get_step_schema(
        session=session,
        target_step_id=request.target_step_id,
        analysis_id=analysis_id or '',
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        tab_id=request.tab_id,
    )


@router.post('/row-count', response_model=schemas.StepRowCountResponse)
@handle_errors(operation='get step row count')
@deterministic_tool
def get_step_row_count(
    request: schemas.StepRowCountRequest,
    session: Session = Depends(get_db),
):
    """Get the row count of a pipeline step."""
    analysis_id = request.analysis_id or request.analysis_pipeline.analysis_id

    return service.get_step_row_count(
        session=session,
        target_step_id=request.target_step_id,
        analysis_id=analysis_id or '',
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        tab_id=request.tab_id,
        request_json=request.model_dump(mode='json'),
    )


@router.get('/iceberg/{datasource_id}/snapshots', response_model=schemas.IcebergSnapshotsResponse)
@handle_errors(operation='list iceberg snapshots')
@deterministic_tool
def list_iceberg_snapshots(
    datasource_id: DataSourceId,
    branch: str | None = None,
    session: Session = Depends(get_db),
):
    """List snapshots for an Iceberg datasource (for time travel selection)."""
    return service.list_iceberg_snapshots(session, parse_datasource_id(datasource_id), branch=branch)


@router.delete(
    '/iceberg/{datasource_id}/snapshots/{snapshot_id}',
    response_model=schemas.IcebergSnapshotDeleteResponse,
)
@handle_errors(operation='delete iceberg snapshot')
@deterministic_tool
def delete_iceberg_snapshot(
    datasource_id: DataSourceId,
    snapshot_id: int,
    session: Session = Depends(get_db),
):
    """Delete an Iceberg snapshot by ID."""
    return service.delete_iceberg_snapshot(session, parse_datasource_id(datasource_id), str(snapshot_id))


@router.post('/build', response_model=schemas.BuildResponse)
@handle_errors(operation='build analysis')
@deterministic_tool
def build_analysis_from_payload(
    request: schemas.BuildRequest,
    session: Session = Depends(get_db),
):
    pipeline = request.analysis_pipeline.model_dump(mode='json') if request.analysis_pipeline else None
    if not isinstance(pipeline, dict):
        raise ValueError('analysis_pipeline is required')
    pipeline = {**pipeline, 'tab_id': request.tab_id}
    result = service.run_analysis_build_from_payload(session, pipeline)
    return schemas.BuildResponse(**result)


# Engine lifecycle endpoints


@router.post('/engine/spawn/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='spawn engine')
@deterministic_tool
def spawn_engine(analysis_id: AnalysisId, request: schemas.SpawnEngineRequest | None = None):
    """Spawn a compute engine for an analysis (called when analysis page opens).

    Optionally accepts resource configuration overrides.
    """
    manager = get_manager()
    resource_config = request.resource_config.model_dump() if request and request.resource_config else None
    analysis_id_value = parse_analysis_id(analysis_id)
    manager.spawn_engine(analysis_id_value, resource_config=resource_config)
    return manager.get_engine_status(analysis_id_value)


@router.post('/engine/keepalive/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='keepalive engine')
@deterministic_tool
def keepalive(analysis_id: AnalysisId):
    """Send keepalive ping for an analysis engine."""
    manager = get_manager()
    analysis_id_value = parse_analysis_id(analysis_id)
    info = manager.keepalive(analysis_id_value)
    if not info:
        raise EngineNotFoundError(analysis_id_value)
    return manager.get_engine_status(analysis_id_value)


@router.post('/engine/configure/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='configure engine')
@deterministic_tool
def configure_engine(analysis_id: AnalysisId, request: schemas.EngineResourceConfig):
    """Update engine resource configuration (restarts the engine).

    This will terminate any running jobs and restart the engine with the new
    resource configuration. Values set to null will use the default from settings.
    """
    manager = get_manager()
    resource_config = request.model_dump()
    analysis_id_value = parse_analysis_id(analysis_id)
    manager.restart_engine_with_config(analysis_id_value, resource_config)
    return manager.get_engine_status(analysis_id_value)


@router.get('/engine/status/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='get engine status')
@deterministic_tool
def get_engine_status(analysis_id: AnalysisId):
    """Get the status of an analysis engine."""
    manager = get_manager()
    return manager.get_engine_status(parse_analysis_id(analysis_id))


@router.delete('/engine/{analysis_id}', status_code=204)
@handle_errors(operation='shutdown engine')
@deterministic_tool
def shutdown_engine(analysis_id: AnalysisId):
    """Shutdown an analysis engine."""
    manager = get_manager()
    analysis_id_value = parse_analysis_id(analysis_id)
    engine = manager.get_engine(analysis_id_value)
    if not engine:
        raise EngineNotFoundError(analysis_id_value)
    manager.shutdown_engine(analysis_id_value)
    return None


@router.get('/engines', response_model=schemas.EngineListSchema)
@handle_errors(operation='list engines')
@deterministic_tool
def list_engines():
    """List all active engines with their status."""
    manager = get_manager()
    statuses = manager.list_all_engine_statuses()
    return {'engines': statuses, 'total': len(statuses)}


@router.get('/defaults', response_model=schemas.EngineDefaults)
@handle_errors(operation='get engine defaults')
@deterministic_tool
def get_engine_defaults():
    """Get default engine resource settings from environment configuration."""
    from core.config import settings

    return schemas.EngineDefaults(
        max_threads=settings.polars_max_threads,
        max_memory_mb=settings.polars_max_memory_mb,
        streaming_chunk_size=settings.polars_streaming_chunk_size,
    )


@router.post('/export')
@handle_errors(operation='export data')
@deterministic_tool
def export_data(
    request: schemas.ExportRequest,
    session: Session = Depends(get_db),
):
    """Export pipeline result to download or output datasource."""
    if request.destination == schemas.ExportDestination.DOWNLOAD:
        file_bytes, filename, content_type = service.download_step(
            session=session,
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
        target_step_id=request.target_step_id,
        analysis_pipeline=request.analysis_pipeline.model_dump(mode='json'),
        filename=request.filename,
        iceberg_options=request.iceberg_options.model_dump() if request.iceberg_options else None,
        analysis_id=request.analysis_id,
        tab_id=request.tab_id,
        request_json=request.model_dump(mode='json'),
        output_datasource_id=request.output_datasource_id,
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


@router.post('/download')
@handle_errors(operation='download step')
@deterministic_tool
def download_step(
    request: schemas.DownloadRequest,
    session: Session = Depends(get_db),
):
    """Download the result of a pipeline step in a specified format."""
    file_bytes, filename, content_type = service.download_step(
        session=session,
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
