"""durable indexed wake state for scheduled work.

Revision ID: 0008_schedule_wake_due
Revises: 0006_runtime_namespace_work
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008_schedule_wake_due'
down_revision: str | Sequence[str] | None = '0006_runtime_namespace_work'
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
    op.add_column('runtime_namespace_work', sa.Column('generation', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('runtime_namespace_work', sa.Column('processed_generation', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('runtime_namespace_work', sa.Column('due_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        'ix_runtime_namespace_work_due_at',
        'runtime_namespace_work',
        ['kind', 'due_at', 'namespace'],
        postgresql_where=sa.text("kind = 'schedule' AND due_at IS NOT NULL"),
    )
    op.execute(
        """
        DO $$
        DECLARE
            namespace_name text;
            schema_name text;
        BEGIN
            FOR namespace_name IN SELECT name FROM public.runtime_namespaces LOOP
                schema_name := CASE WHEN namespace_name = 'public' THEN 'df$tenant$public' ELSE namespace_name END;
                IF to_regclass(format('%I.schedules', schema_name)) IS NOT NULL THEN
                    EXECUTE format($statement$
                        INSERT INTO public.runtime_namespace_work AS work
                            (namespace, kind, pending, generation, processed_generation, due_at, updated_at)
                        SELECT %L, 'schedule', TRUE, 1, 0,
                            (
                                SELECT min(next_run)
                                FROM %I.schedules
                                WHERE enabled IS TRUE
                                  AND depends_on IS NULL
                                  AND trigger_on_datasource_id IS NULL
                            ),
                            CURRENT_TIMESTAMP
                        WHERE EXISTS (
                            SELECT 1 FROM %I.schedules WHERE enabled IS TRUE
                        )
                        ON CONFLICT (namespace, kind) DO UPDATE
                        SET pending = TRUE,
                            generation = work.generation + 1,
                            updated_at = EXCLUDED.updated_at
                    $statement$, namespace_name, schema_name, schema_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_runtime_namespace_work_due_at', table_name='runtime_namespace_work')
    op.drop_column('runtime_namespace_work', 'due_at')
    op.drop_column('runtime_namespace_work', 'processed_generation')
    op.drop_column('runtime_namespace_work', 'generation')
