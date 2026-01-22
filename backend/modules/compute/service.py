import logging
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import (
    DataSourceNotFoundError,
    EngineTimeoutError,
    JobNotFoundError,
    PipelineExecutionError,
    StepNotFoundError,
    UnsupportedExportFormatError,
)
from modules.compute.manager import get_manager
from modules.compute.schemas import ComputeResultSchema, ComputeStatusSchema, JobStatus
from modules.datasource.models import DataSource

logger = logging.getLogger(__name__)

# Job tracking with TTL
_job_results: dict[str, dict] = {}
_job_status: dict[str, dict] = {}
_job_timestamps: dict[str, datetime] = {}
_job_lock = threading.Lock()


def _cleanup_single_job(job_id: str) -> None:
    """Internal helper to clean up a single job (must be called with lock held)."""
    _job_status.pop(job_id, None)
    _job_results.pop(job_id, None)
    _job_timestamps.pop(job_id, None)


def cleanup_old_jobs() -> int:
    """Clean up jobs that have exceeded their TTL. Returns count of cleaned jobs."""
    with _job_lock:
        now = datetime.now(UTC)
        cleaned = 0
        for job_id in list(_job_timestamps.keys()):
            timestamp = _job_timestamps.get(job_id)
            if timestamp and (now - timestamp).total_seconds() > settings.job_ttl:
                _cleanup_single_job(job_id)
                cleaned += 1
                logger.debug(f'Cleaned up expired job {job_id}')
        return cleaned


def enforce_job_size_limit() -> int:
    """Enforce maximum jobs in memory by removing oldest jobs. Returns count of cleaned jobs."""
    with _job_lock:
        if len(_job_timestamps) <= settings.max_jobs_in_memory:
            return 0

        # Sort by timestamp and remove oldest jobs
        sorted_jobs = sorted(_job_timestamps.items(), key=lambda x: x[1])
        to_remove = len(sorted_jobs) - settings.max_jobs_in_memory
        cleaned = 0

        for job_id, _ in sorted_jobs[:to_remove]:
            _cleanup_single_job(job_id)
            cleaned += 1
            logger.debug(f'Cleaned up job {job_id} due to size limit')

        return cleaned


def cleanup_jobs_for_engine(analysis_id: str) -> int:
    """Clean up all jobs associated with an engine. Returns count of cleaned jobs."""
    with _job_lock:
        cleaned = 0
        for job_id in list(_job_status.keys()):
            if _job_status[job_id].get('analysis_id') == analysis_id:
                _cleanup_single_job(job_id)
                cleaned += 1
                logger.debug(f'Cleaned up job {job_id} for engine {analysis_id}')
        return cleaned


async def _get_additional_datasources(session: AsyncSession, pipeline_steps: list[dict]) -> dict[str, dict]:
    """Extract and fetch additional datasources referenced in pipeline steps (e.g., for joins)."""
    additional: dict[str, dict] = {}

    for step in pipeline_steps:
        config = step.get('config', {})
        right_source_id = config.get('right_source') or config.get('rightDataSource')

        union_sources = config.get('sources', [])
        if isinstance(union_sources, str):
            union_sources = [union_sources]

        if right_source_id and right_source_id not in additional:
            result = await session.execute(select(DataSource).where(DataSource.id == right_source_id))
            datasource = result.scalar_one_or_none()
            if datasource:
                additional[right_source_id] = {
                    'source_type': datasource.source_type,
                    **datasource.config,
                }

        for source_id in union_sources:
            if source_id in additional:
                continue
            result = await session.execute(select(DataSource).where(DataSource.id == source_id))
            datasource = result.scalar_one_or_none()
            if datasource:
                additional[source_id] = {
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
    """
    Execute a data analysis pipeline asynchronously.

    Args:
        session: Database session
        analysis_id: Unique identifier for the analysis
        datasource_id: ID of the datasource to analyze
        pipeline_steps: List of pipeline step configurations

    Returns:
        ComputeStatusSchema with job status and metadata

    Raises:
        DataSourceNotFoundError: If datasource doesn't exist
        PipelineExecutionError: If pipeline execution fails
    """
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

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

    with _job_lock:
        # Cleanup old jobs before adding new one
        cleanup_old_jobs()
        enforce_job_size_limit()

        _job_status[job_id] = {
            'job_id': job_id,
            'analysis_id': analysis_id,
            'status': JobStatus.PENDING,
            'progress': 0.0,
            'current_step': None,
            'error_message': None,
            'process_id': engine.process.pid if engine.process else None,
        }
        _job_timestamps[job_id] = datetime.now(UTC)

    logger.info(f'Started job {job_id} for analysis {analysis_id}')
    return ComputeStatusSchema.model_validate(_job_status[job_id])


async def preview_step(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    row_limit: int = 1000,
    page: int = 1,
    timeout: int | None = None,
    analysis_id: str | None = None,
):
    """Preview the result of executing pipeline up to a specific step with pagination."""
    from modules.compute.schemas import StepPreviewResponse

    if timeout is None:
        timeout = settings.job_timeout

    if not analysis_id:
        raise ValueError('analysis_id is required for preview')

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find the step index by step_id
    step_index = None
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            step_index = idx
            break

    if step_index is None:
        raise StepNotFoundError(target_step_id)

    preview_steps = pipeline_steps[: step_index + 1]

    manager = get_manager()
    engine = manager.get_engine(analysis_id)
    if not engine:
        engine = manager.get_or_create_engine(analysis_id)

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

    start_time = time.time()
    while True:
        # Check timeout
        if time.time() - start_time > timeout:
            raise EngineTimeoutError(f'Preview operation timed out after {timeout} seconds', timeout)

        result_data = engine.get_result(timeout=1.0)
        if result_data:
            if result_data['status'] == JobStatus.COMPLETED:
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
                raise PipelineExecutionError(
                    f'Preview failed: {result_data.get("error", "Unknown error")}',
                    details={'operation': 'preview', 'datasource_id': datasource_id},
                )


def get_job_status(job_id: str) -> ComputeStatusSchema:
    """
    Get the current status of a compute job.

    This function polls the engine for updates and refreshes the cached status.

    Args:
        job_id: Unique identifier for the job

    Returns:
        ComputeStatusSchema with current job status

    Raises:
        JobNotFoundError: If job doesn't exist or has been cleaned up
    """
    # Periodic cleanup when accessing jobs
    cleanup_old_jobs()

    manager = get_manager()

    for analysis_id in manager.list_engines():
        engine = manager.get_engine(analysis_id)
        if engine and engine.current_job_id == job_id:
            result = engine.get_result(timeout=0.1)
            if result:
                with _job_lock:
                    _job_status[job_id] = result
                    _job_timestamps[job_id] = datetime.now(UTC)
                    if result.get('data'):
                        _job_results[job_id] = result

    with _job_lock:
        if job_id not in _job_status:
            raise JobNotFoundError(job_id)
        status_data = _job_status[job_id]

    return ComputeStatusSchema.model_validate(status_data)


def get_job_result(job_id: str) -> ComputeResultSchema:
    """Get the result of a completed job."""
    with _job_lock:
        if job_id not in _job_results:
            raise JobNotFoundError(job_id)

        result = _job_results[job_id]
        # Update timestamp on access
        _job_timestamps[job_id] = datetime.now(UTC)

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
            with _job_lock:
                _job_status[job_id] = {
                    'job_id': job_id,
                    'status': JobStatus.CANCELLED,
                    'progress': 0.0,
                    'current_step': None,
                    'error_message': 'Job cancelled by user',
                    'process_id': None,
                }
                _job_timestamps[job_id] = datetime.now(UTC)
            return

    raise JobNotFoundError(job_id)


def cleanup_job(job_id: str) -> None:
    """Clean up job data from memory."""
    with _job_lock:
        _cleanup_single_job(job_id)
    logger.debug(f'Cleaned up job {job_id}')


async def get_step_schema(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    analysis_id: str,
    timeout: int | None = None,
) -> dict:
    """Get the output schema of a pipeline step without returning data."""
    from modules.compute.schemas import StepSchemaResponse

    if timeout is None:
        timeout = settings.job_timeout

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find the step index by step_id
    step_index = None
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            step_index = idx
            break

    if step_index is None:
        raise StepNotFoundError(target_step_id)

    schema_steps = pipeline_steps[: step_index + 1]

    manager = get_manager()
    engine = manager.get_engine(analysis_id)
    if not engine:
        engine = manager.get_or_create_engine(analysis_id)

    datasource_config = {
        'source_type': datasource.source_type,
        **datasource.config,
    }

    additional_datasources = await _get_additional_datasources(session, schema_steps)

    engine.execute(
        datasource_config=datasource_config,
        pipeline_steps=schema_steps,
        additional_datasources=additional_datasources,
    )

    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            raise EngineTimeoutError(f'Schema operation timed out after {timeout} seconds', timeout)

        result_data = engine.get_result(timeout=1.0)
        if result_data:
            if result_data['status'] == JobStatus.COMPLETED:
                schema = result_data['data'].get('schema', {})
                return StepSchemaResponse(
                    step_id=target_step_id,
                    columns=list(schema.keys()),
                    column_types=schema,
                )
            elif result_data['status'] == JobStatus.FAILED:
                raise PipelineExecutionError(
                    f'Schema fetch failed: {result_data.get("error", "Unknown error")}',
                    details={'operation': 'schema', 'datasource_id': datasource_id},
                )


async def export_data(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    export_format: str = 'csv',
    filename: str = 'export',
    destination: str = 'download',
    timeout: int | None = None,
    analysis_id: str | None = None,
) -> tuple[bytes, str, str]:
    """
    Export pipeline result to file.
    Returns (file_bytes, filename_with_ext, content_type).
    """
    import io

    import polars as pl

    if timeout is None:
        timeout = settings.job_timeout

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find steps up to target
    step_index = None
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            step_index = idx
            break

    if step_index is None:
        raise StepNotFoundError(target_step_id)

    export_steps = pipeline_steps[: step_index + 1]

    manager = get_manager()

    # Use analysis engine if provided and exists, otherwise create temporary one
    temp_engine = False
    if analysis_id:
        engine = manager.get_engine(analysis_id)
        if not engine:
            engine = manager.get_or_create_engine(analysis_id)
    else:
        engine = manager.get_or_create_engine(f'{datasource_id}_export')
        temp_engine = True

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

    start_time = time.time()
    temp_engine_id = f'{datasource_id}_export'
    while True:
        # Check timeout
        if time.time() - start_time > timeout:
            if temp_engine:
                manager.shutdown_engine(temp_engine_id)
            raise EngineTimeoutError(f'Export operation timed out after {timeout} seconds', timeout)

        result_data = engine.get_result(timeout=1.0)
        if result_data:
            if result_data['status'] == JobStatus.COMPLETED:
                if temp_engine:
                    manager.shutdown_engine(temp_engine_id)

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
                    raise UnsupportedExportFormatError(export_format)

                buffer.seek(0)
                return buffer.read(), f'{filename}{ext}', content_type

            elif result_data['status'] == JobStatus.FAILED:
                if temp_engine:
                    manager.shutdown_engine(temp_engine_id)
                raise PipelineExecutionError(
                    f'Export failed: {result_data.get("error", "Unknown error")}',
                    details={'operation': 'export', 'datasource_id': datasource_id, 'export_format': export_format},
                )
