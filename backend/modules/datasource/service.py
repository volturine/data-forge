import uuid
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.datasource.models import DataSource
from modules.datasource.schemas import (
    ColumnSchema,
    DataSourceResponse,
    SchemaInfo,
)


async def create_file_datasource(
    session: AsyncSession,
    name: str,
    file_path: str,
    file_type: str,
    options: dict | None = None,
) -> DataSourceResponse:
    datasource_id = str(uuid.uuid4())

    config = {
        'file_path': file_path,
        'file_type': file_type,
        'options': options or {},
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


async def get_datasource_schema(session: AsyncSession, datasource_id: str) -> SchemaInfo:
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    if datasource.schema_cache:
        return SchemaInfo.model_validate(datasource.schema_cache)

    schema_info = await _extract_schema(datasource)

    datasource.schema_cache = schema_info.model_dump()
    await session.commit()

    return schema_info


async def _extract_schema(datasource: DataSource) -> SchemaInfo:
    if datasource.source_type == 'file':
        file_path = datasource.config['file_path']
        file_type = datasource.config['file_type']

        if file_type == 'csv':
            df = pl.scan_csv(file_path)
        elif file_type == 'parquet':
            df = pl.scan_parquet(file_path)
        elif file_type == 'json':
            df = pl.scan_ndjson(file_path)
        elif file_type == 'excel':
            df = pl.read_excel(file_path).lazy()
        else:
            raise ValueError(f'Unsupported file type: {file_type}')

        schema = df.collect_schema()
        # Calculate row count for file datasources
        row_count = df.select(pl.len()).collect().item()

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    elif datasource.source_type == 'database':
        connection_string = datasource.config['connection_string']
        query = datasource.config['query']

        df = pl.read_database(query, connection_string)
        schema = df.schema
        row_count = len(df)

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    else:
        raise ValueError(f'Schema extraction not supported for type: {datasource.source_type}')


async def get_datasource(session: AsyncSession, datasource_id: str) -> DataSourceResponse:
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    return DataSourceResponse.model_validate(datasource)


async def list_datasources(session: AsyncSession) -> list[DataSourceResponse]:
    result = await session.execute(select(DataSource))
    datasources = result.scalars().all()
    return [DataSourceResponse.model_validate(ds) for ds in datasources]


async def delete_datasource(session: AsyncSession, datasource_id: str) -> None:
    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    if datasource.source_type == 'file' and 'file_path' in datasource.config:
        file_path = Path(datasource.config['file_path'])
        if file_path.exists():
            file_path.unlink()

    await session.delete(datasource)
    await session.commit()
