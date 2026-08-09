from pathlib import Path

import pytest

from backend_core.config import settings
from backend_core.namespace import (
    get_namespace,
    list_namespaces,
    namespace_database_schema,
    namespace_paths,
    normalize_namespace,
    set_namespace_context,
)
from modules.namespaces import routes as namespace_routes
from tests.http_client import TestClient


def test_normalize_namespace_default():
    assert normalize_namespace(None) == settings.default_namespace
    assert normalize_namespace('') == settings.default_namespace


def test_normalize_namespace_rejects_invalid():
    with pytest.raises(ValueError, match='Invalid namespace'):
        normalize_namespace('bad name')
    with pytest.raises(ValueError, match='Invalid namespace'):
        normalize_namespace('Team_A')
    with pytest.raises(ValueError, match='Invalid namespace'):
        normalize_namespace('ab')


def test_normalize_namespace_allows_underscores():
    assert normalize_namespace('team_a') == 'team_a'
    assert normalize_namespace('my_namespace') == 'my_namespace'


def test_namespace_paths_creates_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ENV_FILE', '')
    from backend_core.config import Settings

    Settings()
    paths = namespace_paths('alpha')

    assert paths.base_dir == tmp_path / 'data' / 'namespaces' / 'alpha'
    assert paths.upload_dir.is_dir()
    assert paths.clean_dir.is_dir()
    assert paths.exports_dir.is_dir()
    assert paths.db_path == tmp_path / 'data' / 'namespaces' / 'alpha' / 'namespace.db'


def test_set_namespace_context():
    token = set_namespace_context('alpha')
    try:
        assert get_namespace() == 'alpha'
    finally:
        from backend_core.namespace import reset_namespace

        reset_namespace(token)


def test_namespace_database_schema_keeps_regular_namespaces() -> None:
    assert namespace_database_schema('alpha') == 'alpha'


def test_namespace_database_schema_maps_public_namespace_away_from_public_schema() -> None:
    assert namespace_database_schema('public') == 'df$tenant$public'


def test_list_namespaces(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ENV_FILE', '')
    from backend_core.config import Settings

    Settings()
    base = tmp_path / 'data' / 'namespaces'
    (base / 'alpha').mkdir(parents=True)
    (base / 'beta').mkdir(parents=True)
    (base / 'file.txt').write_text('x')

    assert list_namespaces() == ['alpha', 'beta']


def test_list_namespaces_endpoint_merges_filesystem_and_runtime_namespaces(monkeypatch):
    monkeypatch.setattr(namespace_routes, 'list_namespaces', lambda: ['alpha', 'default'])
    monkeypatch.setattr(namespace_routes, 'list_runtime_namespaces', lambda session: ['beta', 'default'])

    from main import app

    client = TestClient(app)
    response = client.get('/api/v1/namespaces')

    assert response.status_code == 200
    assert response.json() == {'namespaces': ['alpha', 'beta', 'default']}


def test_create_namespace_endpoint_registers_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []
    registered: list[str] = []
    provisioned: list[str] = []

    monkeypatch.setattr(namespace_routes, 'namespace_paths', lambda name: created.append(name))
    monkeypatch.setattr(namespace_routes, 'register_namespace', lambda session, name: registered.append(name))
    monkeypatch.setattr(namespace_routes, '_provision_namespace_bucket', lambda name: provisioned.append(name))

    from main import app

    client = TestClient(app)
    response = client.post('/api/v1/namespaces', json={'name': 'test'})

    assert response.status_code == 200
    body = response.json()
    assert body['name'] == 'test'
    assert body['created_bucket'] is True
    assert body['storage']['bucket'] == 'test'
    assert body['storage']['uploads_root'].startswith('s3://test/')
    assert created == ['test']
    assert registered == ['test']
    assert provisioned == ['test']


def test_provision_namespace_bucket_uses_explicit_data_plane_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    ensured: list[str] = []

    class FakeDataPlane:
        def ensure_object_store_bucket(self, name: str) -> None:
            ensured.append(name)

    monkeypatch.setattr(namespace_routes, 'client_from_settings', FakeDataPlane)

    namespace_routes._provision_namespace_bucket('analytics')

    assert ensured == ['analytics']


def test_namespace_storage_plan_endpoint_previews_exact_roots() -> None:
    from main import app

    client = TestClient(app)
    response = client.get('/api/v1/namespaces/storage-plan', params={'name': 'analytics'})

    assert response.status_code == 200
    body = response.json()
    assert body['name'] == 'analytics'
    assert body['bucket'] == 'analytics'
    assert body['uploads_root'] == 's3://analytics/uploads'
    assert body['clean_root'] == 's3://analytics/clean'
    assert body['exports_root'] == 's3://analytics/exports'
    assert 'rules' in body
    assert 'key_prefix' not in body
