from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlparse

from sqlalchemy import or_, select, text
from sqlmodel import Session

from backend_core import runtime_outbox_service, runtime_work_service
from backend_core.namespace import get_namespace
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from backend_core.runtime_outbox_service import STORAGE_CLEANUP_KIND, OutboxClaim
from backend_core.runtime_work_service import RuntimeWorkKind
from backend_core.sqlmodel_typing import col, sa
from dataforge_protocol import enums_pb2

STORAGE_CLEANUP_WAKE_KIND = 'storage_cleanup_wakeup'
PREFLIGHT_TTL = timedelta(minutes=30)
_ACTIVE_REQUEST_STATUSES = (enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED, enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)


class StorageCleanupPhase(StrEnum):
    TRACKED = 'tracked'
    PUBLISHED = 'published'
    AUTHORIZED = 'authorized'
    DELETED = 'deleted'


class StorageCleanupConflict(RuntimeError):
    """An object already authorized for deletion cannot acquire a new reference."""


def _event_id(url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'dataforge-storage-cleanup:{get_namespace()}:{url}'))


def _wake(session: Session) -> None:
    namespace = get_namespace()
    runtime_work_service.append_wake(session, namespace=namespace, kind=RuntimeWorkKind.STORAGE_CLEANUP)
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(
            text('SELECT pg_notify(:channel, :payload)'),
            {'channel': 'runtime_events', 'payload': json.dumps({'kind': STORAGE_CLEANUP_WAKE_KIND, 'namespace': namespace})},
        )


def _enqueue(session: Session, *, url: str, payload: dict[str, object], available_at: datetime | None = None) -> RuntimeOutboxEvent:
    parsed = urlparse(url)
    if parsed.scheme != 's3' or parsed.netloc != get_namespace() or parsed.path.split('/')[1] not in {'uploads', 'clean', 'runtime-staging'}:
        raise ValueError('Storage cleanup must target an exact managed namespace object or prefix')
    event = session.get(RuntimeOutboxEvent, _event_id(url), with_for_update=True, populate_existing=True)
    now = runtime_outbox_service._database_now(session)
    if event is not None:
        if event.kind != STORAGE_CLEANUP_KIND or event.payload_json.get('url') != url:
            raise ValueError('Storage cleanup identity is already in use')
        if available_at is None and event.status in {RuntimeOutboxStatus.PENDING, RuntimeOutboxStatus.FAILED}:
            event.available_at = now
            _wake(session)
        return event
    event = RuntimeOutboxEvent(
        id=_event_id(url),
        kind=STORAGE_CLEANUP_KIND,
        status=RuntimeOutboxStatus.PENDING,
        payload_json={**payload, 'url': url, 'phase': StorageCleanupPhase.TRACKED.value},
        available_at=available_at or now,
        created_at=now,
        updated_at=now,
    )
    session.add(event)
    session.flush()
    _wake(session)
    return event


def register_preflight_source(session: Session, *, preflight_id: str, resource_id: str, source_path: str, available_at: datetime | None = None) -> None:
    _enqueue(
        session,
        url=source_path,
        payload={'resource_id': resource_id, 'owner_kind': 'preflight', 'owner_id': preflight_id, 'is_prefix': False},
        available_at=available_at,
    )


def register_stage(
    session: Session,
    *,
    datasource_id: str,
    owner_kind: str,
    owner_id: str,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    prefix_url: str,
    artifact_url: str,
    catalog_identifier: str,
    build_id: str | None = None,
) -> None:
    from backend_core import build_jobs_service, compute_requests_service

    owner: ComputeRequest | BuildJob | None
    if owner_kind == 'compute':
        owner = compute_requests_service.lock_active_request_claim(
            session, owner_id, worker_id=worker_id, claim_token=claim_token, lease_generation=lease_generation
        )
    elif owner_kind == 'build' and build_id is not None:
        owner = build_jobs_service.lock_active_job_claim(
            session, owner_id, build_id=build_id, worker_id=worker_id, claim_token=claim_token, lease_generation=lease_generation
        )
    else:
        raise ValueError('Datasource staging requires one complete compute or build claim')
    if owner is None:
        raise StorageCleanupConflict('Datasource staging claim is no longer active')
    if isinstance(owner, ComputeRequest) and owner.engine_resource_id != datasource_id:
        raise StorageCleanupConflict('Datasource staging claim targets a different exact RID')
    staging_id = f'{datasource_id}__claim_{claim_token.replace("-", "_")}'
    expected_prefix = f's3://{get_namespace()}/clean/{staging_id}/'
    expected_artifact = (
        f's3://{get_namespace()}/runtime-staging/datasource-stage/{owner_id}/{lease_generation}/data.arrow'
        if owner_kind == 'compute'
        else f's3://{get_namespace()}/runtime-staging/schedule-ingest/{owner_id}/{lease_generation}/data.arrow'
    )
    expected_catalog_identifier = f'clean.{prefix_url.rstrip("/").split("/")[-2]}'
    if not prefix_url.startswith(expected_prefix) or artifact_url != expected_artifact or catalog_identifier != expected_catalog_identifier:
        raise ValueError('Datasource staging targets do not match the claimed attempt')
    payload: dict[str, object] = {
        'resource_id': datasource_id,
        'owner_kind': owner_kind,
        'owner_id': owner_id,
        'owner_token': claim_token,
        'owner_generation': lease_generation,
        'worker_id': worker_id,
    }
    _enqueue(session, url=prefix_url, payload={**payload, 'is_prefix': True, 'catalog_identifier': catalog_identifier})
    _enqueue(session, url=artifact_url, payload={**payload, 'is_prefix': False})
    session.commit()


def _settle_referenced(session: Session, event: RuntimeOutboxEvent) -> None:
    if StorageCleanupPhase(str(event.payload_json['phase'])) not in {StorageCleanupPhase.TRACKED, StorageCleanupPhase.PUBLISHED}:
        raise StorageCleanupConflict('Storage cleanup was already authorized for this path')
    now = runtime_outbox_service._database_now(session)
    event.payload_json = {**event.payload_json, 'phase': StorageCleanupPhase.PUBLISHED.value}
    event.status = RuntimeOutboxStatus.DISPATCHED
    event.claim_token = None
    event.lease_expires_at = None
    event.dispatched_at = now
    event.updated_at = now
    session.add(event)


def settle_publication(session: Session, config: Mapping[str, object]) -> None:
    source = config.get('source')
    paths = [config.get('metadata_path'), config.get('file_path')]
    if isinstance(source, dict):
        paths.extend((source.get('file_path'), source.get('metadata_path')))
    for path in sorted({path for path in paths if isinstance(path, str)}):
        event = session.get(RuntimeOutboxEvent, _event_id(path), with_for_update=True, populate_existing=True)
        if event is not None and event.kind == STORAGE_CLEANUP_KIND:
            _settle_referenced(session, event)


def _lock_source_intent(session: Session, source_path: str) -> tuple[RuntimeOutboxEvent | None, ComputeRequest | BuildJob | None]:
    snapshot = session.get(RuntimeOutboxEvent, _event_id(source_path), populate_existing=True)
    if snapshot is None:
        return None, None
    payload = dict(snapshot.payload_json)
    owner: ComputeRequest | BuildJob | None
    if payload['owner_kind'] == 'build':
        owner = session.get(BuildJob, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    else:
        owner = session.get(ComputeRequest, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    event = session.get(RuntimeOutboxEvent, snapshot.id, with_for_update=True, populate_existing=True)
    assert event is not None
    if event.payload_json != payload:
        raise StorageCleanupConflict('Source ownership changed while enqueueing')
    phase = StorageCleanupPhase(str(event.payload_json['phase']))
    if phase not in {StorageCleanupPhase.TRACKED, StorageCleanupPhase.PUBLISHED}:
        raise StorageCleanupConflict('Source cleanup was already authorized')
    if phase == StorageCleanupPhase.TRACKED and owner is None:
        raise StorageCleanupConflict('Source ownership has been retired')
    return event, owner


def validate_source_enqueue(session: Session, *, source_path: str) -> None:
    _lock_source_intent(session, source_path)


def transfer_preflight_source(session: Session, *, source_path: str, request_id: str) -> None:
    event, owner = _lock_source_intent(session, source_path)
    if event is None or StorageCleanupPhase(str(event.payload_json['phase'])) == StorageCleanupPhase.PUBLISHED:
        return
    if event.payload_json['owner_kind'] == 'source' and event.payload_json['owner_id'] == request_id:
        return
    if event.payload_json['owner_kind'] != 'preflight':
        raise StorageCleanupConflict('Source ownership has already transferred to another consumer')
    if not isinstance(owner, ComputeRequest) or owner.status != enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED:
        raise StorageCleanupConflict('Preflight source has not completed')
    owner.artifact_path = None
    owner.artifact_name = None
    owner.artifact_content_type = None
    session.add(owner)
    event.payload_json = {**event.payload_json, 'owner_kind': 'source', 'owner_id': request_id, 'resource_id': request_id}
    event.lease_generation += 1
    event.claim_token = None
    event.lease_expires_at = None
    event.status = RuntimeOutboxStatus.PENDING
    event.available_at = runtime_outbox_service._database_now(session)
    session.add(event)
    _wake(session)


def _refresh(session: Session) -> None:
    runtime_work_service.refresh_pending_work(
        session,
        namespace=get_namespace(),
        kind=RuntimeWorkKind.STORAGE_CLEANUP,
        pending_query="""
            SELECT 1 FROM runtime_outbox_events
            WHERE kind = 'storage_cleanup' AND available_at <= statement_timestamp()
              AND (status IN ('pending', 'failed') OR (status = 'dispatching' AND lease_expires_at <= statement_timestamp()))
        """,
        due_query="""
            SELECT min(CASE WHEN status = 'dispatching' THEN greatest(available_at, lease_expires_at) ELSE available_at END)
            FROM runtime_outbox_events WHERE kind = 'storage_cleanup' AND status IN ('pending', 'failed', 'dispatching')
        """,
    )
    session.commit()


def claim_cleanups(session: Session, *, limit: int = 1) -> list[OutboxClaim]:
    claims = runtime_outbox_service.claim_storage_cleanups(session, limit=limit)
    _refresh(session)
    return claims


def _has_reference(session: Session, *, url: str, is_prefix: bool, catalog_identifier: str | None = None) -> bool:
    paths = [
        DataSource.config['metadata_path'].as_string(),
        DataSource.config['file_path'].as_string(),
        DataSource.config['source']['metadata_path'].as_string(),
        DataSource.config['source']['file_path'].as_string(),
    ]
    matches = [path == url for path in paths]
    if is_prefix:
        matches.extend(path.startswith(url.rstrip('/') + '/', autoescape=True) for path in paths)
    if catalog_identifier is not None:
        catalog_namespace, _, table = catalog_identifier.partition('.')
        matches.append((DataSource.config['namespace'].as_string() == catalog_namespace) & (DataSource.config['table'].as_string() == table))
    return session.execute(select(col(DataSource.id)).where(or_(*matches)).limit(1)).first() is not None


def _source_in_use(session: Session, *, url: str, resource_id: str) -> bool:
    statement = (
        select(col(ComputeRequest.id))
        .where(sa(ComputeRequest.namespace == get_namespace()))
        .where(col(ComputeRequest.status).in_(_ACTIVE_REQUEST_STATUSES))
        .where(or_(sa(ComputeRequest.engine_resource_id == resource_id), sa(ComputeRequest.artifact_path == url)))
        .limit(1)
    )
    return session.execute(statement).first() is not None


def authorize_cleanup(session: Session, *, event_id: str, claim_token: str, lease_generation: int) -> bool:
    """The single manager must hold the exact RID job slot and have joined all writers before calling."""
    snapshot = session.get(RuntimeOutboxEvent, event_id, populate_existing=True)
    if snapshot is None or snapshot.kind != STORAGE_CLEANUP_KIND:
        return False
    payload = dict(snapshot.payload_json)
    owner_kind = payload['owner_kind']
    owner: BuildJob | ComputeRequest | None
    if owner_kind == 'build':
        owner = session.get(BuildJob, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    else:
        owner = session.get(ComputeRequest, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    event = session.get(RuntimeOutboxEvent, event_id, with_for_update=True, populate_existing=True)
    now = runtime_outbox_service._database_now(session, wall_clock=True)
    if (
        event is None
        or event.status != RuntimeOutboxStatus.DISPATCHING
        or event.claim_token != claim_token
        or event.lease_generation != lease_generation
        or event.payload_json != payload
        or StorageCleanupPhase(str(event.payload_json['phase'])) not in {StorageCleanupPhase.TRACKED, StorageCleanupPhase.AUTHORIZED}
        or event.lease_expires_at is None
        or (event.lease_expires_at if event.lease_expires_at.tzinfo is not None else event.lease_expires_at.replace(tzinfo=UTC)) <= now
    ):
        return False
    if owner is not None:
        if owner_kind in {'preflight', 'source'} and isinstance(owner, ComputeRequest):
            if owner_kind == 'preflight' and owner.artifact_path != payload['url']:
                _settle_referenced(session, event)
                session.commit()
                return False
            if owner.status in _ACTIVE_REQUEST_STATUSES:
                return False
        elif owner.claim_token == payload['owner_token'] and owner.lease_generation == payload['owner_generation']:
            expiry = owner.lease_expires_at
            if expiry is not None and (expiry if expiry.tzinfo is not None else expiry.replace(tzinfo=UTC)) > now:
                return False
    url = str(payload['url'])
    is_prefix = payload['is_prefix'] is True
    catalog_identifier = payload.get('catalog_identifier')
    referenced = _has_reference(session, url=url, is_prefix=is_prefix, catalog_identifier=catalog_identifier if isinstance(catalog_identifier, str) else None)
    if not referenced and _source_in_use(session, url=url, resource_id=str(payload['resource_id'])):
        return False
    if referenced:
        _settle_referenced(session, event)
        session.commit()
        return False
    expiry = event.lease_expires_at
    assert expiry is not None
    if (expiry if expiry.tzinfo is not None else expiry.replace(tzinfo=UTC)) <= runtime_outbox_service._database_now(session, wall_clock=True):
        return False
    if owner_kind == 'preflight' and owner is not None:
        session.delete(owner)
    event.payload_json = {**event.payload_json, 'phase': StorageCleanupPhase.AUTHORIZED.value}
    session.add(event)
    session.commit()
    return True


def complete_cleanup(session: Session, *, event_id: str, claim_token: str, lease_generation: int, error: str | None) -> bool:
    event = session.get(RuntimeOutboxEvent, event_id, with_for_update=True, populate_existing=True)
    if event is None or event.kind != STORAGE_CLEANUP_KIND:
        return False
    if event.status != RuntimeOutboxStatus.DISPATCHING or event.claim_token != claim_token or event.lease_generation != lease_generation:
        return False
    if error is None and StorageCleanupPhase(str(event.payload_json['phase'])) != StorageCleanupPhase.AUTHORIZED:
        raise ValueError('Storage cleanup must be authorized before completion')
    claim = OutboxClaim(event_id, claim_token, lease_generation, STORAGE_CLEANUP_KIND, dict(event.payload_json))
    if event.claim_token == claim_token and event.lease_generation == lease_generation and error is None:
        event.payload_json = {**event.payload_json, 'phase': StorageCleanupPhase.DELETED.value}
        session.add(event)
    finalized = runtime_outbox_service.finalize_storage_cleanup(session, claim, error=error)
    _refresh(session)
    return finalized
