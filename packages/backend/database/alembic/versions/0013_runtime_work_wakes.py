"""replace hot namespace wake updates with append-only wake records.

Revision ID: 0013_runtime_work_wakes
Revises: 0010_mcp_pending_actions
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0013_runtime_work_wakes'
down_revision: str | Sequence[str] | None = '0010_mcp_pending_actions'
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


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_runtime_namespace_work_wakes_namespace_kind_id', table_name='runtime_namespace_work_wakes')
    op.drop_index('ix_runtime_namespace_work_wakes_kind_created', table_name='runtime_namespace_work_wakes')
    op.drop_table('runtime_namespace_work_wakes')
