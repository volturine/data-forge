"""add datasource description.

Revision ID: 0003_tenant_ds_desc
Revises: 0002_runtime_tenant
Create Date: 2026-04-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003_tenant_ds_desc'
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


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_column('datasources', 'description')
