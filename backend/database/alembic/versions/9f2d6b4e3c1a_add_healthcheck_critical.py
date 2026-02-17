"""Add critical flag to healthchecks.

Revision ID: 9f2d6b4e3c1a
Revises: 8b1c9d2f1a3e
Create Date: 2026-02-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '9f2d6b4e3c1a'
down_revision: str | None = '8b1c9d2f1a3e'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'healthchecks',
        sa.Column('critical', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('healthchecks', 'critical')
