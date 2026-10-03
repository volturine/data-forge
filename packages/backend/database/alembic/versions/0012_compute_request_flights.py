"""generalize durable preview flights to exact compute-request flights.

Revision ID: 0012_compute_request_flights
Revises: 0011_namespace_preview_flights
Create Date: 2026-09-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = '0012_compute_request_flights'
down_revision: str | Sequence[str] | None = '0011_namespace_preview_flights'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'upgrade', 'downgrade']


def _scope() -> str:
    migration_context = op.get_context()
    config = migration_context.config
    if config is None:
        return 'public'
    return str(migration_context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def upgrade() -> None:
    if _scope() != 'tenant':
        return
    op.rename_table('compute_request_preview_flights', 'compute_request_flights')
    op.alter_column('compute_request_flights', 'preview_key', new_column_name='flight_key')


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.alter_column('compute_request_flights', 'flight_key', new_column_name='preview_key')
    op.rename_table('compute_request_flights', 'compute_request_preview_flights')
