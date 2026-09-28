from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import event
from sqlmodel import Session, select

from backend_core.domain.compute.base import EngineStatusInfo
from backend_core.domain.engine_instances.models import EngineInstanceStatus
from backend_core.engine_instances_service import persist_engine_snapshot
from backend_core.persistence.engine_instances.models import EngineInstance


def _engine_status(resource_id: str, *, container_id: str, last_activity: str | None = None) -> EngineStatusInfo:
    return EngineStatusInfo(
        analysis_id=resource_id,
        resource_id=resource_id,
        status='healthy',
        container_id=container_id,
        image_digest=None,
        lifecycle_status=EngineInstanceStatus.RUNNING.value,
        termination_reason=None,
        exit_code=None,
        oom_killed=None,
        supervisor_id='worker-snapshots',
        owner_id='worker-snapshots',
        last_activity=last_activity,
        current_job_id=None,
        resource_config=None,
        effective_resources=None,
        defaults={},
        scope='analysis_interactive',
        reuse_policy='shared',
    )


def test_concurrent_engine_snapshots_upsert_one_identity(test_engine) -> None:
    table = EngineInstance.metadata.tables[EngineInstance.__tablename__]
    EngineInstance.metadata.create_all(test_engine, tables=[table])
    barrier = Barrier(12)

    def persist(index: int) -> None:
        status = _engine_status('analysis-shared', container_id=f'container-{index}')
        barrier.wait()
        with Session(test_engine) as session:
            persist_engine_snapshot(
                session,
                worker_id='worker-snapshots',
                namespace='default',
                statuses=[status],
            )

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(persist, range(12)))

    with Session(test_engine) as session:
        rows = session.exec(select(EngineInstance).where(table.c.id.like('worker-snapshots:%'))).all()

    assert len(rows) == 1
    assert rows[0].container_id in {f'container-{index}' for index in range(12)}


def test_engine_snapshot_reads_active_rows_once_and_stops_missing_engines(test_engine) -> None:
    table = EngineInstance.metadata.tables[EngineInstance.__tablename__]
    EngineInstance.metadata.create_all(test_engine, tables=[table])
    last_activity = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    first_stamp = datetime(2026, 1, 1, tzinfo=UTC)
    second_stamp = first_stamp + timedelta(seconds=5)
    statuses = [_engine_status(f'analysis-{index}', container_id=f'container-{index}', last_activity=last_activity) for index in range(20)]
    with Session(test_engine) as session:
        persist_engine_snapshot(session, worker_id='worker-batch', namespace='default', statuses=statuses, now=first_stamp)

    engine_selects = 0
    engine_updates = 0

    def count_engine_selects(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        nonlocal engine_selects, engine_updates
        normalized = statement.upper()
        if normalized.lstrip().startswith('SELECT') and 'ENGINE_INSTANCES' in normalized:
            engine_selects += 1
        if normalized.lstrip().startswith('UPDATE') and 'ENGINE_INSTANCES' in normalized:
            engine_updates += 1

    event.listen(test_engine, 'before_cursor_execute', count_engine_selects)
    try:
        with Session(test_engine) as session:
            persist_engine_snapshot(
                session,
                worker_id='worker-batch',
                namespace='default',
                statuses=[_engine_status('analysis-0', container_id='container-updated'), *statuses[1:19]],
                now=second_stamp,
            )
    finally:
        event.remove(test_engine, 'before_cursor_execute', count_engine_selects)

    with Session(test_engine) as session:
        rows = session.exec(select(EngineInstance).where(table.c.worker_id == 'worker-batch')).all()
        by_analysis = {row.analysis_id: row for row in rows}

    assert engine_selects == 1
    assert engine_updates == 2  # one changed engine and the missing-engine stop sweep
    assert len(by_analysis) == 20
    assert by_analysis['analysis-0'].container_id == 'container-updated'
    assert by_analysis['analysis-0'].last_activity_at == datetime.fromisoformat(last_activity)
    assert by_analysis['analysis-0'].updated_at == second_stamp
    assert by_analysis['analysis-1'].updated_at == first_stamp
    assert by_analysis['analysis-19'].status == EngineInstanceStatus.STOPPED.value
