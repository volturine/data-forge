from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.analysis import schemas as analysis_schemas, service as analysis_service
from modules.compute import schemas, service
from modules.compute.manager import get_manager

router = APIRouter(prefix='/compute', tags=['compute'])


@router.post('/execute', response_model=schemas.ComputeStatusSchema)
async def execute_analysis(
    request: schemas.ComputeExecuteSchema,
    session: AsyncSession = Depends(get_db),
):
    """Execute a data analysis pipeline for a saved analysis."""
    try:
        analysis = await analysis_service.get_analysis(session, request.analysis_id)
        datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
        if not datasource_ids:
            raise HTTPException(status_code=400, detail='Analysis has no linked datasource')

        datasource_id = datasource_ids[0]
        pipeline_steps = analysis.pipeline_definition.get('steps', [])

        job = await service.execute_analysis(
            session=session,
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
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to execute analysis: {str(e)}')


@router.post('/preview', response_model=schemas.StepPreviewResponse)
async def preview_step(
    request: schemas.StepPreviewRequest,
    session: AsyncSession = Depends(get_db),
):
    """Preview the result of a pipeline step with pagination."""
    try:
        return await service.preview_step(
            session=session,
            datasource_id=request.datasource_id,
            pipeline_steps=request.pipeline_steps,
            target_step_id=request.target_step_id,
            row_limit=request.row_limit,
            page=request.page,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to preview step: {str(e)}')


@router.get('/status/{job_id}', response_model=schemas.ComputeStatusSchema)
async def get_job_status(job_id: str):
    """Get the status of a compute job."""
    try:
        return service.get_job_status(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get job status: {str(e)}')


@router.get('/result/{job_id}', response_model=schemas.ComputeResultSchema)
async def get_job_result(job_id: str):
    """Get the result of a completed job."""
    try:
        return service.get_job_result(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get job result: {str(e)}')


@router.delete('/{job_id}')
async def cancel_job(job_id: str):
    """Cancel a running compute job."""
    try:
        service.cancel_job(job_id)
        return {'message': f'Job {job_id} cancelled successfully'}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to cancel job: {str(e)}')


@router.delete('/{job_id}/cleanup')
async def cleanup_job(job_id: str):
    """Clean up job data from memory."""
    try:
        service.cleanup_job(job_id)
        return {'message': f'Job {job_id} cleaned up successfully'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to cleanup job: {str(e)}')


# Engine lifecycle endpoints


@router.post('/engine/spawn/{analysis_id}', response_model=schemas.EngineStatusSchema)
async def spawn_engine(analysis_id: str):
    """Spawn a compute engine for an analysis (called when analysis page opens)."""
    try:
        manager = get_manager()
        manager.spawn_engine(analysis_id)
        return manager.get_engine_status(analysis_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to spawn engine: {str(e)}')


@router.post('/engine/keepalive/{analysis_id}', response_model=schemas.EngineStatusSchema)
async def keepalive(analysis_id: str):
    """Send keepalive ping for an analysis engine."""
    manager = get_manager()
    info = manager.keepalive(analysis_id)
    if not info:
        raise HTTPException(status_code=404, detail=f'No engine found for analysis {analysis_id}')
    return manager.get_engine_status(analysis_id)


@router.get('/engine/status/{analysis_id}', response_model=schemas.EngineStatusSchema)
async def get_engine_status(analysis_id: str):
    """Get the status of an analysis engine."""
    manager = get_manager()
    return manager.get_engine_status(analysis_id)


@router.delete('/engine/{analysis_id}')
async def shutdown_engine(analysis_id: str):
    """Shutdown an analysis engine."""
    manager = get_manager()
    engine = manager.get_engine(analysis_id)
    if not engine:
        raise HTTPException(status_code=404, detail=f'No engine found for analysis {analysis_id}')
    manager.shutdown_engine(analysis_id)
    return {'message': f'Engine for analysis {analysis_id} shutdown successfully'}
