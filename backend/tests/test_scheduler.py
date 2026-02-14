"""Tests for scheduler service."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlmodel import Session

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource
from modules.scheduler.models import Schedule
from modules.scheduler.schemas import ScheduleCreate, ScheduleUpdate
from modules.scheduler.service import (
    create_schedule,
    delete_schedule,
    get_build_order,
    get_due_schedules,
    list_schedules,
    mark_schedule_run,
    run_analysis_build,
    should_run,
    update_schedule,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def schedule_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def analysis_with_output(test_db_session: Session, sample_datasource: DataSource) -> Analysis:
    """Analysis with a tab that has output configuration (for build testing)."""
    analysis_id = str(uuid.uuid4())
    pipeline_definition = {
        'tabs': [
            {
                'id': 'tab-1',
                'name': 'Export Tab',
                'type': 'datasource',
                'parent_id': None,
                'datasource_id': sample_datasource.id,
                'datasource_config': {
                    'output': {
                        'datasource_type': 'file',
                        'format': 'csv',
                        'filename': 'test_output',
                    }
                },
                'steps': [],
            },
            {
                'id': 'tab-2',
                'name': 'No Output Tab',
                'type': 'datasource',
                'parent_id': None,
                'datasource_id': sample_datasource.id,
                'datasource_config': {},
                'steps': [],
            },
        ],
    }
    now = datetime.now(UTC)
    analysis = Analysis(
        id=analysis_id,
        name='Build Test Analysis',
        description='Has output config',
        pipeline_definition=pipeline_definition,
        status='draft',
        created_at=now,
        updated_at=now,
    )
    test_db_session.add(analysis)
    link = AnalysisDataSource(analysis_id=analysis_id, datasource_id=sample_datasource.id)
    test_db_session.add(link)
    test_db_session.commit()
    test_db_session.refresh(analysis)
    return analysis


# ---------------------------------------------------------------------------
# should_run()
# ---------------------------------------------------------------------------


class TestShouldRun:
    def test_empty_cron_returns_false(self):
        assert should_run('', None) is False

    def test_none_last_run_returns_true(self):
        """First run should always trigger."""
        assert should_run('* * * * *', None) is True

    def test_due_schedule(self):
        """Schedule that ran 2 hours ago with hourly cron should be due."""
        last = datetime.now(UTC) - timedelta(hours=2)
        assert should_run('0 * * * *', last) is True

    def test_not_due_schedule(self):
        """Schedule that ran 1 second ago with hourly cron should not be due."""
        last = datetime.now(UTC) - timedelta(seconds=1)
        assert should_run('0 * * * *', last) is False

    def test_every_minute_after_delay(self):
        """Every-minute cron with last_run 2 minutes ago should be due."""
        last = datetime.now(UTC) - timedelta(minutes=2)
        assert should_run('* * * * *', last) is True

    def test_daily_cron_not_due(self):
        """Daily cron that ran a few minutes ago should not be due."""
        last = datetime.now(UTC) - timedelta(minutes=5)
        assert should_run('0 0 * * *', last) is False


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------


class TestScheduleCrud:
    def test_create_schedule(self, test_db_session: Session, sample_analysis: Analysis):
        payload = ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *')
        result = create_schedule(test_db_session, payload)
        assert result.id is not None
        assert result.analysis_id == sample_analysis.id
        assert result.cron_expression == '0 * * * *'
        assert result.enabled is True
        assert result.next_run is not None
        assert result.last_run is None

    def test_create_disabled_schedule(self, test_db_session: Session, sample_analysis: Analysis):
        payload = ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 0 * * *', enabled=False)
        result = create_schedule(test_db_session, payload)
        assert result.enabled is False

    def test_list_schedules_empty(self, test_db_session: Session):
        result = list_schedules(test_db_session)
        assert result == []

    def test_list_schedules_all(self, test_db_session: Session, sample_analysis: Analysis):
        create_schedule(test_db_session, ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *'))
        create_schedule(test_db_session, ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 0 * * *'))
        result = list_schedules(test_db_session)
        assert len(result) == 2

    def test_list_schedules_filter_by_analysis(self, test_db_session: Session, sample_analyses: list[Analysis]):
        a1, a2, _ = sample_analyses
        create_schedule(test_db_session, ScheduleCreate(analysis_id=a1.id, cron_expression='0 * * * *'))
        create_schedule(test_db_session, ScheduleCreate(analysis_id=a2.id, cron_expression='0 0 * * *'))

        result = list_schedules(test_db_session, analysis_id=a1.id)
        assert len(result) == 1
        assert result[0].analysis_id == a1.id

    def test_update_cron_expression(self, test_db_session: Session, sample_analysis: Analysis):
        created = create_schedule(test_db_session, ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *'))
        updated = update_schedule(test_db_session, created.id, ScheduleUpdate(cron_expression='0 0 * * *'))
        assert updated.cron_expression == '0 0 * * *'
        assert updated.next_run is not None

    def test_update_enabled(self, test_db_session: Session, sample_analysis: Analysis):
        created = create_schedule(test_db_session, ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *'))
        updated = update_schedule(test_db_session, created.id, ScheduleUpdate(enabled=False))
        assert updated.enabled is False

    def test_update_nonexistent_raises(self, test_db_session: Session):
        with pytest.raises(ValueError, match='Schedule not found'):
            update_schedule(test_db_session, 'nonexistent', ScheduleUpdate(enabled=False))

    def test_delete_schedule(self, test_db_session: Session, sample_analysis: Analysis):
        created = create_schedule(test_db_session, ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *'))
        delete_schedule(test_db_session, created.id)
        result = list_schedules(test_db_session)
        assert len(result) == 0

    def test_delete_nonexistent_raises(self, test_db_session: Session):
        with pytest.raises(ValueError, match='Schedule not found'):
            delete_schedule(test_db_session, 'nonexistent')

    def test_create_schedule_with_datasource_id(self, test_db_session: Session, sample_analysis: Analysis, sample_datasource: DataSource):
        payload = ScheduleCreate(
            analysis_id=sample_analysis.id,
            cron_expression='0 * * * *',
            datasource_id=sample_datasource.id,
        )
        result = create_schedule(test_db_session, payload)
        assert result.datasource_id == sample_datasource.id
        assert result.analysis_id == sample_analysis.id

    def test_create_schedule_without_datasource_id(self, test_db_session: Session, sample_analysis: Analysis):
        payload = ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *')
        result = create_schedule(test_db_session, payload)
        assert result.datasource_id is None

    def test_list_schedules_filter_by_datasource(self, test_db_session: Session, sample_analysis: Analysis, sample_datasource: DataSource):
        ds_id_1 = sample_datasource.id
        ds_id_2 = str(uuid.uuid4())
        create_schedule(
            test_db_session,
            ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *', datasource_id=ds_id_1),
        )
        create_schedule(
            test_db_session,
            ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 0 * * *', datasource_id=ds_id_2),
        )

        result = list_schedules(test_db_session, datasource_id=ds_id_1)
        assert len(result) == 1
        assert result[0].datasource_id == ds_id_1

        result_all = list_schedules(test_db_session)
        assert len(result_all) == 2


# ---------------------------------------------------------------------------
# get_due_schedules()
# ---------------------------------------------------------------------------


class TestGetDueSchedules:
    def test_no_schedules(self, test_db_session: Session):
        result = get_due_schedules(test_db_session)
        assert result == []

    def test_disabled_schedules_excluded(self, test_db_session: Session, sample_analysis: Analysis):
        """Disabled schedules should not appear even if due."""
        schedule = Schedule(
            id=str(uuid.uuid4()),
            analysis_id=sample_analysis.id,
            cron_expression='* * * * *',
            enabled=False,
            last_run=None,
            next_run=None,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        result = get_due_schedules(test_db_session)
        assert len(result) == 0

    def test_due_schedule_returned(self, test_db_session: Session, sample_analysis: Analysis):
        """Enabled schedule with no last_run should be due."""
        schedule = Schedule(
            id=str(uuid.uuid4()),
            analysis_id=sample_analysis.id,
            cron_expression='* * * * *',
            enabled=True,
            last_run=None,
            next_run=None,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        result = get_due_schedules(test_db_session)
        assert len(result) == 1
        assert result[0].analysis_id == sample_analysis.id

    def test_not_due_schedule_excluded(self, test_db_session: Session, sample_analysis: Analysis):
        """Schedule that just ran should not be due."""
        schedule = Schedule(
            id=str(uuid.uuid4()),
            analysis_id=sample_analysis.id,
            cron_expression='0 0 * * *',  # daily
            enabled=True,
            last_run=datetime.now(UTC),
            next_run=None,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        result = get_due_schedules(test_db_session)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# mark_schedule_run()
# ---------------------------------------------------------------------------


class TestMarkScheduleRun:
    def test_updates_last_run_and_next_run(self, test_db_session: Session, sample_analysis: Analysis):
        created = create_schedule(test_db_session, ScheduleCreate(analysis_id=sample_analysis.id, cron_expression='0 * * * *'))
        assert created.last_run is None

        mark_schedule_run(test_db_session, created.id)

        schedule = test_db_session.get(Schedule, created.id)
        assert schedule is not None
        assert schedule.last_run is not None
        assert schedule.next_run is not None
        # last_run should be very recent (within last 5 seconds)
        # mark_schedule_run stores naive UTC, so compare with naive UTC
        now = datetime.now(UTC).replace(tzinfo=None)
        assert (now - schedule.last_run).total_seconds() < 5

    def test_nonexistent_schedule_no_error(self, test_db_session: Session):
        """Marking a nonexistent schedule should not raise."""
        mark_schedule_run(test_db_session, 'nonexistent')


# ---------------------------------------------------------------------------
# get_build_order() — topological sort
# ---------------------------------------------------------------------------


class TestGetBuildOrder:
    def test_single_analysis(self, test_db_session: Session, sample_analysis: Analysis):
        order = get_build_order(test_db_session, sample_analysis.id)
        assert sample_analysis.id in order

    def test_independent_analyses(self, test_db_session: Session, sample_analyses: list[Analysis]):
        """Independent analyses should all appear in the order."""
        order = get_build_order(test_db_session, sample_analyses[0].id)
        for a in sample_analyses:
            assert a.id in order

    def test_dependent_analyses_order(self, test_db_session: Session, sample_csv_file):
        """Upstream analysis should come before downstream in build order."""
        # Create upstream analysis with output datasource
        upstream_id = str(uuid.uuid4())
        ds_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Upstream datasource
        upstream_ds = DataSource(
            id=ds_id,
            name='Upstream Output',
            source_type='file',
            config={'file_path': str(sample_csv_file), 'file_type': 'csv', 'options': {}},
            created_at=now,
            created_by_analysis_id=upstream_id,
        )
        test_db_session.add(upstream_ds)

        upstream = Analysis(
            id=upstream_id,
            name='Upstream',
            description='',
            pipeline_definition={'tabs': []},
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(upstream)

        # Downstream analysis that depends on upstream's datasource
        downstream_id = str(uuid.uuid4())
        downstream = Analysis(
            id=downstream_id,
            name='Downstream',
            description='',
            pipeline_definition={'tabs': []},
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(downstream)

        # Link downstream to the datasource created by upstream
        link = AnalysisDataSource(analysis_id=downstream_id, datasource_id=ds_id)
        test_db_session.add(link)
        test_db_session.commit()

        order = get_build_order(test_db_session, downstream_id)
        upstream_idx = order.index(upstream_id) if upstream_id in order else -1
        downstream_idx = order.index(downstream_id) if downstream_id in order else -1
        assert upstream_idx < downstream_idx, 'Upstream must come before downstream'


# ---------------------------------------------------------------------------
# run_analysis_build()
# ---------------------------------------------------------------------------


class TestRunAnalysisBuild:
    def test_nonexistent_analysis_raises(self, test_db_session: Session):
        with pytest.raises(ValueError, match='not found'):
            run_analysis_build(test_db_session, 'nonexistent')

    def test_analysis_no_tabs(self, test_db_session: Session):
        """Analysis with no tabs should return 0 tabs built."""
        analysis_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        analysis = Analysis(
            id=analysis_id,
            name='Empty',
            description='',
            pipeline_definition={},
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(analysis)
        test_db_session.commit()

        result = run_analysis_build(test_db_session, analysis_id)
        assert result['tabs_built'] == 0
        assert result['results'] == []

    def test_tabs_without_output_skipped(self, test_db_session: Session, sample_analysis: Analysis):
        """Tabs without output config but missing datasource_config still skip preview."""
        result = run_analysis_build(test_db_session, sample_analysis.id)
        # sample_analysis tab has datasource_id but no datasource_config key,
        # so preview_step runs but fails (no engine) — caught as error, tabs_built stays 0
        assert result['tabs_built'] == 0

    @patch('modules.compute.service._send_pipeline_notifications')
    @patch('modules.compute.service.preview_step')
    @patch('modules.compute.service.export_data')
    def test_builds_all_tabs(self, mock_export, mock_preview, mock_notify, test_db_session: Session, analysis_with_output: Analysis):
        """All tabs with datasource_id should be built — export for output tabs, preview for others."""
        mock_export.return_value = None
        mock_preview.return_value = None

        result = run_analysis_build(test_db_session, analysis_with_output.id)
        # Both tabs have datasource_id: tab-1 via export_data, tab-2 via preview_step
        assert result['tabs_built'] == 2
        assert len(result['results']) == 2
        assert result['results'][0]['status'] == 'success'
        assert result['results'][0]['tab_name'] == 'Export Tab'
        assert result['results'][1]['status'] == 'success'
        assert result['results'][1]['tab_name'] == 'No Output Tab'
        mock_export.assert_called_once()
        mock_preview.assert_called_once()

    @patch('modules.compute.service._send_pipeline_notifications')
    @patch('modules.compute.service.preview_step')
    @patch('modules.compute.service.export_data')
    def test_export_failure_captured(
        self, mock_export, mock_preview, mock_notify, test_db_session: Session, analysis_with_output: Analysis
    ):
        """Failed export should be recorded but not crash the build; other tabs still run."""
        mock_export.side_effect = RuntimeError('Export failed')
        mock_preview.return_value = None

        result = run_analysis_build(test_db_session, analysis_with_output.id)
        # Tab-1 fails (export), tab-2 succeeds (preview)
        assert result['tabs_built'] == 1
        assert len(result['results']) == 2
        failed = [r for r in result['results'] if r['status'] == 'failed']
        succeeded = [r for r in result['results'] if r['status'] == 'success']
        assert len(failed) == 1
        assert 'Export failed' in failed[0]['error']
        assert len(succeeded) == 1
        assert succeeded[0]['tab_name'] == 'No Output Tab'

    @patch('modules.compute.service._send_pipeline_notifications')
    @patch('modules.compute.service.preview_step')
    @patch('modules.compute.service.export_data')
    def test_export_called_only_for_output_tabs(
        self, mock_export, mock_preview, mock_notify, test_db_session: Session, analysis_with_output: Analysis
    ):
        """export_data is called only for tabs with output config; preview_step for the rest."""
        mock_export.return_value = None
        mock_preview.return_value = None

        result = run_analysis_build(test_db_session, analysis_with_output.id)
        # analysis_with_output has 2 tabs: tab-1 with output, tab-2 without
        assert result['tabs_built'] == 2
        assert mock_export.call_count == 1
        assert mock_preview.call_count == 1

    @patch('modules.compute.service._send_pipeline_notifications')
    @patch('modules.compute.service.preview_step')
    @patch('modules.compute.service.export_data')
    def test_build_only_matching_datasource_tab(
        self, mock_export, mock_preview, mock_notify, test_db_session: Session, sample_datasource: DataSource
    ):
        """When datasource_id is provided, only the tab with that datasource runs."""
        other_ds_id = str(uuid.uuid4())
        analysis_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        pipeline = {
            'tabs': [
                {
                    'id': 'tab-a',
                    'name': 'Tab A',
                    'type': 'datasource',
                    'datasource_id': sample_datasource.id,
                    'datasource_config': {},
                    'steps': [],
                },
                {
                    'id': 'tab-b',
                    'name': 'Tab B',
                    'type': 'datasource',
                    'datasource_id': other_ds_id,
                    'datasource_config': {},
                    'steps': [],
                },
            ],
        }
        analysis = Analysis(
            id=analysis_id,
            name='Multi DS',
            description='',
            pipeline_definition=pipeline,
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(analysis)
        test_db_session.commit()

        mock_preview.return_value = None

        # Build only for sample_datasource — tab-a should run, tab-b should be skipped
        result = run_analysis_build(test_db_session, analysis_id, datasource_id=sample_datasource.id)
        assert result['tabs_built'] == 1
        assert len(result['results']) == 1
        assert result['results'][0]['tab_name'] == 'Tab A'

        # Without datasource_id filter — both tabs run
        mock_preview.reset_mock()
        mock_notify.reset_mock()
        result_all = run_analysis_build(test_db_session, analysis_id)
        assert result_all['tabs_built'] == 2
        assert len(result_all['results']) == 2


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


class TestScheduleRoutes:
    def test_list_empty(self, client):
        response = client.get('/api/v1/schedules')
        assert response.status_code == 200
        assert response.json() == []

    def test_create_and_list(self, client, sample_analysis: Analysis):
        payload = {'analysis_id': sample_analysis.id, 'cron_expression': '0 * * * *'}
        response = client.post('/api/v1/schedules', json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data['analysis_id'] == sample_analysis.id
        assert data['cron_expression'] == '0 * * * *'
        assert data['enabled'] is True

        # List
        response = client.get('/api/v1/schedules')
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_list_filtered_by_analysis(self, client, sample_analyses: list[Analysis]):
        a1, a2, _ = sample_analyses
        client.post('/api/v1/schedules', json={'analysis_id': a1.id, 'cron_expression': '0 * * * *'})
        client.post('/api/v1/schedules', json={'analysis_id': a2.id, 'cron_expression': '0 0 * * *'})

        response = client.get(f'/api/v1/schedules?analysis_id={a1.id}')
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_update(self, client, sample_analysis: Analysis):
        create_resp = client.post('/api/v1/schedules', json={'analysis_id': sample_analysis.id, 'cron_expression': '0 * * * *'})
        schedule_id = create_resp.json()['id']

        response = client.put(f'/api/v1/schedules/{schedule_id}', json={'enabled': False})
        assert response.status_code == 200
        assert response.json()['enabled'] is False

    def test_update_nonexistent_404(self, client):
        response = client.put('/api/v1/schedules/nonexistent', json={'enabled': False})
        assert response.status_code == 404

    def test_delete(self, client, sample_analysis: Analysis):
        create_resp = client.post('/api/v1/schedules', json={'analysis_id': sample_analysis.id, 'cron_expression': '0 * * * *'})
        schedule_id = create_resp.json()['id']

        response = client.delete(f'/api/v1/schedules/{schedule_id}')
        assert response.status_code == 200

        # Verify deleted
        response = client.get('/api/v1/schedules')
        assert len(response.json()) == 0

    def test_delete_nonexistent_404(self, client):
        response = client.delete('/api/v1/schedules/nonexistent')
        assert response.status_code == 404

    def test_create_with_datasource_id(self, client, sample_analysis: Analysis, sample_datasource: DataSource):
        payload = {
            'analysis_id': sample_analysis.id,
            'cron_expression': '0 * * * *',
            'datasource_id': sample_datasource.id,
        }
        response = client.post('/api/v1/schedules', json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data['datasource_id'] == sample_datasource.id

    def test_list_filtered_by_datasource_id(self, client, sample_analysis: Analysis, sample_datasource: DataSource):
        ds_id = sample_datasource.id
        other_ds_id = str(uuid.uuid4())
        client.post(
            '/api/v1/schedules',
            json={'analysis_id': sample_analysis.id, 'cron_expression': '0 * * * *', 'datasource_id': ds_id},
        )
        client.post(
            '/api/v1/schedules',
            json={'analysis_id': sample_analysis.id, 'cron_expression': '0 0 * * *', 'datasource_id': other_ds_id},
        )

        response = client.get(f'/api/v1/schedules?datasource_id={ds_id}')
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]['datasource_id'] == ds_id
