import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from backend_core import build_runs_service, compute_requests_service, datasource_delete_service
from backend_core.build_datasource_dependencies import external_datasource_ids
from backend_core.datasource_lifecycle import lock_datasource_lifecycle
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute.schemas import AnalysisPipelinePayload
from backend_core.domain.compute_requests.models import command_from_payload
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.exceptions import AppError
from backend_core.persistence.build_runs.models import BuildRun, BuildRunDatasource
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from dataforge_protocol import enums_pb2
from modules.compute.commands import StartBuildCommand, start_build
from modules.datasource import service as datasource_service
from tests.harness.postgres_harness import wait_for_condition


def _preview_command(datasource_id: str):
    return command_from_payload(
        enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        {
            'analysis_id': 'analysis-1',
            'target_step_id': 'source',
            'row_limit': 100,
            'page': 1,
            'analysis_pipeline': {
                'analysis_id': 'analysis-1',
                'tabs': [
                    {
                        'id': 'tab-1',
                        'datasource': {
                            'id': datasource_id,
                            'analysis_tab_id': 'tab-1',
                            'source_type': 'file',
                            'config': {'branch': 'main'},
                        },
                        'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                        'steps': [],
                    }
                ],
            },
        },
    )


def _build_pipeline(datasource_id: str, *, datasource_type: str = 'file') -> dict[str, object]:
    return {
        'analysis_id': 'analysis-build-dependencies',
        'tabs': [
            {
                'id': 'tab-main',
                'name': 'Main',
                'datasource': {
                    'id': datasource_id,
                    'analysis_tab_id': None,
                    'source_type': datasource_type,
                    'config': {'branch': 'master'},
                },
                'output': {'result_id': 'output-main', 'filename': 'main.csv', 'format': 'csv'},
                'steps': [
                    {'id': 'join-step', 'type': 'join', 'config': {'right_source': 'right-source'}},
                    {
                        'id': 'union-step',
                        'type': 'union_by_name',
                        'config': {'sources': [datasource_id, 'output-main', 'third-source', 'tab-derived']},
                    },
                ],
            },
            {
                'id': 'tab-derived',
                'name': 'Derived',
                'datasource': {
                    'id': 'output-main',
                    'analysis_tab_id': 'tab-main',
                    'source_type': 'analysis',
                    'config': {'branch': 'master'},
                },
                'output': {'result_id': 'output-derived', 'filename': 'derived.csv', 'format': 'csv'},
                'steps': [],
            },
        ],
    }


def _start_build_command(build_id: str, datasource_id: str, *, namespace: str = 'default') -> StartBuildCommand:
    started_at = datetime.now(UTC)
    pipeline = _build_pipeline(datasource_id)
    return StartBuildCommand(
        build_id=build_id,
        namespace=namespace,
        analysis_id='analysis-build-dependencies',
        analysis_name='Build dependencies',
        request_json={'analysis_pipeline': pipeline, 'tab_id': 'tab-main'},
        starter_json={'triggered_by': 'test'},
        current_kind='build',
        current_datasource_id=datasource_id,
        current_tab_id='tab-main',
        current_tab_name='Main',
        current_output_id='output-main',
        current_output_name='main.csv',
        total_tabs=2,
        started_at=started_at,
        placeholders=[],
    )


def _add_file_datasources(session: Session, *datasource_ids: str, pending_delete: bool = False) -> None:
    session.add_all(
        DataSource(
            id=datasource_id,
            name=datasource_id,
            source_type=DataSourceType.FILE.value,
            config={'file_path': f's3://default/uploads/{datasource_id}.csv', 'file_type': 'csv'},
            is_pending_delete=pending_delete,
            created_at=datetime.now(UTC),
        )
        for datasource_id in datasource_ids
    )
    session.commit()


def test_build_pipeline_external_dependencies_include_join_and_union_sources() -> None:
    pipeline = AnalysisPipelinePayload.model_validate(_build_pipeline('source-main'))

    assert external_datasource_ids(pipeline) == ('right-source', 'source-main', 'third-source')


def test_schedule_ingest_source_is_external_when_output_reuses_its_id() -> None:
    pipeline = AnalysisPipelinePayload.model_validate(_build_pipeline('scheduled-source', datasource_type='schedule'))

    assert external_datasource_ids(pipeline) == ('right-source', 'scheduled-source', 'third-source')


def test_finalize_delete_waits_for_active_compute_request(test_db_session) -> None:
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Pending datasource',
            source_type=DataSourceType.ICEBERG.value,
            config={
                'metadata_path': f's3://default/exports/{datasource_id}/master',
                'catalog_type': 'sql',
                'catalog_uri': 'postgresql://catalog-user:secret@catalog.example/iceberg',
                'warehouse': 's3://default/exports',
                'namespace': 'outputs',
                'table': f'{datasource_id}_master',
                'source': {'source_type': 'file', 'file_path': f's3://default/uploads/{datasource_id}.csv'},
            },
            is_pending_delete=True,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=_preview_command(datasource_id),
    )
    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id) is False
    assert test_db_session.get(DataSource, datasource_id) is not None

    request = test_db_session.exec(select(ComputeRequest)).one()
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    test_db_session.add(request)
    test_db_session.commit()

    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id) is True
    assert test_db_session.get(DataSource, datasource_id) is None
    cleanup_events = test_db_session.exec(select(RuntimeOutboxEvent)).all()
    assert {event.payload_json['url'] for event in cleanup_events} == {
        f's3://default/exports/{datasource_id}',
        f's3://default/exports/{datasource_id}/master',
        f's3://default/uploads/{datasource_id}.csv',
    }
    catalog_event = next(event for event in cleanup_events if event.payload_json['url'].endswith('/master'))
    assert catalog_event.payload_json['catalog_identifier'] == f'outputs.{datasource_id}_master'
    assert catalog_event.payload_json['catalog_type'] == 'sql'
    assert catalog_event.payload_json['catalog_uri'] == 'postgresql://catalog-user:secret@catalog.example/iceberg'
    assert catalog_event.payload_json['warehouse'] == 's3://default/exports'
    assert catalog_event.payload_json['catalog_namespace'] == 'outputs'
    assert catalog_event.payload_json['catalog_table'] == f'{datasource_id}_master'
    assert catalog_event.payload_json['catalog_family_prefix'] == f'{datasource_id}_'
    assert all(event.status == RuntimeOutboxStatus.PENDING for event in cleanup_events)


def test_datasource_delete_waits_for_build_reader_until_build_is_terminal(test_db_session) -> None:
    datasource_id = str(uuid.uuid4())
    _add_file_datasources(test_db_session, datasource_id, 'right-source', 'third-source')
    build_id = str(uuid.uuid4())
    start_build(test_db_session, _start_build_command(build_id, datasource_id))

    dependencies = test_db_session.exec(select(BuildRunDatasource).where(BuildRunDatasource.build_id == build_id)).all()
    assert {dependency.datasource_id for dependency in dependencies} == {'right-source', datasource_id, 'third-source'}
    assert build_runs_service.has_active_build_for_datasource(test_db_session, namespace='default', datasource_id=datasource_id)

    datasource_delete_service.request_delete(test_db_session, datasource_id)
    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id) is False
    assert test_db_session.get(DataSource, datasource_id) is not None
    assert test_db_session.exec(select(RuntimeOutboxEvent).where(RuntimeOutboxEvent.kind == 'storage_cleanup')).all() == []

    run = build_runs_service.get_build_run(test_db_session, build_id)
    assert run is not None
    run.status = BuildRunStatus.COMPLETED
    test_db_session.add(run)
    test_db_session.commit()
    assert not build_runs_service.has_active_build_for_datasource(test_db_session, namespace='default', datasource_id=datasource_id)
    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id) is True
    assert test_db_session.get(DataSource, datasource_id) is None


def test_start_build_rejects_a_tombstoned_external_datasource(test_db_session) -> None:
    datasource_id = str(uuid.uuid4())
    _add_file_datasources(test_db_session, datasource_id, 'right-source', 'third-source', pending_delete=True)

    with pytest.raises(AppError, match='not found'):
        start_build(test_db_session, _start_build_command(str(uuid.uuid4()), datasource_id))

    assert test_db_session.exec(select(BuildRunDatasource)).all() == []
    assert test_db_session.exec(select(BuildRun)).all() == []


def test_build_enqueue_holds_shared_lifecycle_lock_against_datasource_tombstone(test_db_session, test_engine) -> None:
    datasource_id = str(uuid.uuid4())
    _add_file_datasources(test_db_session, datasource_id, 'right-source', 'third-source')
    datasource_pid = int(test_db_session.execute(text('SELECT pg_backend_pid()')).scalar_one())
    lock_datasource_lifecycle(test_db_session, namespace='default', datasource_id=datasource_id, shared=True)
    delete_started = Event()
    deletion_pid: list[int] = []

    def delete_and_finalize() -> bool:
        with Session(test_engine) as delete_session:
            delete_pid = int(delete_session.execute(text('SELECT pg_backend_pid()')).scalar_one())
            deletion_pid.append(delete_pid)
            delete_started.set()
            datasource_delete_service.request_delete(delete_session, datasource_id)
            result = datasource_delete_service.finalize_delete(delete_session, datasource_id)
            assert delete_pid != datasource_pid
            return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(delete_and_finalize)
        try:
            assert delete_started.wait(timeout=2)

            def delete_is_waiting_for_build_enqueue() -> bool:
                if not deletion_pid:
                    return False
                with test_engine.connect() as observer:
                    blockers = observer.execute(text('SELECT pg_blocking_pids(:pid)'), {'pid': deletion_pid[0]}).scalar_one()
                return datasource_pid in blockers

            wait_for_condition(delete_is_waiting_for_build_enqueue, timeout=5, description='datasource deletion to wait for the build lifecycle lock')
            build_id = str(uuid.uuid4())
            start_build(test_db_session, _start_build_command(build_id, datasource_id))
            assert deletion.result(timeout=5) is False
        finally:
            if not deletion.done():
                test_db_session.rollback()
                deletion.result(timeout=5)

    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None and stored.is_pending_delete
    assert build_runs_service.has_active_build_for_datasource(test_db_session, namespace='default', datasource_id=datasource_id)


def test_build_datasource_references_are_namespace_scoped(test_db_session) -> None:
    datasource_id = 'shared-looking-datasource-id'
    for namespace in ('default', 'alpha'):
        build_runs_service.stage_build_run(
            test_db_session,
            build_id=f'build-{namespace}',
            namespace=namespace,
            analysis_id=f'analysis-{namespace}',
            analysis_name=f'Analysis {namespace}',
            request_json={},
            starter_json={},
            status=BuildRunStatus.QUEUED,
            datasource_ids=(datasource_id,) if namespace == 'default' else (),
            created_at=datetime.now(UTC),
        )
    test_db_session.commit()

    assert build_runs_service.has_active_build_for_datasource(test_db_session, namespace='default', datasource_id=datasource_id)
    assert not build_runs_service.has_active_build_for_datasource(test_db_session, namespace='alpha', datasource_id=datasource_id)

    alpha_run = build_runs_service.get_build_run(test_db_session, 'build-alpha')
    assert alpha_run is not None
    test_db_session.add(BuildRunDatasource(build_id=alpha_run.id, namespace='alpha', datasource_id=datasource_id))
    test_db_session.commit()
    assert build_runs_service.has_active_build_for_datasource(test_db_session, namespace='alpha', datasource_id=datasource_id)
    alpha_run.status = BuildRunStatus.COMPLETED
    test_db_session.add(alpha_run)
    test_db_session.commit()

    assert build_runs_service.has_active_build_for_datasource(test_db_session, namespace='default', datasource_id=datasource_id)
    assert not build_runs_service.has_active_build_for_datasource(test_db_session, namespace='alpha', datasource_id=datasource_id)


def test_active_datasource_lock_prevents_delete_before_request_enqueue(test_db_session, test_engine) -> None:
    """A delete cannot finalize in the validation-to-enqueue transaction gap."""
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Racing datasource',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://default/clean/racing/master'},
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    # This is the same lock held by a compute route after its active-resource
    # check. The request commit below must release it before deletion can mark
    # and finalize the row.
    datasource_delete_service.get_active_datasource(test_db_session, datasource_id, for_update=True)

    def delete_and_finalize() -> bool:
        with Session(test_engine) as delete_session:
            datasource_delete_service.request_delete(delete_session, datasource_id)
            return datasource_delete_service.finalize_delete(delete_session, datasource_id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(delete_and_finalize)
        request = compute_requests_service.create_request(
            test_db_session,
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=_preview_command(datasource_id),
        )
        assert deletion.result(timeout=5) is False

    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None
    assert stored.is_pending_delete is True
    assert request.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED


def test_finalize_delete_does_not_delete_reactivated_datasource(test_db_session) -> None:
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Republished datasource',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://default/clean/republished/master'},
            is_pending_delete=False,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id) is False
    assert test_db_session.get(DataSource, datasource_id) is not None


def test_finalize_delete_rolls_back_row_and_cleanup_intents_together(test_db_session, monkeypatch) -> None:
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Rollback datasource',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': f's3://default/clean/{datasource_id}/master'},
            is_pending_delete=True,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    def fail_refresh(*_args, **_kwargs) -> None:
        raise RuntimeError('forced transaction failure')

    monkeypatch.setattr(datasource_delete_service.runtime_work_service, 'refresh_pending_work', fail_refresh)
    with pytest.raises(RuntimeError, match='forced transaction failure'):
        datasource_delete_service.finalize_delete(test_db_session, datasource_id)
    test_db_session.rollback()

    assert test_db_session.get(DataSource, datasource_id) is not None
    assert test_db_session.exec(select(RuntimeOutboxEvent)).all() == []


def test_direct_service_delete_enqueues_managed_object_cleanup(test_db_session) -> None:
    datasource_id = str(uuid.uuid4())
    source_path = f's3://default/uploads/{datasource_id}.csv'
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Direct delete datasource',
            source_type=DataSourceType.FILE.value,
            config={'file_path': source_path, 'file_type': 'csv'},
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    datasource_service.delete_datasource(test_db_session, datasource_id)

    pending = test_db_session.get(DataSource, datasource_id)
    assert pending is not None and pending.is_pending_delete
    assert test_db_session.exec(select(RuntimeOutboxEvent).where(RuntimeOutboxEvent.kind == 'storage_cleanup')).all() == []

    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id)
    assert test_db_session.get(DataSource, datasource_id) is None
    cleanup_event = test_db_session.exec(select(RuntimeOutboxEvent).where(RuntimeOutboxEvent.kind == 'storage_cleanup')).one()
    assert cleanup_event.payload_json['url'] == source_path
    assert cleanup_event.payload_json['resource_id'] == datasource_id
    assert cleanup_event.payload_json['owner_kind'] == 'datasource'
    assert cleanup_event.status == RuntimeOutboxStatus.PENDING
