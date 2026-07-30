"""fence build job claims.

Revision ID: 0005_fenced_build_jobs_tenant
Revises: 0004_compute_envelopes_tenant
Create Date: 2026-07-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005_fenced_build_jobs_tenant'
down_revision: str | Sequence[str] | None = '0004_compute_envelopes_tenant'
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
    op.add_column('build_jobs', sa.Column('claim_token', sa.String(), nullable=True))
    op.add_column('build_jobs', sa.Column('lease_generation', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('build_jobs', sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('build_jobs', sa.Column('last_renewed_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE build_runs
            SET status = 'orphaned',
                error_message = 'Build interrupted by fenced lease migration',
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'running')
              AND id IN (
                  SELECT build_id
                  FROM build_jobs
                  WHERE status IN ('leased', 'running')
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE schedules
            SET lease_owner = NULL,
                lease_expires_at = NULL,
                last_failure_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT build_runs.schedule_id
                FROM build_runs
                JOIN build_jobs ON build_jobs.build_id = build_runs.id
                WHERE build_jobs.status IN ('leased', 'running')
                  AND build_runs.schedule_id IS NOT NULL
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE build_jobs
            SET status = 'failed',
                lease_owner = NULL,
                claim_token = NULL,
                lease_expires_at = NULL,
                claimed_at = NULL,
                last_renewed_at = NULL,
                last_error = 'Build interrupted by fenced lease migration',
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('leased', 'running')
            """
        )
    )
    op.create_unique_constraint('uq_build_jobs_claim_token', 'build_jobs', ['claim_token'])
    op.alter_column('build_jobs', 'lease_generation', server_default=None)


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_constraint('uq_build_jobs_claim_token', 'build_jobs', type_='unique')
    op.drop_column('build_jobs', 'last_renewed_at')
    op.drop_column('build_jobs', 'claimed_at')
    op.drop_column('build_jobs', 'lease_generation')
    op.drop_column('build_jobs', 'claim_token')
