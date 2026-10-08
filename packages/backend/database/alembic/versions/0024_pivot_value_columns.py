"""Migrate saved pivot values to value_columns.

Revision ID: 0024_pivot_value_columns
Revises: 0023_drop_ds_freshness
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0024_pivot_value_columns'
down_revision: str | Sequence[str] | None = '0023_drop_ds_freshness'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = [
    'revision',
    'down_revision',
    'branch_labels',
    'depends_on',
    'rewrite_pipeline_definition',
    'upgrade',
    'downgrade',
]

_BATCH_SIZE = 250
_TABLE_NAMES = ('analyses', 'analysis_versions')


def _scope() -> str:
    migration_context = op.get_context()
    config = migration_context.config
    if config is None:
        return 'public'
    return str(migration_context.opts.get('tag') or config.get_main_option('runtime_scope') or config.attributes.get('runtime_scope', 'public'))


def rewrite_pipeline_definition(pipeline_definition: object, *, downgrade: bool) -> bool:
    """Rewrite one persisted pipeline definition for this migration."""
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
            if not isinstance(step, dict) or step.get('type') != 'pivot':
                continue
            config = step.get('config')
            if not isinstance(config, dict):
                continue

            if downgrade:
                if 'value_columns' not in config:
                    continue
                value_columns = config.pop('value_columns')
                if not isinstance(value_columns, list) or not all(isinstance(value, str) for value in value_columns):
                    raise RuntimeError('Cannot downgrade pivot config with invalid value_columns')
                if len(value_columns) > 1:
                    raise RuntimeError('Cannot downgrade pivot config with multiple value_columns')
                config['values'] = value_columns[0] if value_columns else None
            else:
                if 'values' not in config:
                    continue
                values = config.pop('values')
                if 'value_columns' not in config:
                    if values is None or values == '':
                        config['value_columns'] = []
                    elif isinstance(values, str):
                        config['value_columns'] = [values]
                    elif isinstance(values, list) and all(isinstance(value, str) for value in values):
                        config['value_columns'] = values
                    else:
                        raise RuntimeError(f'Cannot migrate pivot values of type {type(values).__name__}')
            changed = True

    return changed


def _rewrite_table(table_name: str, *, downgrade: bool) -> None:
    connection = op.get_bind()
    table = sa.Table(
        table_name,
        sa.MetaData(),
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('pipeline_definition', sa.JSON()),
    )
    update = sa.update(table).where(table.c.id == sa.bindparam('_row_id')).values(pipeline_definition=sa.bindparam('_pipeline_definition', type_=sa.JSON()))
    last_id: str | None = None
    while True:
        query = sa.select(table.c.id, table.c.pipeline_definition).order_by(table.c.id).limit(_BATCH_SIZE)
        if last_id is not None:
            query = query.where(table.c.id > last_id)
        batch = connection.execute(query).all()
        if not batch:
            return

        updates = []
        for row in batch:
            pipeline_definition = row.pipeline_definition
            if rewrite_pipeline_definition(pipeline_definition, downgrade=downgrade):
                updates.append({'_row_id': row.id, '_pipeline_definition': pipeline_definition})
        if updates:
            connection.execute(update, updates)
        last_id = batch[-1].id


def upgrade() -> None:
    if _scope() != 'tenant':
        return
    for table_name in _TABLE_NAMES:
        _rewrite_table(table_name, downgrade=False)


def downgrade() -> None:
    if _scope() != 'tenant':
        return
    for table_name in _TABLE_NAMES:
        _rewrite_table(table_name, downgrade=True)
