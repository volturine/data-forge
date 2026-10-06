"""last_data_update enrichment and source revision tracking on datasources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.datasource.models import DataSource
from modules.datasource import service as datasource_service
from modules.datasource.schemas import DataSourceUpdate


def _insert_datasource(
    session: Session,
    *,
    datasource_id: str,
    source_type: str = 'iceberg',
    config: dict | None = None,
    created_by: str = 'import',
    created_by_analysis_id: str | None = None,
) -> DataSource:
    ds = DataSource(
        id=datasource_id,
        name=datasource_id,
        description=None,
        source_type=source_type,
        config=config or {},
        created_by=created_by,
        created_by_analysis_id=created_by_analysis_id,
        is_hidden=False,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _insert_build_run(
    session: Session,
    *,
    analysis_id: str,
    completed_at: datetime,
    status: str = BuildRunStatus.COMPLETED,
) -> None:
    run = BuildRun(
        id=f'build-{analysis_id}-{completed_at.timestamp()}',
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Test',
        status=status,
        request_json={},
        starter_json={},
        created_at=completed_at,
        started_at=completed_at,
        completed_at=completed_at,
        updated_at=completed_at,
        execution_generation=0,
        next_event_sequence=1,
    )
    session.add(run)
    session.commit()


class TestLastDataUpdate:
    @staticmethod
    def _epoch_ms(value: datetime) -> int:
        return int(value.replace(tzinfo=UTC).timestamp() * 1000)

    def test_uses_iceberg_snapshot_timestamp_from_config(self, test_db_session: Session) -> None:
        snapshot_time = datetime(2026, 5, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
        _insert_datasource(
            test_db_session,
            datasource_id='ds-snapshot',
            config={'current_snapshot_timestamp_ms': self._epoch_ms(snapshot_time)},
        )

        item = next(i for i in datasource_service.list_datasources(test_db_session) if i.id == 'ds-snapshot')

        assert item.last_data_update == snapshot_time

    def test_accepts_integral_protobuf_struct_number(self, test_db_session: Session) -> None:
        snapshot_time = datetime(2026, 5, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
        _insert_datasource(
            test_db_session,
            datasource_id='ds-protobuf-snapshot',
            # Worker RPC Struct values are decoded as floats.
            config={'current_snapshot_timestamp_ms': float(self._epoch_ms(snapshot_time))},
        )

        item = next(i for i in datasource_service.list_datasources(test_db_session) if i.id == 'ds-protobuf-snapshot')

        assert item.last_data_update == snapshot_time

    def test_ignores_invalid_snapshot_timestamp_values(self) -> None:
        for value in (True, 0, -1, 1.5, float('nan'), float('inf')):
            assert datasource_service._snapshot_timestamp_ms({'current_snapshot_timestamp_ms': value}) is None

    def test_prefers_current_over_plain_snapshot_timestamp(self, test_db_session: Session) -> None:
        old_time = datetime(2026, 4, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
        new_time = datetime(2026, 6, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
        _insert_datasource(
            test_db_session,
            datasource_id='ds-both',
            config={
                'snapshot_timestamp_ms': self._epoch_ms(old_time),
                'current_snapshot_timestamp_ms': self._epoch_ms(new_time),
            },
        )

        item = next(i for i in datasource_service.list_datasources(test_db_session) if i.id == 'ds-both')

        assert item.last_data_update == new_time

    def test_falls_back_to_latest_successful_build_for_analysis_output(self, test_db_session: Session) -> None:
        analysis_id = 'analysis-1'
        old_build = datetime(2026, 5, 1, 9, 0, tzinfo=UTC).replace(tzinfo=None)
        new_build = datetime(2026, 5, 2, 18, 30, tzinfo=UTC).replace(tzinfo=None)
        _insert_build_run(test_db_session, analysis_id=analysis_id, completed_at=old_build)
        _insert_build_run(test_db_session, analysis_id=analysis_id, completed_at=new_build)
        _insert_datasource(
            test_db_session,
            datasource_id='ds-analysis-output',
            source_type='analysis',
            created_by='analysis',
            created_by_analysis_id=analysis_id,
        )

        item = next(i for i in datasource_service.list_datasources(test_db_session) if i.id == 'ds-analysis-output')

        assert item.last_data_update == new_build

    def test_ignores_failed_builds_for_analysis_output(self, test_db_session: Session) -> None:
        analysis_id = 'analysis-2'
        failed = datetime(2026, 5, 1, 9, 0, tzinfo=UTC).replace(tzinfo=None)
        succeeded = datetime(2026, 5, 2, 18, 30, tzinfo=UTC).replace(tzinfo=None)
        _insert_build_run(
            test_db_session,
            analysis_id=analysis_id,
            completed_at=failed + timedelta(hours=1),
            status=BuildRunStatus.FAILED,
        )
        _insert_build_run(test_db_session, analysis_id=analysis_id, completed_at=succeeded)
        _insert_datasource(
            test_db_session,
            datasource_id='ds-analysis-output-2',
            source_type='analysis',
            created_by='analysis',
            created_by_analysis_id=analysis_id,
        )

        item = next(i for i in datasource_service.list_datasources(test_db_session) if i.id == 'ds-analysis-output-2')

        assert item.last_data_update == succeeded

    def test_unknown_without_snapshot_or_build(self, test_db_session: Session) -> None:
        _insert_datasource(test_db_session, datasource_id='ds-unknown', source_type='file')

        item = next(i for i in datasource_service.list_datasources(test_db_session) if i.id == 'ds-unknown')

        assert item.last_data_update is None

    def test_get_datasource_enriches_last_data_update(self, test_db_session: Session) -> None:
        snapshot_time = datetime(2026, 5, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
        _insert_datasource(
            test_db_session,
            datasource_id='ds-detail',
            config={'snapshot_timestamp_ms': self._epoch_ms(snapshot_time)},
        )

        response = datasource_service.get_datasource(test_db_session, 'ds-detail')

        assert response.last_data_update == snapshot_time


class TestSourceRevision:
    def test_update_advances_source_revision(self, test_db_session: Session) -> None:
        datasource = _insert_datasource(test_db_session, datasource_id='ds-update-revision')

        response = datasource_service.update_datasource(
            test_db_session,
            'ds-update-revision',
            DataSourceUpdate(is_hidden=True),
        )

        assert response.is_hidden is True
        test_db_session.refresh(datasource)
        assert datasource.revision == 2

    def test_noop_update_does_not_advance_source_revision(self, test_db_session: Session) -> None:
        datasource = _insert_datasource(test_db_session, datasource_id='ds-noop-update')

        datasource_service.update_datasource(
            test_db_session,
            datasource.id,
            DataSourceUpdate(is_hidden=False),
        )

        test_db_session.refresh(datasource)
        assert datasource.revision == 1

    def test_analysis_output_placeholder_update_advances_source_revision(self, test_db_session: Session) -> None:
        datasource = _insert_datasource(
            test_db_session,
            datasource_id='11111111-1111-4111-8111-111111111112',
            source_type='analysis',
            created_by='analysis',
            created_by_analysis_id='analysis-1',
        )

        datasource_service.create_placeholder_output_datasource(
            test_db_session,
            datasource.id,
            'analysis-1',
            'tab-2',
        )

        test_db_session.refresh(datasource)
        assert datasource.revision == 2
