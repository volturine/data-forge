from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlmodel import SQLModel

from core.config import settings
from modules.analysis import models as analysis_models
from modules.analysis_versions import models as analysis_versions_models
from modules.auth import models as auth_models
from modules.build_jobs import models as build_jobs_models
from modules.build_runs import models as build_runs_models
from modules.chat.sessions import ChatSession
from modules.datasource import models as datasource_models
from modules.engine_instances import models as engine_instances_models
from modules.engine_runs import models as engine_runs_models
from modules.healthcheck import models as healthcheck_models
from modules.locks import models as locks_models
from modules.runtime_workers import models as runtime_workers_models
from modules.scheduler import models as scheduler_models
from modules.settings import models as settings_models
from modules.telegram import models as telegram_models
from modules.udf import models as udf_models

del analysis_models
del analysis_versions_models
del auth_models
del build_jobs_models
del build_runs_models
del datasource_models
del engine_instances_models
del engine_runs_models
del healthcheck_models
del locks_models
del runtime_workers_models
del scheduler_models
del settings_models
del telegram_models
del udf_models
del ChatSession

config = context.config
config.set_main_option('sqlalchemy.url', settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_SHARED_TABLES = {
    'app_settings',
    'auth_providers',
    'chat_sessions',
    'engine_instances',
    'runtime_workers',
    'user_sessions',
    'users',
    'verification_tokens',
}
_TENANT_TABLES = {
    'analyses',
    'analysis_datasources',
    'analysis_versions',
    'build_events',
    'build_jobs',
    'build_runs',
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
    return str(config.attributes.get('runtime_scope', 'public'))


def _target_schema() -> str:
    return str(config.attributes.get('target_schema', 'public'))


def _runtime_attributes() -> dict[str, Any]:
    raw = config.attributes
    return raw if isinstance(raw, dict) else {}


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
        version_table_schema=_target_schema() if settings.is_postgres else None,
        include_schemas=settings.is_postgres,
        render_as_batch=not settings.is_postgres,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration['sqlalchemy.url'] = settings.database_url
    connectable = create_engine(configuration['sqlalchemy.url'], poolclass=pool.NullPool)

    with connectable.connect() as connection:
        if settings.is_postgres:
            schema = _target_schema()
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            connection.execute(text(f'SET search_path TO "{schema}", public'))
        context.configure(
            connection=connection,
            target_metadata=_target_metadata(),
            include_object=_include_object,
            version_table_schema=_target_schema() if settings.is_postgres else None,
            include_schemas=settings.is_postgres,
            render_as_batch=not settings.is_postgres,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
