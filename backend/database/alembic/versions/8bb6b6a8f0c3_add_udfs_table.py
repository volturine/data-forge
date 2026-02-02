"""add udfs table.

Revision ID: 8bb6b6a8f0c3
Revises: a7fc1ff5a710
Create Date: 2026-02-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8bb6b6a8f0c3'
down_revision: str | Sequence[str] | None = 'a7fc1ff5a710'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'udfs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('signature', sa.JSON(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('udfs')
