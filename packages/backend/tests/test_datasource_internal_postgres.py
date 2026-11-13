from datetime import UTC, datetime
from typing import Any

import pytest

from backend_core import datasource_delete_service
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.persistence.datasource.models import DataSource
from modules.auth.dependencies import get_current_user
from modules.auth.models import User, UserStatus
from modules.auth.service import get_default_user_id
from modules.datasource import service


@pytest.fixture
def admin_client(client):
    from backend_core.application import app

    now = datetime.now(UTC)
    admin = User(
        id=get_default_user_id(),
        email='admin@example.com',
        display_name='Admin',
        status=UserStatus.ACTIVE,
        email_verified=True,
        has_password=True,
        preferences={},
        created_at=now,
        updated_at=now,
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    return client


def _add_internal_database_datasource(session, *, datasource_id: str = 'internal-analyses') -> DataSource:
    datasource = DataSource(
        id=datasource_id,
        name='internal.default.analyses',
        source_type=DataSourceType.DATABASE.value,
        config={
            'connection_string': service.InternalPostgresOnboarding.connection_string(),
            'query': service.InternalPostgresOnboarding.query_for('default', 'analyses'),
            'branch': 'master',
        },
        created_by='import',
        created_at=datetime.now(UTC),
    )
    session.add(datasource)
    session.commit()
    return datasource


class _AvailableRuntimeProbe:
    @staticmethod
    def available(*, kind) -> bool:
        del kind
        return True


def _create_database_datasource_stub(
    session,
    *,
    name: str,
    description: str | None,
    connection_string: str,
    query: str,
    branch: str,
    owner_id: str | None = None,
    **kwargs: Any,
):
    del kwargs
    datasource = DataSource(
        id='internal-ds-1',
        name=name,
        description=description,
        source_type=DataSourceType.DATABASE.value,
        config={'connection_string': connection_string, 'query': query, 'branch': branch},
        owner_id=owner_id,
        created_by='import',
        created_at=datetime.now(UTC),
    )
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    return datasource


def test_list_internal_postgres_tables_reports_application_tables(admin_client, test_db_session) -> None:
    del test_db_session

    response = admin_client.get('/api/v1/datasource/internal-postgres/tables')

    assert response.status_code == 200
    rows = response.json()
    names = {(row['schema_name'], row['table_name']) for row in rows}
    assert ('default', 'analyses') in names
    row = next(row for row in rows if row['schema_name'] == 'default' and row['table_name'] == 'analyses')
    assert row['is_onboarded'] is False


def test_list_internal_postgres_tables_materializes_onboarding_metadata_once(test_db_session, monkeypatch) -> None:
    test_db_session.add(
        DataSource(
            id='internal-query-analyses',
            name='legacy-analysis-source',
            source_type='database',
            config={
                'connection_string': service.InternalPostgresOnboarding.connection_string(),
                'query': 'SELECT * FROM "default"."analyses"',
            },
            created_by='import',
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    onboarding = service.InternalPostgresOnboarding(test_db_session)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError('list_tables must not scan datasources per table')

    monkeypatch.setattr(onboarding, 'matching_datasources', fail_if_called)

    rows = onboarding.list_tables()

    row = next(item for item in rows if item.schema_name == 'default' and item.table_name == 'analyses')
    assert row.is_onboarded is True


def test_internal_postgres_display_names_strip_internal_namespace_storage_prefix(test_db_session) -> None:
    namespace_public = DataSource(
        id='namespace-public-ds',
        name='internal.public.users',
        source_type='iceberg',
        config={
            'metadata_path': '/tmp/namespace-public',
            'source': {
                'source_type': 'database',
                'connection_string': service.InternalPostgresOnboarding.connection_string(),
                'query': 'SELECT * FROM "df$tenant$public"."users"',
            },
        },
        created_by='import',
        created_at=datetime.now(UTC),
    )
    default_namespace = DataSource(
        id='default-namespace-ds',
        name='internal.default.users',
        source_type='iceberg',
        config={
            'metadata_path': '/tmp/default-namespace',
            'source': {
                'source_type': 'database',
                'connection_string': service.InternalPostgresOnboarding.connection_string(),
                'query': 'SELECT * FROM "default"."users"',
            },
        },
        created_by='import',
        created_at=datetime.now(UTC),
    )
    test_db_session.add(namespace_public)
    test_db_session.add(default_namespace)
    test_db_session.commit()

    listed = {item.id: item.name for item in service.list_datasources(test_db_session, include_hidden=True)}

    assert listed[namespace_public.id] == 'internal.public.users'
    assert listed[default_namespace.id] == 'internal.default.users'
    assert service.get_datasource(test_db_session, namespace_public.id).name == 'internal.public.users'
    assert service.get_datasource(test_db_session, default_namespace.id).name == 'internal.default.users'


def test_toggle_internal_postgres_table_creates_database_datasource_once_and_deletes_on_disable(
    admin_client,
    monkeypatch,
    test_db_session,
) -> None:
    calls = 0

    def _stub(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _create_database_datasource_stub(*args, **kwargs)

    monkeypatch.setattr(service, 'create_database_datasource_record', _stub)

    enabled = admin_client.post(
        '/api/v1/datasource/internal-postgres/toggle',
        json={'schema_name': 'default', 'table_name': 'analyses', 'enabled': True},
    )
    assert enabled.status_code == 200
    assert enabled.json() == {
        'schema_name': 'default',
        'table_name': 'analyses',
        'is_onboarded': True,
    }
    assert calls == 1

    calls_before_enabled_again = calls
    enabled_again = admin_client.post(
        '/api/v1/datasource/internal-postgres/toggle',
        json={'schema_name': 'default', 'table_name': 'analyses', 'enabled': True},
    )
    assert enabled_again.status_code == 200
    assert enabled_again.json()['is_onboarded'] is True
    assert calls == calls_before_enabled_again

    listed = admin_client.get('/api/v1/datasource/internal-postgres/tables')
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item['schema_name'] == 'default' and item['table_name'] == 'analyses')
    assert row['is_onboarded'] is True
    assert test_db_session.get(DataSource, 'internal-ds-1') is not None

    disabled = admin_client.post(
        '/api/v1/datasource/internal-postgres/toggle',
        json={'schema_name': 'default', 'table_name': 'analyses', 'enabled': False},
    )
    assert disabled.status_code == 200
    assert disabled.json() == {
        'schema_name': 'default',
        'table_name': 'analyses',
        'is_onboarded': False,
    }
    pending_delete = test_db_session.get(DataSource, 'internal-ds-1')
    assert pending_delete is not None
    assert pending_delete.is_pending_delete is True
    assert pending_delete.is_hidden is True
    assert datasource_delete_service.finalize_delete(test_db_session, 'internal-ds-1') is True
    assert test_db_session.get(DataSource, 'internal-ds-1') is None

    relisted = admin_client.get('/api/v1/datasource/internal-postgres/tables')
    assert relisted.status_code == 200
    row = next(item for item in relisted.json() if item['schema_name'] == 'default' and item['table_name'] == 'analyses')
    assert row['is_onboarded'] is False


def test_internal_postgres_onboarding_ignores_unrelated_datasource_with_internal_name(admin_client, test_db_session) -> None:
    # A user datasource that merely carries an internal-looking name is not an
    # onboarded table: listing must not report it, and disabling the table
    # must not delete it.
    test_db_session.add(
        DataSource(
            id='user-named-like-internal',
            name='internal.default.analyses',
            source_type='iceberg',
            config={'metadata_path': '/tmp/user-upload'},
            created_by='import',
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    listed = admin_client.get('/api/v1/datasource/internal-postgres/tables')
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item['schema_name'] == 'default' and item['table_name'] == 'analyses')
    assert row['is_onboarded'] is False

    disabled = admin_client.post(
        '/api/v1/datasource/internal-postgres/toggle',
        json={'schema_name': 'default', 'table_name': 'analyses', 'enabled': False},
    )
    assert disabled.status_code == 200
    test_db_session.expire_all()
    untouched = test_db_session.get(DataSource, 'user-named-like-internal')
    assert untouched is not None
    assert untouched.is_pending_delete is False


def test_list_internal_postgres_tables_recognizes_escaped_identifiers(test_db_session) -> None:
    onboarding = service.InternalPostgresOnboarding(test_db_session)
    test_db_session.add(
        DataSource(
            id='quoted-table-ds',
            name='renamed',
            source_type='database',
            config={
                'connection_string': service.InternalPostgresOnboarding.connection_string(),
                'query': onboarding.query_for('default', 'a"b'),
            },
            created_by='import',
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    assert onboarding.query_for('default', 'a"b') in onboarding._onboarded_table_queries()


def test_internal_postgres_endpoints_require_admin(client, monkeypatch) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError('non-admin requests must not reach internal Postgres onboarding')

    monkeypatch.setattr(service, 'list_internal_postgres_tables', fail_if_called)
    monkeypatch.setattr(service, 'toggle_internal_postgres_table', fail_if_called)

    listed = client.get('/api/v1/datasource/internal-postgres/tables')
    toggled = client.post(
        '/api/v1/datasource/internal-postgres/toggle',
        json={'schema_name': 'default', 'table_name': 'users', 'enabled': True},
    )

    assert listed.status_code == 403
    assert listed.json()['detail'] == 'Admin access required'
    assert toggled.status_code == 403
    assert toggled.json()['detail'] == 'Admin access required'


def test_non_admin_cannot_repoint_internal_datasource_query(client, test_db_session) -> None:
    datasource = _add_internal_database_datasource(test_db_session)
    original_query = datasource.config['query']

    response = client.put(f'/api/v1/datasource/{datasource.id}', json={'config': {'query': 'SELECT * FROM "default"."users"'}})

    assert response.status_code == 403
    assert response.json()['detail'] == 'Admin access required'
    test_db_session.expire_all()
    assert test_db_session.get(DataSource, datasource.id).config['query'] == original_query


def test_non_admin_can_rename_internal_datasource(client, test_db_session) -> None:
    datasource = _add_internal_database_datasource(test_db_session)

    response = client.put(f'/api/v1/datasource/{datasource.id}', json={'name': 'Renamed internal', 'config': dict(datasource.config)})

    assert response.status_code == 200
    assert response.json()['name'] == 'Renamed internal'


def test_non_admin_cannot_point_ingest_source_at_internal_database(client, test_db_session) -> None:
    datasource = DataSource(
        id='external-iceberg',
        name='external',
        source_type=DataSourceType.ICEBERG.value,
        config={
            'metadata_path': '/tmp/external-iceberg',
            'source': {'source_type': 'database', 'connection_string': 'postgresql://external/db', 'query': 'SELECT 1'},
        },
        created_by='import',
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    response = client.put(
        f'/api/v1/datasource/{datasource.id}',
        json={
            'config': {
                'source': {
                    'source_type': 'database',
                    'connection_string': service.InternalPostgresOnboarding.connection_string(),
                    'query': 'SELECT * FROM "default"."users"',
                },
            },
        },
    )

    assert response.status_code == 403


def test_admin_can_edit_internal_datasource_query(admin_client, test_db_session) -> None:
    datasource = _add_internal_database_datasource(test_db_session)
    next_query = service.InternalPostgresOnboarding.query_for('default', 'datasources')

    response = admin_client.put(f'/api/v1/datasource/{datasource.id}', json={'config': {'query': next_query}})

    assert response.status_code == 200
    test_db_session.expire_all()
    assert test_db_session.get(DataSource, datasource.id).config['query'] == next_query
