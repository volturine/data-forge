"""rename persisted engine instances to compute worker instances.

Revision ID: 0025_compute_worker_instances
Revises: 0020_runtime_wakes
Create Date: 2026-10-08

Stored scope and reuse-policy tokens intentionally remain unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0025_compute_worker_instances'
down_revision: str | Sequence[str] | None = '0020_runtime_wakes'
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
    if _scope() != 'public':
        return

    schema = _schema()
    op.rename_table('engine_instances', 'compute_worker_instances', schema=schema)
    for old_name, new_name in (
        ('engine_scope', 'compute_worker_scope'),
        ('engine_reuse_policy', 'compute_worker_reuse_policy'),
        ('current_engine_run_id', 'current_compute_worker_run_id'),
    ):
        op.alter_column('compute_worker_instances', old_name, new_column_name=new_name, schema=schema)
    for old_name, new_name in (
        ('ix_engine_instances_worker_id', 'ix_compute_worker_instances_worker_id'),
        ('ix_engine_instances_namespace', 'ix_compute_worker_instances_namespace'),
        ('ix_engine_instances_analysis_id', 'ix_compute_worker_instances_analysis_id'),
        ('ix_engine_instances_engine_scope', 'ix_compute_worker_instances_compute_worker_scope'),
        ('ix_engine_instances_status', 'ix_compute_worker_instances_status'),
        ('ix_engine_instances_last_seen_at', 'ix_compute_worker_instances_last_seen_at'),
    ):
        _rename_index(old_name, new_name)


def downgrade() -> None:
    if _scope() != 'public':
        return

    schema = _schema()
    for old_name, new_name in (
        ('ix_compute_worker_instances_worker_id', 'ix_engine_instances_worker_id'),
        ('ix_compute_worker_instances_namespace', 'ix_engine_instances_namespace'),
        ('ix_compute_worker_instances_analysis_id', 'ix_engine_instances_analysis_id'),
        ('ix_compute_worker_instances_compute_worker_scope', 'ix_engine_instances_engine_scope'),
        ('ix_compute_worker_instances_status', 'ix_engine_instances_status'),
        ('ix_compute_worker_instances_last_seen_at', 'ix_engine_instances_last_seen_at'),
    ):
        _rename_index(old_name, new_name)
    for old_name, new_name in (
        ('compute_worker_scope', 'engine_scope'),
        ('compute_worker_reuse_policy', 'engine_reuse_policy'),
        ('current_compute_worker_run_id', 'current_engine_run_id'),
    ):
        op.alter_column('compute_worker_instances', old_name, new_column_name=new_name, schema=schema)
    op.rename_table('compute_worker_instances', 'engine_instances', schema=schema)
