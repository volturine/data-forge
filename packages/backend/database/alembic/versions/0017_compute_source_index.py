"""Index exact source references used by durable storage cleanup."""

from collections.abc import Sequence

from alembic import op

revision: str = '0017_compute_source_index'
down_revision: str | Sequence[str] | None = '0012_compute_request_flights'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']


def _scope() -> str:
    context = op.get_context()
    config = context.config
    if config is None:
        return 'public'
    return str(context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def upgrade() -> None:
    if _scope() == 'tenant':
        op.create_index('ix_compute_requests_active_source', 'compute_requests', ['artifact_path', 'status'])


def downgrade() -> None:
    if _scope() == 'tenant':
        op.drop_index('ix_compute_requests_active_source', table_name='compute_requests')
