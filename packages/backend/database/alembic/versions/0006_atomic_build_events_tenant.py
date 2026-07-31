"""allocate build event sequences atomically.

Revision ID: 0006_atomic_build_events_tenant
Revises: 0005_fenced_build_jobs_tenant
Create Date: 2026-07-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006_atomic_build_events_tenant'
down_revision: str | Sequence[str] | None = '0005_fenced_build_jobs_tenant'
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
    op.add_column('build_runs', sa.Column('next_event_sequence', sa.Integer(), server_default='1', nullable=False))
    op.execute(
        sa.text(
            """
            UPDATE build_runs
            SET next_event_sequence = COALESCE(
                (
                    SELECT MAX(build_events.sequence) + 1
                    FROM build_events
                    WHERE build_events.build_id = build_runs.id
                ),
                1
            )
            """
        )
    )
    op.alter_column('build_runs', 'next_event_sequence', server_default=None)


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_column('build_runs', 'next_event_sequence')
