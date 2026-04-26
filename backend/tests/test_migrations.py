from pathlib import Path

from sqlalchemy import create_engine, text

from core.database import _ensure_namespace_runtime_columns
from core.migrations import _alembic_config, migrate_runtime


def test_alembic_config_includes_runtime_scope(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    config = _alembic_config(scope='tenant', schema='alpha')

    assert config.get_main_option('sqlalchemy.url') == 'postgresql+psycopg://user:pass@host:5432/db'
    assert config.attributes['runtime_scope'] == 'tenant'
    assert config.attributes['target_schema'] == 'alpha'


def test_migrate_runtime_runs_public_then_each_tenant(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_current_revision(schema: str) -> str | None:
        if schema == 'alpha':
            return 'old-tenant-revision'
        return None

    def fake_has_version_table(schema: str) -> bool:
        return schema == 'alpha'

    monkeypatch.setattr('core.migrations._current_revision', fake_current_revision)
    monkeypatch.setattr('core.migrations._has_version_table', fake_has_version_table)
    monkeypatch.setattr('core.migrations._bootstrap_public_schema', lambda: calls.append(('bootstrap_public', 'public')))
    monkeypatch.setattr('core.migrations._bootstrap_tenant_schema', lambda schema: calls.append(('bootstrap_tenant', schema)))

    def fake_upgrade(config, target: str) -> None:
        calls.append((str(config.attributes['runtime_scope']), str(config.attributes['target_schema'])))
        assert target == 'head'

    monkeypatch.setattr('core.migrations.command.upgrade', fake_upgrade)
    monkeypatch.setattr('core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    migrate_runtime(['alpha', 'beta'])

    assert calls == [
        ('bootstrap_public', 'public'),
        ('tenant', 'alpha'),
        ('bootstrap_tenant', 'beta'),
    ]


def test_sqlite_runtime_bootstrap_adds_datasource_description_column(tmp_path: Path) -> None:
    db_path = tmp_path / 'namespace.db'
    engine = create_engine(f'sqlite:///{db_path}')
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    'CREATE TABLE datasources ('
                    'id VARCHAR PRIMARY KEY, '
                    'name VARCHAR NOT NULL, '
                    'source_type VARCHAR NOT NULL, '
                    'config JSON NOT NULL, '
                    'schema_cache JSON, '
                    'created_by_analysis_id VARCHAR, '
                    "created_by VARCHAR NOT NULL DEFAULT 'import', "
                    'is_hidden BOOLEAN NOT NULL DEFAULT 0, '
                    'owner_id VARCHAR, '
                    'created_at DATETIME NOT NULL'
                    ')'
                )
            )

        _ensure_namespace_runtime_columns(engine)

        with engine.begin() as connection:
            columns = connection.execute(text("PRAGMA table_info('datasources')")).all()
        column_names = {str(row[1]) for row in columns}
        assert 'description' in column_names
    finally:
        engine.dispose()
