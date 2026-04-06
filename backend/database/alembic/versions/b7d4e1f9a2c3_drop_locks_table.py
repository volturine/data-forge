"""Drop locks table.

Revision ID: b7d4e1f9a2c3
Revises: 2c1d3ab4f1b2
Create Date: 2026-03-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b7d4e1f9a2c3'
down_revision: str | None = '2c1d3ab4f1b2'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table('locks')


def downgrade() -> None:
    op.create_table(
        'locks',
        sa.Column('resource_id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=False),
        sa.Column('client_signature', sa.String(), nullable=False),
        sa.Column('lock_token', sa.String(), nullable=False),
        sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('resource_id'),
        sa.UniqueConstraint('lock_token'),
    )
