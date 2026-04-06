import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from shutil import copy2

from fastapi import Depends, Form, HTTPException, UploadFile
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from core.config import settings
from core.database import get_db, run_db
from core.dependencies import get_manager
from core.error_handlers import handle_errors
from core.namespace import namespace_paths
from core.validation import DataSourceId, PreflightId, parse_datasource_id, parse_preflight_id
from modules.auth.dependencies import get_optional_user
from modules.auth.models import User
from modules.compute.manager import ProcessManager
from modules.datasource import schemas, service
from modules.datasource.preflight import clear_preflight, create_preflight, get_preflight
from modules.datasource.source_types import DataSourceType
from modules.mcp.router import MCPRouter

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/datasource', tags=['datasource'])

_FILE_TYPE_MAPPING: dict[str, str] = {
    '.csv': 'csv',
    '.parquet': 'parquet',
    '.json': 'json',
    '.ndjson': 'ndjson',
    '.jsonl': 'ndjson',
    '.xlsx': 'excel',
}


def _write_chunk(path: Path, chunk: bytes) -> None:
    with open(path, 'ab') as handle:
        handle.write(chunk)


async def _save_upload_file(file: UploadFile, file_path: Path, max_bytes: int) -> None:
    total = 0
    await asyncio.to_thread(file_path.write_bytes, b'')
    while True:
        chunk = await file.read(settings.upload_chunk_size)
        if not chunk:
            return
        total += len(chunk)
        if max_bytes and total > max_bytes:
            raise HTTPException(status_code=413, detail='Uploaded file exceeds size limit')
        await asyncio.to_thread(_write_chunk, file_path, chunk)


def _list_export_branches(metadata_path: str) -> list[str]:
    normalized = str(Path(metadata_path))
    path = Path(normalized)
    if not path.is_dir():
        return []
    metadata_dir = path / 'metadata'
    if metadata_dir.is_dir():
        return []
    entries = []
    for entry in path.iterdir():
        if not entry.is_dir():
            continue
        if (entry / 'metadata').is_dir():
            entries.append(entry.name)
            continue
        if list(entry.glob('*.metadata.json')):
            entries.append(entry.name)
            continue
    branches = sorted(entries)
    if 'master' not in branches:
        branches.insert(0, 'master')
    return branches


def _matches_magic_number(file_extension: str, upload: UploadFile) -> bool:
    header = upload.file.read(8)
    upload.file.seek(0)
    if file_extension == '.parquet':
        return header.startswith(b'PAR1')
    if file_extension == '.xlsx':
        return header.startswith(b'PK')
    return file_extension in {'.csv', '.json', '.ndjson', '.jsonl'}


@router.post('/upload', response_model=schemas.DataSourceResponse)
@handle_errors(operation='upload datasource', value_error_status=400)
async def upload_file(
    file: UploadFile,
    name: str = Form(...),
    delimiter: str = Form(','),
    quote_char: str = Form('"'),
    has_header: bool = Form(True),
    skip_rows: int = Form(0),
    encoding: str = Form('utf8'),
    user: User | None = Depends(get_optional_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail='No filename provided')

    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in _FILE_TYPE_MAPPING:
        raise HTTPException(
            status_code=400,
            detail=f'Unsupported file type: {file_extension}. Supported types: {", ".join(_FILE_TYPE_MAPPING.keys())}',
        )

    if not _matches_magic_number(file_extension, file):
        raise HTTPException(status_code=400, detail='File content does not match extension')
    file_type = _FILE_TYPE_MAPPING[file_extension]
    unique_filename = f'{uuid.uuid4()}{file_extension}'
    file_path = namespace_paths().upload_dir / unique_filename

    try:
        await _save_upload_file(file, file_path, settings.upload_max_file_size_bytes)
    except HTTPException:
        if file_path.exists():
            file_path.unlink()
        raise
    except Exception as e:
        logger.error('Failed to save file: %s', type(e).__name__, exc_info=True)
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail='Failed to save file') from e

    csv_options = None
    if file_type == 'csv':
        csv_options = schemas.CSVOptions(
            delimiter=delimiter,
            quote_char=quote_char,
            has_header=has_header,
            skip_rows=skip_rows,
            encoding=encoding,
        )

    try:
        owner_id = user.id if user else None
        return await run_in_threadpool(
            run_db,
            service.create_file_datasource,
            name=name,
            file_path=str(file_path),
            file_type=file_type,
            csv_options=csv_options,
            owner_id=owner_id,
        )
    except Exception as e:
        logger.error('Failed to create datasource: %s', type(e).__name__, exc_info=True)
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail='Failed to create datasource') from e


@router.post('/upload/bulk', response_model=schemas.BulkUploadResponse)
@handle_errors(operation='bulk upload datasources', value_error_status=400)
async def upload_bulk(
    files: list[UploadFile],
    delimiter: str = Form(','),
    quote_char: str = Form('"'),
    has_header: bool = Form(True),
    skip_rows: int = Form(0),
    encoding: str = Form('utf8'),
    user: User | None = Depends(get_optional_user),
):
    if not files:
        raise HTTPException(status_code=400, detail='No files provided')

    csv_options = schemas.CSVOptions(
        delimiter=delimiter,
        quote_char=quote_char,
        has_header=has_header,
        skip_rows=skip_rows,
        encoding=encoding,
    )

    selected_extensions = [Path(file.filename).suffix.lower() for file in files if file.filename]
    if selected_extensions:
        unique_extensions = set(selected_extensions)
        if len(unique_extensions) > 1:
            raise HTTPException(status_code=400, detail='Bulk upload must use a single file type per batch')

    results: list[schemas.BulkUploadResult] = []

    for file in files:
        if not file.filename:
            results.append(schemas.BulkUploadResult(name='unknown', success=False, error='No filename provided'))
            continue

        file_extension = Path(file.filename).suffix.lower()

        if file_extension not in _FILE_TYPE_MAPPING:
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=f'Unsupported file type: {file_extension}'))
            continue

        if not _matches_magic_number(file_extension, file):
            results.append(
                schemas.BulkUploadResult(
                    name=file.filename,
                    success=False,
                    error='File content does not match extension',
                ),
            )
            continue
        file_type = _FILE_TYPE_MAPPING[file_extension]
        unique_filename = f'{uuid.uuid4()}{file_extension}'
        file_path = namespace_paths().upload_dir / unique_filename
        name = Path(file.filename).stem

        try:
            await _save_upload_file(file, file_path, settings.upload_max_file_size_bytes)
        except HTTPException as exc:
            if file_path.exists():
                file_path.unlink()
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=str(exc.detail)))
            continue
        except Exception as e:
            if file_path.exists():
                file_path.unlink()
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=f'Failed to save file: {e!s}'))
            continue

        file_csv_options = csv_options if file_type == 'csv' else None
        try:
            owner_id = user.id if user else None
            datasource = await run_in_threadpool(
                run_db,
                service.create_file_datasource,
                name=name,
                file_path=str(file_path),
                file_type=file_type,
                csv_options=file_csv_options,
                owner_id=owner_id,
            )
            results.append(schemas.BulkUploadResult(name=file.filename, success=True, datasource=datasource))
        except Exception as e:
            if file_path.exists():
                file_path.unlink()
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=f'Failed to create datasource: {e!s}'))

    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    return schemas.BulkUploadResponse(results=results, total=len(results), successful=successful, failed=failed)


@router.post('/preflight', response_model=schemas.ExcelPreflightResponse)
@handle_errors(operation='preflight excel', value_error_status=400)
async def preflight_excel(
    file: UploadFile,
    sheet_name: str | None = Form(None),
    start_row: int = Form(0),
    start_col: int = Form(0),
    end_col: int = Form(0),
    end_row: int | None = Form(None),
    has_header: bool = Form(True),
    table_name: str | None = Form(None),
    named_range: str | None = Form(None),
    cell_range: str | None = Form(None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail='No filename provided')
    file_extension = Path(file.filename).suffix.lower()
    if file_extension != '.xlsx':
        raise HTTPException(status_code=400, detail='Only .xlsx files are supported for preflight')
    if not _matches_magic_number(file_extension, file):
        raise HTTPException(status_code=400, detail='File content does not match extension')

    unique_filename = f'{uuid.uuid4()}{file_extension}'
    file_path = namespace_paths().upload_dir / unique_filename
    try:
        await _save_upload_file(file, file_path, settings.upload_max_file_size_bytes)
    except HTTPException:
        if file_path.exists():
            file_path.unlink()
        raise
    except Exception as e:
        logger.error('Failed to save file: %s', type(e).__name__, exc_info=True)
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail='Failed to save file') from e

    preflight_id, preflight = await create_preflight(file_path, delete_file=False)
    target_sheet = sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        await clear_preflight(preflight_id, delete_file=False)
        raise HTTPException(status_code=400, detail='No sheets found in file')

    preview_result = await asyncio.to_thread(
        service.build_excel_preview,
        file_path=file_path,
        sheet_name=target_sheet,
        start_row=start_row,
        start_col=start_col,
        end_col=end_col,
        end_row=end_row,
        has_header=has_header,
        table_name=table_name,
        named_range=named_range,
        cell_range=cell_range,
    )

    return schemas.ExcelPreflightResponse(
        preflight_id=preflight_id,
        sheet_name=preview_result.sheet_name,
        sheet_names=preflight.sheets,
        tables=preflight.tables,
        named_ranges=preflight.named_ranges,
        preview=preview_result.preview,
        start_row=preview_result.start_row,
        start_col=preview_result.start_col,
        end_col=preview_result.end_col,
        detected_end_row=preview_result.detected_end_row,
    )


@router.post('/preflight-path', response_model=schemas.ExcelPreflightResponse)
@handle_errors(operation='preflight excel path', value_error_status=400)
async def preflight_excel_path(payload: schemas.ExcelPreflightPathRequest):
    file_path = Path(payload.file_path)
    paths = namespace_paths()
    resolved = Path(os.path.realpath(file_path))
    real_base = Path(os.path.realpath(paths.base_dir))
    if real_base not in resolved.parents and real_base != resolved:
        raise HTTPException(status_code=400, detail='Excel file must be inside the data directory')
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=400, detail='Excel file not found')
    if resolved.suffix.lower() != '.xlsx':
        raise HTTPException(status_code=400, detail='Only .xlsx files are supported for preflight')

    preflight_id, preflight = await create_preflight(file_path)
    target_sheet = payload.sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        await clear_preflight(preflight_id)
        raise HTTPException(status_code=400, detail='No sheets found in file')

    preview_result = await asyncio.to_thread(
        service.build_excel_preview,
        file_path=file_path,
        sheet_name=target_sheet,
        start_row=payload.start_row,
        start_col=payload.start_col,
        end_col=payload.end_col,
        end_row=payload.end_row,
        has_header=payload.has_header,
        table_name=payload.table_name,
        named_range=payload.named_range,
        cell_range=payload.cell_range,
    )

    return schemas.ExcelPreflightResponse(
        preflight_id=preflight_id,
        sheet_name=preview_result.sheet_name,
        sheet_names=preflight.sheets,
        tables=preflight.tables,
        named_ranges=preflight.named_ranges,
        preview=preview_result.preview,
        start_row=preview_result.start_row,
        start_col=preview_result.start_col,
        end_col=preview_result.end_col,
        detected_end_row=preview_result.detected_end_row,
    )


@router.get('/preflight/{preflight_id}/preview', response_model=schemas.ExcelPreflightPreviewResponse)
@handle_errors(operation='preflight preview', value_error_status=400)
async def preflight_preview(
    preflight_id: PreflightId,
    sheet_name: str,
    start_row: int = 0,
    start_col: int = 0,
    end_col: int = 0,
    end_row: int | None = None,
    has_header: bool = True,
    table_name: str | None = None,
    named_range: str | None = None,
    cell_range: str | None = None,
):
    preflight = await get_preflight(parse_preflight_id(preflight_id))
    if not preflight:
        raise HTTPException(status_code=404, detail='Preflight not found')

    preview_result = await asyncio.to_thread(
        service.build_excel_preview,
        file_path=preflight.temp_path,
        sheet_name=sheet_name,
        start_row=start_row,
        start_col=start_col,
        end_col=end_col,
        end_row=end_row,
        has_header=has_header,
        table_name=table_name,
        named_range=named_range,
        cell_range=cell_range,
    )
    return schemas.ExcelPreflightPreviewResponse(
        preview=preview_result.preview,
        sheet_name=preview_result.sheet_name,
        start_row=preview_result.start_row,
        start_col=preview_result.start_col,
        end_col=preview_result.end_col,
        detected_end_row=preview_result.detected_end_row,
    )


@router.post('/confirm', response_model=schemas.DataSourceResponse)
@handle_errors(operation='confirm excel', value_error_status=400)
async def confirm_excel(
    preflight_id: str = Form(...),
    name: str = Form(...),
    sheet_name: str | None = Form(None),
    start_row: int = Form(0),
    start_col: int = Form(0),
    end_col: int = Form(0),
    end_row: int | None = Form(None),
    has_header: bool = Form(True),
    table_name: str | None = Form(None),
    named_range: str | None = Form(None),
    cell_range: str | None = Form(None),
    user: User | None = Depends(get_optional_user),
):
    preflight = await get_preflight(parse_preflight_id(preflight_id))
    if not preflight:
        raise HTTPException(status_code=404, detail='Preflight not found')

    target_sheet = sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        await clear_preflight(parse_preflight_id(preflight_id))
        raise HTTPException(status_code=400, detail='No sheet selected')

    file_extension = preflight.temp_path.suffix.lower()
    target_filename = f'{uuid.uuid4()}{file_extension}'
    target_path = namespace_paths().upload_dir / target_filename

    try:
        await asyncio.to_thread(copy2, preflight.temp_path, target_path)
        resolved_sheet, resolved_start_row, resolved_start_col, resolved_end_col, resolved_end_row = await asyncio.to_thread(
            service.resolve_excel_selection,
            preflight.temp_path,
            target_sheet,
            start_row,
            start_col,
            end_col,
            end_row,
            table_name,
            named_range,
            cell_range,
        )
        resolved_cell_range = cell_range
        if not resolved_cell_range and (table_name or named_range or cell_range):
            resolved_cell_range = service.format_excel_cell_range(
                resolved_sheet,
                resolved_start_row,
                resolved_start_col,
                resolved_end_row,
                resolved_end_col,
            )
        datasource = await run_in_threadpool(
            run_db,
            service.create_file_datasource,
            name=name,
            file_path=str(target_path),
            file_type='excel',
            sheet_name=resolved_sheet,
            start_row=resolved_start_row,
            start_col=resolved_start_col,
            end_col=resolved_end_col,
            end_row=resolved_end_row,
            has_header=has_header,
            table_name=table_name,
            named_range=named_range,
            cell_range=resolved_cell_range,
            owner_id=user.id if user else None,
        )
    except Exception as e:
        logger.error('Failed to create datasource: %s', type(e).__name__, exc_info=True)
        if target_path.exists():
            target_path.unlink()
        await clear_preflight(parse_preflight_id(preflight_id))
        raise HTTPException(status_code=500, detail='Failed to create datasource') from e

    await clear_preflight(parse_preflight_id(preflight_id))
    return datasource


@router.post('/connect', response_model=schemas.DataSourceResponse, mcp=True)
@handle_errors(operation='connect datasource', value_error_status=400)
def connect_datasource(
    datasource: schemas.DataSourceCreate,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Connect a new datasource (database, Iceberg, or analysis type).

    For database: config needs {connection_string, query, branch}.
    For Iceberg: config needs {source} where source_type is reingestable today (file/database).
    File datasources must use the /upload endpoint instead.
    Use GET /datasource to verify creation.
    """
    if datasource.source_type == DataSourceType.FILE:
        raise HTTPException(
            status_code=400,
            detail='File datasource creation must use upload',
        )
    if datasource.source_type == 'duckdb':
        raise HTTPException(
            status_code=400,
            detail='DuckDB datasource creation is no longer supported',
        )
    if datasource.source_type == 'api':
        raise HTTPException(status_code=400, detail='API datasources are not supported')
    handlers = _connect_handlers()
    handler = handlers.get(datasource.source_type)
    if not handler:
        raise HTTPException(
            status_code=400,
            detail=(f'Unsupported source type: {datasource.source_type}. Use "file", "database", "iceberg", or "analysis"'),
        )
    return handler(datasource, session, user.id if user else None)


def _connect_handlers() -> dict[DataSourceType, Callable[[schemas.DataSourceCreate, Session, str | None], schemas.DataSourceResponse]]:
    return {
        DataSourceType.DATABASE: _connect_database,
        DataSourceType.ICEBERG: _connect_iceberg,
        DataSourceType.ANALYSIS: _connect_analysis,
    }


def _connect_database(datasource: schemas.DataSourceCreate, session: Session, owner_id: str | None) -> schemas.DataSourceResponse:
    db_config = schemas.DatabaseDataSourceConfig.model_validate(datasource.config)
    return service.create_database_datasource(
        session=session,
        name=datasource.name,
        connection_string=db_config.connection_string,
        query=db_config.query,
        branch=db_config.branch,
        owner_id=owner_id,
    )


def _connect_iceberg(datasource: schemas.DataSourceCreate, session: Session, owner_id: str | None) -> schemas.DataSourceResponse:
    iceberg_config = schemas.IcebergDataSourceConfig.model_validate(datasource.config)
    return service.create_iceberg_datasource(
        session=session,
        name=datasource.name,
        source=iceberg_config.source,
        branch=iceberg_config.branch,
        owner_id=owner_id,
    )


def _connect_analysis(datasource: schemas.DataSourceCreate, session: Session, owner_id: str | None) -> schemas.DataSourceResponse:
    _ = owner_id
    raise HTTPException(
        status_code=400,
        detail='Direct creation of analysis datasources is no longer supported. Use analysis tabs with analysis_tab_id.',
    )


@router.get('', response_model=list[schemas.DataSourceListItem], mcp=True)
@handle_errors(operation='list datasources')
def list_datasources(include_hidden: bool = False, session: Session = Depends(get_db)):
    """List all datasources with their type, config, and metadata.

    Set include_hidden=true to include auto-generated output datasources created by analyses.
    Each datasource has an id, name, source_type, and config dict.
    """
    return service.list_datasources(session, include_hidden=include_hidden)


@router.get('/lineage', mcp=True)
@handle_errors(operation='get lineage')
def get_lineage(
    target_datasource_id: DataSourceId | None = None,
    branch: str | None = None,
    include_internals: bool = False,
    mode: str = 'full',
    session: Session = Depends(get_db),
):
    """Get the dependency lineage graph for datasources.

    Returns nodes (datasources and analyses) and edges showing data flow.
    Optionally filter by target_datasource_id or branch to scope the graph.
    """
    from modules.datasource.service_lineage import build_lineage

    datasource_id = None
    if target_datasource_id:
        try:
            datasource_id = parse_datasource_id(target_datasource_id)
        except HTTPException:
            datasource_id = target_datasource_id
    if branch is not None:
        branch = branch.strip()
        if not branch:
            branch = None
    return build_lineage(
        session,
        target_datasource_id=datasource_id,
        branch=branch,
        include_internals=include_internals,
        mode=mode,
    )


@router.get('/{datasource_id}', response_model=schemas.DataSourceResponse, mcp=True)
@handle_errors(operation='get datasource')
def get_datasource(
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    """Get a single datasource by ID with full config and metadata. Use GET /datasource to find IDs."""
    response = service.get_datasource(session, parse_datasource_id(datasource_id))
    if response.source_type == DataSourceType.ICEBERG:
        metadata_path = response.config.get('metadata_path')
        if isinstance(metadata_path, str):
            response.config['branches'] = _list_export_branches(metadata_path)
    return response


@router.get('/{datasource_id}/schema', response_model=schemas.SchemaInfo, mcp=True)
@handle_errors(operation='get datasource schema')
def get_datasource_schema(
    datasource_id: DataSourceId,
    sheet_name: str | None = None,
    refresh: bool = False,
    session: Session = Depends(get_db),
):
    """Get the column schema of a datasource (column names, types, nullability).

    For Excel files, pass sheet_name to select a specific sheet.
    Set refresh=true to re-read the schema from the source file.
    """
    return service.get_datasource_schema(session, parse_datasource_id(datasource_id), sheet_name=sheet_name, refresh=refresh)


@router.post('/{datasource_id}/compare-snapshots', response_model=schemas.SnapshotCompareResponse, mcp=True)
@handle_errors(operation='compare datasource snapshots')
def compare_snapshots(
    datasource_id: DataSourceId,
    payload: schemas.SnapshotCompareRequest,
    session: Session = Depends(get_db),
):
    """Compare two Iceberg snapshots of a datasource.

    Returns row count deltas, schema differences, column stats, and data previews for both snapshots.
    Use GET /compute/iceberg/{id}/snapshots to find snapshot IDs.
    """
    return service.compare_iceberg_snapshots(
        session,
        parse_datasource_id(datasource_id),
        payload.snapshot_a,
        payload.snapshot_b,
        payload.row_limit,
    )


def _handle_column_stats(
    datasource_id: DataSourceId,
    column_name: str,
    sample: bool,
    payload: schemas.ColumnStatsRequest | None,
    session: Session,
):
    datasource = payload.datasource if payload else None
    config = None
    if isinstance(datasource, dict):
        config = datasource.get('config')
    return service.get_column_stats(
        session=session,
        datasource_id=parse_datasource_id(datasource_id),
        column_name=column_name,
        use_sample=sample,
        datasource_config=config if isinstance(config, dict) else None,
    )


@router.get('/{datasource_id}/column/{column_name}/stats', response_model=schemas.ColumnStatsResponse, mcp=True)
@handle_errors(operation='get column stats')
def get_column_stats(
    datasource_id: DataSourceId,
    column_name: str,
    sample: bool = True,
    session: Session = Depends(get_db),
):
    """Get statistics for a single column: count, nulls, unique values, min/max, mean, histogram.

    Set sample=false for exact stats (slower on large datasets).
    """
    return _handle_column_stats(datasource_id, column_name, sample, None, session)


@router.post('/{datasource_id}/column/{column_name}/stats', response_model=schemas.ColumnStatsResponse, mcp=True)
@handle_errors(operation='get column stats')
def get_column_stats_with_config(
    datasource_id: DataSourceId,
    column_name: str,
    payload: schemas.ColumnStatsRequest,
    sample: bool = True,
    session: Session = Depends(get_db),
):
    """Get column statistics with custom datasource config (e.g., different branch or snapshot)."""
    return _handle_column_stats(datasource_id, column_name, sample, payload, session)


@router.get('/file/list', response_model=schemas.FileListResponse, mcp=True)
@handle_errors(operation='list data files', value_error_status=400)
async def list_files(path: str | None = None):
    """List data files in the upload/data directory. Optionally pass path to list a subdirectory."""
    return service.list_data_files(path)


@router.put('/{datasource_id}', response_model=schemas.DataSourceResponse, mcp=True)
@handle_errors(operation='update datasource')
def update_datasource(
    datasource_id: DataSourceId,
    update: schemas.DataSourceUpdate,
    session: Session = Depends(get_db),
):
    """Update a datasource's name or config. Use GET /datasource/{id} to see current values."""
    return service.update_datasource(session, parse_datasource_id(datasource_id), update)


@router.post('/{datasource_id}/refresh', response_model=schemas.DataSourceResponse, mcp=True)
@handle_errors(operation='refresh datasource')
def refresh_datasource(
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    """Refresh an external datasource (re-read schema from source). Useful after upstream data changes."""
    return service.refresh_external_datasource(session, parse_datasource_id(datasource_id))


@router.delete('/{datasource_id}', status_code=204, mcp=True)
@handle_errors(operation='delete datasource')
def delete_datasource(
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
    manager: ProcessManager = Depends(get_manager),
):
    """Delete a datasource and its associated files. Use GET /datasource to find IDs."""
    datasource_id_value = parse_datasource_id(datasource_id)
    service.delete_datasource(session, datasource_id_value)
    preview_key = f'__preview__{datasource_id_value}'
    if manager.get_engine(preview_key):
        manager.shutdown_engine(preview_key)
