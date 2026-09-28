"""persist one-use MCP confirmation actions across API workers.

Revision ID: 0010_mcp_pending_actions
Revises: 0009_runtime_lease_wake_due
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0010_mcp_pending_actions'
down_revision: str | Sequence[str] | None = '0009_runtime_lease_wake_due'
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
    if _scope() != 'public':
        return
    op.create_table(
        'mcp_pending_actions',
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('tool_id', sa.String(), nullable=False),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('args_encrypted', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_index('ix_mcp_pending_actions_expires_at', 'mcp_pending_actions', ['expires_at'])


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_mcp_pending_actions_expires_at', table_name='mcp_pending_actions')
    op.drop_table('mcp_pending_actions')
