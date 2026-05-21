import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import polars as pl
from contracts.datasource.models import DataSource
from contracts.engine_runs.models import EngineRun
from sqlmodel import Session, select


class TestDatasourceIngest:
    @patch("datasources.datasource_service.load_datasource")
    @patch("datasources.datasource_service._write_iceberg_table")
    def test_create_file_datasource_persists_ingest_run(
        self,
        mock_write,
        mock_load,
        test_db_session,
        sample_csv_file: Path,
    ):
        from core.namespace import namespace_paths

        from datasources.datasource_service import create_file_datasource

        class _Snap:
            snapshot_id = 101
            timestamp_ms = 123123

        class _Table:
            def current_snapshot(self):
                return _Snap()

        mock_load.return_value = pl.DataFrame({"x": [1]}).lazy()
        mock_write.return_value = _Table()

        allowed_file = namespace_paths().upload_dir / sample_csv_file.name
        allowed_file.write_bytes(sample_csv_file.read_bytes())

        out = create_file_datasource(
            test_db_session,
            name="Uploaded CSV",
            description=None,
            file_path=str(allowed_file),
            file_type="csv",
        )

        assert out.source_type == "iceberg"
        assert out.config["source"]["source_type"] == "file"
        assert out.config["source"]["file_type"] == "csv"

        runs = (
            test_db_session.execute(select(EngineRun).where(EngineRun.datasource_id == out.id))  # type: ignore[arg-type]
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert runs[0].kind == "ingest"
        assert runs[0].status == "success"
        assert runs[0].result_json is not None
        assert runs[0].result_json["original_source_type"] == "file"

    @patch("datasources.datasource_service.load_datasource")
    @patch("datasources.datasource_service._write_iceberg_table")
    def test_create_database_datasource_marks_database_source_type(
        self,
        mock_write,
        mock_load,
        test_db_session,
    ):
        from datasources.datasource_service import create_database_datasource

        class _Snap:
            snapshot_id = 111
            timestamp_ms = 123456

        class _Table:
            def current_snapshot(self):
                return _Snap()

        mock_load.return_value = pl.DataFrame({"x": [1]}).lazy()
        mock_write.return_value = _Table()

        out = create_database_datasource(
            test_db_session,
            name="Ingestable Database",
            description=None,
            connection_string="postgresql://example/db",
            query="select * from public.users",
        )

        assert out.source_type == "iceberg"
        assert out.config["source"]["source_type"] == "database"
        assert out.config["source"]["connection_string"] == "postgresql://example/db"
        assert out.config["source"]["query"] == "select * from public.users"

        runs = (
            test_db_session.execute(select(EngineRun).where(EngineRun.datasource_id == out.id))  # type: ignore[arg-type]
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert runs[0].kind == "ingest"
        assert runs[0].status == "success"
        assert runs[0].result_json is not None
        assert runs[0].result_json["original_source_type"] == "database"

    @patch("datasources.datasource_service.load_datasource")
    @patch("datasources.datasource_service._write_iceberg_table")
    def test_create_iceberg_datasource_persists_ingest_run(
        self,
        mock_write,
        mock_load,
        test_db_session,
        sample_csv_file: Path,
    ):
        from datasources.datasource_service import create_iceberg_datasource

        class _Snap:
            snapshot_id = 131
            timestamp_ms = 456456

        class _Table:
            def current_snapshot(self):
                return _Snap()

        mock_load.return_value = pl.DataFrame({"x": [1]}).lazy()
        mock_write.return_value = _Table()

        out = create_iceberg_datasource(
            test_db_session,
            name="External File Raw",
            description=None,
            source={
                "source_type": "file",
                "file_path": str(sample_csv_file),
                "file_type": "csv",
                "options": {},
            },
        )

        assert out.source_type == "iceberg"
        assert out.config["source"]["source_type"] == "file"

        runs = (
            test_db_session.execute(select(EngineRun).where(EngineRun.datasource_id == out.id))  # type: ignore[arg-type]
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert runs[0].kind == "ingest"
        assert runs[0].status == "success"
        assert runs[0].result_json is not None
        assert runs[0].result_json["original_source_type"] == "file"

    @patch("datasources.datasource_service.load_datasource")
    @patch("datasources.datasource_service._write_iceberg_table")
    def test_ingest_external_builds_snapshot_fields(
        self,
        mock_write,
        mock_load,
        test_db_session,
        sample_csv_file: Path,
    ):
        from datasources.datasource_service import ingest_external_datasource

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
            name="Ingestable Raw",
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

        out = ingest_external_datasource(test_db_session, ds.id)
        assert out.config["snapshot_id"] == "222"
        assert out.config["snapshot_timestamp_ms"] == 654321
        assert out.config["current_snapshot_id"] == "222"
        assert out.config["current_snapshot_timestamp_ms"] == 654321
        assert out.config["ingest"] is not None
        mock_write.assert_called_once_with(mock_load.return_value, Path(out.config["metadata_path"]), build_mode="full")

        runs = (
            test_db_session.execute(select(EngineRun).where(EngineRun.datasource_id == ds.id))  # type: ignore[arg-type]
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert runs[0].kind == "ingest"
        assert runs[0].status == "success"
        assert runs[0].result_json is not None
        assert runs[0].result_json["original_source_type"] == "file"

    @patch("datasources.datasource_service.load_datasource")
    @patch("datasources.datasource_service._write_iceberg_table")
    def test_ingest_external_serializes_same_datasource_writes(
        self,
        mock_write,
        mock_load,
        test_engine,
        test_db_session,
        sample_csv_file: Path,
    ):
        from datasources.datasource_service import ingest_external_datasource

        class _Snap:
            snapshot_id = 333
            timestamp_ms = 777777

        class _Table:
            def current_snapshot(self):
                return _Snap()

        mock_load.return_value = pl.DataFrame({"x": [1]}).lazy()

        entered = threading.Event()
        release = threading.Event()
        counters_lock = threading.Lock()
        active_writes = 0
        max_active_writes = 0

        def fake_write(*_args, **_kwargs):
            nonlocal active_writes, max_active_writes
            with counters_lock:
                active_writes += 1
                max_active_writes = max(max_active_writes, active_writes)
                if active_writes == 1:
                    entered.set()
            release.wait(timeout=5)
            with counters_lock:
                active_writes -= 1
            return _Table()

        mock_write.side_effect = fake_write

        ds = DataSource(
            id=str(uuid.uuid4()),
            name="Concurrent Raw",
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

        errors: list[Exception] = []

        def run_ingest() -> None:
            try:
                with Session(test_engine) as session:
                    ingest_external_datasource(session, ds.id)
            except Exception as exc:  # pragma: no cover - assertion captures failure state
                errors.append(exc)

        first = threading.Thread(target=run_ingest)
        second = threading.Thread(target=run_ingest)

        first.start()
        assert entered.wait(timeout=5)
        second.start()
        threading.Event().wait(0.2)
        release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert not first.is_alive()
        assert not second.is_alive()
        assert not errors
        assert max_active_writes == 1
