from pathlib import Path
from typing import Any

import pytest
from sqlmodel import SQLModel

from backend_core import public_schema
from backend_core.migrations import _PUBLIC_REVISION, _TENANT_REVISION, _alembic_config, ensure_database_exists, migrate_runtime
from backend_core.namespace import namespace_database_schema


def test_runtime_schema_has_only_public_and_tenant_creation_revisions() -> None:
    versions_dir = Path(__file__).parents[1] / 'database' / 'alembic' / 'versions'

    assert len(_TENANT_REVISION) <= 32  # alembic_version.version_num is VARCHAR(32)
    assert sorted(path.name for path in versions_dir.glob('*.py')) == [
        '0001_runtime_public.py',
        '0002_runtime_tenant.py',
        '0003_engine_request_identity.py',
        '0004_compute_request_datasources.py',
        '0005_durable_preview_flights.py',
        '0006_runtime_namespace_work.py',
        '0007_schedule_due_index.py',
        '0008_schedule_trigger_index.py',
        '0008_schedule_wake_due.py',
        '0009_runtime_lease_wake_due.py',
        '0010_mcp_pending_actions.py',
        '0011_namespace_scoped_preview_flights.py',
        '0012_compute_request_flights.py',
        '0013_runtime_work_wakes.py',
        '0014_runtime_coordinator_fencing.py',
        '0015_durable_chat_turns.py',
        '0016_telegram_integration_runtime.py',
        '0017_compute_source_index.py',
    ]


def test_public_revision_is_telegram_runtime_head() -> None:
    assert _PUBLIC_REVISION == '0016_telegram_runtime'


def test_public_schema_registers_telegram_runtime_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    created_table_names: set[str] = set()

    def capture_create_all(_connection: object, *, tables: list[object]) -> None:
        created_table_names.update(table.name for table in tables)  # type: ignore[attr-defined]

    monkeypatch.setattr(public_schema.User.metadata, 'create_all', capture_create_all)
    monkeypatch.setattr(public_schema, 'run_settings_connection_locked', lambda callback: callback(object()))

    public_schema.ensure_backend_public_tables()

    assert {'telegram_poll_offsets', 'telegram_detection_requests'} <= created_table_names
    assert {'telegram_poll_offsets', 'telegram_detection_requests'} <= SQLModel.metadata.tables.keys()


def test_alembic_config_includes_runtime_scope(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('backend_core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    config = _alembic_config(scope='tenant', schema='alpha')

    assert config.get_main_option('sqlalchemy.url') == 'postgresql+psycopg://user:pass@host:5432/db'
    assert config.attributes['runtime_scope'] == 'tenant'
    assert config.attributes['target_schema'] == 'alpha'
    assert config.attributes['configure_logging'] is False


def test_migrate_runtime_runs_public_then_each_tenant(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_current_revision(schema: str) -> str | None:
        revisions = {'public': None, 'alpha': None, 'beta': _TENANT_REVISION, 'gamma': '0007_schedule_due_index'}
        return revisions[schema]

    monkeypatch.setattr('backend_core.migrations._current_revision', fake_current_revision)
    monkeypatch.setattr(
        'backend_core.migrations._schema_is_empty',
        lambda schema: schema == namespace_database_schema('alpha'),
    )
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: calls.append(('ensure_database', 'db')))
    monkeypatch.setattr('backend_core.migrations._upgrade_schema', lambda *, scope, schema, revision: calls.append((scope, f'{schema}:{revision}')))
    monkeypatch.setattr('backend_core.migrations._bootstrap_empty_tenant_schema', lambda schema: calls.append(('tenant-bootstrap', schema)))
    monkeypatch.setattr('backend_core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    migrate_runtime(['alpha', 'beta', 'gamma'])

    assert calls == [
        ('ensure_database', 'db'),
        ('public', f'public:{_PUBLIC_REVISION}'),
        ('tenant-bootstrap', namespace_database_schema('alpha')),
        ('tenant', f'gamma:{_TENANT_REVISION}'),
    ]


def test_migrate_runtime_upgrades_existing_public_work_index(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr('backend_core.migrations._current_revision', lambda schema: '0006_runtime_namespace_work' if schema == 'public' else _TENANT_REVISION)
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('backend_core.migrations._upgrade_schema', lambda *, scope, schema, revision: calls.append((scope, f'{schema}:{revision}')))
    monkeypatch.setattr('backend_core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    migrate_runtime(['default'])

    assert calls == [('public', f'public:{_PUBLIC_REVISION}')]


def test_migrate_runtime_upgrades_existing_schedule_wake_index(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr('backend_core.migrations._current_revision', lambda schema: '0008_schedule_wake_due' if schema == 'public' else _TENANT_REVISION)
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('backend_core.migrations._upgrade_schema', lambda *, scope, schema, revision: calls.append((scope, f'{schema}:{revision}')))
    monkeypatch.setattr('backend_core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    migrate_runtime(['default'])

    assert calls == [('public', f'public:{_PUBLIC_REVISION}')]


def test_migrate_runtime_upgrades_existing_public_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr('backend_core.migrations._current_revision', lambda schema: '0010_mcp_pending_actions' if schema == 'public' else _TENANT_REVISION)
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('backend_core.migrations._upgrade_schema', lambda *, scope, schema, revision: calls.append((scope, f'{schema}:{revision}')))
    monkeypatch.setattr('backend_core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    migrate_runtime(['default'])

    assert calls == [('public', f'public:{_PUBLIC_REVISION}')]


def test_migrate_runtime_upgrades_durable_chat_revision_to_telegram_head(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr('backend_core.migrations._current_revision', lambda schema: '0015_durable_chat_turns' if schema == 'public' else _TENANT_REVISION)
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('backend_core.migrations._upgrade_schema', lambda *, scope, schema, revision: calls.append((scope, f'{schema}:{revision}')))

    migrate_runtime(['default'])

    assert calls == [('public', f'public:{_PUBLIC_REVISION}')]


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

    monkeypatch.setattr('backend_core.migrations._database_exists', lambda _database_url: False)
    monkeypatch.setattr('backend_core.migrations._connect', fake_connect)

    ensure_database_exists('postgresql+psycopg://user:pass@127.0.0.1:5432/dataforge')

    assert calls[0] == ('connect', 'postgresql://user:pass@127.0.0.1:5432/postgres')
    assert calls[1] == ('execute', ('SELECT 1 FROM pg_database WHERE datname = %s', ('dataforge',)))
    assert calls[2] == ('fetchone', None)
    assert calls[3][0] == 'execute'
    assert calls[3][1][1] is None


def test_migrate_runtime_rejects_existing_public_revision(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('backend_core.migrations._current_revision', lambda schema: 'unsupported-public' if schema == 'public' else None)

    with pytest.raises(RuntimeError, match='Unsupported existing public schema revision'):
        migrate_runtime(['default'])


def test_migrate_runtime_rejects_existing_tenant_revision(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('backend_core.migrations._current_revision', lambda schema: _PUBLIC_REVISION if schema == 'public' else 'unsupported-tenant')

    with pytest.raises(RuntimeError, match='Unsupported existing tenant schema revision'):
        migrate_runtime(['default'])


def test_migrate_runtime_maps_public_namespace_to_tenant_schema(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    tenant_schema = namespace_database_schema('public')

    def fake_current_revision(schema: str) -> str | None:
        revisions = {'public': _PUBLIC_REVISION, namespace_database_schema('public'): None}
        return revisions.get(schema)

    monkeypatch.setattr('backend_core.migrations._current_revision', fake_current_revision)
    monkeypatch.setattr('backend_core.migrations.ensure_database_exists', lambda _database_url=None: calls.append(('ensure_database', 'db')))
    monkeypatch.setattr('backend_core.migrations._schema_is_empty', lambda schema: schema == tenant_schema)
    monkeypatch.setattr('backend_core.migrations._bootstrap_empty_tenant_schema', lambda schema: calls.append(('tenant-bootstrap', schema)))

    migrate_runtime(['public'])

    assert calls == [
        ('ensure_database', 'db'),
        ('tenant-bootstrap', tenant_schema),
    ]
