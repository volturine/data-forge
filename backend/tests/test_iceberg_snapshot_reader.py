from unittest.mock import MagicMock

import pyarrow as pa  # type: ignore[import-untyped]
from pyiceberg.schema import Schema as IcebergSchema
from pyiceberg.types import NestedField, StringType

from modules.compute.iceberg_reader import scan_iceberg_snapshot


def test_scan_iceberg_snapshot_inserts_missing_columns(monkeypatch):
    schema = IcebergSchema(NestedField(1, 'a', StringType(), required=False), NestedField(2, 'b', StringType(), required=False))
    snapshot = MagicMock(schema_id=1)
    metadata = MagicMock(schema_by_id=MagicMock(return_value=schema))

    table = MagicMock()
    table.snapshot_by_id.return_value = snapshot
    table.metadata = metadata
    table.schema.return_value = schema
    table.scan.return_value.to_arrow.return_value = pa.table({'a': ['x']})

    monkeypatch.setattr('modules.compute.iceberg_reader.StaticTable.from_metadata', MagicMock(return_value=table))

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

    monkeypatch.setattr('modules.compute.iceberg_reader.StaticTable.from_metadata', MagicMock(return_value=table))

    lf = scan_iceberg_snapshot('file://tmp/metadata.json', 123, None)
    df = lf.collect()

    assert df.columns == ['a']
