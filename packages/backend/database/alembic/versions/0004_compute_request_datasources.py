"""materialize compute-request datasource dependencies.

Revision ID: 0004_compute_request_datasources
Revises: 0003_engine_request_identity
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004_compute_request_datasources'
down_revision: str | Sequence[str] | None = '0003_engine_request_identity'
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
        'compute_request_datasources',
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['compute_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('request_id', 'datasource_id'),
    )
    op.create_index(
        'ix_compute_request_datasources_datasource_id',
        'compute_request_datasources',
        ['datasource_id'],
    )


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_compute_request_datasources_datasource_id', table_name='compute_request_datasources')
    op.drop_table('compute_request_datasources')
