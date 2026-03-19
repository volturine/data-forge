from __future__ import annotations

import logging
from typing import Any

import polars as pl
from pyiceberg.table import StaticTable

logger = logging.getLogger(__name__)


def scan_iceberg_snapshot(
    metadata_path: str,
    snapshot_id: int,
    storage_options: dict[str, Any] | None,
) -> pl.LazyFrame:
    table = StaticTable.from_metadata(metadata_path)
    snapshot = table.snapshot_by_id(snapshot_id)
    if snapshot is None:
        logger.warning('Iceberg snapshot ID %s not found, falling back to latest snapshot', snapshot_id)
        snapshot = table.current_snapshot()
        if snapshot is None:
            raise ValueError(f'Iceberg table has no snapshots (requested snapshot_id: {snapshot_id})')
        snapshot_id = snapshot.snapshot_id

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
