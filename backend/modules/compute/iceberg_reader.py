from __future__ import annotations

import logging
from typing import Any

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
from pyiceberg.table import StaticTable, Table as IcebergTable

from core.exceptions import DataSourceSnapshotError

logger = logging.getLogger(__name__)


def sync_iceberg_schema(table: IcebergTable, new_schema: pa.Schema) -> bool:
    """Sync Iceberg table schema to match *new_schema*.

    Drops removed columns, adds new columns via ``union_by_name``.
    Returns ``True`` if the schema was modified.
    """
    current = table.schema()
    current_names = {field.name for field in current.fields}
    new_names = set(new_schema.names)

    to_delete = current_names - new_names
    has_additions = bool(new_names - current_names)

    if not to_delete and not has_additions:
        return False

    update = table.update_schema()
    for name in sorted(to_delete):
        update.delete_column(name)
    if has_additions:
        update.union_by_name(new_schema)
    update.commit()
    return True


def scan_iceberg_snapshot(
    metadata_path: str,
    snapshot_id: int,
    storage_options: dict[str, Any] | None,
) -> pl.LazyFrame:
    table = StaticTable.from_metadata(metadata_path)
    snapshot = table.snapshot_by_id(snapshot_id)
    if snapshot is None:
        raise DataSourceSnapshotError(
            f'Iceberg snapshot ID not found: {snapshot_id}',
            details={'snapshot_id': str(snapshot_id)},
        )

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
