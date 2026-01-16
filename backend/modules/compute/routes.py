from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.compute import schemas, service

router = APIRouter(prefix='/api/v1/compute', tags=['compute'])


class ExecuteRequest(BaseModel):
    datasource_id: str
    pipeline_steps: list[dict]


class PreviewRequest(BaseModel):
    datasource_id: str
    pipeline_steps: list[dict]
    step_index: int


@router.post('/execute', response_model=schemas.ComputeStatusSchema)
async def execute_analysis(
    request: ExecuteRequest,
    session: AsyncSession = Depends(get_db),
):
    """Execute a data analysis pipeline."""
    try:
        return await service.execute_analysis(
            session=session,
            datasource_id=request.datasource_id,
            pipeline_steps=request.pipeline_steps,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to execute analysis: {str(e)}')


@router.post('/preview', response_model=dict)
async def preview_step(
    request: PreviewRequest,
    session: AsyncSession = Depends(get_db),
):
    """Preview the result of a pipeline step."""
    try:
        return await service.preview_step(
            session=session,
            datasource_id=request.datasource_id,
            pipeline_steps=request.pipeline_steps,
            step_index=request.step_index,
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
