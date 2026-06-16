from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa  # type: ignore[import-untyped]

from backend_core import data_plane_iceberg


@dataclass
class FakeDataPlaneClient:
    rows: list[dict[str, object]]
    scan_args: dict[str, object] | None = None
    sync_args: dict[str, object] | None = None

    def scan_iceberg_snapshot(self, *, metadata_path: str, snapshot_id: str, limit: int | None = None) -> list[dict[str, object]]:
        self.scan_args = {
            'metadata_path': metadata_path,
            'snapshot_id': snapshot_id,
            'limit': limit,
        }
        return self.rows

    def sync_iceberg_schema(self, *, metadata_path: str, schema_payload: dict[str, object]) -> None:
        self.sync_args = {'metadata_path': metadata_path, 'schema_payload': schema_payload}

    def resolve_iceberg_branch_metadata_path(self, *, namespace: str, metadata_path: str, branch: str | None = None) -> str:
        return f'{namespace}:{metadata_path}:{branch}'


def test_scan_iceberg_snapshot_uses_worker_data_plane(monkeypatch):
    client = FakeDataPlaneClient(rows=[{'a': 'x', 'b': 1}])
    monkeypatch.setattr(data_plane_iceberg, 'client_from_settings', lambda: client)

    frame = data_plane_iceberg.scan_iceberg_snapshot('s3://bucket/table/metadata.json', 123, limit=10).collect()

    assert frame.to_dicts() == [{'a': 'x', 'b': 1}]
    assert client.scan_args == {
        'metadata_path': 's3://bucket/table/metadata.json',
        'snapshot_id': '123',
        'limit': 10,
    }


def test_resolve_iceberg_branch_metadata_path_uses_worker_data_plane(monkeypatch):
    client = FakeDataPlaneClient(rows=[])
    monkeypatch.setattr(data_plane_iceberg, 'client_from_settings', lambda: client)

    assert data_plane_iceberg.resolve_iceberg_branch_metadata_path('s3://bucket/table', 'dev', namespace_name='tenant_a') == 'tenant_a:s3://bucket/table:dev'


def test_sync_iceberg_schema_uses_worker_data_plane(monkeypatch):
    client = FakeDataPlaneClient(rows=[])
    monkeypatch.setattr(data_plane_iceberg, 'client_from_settings', lambda: client)

    data_plane_iceberg.sync_iceberg_schema(
        's3://bucket/table/metadata.json',
        pa.schema([pa.field('id', pa.int64()), pa.field('name', pa.string())]),
    )

    assert client.sync_args is not None
    assert client.sync_args['metadata_path'] == 's3://bucket/table/metadata.json'
    schema_payload = client.sync_args['schema_payload']
    assert isinstance(schema_payload, dict)
    assert isinstance(schema_payload.get('arrow_schema_ipc_base64'), str)
