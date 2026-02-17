import uuid
from pathlib import Path
from shutil import copy2
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from core.config import settings
from core.database import get_db, run_db
from core.error_handlers import handle_errors
from core.exceptions import DataSourceNotFoundError, DataSourceValidationError
from core.validation import DataSourceId, PreflightId, parse_datasource_id, parse_preflight_id
from modules.compute.operations.datasource import resolve_iceberg_metadata_path
from modules.datasource import schemas, service
from modules.datasource.preflight import clear_preflight, create_preflight, get_preflight

router = APIRouter(prefix='/datasource', tags=['datasource'])


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
):
    if not file.filename:
        raise HTTPException(status_code=400, detail='No filename provided')

    file_extension = Path(file.filename).suffix.lower()
    file_type_mapping = {
        '.csv': 'csv',
        '.parquet': 'parquet',
        '.json': 'json',
        '.ndjson': 'ndjson',
        '.jsonl': 'ndjson',
        '.xlsx': 'excel',
    }

    if file_extension not in file_type_mapping:
        raise HTTPException(
            status_code=400,
            detail=f'Unsupported file type: {file_extension}. Supported types: {", ".join(file_type_mapping.keys())}',
        )

    if not _matches_magic_number(file_extension, file):
        raise HTTPException(status_code=400, detail='File content does not match extension')
    file_type = file_type_mapping[file_extension]
    unique_filename = f'{uuid.uuid4()}{file_extension}'
    file_path = settings.upload_dir / unique_filename

    max_bytes = settings.upload_max_file_size_bytes
    total = 0
    try:
        with open(file_path, 'wb') as f:
            while True:
                chunk = await file.read(settings.upload_chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes and total > max_bytes:
                    raise HTTPException(status_code=413, detail='Uploaded file exceeds size limit')
                f.write(chunk)
    except HTTPException:
        if file_path.exists():
            file_path.unlink()
        raise
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f'Failed to save file: {str(e)}') from e

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
        return await run_in_threadpool(
            run_db,
            service.create_file_datasource,
            name=name,
            file_path=str(file_path),
            file_type=file_type,
            csv_options=csv_options,
        )
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f'Failed to create datasource: {str(e)}') from e


@router.post('/upload/bulk', response_model=schemas.BulkUploadResponse)
@handle_errors(operation='bulk upload datasources', value_error_status=400)
async def upload_bulk(
    files: list[UploadFile],
    delimiter: str = Form(','),
    quote_char: str = Form('"'),
    has_header: bool = Form(True),
    skip_rows: int = Form(0),
    encoding: str = Form('utf8'),
):
    if not files:
        raise HTTPException(status_code=400, detail='No files provided')

    file_type_mapping = {
        '.csv': 'csv',
        '.parquet': 'parquet',
        '.json': 'json',
        '.ndjson': 'ndjson',
        '.jsonl': 'ndjson',
        '.xlsx': 'excel',
    }

    csv_options = schemas.CSVOptions(
        delimiter=delimiter,
        quote_char=quote_char,
        has_header=has_header,
        skip_rows=skip_rows,
        encoding=encoding,
    )

    results: list[schemas.BulkUploadResult] = []

    for file in files:
        if not file.filename:
            results.append(schemas.BulkUploadResult(name='unknown', success=False, error='No filename provided'))
            continue

        file_extension = Path(file.filename).suffix.lower()

        if file_extension not in file_type_mapping:
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=f'Unsupported file type: {file_extension}'))
            continue

        if not _matches_magic_number(file_extension, file):
            results.append(
                schemas.BulkUploadResult(
                    name=file.filename,
                    success=False,
                    error='File content does not match extension',
                )
            )
            continue
        file_type = file_type_mapping[file_extension]
        unique_filename = f'{uuid.uuid4()}{file_extension}'
        file_path = settings.upload_dir / unique_filename
        name = Path(file.filename).stem

        max_bytes = settings.upload_max_file_size_bytes
        total = 0
        try:
            with open(file_path, 'wb') as f:
                while True:
                    chunk = await file.read(settings.upload_chunk_size)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise HTTPException(status_code=413, detail='Uploaded file exceeds size limit')
                    f.write(chunk)
        except HTTPException as exc:
            if file_path.exists():
                file_path.unlink()
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=str(exc.detail)))
            continue
        except Exception as e:
            if file_path.exists():
                file_path.unlink()
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=f'Failed to save file: {str(e)}'))
            continue

        file_csv_options = csv_options if file_type == 'csv' else None
        try:
            datasource = await run_in_threadpool(
                run_db,
                service.create_file_datasource,
                name=name,
                file_path=str(file_path),
                file_type=file_type,
                csv_options=file_csv_options,
            )
            results.append(schemas.BulkUploadResult(name=file.filename, success=True, datasource=datasource))
        except Exception as e:
            if file_path.exists():
                file_path.unlink()
            results.append(schemas.BulkUploadResult(name=file.filename, success=False, error=f'Failed to create datasource: {str(e)}'))

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
    has_header: bool = Form(True),
    table_name: str | None = Form(None),
    named_range: str | None = Form(None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail='No filename provided')
    file_extension = Path(file.filename).suffix.lower()
    if file_extension != '.xlsx':
        raise HTTPException(status_code=400, detail='Only .xlsx files are supported for preflight')
    if not _matches_magic_number(file_extension, file):
        raise HTTPException(status_code=400, detail='File content does not match extension')

    unique_filename = f'{uuid.uuid4()}{file_extension}'
    file_path = settings.upload_dir / unique_filename
    max_bytes = settings.upload_max_file_size_bytes
    total = 0
    try:
        with open(file_path, 'wb') as f:
            while True:
                chunk = await file.read(settings.upload_chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes and total > max_bytes:
                    raise HTTPException(status_code=413, detail='Uploaded file exceeds size limit')
                f.write(chunk)
    except HTTPException:
        if file_path.exists():
            file_path.unlink()
        raise
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f'Failed to save file: {str(e)}') from e

    preflight_id, preflight = create_preflight(file_path)
    target_sheet = sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        clear_preflight(preflight_id)
        raise HTTPException(status_code=400, detail='No sheets found in file')

    preview_result = service.build_excel_preview(
        file_path=file_path,
        sheet_name=target_sheet,
        start_row=start_row,
        start_col=start_col,
        end_col=end_col,
        has_header=has_header,
        table_name=table_name,
        named_range=named_range,
    )

    return schemas.ExcelPreflightResponse(
        preflight_id=preflight_id,
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
    has_header: bool = True,
    table_name: str | None = None,
    named_range: str | None = None,
):
    preflight = get_preflight(parse_preflight_id(preflight_id))
    if not preflight:
        raise HTTPException(status_code=404, detail='Preflight not found')

    preview_result = service.build_excel_preview(
        file_path=preflight.temp_path,
        sheet_name=sheet_name,
        start_row=start_row,
        start_col=start_col,
        end_col=end_col,
        has_header=has_header,
        table_name=table_name,
        named_range=named_range,
    )
    return schemas.ExcelPreflightPreviewResponse(
        preview=preview_result.preview,
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
    has_header: bool = Form(True),
    table_name: str | None = Form(None),
    named_range: str | None = Form(None),
):
    preflight = get_preflight(parse_preflight_id(preflight_id))
    if not preflight:
        raise HTTPException(status_code=404, detail='Preflight not found')

    target_sheet = sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        clear_preflight(parse_preflight_id(preflight_id))
        raise HTTPException(status_code=400, detail='No sheet selected')

    file_extension = preflight.temp_path.suffix.lower()
    target_filename = f'{uuid.uuid4()}{file_extension}'
    target_path = settings.upload_dir / target_filename

    try:
        copy2(preflight.temp_path, target_path)
        resolved_sheet, resolved_start_row, resolved_start_col, resolved_end_col, resolved_end_row = service.resolve_excel_selection(
            preflight.temp_path,
            target_sheet,
            start_row,
            start_col,
            end_col,
            table_name,
            named_range,
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
        )
    except Exception as e:
        if target_path.exists():
            target_path.unlink()
        clear_preflight(parse_preflight_id(preflight_id))
        raise HTTPException(status_code=500, detail=f'Failed to create datasource: {str(e)}') from e

    clear_preflight(parse_preflight_id(preflight_id))
    return datasource


@router.post('/connect', response_model=schemas.DataSourceResponse)
@handle_errors(operation='connect datasource', value_error_status=400)
def connect_datasource(
    datasource: schemas.DataSourceCreate,
    session: Session = Depends(get_db),
):
    if datasource.source_type == 'database':
        db_config = schemas.DatabaseDataSourceConfig.model_validate(datasource.config)
        return service.create_database_datasource(
            session=session,
            name=datasource.name,
            connection_string=db_config.connection_string,
            query=db_config.query,
        )
    if datasource.source_type == 'api':
        api_config = schemas.APIDataSourceConfig.model_validate(datasource.config)
        parsed = urlparse(api_config.url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise HTTPException(status_code=400, detail='API URL must be http or https')
        return service.create_api_datasource(
            session=session,
            name=datasource.name,
            url=api_config.url,
            method=api_config.method,
            headers=api_config.headers,
            auth=api_config.auth,
        )
    if datasource.source_type == 'file':
        file_config = schemas.FileDataSourceConfig.model_validate(datasource.config)
        return service.create_file_datasource(
            session=session,
            name=datasource.name,
            file_path=file_config.file_path,
            file_type=file_config.file_type,
            csv_options=file_config.csv_options,
            sheet_name=file_config.sheet_name,
            start_row=file_config.start_row,
            start_col=file_config.start_col,
            end_col=file_config.end_col,
            end_row=file_config.end_row,
            has_header=file_config.has_header,
            table_name=file_config.table_name,
            named_range=file_config.named_range,
        )
    if datasource.source_type == 'duckdb':
        duckdb_config = schemas.DuckDBDataSourceConfig.model_validate(datasource.config)
        return service.create_duckdb_datasource(
            session=session,
            name=datasource.name,
            db_path=duckdb_config.db_path,
            query=duckdb_config.query,
            read_only=duckdb_config.read_only,
        )
    if datasource.source_type == 'iceberg':
        iceberg_config = schemas.IcebergDataSourceConfig.model_validate(datasource.config)
        return service.create_iceberg_datasource(
            session=session,
            name=datasource.name,
            metadata_path=iceberg_config.metadata_path,
            snapshot_id=iceberg_config.snapshot_id,
            snapshot_timestamp_ms=iceberg_config.snapshot_timestamp_ms,
            storage_options=iceberg_config.storage_options,
            reader=iceberg_config.reader,
            catalog_type=iceberg_config.catalog_type,
            catalog_uri=iceberg_config.catalog_uri,
            warehouse=iceberg_config.warehouse,
            namespace=iceberg_config.namespace,
            table=iceberg_config.table,
        )
    if datasource.source_type == 'analysis':
        analysis_id = datasource.config.get('analysis_id')
        analysis_tab_id = datasource.config.get('analysis_tab_id')
        if not analysis_id:
            raise HTTPException(status_code=400, detail='analysis_id required for analysis datasource')
        return service.create_analysis_datasource(
            session=session,
            name=datasource.name,
            analysis_id=str(analysis_id),
            analysis_tab_id=str(analysis_tab_id) if analysis_tab_id else None,
        )
    raise HTTPException(
        status_code=400,
        detail=(f'Unsupported source type: {datasource.source_type}. Use "file", "database", "api", "duckdb", "iceberg", or "analysis"'),
    )


@router.get('', response_model=list[schemas.DataSourceResponse])
@handle_errors(operation='list datasources')
def list_datasources(include_hidden: bool = False, session: Session = Depends(get_db)):
    """List all data sources. Set include_hidden=true to include auto-generated hidden datasources."""
    return service.list_datasources(session, include_hidden=include_hidden)


@router.get('/lineage')
@handle_errors(operation='get lineage')
def get_lineage(session: Session = Depends(get_db)):
    from modules.datasource.service_lineage import build_lineage

    return build_lineage(session)


@router.get('/{datasource_id}', response_model=schemas.DataSourceResponse)
@handle_errors(operation='get datasource')
def get_datasource(
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    try:
        return service.get_datasource(session, parse_datasource_id(datasource_id))
    except DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataSourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/{datasource_id}/schema', response_model=schemas.SchemaInfo)
@handle_errors(operation='get datasource schema')
def get_datasource_schema(
    datasource_id: DataSourceId,
    sheet_name: str | None = None,
    refresh: bool = False,
    session: Session = Depends(get_db),
):
    try:
        return service.get_datasource_schema(session, parse_datasource_id(datasource_id), sheet_name=sheet_name, refresh=refresh)
    except DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataSourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _handle_column_stats(
    datasource_id: DataSourceId,
    column_name: str,
    sample: bool,
    payload: schemas.ColumnStatsRequest | None,
    session: Session,
):
    return service.get_column_stats(
        session=session,
        datasource_id=parse_datasource_id(datasource_id),
        column_name=column_name,
        use_sample=sample,
        datasource_config=payload.datasource_config if payload else None,
    )


@router.get('/{datasource_id}/column/{column_name}/stats', response_model=schemas.ColumnStatsResponse)
@handle_errors(operation='get column stats')
def get_column_stats(
    datasource_id: DataSourceId,
    column_name: str,
    sample: bool = True,
    session: Session = Depends(get_db),
):
    try:
        return _handle_column_stats(datasource_id, column_name, sample, None, session)
    except DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataSourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/{datasource_id}/column/{column_name}/stats', response_model=schemas.ColumnStatsResponse)
@handle_errors(operation='get column stats')
def get_column_stats_with_config(
    datasource_id: DataSourceId,
    column_name: str,
    payload: schemas.ColumnStatsRequest,
    sample: bool = True,
    session: Session = Depends(get_db),
):
    try:
        return _handle_column_stats(datasource_id, column_name, sample, payload, session)
    except DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataSourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/iceberg/resolve')
@handle_errors(operation='resolve iceberg metadata', value_error_status=400)
async def resolve_iceberg(metadata_path: str):
    resolved = resolve_iceberg_metadata_path(metadata_path)
    return {'metadata_path': resolved}


@router.get('/file/list', response_model=schemas.FileListResponse)
@handle_errors(operation='list data files', value_error_status=400)
async def list_files(path: str | None = None):
    return service.list_data_files(path)


@router.put('/{datasource_id}', response_model=schemas.DataSourceResponse)
@handle_errors(operation='update datasource')
def update_datasource(
    datasource_id: DataSourceId,
    update: schemas.DataSourceUpdate,
    session: Session = Depends(get_db),
):
    try:
        return service.update_datasource(session, parse_datasource_id(datasource_id), update)
    except DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataSourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete('/{datasource_id}', status_code=204)
@handle_errors(operation='delete datasource')
def delete_datasource(
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    datasource_id_value = parse_datasource_id(datasource_id)
    try:
        service.delete_datasource(session, datasource_id_value)
    except DataSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return None
