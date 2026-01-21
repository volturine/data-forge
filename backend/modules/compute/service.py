import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.compute.manager import get_manager
from modules.compute.schemas import ComputeResultSchema, ComputeStatusSchema, JobStatus
from modules.datasource.models import DataSource

logger = logging.getLogger(__name__)

# Job tracking
_job_results: dict[str, dict] = {}
_job_status: dict[str, dict] = {}


def cleanup_jobs_for_engine(analysis_id: str) -> int:
    """Clean up all jobs associated with an engine. Returns count of cleaned jobs."""
    cleaned = 0
    for job_id in list(_job_status.keys()):
        if _job_status[job_id].get('analysis_id') == analysis_id:
            _job_status.pop(job_id, None)
            _job_results.pop(job_id, None)
            cleaned += 1
            logger.debug(f'Cleaned up job {job_id} for engine {analysis_id}')
    return cleaned


async def _get_additional_datasources(session: AsyncSession, pipeline_steps: list[dict]) -> dict[str, dict]:
    """Extract and fetch additional datasources referenced in pipeline steps (e.g., for joins)."""
    additional: dict[str, dict] = {}

    for step in pipeline_steps:
        config = step.get('config', {})
        right_source_id = config.get('right_source') or config.get('rightDataSource')

        if right_source_id and right_source_id not in additional:
            result = await session.execute(select(DataSource).where(DataSource.id == right_source_id))
            datasource = result.scalar_one_or_none()
            if datasource:
                additional[right_source_id] = {
                    'source_type': datasource.source_type,
                    **datasource.config,
                }

    return additional


async def execute_analysis(
    session: AsyncSession,
    analysis_id: str,
    datasource_id: str,
    pipeline_steps: list[dict],
) -> ComputeStatusSchema:
    """Execute a data analysis pipeline."""
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    manager = get_manager()
    engine = manager.get_or_create_engine(analysis_id)

    datasource_config = {
        'source_type': datasource.source_type,
        **datasource.config,
    }

    additional_datasources = await _get_additional_datasources(session, pipeline_steps)

    job_id = engine.execute(
        datasource_config=datasource_config,
        pipeline_steps=pipeline_steps,
        additional_datasources=additional_datasources,
    )

    _job_status[job_id] = {
        'job_id': job_id,
        'analysis_id': analysis_id,
        'status': JobStatus.PENDING,
        'progress': 0.0,
        'current_step': None,
        'error_message': None,
        'process_id': engine.process.pid if engine.process else None,
    }

    logger.info(f'Started job {job_id} for analysis {analysis_id}')
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

    additional_datasources = await _get_additional_datasources(session, preview_steps)

    engine.execute(
        datasource_config=datasource_config,
        pipeline_steps=preview_steps,
        additional_datasources=additional_datasources,
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
                    column_types=schema,
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
    _job_status.pop(job_id, None)
    _job_results.pop(job_id, None)
    logger.debug(f'Cleaned up job {job_id}')


async def export_data(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    export_format: str = 'csv',
    filename: str = 'export',
    destination: str = 'download',
) -> tuple[bytes, str, str]:
    """
    Export pipeline result to file.
    Returns (file_bytes, filename_with_ext, content_type).
    """
    import io

    import polars as pl

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    # Find steps up to target
    step_index = None
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            step_index = idx
            break

    if step_index is None:
        raise ValueError(f'Step with id {target_step_id} not found in pipeline')

    export_steps = pipeline_steps[: step_index + 1]

    manager = get_manager()
    engine = manager.get_or_create_engine(f'{datasource_id}_export')

    datasource_config = {
        'source_type': datasource.source_type,
        **datasource.config,
    }

    additional_datasources = await _get_additional_datasources(session, export_steps)

    engine.execute(
        datasource_config=datasource_config,
        pipeline_steps=export_steps,
        additional_datasources=additional_datasources,
    )

    while True:
        result_data = engine.get_result(timeout=1.0)
        if result_data:
            if result_data['status'] == JobStatus.COMPLETED:
                manager.shutdown_engine(f'{datasource_id}_export')

                sample_data = result_data['data'].get('sample_data', [])
                df = pl.DataFrame(sample_data)

                buffer = io.BytesIO()
                if export_format == 'csv':
                    df.write_csv(buffer)
                    ext = '.csv'
                    content_type = 'text/csv'
                elif export_format == 'parquet':
                    df.write_parquet(buffer)
                    ext = '.parquet'
                    content_type = 'application/octet-stream'
                elif export_format == 'json':
                    df.write_json(buffer)
                    ext = '.json'
                    content_type = 'application/json'
                elif export_format == 'ndjson':
                    df.write_ndjson(buffer)
                    ext = '.ndjson'
                    content_type = 'application/x-ndjson'
                else:
                    raise ValueError(f'Unsupported export format: {export_format}')

                buffer.seek(0)
                return buffer.read(), f'{filename}{ext}', content_type

            elif result_data['status'] == JobStatus.FAILED:
                manager.shutdown_engine(f'{datasource_id}_export')
                raise ValueError(f'Export failed: {result_data.get("error", "Unknown error")}')
