from collections.abc import Callable
from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class ExportFormat:
    extension: str
    content_type: str
    writer: Callable[[pl.DataFrame, str], None]


def _write_duckdb(df: pl.DataFrame, path: str) -> None:
    import duckdb

    conn = duckdb.connect(path)
    try:
        conn.execute('CREATE TABLE data AS SELECT * FROM df')
    finally:
        conn.close()


EXPORT_FORMATS: dict[str, ExportFormat] = {
    'csv': ExportFormat('.csv', 'text/csv', lambda df, path: df.write_csv(path)),
    'parquet': ExportFormat('.parquet', 'application/octet-stream', lambda df, path: df.write_parquet(path)),
    'json': ExportFormat('.json', 'application/json', lambda df, path: df.write_json(path)),
    'ndjson': ExportFormat('.ndjson', 'application/x-ndjson', lambda df, path: df.write_ndjson(path)),
    'excel': ExportFormat(
        '.xlsx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        lambda df, path: df.write_excel(path),
    ),
    'duckdb': ExportFormat('.duckdb', 'application/octet-stream', _write_duckdb),
}


def get_export_format(name: str) -> ExportFormat:
    fmt = EXPORT_FORMATS.get(name)
    if not fmt:
        raise ValueError(f'Unsupported export format: {name}')
    return fmt
