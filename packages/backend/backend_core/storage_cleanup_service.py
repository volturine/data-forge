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
from backend_core.config import settings
from backend_core.domain.datasource.source_types import DataSourceType
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
    segments = parsed.path.strip('/').split('/')
    if (
        parsed.scheme != 's3'
        or parsed.netloc != get_namespace()
        or not segments
        or segments[0] not in {'uploads', 'clean', 'exports', 'runtime-staging'}
        or any(segment in {'.', '..'} for segment in segments)
    ):
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
        catalog_namespace=payload.get('catalog_namespace') if isinstance(payload.get('catalog_namespace'), str) else None,
        catalog_table=payload.get('catalog_table') if isinstance(payload.get('catalog_table'), str) else None,
        catalog_family_prefix=payload.get('catalog_family_prefix') if isinstance(payload.get('catalog_family_prefix'), str) else None,
        available_at=available_at or now,
        created_at=now,
        updated_at=now,
    )
    session.add(event)
    session.flush()
    _wake(session)
    return event


def _catalog_cleanup_identity(config: Mapping[str, object], *, datasource_id: str) -> dict[str, str]:
    namespace = config.get('namespace')
    table = config.get('table')
    if not isinstance(namespace, str) or not namespace or not isinstance(table, str) or not table:
        return {}

    catalog_type = config.get('catalog_type')
    catalog_uri = config.get('catalog_uri')
    warehouse = config.get('warehouse')
    # Product-managed SQL catalogs historically omit catalog_uri and resolve
    # it to the configured application database. Resolve that choice now so
    # the durable intent never depends on the worker's later environment.
    if catalog_type == 'sql' and not catalog_uri:
        catalog_uri = settings.database_url
    if (
        not isinstance(catalog_type, str)
        or not catalog_type
        or not isinstance(catalog_uri, str)
        or not catalog_uri
        or not isinstance(warehouse, str)
        or not warehouse
    ):
        raise ValueError('Iceberg cleanup requires a complete catalog type, URI, and warehouse')

    identity = {
        'catalog_identifier': f'{namespace}.{table}',
        'catalog_type': catalog_type,
        'catalog_uri': catalog_uri,
        'warehouse': warehouse,
        'catalog_namespace': namespace,
        'catalog_table': table,
    }
    if table == datasource_id or table.startswith(f'{datasource_id}_'):
        # The stable published table (<datasource_id>) and every claim-scoped
        # revision of it (<datasource_id>_*) share one deletion family.
        identity['catalog_family_prefix'] = f'{datasource_id}_'
    return identity


def enqueue_datasource_cleanup(session: Session, datasource: DataSource) -> None:
    """Atomically record exact managed storage targets before deleting a datasource row."""
    config = datasource.config
    if not isinstance(config, Mapping):
        return

    datasource_id = str(datasource.id)
    catalog_identity = _catalog_cleanup_identity(config, datasource_id=datasource_id) if datasource.is_iceberg else {}

    metadata_path = config.get('metadata_path') if datasource.is_iceberg else None
    targets: dict[str, tuple[bool, dict[str, str]]] = {}
    if isinstance(metadata_path, str):
        parsed = urlparse(metadata_path)
        segments = parsed.path.strip('/').split('/')
        is_metadata_file = metadata_path.endswith('.metadata.json')
        metadata_target = (metadata_path, not is_metadata_file)

        # Rebuild revisions live beneath a deterministic datasource-ID root.
        # Enqueue that exact managed prefix instead of discovering/listing a
        # family of object keys during deletion.
        family_target: tuple[str, bool] | None = None
        if datasource_id in segments:
            identity_index = segments.index(datasource_id)
            family_root = f's3://{parsed.netloc}/' + '/'.join(segments[: identity_index + 1])
            if family_root != metadata_path.rstrip('/'):
                family_target = (family_root, True)
        targets[metadata_target[0]] = (metadata_target[1], catalog_identity)
        if family_target is not None:
            targets[family_target[0]] = (family_target[1], catalog_identity)

    file_paths = [config.get('file_path')] if datasource.source_type == DataSourceType.FILE.value else []
    source = config.get('source')
    if isinstance(source, Mapping) and source.get('source_type') == DataSourceType.FILE.value:
        file_paths.append(source.get('file_path'))
    for file_path in file_paths:
        if isinstance(file_path, str):
            targets.setdefault(file_path, (False, {}))

    for url, (is_prefix, target_catalog_identity) in sorted(targets.items()):
        parsed = urlparse(url)
        segments = parsed.path.strip('/').split('/')
        if (
            parsed.scheme != 's3'
            or parsed.netloc != get_namespace()
            or not segments
            or segments[0] not in {'uploads', 'clean', 'exports', 'runtime-staging'}
            or any(segment in {'.', '..'} for segment in segments)
        ):
            continue

        payload: dict[str, object] = {
            'resource_id': datasource_id,
            'owner_kind': 'datasource',
            'owner_id': datasource_id,
            'is_prefix': is_prefix,
        }
        payload.update(target_catalog_identity)
        _enqueue_datasource_target(session, url=url, payload=payload)

    if catalog_identity:
        _rearm_published_catalog_intents(
            session,
            namespace=catalog_identity['catalog_namespace'],
            table=catalog_identity['catalog_table'],
            family_prefix=catalog_identity.get('catalog_family_prefix'),
        )


def _enqueue_datasource_target(session: Session, *, url: str, payload: dict[str, object]) -> None:
    """Re-arm a published intent while preserving active and completed claims."""
    event = session.get(RuntimeOutboxEvent, _event_id(url), with_for_update=True, populate_existing=True)
    if event is None:
        _enqueue(session, url=url, payload=payload)
        return
    if event.kind != STORAGE_CLEANUP_KIND or event.payload_json.get('url') != url:
        raise ValueError('Storage cleanup identity is already in use')

    phase = StorageCleanupPhase(str(event.payload_json['phase']))
    if phase in {StorageCleanupPhase.AUTHORIZED, StorageCleanupPhase.DELETED}:
        return

    now = runtime_outbox_service._database_now(session)
    event.payload_json = {**payload, 'url': url, 'phase': StorageCleanupPhase.TRACKED.value}
    event.status = RuntimeOutboxStatus.PENDING
    event.claim_token = None
    event.lease_expires_at = None
    event.lease_generation += 1
    event.available_at = now
    event.dispatched_at = None
    event.updated_at = now
    session.add(event)
    _wake(session)


def register_preflight_source(session: Session, *, preflight_id: str, resource_id: str, source_path: str, available_at: datetime | None = None) -> None:
    event = session.get(RuntimeOutboxEvent, _event_id(source_path), with_for_update=True, populate_existing=True)
    if event is not None and event.payload_json.get('owner_kind') == 'upload':
        if StorageCleanupPhase(str(event.payload_json.get('phase'))) != StorageCleanupPhase.TRACKED:
            raise StorageCleanupConflict('Uploaded preflight source is no longer available')
        event.payload_json = {
            **event.payload_json,
            'resource_id': resource_id,
            'owner_kind': 'preflight',
            'owner_id': preflight_id,
        }
        event.lease_generation += 1
        event.claim_token = None
        event.lease_expires_at = None
        event.status = RuntimeOutboxStatus.PENDING
        event.available_at = available_at or runtime_outbox_service._database_now(session)
        event.updated_at = runtime_outbox_service._database_now(session)
        session.add(event)
        _wake(session)
        return
    _enqueue(
        session,
        url=source_path,
        payload={'resource_id': resource_id, 'owner_kind': 'preflight', 'owner_id': preflight_id, 'is_prefix': False},
        available_at=available_at,
    )


def register_upload_source(session: Session, *, upload_id: str, source_path: str) -> None:
    """Persist cleanup ownership before bytes are transferred to private storage."""
    event = _enqueue(
        session,
        url=source_path,
        payload={'resource_id': upload_id, 'owner_kind': 'upload', 'owner_id': upload_id, 'is_prefix': False},
        available_at=runtime_outbox_service._database_now(session) + PREFLIGHT_TTL,
    )
    if event.payload_json.get('owner_kind') != 'upload' or event.payload_json.get('owner_id') != upload_id:
        raise StorageCleanupConflict('Upload target already has a different durable owner')
    session.commit()


def renew_upload_source(session: Session, *, upload_id: str, source_path: str) -> None:
    event = session.get(RuntimeOutboxEvent, _event_id(source_path), with_for_update=True, populate_existing=True)
    if (
        event is None
        or event.kind != STORAGE_CLEANUP_KIND
        or event.payload_json.get('owner_kind') != 'upload'
        or event.payload_json.get('owner_id') != upload_id
        or StorageCleanupPhase(str(event.payload_json.get('phase'))) != StorageCleanupPhase.TRACKED
    ):
        raise StorageCleanupConflict('Upload source ownership was lost')
    event.status = RuntimeOutboxStatus.PENDING
    event.claim_token = None
    event.lease_expires_at = None
    event.lease_generation += 1
    event.available_at = runtime_outbox_service._database_now(session) + PREFLIGHT_TTL
    event.updated_at = runtime_outbox_service._database_now(session)
    session.add(event)
    _wake(session)
    session.commit()


def complete_upload_source(session: Session, *, upload_id: str, source_path: str) -> None:
    """Leave a bounded handoff window for the following durable create request."""
    renew_upload_source(session, upload_id=upload_id, source_path=source_path)


def release_upload_source_for_cleanup(session: Session, *, upload_id: str, source_path: str) -> None:
    """Make an abandoned or failed, fully-settled transfer immediately retryable."""
    event = session.get(RuntimeOutboxEvent, _event_id(source_path), with_for_update=True, populate_existing=True)
    if (
        event is None
        or event.kind != STORAGE_CLEANUP_KIND
        or event.payload_json.get('owner_kind') != 'upload'
        or event.payload_json.get('owner_id') != upload_id
        or StorageCleanupPhase(str(event.payload_json.get('phase'))) != StorageCleanupPhase.TRACKED
    ):
        raise StorageCleanupConflict('Upload source ownership was lost before cleanup handoff')
    event.status = RuntimeOutboxStatus.PENDING
    event.claim_token = None
    event.lease_expires_at = None
    event.lease_generation += 1
    event.available_at = runtime_outbox_service._database_now(session)
    event.updated_at = event.available_at
    session.add(event)
    _wake(session)
    session.commit()


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
    manifest_url: str,
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
    expected_manifest = (
        f's3://{get_namespace()}/runtime-staging/datasource-stage/{owner_id}/{lease_generation}/manifest.json'
        if owner_kind == 'compute'
        else f's3://{get_namespace()}/runtime-staging/schedule-ingest/{owner_id}/{lease_generation}/manifest.json'
    )
    expected_catalog_identifier = f'clean.{prefix_url.rstrip("/").split("/")[-2]}'
    if not prefix_url.startswith(expected_prefix) or manifest_url != expected_manifest or catalog_identifier != expected_catalog_identifier:
        raise ValueError('Datasource staging targets do not match the claimed attempt')
    payload: dict[str, object] = {
        'resource_id': datasource_id,
        'owner_kind': owner_kind,
        'owner_id': owner_id,
        'owner_token': claim_token,
        'owner_generation': lease_generation,
        'worker_id': worker_id,
    }
    catalog_table = prefix_url.rstrip('/').split('/')[-2]
    _enqueue(
        session,
        url=prefix_url,
        payload={
            **payload,
            'is_prefix': True,
            'catalog_identifier': catalog_identifier,
            'catalog_type': 'sql',
            'catalog_uri': settings.database_url,
            'warehouse': f's3://{get_namespace()}/clean',
            'catalog_namespace': 'clean',
            'catalog_table': catalog_table,
        },
    )
    _enqueue(session, url=manifest_url, payload={**payload, 'is_prefix': False})
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


def _table_family_prefixes(table: str) -> tuple[str, ...]:
    return tuple(table[: index + 1] for index, character in enumerate(table) if character == '_')


def _catalog_intents(
    session: Session,
    namespace: str,
    table: str,
    *,
    family_prefix: str | None = None,
) -> list[RuntimeOutboxEvent]:
    matching_identity = [col(RuntimeOutboxEvent.catalog_table) == table]
    family_prefixes = _table_family_prefixes(table)
    if family_prefixes:
        matching_identity.append(col(RuntimeOutboxEvent.catalog_family_prefix).in_(family_prefixes))
    if family_prefix is not None:
        escaped_prefix = family_prefix.replace('/', '//').replace('%', '/%').replace('_', '/_')
        matching_identity.append(col(RuntimeOutboxEvent.catalog_table).like(f'{escaped_prefix}%', escape='/'))
    return list(
        session.execute(
            select(RuntimeOutboxEvent)
            .where(col(RuntimeOutboxEvent.kind) == STORAGE_CLEANUP_KIND)
            .where(col(RuntimeOutboxEvent.catalog_namespace) == namespace)
            .where(or_(*matching_identity))
            .order_by(col(RuntimeOutboxEvent.id))
        )
        .scalars()
        .all()
    )


def _intent_matches_catalog_table(payload: Mapping[str, object], table: str) -> bool:
    if payload.get('catalog_table') == table:
        return True
    family_prefix = payload.get('catalog_family_prefix')
    return isinstance(family_prefix, str) and table.startswith(family_prefix)


def _rearm_published_catalog_intents(
    session: Session,
    *,
    namespace: str,
    table: str,
    family_prefix: str | None,
) -> None:
    for snapshot in _catalog_intents(session, namespace, table, family_prefix=family_prefix):
        payload = dict(snapshot.payload_json)
        if StorageCleanupPhase(str(payload.get('phase'))) != StorageCleanupPhase.PUBLISHED:
            continue
        if snapshot.status != RuntimeOutboxStatus.DISPATCHED:
            continue
        catalog_table = payload.get('catalog_table')
        affects_deleted_datasource = _intent_matches_catalog_table(payload, table) or (
            family_prefix is not None and isinstance(catalog_table, str) and catalog_table.startswith(family_prefix)
        )
        if not affects_deleted_datasource:
            continue
        event = session.get(RuntimeOutboxEvent, snapshot.id, with_for_update=True, populate_existing=True)
        if event is None or event.payload_json != payload or event.status != RuntimeOutboxStatus.DISPATCHED:
            continue
        now = runtime_outbox_service._database_now(session)
        event.payload_json = {**payload, 'phase': StorageCleanupPhase.TRACKED.value}
        event.status = RuntimeOutboxStatus.PENDING
        event.claim_token = None
        event.lease_expires_at = None
        event.lease_generation += 1
        event.available_at = now
        event.dispatched_at = None
        event.updated_at = now
        session.add(event)
        _wake(session)


def settle_publication(session: Session, config: Mapping[str, object]) -> None:
    source = config.get('source')
    paths = [config.get('metadata_path'), config.get('file_path')]
    if isinstance(source, dict):
        paths.extend((source.get('file_path'), source.get('metadata_path')))
    # Ingest snapshots reference the staged Parquet files under the claim
    # prefix; the published config records that prefix so it is retained for
    # as long as table history references it.
    ingest = config.get('ingest')
    if isinstance(ingest, Mapping) and isinstance(ingest.get('claim_prefix'), str):
        paths.append(ingest['claim_prefix'])
    for path in sorted({path for path in paths if isinstance(path, str)}):
        event = session.get(RuntimeOutboxEvent, _event_id(path), with_for_update=True, populate_existing=True)
        if event is not None and event.kind == STORAGE_CLEANUP_KIND:
            _settle_referenced(session, event)

    namespace = config.get('namespace')
    table = config.get('table')
    if isinstance(namespace, str) and namespace and isinstance(table, str) and table:
        for snapshot in _catalog_intents(session, namespace, table):
            payload = dict(snapshot.payload_json)
            if not _intent_matches_catalog_table(payload, table):
                continue
            event = session.get(RuntimeOutboxEvent, snapshot.id, with_for_update=True, populate_existing=True)
            if event is not None and event.kind == STORAGE_CLEANUP_KIND:
                _settle_referenced(session, event)


def _lock_source_intent(session: Session, source_path: str) -> tuple[RuntimeOutboxEvent | None, ComputeRequest | BuildJob | DataSource | None]:
    snapshot = session.get(RuntimeOutboxEvent, _event_id(source_path), populate_existing=True)
    if snapshot is None:
        return None, None
    payload = dict(snapshot.payload_json)
    owner: ComputeRequest | BuildJob | DataSource | None
    if payload['owner_kind'] == 'build':
        owner = session.get(BuildJob, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    elif payload['owner_kind'] == 'datasource':
        owner = session.get(DataSource, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    else:
        owner = session.get(ComputeRequest, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    event = session.get(RuntimeOutboxEvent, snapshot.id, with_for_update=True, populate_existing=True)
    assert event is not None
    if event.payload_json != payload:
        raise StorageCleanupConflict('Source ownership changed while enqueueing')
    phase = StorageCleanupPhase(str(event.payload_json['phase']))
    if phase not in {StorageCleanupPhase.TRACKED, StorageCleanupPhase.PUBLISHED}:
        raise StorageCleanupConflict('Source cleanup was already authorized')
    if phase == StorageCleanupPhase.TRACKED and owner is None and payload['owner_kind'] not in {'datasource', 'upload'}:
        raise StorageCleanupConflict('Source ownership has been retired')
    return event, owner


def validate_source_enqueue(session: Session, *, source_path: str) -> None:
    _lock_source_intent(session, source_path)


def transfer_preflight_source(session: Session, *, source_path: str, request_id: str) -> None:
    event, owner = _lock_source_intent(session, source_path)
    if event is None:
        parsed = urlparse(source_path)
        segments = parsed.path.strip('/').split('/')
        if (
            parsed.scheme == 's3'
            and parsed.netloc == get_namespace()
            and segments
            and segments[0] == 'uploads'
            and not any(segment in {'.', '..'} for segment in segments)
        ):
            # An uploaded source is durably owned by its create request before
            # the request becomes visible to dispatch. Publication settles
            # this intent in the datasource transaction; failed requests leave
            # it for the normal reference-checking cleanup authorization path.
            _enqueue(
                session,
                url=source_path,
                payload={
                    'resource_id': request_id,
                    'owner_kind': 'source',
                    'owner_id': request_id,
                    'is_prefix': False,
                },
            )
        return
    if StorageCleanupPhase(str(event.payload_json['phase'])) == StorageCleanupPhase.PUBLISHED:
        return
    if event.payload_json['owner_kind'] == 'source' and event.payload_json['owner_id'] == request_id:
        return
    if event.payload_json['owner_kind'] == 'upload':
        now = runtime_outbox_service._database_now(session)
        event.payload_json = {**event.payload_json, 'owner_kind': 'source', 'owner_id': request_id, 'resource_id': request_id}
        event.lease_generation += 1
        event.claim_token = None
        event.lease_expires_at = None
        event.status = RuntimeOutboxStatus.PENDING
        event.available_at = now
        event.updated_at = now
        session.add(event)
        _wake(session)
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


def _has_reference(
    session: Session,
    *,
    url: str,
    is_prefix: bool,
    catalog_namespace: str | None = None,
    catalog_table: str | None = None,
    catalog_family_prefix: str | None = None,
) -> bool:
    paths = [
        DataSource.config['metadata_path'].as_string(),
        DataSource.config['file_path'].as_string(),
        DataSource.config['source']['metadata_path'].as_string(),
        DataSource.config['source']['file_path'].as_string(),
    ]
    matches = [path == url for path in paths]
    if is_prefix:
        matches.extend(path.startswith(url.rstrip('/') + '/', autoescape=True) for path in paths)
    if catalog_namespace is not None and catalog_table is not None:
        table_matches = [DataSource.config['table'].as_string() == catalog_table]
        if catalog_family_prefix is not None:
            table_matches.append(DataSource.config['table'].as_string().startswith(catalog_family_prefix, autoescape=True))
        matches.append((DataSource.config['namespace'].as_string() == catalog_namespace) & or_(*table_matches))
    return session.execute(select(col(DataSource.id)).where(or_(*matches)).limit(1)).first() is not None


def _source_in_use(session: Session, *, url: str, resource_id: str) -> bool:
    # Analysis previews run under the analysis RID, not the source datasource
    # RID. The durable association table is the authoritative dependency map.
    from backend_core import build_runs_service, compute_requests_service

    if compute_requests_service.has_active_request_for_datasource(session, resource_id):
        return True
    if build_runs_service.has_active_build_for_datasource(session, namespace=get_namespace(), datasource_id=resource_id):
        return True

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
    owner: BuildJob | ComputeRequest | DataSource | None
    if owner_kind == 'build':
        owner = session.get(BuildJob, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    elif owner_kind == 'datasource':
        owner = session.get(DataSource, str(payload['owner_id']), with_for_update=True, populate_existing=True)
    elif owner_kind == 'upload':
        owner = None
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
        if owner_kind == 'datasource' and isinstance(owner, DataSource):
            return False
        if owner_kind in {'preflight', 'source'} and isinstance(owner, ComputeRequest):
            if owner_kind == 'preflight' and owner.artifact_path != payload['url']:
                _settle_referenced(session, event)
                session.commit()
                return False
            if owner.status in _ACTIVE_REQUEST_STATUSES:
                return False
        elif (
            isinstance(owner, (BuildJob, ComputeRequest))
            and owner.claim_token == payload['owner_token']
            and owner.lease_generation == payload['owner_generation']
        ):
            expiry = owner.lease_expires_at
            if expiry is not None and (expiry if expiry.tzinfo is not None else expiry.replace(tzinfo=UTC)) > now:
                return False
    url = str(payload['url'])
    is_prefix = payload['is_prefix'] is True
    catalog_namespace = payload.get('catalog_namespace')
    catalog_table = payload.get('catalog_table')
    catalog_family_prefix = payload.get('catalog_family_prefix')
    referenced = _has_reference(
        session,
        url=url,
        is_prefix=is_prefix,
        catalog_namespace=catalog_namespace if isinstance(catalog_namespace, str) else None,
        catalog_table=catalog_table if isinstance(catalog_table, str) else None,
        catalog_family_prefix=catalog_family_prefix if isinstance(catalog_family_prefix, str) else None,
    )
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
