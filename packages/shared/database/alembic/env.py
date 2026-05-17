import importlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlmodel import SQLModel

from core.config import settings
from core.migrations import ensure_database_exists

_MODEL_MODULES = (
    'contracts.analysis.models',
    'contracts.datasource.models',
    'contracts.healthcheck_models',
    'contracts.compute_requests.models',
    'contracts.namespaces.models',
    'contracts.settings_models',
    'contracts.telegram_models',
    'contracts.udf_models',
    'contracts.analysis_versions.models',
    'contracts.build_jobs.models',
    'contracts.build_runs.models',
    'contracts.engine_instances.models',
    'contracts.engine_runs.models',
    'contracts.locks.models',
    'contracts.runtime_workers.models',
    'contracts.scheduler.models',
)

for module_name in _MODEL_MODULES:
    importlib.import_module(module_name)

config = context.config
config.set_main_option('sqlalchemy.url', settings.database_url)


def _should_configure_logging() -> bool:
    return bool(config.attributes.get('configure_logging', True))


if config.config_file_name is not None and _should_configure_logging():
    fileConfig(config.config_file_name)

_SHARED_TABLES = {'app_settings', 'engine_instances', 'runtime_namespaces', 'runtime_workers'}
_TENANT_TABLES = {
    'analyses',
    'analysis_datasources',
    'analysis_versions',
    'build_events',
    'build_jobs',
    'build_runs',
    'compute_requests',
    'datasources',
    'datasource_column_metadata',
    'engine_runs',
    'healthcheck_results',
    'healthchecks',
    'resource_locks',
    'schedules',
    'telegram_listeners',
    'telegram_subscribers',
    'udfs',
}


def _runtime_scope() -> str:
    return context.get_tag_argument() or config.get_main_option('runtime_scope') or str(config.attributes.get('runtime_scope', 'public'))


def _target_schema() -> str:
    return config.get_main_option('target_schema') or str(config.attributes.get('target_schema', 'public'))


def _table_names() -> set[str]:
    if _runtime_scope() == 'tenant':
        return _TENANT_TABLES
    return _SHARED_TABLES


def _target_metadata():
    metadata = SQLModel.metadata
    names = _table_names()
    metadata.info['alembic_table_names'] = names
    metadata.info['alembic_target_schema'] = _target_schema()
    return metadata


def _include_object(object_, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    del object_, reflected, compare_to
    if type_ != 'table':
        return True
    return name in _table_names()


def run_migrations_offline() -> None:
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=_target_metadata(),
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        include_object=_include_object,
        version_table_schema=_target_schema(),
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration['sqlalchemy.url'] = settings.database_url
    ensure_database_exists(settings.database_url)
    connectable = create_engine(configuration['sqlalchemy.url'], poolclass=pool.NullPool)

    with connectable.connect() as connection:
        schema = _target_schema()
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        context.configure(
            connection=connection, target_metadata=_target_metadata(), include_object=_include_object, version_table_schema=schema, include_schemas=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
