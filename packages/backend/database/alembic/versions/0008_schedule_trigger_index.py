"""index build completion lookups used by datasource-triggered schedules.

Revision ID: 0008_schedule_trigger_index
Revises: 0007_schedule_due_index
Create Date: 2026-09-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = '0008_schedule_trigger_index'
down_revision: str | Sequence[str] | None = '0007_schedule_due_index'
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
    op.create_index('ix_build_runs_datasource_completion', 'build_runs', ['current_datasource_id', 'status', 'completed_at'])
    op.create_index('ix_build_runs_output_completion', 'build_runs', ['current_output_id', 'status', 'completed_at'])


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_build_runs_output_completion', table_name='build_runs')
    op.drop_index('ix_build_runs_datasource_completion', table_name='build_runs')
