"""encrypt secrets at rest.

Revision ID: 0003_encrypt_secrets_at_rest
Revises: 0002_runtime_tenant
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend_core.exceptions import SettingsConfigurationError
from backend_core.secrets import decrypt_secret, encrypt_secret, is_encrypted_secret, is_masked_secret

revision: str = '0003_encrypt_secrets_at_rest'
down_revision: str | Sequence[str] | None = '0002_runtime_tenant'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']

_SECRET_COLUMNS = {
    'app_settings': ('smtp_password', 'telegram_bot_token', 'openrouter_api_key', 'openai_api_key'),
    'telegram_subscribers': ('bot_token',),
}


def _scope() -> str:
    migration_context = op.get_context()
    config = migration_context.config
    if config is None:
        return 'public'
    return str(migration_context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def _transform_values(encrypting: bool) -> None:
    connection = op.get_bind()
    for table, columns in _SECRET_COLUMNS.items():
        for column in columns:
            rows = connection.execute(sa.text(f'SELECT id, {column} FROM {table}')).fetchall()
            for row in rows:
                value = str(row[1] or '')
                if not value or is_masked_secret(value):
                    continue
                if encrypting == is_encrypted_secret(value):
                    continue
                try:
                    updated = encrypt_secret(value) if encrypting else decrypt_secret(value)
                except SettingsConfigurationError:
                    continue
                if updated != value:
                    connection.execute(sa.text(f'UPDATE {table} SET {column} = :value WHERE id = :id'), {'value': updated, 'id': row[0]})


def upgrade() -> None:
    if _scope() != 'tenant':
        return
    _transform_values(encrypting=True)


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    _transform_values(encrypting=False)
