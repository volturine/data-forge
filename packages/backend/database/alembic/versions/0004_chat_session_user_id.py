"""per-user chat session isolation.

Revision ID: 0004_chat_session_user_id
Revises: 0003_encrypt_secrets_at_rest
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004_chat_session_user_id'
down_revision: str | Sequence[str] | None = '0003_encrypt_secrets_at_rest'
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
    connection = op.get_bind()
    # chat_sessions is created by app bootstrap (SQLModel create_all) in the public
    # schema after migrations run, so it may not exist yet on fresh installs.
    inspector = sa.inspect(connection)
    if 'chat_sessions' not in inspector.get_table_names():
        return
    columns = {column['name'] for column in inspector.get_columns('chat_sessions')}
    if 'user_id' not in columns:
        op.add_column('chat_sessions', sa.Column('user_id', sa.String(), nullable=True))
        # Sessions are keyed by a random token with no resolvable owner; legacy rows
        # belong to the default user so AUTH_REQUIRED=false behavior is preserved.
        from modules.auth.service import get_default_user_id

        connection.execute(sa.text('UPDATE chat_sessions SET user_id = :user_id WHERE user_id IS NULL'), {'user_id': get_default_user_id()})
    indexes = {index['name'] for index in inspector.get_indexes('chat_sessions')}
    if 'ix_chat_sessions_user_id' not in indexes:
        op.create_index('ix_chat_sessions_user_id', 'chat_sessions', ['user_id'])


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'chat_sessions' not in inspector.get_table_names():
        return
    indexes = {index['name'] for index in inspector.get_indexes('chat_sessions')}
    if 'ix_chat_sessions_user_id' in indexes:
        op.drop_index('ix_chat_sessions_user_id', table_name='chat_sessions')
    columns = {column['name'] for column in inspector.get_columns('chat_sessions')}
    if 'user_id' in columns:
        op.drop_column('chat_sessions', 'user_id')
