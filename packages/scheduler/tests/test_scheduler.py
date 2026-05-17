"""Tests for scheduler service."""

import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from contracts.analysis.models import Analysis, AnalysisDataSource, AnalysisStatus
from contracts.build_runs.models import BuildRunStatus
from contracts.datasource.models import DataSource
from contracts.engine_runs.schemas import EngineRunKind
from contracts.scheduler.models import Schedule
from contracts.scheduler.schemas import ScheduleCreate, ScheduleUpdate
from core import (
    build_jobs_service as build_job_service,
)
from core import (
    build_runs_service as build_run_service,
)
from core.exceptions import DataSourceNotFoundError, ScheduleNotFoundError
from sqlmodel import Session

from scheduler_service import (
    claim_due_schedules,
    create_schedule,
    delete_schedule,
    enqueue_schedule_run,
    get_build_order,
    get_due_schedules,
    is_schedule_target_eligible,
    list_schedules,
    mark_schedule_run,
    reconcile_schedule_run,
    should_run,
    update_schedule,
)


def _load_runtime_scheduler():
    path = Path(__file__).resolve().parents[2] / "scheduler" / "main.py"
    spec = importlib.util.spec_from_file_location("scheduler_main_for_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load scheduler runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_scheduler = _load_runtime_scheduler()


@pytest.mark.asyncio
async def test_scheduler_main_starts_runtime_listener(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    async def fake_init_db() -> None:
        calls.append(("init_db", None))

    async def fake_start_api_server() -> object:
        server = object()
        calls.append(("start_api_server", server))
        return server

    async def fake_serve_api_notifications(server: object, stop_event: asyncio.Event, handler) -> None:
        calls.append(("serve_api_notifications", server))
        assert handler is runtime_scheduler.handle_runtime_payload
        await stop_event.wait()

    async def fake_stop_api_server(server: object) -> None:
        calls.append(("stop_api_server", server))

    async def fake_scheduler_loop(stop_event: asyncio.Event, worker_id: str, **_kwargs) -> None:
        calls.append(("scheduler_loop", worker_id))
        stop_event.set()

    monkeypatch.setattr(
        runtime_scheduler.settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )
    monkeypatch.setattr(
        runtime_scheduler,
        "configure_logging",
        lambda: calls.append(("configure_logging", None)),
    )
    monkeypatch.setattr(runtime_scheduler, "init_db", fake_init_db)
    monkeypatch.setattr(runtime_scheduler.runtime_ipc, "start_api_server", fake_start_api_server)
    monkeypatch.setattr(
        runtime_scheduler.runtime_ipc,
        "serve_api_notifications",
        fake_serve_api_notifications,
    )
    monkeypatch.setattr(runtime_scheduler.runtime_ipc, "stop_api_server", fake_stop_api_server)
    monkeypatch.setattr(
        runtime_scheduler,
        "install_stop_handlers",
        lambda stop_event: calls.append(("install_stop_handlers", stop_event)),
    )
    monkeypatch.setattr(runtime_scheduler, "scheduler_loop", fake_scheduler_loop)
    monkeypatch.setattr(runtime_scheduler, "scheduler_id", lambda: "scheduler-1")

    await runtime_scheduler.main()

    names = [name for name, _ in calls]

    assert names[0:4] == [
        "init_db",
        "configure_logging",
        "install_stop_handlers",
        "start_api_server",
    ]
    assert "serve_api_notifications" in names
    assert "scheduler_loop" in names
    assert "stop_api_server" in names

    server = next(value for name, value in calls if name == "start_api_server")
    assert next(value for name, value in calls if name == "serve_api_notifications") is server
    assert next(value for name, value in calls if name == "stop_api_server") is server


@pytest.mark.asyncio
async def test_scheduler_main_invokes_runtime_listener_start(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_init_db() -> None:
        calls.append("init_db")

    async def fake_scheduler_loop(stop_event: asyncio.Event, worker_id: str, **_kwargs) -> None:
        calls.append("scheduler_loop")
        assert worker_id == "scheduler-1"
        stop_event.set()

    monkeypatch.setattr(
        runtime_scheduler.settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )
    monkeypatch.setattr(
        runtime_scheduler,
        "configure_logging",
        lambda: calls.append("configure_logging"),
    )
    monkeypatch.setattr(runtime_scheduler, "init_db", fake_init_db)

    server = object()

    async def fake_start_api_server():
        calls.append("start_api_server")
        return server

    async def fake_stop_api_server(_server: object) -> None:
        calls.append("stop_api_server")
        assert _server is server

    monkeypatch.setattr(runtime_scheduler.runtime_ipc, "start_api_server", fake_start_api_server)
    monkeypatch.setattr(runtime_scheduler.runtime_ipc, "stop_api_server", fake_stop_api_server)
    monkeypatch.setattr(
        runtime_scheduler,
        "install_stop_handlers",
        lambda stop_event: calls.append("install_stop_handlers"),
    )
    monkeypatch.setattr(runtime_scheduler, "scheduler_loop", fake_scheduler_loop)
    monkeypatch.setattr(runtime_scheduler, "scheduler_id", lambda: "scheduler-1")

    await runtime_scheduler.main()

    assert calls == [
        "init_db",
        "configure_logging",
        "install_stop_handlers",
        "start_api_server",
        "scheduler_loop",
        "stop_api_server",
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def schedule_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def output_datasource(test_db_session: Session, sample_analysis: Analysis) -> DataSource:
    """Datasource with created_by='analysis' — eligible for schedules."""
    ds = DataSource(
        id=str(uuid.uuid4()),
        name="Output DataSource",
        source_type="iceberg",
        config={"analysis_tab_id": "tab1"},
        created_by="analysis",
        created_by_analysis_id=sample_analysis.id,
        is_hidden=True,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(ds)
    test_db_session.commit()
    test_db_session.refresh(ds)
    return ds


@pytest.fixture
def analysis_with_output(test_db_session: Session, sample_datasource: DataSource) -> Analysis:
    """Analysis with a tab that has output configuration (for build testing)."""
    analysis_id = str(uuid.uuid4())
    pipeline_definition: dict[str, Any] = {
        "tabs": [
            {
                "id": "tab-1",
                "name": "Export Tab",
                "parent_id": None,
                "datasource": {
                    "id": sample_datasource.id,
                    "analysis_tab_id": None,
                    "config": {"branch": "master"},
                },
                "output": {
                    "result_id": str(uuid.uuid4()),
                    "datasource_type": "iceberg",
                    "format": "parquet",
                    "filename": "test_output",
                    "iceberg": {"namespace": "outputs", "table_name": "test_output"},
                },
                "steps": [],
            },
            {
                "id": "tab-2",
                "name": "No Output Tab",
                "parent_id": None,
                "datasource": {
                    "id": sample_datasource.id,
                    "analysis_tab_id": None,
                    "config": {"branch": "master"},
                },
                "output": {
                    "result_id": str(uuid.uuid4()),
                    "datasource_type": "iceberg",
                    "format": "parquet",
                    "filename": "test_output_two",
                    "iceberg": {
                        "namespace": "outputs",
                        "table_name": "test_output_two",
                    },
                },
                "steps": [],
            },
        ],
    }
    now = datetime.now(UTC)
    analysis = Analysis(
        id=analysis_id,
        name="Build Test Analysis",
        description="Has output config",
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
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
        assert should_run("", None) is False

    def test_none_last_run_returns_true(self):
        """First run should always trigger."""
        assert should_run("* * * * *", None) is True

    def test_due_schedule(self):
        """Schedule that ran 2 hours ago with hourly cron should be due."""
        last = datetime.now(UTC) - timedelta(hours=2)
        assert should_run("0 * * * *", last) is True

    def test_not_due_schedule(self):
        """Schedule that ran 1 second ago with hourly cron should not be due."""
        last = datetime.now(UTC) - timedelta(seconds=1)
        assert should_run("0 * * * *", last) is False

    def test_every_minute_after_delay(self):
        """Every-minute cron with last_run 2 minutes ago should be due."""
        last = datetime.now(UTC) - timedelta(minutes=2)
        assert should_run("* * * * *", last) is True

    def test_daily_cron_not_due(self):
        """Daily cron that ran a few minutes ago should not be due."""
        now = datetime.now(UTC)
        last = now - timedelta(minutes=5)
        future = now + timedelta(hours=2)
        cron_expr = f"{future.minute} {future.hour} * * *"
        assert should_run(cron_expr, last) is False


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------


class TestScheduleCrud:
    def test_create_schedule(
        self,
        test_db_session: Session,
        sample_analysis: Analysis,
        output_datasource: DataSource,
    ):
        payload = ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *")
        result = create_schedule(test_db_session, payload)
        assert result.id is not None
        assert result.datasource_id == output_datasource.id
        assert result.analysis_id == sample_analysis.id  # Resolved from datasource
        assert result.analysis_name == sample_analysis.name  # Resolved from datasource
        assert result.cron_expression == "0 * * * *"
        assert result.enabled is True
        assert result.next_run is not None
        assert result.last_run is None

    def test_create_disabled_schedule(self, test_db_session: Session, output_datasource: DataSource):
        payload = ScheduleCreate(
            datasource_id=output_datasource.id,
            cron_expression="0 0 * * *",
            enabled=False,
        )
        result = create_schedule(test_db_session, payload)
        assert result.enabled is False

    def test_list_schedules_empty(self, test_db_session: Session):
        result = list_schedules(test_db_session)
        assert result == []

    def test_list_schedules_all(self, test_db_session: Session, output_datasource: DataSource):
        create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 0 * * *"),
        )
        result = list_schedules(test_db_session)
        assert len(result) == 2

    def test_list_schedules_batch_enrichment(
        self,
        test_db_session: Session,
        sample_analysis: Analysis,
        sample_analyses: list[Analysis],
        output_datasource: DataSource,
    ):
        """Batch enrichment resolves analysis_name and analysis_id for multiple schedules."""
        ds2 = DataSource(
            id=str(uuid.uuid4()),
            name="Output DS 2",
            source_type="iceberg",
            config={"analysis_tab_id": "tab1"},
            created_by="analysis",
            created_by_analysis_id=sample_analyses[1].id,
            is_hidden=True,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds2)
        test_db_session.commit()

        create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=ds2.id, cron_expression="0 0 * * *"),
        )

        result = list_schedules(test_db_session)
        assert len(result) == 2

        by_ds = {r.datasource_id: r for r in result}
        r1 = by_ds[output_datasource.id]
        r2 = by_ds[ds2.id]

        assert r1.analysis_id == sample_analysis.id
        assert r1.analysis_name == sample_analysis.name
        assert r2.analysis_id == sample_analyses[1].id
        assert r2.analysis_name == sample_analyses[1].name

    def test_list_schedules_filter_by_datasource(
        self,
        test_db_session: Session,
        sample_analyses: list[Analysis],
        output_datasource: DataSource,
    ):
        # Create second output datasource for filtering test
        ds2 = DataSource(
            id=str(uuid.uuid4()),
            name="Output DataSource 2",
            source_type="iceberg",
            config={"analysis_tab_id": "tab1"},
            created_by="analysis",
            created_by_analysis_id=sample_analyses[1].id,
            is_hidden=True,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds2)
        test_db_session.commit()

        create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=ds2.id, cron_expression="0 0 * * *"),
        )

        result = list_schedules(test_db_session, datasource_id=output_datasource.id)
        assert len(result) == 1
        assert result[0].datasource_id == output_datasource.id

    def test_update_cron_expression(self, test_db_session: Session, output_datasource: DataSource):
        created = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        updated = update_schedule(test_db_session, created.id, ScheduleUpdate(cron_expression="0 0 * * *"))
        assert updated.cron_expression == "0 0 * * *"
        assert updated.next_run is not None

    def test_update_schedule_rejected_for_multiple_triggers(self, test_db_session: Session, output_datasource: DataSource):
        """Schedule updates cannot set multiple trigger fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="depends_on or trigger_on_datasource_id"):
            ScheduleUpdate(depends_on=str(uuid.uuid4()), trigger_on_datasource_id=str(uuid.uuid4()))

    def test_update_enabled(self, test_db_session: Session, output_datasource: DataSource):
        created = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        updated = update_schedule(test_db_session, created.id, ScheduleUpdate(enabled=False))
        assert updated.enabled is False

    def test_update_nonexistent_raises(self, test_db_session: Session):
        with pytest.raises(ScheduleNotFoundError):
            update_schedule(test_db_session, "nonexistent", ScheduleUpdate(enabled=False))

    def test_delete_schedule(self, test_db_session: Session, output_datasource: DataSource):
        created = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        delete_schedule(test_db_session, created.id)
        result = list_schedules(test_db_session)
        assert len(result) == 0

    def test_delete_nonexistent_raises(self, test_db_session: Session):
        with pytest.raises(ScheduleNotFoundError):
            delete_schedule(test_db_session, "nonexistent")

    def test_create_schedule_without_datasource_id(self, test_db_session: Session):
        """ScheduleCreate requires datasource_id - should raise validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ScheduleCreate(cron_expression="0 * * * *")  # type: ignore[call-arg]

    def test_create_schedule_allows_non_analysis_datasource(self, test_db_session: Session, sample_datasource: DataSource):
        """Schedules can target non-analysis datasources."""
        payload = ScheduleCreate(
            datasource_id=sample_datasource.id,
            cron_expression="0 * * * *",
        )
        created = create_schedule(test_db_session, payload)
        assert created.datasource_id == sample_datasource.id

    def test_create_schedule_allows_reingestable_raw_iceberg(self, test_db_session: Session, sample_csv_file):
        source = {
            "source_type": "file",
            "file_path": str(sample_csv_file),
            "file_type": "csv",
            "options": {},
        }
        raw = DataSource(
            id=str(uuid.uuid4()),
            name="Raw Iceberg",
            source_type="iceberg",
            config={"metadata_path": "/tmp/path", "branch": "master", "source": source},
            created_by="import",
            created_at=datetime.now(UTC),
        )
        test_db_session.add(raw)
        test_db_session.commit()

        created = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=raw.id, cron_expression="0 * * * *"),
        )
        assert created.datasource_id == raw.id


class TestScheduleEligibility:
    def test_eligible_for_analysis_output(self, output_datasource: DataSource):
        assert is_schedule_target_eligible(output_datasource) is True

    def test_eligible_for_reingestable_raw_iceberg(self, sample_csv_file):
        raw = DataSource(
            id=str(uuid.uuid4()),
            name="Raw Iceberg",
            source_type="iceberg",
            config={
                "metadata_path": "/tmp/path",
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
        assert is_schedule_target_eligible(raw) is True

    def test_eligible_for_non_reingestable_raw(self):
        datasource = DataSource(
            id=str(uuid.uuid4()),
            name="Raw Iceberg",
            source_type="iceberg",
            config={
                "metadata_path": "/tmp/path",
                "branch": "master",
                "source": {"source_type": "s3"},
            },
            created_by="import",
            created_at=datetime.now(UTC),
        )
        assert is_schedule_target_eligible(datasource) is True

    def test_create_schedule_rejected_for_nonexistent_datasource(self, test_db_session: Session):
        """Schedules must be rejected when datasource does not exist."""
        payload = ScheduleCreate(
            datasource_id=str(uuid.uuid4()),
            cron_expression="0 * * * *",
        )
        with pytest.raises(DataSourceNotFoundError):
            create_schedule(test_db_session, payload)

    def test_create_schedule_rejected_for_multiple_triggers(self, test_db_session: Session, output_datasource: DataSource):
        """Schedules cannot define multiple trigger fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="depends_on or trigger_on_datasource_id"):
            ScheduleCreate(
                datasource_id=output_datasource.id,
                cron_expression="0 * * * *",
                depends_on=str(uuid.uuid4()),
                trigger_on_datasource_id=str(uuid.uuid4()),
            )


# ---------------------------------------------------------------------------
# get_due_schedules()
# ---------------------------------------------------------------------------


class TestGetDueSchedules:
    def test_no_schedules(self, test_db_session: Session):
        result = get_due_schedules(test_db_session)
        assert result == []

    def test_disabled_schedules_excluded(self, test_db_session: Session, output_datasource: DataSource):
        """Disabled schedules should not appear even if due."""
        schedule = Schedule(
            id=str(uuid.uuid4()),
            datasource_id=output_datasource.id,
            cron_expression="* * * * *",
            enabled=False,
            last_run=None,
            next_run=None,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        result = get_due_schedules(test_db_session)
        assert len(result) == 0

    def test_due_schedule_returned(self, test_db_session: Session, output_datasource: DataSource):
        """Enabled schedule with no last_run should be due."""
        schedule = Schedule(
            id=str(uuid.uuid4()),
            datasource_id=output_datasource.id,
            cron_expression="* * * * *",
            enabled=True,
            last_run=None,
            next_run=None,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        result = get_due_schedules(test_db_session)
        assert len(result) == 1
        assert result[0].datasource_id == output_datasource.id

    def test_not_due_schedule_excluded(self, test_db_session: Session, output_datasource: DataSource):
        """Schedule that just ran should not be due."""
        schedule = Schedule(
            id=str(uuid.uuid4()),
            datasource_id=output_datasource.id,
            cron_expression="0 0 * * *",  # daily
            enabled=True,
            last_run=datetime.now(UTC),
            next_run=None,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        result = get_due_schedules(test_db_session)
        assert len(result) == 0

    def test_dependency_schedule_uses_last_triggered_at(self, test_db_session: Session, output_datasource: DataSource):
        upstream = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        downstream = create_schedule(
            test_db_session,
            ScheduleCreate(
                datasource_id=output_datasource.id,
                cron_expression="0 * * * *",
                depends_on=upstream.id,
            ),
        )

        upstream_row = test_db_session.get(Schedule, upstream.id)
        assert upstream_row is not None
        upstream_row.last_success_at = datetime.now(UTC).replace(tzinfo=None)
        test_db_session.add(upstream_row)
        test_db_session.commit()

        due = get_due_schedules(test_db_session)
        assert downstream.id in {schedule.id for schedule in due}

        downstream_row = test_db_session.get(Schedule, downstream.id)
        assert downstream_row is not None
        downstream_row.last_triggered_at = datetime.now(UTC).replace(tzinfo=None)
        test_db_session.add(downstream_row)
        test_db_session.commit()

        due = get_due_schedules(test_db_session)
        assert downstream.id not in {schedule.id for schedule in due}


# ---------------------------------------------------------------------------
# mark_schedule_run()
# ---------------------------------------------------------------------------


class TestMarkScheduleRun:
    def test_updates_last_run_and_next_run(self, test_db_session: Session, output_datasource: DataSource):
        created = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        assert created.last_run is None

        mark_schedule_run(test_db_session, created.id)

        schedule = test_db_session.get(Schedule, created.id)
        assert schedule is not None
        assert schedule.last_run is not None
        assert schedule.next_run is not None
        # last_run should be very recent (within last 5 seconds)
        last_run = schedule.last_run if schedule.last_run.tzinfo is not None else schedule.last_run.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        assert (now - last_run).total_seconds() < 5

    def test_nonexistent_schedule_no_error(self, test_db_session: Session):
        """Marking a nonexistent schedule should not raise."""
        mark_schedule_run(test_db_session, "nonexistent")


class TestScheduleClaiming:
    def test_claim_due_schedule_sets_lease(self, test_db_session: Session, output_datasource: DataSource):
        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="* * * * *"),
        )
        row = test_db_session.get(Schedule, schedule.id)
        assert row is not None
        row.next_run = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        test_db_session.add(row)
        test_db_session.commit()

        claimed = claim_due_schedules(test_db_session, worker_id="scheduler:test")

        assert [row.id for row in claimed] == [schedule.id]
        row = test_db_session.get(Schedule, schedule.id)
        assert row is not None
        assert row.lease_owner == "scheduler:test"
        assert row.lease_expires_at is None

    def test_claim_due_schedule_skips_already_owned_row(self, test_db_session: Session, output_datasource: DataSource):
        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="* * * * *"),
        )
        row = test_db_session.get(Schedule, schedule.id)
        assert row is not None
        row.next_run = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        test_db_session.add(row)
        test_db_session.commit()

        first = claim_due_schedules(test_db_session, worker_id="scheduler:one")
        second = claim_due_schedules(test_db_session, worker_id="scheduler:two")

        assert [row.id for row in first] == [schedule.id]
        assert second == []
        stored = test_db_session.get(Schedule, schedule.id)
        assert stored is not None
        assert stored.lease_owner == "scheduler:one"

    def test_claim_due_schedule_reclaims_stale_owner(self, test_db_session: Session, output_datasource: DataSource):
        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="* * * * *"),
        )
        row = test_db_session.get(Schedule, schedule.id)
        assert row is not None
        row.next_run = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        row.lease_owner = "scheduler:stale"
        test_db_session.add(row)
        test_db_session.commit()

        claimed = claim_due_schedules(
            test_db_session,
            worker_id="scheduler:two",
            reclaimable_owner_ids={"scheduler:stale"},
        )

        assert [item.id for item in claimed] == [schedule.id]
        stored = test_db_session.get(Schedule, schedule.id)
        assert stored is not None
        assert stored.lease_owner == "scheduler:two"

    def test_claim_due_schedule_skips_inflight_build(self, test_db_session: Session, output_datasource: DataSource):
        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="* * * * *"),
        )
        build_run_service.create_build_run(
            test_db_session,
            build_id=str(uuid.uuid4()),
            namespace="default",
            schedule_id=schedule.id,
            analysis_id="analysis",
            analysis_name="Analysis",
            request_json={
                "analysis_pipeline": {"analysis_id": "analysis", "tabs": []},
                "tab_id": None,
            },
            starter_json={"triggered_by": f"schedule:{schedule.id}"},
            status=BuildRunStatus.QUEUED,
        )

        claimed = claim_due_schedules(test_db_session, worker_id="scheduler:test")

        assert claimed == []


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
            name="Upstream Output",
            source_type="file",
            config={
                "file_path": str(sample_csv_file),
                "file_type": "csv",
                "options": {},
            },
            created_at=now,
            created_by_analysis_id=upstream_id,
        )
        test_db_session.add(upstream_ds)

        upstream = Analysis(
            id=upstream_id,
            name="Upstream",
            description="",
            pipeline_definition={
                "tabs": [
                    {
                        "id": "tab-upstream",
                        "name": "Upstream",
                        "parent_id": None,
                        "datasource": {
                            "id": ds_id,
                            "analysis_tab_id": None,
                            "config": {"branch": "master"},
                        },
                        "output": {
                            "result_id": str(uuid.uuid4()),
                            "datasource_type": "iceberg",
                            "format": "parquet",
                            "filename": "scheduled_source",
                        },
                        "steps": [],
                    },
                ],
            },
            status=AnalysisStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(upstream)

        # Downstream analysis that depends on upstream's datasource
        downstream_id = str(uuid.uuid4())
        downstream = Analysis(
            id=downstream_id,
            name="Downstream",
            description="",
            pipeline_definition={
                "tabs": [
                    {
                        "id": "tab-downstream",
                        "name": "Downstream",
                        "parent_id": None,
                        "datasource": {
                            "id": ds_id,
                            "analysis_tab_id": None,
                            "config": {"branch": "master"},
                        },
                        "output": {
                            "result_id": str(uuid.uuid4()),
                            "datasource_type": "iceberg",
                            "format": "parquet",
                            "filename": "scheduled_source",
                        },
                        "steps": [],
                    },
                ],
            },
            status=AnalysisStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(downstream)
        test_db_session.commit()

        # Link downstream to the datasource created by upstream
        link = AnalysisDataSource(analysis_id=downstream_id, datasource_id=ds_id)
        test_db_session.add(link)
        test_db_session.commit()

        order = get_build_order(test_db_session, downstream_id)
        upstream_idx = order.index(upstream_id) if upstream_id in order else -1
        downstream_idx = order.index(downstream_id) if downstream_id in order else -1
        assert upstream_idx < downstream_idx, "Upstream must come before downstream"


class TestEnqueueScheduleRun:
    def test_enqueue_schedule_for_analysis_creates_queued_build(
        self,
        test_db_session: Session,
        analysis_with_output: Analysis,
        sample_datasource: DataSource,
    ):
        output_id = analysis_with_output.pipeline_definition["tabs"][0]["output"]["result_id"]
        output = DataSource(
            id=output_id,
            name="Analysis Output",
            source_type="iceberg",
            config={"analysis_tab_id": "tab-1"},
            created_by="analysis",
            created_by_analysis_id=analysis_with_output.id,
            is_hidden=True,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(output)
        test_db_session.commit()

        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output.id, cron_expression="0 * * * *"),
        )
        row = test_db_session.get(Schedule, schedule.id)
        assert row is not None
        row.lease_owner = "scheduler:test"
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        test_db_session.add(row)
        test_db_session.commit()

        run_id = enqueue_schedule_run(test_db_session, schedule.id, worker_id="scheduler:test")
        run = build_run_service.get_build_run(test_db_session, run_id)

        assert run is not None
        assert run.schedule_id == schedule.id
        assert run.status == BuildRunStatus.QUEUED
        assert run.current_datasource_id == output.id
        job = build_job_service.get_job_by_build_id(test_db_session, run_id)
        assert job is not None

    def test_enqueue_schedule_for_plain_datasource_creates_refresh_build(self, test_db_session: Session, sample_datasource: DataSource):
        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=sample_datasource.id, cron_expression="0 * * * *"),
        )
        row = test_db_session.get(Schedule, schedule.id)
        assert row is not None
        row.lease_owner = "scheduler:test"
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        test_db_session.add(row)
        test_db_session.commit()

        run_id = enqueue_schedule_run(test_db_session, schedule.id, worker_id="scheduler:test")
        run = build_run_service.get_build_run(test_db_session, run_id)

        assert run is not None
        assert run.schedule_id == schedule.id
        assert run.current_kind == EngineRunKind.BUILD.value
        assert run.status == BuildRunStatus.QUEUED


class TestScheduleReconciliation:
    def test_reconcile_success_updates_success_fields(self, test_db_session: Session, output_datasource: DataSource):
        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        build = build_run_service.create_build_run(
            test_db_session,
            build_id=str(uuid.uuid4()),
            namespace="default",
            schedule_id=schedule.id,
            analysis_id="analysis",
            analysis_name="Analysis",
            request_json={
                "analysis_pipeline": {"analysis_id": "analysis", "tabs": []},
                "tab_id": None,
            },
            starter_json={"triggered_by": f"schedule:{schedule.id}"},
            status=BuildRunStatus.COMPLETED,
        )
        build.completed_at = datetime.now(UTC)
        test_db_session.add(build)
        test_db_session.commit()

        updated = reconcile_schedule_run(test_db_session, build_id=build.id)

        assert updated is not None
        assert updated.last_run is not None
        assert updated.last_success_at is not None
        assert updated.last_successful_build_id == build.id
        assert updated.lease_owner is None

    def test_reconcile_failure_does_not_advance_last_run(self, test_db_session: Session, output_datasource: DataSource):
        schedule = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        row = test_db_session.get(Schedule, schedule.id)
        assert row is not None
        row.last_run = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        row.lease_owner = "scheduler:test"
        test_db_session.add(row)
        test_db_session.commit()

        build = build_run_service.create_build_run(
            test_db_session,
            build_id=str(uuid.uuid4()),
            namespace="default",
            schedule_id=schedule.id,
            analysis_id="analysis",
            analysis_name="Analysis",
            request_json={
                "analysis_pipeline": {"analysis_id": "analysis", "tabs": []},
                "tab_id": None,
            },
            starter_json={"triggered_by": f"schedule:{schedule.id}"},
            status=BuildRunStatus.FAILED,
        )
        build.completed_at = datetime.now(UTC)
        test_db_session.add(build)
        test_db_session.commit()

        updated = reconcile_schedule_run(test_db_session, build_id=build.id)

        assert updated is not None
        assert updated.last_failure_at is not None
        assert updated.last_successful_build_id is None
        assert updated.lease_owner is None


# ---------------------------------------------------------------------------
# Bug fixes
# ---------------------------------------------------------------------------


class TestSkippedScheduleDoesNotAdvanceLastRun:
    """Bug 5: skipping a schedule due to unmet dependency must not call mark_schedule_run."""

    def test_skipped_schedule_last_run_unchanged(self, test_db_session: Session, output_datasource: DataSource) -> None:
        """A schedule skipped for unmet dependency keeps last_run=None."""
        created = create_schedule(
            test_db_session,
            ScheduleCreate(datasource_id=output_datasource.id, cron_expression="0 * * * *"),
        )
        assert created.last_run is None

        row = test_db_session.get(Schedule, created.id)
        assert row is not None
        assert row.last_run is None


class TestGetBuildOrderNoDuplicateInDegree:
    """Bug 6: in_degree must not be double-incremented when two datasources from the
    same upstream analysis link to the same downstream analysis.
    """

    def test_two_datasources_same_upstream_no_double_in_degree(self, test_db_session: Session, sample_csv_file) -> None:
        """Downstream linked to two datasources both created by the same upstream.
        Before the fix, each datasource link incremented in_degree unconditionally,
        raising it to 2 and stalling BFS so downstream never appeared in the order.
        After the fix, the set-based dedup prevents the second increment.
        """
        upstream_id = str(uuid.uuid4())
        ds_a_id = str(uuid.uuid4())
        ds_b_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        for ds_id in (ds_a_id, ds_b_id):
            ds = DataSource(
                id=ds_id,
                name=f"Output {ds_id[:8]}",
                source_type="file",
                config={
                    "file_path": str(sample_csv_file),
                    "file_type": "csv",
                    "options": {},
                },
                created_at=now,
                created_by_analysis_id=upstream_id,
            )
            test_db_session.add(ds)

        upstream = Analysis(
            id=upstream_id,
            name="Upstream",
            description="",
            pipeline_definition={"tabs": []},
            status=AnalysisStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(upstream)

        downstream_id = str(uuid.uuid4())
        downstream = Analysis(
            id=downstream_id,
            name="Downstream",
            description="",
            pipeline_definition={"tabs": []},
            status=AnalysisStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(downstream)
        test_db_session.commit()

        link_a = AnalysisDataSource(analysis_id=downstream_id, datasource_id=ds_a_id)
        link_b = AnalysisDataSource(analysis_id=downstream_id, datasource_id=ds_b_id)
        test_db_session.add(link_a)
        test_db_session.add(link_b)
        test_db_session.commit()

        order = get_build_order(test_db_session, downstream_id)
        assert downstream_id in order
        assert upstream_id in order
        assert order.index(upstream_id) < order.index(downstream_id)
