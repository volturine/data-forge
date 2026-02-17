"""add analysis versions and datasource lineage.

Revision ID: 7f3c2a1b9e10
Revises: f3a9c1d2b4e5
Create Date: 2026-02-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f3c2a1b9e10'
down_revision: str | Sequence[str] | None = 'f3a9c1d2b4e5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('datasources', sa.Column('created_by_analysis_id', sa.String(), nullable=True))
    op.create_table(
        'analysis_versions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('pipeline_definition', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('analysis_versions')
    op.drop_column('datasources', 'created_by_analysis_id')
