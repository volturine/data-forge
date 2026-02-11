import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from pyiceberg.catalog import load_catalog
from sqlalchemy import select
from sqlmodel import Session

from core.config import settings
from core.exceptions import DataSourceNotFoundError, DataSourceValidationError, FileError
from modules.compute.operations.datasource import load_datasource, resolve_iceberg_metadata_path
from modules.datasource.models import DataSource
from modules.datasource.schemas import (
    ColumnSchema,
    CSVOptions,
    DataSourceResponse,
    DataSourceUpdate,
    FileListItem,
    FileListResponse,
    SchemaInfo,
)
from modules.engine_runs import service as engine_run_service

logger = logging.getLogger(__name__)


def create_file_datasource(
    session: Session,
    name: str,
    file_path: str,
    file_type: str,
    options: dict | None = None,
    csv_options: CSVOptions | None = None,
    sheet_name: str | None = None,
    start_row: int | None = None,
    start_col: int | None = None,
    end_col: int | None = None,
    end_row: int | None = None,
    has_header: bool | None = None,
    table_name: str | None = None,
    named_range: str | None = None,
) -> DataSourceResponse:
    """Create a file-based datasource."""
    datasource_id = str(uuid.uuid4())
    resolved_path = Path(os.path.realpath(Path(file_path).resolve()))
    data_root = Path(os.path.realpath(settings.data_dir.resolve()))
    upload_root = Path(os.path.realpath(settings.upload_dir.resolve()))
    within_data_root = data_root in resolved_path.parents or data_root == resolved_path
    within_upload_root = upload_root in resolved_path.parents or upload_root == resolved_path
    if not (within_data_root or within_upload_root):
        raise ValueError(f'Path must be inside data directory: {data_root}')
    if file_type in {'csv', 'json', 'ndjson', 'excel'} and not resolved_path.is_file():
        raise ValueError(f'Path must be a file for type: {file_type}')
    if file_type == 'parquet' and not (resolved_path.is_file() or resolved_path.is_dir()):
        raise ValueError('Parquet path must be a file or directory')

    config = {
        'file_path': str(resolved_path),
        'file_type': file_type,
        'options': options or {},
        'csv_options': csv_options.model_dump() if csv_options else None,
        'sheet_name': sheet_name,
        'start_row': start_row,
        'start_col': start_col,
        'end_col': end_col,
        'end_row': end_row,
        'has_header': has_header,
        'table_name': table_name,
        'named_range': named_range,
    }

    datasource = DataSource(
        id=datasource_id,
        name=name,
        source_type='file',
        config=config,
        created_at=datetime.now(UTC),
    )

    session.add(datasource)
    session.commit()
    session.refresh(datasource)

    _log_datasource_create(session, datasource_id, name, 'file', config)

    # Extract and cache schema immediately
    try:
        schema_info = _extract_schema(datasource, sheet_name=sheet_name)
        datasource.schema_cache = schema_info.model_dump()
        session.commit()
        session.refresh(datasource)
        logger.info(f'Cached schema for datasource {datasource_id}: {len(schema_info.columns)} columns, {schema_info.row_count} rows')
    except Exception as e:
        logger.warning(f'Failed to extract schema for datasource {datasource_id}: {e}')

    logger.info(f'Created file datasource {datasource_id} ({name}) with file {file_path}')
    return DataSourceResponse.model_validate(datasource)


@dataclass
class ExcelPreviewResult:
    preview: list[list[str | None]]
    detected_end_row: int | None
    sheet_name: str
    start_row: int
    start_col: int
    end_col: int


def build_excel_preview(
    file_path: Path,
    sheet_name: str,
    start_row: int,
    start_col: int,
    end_col: int,
    has_header: bool,
    table_name: str | None = None,
    named_range: str | None = None,
    preview_rows: int = 100,
) -> ExcelPreviewResult:
    workbook = load_workbook(file_path, read_only=False, data_only=True)
    resolved = _resolve_excel_bounds(
        workbook,
        sheet_name,
        start_row,
        start_col,
        end_col,
        table_name,
        named_range,
    )
    sheet = workbook[resolved.sheet_name]

    detected_end_row = resolved.end_row
    if detected_end_row is None:
        detected_end_row = _detect_end_row(sheet, resolved.start_row, resolved.start_col, resolved.end_col)

    preview_end_row = min(resolved.start_row + preview_rows - 1, detected_end_row)
    rows = _collect_preview_rows(sheet, resolved.start_row, resolved.start_col, resolved.end_col, preview_end_row)
    return ExcelPreviewResult(
        preview=rows,
        detected_end_row=detected_end_row,
        sheet_name=resolved.sheet_name,
        start_row=resolved.start_row,
        start_col=resolved.start_col,
        end_col=resolved.end_col,
    )


def resolve_excel_selection(
    file_path: Path,
    sheet_name: str,
    start_row: int,
    start_col: int,
    end_col: int,
    table_name: str | None = None,
    named_range: str | None = None,
) -> tuple[str, int, int, int, int]:
    workbook = load_workbook(file_path, read_only=False, data_only=True)
    resolved = _resolve_excel_bounds(
        workbook,
        sheet_name,
        start_row,
        start_col,
        end_col,
        table_name,
        named_range,
    )
    sheet = workbook[resolved.sheet_name]
    end_row = resolved.end_row
    if end_row is None:
        end_row = _detect_end_row(sheet, resolved.start_row, resolved.start_col, resolved.end_col)
    return resolved.sheet_name, resolved.start_row, resolved.start_col, resolved.end_col, end_row


@dataclass
class _ExcelBounds:
    sheet_name: str
    start_row: int
    start_col: int
    end_col: int
    end_row: int | None


def _resolve_excel_bounds(
    workbook,
    sheet_name: str,
    start_row: int,
    start_col: int,
    end_col: int,
    table_name: str | None,
    named_range: str | None,
) -> _ExcelBounds:
    if table_name:
        sheet = workbook[sheet_name]
        tables = getattr(sheet, 'tables', None)
        if not tables:
            raise ValueError(f'No tables available in sheet: {sheet_name}')
        table = tables.get(table_name)
        if not table:
            raise ValueError(f'Table not found: {table_name}')
        min_col, min_row, max_col, max_row = range_boundaries(table.ref)
        if min_col is None or min_row is None or max_col is None or max_row is None:
            raise ValueError(f'Invalid table range: {table_name}')
        min_col = int(min_col)
        min_row = int(min_row)
        max_col = int(max_col)
        max_row = int(max_row)
        return _ExcelBounds(sheet_name, min_row - 1, min_col - 1, max_col - 1, max_row - 1)

    if named_range:
        defined = workbook.defined_names.get(named_range)
        if not defined:
            raise ValueError(f'Named range not found: {named_range}')
        destinations = list(defined.destinations)
        if not destinations:
            raise ValueError(f'Named range has no destinations: {named_range}')
        dest_sheet, coord = destinations[0]
        min_col, min_row, max_col, max_row = range_boundaries(coord)
        if min_col is None or min_row is None or max_col is None or max_row is None:
            raise ValueError(f'Invalid named range: {named_range}')
        min_col = int(min_col)
        min_row = int(min_row)
        max_col = int(max_col)
        max_row = int(max_row)
        return _ExcelBounds(dest_sheet, min_row - 1, min_col - 1, max_col - 1, max_row - 1)

    return _ExcelBounds(sheet_name, max(start_row, 0), max(start_col, 0), max(end_col, start_col), None)


def _detect_end_row(sheet, start_row: int, start_col: int, end_col: int) -> int:
    max_row = sheet.max_row or 0
    if max_row <= start_row:
        return start_row
    for row_index in range(start_row + 1, max_row + 1):
        values = []
        for cell in sheet.iter_rows(min_row=row_index, max_row=row_index, min_col=start_col + 1, max_col=end_col + 1):
            values = [c.value for c in cell]
        if all(value is None or str(value).strip() == '' for value in values):
            return max(start_row, row_index - 2)
    return max_row - 1


def _collect_preview_rows(
    sheet,
    start_row: int,
    start_col: int,
    end_col: int,
    preview_end_row: int,
) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for row in sheet.iter_rows(
        min_row=start_row + 1,
        max_row=preview_end_row + 1,
        min_col=start_col + 1,
        max_col=end_col + 1,
    ):
        values = [cell.value for cell in row]
        rows.append([str(value) if value is not None else None for value in values])
    return rows


def create_database_datasource(
    session: Session,
    name: str,
    connection_string: str,
    query: str,
) -> DataSourceResponse:
    datasource_id = str(uuid.uuid4())

    config = {
        'connection_string': connection_string,
        'query': query,
    }

    datasource = DataSource(
        id=datasource_id,
        name=name,
        source_type='database',
        config=config,
        created_at=datetime.now(UTC),
    )

    session.add(datasource)
    session.commit()
    session.refresh(datasource)

    _log_datasource_create(session, datasource_id, name, 'database', config)
    return DataSourceResponse.model_validate(datasource)


def create_api_datasource(
    session: Session,
    name: str,
    url: str,
    method: str = 'GET',
    headers: dict | None = None,
    auth: dict | None = None,
) -> DataSourceResponse:
    datasource_id = str(uuid.uuid4())

    config = {
        'url': url,
        'method': method,
        'headers': headers,
        'auth': auth,
    }

    datasource = DataSource(
        id=datasource_id,
        name=name,
        source_type='api',
        config=config,
        created_at=datetime.now(UTC),
    )

    session.add(datasource)
    session.commit()
    session.refresh(datasource)

    _log_datasource_create(session, datasource_id, name, 'api', config)
    return DataSourceResponse.model_validate(datasource)


def create_duckdb_datasource(
    session: Session,
    name: str,
    db_path: str | None,
    query: str,
    read_only: bool = True,
) -> DataSourceResponse:
    """Create a DuckDB datasource."""
    datasource_id = str(uuid.uuid4())

    config = {
        'db_path': db_path,
        'query': query,
        'read_only': read_only,
    }

    datasource = DataSource(
        id=datasource_id,
        name=name,
        source_type='duckdb',
        config=config,
        created_at=datetime.now(UTC),
    )

    session.add(datasource)
    session.commit()
    session.refresh(datasource)

    logger.info(f'Created DuckDB datasource {datasource_id} ({name})')
    _log_datasource_create(session, datasource_id, name, 'duckdb', config)
    return DataSourceResponse.model_validate(datasource)


def create_iceberg_datasource(
    session: Session,
    name: str,
    metadata_path: str,
    snapshot_id: str | None = None,
    snapshot_timestamp_ms: int | None = None,
    storage_options: dict | None = None,
    reader: str | None = None,
    catalog_type: str | None = None,
    catalog_uri: str | None = None,
    warehouse: str | None = None,
    namespace: str | None = None,
    table: str | None = None,
) -> DataSourceResponse:
    """Create an Iceberg datasource."""
    datasource_id = str(uuid.uuid4())

    normalized_path = _normalize_iceberg_path(metadata_path)
    try:
        resolved_metadata = resolve_iceberg_metadata_path(normalized_path)
    except ValueError as exc:
        raise DataSourceValidationError(str(exc), details={'metadata_path': metadata_path}) from exc

    snapshot_value = snapshot_id
    if snapshot_id:
        try:
            int(snapshot_id)
        except (TypeError, ValueError) as exc:
            raise DataSourceValidationError('Snapshot ID must be an integer', details={'snapshot_id': snapshot_id}) from exc

    config = {
        'metadata_path': normalized_path,
        'snapshot_id': snapshot_value,
        'snapshot_timestamp_ms': snapshot_timestamp_ms,
        'storage_options': storage_options,
        'reader': reader,
    }
    catalog_config = {
        'type': catalog_type or 'sql',
        'uri': catalog_uri or f'sqlite:///{settings.data_dir / "iceberg" / "catalog.db"}',
        'warehouse': warehouse or f'file://{settings.data_dir / "iceberg" / "warehouse"}',
    }
    namespace_value = namespace or 'external'
    table_value = table
    if not table_value:
        table_value = Path(resolved_metadata).parent.parent.name
    try:
        catalog = load_catalog('local', **catalog_config)
        catalog.create_namespace_if_not_exists(namespace_value)
        identifier = f'{namespace_value}.{table_value}'
        if catalog.table_exists(identifier):
            existing = catalog.load_table(identifier)
            if existing.metadata_location != resolved_metadata:
                raise DataSourceValidationError(
                    'Iceberg catalog table already exists with different metadata',
                    details={'metadata_path': normalized_path, 'namespace': namespace_value, 'table': table_value},
                )
        else:
            catalog.register_table(identifier, resolved_metadata)
    except Exception as exc:
        raise DataSourceValidationError(
            f'Failed to register Iceberg table in catalog: {exc}',
            details={'metadata_path': normalized_path, 'namespace': namespace_value, 'table': table_value},
        ) from exc
    config['catalog_type'] = catalog_config['type']
    config['catalog_uri'] = catalog_config['uri']
    config['warehouse'] = catalog_config['warehouse']
    config['namespace'] = namespace_value
    config['table'] = table_value

    datasource = DataSource(
        id=datasource_id,
        name=name,
        source_type='iceberg',
        config=config,
        created_at=datetime.now(UTC),
    )

    session.add(datasource)
    session.commit()
    session.refresh(datasource)

    _log_datasource_create(session, datasource_id, name, 'iceberg', config)

    try:
        schema_info = _extract_schema(datasource)
        datasource.schema_cache = schema_info.model_dump()
        session.commit()
        session.refresh(datasource)
        logger.info(f'Cached schema for datasource {datasource_id}: {len(schema_info.columns)} columns, {schema_info.row_count} rows')
    except Exception as e:
        logger.warning(f'Failed to extract schema for datasource {datasource_id}: {e}')

    logger.info(f'Created Iceberg datasource {datasource_id} ({name})')
    return DataSourceResponse.model_validate(datasource)


def _log_datasource_create(
    session: Session,
    datasource_id: str,
    name: str,
    source_type: str,
    config: dict,
) -> None:
    payload = engine_run_service.create_engine_run_payload(
        analysis_id=None,
        datasource_id=datasource_id,
        kind='datasource_create',
        status='success',
        request_json={
            'name': name,
            'source_type': source_type,
            'config': config,
        },
        result_json={'datasource_id': datasource_id, 'datasource_name': name},
    )
    engine_run_service.create_engine_run(session, payload)


def get_datasource_schema(
    session: Session,
    datasource_id: str,
    sheet_name: str | None = None,
    refresh: bool = False,
) -> SchemaInfo:
    """Get or extract schema for a datasource."""
    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    if refresh and sheet_name is None:
        datasource.schema_cache = None
        session.commit()

    # Check if we have cached schema with row_count and sample_value
    if datasource.schema_cache and sheet_name is None and not refresh:
        cached = SchemaInfo.model_validate(datasource.schema_cache)
        # Re-extract if row_count or sample_value is missing
        has_samples = cached.columns and any(c.sample_value is not None for c in cached.columns)
        if cached.row_count is not None and has_samples:
            logger.debug(f'Using cached schema for datasource {datasource_id}')
            return cached

    logger.info(f'Extracting schema for datasource {datasource_id}')
    schema_info = _extract_schema(datasource, sheet_name=sheet_name)

    if sheet_name is None:
        datasource.schema_cache = schema_info.model_dump()
        session.commit()

    logger.info(f'Schema extracted and cached for datasource {datasource_id}: {len(schema_info.columns)} columns')
    return schema_info


def _get_first_non_null_samples(lazy: pl.LazyFrame, max_rows: int = 1000) -> dict[str, str | None]:
    """Get first non-null value for each column by scanning up to max_rows."""
    sample_values: dict[str, str | None] = {}
    columns = lazy.collect_schema().names()

    # Build expressions to get first non-null for each column
    exprs = [pl.col(col).drop_nulls().first().alias(col) for col in columns]

    # Limit scan to max_rows for performance
    result = lazy.head(max_rows).select(exprs).collect()

    if result.height > 0:
        for col in columns:
            val = result[col][0]
            sample_values[col] = str(val) if val is not None else None

    return sample_values


def _get_first_non_null_samples_eager(frame: pl.DataFrame, max_rows: int = 1000) -> dict[str, str | None]:
    """Get first non-null value for each column from eager DataFrame."""
    sample_values: dict[str, str | None] = {}
    columns = frame.columns

    # Limit to max_rows for performance
    subset = frame.head(max_rows)

    for col in columns:
        non_null = subset[col].drop_nulls()
        if non_null.len() > 0:
            sample_values[col] = str(non_null[0])
        else:
            sample_values[col] = None

    return sample_values


def _extract_schema(datasource: DataSource, sheet_name: str | None = None) -> SchemaInfo:
    if datasource.source_type == 'file':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        if sheet_name:
            config = {**config, 'sheet_name': sheet_name}
        lazy = load_datasource(config)
        schema = lazy.collect_schema()
        row_count = lazy.select(pl.len()).collect().item()
        sheet_names = None

        # Get first non-null value for each column
        sample_values = _get_first_non_null_samples(lazy)

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
                sample_value=sample_values.get(name),
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count, sheet_names=sheet_names)

    if datasource.source_type == 'database':
        connection_string = datasource.config['connection_string']
        query = datasource.config['query']

        frame = pl.read_database(query, connection_string)
        schema = frame.schema
        row_count = frame.height

        # Get first non-null value for each column
        sample_values = _get_first_non_null_samples_eager(frame)

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
                sample_value=sample_values.get(name),
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    if datasource.source_type == 'duckdb':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        lazy = load_datasource(config)
        schema = lazy.collect_schema()
        row_count = lazy.select(pl.len()).collect().item()

        # Get first non-null value for each column
        sample_values = _get_first_non_null_samples(lazy)

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
                sample_value=sample_values.get(name),
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    if datasource.source_type == 'iceberg':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        lazy = load_datasource(config)
        schema = lazy.collect_schema()
        row_count = lazy.select(pl.len()).collect().item()

        sample_values = _get_first_non_null_samples(lazy)

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
                sample_value=sample_values.get(name),
            )
            for name, dtype in schema.items()
        ]
        return SchemaInfo(columns=columns, row_count=row_count)

    raise DataSourceValidationError(
        f'Schema extraction not supported for type: {datasource.source_type}',
        details={'source_type': datasource.source_type},
    )


def list_data_files(path: str | None) -> FileListResponse:
    base_dir = settings.data_dir.resolve()
    target = Path(path) if path else base_dir
    resolved = target.resolve()
    if base_dir not in resolved.parents and base_dir != resolved:
        raise ValueError(f'Path must be inside data directory: {base_dir}')
    if not resolved.exists():
        raise ValueError(f'Path does not exist: {resolved}')
    if not resolved.is_dir():
        raise ValueError(f'Path must be a directory: {resolved}')

    entries = [
        FileListItem(
            name=item.name,
            path=str(item),
            is_dir=item.is_dir(),
        )
        for item in sorted(resolved.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower()))
    ]
    return FileListResponse(base_path=str(resolved), entries=entries)


def _normalize_iceberg_path(metadata_path: str) -> str:
    path = Path(metadata_path)
    if path.suffix == '.db':
        raise DataSourceValidationError('Iceberg metadata_path must be a table directory, not catalog.db')
    if path.name.endswith('.metadata.json'):
        return str(path)
    return str(path)


def get_datasource(session: Session, datasource_id: str) -> DataSourceResponse:
    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    return DataSourceResponse.model_validate(datasource)


def list_datasources(session: Session) -> list[DataSourceResponse]:
    result = session.execute(select(DataSource))
    datasources = result.scalars().all()

    # Populate schema_cache for datasources that don't have it
    for ds in datasources:
        if ds.schema_cache is None:
            try:
                schema_info = _extract_schema(ds)
                ds.schema_cache = schema_info.model_dump()
                logger.info(f'Populated schema cache for datasource {ds.id}')
            except Exception as e:
                logger.warning(f'Failed to extract schema for datasource {ds.id}: {e}')

    session.commit()
    return [DataSourceResponse.model_validate(ds) for ds in datasources]


def update_datasource(
    session: Session,
    datasource_id: str,
    update: DataSourceUpdate,
) -> DataSourceResponse:
    """Update a datasource configuration."""
    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Update name if provided
    if update.name is not None:
        datasource.name = update.name

    # Update config if provided
    if update.config is not None:
        if 'column_schema' in update.config:
            raise DataSourceValidationError(
                'Datasource schemas are read-only and cannot be modified',
                details={'datasource_id': datasource_id},
            )

        immutable_keys = {
            'file': ['file_path'],
            'database': ['connection_string'],
            'api': ['url'],
            'duckdb': ['db_path'],
            'iceberg': ['metadata_path'],
        }
        for key in immutable_keys.get(datasource.source_type, []):
            if key not in update.config:
                continue
            if update.config.get(key) == datasource.config.get(key):
                continue
            raise DataSourceValidationError(
                'Datasource location is immutable. Create a new datasource to change location.',
                details={'datasource_id': datasource_id, 'field': key},
            )

        if (
            datasource.source_type == 'duckdb'
            and 'read_only' in update.config
            and update.config.get('read_only') != datasource.config.get('read_only', True)
        ):
            raise DataSourceValidationError(
                'Datasource mode is immutable. Create a new datasource to change read-only mode.',
                details={'datasource_id': datasource_id, 'field': 'read_only'},
            )

        # Check if parsing options changed (requires schema re-extraction)
        parsing_changed = any(
            key in update.config for key in ['csv_options', 'sheet_name', 'start_row', 'start_col', 'end_col', 'has_header', 'skip_rows']
        )

        # Merge new config with existing config
        datasource.config = {**datasource.config, **update.config}
        if parsing_changed:
            datasource.schema_cache = None

    session.commit()
    session.refresh(datasource)

    run_payload = engine_run_service.create_engine_run_payload(
        analysis_id=None,
        datasource_id=datasource_id,
        kind='datasource_update',
        status='success',
        request_json=update.model_dump(exclude_none=True),
        result_json={'datasource_id': datasource_id, 'datasource_name': datasource.name},
    )
    engine_run_service.create_engine_run(session, run_payload)

    logger.info(f'Updated datasource {datasource_id}')
    return DataSourceResponse.model_validate(datasource)


def delete_datasource(session: Session, datasource_id: str) -> None:
    """Delete a datasource and its associated file if it exists."""
    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Delete associated file if it's a file datasource
    if datasource.source_type == 'file' and 'file_path' in datasource.config:
        file_path = Path(datasource.config['file_path'])
        if file_path.exists():
            try:
                # Check if file is accessible before deletion
                if not file_path.is_file():
                    logger.warning(f'Path exists but is not a file: {file_path}')
                else:
                    file_path.unlink()
                    logger.info(f'Deleted file: {file_path}')
            except PermissionError as e:
                logger.error(f'Permission denied when deleting file {file_path}: {e}')
                raise FileError(
                    f'Permission denied when deleting file: {file_path}',
                    error_code='FILE_PERMISSION_DENIED',
                    details={'file_path': str(file_path)},
                )
            except OSError as e:
                logger.error(f'OS error when deleting file {file_path}: {e}')
                raise FileError(
                    f'Failed to delete file: {file_path}',
                    error_code='FILE_DELETE_ERROR',
                    details={'file_path': str(file_path), 'error': str(e)},
                )

    session.delete(datasource)
    session.commit()
    logger.info(f'Deleted datasource {datasource_id}')
