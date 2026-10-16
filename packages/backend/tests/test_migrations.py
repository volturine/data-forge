import runpy
import uuid
from pathlib import Path
from typing import Any

import pytest
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

from backend_core import migrations, public_schema
from backend_core.migrations import _BASELINE_REVISION, _SCHEMA_REVISION, _alembic_config, ensure_database_exists, migrate_runtime
from backend_core.namespace import namespace_database_schema


def test_runtime_schema_has_one_shared_migration_head() -> None:
    versions_dir = Path(__file__).parents[1] / 'database' / 'alembic' / 'versions'

    assert len(_SCHEMA_REVISION) <= 32
    assert sorted(path.name for path in versions_dir.glob('*.py')) == ['0001_runtime_schema.py', '0002_view_cache_enabled.py']
    assert _BASELINE_REVISION == 'runtime_schema_baseline'
    assert _SCHEMA_REVISION == 'view_cache_enabled'


def test_pivot_values_migration_rewrites_only_legacy_pivot_configs() -> None:
    migration_path = Path(__file__).parents[1] / 'database' / 'alembic' / 'versions' / '0001_runtime_schema.py'
    rewrite_pipeline_definition = runpy.run_path(str(migration_path))['rewrite_pipeline_definition']
    pipeline_definition: dict[str, Any] = {
        'tabs': [
            {
                'steps': [
                    {'type': 'pivot', 'config': {'values': 'age'}},
                    {'type': 'pivot', 'config': {'values': None}},
                    {'type': 'pivot', 'config': {'values': 'stale', 'value_columns': ['sales', 'units']}},
                    {'type': 'filter', 'config': {'values': 'untouched'}},
                ]
            }
        ]
    }

    assert rewrite_pipeline_definition(pipeline_definition, downgrade=False)
    steps = pipeline_definition['tabs'][0]['steps']
    assert steps[0]['config'] == {'value_columns': ['age']}
    assert steps[1]['config'] == {'value_columns': []}
    assert steps[2]['config'] == {'value_columns': ['sales', 'units']}
    assert steps[3]['config'] == {'values': 'untouched'}
    assert not rewrite_pipeline_definition(pipeline_definition, downgrade=False)

    from modules.analysis.step_schemas import normalize_step_config

    assert normalize_step_config('pivot', steps[0]['config'])['value_columns'] == ['age']

    multiple_value_pipeline = {'tabs': [{'steps': [{'type': 'pivot', 'config': {'value_columns': ['sales', 'units']}}]}]}
    with pytest.raises(RuntimeError, match='multiple value_columns'):
        rewrite_pipeline_definition(multiple_value_pipeline, downgrade=True)


def test_view_cache_migration_preserves_explicit_values_and_unrelated_config() -> None:
    migration_path = Path(__file__).parents[1] / 'database' / 'alembic' / 'versions' / '0002_view_cache_enabled.py'
    rewrite_pipeline_definition = runpy.run_path(str(migration_path))['rewrite_pipeline_definition']
    pipeline_definition: dict[str, Any] = {
        'unknown_pipeline_field': {'keep': True},
        'tabs': [
            {
                'unknown_tab_field': 'keep',
                'steps': [
                    {'type': 'view', 'config': {'rowLimit': 100, 'other': 'keep'}},
                    {'type': 'view', 'config': {'rowLimit': 20, 'cacheEnabled': False, 'other': 'keep'}},
                    {'type': 'filter', 'config': {'cacheEnabled': False}},
                ],
            }
        ],
    }

    assert rewrite_pipeline_definition(pipeline_definition, downgrade=False)
    steps = pipeline_definition['tabs'][0]['steps']
    assert steps[0]['config'] == {'rowLimit': 100, 'other': 'keep', 'cacheEnabled': True}
    assert steps[1]['config'] == {'rowLimit': 20, 'cacheEnabled': False, 'other': 'keep'}
    assert steps[2]['config'] == {'cacheEnabled': False}
    assert pipeline_definition['unknown_pipeline_field'] == {'keep': True}
    assert pipeline_definition['tabs'][0]['unknown_tab_field'] == 'keep'
    assert not rewrite_pipeline_definition(pipeline_definition, downgrade=False)

    assert rewrite_pipeline_definition(pipeline_definition, downgrade=True)
    assert steps[0]['config'] == {'rowLimit': 100, 'other': 'keep'}
    assert steps[1]['config'] == {'rowLimit': 20, 'other': 'keep'}
    assert steps[2]['config'] == {'cacheEnabled': False}
    assert not rewrite_pipeline_definition(pipeline_definition, downgrade=True)


def test_public_schema_registers_telegram_runtime_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    created_table_names: set[str] = set()

    def capture_create_all(_connection: object, *, tables: list[object]) -> None:
        created_table_names.update(table.name for table in tables)  # type: ignore[attr-defined]

    monkeypatch.setattr(public_schema.User.metadata, 'create_all', capture_create_all)
    monkeypatch.setattr(public_schema, 'run_settings_connection_locked', lambda callback: callback(object()))

    public_schema.ensure_backend_public_tables()

    assert {'telegram_poll_offsets', 'telegram_detection_requests'} <= created_table_names
    assert {'telegram_poll_offsets', 'telegram_detection_requests'} <= SQLModel.metadata.tables.keys()


def test_alembic_config_includes_runtime_scope(monkeypatch) -> None:
    monkeypatch.setattr(migrations.settings, 'database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    config = _alembic_config(scope='tenant', schema='alpha')

    assert config.get_main_option('sqlalchemy.url') == 'postgresql+psycopg://user:pass@host:5432/db'
    assert config.attributes['runtime_scope'] == 'tenant'
    assert config.attributes['target_schema'] == 'alpha'
    assert config.attributes['configure_logging'] is False


def test_migrate_runtime_runs_public_then_each_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(migrations, 'ensure_database_exists', lambda _database_url=None: calls.append(('ensure', 'db')))
    monkeypatch.setattr(migrations, '_migrate_scope', lambda *, scope, schema: calls.append((scope, schema)))

    migrate_runtime(['alpha', 'beta'])

    assert calls == [
        ('ensure', 'db'),
        ('public', 'public'),
        ('tenant', namespace_database_schema('alpha')),
        ('tenant', namespace_database_schema('beta')),
    ]


@pytest.mark.parametrize(
    ('scope', 'schema', 'revision'),
    [
        ('public', 'public', '0020_runtime_wakes'),
        ('public', 'public', '0029_compute_worker_host'),
        ('tenant', 'default', '0022_telegram_part_receipts'),
        ('tenant', 'default', '0028_compute_worker_run'),
    ],
)
def test_migrate_scope_adopts_managed_legacy_revision(monkeypatch: pytest.MonkeyPatch, scope: str, schema: str, revision: str) -> None:
    calls: list[tuple[str, str, str] | tuple[str, str]] = []
    monkeypatch.setattr(migrations, '_current_revision', lambda _schema: revision)
    monkeypatch.setattr(
        migrations,
        '_upgrade_legacy_schema',
        lambda *, scope, schema, revision: calls.append(('adopt', scope, revision)),
    )
    monkeypatch.setattr(migrations, '_upgrade_schema', lambda *, scope, schema: calls.append(('upgrade', scope)))

    migrations._migrate_scope(scope=scope, schema=schema)

    assert calls == [('adopt', scope, revision), ('upgrade', scope)]


@pytest.mark.parametrize(('scope', 'schema'), [('public', 'public'), ('tenant', 'default')])
def test_migrate_scope_is_idempotent_at_head(monkeypatch: pytest.MonkeyPatch, scope: str, schema: str) -> None:
    calls: list[str] = []
    monkeypatch.setattr(migrations, '_current_revision', lambda _schema: _SCHEMA_REVISION)
    monkeypatch.setattr(migrations, '_upgrade_schema', lambda **_kwargs: calls.append('upgrade'))
    monkeypatch.setattr(migrations, '_upgrade_legacy_schema', lambda **_kwargs: calls.append('adopt'))

    migrations._migrate_scope(scope=scope, schema=schema)

    assert calls == []


def test_migrate_scope_upgrades_from_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(migrations, '_current_revision', lambda _schema: _BASELINE_REVISION)
    monkeypatch.setattr(migrations, '_upgrade_schema', lambda *, scope, schema: calls.append((scope, schema)))

    migrations._migrate_scope(scope='tenant', schema='default')

    assert calls == [('tenant', 'default')]


def test_migrate_scope_upgrades_fresh_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(migrations, '_current_revision', lambda _schema: None)
    monkeypatch.setattr(migrations, '_schema_is_empty', lambda _schema: True)
    monkeypatch.setattr(migrations, '_upgrade_schema', lambda *, scope, schema: calls.append((scope, schema)))

    migrations._migrate_scope(scope='public', schema='public')
    migrations._migrate_scope(scope='tenant', schema='default')

    assert calls == [('public', 'public'), ('tenant', 'default')]


def test_migrate_scope_rejects_unknown_nonempty_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrations, '_current_revision', lambda _schema: None)
    monkeypatch.setattr(migrations, '_schema_is_empty', lambda _schema: False)

    with pytest.raises(RuntimeError, match='without a migration revision'):
        migrations._migrate_scope(scope='tenant', schema='default')


@pytest.mark.parametrize(('scope', 'revision'), [('public', 'unsupported-public'), ('tenant', 'unsupported-tenant')])
def test_migrate_scope_rejects_unknown_revision(monkeypatch: pytest.MonkeyPatch, scope: str, revision: str) -> None:
    monkeypatch.setattr(migrations, '_current_revision', lambda _schema: revision)

    with pytest.raises(RuntimeError, match='Unsupported existing'):
        migrations._migrate_scope(scope=scope, schema='test_schema')


def test_ensure_database_exists_creates_missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    class FakeCursor:
        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object, params: object = None) -> None:
            calls.append(('execute', (statement, params)))

        def fetchone(self) -> None:
            calls.append(('fetchone', None))
            return None

    class FakeConnection:
        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    def fake_connect(database_url: str) -> FakeConnection:
        calls.append(('connect', database_url))
        return FakeConnection()

    monkeypatch.setattr(migrations, '_database_exists', lambda _database_url: False)
    monkeypatch.setattr(migrations, '_connect', fake_connect)

    ensure_database_exists('postgresql+psycopg://user:pass@127.0.0.1:5432/dataforge')

    assert calls[0] == ('connect', 'postgresql://user:pass@127.0.0.1:5432/postgres')
    assert calls[1] == ('execute', ('SELECT 1 FROM pg_database WHERE datname = %s', ('dataforge',)))
    assert calls[2] == ('fetchone', None)
    assert calls[3][0] == 'execute'
    assert calls[3][1][1] is None


def test_migrate_runtime_maps_public_namespace_to_tenant_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(migrations, 'ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr(migrations, '_migrate_scope', lambda *, scope, schema: calls.append((scope, schema)))

    migrate_runtime(['public'])

    assert calls == [('public', 'public'), ('tenant', namespace_database_schema('public'))]


def test_fresh_schema_upgrades_both_scopes_to_head(postgres_container, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = postgres_container.url
    monkeypatch.setattr(migrations.settings, 'database_url', database_url)
    engine = create_engine(database_url)
    schemas = [f'migration_public_{uuid.uuid4().hex}', f'migration_tenant_{uuid.uuid4().hex}']
    try:
        migrations._upgrade_schema(scope='public', schema=schemas[0])
        migrations._upgrade_schema(scope='tenant', schema=schemas[1])

        with engine.connect() as connection:
            revisions = [connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one() for schema in schemas]
            public_tables = set(inspect(connection).get_table_names(schema=schemas[0]))
            tenant_tables = set(inspect(connection).get_table_names(schema=schemas[1]))
            coordinator_generation = connection.execute(
                text(f'SELECT generation FROM "{schemas[0]}".runtime_coordinator_state WHERE singleton_id = 1')
            ).scalar_one()
            settings_count = connection.execute(text(f'SELECT COUNT(*) FROM "{schemas[0]}".app_settings')).scalar_one()

        assert revisions == [_SCHEMA_REVISION, _SCHEMA_REVISION]
        assert 'compute_worker_instances' in public_tables
        assert 'engine_instances' not in public_tables
        assert coordinator_generation == 0
        assert settings_count == 1
        assert 'compute_worker_runs' in tenant_tables
        assert 'engine_runs' not in tenant_tables

        from alembic import command

        for scope, schema in zip(('public', 'tenant'), schemas, strict=True):
            command.downgrade(_alembic_config(scope=scope, schema=schema), 'base', tag=scope)
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names(schema=schemas[0])) == {'alembic_version'}
            assert set(inspect(connection).get_table_names(schema=schemas[1])) == {'alembic_version'}

        from alembic import command

        for scope, schema in zip(('public', 'tenant'), schemas, strict=True):
            command.downgrade(_alembic_config(scope=scope, schema=schema), 'base', tag=scope)
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names(schema=schemas[0])) == {'alembic_version'}
            assert set(inspect(connection).get_table_names(schema=schemas[1])) == {'alembic_version'}
    finally:
        with engine.begin() as connection:
            for schema in schemas:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_squashed_baseline_preserves_legacy_public_worker_instances(postgres_container, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = postgres_container.url
    monkeypatch.setattr(migrations.settings, 'database_url', database_url)
    schema = f'migration_public_legacy_{uuid.uuid4().hex}'
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'CREATE TABLE "{schema}".alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
            connection.execute(
                text(f'INSERT INTO "{schema}".alembic_version (version_num) VALUES (:revision)'),
                {'revision': '0020_runtime_wakes'},
            )
            connection.execute(
                text(
                    f"""
                    CREATE TABLE "{schema}".engine_instances (
                        id VARCHAR NOT NULL,
                        worker_id VARCHAR NOT NULL,
                        namespace VARCHAR NOT NULL,
                        analysis_id VARCHAR NOT NULL,
                        engine_scope VARCHAR NOT NULL,
                        engine_reuse_policy VARCHAR NOT NULL,
                        datasource_id VARCHAR,
                        build_id VARCHAR,
                        container_id VARCHAR,
                        image_digest VARCHAR,
                        termination_reason VARCHAR,
                        exit_code INTEGER,
                        oom_killed BOOLEAN,
                        supervisor_id VARCHAR,
                        owner_id VARCHAR,
                        status VARCHAR NOT NULL,
                        current_job_id VARCHAR,
                        current_build_id VARCHAR,
                        current_engine_run_id VARCHAR,
                        resource_config_json JSON,
                        effective_resources_json JSON,
                        last_activity_at TIMESTAMPTZ,
                        last_seen_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        CONSTRAINT engine_instances_pkey PRIMARY KEY (id),
                        CONSTRAINT engine_instances_worker_id_not_null CHECK (worker_id IS NOT NULL),
                        CONSTRAINT engine_instances_namespace_not_null CHECK (namespace IS NOT NULL),
                        CONSTRAINT engine_instances_analysis_id_not_null CHECK (analysis_id IS NOT NULL),
                        CONSTRAINT engine_instances_engine_scope_not_null CHECK (engine_scope IS NOT NULL),
                        CONSTRAINT engine_instances_engine_reuse_policy_not_null CHECK (engine_reuse_policy IS NOT NULL),
                        CONSTRAINT engine_instances_status_not_null CHECK (status IS NOT NULL),
                        CONSTRAINT engine_instances_last_seen_at_not_null CHECK (last_seen_at IS NOT NULL),
                        CONSTRAINT engine_instances_updated_at_not_null CHECK (updated_at IS NOT NULL)
                    )
                    """
                )
            )
            for old_index, column in (
                ('ix_engine_instances_worker_id', 'worker_id'),
                ('ix_engine_instances_namespace', 'namespace'),
                ('ix_engine_instances_analysis_id', 'analysis_id'),
                ('ix_engine_instances_engine_scope', 'engine_scope'),
                ('ix_engine_instances_status', 'status'),
                ('ix_engine_instances_last_seen_at', 'last_seen_at'),
            ):
                connection.execute(text(f'CREATE INDEX {old_index} ON "{schema}".engine_instances ({column})'))
            connection.execute(
                text(
                    f"""
                    INSERT INTO "{schema}".engine_instances (
                        id, worker_id, namespace, analysis_id, engine_scope, engine_reuse_policy,
                        status, current_engine_run_id, last_seen_at, updated_at
                    ) VALUES ('instance-1', 'worker-1', 'default', 'analysis-1', 'interactive', 'shared', 'idle', 'run-1', now(), now())
                    """
                )
            )

        migrations._upgrade_legacy_schema(scope='public', schema=schema, revision='0020_runtime_wakes')

        with engine.connect() as connection:
            version = connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one()
            columns = {column['name'] for column in inspect(connection).get_columns('compute_worker_instances', schema=schema)}
            row = connection.execute(
                text(
                    f'SELECT compute_worker_scope, compute_worker_reuse_policy, current_compute_worker_run_id '
                    f'FROM "{schema}".compute_worker_instances WHERE id = :id'
                ),
                {'id': 'instance-1'},
            ).one()
            indexes = {index['name'] for index in inspect(connection).get_indexes('compute_worker_instances', schema=schema)}
            primary_key = inspect(connection).get_pk_constraint('compute_worker_instances', schema=schema)['name']

        assert version == _BASELINE_REVISION
        assert {'compute_worker_scope', 'compute_worker_reuse_policy', 'current_compute_worker_run_id', 'docker_host'} <= columns
        assert {'engine_scope', 'engine_reuse_policy', 'current_engine_run_id'}.isdisjoint(columns)
        assert row == ('interactive', 'shared', 'run-1')
        assert {
            'ix_compute_worker_instances_worker_id',
            'ix_compute_worker_instances_namespace',
            'ix_compute_worker_instances_analysis_id',
            'ix_compute_worker_instances_compute_worker_scope',
            'ix_compute_worker_instances_status',
            'ix_compute_worker_instances_last_seen_at',
        } <= indexes
        assert primary_key == 'compute_worker_instances_pkey'

        migrations._migrate_scope(scope='public', schema=schema)
        with engine.connect() as connection:
            assert connection.execute(text(f'SELECT COUNT(*) FROM "{schema}".compute_worker_instances')).scalar_one() == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_squashed_baseline_preserves_tenant_rows_and_rewrites_pivot_values(postgres_container, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = postgres_container.url
    monkeypatch.setattr(migrations.settings, 'database_url', database_url)
    schema = f'migration_tenant_legacy_{uuid.uuid4().hex}'
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'CREATE TABLE "{schema}".alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
            connection.execute(
                text(f'INSERT INTO "{schema}".alembic_version (version_num) VALUES (:revision)'),
                {'revision': '0022_telegram_part_receipts'},
            )
            connection.execute(text(f'CREATE TABLE "{schema}".datasources (id VARCHAR PRIMARY KEY, freshness_threshold_minutes INTEGER)'))
            connection.execute(text(f'CREATE TABLE "{schema}".analyses (id VARCHAR PRIMARY KEY, pipeline_definition JSON)'))
            connection.execute(text(f'CREATE TABLE "{schema}".analysis_versions (id VARCHAR PRIMARY KEY, pipeline_definition JSON)'))
            connection.execute(
                text(f'CREATE TABLE "{schema}".engine_runs (id VARCHAR NOT NULL, namespace VARCHAR NOT NULL, CONSTRAINT engine_runs_pkey PRIMARY KEY (id))')
            )
            connection.execute(text(f'CREATE INDEX ix_engine_runs_namespace ON "{schema}".engine_runs (namespace)'))
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".compute_requests '
                    '(id VARCHAR PRIMARY KEY, engine_scope VARCHAR, engine_reuse_policy VARCHAR, engine_resource_id VARCHAR)'
                )
            )
            connection.execute(text(f'CREATE TABLE "{schema}".build_runs (id VARCHAR PRIMARY KEY, current_engine_run_id VARCHAR)'))
            connection.execute(text(f'CREATE TABLE "{schema}".build_events (id VARCHAR PRIMARY KEY, engine_run_id VARCHAR)'))
            connection.execute(text(f'CREATE INDEX ix_compute_requests_engine_identity ON "{schema}".compute_requests (engine_scope)'))
            connection.execute(text(f'CREATE INDEX ix_build_runs_current_engine_run_id ON "{schema}".build_runs (current_engine_run_id)'))
            connection.execute(text(f'CREATE INDEX ix_build_events_engine_run_id ON "{schema}".build_events (engine_run_id)'))
            pipeline = {
                'tabs': [
                    {
                        'steps': [
                            {'type': 'pivot', 'config': {'values': 'age'}},
                            {'type': 'view', 'config': {'rowLimit': 100, 'cacheEnabled': False}},
                            {'type': 'view', 'config': {'rowLimit': 25}},
                        ]
                    }
                ]
            }
            connection.execute(
                text(f'INSERT INTO "{schema}".analyses (id, pipeline_definition) VALUES (:id, :definition)'),
                {'id': 'analysis-1', 'definition': Jsonb(pipeline)},
            )
            connection.execute(
                text(f'INSERT INTO "{schema}".analysis_versions (id, pipeline_definition) VALUES (:id, :definition)'),
                {'id': 'version-1', 'definition': Jsonb(pipeline)},
            )
            connection.execute(
                text(f'INSERT INTO "{schema}".engine_runs (id, namespace) VALUES (:id, :namespace)'),
                {'id': 'run-1', 'namespace': 'default'},
            )

        migrations._upgrade_legacy_schema(scope='tenant', schema=schema, revision='0022_telegram_part_receipts')

        with engine.connect() as connection:
            revision = connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one()
            datasource_columns = {column['name'] for column in inspect(connection).get_columns('datasources', schema=schema)}
            analysis = connection.execute(text(f'SELECT pipeline_definition FROM "{schema}".analyses WHERE id = :id'), {'id': 'analysis-1'}).scalar_one()
            analysis_version = connection.execute(
                text(f'SELECT pipeline_definition FROM "{schema}".analysis_versions WHERE id = :id'), {'id': 'version-1'}
            ).scalar_one()
            run = connection.execute(text(f'SELECT id FROM "{schema}".compute_worker_runs')).scalar_one()
            requests_columns = {column['name'] for column in inspect(connection).get_columns('compute_requests', schema=schema)}
            primary_key = inspect(connection).get_pk_constraint('compute_worker_runs', schema=schema)['name']

        assert revision == _BASELINE_REVISION
        assert 'freshness_threshold_minutes' not in datasource_columns
        assert analysis['tabs'][0]['steps'][0]['config'] == {'value_columns': ['age']}
        assert analysis_version['tabs'][0]['steps'][0]['config'] == {'value_columns': ['age']}
        assert analysis['tabs'][0]['steps'][1]['config'] == {'rowLimit': 100, 'cacheEnabled': False}
        assert analysis_version['tabs'][0]['steps'][1]['config'] == {'rowLimit': 100, 'cacheEnabled': False}
        assert analysis['tabs'][0]['steps'][2]['config'] == {'rowLimit': 25}
        assert analysis_version['tabs'][0]['steps'][2]['config'] == {'rowLimit': 25}
        assert run == 'run-1'
        assert {'compute_worker_scope', 'compute_worker_reuse_policy', 'compute_worker_resource_id'} <= requests_columns
        assert {'engine_scope', 'engine_reuse_policy', 'engine_resource_id'}.isdisjoint(requests_columns)
        assert primary_key == 'compute_worker_runs_pkey'

        migrations._migrate_scope(scope='tenant', schema=schema)
        with engine.connect() as connection:
            assert connection.execute(text(f'SELECT COUNT(*) FROM "{schema}".compute_worker_runs')).scalar_one() == 1
            assert connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one() == _SCHEMA_REVISION
            migrated_analysis = connection.execute(
                text(f'SELECT pipeline_definition FROM "{schema}".analyses WHERE id = :id'), {'id': 'analysis-1'}
            ).scalar_one()
            migrated_version = connection.execute(
                text(f'SELECT pipeline_definition FROM "{schema}".analysis_versions WHERE id = :id'), {'id': 'version-1'}
            ).scalar_one()

        for pipeline_definition in (migrated_analysis, migrated_version):
            steps = pipeline_definition['tabs'][0]['steps']
            assert steps[1]['config'] == {'rowLimit': 100, 'cacheEnabled': False}
            assert steps[2]['config'] == {'rowLimit': 25, 'cacheEnabled': True}
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
