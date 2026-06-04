"""runtime outbox events.

Revision ID: 0003_runtime_outbox
Revises: 0002_runtime_tenant
Create Date: 2026-06-02

"""

from collections.abc import Sequence

from alembic import op

revision: str = '0003_runtime_outbox'
down_revision: str | Sequence[str] | None = '0002_runtime_tenant'
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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_outbox_events (
            id VARCHAR NOT NULL PRIMARY KEY,
            kind VARCHAR NOT NULL,
            status VARCHAR(10) NOT NULL,
            payload_json JSON NOT NULL,
            attempts INTEGER DEFAULT 0 NOT NULL,
            last_error VARCHAR NULL,
            available_at TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            dispatched_at TIMESTAMP WITH TIME ZONE NULL
        )
        """
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_runtime_outbox_events_kind ON runtime_outbox_events (kind)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_runtime_outbox_events_status ON runtime_outbox_events (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_runtime_outbox_events_available_at ON runtime_outbox_events (available_at)')


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_runtime_outbox_events_available_at', table_name='runtime_outbox_events')
    op.drop_index('ix_runtime_outbox_events_status', table_name='runtime_outbox_events')
    op.drop_index('ix_runtime_outbox_events_kind', table_name='runtime_outbox_events')
    op.drop_table('runtime_outbox_events')
