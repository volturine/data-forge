from collections.abc import Callable
from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class ExportFormat:
    extension: str
    content_type: str
    writer: Callable[[pl.DataFrame, str], None]


class ExportRegistry:
    FORMATS: dict[str, ExportFormat] = {
        'csv': ExportFormat('.csv', 'text/csv', lambda df, path: df.write_csv(path)),
        'parquet': ExportFormat('.parquet', 'application/octet-stream', lambda df, path: df.write_parquet(path)),
        'json': ExportFormat('.json', 'application/json', lambda df, path: df.write_json(path)),
        'ndjson': ExportFormat('.ndjson', 'application/x-ndjson', lambda df, path: df.write_ndjson(path)),
    }

    @classmethod
    def get(cls, name: str) -> ExportFormat:
        fmt = cls.FORMATS.get(name)
        if not fmt:
            raise ValueError(f'Unsupported export format: {name}')
        return fmt


def get_export_format(name: str) -> ExportFormat:
    return ExportRegistry.get(name)
