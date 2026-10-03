"""index schedules by enabled state and next due time.

Revision ID: 0007_schedule_due_index
Revises: 0005_durable_preview_flights
Create Date: 2026-09-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = '0007_schedule_due_index'
down_revision: str | Sequence[str] | None = '0005_durable_preview_flights'
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
    if _scope() != 'tenant':
        return
    op.create_index('ix_schedules_enabled_next_run', 'schedules', ['enabled', 'next_run'])


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_schedules_enabled_next_run', table_name='schedules')
