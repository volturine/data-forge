"""runtime public schema.

Revision ID: 0001_runtime_public
Revises:
Create Date: 2026-04-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001_runtime_public'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ('public',)
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
        'app_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('smtp_host', sa.String(), nullable=False, server_default=''),
        sa.Column('smtp_port', sa.Integer(), nullable=False, server_default='587'),
        sa.Column('smtp_user', sa.String(), nullable=False, server_default=''),
        sa.Column('smtp_password', sa.String(), nullable=False, server_default=''),
        sa.Column('telegram_bot_token', sa.String(), nullable=False, server_default=''),
        sa.Column('telegram_bot_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('openrouter_api_key', sa.String(), nullable=False, server_default=''),
        sa.Column('openrouter_default_model', sa.String(), nullable=False, server_default=''),
        sa.Column('openai_api_key', sa.String(), nullable=False, server_default=''),
        sa.Column('openai_endpoint_url', sa.String(), nullable=False, server_default='https://api.openai.com'),
        sa.Column('openai_default_model', sa.String(), nullable=False, server_default='gpt-4o-mini'),
        sa.Column('openai_organization_id', sa.String(), nullable=False, server_default=''),
        sa.Column('ollama_endpoint_url', sa.String(), nullable=False, server_default='http://localhost:11434'),
        sa.Column('ollama_default_model', sa.String(), nullable=False, server_default='llama3.2'),
        sa.Column('huggingface_api_token', sa.String(), nullable=False, server_default=''),
        sa.Column('huggingface_default_model', sa.String(), nullable=False, server_default='google/flan-t5-base'),
        sa.Column('env_bootstrap_complete', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('public_idb_debug', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute('INSERT INTO app_settings (id) VALUES (1)')
    op.create_table(
        'runtime_namespaces',
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('name'),
    )
    op.create_table(
        'runtime_workers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('hostname', sa.String(), nullable=False),
        sa.Column('pid', sa.Integer(), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('active_jobs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_runtime_workers_kind', 'runtime_workers', ['kind'])
    op.create_index('ix_runtime_workers_last_heartbeat_at', 'runtime_workers', ['last_heartbeat_at'])
    op.create_table(
        'engine_instances',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('worker_id', sa.String(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=False),
        sa.Column('process_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('current_job_id', sa.String(), nullable=True),
        sa.Column('current_build_id', sa.String(), nullable=True),
        sa.Column('current_engine_run_id', sa.String(), nullable=True),
        sa.Column('resource_config_json', sa.JSON(), nullable=True),
        sa.Column('effective_resources_json', sa.JSON(), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_engine_instances_worker_id', 'engine_instances', ['worker_id'])
    op.create_index('ix_engine_instances_namespace', 'engine_instances', ['namespace'])
    op.create_index('ix_engine_instances_analysis_id', 'engine_instances', ['analysis_id'])
    op.create_index('ix_engine_instances_status', 'engine_instances', ['status'])
    op.create_index('ix_engine_instances_last_seen_at', 'engine_instances', ['last_seen_at'])


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_index('ix_engine_instances_last_seen_at', table_name='engine_instances')
    op.drop_index('ix_engine_instances_status', table_name='engine_instances')
    op.drop_index('ix_engine_instances_analysis_id', table_name='engine_instances')
    op.drop_index('ix_engine_instances_namespace', table_name='engine_instances')
    op.drop_index('ix_engine_instances_worker_id', table_name='engine_instances')
    op.drop_table('engine_instances')
    op.drop_index('ix_runtime_workers_last_heartbeat_at', table_name='runtime_workers')
    op.drop_index('ix_runtime_workers_kind', table_name='runtime_workers')
    op.drop_table('runtime_workers')
    op.drop_table('runtime_namespaces')
    op.drop_table('app_settings')
