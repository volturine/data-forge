import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.compute.manager import get_manager
from modules.compute.schemas import ComputeResultSchema, ComputeStatusSchema, JobStatus
from modules.datasource.models import DataSource

logger = logging.getLogger(__name__)

# Job tracking with timestamps for TTL cleanup
_job_results: dict[str, dict] = {}
_job_status: dict[str, dict] = {}
_job_timestamps: dict[str, float] = {}


def _cleanup_expired_jobs() -> None:
    """Remove jobs older than TTL from memory."""
    current_time = time.time()
    expired_jobs = [job_id for job_id, timestamp in _job_timestamps.items() if current_time - timestamp > settings.job_ttl]

    for job_id in expired_jobs:
        logger.debug(f'Cleaning up expired job: {job_id}')
        _job_status.pop(job_id, None)
        _job_results.pop(job_id, None)
        _job_timestamps.pop(job_id, None)

    if expired_jobs:
        logger.info(f'Cleaned up {len(expired_jobs)} expired jobs')


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
    _job_timestamps[job_id] = time.time()

    logger.info(f'Started job {job_id} for datasource {datasource_id}')
    return ComputeStatusSchema.model_validate(_job_status[job_id])


async def preview_step(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    row_limit: int = 1000,
    page: int = 1,
):
    """Preview the result of executing pipeline up to a specific step with pagination."""
    from modules.compute.schemas import StepPreviewResponse

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    # Find the step index by step_id
    step_index = None
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            step_index = idx
            break

    if step_index is None:
        raise ValueError(f'Step with id {target_step_id} not found in pipeline')

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
        timeout=30,
    )

    while True:
        result_data = engine.get_result(timeout=1.0)
        if result_data:
            if result_data['status'] == JobStatus.COMPLETED:
                manager.shutdown_engine(f'{datasource_id}_preview')

                # Extract data for pagination
                sample_data = result_data['data'].get('sample_data', [])
                total_rows = result_data['data'].get('row_count', 0)
                schema = result_data['data'].get('schema', {})

                # Apply pagination
                start_idx = (page - 1) * row_limit
                end_idx = start_idx + row_limit
                paginated_data = sample_data[start_idx:end_idx]

                return StepPreviewResponse(
                    step_id=target_step_id,
                    columns=list(schema.keys()),
                    data=paginated_data,
                    total_rows=total_rows,
                    page=page,
                    page_size=len(paginated_data),
                )
            elif result_data['status'] == JobStatus.FAILED:
                manager.shutdown_engine(f'{datasource_id}_preview')
                raise ValueError(f'Preview failed: {result_data.get("error", "Unknown error")}')


def get_job_status(job_id: str) -> ComputeStatusSchema:
    """Get the status of a compute job."""
    # Cleanup expired jobs periodically
    _cleanup_expired_jobs()

    manager = get_manager()

    for analysis_id in manager.list_engines():
        engine = manager.get_engine(analysis_id)
        if engine and engine.current_job_id == job_id:
            result = engine.get_result(timeout=0.1)
            if result:
                _job_status[job_id] = result
                _job_timestamps[job_id] = time.time()  # Update timestamp on activity
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
    _job_status.pop(job_id, None)
    _job_results.pop(job_id, None)
    _job_timestamps.pop(job_id, None)
    logger.debug(f'Cleaned up job {job_id}')
