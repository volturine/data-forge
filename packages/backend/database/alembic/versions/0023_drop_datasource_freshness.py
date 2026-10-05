"""Drop the unused datasource freshness threshold.

Revision ID: 0023_drop_ds_freshness
Revises: 0022_telegram_part_receipts
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0023_drop_ds_freshness'
down_revision: str | Sequence[str] | None = '0022_telegram_part_receipts'
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
    op.drop_column('datasources', 'freshness_threshold_minutes')


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.add_column('datasources', sa.Column('freshness_threshold_minutes', sa.Integer(), nullable=True))
