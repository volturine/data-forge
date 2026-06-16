"""store explicit engine identity fields.

Revision ID: 0003_engine_identity_public
Revises: 0001_runtime_public
Create Date: 2026-06-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003_engine_identity_public'
down_revision: str | Sequence[str] | None = '0001_runtime_public'
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
    op.add_column('engine_instances', sa.Column('engine_scope', sa.String(), nullable=False, server_default='analysis_interactive'))
    op.add_column('engine_instances', sa.Column('engine_reuse_policy', sa.String(), nullable=False, server_default='shared'))
    op.add_column('engine_instances', sa.Column('datasource_id', sa.String(), nullable=True))
    op.add_column('engine_instances', sa.Column('build_id', sa.String(), nullable=True))
    op.execute(
        """
        UPDATE engine_instances
        SET
            engine_scope = CASE
                WHEN analysis_id LIKE '__preview__%' THEN 'datasource_preview'
                WHEN analysis_id LIKE 'build:%' THEN 'build'
                ELSE 'analysis_interactive'
            END,
            engine_reuse_policy = CASE
                WHEN analysis_id LIKE 'build:%' THEN 'exclusive'
                ELSE 'shared'
            END,
            datasource_id = CASE
                WHEN analysis_id LIKE '__preview__%' THEN substring(analysis_id from 12)
                ELSE NULL
            END,
            build_id = CASE
                WHEN analysis_id LIKE 'build:%' THEN substring(analysis_id from 7)
                ELSE NULL
            END
        """
    )
    op.create_index('ix_engine_instances_engine_scope', 'engine_instances', ['engine_scope'])


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_engine_instances_engine_scope', table_name='engine_instances')
    op.drop_column('engine_instances', 'build_id')
    op.drop_column('engine_instances', 'datasource_id')
    op.drop_column('engine_instances', 'engine_reuse_policy')
    op.drop_column('engine_instances', 'engine_scope')
