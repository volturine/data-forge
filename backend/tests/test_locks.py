from datetime import UTC, datetime, timedelta

from core.database import run_settings_db
from modules.auth.service import ensure_default_user
from modules.locks.models import ResourceLock


class TestLockRoutes:
    def test_acquire_heartbeat_release_status_flow(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)
        acquire = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-1'},
        )

        assert acquire.status_code == 200
        body = acquire.json()
        assert body['resource_type'] == 'analysis'
        assert body['resource_id'] == 'analysis-1'
        assert body['owner_id'] == owner.id
        assert body['is_expired'] is False

        status = client.get('/api/v1/locks/analysis/analysis-1')
        assert status.status_code == 200
        assert status.json()['lock_token'] == body['lock_token']

        heartbeat = client.post(
            '/api/v1/locks/analysis/analysis-1/heartbeat',
            json={'lock_token': body['lock_token']},
        )
        assert heartbeat.status_code == 200
        assert heartbeat.json()['lock_token'] == body['lock_token']

        release = client.request(
            'DELETE',
            '/api/v1/locks/analysis/analysis-1',
            json={'lock_token': body['lock_token']},
        )
        assert release.status_code == 200
        assert release.json() == {'released': True}

        assert test_db_session.get(ResourceLock, ('analysis', 'analysis-1')) is None

    def test_no_auth_reacquire_ignores_client_id(self, client, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)
        first = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-2'},
            headers={'X-Client-Id': 'owner-1'},
        )
        assert first.status_code == 200

        second = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-2'},
            headers={'X-Client-Id': 'owner-2'},
        )
        assert second.status_code == 200
        assert second.json()['owner_id'] == owner.id
        assert second.json()['lock_token'] != first.json()['lock_token']

    def test_expired_lock_replacement(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)
        now = datetime.now(UTC).replace(tzinfo=None)
        lock = ResourceLock(
            resource_type='analysis',
            resource_id='analysis-3',
            owner_id='other-owner',
            lock_token='expired-token',
            acquired_at=now - timedelta(minutes=2),
            expires_at=now - timedelta(seconds=1),
            last_heartbeat=now - timedelta(minutes=1),
        )
        test_db_session.add(lock)
        test_db_session.commit()

        acquire = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-3'},
            headers={'X-Client-Id': 'owner-1'},
        )
        assert acquire.status_code == 200
        body = acquire.json()
        assert body['owner_id'] == owner.id
        assert body['lock_token'] != 'expired-token'

    def test_no_auth_resolves_default_user_when_auth_disabled(self, client, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        response = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-4'},
            headers={'X-Client-Id': 'anon-client'},
        )

        assert response.status_code == 200
        assert response.json()['owner_id'] == owner.id

    def test_release_with_stale_token_is_idempotent(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        acquire = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-5'},
        )
        assert acquire.status_code == 200

        release = client.request(
            'DELETE',
            '/api/v1/locks/analysis/analysis-5',
            json={'lock_token': 'wrong-token'},
        )
        assert release.status_code == 200
        assert release.json() == {'released': False}

        lock = test_db_session.get(ResourceLock, ('analysis', 'analysis-5'))
        assert lock is not None


class TestLockWebsocket:
    def test_watch_can_acquire_and_release_over_websocket(self, client, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json({'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'analysis-ws-0'})
            assert websocket.receive_json() == {
                'type': 'status',
                'resource_type': 'analysis',
                'resource_id': 'analysis-ws-0',
                'lock': None,
            }

            websocket.send_json({'action': 'acquire'})
            acquired = websocket.receive_json()

            websocket.send_json({'action': 'release'})
            released = websocket.receive_json()

        assert acquired['type'] == 'status'
        assert acquired['resource_type'] == 'analysis'
        assert acquired['resource_id'] == 'analysis-ws-0'
        assert acquired['lock']['owner_id'] == owner.id
        assert acquired['lock']['is_expired'] is False
        assert released == {
            'type': 'status',
            'resource_type': 'analysis',
            'resource_id': 'analysis-ws-0',
            'lock': None,
        }

    def test_watch_receives_initial_and_release_updates(self, client, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        acquire = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-ws-1'},
        )
        token = acquire.json()['lock_token']

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            connected = websocket.receive_json()
            websocket.send_json({'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'analysis-ws-1'})
            initial = websocket.receive_json()

            release = client.request(
                'DELETE',
                '/api/v1/locks/analysis/analysis-ws-1',
                json={'lock_token': token},
            )
            updated = websocket.receive_json()

        assert connected == {'type': 'connected'}
        assert initial['type'] == 'status'
        assert initial['resource_type'] == 'analysis'
        assert initial['resource_id'] == 'analysis-ws-1'
        assert initial['lock']['owner_id'] == owner.id
        assert initial['lock']['lock_token'] == token
        assert release.status_code == 200
        assert updated == {
            'type': 'status',
            'resource_type': 'analysis',
            'resource_id': 'analysis-ws-1',
            'lock': None,
        }

    def test_disconnect_releases_socket_owned_lock(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json({'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'analysis-ws-disconnect'})
            assert websocket.receive_json() == {
                'type': 'status',
                'resource_type': 'analysis',
                'resource_id': 'analysis-ws-disconnect',
                'lock': None,
            }
            websocket.send_json({'action': 'acquire'})
            acquired = websocket.receive_json()
            assert acquired['lock'] is not None

        assert test_db_session.get(ResourceLock, ('analysis', 'analysis-ws-disconnect')) is None

    def test_watch_with_lock_token_heartbeats_default_owner_without_client_id(
        self,
        client,
        test_db_session,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        acquire = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-ws-2', 'ttl_seconds': 5},
        )
        body = acquire.json()

        lock = test_db_session.get(ResourceLock, ('analysis', 'analysis-ws-2'))
        assert lock is not None
        expires_before = lock.expires_at

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json(
                {
                    'action': 'watch',
                    'resource_type': 'analysis',
                    'resource_id': 'analysis-ws-2',
                    'lock_token': body['lock_token'],
                    'ttl_seconds': 30,
                },
            )
            status = websocket.receive_json()

            test_db_session.expire_all()
            refreshed = test_db_session.get(ResourceLock, ('analysis', 'analysis-ws-2'))
            assert refreshed is not None
            refreshed_expires_at = refreshed.expires_at
            refreshed_last_heartbeat = refreshed.last_heartbeat

            websocket.send_json({'action': 'ping', 'ttl_seconds': 45})
            pinged = websocket.receive_json()

            test_db_session.expire_all()
            updated = test_db_session.get(ResourceLock, ('analysis', 'analysis-ws-2'))

        assert updated is not None
        assert status['type'] == 'status'
        assert status['lock']['owner_id'] == owner.id
        assert status['lock']['lock_token'] == body['lock_token']
        assert refreshed_expires_at > expires_before
        assert refreshed_expires_at - refreshed_last_heartbeat == timedelta(seconds=30)
        assert pinged['type'] == 'status'
        assert pinged['lock']['owner_id'] == owner.id
        assert pinged['lock']['lock_token'] == body['lock_token']
        assert updated.expires_at > refreshed_expires_at
        assert updated.last_heartbeat >= refreshed_last_heartbeat
        assert updated.expires_at - updated.last_heartbeat == timedelta(seconds=45)

    def test_ping_without_watch_returns_error(self, client, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json({'action': 'ping'})
            error = websocket.receive_json()

        assert error == {
            'type': 'error',
            'error': 'watch must be called before ping',
            'status_code': 400,
        }

    def test_status_lookup_cleanup_notifies_watchers(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)

        now = datetime.now(UTC).replace(tzinfo=None)
        lock = ResourceLock(
            resource_type='analysis',
            resource_id='analysis-ws-3',
            owner_id='owner-1',
            lock_token='expired-token',
            acquired_at=now - timedelta(minutes=2),
            expires_at=now - timedelta(seconds=1),
            last_heartbeat=now - timedelta(minutes=1),
        )
        test_db_session.add(lock)
        test_db_session.commit()

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json({'action': 'watch', 'resource_type': 'analysis', 'resource_id': 'analysis-ws-3'})
            status = websocket.receive_json()

        assert status == {
            'type': 'status',
            'resource_type': 'analysis',
            'resource_id': 'analysis-ws-3',
            'lock': None,
        }

        lookup = client.get('/api/v1/locks/analysis/analysis-ws-3')
        assert lookup.status_code == 200
        assert lookup.json() is None
