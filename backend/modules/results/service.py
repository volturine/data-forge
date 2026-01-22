from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from core.config import settings
from modules.results.schemas import ColumnSchema, ResultDataSchema, ResultMetadataSchema


def _get_result_path(analysis_id: str) -> Path:
    return settings.results_dir / f'{analysis_id}.parquet'


async def store_result(analysis_id: str, df: pl.DataFrame) -> None:
    """Store analysis result as parquet file."""
    result_path = _get_result_path(analysis_id)
    df.write_parquet(result_path)


async def get_result_metadata(analysis_id: str) -> ResultMetadataSchema:
    """Get metadata about stored result."""
    result_path = _get_result_path(analysis_id)

    if not result_path.exists():
        raise ValueError(f'Result {analysis_id} not found')

    df = pl.scan_parquet(result_path)
    schema = df.collect_schema()
    row_count = df.select(pl.len()).collect().item()

    columns = [ColumnSchema(name=name, dtype=str(dtype)) for name, dtype in schema.items()]

    return ResultMetadataSchema(
        analysis_id=analysis_id,
        row_count=row_count,
        column_count=len(columns),
        columns_schema=columns,
        created_at=datetime.fromtimestamp(result_path.stat().st_mtime, tz=UTC),
    )


async def get_result_data(analysis_id: str, page: int = 1, page_size: int = 100) -> ResultDataSchema:
    """Get paginated result data."""
    result_path = _get_result_path(analysis_id)

    if not result_path.exists():
        raise ValueError(f'Result {analysis_id} not found')

    df = pl.scan_parquet(result_path)
    total_count = df.select(pl.len()).collect().item()

    offset = (page - 1) * page_size
    paginated_df = df.slice(offset, page_size).collect()

    columns = paginated_df.columns
    data = paginated_df.to_dicts()

    return ResultDataSchema(columns=columns, data=data, total_count=total_count, page=page, page_size=page_size)


async def export_result(analysis_id: str, format: str) -> Path:
    """Export result to requested format."""
    import os
    import tempfile

    import duckdb

    result_path = _get_result_path(analysis_id)

    if not result_path.exists():
        raise ValueError(f'Result {analysis_id} not found')

    df = pl.read_parquet(result_path)

    export_path = settings.results_dir / f'{analysis_id}.{format}'

    if format == 'csv':
        df.write_csv(export_path)
    elif format == 'parquet':
        export_path = result_path
    elif format == 'excel':
        df.write_excel(export_path)
    elif format == 'json':
        df.write_json(export_path)
    elif format == 'duckdb':
        with tempfile.NamedTemporaryFile(suffix='.duckdb', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            conn = duckdb.connect(tmp_path)
            conn.execute('CREATE TABLE data AS SELECT * FROM df')
            conn.close()

            with open(tmp_path, 'rb') as f:
                export_path.write_bytes(f.read())
        finally:
            os.unlink(tmp_path)
    else:
        raise ValueError(f'Unsupported format: {format}')

    return export_path


async def delete_result(analysis_id: str) -> None:
    """Delete stored result file."""
    result_path = _get_result_path(analysis_id)

    if not result_path.exists():
        raise ValueError(f'Result {analysis_id} not found')

    result_path.unlink()

    export_extensions = ['csv', 'excel', 'json']
    for ext in export_extensions:
        export_path = settings.results_dir / f'{analysis_id}.{ext}'
        if export_path.exists():
            export_path.unlink()
