"""rename persisted engine runs and references to compute worker runs.

Revision ID: 0026_compute_worker_runs
Revises: 0024_pivot_value_columns
Create Date: 2026-10-08

This only renames identifiers; row values and enum tokens are preserved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0026_compute_worker_runs'
down_revision: str | Sequence[str] | None = '0024_pivot_value_columns'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']


def _scope() -> str:
    migration_context = op.get_context()
    config = migration_context.config
    if config is None:
        return 'public'
    return str(migration_context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def _schema() -> str:
    config = op.get_context().config
    if config is None:
        return 'public'
    return str(config.get_main_option('target_schema') or config.attributes.get('target_schema', 'public'))


def _rename_index(old_name: str, new_name: str) -> None:
    preparer = op.get_context().dialect.identifier_preparer
    schema = preparer.quote_schema(_schema())
    old = preparer.quote(old_name)
    new = preparer.quote(new_name)
    op.execute(sa.text(f'ALTER INDEX {schema}.{old} RENAME TO {new}'))


def upgrade() -> None:
    if _scope() != 'tenant':
        return

    schema = _schema()
    op.rename_table('engine_runs', 'compute_worker_runs', schema=schema)
    for table_name, old_name, new_name in (
        ('compute_requests', 'engine_scope', 'compute_worker_scope'),
        ('compute_requests', 'engine_reuse_policy', 'compute_worker_reuse_policy'),
        ('compute_requests', 'engine_resource_id', 'compute_worker_resource_id'),
        ('build_runs', 'current_engine_run_id', 'current_compute_worker_run_id'),
        ('build_events', 'engine_run_id', 'compute_worker_run_id'),
    ):
        op.alter_column(table_name, old_name, new_column_name=new_name, schema=schema)
    for old_name, new_name in (
        ('ix_engine_runs_namespace', 'ix_compute_worker_runs_namespace'),
        ('ix_compute_requests_engine_identity', 'ix_compute_requests_compute_worker_identity'),
        ('ix_build_runs_current_engine_run_id', 'ix_build_runs_current_compute_worker_run_id'),
        ('ix_build_events_engine_run_id', 'ix_build_events_compute_worker_run_id'),
    ):
        _rename_index(old_name, new_name)


def downgrade() -> None:
    if _scope() != 'tenant':
        return

    schema = _schema()
    for old_name, new_name in (
        ('ix_compute_worker_runs_namespace', 'ix_engine_runs_namespace'),
        ('ix_compute_requests_compute_worker_identity', 'ix_compute_requests_engine_identity'),
        ('ix_build_runs_current_compute_worker_run_id', 'ix_build_runs_current_engine_run_id'),
        ('ix_build_events_compute_worker_run_id', 'ix_build_events_engine_run_id'),
    ):
        _rename_index(old_name, new_name)
    for table_name, old_name, new_name in (
        ('compute_requests', 'compute_worker_scope', 'engine_scope'),
        ('compute_requests', 'compute_worker_reuse_policy', 'engine_reuse_policy'),
        ('compute_requests', 'compute_worker_resource_id', 'engine_resource_id'),
        ('build_runs', 'current_compute_worker_run_id', 'current_engine_run_id'),
        ('build_events', 'compute_worker_run_id', 'engine_run_id'),
    ):
        op.alter_column(table_name, old_name, new_column_name=new_name, schema=schema)
    op.rename_table('compute_worker_runs', 'engine_runs', schema=schema)
