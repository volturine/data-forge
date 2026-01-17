import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from modules.datasource import schemas, service

router = APIRouter(prefix='/datasource', tags=['datasource'])


@router.post('/upload', response_model=schemas.DataSourceResponse)
async def upload_file(
    file: UploadFile,
    name: str = Form(...),
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
        '.ndjson': 'json',
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

    try:
        return await service.create_file_datasource(
            session=session,
            name=name,
            file_path=str(file_path),
            file_type=file_type,
        )
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f'Failed to create datasource: {str(e)}')


@router.post('/connect', response_model=schemas.DataSourceResponse)
async def connect_datasource(
    datasource: schemas.DataSourceCreate,
    session: AsyncSession = Depends(get_db),
):
    """Create a database or API data source connection."""
    try:
        if datasource.source_type == 'database':
            config = schemas.DatabaseDataSourceConfig.model_validate(datasource.config)
            return await service.create_database_datasource(
                session=session,
                name=datasource.name,
                connection_string=config.connection_string,
                query=config.query,
            )
        elif datasource.source_type == 'api':
            config = schemas.APIDataSourceConfig.model_validate(datasource.config)
            return await service.create_api_datasource(
                session=session,
                name=datasource.name,
                url=config.url,
                method=config.method,
                headers=config.headers,
                auth=config.auth,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f'Unsupported source type: {datasource.source_type}. Use "database" or "api"',
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
        # Surface details in body while keeping 500 status
        return JSONResponse(status_code=500, content={'detail': f'Failed to list datasources: {str(e)}'})


@router.get('/{datasource_id}', response_model=schemas.DataSourceResponse)
async def get_datasource(
    datasource_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Get a single data source by ID."""
    try:
        return await service.get_datasource(session, datasource_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to get datasource: {str(e)}')


@router.get('/{datasource_id}/schema', response_model=schemas.SchemaInfo)
async def get_datasource_schema(
    datasource_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Get schema information for a data source."""
    try:
        return await service.get_datasource_schema(session, datasource_id)
    except ValueError as e:
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to delete datasource: {str(e)}')
