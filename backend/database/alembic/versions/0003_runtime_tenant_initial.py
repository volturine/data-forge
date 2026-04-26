"""runtime tenant initialization additions.

Revision ID: 0003_runtime_tenant_initial
Revises: 0002_runtime_tenant
Create Date: 2026-04-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003_runtime_tenant_initial'
down_revision: str | Sequence[str] | None = '0002_runtime_tenant'
branch_labels: str | Sequence[str] | None = ('tenant',)
depends_on: str | Sequence[str] | None = None


def _scope() -> str:
    config = op.get_context().config
    if config is None:
        return 'public'
    return str(config.attributes.get('runtime_scope', 'public'))


def upgrade() -> None:
    if _scope() != 'tenant':
        return
    op.add_column('datasources', sa.Column('description', sa.String(length=4000), nullable=True))
    op.create_table(
        'datasource_column_metadata',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.Column('column_name', sa.String(), nullable=False),
        sa.Column('description', sa.String(length=2000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['datasource_id'], ['datasources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('datasource_id', 'column_name', name='uq_datasource_column_metadata_name'),
    )
    op.create_index('ix_datasource_column_metadata_datasource_id', 'datasource_column_metadata', ['datasource_id'])


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_datasource_column_metadata_datasource_id', table_name='datasource_column_metadata')
    op.drop_table('datasource_column_metadata')
    op.drop_column('datasources', 'description')
