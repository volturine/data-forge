"""index lease deadlines used by runtime recovery.

Revision ID: 0009_runtime_lease_wake_due
Revises: 0008_schedule_wake_due
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0009_runtime_lease_wake_due'
down_revision: str | Sequence[str] | None = '0008_schedule_wake_due'
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
    op.drop_index('ix_runtime_namespace_work_due_at', table_name='runtime_namespace_work')
    op.create_index(
        'ix_runtime_namespace_work_due_at',
        'runtime_namespace_work',
        ['kind', 'due_at', 'namespace'],
        postgresql_where=sa.text('due_at IS NOT NULL'),
    )


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_runtime_namespace_work_due_at', table_name='runtime_namespace_work')
    op.create_index(
        'ix_runtime_namespace_work_due_at',
        'runtime_namespace_work',
        ['kind', 'due_at', 'namespace'],
        postgresql_where=sa.text("kind = 'schedule' AND due_at IS NOT NULL"),
    )
