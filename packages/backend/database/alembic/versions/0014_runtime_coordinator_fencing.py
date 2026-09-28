"""add a durable fencing generation for the runtime coordinator.

Revision ID: 0014_runtime_coordinator_fencing
Revises: 0013_runtime_work_wakes
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0014_runtime_coordinator_fencing'
down_revision: str | Sequence[str] | None = '0013_runtime_work_wakes'
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
        'runtime_coordinator_state',
        sa.Column('singleton_id', sa.Integer(), nullable=False),
        sa.Column('generation', sa.BigInteger(), server_default='0', nullable=False),
        sa.CheckConstraint('singleton_id = 1', name='ck_runtime_coordinator_singleton'),
        sa.PrimaryKeyConstraint('singleton_id'),
    )
    op.execute('INSERT INTO public.runtime_coordinator_state (singleton_id, generation) VALUES (1, 0)')


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_table('runtime_coordinator_state')
