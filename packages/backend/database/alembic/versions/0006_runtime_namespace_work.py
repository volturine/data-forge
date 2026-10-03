"""durable pending-work index for runtime recovery.

Revision ID: 0006_runtime_namespace_work
Revises: 0001_runtime_public
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006_runtime_namespace_work'
down_revision: str | Sequence[str] | None = '0001_runtime_public'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']


def _scope() -> str:
    migration_context = op.get_context()
    config = migration_context.config
    if config is None:
        return 'public'
    return str(migration_context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def upgrade() -> None:
    if _scope() != 'public':
        return
    op.create_table(
        'runtime_namespace_work',
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('pending', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('namespace', 'kind'),
    )
    op.create_index(
        'ix_runtime_namespace_work_pending',
        'runtime_namespace_work',
        ['kind', 'pending', 'updated_at', 'namespace'],
    )
    # Preserve work that was already durable before this index existed. This
    # is intentionally a one-time migration scan over the namespace registry;
    # hot-path recovery uses the indexed table and never repeats this fan-out.
    op.execute(
        """
        DO $$
        DECLARE
            namespace_name text;
            schema_name text;
        BEGIN
            FOR namespace_name IN SELECT name FROM public.runtime_namespaces LOOP
                schema_name := CASE WHEN namespace_name = 'public' THEN 'df$tenant$public' ELSE namespace_name END;
                IF to_regclass(format('%I.runtime_outbox_events', schema_name)) IS NOT NULL THEN
                    EXECUTE format($statement$
                        INSERT INTO public.runtime_namespace_work (namespace, kind, pending, updated_at)
                        SELECT %L, 'outbox', TRUE, CURRENT_TIMESTAMP
                        WHERE EXISTS (
                            SELECT 1 FROM %I.runtime_outbox_events
                            WHERE status IN ('pending', 'failed', 'dispatching')
                        )
                        ON CONFLICT (namespace, kind) DO UPDATE
                        SET pending = TRUE, updated_at = EXCLUDED.updated_at
                    $statement$, namespace_name, schema_name);
                END IF;
                IF to_regclass(format('%I.build_jobs', schema_name)) IS NOT NULL THEN
                    EXECUTE format($statement$
                        INSERT INTO public.runtime_namespace_work (namespace, kind, pending, updated_at)
                        SELECT %L, 'build', TRUE, CURRENT_TIMESTAMP
                        WHERE EXISTS (
                            SELECT 1 FROM %I.build_jobs
                            WHERE status = 'queued'
                               OR (
                                    status IN ('leased', 'running')
                                    AND (lease_owner IS NULL OR lease_expires_at <= CURRENT_TIMESTAMP)
                                    AND attempts < max_attempts
                               )
                        )
                        ON CONFLICT (namespace, kind) DO UPDATE
                        SET pending = TRUE, updated_at = EXCLUDED.updated_at
                    $statement$, namespace_name, schema_name);
                END IF;
                IF to_regclass(format('%I.compute_requests', schema_name)) IS NOT NULL THEN
                    EXECUTE format($statement$
                        INSERT INTO public.runtime_namespace_work (namespace, kind, pending, updated_at)
                        SELECT %L, 'compute', TRUE, CURRENT_TIMESTAMP
                        WHERE EXISTS (
                            SELECT 1 FROM %I.compute_requests
                            WHERE status IN (1, 2)
                        )
                        ON CONFLICT (namespace, kind) DO UPDATE
                        SET pending = TRUE, updated_at = EXCLUDED.updated_at
                    $statement$, namespace_name, schema_name);
                END IF;
                IF to_regclass(format('%I.datasources', schema_name)) IS NOT NULL THEN
                    EXECUTE format($statement$
                        INSERT INTO public.runtime_namespace_work (namespace, kind, pending, updated_at)
                        SELECT %L, 'datasource_delete', TRUE, CURRENT_TIMESTAMP
                        WHERE EXISTS (
                            SELECT 1 FROM %I.datasources
                            WHERE is_pending_delete IS TRUE
                        )
                        ON CONFLICT (namespace, kind) DO UPDATE
                        SET pending = TRUE, updated_at = EXCLUDED.updated_at
                    $statement$, namespace_name, schema_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_runtime_namespace_work_pending', table_name='runtime_namespace_work')
    op.drop_table('runtime_namespace_work')
