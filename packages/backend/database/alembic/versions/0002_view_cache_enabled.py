"""Add the default view preview cache setting to saved pipelines."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'view_cache_enabled'
down_revision: str | Sequence[str] | None = 'runtime_schema_baseline'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'rewrite_pipeline_definition', 'upgrade', 'downgrade']

_BATCH_SIZE = 250


def rewrite_pipeline_definition(pipeline_definition: object, *, downgrade: bool) -> bool:
    """Add or remove the persisted view cache option without changing other config."""
    if not isinstance(pipeline_definition, dict):
        return False
    tabs = pipeline_definition.get('tabs')
    if not isinstance(tabs, list):
        return False

    changed = False
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        steps = tab.get('steps')
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict) or step.get('type') != 'view':
                continue
            config = step.get('config')
            if not isinstance(config, dict):
                continue

            if downgrade:
                if 'cacheEnabled' in config:
                    del config['cacheEnabled']
                    changed = True
                continue

            if 'cacheEnabled' not in config:
                config['cacheEnabled'] = True
                changed = True

    return changed


def _scope() -> str:
    migration_context = op.get_context()
    if migration_context.opts.get('tag'):
        return str(migration_context.opts['tag'])
    if migration_context.opts.get('runtime_scope'):
        return str(migration_context.opts['runtime_scope'])
    config = migration_context.config
    if config is None:
        return 'public'
    return str(config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def _schema() -> str:
    migration_context = op.get_context()
    if migration_context.opts.get('target_schema'):
        return str(migration_context.opts['target_schema'])
    config = migration_context.config
    if config is None:
        return 'public'
    return str(config.get_main_option('target_schema') or config.attributes.get('target_schema', 'public'))


def _columns(bind: sa.Connection, schema: str, table_name: str) -> set[str]:
    if table_name not in sa.inspect(bind).get_table_names(schema=schema):
        return set()
    return {str(column['name']) for column in sa.inspect(bind).get_columns(table_name, schema=schema)}


def _rewrite_table(bind: sa.Connection, schema: str, table_name: str, *, downgrade: bool) -> None:
    if not {'id', 'pipeline_definition'} <= _columns(bind, schema, table_name):
        return

    metadata = sa.MetaData()
    table = sa.Table(
        table_name,
        metadata,
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('pipeline_definition', sa.JSON()),
        schema=schema,
    )
    update = sa.update(table).where(table.c.id == sa.bindparam('_row_id')).values(pipeline_definition=sa.bindparam('_pipeline_definition', type_=sa.JSON()))
    last_id: str | None = None
    while True:
        query = sa.select(table.c.id, table.c.pipeline_definition).order_by(table.c.id).limit(_BATCH_SIZE).with_for_update()
        if last_id is not None:
            query = query.where(table.c.id > last_id)
        batch = bind.execute(query).all()
        if not batch:
            return

        updates = []
        for row in batch:
            pipeline_definition = row.pipeline_definition
            if rewrite_pipeline_definition(pipeline_definition, downgrade=downgrade):
                updates.append({'_row_id': row.id, '_pipeline_definition': pipeline_definition})
        if updates:
            bind.execute(update, updates)
        last_id = batch[-1].id


def _rewrite_pipelines(*, downgrade: bool) -> None:
    if _scope() != 'tenant':
        return

    bind = op.get_bind()
    schema = _schema()
    preparer = bind.dialect.identifier_preparer
    bind.execute(sa.text(f'SET LOCAL search_path TO {preparer.quote_schema(schema)}, public'))
    for table_name in ('analyses', 'analysis_versions'):
        _rewrite_table(bind, schema, table_name, downgrade=downgrade)


def upgrade() -> None:
    _rewrite_pipelines(downgrade=False)


def downgrade() -> None:
    _rewrite_pipelines(downgrade=True)
