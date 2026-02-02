import logging
import os
import tempfile

import duckdb
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import DataSourceNotFoundError, PipelineExecutionError
from modules.compute.core.exports import get_export_format
from modules.compute.manager import get_manager
from modules.compute.utils import await_engine_result, build_datasource_config, find_step_index
from modules.datasource.models import DataSource
from modules.udf.models import Udf

logger = logging.getLogger(__name__)


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


async def _hydrate_udfs(session: AsyncSession, pipeline_steps: list[dict]) -> list[dict]:
    next_steps: list[dict] = []
    for step in pipeline_steps:
        if step.get('type') != 'with_columns':
            next_steps.append(step)
            continue
        config = step.get('config', {})
        expressions = config.get('expressions', [])
        if not isinstance(expressions, list):
            next_steps.append(step)
            continue
        updated = []
        for expr in expressions:
            if not isinstance(expr, dict) or expr.get('type') != 'udf':
                updated.append(expr)
                continue
            udf_id = expr.get('udf_id')
            if not udf_id or expr.get('code'):
                updated.append(expr)
                continue
            result = await session.execute(select(Udf).where(Udf.id == udf_id))
            udf = result.scalar_one_or_none()
            if not udf:
                raise ValueError(f'UDF {udf_id} not found')
            updated.append({**expr, 'code': udf.code})
        next_steps.append({**step, 'config': {**config, 'expressions': updated}})
    return next_steps


async def preview_step(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    row_limit: int = 1000,
    page: int = 1,
    timeout: int | None = None,
    analysis_id: str | None = None,
    resource_config: dict | None = None,
):
    """Preview the result of executing pipeline up to a specific step with pagination."""
    from modules.compute.schemas import StepPreviewResponse

    if timeout is None:
        timeout = settings.job_timeout

    if not analysis_id:
        # Create a temporary analysis_id for datasource preview
        analysis_id = f'__preview__{datasource_id}'

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find the step index by step_id
    # Special case: previewing raw datasource (no pipeline steps, target is "source")
    if target_step_id == 'source' and len(pipeline_steps) == 0:
        preview_steps = []
    else:
        step_index = find_step_index(pipeline_steps, target_step_id)
        preview_steps = pipeline_steps[: step_index + 1]
        preview_steps = await _hydrate_udfs(session, preview_steps)

    manager = get_manager()
    # get_or_create_engine will restart the engine if resource_config changed
    engine = manager.get_or_create_engine(analysis_id, resource_config=resource_config)

    datasource_config = build_datasource_config(datasource)

    additional_datasources = await _get_additional_datasources(session, preview_steps)

    # Calculate offset for pagination
    offset = (page - 1) * row_limit

    # Use the new preview method that efficiently fetches only needed rows
    engine.preview(
        datasource_config=datasource_config,
        pipeline_steps=preview_steps,
        row_limit=row_limit,
        offset=offset,
        additional_datasources=additional_datasources,
    )

    result_data = await await_engine_result(engine, timeout)
    error = result_data.get('error')
    if error:
        raise PipelineExecutionError(
            f'Preview failed: {error}',
            details={'operation': 'preview', 'datasource_id': datasource_id},
        )

    data = result_data.get('data', {})
    return StepPreviewResponse(
        step_id=target_step_id,
        columns=list(data.get('schema', {}).keys()),
        column_types=data.get('schema', {}),
        data=data.get('data', []),
        total_rows=data.get('row_count', 0),
        page=page,
        page_size=len(data.get('data', [])),
    )


async def get_step_schema(
    session: AsyncSession,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    analysis_id: str,
    timeout: int | None = None,
):
    """Get the output schema of a pipeline step without returning data."""
    from modules.compute.schemas import StepSchemaResponse

    if timeout is None:
        timeout = settings.job_timeout

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find the step index by step_id
    step_index = find_step_index(pipeline_steps, target_step_id)
    schema_steps = pipeline_steps[: step_index + 1]
    schema_steps = await _hydrate_udfs(session, schema_steps)

    manager = get_manager()
    engine = manager.get_engine(analysis_id)
    if not engine:
        engine = manager.get_or_create_engine(analysis_id)

    datasource_config = build_datasource_config(datasource)

    additional_datasources = await _get_additional_datasources(session, schema_steps)

    # Use the new schema command that doesn't collect full data
    engine.get_schema(
        datasource_config=datasource_config,
        pipeline_steps=schema_steps,
        additional_datasources=additional_datasources,
    )

    result_data = await await_engine_result(engine, timeout)
    error = result_data.get('error')
    if error:
        raise PipelineExecutionError(
            f'Schema fetch failed: {error}',
            details={'operation': 'schema', 'datasource_id': datasource_id},
        )

    data = result_data.get('data', {})
    schema = data.get('schema', {})
    return StepSchemaResponse(
        step_id=target_step_id,
        columns=list(schema.keys()),
        column_types=schema,
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

    The engine subprocess writes the full dataset to a temp file,
    then we read it and return the bytes.
    """
    if timeout is None:
        timeout = settings.job_timeout

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find steps up to target
    step_index = find_step_index(pipeline_steps, target_step_id)
    export_steps = pipeline_steps[: step_index + 1]
    export_steps = await _hydrate_udfs(session, export_steps)

    manager = get_manager()

    # Use analysis engine if provided and exists, otherwise create temporary one
    temp_engine = False
    temp_engine_id = f'{datasource_id}_export'
    if analysis_id:
        engine = manager.get_engine(analysis_id)
        if not engine:
            engine = manager.get_or_create_engine(analysis_id)
    else:
        engine = manager.get_or_create_engine(temp_engine_id)
        temp_engine = True

    datasource_config = build_datasource_config(datasource)

    additional_datasources = await _get_additional_datasources(session, export_steps)

    # Determine file extension and content type
    format_config = {
        'duckdb': ('.parquet', 'application/octet-stream'),
    }

    if export_format == 'duckdb':
        ext, content_type = format_config['duckdb']
    else:
        fmt = get_export_format(export_format)
        ext = fmt.extension
        content_type = fmt.content_type

    # For duckdb, we first export to parquet then convert
    actual_format = 'parquet' if export_format == 'duckdb' else export_format

    # Create temp file for engine to write to
    tmp_output = tempfile.mktemp(suffix=ext)

    try:
        # Use the new export method that writes full data directly to file
        engine.export(
            datasource_config=datasource_config,
            pipeline_steps=export_steps,
            output_path=tmp_output,
            export_format=actual_format,
            additional_datasources=additional_datasources,
        )

        result_data = await await_engine_result(engine, timeout)
        error = result_data.get('error')
        if error:
            if temp_engine:
                manager.shutdown_engine(temp_engine_id)
            raise PipelineExecutionError(
                f'Export failed: {error}',
                details={'operation': 'export', 'datasource_id': datasource_id, 'export_format': export_format},
            )

        if temp_engine:
            manager.shutdown_engine(temp_engine_id)

        data = result_data.get('data', {})
        row_count = data.get('row_count', 0)
        logger.info(f'Export completed: {row_count} rows written to {export_format}')

        # Handle DuckDB conversion
        if export_format == 'duckdb':
            tmp_db_path = tempfile.mktemp(suffix='.duckdb')
            try:
                conn = duckdb.connect(tmp_db_path)
                conn.execute('CREATE TABLE data AS SELECT * FROM read_parquet(?)', [tmp_output])
                conn.close()

                with open(tmp_db_path, 'rb') as f:
                    file_bytes = f.read()

                return file_bytes, f'{filename}.duckdb', 'application/octet-stream'
            finally:
                if os.path.exists(tmp_db_path):
                    os.unlink(tmp_db_path)

        # Read the exported file
        with open(tmp_output, 'rb') as f:
            file_bytes = f.read()

        return file_bytes, f'{filename}{ext}', content_type
    finally:
        # Clean up temp file
        if os.path.exists(tmp_output):
            os.unlink(tmp_output)
