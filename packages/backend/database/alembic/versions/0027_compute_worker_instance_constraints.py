"""rename leftover constraints on compute worker instances.

Revision ID: 0027_compute_worker_instance
Revises: 0025_compute_worker_instances
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0027_compute_worker_instance'
down_revision: str | Sequence[str] | None = '0025_compute_worker_instances'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']


_CONSTRAINT_RENAMES = (
    ('engine_instances_pkey', 'compute_worker_instances_pkey'),
    ('engine_instances_id_not_null', 'compute_worker_instances_id_not_null'),
    ('engine_instances_worker_id_not_null', 'compute_worker_instances_worker_id_not_null'),
    ('engine_instances_namespace_not_null', 'compute_worker_instances_namespace_not_null'),
    ('engine_instances_analysis_id_not_null', 'compute_worker_instances_analysis_id_not_null'),
    ('engine_instances_engine_scope_not_null', 'compute_worker_instances_compute_worker_scope_not_null'),
    ('engine_instances_engine_reuse_policy_not_null', 'compute_worker_instances_compute_worker_reuse_policy_not_null'),
    ('engine_instances_status_not_null', 'compute_worker_instances_status_not_null'),
    ('engine_instances_last_seen_at_not_null', 'compute_worker_instances_last_seen_at_not_null'),
    ('engine_instances_updated_at_not_null', 'compute_worker_instances_updated_at_not_null'),
)


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


def _rename_constraint(old_name: str, new_name: str) -> None:
    preparer = op.get_context().dialect.identifier_preparer
    schema = preparer.quote_schema(_schema())
    table = preparer.quote('compute_worker_instances')
    old = preparer.quote(old_name)
    new = preparer.quote(new_name)
    op.execute(sa.text(f'ALTER TABLE {schema}.{table} RENAME CONSTRAINT {old} TO {new}'))


def upgrade() -> None:
    if _scope() != 'public':
        return
    for old_name, new_name in _CONSTRAINT_RENAMES:
        _rename_constraint(old_name, new_name)


def downgrade() -> None:
    if _scope() != 'public':
        return
    for old_name, new_name in reversed(_CONSTRAINT_RENAMES):
        _rename_constraint(new_name, old_name)
