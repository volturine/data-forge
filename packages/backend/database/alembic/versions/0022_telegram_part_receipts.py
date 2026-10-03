"""Persist per-part progress for multi-request Telegram deliveries.

Revision ID: 0022_telegram_part_receipts
Revises: 0021_cleanup_catalog_idx
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0022_telegram_part_receipts'
down_revision: str | Sequence[str] | None = '0021_cleanup_catalog_idx'
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
        'notification_delivery_part_receipts',
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('part_key', sa.String(), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['runtime_outbox_events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('event_id', 'part_key'),
    )


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_table('notification_delivery_part_receipts')
