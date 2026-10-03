"""Move runtime wake state to generation-fenced namespace markers.

Revision ID: 0018_runtime_work_generations
Revises: 0016_telegram_runtime, 0017_compute_source_index
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0018_runtime_work_generations'
down_revision: str | Sequence[str] | None = ('0016_telegram_runtime', '0017_compute_source_index')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']


def _scope() -> str:
    context = op.get_context()
    config = context.config
    if config is None:
        return 'public'
    return str(context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def upgrade() -> None:
    if _scope() != 'public':
        return
    op.execute(
        sa.text(
            """
            INSERT INTO public.runtime_namespace_work AS work
                (namespace, kind, pending, generation, processed_generation, due_at, updated_at)
            SELECT namespace, kind, TRUE, count(*), 0, NULL, statement_timestamp()
            FROM public.runtime_namespace_work_wakes
            GROUP BY namespace, kind
            ON CONFLICT (namespace, kind) DO UPDATE
            SET pending = TRUE,
                generation = work.generation + EXCLUDED.generation,
                due_at = NULL,
                updated_at = statement_timestamp()
            """
        )
    )
    op.drop_index('ix_runtime_namespace_work_wakes_namespace_kind_id', table_name='runtime_namespace_work_wakes')
    op.drop_index('ix_runtime_namespace_work_wakes_kind_created', table_name='runtime_namespace_work_wakes')
    op.drop_table('runtime_namespace_work_wakes')


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.create_table(
        'runtime_namespace_work_wakes',
        sa.Column('id', sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('statement_timestamp()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_runtime_namespace_work_wakes_kind_created',
        'runtime_namespace_work_wakes',
        ['kind', 'created_at', 'namespace'],
    )
    op.create_index(
        'ix_runtime_namespace_work_wakes_namespace_kind_id',
        'runtime_namespace_work_wakes',
        ['namespace', 'kind', 'id'],
    )
