"""Add namespace ownership to engine runs."""

from collections.abc import Sequence

from alembic import op

revision: str = '0004_engine_run_namespace'
down_revision: str | None = '0003_runtime_outbox'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE engine_runs ADD COLUMN IF NOT EXISTS namespace VARCHAR DEFAULT 'default' NOT NULL")
    op.execute('CREATE INDEX IF NOT EXISTS ix_engine_runs_namespace ON engine_runs (namespace)')
    op.execute('ALTER TABLE engine_runs ALTER COLUMN namespace DROP DEFAULT')


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_engine_runs_namespace')
    op.execute('ALTER TABLE engine_runs DROP COLUMN IF EXISTS namespace')
