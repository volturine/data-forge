"""Add schedules for lineage.

Revision ID: 2c1d3ab4f1b2
Revises: 8b1c9d2f1a3e
Create Date: 2026-02-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '2c1d3ab4f1b2'
down_revision: str | None = '8b1c9d2f1a3e'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'schedules',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=False, index=True),
        sa.Column('cron_expression', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_run', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_schedules_analysis_id', 'schedules', ['analysis_id'])


def downgrade() -> None:
    op.drop_index('ix_schedules_analysis_id', table_name='schedules')
    op.drop_table('schedules')
