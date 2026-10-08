from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend_core import build_runs_service, compute_requests_service, runtime_outbox_service, storage_cleanup_service as cleanup
from backend_core.config import settings
from backend_core.database import init_db
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute_requests.models import command_from_payload
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.persistence.build_runs.models import BuildRunDatasource
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from backend_core.runtime_outbox_service import OutboxClaim
from backend_core.sqlmodel_typing import col
from dataforge_protocol import enums_pb2
from modules.datasource import preflight, publication_service
from tests.harness.postgres_harness import wait_for_condition


def _stage(session: Session) -> tuple[ComputeRequest, str, str]:
    request = compute_requests_service.create_request(
        session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
            {'name': 'Staged', 'file_path': 's3://default/uploads/source.csv', 'file_type': 'csv'},
        ),
    )
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    request.claim_token = str(uuid4())
    request.lease_owner = 'writer'
    request.lease_generation = 1
    request.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    session.commit()
    table = f'{request.id}__claim_{request.claim_token.replace("-", "_")}'
    prefix = f's3://default/clean/{table}/master'
    artifact = f's3://default/runtime-staging/datasource-stage/{request.id}/1/manifest.json'
    cleanup.register_stage(
        session,
        datasource_id=request.id,
        owner_kind='compute',
        owner_id=request.id,
        worker_id='writer',
        claim_token=request.claim_token,
        lease_generation=1,
        prefix_url=prefix,
        manifest_url=artifact,
        catalog_identifier=f'clean.{table}',
    )
    return request, prefix, artifact


def _preview_command_for_resource(datasource_id: str):
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
                        'datasource': {'id': datasource_id, 'source_type': 'file', 'config': {}},
                        'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                        'steps': [],
                    }
                ],
            },
        },
    )


def _claim(session: Session, url: str) -> OutboxClaim:
    return next(claim for claim in cleanup.claim_cleanups(session, limit=16) if claim.payload['url'] == url)


def _authorize(session: Session, claim: OutboxClaim) -> bool:
    return cleanup.authorize_cleanup(session, event_id=claim.event_id, claim_token=claim.claim_token, lease_generation=claim.lease_generation)


def _complete(session: Session, claim: OutboxClaim, *, error: str | None = None) -> bool:
    return cleanup.complete_cleanup(session, event_id=claim.event_id, claim_token=claim.claim_token, lease_generation=claim.lease_generation, error=error)


def _settle_writer(session: Session, request: ComputeRequest) -> None:
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    request.claim_token = None
    request.lease_expires_at = None
    session.add(request)
    session.commit()


def test_registration_persists_both_targets_and_runtime_wakes_never_claim_them(test_db_session: Session) -> None:
    request, prefix, artifact = _stage(test_db_session)
    assert request.artifact_path is not None
    assert runtime_outbox_service.dispatch_pending_events(test_db_session) == 0
    claims = cleanup.claim_cleanups(test_db_session, limit=16)
    assert {claim.payload['url'] for claim in claims} == {prefix, artifact, request.artifact_path}
    prefix_claim = next(claim for claim in claims if claim.payload['url'] == prefix)
    assert prefix_claim.payload['catalog_identifier'] == f'clean.{prefix.split("/")[-2]}'
    assert all(claim.lease_generation == 1 for claim in claims)


def test_uploaded_source_intent_is_settled_when_publication_commits_before_request_failure(test_db_session: Session) -> None:
    source = 's3://default/uploads/published-before-ingest-completion.csv'
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
            {'name': 'Published before failure', 'file_path': source, 'file_type': 'csv'},
        ),
    )
    event = test_db_session.get(RuntimeOutboxEvent, cleanup._event_id(source))
    assert event is not None
    assert event.payload_json['owner_kind'] == 'source'
    assert event.payload_json['owner_id'] == request.id
    assert event.payload_json['phase'] == cleanup.StorageCleanupPhase.TRACKED.value

    publication_service.create_datasource(
        test_db_session,
        datasource_id=request.id,
        name='Published before failure',
        description=None,
        source_type='file',
        config={'file_path': source, 'file_type': 'csv'},
        owner_id=None,
    )
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    test_db_session.add(request)
    test_db_session.commit()
    test_db_session.expire_all()

    published = test_db_session.get(DataSource, request.id)
    event = test_db_session.get(RuntimeOutboxEvent, cleanup._event_id(source))
    assert published is not None and published.config['file_path'] == source
    assert event is not None
    assert event.payload_json['phase'] == cleanup.StorageCleanupPhase.PUBLISHED.value
    assert event.status == RuntimeOutboxStatus.DISPATCHED


def test_upload_intent_precedes_transfer_and_renewal_fences_stale_cleanup_claim(test_db_session: Session) -> None:
    source = 's3://default/uploads/in-progress.csv'
    upload_id = str(uuid4())
    cleanup.register_upload_source(test_db_session, upload_id=upload_id, source_path=source)
    event = test_db_session.get(RuntimeOutboxEvent, cleanup._event_id(source))
    assert event is not None
    assert event.payload_json['owner_kind'] == 'upload'
    assert event.payload_json['owner_id'] == upload_id
    assert cleanup.claim_cleanups(test_db_session) == []

    # Simulate a transfer lasting longer than its original expiry. Renewal
    # invalidates any claim already taken by a lagging cleanup dispatcher.
    event.available_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.commit()
    stale_claim = _claim(test_db_session, source)
    cleanup.renew_upload_source(test_db_session, upload_id=upload_id, source_path=source)
    assert not _authorize(test_db_session, stale_claim)
    assert cleanup.claim_cleanups(test_db_session) == []

    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
            {'name': 'Transferred', 'file_path': source, 'file_type': 'csv'},
        ),
    )
    event = test_db_session.get(RuntimeOutboxEvent, cleanup._event_id(source))
    assert event is not None
    assert event.payload_json['owner_kind'] == 'source'
    assert event.payload_json['owner_id'] == request.id
    assert event.available_at <= datetime.now(UTC)


def test_upload_intent_transfers_to_preflight_owner(test_db_session: Session) -> None:
    source = 's3://default/uploads/preflight-upload.xlsx'
    upload_id = str(uuid4())
    preflight_id = str(uuid4())
    cleanup.register_upload_source(test_db_session, upload_id=upload_id, source_path=source)
    cleanup.register_preflight_source(test_db_session, preflight_id=preflight_id, resource_id=preflight_id, source_path=source)
    event = test_db_session.get(RuntimeOutboxEvent, cleanup._event_id(source))
    assert event is not None
    assert event.payload_json['owner_kind'] == 'preflight'
    assert event.payload_json['owner_id'] == preflight_id
    assert event.payload_json['resource_id'] == preflight_id


def test_settled_abandoned_upload_releases_only_a_fresh_cleanup_claim(test_db_session: Session) -> None:
    source = 's3://default/uploads/settled-abandoned.csv'
    upload_id = str(uuid4())
    cleanup.register_upload_source(test_db_session, upload_id=upload_id, source_path=source)
    event = test_db_session.get(RuntimeOutboxEvent, cleanup._event_id(source))
    assert event is not None
    event.available_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.commit()

    stale_claim = _claim(test_db_session, source)
    cleanup.renew_upload_source(test_db_session, upload_id=upload_id, source_path=source)
    assert not _authorize(test_db_session, stale_claim)
    assert cleanup.claim_cleanups(test_db_session) == []

    # The route calls this only after the blocking object-store transfer has
    # settled; now cleanup can safely take ownership of the exact target.
    cleanup.release_upload_source_for_cleanup(test_db_session, upload_id=upload_id, source_path=source)
    current_claim = _claim(test_db_session, source)
    assert current_claim.lease_generation > stale_claim.lease_generation
    assert not _authorize(test_db_session, stale_claim)
    assert _authorize(test_db_session, current_claim)


def test_datasource_delete_rearms_published_intent_with_exact_owner(test_db_session: Session) -> None:
    datasource_id = str(uuid4())
    metadata_path = f's3://default/exports/{datasource_id}/master/revision_1'
    datasource = DataSource(
        id=datasource_id,
        name='Published target',
        source_type='iceberg',
        config={
            'metadata_path': metadata_path,
            'catalog_type': 'sql',
            'catalog_uri': 'postgresql://catalog.test/dataforge',
            'warehouse': 's3://default/exports',
            'namespace': 'outputs',
            'table': f'{datasource_id}_master_rev1',
        },
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()
    cleanup.enqueue_datasource_cleanup(test_db_session, datasource)
    test_db_session.commit()
    claim = _claim(test_db_session, metadata_path)
    assert claim.payload['catalog_identifier'] == f'outputs.{datasource_id}_master_rev1'
    assert _authorize(test_db_session, claim) is False

    # Publishing settles the intent; deletion must re-arm the same URL-keyed
    # record so the worker can clean it only after the row is gone.
    cleanup.settle_publication(test_db_session, datasource.config)
    test_db_session.commit()
    loaded_datasource = test_db_session.get(DataSource, datasource_id)
    assert loaded_datasource is not None
    cleanup.enqueue_datasource_cleanup(test_db_session, loaded_datasource)
    test_db_session.delete(loaded_datasource)
    test_db_session.commit()

    deletion_claim = _claim(test_db_session, metadata_path)
    assert deletion_claim.payload['owner_kind'] == 'datasource'
    assert deletion_claim.payload['resource_id'] == datasource_id
    assert _authorize(test_db_session, deletion_claim)


def test_catalog_intent_lookup_uses_indexed_identity_and_matches_table_family(test_db_session: Session) -> None:
    datasource_id = str(uuid4())
    unrelated_id = str(uuid4())

    def catalog_datasource(resource_id: str, table: str) -> DataSource:
        return DataSource(
            id=resource_id,
            name=resource_id,
            source_type='iceberg',
            config={
                'metadata_path': f's3://default/exports/{resource_id}/master/revision_1',
                'catalog_type': 'sql',
                'catalog_uri': 'postgresql://catalog.test/dataforge',
                'warehouse': 's3://default/exports',
                'namespace': 'outputs',
                'table': table,
            },
            created_at=datetime.now(UTC),
        )

    datasource = catalog_datasource(datasource_id, f'{datasource_id}_main_rev1')
    unrelated = catalog_datasource(unrelated_id, f'{unrelated_id}_main_rev1')
    cleanup.enqueue_datasource_cleanup(test_db_session, datasource)
    cleanup.enqueue_datasource_cleanup(test_db_session, unrelated)
    test_db_session.commit()

    sql_statements: list[str] = []

    def record_catalog_lookup(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        if 'runtime_outbox_events' in statement and statement.lstrip().upper().startswith('SELECT'):
            sql_statements.append(statement)

    bind = test_db_session.get_bind()
    event.listen(bind, 'before_cursor_execute', record_catalog_lookup)
    try:
        cleanup.settle_publication(
            test_db_session,
            {'namespace': 'outputs', 'table': f'{datasource_id}_main_rev2'},
        )
    finally:
        event.remove(bind, 'before_cursor_execute', record_catalog_lookup)
    test_db_session.commit()

    assert sql_statements
    assert 'catalog_namespace' in sql_statements[0]
    assert 'catalog_table' in sql_statements[0]
    assert 'catalog_family_prefix' in sql_statements[0]
    assert 'payload_json' not in sql_statements[0].partition('WHERE')[2]

    events = [item for item in test_db_session.execute(select(RuntimeOutboxEvent)).scalars().all() if item.catalog_namespace == 'outputs']
    own_events = [item for item in events if item.catalog_family_prefix == f'{datasource_id}_']
    unrelated_events = [item for item in events if item.catalog_family_prefix == f'{unrelated_id}_']
    assert len(own_events) == 2
    assert all(item.status == RuntimeOutboxStatus.DISPATCHED for item in own_events)
    assert all(item.payload_json['phase'] == 'published' for item in own_events)
    assert len(unrelated_events) == 2
    assert all(item.status == RuntimeOutboxStatus.PENDING for item in unrelated_events)


def test_datasource_cleanup_waits_for_active_rid_request(test_db_session: Session) -> None:
    datasource_id = str(uuid4())
    datasource = DataSource(
        id=datasource_id,
        name='Active source',
        source_type='file',
        config={'file_path': f's3://default/uploads/{datasource_id}.csv'},
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()
    cleanup.enqueue_datasource_cleanup(test_db_session, datasource)
    test_db_session.delete(datasource)
    test_db_session.commit()
    compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=_preview_command_for_resource(datasource_id),
    )

    claim = _claim(test_db_session, f's3://default/uploads/{datasource_id}.csv')
    assert _authorize(test_db_session, claim) is False


def test_storage_cleanup_authorization_waits_for_active_build_datasource_reference(test_db_session: Session) -> None:
    datasource_id = str(uuid4())
    source = f's3://default/uploads/{datasource_id}.csv'
    datasource = DataSource(
        id=datasource_id,
        name='Build source',
        source_type='file',
        config={'file_path': source, 'file_type': 'csv'},
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()
    cleanup.enqueue_datasource_cleanup(test_db_session, datasource)

    build = build_runs_service.create_build_run(
        test_db_session,
        build_id=str(uuid4()),
        namespace='default',
        analysis_id='build-analysis',
        analysis_name='Active build source reader',
        request_json={},
        starter_json={},
        status=BuildRunStatus.QUEUED,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(BuildRunDatasource(build_id=build.id, namespace='default', datasource_id=datasource_id))
    test_db_session.delete(datasource)
    test_db_session.commit()

    claim = _claim(test_db_session, source)
    assert not _authorize(test_db_session, claim)

    build.status = BuildRunStatus.COMPLETED
    test_db_session.add(build)
    test_db_session.commit()
    assert _authorize(test_db_session, claim)


def test_expiry_alone_cannot_authorize_an_active_writer(test_db_session: Session) -> None:
    request, prefix, _artifact = _stage(test_db_session)
    request.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.commit()
    claim = _claim(test_db_session, prefix)
    assert not _authorize(test_db_session, claim)
    _settle_writer(test_db_session, request)
    assert _authorize(test_db_session, claim)


def test_io_failures_remain_retryable_past_the_notification_poison_limit(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    request, prefix, _artifact = _stage(test_db_session)
    _settle_writer(test_db_session, request)
    claim = _claim(test_db_session, prefix)
    assert _authorize(test_db_session, claim)
    monkeypatch.setattr(settings, 'runtime_outbox_max_attempts', 1)
    assert _complete(test_db_session, claim, error='Storage unavailable')
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None
    assert event.status == RuntimeOutboxStatus.FAILED
    assert event.payload_json['url'] == prefix
    assert event.payload_json['catalog_identifier'] == f'clean.{prefix.split("/")[-2]}'
    event.available_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.commit()
    retry = _claim(test_db_session, prefix)
    assert retry.lease_generation == claim.lease_generation + 1
    assert _authorize(test_db_session, retry)
    assert _complete(test_db_session, retry)
    test_db_session.refresh(event)
    assert event.status == RuntimeOutboxStatus.DISPATCHED
    assert event.payload_json['phase'] == cleanup.StorageCleanupPhase.DELETED


def test_publication_settles_claim_atomically_even_when_reply_is_lost(test_db_session: Session) -> None:
    request, prefix, _artifact = _stage(test_db_session)
    claim = _claim(test_db_session, prefix)
    publication_service.create_datasource(
        test_db_session,
        datasource_id=request.id,
        name='Published',
        description=None,
        source_type='iceberg',
        config={'metadata_path': prefix, 'namespace': 'clean', 'table': prefix.split('/')[-2]},
        owner_id=None,
    )
    assert not _authorize(test_db_session, claim)
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None and event.status == RuntimeOutboxStatus.DISPATCHED
    assert event.payload_json['phase'] == cleanup.StorageCleanupPhase.PUBLISHED
    assert test_db_session.get(DataSource, request.id) is not None


def test_publish_ingest_settles_the_claim_prefix_recorded_in_config(test_db_session: Session) -> None:
    """Ingest snapshots reference the staged claim prefix; the published config
    carries ingest.claim_prefix so the prefix is retained with table history.
    """
    request, staged_prefix, _artifact = _stage(test_db_session)
    claim = _claim(test_db_session, staged_prefix)
    stable_table = request.id
    stable_metadata = f's3://default/clean/{stable_table}/master'
    test_db_session.add(
        DataSource(
            id=stable_table,
            name='Ingested',
            source_type='iceberg',
            config={'metadata_path': 's3://default/clean/old/master', 'namespace': 'clean', 'table': 'old_claim_table'},
            revision=1,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    publication_service.publish_ingest(
        test_db_session,
        datasource_id=request.id,
        config={
            'metadata_path': stable_metadata,
            'namespace': 'clean',
            'table': stable_table,
            'branch': 'master',
            'source': {'source_type': 'file', 'file_path': 's3://default/uploads/source.csv'},
            'ingest': {'ingested_at': '2026-10-06T12:00:00', 'claim_prefix': staged_prefix},
        },
        expected_revision=1,
        schema_info=None,
    )
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None and event.payload_json['phase'] == cleanup.StorageCleanupPhase.PUBLISHED
    # The claim prefix is part of table history: even with the writer settled
    # and no config reference, a PUBLISHED intent can never be authorized.
    _settle_writer(test_db_session, request)
    assert not _authorize(test_db_session, claim)


def test_catalog_cleanup_identity_treats_the_stable_table_as_its_family(test_db_session: Session) -> None:
    datasource_id = str(uuid4())
    stable = cleanup._catalog_cleanup_identity(
        {'namespace': 'clean', 'table': datasource_id, 'catalog_type': 'sql', 'warehouse': 's3://default/clean'},
        datasource_id=datasource_id,
    )
    assert stable['catalog_family_prefix'] == f'{datasource_id}_'
    claim = cleanup._catalog_cleanup_identity(
        {'namespace': 'clean', 'table': f'{datasource_id}__claim_token', 'catalog_type': 'sql', 'warehouse': 's3://default/clean'},
        datasource_id=datasource_id,
    )
    assert claim['catalog_family_prefix'] == f'{datasource_id}_'


def test_postgres_authorization_waits_for_the_publication_request_lock(test_db_session: Session, test_engine: Engine) -> None:
    assert test_engine.dialect.name == 'postgresql'
    request, prefix, _artifact = _stage(test_db_session)
    claim = _claim(test_db_session, prefix)
    publication_service.create_datasource(
        test_db_session,
        datasource_id=request.id,
        name='Before publication',
        description=None,
        source_type='iceberg',
        config={'metadata_path': 's3://default/clean/previous/master'},
        owner_id=None,
    )
    started = threading.Event()
    cleanup_pid: list[int] = []

    def authorize_in_new_session() -> bool:
        with Session(test_engine) as session:
            cleanup_pid.append(int(session.execute(text('SELECT pg_backend_pid()')).scalar_one()))
            started.set()
            return _authorize(session, claim)

    with Session(test_engine) as publisher, ThreadPoolExecutor(max_workers=1) as pool:
        publisher_pid = int(publisher.execute(text('SELECT pg_backend_pid()')).scalar_one())
        owner = publisher.get(ComputeRequest, request.id, with_for_update=True)
        assert owner is not None
        result = pool.submit(authorize_in_new_session)
        try:
            assert started.wait(timeout=5)

            def cleanup_is_blocked() -> bool:
                with test_engine.connect() as observer:
                    blockers = observer.execute(text('SELECT pg_blocking_pids(:pid)'), {'pid': cleanup_pid[0]}).scalar_one()
                return publisher_pid in blockers

            wait_for_condition(cleanup_is_blocked, timeout=5, interval=0.01, description='cleanup authorization to wait for the publisher request lock')

            def publication_guard(session: Session) -> None:
                assert (
                    compute_requests_service.lock_active_request_claim(
                        session, request.id, worker_id='writer', claim_token=str(request.claim_token), lease_generation=1
                    )
                    is not None
                )

            publication_service.publish_ingest(
                publisher,
                datasource_id=request.id,
                config={'metadata_path': prefix, 'namespace': 'clean', 'table': prefix.split('/')[-2]},
                expected_revision=1,
                schema_info=None,
                publication_guard=publication_guard,
            )
            assert result.result(timeout=5) is False
        finally:
            publisher.rollback()
    test_db_session.expire_all()
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None and event.payload_json['phase'] == cleanup.StorageCleanupPhase.PUBLISHED
    published = test_db_session.get(DataSource, request.id)
    assert published is not None and published.config['metadata_path'] == prefix


def test_postgres_authorization_rejects_lease_expired_during_owner_lock_wait(test_db_session: Session, test_engine: Engine) -> None:
    assert test_engine.dialect.name == 'postgresql'
    request = _preflight(test_db_session)
    source = request.artifact_path
    assert source is not None
    event = test_db_session.get(RuntimeOutboxEvent, cleanup._event_id(source))
    assert event is not None
    event.available_at = runtime_outbox_service._database_now(test_db_session)
    test_db_session.commit()
    claim = _claim(test_db_session, source)

    started = threading.Event()
    cleanup_pid: list[int] = []

    def authorize_in_new_session() -> bool:
        token = set_namespace_context('default')
        try:
            with Session(test_engine) as session:
                cleanup_pid.append(int(session.execute(text('SELECT pg_backend_pid()')).scalar_one()))
                started.set()
                return _authorize(session, claim)
        finally:
            reset_namespace(token)

    with Session(test_engine) as owner_lock, ThreadPoolExecutor(max_workers=1) as pool:
        owner_pid = int(owner_lock.execute(text('SELECT pg_backend_pid()')).scalar_one())
        assert owner_lock.get(ComputeRequest, request.id, with_for_update=True) is not None
        result = pool.submit(authorize_in_new_session)
        try:
            assert started.wait(timeout=5)

            def authorization_waits_for_owner() -> bool:
                with test_engine.connect() as observer:
                    blockers = observer.execute(text('SELECT pg_blocking_pids(:pid)'), {'pid': cleanup_pid[0]}).scalar_one()
                return owner_pid in blockers

            wait_for_condition(authorization_waits_for_owner, timeout=5, interval=0.01, description='cleanup authorization to wait for the owner row')
            with Session(test_engine) as lease_update:
                lease_update.execute(
                    text("UPDATE runtime_outbox_events SET lease_expires_at = statement_timestamp() + interval '300 milliseconds' WHERE id = :event_id"),
                    {'event_id': claim.event_id},
                )
                lease_update.commit()

            def claim_expired() -> bool:
                with test_engine.connect() as observer:
                    return bool(
                        observer.execute(
                            text('SELECT lease_expires_at <= statement_timestamp() FROM runtime_outbox_events WHERE id = :event_id'),
                            {'event_id': claim.event_id},
                        ).scalar_one()
                    )

            wait_for_condition(claim_expired, timeout=5, interval=0.01, description='cleanup lease to expire while authorization waits')
            owner_lock.rollback()
            assert result.result(timeout=5) is False
        finally:
            owner_lock.rollback()


def test_cleanup_completion_after_grant_uses_claim_token_and_generation(test_db_session: Session) -> None:
    request, prefix, _artifact = _stage(test_db_session)
    _settle_writer(test_db_session, request)
    claim = _claim(test_db_session, prefix)
    assert _authorize(test_db_session, claim)
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None
    event.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.commit()

    assert _complete(test_db_session, claim)
    test_db_session.refresh(event)
    assert event.status == RuntimeOutboxStatus.DISPATCHED
    assert event.payload_json['phase'] == cleanup.StorageCleanupPhase.DELETED


@pytest.mark.parametrize('lock_target', ['owner', 'outbox'])
def test_postgres_authorization_rejects_claim_expired_while_blocked(test_db_session: Session, test_engine: Engine, lock_target: str) -> None:
    assert test_engine.dialect.name == 'postgresql'
    request, prefix, _artifact = _stage(test_db_session)
    _settle_writer(test_db_session, request)
    claim = _claim(test_db_session, prefix)
    started = threading.Event()
    caller_pid: list[int] = []
    transaction_start: list[datetime] = []

    def authorize_in_new_session() -> bool:
        with Session(test_engine) as session:
            pid, timestamp = session.execute(text('SELECT pg_backend_pid(), CURRENT_TIMESTAMP')).one()
            caller_pid.append(int(pid))
            transaction_start.append(timestamp)
            started.set()
            return _authorize(session, claim)

    with Session(test_engine) as locker, ThreadPoolExecutor(max_workers=1) as pool:
        locker_pid = int(locker.execute(text('SELECT pg_backend_pid()')).scalar_one())
        if lock_target == 'owner':
            assert locker.get(ComputeRequest, request.id, with_for_update=True) is not None
        else:
            assert locker.get(RuntimeOutboxEvent, claim.event_id, with_for_update=True) is not None
        result = pool.submit(authorize_in_new_session)
        try:
            assert started.wait(timeout=5)

            def caller_is_blocked() -> bool:
                with test_engine.connect() as observer:
                    blockers = observer.execute(text('SELECT pg_blocking_pids(:pid)'), {'pid': caller_pid[0]}).scalar_one()
                return locker_pid in blockers

            wait_for_condition(caller_is_blocked, timeout=5, interval=0.01, description='cleanup authorization to wait on the held row lock')
            deadline = locker.execute(
                text(
                    "UPDATE runtime_outbox_events SET lease_expires_at = clock_timestamp() + interval '250 milliseconds' "
                    'WHERE id = :id RETURNING lease_expires_at'
                ),
                {'id': claim.event_id},
            ).scalar_one()
            assert transaction_start[0] < deadline

            def lease_has_expired() -> bool:
                with test_engine.connect() as observer:
                    return bool(observer.execute(text('SELECT clock_timestamp() >= :deadline'), {'deadline': deadline}).scalar_one())

            wait_for_condition(lease_has_expired, timeout=5, interval=0.01, description='cleanup lease to expire before releasing the row lock')
            locker.commit()
            assert result.result(timeout=5) is False
        finally:
            locker.rollback()
    test_db_session.expire_all()
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None and event.status == RuntimeOutboxStatus.DISPATCHING
    assert event.payload_json['phase'] == cleanup.StorageCleanupPhase.TRACKED


def test_lost_cleanup_ack_reclaims_and_rejects_the_stale_finalizer(test_db_session: Session) -> None:
    request, prefix, _artifact = _stage(test_db_session)
    _settle_writer(test_db_session, request)
    claim = _claim(test_db_session, prefix)
    assert _authorize(test_db_session, claim)
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None
    event.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.commit()
    retry = _claim(test_db_session, prefix)
    assert not _complete(test_db_session, claim)
    assert _authorize(test_db_session, retry)
    assert _complete(test_db_session, retry)


def _preflight(session: Session, *, source: str = 's3://default/uploads/preflight.xlsx') -> ComputeRequest:
    request = compute_requests_service.create_request(
        session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT,
        command=command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT,
            {'preflight_id': str(uuid4()), 'source_path': source, 'action': enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL, 'delete_source': True},
        ),
    )
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    session.commit()
    return request


def test_preflight_retirement_keeps_the_source_in_a_durable_retry_intent(test_db_session: Session) -> None:
    request = _preflight(test_db_session)
    source = request.artifact_path
    assert source is not None
    assert preflight._remove_preflight(test_db_session, request.id, delete_source=True) == source
    assert test_db_session.get(ComputeRequest, request.id) is None
    claim = _claim(test_db_session, source)
    assert _authorize(test_db_session, claim)
    assert _complete(test_db_session, claim, error='Object store disconnected')
    event = test_db_session.get(RuntimeOutboxEvent, claim.event_id)
    assert event is not None and event.payload_json['url'] == source
    assert event.status == RuntimeOutboxStatus.FAILED


def test_ownership_transfer_revokes_a_cleanup_claim_joined_on_the_old_rid(test_db_session: Session) -> None:
    request = _preflight(test_db_session)
    source = request.artifact_path
    assert source is not None
    assert request.compute_worker_resource_id is not None
    cleanup.register_preflight_source(test_db_session, preflight_id=request.id, resource_id=request.compute_worker_resource_id, source_path=source)
    test_db_session.commit()
    old_claim = _claim(test_db_session, source)
    consumer = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, {'name': 'Confirmed', 'file_path': source, 'file_type': 'excel'}),
    )
    assert consumer.artifact_path == source
    cleanup.transfer_preflight_source(test_db_session, source_path=source, request_id=consumer.id)
    request.artifact_path = None
    test_db_session.commit()
    _settle_writer(test_db_session, consumer)
    assert not _authorize(test_db_session, old_claim)
    retry = _claim(test_db_session, source)
    assert retry.payload['resource_id'] == consumer.id
    assert retry.lease_generation > old_claim.lease_generation
    assert _authorize(test_db_session, retry)


def test_transfer_after_authorization_is_rejected(test_db_session: Session) -> None:
    request = _preflight(test_db_session)
    source = request.artifact_path
    assert source is not None
    preflight._remove_preflight(test_db_session, request.id, delete_source=True)
    claim = _claim(test_db_session, source)
    assert _authorize(test_db_session, claim)
    with pytest.raises(cleanup.StorageCleanupConflict, match='already authorized'):
        cleanup.transfer_preflight_source(test_db_session, source_path=source, request_id='late-consumer')
    test_db_session.rollback()


def test_exact_queued_source_reference_defers_cleanup_without_scanning_command_bytes(test_db_session: Session) -> None:
    request = _preflight(test_db_session)
    source = request.artifact_path
    assert source is not None
    consumer = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, {'name': 'Pending', 'file_path': source, 'file_type': 'excel'}),
    )
    assert consumer.artifact_path == source
    assert preflight._remove_preflight(test_db_session, request.id, delete_source=True) is None
    claim = _claim(test_db_session, source)
    assert not _authorize(test_db_session, claim)
    _settle_writer(test_db_session, consumer)
    assert _authorize(test_db_session, claim)


def test_retired_source_cannot_acquire_a_new_queued_reader(test_db_session: Session) -> None:
    request = _preflight(test_db_session)
    source = request.artifact_path
    assert source is not None
    preflight._remove_preflight(test_db_session, request.id, delete_source=True)
    with pytest.raises(cleanup.StorageCleanupConflict, match='retired'):
        compute_requests_service.create_request(
            test_db_session,
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
            command=command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, {'name': 'Late', 'file_path': source, 'file_type': 'excel'}),
        )
    test_db_session.rollback()


def test_only_one_consumer_can_take_an_owned_preflight_source(test_db_session: Session) -> None:
    request = _preflight(test_db_session)
    source = request.artifact_path
    assert source is not None
    create = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, {'name': 'First', 'file_path': source, 'file_type': 'excel'})
    first = compute_requests_service.create_request(
        test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, command=create
    )
    cleanup.transfer_preflight_source(test_db_session, source_path=source, request_id=first.id)
    with pytest.raises(cleanup.StorageCleanupConflict, match='already transferred'):
        compute_requests_service.create_request(
            test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, command=create
        )
    test_db_session.rollback()


def test_preflight_future_deadline_survives_clearing_the_pending_marker(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = test_db_session.get_bind()
    assert engine.dialect.name == 'postgresql'
    # Run the same public + tenant migration path as API startup before this
    # test reads the shared public wake table. Creating that table directly
    # would leave Alembic without its public version row, so a later TestClient
    # startup would try to create it again from the initial migration.
    asyncio.run(init_db())
    namespace = f'cleanup-{uuid4().hex}'
    token = set_namespace_context(namespace)
    monkeypatch.setattr(settings, 'distributed_runtime_enabled', True)
    try:
        due_at = datetime.now(UTC) + cleanup.PREFLIGHT_TTL
        preflight_id = str(uuid4())
        cleanup.register_preflight_source(
            test_db_session,
            preflight_id=preflight_id,
            resource_id=preflight_id,
            source_path=f's3://{namespace}/uploads/future.xlsx',
            available_at=due_at,
        )
        test_db_session.commit()
        assert cleanup.claim_cleanups(test_db_session) == []
        row = test_db_session.execute(
            text("SELECT pending, due_at FROM public.runtime_namespace_work WHERE namespace = :namespace AND kind = 'storage_cleanup'"),
            {'namespace': namespace},
        ).one()
        assert row.pending is False
        assert row.due_at == due_at
        event = test_db_session.execute(select(RuntimeOutboxEvent).where(col(RuntimeOutboxEvent.kind) == 'storage_cleanup')).scalar_one()
        event.available_at = datetime.now(UTC) - timedelta(seconds=1)
        test_db_session.commit()
        assert len(cleanup.claim_cleanups(test_db_session)) == 1
    finally:
        test_db_session.rollback()
        test_db_session.execute(text('DELETE FROM public.runtime_namespace_work WHERE namespace = :namespace'), {'namespace': namespace})
        test_db_session.commit()
        reset_namespace(token)
