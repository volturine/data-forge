from collections.abc import Callable

import polars as pl

from modules.compute.operations.base import OperationHandler, OperationParams


class DatasourceParams(OperationParams):
    source_type: str = 'file'
    file_path: str | None = None
    file_type: str | None = None
    options: dict | None = None
    csv_options: dict | None = None
    connection_string: str | None = None
    query: str | None = None
    db_path: str | None = None
    read_only: bool = True


class DatasourceHandler(OperationHandler):
    FILE_LOADERS: dict[str, Callable[[str, dict], pl.LazyFrame]] = {
        'csv': lambda path, opts: pl.scan_csv(path, **DatasourceHandler._csv_opts(opts)),
        'parquet': lambda path, _: pl.scan_parquet(path),
        'json': lambda path, _: pl.read_json(path).lazy(),
        'ndjson': lambda path, _: pl.scan_ndjson(path),
        'excel': lambda path, _: pl.read_excel(path).lazy(),
    }

    @property
    def name(self) -> str:
        return 'datasource'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = DatasourceParams.model_validate(params)
        loaders = {
            'file': self._load_file,
            'database': self._load_database,
            'duckdb': self._load_duckdb,
        }
        loader = loaders.get(validated.source_type)
        if not loader:
            raise ValueError(f'Unsupported source type: {validated.source_type}')
        return loader(validated)

    @staticmethod
    def _csv_opts(opts: dict | None) -> dict:
        if not opts:
            return {}
        return {
            'separator': opts.get('delimiter', ','),
            'quote_char': opts.get('quote_char', '"'),
            'has_header': opts.get('has_header', True),
            'skip_rows': opts.get('skip_rows', 0),
            'encoding': opts.get('encoding', 'utf8'),
        }

    def _load_file(self, config: DatasourceParams) -> pl.LazyFrame:
        if not config.file_path or not config.file_type:
            raise ValueError('Datasource file loading requires file_path and file_type')
        opts = config.csv_options or config.options or {}
        loader = self.FILE_LOADERS.get(config.file_type)
        if not loader:
            raise ValueError(f'Unsupported file type: {config.file_type}')
        return loader(config.file_path, opts)

    def _load_database(self, config: DatasourceParams) -> pl.LazyFrame:
        if not config.connection_string or not config.query:
            raise ValueError('Datasource database loading requires connection_string and query')
        return pl.read_database(config.query, config.connection_string).lazy()

    def _load_duckdb(self, config: DatasourceParams) -> pl.LazyFrame:
        import duckdb

        if not config.query:
            raise ValueError('Datasource DuckDB loading requires query')
        conn = (
            duckdb.connect(database=config.db_path, read_only=config.read_only) if config.db_path else duckdb.connect(database=':memory:')
        )
        try:
            return conn.execute(config.query).fetch_df().lazy()
        finally:
            conn.close()


def load_datasource(config: dict) -> pl.LazyFrame:
    return DatasourceHandler()(pl.LazyFrame(), config)
