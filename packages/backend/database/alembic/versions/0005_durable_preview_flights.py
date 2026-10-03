"""persist exact preview single-flight ownership.

Revision ID: 0005_durable_preview_flights
Revises: 0004_compute_request_datasources
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005_durable_preview_flights'
down_revision: str | Sequence[str] | None = '0004_compute_request_datasources'
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
    op.create_table(
        'compute_request_preview_flights',
        sa.Column('preview_key', sa.String(), nullable=False),
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['request_id'], ['compute_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('preview_key'),
        sa.UniqueConstraint('request_id', name='uq_compute_request_preview_flights_request_id'),
    )
    op.create_index('ix_compute_request_preview_flights_request_id', 'compute_request_preview_flights', ['request_id'])
    op.create_index('ix_compute_request_preview_flights_expires_at', 'compute_request_preview_flights', ['expires_at'])


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_compute_request_preview_flights_expires_at', table_name='compute_request_preview_flights')
    op.drop_index('ix_compute_request_preview_flights_request_id', table_name='compute_request_preview_flights')
    op.drop_table('compute_request_preview_flights')
