import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from threading import Barrier, Event

import pytest

from backend_core.api_execution_budget import BoundedThreadPoolExecutor
from backend_core.config import settings
from backend_core.database import run_settings_db
from backend_core.namespace import (
    get_namespace,
    namespace_database_schema,
    normalize_namespace,
    set_namespace_context,
)
from backend_core.namespaces_service import list_runtime_namespaces
from backend_core.persistence.namespaces.models import RuntimeNamespace
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


def test_normalize_namespace_rejects_underscores():
    # Namespace names are used verbatim as S3 bucket names, which forbid underscores.
    with pytest.raises(ValueError, match='Invalid namespace'):
        normalize_namespace('team_a')
    with pytest.raises(ValueError, match='Invalid namespace'):
        normalize_namespace('my_namespace')
    assert normalize_namespace('team-a') == 'team-a'


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


def test_namespaces_endpoint_reads_only_the_runtime_registry(monkeypatch):
    # Every API replica must answer identically, so the list comes from
    # PostgreSQL alone and never from a replica's local filesystem.
    monkeypatch.setattr(namespace_routes, 'list_runtime_namespaces', lambda session: ['beta', 'default'])

    from backend_core.application import app

    client = TestClient(app)
    response = client.get('/api/v1/namespaces')

    assert response.status_code == 200
    assert response.json() == {'namespaces': ['beta', 'default']}


@contextmanager
def _registered_rows(*names: str):
    def insert(session) -> None:
        for name in names:
            session.add(RuntimeNamespace(name=name))
        session.commit()

    def remove(session) -> None:
        for name in names:
            row = session.get(RuntimeNamespace, name)
            if row is not None:
                session.delete(row)
        session.commit()

    run_settings_db(insert)
    try:
        yield
    finally:
        run_settings_db(remove)


def test_list_runtime_namespaces_skips_rows_with_invalid_names(caplog: pytest.LogCaptureFixture) -> None:
    suffix = uuid.uuid4().hex[:8]
    valid = f'valid-{suffix}'
    legacy = f'legacy_{suffix}'

    with _registered_rows(valid, legacy), caplog.at_level(logging.WARNING, logger='backend_core.namespaces_service'):
        names = run_settings_db(list_runtime_namespaces)

    assert valid in names
    assert settings.default_namespace in names
    assert legacy not in names
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert legacy in warnings[0].getMessage()


def test_bootstrap_migrates_only_valid_registered_namespaces(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend_core import database, migrations

    suffix = uuid.uuid4().hex[:8]
    valid = f'valid-{suffix}'
    legacy = f'legacy_{suffix}'
    migrated: list[list[str]] = []
    monkeypatch.setattr(migrations, 'migrate_runtime', lambda namespaces: migrated.append(list(namespaces)))

    with _registered_rows(valid, legacy):
        database._bootstrap_postgres()

    assert migrated[0] == [settings.default_namespace]
    assert valid in migrated[1]
    assert all(legacy not in batch for batch in migrated)


@pytest.mark.asyncio
async def test_namespace_work_waits_for_bounded_executor_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=0, thread_name_prefix='namespace-admission-test')
    started = Event()
    release = Event()

    def block() -> str:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError('namespace admission test was not released')
        return 'finished'

    monkeypatch.setattr(namespace_routes, '_NAMESPACE_EXECUTOR', executor)
    try:
        running = asyncio.create_task(namespace_routes._run_namespace(namespace_routes._NAMESPACE_EXECUTOR, block))
        assert await asyncio.to_thread(started.wait, 1)
        waiting = asyncio.create_task(namespace_routes._run_namespace(namespace_routes._NAMESPACE_EXECUTOR, lambda: 'queued'))
        cancelled = asyncio.create_task(namespace_routes._run_namespace(namespace_routes._NAMESPACE_EXECUTOR, lambda: 'cancelled'))
        await asyncio.sleep(0)
        assert not waiting.done()
        assert not cancelled.done()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        release.set()
        assert await running == 'finished'
        assert await waiting == 'queued'
        assert await namespace_routes._run_namespace(namespace_routes._NAMESPACE_EXECUTOR, lambda: 'after-settlement') == 'after-settlement'
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_create_namespace_endpoint_registers_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[str] = []
    provisioned: list[str] = []

    monkeypatch.setattr(namespace_routes, 'register_namespace', lambda session, name: registered.append(name))
    monkeypatch.setattr(namespace_routes, '_provision_namespace_bucket', provisioned.append)
    monkeypatch.setattr(namespace_routes, 'initialize_namespace_db', lambda name: None)
    monkeypatch.setattr(namespace_routes, 'namespace_provision_lock', lambda _name: nullcontext())

    from backend_core.application import app

    client = TestClient(app)
    response = client.post('/api/v1/namespaces', json={'name': 'test'})

    assert response.status_code == 200
    body = response.json()
    assert body['name'] == 'test'
    assert body['created_bucket'] is True
    assert body['storage']['bucket'] == 'test'
    assert body['storage']['uploads_root'].startswith('s3://test/')
    assert registered == ['test']
    assert provisioned == ['test']


def test_create_namespace_provisions_bucket_and_credentials_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []
    both_started = Barrier(2)

    def provision_bucket(name: str) -> None:
        started.append('bucket')
        both_started.wait(timeout=2)

    def run_settings_db(function, name: str, **kwargs) -> bool | None:
        if function is namespace_routes.runtime_namespace_exists:
            return False
        if function is namespace_routes.provision_namespace_engine_credentials:
            assert kwargs == {'namespace_lock_held': True}
            started.append('credentials')
            both_started.wait(timeout=2)
            return None
        assert function is namespace_routes.register_namespace
        started.append('register')
        return None

    monkeypatch.setattr(namespace_routes, '_provision_namespace_bucket', provision_bucket)
    monkeypatch.setattr(namespace_routes, 'run_settings_db', run_settings_db)
    monkeypatch.setattr(namespace_routes, 'initialize_namespace_db', lambda name: None)
    monkeypatch.setattr(namespace_routes, 'namespace_provision_lock', lambda _name: nullcontext())

    response = namespace_routes._create_namespace('parallel')

    assert response.name == 'parallel'
    assert set(started[:2]) == {'bucket', 'credentials'}
    assert started[-1] == 'register'


def test_create_namespace_reuses_published_namespace_without_reprovisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(namespace_routes, 'runtime_namespace_exists', lambda session, name: True)

    def run_settings_db(function, name: str) -> bool:
        del function
        calls.append(name)
        return True

    monkeypatch.setattr(namespace_routes, 'run_settings_db', run_settings_db)
    monkeypatch.setattr(namespace_routes, '_provision_namespace_bucket', lambda name: calls.append(f'bucket:{name}'))
    monkeypatch.setattr(namespace_routes, 'namespace_provision_lock', lambda _name: nullcontext())

    response = namespace_routes._create_namespace('published')

    assert response.created_bucket is False
    assert response.name == 'published'
    assert calls == ['published']


def test_namespace_provisioning_failure_waits_for_sibling_work_before_unlocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bucket_started = Event()
    migration_started = Event()
    release_bucket = Event()
    release_migration = Event()
    lock_released = Event()

    @contextmanager
    def provisioning_lock(_name: str):
        try:
            yield
        finally:
            lock_released.set()

    def provision_bucket(_name: str) -> None:
        bucket_started.set()
        assert release_bucket.wait(timeout=2)

    def initialize_database(_name: str) -> None:
        migration_started.set()
        assert release_migration.wait(timeout=2)

    def run_settings_db(function, name: str, **kwargs):
        if function is namespace_routes.runtime_namespace_exists:
            return False
        assert function is namespace_routes.provision_namespace_engine_credentials
        assert kwargs == {'namespace_lock_held': True}
        raise RuntimeError(f'credentials failed for {name}')

    monkeypatch.setattr(namespace_routes, 'namespace_provision_lock', provisioning_lock)
    monkeypatch.setattr(namespace_routes, 'run_settings_db', run_settings_db)
    monkeypatch.setattr(namespace_routes, '_provision_namespace_bucket', provision_bucket)
    monkeypatch.setattr(namespace_routes, 'initialize_namespace_db', initialize_database)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(namespace_routes._create_namespace, 'drain')
        assert bucket_started.wait(timeout=2)
        assert migration_started.wait(timeout=2)
        assert not future.done()
        assert not lock_released.is_set()
        release_bucket.set()
        release_migration.set()
        with pytest.raises(RuntimeError, match='credentials failed'):
            future.result(timeout=2)

    assert lock_released.is_set()


def test_provision_namespace_bucket_uses_explicit_data_plane_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    ensured: list[str] = []

    class FakeDataPlane:
        def ensure_object_store_bucket(self, name: str) -> None:
            ensured.append(name)

    monkeypatch.setattr(namespace_routes, 'client_from_settings', FakeDataPlane)

    namespace_routes._provision_namespace_bucket('analytics')

    assert ensured == ['analytics']


def test_namespace_storage_plan_endpoint_previews_exact_roots() -> None:
    from backend_core.application import app

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
