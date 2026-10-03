"""Index structured catalog identities on durable storage-cleanup intents.

Revision ID: 0021_cleanup_catalog_idx
Revises: 0019_build_run_datasources
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0021_cleanup_catalog_idx'
down_revision: str | Sequence[str] | None = '0019_build_run_datasources'
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

    op.add_column('runtime_outbox_events', sa.Column('catalog_namespace', sa.String(), nullable=True))
    op.add_column('runtime_outbox_events', sa.Column('catalog_table', sa.String(), nullable=True))
    op.add_column('runtime_outbox_events', sa.Column('catalog_family_prefix', sa.String(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE runtime_outbox_events
            SET catalog_namespace = payload_json ->> 'catalog_namespace',
                catalog_table = payload_json ->> 'catalog_table',
                catalog_family_prefix = payload_json ->> 'catalog_family_prefix'
            WHERE kind = 'storage_cleanup'
              AND payload_json ->> 'catalog_namespace' IS NOT NULL
            """
        )
    )
    op.create_index(
        'ix_runtime_outbox_catalog_table',
        'runtime_outbox_events',
        ['catalog_namespace', 'catalog_table'],
        postgresql_where=sa.text('catalog_namespace IS NOT NULL'),
        postgresql_ops={'catalog_table': 'varchar_pattern_ops'},
    )
    op.create_index(
        'ix_runtime_outbox_catalog_family',
        'runtime_outbox_events',
        ['catalog_namespace', 'catalog_family_prefix'],
        postgresql_where=sa.text('catalog_namespace IS NOT NULL'),
    )


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_runtime_outbox_catalog_family', table_name='runtime_outbox_events')
    op.drop_index('ix_runtime_outbox_catalog_table', table_name='runtime_outbox_events')
    op.drop_column('runtime_outbox_events', 'catalog_family_prefix')
    op.drop_column('runtime_outbox_events', 'catalog_table')
    op.drop_column('runtime_outbox_events', 'catalog_namespace')
