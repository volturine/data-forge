from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.error_handlers import handle_errors
from core.exceptions import EngineNotFoundError
from modules.analysis import schemas as analysis_schemas, service as analysis_service
from modules.compute import schemas, service
from modules.compute.manager import get_manager

router = APIRouter(prefix='/compute', tags=['compute'])


@router.post('/execute', response_model=schemas.ComputeStatusSchema)
@handle_errors(operation='execute analysis')
async def execute_analysis(
    request: schemas.ComputeExecuteSchema,
    session: AsyncSession = Depends(get_db),
):
    """Execute a data analysis pipeline for a saved analysis."""
    analysis = await analysis_service.get_analysis(session, request.analysis_id)
    datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
    if not datasource_ids:
        raise HTTPException(status_code=400, detail='Analysis has no linked datasource')

    datasource_id = datasource_ids[0]
    pipeline_steps = analysis.pipeline_definition.get('steps', [])
    if not pipeline_steps:
        tabs = analysis.pipeline_definition.get('tabs', [])
        pipeline_steps = [step for tab in tabs for step in tab.get('steps', [])]

    job = await service.execute_analysis(
        session=session,
        analysis_id=request.analysis_id,
        datasource_id=datasource_id,
        pipeline_steps=pipeline_steps,
    )

    # Mark analysis status running
    await analysis_service.update_analysis(
        session=session,
        analysis_id=request.analysis_id,
        data=analysis_schemas.AnalysisUpdateSchema(status='running'),
    )

    return job


@router.post('/preview', response_model=schemas.StepPreviewResponse)
@handle_errors(operation='preview step')
async def preview_step(
    request: schemas.StepPreviewRequest,
    session: AsyncSession = Depends(get_db),
):
    """Preview the result of a pipeline step with pagination."""
    return await service.preview_step(
        session=session,
        datasource_id=request.datasource_id,
        pipeline_steps=request.pipeline_steps,
        target_step_id=request.target_step_id,
        row_limit=request.row_limit,
        page=request.page,
        analysis_id=request.analysis_id,
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


@router.get('/status/{job_id}', response_model=schemas.ComputeStatusSchema)
@handle_errors(operation='get job status')
def get_job_status(job_id: str):
    """Get the status of a compute job."""
    return service.get_job_status(job_id)


@router.get('/result/{job_id}', response_model=schemas.ComputeResultSchema)
@handle_errors(operation='get job result')
def get_job_result(job_id: str):
    """Get the result of a completed job."""
    return service.get_job_result(job_id)


@router.delete('/{job_id}')
@handle_errors(operation='cancel job')
def cancel_job(job_id: str):
    """Cancel a running compute job."""
    service.cancel_job(job_id)
    return {'message': f'Job {job_id} cancelled successfully'}


@router.delete('/{job_id}/cleanup')
@handle_errors(operation='cleanup job')
def cleanup_job(job_id: str):
    """Clean up job data from memory."""
    service.cleanup_job(job_id)
    return {'message': f'Job {job_id} cleaned up successfully'}


# Engine lifecycle endpoints


@router.post('/engine/spawn/{analysis_id}', response_model=schemas.EngineStatusSchema)
@handle_errors(operation='spawn engine')
def spawn_engine(analysis_id: str):
    """Spawn a compute engine for an analysis (called when analysis page opens)."""
    manager = get_manager()
    manager.spawn_engine(analysis_id)
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
