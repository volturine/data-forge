from __future__ import annotations

import logging
import time
from collections.abc import Collection
from datetime import datetime
from enum import StrEnum

from sqlalchemy import delete, func, or_, select, text
from sqlmodel import Session

from backend_core.config import settings
from backend_core.persistence.runtime_events.models import RuntimeNamespaceWork, RuntimeNamespaceWorkWake

logger = logging.getLogger(__name__)


class RuntimeWorkKind(StrEnum):
    OUTBOX = 'outbox'
    BUILD = 'build'
    COMPUTE = 'compute'
    DATASOURCE_DELETE = 'datasource_delete'
    STORAGE_CLEANUP = 'storage_cleanup'
    SCHEDULE = 'schedule'


WORKER_RECOVERY_KINDS = (
    RuntimeWorkKind.BUILD,
    RuntimeWorkKind.COMPUTE,
    RuntimeWorkKind.DATASOURCE_DELETE,
    RuntimeWorkKind.STORAGE_CLEANUP,
)
_SLOW_WAKE_OPERATION_SECONDS = 0.25


def _is_distributed_postgres(session: Session) -> bool:
    bind = session.get_bind()
    return settings.distributed_runtime_enabled and getattr(getattr(bind, 'dialect', None), 'name', None) == 'postgresql'


def append_wake(session: Session, *, namespace: str, kind: RuntimeWorkKind) -> None:
    """Append an independent durable wake without updating a hot namespace row."""
    if not _is_distributed_postgres(session):
        return
    started = time.perf_counter()
    session.execute(
        text(
            """
            INSERT INTO public.runtime_namespace_work_wakes (namespace, kind, created_at)
            VALUES (:namespace, :kind, statement_timestamp())
            """
        ),
        {'namespace': namespace, 'kind': kind.value},
    )
    duration_ms = (time.perf_counter() - started) * 1000
    if duration_ms >= _SLOW_WAKE_OPERATION_SECONDS * 1000:
        logger.warning(
            'Slow durable runtime wake append namespace=%s kind=%s duration_ms=%.1f',
            namespace,
            kind.value,
            duration_ms,
            extra={
                'runtime_namespace': namespace,
                'runtime_work_kind': kind.value,
                'runtime_wake_write_ms': round(duration_ms, 1),
            },
        )


def mark_schedule_pending(session: Session, *, namespace: str) -> None:
    """Record a durable schedule event in the producer transaction."""
    if not _is_distributed_postgres(session):
        return
    session.execute(
        text(
            """
            INSERT INTO public.runtime_namespace_work AS work
                (namespace, kind, pending, generation, processed_generation, updated_at)
            VALUES (:namespace, :kind, TRUE, 1, 0, CURRENT_TIMESTAMP)
            ON CONFLICT (namespace, kind) DO UPDATE
            SET pending = TRUE,
                generation = work.generation + 1,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {'namespace': namespace, 'kind': RuntimeWorkKind.SCHEDULE.value},
    )


def list_due_schedule_namespaces(session: Session, *, limit: int = 100) -> list[tuple[str, int]]:
    """Return schedule namespaces with an event or an elapsed cron deadline."""
    if not _is_distributed_postgres(session):
        return []
    rows = session.execute(
        text(
            """
            SELECT namespace, generation
            FROM public.runtime_namespace_work
            WHERE kind = :kind
              AND (pending IS TRUE OR due_at <= CURRENT_TIMESTAMP)
            ORDER BY CASE WHEN pending IS TRUE THEN updated_at ELSE due_at END, namespace
            LIMIT :limit
            """
        ),
        {'kind': RuntimeWorkKind.SCHEDULE.value, 'limit': limit},
    ).all()
    return [(str(namespace), int(generation)) for namespace, generation in rows]


def finish_schedule_scan(
    session: Session,
    *,
    namespace: str,
    generation: int,
    due_at: datetime | None,
) -> None:
    """Acknowledge only the generation actually scanned; newer events stay pending."""
    if not _is_distributed_postgres(session):
        return
    result = session.execute(
        text(
            """
            UPDATE public.runtime_namespace_work AS work
            SET processed_generation = :generation,
                pending = (work.generation > :generation),
                due_at = :due_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE work.namespace = :namespace
              AND work.kind = :kind
              AND work.generation >= :generation
            RETURNING work.namespace
            """
        ),
        {
            'namespace': namespace,
            'kind': RuntimeWorkKind.SCHEDULE.value,
            'generation': generation,
            'due_at': due_at,
        },
    )
    if result.scalar_one_or_none() is None:
        raise RuntimeError(f'Schedule work row missing or generation invalid for namespace {namespace}')


def list_pending_namespaces(
    session: Session,
    *,
    kinds: Collection[RuntimeWorkKind] = WORKER_RECOVERY_KINDS,
) -> list[str]:
    """Return only namespaces with pending work, not the tenant registry."""
    if not _is_distributed_postgres(session):
        return []
    kind_values = [kind.value for kind in kinds]
    if not kind_values:
        return []
    state_table = RuntimeNamespaceWork.metadata.tables[RuntimeNamespaceWork.__tablename__]
    wake_table = RuntimeNamespaceWorkWake.metadata.tables[RuntimeNamespaceWorkWake.__tablename__]
    wake_namespaces = (
        select(wake_table.c.namespace, func.min(wake_table.c.created_at).label('ready_at'))
        .where(wake_table.c.kind.in_(kind_values))
        .group_by(wake_table.c.namespace)
    )
    due_namespaces = (
        select(state_table.c.namespace, func.min(state_table.c.updated_at).label('ready_at'))
        .where(state_table.c.kind.in_(kind_values))
        .where(or_(state_table.c.pending.is_(True), state_table.c.due_at <= func.statement_timestamp()))
        .group_by(state_table.c.namespace)
    )
    ready = wake_namespaces.union_all(due_namespaces).subquery()
    statement = select(ready.c.namespace).group_by(ready.c.namespace).order_by(func.min(ready.c.ready_at), ready.c.namespace)
    return [str(namespace) for namespace in session.execute(statement).scalars().all()]


def refresh_pending_work(
    session: Session,
    *,
    namespace: str,
    kind: RuntimeWorkKind,
    pending_query: str,
    due_query: str = 'SELECT NULL::timestamptz',
) -> None:
    """Refresh queue state and consume only wake records captured before its scan.

    Producers append wake rows with their durable queue changes. This method
    locks a bounded batch first, checks pending work, then deletes only that
    captured batch. A wake committed during the scan is a distinct row and
    remains visible to recovery. ``due_at`` parks leased work until expiry.
    The SQL fragments are fixed by callers and never contain request input.
    The caller owns the surrounding transaction and commit.
    """
    if not _is_distributed_postgres(session):
        return
    started = time.perf_counter()
    ensure_started = started
    state_table = RuntimeNamespaceWork.metadata.tables[RuntimeNamespaceWork.__tablename__]
    wake_table = RuntimeNamespaceWorkWake.metadata.tables[RuntimeNamespaceWorkWake.__tablename__]
    session.execute(
        text(
            """
            INSERT INTO public.runtime_namespace_work
                (namespace, kind, pending, generation, processed_generation, due_at, updated_at)
            VALUES (:namespace, :kind, FALSE, 0, 0, NULL, statement_timestamp())
            ON CONFLICT (namespace, kind) DO NOTHING
            """
        ),
        {'namespace': namespace, 'kind': kind.value},
    )
    ensure_ms = (time.perf_counter() - ensure_started) * 1000
    state_lock_started = time.perf_counter()
    session.execute(
        select(state_table.c.namespace).where(state_table.c.namespace == namespace, state_table.c.kind == kind.value).with_for_update()
    ).scalar_one()
    state_lock_ms = (time.perf_counter() - state_lock_started) * 1000
    capture_started = time.perf_counter()
    wake_ids = list(
        session.execute(
            select(wake_table.c.id)
            .where(wake_table.c.namespace == namespace, wake_table.c.kind == kind.value)
            .order_by(wake_table.c.id)
            .limit(512)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    capture_ms = (time.perf_counter() - capture_started) * 1000
    scan_started = time.perf_counter()
    state = session.execute(
        text(
            f"""
            SELECT EXISTS ({pending_query}),
                   ({due_query})
            FROM public.runtime_namespace_work AS work
            WHERE work.namespace = :namespace AND work.kind = :kind
            """
        ),
        {'namespace': namespace, 'kind': kind.value},
    ).one()
    scan_ms = (time.perf_counter() - scan_started) * 1000
    pending, due_at = state
    update_started = time.perf_counter()
    session.execute(
        text(
            """
            UPDATE public.runtime_namespace_work
            SET pending = :pending,
                due_at = CASE WHEN :pending THEN NULL ELSE CAST(:due_at AS timestamptz) END,
                updated_at = statement_timestamp()
            WHERE namespace = :namespace
              AND kind = :kind
              AND (
                  pending IS DISTINCT FROM :pending
                  OR due_at IS DISTINCT FROM CASE WHEN :pending THEN NULL ELSE CAST(:due_at AS timestamptz) END
              )
            """
        ),
        {
            'namespace': namespace,
            'kind': kind.value,
            'pending': pending,
            'due_at': due_at,
        },
    )
    update_ms = (time.perf_counter() - update_started) * 1000
    delete_started = time.perf_counter()
    if wake_ids:
        session.execute(delete(wake_table).where(wake_table.c.id.in_(wake_ids)))
    delete_ms = (time.perf_counter() - delete_started) * 1000
    total_ms = (time.perf_counter() - started) * 1000
    if max(ensure_ms, state_lock_ms, capture_ms, scan_ms, update_ms, delete_ms, total_ms) >= _SLOW_WAKE_OPERATION_SECONDS * 1000:
        logger.warning(
            'Slow durable runtime wake refresh namespace=%s kind=%s '
            'ensure_ms=%.1f state_lock_ms=%.1f wake_capture_ms=%.1f queue_scan_ms=%.1f '
            'state_update_ms=%.1f wake_delete_ms=%.1f total_ms=%.1f',
            namespace,
            kind.value,
            ensure_ms,
            state_lock_ms,
            capture_ms,
            scan_ms,
            update_ms,
            delete_ms,
            total_ms,
            extra={
                'runtime_namespace': namespace,
                'runtime_work_kind': kind.value,
                'runtime_wake_ensure_ms': round(ensure_ms, 1),
                'runtime_wake_state_lock_ms': round(state_lock_ms, 1),
                'runtime_wake_capture_ms': round(capture_ms, 1),
                'runtime_wake_queue_scan_ms': round(scan_ms, 1),
                'runtime_wake_state_update_ms': round(update_ms, 1),
                'runtime_wake_delete_ms': round(delete_ms, 1),
                'runtime_wake_refresh_ms': round(total_ms, 1),
            },
        )
