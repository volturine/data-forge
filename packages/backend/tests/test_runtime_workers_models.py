from datetime import UTC, datetime, timedelta

import pytest

from backend_core import runtime_workers_service as runtime_worker_service
from backend_core.database import run_settings_db
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.persistence.runtime_workers.models import RuntimeWorker


def _worker(heartbeat: datetime, stopped: datetime | None = None) -> RuntimeWorker:
    return RuntimeWorker(
        id='worker-1',
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname='host',
        pid=1,
        capacity=1,
        active_jobs=0,
        started_at=heartbeat,
        last_heartbeat_at=heartbeat,
        updated_at=heartbeat,
        stopped_at=stopped,
    )


def test_is_reclaimable_with_naive_now_and_naive_heartbeat():
    stale = _worker(datetime(2026, 1, 1, 0, 0, 0))
    fresh_heartbeat = _worker(datetime.now(UTC).replace(tzinfo=None))

    assert stale.is_reclaimable(now=datetime.now(UTC).replace(tzinfo=None), heartbeat_seconds=15.0) is True
    assert fresh_heartbeat.is_reclaimable(now=datetime.now(UTC).replace(tzinfo=None), heartbeat_seconds=15.0) is False


def test_is_reclaimable_with_aware_now_and_naive_heartbeat():
    worker = _worker(datetime.now(UTC).replace(tzinfo=None))
    assert worker.is_reclaimable(now=datetime.now(UTC), heartbeat_seconds=15.0) is False


def test_is_reclaimable_with_naive_now_and_aware_utc_heartbeat():
    worker = _worker(datetime.now(UTC))
    assert worker.is_reclaimable(now=datetime.now(UTC).replace(tzinfo=None), heartbeat_seconds=15.0) is False


def test_is_reclaimable_with_aware_non_utc_inputs():
    heartbeat_utc = datetime.now(UTC)
    worker = _worker(heartbeat_utc)
    later = (heartbeat_utc + timedelta(hours=2)).astimezone()
    assert worker.is_reclaimable(now=later, heartbeat_seconds=15.0) is True


def test_is_reclaimable_when_stopped():
    worker = _worker(datetime.now(UTC), stopped=datetime.now(UTC))
    assert worker.is_reclaimable(now=datetime.now(UTC), heartbeat_seconds=15.0) is True


def test_heartbeat_worker_updates_jobs_and_rejects_unknown_worker() -> None:
    now = datetime.now(UTC)
    run_settings_db(
        lambda session: runtime_worker_service.register_worker(
            session, worker_id='heartbeat-worker', kind=RuntimeWorkerKind.COORDINATOR, hostname='host', pid=3, capacity=4, now=now
        )
    )

    run_settings_db(lambda session: runtime_worker_service.heartbeat_worker(session, worker_id='heartbeat-worker', active_jobs=2, now=now))
    worker = run_settings_db(lambda session: session.get(RuntimeWorker, 'heartbeat-worker'))
    assert worker is not None
    assert worker.active_jobs == 2
    assert worker.last_heartbeat_at.replace(tzinfo=UTC) == now

    with pytest.raises(ValueError, match='missing-worker'):
        run_settings_db(lambda session: runtime_worker_service.heartbeat_worker(session, worker_id='missing-worker', now=now))
