"""Restore append-only durable runtime wake pointers.

Revision ID: 0020_runtime_wakes
Revises: 0018_runtime_work_generations
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0020_runtime_wakes'
down_revision: str | Sequence[str] | None = '0018_runtime_work_generations'
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
    # 0018 already removed the old journal. Marker pending/due state remains
    # authoritative for recovery while this fresh append-only journal handles
    # all new work without producer-side marker locks.
    op.create_table(
        'runtime_namespace_work_wakes',
        sa.Column('id', sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('statement_timestamp()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_runtime_namespace_work_wakes_kind_namespace_id',
        'runtime_namespace_work_wakes',
        ['kind', 'namespace', 'id'],
    )
    op.create_index(
        'ix_runtime_namespace_work_wakes_namespace_kind_id',
        'runtime_namespace_work_wakes',
        ['namespace', 'kind', 'id'],
    )


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_runtime_namespace_work_wakes_namespace_kind_id', table_name='runtime_namespace_work_wakes')
    op.drop_index('ix_runtime_namespace_work_wakes_kind_namespace_id', table_name='runtime_namespace_work_wakes')
    op.drop_table('runtime_namespace_work_wakes')
