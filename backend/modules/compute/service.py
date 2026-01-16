from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.compute.manager import get_manager
from modules.compute.schemas import ComputeResultSchema, ComputeStatusSchema, JobStatus
from modules.datasource.models import DataSource

_job_results: dict[str, dict] = {}
_job_status: dict[str, dict] = {}


async def execute_analysis(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
) -> ComputeStatusSchema:
    """Execute a data analysis pipeline."""
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    manager = get_manager()
    engine = manager.get_or_create_engine(datasource_id)

    datasource_config = {
        'source_type': datasource.source_type,
        **datasource.config,
    }

    job_id = engine.execute(
        datasource_config=datasource_config,
        pipeline_steps=pipeline_steps,
        timeout=300,
    )

    _job_status[job_id] = {
        'job_id': job_id,
        'status': JobStatus.PENDING,
        'progress': 0.0,
        'current_step': None,
        'error_message': None,
        'process_id': engine.process.pid if engine.process else None,
    }

    return ComputeStatusSchema.model_validate(_job_status[job_id])


async def preview_step(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    step_index: int,
) -> dict:
    """Preview the result of executing pipeline up to a specific step."""
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    preview_steps = pipeline_steps[: step_index + 1]

    manager = get_manager()
    engine = manager.get_or_create_engine(f'{datasource_id}_preview')

    datasource_config = {
        'source_type': datasource.source_type,
        **datasource.config,
    }

    engine.execute(
        datasource_config=datasource_config,
        pipeline_steps=preview_steps,
        timeout=300,
    )

    while True:
        result_data = engine.get_result(timeout=1.0)
        if result_data:
            if result_data['status'] == JobStatus.COMPLETED:
                manager.shutdown_engine(f'{datasource_id}_preview')
                return result_data['data']
            elif result_data['status'] == JobStatus.FAILED:
                manager.shutdown_engine(f'{datasource_id}_preview')
                raise ValueError(f'Preview failed: {result_data.get("error", "Unknown error")}')


def get_job_status(job_id: str) -> ComputeStatusSchema:
    """Get the status of a compute job."""
    manager = get_manager()

    for analysis_id in manager.list_engines():
        engine = manager.get_engine(analysis_id)
        if engine and engine.current_job_id == job_id:
            result = engine.get_result(timeout=0.1)
            if result:
                _job_status[job_id] = result
                if result.get('data'):
                    _job_results[job_id] = result

    if job_id not in _job_status:
        raise ValueError(f'Job {job_id} not found')

    return ComputeStatusSchema.model_validate(_job_status[job_id])


def get_job_result(job_id: str) -> ComputeResultSchema:
    """Get the result of a completed job."""
    if job_id not in _job_results:
        raise ValueError(f'Job {job_id} result not found')

    result = _job_results[job_id]

    return ComputeResultSchema(
        job_id=job_id,
        status=result['status'],
        data=result.get('data'),
        error=result.get('error'),
    )


def cancel_job(job_id: str) -> None:
    """Cancel a running job."""
    manager = get_manager()

    for analysis_id in manager.list_engines():
        engine = manager.get_engine(analysis_id)
        if engine and engine.current_job_id == job_id:
            manager.shutdown_engine(analysis_id)
            _job_status[job_id] = {
                'job_id': job_id,
                'status': JobStatus.CANCELLED,
                'progress': 0.0,
                'current_step': None,
                'error_message': 'Job cancelled by user',
                'process_id': None,
            }
            return

    raise ValueError(f'Job {job_id} not found or already completed')


def cleanup_job(job_id: str) -> None:
    """Clean up job data from memory."""
    if job_id in _job_status:
        del _job_status[job_id]
    if job_id in _job_results:
        del _job_results[job_id]
