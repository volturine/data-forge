from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlmodel import Session

from backend_core.config import settings
from backend_core.database import run_settings_db
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_workers.models import RuntimeWorker
from backend_core.persistence.scheduler.models import Schedule
from backend_core.sqlmodel_typing import sa
from backend_grpc.server import SchedulerRuntimeServicer
from dataforge_protocol import common_pb2, scheduler_runtime_pb2


class FakeGrpcContext:
    def __init__(self, token: str | None) -> None:
        self._metadata = (('x-internal-token', token),) if token is not None else ()

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._metadata

    async def abort(self, _code, details: str) -> None:
        raise RuntimeError(details)


def _set_internal_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = 'test-internal-token'
    monkeypatch.setattr(settings, 'internal_api_token', token)
    return token


@pytest.mark.asyncio
async def test_internal_scheduler_grpc_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_internal_token(monkeypatch)

    with pytest.raises(RuntimeError, match='Invalid internal runtime token'):
        await SchedulerRuntimeServicer().HeartbeatScheduler(common_pb2.RuntimeWorkerRequest(worker_id='scheduler-1'), FakeGrpcContext(None))


@pytest.mark.asyncio
async def test_internal_scheduler_grpc_registers_and_stops_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    token = _set_internal_token(monkeypatch)
    context = FakeGrpcContext(token)
    worker_id = f'scheduler:{uuid.uuid4()}'
    servicer = SchedulerRuntimeServicer()

    await servicer.RegisterScheduler(
        scheduler_runtime_pb2.SchedulerRegisterRequest(worker_id=worker_id, hostname='scheduler-host', pid=123, capacity=1),
        context,
    )

    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.hostname == 'scheduler-host'
    assert worker.stopped_at is None

    await servicer.StopScheduler(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)

    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.stopped_at is not None


@pytest.mark.asyncio
async def test_internal_scheduler_grpc_run_due_enqueues_build_job(
    sample_datasource: DataSource,
    test_db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _set_internal_token(monkeypatch)
    worker_id = f'scheduler:{uuid.uuid4()}'
    schedule = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=sample_datasource.id,
        cron_expression='* * * * *',
        enabled=True,
        last_run=None,
        next_run=datetime.now(UTC) - timedelta(minutes=1),
        created_at=datetime.now(UTC),
    )
    test_db_session.add(schedule)
    test_db_session.commit()

    response = await SchedulerRuntimeServicer().RunDueSchedules(
        common_pb2.RuntimeWorkerRequest(worker_id=worker_id),
        FakeGrpcContext(token),
    )

    assert response.handled is True
    assert list(response.failures) == []
    assert len(response.enqueued) == 1
    assert response.enqueued[0].schedule_id == schedule.id
    assert response.enqueued[0].datasource_id == sample_datasource.id

    test_db_session.refresh(schedule)
    build_id = response.enqueued[0].build_id
    assert schedule.last_triggered_at is not None
    assert schedule.lease_owner == worker_id
    job = test_db_session.execute(select(BuildJob).where(sa(BuildJob.build_id == build_id))).scalar_one_or_none()
    assert job is not None
