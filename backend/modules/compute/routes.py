from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.error_handlers import handle_errors
from core.exceptions import EngineNotFoundError
from modules.compute import schemas, service
from modules.compute.manager import get_manager

router = APIRouter(prefix='/compute', tags=['compute'])


@router.post('/preview', response_model=schemas.StepPreviewResponse)
@handle_errors(operation='preview step')
async def preview_step(
    request: schemas.StepPreviewRequest,
    session: AsyncSession = Depends(get_db),
):
    """Preview the result of a pipeline step with pagination."""
    resource_config = None
    if request.resource_config:
        resource_config = request.resource_config.model_dump()

    return await service.preview_step(
        session=session,
        datasource_id=request.datasource_id,
        pipeline_steps=request.pipeline_steps,
        target_step_id=request.target_step_id,
        row_limit=request.row_limit,
        page=request.page,
        analysis_id=request.analysis_id,
        resource_config=resource_config,
    )


@router.post('/schema', response_model=schemas.StepSchemaResponse)
@handle_errors(operation='get step schema')
async def get_step_schema(
    request: schemas.StepSchemaRequest,
    session: AsyncSession = Depends(get_db),
):
    """Get the output schema of a pipeline step (for pivot/unpivot dynamic columns)."""
    return await service.get_step_schema(
        session=session,
        datasource_id=request.datasource_id,
        pipeline_steps=request.pipeline_steps,
        target_step_id=request.target_step_id,
        analysis_id=request.analysis_id,
    )


# Engine lifecycle endpoints


@router.post('/engine/spawn/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='spawn engine')
def spawn_engine(analysis_id: str, request: schemas.SpawnEngineRequest | None = None):
    """Spawn a compute engine for an analysis (called when analysis page opens).

    Optionally accepts resource configuration overrides.
    """
    manager = get_manager()
    resource_config = None
    if request and request.resource_config:
        resource_config = request.resource_config.model_dump()
    manager.spawn_engine(analysis_id, resource_config=resource_config)
    return manager.get_engine_status(analysis_id)


@router.post('/engine/keepalive/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='keepalive engine')
def keepalive(analysis_id: str):
    """Send keepalive ping for an analysis engine."""
    manager = get_manager()
    info = manager.keepalive(analysis_id)
    if not info:
        raise EngineNotFoundError(analysis_id)
    return manager.get_engine_status(analysis_id)


@router.post('/engine/configure/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='configure engine')
def configure_engine(analysis_id: str, request: schemas.EngineResourceConfig):
    """Update engine resource configuration (restarts the engine).

    This will terminate any running jobs and restart the engine with the new
    resource configuration. Values set to null will use the default from settings.
    """
    manager = get_manager()
    resource_config = request.model_dump()
    manager.restart_engine_with_config(analysis_id, resource_config)
    return manager.get_engine_status(analysis_id)


@router.get('/engine/status/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='get engine status')
def get_engine_status(analysis_id: str):
    """Get the status of an analysis engine."""
    manager = get_manager()
    return manager.get_engine_status(analysis_id)


@router.delete('/engine/{analysis_id}')
@handle_errors(operation='shutdown engine')
def shutdown_engine(analysis_id: str):
    """Shutdown an analysis engine."""
    manager = get_manager()
    engine = manager.get_engine(analysis_id)
    if not engine:
        raise EngineNotFoundError(analysis_id)
    manager.shutdown_engine(analysis_id)
    return {'message': f'Engine for analysis {analysis_id} shutdown successfully'}


@router.get('/engines', response_model=schemas.EngineListSchema)
@handle_errors(operation='list engines')
def list_engines():
    """List all active engines with their status."""
    manager = get_manager()
    statuses = manager.list_all_engine_statuses()
    return {'engines': statuses, 'total': len(statuses)}


@router.get('/defaults', response_model=schemas.EngineDefaultsResponse)
@handle_errors(operation='get engine defaults')
def get_engine_defaults():
    """Get default engine resource settings from environment configuration."""
    from core.config import settings

    return schemas.EngineDefaultsResponse(
        max_threads=settings.polars_max_threads,
        max_memory_mb=settings.polars_max_memory_mb,
        streaming_chunk_size=settings.polars_streaming_chunk_size,
    )


@router.post('/export')
@handle_errors(operation='export data')
async def export_data(
    request: schemas.ExportRequest,
    session: AsyncSession = Depends(get_db),
):
    """Export pipeline result to file (download or save to filesystem)."""
    file_bytes, filename, content_type = await service.export_data(
        session=session,
        datasource_id=request.datasource_id,
        pipeline_steps=request.pipeline_steps,
        target_step_id=request.target_step_id,
        export_format=request.format.value,
        filename=request.filename,
        destination=request.destination.value,
        analysis_id=request.analysis_id,
    )

    if request.destination == schemas.ExportDestination.DOWNLOAD:
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    else:
        # Filesystem destination - save to exports directory
        from core.config import settings

        file_path = settings.exports_dir / filename

        with open(file_path, 'wb') as f:
            f.write(file_bytes)

        return schemas.ExportResponse(
            success=True,
            filename=filename,
            format=request.format.value,
            destination=request.destination.value,
            file_path=str(file_path.absolute()),
            message=f'File saved to {file_path.absolute()}',
        )
