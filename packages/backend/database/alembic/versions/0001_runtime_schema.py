"""Bootstrap the current shared and tenant schemas."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'runtime_schema_baseline'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ['revision', 'down_revision', 'branch_labels', 'depends_on', 'rewrite_pipeline_definition', 'upgrade', 'downgrade']

_BATCH_SIZE = 250
_PIVOT_REWRITE_REVISIONS = {'0022_telegram_part_receipts', '0023_drop_ds_freshness'}
_DROP_FRESHNESS_REVISION = '0022_telegram_part_receipts'
_CONSTRAINT_RENAMES = {
    'public': (
        ('compute_worker_instances', 'engine_instances_pkey', 'compute_worker_instances_pkey'),
        ('compute_worker_instances', 'engine_instances_id_not_null', 'compute_worker_instances_id_not_null'),
        ('compute_worker_instances', 'engine_instances_worker_id_not_null', 'compute_worker_instances_worker_id_not_null'),
        ('compute_worker_instances', 'engine_instances_namespace_not_null', 'compute_worker_instances_namespace_not_null'),
        ('compute_worker_instances', 'engine_instances_analysis_id_not_null', 'compute_worker_instances_analysis_id_not_null'),
        ('compute_worker_instances', 'engine_instances_engine_scope_not_null', 'compute_worker_instances_compute_worker_scope_not_null'),
        ('compute_worker_instances', 'engine_instances_engine_reuse_policy_not_null', 'compute_worker_instances_compute_worker_reuse_policy_not_null'),
        ('compute_worker_instances', 'engine_instances_status_not_null', 'compute_worker_instances_status_not_null'),
        ('compute_worker_instances', 'engine_instances_last_seen_at_not_null', 'compute_worker_instances_last_seen_at_not_null'),
        ('compute_worker_instances', 'engine_instances_updated_at_not_null', 'compute_worker_instances_updated_at_not_null'),
    ),
    'tenant': (
        ('compute_worker_runs', 'engine_runs_pkey', 'compute_worker_runs_pkey'),
        ('compute_worker_runs', 'engine_runs_id_not_null', 'compute_worker_runs_id_not_null'),
        ('compute_worker_runs', 'engine_runs_datasource_id_not_null', 'compute_worker_runs_datasource_id_not_null'),
        ('compute_worker_runs', 'engine_runs_kind_not_null', 'compute_worker_runs_kind_not_null'),
        ('compute_worker_runs', 'engine_runs_status_not_null', 'compute_worker_runs_status_not_null'),
        ('compute_worker_runs', 'engine_runs_request_json_not_null', 'compute_worker_runs_request_json_not_null'),
        ('compute_worker_runs', 'engine_runs_created_at_not_null', 'compute_worker_runs_created_at_not_null'),
        ('compute_worker_runs', 'engine_runs_step_timings_not_null', 'compute_worker_runs_step_timings_not_null'),
        ('compute_worker_runs', 'engine_runs_progress_not_null', 'compute_worker_runs_progress_not_null'),
        ('compute_worker_runs', 'engine_runs_namespace_not_null', 'compute_worker_runs_namespace_not_null'),
    ),
}


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


def _source_revision() -> str | None:
    value = op.get_context().opts.get('source_revision')
    return str(value) if value is not None else None


def rewrite_pipeline_definition(pipeline_definition: object, *, downgrade: bool) -> bool:
    """Rewrite one persisted pipeline definition for the pivot config change."""
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


def _tables(bind: sa.Connection, schema: str) -> set[str]:
    return set(sa.inspect(bind).get_table_names(schema=schema))


def _columns(bind: sa.Connection, schema: str, table_name: str) -> set[str]:
    if table_name not in _tables(bind, schema):
        return set()
    return {str(column['name']) for column in sa.inspect(bind).get_columns(table_name, schema=schema)}


def _rename_table(bind: sa.Connection, schema: str, old_name: str, new_name: str) -> None:
    tables = _tables(bind, schema)
    if old_name not in tables:
        return
    if new_name in tables:
        raise RuntimeError(f'Both {schema}.{old_name} and {schema}.{new_name} exist; refusing to merge persisted tables')
    op.rename_table(old_name, new_name, schema=schema)


def _rename_column(bind: sa.Connection, schema: str, table_name: str, old_name: str, new_name: str) -> None:
    columns = _columns(bind, schema, table_name)
    if old_name not in columns:
        return
    if new_name in columns:
        raise RuntimeError(f'Both {schema}.{table_name}.{old_name} and {new_name} exist; refusing to merge persisted columns')
    op.alter_column(table_name, old_name, new_column_name=new_name, schema=schema)


def _add_column(bind: sa.Connection, schema: str, table_name: str, column: sa.Column) -> None:
    if table_name in _tables(bind, schema) and column.name not in _columns(bind, schema, table_name):
        op.add_column(table_name, column, schema=schema)


def _drop_column(bind: sa.Connection, schema: str, table_name: str, column_name: str) -> None:
    if column_name in _columns(bind, schema, table_name):
        op.drop_column(table_name, column_name, schema=schema)


def _rename_index(bind: sa.Connection, schema: str, table_name: str, old_name: str, new_name: str) -> None:
    if table_name not in _tables(bind, schema):
        return
    names = {str(index['name']) for index in sa.inspect(bind).get_indexes(table_name, schema=schema)}
    if old_name not in names or new_name in names:
        return
    preparer = bind.dialect.identifier_preparer
    op.execute(sa.text(f'ALTER INDEX {preparer.quote_schema(schema)}.{preparer.quote(old_name)} RENAME TO {preparer.quote(new_name)}'))


def _rename_constraint(bind: sa.Connection, schema: str, table_name: str, old_name: str, new_name: str) -> None:
    row = (
        bind.execute(
            sa.text(
                """
            SELECT c.conname
            FROM pg_constraint AS c
            JOIN pg_class AS t ON t.oid = c.conrelid
            JOIN pg_namespace AS n ON n.oid = t.relnamespace
            WHERE n.nspname = :schema AND t.relname = :table_name
              AND c.conname IN (:old_name, :new_name)
            """
            ),
            {'schema': schema, 'table_name': table_name, 'old_name': old_name, 'new_name': new_name},
        )
        .scalars()
        .all()
    )
    names = set(row)
    if old_name in names and new_name in names:
        raise RuntimeError(f'Both constraints {schema}.{table_name}.{old_name} and {new_name} exist')
    if old_name not in names:
        return
    preparer = bind.dialect.identifier_preparer
    op.execute(
        sa.text(
            f'ALTER TABLE {preparer.quote_schema(schema)}.{preparer.quote(table_name)} '
            f'RENAME CONSTRAINT {preparer.quote(old_name)} TO {preparer.quote(new_name)}'
        )
    )


def _rewrite_table(bind: sa.Connection, schema: str, table_name: str) -> None:
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
        query = sa.select(table.c.id, table.c.pipeline_definition).order_by(table.c.id).limit(_BATCH_SIZE)
        if last_id is not None:
            query = query.where(table.c.id > last_id)
        batch = bind.execute(query).all()
        if not batch:
            return

        updates = []
        for row in batch:
            pipeline_definition = row.pipeline_definition
            if rewrite_pipeline_definition(pipeline_definition, downgrade=False):
                updates.append({'_row_id': row.id, '_pipeline_definition': pipeline_definition})
        if updates:
            bind.execute(update, updates)
        last_id = batch[-1].id


def _upgrade_public(bind: sa.Connection, schema: str) -> None:
    _rename_table(bind, schema, 'engine_instances', 'compute_worker_instances')
    for old_name, new_name in (
        ('engine_scope', 'compute_worker_scope'),
        ('engine_reuse_policy', 'compute_worker_reuse_policy'),
        ('current_engine_run_id', 'current_compute_worker_run_id'),
    ):
        _rename_column(bind, schema, 'compute_worker_instances', old_name, new_name)
    for old_name, new_name in (
        ('ix_engine_instances_worker_id', 'ix_compute_worker_instances_worker_id'),
        ('ix_engine_instances_namespace', 'ix_compute_worker_instances_namespace'),
        ('ix_engine_instances_analysis_id', 'ix_compute_worker_instances_analysis_id'),
        ('ix_engine_instances_engine_scope', 'ix_compute_worker_instances_compute_worker_scope'),
        ('ix_engine_instances_status', 'ix_compute_worker_instances_status'),
        ('ix_engine_instances_last_seen_at', 'ix_compute_worker_instances_last_seen_at'),
    ):
        _rename_index(bind, schema, 'compute_worker_instances', old_name, new_name)
    for table_name, old_name, new_name in _CONSTRAINT_RENAMES['public']:
        _rename_constraint(bind, schema, table_name, old_name, new_name)
    _add_column(bind, schema, 'compute_worker_instances', sa.Column('docker_host', sa.String(), nullable=True))


def _upgrade_tenant(bind: sa.Connection, schema: str, source_revision: str | None) -> None:
    if source_revision == _DROP_FRESHNESS_REVISION:
        _drop_column(bind, schema, 'datasources', 'freshness_threshold_minutes')
    if source_revision in _PIVOT_REWRITE_REVISIONS:
        for table_name in ('analyses', 'analysis_versions'):
            _rewrite_table(bind, schema, table_name)

    _rename_table(bind, schema, 'engine_runs', 'compute_worker_runs')
    for table_name, old_name, new_name in (
        ('compute_requests', 'engine_scope', 'compute_worker_scope'),
        ('compute_requests', 'engine_reuse_policy', 'compute_worker_reuse_policy'),
        ('compute_requests', 'engine_resource_id', 'compute_worker_resource_id'),
        ('build_runs', 'current_engine_run_id', 'current_compute_worker_run_id'),
        ('build_events', 'engine_run_id', 'compute_worker_run_id'),
    ):
        _rename_column(bind, schema, table_name, old_name, new_name)
    for table_name, old_name, new_name in (
        ('compute_worker_runs', 'ix_engine_runs_namespace', 'ix_compute_worker_runs_namespace'),
        ('compute_requests', 'ix_compute_requests_engine_identity', 'ix_compute_requests_compute_worker_identity'),
        ('build_runs', 'ix_build_runs_current_engine_run_id', 'ix_build_runs_current_compute_worker_run_id'),
        ('build_events', 'ix_build_events_engine_run_id', 'ix_build_events_compute_worker_run_id'),
    ):
        _rename_index(bind, schema, table_name, old_name, new_name)
    for table_name, old_name, new_name in _CONSTRAINT_RENAMES['tenant']:
        _rename_constraint(bind, schema, table_name, old_name, new_name)


def _scope_tables(scope: str, schema: str) -> tuple[sa.MetaData, list[sa.Table]]:
    from backend_core.database import _shared_tables, _tenant_tables

    source_tables = _shared_tables() if scope == 'public' else _tenant_tables()
    # Index names are already scoped by schema; excluding it avoids truncation collisions for long tenant names.
    metadata = sa.MetaData(naming_convention={'ix': 'ix_%(table_name)s_%(column_0_name)s'})
    return metadata, [table.to_metadata(metadata, schema=schema) for table in source_tables]


def upgrade() -> None:
    scope = _scope()
    schema = _schema()
    if scope not in {'public', 'tenant'}:
        raise RuntimeError(f'Unsupported migration scope: {scope}')

    bind = op.get_bind()
    source_revision = _source_revision()
    preparer = bind.dialect.identifier_preparer
    bind.execute(sa.text(f'SET LOCAL search_path TO {preparer.quote_schema(schema)}, public'))
    if scope == 'public':
        _upgrade_public(bind, schema)
    else:
        _upgrade_tenant(bind, schema, source_revision)

    metadata, tables = _scope_tables(scope, schema)
    if not tables:
        raise RuntimeError(f'No current tables registered for {scope} migration')
    metadata.create_all(bind, tables=tables, checkfirst=True)
    if scope == 'public':
        quoted_schema = preparer.quote_schema(schema)
        bind.execute(
            sa.text(
                f'INSERT INTO {quoted_schema}.app_settings '
                '(id, smtp_host, smtp_port, smtp_user, smtp_password, telegram_bot_token, telegram_bot_enabled, '
                'openrouter_api_key, openrouter_default_model, ollama_endpoint_url, ollama_default_model, '
                'env_bootstrap_complete, public_idb_debug) '
                'VALUES (1, :smtp_host, :smtp_port, :smtp_user, :smtp_password, :telegram_bot_token, '
                ':telegram_bot_enabled, :openrouter_api_key, :openrouter_default_model, :ollama_endpoint_url, '
                ':ollama_default_model, :env_bootstrap_complete, :public_idb_debug) '
                'ON CONFLICT (id) DO NOTHING'
            ),
            {
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'telegram_bot_enabled': False,
                'openrouter_api_key': '',
                'openrouter_default_model': '',
                'ollama_endpoint_url': 'http://localhost:11434',
                'ollama_default_model': 'llama3.2',
                'env_bootstrap_complete': True,
                'public_idb_debug': False,
            },
        )
        op.execute(
            sa.text(f'INSERT INTO {quoted_schema}.runtime_coordinator_state (singleton_id, generation) VALUES (1, 0) ON CONFLICT (singleton_id) DO NOTHING')
        )


def downgrade() -> None:
    metadata, tables = _scope_tables(_scope(), _schema())
    if tables:
        metadata.drop_all(op.get_bind(), tables=tables, checkfirst=True)
