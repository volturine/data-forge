import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from runtime import compute_service
from runtime.config import settings
from runtime.domain.datasource.source_types import DataSourceType
from runtime.notification_delivery import encode_staged_deliveries, staged_column_name


@pytest.fixture
def worker_database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"postgresql://worker:{uuid4()}@internal-db:5432/worker"
    monkeypatch.setattr(settings, "database_url", url)
    return url


def test_internal_catalog_uri_prefers_worker_env(worker_database_url: str) -> None:
    config_uri = "postgresql://leaked:creds@config-db:5432/platform"

    assert compute_service._internal_catalog_uri(config_uri) == worker_database_url


def test_internal_catalog_uri_falls_back_to_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_url", "")
    config_uri = "postgresql://fallback@config-db:5432/platform"

    assert compute_service._internal_catalog_uri(config_uri) == config_uri


def test_internal_catalog_uri_returns_none_without_either(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_url", "")

    assert compute_service._internal_catalog_uri(None) is None
    assert compute_service._internal_catalog_uri("") is None
    assert compute_service._internal_catalog_uri(123) is None


def _datasource_with_catalog_uri(config_uri: object) -> SimpleNamespace:
    return SimpleNamespace(
        found=True,
        source_type=DataSourceType.ICEBERG,
        config={
            "catalog_type": "sql",
            "catalog_uri": config_uri,
            "namespace": "outputs",
            "table": "table_1",
            "warehouse": "s3://bucket/warehouse",
            "metadata_path": "s3://bucket/warehouse/outputs/table_1/metadata/000.metadata.json",
        },
    )


def test_list_iceberg_snapshots_uses_worker_database_url(
    monkeypatch: pytest.MonkeyPatch,
    worker_database_url: str,
) -> None:
    captured: dict = {}

    def fake_load_runtime_catalog(name: str, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before catalog access")

    monkeypatch.setattr(
        compute_service,
        "client_from_env",
        lambda: SimpleNamespace(datasource_metadata=lambda **_: _datasource_with_catalog_uri("postgresql://leaked:creds@config-db:5432/platform")),
    )
    monkeypatch.setattr(compute_service, "load_runtime_catalog", fake_load_runtime_catalog)

    with pytest.raises(RuntimeError, match="stop before catalog access"):
        compute_service.list_iceberg_snapshots(session=None, datasource_id="ds-1")

    assert captured["uri"] == worker_database_url


def test_delete_iceberg_snapshot_uses_worker_database_url(
    monkeypatch: pytest.MonkeyPatch,
    worker_database_url: str,
) -> None:
    captured: dict = {}

    def fake_load_runtime_catalog(name: str, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before catalog access")

    monkeypatch.setattr(
        compute_service,
        "client_from_env",
        lambda: SimpleNamespace(datasource_metadata=lambda **_: _datasource_with_catalog_uri("postgresql://leaked:creds@config-db:5432/platform")),
    )
    monkeypatch.setattr(compute_service, "load_runtime_catalog", fake_load_runtime_catalog)

    with pytest.raises(RuntimeError, match="stop before catalog access"):
        compute_service.delete_iceberg_snapshot(session=None, datasource_id="ds-1", snapshot_id="1")

    assert captured["uri"] == worker_database_url


def _write_parquet(path: Path, columns: dict[str, pa.Array]) -> None:
    table = pa.table(columns)
    pq.write_table(table, os.fspath(path))


def test_strip_staged_notification_columns_removes_staged_and_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "output.parquet"
    deliveries_a = [{"channel": "email", "to": "a@example.com"}]
    deliveries_b = [{"channel": "telegram", "chat_id": "1"}, {"channel": "telegram", "chat_id": "2"}]
    _write_parquet(
        path,
        {
            "id": pa.array([1, 2, 3], type=pa.int64()),
            "name": pa.array(["x", "y", "z"], type=pa.string()),
            staged_column_name("step-a"): pa.array(
                [encode_staged_deliveries(deliveries_a), None, None],
                type=pa.string(),
            ),
            staged_column_name("step-b"): pa.array(
                [None, encode_staged_deliveries(deliveries_b), None],
                type=pa.string(),
            ),
        },
    )

    result = compute_service._strip_staged_notification_columns(os.fspath(path))

    assert result == [*deliveries_a, *deliveries_b]
    out = pq.read_table(os.fspath(path))
    assert out.column_names == ["id", "name"]
    assert out.column("id").to_pylist() == [1, 2, 3]
    assert out.column("name").to_pylist() == ["x", "y", "z"]


def test_strip_staged_notification_columns_noop_without_staged(tmp_path: Path) -> None:
    path = tmp_path / "output.parquet"
    _write_parquet(path, {"id": pa.array([1, 2], type=pa.int64())})
    before = path.read_bytes()

    result = compute_service._strip_staged_notification_columns(os.fspath(path))

    assert result is None
    assert path.read_bytes() == before


def test_strip_staged_notification_columns_propagates_invalid_payload(tmp_path: Path) -> None:
    path = tmp_path / "output.parquet"
    _write_parquet(
        path,
        {
            "id": pa.array([1], type=pa.int64()),
            staged_column_name("step-a"): pa.array(["not-json"], type=pa.string()),
        },
    )

    with pytest.raises(ValueError):
        compute_service._strip_staged_notification_columns(os.fspath(path))


def test_strip_staged_notification_columns_streams_in_batches(tmp_path: Path) -> None:
    path = tmp_path / "output.parquet"
    row_count = 150_000
    values = list(range(row_count))
    _write_parquet(
        path,
        {
            "id": pa.array(values, type=pa.int64()),
            staged_column_name("step-a"): pa.array(
                [encode_staged_deliveries([{"i": i}]) for i in range(100)] + [None] * (row_count - 100),
                type=pa.string(),
            ),
        },
    )

    result = compute_service._strip_staged_notification_columns(os.fspath(path))

    assert result is not None
    assert result == [{"i": i} for i in range(100)]
    out = pq.read_table(os.fspath(path))
    assert out.num_rows == row_count
    assert out.column_names == ["id"]
