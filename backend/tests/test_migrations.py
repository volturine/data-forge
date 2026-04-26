from pathlib import Path

import pytest

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
        return '0001_runtime_public' if schema == 'public' else None

    monkeypatch.setattr('core.migrations._current_revision', fake_current_revision)
    monkeypatch.setattr('core.migrations._bootstrap_public_schema', lambda: calls.append(('bootstrap_public', 'public')))
    monkeypatch.setattr('core.migrations._bootstrap_tenant_schema', lambda schema: calls.append(('bootstrap_tenant', schema)))
    monkeypatch.setattr('core.migrations.settings.database_url', 'postgresql+psycopg://user:pass@host:5432/db')

    migrate_runtime(['alpha', 'beta'])

    assert calls == [
        ('bootstrap_tenant', 'alpha'),
        ('bootstrap_tenant', 'beta'),
    ]


def test_migrate_runtime_rejects_existing_public_revision(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setattr('core.migrations._current_revision', lambda schema: 'legacy-public' if schema == 'public' else None)

    with pytest.raises(RuntimeError, match='Unsupported existing public schema revision'):
        migrate_runtime(['default'])


def test_migrate_runtime_rejects_existing_tenant_revision(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setattr(
        'core.migrations._current_revision', lambda schema: '0001_runtime_public' if schema == 'public' else 'legacy-tenant'
    )

    with pytest.raises(RuntimeError, match='Unsupported existing tenant schema revision'):
        migrate_runtime(['default'])
