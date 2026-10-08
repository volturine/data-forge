"""record the Docker host that runs each compute worker container.

Revision ID: 0027_compute_worker_host
Revises: 0025_compute_worker_instances
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0027_compute_worker_host'
down_revision: str | Sequence[str] | None = '0025_compute_worker_instances'
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


def upgrade() -> None:
    if _scope() != 'public':
        return
    op.add_column('compute_worker_instances', sa.Column('docker_host', sa.String(), nullable=True), schema=_schema())


def downgrade() -> None:
    if _scope() != 'public':
        return
    op.drop_column('compute_worker_instances', 'docker_host', schema=_schema())
