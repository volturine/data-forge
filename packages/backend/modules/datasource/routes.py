import asyncio
import contextlib
import logging
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, Form, HTTPException, UploadFile
from sqlmodel import Session

from backend_core import datasource_delete_service
from backend_core.config import settings
from backend_core.data_plane_client import WorkerDataPlaneClient, client_from_settings
from backend_core.database import get_db_async, run_db
from backend_core.dependencies import (
    RuntimeAvailabilityProbe,
    get_runtime_availability_probe,
)
from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.domain.datasource.source_types import DataSourceFileType, DataSourceType
from backend_core.error_handlers import handle_errors
from backend_core.exceptions import AppError
from backend_core.namespace import get_namespace
from backend_core.validation import (
    DataSourceId,
    PreflightId,
    parse_datasource_id,
    parse_preflight_id,
)
from dataforge_protocol import enums_pb2
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.compute.executor_client import (
    compare_iceberg_snapshots as compare_remote_iceberg_snapshots,
    create_database_datasource as create_remote_database_datasource,
    create_file_datasource as create_remote_file_datasource,
    create_iceberg_datasource as create_remote_iceberg_datasource,
    execute_excel_preflight,
    get_column_stats as get_remote_column_stats,
    get_datasource_schema as get_remote_datasource_schema,
    ingest_datasource as ingest_remote_datasource,
    json_response,
)
from modules.datasource import schemas, service
from modules.datasource.preflight import (
    clear_preflight,
    create_preflight,
    format_excel_cell_range,
    get_preflight,
    preview_result,
    resolved_selection,
)
from modules.datasource.schema_protocol import schema_info_response_payload
from modules.mcp.router import MCPRouter

logger = logging.getLogger(__name__)
_MAX_OBJECT_TRANSFER_BYTES = 2 * 1024 * 1024 * 1024

router = MCPRouter(prefix='/datasource', tags=['datasource'])

_EXCEL_PARSING_KEYS = (
    'sheet_name',
    'start_row',
    'start_col',
    'end_col',
    'end_row',
    'has_header',
    'table_name',
    'named_range',
    'cell_range',
)


def _datasource_update_snapshot(session: Session, datasource_id: str) -> tuple[dict[str, object], int, str, str]:
    datasource = datasource_delete_service.get_active_datasource(session, datasource_id)
    return (
        dict(datasource.config),
        datasource.revision,
        datasource.source_type,
        datasource.config.get('file_type', '') if isinstance(datasource.config.get('file_type', ''), str) else '',
    )


def _require_active_datasource(session: Session, datasource_id: str) -> None:
    # This is an existence check used before read/compute work. A row lock
    # here would outlive this short thread-pool task while the endpoint
    # schedules its real work, serializing every concurrent reader behind the
    # first request. Compute enqueue paths take the lock in the same task that
    # commits the durable request instead.
    datasource_delete_service.get_active_datasource(session, datasource_id)


def _write_chunk(path: Path, chunk: bytes) -> None:
    with open(path, 'ab') as handle:
        handle.write(chunk)


async def _save_upload_file(file: UploadFile, file_path: Path, max_bytes: int) -> None:
    effective_max_bytes = min(max_bytes or _MAX_OBJECT_TRANSFER_BYTES, _MAX_OBJECT_TRANSFER_BYTES)
    total = 0
    await asyncio.to_thread(file_path.write_bytes, b'')
    while True:
        chunk = await file.read(settings.upload_chunk_size)
        if not chunk:
            return
        total += len(chunk)
        if total > effective_max_bytes:
            raise HTTPException(status_code=413, detail='Uploaded file exceeds size limit')
        await asyncio.to_thread(_write_chunk, file_path, chunk)


def _temporary_upload_path(suffix: str) -> Path:
    directory = Path(settings.data_dir) / 'runtime-upload-temp'
    directory.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=suffix, dir=directory)
    os.close(fd)
    return Path(path)


async def _wait_for_transfer_task[T](task: asyncio.Task[T]) -> T:
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def _upload_staged_file_to_object_store(
    data_plane: WorkerDataPlaneClient,
    file_path: Path,
    target_url: str,
    *,
    max_bytes: int,
) -> None:
    upload_task = asyncio.create_task(asyncio.to_thread(data_plane.upload_object_file, file_path, target_url, max_bytes=max_bytes))
    try:
        await asyncio.shield(upload_task)
    except asyncio.CancelledError:
        try:
            await _wait_for_transfer_task(upload_task)
        except Exception:
            logger.debug('Cancelled staged upload did not complete successfully: %s', target_url, exc_info=True)
        cleanup_task = asyncio.create_task(asyncio.to_thread(data_plane.delete_object, target_url))
        try:
            await _wait_for_transfer_task(cleanup_task)
        except Exception:
            logger.exception('Failed to remove cancelled staged upload target: %s', target_url)
        raise


async def _stage_upload_to_object_store(file: UploadFile, target_name: str) -> str:
    temp_path = await asyncio.to_thread(_temporary_upload_path, Path(target_name).suffix.lower())
    try:
        await _save_upload_file(file, temp_path, settings.upload_max_file_size_bytes)
        data_plane = await asyncio.to_thread(client_from_settings)
        target_url = await asyncio.to_thread(lambda: data_plane.build_object_url('uploads', target_name, namespace=get_namespace()))
        await _upload_staged_file_to_object_store(
            data_plane,
            temp_path,
            target_url,
            max_bytes=settings.upload_max_file_size_bytes,
        )
        return target_url
    finally:
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(temp_path.unlink)


async def _delete_managed_object(source_path: str) -> None:
    data_plane = await asyncio.to_thread(client_from_settings)
    classification = await asyncio.to_thread(data_plane.classify_object_url, source_path)
    if classification.is_managed:
        await asyncio.to_thread(data_plane.delete_object, source_path)


def _list_export_branches(metadata_path: str, current_branch: str | None = None) -> list[str]:
    if client_from_settings().classify_object_url(metadata_path).is_object_store:
        data_plane = client_from_settings()
        entries = data_plane.list_prefixes(metadata_path)
        if entries:
            branches = sorted(entries)
        elif data_plane.list_metadata_files(metadata_path):
            branches = [current_branch or 'master']
        else:
            branches = []
    else:
        normalized = str(Path(metadata_path))
        path = Path(normalized)
        if not path.is_dir():
            return []
        metadata_dir = path / 'metadata'
        if metadata_dir.is_dir():
            branches = [current_branch or 'master']
        else:
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
    if not branches:
        return []
    if current_branch and current_branch not in branches:
        branches.insert(0, current_branch)
    if 'master' not in branches:
        branches.insert(0, 'master')
    return branches


@router.post('/upload', response_model=schemas.DataSourceResponse)
@handle_errors(operation='upload datasource', value_error_status=400)
async def upload_file(
    file: UploadFile,
    name: str = Form(...),
    description: str | None = Form(None, max_length=4000),
    delimiter: str = Form(','),
    quote_char: str = Form('"'),
    has_header: bool = Form(True),
    skip_rows: int = Form(0),
    encoding: str = Form('utf8'),
    user: User | None = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail='No filename provided')

    file_type = DataSourceFileType.from_upload_filename(file.filename)
    if file_type is None:
        file_extension = Path(file.filename).suffix.lower()
        supported = ', '.join(DataSourceFileType.supported_upload_suffixes())
        raise HTTPException(status_code=400, detail=f'Unsupported file type: {file_extension}. Supported types: {supported}')

    header = await file.read(8)
    await file.seek(0)
    if not file_type.matches_magic_number(header):
        raise HTTPException(status_code=400, detail='File content does not match extension')
    unique_filename = f'{uuid.uuid4()}{Path(file.filename).suffix.lower()}'

    try:
        file_path = await _stage_upload_to_object_store(file, unique_filename)
    except HTTPException:
        raise
    except Exception as e:
        logger.error('Failed to stage file: %s', type(e).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail='Failed to save file') from e

    csv_options = None
    if file_type.uses_csv_options:
        csv_options = schemas.CSVOptions(
            delimiter=delimiter,
            quote_char=quote_char,
            has_header=has_header,
            skip_rows=skip_rows,
            encoding=encoding,
        )

    try:
        owner_id = user.id if user else None
        datasource = await create_remote_file_datasource(
            runtime_probe=runtime_probe,
            name=name,
            description=description,
            file_path=str(file_path),
            file_type=file_type.value,
            csv_options=csv_options.model_dump() if csv_options else None,
            owner_id=owner_id,
        )
        return await json_response(datasource)
    except AppError, HTTPException, ValueError:
        await _delete_managed_object(file_path)
        raise
    except Exception as e:
        logger.error('Failed to create datasource: %s', type(e).__name__, exc_info=True)
        await _delete_managed_object(file_path)
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
    user: User | None = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
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

    selected_file_types = [file_type for file in files if file.filename and (file_type := DataSourceFileType.from_upload_filename(file.filename)) is not None]
    if selected_file_types and len(set(selected_file_types)) > 1:
        raise HTTPException(
            status_code=400,
            detail='Bulk upload must use a single file type per batch',
        )

    results: list[schemas.BulkUploadResult] = []

    for file in files:
        if not file.filename:
            results.append(schemas.BulkUploadResult(name='unknown', success=False, error='No filename provided'))
            continue

        file_type = DataSourceFileType.from_upload_filename(file.filename)
        file_extension = Path(file.filename).suffix.lower()
        if file_type is None:
            results.append(
                schemas.BulkUploadResult(
                    name=file.filename,
                    success=False,
                    error=f'Unsupported file type: {file_extension}',
                )
            )
            continue

        header = await file.read(8)
        await file.seek(0)
        if not file_type.matches_magic_number(header):
            results.append(
                schemas.BulkUploadResult(
                    name=file.filename,
                    success=False,
                    error='File content does not match extension',
                ),
            )
            continue
        unique_filename = f'{uuid.uuid4()}{file_extension}'
        name = Path(file.filename).stem

        try:
            file_path = await _stage_upload_to_object_store(file, unique_filename)
        except HTTPException as exc:
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=str(exc.detail)))
            continue
        except Exception as e:
            results.append(
                schemas.BulkUploadResult(
                    name=file.filename,
                    success=False,
                    error=f'Failed to save file: {e!s}',
                )
            )
            continue

        file_csv_options = csv_options if file_type.uses_csv_options else None
        try:
            owner_id = user.id if user else None
            datasource = await create_remote_file_datasource(
                runtime_probe=runtime_probe,
                name=name,
                description=None,
                file_path=file_path,
                file_type=file_type.value,
                csv_options=file_csv_options.model_dump() if file_csv_options else None,
                owner_id=owner_id,
            )
            results.append(schemas.BulkUploadResult(name=file.filename, success=True, datasource=datasource))
        except AppError as exc:
            await _delete_managed_object(file_path)
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=exc.message))
        except HTTPException as exc:
            await _delete_managed_object(file_path)
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=str(exc.detail)))
        except ValueError as exc:
            await _delete_managed_object(file_path)
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=str(exc)))
        except Exception as e:
            await _delete_managed_object(file_path)
            results.append(
                schemas.BulkUploadResult(
                    name=file.filename,
                    success=False,
                    error=f'Failed to create datasource: {e!s}',
                )
            )

    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    return await json_response(schemas.BulkUploadResponse(results=results, total=len(results), successful=successful, failed=failed))


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
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail='No filename provided')
    file_type = DataSourceFileType.from_upload_filename(file.filename)
    if file_type != DataSourceFileType.EXCEL:
        raise HTTPException(status_code=400, detail='Only .xlsx files are supported for preflight')
    header = await file.read(8)
    await file.seek(0)
    if not file_type.matches_magic_number(header):
        raise HTTPException(status_code=400, detail='File content does not match extension')

    unique_filename = f'{uuid.uuid4()}{Path(file.filename).suffix.lower()}'
    temp_path = await asyncio.to_thread(_temporary_upload_path, Path(file.filename).suffix.lower())
    try:
        await _save_upload_file(file, temp_path, settings.upload_max_file_size_bytes)
        data_plane = await asyncio.to_thread(client_from_settings)
        source_path = await asyncio.to_thread(lambda: data_plane.build_object_url('uploads', unique_filename, namespace=get_namespace()))
        await _upload_staged_file_to_object_store(
            data_plane,
            temp_path,
            source_path,
            max_bytes=settings.upload_max_file_size_bytes,
        )
    except asyncio.CancelledError:
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(temp_path.unlink)
        raise
    except HTTPException:
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(temp_path.unlink)
        raise
    except Exception as e:
        logger.error('Failed to save file: %s', type(e).__name__, exc_info=True)
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(temp_path.unlink)
        raise HTTPException(status_code=500, detail='Failed to save file') from e

    try:
        preflight_id, preflight, result = await create_preflight(
            source_path=source_path,
            selection={
                'sheet_name': sheet_name,
                'start_row': start_row,
                'start_col': start_col,
                'end_col': end_col,
                'end_row': end_row,
                'has_header': has_header,
                'table_name': table_name,
                'named_range': named_range,
                'cell_range': cell_range,
            },
            runtime_probe=runtime_probe,
            delete_source=True,
        )
    except asyncio.CancelledError:
        cleanup_task = asyncio.create_task(_delete_managed_object(source_path))
        with contextlib.suppress(Exception):
            await _wait_for_transfer_task(cleanup_task)
        raise
    finally:
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(temp_path.unlink)
    target_sheet = sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        await clear_preflight(preflight_id)
        raise HTTPException(status_code=400, detail='No sheets found in file')

    result_sheet, result_start_row, result_start_col, result_end_col, result_end_row, rows = preview_result(result)
    return schemas.ExcelPreflightResponse(
        preflight_id=preflight_id,
        sheet_name=result_sheet or target_sheet,
        sheet_names=preflight.sheets,
        tables=preflight.tables,
        named_ranges=preflight.named_ranges,
        preview=rows,
        start_row=result_start_row,
        start_col=result_start_col,
        end_col=result_end_col,
        detected_end_row=result_end_row,
    )


@router.post('/preflight-path', response_model=schemas.ExcelPreflightResponse)
@handle_errors(operation='preflight excel path', value_error_status=400)
async def preflight_excel_path(
    payload: schemas.ExcelPreflightPathRequest,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    data_plane = await asyncio.to_thread(client_from_settings)
    if not await asyncio.to_thread(data_plane.object_exists, payload.file_path):
        raise HTTPException(status_code=400, detail='Excel file not found')

    if DataSourceFileType.from_upload_suffix(Path(urlparse(payload.file_path).path).suffix.lower()) != DataSourceFileType.EXCEL:
        raise HTTPException(status_code=400, detail='Only .xlsx files are supported for preflight')
    preflight_id, preflight, result = await create_preflight(
        source_path=payload.file_path,
        selection={
            'sheet_name': payload.sheet_name,
            'start_row': payload.start_row,
            'start_col': payload.start_col,
            'end_col': payload.end_col,
            'end_row': payload.end_row,
            'has_header': payload.has_header,
            'table_name': payload.table_name,
            'named_range': payload.named_range,
            'cell_range': payload.cell_range,
        },
        runtime_probe=runtime_probe,
        delete_source=False,
    )
    target_sheet = payload.sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        await clear_preflight(preflight_id, delete_source=False)
        raise HTTPException(status_code=400, detail='No sheets found in file')
    result_sheet, result_start_row, result_start_col, result_end_col, result_end_row, rows = preview_result(result)
    return schemas.ExcelPreflightResponse(
        preflight_id=preflight_id,
        sheet_name=result_sheet or target_sheet,
        sheet_names=preflight.sheets,
        tables=preflight.tables,
        named_ranges=preflight.named_ranges,
        preview=rows,
        start_row=result_start_row,
        start_col=result_start_col,
        end_col=result_end_col,
        detected_end_row=result_end_row,
    )


@router.get(
    '/preflight/{preflight_id}/preview',
    response_model=schemas.ExcelPreflightPreviewResponse,
)
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
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    preflight = await get_preflight(parse_preflight_id(preflight_id))
    if not preflight:
        raise HTTPException(status_code=404, detail='Preflight not found')

    result = await execute_excel_preflight(
        preflight_id=parse_preflight_id(preflight_id),
        source_path=preflight.source_path,
        action=enums_pb2.DATASOURCE_PREFLIGHT_ACTION_PREVIEW,
        selection={
            'sheet_name': sheet_name,
            'start_row': start_row,
            'start_col': start_col,
            'end_col': end_col,
            'end_row': end_row,
            'has_header': has_header,
            'table_name': table_name,
            'named_range': named_range,
            'cell_range': cell_range,
        },
        runtime_probe=runtime_probe,
        delete_source=False,
    )
    result_sheet, result_start_row, result_start_col, result_end_col, result_end_row, rows = preview_result(result)
    return schemas.ExcelPreflightPreviewResponse(
        preview=rows,
        sheet_name=result_sheet,
        start_row=result_start_row,
        start_col=result_start_col,
        end_col=result_end_col,
        detected_end_row=result_end_row,
    )


@router.post('/confirm', response_model=schemas.DataSourceResponse)
@handle_errors(operation='confirm excel', value_error_status=400)
async def confirm_excel(
    preflight_id: str = Form(...),
    name: str = Form(...),
    description: str | None = Form(None, max_length=4000),
    sheet_name: str | None = Form(None),
    start_row: int = Form(0),
    start_col: int = Form(0),
    end_col: int = Form(0),
    end_row: int | None = Form(None),
    has_header: bool = Form(True),
    table_name: str | None = Form(None),
    named_range: str | None = Form(None),
    cell_range: str | None = Form(None),
    user: User | None = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    preflight = await get_preflight(parse_preflight_id(preflight_id))
    if not preflight:
        raise HTTPException(status_code=404, detail='Preflight not found')

    target_sheet = sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        await clear_preflight(parse_preflight_id(preflight_id))
        raise HTTPException(status_code=400, detail='No sheet selected')

    try:
        resolved = await execute_excel_preflight(
            preflight_id=parse_preflight_id(preflight_id),
            source_path=preflight.source_path,
            action=enums_pb2.DATASOURCE_PREFLIGHT_ACTION_RESOLVE_SELECTION,
            selection={
                'sheet_name': target_sheet,
                'start_row': start_row,
                'start_col': start_col,
                'end_col': end_col,
                'end_row': end_row,
                'has_header': has_header,
                'table_name': table_name,
                'named_range': named_range,
                'cell_range': cell_range,
            },
            runtime_probe=runtime_probe,
            delete_source=False,
        )
        resolved_sheet, resolved_start_row, resolved_start_col, resolved_end_col, resolved_end_row = resolved_selection(resolved)
        if resolved_end_row is None:
            raise ValueError('Excel selection result has no end row')
        target_path = preflight.source_path
        resolved_cell_range = cell_range
        if not resolved_cell_range and (table_name or named_range or cell_range):
            resolved_cell_range = format_excel_cell_range(
                resolved_sheet,
                resolved_start_row,
                resolved_start_col,
                resolved_end_row,
                resolved_end_col,
            )
        datasource = await create_remote_file_datasource(
            runtime_probe=runtime_probe,
            name=name,
            description=description,
            file_path=target_path,
            file_type=DataSourceFileType.EXCEL.value,
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
    except AppError, HTTPException:
        await clear_preflight(parse_preflight_id(preflight_id))
        raise
    except Exception as e:
        logger.error('Failed to create datasource: %s', type(e).__name__, exc_info=True)
        await clear_preflight(parse_preflight_id(preflight_id))
        raise HTTPException(status_code=500, detail='Failed to create datasource') from e

    await clear_preflight(parse_preflight_id(preflight_id), delete_source=False)
    return await json_response(datasource)


@router.post('/connect', response_model=schemas.DataSourceResponse, mcp=True)
@handle_errors(operation='connect datasource', value_error_status=400)
async def connect_datasource(
    datasource: schemas.DataSourceCreate,
    user: User | None = Depends(get_current_user),
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Connect a new datasource (database, Iceberg, or analysis type).

    For database: config needs {connection_string, query, branch}.
    For Iceberg: config needs {source} where source_type is reingestable today (file/database).
    File datasources must use the /upload endpoint instead.
    Use GET /datasource to verify creation.
    """
    source_type = datasource.source_type
    if (error_message := source_type.connect_api_error_message) is not None:
        raise HTTPException(status_code=400, detail=error_message)

    owner_id = user.id if user else None
    if source_type == DataSourceType.FILE:
        file_config = await asyncio.to_thread(schemas.FileDataSourceConfig.model_validate, datasource.config)
        result = await create_remote_file_datasource(
            runtime_probe=runtime_probe,
            name=datasource.name,
            description=datasource.description,
            file_path=file_config.file_path,
            file_type=file_config.file_type.value,
            options=file_config.options,
            csv_options=file_config.csv_options.model_dump() if file_config.csv_options else None,
            sheet_name=file_config.sheet_name,
            start_row=file_config.start_row,
            start_col=file_config.start_col,
            end_col=file_config.end_col,
            end_row=file_config.end_row,
            has_header=file_config.has_header,
            table_name=file_config.table_name,
            named_range=file_config.named_range,
            cell_range=file_config.cell_range,
            owner_id=owner_id,
        )
        return await json_response(result)
    if source_type == DataSourceType.DATABASE:
        db_config = await asyncio.to_thread(schemas.DatabaseDataSourceConfig.model_validate, datasource.config)
        result = await create_remote_database_datasource(
            runtime_probe=runtime_probe,
            name=datasource.name,
            description=datasource.description,
            connection_string=db_config.connection_string,
            query=db_config.query,
            branch=db_config.branch,
            owner_id=owner_id,
        )
        return await json_response(result)
    if source_type == DataSourceType.ICEBERG:
        iceberg_config = await asyncio.to_thread(schemas.IcebergDataSourceConfig.model_validate, datasource.config)
        result = await create_remote_iceberg_datasource(
            runtime_probe=runtime_probe,
            name=datasource.name,
            description=datasource.description,
            source=iceberg_config.source,
            branch=iceberg_config.branch,
            owner_id=owner_id,
        )
        return await json_response(result)
    raise HTTPException(
        status_code=400,
        detail=(f'Unsupported source type: {datasource.source_type}. Use "file", "database", "iceberg", or "analysis"'),
    )


@router.get('/internal-postgres/tables', response_model=list[schemas.InternalPostgresTable])
@handle_errors(operation='list internal Postgres tables')
def list_internal_postgres_tables(session: Session = Depends(get_db_async)):
    return service.list_internal_postgres_tables(session)


@router.post('/internal-postgres/toggle', response_model=schemas.InternalPostgresTable)
@handle_errors(operation='toggle internal Postgres table', value_error_status=400)
def toggle_internal_postgres_table(
    request: schemas.InternalPostgresToggleRequest,
    session: Session = Depends(get_db_async),
    user: User | None = Depends(get_current_user),
):
    if request.enabled:
        if service.internal_postgres_table_is_onboarded(session, request.schema_name, request.table_name):
            return schemas.InternalPostgresTable(
                schema_name=request.schema_name,
                table_name=request.table_name,
                is_onboarded=True,
            )
        query = service.internal_postgres_table_query(session, request.schema_name, request.table_name)
        service.create_database_datasource_record(
            session,
            name=service.InternalPostgresOnboarding.datasource_name_for(
                request.schema_name,
                request.table_name,
            ),
            description=service.InternalPostgresOnboarding.datasource_description_for(
                request.schema_name,
                request.table_name,
            ),
            connection_string=service.internal_postgres_connection_string(),
            query=query,
            branch='master',
            owner_id=user.id if user else None,
        )
        return schemas.InternalPostgresTable(
            schema_name=request.schema_name,
            table_name=request.table_name,
            is_onboarded=True,
        )
    return service.set_internal_postgres_table_onboarded(
        session,
        request.schema_name,
        request.table_name,
        enabled=False,
    )


@router.get('', response_model=list[schemas.DataSourceListItem], mcp=True)
@handle_errors(operation='list datasources')
async def list_datasources(include_hidden: bool = False):
    """List all datasources with their type, config, and metadata.

    Set include_hidden=true to include auto-generated output datasources created by analyses.
    Each datasource has an id, name, source_type, and config dict.
    """
    datasources = await asyncio.to_thread(run_db, service.list_datasources, include_hidden=include_hidden)
    return await json_response(datasources)


@router.get('/lineage', mcp=True)
@handle_errors(operation='get lineage')
def get_lineage(
    target_datasource_id: DataSourceId | None = None,
    branch: str | None = None,
    include_internals: bool = False,
    mode: str = 'full',
    session: Session = Depends(get_db_async),
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
async def get_datasource(datasource_id: DataSourceId):
    """Get a single datasource by ID with full config and metadata. Use GET /datasource to find IDs."""
    response = await asyncio.to_thread(run_db, service.get_datasource, parse_datasource_id(datasource_id))
    # Branch listing is optional enrichment for analysis outputs (data-plane / object store).
    # Existence of the row is a DB fact — never fail GET when the data-plane is unavailable.
    if response.source_type == DataSourceType.ICEBERG and response.created_by == DataSourceCreatedBy.ANALYSIS.value:
        metadata_path = response.config.get('metadata_path')
        branch_name = response.config.get('branch') if isinstance(response.config.get('branch'), str) else None
        if isinstance(metadata_path, str):
            try:
                response.config['branches'] = await asyncio.to_thread(_list_export_branches, metadata_path, branch_name)
            except Exception:
                logger.warning(
                    'Failed to list export branches for analysis output %s; returning row without live branches',
                    response.id,
                    exc_info=True,
                )
                response.config['branches'] = [branch_name] if branch_name else ['master']
    return await json_response(response)


@router.get('/{datasource_id}/schema', response_model=schemas.SchemaInfo, mcp=True)
@handle_errors(operation='get datasource schema')
async def get_datasource_schema(
    datasource_id: DataSourceId,
    sheet_name: str | None = None,
    refresh: bool = False,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Get the column schema of a datasource (column names, types, nullability).

    For Excel files, pass sheet_name to select a specific sheet.
    Set refresh=true to re-read the schema from the source file.
    """
    datasource_id_value = parse_datasource_id(datasource_id)
    await asyncio.to_thread(run_db, _require_active_datasource, datasource_id_value)
    if refresh:
        datasource = await asyncio.to_thread(run_db, service.get_datasource, datasource_id_value)
        source = datasource.config.get('source') if isinstance(datasource.config, dict) else None
        source_type = DataSourceType.read(source.get('source_type') if isinstance(source, dict) else None, default=None)
        if datasource.source_type == DataSourceType.ICEBERG and source_type is not None and source_type.supports_external_ingestion:
            await ingest_remote_datasource(
                datasource_id=datasource_id_value,
                runtime_probe=runtime_probe,
            )
    schema = None
    if sheet_name is None:
        schema = await asyncio.to_thread(run_db, service.cached_schema, datasource_id_value)
    if schema is None:
        schema = await get_remote_datasource_schema(
            datasource_id=datasource_id_value,
            sheet_name=sheet_name,
            refresh=False,
            runtime_probe=runtime_probe,
        )
    schema = await asyncio.to_thread(run_db, service.attach_column_descriptions, datasource_id_value, schema)
    response = await asyncio.to_thread(schemas.SchemaInfo.model_validate, schema_info_response_payload(schema))
    return await json_response(response)


@router.patch('/{datasource_id}/column-metadata', response_model=schemas.SchemaInfo, mcp=True)
@handle_errors(operation='update datasource column metadata', value_error_status=400)
async def update_datasource_column_metadata(
    datasource_id: DataSourceId,
    payload: schemas.BatchColumnDescriptionUpdate,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Update one or more datasource column descriptions and return the active schema."""
    datasource_id_value = parse_datasource_id(datasource_id)
    await asyncio.to_thread(run_db, _require_active_datasource, datasource_id_value)
    schema = await asyncio.to_thread(run_db, service.cached_schema, datasource_id_value)
    if schema is None:
        schema = await get_remote_datasource_schema(
            datasource_id=datasource_id_value,
            sheet_name=None,
            refresh=False,
            runtime_probe=runtime_probe,
        )
    schema = await asyncio.to_thread(run_db, service.update_column_descriptions, datasource_id_value, payload, schema)
    response = await asyncio.to_thread(schemas.SchemaInfo.model_validate, schema_info_response_payload(schema))
    return await json_response(response)


@router.post(
    '/{datasource_id}/compare-snapshots',
    response_model=schemas.SnapshotCompareResponse,
    mcp=True,
)
@handle_errors(operation='compare datasource snapshots')
async def compare_snapshots(
    datasource_id: DataSourceId,
    payload: schemas.SnapshotCompareRequest,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Compare two Iceberg snapshots of a datasource.

    Returns row count deltas, schema differences, column stats, and data previews for both snapshots.
    Use GET /compute/iceberg/{id}/snapshots to find snapshot IDs.
    """
    datasource_id_value = parse_datasource_id(datasource_id)
    await asyncio.to_thread(run_db, _require_active_datasource, datasource_id_value)
    response = await compare_remote_iceberg_snapshots(
        datasource_id=datasource_id_value,
        snapshot_a=payload.snapshot_a,
        snapshot_b=payload.snapshot_b,
        row_limit=payload.row_limit,
        runtime_probe=runtime_probe,
    )
    return await json_response(response)


async def _handle_column_stats(
    datasource_id: DataSourceId,
    column_name: str,
    sample: bool,
    payload: schemas.ColumnStatsRequest | None,
    runtime_probe: RuntimeAvailabilityProbe,
):
    datasource_id_value = parse_datasource_id(datasource_id)
    await asyncio.to_thread(run_db, _require_active_datasource, datasource_id_value)
    datasource = payload.datasource if payload else None
    config = None
    if isinstance(datasource, dict):
        config = datasource.get('config')
    return await get_remote_column_stats(
        datasource_id=datasource_id_value,
        column_name=column_name,
        use_sample=sample,
        sample_size=10000,
        datasource_config=config if isinstance(config, dict) else None,
        runtime_probe=runtime_probe,
    )


@router.get(
    '/{datasource_id}/column/{column_name}/stats',
    response_model=schemas.ColumnStatsResponse,
    mcp=True,
)
@handle_errors(operation='get column stats')
async def get_column_stats(
    datasource_id: DataSourceId,
    column_name: str,
    sample: bool = True,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Get statistics for a single column: count, nulls, unique values, min/max, mean, histogram.

    Set sample=false for exact stats (slower on large datasets).
    """
    response = await _handle_column_stats(datasource_id, column_name, sample, None, runtime_probe)
    return await json_response(response)


@router.post(
    '/{datasource_id}/column/{column_name}/stats',
    response_model=schemas.ColumnStatsResponse,
    mcp=True,
)
@handle_errors(operation='get column stats')
async def get_column_stats_with_config(
    datasource_id: DataSourceId,
    column_name: str,
    payload: schemas.ColumnStatsRequest,
    sample: bool = True,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Get column statistics with custom datasource config (e.g., different branch or snapshot)."""
    response = await _handle_column_stats(datasource_id, column_name, sample, payload, runtime_probe)
    return await json_response(response)


@router.put('/{datasource_id}', response_model=schemas.DataSourceResponse, mcp=True)
@handle_errors(operation='update datasource')
async def update_datasource(
    datasource_id: DataSourceId,
    update: schemas.DataSourceUpdate,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Update a datasource's name or config. Use GET /datasource/{id} to see current values."""
    datasource_id_value = parse_datasource_id(datasource_id)
    if update.config is None or not any(key in update.config for key in (*_EXCEL_PARSING_KEYS, 'csv_options', 'skip_rows')):
        return await asyncio.to_thread(run_db, service.update_datasource, datasource_id_value, update)

    snapshot = await asyncio.to_thread(run_db, _datasource_update_snapshot, datasource_id_value)
    current_config, expected_revision, source_type, file_type = snapshot
    next_config = {**current_config, **update.config}
    is_excel = (
        DataSourceType.read(source_type, default=None) == DataSourceType.FILE and DataSourceFileType.read(file_type, default=None) == DataSourceFileType.EXCEL
    )
    parsing_changed = is_excel and any(key in update.config and update.config[key] != current_config.get(key) for key in _EXCEL_PARSING_KEYS)
    if not parsing_changed:
        if is_excel:
            simple_config = {key: value for key, value in update.config.items() if key not in _EXCEL_PARSING_KEYS or value != current_config.get(key)}
            update = update.model_copy(update={'config': simple_config})
        return await asyncio.to_thread(run_db, service.update_datasource, datasource_id_value, update)

    source_path = current_config.get('file_path')
    if not isinstance(source_path, str) or not source_path:
        return await asyncio.to_thread(run_db, service.update_datasource, datasource_id_value, update)
    selection = {key: next_config[key] for key in _EXCEL_PARSING_KEYS if key in next_config}
    selection.setdefault('has_header', True)
    resolved = await execute_excel_preflight(
        preflight_id=str(uuid.uuid4()),
        source_path=source_path,
        action=enums_pb2.DATASOURCE_PREFLIGHT_ACTION_RESOLVE_SELECTION,
        selection=selection,
        runtime_probe=runtime_probe,
        delete_source=False,
        datasource_id=datasource_id_value,
    )
    return await asyncio.to_thread(
        run_db,
        service.update_datasource,
        datasource_id_value,
        update,
        resolved_excel_selection=resolved_selection(resolved),
        expected_revision=expected_revision,
    )


@router.post('/{datasource_id}/ingest', response_model=schemas.DataSourceResponse, mcp=True)
@handle_errors(operation='ingest datasource')
async def ingest_datasource(
    datasource_id: DataSourceId,
    runtime_probe: RuntimeAvailabilityProbe = Depends(get_runtime_availability_probe),
):
    """Ingest an external datasource again from source. Useful after upstream data changes."""
    datasource_id_value = parse_datasource_id(datasource_id)
    await asyncio.to_thread(run_db, _require_active_datasource, datasource_id_value)
    response = await ingest_remote_datasource(
        datasource_id=datasource_id_value,
        runtime_probe=runtime_probe,
    )
    return await json_response(response)


@router.delete('/{datasource_id}', status_code=202, mcp=True)
@handle_errors(operation='delete datasource')
def delete_datasource(
    datasource_id: DataSourceId,
    session: Session = Depends(get_db_async),
):
    """Queue datasource deletion and finalize it once the preview engine is fully drained."""
    datasource_id_value = parse_datasource_id(datasource_id)
    datasource_delete_service.request_delete(session, datasource_id_value)
    return {'accepted': True}
