import uuid
from pathlib import Path
from shutil import copy2

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from core.exceptions import DataSourceNotFoundError
from modules.datasource import schemas, service
from modules.datasource.preflight import clear_preflight, create_preflight, get_preflight

router = APIRouter(prefix='/datasource', tags=['datasource'])


@router.post('/upload', response_model=schemas.DataSourceResponse)
async def upload_file(
    file: UploadFile,
    name: str = Form(...),
    delimiter: str = Form(','),
    quote_char: str = Form('"'),
    has_header: bool = Form(True),
    skip_rows: int = Form(0),
    encoding: str = Form('utf8'),
    session: AsyncSession = Depends(get_db),
):
    """Upload a file and create a data source."""
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

    file_type = file_type_mapping[file_extension]
    unique_filename = f'{uuid.uuid4()}{file_extension}'
    file_path = settings.upload_dir / unique_filename

    try:
        contents = await file.read()
        with open(file_path, 'wb') as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to save file: {str(e)}')

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
        return await service.create_file_datasource(
            session=session,
            name=name,
            file_path=str(file_path),
            file_type=file_type,
            csv_options=csv_options,
        )
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f'Failed to create datasource: {str(e)}')


@router.post('/preflight', response_model=schemas.ExcelPreflightResponse)
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

    unique_filename = f'{uuid.uuid4()}{file_extension}'
    file_path = settings.upload_dir / unique_filename
    try:
        contents = await file.read()
        with open(file_path, 'wb') as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to save file: {str(e)}')

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
async def preflight_preview(
    preflight_id: str,
    sheet_name: str,
    start_row: int = 0,
    start_col: int = 0,
    end_col: int = 0,
    has_header: bool = True,
    table_name: str | None = None,
    named_range: str | None = None,
):
    preflight = get_preflight(preflight_id)
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
    session: AsyncSession = Depends(get_db),
):
    preflight = get_preflight(preflight_id)
    if not preflight:
        raise HTTPException(status_code=404, detail='Preflight not found')

    target_sheet = sheet_name or (preflight.sheets[0] if preflight.sheets else None)
    if not target_sheet:
        clear_preflight(preflight_id)
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
        datasource = await service.create_file_datasource(
            session=session,
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
        clear_preflight(preflight_id)
        raise HTTPException(status_code=500, detail=f'Failed to create datasource: {str(e)}')

    clear_preflight(preflight_id)
    return datasource


@router.post('/connect', response_model=schemas.DataSourceResponse)
async def connect_datasource(
    datasource: schemas.DataSourceCreate,
    session: AsyncSession = Depends(get_db),
):
    """Create a database or API data source connection."""
    try:
        if datasource.source_type == 'database':
            db_config = schemas.DatabaseDataSourceConfig.model_validate(datasource.config)
            return await service.create_database_datasource(
                session=session,
                name=datasource.name,
                connection_string=db_config.connection_string,
                query=db_config.query,
            )
        if datasource.source_type == 'api':
            api_config = schemas.APIDataSourceConfig.model_validate(datasource.config)
            return await service.create_api_datasource(
                session=session,
                name=datasource.name,
                url=api_config.url,
                method=api_config.method,
                headers=api_config.headers,
                auth=api_config.auth,
            )
        if datasource.source_type == 'duckdb':
            duckdb_config = schemas.DuckDBDataSourceConfig.model_validate(datasource.config)
            return await service.create_duckdb_datasource(
                session=session,
                name=datasource.name,
                db_path=duckdb_config.db_path,
                query=duckdb_config.query,
                read_only=duckdb_config.read_only,
            )
        raise HTTPException(
            status_code=400,
            detail=f'Unsupported source type: {datasource.source_type}. Use "database", "api", or "duckdb"',
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to create datasource: {str(e)}')


@router.get('', response_model=list[schemas.DataSourceResponse])
async def list_datasources(session: AsyncSession = Depends(get_db)):
    """List all data sources."""
    try:
        return await service.list_datasources(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to list datasources: {str(e)}')


@router.get('/{datasource_id}', response_model=schemas.DataSourceResponse)
async def get_datasource(
    datasource_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Get a single data source by ID."""
    try:
        return await service.get_datasource(session, datasource_id)
    except (ValueError, DataSourceNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get datasource: {str(e)}')


@router.get('/{datasource_id}/schema', response_model=schemas.SchemaInfo)
async def get_datasource_schema(
    datasource_id: str,
    sheet_name: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    """Get schema information for a data source."""
    try:
        return await service.get_datasource_schema(session, datasource_id, sheet_name=sheet_name)
    except (ValueError, DataSourceNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get schema: {str(e)}')


@router.delete('/{datasource_id}')
async def delete_datasource(
    datasource_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Delete a data source and associated file."""
    try:
        await service.delete_datasource(session, datasource_id)
        return {'message': f'DataSource {datasource_id} deleted successfully'}
    except (ValueError, DataSourceNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to delete datasource: {str(e)}')
