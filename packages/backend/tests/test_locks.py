from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from backend_core.database import run_settings_db
from backend_core.persistence.locks.models import ResourceLock
from modules.auth.service import ensure_default_user


class TestLockRoutes:
    def test_acquire_heartbeat_release_status_flow(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
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
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
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
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
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

    def test_status_handles_aware_postgres_style_timestamps(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)
        now = datetime.now(UTC)
        lock = ResourceLock(
            resource_type='analysis',
            resource_id='analysis-aware',
            owner_id=owner.id,
            lock_token='aware-token',
            acquired_at=now,
            expires_at=now + timedelta(seconds=30),
            last_heartbeat=now,
        )
        test_db_session.add(lock)
        test_db_session.commit()

        status = client.get('/api/v1/locks/analysis/analysis-aware')

        assert status.status_code == 200
        body = status.json()
        assert body['lock_token'] == 'aware-token'
        assert body['is_expired'] is False

    def test_no_auth_resolves_default_user_when_auth_disabled(self, client, monkeypatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        response = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-4'},
            headers={'X-Client-Id': 'anon-client'},
        )

        assert response.status_code == 200
        assert response.json()['owner_id'] == owner.id

    def test_release_with_stale_token_is_idempotent(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
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

    def test_acquire_lock_recovers_from_conflicting_insert_during_commit(
        self,
        test_db_session,
        test_engine,
        monkeypatch,
    ) -> None:
        from sqlmodel import Session as SQLModelSession

        from modules.locks import service as locks_service

        now = datetime.now(UTC).replace(tzinfo=None)
        injected = False

        def racing_commit() -> None:
            nonlocal injected
            if not injected:
                injected = True
                # Another acquirer wins the insert race just before our commit.
                with SQLModelSession(test_engine) as other:
                    other.add(
                        ResourceLock(
                            resource_type='analysis',
                            resource_id='analysis-insert-race',
                            owner_id='owner-b',
                            lock_token='lock-b',
                            acquired_at=now,
                            expires_at=now + timedelta(seconds=30),
                            last_heartbeat=now,
                        )
                    )
                    other.commit()
            original_commit()

        original_commit = test_db_session.commit
        monkeypatch.setattr(test_db_session, 'commit', racing_commit)

        lock = locks_service.acquire_lock(test_db_session, 'analysis', 'analysis-insert-race', 'owner-b')

        assert lock.owner_id == 'owner-b'
        assert lock.lock_token != 'lock-b'
        stored = test_db_session.get(ResourceLock, ('analysis', 'analysis-insert-race'))
        assert stored is not None
        assert stored.owner_id == 'owner-b'
        assert stored.lock_token == lock.lock_token

    def _seed_lock(self, test_db_session, resource_id: str, *, owner: str, token: str, expires_at: datetime) -> ResourceLock:
        now = datetime.now(UTC).replace(tzinfo=None)
        lock = ResourceLock(
            resource_type='analysis',
            resource_id=resource_id,
            owner_id=owner,
            lock_token=token,
            acquired_at=now,
            expires_at=expires_at,
            last_heartbeat=now,
        )
        test_db_session.add(lock)
        test_db_session.commit()
        return lock

    def _patch_stale_read_with_takeover(self, monkeypatch, test_engine, resource_type: str, resource_id: str):
        """First service-level read returns the stale row while a competing owner
        concurrently takes over the committed row in between.
        """
        from modules.locks import service as locks_service

        original_get_lock = locks_service.get_lock
        raced = {'done': False}

        def racing_get_lock(session, rt, rid):
            lock = original_get_lock(session, rt, rid)
            if not raced['done'] and lock is not None and rt == resource_type and rid == resource_id:
                raced['done'] = True
                fresh_expires = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=60)
                with Session(test_engine) as other:
                    victim = other.get(ResourceLock, (rt, rid))
                    victim.owner_id = 'owner-thief'
                    victim.lock_token = 'thief-token'
                    victim.acquired_at = datetime.now(UTC).replace(tzinfo=None)
                    victim.last_heartbeat = victim.acquired_at
                    victim.expires_at = fresh_expires
                    other.add(victim)
                    other.commit()
            return lock

        monkeypatch.setattr(locks_service, 'get_lock', racing_get_lock)
        return raced

    def test_acquire_lock_cas_rejects_takeover_of_live_lock(self, test_db_session, test_engine, monkeypatch) -> None:
        from modules.locks import service as locks_service

        expired = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        self._seed_lock(test_db_session, 'analysis-cas-acquire', owner='owner-a', token='token-a', expires_at=expired)
        raced = self._patch_stale_read_with_takeover(monkeypatch, test_engine, 'analysis', 'analysis-cas-acquire')

        # Caller saw the stale expired row (owner-a), but by the time the
        # compare-and-set UPDATE runs, the committed row is live under another
        # owner: neither the owner nor expiry predicate matches.
        with pytest.raises(ValueError, match='locked by another owner'):
            locks_service.acquire_lock(test_db_session, 'analysis', 'analysis-cas-acquire', 'owner-c')

        assert raced['done'] is True
        test_db_session.expire_all()
        stored = test_db_session.get(ResourceLock, ('analysis', 'analysis-cas-acquire'))
        assert stored is not None
        assert stored.owner_id == 'owner-thief'
        assert stored.lock_token == 'thief-token'

    def test_heartbeat_lock_cas_rejects_superseded_token(self, test_db_session, test_engine) -> None:
        from modules.locks import service as locks_service

        active = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=60)
        seeded = self._seed_lock(test_db_session, 'analysis-cas-heartbeat', owner='owner-a', token='token-a', expires_at=active)

        # A competing acquirer rotates the committed token before we heartbeat.
        with Session(test_engine) as other:
            victim = other.get(ResourceLock, ('analysis', 'analysis-cas-heartbeat'))
            assert victim is not None
            victim.lock_token = 'rotated-token'
            other.add(victim)
            other.commit()
        test_db_session.expire_all()

        with pytest.raises(ValueError, match='owned by another owner'):
            locks_service.heartbeat_lock(test_db_session, 'analysis', 'analysis-cas-heartbeat', 'owner-a', 'token-a')

        stored = test_db_session.get(ResourceLock, ('analysis', 'analysis-cas-heartbeat'))
        assert stored is not None
        assert stored.lock_token == 'rotated-token'
        # The superseded heartbeat must not extend the lock expiry.
        assert ResourceLock.as_utc(stored.expires_at) == ResourceLock.as_utc(seeded.expires_at)

    def test_acquire_lock_cas_takes_over_only_expired_row(self, test_db_session) -> None:
        from modules.locks import service as locks_service

        expired = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        self._seed_lock(test_db_session, 'analysis-cas-expired', owner='owner-old', token='old-token', expires_at=expired)

        acquired = locks_service.acquire_lock(test_db_session, 'analysis', 'analysis-cas-expired', 'owner-new')

        assert acquired.owner_id == 'owner-new'
        assert acquired.lock_token != 'old-token'
        test_db_session.expire_all()
        stored = test_db_session.get(ResourceLock, ('analysis', 'analysis-cas-expired'))
        assert stored is not None
        assert stored.owner_id == 'owner-new'
        assert stored.is_expired() is False

    def test_same_owner_reacquire_rotates_token_via_cas(self, test_db_session) -> None:
        from modules.locks import service as locks_service

        active = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=60)
        self._seed_lock(test_db_session, 'analysis-cas-reacquire', owner='owner-same', token='first-token', expires_at=active)

        reacquired = locks_service.acquire_lock(test_db_session, 'analysis', 'analysis-cas-reacquire', 'owner-same')

        assert reacquired.owner_id == 'owner-same'
        assert reacquired.lock_token != 'first-token'
        assert reacquired.is_expired is False


class TestLockWebsocket:
    def test_watch_can_acquire_and_release_over_websocket(self, client, monkeypatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json(
                {
                    'action': 'watch',
                    'resource_type': 'analysis',
                    'resource_id': 'analysis-ws-0',
                }
            )
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

    def test_watch_acquire_succeeds_with_aware_existing_lock(self, client, test_db_session, monkeypatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)
        now = datetime.now(UTC)
        lock = ResourceLock(
            resource_type='analysis',
            resource_id='analysis-ws-aware',
            owner_id=owner.id,
            lock_token='aware-existing-token',
            acquired_at=now,
            expires_at=now + timedelta(seconds=30),
            last_heartbeat=now,
        )
        test_db_session.add(lock)
        test_db_session.commit()

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json(
                {
                    'action': 'watch',
                    'resource_type': 'analysis',
                    'resource_id': 'analysis-ws-aware',
                }
            )
            initial = websocket.receive_json()

        assert initial['type'] == 'status'
        assert initial['lock']['lock_token'] == 'aware-existing-token'

    def test_watch_receives_initial_and_release_updates(self, client, monkeypatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        acquire = client.post(
            '/api/v1/locks',
            json={'resource_type': 'analysis', 'resource_id': 'analysis-ws-1'},
        )
        token = acquire.json()['lock_token']

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            connected = websocket.receive_json()
            websocket.send_json(
                {
                    'action': 'watch',
                    'resource_type': 'analysis',
                    'resource_id': 'analysis-ws-1',
                }
            )
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
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            assert websocket.receive_json() == {'type': 'connected'}
            websocket.send_json(
                {
                    'action': 'watch',
                    'resource_type': 'analysis',
                    'resource_id': 'analysis-ws-disconnect',
                }
            )
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
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        owner = run_settings_db(ensure_default_user)

        acquire = client.post(
            '/api/v1/locks',
            json={
                'resource_type': 'analysis',
                'resource_id': 'analysis-ws-2',
                'ttl_seconds': 5,
            },
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
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)

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
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)

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
            websocket.send_json(
                {
                    'action': 'watch',
                    'resource_type': 'analysis',
                    'resource_id': 'analysis-ws-3',
                }
            )
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
