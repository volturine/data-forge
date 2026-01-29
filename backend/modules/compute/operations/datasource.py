from collections.abc import Callable

import polars as pl

from modules.compute.operations.base import OperationHandler, OperationParams


class DatasourceParams(OperationParams):
    source_type: str = 'file'
    file_path: str | None = None
    file_type: str | None = None
    options: dict | None = None
    csv_options: dict | None = None
    sheet_name: str | None = None
    start_row: int | None = None
    start_col: int | None = None
    end_col: int | None = None
    end_row: int | None = None
    has_header: bool | None = None
    table_name: str | None = None
    named_range: str | None = None
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
        'excel': lambda path, opts: DatasourceHandler._read_excel(path, opts),
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
        opts = self._merge_excel_opts(config, opts)
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

    @staticmethod
    def _read_excel(path: str, opts: dict) -> pl.LazyFrame:
        sheet_name = opts.get('sheet_name')
        table_name = opts.get('table_name')
        named_range = opts.get('named_range')
        cell_range = opts.get('cell_range')

        next_opts: dict = {}
        if sheet_name is not None:
            next_opts['sheet_name'] = sheet_name
        if table_name is not None:
            next_opts['table_name'] = table_name
        if named_range is not None:
            next_opts['named_range'] = named_range
        if cell_range is not None:
            next_opts['cell_range'] = cell_range
        return pl.read_excel(path, **next_opts).lazy()

    @staticmethod
    def _merge_excel_opts(config: DatasourceParams, opts: dict) -> dict:
        next_opts = opts
        if config.sheet_name:
            next_opts = {**next_opts, 'sheet_name': config.sheet_name}
        if config.table_name:
            next_opts = {**next_opts, 'table_name': config.table_name}
        if config.named_range:
            next_opts = {**next_opts, 'named_range': config.named_range}
        if config.start_row is not None and config.start_col is not None and config.end_col is not None and config.end_row is not None:
            next_opts = {
                **next_opts,
                'cell_range': _build_range(config.start_row, config.start_col, config.end_col, config.end_row),
            }
        if config.has_header is not None:
            next_opts = {**next_opts, 'has_header': config.has_header}
        return next_opts


def _build_range(start_row: int, start_col: int, end_col: int, end_row: int) -> str:
    start_row_index = start_row + 1
    end_row_index = end_row + 1
    start_cell = f'{_col_label(start_col)}{start_row_index}'
    end_cell = f'{_col_label(end_col)}{end_row_index}'
    return f'{start_cell}:{end_cell}'


def _col_label(index: int) -> str:
    idx = index + 1
    label = ''
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        label = chr(65 + rem) + label
    return label


def load_datasource(config: dict) -> pl.LazyFrame:
    return DatasourceHandler()(pl.LazyFrame(), config)
