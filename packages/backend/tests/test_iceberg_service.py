from datetime import UTC, datetime

from backend_core import build_runs_service, engine_runs_service
from backend_core.contracts.build_runs.models import BuildRunStatus
from backend_core.contracts.datasource.models import DataSourceCreatedBy
from backend_core.contracts.datasource.source_types import DataSourceType
from backend_core.contracts.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.data_plane_client import IcebergSnapshotInfo, IcebergSnapshots
from backend_core.persistence.datasource.models import DataSource
from modules.compute import iceberg_service


class _FakeWorkerDataPlaneClient:
    def __init__(self, snapshots: list[IcebergSnapshotInfo]) -> None:
        self._snapshots = snapshots

    def list_snapshots(self, *, namespace: str, datasource_id: str, branch: str | None = None) -> IcebergSnapshots:
        del namespace, branch
        return IcebergSnapshots(datasource_id=datasource_id, table_path='/tmp/warehouse/outputs/table1', snapshots=self._snapshots)


def test_list_iceberg_snapshots_can_filter_to_completed_build_results(test_db_session, monkeypatch) -> None:
    datasource = DataSource(
        id='ds-1',
        name='Output datasource',
        description=None,
        source_type=DataSourceType.ICEBERG.value,
        config={
            'catalog_type': 'sql',
            'catalog_uri': 'postgresql://test',
            'namespace': 'outputs',
            'table': 'table1',
            'warehouse': 'file:///tmp/warehouse',
            'metadata_path': '/tmp/warehouse/outputs/table1/metadata/v1.metadata.json',
            'branch': 'master',
        },
        created_by=DataSourceCreatedBy.ANALYSIS.value,
        created_by_analysis_id='analysis-1',
        is_hidden=True,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    build_runs_service.create_build_run(
        test_db_session,
        build_id='build-1',
        namespace='default',
        analysis_id='analysis-1',
        analysis_name='Analysis 1',
        request_json={},
        starter_json={},
        result_json={'snapshot_id': 'snap-build-1', 'branch': 'master'},
        status=BuildRunStatus.COMPLETED,
        current_kind='build',
        current_output_id='ds-1',
    )
    build_runs_service.create_build_run(
        test_db_session,
        build_id='build-2',
        namespace='default',
        analysis_id='analysis-1',
        analysis_name='Analysis 1',
        request_json={},
        starter_json={},
        result_json={'snapshot_id': 'snap-build-2', 'branch': 'dev'},
        status=BuildRunStatus.COMPLETED,
        current_kind='build',
        current_output_id='ds-1',
    )

    snapshots = [
        IcebergSnapshotInfo('snap-delete', 3000, None, 'delete', True),
        IcebergSnapshotInfo('snap-build-2', 2000, None, 'append', False),
        IcebergSnapshotInfo('snap-build-1', 1000, None, 'append', False),
    ]
    monkeypatch.setattr(iceberg_service, 'client_from_settings', lambda: _FakeWorkerDataPlaneClient(snapshots))

    response = iceberg_service.list_iceberg_snapshots(
        test_db_session,
        'ds-1',
        branch='master',
        build_results_only=True,
    )

    assert [snapshot.snapshot_id for snapshot in response.snapshots] == ['snap-build-1']
    assert response.snapshots[0].operation == 'append'


def test_list_iceberg_snapshots_can_collapse_ingest_churn_to_logical_results(test_db_session, monkeypatch) -> None:
    datasource = DataSource(
        id='ds-raw-1',
        name='Imported datasource',
        description=None,
        source_type=DataSourceType.ICEBERG.value,
        config={
            'catalog_type': 'sql',
            'catalog_uri': 'postgresql://test',
            'namespace': 'clean',
            'table': 'table1',
            'warehouse': 'file:///tmp/warehouse',
            'metadata_path': '/tmp/warehouse/clean/table1/metadata/v1.metadata.json',
            'branch': 'master',
            'source': {'source_type': 'file', 'file_path': '/tmp/source.csv', 'file_type': 'csv'},
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
                datasource_id='ds-raw-1',
                kind=EngineRunKind.INGEST,
                status=EngineRunStatus.SUCCESS,
                request_json={'branch': 'master', 'mode': 'manual_ingest'},
                created_at=completed_at,
                completed_at=completed_at,
            ),
        )

    snapshots = [
        IcebergSnapshotInfo('snap-initial', 1779491921000, None, 'append', False),
        IcebergSnapshotInfo('snap-delete-1', 1779491930000, None, 'delete', False),
        IcebergSnapshotInfo('snap-refresh-1', 1779491930000, None, 'append', False),
        IcebergSnapshotInfo('snap-delete-2', 1779491936000, None, 'delete', False),
        IcebergSnapshotInfo('snap-refresh-2', 1779491936000, None, 'append', True),
    ]
    monkeypatch.setattr(iceberg_service, 'client_from_settings', lambda: _FakeWorkerDataPlaneClient(snapshots))

    response = iceberg_service.list_iceberg_snapshots(
        test_db_session,
        'ds-raw-1',
        branch='master',
        build_results_only=True,
    )

    assert [snapshot.snapshot_id for snapshot in response.snapshots] == [
        'snap-refresh-2',
        'snap-refresh-1',
        'snap-initial',
    ]
