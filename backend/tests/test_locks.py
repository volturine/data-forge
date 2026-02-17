import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from modules.locks import service as lock_service
from modules.locks.models import Lock


def test_acquire_lock_creates_lock(test_db_session):
    resource_id = str(uuid.uuid4())
    response = lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')

    assert response.resource_id == resource_id
    assert response.client_id == 'client-a'
    lock = test_db_session.get(Lock, resource_id)
    assert lock is not None
    assert lock.client_id == 'client-a'


def test_acquire_lock_reuses_same_client(test_db_session):
    resource_id = str(uuid.uuid4())
    first = lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')
    second = lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-b')

    assert first.lock_token != second.lock_token
    lock = test_db_session.get(Lock, resource_id)
    assert lock is not None
    assert lock.client_signature == 'sig-b'


def test_acquire_lock_blocks_other_client(test_db_session):
    resource_id = str(uuid.uuid4())
    lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')

    try:
        lock_service.acquire_lock(test_db_session, resource_id, 'client-b', 'sig-b')
    except ValueError as exc:
        assert 'locked by another client' in str(exc)
    else:
        raise AssertionError('Expected ValueError for conflicting lock acquisition')


def test_acquire_lock_replaces_expired_lock(test_db_session):
    resource_id = str(uuid.uuid4())
    lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')
    lock = test_db_session.get(Lock, resource_id)
    assert lock is not None
    lock.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    test_db_session.add(lock)
    test_db_session.commit()

    response = lock_service.acquire_lock(test_db_session, resource_id, 'client-b', 'sig-b')
    assert response.client_id == 'client-b'


def test_heartbeat_extends_lock(test_db_session):
    resource_id = str(uuid.uuid4())
    response = lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')
    lock = test_db_session.get(Lock, resource_id)
    assert lock is not None
    original_expiry = lock.expires_at

    heartbeat = lock_service.heartbeat(test_db_session, resource_id, 'client-a', response.lock_token)
    assert heartbeat.client_id == 'client-a'
    refreshed = test_db_session.get(Lock, resource_id)
    assert refreshed is not None
    assert refreshed.expires_at >= original_expiry


def test_release_lock_removes_lock(test_db_session):
    resource_id = str(uuid.uuid4())
    response = lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')

    lock_service.release_lock(test_db_session, resource_id, 'client-a', response.lock_token)
    assert test_db_session.get(Lock, resource_id) is None


def test_get_lock_status_reports_locked(test_db_session):
    resource_id = str(uuid.uuid4())
    lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')

    status = lock_service.get_lock_status(test_db_session, resource_id, 'client-a')
    assert status.locked is True
    assert status.locked_by_me is True
    assert status.client_id == 'client-a'


def test_validate_lock_rejects_invalid_token(test_db_session):
    resource_id = str(uuid.uuid4())
    lock_service.acquire_lock(test_db_session, resource_id, 'client-a', 'sig-a')

    try:
        lock_service.validate_lock(test_db_session, resource_id, 'client-a', 'bad-token')
    except ValueError as exc:
        assert 'Invalid lock token' in str(exc)
    else:
        raise AssertionError('Expected ValueError for invalid lock token')


def test_locks_endpoints_smoke(client: TestClient):
    resource_id = str(uuid.uuid4())
    payload = {'client_id': 'client-a', 'client_signature': 'sig-a'}
    acquire = client.post(f'/api/v1/locks/{resource_id}/acquire', json=payload)
    assert acquire.status_code == 200
    lock_token = acquire.json()['lock_token']

    heartbeat = client.post(
        f'/api/v1/locks/{resource_id}/heartbeat',
        json={'client_id': 'client-a', 'lock_token': lock_token},
    )
    assert heartbeat.status_code == 200

    status = client.get(f'/api/v1/locks/{resource_id}', params={'client_id': 'client-a'})
    assert status.status_code == 200
    assert status.json()['locked'] is True

    release = client.post(
        f'/api/v1/locks/{resource_id}/release',
        json={'client_id': 'client-a', 'lock_token': lock_token},
    )
    assert release.status_code == 200
