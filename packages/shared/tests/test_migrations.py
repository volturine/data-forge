from pathlib import Path
from typing import Any

import pytest

from core.migrations import _PUBLIC_REVISION, _TENANT_REVISION, _alembic_config, ensure_database_exists, migrate_runtime


def test_alembic_config_includes_runtime_scope(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    config = _alembic_config(scope='tenant', schema='alpha')

    assert config.get_main_option('sqlalchemy.url') == 'postgresql+psycopg://user:pass@host:5432/db'
    assert config.attributes['runtime_scope'] == 'tenant'
    assert config.attributes['target_schema'] == 'alpha'
    assert config.attributes['configure_logging'] is False


def test_migrate_runtime_runs_public_then_each_tenant(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_current_revision(schema: str) -> str | None:
        revisions = {'public': None, 'alpha': None, 'beta': _TENANT_REVISION}
        return revisions[schema]

    monkeypatch.setattr('core.migrations._current_revision', fake_current_revision)
    monkeypatch.setattr('core.migrations._schema_has_table', lambda *, schema, table_name: False)
    monkeypatch.setattr('core.migrations.ensure_database_exists', lambda _database_url=None: calls.append(('ensure_database', 'db')))
    monkeypatch.setattr('core.migrations._upgrade_schema', lambda *, scope, schema, revision: calls.append((scope, f'{schema}:{revision}')))
    monkeypatch.setattr('core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    migrate_runtime(['alpha', 'beta'])

    assert calls == [('ensure_database', 'db'), ('public', f'public:{_PUBLIC_REVISION}'), ('tenant', f'alpha:{_TENANT_REVISION}')]


def test_ensure_database_exists_creates_missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    class FakeCursor:
        def __enter__(self) -> 'FakeCursor':
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object, params: object = None) -> None:
            calls.append(('execute', (statement, params)))

        def fetchone(self) -> None:
            calls.append(('fetchone', None))
            return None

    class FakeConnection:
        def __enter__(self) -> 'FakeConnection':
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    def fake_connect(database_url: str) -> FakeConnection:
        calls.append(('connect', database_url))
        return FakeConnection()

    monkeypatch.setattr('core.migrations._database_exists', lambda _database_url: False)
    monkeypatch.setattr('core.migrations._connect', fake_connect)

    ensure_database_exists('postgresql+psycopg://user:pass@127.0.0.1:5432/dataforge')

    assert calls[0] == ('connect', 'postgresql://user:pass@127.0.0.1:5432/postgres')
    assert calls[1] == ('execute', ('SELECT 1 FROM pg_database WHERE datname = %s', ('dataforge',)))
    assert calls[2] == ('fetchone', None)
    assert calls[3][0] == 'execute'
    assert calls[3][1][1] is None


def test_migrate_runtime_rejects_existing_public_revision(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setattr('core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('core.migrations._current_revision', lambda schema: 'legacy-public' if schema == 'public' else None)

    with pytest.raises(RuntimeError, match='Unsupported existing public schema revision'):
        migrate_runtime(['default'])


def test_migrate_runtime_rejects_existing_tenant_revision(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setattr('core.migrations.ensure_database_exists', lambda _database_url=None: None)
    monkeypatch.setattr('core.migrations._current_revision', lambda schema: _PUBLIC_REVISION if schema == 'public' else 'legacy-tenant')

    with pytest.raises(RuntimeError, match='Unsupported existing tenant schema revision'):
        migrate_runtime(['default'])
