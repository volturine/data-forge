import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import DataSourceNotFoundError, DataSourceValidationError, FileError
from modules.compute.operations.datasource import load_datasource
from modules.datasource.models import DataSource
from modules.datasource.schemas import ColumnSchema, CSVOptions, DataSourceResponse, SchemaInfo

logger = logging.getLogger(__name__)


async def create_file_datasource(
    session: AsyncSession,
    name: str,
    file_path: str,
    file_type: str,
    options: dict | None = None,
    csv_options: CSVOptions | None = None,
) -> DataSourceResponse:
    """Create a file-based datasource."""
    datasource_id = str(uuid.uuid4())

    config = {
        'file_path': file_path,
        'file_type': file_type,
        'options': options or {},
        'csv_options': csv_options.model_dump() if csv_options else None,
    }

    datasource = DataSource(
        id=datasource_id,
        name=name,
        source_type='file',
        config=config,
        created_at=datetime.now(UTC),
    )

    session.add(datasource)
    await session.commit()
    await session.refresh(datasource)

    logger.info(f'Created file datasource {datasource_id} ({name}) with file {file_path}')
    return DataSourceResponse.model_validate(datasource)


async def create_database_datasource(
    session: AsyncSession,
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
    await session.commit()
    await session.refresh(datasource)

    return DataSourceResponse.model_validate(datasource)


async def create_api_datasource(
    session: AsyncSession,
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
    await session.commit()
    await session.refresh(datasource)

    return DataSourceResponse.model_validate(datasource)


async def create_duckdb_datasource(
    session: AsyncSession,
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
    await session.commit()
    await session.refresh(datasource)

    logger.info(f'Created DuckDB datasource {datasource_id} ({name})')
    return DataSourceResponse.model_validate(datasource)


async def get_datasource_schema(session: AsyncSession, datasource_id: str) -> SchemaInfo:
    """Get or extract schema for a datasource."""
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    # Check if we have cached schema with row_count
    if datasource.schema_cache:
        cached = SchemaInfo.model_validate(datasource.schema_cache)
        # If row_count is missing from cache, re-extract to get it
        if cached.row_count is not None:
            logger.debug(f'Using cached schema for datasource {datasource_id}')
            return cached

    logger.info(f'Extracting schema for datasource {datasource_id}')
    schema_info = await _extract_schema(datasource)

    datasource.schema_cache = schema_info.model_dump()
    await session.commit()

    logger.info(f'Schema extracted and cached for datasource {datasource_id}: {len(schema_info.columns)} columns')
    return schema_info


async def _extract_schema(datasource: DataSource) -> SchemaInfo:
    if datasource.source_type == 'file':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        lazy = load_datasource(config)
        schema = lazy.collect_schema()
        row_count = lazy.select(pl.len()).collect().item()

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    if datasource.source_type == 'database':
        connection_string = datasource.config['connection_string']
        query = datasource.config['query']

        frame = pl.read_database(query, connection_string)
        schema = frame.schema
        row_count = frame.height

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    if datasource.source_type == 'duckdb':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        frame = load_datasource(config).collect()
        schema = frame.schema
        row_count = frame.height

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    raise DataSourceValidationError(
        f'Schema extraction not supported for type: {datasource.source_type}',
        details={'source_type': datasource.source_type},
    )


async def get_datasource(session: AsyncSession, datasource_id: str) -> DataSourceResponse:
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    return DataSourceResponse.model_validate(datasource)


async def list_datasources(session: AsyncSession) -> list[DataSourceResponse]:
    result = await session.execute(select(DataSource))
    datasources = result.scalars().all()
    return [DataSourceResponse.model_validate(ds) for ds in datasources]


async def delete_datasource(session: AsyncSession, datasource_id: str) -> None:
    """Delete a datasource and its associated file if it exists."""
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

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

    await session.delete(datasource)
    await session.commit()
    logger.info(f'Deleted datasource {datasource_id}')
