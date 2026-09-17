import json
import os

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from backend_core.namespace_credentials_service import (
    NamespaceCredentialError,
    provision_namespace_engine_credentials,
    resolve_namespace_engine_credentials,
)
from backend_core.persistence.namespaces.models import NamespaceEngineCredential
from backend_core.secrets import is_encrypted_secret


class FakeAdmin:
    def __init__(self):
        self.calls: list[tuple] = []

    async def user_add(self, access_key: str, secret_key: str) -> str:
        self.calls.append(('user_add', access_key, secret_key))
        return ''

    async def policy_add(self, policy_name: str, policy_path: str) -> str:
        self.calls.append(('policy_add', policy_name))
        return ''

    async def policy_set(self, policy_name: str, *, user: str, group: str | None = None) -> str:
        self.calls.append(('policy_set', policy_name, user))
        return ''


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine, tables=[NamespaceEngineCredential.__table__])
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def fake_admin(monkeypatch) -> FakeAdmin:
    admin = FakeAdmin()
    monkeypatch.setattr('backend_core.namespace_credentials_service._admin_client', lambda _session: admin)
    return admin


def test_provision_creates_reader_and_builder_identities(session, fake_admin):
    provision_namespace_engine_credentials(session, 'tenant-a')

    roles = {row.role for row in session.exec(select(NamespaceEngineCredential)).all()}
    assert roles == {'reader', 'builder'}

    user_adds = [call for call in fake_admin.calls if call[0] == 'user_add']
    assert {call[1] for call in user_adds} == {row.access_key for row in session.exec(select(NamespaceEngineCredential)).all()}
    assert all(secret for _, _, secret in user_adds)
    assert {call[1] for call in fake_admin.calls if call[0] == 'policy_add'} == {
        'namespace-tenant-a-reader',
        'namespace-tenant-a-builder',
    }
    assert {(call[1], call[2]) for call in fake_admin.calls if call[0] == 'policy_set'} == {
        ('namespace-tenant-a-reader', user_adds[0][1]),
        ('namespace-tenant-a-builder', user_adds[1][1]),
    }


def test_provision_stores_secrets_encrypted(session, fake_admin):
    provision_namespace_engine_credentials(session, 'tenant-a')

    rows = session.exec(select(NamespaceEngineCredential)).all()
    assert len(rows) == 2
    assert all(is_encrypted_secret(row.secret_key_encrypted) for row in rows)


def test_provision_is_idempotent(session, fake_admin):
    provision_namespace_engine_credentials(session, 'tenant-a')
    calls_after_first = list(fake_admin.calls)

    provision_namespace_engine_credentials(session, 'tenant-a')

    assert fake_admin.calls == calls_after_first


def test_resolve_returns_decrypted_secret(session, fake_admin):
    provision_namespace_engine_credentials(session, 'tenant-a')

    row = session.exec(select(NamespaceEngineCredential).where(NamespaceEngineCredential.role == 'reader')).one()
    access_key, secret_key = resolve_namespace_engine_credentials(session, 'tenant-a', 'reader')

    assert access_key == row.access_key
    assert secret_key not in (None, '', row.secret_key_encrypted)


def test_resolve_missing_namespace_raises(session, fake_admin):
    with pytest.raises(NamespaceCredentialError, match='No reader credentials provisioned'):
        resolve_namespace_engine_credentials(session, 'missing-ns', 'reader')


def test_duplicate_role_for_a_namespace_is_rejected_by_the_database(session, fake_admin):
    """Concurrent provisioning across API processes must not create two identities."""
    provision_namespace_engine_credentials(session, 'tenant-a')

    session.add(
        NamespaceEngineCredential(
            id='duplicate',
            namespace='tenant-a',
            role='reader',
            access_key='dfg-tenant-a-reader-duplicate',
            secret_key_encrypted='secret',
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_policy_failures_are_reported_not_swallowed(session, monkeypatch):
    class FailingAdmin(FakeAdmin):
        async def policy_add(self, policy_name: str, policy_path: str) -> str:
            raise RuntimeError('admin API rejected the policy')

    monkeypatch.setattr('backend_core.namespace_credentials_service._admin_client', lambda _session: FailingAdmin())

    with pytest.raises(NamespaceCredentialError, match='Failed to provision engine credentials'):
        provision_namespace_engine_credentials(session, 'tenant-a')

    assert session.exec(select(NamespaceEngineCredential)).all() == []


def test_policy_documents_are_written_to_unique_paths(session, monkeypatch):
    seen_paths: list[str] = []

    class PathRecordingAdmin(FakeAdmin):
        async def policy_add(self, policy_name: str, policy_path: str) -> str:
            seen_paths.append(policy_path)
            with open(policy_path, encoding='utf-8') as policy_file:
                assert json.load(policy_file)['Statement']
            return ''

    monkeypatch.setattr('backend_core.namespace_credentials_service._admin_client', lambda _session: PathRecordingAdmin())

    provision_namespace_engine_credentials(session, 'tenant-a')

    assert len(set(seen_paths)) == len(seen_paths) == 2
    assert not any(os.path.exists(path) for path in seen_paths)
