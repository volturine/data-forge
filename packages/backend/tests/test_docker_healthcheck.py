from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend_core import runtime_workers_service as runtime_worker_service
from backend_core.database import run_settings_db
from backend_core.docker_healthcheck import worker_healthy
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind


def test_worker_healthy_accepts_recent_scheduler_heartbeat(monkeypatch) -> None:
    host = 'scheduler-host'
    now = datetime.now(UTC)
    monkeypatch.setattr('backend_core.docker_healthcheck.socket.gethostname', lambda: host)

    run_settings_db(
        lambda session: runtime_worker_service.register_worker(
            session, worker_id='scheduler-1', kind=RuntimeWorkerKind.SCHEDULER, hostname=host, pid=1, capacity=1, now=now
        )
    )

    assert worker_healthy(kind=RuntimeWorkerKind.SCHEDULER, heartbeat_seconds=15.0, hostname=host)


def test_worker_healthy_rejects_stale_manager_heartbeat(monkeypatch) -> None:
    host = 'worker-host'
    now = datetime.now(UTC)
    stale = now - timedelta(seconds=20)
    monkeypatch.setattr('backend_core.docker_healthcheck.socket.gethostname', lambda: host)

    run_settings_db(
        lambda session: runtime_worker_service.register_worker(
            session, worker_id='manager-1', kind=RuntimeWorkerKind.BUILD_MANAGER, hostname=host, pid=1, capacity=1, now=stale
        )
    )

    assert not worker_healthy(kind=RuntimeWorkerKind.BUILD_MANAGER, heartbeat_seconds=15.0, hostname=host)


def test_worker_healthy_rejects_stopped_worker(monkeypatch) -> None:
    host = 'scheduler-host'
    now = datetime.now(UTC)
    monkeypatch.setattr('backend_core.docker_healthcheck.socket.gethostname', lambda: host)

    run_settings_db(
        lambda session: runtime_worker_service.register_worker(
            session, worker_id='scheduler-2', kind=RuntimeWorkerKind.SCHEDULER, hostname=host, pid=2, capacity=1, now=now
        )
    )
    run_settings_db(lambda session: runtime_worker_service.mark_worker_stopped(session, worker_id='scheduler-2', now=now))

    assert not worker_healthy(kind=RuntimeWorkerKind.SCHEDULER, heartbeat_seconds=15.0, hostname=host)


def test_heartbeat_worker_updates_jobs_and_rejects_unknown_worker() -> None:
    now = datetime.now(UTC)
    run_settings_db(
        lambda session: runtime_worker_service.register_worker(
            session, worker_id='heartbeat-worker', kind=RuntimeWorkerKind.COORDINATOR, hostname='host', pid=3, capacity=4, now=now
        )
    )

    run_settings_db(lambda session: runtime_worker_service.heartbeat_worker(session, worker_id='heartbeat-worker', active_jobs=2, now=now))
    worker = run_settings_db(lambda session: runtime_worker_service.get_worker(session, 'heartbeat-worker'))
    assert worker is not None
    assert worker.active_jobs == 2
    assert worker.last_heartbeat_at.replace(tzinfo=UTC) == now

    with pytest.raises(ValueError, match='missing-worker'):
        run_settings_db(lambda session: runtime_worker_service.heartbeat_worker(session, worker_id='missing-worker', now=now))
