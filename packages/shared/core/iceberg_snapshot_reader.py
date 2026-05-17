from __future__ import annotations

from typing import Any

import polars as pl
from pyiceberg.table import StaticTable

from core.exceptions import DataSourceSnapshotError


def scan_iceberg_snapshot(metadata_path: str, snapshot_id: int, storage_options: dict[str, Any] | None) -> pl.LazyFrame:
    del storage_options
    table = StaticTable.from_metadata(metadata_path)
    snapshot = table.snapshot_by_id(snapshot_id)
    if snapshot is None:
        raise DataSourceSnapshotError(f'Iceberg snapshot ID not found: {snapshot_id}', details={'snapshot_id': str(snapshot_id)})

    schema_id = snapshot.schema_id
    schema = table.schema() if schema_id is None else table.metadata.schema_by_id(schema_id) or table.schema()

    names = [field.name for field in schema.fields]
    data = table.scan(snapshot_id=snapshot_id).to_arrow()
    frame = pl.from_arrow(data) if data.num_rows else pl.DataFrame({name: [] for name in names})
    if isinstance(frame, pl.Series):
        frame = frame.to_frame()

    for name in names:
        if name not in frame.columns:
            frame = frame.with_columns(pl.lit(None).alias(name))
    return frame.lazy().select(names)
