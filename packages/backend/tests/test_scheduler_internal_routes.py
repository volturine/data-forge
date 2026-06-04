from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlmodel import Session

from backend_core.config import settings
from backend_core.database import run_settings_db
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_workers.models import RuntimeWorker
from backend_core.persistence.scheduler.models import Schedule


def _set_internal_token(monkeypatch) -> str:
    token = 'test-internal-token'
    monkeypatch.setattr(settings, 'internal_api_token', token)
    return token


def test_internal_scheduler_routes_reject_missing_token(client, monkeypatch) -> None:
    _set_internal_token(monkeypatch)

    response = client.post('/api/v1/internal/scheduler/heartbeat', json={'worker_id': 'scheduler-1'})

    assert response.status_code == 401


def test_internal_scheduler_registers_and_stops_worker(client, monkeypatch) -> None:
    token = _set_internal_token(monkeypatch)
    headers = {'X-Internal-Token': token}
    worker_id = f'scheduler:{uuid.uuid4()}'

    response = client.post(
        '/api/v1/internal/scheduler/register',
        headers=headers,
        json={
            'worker_id': worker_id,
            'hostname': 'scheduler-host',
            'pid': 123,
            'capacity': 1,
        },
    )
    assert response.status_code == 200

    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.hostname == 'scheduler-host'
    assert worker.stopped_at is None

    response = client.post('/api/v1/internal/scheduler/stop', headers=headers, json={'worker_id': worker_id})
    assert response.status_code == 200

    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.stopped_at is not None


def test_internal_scheduler_run_due_enqueues_build_job(
    client,
    sample_datasource: DataSource,
    test_db_session: Session,
    monkeypatch,
) -> None:
    token = _set_internal_token(monkeypatch)
    headers = {'X-Internal-Token': token}
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

    response = client.post('/api/v1/internal/scheduler/run-due', headers=headers, json={'worker_id': worker_id})

    assert response.status_code == 200
    data = response.json()
    assert data['handled'] is True
    assert data['failures'] == []
    assert len(data['enqueued']) == 1
    assert data['enqueued'][0]['schedule_id'] == schedule.id
    assert data['enqueued'][0]['datasource_id'] == sample_datasource.id

    test_db_session.refresh(schedule)
    build_id = data['enqueued'][0]['build_id']
    assert schedule.last_triggered_at is not None
    assert schedule.lease_owner == worker_id
    job = test_db_session.execute(select(BuildJob).where(BuildJob.build_id == build_id)).scalar_one_or_none()
    assert job is not None
