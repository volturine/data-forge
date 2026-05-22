from datetime import UTC, datetime
from types import SimpleNamespace

from contracts.build_runs.models import BuildRunStatus
from contracts.datasource.models import DataSource, DataSourceCreatedBy
from contracts.datasource.source_types import DataSourceType
from contracts.engine_runs.schemas import EngineRunKind, EngineRunStatus
from core import build_runs_service, engine_runs_service

from modules.compute import iceberg_service


class _FakeSnapshot:
    def __init__(
        self,
        snapshot_id: str,
        timestamp_ms: int,
        *,
        operation: str | None = None,
        parent_snapshot_id: str | None = None,
    ) -> None:
        self.snapshot_id = snapshot_id
        self.timestamp_ms = timestamp_ms
        self.parent_snapshot_id = parent_snapshot_id
        self.summary = SimpleNamespace(operation=operation) if operation is not None else None


class _FakeTable:
    def __init__(self, snapshots: list[_FakeSnapshot], current_snapshot_id: str | None) -> None:
        self._snapshots = snapshots
        self._current_snapshot_id = current_snapshot_id
        self.metadata_location = "/tmp/warehouse/outputs/table1/metadata/v1.metadata.json"

    def snapshots(self) -> list[_FakeSnapshot]:
        return self._snapshots

    def current_snapshot(self):
        if self._current_snapshot_id is None:
            return None
        return SimpleNamespace(snapshot_id=self._current_snapshot_id)


class _FakeCatalog:
    def __init__(self, table: _FakeTable, *, expected_identifier: str) -> None:
        self._table = table
        self._expected_identifier = expected_identifier

    def load_table(self, identifier: str) -> _FakeTable:
        assert identifier == self._expected_identifier
        return self._table


def test_list_iceberg_snapshots_can_filter_to_completed_build_results(test_db_session, monkeypatch) -> None:
    datasource = DataSource(
        id="ds-1",
        name="Output datasource",
        description=None,
        source_type=DataSourceType.ICEBERG.value,
        config={
            "catalog_type": "sql",
            "catalog_uri": "postgresql://test",
            "namespace": "outputs",
            "table": "table1",
            "warehouse": "file:///tmp/warehouse",
            "metadata_path": "/tmp/warehouse/outputs/table1/metadata/v1.metadata.json",
            "branch": "master",
        },
        created_by=DataSourceCreatedBy.ANALYSIS.value,
        created_by_analysis_id="analysis-1",
        is_hidden=True,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    build_runs_service.create_build_run(
        test_db_session,
        build_id="build-1",
        namespace="default",
        analysis_id="analysis-1",
        analysis_name="Analysis 1",
        request_json={},
        starter_json={},
        result_json={"snapshot_id": "snap-build-1", "branch": "master"},
        status=BuildRunStatus.COMPLETED,
        current_kind="build",
        current_output_id="ds-1",
    )
    build_runs_service.create_build_run(
        test_db_session,
        build_id="build-2",
        namespace="default",
        analysis_id="analysis-1",
        analysis_name="Analysis 1",
        request_json={},
        starter_json={},
        result_json={"snapshot_id": "snap-build-2", "branch": "dev"},
        status=BuildRunStatus.COMPLETED,
        current_kind="build",
        current_output_id="ds-1",
    )

    fake_table = _FakeTable(
        [
            _FakeSnapshot("snap-delete", 3000, operation="delete"),
            _FakeSnapshot("snap-build-2", 2000, operation="append"),
            _FakeSnapshot("snap-build-1", 1000, operation="append"),
        ],
        current_snapshot_id="snap-delete",
    )
    monkeypatch.setattr(
        iceberg_service,
        "load_runtime_catalog",
        lambda *_args, **_kwargs: _FakeCatalog(fake_table, expected_identifier="outputs.table1"),
    )
    monkeypatch.setattr(
        iceberg_service,
        "resolve_iceberg_metadata_path",
        lambda path: path,
    )

    response = iceberg_service.list_iceberg_snapshots(
        test_db_session,
        "ds-1",
        branch="master",
        build_results_only=True,
    )

    assert [snapshot.snapshot_id for snapshot in response.snapshots] == ["snap-build-1"]
    assert response.snapshots[0].operation == "append"


def test_list_iceberg_snapshots_can_collapse_ingest_churn_to_logical_results(test_db_session, monkeypatch) -> None:
    datasource = DataSource(
        id="ds-raw-1",
        name="Imported datasource",
        description=None,
        source_type=DataSourceType.ICEBERG.value,
        config={
            "catalog_type": "sql",
            "catalog_uri": "postgresql://test",
            "namespace": "clean",
            "table": "table1",
            "warehouse": "file:///tmp/warehouse",
            "metadata_path": "/tmp/warehouse/clean/table1/metadata/v1.metadata.json",
            "branch": "master",
            "source": {"source_type": "file", "file_path": "/tmp/source.csv", "file_type": "csv"},
        },
        created_by=DataSourceCreatedBy.IMPORT.value,
        is_hidden=False,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    run_times = [
        datetime(2026, 5, 22, 23, 18, 41, tzinfo=UTC),
        datetime(2026, 5, 22, 23, 18, 50, tzinfo=UTC),
        datetime(2026, 5, 22, 23, 18, 56, tzinfo=UTC),
    ]
    for completed_at in run_times:
        engine_runs_service.create_engine_run(
            test_db_session,
            engine_runs_service.create_engine_run_payload(
                analysis_id=None,
                datasource_id="ds-raw-1",
                kind=EngineRunKind.INGEST,
                status=EngineRunStatus.SUCCESS,
                request_json={"branch": "master", "mode": "manual_ingest"},
                created_at=completed_at,
                completed_at=completed_at,
            ),
        )

    fake_table = _FakeTable(
        [
            _FakeSnapshot("snap-initial", 1779491921000, operation="append"),
            _FakeSnapshot("snap-delete-1", 1779491930000, operation="delete"),
            _FakeSnapshot("snap-refresh-1", 1779491930000, operation="append"),
            _FakeSnapshot("snap-delete-2", 1779491936000, operation="delete"),
            _FakeSnapshot("snap-refresh-2", 1779491936000, operation="append"),
        ],
        current_snapshot_id="snap-refresh-2",
    )
    monkeypatch.setattr(
        iceberg_service,
        "load_runtime_catalog",
        lambda *_args, **_kwargs: _FakeCatalog(fake_table, expected_identifier="clean.table1"),
    )
    monkeypatch.setattr(
        iceberg_service,
        "resolve_iceberg_metadata_path",
        lambda path: path,
    )

    response = iceberg_service.list_iceberg_snapshots(
        test_db_session,
        "ds-raw-1",
        branch="master",
        build_results_only=True,
    )

    assert [snapshot.snapshot_id for snapshot in response.snapshots] == [
        "snap-refresh-2",
        "snap-refresh-1",
        "snap-initial",
    ]
