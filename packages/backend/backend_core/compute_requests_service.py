import hashlib
import uuid
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict, cast

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.orm import load_only
from sqlmodel import Session

from backend_core import engine_runs_service, runtime_ipc, runtime_work_service
from backend_core.claiming import CLAIM_DELIVERY_LEASE_SECONDS, claim_by_lease_owner, database_lease_clock, with_for_update_skip_locked
from backend_core.config import settings
from backend_core.domain.compute_requests.models import (
    command_envelope,
    compute_request_kind_name,
    compute_request_status_name,
    kind_from_proto,
    response_envelope,
    response_payload as proto_response_payload,
    status_from_proto,
)
from backend_core.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.lease_observability import record_lease_transition
from backend_core.persistence.compute_requests.models import ComputeRequest, ComputeRequestDatasource, ComputeRequestFlight
from backend_core.persistence.datasource.models import DataSource
from backend_core.runtime_work_service import RuntimeWorkKind
from backend_core.sqlmodel_typing import col, sa
from backend_core.time import utc_now as _utcnow
from backend_core.transactions import committed
from backend_core.transitions import TransitionOutcome, TransitionResult, applied, rejected
from dataforge_protocol import compute_pb2, enums_pb2

_HIGH_PRIORITY_REQUEST_KINDS = frozenset(
    {
        enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT,
        enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD,
        enums_pb2.COMPUTE_REQUEST_KIND_EXPORT,
    }
)
_COMPUTE_WORK_PENDING_QUERY = """
    SELECT 1
    FROM compute_requests
    WHERE status = 1
       OR (
            status = 2
            AND (lease_owner IS NULL OR lease_expires_at <= statement_timestamp())
       )
"""
_COMPUTE_WORK_DUE_QUERY = """
    SELECT min(lease_expires_at)
    FROM compute_requests
    WHERE status = 2 AND lease_expires_at > statement_timestamp()
"""

_USER_CREATE_REQUEST_KINDS = frozenset(
    {
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
    }
)

# Keep a completed preview reusable for the lifetime of an idle worker. The
# flight key includes source revisions, so a committed ingest/config change
# naturally routes the next caller to a new result.
_RECONCILIATION_BATCH_SIZE = 100
_FLIGHT_CACHE_SECONDS = 300
ANALYSIS_FLIGHT_REQUEST_KINDS = frozenset(
    {
        enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
    }
)
DATASOURCE_FLIGHT_REQUEST_KINDS = frozenset(
    {
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
    }
)
SHARED_FLIGHT_REQUEST_KINDS = ANALYSIS_FLIGHT_REQUEST_KINDS | DATASOURCE_FLIGHT_REQUEST_KINDS
_SHARED_FLIGHT_COMMANDS = {
    enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW: 'preview',
    enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA: 'schema',
    enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT: 'row_count',
    **{kind: 'datasource' for kind in DATASOURCE_FLIGHT_REQUEST_KINDS},
}


class ComputeFlightLockBusy(RuntimeError):
    """A matching flight is being staged by another short transaction."""


@dataclass(frozen=True)
class ComputeRequestLease:
    lease_expires_at: datetime
    last_renewed_at: datetime
    lease_generation: int
    attempts: int


@dataclass(frozen=True)
class ComputeRequestLeaseClaim:
    request_id: str
    claim_token: str
    lease_generation: int


@dataclass(frozen=True, slots=True)
class TerminalComputeRequest:
    """Detached fields required to publish one durable terminal response."""

    id: str
    kind: int
    status: int
    response_envelope: bytes | None
    error_message: str | None
    artifact_path: str | None
    artifact_name: str | None
    artifact_content_type: str | None


@dataclass(frozen=True, slots=True)
class EngineRunFinalization:
    run_id: str
    fields: dict[str, object]
    merge_result_json: bool = False


class _EngineRunFinalizationFields(TypedDict, total=False):
    analysis_id: str | None
    datasource_id: str
    kind: EngineRunKind | str
    status: EngineRunStatus | str
    request_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error_message: str | None
    completed_at: datetime | None
    duration_ms: int | None
    step_timings: dict[str, float] | None
    query_plan: str | None
    execution_entries: list[dict[str, Any]] | None
    progress: float
    current_step: str | None
    triggered_by: str | None


def _database_now(session: Session) -> datetime:
    value = session.execute(select(func.current_timestamp())).scalar_one()
    if not isinstance(value, datetime):
        raise TypeError('Database CURRENT_TIMESTAMP did not return a datetime')
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _request_priority_clause(table):
    return case(
        *[(table.c.kind == kind, 0) for kind in _HIGH_PRIORITY_REQUEST_KINDS],
        *[(table.c.kind == kind, 1) for kind in _USER_CREATE_REQUEST_KINDS],
        else_=2,
    )


def _refresh_pending_work(session: Session, *, namespace: str) -> None:
    runtime_work_service.refresh_pending_work(
        session,
        namespace=namespace,
        kind=RuntimeWorkKind.COMPUTE,
        pending_query=_COMPUTE_WORK_PENDING_QUERY,
        due_query=_COMPUTE_WORK_DUE_QUERY,
    )


def _flight_key(
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
) -> str | None:
    if kind not in SHARED_FLIGHT_REQUEST_KINDS:
        return None
    # The complete protocol command includes the exact analysis/datasource
    # identity and all operation settings. Hashing deterministic bytes gives
    # API processes one stable key while keeping different transforms, pages,
    # refresh modes, columns, or snapshots independent.
    digest = hashlib.sha256(command.SerializeToString(deterministic=True))
    return f'{kind}:{digest.hexdigest()}'


def _snapshot_input_revisions(session: Session, command: compute_pb2.ComputeCommand) -> None:
    datasource_ids = _datasource_ids_for_command(command)
    del command.input_revisions[:]
    if not datasource_ids:
        return
    rows = session.execute(
        select(col(DataSource.id), col(DataSource.revision))
        .where(col(DataSource.id).in_(datasource_ids))
        .order_by(col(DataSource.id))
        .with_for_update(read=True)
    ).all()
    revisions = {datasource_id: revision for datasource_id, revision in rows}
    for datasource_id in sorted(datasource_ids):
        revision = revisions.get(datasource_id)
        if revision is None:
            continue
        command.input_revisions.add(datasource_id=datasource_id, revision=revision)


def _flight_lock_key(namespace: str, flight_key: str) -> int:
    return int.from_bytes(hashlib.sha256(f'dataforge:compute-flight:{namespace}:{flight_key}'.encode()).digest()[:8], 'big', signed=True)


def _engine_claim_lock_key(request: ComputeRequest) -> int | None:
    identity = _engine_claim_identity(request)
    if identity is None:
        return None
    namespace, scope, reuse_policy, resource_id = identity
    key = f'{namespace}:{scope}:{reuse_policy}:{resource_id}'
    return int.from_bytes(hashlib.sha256(f'dataforge:compute-engine-claim:{key}'.encode()).digest()[:8], 'big', signed=True)


def _engine_claim_identity(request: ComputeRequest) -> tuple[str, int, int, str] | None:
    if request.compute_worker_scope is None or request.compute_worker_reuse_policy is None or request.compute_worker_resource_id is None:
        return None
    return request.namespace, request.compute_worker_scope, request.compute_worker_reuse_policy, request.compute_worker_resource_id


def _try_lock_flight(session: Session, namespace: str, flight_key: str) -> bool:
    bind = session.get_bind()
    if getattr(getattr(bind, 'dialect', None), 'name', None) != 'postgresql':
        return True
    acquired = session.execute(
        text('SELECT pg_try_advisory_xact_lock(:key)'),
        {'key': _flight_lock_key(namespace, flight_key)},
    ).scalar_one()
    return bool(acquired)


def _lock_engine_claim(session: Session, request: ComputeRequest) -> bool:
    lock_key = _engine_claim_lock_key(request)
    if lock_key is None or getattr(getattr(session.get_bind(), 'dialect', None), 'name', None) != 'postgresql':
        return True
    acquired = session.execute(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': lock_key}).scalar_one()
    return bool(acquired)


def _reusable_flight(session: Session, namespace: str, flight_key: str, *, now: datetime) -> ComputeRequest | None:
    flight_state = _read_flight(session, namespace, flight_key)
    if flight_state is None:
        return None
    flight, request = flight_state
    reusable = _reusable_flight_request(request, flight, now=now)
    if reusable is not None:
        return reusable

    # Stale cleanup can race with completion extending the cache. Lock and
    # refresh both rows before deleting; active/cached followers stay lock-free.
    stale_flight = (
        session.execute(
            select(ComputeRequestFlight)
            .where(sa(ComputeRequestFlight.namespace == namespace))
            .where(sa(ComputeRequestFlight.flight_key == flight_key))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .first()
    )
    if stale_flight is None:
        return None

    request = session.get(ComputeRequest, stale_flight.request_id, populate_existing=True)
    reusable = _reusable_flight_request(request, stale_flight, now=now)
    if reusable is not None:
        return reusable

    session.delete(stale_flight)
    session.flush()
    return None


def _find_reusable_flight(session: Session, namespace: str, flight_key: str, *, now: datetime) -> ComputeRequest | None:
    flight_state = _read_flight(session, namespace, flight_key)
    if flight_state is None:
        return None
    flight, request = flight_state
    return _reusable_flight_request(request, flight, now=now)


def _read_flight(
    session: Session,
    namespace: str,
    flight_key: str,
) -> tuple[ComputeRequestFlight, ComputeRequest | None] | None:
    flight = (
        session.execute(
            select(ComputeRequestFlight).where(sa(ComputeRequestFlight.namespace == namespace)).where(sa(ComputeRequestFlight.flight_key == flight_key))
        )
        .scalars()
        .first()
    )
    if flight is None:
        return None

    request = session.get(ComputeRequest, flight.request_id, populate_existing=True)
    return flight, request


def _reusable_flight_request(request: ComputeRequest | None, flight: ComputeRequestFlight, *, now: datetime) -> ComputeRequest | None:
    if request is None:
        return None
    if request.status in {
        enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
        enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
    }:
        return request
    cached = (
        request.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
        and request.response_envelope is not None
        and flight.expires_at is not None
        and flight.expires_at > now
    )
    return request if cached else None


def _finish_flight(session: Session, request: ComputeRequest, *, cache_result: bool, completed_at: datetime) -> None:
    flight = session.execute(select(ComputeRequestFlight).where(sa(ComputeRequestFlight.request_id == request.id)).with_for_update()).scalars().first()
    if flight is None:
        return
    if cache_result:
        flight.expires_at = completed_at + timedelta(seconds=_FLIGHT_CACHE_SECONDS)
        session.add(flight)
    else:
        session.delete(flight)


def _stage_request(
    session: Session,
    *,
    namespace: str,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    deduplicate_flight: bool,
    request_id: str | None = None,
    validate: Callable[[], None] | None = None,
) -> tuple[ComputeRequest, bool]:
    now = _utcnow()
    if validate is not None:
        # Flight followers must still satisfy current datasource lifecycle
        # checks. Shared lifecycle locks keep duplicate previews concurrent
        # while deletion retains an exclusive fence.
        validate()

    if command.WhichOneof('command') == 'datasource' and command.datasource.WhichOneof('command') == 'preflight':
        preflight = command.datasource.preflight
        if preflight.action != enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL and not preflight.HasField('datasource_id'):
            parent = session.get(ComputeRequest, preflight.preflight_id, with_for_update=True, populate_existing=True)
            if parent is None or parent.kind != enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT:
                raise ValueError('Excel preflight source has been retired')
            original = command_envelope_for_request(parent).command.datasource.preflight
            if parent.status != enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED or original.source_path != preflight.source_path:
                raise ValueError('Excel preflight source is not available for this command')

    _snapshot_input_revisions(session, command)
    datasource_ids = _datasource_ids_for_command(command)
    flight_key = _flight_key(kind, command) if deduplicate_flight else None
    if flight_key is not None:
        existing = _find_reusable_flight(session, namespace, flight_key, now=now)
        if existing is not None:
            return existing, False

        # PostgreSQL advisory transaction locking serializes only equal keys;
        # misses recheck under the lock before creation. Active and cached
        # followers use the lock-free lookup above.
        if not _try_lock_flight(session, namespace, flight_key):
            # Never park an API database connection behind another viewer of
            # the same preview. The HTTP layer retries after closing this
            # short transaction, leaving the connection available to other
            # requests while the current flight leader commits.
            raise ComputeFlightLockBusy(f'Compute flight {flight_key} is being staged')
        existing = _reusable_flight(session, namespace, flight_key, now=now)
        if existing is not None:
            # The first request created its durable namespace marker in the
            # same transaction. Followers share that request and need no queue
            # write or marker-row lock of their own.
            return existing, False

    request_id = request_id or str(uuid.uuid4())
    if command.WhichOneof('command') == 'datasource':
        from backend_core import storage_cleanup_service

        if command.datasource.WhichOneof('command') == 'create_file':
            storage_cleanup_service.transfer_preflight_source(session, source_path=command.datasource.create_file.file_path, request_id=request_id)
        if command.datasource.WhichOneof('command') == 'preflight':
            storage_cleanup_service.validate_source_enqueue(session, source_path=command.datasource.preflight.source_path)
    envelope = command_envelope(
        kind=kind,
        command=command,
        request_id=request_id,
    )
    identity = _engine_identity_for_command(command, request_id=request_id)
    request = ComputeRequest(
        id=request_id,
        namespace=namespace,
        kind=kind,
        status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
        compute_worker_scope=identity.scope if identity is not None else None,
        compute_worker_reuse_policy=identity.reuse_policy if identity is not None else None,
        compute_worker_resource_id=identity.resource_id if identity is not None else None,
        command_envelope=envelope.SerializeToString(),
        max_attempts=settings.runtime_compute_max_attempts,
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    if command.WhichOneof('command') == 'datasource' and command.datasource.WhichOneof('command') == 'preflight':
        preflight = command.datasource.preflight
        request.artifact_path = preflight.source_path
        if preflight.action == enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL and preflight.delete_source:
            from backend_core import storage_cleanup_service

            request.artifact_path = preflight.source_path
            request.artifact_name = 'preflight-source'
            request.artifact_content_type = 'application/vnd.dataforge.preflight-source'
            storage_cleanup_service.register_preflight_source(
                session,
                preflight_id=request.id,
                resource_id=preflight.preflight_id,
                source_path=preflight.source_path,
                available_at=now + storage_cleanup_service.PREFLIGHT_TTL,
            )
    if command.WhichOneof('command') == 'datasource' and command.datasource.WhichOneof('command') == 'create_file':
        request.artifact_path = command.datasource.create_file.file_path
    session.flush()
    session.add_all(ComputeRequestDatasource(request_id=request.id, datasource_id=datasource_id) for datasource_id in datasource_ids)
    if flight_key is not None:
        session.add(
            ComputeRequestFlight(
                namespace=namespace,
                flight_key=flight_key,
                request_id=request.id,
                created_at=now,
            )
        )
        session.flush()
    runtime_work_service.append_wake(session, namespace=namespace, kind=RuntimeWorkKind.COMPUTE)
    return request, True


def stage_request(
    session: Session,
    *,
    namespace: str,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    request_id: str | None = None,
) -> ComputeRequest:
    request, _created = _stage_request(
        session,
        namespace=namespace,
        kind=kind,
        command=command,
        deduplicate_flight=False,
        request_id=request_id,
    )
    return request


def stage_shared_flight_request(
    session: Session,
    *,
    namespace: str,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    request_id: str | None = None,
    validate: Callable[[], None] | None = None,
) -> tuple[ComputeRequest, bool]:
    if kind not in SHARED_FLIGHT_REQUEST_KINDS:
        raise ValueError(f'{compute_request_kind_name(kind)} does not support shared request flights')
    expected_command = _SHARED_FLIGHT_COMMANDS[kind]
    if command.WhichOneof('command') != expected_command:
        raise ValueError(f'{compute_request_kind_name(kind)} requires a {expected_command} command')
    return _stage_request(
        session,
        namespace=namespace,
        kind=kind,
        command=command,
        deduplicate_flight=True,
        request_id=request_id,
        validate=validate,
    )


create_request = committed(stage_request, refresh=True)


def command_envelope_for_request(request: ComputeRequest):
    envelope = compute_pb2.ComputeCommandEnvelope.FromString(request.command_envelope)
    row_kind = kind_from_proto(request.kind)
    if kind_from_proto(envelope.kind) != row_kind:
        raise ValueError(
            f'Compute request {request.id} envelope kind {compute_request_kind_name(kind_from_proto(envelope.kind))!r} '
            f'does not match row kind {compute_request_kind_name(row_kind)!r}'
        )
    if envelope.correlation_id != request.id:
        raise ValueError(f'Compute request {request.id} envelope correlation id {envelope.correlation_id!r} does not match request id')
    return envelope


def response_payload(request: ComputeRequest | TerminalComputeRequest) -> dict[str, object]:
    if request.response_envelope is None:
        raise ValueError(f'Compute request {request.id} has no response envelope')
    envelope = compute_pb2.ComputeResponseEnvelope.FromString(request.response_envelope)
    row_kind = kind_from_proto(request.kind)
    if kind_from_proto(envelope.kind) != row_kind:
        raise ValueError(
            f'Compute request {request.id} response kind {compute_request_kind_name(kind_from_proto(envelope.kind))!r} '
            f'does not match row kind {compute_request_kind_name(row_kind)!r}'
        )
    row_status = status_from_proto(request.status)
    if status_from_proto(envelope.status) != row_status:
        raise ValueError(
            f'Compute request {request.id} response status {compute_request_status_name(status_from_proto(envelope.status))!r} '
            f'does not match row status {compute_request_status_name(row_status)!r}'
        )
    if envelope.correlation_id != request.id:
        raise ValueError(f'Compute request {request.id} response correlation id {envelope.correlation_id!r} does not match request id')
    return proto_response_payload(envelope)


def get_request(session: Session, request_id: str) -> ComputeRequest | None:
    return session.get(ComputeRequest, request_id)


def list_terminal_requests(session: Session, request_ids: Collection[str]) -> list[TerminalComputeRequest]:
    """Return terminal response envelopes from one namespace in one query.

    HTTP waiters use this only as a lost-notification backstop. Keep the
    projection narrow: the recovery task batches waiters by namespace and
    delivers detached response fields so they do not each reread the same
    terminal rows through the API executor.
    """
    ids = tuple(dict.fromkeys(request_ids))
    if not ids:
        return []
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    statement = (
        select(
            table.c.id,
            table.c.kind,
            table.c.status,
            table.c.response_envelope,
            table.c.error_message,
            table.c.artifact_path,
            table.c.artifact_name,
            table.c.artifact_content_type,
        )
        .where(table.c.id.in_(ids))
        .where(
            table.c.status.in_(
                [
                    enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
                    enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
                ]
            )
        )
    )
    return [
        TerminalComputeRequest(
            id=str(request_id),
            kind=int(kind),
            status=int(status),
            response_envelope=response_envelope,
            error_message=error_message,
            artifact_path=artifact_path,
            artifact_name=artifact_name,
            artifact_content_type=artifact_content_type,
        )
        for request_id, kind, status, response_envelope, error_message, artifact_path, artifact_name, artifact_content_type in session.execute(statement)
    ]


def _datasource_engine_identity(resource_id: str) -> compute_pb2.ComputeWorkerIdentity:
    return compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        datasource_id=resource_id,
        resource_id=resource_id,
    )


def _engine_identity_for_command(command: compute_pb2.ComputeCommand, *, request_id: str) -> compute_pb2.ComputeWorkerIdentity | None:
    command_name = command.WhichOneof('command')
    if command_name in {'spawn_engine', 'configure_engine', 'shutdown_engine'}:
        return getattr(command, command_name).engine_identity
    if command_name == 'preview':
        preview = command.preview
        if preview.HasField('engine_identity'):
            return preview.engine_identity
        analysis_id = preview.analysis_pipeline.analysis_id or preview.analysis_id
        if analysis_id:
            return compute_pb2.ComputeWorkerIdentity(
                scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
                reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
                analysis_id=analysis_id,
                resource_id=analysis_id,
            )
        return None
    if command_name in {'schema', 'row_count', 'download', 'export'}:
        interactive = getattr(command, command_name)
        analysis_id = interactive.analysis_pipeline.analysis_id or interactive.analysis_id
        if analysis_id:
            return compute_pb2.ComputeWorkerIdentity(
                scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
                reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
                analysis_id=analysis_id,
                resource_id=analysis_id,
            )
    if command_name == 'datasource':
        datasource = command.datasource
        datasource_command = datasource.WhichOneof('command')
        if datasource_command in {'create_file', 'create_database', 'create_iceberg'}:
            return _datasource_engine_identity(request_id)
        if datasource_command == 'preflight':
            return _datasource_engine_identity(datasource.preflight.preflight_id)
        if datasource_command is not None:
            operation = getattr(datasource, datasource_command)
            datasource_id = getattr(operation, 'datasource_id', '')
            if datasource_id:
                return _datasource_engine_identity(datasource_id)
    return None


def _is_shared_flight_request(request: ComputeRequest) -> bool:
    envelope = command_envelope_for_request(request)
    return _flight_key(kind_from_proto(request.kind), envelope.command) is not None


def _cache_completed_flight(request: ComputeRequest) -> bool:
    if request.kind != enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
        return True
    command = command_envelope_for_request(request).command
    return not command.datasource.schema.refresh


def _retire_request(session: Session, request: ComputeRequest, *, reason: str, now: datetime) -> None:
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    request.error_message = reason
    request.response_envelope = response_envelope(
        kind=kind_from_proto(request.kind),
        request_id=request.id,
        status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
        payload={'error': reason},
        error_message=reason,
    ).SerializeToString()
    request.completed_at = now
    request.updated_at = now
    request.lease_owner = None
    request.claim_token = None
    request.lease_expires_at = None
    request.claimed_at = None
    request.last_renewed_at = None
    session.add(request)
    _finish_flight(session, request, cache_result=False, completed_at=now)
    runtime_ipc.notify_compute_response_on_commit(session, request_id=request.id, namespace=request.namespace)


def _cancel_request(
    session: Session,
    request_id: str,
    *,
    reason: str,
    allow_running_engine_request: bool,
    preserve_shared_flight: bool = False,
) -> ComputeRequest | None:
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    active_statuses = [enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED]
    if allow_running_engine_request:
        active_statuses.append(enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
    statement = select(ComputeRequest).where(table.c.id == request_id).where(table.c.status.in_(active_statuses)).with_for_update()
    request = session.execute(statement).scalars().first()
    if request is None:
        session.rollback()
        return None

    if preserve_shared_flight and _is_shared_flight_request(request):
        # A shared read is keyed by the exact resource identity and command.
        # browser that became the HTTP leader may disappear while another tab
        # is already waiting for the same result. Leave the durable request
        # alive so the worker can publish the result to the cache/followers.
        session.rollback()
        return None

    if request.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING and allow_running_engine_request:
        envelope = command_envelope_for_request(request)
        if _engine_identity_for_command(envelope.command, request_id=request.id) is None:
            # Datasource ingestion/publication is not tied to a killable engine.
            # Let it finish its publication claim instead of creating orphaned
            # source objects when a browser closes the upload request.
            session.rollback()
            return None

    _retire_request(session, request, reason=reason, now=_utcnow())
    session.commit()
    session.refresh(request)
    record_lease_transition(
        kind='compute_request',
        transition='cancel',
        outcome=TransitionOutcome.APPLIED,
        entity_id=request.id,
        owner_id='http-client',
        claim_token='cancelled',
        generation=request.lease_generation,
        attempt=request.attempts,
    )
    return request


def cancel_queued_request(session: Session, request_id: str, *, reason: str) -> ComputeRequest | None:
    """Retire a request whose HTTP client went away before execution started."""
    return _cancel_request(
        session,
        request_id,
        reason=reason,
        allow_running_engine_request=False,
    )


def cancel_disconnected_request(session: Session, request_id: str, *, reason: str) -> ComputeRequest | None:
    """Retire abandoned queue work and non-shared running engine requests.

    A running datasource mutation must finish because it may be publishing a
    new datasource. A shared read is also allowed to finish: another tab may
    already be waiting on the same exact resource and command.
    Other engine-backed work can be retired because its worker observes the
    retired lease and stops that request.
    """
    return _cancel_request(
        session,
        request_id,
        reason=reason,
        allow_running_engine_request=True,
        preserve_shared_flight=True,
    )


def cancel_active_requests_for_engine(
    session: Session,
    *,
    namespace: str,
    identity: compute_pb2.ComputeWorkerIdentity,
    reason: str,
) -> int:
    """Retire active requests that target an engine being explicitly shut down.

    Requests are durable and may already have been claimed by a capacity
    waiter when the engine teardown is staged. The relational identity columns
    let this target only the matching requests. Decoding and locking every
    active protobuf command in a namespace created an O(n) lock convoy during
    teardown, which delayed unrelated uploads and saves. A worker that was
    already executing the request observes the retired lease when it publishes
    its result.
    """
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    statement = (
        select(ComputeRequest)
        .where(table.c.namespace == namespace)
        .where(
            table.c.status.in_(
                [
                    enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
                    enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
                ]
            )
        )
        .where(table.c.compute_worker_scope == identity.scope)
        .where(table.c.compute_worker_reuse_policy == identity.reuse_policy)
        .where(table.c.compute_worker_resource_id == identity.resource_id)
        .with_for_update()
    )
    requests = list(session.execute(statement).scalars().all())
    now = _utcnow()
    cancelled = 0
    for request in requests:
        _retire_request(session, request, reason=reason, now=now)
        record_lease_transition(
            kind='compute_request',
            transition='cancel',
            outcome=TransitionOutcome.APPLIED,
            entity_id=request.id,
            owner_id='engine-shutdown',
            claim_token='cancelled',
            generation=request.lease_generation,
            attempt=request.attempts,
        )
        cancelled += 1
    if cancelled:
        session.commit()
    else:
        session.rollback()
    return cancelled


def _datasource_ids_for_command(command: compute_pb2.ComputeCommand) -> set[str]:
    """Extract source dependencies once when a request becomes durable."""
    command_name = command.WhichOneof('command')
    if command_name is None:
        return set()
    payload = getattr(command, command_name)
    if command_name == 'datasource':
        datasource_command_name = payload.WhichOneof('command')
        if datasource_command_name is None:
            return set()
        datasource_command = getattr(payload, datasource_command_name)
        datasource_id = getattr(datasource_command, 'datasource_id', '')
        return {datasource_id} if datasource_id else set()

    pipeline = getattr(payload, 'analysis_pipeline', None)
    if pipeline is None:
        return set()
    datasource_ids = {tab.datasource.id for tab in pipeline.tabs if tab.datasource.id}
    for tab in pipeline.tabs:
        for step in tab.steps:
            config_name = step.config.WhichOneof('config')
            if config_name == 'join' and step.config.join.right_source:
                datasource_ids.add(step.config.join.right_source)
            elif config_name == 'union_by_name':
                datasource_ids.update(source for source in step.config.union_by_name.sources if source)
    return datasource_ids


def has_active_request_for_datasource(session: Session, datasource_id: str) -> bool:
    """Return whether queued or running compute work still references a datasource.

    Dependencies are materialized at enqueue time. Deletion therefore checks
    one indexed association instead of decoding every active protobuf command
    in the tenant schema while holding a datasource transaction.
    """
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    association_table = ComputeRequestDatasource.metadata.tables[ComputeRequestDatasource.__tablename__]
    active_statuses = [
        enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
        enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
    ]
    statement = (
        select(association_table.c.request_id)
        .join(ComputeRequest, association_table.c.request_id == table.c.id)
        .where(association_table.c.datasource_id == datasource_id)
        .where(table.c.status.in_(active_statuses))
        .limit(1)
    )
    return session.execute(statement).first() is not None


def claim_next_request(
    session: Session,
    *,
    worker_id: str,
    reclaimable_owner_ids: set[str] | None = None,
    allowed_kinds: Collection[enums_pb2.ComputeRequestKind] | None = None,
) -> ComputeRequest | None:
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    reclaimable = set(reclaimable_owner_ids or ())
    has_engine_identity = and_(
        table.c.compute_worker_scope.is_not(None),
        table.c.compute_worker_reuse_policy.is_not(None),
        table.c.compute_worker_resource_id.is_not(None),
    )
    blocked_engine_identities: set[tuple[str, int, int, str]] = set()
    while True:
        now = _database_now(session)
        queued_clause = table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
        reclaimable_clause = and_(
            table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
            or_(table.c.lease_owner.is_(None), table.c.lease_owner.in_(reclaimable), table.c.lease_expires_at <= now),
            table.c.attempts < table.c.max_attempts,
        )
        running = table.alias('running_engine_request')
        has_running_sibling = (
            select(running.c.id)
            .where(running.c.namespace == table.c.namespace)
            .where(running.c.compute_worker_scope == table.c.compute_worker_scope)
            .where(running.c.compute_worker_reuse_policy == table.c.compute_worker_reuse_policy)
            .where(running.c.compute_worker_resource_id == table.c.compute_worker_resource_id)
            .where(running.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
            .where(running.c.id != table.c.id)
            .exists()
        )
        base = select(ComputeRequest).where(or_(queued_clause, reclaimable_clause)).where(or_(~has_engine_identity, ~has_running_sibling))
        if allowed_kinds is not None:
            base = base.where(table.c.kind.in_(allowed_kinds))
        if blocked_engine_identities:
            base = base.where(
                or_(
                    ~has_engine_identity,
                    ~or_(
                        *(
                            and_(
                                table.c.namespace == namespace,
                                table.c.compute_worker_scope == scope,
                                table.c.compute_worker_reuse_policy == reuse_policy,
                                table.c.compute_worker_resource_id == resource_id,
                            )
                            for namespace, scope, reuse_policy, resource_id in sorted(blocked_engine_identities)
                        )
                    ),
                )
            )
        base = base.order_by(_request_priority_clause(table), table.c.created_at, table.c.id).limit(1)
        stmt = with_for_update_skip_locked(session, base)
        row = session.execute(stmt).scalars().first()
        if row is None:
            session.commit()
            return None
        if not _lock_engine_claim(session, row):
            identity = _engine_claim_identity(row)
            if identity is None:
                raise RuntimeError(f'Engine claim lock was unavailable without an engine identity for request {row.id}')
            session.rollback()
            blocked_engine_identities.add(identity)
            continue

        active_sibling = session.execute(
            select(running.c.id)
            .where(running.c.namespace == row.namespace)
            .where(running.c.compute_worker_scope == row.compute_worker_scope)
            .where(running.c.compute_worker_reuse_policy == row.compute_worker_reuse_policy)
            .where(running.c.compute_worker_resource_id == row.compute_worker_resource_id)
            .where(running.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
            .where(running.c.id != row.id)
            .limit(1)
        ).first()
        if active_sibling is None:
            break

        # Another API process claimed a different command for this exact
        # engine after our candidate query. The transaction lock made the race
        # visible; retry with a fresh snapshot so another RID can progress.
        session.rollback()

    previous_status = row.status
    previous_owner = row.lease_owner
    previous_generation = row.lease_generation
    claim_token = str(uuid.uuid4())
    lease_now = database_lease_clock(session, now)
    lease_claimed = claim_by_lease_owner(
        session,
        ComputeRequest,
        table=table,
        row_id=row.id,
        previous_owner=previous_owner,
        extra_conditions=(table.c.status == previous_status, table.c.lease_generation == previous_generation),
        values={
            'status': enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
            'lease_owner': worker_id,
            'claim_token': claim_token,
            'lease_generation': previous_generation + 1,
            'lease_expires_at': lease_now + timedelta(seconds=CLAIM_DELIVERY_LEASE_SECONDS),
            'claimed_at': lease_now,
            'last_renewed_at': lease_now,
            'attempts': row.attempts + 1,
            'updated_at': lease_now,
        },
    )
    if not lease_claimed:
        session.rollback()
        session.commit()
        return None
    session.commit()
    claimed = session.get(ComputeRequest, row.id)
    # A disconnect/engine shutdown can retire the row after the claim commit
    # and before the gRPC handler serializes it.  Do not turn that harmless
    # race into a worker-loop error or return a lease-less claim.
    if claimed is None or claimed.status != enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING or claimed.claim_token is None or claimed.lease_expires_at is None:
        session.commit()
        return None
    record_lease_transition(
        kind='compute_request',
        transition='reclaim' if previous_owner is not None else 'claim',
        outcome=TransitionOutcome.APPLIED,
        entity_id=claimed.id,
        owner_id=worker_id,
        claim_token=claim_token,
        generation=claimed.lease_generation,
        attempt=claimed.attempts,
    )
    return claimed


def stage_exhausted_requests(session: Session, *, namespace: str) -> int:
    """Reconcile compute queue state once per namespace recovery pass.

    Claiming stays limited to one directed request. This scheduled pass fails
    exhausted leases and refreshes the durable namespace wake marker together,
    avoiding a queue scan and marker write for every empty claim lane.
    """
    now = _database_now(session)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    statement = (
        select(ComputeRequest)
        .where(table.c.namespace == namespace)
        .where(table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
        .where(table.c.attempts >= table.c.max_attempts)
        .where(table.c.lease_expires_at <= now)
        .order_by(table.c.lease_expires_at, table.c.id)
        .limit(_RECONCILIATION_BATCH_SIZE)
    )
    requests = list(session.execute(with_for_update_skip_locked(session, statement)).scalars().all())
    for request in requests:
        owner_id = request.lease_owner or 'unowned'
        claim_token = request.claim_token or ''
        error_message = f'Compute request exhausted {request.max_attempts} execution attempts'
        request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
        request.response_envelope = response_envelope(
            kind=kind_from_proto(request.kind),
            request_id=request.id,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            payload=None,
            error_message=error_message,
        ).SerializeToString()
        request.error_message = error_message
        request.completed_at = now
        request.updated_at = now
        request.lease_owner = None
        request.claim_token = None
        request.lease_expires_at = None
        request.claimed_at = None
        request.last_renewed_at = None
        session.add(request)
        _finish_flight(session, request, cache_result=False, completed_at=now)
        runtime_ipc.notify_compute_response_on_commit(session, request_id=request.id, namespace=request.namespace)
        record_lease_transition(
            kind='compute_request',
            transition='exhaust',
            outcome=TransitionOutcome.APPLIED,
            entity_id=request.id,
            owner_id=owner_id,
            claim_token=claim_token,
            generation=request.lease_generation,
            attempt=request.attempts,
        )
    session.flush()
    _refresh_pending_work(session, namespace=namespace)
    return len(requests)


reconcile_expired_requests = committed(stage_exhausted_requests)


def renew_request_lease(
    session: Session,
    request_id: str,
    *,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
) -> TransitionResult[ComputeRequestLease]:
    lease_now = database_lease_clock(session, _utcnow())
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    statement = (
        update(ComputeRequest)
        .where(table.c.id == request_id)
        .where(table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .where(table.c.lease_expires_at > lease_now)
        .values(
            lease_expires_at=lease_now + timedelta(seconds=settings.runtime_work_lease_ttl_seconds),
            last_renewed_at=lease_now,
            updated_at=lease_now,
        )
    )
    row = session.execute(
        statement.returning(
            table.c.lease_expires_at,
            table.c.last_renewed_at,
            table.c.lease_generation,
            table.c.attempts,
        )
    ).one_or_none()
    if row is None:
        session.rollback()
        # Missing and stale leases have the same runtime action. Avoid a
        # second read on this high-frequency path just to distinguish them.
        outcome = TransitionOutcome.LEASE_LOST
        record_lease_transition(
            kind='compute_request',
            transition='renew',
            outcome=outcome,
            entity_id=request_id,
            owner_id=worker_id,
            claim_token=claim_token,
            generation=lease_generation,
        )
        return rejected(outcome)
    session.commit()
    renewal = ComputeRequestLease(
        lease_expires_at=cast(datetime, row[0]),
        last_renewed_at=cast(datetime, row[1]),
        lease_generation=int(row[2]),
        attempts=int(row[3]),
    )
    record_lease_transition(
        kind='compute_request',
        transition='renew',
        outcome=TransitionOutcome.APPLIED,
        entity_id=request_id,
        owner_id=worker_id,
        claim_token=claim_token,
        generation=lease_generation,
        attempt=renewal.attempts,
    )
    return applied(renewal)


def renew_request_leases(
    session: Session,
    claims: Sequence[ComputeRequestLeaseClaim],
    *,
    worker_id: str,
) -> set[str]:
    """Renew a worker's active compute claims in one database transaction."""
    request_ids = [claim.request_id for claim in claims]
    if not request_ids or len(request_ids) != len(set(request_ids)):
        raise ValueError('Compute lease renewal batch must contain unique request IDs')

    lease_now = database_lease_clock(session, _utcnow())
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    claim_matches = [
        and_(
            table.c.id == claim.request_id,
            table.c.claim_token == claim.claim_token,
            table.c.lease_generation == claim.lease_generation,
        )
        for claim in claims
    ]
    statement = (
        update(ComputeRequest)
        .where(table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.lease_expires_at > lease_now)
        .where(or_(*claim_matches))
        .values(
            lease_expires_at=lease_now + timedelta(seconds=settings.runtime_work_lease_ttl_seconds),
            last_renewed_at=lease_now,
            updated_at=lease_now,
        )
        .returning(table.c.id)
    )
    renewed_ids = set(session.execute(statement).scalars().all())

    if renewed_ids:
        session.commit()
    else:
        session.rollback()

    for claim in claims:
        renewed = claim.request_id in renewed_ids
        record_lease_transition(
            kind='compute_request',
            transition='renew',
            outcome=TransitionOutcome.APPLIED if renewed else TransitionOutcome.LEASE_LOST,
            entity_id=claim.request_id,
            owner_id=worker_id,
            claim_token=claim.claim_token,
            generation=claim.lease_generation,
        )
    return renewed_ids


def lock_active_request_claim(
    session: Session,
    request_id: str,
    *,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    include_command_envelope: bool = False,
) -> ComputeRequest | None:
    return _active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        for_update=True,
        include_command_envelope=include_command_envelope,
    )


def get_active_request_claim(
    session: Session,
    request_id: str,
    *,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    include_command_envelope: bool = False,
) -> ComputeRequest | None:
    """Read a candidate claim without holding its row lock during preparation.

    Callers that will publish a terminal state must revalidate with
    ``lock_active_request_claim`` immediately before writing.
    """
    return _active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        for_update=False,
        include_command_envelope=include_command_envelope,
    )


def _active_request_claim(
    session: Session,
    request_id: str,
    *,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    for_update: bool,
    include_command_envelope: bool,
) -> ComputeRequest | None:
    now = _database_now(session)
    lease_now = database_lease_clock(session, now)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    selected_columns: list[Any] = [
        ComputeRequest.id,
        ComputeRequest.namespace,
        ComputeRequest.kind,
        ComputeRequest.status,
        ComputeRequest.compute_worker_resource_id,
    ]
    if include_command_envelope:
        selected_columns.append(ComputeRequest.command_envelope)
    statement = (
        select(ComputeRequest)
        .options(load_only(*selected_columns))
        .where(table.c.id == request_id)
        .where(table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .where(table.c.lease_expires_at > lease_now)
    )
    if for_update:
        statement = statement.with_for_update()
    return session.execute(statement).scalars().first()


def _stage_engine_run_finalization(
    session: Session,
    request: ComputeRequest,
    finalization: EngineRunFinalization | None,
    *,
    expected_status: EngineRunStatus,
) -> None:
    if finalization is None:
        return
    if request.kind != enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
        raise ValueError('Only preview requests can finalize a preview engine run')
    status = finalization.fields.get('status')
    if not isinstance(status, str) or EngineRunStatus.require(status) != expected_status:
        raise ValueError(f'Preview engine run must finish with status {expected_status.value}')
    if 'completed_at' not in finalization.fields:
        raise ValueError('Preview engine run finalization requires completed_at')
    fields = cast(_EngineRunFinalizationFields, finalization.fields)
    result = engine_runs_service.stage_update_engine_run(
        session,
        finalization.run_id,
        merge_result_json=finalization.merge_result_json,
        serialize_response=False,
        **fields,
    )
    if result is not True:
        raise ValueError(f'Preview engine run {finalization.run_id} rejected its terminal status transition')


def _matching_terminal_request(
    session: Session,
    request_id: str,
    *,
    status: enums_pb2.ComputeRequestStatus,
    response_envelope: compute_pb2.ComputeResponseEnvelope,
    error_message: str | None = None,
    artifact_path: str | None = None,
    artifact_name: str | None = None,
    artifact_content_type: str | None = None,
) -> ComputeRequest | None:
    """Acknowledge an identical retry after the first terminal commit succeeded."""
    request = session.get(ComputeRequest, request_id)
    if request is None or request.status != status or request.response_envelope is None:
        return None
    if compute_pb2.ComputeResponseEnvelope.FromString(request.response_envelope) != response_envelope:
        return None
    if (
        request.error_message != error_message
        or request.artifact_path != artifact_path
        or request.artifact_name != artifact_name
        or request.artifact_content_type != artifact_content_type
    ):
        return None
    # This is a read-only acknowledgement. The original transaction already
    # finalized engine-run state and emitted the response notification.
    return request


def mark_request_completed(
    session: Session,
    request_id: str,
    *,
    response_envelope: compute_pb2.ComputeResponseEnvelope,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    artifact_path: str | None = None,
    artifact_name: str | None = None,
    artifact_content_type: str | None = None,
    engine_run_finalization: EngineRunFinalization | None = None,
) -> ComputeRequest | None:
    # Serialize the potentially large preview payload before opening a DB
    # transaction or locking the durable request row.
    serialized_response = response_envelope.SerializeToString()
    include_command_envelope = response_envelope.kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA
    request = get_active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        include_command_envelope=include_command_envelope,
    )
    if request is None:
        session.rollback()
        return _matching_terminal_request(
            session,
            request_id,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
            response_envelope=response_envelope,
            artifact_path=artifact_path,
            artifact_name=artifact_name,
            artifact_content_type=artifact_content_type,
        )
    _validate_response_envelope(request, response_envelope, enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED)
    _stage_engine_run_finalization(
        session,
        request,
        engine_run_finalization,
        expected_status=EngineRunStatus.SUCCESS,
    )
    # Engine-run finalization and payload serialization can be expensive. Keep
    # the request row unlocked during that work, then revalidate under lock at
    # the write boundary. If the claim changed, rollback also discards the
    # staged engine-run finalization.
    request = lock_active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        include_command_envelope=include_command_envelope,
    )
    if request is None:
        session.rollback()
        return _matching_terminal_request(
            session,
            request_id,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
            response_envelope=response_envelope,
            artifact_path=artifact_path,
            artifact_name=artifact_name,
            artifact_content_type=artifact_content_type,
        )
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    request.response_envelope = serialized_response
    request.error_message = None
    request.artifact_path = artifact_path
    request.artifact_name = artifact_name
    request.artifact_content_type = artifact_content_type
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.claim_token = None
    request.lease_expires_at = None
    request.claimed_at = None
    request.last_renewed_at = None
    session.add(request)
    _finish_flight(
        session,
        request,
        cache_result=_cache_completed_flight(request),
        completed_at=request.completed_at,
    )
    runtime_ipc.notify_compute_response_on_commit(session, request_id=request.id, namespace=request.namespace)
    session.commit()
    return request


def mark_request_failed(
    session: Session,
    request_id: str,
    *,
    error_message: str,
    response_envelope: compute_pb2.ComputeResponseEnvelope,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    engine_run_finalization: EngineRunFinalization | None = None,
) -> ComputeRequest | None:
    serialized_response = response_envelope.SerializeToString()
    request = get_active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
    )
    if request is None:
        session.rollback()
        return _matching_terminal_request(
            session,
            request_id,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            response_envelope=response_envelope,
            error_message=error_message,
        )
    _validate_response_envelope(request, response_envelope, enums_pb2.COMPUTE_REQUEST_STATUS_FAILED)
    _stage_engine_run_finalization(
        session,
        request,
        engine_run_finalization,
        expected_status=EngineRunStatus.FAILED,
    )
    # Do not hold the request row lock through engine-run finalization. The
    # final lock below revalidates the exact claim before publishing failure.
    request = lock_active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
    )
    if request is None:
        session.rollback()
        return _matching_terminal_request(
            session,
            request_id,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            response_envelope=response_envelope,
            error_message=error_message,
        )
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    request.error_message = error_message
    request.response_envelope = serialized_response
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.claim_token = None
    request.lease_expires_at = None
    request.claimed_at = None
    request.last_renewed_at = None
    session.add(request)
    _finish_flight(session, request, cache_result=False, completed_at=request.completed_at)
    runtime_ipc.notify_compute_response_on_commit(session, request_id=request.id, namespace=request.namespace)
    session.commit()
    return request


def _validate_response_envelope(
    request: ComputeRequest,
    envelope: compute_pb2.ComputeResponseEnvelope,
    expected_status: enums_pb2.ComputeRequestStatus,
) -> None:
    if kind_from_proto(envelope.kind) != kind_from_proto(request.kind):
        raise ValueError(f'Compute request {request.id} response kind does not match request kind')
    if status_from_proto(envelope.status) != expected_status:
        raise ValueError(f'Compute request {request.id} response status does not match completion status')
    if envelope.correlation_id != request.id:
        raise ValueError(f'Compute request {request.id} response correlation id does not match request id')


def queued_request_count(session: Session) -> int:
    stmt = select(func.count()).select_from(ComputeRequest).where(sa(ComputeRequest.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED))
    return session.execute(stmt).scalar_one()


def cleanup_completed_requests(session: Session, *, older_than_seconds: int) -> int:
    cutoff = _utcnow() - timedelta(seconds=older_than_seconds)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    stmt = select(ComputeRequest).where(table.c.completed_at.is_not(None)).where(table.c.completed_at < cutoff)
    rows = list(session.execute(stmt).scalars().all())
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)
