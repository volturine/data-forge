from __future__ import annotations

from datetime import UTC, datetime, timedelta

from contracts.runtime_workers.models import RuntimeWorkerKind
from core import runtime_workers_service as runtime_worker_service
from core.database import run_settings_db
from core.docker_healthcheck import worker_healthy


def test_worker_healthy_accepts_recent_scheduler_heartbeat(monkeypatch) -> None:
    host = 'scheduler-host'
    now = datetime.now(UTC)
    monkeypatch.setattr('core.docker_healthcheck.socket.gethostname', lambda: host)

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
    monkeypatch.setattr('core.docker_healthcheck.socket.gethostname', lambda: host)

    run_settings_db(
        lambda session: runtime_worker_service.register_worker(
            session, worker_id='manager-1', kind=RuntimeWorkerKind.BUILD_MANAGER, hostname=host, pid=1, capacity=1, now=stale
        )
    )

    assert not worker_healthy(kind=RuntimeWorkerKind.BUILD_MANAGER, heartbeat_seconds=15.0, hostname=host)


def test_worker_healthy_rejects_stopped_worker(monkeypatch) -> None:
    host = 'scheduler-host'
    now = datetime.now(UTC)
    monkeypatch.setattr('core.docker_healthcheck.socket.gethostname', lambda: host)

    run_settings_db(
        lambda session: runtime_worker_service.register_worker(
            session, worker_id='scheduler-2', kind=RuntimeWorkerKind.SCHEDULER, hostname=host, pid=2, capacity=1, now=now
        )
    )
    run_settings_db(lambda session: runtime_worker_service.mark_worker_stopped(session, worker_id='scheduler-2', now=now))

    assert not worker_healthy(kind=RuntimeWorkerKind.SCHEDULER, heartbeat_seconds=15.0, hostname=host)
