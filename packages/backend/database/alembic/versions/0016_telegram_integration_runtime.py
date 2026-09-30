"""Persist Telegram polling offsets and coordinator-owned detection requests.

Revision ID: 0016_telegram_runtime
Revises: 0015_durable_chat_turns
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0016_telegram_runtime'
down_revision: str | Sequence[str] | None = '0015_durable_chat_turns'
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
        'telegram_poll_offsets',
        sa.Column('token_sha256', sa.String(length=64), nullable=False),
        sa.Column('next_update_id', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('chats_json', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('coordinator_generation', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('next_update_id >= 0', name='ck_telegram_poll_offset_nonnegative'),
        sa.PrimaryKeyConstraint('token_sha256'),
        schema='public',
    )
    op.create_table(
        'telegram_detection_requests',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('token_encrypted', sa.Text(), nullable=False),
        sa.Column('token_sha256', sa.String(length=64), nullable=False),
        sa.Column('request_user_id', sa.String(length=64), nullable=False),
        sa.Column('namespace', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('owner_generation', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'timed_out')", name='ck_telegram_detection_status'),
        sa.PrimaryKeyConstraint('id'),
        schema='public',
    )
    op.create_index(
        'ix_telegram_detection_requests_recovery',
        'telegram_detection_requests',
        ['status', 'deadline_at', 'created_at'],
        schema='public',
    )


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_telegram_detection_requests_recovery', table_name='telegram_detection_requests', schema='public')
    op.drop_table('telegram_detection_requests', schema='public')
    op.drop_table('telegram_poll_offsets', schema='public')
