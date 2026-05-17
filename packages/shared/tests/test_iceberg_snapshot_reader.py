from unittest.mock import MagicMock

import pyarrow as pa  # type: ignore[import-untyped]
import pytest
from pyiceberg.schema import Schema as IcebergSchema
from pyiceberg.types import NestedField, StringType

from core.exceptions import DataSourceSnapshotError
from core.iceberg_snapshot_reader import scan_iceberg_snapshot


def test_scan_iceberg_snapshot_inserts_missing_columns(monkeypatch):
    schema = IcebergSchema(NestedField(1, 'a', StringType(), required=False), NestedField(2, 'b', StringType(), required=False))
    snapshot = MagicMock(schema_id=1)
    metadata = MagicMock(schema_by_id=MagicMock(return_value=schema))

    table = MagicMock()
    table.snapshot_by_id.return_value = snapshot
    table.metadata = metadata
    table.schema.return_value = schema
    table.scan.return_value.to_arrow.return_value = pa.table({'a': ['x']})

    monkeypatch.setattr('core.iceberg_snapshot_reader.StaticTable.from_metadata', MagicMock(return_value=table))

    lf = scan_iceberg_snapshot('file://tmp/metadata.json', 123, None)
    df = lf.collect()

    assert df.columns == ['a', 'b']
    assert df['b'].is_null().all()


def test_scan_iceberg_snapshot_drops_extra_columns(monkeypatch):
    schema = IcebergSchema(NestedField(1, 'a', StringType(), required=False))
    snapshot = MagicMock(schema_id=1)
    metadata = MagicMock(schema_by_id=MagicMock(return_value=schema))

    table = MagicMock()
    table.snapshot_by_id.return_value = snapshot
    table.metadata = metadata
    table.schema.return_value = schema
    table.scan.return_value.to_arrow.return_value = pa.table({'a': ['x'], 'extra': ['y']})

    monkeypatch.setattr('core.iceberg_snapshot_reader.StaticTable.from_metadata', MagicMock(return_value=table))

    lf = scan_iceberg_snapshot('file://tmp/metadata.json', 123, None)
    df = lf.collect()

    assert df.columns == ['a']


def test_scan_iceberg_snapshot_raises_on_missing_snapshot(monkeypatch):
    table = MagicMock()
    table.snapshot_by_id.return_value = None

    monkeypatch.setattr('core.iceberg_snapshot_reader.StaticTable.from_metadata', MagicMock(return_value=table))

    with pytest.raises(DataSourceSnapshotError, match='Iceberg snapshot ID not found'):
        scan_iceberg_snapshot('file://tmp/metadata.json', 999, None)
