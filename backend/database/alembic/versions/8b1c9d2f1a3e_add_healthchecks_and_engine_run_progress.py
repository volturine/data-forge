"""Add healthchecks and engine run progress.

Revision ID: 8b1c9d2f1a3e
Revises: 7f3c2a1b9e10
Create Date: 2026-02-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '8b1c9d2f1a3e'
down_revision: str | None = '7f3c2a1b9e10'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'healthchecks',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False, index=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('check_type', sa.String(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_healthchecks_datasource_id', 'healthchecks', ['datasource_id'])

    op.create_table(
        'healthcheck_results',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('healthcheck_id', sa.String(), nullable=False, index=True),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_healthcheck_results_healthcheck_id', 'healthcheck_results', ['healthcheck_id'])

    op.add_column('engine_runs', sa.Column('step_timings', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('engine_runs', sa.Column('query_plan', sa.String(), nullable=True))
    op.add_column('engine_runs', sa.Column('progress', sa.Float(), nullable=False, server_default='0'))
    op.add_column('engine_runs', sa.Column('current_step', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('engine_runs', 'current_step')
    op.drop_column('engine_runs', 'progress')
    op.drop_column('engine_runs', 'query_plan')
    op.drop_column('engine_runs', 'step_timings')

    op.drop_index('ix_healthcheck_results_healthcheck_id', table_name='healthcheck_results')
    op.drop_table('healthcheck_results')

    op.drop_index('ix_healthchecks_datasource_id', table_name='healthchecks')
    op.drop_table('healthchecks')
