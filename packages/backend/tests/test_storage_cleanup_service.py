from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, select, text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend_core import compute_requests_service, runtime_outbox_service, storage_cleanup_service as cleanup
from backend_core.config import settings
from backend_core.domain.compute_requests.models import command_from_payload
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeNamespaceWork, RuntimeOutboxEvent, RuntimeOutboxStatus
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
    artifact = f's3://default/runtime-staging/datasource-stage/{request.id}/1/data.arrow'
    cleanup.register_stage(
        session,
        datasource_id=request.id,
        owner_kind='compute',
        owner_id=request.id,
        worker_id='writer',
        claim_token=request.claim_token,
        lease_generation=1,
        prefix_url=prefix,
        artifact_url=artifact,
        catalog_identifier=f'clean.{table}',
    )
    return request, prefix, artifact


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
    _request, prefix, artifact = _stage(test_db_session)
    assert runtime_outbox_service.dispatch_pending_events(test_db_session) == 0
    claims = cleanup.claim_cleanups(test_db_session, limit=16)
    assert {claim.payload['url'] for claim in claims} == {prefix, artifact}
    prefix_claim = next(claim for claim in claims if claim.payload['url'] == prefix)
    assert prefix_claim.payload['catalog_identifier'] == f'clean.{prefix.split("/")[-2]}'
    assert all(claim.lease_generation == 1 for claim in claims)


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
    assert request.engine_resource_id is not None
    cleanup.register_preflight_source(test_db_session, preflight_id=request.id, resource_id=request.engine_resource_id, source_path=source)
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
    namespace = f'cleanup-{uuid4().hex}'
    token = set_namespace_context(namespace)
    for table_name in ('runtime_namespace_work', 'runtime_namespace_work_wakes'):
        RuntimeNamespaceWork.metadata.tables[table_name].to_metadata(MetaData(), schema='public').create(engine, checkfirst=True)
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
        test_db_session.execute(text('DELETE FROM public.runtime_namespace_work_wakes WHERE namespace = :namespace'), {'namespace': namespace})
        test_db_session.commit()
        reset_namespace(token)
