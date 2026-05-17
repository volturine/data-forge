from collections.abc import Callable
from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class SinkFormat:
    extension: str
    content_type: str
    sink: Callable[[pl.LazyFrame, str], None]
    scanner: Callable[[str], pl.LazyFrame]
    df_writer: Callable[[pl.DataFrame, str], None]

    def write(self, lf: pl.LazyFrame, path: str) -> int:
        self.sink(lf, path)
        return self.scanner(path).select(pl.len()).collect().item()

    def write_df(self, df: pl.DataFrame, path: str) -> None:
        self.df_writer(df, path)


@dataclass(frozen=True)
class CollectFormat:
    extension: str
    content_type: str
    df_writer: Callable[[pl.DataFrame, str], None]

    def write(self, lf: pl.LazyFrame, path: str) -> int:
        df = lf.collect()
        self.df_writer(df, path)
        return len(df)

    def write_df(self, df: pl.DataFrame, path: str) -> None:
        self.df_writer(df, path)


ExportFormat = SinkFormat | CollectFormat


def _write_duckdb(df: pl.DataFrame, path: str) -> None:
    import duckdb

    conn = duckdb.connect(path)
    try:
        conn.execute('CREATE TABLE data AS SELECT * FROM df')
    finally:
        conn.close()


EXPORT_FORMATS: dict[str, ExportFormat] = {
    'csv': SinkFormat(
        extension='.csv', content_type='text/csv', sink=lambda lf, path: lf.sink_csv(path), scanner=pl.scan_csv, df_writer=lambda df, path: df.write_csv(path)
    ),
    'parquet': SinkFormat(
        extension='.parquet',
        content_type='application/octet-stream',
        sink=lambda lf, path: lf.sink_parquet(path),
        scanner=pl.scan_parquet,
        df_writer=lambda df, path: df.write_parquet(path),
    ),
    'json': CollectFormat(extension='.json', content_type='application/json', df_writer=lambda df, path: df.write_json(path)),
    'ndjson': CollectFormat(extension='.ndjson', content_type='application/x-ndjson', df_writer=lambda df, path: df.write_ndjson(path)),
    'excel': CollectFormat(
        extension='.xlsx', content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', df_writer=lambda df, path: df.write_excel(path)
    ),
    'duckdb': CollectFormat(extension='.duckdb', content_type='application/octet-stream', df_writer=_write_duckdb),
}


def get_export_format(name: str) -> ExportFormat:
    fmt = EXPORT_FORMATS.get(name)
    if not fmt:
        raise ValueError(f'Unsupported export format: {name}')
    return fmt
