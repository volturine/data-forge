"""rename leftover constraints on compute worker runs.

Revision ID: 0028_compute_worker_run
Revises: 0026_compute_worker_runs
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0028_compute_worker_run'
down_revision: str | Sequence[str] | None = '0026_compute_worker_runs'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']


_CONSTRAINT_RENAMES = (
    ('engine_runs_pkey', 'compute_worker_runs_pkey'),
    ('engine_runs_id_not_null', 'compute_worker_runs_id_not_null'),
    ('engine_runs_datasource_id_not_null', 'compute_worker_runs_datasource_id_not_null'),
    ('engine_runs_kind_not_null', 'compute_worker_runs_kind_not_null'),
    ('engine_runs_status_not_null', 'compute_worker_runs_status_not_null'),
    ('engine_runs_request_json_not_null', 'compute_worker_runs_request_json_not_null'),
    ('engine_runs_created_at_not_null', 'compute_worker_runs_created_at_not_null'),
    ('engine_runs_step_timings_not_null', 'compute_worker_runs_step_timings_not_null'),
    ('engine_runs_progress_not_null', 'compute_worker_runs_progress_not_null'),
    ('engine_runs_namespace_not_null', 'compute_worker_runs_namespace_not_null'),
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
    table = preparer.quote('compute_worker_runs')
    old = preparer.quote(old_name)
    new = preparer.quote(new_name)
    op.execute(sa.text(f'ALTER TABLE {schema}.{table} RENAME CONSTRAINT {old} TO {new}'))


def upgrade() -> None:
    if _scope() != 'tenant':
        return
    for old_name, new_name in _CONSTRAINT_RENAMES:
        _rename_constraint(old_name, new_name)


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    for old_name, new_name in reversed(_CONSTRAINT_RENAMES):
        _rename_constraint(new_name, old_name)
