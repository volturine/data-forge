import uuid
from datetime import UTC, datetime

import polars as pl
from contracts.datasource.models import DataSource

from datasources.datasource_service import compare_iceberg_snapshots


def test_compare_iceberg_snapshots(test_db_session, monkeypatch):
    datasource_id = str(uuid.uuid4())
    config = {"metadata_path": "/tmp/iceberg/table"}
    datasource = DataSource(
        id=datasource_id,
        name="Iceberg Test",
        source_type="iceberg",
        config=config,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    def fake_load_datasource(config):
        snapshot_id = config.get("snapshot_id")
        if snapshot_id == "1":
            return pl.DataFrame(
                {
                    "id": [1, 2, 3],
                    "name": ["a", "b", None],
                    "value": [10, 20, 30],
                },
            ).lazy()
        if snapshot_id == "2":
            return pl.DataFrame(
                {
                    "id": [1, 2, 3, 4],
                    "name": ["a", "b", "c", "d"],
                    "value": [10, 20, 30, 40],
                    "extra": ["x", "y", "z", "w"],
                },
            ).lazy()
        return pl.DataFrame({"id": []}).lazy()

    monkeypatch.setattr("datasources.datasource_service.load_datasource", fake_load_datasource)

    result = compare_iceberg_snapshots(test_db_session, datasource_id, "1", "2", 100)

    assert result.datasource_id == datasource_id
    assert result.snapshot_a == "1"
    assert result.snapshot_b == "2"
    assert result.row_count_a == 3
    assert result.row_count_b == 4
    assert result.row_count_delta == 1

    diff = {(item.column, item.status) for item in result.schema_diff}
    assert ("extra", "added") in diff

    stats_a = {item.column: item for item in result.stats_a}
    stats_b = {item.column: item for item in result.stats_b}

    assert stats_a["name"].null_count == 1
    assert stats_a["name"].unique_count == 2
    assert stats_a["value"].min == 10
    assert stats_a["value"].max == 30

    assert stats_b["extra"].null_count == 0
    assert stats_b["extra"].unique_count == 4

    assert result.preview_a.row_count == 3
    assert result.preview_b.row_count == 4
    assert len(result.preview_a.data) == 3
    assert len(result.preview_b.data) == 4
