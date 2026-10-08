from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

import backend_core.engine_instances_service as engine_instances_service
from backend_core.domain.compute.base import ComputeWorkerStatusInfo
from backend_core.domain.engine_instances.models import EngineInstanceStatus
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.engine_instances_service import persist_compute_worker_snapshot
from backend_core.persistence.compute_worker_instances.models import ComputeWorkerInstance


@pytest.fixture(autouse=True)
def _no_reclaimable_coordinator_workers(monkeypatch) -> None:
    def reclaimable_worker_ids(_session, *, kind: RuntimeWorkerKind) -> set[str]:
        assert kind == RuntimeWorkerKind.COORDINATOR
        return set()

    monkeypatch.setattr(engine_instances_service.runtime_workers_service, 'reclaimable_worker_ids', reclaimable_worker_ids)


def _engine_status(resource_id: str, *, container_id: str, last_activity: str | None = None) -> ComputeWorkerStatusInfo:
    return ComputeWorkerStatusInfo(
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


def _engine_instance(worker_id: str, namespace: str, resource_id: str, *, stamp: datetime) -> ComputeWorkerInstance:
    return ComputeWorkerInstance(
        id=f'{worker_id}:{namespace}:analysis_interactive:{resource_id}',
        worker_id=worker_id,
        namespace=namespace,
        analysis_id=resource_id,
        compute_worker_scope='analysis_interactive',
        compute_worker_reuse_policy='shared',
        status=EngineInstanceStatus.RUNNING.value,
        current_job_id=f'job-{resource_id}',
        current_build_id=f'build-{resource_id}',
        current_compute_worker_run_id=f'run-{resource_id}',
        last_seen_at=stamp,
        updated_at=stamp,
    )


def test_concurrent_engine_snapshots_upsert_one_identity(test_engine) -> None:
    table = ComputeWorkerInstance.metadata.tables[ComputeWorkerInstance.__tablename__]
    ComputeWorkerInstance.metadata.create_all(test_engine, tables=[table])
    barrier = Barrier(12)

    def persist(index: int) -> None:
        status = _engine_status('analysis-shared', container_id=f'container-{index}')
        barrier.wait()
        with Session(test_engine) as session:
            persist_compute_worker_snapshot(
                session,
                worker_id='worker-snapshots',
                namespace='default',
                statuses=[status],
            )

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(persist, range(12)))

    with Session(test_engine) as session:
        rows = session.exec(select(ComputeWorkerInstance).where(table.c.id.like('worker-snapshots:%'))).all()

    assert len(rows) == 1
    assert rows[0].container_id in {f'container-{index}' for index in range(12)}


def test_engine_snapshot_reads_active_rows_once_and_stops_missing_engines(test_engine) -> None:
    table = ComputeWorkerInstance.metadata.tables[ComputeWorkerInstance.__tablename__]
    ComputeWorkerInstance.metadata.create_all(test_engine, tables=[table])
    last_activity = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    first_stamp = datetime(2026, 1, 1, tzinfo=UTC)
    second_stamp = first_stamp + timedelta(seconds=5)
    statuses = [_engine_status(f'analysis-{index}', container_id=f'container-{index}', last_activity=last_activity) for index in range(20)]
    with Session(test_engine) as session:
        persist_compute_worker_snapshot(session, worker_id='worker-batch', namespace='default', statuses=statuses, now=first_stamp)

    engine_selects: list[str] = []
    engine_updates = 0
    engine_update_batches: list[tuple[bool, int]] = []

    def count_engine_selects(_conn, _cursor, statement, parameters, _context, executemany) -> None:
        nonlocal engine_updates
        normalized = statement.upper()
        if normalized.lstrip().startswith('SELECT') and 'COMPUTE_WORKER_INSTANCES' in normalized:
            engine_selects.append(normalized)
        if normalized.lstrip().startswith('UPDATE') and 'COMPUTE_WORKER_INSTANCES' in normalized:
            engine_updates += 1
            engine_update_batches.append((executemany, len(parameters) if executemany else 1))

    event.listen(test_engine, 'before_cursor_execute', count_engine_selects)
    try:
        with Session(test_engine) as session:
            persist_compute_worker_snapshot(
                session,
                worker_id='worker-batch',
                namespace='default',
                statuses=[
                    _engine_status('analysis-0', container_id='container-updated'),
                    _engine_status('analysis-1', container_id='container-1-updated', last_activity=last_activity),
                    *statuses[2:19],
                    _engine_status('analysis-new', container_id='container-new'),
                ],
                now=second_stamp,
            )
    finally:
        event.remove(test_engine, 'before_cursor_execute', count_engine_selects)

    with Session(test_engine) as session:
        rows = session.exec(select(ComputeWorkerInstance).where(table.c.worker_id == 'worker-batch')).all()
        by_analysis = {row.analysis_id: row for row in rows}

    assert len(engine_selects) == 1
    selected_columns = engine_selects[0].partition('FROM')[0].removeprefix('SELECT').strip()
    assert [column.rsplit('.', 1)[-1].strip() for column in selected_columns.split(',')] == [
        'ID',
        'CONTAINER_ID',
        'IMAGE_DIGEST',
        'TERMINATION_REASON',
        'EXIT_CODE',
        'OOM_KILLED',
        'SUPERVISOR_ID',
        'OWNER_ID',
        'DOCKER_HOST',
        'STATUS',
        'COMPUTE_WORKER_SCOPE',
        'COMPUTE_WORKER_REUSE_POLICY',
        'DATASOURCE_ID',
        'BUILD_ID',
        'CURRENT_JOB_ID',
        'CURRENT_BUILD_ID',
        'CURRENT_COMPUTE_WORKER_RUN_ID',
        'RESOURCE_CONFIG_JSON',
        'EFFECTIVE_RESOURCES_JSON',
        'LAST_ACTIVITY_AT',
    ]
    assert engine_updates == 2  # one changed engine and the missing-engine stop sweep
    assert engine_update_batches == [(True, 2), (False, 1)]
    assert len(by_analysis) == 21
    assert by_analysis['analysis-0'].updated_at == second_stamp
    assert by_analysis['analysis-0'].container_id == 'container-updated'
    assert by_analysis['analysis-0'].last_activity_at == datetime.fromisoformat(last_activity)
    assert by_analysis['analysis-1'].updated_at == second_stamp
    assert by_analysis['analysis-1'].container_id == 'container-1-updated'
    assert by_analysis['analysis-2'].updated_at == first_stamp
    assert by_analysis['analysis-2'].last_seen_at == first_stamp
    assert by_analysis['analysis-19'].status == EngineInstanceStatus.STOPPED.value
    assert by_analysis['analysis-19'].updated_at == second_stamp
    assert by_analysis['analysis-new'].container_id == 'container-new'
    assert by_analysis['analysis-new'].updated_at == second_stamp


def test_engine_snapshot_generation_stops_reclaimable_prior_coordinator_rows(test_engine, monkeypatch) -> None:
    table = ComputeWorkerInstance.metadata.tables[ComputeWorkerInstance.__tablename__]
    ComputeWorkerInstance.metadata.create_all(test_engine, tables=[table])
    first_stamp = datetime(2026, 1, 1, tzinfo=UTC)
    snapshot_stamp = first_stamp + timedelta(seconds=5)
    requested_kinds: list[RuntimeWorkerKind] = []

    def reclaimable_worker_ids(_session, *, kind: RuntimeWorkerKind) -> set[str]:
        requested_kinds.append(kind)
        return {'worker-stopped', 'worker-stale', 'worker-current'}

    monkeypatch.setattr(engine_instances_service.runtime_workers_service, 'reclaimable_worker_ids', reclaimable_worker_ids)
    prior_rows = [
        _engine_instance('worker-stopped', 'default', 'analysis-stopped', stamp=first_stamp),
        _engine_instance('worker-stale', 'default', 'analysis-stale', stamp=first_stamp),
    ]
    with Session(test_engine) as session:
        session.add_all(prior_rows)
        session.commit()

    with Session(test_engine) as session:
        persist_compute_worker_snapshot(
            session,
            worker_id='worker-current',
            namespace='default',
            statuses=[_engine_status('analysis-current', container_id='container-current')],
            now=snapshot_stamp,
        )

    with Session(test_engine) as session:
        rows = session.exec(select(ComputeWorkerInstance).where(table.c.namespace == 'default')).all()
        by_id = {row.id: row for row in rows}

    assert requested_kinds == [RuntimeWorkerKind.COORDINATOR]
    for worker_id, resource_id in (
        ('worker-stopped', 'analysis-stopped'),
        ('worker-stale', 'analysis-stale'),
    ):
        row = by_id[f'{worker_id}:default:analysis_interactive:{resource_id}']
        assert row.status == EngineInstanceStatus.STOPPED.value
        assert row.current_job_id is None
        assert row.current_build_id is None
        assert row.current_compute_worker_run_id is None
        assert row.last_seen_at == snapshot_stamp
        assert row.updated_at == snapshot_stamp

    current_row = by_id['worker-current:default:analysis_interactive:analysis-current']
    assert current_row.status == EngineInstanceStatus.RUNNING.value
    assert current_row.last_seen_at == snapshot_stamp


def test_engine_snapshot_generation_preserves_fresh_prior_coordinator_rows(test_engine, monkeypatch) -> None:
    table = ComputeWorkerInstance.metadata.tables[ComputeWorkerInstance.__tablename__]
    ComputeWorkerInstance.metadata.create_all(test_engine, tables=[table])
    first_stamp = datetime(2026, 1, 1, tzinfo=UTC)
    snapshot_stamp = first_stamp + timedelta(seconds=5)
    monkeypatch.setattr(
        engine_instances_service.runtime_workers_service,
        'reclaimable_worker_ids',
        lambda _session, *, kind: {'worker-stale'},
    )
    prior_rows = [
        _engine_instance('worker-fresh', 'default', 'analysis-fresh', stamp=first_stamp),
        _engine_instance('worker-stale', 'default', 'analysis-stale', stamp=first_stamp),
        _engine_instance('worker-stale', 'other', 'analysis-other-namespace', stamp=first_stamp),
    ]
    with Session(test_engine) as session:
        session.add_all(prior_rows)
        session.commit()

    with Session(test_engine) as session:
        persist_compute_worker_snapshot(session, worker_id='worker-current', namespace='default', statuses=[], now=snapshot_stamp)

    with Session(test_engine) as session:
        rows = session.exec(select(ComputeWorkerInstance)).all()
        by_id = {row.id: row for row in rows}

    fresh_row = by_id['worker-fresh:default:analysis_interactive:analysis-fresh']
    assert fresh_row.status == EngineInstanceStatus.RUNNING.value
    assert fresh_row.current_job_id == 'job-analysis-fresh'
    assert fresh_row.last_seen_at == first_stamp
    assert fresh_row.updated_at == first_stamp

    stale_row = by_id['worker-stale:default:analysis_interactive:analysis-stale']
    assert stale_row.status == EngineInstanceStatus.STOPPED.value
    assert stale_row.current_job_id is None
    assert stale_row.last_seen_at == snapshot_stamp
    assert stale_row.updated_at == snapshot_stamp

    other_namespace_row = by_id['worker-stale:other:analysis_interactive:analysis-other-namespace']
    assert other_namespace_row.status == EngineInstanceStatus.RUNNING.value
    assert other_namespace_row.current_job_id == 'job-analysis-other-namespace'
    assert other_namespace_row.last_seen_at == first_stamp
    assert other_namespace_row.updated_at == first_stamp


def test_engine_snapshot_reports_advisory_wait_and_snapshot_write_phases(test_engine, monkeypatch) -> None:
    table = ComputeWorkerInstance.metadata.tables[ComputeWorkerInstance.__tablename__]
    ComputeWorkerInstance.metadata.create_all(test_engine, tables=[table])
    tick = 10.0

    def fake_clock() -> float:
        nonlocal tick
        current = tick
        tick += 0.125
        return current

    monkeypatch.setattr(engine_instances_service, '_snapshot_phase_clock', fake_clock)
    phases: dict[str, float] = {}

    with Session(test_engine) as session:
        persist_compute_worker_snapshot(
            session,
            worker_id='worker-timed-snapshot',
            namespace='default',
            statuses=[_engine_status('analysis-timed', container_id='container-timed')],
            phase_timings=phases,
        )

    assert phases == {
        'advisory_lock_wait_ms': 125.0,
        'snapshot_write_ms': 1625.0,
        'active_id_mapping_ms': 125.0,
        'existing_row_query_fetch_ms': 125.0,
        'applying_statuses_ms': 125.0,
        'stale_row_sweep_ms': 125.0,
        'notification_enqueue_ms': 125.0,
        'snapshot_commit_ms': 125.0,
    }
