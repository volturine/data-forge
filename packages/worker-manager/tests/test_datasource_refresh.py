import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import polars as pl
from contracts.datasource.models import DataSource
from contracts.engine_runs.models import EngineRun
from sqlmodel import select


class TestDatasourceRefresh:
    @patch("datasources.datasource_service.load_datasource")
    @patch("datasources.datasource_service._write_iceberg_table")
    def test_refresh_external_builds_snapshot_fields(
        self,
        mock_write,
        mock_load,
        test_db_session,
        sample_csv_file: Path,
    ):
        from datasources.datasource_service import refresh_external_datasource

        class _Snap:
            snapshot_id = 222
            timestamp_ms = 654321

        class _Table:
            def current_snapshot(self):
                return _Snap()

        mock_load.return_value = pl.DataFrame({"x": [1]}).lazy()
        mock_write.return_value = _Table()

        ds = DataSource(
            id=str(uuid.uuid4()),
            name="Refreshable Raw",
            source_type="iceberg",
            config={
                "metadata_path": str(Path("data") / "clean" / str(uuid.uuid4()) / "master"),
                "branch": "master",
                "source": {
                    "source_type": "file",
                    "file_path": str(sample_csv_file),
                    "file_type": "csv",
                    "options": {},
                },
            },
            created_by="import",
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds)
        test_db_session.commit()

        out = refresh_external_datasource(test_db_session, ds.id)
        assert out.config["snapshot_id"] == "222"
        assert out.config["snapshot_timestamp_ms"] == 654321
        assert out.config["current_snapshot_id"] == "222"
        assert out.config["current_snapshot_timestamp_ms"] == 654321
        assert out.config["refresh"] is not None
        mock_write.assert_called_once_with(mock_load.return_value, Path(out.config["metadata_path"]), build_mode="full")

        runs = (
            test_db_session.execute(select(EngineRun).where(EngineRun.datasource_id == ds.id))  # type: ignore[arg-type]
            .scalars()
            .all()
        )
        assert runs == []
