"""Move chat turns, transcript, and events into durable ordered tables.

Revision ID: 0015_durable_chat_turns
Revises: 0014_runtime_coordinator_fencing
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0015_durable_chat_turns'
down_revision: str | Sequence[str] | None = '0014_runtime_coordinator_fencing'
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

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.chat_sessions (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NULL,
            provider VARCHAR NOT NULL DEFAULT 'openrouter',
            model VARCHAR NOT NULL DEFAULT '',
            api_key VARCHAR NOT NULL DEFAULT '',
            messages_json TEXT NOT NULL DEFAULT '[]',
            history_json TEXT NOT NULL DEFAULT '[]',
            created_at DOUBLE PRECISION NOT NULL,
            system_prompt VARCHAR NOT NULL DEFAULT ''
        )
        """
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id ON public.chat_sessions (user_id)')
    op.create_table(
        'chat_turns',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tool_ids', sa.JSON(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('session_token_encrypted', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), server_default='queued', nullable=False),
        sa.Column('checkpoint', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('stop_requested', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('confirmation_decision', sa.Boolean(), nullable=True),
        sa.Column('claim_token', sa.String(), nullable=True),
        sa.Column('coordinator_generation', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('statement_timestamp()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('statement_timestamp()'), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_confirmation', 'completed', 'failed', 'interrupted')",
            name='ck_chat_turns_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_chat_turns_active_session',
        'chat_turns',
        ['session_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'awaiting_confirmation')"),
    )
    op.create_index('ix_chat_turns_ready', 'chat_turns', ['status', 'created_at'])
    op.create_index('ix_chat_turns_session_id', 'chat_turns', ['session_id'])
    op.create_table(
        'chat_messages',
        sa.Column('sequence', sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column('session_id', sa.String(), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('turn_id', sa.String(), sa.ForeignKey('chat_turns.id', ondelete='CASCADE'), nullable=True),
        sa.Column('message', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('statement_timestamp()'), nullable=False),
        sa.PrimaryKeyConstraint('sequence'),
    )
    op.create_index('ix_chat_messages_session_sequence', 'chat_messages', ['session_id', 'sequence'])
    op.create_table(
        'chat_events',
        sa.Column('sequence', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.String(), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('turn_id', sa.String(), sa.ForeignKey('chat_turns.id', ondelete='CASCADE'), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('statement_timestamp()'), nullable=False),
        sa.PrimaryKeyConstraint('session_id', 'sequence'),
    )

    op.execute(
        """
        INSERT INTO public.chat_messages (session_id, message, created_at)
        SELECT s.id, item.value, to_timestamp(s.created_at)
        FROM public.chat_sessions AS s
        CROSS JOIN LATERAL jsonb_array_elements(s.messages_json::jsonb) WITH ORDINALITY AS item(value, ordinality)
        ORDER BY s.id, item.ordinality
        """
    )
    op.execute(
        """
        INSERT INTO public.chat_events (session_id, sequence, payload, created_at)
        SELECT s.id, item.ordinality, item.value, to_timestamp(s.created_at)
        FROM public.chat_sessions AS s
        CROSS JOIN LATERAL jsonb_array_elements(s.history_json::jsonb) WITH ORDINALITY AS item(value, ordinality)
        """
    )
    op.drop_column('chat_sessions', 'messages_json')
    op.drop_column('chat_sessions', 'history_json')


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.add_column('chat_sessions', sa.Column('messages_json', sa.Text(), server_default='[]', nullable=False))
    op.add_column('chat_sessions', sa.Column('history_json', sa.Text(), server_default='[]', nullable=False))
    op.execute(
        """
        UPDATE public.chat_sessions AS s
        SET messages_json = COALESCE((
            SELECT jsonb_agg(m.message ORDER BY m.sequence)::text
            FROM public.chat_messages AS m WHERE m.session_id = s.id
        ), '[]')
        """
    )
    op.execute(
        """
        UPDATE public.chat_sessions AS s
        SET history_json = COALESCE((
            SELECT jsonb_agg(e.payload ORDER BY e.sequence)::text
            FROM public.chat_events AS e WHERE e.session_id = s.id
        ), '[]')
        """
    )
    op.drop_table('chat_events')
    op.drop_index('ix_chat_messages_session_sequence', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index('ix_chat_turns_session_id', table_name='chat_turns')
    op.drop_index('ix_chat_turns_ready', table_name='chat_turns')
    op.drop_index('uq_chat_turns_active_session', table_name='chat_turns')
    op.drop_table('chat_turns')
