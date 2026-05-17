"""runtime tenant schema.

Revision ID: 0002_runtime_tenant
Revises: 0001_runtime_public
Create Date: 2026-04-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002_runtime_tenant'
down_revision: str | Sequence[str] | None = '0001_runtime_public'
branch_labels: str | Sequence[str] | None = ('tenant',)
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']

COMPUTE_REQUEST_KIND = sa.Enum(
    'preview',
    'schema',
    'row_count',
    'download',
    'export',
    'create_file_datasource',
    'create_database_datasource',
    'create_iceberg_datasource',
    'refresh_datasource',
    'spawn_engine',
    'keepalive_engine',
    'configure_engine',
    'shutdown_engine',
    name='computerequestkind',
    native_enum=False,
)

COMPUTE_REQUEST_STATUS = sa.Enum('queued', 'running', 'completed', 'failed', name='computerequeststatus', native_enum=False)


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
        'datasources',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(length=4000), nullable=True),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('schema_cache', sa.JSON(), nullable=True),
        sa.Column('created_by_analysis_id', sa.String(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=False, server_default='import'),
        sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('owner_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'datasource_column_metadata',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.Column('column_name', sa.String(), nullable=False),
        sa.Column('description', sa.String(length=2000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['datasource_id'], ['datasources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('datasource_id', 'column_name', name='uq_datasource_column_metadata_name'),
    )
    op.create_index('ix_datasource_column_metadata_datasource_id', 'datasource_column_metadata', ['datasource_id'])
    op.create_table(
        'analyses',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('pipeline_definition', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('result_path', sa.String(), nullable=True),
        sa.Column('thumbnail', sa.String(), nullable=True),
        sa.Column('owner_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'analysis_datasources',
        sa.Column('analysis_id', sa.String(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['datasource_id'], ['datasources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('analysis_id', 'datasource_id'),
    )
    op.create_table(
        'analysis_favorites',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'analysis_id'),
    )
    op.create_index('ix_analysis_favorites_analysis_id', 'analysis_favorites', ['analysis_id'])
    op.create_table(
        'analysis_versions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('pipeline_definition', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'engine_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=True),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('request_json', sa.JSON(), nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('step_timings', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('query_plan', sa.String(), nullable=True),
        sa.Column('progress', sa.Float(), nullable=False, server_default='0'),
        sa.Column('current_step', sa.String(), nullable=True),
        sa.Column('triggered_by', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'build_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('schedule_id', sa.String(), nullable=True),
        sa.Column('analysis_id', sa.String(), nullable=False),
        sa.Column('analysis_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('request_json', sa.JSON(), nullable=False),
        sa.Column('starter_json', sa.JSON(), nullable=False),
        sa.Column('resource_config_json', sa.JSON(), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('current_engine_run_id', sa.String(), nullable=True),
        sa.Column('current_kind', sa.String(), nullable=True),
        sa.Column('current_datasource_id', sa.String(), nullable=True),
        sa.Column('current_tab_id', sa.String(), nullable=True),
        sa.Column('current_tab_name', sa.String(), nullable=True),
        sa.Column('current_output_id', sa.String(), nullable=True),
        sa.Column('current_output_name', sa.String(), nullable=True),
        sa.Column('progress', sa.Float(), nullable=False, server_default='0'),
        sa.Column('elapsed_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estimated_remaining_ms', sa.Integer(), nullable=True),
        sa.Column('current_step', sa.String(), nullable=True),
        sa.Column('current_step_index', sa.Integer(), nullable=True),
        sa.Column('total_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tabs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_build_runs_namespace', 'build_runs', ['namespace'])
    op.create_index('ix_build_runs_schedule_id', 'build_runs', ['schedule_id'])
    op.create_index('ix_build_runs_analysis_id', 'build_runs', ['analysis_id'])
    op.create_index('ix_build_runs_status', 'build_runs', ['status'])
    op.create_index('ix_build_runs_current_engine_run_id', 'build_runs', ['current_engine_run_id'])
    op.create_table(
        'build_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('build_id', sa.String(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('engine_run_id', sa.String(), nullable=True),
        sa.Column('emitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('build_id', 'sequence', name='uq_build_events_build_sequence'),
    )
    op.create_index('ix_build_events_build_id', 'build_events', ['build_id'])
    op.create_index('ix_build_events_namespace', 'build_events', ['namespace'])
    op.create_index('ix_build_events_engine_run_id', 'build_events', ['engine_run_id'])
    op.create_table(
        'build_jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('build_id', sa.String(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lease_owner', sa.String(), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('build_id'),
    )
    op.create_index('ix_build_jobs_build_id', 'build_jobs', ['build_id'])
    op.create_index('ix_build_jobs_namespace', 'build_jobs', ['namespace'])
    op.create_index('ix_build_jobs_status', 'build_jobs', ['status'])
    op.create_index('ix_build_jobs_lease_owner', 'build_jobs', ['lease_owner'])
    op.create_index('ix_build_jobs_available_at', 'build_jobs', ['available_at'])
    op.create_table(
        'compute_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('kind', COMPUTE_REQUEST_KIND, nullable=False),
        sa.Column('status', COMPUTE_REQUEST_STATUS, nullable=False),
        sa.Column('request_json', sa.JSON(), nullable=False),
        sa.Column('response_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('artifact_path', sa.String(), nullable=True),
        sa.Column('artifact_name', sa.String(), nullable=True),
        sa.Column('artifact_content_type', sa.String(), nullable=True),
        sa.Column('lease_owner', sa.String(), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_compute_requests_namespace', 'compute_requests', ['namespace'])
    op.create_index('ix_compute_requests_kind', 'compute_requests', ['kind'])
    op.create_index('ix_compute_requests_status', 'compute_requests', ['status'])
    op.create_index('ix_compute_requests_lease_owner', 'compute_requests', ['lease_owner'])
    op.create_table(
        'healthchecks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('check_type', sa.String(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('critical', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_healthchecks_datasource_id', 'healthchecks', ['datasource_id'])
    op.create_table(
        'healthcheck_results',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('healthcheck_id', sa.String(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_healthcheck_results_healthcheck_id', 'healthcheck_results', ['healthcheck_id'])
    op.create_table(
        'resource_locks',
        sa.Column('resource_type', sa.String(), nullable=False),
        sa.Column('resource_id', sa.String(), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('lock_token', sa.String(), nullable=False),
        sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('resource_type', 'resource_id'),
    )
    op.create_index('ix_resource_locks_owner_id', 'resource_locks', ['owner_id'])
    op.create_index('ix_resource_locks_lock_token', 'resource_locks', ['lock_token'], unique=True)
    op.create_index('ix_resource_locks_expires_at', 'resource_locks', ['expires_at'])
    op.create_table(
        'schedules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.Column('cron_expression', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('depends_on', sa.String(), nullable=True),
        sa.Column('trigger_on_datasource_id', sa.String(), nullable=True),
        sa.Column('last_run', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_owner', sa.String(), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_successful_build_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_schedules_datasource_id', 'schedules', ['datasource_id'])
    op.create_index('ix_schedules_lease_owner', 'schedules', ['lease_owner'])
    op.create_table(
        'telegram_subscribers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False, server_default=''),
        sa.Column('bot_token', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('subscribed_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'telegram_listeners',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('subscriber_id', sa.Integer(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'udfs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('signature', sa.JSON(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_table('udfs')
    op.drop_table('telegram_listeners')
    op.drop_table('telegram_subscribers')
    op.drop_index('ix_schedules_lease_owner', table_name='schedules')
    op.drop_index('ix_schedules_datasource_id', table_name='schedules')
    op.drop_table('schedules')
    op.drop_index('ix_resource_locks_expires_at', table_name='resource_locks')
    op.drop_index('ix_resource_locks_lock_token', table_name='resource_locks')
    op.drop_index('ix_resource_locks_owner_id', table_name='resource_locks')
    op.drop_table('resource_locks')
    op.drop_index('ix_healthcheck_results_healthcheck_id', table_name='healthcheck_results')
    op.drop_table('healthcheck_results')
    op.drop_index('ix_healthchecks_datasource_id', table_name='healthchecks')
    op.drop_table('healthchecks')
    op.drop_index('ix_compute_requests_lease_owner', table_name='compute_requests')
    op.drop_index('ix_compute_requests_status', table_name='compute_requests')
    op.drop_index('ix_compute_requests_kind', table_name='compute_requests')
    op.drop_index('ix_compute_requests_namespace', table_name='compute_requests')
    op.drop_table('compute_requests')
    op.drop_index('ix_build_jobs_available_at', table_name='build_jobs')
    op.drop_index('ix_build_jobs_lease_owner', table_name='build_jobs')
    op.drop_index('ix_build_jobs_status', table_name='build_jobs')
    op.drop_index('ix_build_jobs_namespace', table_name='build_jobs')
    op.drop_index('ix_build_jobs_build_id', table_name='build_jobs')
    op.drop_table('build_jobs')
    op.drop_index('ix_build_events_engine_run_id', table_name='build_events')
    op.drop_index('ix_build_events_namespace', table_name='build_events')
    op.drop_index('ix_build_events_build_id', table_name='build_events')
    op.drop_table('build_events')
    op.drop_index('ix_build_runs_current_engine_run_id', table_name='build_runs')
    op.drop_index('ix_build_runs_status', table_name='build_runs')
    op.drop_index('ix_build_runs_analysis_id', table_name='build_runs')
    op.drop_index('ix_build_runs_schedule_id', table_name='build_runs')
    op.drop_index('ix_build_runs_namespace', table_name='build_runs')
    op.drop_table('build_runs')
    op.drop_table('engine_runs')
    op.drop_table('analysis_versions')
    op.drop_index('ix_analysis_favorites_analysis_id', table_name='analysis_favorites')
    op.drop_table('analysis_favorites')
    op.drop_table('analysis_datasources')
    op.drop_table('analyses')
    op.drop_index('ix_datasource_column_metadata_datasource_id', table_name='datasource_column_metadata')
    op.drop_table('datasource_column_metadata')
    op.drop_table('datasources')
