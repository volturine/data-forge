"""store compute request envelopes as protobuf bytes.

Revision ID: 0004_compute_envelopes_tenant
Revises: 0002_runtime_tenant
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004_compute_envelopes_tenant'
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
    op.execute(sa.text('DELETE FROM compute_requests'))
    op.drop_column('compute_requests', 'response_json')
    op.drop_column('compute_requests', 'request_json')
    op.add_column('compute_requests', sa.Column('command_envelope', sa.LargeBinary(), nullable=False))
    op.add_column('compute_requests', sa.Column('response_envelope', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.execute(sa.text('DELETE FROM compute_requests'))
    op.drop_column('compute_requests', 'response_envelope')
    op.drop_column('compute_requests', 'command_envelope')
    op.add_column('compute_requests', sa.Column('request_json', sa.JSON(), nullable=False))
    op.add_column('compute_requests', sa.Column('response_json', sa.JSON(), nullable=True))
