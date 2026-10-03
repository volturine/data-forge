"""Persist exact datasource dependencies for active build runs.

Revision ID: 0019_build_run_datasources
Revises: 0018_runtime_work_generations
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0019_build_run_datasources'
down_revision: str | Sequence[str] | None = '0018_runtime_work_generations'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'upgrade', 'downgrade']


def _scope() -> str:
    migration_context = op.get_context()
    config = migration_context.config
    if config is None:
        return 'public'
    return str(migration_context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def _datasource_ids(request_json: object) -> list[str]:
    if not isinstance(request_json, dict):
        return []
    pipeline = request_json.get('analysis_pipeline')
    if not isinstance(pipeline, dict) or not isinstance(pipeline.get('tabs'), list):
        return []
    tabs = [tab for tab in pipeline['tabs'] if isinstance(tab, dict)]
    local_ids = {tab['id'] for tab in tabs if isinstance(tab.get('id'), str)}
    local_ids.update(result_id for tab in tabs if isinstance(tab.get('output'), dict) if isinstance((result_id := tab['output'].get('result_id')), str))
    datasource_ids: set[str] = set()
    for tab in tabs:
        datasource = tab.get('datasource')
        if isinstance(datasource, dict):
            datasource_id = datasource.get('id')
            # Scheduled-ingest pipelines intentionally reuse the source RID as
            # output.result_id; that source remains a true input.
            if (
                isinstance(datasource_id, str)
                and datasource.get('analysis_tab_id') is None
                and (datasource_id not in local_ids or datasource.get('source_type') == 'schedule')
            ):
                datasource_ids.add(datasource_id)
        steps = tab.get('steps')
        if not isinstance(steps, list):
            continue
        for step in steps:
            config = step.get('config') if isinstance(step, dict) else None
            if not isinstance(config, dict):
                continue
            right_source = config.get('right_source')
            if isinstance(right_source, str) and right_source not in local_ids:
                datasource_ids.add(right_source)
            sources = config.get('sources')
            if isinstance(sources, list):
                datasource_ids.update(source for source in sources if isinstance(source, str) and source not in local_ids)
    return sorted(datasource_ids)


def upgrade() -> None:
    if _scope() != 'tenant':
        return
    op.create_table(
        'build_run_datasources',
        sa.Column('build_id', sa.String(), nullable=False),
        sa.Column('namespace', sa.String(), nullable=False),
        sa.Column('datasource_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['build_id'], ['build_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('build_id', 'datasource_id'),
    )
    op.create_index(
        'ix_build_run_datasources_namespace_source',
        'build_run_datasources',
        ['namespace', 'datasource_id', 'build_id'],
    )

    connection = op.get_bind()
    active_runs = connection.execute(sa.text("SELECT id, namespace, request_json FROM build_runs WHERE status IN ('queued', 'running')"))
    for build_id, namespace, request_json in active_runs:
        rows = [{'build_id': str(build_id), 'namespace': str(namespace), 'datasource_id': datasource_id} for datasource_id in _datasource_ids(request_json)]
        if rows:
            connection.execute(
                sa.text(
                    'INSERT INTO build_run_datasources (build_id, namespace, datasource_id) '
                    'VALUES (:build_id, :namespace, :datasource_id) ON CONFLICT DO NOTHING'
                ),
                rows,
            )


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    op.drop_index('ix_build_run_datasources_namespace_source', table_name='build_run_datasources')
    op.drop_table('build_run_datasources')
