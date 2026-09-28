"""scope durable preview flights by namespace.

Revision ID: 0011_namespace_preview_flights
Revises: 0008_schedule_trigger_index
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0011_namespace_preview_flights'
down_revision: str | Sequence[str] | None = '0008_schedule_trigger_index'
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
    op.add_column('compute_request_preview_flights', sa.Column('namespace', sa.String(), nullable=True))
    op.execute(
        sa.text(
            'UPDATE compute_request_preview_flights AS flight '
            'SET namespace = request.namespace '
            'FROM compute_requests AS request '
            'WHERE request.id = flight.request_id'
        )
    )
    op.alter_column('compute_request_preview_flights', 'namespace', nullable=False)
    op.drop_constraint('compute_request_preview_flights_pkey', 'compute_request_preview_flights', type_='primary')
    op.create_primary_key(
        'pk_compute_request_preview_flights',
        'compute_request_preview_flights',
        ['namespace', 'preview_key'],
    )


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_constraint('pk_compute_request_preview_flights', 'compute_request_preview_flights', type_='primary')
    op.create_primary_key(None, 'compute_request_preview_flights', ['preview_key'])
    op.drop_column('compute_request_preview_flights', 'namespace')
