"""index durable compute requests by their engine identity.

Revision ID: 0003_engine_request_identity
Revises: 0002_runtime_tenant
Create Date: 2026-09-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003_engine_request_identity'
down_revision: str | Sequence[str] | None = '0002_runtime_tenant'
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
    op.add_column('compute_requests', sa.Column('engine_scope', sa.Integer(), nullable=True))
    op.add_column('compute_requests', sa.Column('engine_reuse_policy', sa.Integer(), nullable=True))
    op.add_column('compute_requests', sa.Column('engine_resource_id', sa.String(), nullable=True))
    op.create_index(
        'ix_compute_requests_engine_identity',
        'compute_requests',
        ['namespace', 'status', 'engine_scope', 'engine_reuse_policy', 'engine_resource_id'],
    )


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_compute_requests_engine_identity', table_name='compute_requests')
    op.drop_column('compute_requests', 'engine_resource_id')
    op.drop_column('compute_requests', 'engine_reuse_policy')
    op.drop_column('compute_requests', 'engine_scope')
