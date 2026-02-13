import logging
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl
from pyiceberg.catalog import load_catalog
from sqlalchemy import select
from sqlmodel import Session

from core.config import settings
from core.exceptions import DataSourceNotFoundError, DataSourceSnapshotError, PipelineExecutionError
from modules.compute.core.exports import get_export_format
from modules.compute.manager import get_manager
from modules.compute.operations.datasource import resolve_iceberg_metadata_path
from modules.compute.utils import await_engine_result, build_datasource_config, find_step_index
from modules.datasource.models import DataSource
from modules.engine_runs import service as engine_run_service
from modules.udf.models import Udf

logger = logging.getLogger(__name__)


def _build_preview_result_metadata(
    data: dict,
    page: int,
    row_limit: int,
    offset: int,
) -> dict:
    schema = data.get('schema', {}) or {}
    rows = data.get('data', []) or []
    query_plans = data.get('query_plans')

    result: dict = {
        'schema': schema,
        'columns': list(schema.keys()),
        'row_count': data.get('row_count', 0),
        'page': page,
        'row_limit': row_limit,
        'offset': offset,
        'page_size': len(rows),
    }

    if query_plans:
        result['query_plans'] = query_plans

    return result


def _build_export_result_metadata(
    data: dict,
    file_size_bytes: int,
) -> dict:
    query_plans = data.get('query_plans')

    result: dict = {
        'row_count': data.get('row_count', 0),
        'export_format': data.get('export_format'),
        'file_size_bytes': file_size_bytes,
    }

    if query_plans:
        result['query_plans'] = query_plans

    return result


def _get_additional_datasources(session: Session, pipeline_steps: list[dict]) -> dict[str, dict]:
    """Extract and fetch additional datasources referenced in pipeline steps (e.g., for joins)."""
    additional: dict[str, dict] = {}

    for step in pipeline_steps:
        config = step.get('config', {})
        right_source_id = config.get('right_source') or config.get('rightDataSource')

        union_sources = config.get('sources', [])
        if isinstance(union_sources, str):
            union_sources = [union_sources]

        if right_source_id and right_source_id not in additional:
            datasource = session.get(DataSource, right_source_id)
            if datasource:
                additional[right_source_id] = {
                    'source_type': datasource.source_type,
                    **datasource.config,
                }

        for source_id in union_sources:
            if source_id in additional:
                continue
            datasource = session.get(DataSource, source_id)
            if datasource:
                additional[source_id] = {
                    'source_type': datasource.source_type,
                    **datasource.config,
                }

    return additional


def _hydrate_udfs(session: Session, pipeline_steps: list[dict]) -> list[dict]:
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
            result = session.execute(select(Udf).where(Udf.id == udf_id))  # type: ignore[arg-type]
            udf = result.scalar_one_or_none()
            if not udf:
                raise ValueError(f'UDF {udf_id} not found')
            updated.append({**expr, 'code': udf.code})
        next_steps.append({**step, 'config': {**config, 'expressions': updated}})
    return next_steps


def preview_step(
    session: Session,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    row_limit: int = 1000,
    page: int = 1,
    timeout: int | None = None,
    analysis_id: str | None = None,
    resource_config: dict | None = None,
    datasource_config: dict | None = None,
    request_json: dict | None = None,
):
    """Preview the result of executing pipeline up to a specific step with pagination."""
    from modules.compute.schemas import StepPreviewResponse

    if timeout is None:
        timeout = settings.job_timeout

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    if not analysis_id:
        # Create a temporary analysis_id for datasource preview
        analysis_id = f'__preview__{datasource_id}'

    run_analysis_id = analysis_id

    request_payload = request_json or {
        'analysis_id': run_analysis_id,
        'datasource_id': datasource_id,
        'pipeline_steps': pipeline_steps,
        'target_step_id': target_step_id,
        'row_limit': row_limit,
        'page': page,
        'resource_config': resource_config,
    }

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find the step index by step_id
    # Special case: previewing raw datasource (no pipeline steps, target is "source")
    if target_step_id == 'source' and len(pipeline_steps) == 0:
        preview_steps = []
    else:
        step_index = find_step_index(pipeline_steps, target_step_id)
        preview_steps = pipeline_steps[: step_index + 1]
        preview_steps = _hydrate_udfs(session, preview_steps)

    manager = get_manager()
    # get_or_create_engine will restart the engine if resource_config changed
    engine = manager.get_or_create_engine(analysis_id, resource_config=resource_config)

    datasource_config = build_datasource_config(datasource, datasource_config)

    additional_datasources = _get_additional_datasources(session, preview_steps)

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

    try:
        result_data = await_engine_result(engine, timeout)
        error = result_data.get('error')
        if error:
            raise PipelineExecutionError(
                f'Preview failed: {error}',
                details={'operation': 'preview', 'datasource_id': datasource_id},
            )

        data = result_data.get('data', {})
        offset = (page - 1) * row_limit
        result_meta = _build_preview_result_metadata(
            data=data,
            page=page,
            row_limit=row_limit,
            offset=offset,
        )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=run_analysis_id,
            datasource_id=datasource_id,
            kind='preview',
            status='success',
            request_json=request_payload,
            result_json=result_meta,
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        engine_run_service.create_engine_run(session, payload)

        return StepPreviewResponse(
            step_id=target_step_id,
            columns=list(data.get('schema', {}).keys()),
            column_types=data.get('schema', {}),
            data=data.get('data', []),
            total_rows=data.get('row_count', 0),
            page=page,
            page_size=len(data.get('data', [])),
        )
    except Exception as exc:
        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=run_analysis_id,
            datasource_id=datasource_id,
            kind='preview',
            status='failed',
            request_json=request_payload,
            error_message=str(exc),
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        engine_run_service.create_engine_run(session, payload)
        raise


def get_step_schema(
    session: Session,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    analysis_id: str,
    timeout: int | None = None,
    datasource_config: dict | None = None,
):
    """Get the output schema of a pipeline step without returning data."""
    from modules.compute.schemas import StepSchemaResponse

    if timeout is None:
        timeout = settings.job_timeout

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find the step index by step_id
    step_index = find_step_index(pipeline_steps, target_step_id)
    schema_steps = pipeline_steps[: step_index + 1]
    schema_steps = _hydrate_udfs(session, schema_steps)

    manager = get_manager()
    engine = manager.get_engine(analysis_id)
    if not engine:
        engine = manager.get_or_create_engine(analysis_id)

    datasource_config = build_datasource_config(datasource, datasource_config)

    additional_datasources = _get_additional_datasources(session, schema_steps)

    # Use the new schema command that doesn't collect full data
    engine.get_schema(
        datasource_config=datasource_config,
        pipeline_steps=schema_steps,
        additional_datasources=additional_datasources,
    )

    result_data = await_engine_result(engine, timeout)
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


def export_data(
    session: Session,
    datasource_id: str,
    pipeline_steps: list[dict],
    target_step_id: str,
    export_format: str = 'csv',
    filename: str = 'export',
    destination: str = 'download',
    datasource_type: str = 'iceberg',
    iceberg_options: dict | None = None,
    duckdb_options: dict | None = None,
    datasource_config: dict | None = None,
    timeout: int | None = None,
    analysis_id: str | None = None,
    request_json: dict | None = None,
) -> tuple[bytes | None, str | None, str | None, str | None, str | None, dict | None]:
    """
    Export pipeline result to file or datasource.

    Returns tuple:
    (file_bytes, filename_with_ext, content_type, file_path, datasource_id, result_meta)
    """
    if timeout is None:
        timeout = settings.job_timeout

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    run_analysis_id = analysis_id

    request_payload = request_json or {
        'analysis_id': run_analysis_id,
        'datasource_id': datasource_id,
        'pipeline_steps': pipeline_steps,
        'target_step_id': target_step_id,
        'format': export_format,
        'filename': filename,
        'destination': destination,
        'datasource_type': datasource_type,
        'iceberg_options': iceberg_options,
        'duckdb_options': duckdb_options,
        'datasource_config': datasource_config,
    }

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Find steps up to target
    step_index = find_step_index(pipeline_steps, target_step_id)
    export_steps = pipeline_steps[: step_index + 1]
    export_steps = _hydrate_udfs(session, export_steps)

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

    datasource_config = build_datasource_config(datasource, datasource_config)

    additional_datasources = _get_additional_datasources(session, export_steps)

    if destination == 'datasource' and datasource_type == 'iceberg':
        export_format = 'parquet'
    if destination == 'datasource' and datasource_type == 'duckdb':
        export_format = 'duckdb'
    if destination == 'datasource' and datasource_type == 'file' and export_format == 'duckdb':
        raise ValueError('DuckDB format is not supported for file datasource exports')

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
        try:
            engine.export(
                datasource_config=datasource_config,
                pipeline_steps=export_steps,
                output_path=tmp_output,
                export_format=actual_format,
                additional_datasources=additional_datasources,
            )

            result_data = await_engine_result(engine, timeout)
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

            completed_at = datetime.now(UTC)
            duration_ms = int((time.perf_counter() - started_perf) * 1000)

            # Handle DuckDB conversion for download/filesystem/datasource
            file_bytes = None
            output_path = tmp_output
            result_format = export_format
            if export_format == 'duckdb':
                tmp_db_path = tempfile.mktemp(suffix='.duckdb')
                try:
                    conn = duckdb.connect(tmp_db_path)
                    table_name = 'data'
                    if duckdb_options:
                        table_name = duckdb_options.get('table_name', 'data')
                    conn.execute(f'CREATE TABLE {table_name} AS SELECT * FROM read_parquet(?)', [tmp_output])
                    conn.close()
                    output_path = tmp_db_path
                    result_format = 'duckdb'
                except Exception:
                    if os.path.exists(tmp_db_path):
                        os.unlink(tmp_db_path)
                    if os.path.exists(tmp_output):
                        os.unlink(tmp_output)
                    raise

            result_meta = _build_export_result_metadata(
                data=data,
                file_size_bytes=os.path.getsize(output_path),
            )
            # Download - return bytes
            if destination == 'download':
                payload = engine_run_service.create_engine_run_payload(
                    analysis_id=run_analysis_id,
                    datasource_id=datasource_id,
                    kind='export',
                    status='success',
                    request_json=request_payload,
                    result_json=result_meta,
                    created_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                )
                engine_run_service.create_engine_run(session, payload)
                with open(output_path, 'rb') as f:
                    file_bytes = f.read()
                return file_bytes, f'{filename}.{result_format}', content_type, None, None, result_meta

            # Filesystem - save in exports dir
            if destination == 'filesystem':
                payload = engine_run_service.create_engine_run_payload(
                    analysis_id=run_analysis_id,
                    datasource_id=datasource_id,
                    kind='export',
                    status='success',
                    request_json=request_payload,
                    result_json=result_meta,
                    created_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                )
                engine_run_service.create_engine_run(session, payload)
                file_name = f'{filename}.{result_format}'
                file_path = settings.exports_dir / file_name
                with open(output_path, 'rb') as f:
                    file_bytes = f.read()
                with open(file_path, 'wb') as f:
                    f.write(file_bytes)
                return None, file_name, content_type, str(file_path.absolute()), None, result_meta

            # Datasource - create datasource entry based on type
            if destination == 'datasource':
                payload = engine_run_service.create_engine_run_payload(
                    analysis_id=run_analysis_id,
                    datasource_id=datasource_id,
                    kind='export',
                    status='success',
                    request_json=request_payload,
                    result_json=result_meta,
                    created_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                )
                engine_run_service.create_engine_run(session, payload)
                if datasource_type == 'file':
                    file_name = f'{filename}.{result_format}'
                    file_path = settings.exports_dir / file_name
                    with open(output_path, 'rb') as f:
                        file_bytes = f.read()
                    with open(file_path, 'wb') as f:
                        f.write(file_bytes)

                    new_id = str(uuid.uuid4())
                    new_datasource = DataSource(
                        id=new_id,
                        name=filename,
                        source_type='file',
                        config={
                            'file_path': str(file_path.absolute()),
                            'file_type': result_format,
                            'options': {},
                            'csv_options': None,
                        },
                        schema_cache=data.get('schema', {}),
                        created_at=datetime.now(UTC),
                    )
                    session.add(new_datasource)
                    session.commit()

                    result_meta['datasource_id'] = new_id
                    result_meta['datasource_name'] = filename
                    payload = engine_run_service.create_engine_run_payload(
                        analysis_id=run_analysis_id,
                        datasource_id=new_id,
                        kind='datasource_create',
                        status='success',
                        request_json=request_payload,
                        result_json=result_meta,
                        created_at=started_at,
                        completed_at=completed_at,
                        duration_ms=duration_ms,
                    )
                    engine_run_service.create_engine_run(session, payload)

                    return None, file_name, content_type, str(file_path.absolute()), new_id, result_meta

                if datasource_type == 'duckdb':
                    file_name = f'{filename}.duckdb'
                    file_path = settings.exports_dir / file_name
                    with open(output_path, 'rb') as f:
                        file_bytes = f.read()
                    with open(file_path, 'wb') as f:
                        f.write(file_bytes)

                    table_name = 'data'
                    if duckdb_options:
                        table_name = duckdb_options.get('table_name', 'data')
                    new_id = str(uuid.uuid4())
                    new_datasource = DataSource(
                        id=new_id,
                        name=filename,
                        source_type='duckdb',
                        config={
                            'db_path': str(file_path.absolute()),
                            'query': f'SELECT * FROM {table_name}',
                            'read_only': True,
                        },
                        schema_cache=data.get('schema', {}),
                        created_at=datetime.now(UTC),
                    )
                    session.add(new_datasource)
                    session.commit()

                    result_meta['datasource_id'] = new_id
                    result_meta['datasource_name'] = filename
                    payload = engine_run_service.create_engine_run_payload(
                        analysis_id=run_analysis_id,
                        datasource_id=new_id,
                        kind='datasource_create',
                        status='success',
                        request_json=request_payload,
                        result_json=result_meta,
                        created_at=started_at,
                        completed_at=completed_at,
                        duration_ms=duration_ms,
                    )
                    engine_run_service.create_engine_run(session, payload)

                    return None, file_name, content_type, str(file_path.absolute()), new_id, result_meta

                if datasource_type == 'iceberg':
                    iceberg_opts = iceberg_options or {}
                    table_name = iceberg_opts.get('table_name', 'exported_data')
                    namespace = iceberg_opts.get('namespace', 'exports')

                    iceberg_base = settings.data_dir / 'iceberg'
                    warehouse_path = iceberg_base / 'warehouse'
                    catalog_path = iceberg_base / 'catalog.db'

                    warehouse_path.mkdir(parents=True, exist_ok=True)
                    if not catalog_path.exists():
                        catalog_path.touch()

                    catalog_config = {
                        'type': 'sql',
                        'uri': f'sqlite:///{catalog_path}',
                        'warehouse': f'file://{warehouse_path}',
                    }

                    catalog = load_catalog('local', **catalog_config)
                    catalog.create_namespace_if_not_exists(namespace)

                    unique_table = table_name
                    identifier = f'{namespace}.{unique_table}'

                    arrow_table = pl.read_parquet(output_path).to_arrow()
                    table = None
                    if catalog.table_exists(identifier):
                        table = catalog.load_table(identifier)
                        table.overwrite(arrow_table)
                    else:
                        table = catalog.create_table(identifier, schema=arrow_table.schema)
                        table.append(arrow_table)

                    metadata_path = str(table.metadata_location)
                    resolved_metadata = resolve_iceberg_metadata_path(metadata_path)
                    table_dir = str(Path(resolved_metadata).parents[1])
                    existing = session.execute(select(DataSource).filter_by(source_type='iceberg', name=unique_table)).scalar_one_or_none()
                    if existing:
                        existing_namespace = str(existing.config.get('namespace', ''))
                        existing_catalog = str(existing.config.get('catalog_uri', ''))
                        expected_catalog = f'sqlite:///{catalog_path}'
                        if existing_namespace != namespace or existing_catalog != expected_catalog:
                            existing = None

                    datasource_id_value = str(uuid.uuid4())
                    run_kind = 'datasource_create'
                    if existing:
                        existing.config = {
                            **existing.config,
                            'metadata_path': table_dir,
                        }
                        existing.schema_cache = data.get('schema', {})
                        session.add(existing)
                        session.commit()
                        datasource_id_value = existing.id
                        run_kind = 'datasource_update'
                    else:
                        new_datasource = DataSource(
                            id=datasource_id_value,
                            name=unique_table,
                            source_type='iceberg',
                            config={
                                'catalog_type': 'sql',
                                'catalog_uri': f'sqlite:///{catalog_path}',
                                'warehouse': f'file://{warehouse_path}',
                                'namespace': namespace,
                                'table': unique_table,
                                'metadata_path': table_dir,
                            },
                            schema_cache=data.get('schema', {}),
                            created_at=datetime.now(UTC),
                        )
                        session.add(new_datasource)
                        session.commit()

                    result_meta['datasource_id'] = datasource_id_value
                    result_meta['datasource_name'] = unique_table
                    payload = engine_run_service.create_engine_run_payload(
                        analysis_id=run_analysis_id,
                        datasource_id=datasource_id_value,
                        kind=run_kind,
                        status='success',
                        request_json=request_payload,
                        result_json=result_meta,
                        created_at=started_at,
                        completed_at=completed_at,
                        duration_ms=duration_ms,
                    )
                    engine_run_service.create_engine_run(session, payload)

                    return None, unique_table, content_type, table_dir, datasource_id_value, result_meta

            return None, None, None, None, None, result_meta
        except Exception as exc:
            completed_at = datetime.now(UTC)
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            if temp_engine:
                manager.shutdown_engine(temp_engine_id)
            payload = engine_run_service.create_engine_run_payload(
                analysis_id=run_analysis_id,
                datasource_id=datasource_id,
                kind='export',
                status='failed',
                request_json=request_payload,
                error_message=str(exc),
                created_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )
            engine_run_service.create_engine_run(session, payload)
            raise
    finally:
        if os.path.exists(tmp_output):
            os.unlink(tmp_output)


def list_iceberg_snapshots(session: Session, datasource_id: str):
    from modules.compute.schemas import IcebergSnapshotInfo, IcebergSnapshotsResponse

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)
    if datasource.source_type != 'iceberg':
        raise ValueError('Snapshots are only available for Iceberg datasources')

    metadata_path = datasource.config.get('metadata_path')
    if not metadata_path:
        raise ValueError('Iceberg datasource missing metadata_path')

    catalog_type = datasource.config.get('catalog_type')
    catalog_uri = datasource.config.get('catalog_uri')
    namespace = datasource.config.get('namespace')
    table_name = datasource.config.get('table')
    warehouse = datasource.config.get('warehouse')

    if catalog_type and catalog_uri and namespace and table_name:
        catalog_config = {
            'type': catalog_type,
            'uri': catalog_uri,
        }
        if warehouse:
            catalog_config['warehouse'] = warehouse
        catalog = load_catalog('local', **catalog_config)
        identifier = f'{namespace}.{table_name}'
        table = catalog.load_table(identifier)
        resolved = resolve_iceberg_metadata_path(str(table.metadata_location))
    else:
        from pyiceberg.table import StaticTable

        resolved = resolve_iceberg_metadata_path(metadata_path)
        table = StaticTable.from_metadata(resolved)

    current_snapshot = table.current_snapshot()
    current_snapshot_id = str(current_snapshot.snapshot_id) if current_snapshot else None
    snapshots = []
    for snap in table.snapshots():
        operation = None
        if snap.summary and snap.summary.operation:
            operation = str(snap.summary.operation)
        snapshots.append(
            IcebergSnapshotInfo(
                snapshot_id=str(snap.snapshot_id),
                timestamp_ms=snap.timestamp_ms,
                parent_snapshot_id=str(snap.parent_snapshot_id) if snap.parent_snapshot_id is not None else None,
                operation=operation,
                is_current=str(snap.snapshot_id) == current_snapshot_id,
            )
        )

    snapshots.sort(key=lambda s: s.timestamp_ms, reverse=True)

    return IcebergSnapshotsResponse(
        datasource_id=datasource_id,
        table_path=str(Path(resolved).parents[1]),
        snapshots=snapshots,
    )


def delete_iceberg_snapshot(session: Session, datasource_id: str, snapshot_id: str):
    from modules.compute.schemas import IcebergSnapshotDeleteResponse

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)
    if datasource.source_type != 'iceberg':
        raise ValueError('Snapshots are only available for Iceberg datasources')

    try:
        snapshot_value = int(snapshot_id)
    except (TypeError, ValueError) as exc:
        raise DataSourceSnapshotError('Snapshot ID must be an integer', details={'snapshot_id': snapshot_id}) from exc

    catalog_type = datasource.config.get('catalog_type')
    catalog_uri = datasource.config.get('catalog_uri')
    namespace = datasource.config.get('namespace')
    table_name = datasource.config.get('table')
    warehouse = datasource.config.get('warehouse')
    if catalog_type and catalog_uri and namespace and table_name:
        catalog_config = {
            'type': catalog_type,
            'uri': catalog_uri,
        }
        if warehouse:
            catalog_config['warehouse'] = warehouse
        catalog = load_catalog('local', **catalog_config)
        identifier = f'{namespace}.{table_name}'
        table = catalog.load_table(identifier)
    else:
        raise DataSourceSnapshotError(
            'Snapshot deletion requires a catalog-backed Iceberg datasource',
            details={'snapshot_id': snapshot_id},
        )

    if not hasattr(table, 'maintenance'):
        raise DataSourceSnapshotError(
            'Snapshot deletion is not supported by the current Iceberg runtime',
            details={'snapshot_id': snapshot_id},
        )
    maintenance = table.maintenance
    if not hasattr(maintenance, 'expire_snapshots'):
        raise DataSourceSnapshotError(
            'Snapshot deletion is not supported by the current Iceberg runtime',
            details={'snapshot_id': snapshot_id},
        )

    try:
        current = table.current_snapshot()
        if current and current.snapshot_id == snapshot_value:
            raise DataSourceSnapshotError(
                'Cannot delete the current snapshot',
                details={'snapshot_id': snapshot_id},
            )
        available_ids = [snap.snapshot_id for snap in table.snapshots()]
        if snapshot_value not in available_ids:
            raise DataSourceSnapshotError(
                f'Snapshot with snapshot id {snapshot_value} does not exist',
                details={'snapshot_id': snapshot_id, 'available_snapshot_ids': available_ids},
            )
        maintenance.expire_snapshots().by_id(snapshot_value).commit()
    except ValueError as exc:
        raise DataSourceSnapshotError(str(exc), details={'snapshot_id': snapshot_id}) from exc
    except NotImplementedError as exc:
        raise DataSourceSnapshotError(
            'Snapshot deletion is not supported by the current Iceberg catalog',
            details={'snapshot_id': snapshot_id},
        ) from exc

    return IcebergSnapshotDeleteResponse(
        datasource_id=datasource_id,
        snapshot_id=snapshot_id,
    )
