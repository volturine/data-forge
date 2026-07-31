import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from backend_core import build_runs_service as build_run_service
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.engine_runs.schemas import EngineRunKind
from backend_core.persistence.build_runs.models import BuildEvent
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent
from backend_core.sqlmodel_typing import sa


def _starter() -> dict[str, object]:
    return {'user_id': 'user-1', 'display_name': 'Test User', 'email': 'test@example.com', 'triggered_by': 'user'}


def _create_run(test_db_session):
    return build_run_service.create_build_run(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        analysis_id='analysis-1',
        analysis_name='Analysis 1',
        request_json={'analysis_id': 'analysis-1'},
        starter_json=_starter(),
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        current_tab_id='tab-1',
        current_tab_name='Tab 1',
        total_tabs=1,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
    )


def test_create_build_run_persists(test_db_session) -> None:
    run = _create_run(test_db_session)

    stored = build_run_service.get_build_run(test_db_session, run.id)

    assert stored is not None
    assert stored.status == BuildRunStatus.RUNNING
    assert stored.analysis_name == 'Analysis 1'
    assert stored.starter_json['email'] == 'test@example.com'
    assert stored.next_event_sequence == 1


def test_append_build_event_sequences_and_updates_snapshot(test_db_session) -> None:
    run = _create_run(test_db_session)
    started_at = datetime.now(UTC)
    progress = compute_schemas.BuildProgressEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=started_at,
        current_kind=EngineRunKind.BUILD,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        current_output_id='out-1',
        current_output_name='Output 1',
        engine_run_id='engine-1',
        progress=0.5,
        elapsed_ms=1200,
        estimated_remaining_ms=800,
        current_step='Filter rows',
        current_step_index=1,
        total_steps=4,
    )
    log = compute_schemas.BuildLogEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=started_at + timedelta(seconds=1),
        current_kind=EngineRunKind.BUILD,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        current_output_id='out-1',
        current_output_name='Output 1',
        engine_run_id='engine-1',
        level=compute_schemas.BuildLogLevel.INFO,
        message='hello',
    )

    first = build_run_service.append_build_event(test_db_session, build_id=run.id, event=progress)
    second = build_run_service.append_build_event(test_db_session, build_id=run.id, event=log)
    stored = build_run_service.get_build_run(test_db_session, run.id)

    assert first is not None
    assert second is not None
    assert first.sequence == 1
    assert second.sequence == 2
    assert stored is not None
    assert stored.current_engine_run_id == 'engine-1'
    assert stored.current_output_name == 'Output 1'
    assert stored.progress == 0.5
    assert stored.current_step == 'Filter rows'
    assert stored.next_event_sequence == 3


def test_concurrent_build_event_producers_receive_one_total_order_and_consistent_projection(test_engine, test_db_session) -> None:
    run = _create_run(test_db_session)
    producer_count = 8
    barrier = threading.Barrier(producer_count)
    emitted_at = datetime.now(UTC)

    def append_progress(index: int) -> tuple[int, str]:
        current_step = f'producer-{index}'
        event = compute_schemas.BuildProgressEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=emitted_at + timedelta(milliseconds=index),
            current_kind=EngineRunKind.BUILD,
            current_datasource_id='source-1',
            progress=(index + 1) / producer_count,
            elapsed_ms=index,
            current_step=current_step,
            current_step_index=index,
            total_steps=producer_count,
        )
        with Session(test_engine) as session:
            barrier.wait(timeout=5)
            row = build_run_service.append_build_event(session, build_id=run.id, event=event)
            assert row is not None
            return row.sequence, current_step

    with ThreadPoolExecutor(max_workers=producer_count) as pool:
        accepted = list(pool.map(append_progress, range(producer_count)))

    with Session(test_engine) as session:
        events = build_run_service.list_build_events_after(session, run.id)
        stored = build_run_service.get_build_run(session, run.id)
        outbox_events = list(session.execute(select(RuntimeOutboxEvent)).scalars().all())

    assert sorted(sequence for sequence, _step in accepted) == list(range(1, producer_count + 1))
    assert [event.sequence for event in events] == list(range(1, producer_count + 1))
    assert stored is not None
    assert stored.next_event_sequence == producer_count + 1
    assert stored.version == producer_count + 1
    assert stored.current_step == events[-1].payload_json['current_step']
    assert stored.current_step_index == events[-1].payload_json['current_step_index']
    assert sorted(event.payload_json['latest_sequence'] for event in outbox_events) == list(range(1, producer_count + 1))


def test_build_event_projection_counter_and_outbox_roll_back_together(test_db_session) -> None:
    run = _create_run(test_db_session)
    event = compute_schemas.BuildLogEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=datetime.now(UTC),
        current_kind=EngineRunKind.BUILD,
        current_datasource_id='source-1',
        level=compute_schemas.BuildLogLevel.INFO,
        message='uncommitted',
    )

    row = build_run_service.append_build_event(test_db_session, build_id=run.id, event=event, commit=False)
    assert row is not None
    test_db_session.rollback()
    test_db_session.expire_all()

    stored = build_run_service.get_build_run(test_db_session, run.id)
    events = list(test_db_session.execute(select(BuildEvent).where(sa(BuildEvent.build_id == run.id))).scalars().all())
    outbox_events = list(test_db_session.execute(select(RuntimeOutboxEvent)).scalars().all())

    assert stored is not None
    assert stored.next_event_sequence == 1
    assert stored.version == 1
    assert events == []
    assert outbox_events == []


def test_list_build_events_after_and_latest_sequence(test_db_session) -> None:
    run = _create_run(test_db_session)
    base = datetime.now(UTC)
    first = build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildLogEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=base,
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            level=compute_schemas.BuildLogLevel.INFO,
            message='one',
        ),
    )
    second = build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildLogEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=base + timedelta(seconds=1),
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            level=compute_schemas.BuildLogLevel.INFO,
            message='two',
        ),
    )

    assert first is not None
    assert second is not None
    rows = build_run_service.list_build_events_after(test_db_session, run.id, 1)
    serialized = build_run_service.serialize_event_row(rows[0])

    assert build_run_service.get_latest_sequence(test_db_session, run.id) == 2
    assert [row.sequence for row in rows] == [2]
    context = serialized['context']
    log = serialized['log']
    assert isinstance(context, dict)
    assert isinstance(log, dict)
    assert context['sequence'] == 2
    assert context['buildId'] == run.id
    assert log['level'] == 'BUILD_LOG_LEVEL_INFO'
    assert log['message'] == 'two'


def test_serialize_event_row_preserves_proto_default_scalars(test_db_session) -> None:
    run = _create_run(test_db_session)
    event = compute_schemas.BuildProgressEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=datetime.now(UTC),
        current_kind=EngineRunKind.BUILD,
        progress=0.0,
        elapsed_ms=0,
        total_steps=0,
    )

    row = build_run_service.append_build_event(test_db_session, build_id=run.id, event=event)

    assert row is not None
    serialized = build_run_service.serialize_event_row(row)
    progress = serialized['progress']
    assert isinstance(progress, dict)
    assert progress['progress'] == 0.0
    assert progress['elapsedMs'] == 0
    assert progress['totalSteps'] == 0


def test_serialize_step_event_includes_protocol_pipeline_step_kind(test_db_session) -> None:
    run = _create_run(test_db_session)
    row = build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildStepStartEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=datetime.now(UTC),
            current_kind=EngineRunKind.BUILD,
            build_step_index=1,
            step_index=0,
            step_id='step-1',
            step_name='Filter rows',
            step_type='filter',
            total_steps=2,
        ),
    )

    assert row is not None
    serialized = build_run_service.serialize_event_row(row)
    step_started = serialized['stepStarted']
    assert isinstance(step_started, dict)
    assert 'stepType' not in step_started
    assert step_started['stepKind'] == {'pipeline': 'STEP_TYPE_FILTER'}


def test_serialize_step_event_includes_protocol_execution_category_kind(test_db_session) -> None:
    run = _create_run(test_db_session)
    row = build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildStepCompleteEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=datetime.now(UTC),
            current_kind=EngineRunKind.BUILD,
            build_step_index=0,
            step_index=0,
            step_id='tab-1:initial_read',
            step_name='Initial Read',
            step_type='read',
            duration_ms=25,
            total_steps=2,
        ),
    )

    assert row is not None
    serialized = build_run_service.serialize_event_row(row)
    step_completed = serialized['stepCompleted']
    assert isinstance(step_completed, dict)
    assert 'stepType' not in step_completed
    assert step_completed['stepKind'] == {'executionCategory': 'ENGINE_RUN_EXECUTION_CATEGORY_READ'}


def test_serialize_step_event_rejects_untyped_step_kind(test_db_session) -> None:
    run = _create_run(test_db_session)
    row = build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildStepStartEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=datetime.now(UTC),
            current_kind=EngineRunKind.BUILD,
            build_step_index=1,
            step_index=0,
            step_id='step-1',
            step_name='Unknown stage',
            step_type='unknown',
            total_steps=2,
        ),
    )

    assert row is not None
    with pytest.raises(ValueError, match='Unsupported build step type'):
        build_run_service.serialize_event_row(row)


def test_fold_build_detail_reconstructs_snapshot(test_db_session) -> None:
    run = _create_run(test_db_session)
    emitted_at = datetime.now(UTC)
    build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildPlanEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=emitted_at,
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            tab_id='tab-1',
            tab_name='Tab 1',
            optimized_plan='optimized',
            unoptimized_plan='raw',
        ),
    )
    build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildStepStartEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=emitted_at + timedelta(seconds=1),
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            tab_id='tab-1',
            tab_name='Tab 1',
            build_step_index=0,
            step_index=0,
            step_id='step-1',
            step_name='Filter rows',
            step_type='filter',
            total_steps=1,
        ),
    )
    build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildResourceEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=emitted_at + timedelta(seconds=2),
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            tab_id='tab-1',
            tab_name='Tab 1',
            cpu_percent=10.0,
            memory_mb=128.0,
            memory_limit_mb=512.0,
            active_threads=4,
            max_threads=8,
        ),
        resource_config_json={'max_threads': 8, 'max_memory_mb': 512, 'streaming_chunk_size': 1000},
    )
    build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildCompleteEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=emitted_at + timedelta(seconds=3),
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            tab_id='tab-1',
            tab_name='Tab 1',
            current_output_id='out-1',
            current_output_name='Output 1',
            engine_run_id='engine-1',
            elapsed_ms=1500,
            total_steps=1,
            tabs_built=1,
            results=[
                compute_schemas.BuildTabResult(
                    tab_id='tab-1', tab_name='Tab 1', status=compute_schemas.BuildTabStatus.SUCCESS, output_id='out-1', output_name='Output 1'
                )
            ],
            duration_ms=1500,
        ),
    )

    stored = build_run_service.get_build_run(test_db_session, run.id)
    assert stored is not None
    detail = build_run_service.fold_build_detail(test_db_session, stored)

    assert detail.status == compute_schemas.ActiveBuildStatus.COMPLETED
    assert detail.query_plans[0].optimized_plan == 'optimized'
    assert detail.steps[0].state == compute_schemas.BuildStepState.RUNNING
    assert detail.latest_resources is not None
    assert detail.latest_resources.cpu_percent == 10.0
    assert detail.resource_config is not None
    assert detail.resource_config.max_threads == 8
    assert detail.results[0].output_name == 'Output 1'


def test_step_failed_event_does_not_make_running_snapshot_terminal(test_db_session) -> None:
    run = _create_run(test_db_session)
    emitted_at = datetime.now(UTC)
    build_run_service.append_build_event(
        test_db_session,
        build_id=run.id,
        event=compute_schemas.BuildStepFailedEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=emitted_at,
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            tab_id='tab-1',
            tab_name='Tab 1',
            build_step_index=0,
            step_index=0,
            step_id='step-1',
            step_name='Filter rows',
            step_type='filter',
            total_steps=1,
            error='Column not found',
        ),
    )

    stored = build_run_service.get_build_run(test_db_session, run.id)
    assert stored is not None
    detail = build_run_service.fold_build_detail(test_db_session, stored)

    assert detail.status == compute_schemas.ActiveBuildStatus.RUNNING
    assert detail.error is None
    assert detail.steps[0].state == compute_schemas.BuildStepState.FAILED
    assert detail.steps[0].error == 'Column not found'


def test_guarded_terminal_update_preserves_cancelled_terminal_state(test_db_session) -> None:
    run = _create_run(test_db_session)
    cancelled = compute_schemas.BuildCancelledEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=datetime.now(UTC),
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        progress=0.2,
        elapsed_ms=500,
        total_steps=2,
        tabs_built=0,
        results=[],
        duration_ms=500,
        cancelled_at=datetime.now(UTC),
        cancelled_by='user@example.com',
    )
    completed = compute_schemas.BuildCompleteEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=datetime.now(UTC) + timedelta(seconds=1),
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        elapsed_ms=900,
        total_steps=2,
        tabs_built=1,
        results=[],
        duration_ms=900,
    )

    first = build_run_service.guarded_terminal_update(test_db_session, build_id=run.id, event=cancelled)
    second = build_run_service.guarded_terminal_update(test_db_session, build_id=run.id, event=completed)
    stored = build_run_service.get_build_run(test_db_session, run.id)

    assert first is not None
    assert second is None
    assert stored is not None
    assert stored.status == BuildRunStatus.CANCELLED
    assert stored.cancelled_by == 'user@example.com'


def test_mark_build_running_uses_cas_and_preserves_terminal_state(test_db_session) -> None:
    run = _create_run(test_db_session)
    run.status = BuildRunStatus.CANCELLED
    run.version = 5
    test_db_session.add(run)
    test_db_session.commit()

    updated = build_run_service.mark_build_running(test_db_session, run.id)
    stored = build_run_service.get_build_run(test_db_session, run.id)

    assert updated is not None
    assert stored is not None
    assert updated.status == BuildRunStatus.CANCELLED
    assert stored.status == BuildRunStatus.CANCELLED
    assert stored.version == 5


def test_append_build_event_persists_matching_terminal_event_without_mutating_terminal_run(test_db_session) -> None:
    run = _create_run(test_db_session)
    cancelled_at = datetime.now(UTC)
    cancelled = compute_schemas.BuildCancelledEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=cancelled_at,
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        progress=0.2,
        elapsed_ms=500,
        total_steps=2,
        tabs_built=0,
        results=[],
        duration_ms=500,
        cancelled_at=cancelled_at,
        cancelled_by='user@example.com',
    )
    first = build_run_service.append_build_event(test_db_session, build_id=run.id, event=cancelled)
    test_db_session.expire_all()

    replay = compute_schemas.BuildCancelledEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=cancelled_at + timedelta(seconds=1),
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        progress=0.2,
        elapsed_ms=500,
        total_steps=2,
        tabs_built=0,
        results=[],
        duration_ms=500,
        cancelled_at=cancelled_at,
        cancelled_by='user@example.com',
    )
    second = build_run_service.append_build_event(test_db_session, build_id=run.id, event=replay)
    stored = build_run_service.get_build_run(test_db_session, run.id)

    assert first is not None
    assert second is not None
    assert first.sequence == 1
    assert second.sequence == 2
    assert stored is not None
    assert stored.status == BuildRunStatus.CANCELLED
    assert stored.updated_at is not None
    assert stored.completed_at is not None
    assert stored.cancelled_at is not None
    assert stored.updated_at.replace(tzinfo=UTC) == cancelled.emitted_at
    assert stored.completed_at.replace(tzinfo=UTC) == cancelled.emitted_at
    assert stored.cancelled_at.replace(tzinfo=UTC) == cancelled.cancelled_at
    assert stored.cancelled_by == 'user@example.com'


def test_append_build_event_rejects_conflicting_terminal_event_for_terminal_run(test_db_session) -> None:
    run = _create_run(test_db_session)
    cancelled = compute_schemas.BuildCancelledEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=datetime.now(UTC),
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        progress=0.2,
        elapsed_ms=500,
        total_steps=2,
        tabs_built=0,
        results=[],
        duration_ms=500,
        cancelled_at=datetime.now(UTC),
        cancelled_by='user@example.com',
    )
    complete = compute_schemas.BuildCompleteEvent(
        build_id=run.id,
        analysis_id=run.analysis_id,
        emitted_at=datetime.now(UTC) + timedelta(seconds=1),
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        elapsed_ms=900,
        total_steps=2,
        tabs_built=1,
        results=[],
        duration_ms=900,
    )

    first = build_run_service.append_build_event(test_db_session, build_id=run.id, event=cancelled)
    second = build_run_service.append_build_event(test_db_session, build_id=run.id, event=complete)
    rows = test_db_session.exec(select(BuildEvent).where(sa(BuildEvent.build_id == run.id))).all()

    assert first is not None
    assert second is None
    assert len(rows) == 1


def test_mark_running_builds_orphaned_marks_only_running(test_db_session) -> None:
    running = _create_run(test_db_session)
    done = build_run_service.create_build_run(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        analysis_id='analysis-2',
        analysis_name='Analysis 2',
        request_json={'analysis_id': 'analysis-2'},
        starter_json=_starter(),
        status=BuildRunStatus.COMPLETED,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
    )

    changed = build_run_service.mark_running_builds_orphaned(test_db_session, now=datetime.now(UTC) + timedelta(minutes=1))
    running_stored = build_run_service.get_build_run(test_db_session, running.id)
    done_stored = build_run_service.get_build_run(test_db_session, done.id)

    assert changed == 1
    assert running_stored is not None
    assert done_stored is not None
    assert running_stored.status == BuildRunStatus.ORPHANED
    assert running_stored.error_message == 'Build orphaned during startup recovery'
    assert done_stored.status == BuildRunStatus.COMPLETED


def test_get_build_run_by_engine_run_returns_latest_match(test_db_session) -> None:
    first = _create_run(test_db_session)
    second = _create_run(test_db_session)
    event = compute_schemas.BuildProgressEvent(
        build_id=second.id,
        analysis_id=second.analysis_id,
        emitted_at=datetime.now(UTC),
        current_kind=EngineRunKind.PREVIEW,
        current_datasource_id='source-1',
        tab_id='tab-1',
        tab_name='Tab 1',
        engine_run_id='engine-42',
        progress=0.1,
        elapsed_ms=100,
        total_steps=3,
    )
    build_run_service.append_build_event(test_db_session, build_id=second.id, event=event)
    build_run_service.append_build_event(
        test_db_session,
        build_id=first.id,
        event=compute_schemas.BuildProgressEvent(
            build_id=first.id,
            analysis_id=first.analysis_id,
            emitted_at=datetime.now(UTC) - timedelta(seconds=2),
            current_kind=EngineRunKind.PREVIEW,
            current_datasource_id='source-1',
            tab_id='tab-1',
            tab_name='Tab 1',
            engine_run_id='engine-42',
            progress=0.1,
            elapsed_ms=100,
            total_steps=3,
        ),
    )

    found = build_run_service.get_build_run_by_engine_run(test_db_session, 'engine-42')
    events = test_db_session.exec(select(BuildEvent).where(sa(BuildEvent.build_id == second.id))).all()

    assert found is not None
    assert found.id == second.id
    assert len(events) == 1
