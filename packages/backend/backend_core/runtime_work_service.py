from __future__ import annotations

import logging
import time
from collections.abc import Collection
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select, text
from sqlmodel import Session

from backend_core.config import settings
from backend_core.persistence.runtime_events.models import RuntimeNamespaceWorkWake
from backend_core.sqlmodel_typing import col

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
_WAKE_BATCH_SIZE = 256


def _is_distributed_postgres(session: Session) -> bool:
    bind = session.get_bind()
    return settings.distributed_runtime_enabled and getattr(getattr(bind, 'dialect', None), 'name', None) == 'postgresql'


def append_wake(session: Session, *, namespace: str, kind: RuntimeWorkKind) -> int | None:
    """Append a durable wake pointer in the work transaction without locking the projection."""
    if not _is_distributed_postgres(session):
        return None
    started = time.perf_counter()
    wake_id = session.execute(
        text(
            """
            INSERT INTO public.runtime_namespace_work_wakes (namespace, kind)
            VALUES (:namespace, :kind)
            RETURNING id
            """
        ),
        {'namespace': namespace, 'kind': kind.value},
    ).scalar_one()
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
                'runtime_work_wake_append_ms': round(duration_ms, 1),
            },
        )
    return int(wake_id)


def mark_schedule_pending(session: Session, *, namespace: str) -> None:
    """Record a durable schedule event in the producer transaction."""
    append_wake(session, namespace=namespace, kind=RuntimeWorkKind.SCHEDULE)


def list_due_schedule_namespaces(session: Session, *, limit: int = 100) -> list[tuple[str, int, list[int]]]:
    """Return due namespaces and exact bounded schedule wake IDs captured for each."""
    if not _is_distributed_postgres(session):
        return []
    rows = session.execute(
        text(
            """
            SELECT candidate.namespace,
                   COALESCE(work.generation, 0),
                   COALESCE(captured.ids, ARRAY[]::bigint[])
            FROM (
                SELECT namespace
                FROM public.runtime_namespace_work
                WHERE kind = :kind AND (pending IS TRUE OR due_at <= statement_timestamp())
                UNION
                SELECT namespace
                FROM public.runtime_namespace_work_wakes
                WHERE kind = :kind
            ) AS candidate
            LEFT JOIN public.runtime_namespace_work AS work
              ON work.namespace = candidate.namespace AND work.kind = :kind
            LEFT JOIN LATERAL (
                SELECT array_agg(wake.id ORDER BY wake.id) AS ids
                FROM (
                    SELECT id
                    FROM public.runtime_namespace_work_wakes
                    WHERE namespace = candidate.namespace AND kind = :kind
                    ORDER BY id
                    LIMIT :wake_limit
                ) AS wake
            ) AS captured ON TRUE
            ORDER BY CASE
                WHEN work.pending IS TRUE THEN work.updated_at
                WHEN work.due_at <= statement_timestamp() THEN work.due_at
                ELSE COALESCE((
                    SELECT min(created_at)
                    FROM public.runtime_namespace_work_wakes
                    WHERE namespace = candidate.namespace AND kind = :kind
                ), statement_timestamp())
            END, candidate.namespace
            LIMIT :limit
            """
        ),
        {'kind': RuntimeWorkKind.SCHEDULE.value, 'limit': limit, 'wake_limit': _WAKE_BATCH_SIZE},
    ).all()
    return [(str(namespace), int(generation), [int(wake_id) for wake_id in wake_ids]) for namespace, generation, wake_ids in rows]


def finish_schedule_scan(
    session: Session,
    *,
    namespace: str,
    generation: int,
    due_at: datetime | None,
    wake_ids: Collection[int] = (),
) -> None:
    """Acknowledge captured IDs and CAS schedule state after the scan."""
    if not _is_distributed_postgres(session):
        return
    session.execute(
        text(
            """
            INSERT INTO public.runtime_namespace_work
                (namespace, kind, pending, generation, processed_generation, due_at, updated_at)
            VALUES (:namespace, :kind, FALSE, 0, 0, NULL, statement_timestamp())
            ON CONFLICT (namespace, kind) DO NOTHING
            """
        ),
        {'namespace': namespace, 'kind': RuntimeWorkKind.SCHEDULE.value},
    )
    if wake_ids:
        session.execute(
            text(
                """
                DELETE FROM public.runtime_namespace_work_wakes
                WHERE namespace = :namespace AND kind = :kind AND id = ANY(CAST(:wake_ids AS bigint[]))
                """
            ),
            {'namespace': namespace, 'kind': RuntimeWorkKind.SCHEDULE.value, 'wake_ids': list(wake_ids)},
        )
    result = session.execute(
        text(
            """
            UPDATE public.runtime_namespace_work AS work
            SET generation = work.generation + 1,
                processed_generation = work.generation + 1,
                pending = EXISTS (
                    SELECT 1 FROM public.runtime_namespace_work_wakes AS wake
                    WHERE wake.namespace = work.namespace AND wake.kind = work.kind
                ),
                due_at = :due_at,
                updated_at = statement_timestamp()
            WHERE work.namespace = :namespace
              AND work.kind = :kind
              AND work.generation = :generation
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
        raise RuntimeError(f'Schedule work changed while scanning namespace {namespace}')


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
    rows = session.execute(
        text(
            """
            SELECT namespace, min(priority_at) AS priority_at
            FROM (
                SELECT namespace,
                       CASE WHEN pending IS TRUE THEN updated_at ELSE due_at END AS priority_at
                FROM public.runtime_namespace_work
                WHERE kind = ANY(CAST(:kinds AS text[]))
                  AND (pending IS TRUE OR due_at <= statement_timestamp())
                UNION ALL
                SELECT namespace, min(created_at) AS priority_at
                FROM public.runtime_namespace_work_wakes
                WHERE kind = ANY(CAST(:kinds AS text[]))
                GROUP BY namespace
            ) AS pending_work
            GROUP BY namespace
            ORDER BY priority_at, namespace
            """
        ),
        {'kinds': kind_values},
    ).all()
    return [str(namespace) for namespace, _priority_at in rows]


def refresh_pending_work(
    session: Session,
    *,
    namespace: str,
    kind: RuntimeWorkKind,
    pending_query: str,
    due_query: str = 'SELECT NULL::timestamptz',
) -> None:
    """Refresh one queue projection and acknowledge only exact captured wake IDs.

    Producers append without touching the marker. Consumers capture a bounded
    ID set, snapshot the targeted queue, CAS the shared projection, then delete
    only those captured rows in the same transaction. Later commits remain
    discoverable even if their sequence values are lower.
    """
    if not _is_distributed_postgres(session):
        return
    started = time.perf_counter()
    captured_ids = [
        int(wake_id)
        for wake_id in session.execute(
            select(col(RuntimeNamespaceWorkWake.id))
            .where(col(RuntimeNamespaceWorkWake.namespace) == namespace, col(RuntimeNamespaceWorkWake.kind) == kind.value)
            .order_by(col(RuntimeNamespaceWorkWake.id))
            .limit(_WAKE_BATCH_SIZE)
        ).scalars()
    ]
    scan_started = time.perf_counter()
    state = session.execute(
        text(
            f"""
            SELECT COALESCE(work.generation, 0),
                   EXISTS ({pending_query}),
                   ({due_query})
            FROM (SELECT 1) AS snapshot
            LEFT JOIN public.runtime_namespace_work AS work
              ON work.namespace = :namespace AND work.kind = :kind
            """
        ),
        {'namespace': namespace, 'kind': kind.value},
    ).one()
    scan_ms = (time.perf_counter() - scan_started) * 1000
    generation, pending, due_at = state
    update_started = time.perf_counter()
    updated_namespace = session.execute(
        text(
            """
            INSERT INTO public.runtime_namespace_work AS work
                (namespace, kind, pending, generation, processed_generation, due_at, updated_at)
            VALUES (
                :namespace,
                :kind,
                :pending,
                :generation + 1,
                :generation + 1,
                CASE WHEN :pending THEN NULL ELSE CAST(:due_at AS timestamptz) END,
                statement_timestamp()
            )
            ON CONFLICT (namespace, kind) DO UPDATE
            SET pending = EXCLUDED.pending,
                generation = work.generation + 1,
                processed_generation = EXCLUDED.processed_generation,
                due_at = EXCLUDED.due_at,
                updated_at = EXCLUDED.updated_at
            WHERE work.generation = :generation
            RETURNING namespace
            """
        ),
        {
            'namespace': namespace,
            'kind': kind.value,
            'generation': generation,
            'pending': pending,
            'due_at': due_at,
        },
    ).scalar_one_or_none()
    if updated_namespace is not None and captured_ids:
        session.execute(
            text(
                """
                DELETE FROM public.runtime_namespace_work_wakes
                WHERE namespace = :namespace AND kind = :kind AND id = ANY(CAST(:wake_ids AS bigint[]))
                """
            ),
            {'namespace': namespace, 'kind': kind.value, 'wake_ids': captured_ids},
        )
    update_ms = (time.perf_counter() - update_started) * 1000
    total_ms = (time.perf_counter() - started) * 1000
    if max(scan_ms, update_ms, total_ms) >= _SLOW_WAKE_OPERATION_SECONDS * 1000:
        logger.warning(
            'Slow durable runtime work refresh namespace=%s kind=%s '
            'queue_snapshot_ms=%.1f state_update_ms=%.1f '
            'snapshot_generation=%s applied=%s total_ms=%.1f',
            namespace,
            kind.value,
            scan_ms,
            update_ms,
            generation,
            updated_namespace is not None,
            total_ms,
            extra={
                'runtime_namespace': namespace,
                'runtime_work_kind': kind.value,
                'runtime_work_snapshot_ms': round(scan_ms, 1),
                'runtime_work_state_update_ms': round(update_ms, 1),
                'runtime_work_snapshot_generation': generation,
                'runtime_work_snapshot_applied': updated_namespace is not None,
                'runtime_work_refresh_ms': round(total_ms, 1),
            },
        )
