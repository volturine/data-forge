"""Tests for the settings module — GET/PUT settings, test SMTP/Telegram."""

import asyncio
import gc
import threading
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, cast
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

from backend_core.secrets import MASKED_SECRET, decrypt_secret, encrypt_secret
from tests.http_client import TestClient


@pytest.fixture
async def smtp_loop_errors() -> AsyncIterator[list[dict[str, object]]]:
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    errors: list[dict[str, object]] = []

    def _record_error(_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        errors.append(context)

    loop.set_exception_handler(_record_error)
    try:
        yield errors
        # Drain result propagation after the tests join their SMTP worker threads.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gc.collect()
        assert errors == []
    finally:
        loop.set_exception_handler(previous_handler)


async def _smtp_settings_lookup(_operation: object) -> dict[str, object]:
    return {'host': 'smtp.test.com', 'port': 587, 'user': 'user@test.com', 'password': 'pw'}


def _use_smtp_test_executor(monkeypatch, executor: object, deadline: float = 12.0) -> None:
    from modules.settings import routes

    monkeypatch.setattr(routes, 'run_api_blocking', _smtp_settings_lookup)
    monkeypatch.setattr(routes, '_SMTP_TEST_EXECUTOR', executor)
    monkeypatch.setattr(routes, '_SMTP_TEST_CAPACITY', threading.BoundedSemaphore(1))
    monkeypatch.setattr(routes, '_SMTP_TEST_DEADLINE', deadline)


def _make_postgres_engine(prefix: str = 'settings'):
    from sqlmodel import SQLModel

    url = __import__('os').environ['TEST_POSTGRES_URL']
    schema = f'{prefix}_{uuid.uuid4().hex}'
    engine = create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={'options': f'-c search_path={schema},public'},
    )

    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        SQLModel.metadata.create_all(connection)
    return engine, schema


class TestGetSettings:
    """GET /v1/settings — returns singleton settings row."""

    def test_returns_defaults_when_no_row(self, client: TestClient) -> None:
        resp = client.get('/api/v1/settings')
        assert resp.status_code == 200
        data = resp.json()
        assert 'smtp_host' in data
        assert 'smtp_port' in data
        assert 'telegram_bot_token' in data
        assert 'public_idb_debug' in data

    def test_returns_saved_values(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        # First save some values
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'mail.example.com',
                'smtp_port': 465,
                'smtp_user': 'user@example.com',
                'smtp_password': 'secret',
                'telegram_bot_token': 'bot123:abc',
                'telegram_bot_enabled': True,
                'public_idb_debug': True,
            },
        )
        resp = client.get('/api/v1/settings')
        assert resp.status_code == 200
        data = resp.json()
        assert data['smtp_host'] == 'mail.example.com'
        assert data['smtp_port'] == 465
        assert data['smtp_user'] == 'user@example.com'
        assert data['smtp_password'] == MASKED_SECRET
        assert data['telegram_bot_token'] == MASKED_SECRET
        assert data['public_idb_debug'] is True


class TestConfigRoute:
    def test_config_endpoint_reads_current_persisted_settings(self, client: TestClient, monkeypatch) -> None:
        from backend_core.database import run_settings_db
        from backend_core.settings_schemas import SettingsUpdate
        from backend_core.settings_store import update_settings

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        initial = client.get('/api/v1/config')
        assert initial.status_code == 200
        assert initial.json()['public_idb_debug'] is False

        run_settings_db(
            update_settings,
            SettingsUpdate(
                smtp_host='mail.example.com',
                smtp_user='user@example.com',
                telegram_bot_enabled=True,
                telegram_bot_token='bot123:abc',
                public_idb_debug=True,
            ),
        )

        resp = client.get('/api/v1/config')
        assert resp.status_code == 200
        data = resp.json()
        assert data['public_idb_debug'] is True
        assert data['smtp_enabled'] is True
        assert data['telegram_enabled'] is True
        assert 'default_namespace' in data
        assert 'auth_required' in data


class TestNamespaceDatabaseConcurrency:
    def test_pool_snapshot_identifies_checked_out_connection_owner(self, monkeypatch, tmp_path) -> None:
        from backend_core import database

        engine = database._create_engine(f'sqlite:///{tmp_path / "pool.db"}', pool_name='tenant')
        monkeypatch.setattr(database, 'tenant_engine', engine)
        monkeypatch.setattr(database, 'settings_engine', None)
        monkeypatch.setattr(database, '_engine_override', None)
        monkeypatch.setattr(database, '_settings_engine_override', None)
        try:
            with engine.connect():
                snapshot = database.database_pool_snapshot()
                assert snapshot['tenant_checkedout'] == 1
                oldest_ms = snapshot['tenant_checkout_oldest_ms']
                owners = snapshot['tenant_checkout_owners']
                assert isinstance(oldest_ms, int) and oldest_ms >= 0
                assert isinstance(owners, str)
                assert 'MainThread' in owners
                assert 'test_settings.py' in owners
                assert 'connection.py' not in owners

            snapshot = database.database_pool_snapshot()
            assert 'tenant_checkout_owners' not in snapshot
        finally:
            engine.dispose()

    def test_run_db_is_safe_across_concurrent_threads(self) -> None:
        from backend_core.database import run_db
        from backend_core.namespace import reset_namespace, set_namespace_context

        namespace = f'concurrency_{uuid.uuid4().hex}'

        def call() -> int:
            token = set_namespace_context(namespace)
            try:
                return run_db(lambda session: 1)
            finally:
                reset_namespace(token)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: call(), range(8)))

        assert results == [1] * 8


class TestUpdateSettings:
    """PUT /v1/settings — upserts the singleton row."""

    def test_ai_provider_update_does_not_reconfigure_telegram_runtime(self, client: TestClient, monkeypatch) -> None:
        from backend_core import settings_store

        def unexpected_telegram_lookup():
            raise AssertionError('AI-only settings updates must not load Telegram settings')

        monkeypatch.setattr(settings_store, 'get_resolved_telegram_settings', unexpected_telegram_lookup)

        response = client.put('/api/v1/settings', json={'openrouter_default_model': 'e2e-model'})

        assert response.status_code == 200
        assert response.json()['openrouter_default_model'] == 'e2e-model'

    def test_update_smtp(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        resp = client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_user': 'test@test.com',
                'smtp_password': 'pw',
                'telegram_bot_token': '',
                'telegram_bot_enabled': True,
                'public_idb_debug': False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['smtp_host'] == 'smtp.test.com'
        assert data['smtp_user'] == 'test@test.com'
        assert data['smtp_password'] == MASKED_SECRET

    def test_update_telegram(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        resp = client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot999:xyz',
                'telegram_bot_enabled': False,
                'public_idb_debug': False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()['telegram_bot_token'] == MASKED_SECRET

    def test_update_idb_debug(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        resp = client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'telegram_bot_enabled': False,
                'public_idb_debug': True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()['public_idb_debug'] is True

    def test_preserves_masked_secrets_on_partial_update(self, client: TestClient, monkeypatch) -> None:
        from backend_core.settings_store import (
            get_resolved_openrouter_key,
            get_resolved_smtp,
            get_resolved_telegram_token,
        )

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_user': 'test@test.com',
                'smtp_password': 'pw',
                'telegram_bot_token': 'bot999:xyz',
                'telegram_bot_enabled': True,
                'openrouter_api_key': 'sk-live',
                'public_idb_debug': False,
            },
        )

        resp = client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'smtp.changed.com',
                'smtp_password': MASKED_SECRET,
                'telegram_bot_token': '********',
                'openrouter_api_key': MASKED_SECRET,
            },
        )
        assert resp.status_code == 200
        assert get_resolved_smtp()['password'] == 'pw'
        assert get_resolved_telegram_token() == 'bot999:xyz'
        assert get_resolved_openrouter_key() == 'sk-live'

    def test_get_populates_empty_openrouter_key_then_keeps_a_profile_key(self, client: TestClient, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.database import run_settings_db
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import get_resolved_openrouter_key

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'sk-or-env', raising=False)
        cleared = client.put('/api/v1/settings', json={'openrouter_api_key': ''})
        assert cleared.status_code == 200
        assert cleared.json()['openrouter_api_key'] == ''

        populated = client.get('/api/v1/settings')
        assert populated.status_code == 200
        assert populated.json()['openrouter_api_key'] == MASKED_SECRET
        assert get_resolved_openrouter_key() == 'sk-or-env'

        def _stored_key(session: Session) -> str:
            row = session.get(AppSettings, 1)
            assert row is not None
            assert str(row.openrouter_api_key).startswith('enc:v1:')
            return decrypt_secret(row.openrouter_api_key)

        assert run_settings_db(_stored_key) == 'sk-or-env'

        saved = client.put('/api/v1/settings', json={'openrouter_api_key': 'sk-or-user'})
        assert saved.status_code == 200
        assert saved.json()['openrouter_api_key'] == MASKED_SECRET
        reread = client.get('/api/v1/settings')
        assert reread.status_code == 200
        assert reread.json()['openrouter_api_key'] == MASKED_SECRET
        assert get_resolved_openrouter_key() == 'sk-or-user'
        assert run_settings_db(_stored_key) == 'sk-or-user'

    def test_encrypts_settings_secrets_at_rest(self, client: TestClient, monkeypatch) -> None:
        from backend_core.database import run_settings_db
        from backend_core.persistence.settings.models import AppSettings

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_user': 'test@test.com',
                'smtp_password': 'pw',
                'telegram_bot_token': 'bot999:xyz',
                'telegram_bot_enabled': True,
                'openrouter_api_key': 'sk-live',
                'public_idb_debug': False,
            },
        )

        def _read(session: Session) -> AppSettings | None:
            return session.get(AppSettings, 1)

        row = run_settings_db(_read)
        assert row is not None
        assert row.smtp_password != 'pw'
        assert row.telegram_bot_token != 'bot999:xyz'
        assert row.openrouter_api_key != 'sk-live'
        assert row.smtp_password.startswith('enc:v1:')
        assert row.telegram_bot_token.startswith('enc:v1:')
        assert row.openrouter_api_key.startswith('enc:v1:')

    def test_get_rejects_unsupported_secret_storage_format(self, client: TestClient, monkeypatch) -> None:
        from backend_core.database import run_settings_db
        from backend_core.persistence.settings.models import AppSettings

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')

        def _seed(session: Session) -> None:
            row = session.get(AppSettings, 1)
            assert row is not None
            row.smtp_password = 'enc:07001001000d'
            session.commit()

        run_settings_db(_seed)

        resp = client.get('/api/v1/settings')
        assert resp.status_code == 500
        assert resp.json()['detail'] == 'Stored secret is not encrypted with the supported format'


class TestTestSmtp:
    """POST /v1/settings/test-smtp — test email sending."""

    def test_not_configured(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        # Ensure SMTP is cleared
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'telegram_bot_enabled': False,
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/test-smtp', json={'to': 'test@test.com'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'not configured' in data['message'].lower()

    @patch('modules.settings.routes.send_smtp_message')
    def test_success(self, mock_send_smtp: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')

        # Configure SMTP first
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_user': 'user@test.com',
                'smtp_password': 'pw',
                'telegram_bot_token': '',
                'telegram_bot_enabled': False,
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-smtp', json={'to': 'recipient@test.com'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        mock_send_smtp.assert_called_once()

    @patch('modules.settings.routes.send_smtp_message')
    def test_failure(self, mock_send_smtp: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        mock_send_smtp.side_effect = ConnectionRefusedError('Connection refused')

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'bad-host',
                'smtp_port': 587,
                'smtp_user': 'user@test.com',
                'smtp_password': '',
                'telegram_bot_token': '',
                'telegram_bot_enabled': False,
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-smtp', json={'to': 'test@test.com'})
        assert resp.status_code == 502
        data = resp.json()
        assert 'refused' in data['detail'].lower()

    @pytest.mark.asyncio
    async def test_slow_provider_does_not_block_event_loop(self, monkeypatch) -> None:
        from backend_core.settings_schemas import TestSmtpRequest
        from modules.settings.routes import test_smtp

        started = threading.Event()
        release = threading.Event()

        def _slow_send(*_args, **_kwargs) -> None:
            started.set()
            assert release.wait(timeout=2)

        monkeypatch.setattr('modules.settings.routes.send_smtp_message', _slow_send)
        with ThreadPoolExecutor(max_workers=1) as executor:
            _use_smtp_test_executor(monkeypatch, executor)
            request = asyncio.create_task(test_smtp(TestSmtpRequest(to='recipient@test.com')))
            assert await asyncio.to_thread(started.wait, 1)
            release.set()
            result = await request

        assert result.success is True

    @pytest.mark.asyncio
    async def test_busy_while_provider_call_is_running(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from backend_core.settings_schemas import TestSmtpRequest
        from modules.settings.routes import test_smtp

        started = threading.Event()
        release = threading.Event()
        calls = 0

        def _slow_send(*_args, **_kwargs) -> None:
            nonlocal calls
            calls += 1
            started.set()
            assert release.wait(timeout=2)

        monkeypatch.setattr('modules.settings.routes.send_smtp_message', _slow_send)
        with ThreadPoolExecutor(max_workers=1) as executor:
            _use_smtp_test_executor(monkeypatch, executor, deadline=1)
            request = TestSmtpRequest(to='recipient@test.com')
            first = asyncio.create_task(test_smtp(request))
            assert await asyncio.to_thread(started.wait, 1)
            with pytest.raises(HTTPException, match='busy') as exc_info:
                await test_smtp(request)
            assert exc_info.value.status_code == 429

            release.set()
            await first

        assert calls == 1

    @pytest.mark.asyncio
    async def test_cancellation_before_submission_does_not_consume_capacity(self, monkeypatch, smtp_loop_errors) -> None:
        from backend_core.settings_schemas import TestSmtpRequest
        from modules.settings import routes

        waiting = asyncio.Event()
        continue_lookup = asyncio.Event()
        sent = threading.Event()

        async def _blocked_lookup(_operation):
            waiting.set()
            await continue_lookup.wait()
            return {'host': 'smtp.test.com', 'port': 587, 'user': 'user@test.com', 'password': 'pw'}

        with ThreadPoolExecutor(max_workers=1) as executor:
            _use_smtp_test_executor(monkeypatch, executor)
            monkeypatch.setattr(routes, 'run_api_blocking', _blocked_lookup)
            monkeypatch.setattr(routes, 'send_smtp_message', lambda *_args, **_kwargs: sent.set())
            request = asyncio.create_task(routes.test_smtp(TestSmtpRequest(to='recipient@test.com')))
            await waiting.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request

            continue_lookup.set()
            result = await routes.test_smtp(TestSmtpRequest(to='recipient@test.com'))

        assert result.success is True
        assert sent.is_set()

    @pytest.mark.asyncio
    async def test_deadline_cancels_executor_work_that_has_not_started(self, monkeypatch, smtp_loop_errors) -> None:
        from fastapi import HTTPException

        from backend_core.settings_schemas import TestSmtpRequest
        from modules.settings import routes

        class DelayedExecutor:
            def __init__(self) -> None:
                self.future: Future[None] = Future()

            def submit(self, *_args: object, **_kwargs: object) -> Future[None]:
                return self.future

        executor = DelayedExecutor()
        sent = threading.Event()
        monkeypatch.setattr(routes, 'send_smtp_message', lambda *_args, **_kwargs: sent.set())
        monkeypatch.setattr(routes, 'run_api_blocking', _smtp_settings_lookup)
        monkeypatch.setattr(routes, '_SMTP_TEST_EXECUTOR', executor)
        monkeypatch.setattr(routes, '_SMTP_TEST_CAPACITY', threading.BoundedSemaphore(1))
        monkeypatch.setattr(routes, '_SMTP_TEST_DEADLINE', 0.01)

        with pytest.raises(HTTPException) as exc_info:
            await routes.test_smtp(TestSmtpRequest(to='recipient@test.com'))

        assert exc_info.value.status_code == 504
        assert 'not sent' in exc_info.value.detail
        assert executor.future.cancelled()
        assert not executor.future.set_running_or_notify_cancel()
        assert not sent.is_set()

    @pytest.mark.asyncio
    async def test_timeout_keeps_admission_occupied_until_worker_settles(self, monkeypatch, smtp_loop_errors) -> None:
        from fastapi import HTTPException

        from backend_core.settings_schemas import TestSmtpRequest
        from modules.settings.routes import test_smtp

        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = 0

        def _slow_send(*_args, **_kwargs) -> None:
            nonlocal calls
            calls += 1
            started.set()
            if calls == 1:
                assert release.wait(timeout=5)
                finished.set()

        monkeypatch.setattr('modules.settings.routes.send_smtp_message', _slow_send)
        with ThreadPoolExecutor(max_workers=1) as executor:
            _use_smtp_test_executor(monkeypatch, executor, deadline=0.05)
            request = TestSmtpRequest(to='recipient@test.com')
            first = asyncio.create_task(test_smtp(request))
            assert await asyncio.to_thread(started.wait, 1)
            with pytest.raises(HTTPException) as exc_info:
                await first
            assert exc_info.value.status_code == 504
            assert 'may have accepted' in exc_info.value.detail

            with pytest.raises(HTTPException) as busy:
                await test_smtp(request)
            assert busy.value.status_code == 429

            release.set()
            assert await asyncio.to_thread(finished.wait, 1)

            loop = asyncio.get_running_loop()
            admission_deadline = loop.time() + 1
            while True:
                try:
                    result = await test_smtp(request)
                except HTTPException as exc:
                    assert exc.status_code == 429
                    assert loop.time() < admission_deadline
                    await asyncio.sleep(0.01)
                    continue
                break

        assert result.success is True
        assert calls == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize('cancel_request', [False, True])
    async def test_ended_request_observes_late_smtp_error(self, monkeypatch, smtp_loop_errors, cancel_request: bool) -> None:
        from fastapi import HTTPException

        from backend_core.settings_schemas import TestSmtpRequest
        from modules.settings.routes import test_smtp

        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()

        def _late_failure(*_args, **_kwargs) -> None:
            started.set()
            assert release.wait(timeout=2)
            try:
                raise RuntimeError('late SMTP failure')
            finally:
                finished.set()

        monkeypatch.setattr('modules.settings.routes.send_smtp_message', _late_failure)
        with ThreadPoolExecutor(max_workers=1) as executor:
            _use_smtp_test_executor(monkeypatch, executor, deadline=0.05)
            request = TestSmtpRequest(to='recipient@test.com')
            sending = asyncio.create_task(test_smtp(request))
            assert await asyncio.to_thread(started.wait, 1)
            if cancel_request:
                sending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await sending
            else:
                with pytest.raises(HTTPException) as exc_info:
                    await sending
                assert exc_info.value.status_code == 504
                assert 'may have accepted' in exc_info.value.detail

            with pytest.raises(HTTPException) as busy:
                await test_smtp(request)
            assert busy.value.status_code == 429

            release.set()
            assert await asyncio.to_thread(finished.wait, 1)

        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gc.collect()
        assert smtp_loop_errors == []


class TestTestTelegram:
    """POST /v1/settings/test-telegram — test Telegram sending."""

    def test_not_configured(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'telegram_bot_enabled': False,
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/test-telegram', json={'chat_id': '123'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'not configured' in data['message'].lower()

    @patch('modules.settings.routes.httpx.AsyncClient.post')
    def test_success(self, mock_post: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot123:abc',
                'telegram_bot_enabled': True,
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-telegram', json={'chat_id': '456'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True

    @patch('modules.settings.routes.httpx.AsyncClient.post')
    def test_api_error(self, mock_post: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {'description': 'Bad Request: chat not found'}
        mock_post.return_value = mock_resp

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot123:abc',
                'telegram_bot_enabled': True,
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-telegram', json={'chat_id': 'bad'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'chat not found' in data['message'].lower()

    @patch('modules.settings.routes.httpx.AsyncClient.post')
    def test_transport_failure(self, mock_post: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        mock_post.side_effect = httpx.ConnectError('Connection refused')

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot123:abc',
                'telegram_bot_enabled': True,
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-telegram', json={'chat_id': '123'})
        assert resp.status_code == 502
        data = resp.json()
        assert 'refused' in data['detail'].lower()


class TestConfigEndpointWithDbSettings:
    """GET /v1/config — should reflect DB settings for smtp/telegram enabled."""

    def test_config_reflects_db_settings(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        # Save SMTP settings
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'mail.example.com',
                'smtp_port': 587,
                'smtp_user': 'user@example.com',
                'smtp_password': 'pw',
                'telegram_bot_token': 'botXYZ',
                'telegram_bot_enabled': False,
                'public_idb_debug': True,
            },
        )

        resp = client.get('/api/v1/config')
        assert resp.status_code == 200
        data = resp.json()
        assert data['auth_required'] is True
        assert data['verify_email_address'] is True
        assert data['smtp_enabled'] is True
        assert data['telegram_enabled'] is False
        assert data['public_idb_debug'] is True

    def test_config_reflects_empty_settings(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        monkeypatch.setattr('backend_core.auth_config.settings.verify_email_address', False)
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'telegram_bot_enabled': False,
                'public_idb_debug': False,
            },
        )

        resp = client.get('/api/v1/config')
        assert resp.status_code == 200
        data = resp.json()
        assert data['auth_required'] is False
        assert data['verify_email_address'] is False
        assert data['smtp_enabled'] is False
        assert data['telegram_enabled'] is False
        assert data['public_idb_debug'] is False


class TestGenerateUuid:
    """GET /v1/config/uuid — generate UUID v4 values."""

    def test_generates_single_uuid(self, client: TestClient) -> None:
        resp = client.get('/api/v1/config/uuid')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data['uuids']) == 1
        import uuid

        uuid.UUID(data['uuids'][0], version=4)

    def test_generates_multiple_uuids(self, client: TestClient) -> None:
        resp = client.get('/api/v1/config/uuid?count=5')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data['uuids']) == 5
        assert len(set(data['uuids'])) == 5  # all unique

    def test_rejects_invalid_count(self, client: TestClient) -> None:
        resp = client.get('/api/v1/config/uuid?count=0')
        assert resp.status_code == 422
        resp = client.get('/api/v1/config/uuid?count=21')
        assert resp.status_code == 422


class TestDetectTelegramChat:
    def test_not_configured(self, client: TestClient) -> None:
        client.put('/api/v1/settings', json={'telegram_bot_token': '', 'telegram_bot_enabled': False})
        response = client.post('/api/v1/settings/detect-telegram-chat')
        assert response.status_code == 200
        assert response.json()['success'] is False
        assert response.json()['chats'] == []

    @patch('modules.settings.routes.request_chat_detection')
    def test_detects_through_owner(self, request_detection, client: TestClient) -> None:
        request_detection.return_value = {
            'success': True,
            'message': 'Found 1 chat(s)',
            'chats': [{'chat_id': '123', 'title': 'Test User'}],
        }
        client.put('/api/v1/settings', json={'telegram_bot_token': 'bot123:abc', 'telegram_bot_enabled': True})
        response = client.post('/api/v1/settings/detect-telegram-chat')
        assert response.status_code == 200
        assert response.json()['chats'] == [{'chat_id': '123', 'title': 'Test User'}]
        assert request_detection.await_args.kwargs['token'] == 'bot123:abc'
        assert request_detection.await_args.kwargs['request_user_id']
        assert request_detection.await_args.kwargs['namespace']

    @patch('modules.settings.routes.request_chat_detection')
    def test_custom_token_uses_authenticated_owner_request(self, request_detection, client: TestClient) -> None:
        request_detection.return_value = {'success': True, 'message': 'Found 0 chat(s)', 'chats': []}
        response = client.post('/api/v1/settings/detect-chat-custom', json={'bot_token': 'custom:secret'})
        assert response.status_code == 200
        assert request_detection.await_args.kwargs['token'] == 'custom:secret'
        assert request_detection.await_args.kwargs['request_user_id']

    @pytest.mark.parametrize('failure,status', [('busy', 429), ('timeout', 504), ('transport', 502)])
    @patch('modules.settings.routes.request_chat_detection')
    def test_bounded_error_responses(self, request_detection, client: TestClient, failure: str, status: int) -> None:
        from modules.telegram.runtime import TelegramDetectionFailed, TelegramDetectionTimedOut
        from modules.telegram.store import DetectionQueueFull

        errors = {
            'busy': DetectionQueueFull('Detection queue is busy'),
            'timeout': TelegramDetectionTimedOut('Detection deadline expired'),
            'transport': TelegramDetectionFailed('Provider unavailable'),
        }
        request_detection.side_effect = errors[failure]
        response = client.post('/api/v1/settings/detect-chat-custom', json={'bot_token': 'custom:secret'})
        assert response.status_code == status
        assert 'custom:secret' not in response.text


class TestSeedSettingsFromEnv:
    """seed_settings_from_env() writes ENV values to an empty DB row."""

    def _make_engine(self):
        engine, _schema = _make_postgres_engine('settings')
        return engine

    def test_seeds_all_fields_when_db_is_empty(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr(app_settings, 'settings_encryption_key', 'test-key', raising=False)
        monkeypatch.setattr(app_settings, 'smtp_host', 'mail.example.com', raising=False)
        monkeypatch.setattr(app_settings, 'smtp_port', 465, raising=False)
        monkeypatch.setattr(app_settings, 'smtp_user', 'user@example.com', raising=False)
        monkeypatch.setattr(app_settings, 'telegram_bot_token', 'bot123:abc', raising=False)
        monkeypatch.setattr(app_settings, 'telegram_bot_enabled', True, raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'sk-or-test', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_default_model', 'openai/gpt-4o', raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            seed_settings_from_env(session)
            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.smtp_host == 'mail.example.com'
            assert row.smtp_port == 465
            assert row.smtp_user == 'user@example.com'
            assert row.telegram_bot_token.startswith('enc:v1:')
            assert row.telegram_bot_enabled is True
            assert row.openrouter_api_key.startswith('enc:v1:')
            assert row.openrouter_default_model == 'openai/gpt-4o'
            assert row.env_bootstrap_complete is True

    def test_does_not_overwrite_existing_db_values(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(app_settings, 'smtp_host', 'env.example.com', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'sk-or-env', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_default_model', 'env/model', raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            # Pre-populate DB with user-set values
            row = AppSettings(
                id=1,
                smtp_host='db.example.com',
                openrouter_api_key='sk-or-db',
                openrouter_default_model='db/model',
                env_bootstrap_complete=True,
            )
            session.add(row)
            session.commit()

            seed_settings_from_env(session)
            session.refresh(row)

            # DB values must not be overwritten
            assert row.smtp_host == 'db.example.com'
            assert row.openrouter_api_key == 'sk-or-db'
            assert row.openrouter_default_model == 'db/model'

    def test_seed_copies_deployment_key_when_saved_openrouter_key_is_empty(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr(app_settings, 'settings_encryption_key', 'test-key', raising=False)
        monkeypatch.setattr(app_settings, 'smtp_host', 'env.example.com', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'sk-or-env', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_default_model', 'env/model', raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            row = AppSettings(
                id=1,
                smtp_host='db.example.com',
                openrouter_api_key='',
                openrouter_default_model='db/model',
                env_bootstrap_complete=True,
            )
            session.add(row)
            session.commit()

            seed_settings_from_env(session)
            session.refresh(row)

            assert row.smtp_host == 'db.example.com'
            assert row.openrouter_default_model == 'db/model'
            assert row.openrouter_api_key.startswith('enc:v1:')
            assert decrypt_secret(row.openrouter_api_key) == 'sk-or-env'

    def test_seeds_openrouter_default_model_field(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(
            app_settings,
            'openrouter_default_model',
            'anthropic/claude-3-5-sonnet',
            raising=False,
        )

        engine = self._make_engine()
        with Session(engine) as session:
            seed_settings_from_env(session)
            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.openrouter_default_model == 'anthropic/claude-3-5-sonnet'

    def test_seed_is_idempotent(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr(app_settings, 'settings_encryption_key', 'test-key', raising=False)
        monkeypatch.setattr(app_settings, 'smtp_host', 'mail.example.com', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'sk-or-test', raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            seed_settings_from_env(session)
            seed_settings_from_env(session)  # second call must be a no-op
            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.smtp_host == 'mail.example.com'
            assert row.openrouter_api_key.startswith('enc:v1:')
            assert row.env_bootstrap_complete is True

    def test_existing_row_preserves_explicit_default_values(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(app_settings, 'smtp_port', 465, raising=False)
        monkeypatch.setattr(app_settings, 'telegram_bot_enabled', True, raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            row = AppSettings(
                id=1,
                smtp_port=587,
                telegram_bot_enabled=False,
                env_bootstrap_complete=True,
            )
            session.add(row)
            session.commit()

            seed_settings_from_env(session)
            session.refresh(row)

            assert row.smtp_port == 587
            assert row.telegram_bot_enabled is False

    def test_password_seed_logs_warning_until_encryption_key_exists(self, monkeypatch, caplog) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(app_settings, 'smtp_host', 'mail.example.com', raising=False)
        monkeypatch.setattr(app_settings, 'smtp_password', 'secret', raising=False)
        monkeypatch.delenv('SETTINGS_ENCRYPTION_KEY', raising=False)
        monkeypatch.setattr(app_settings, 'settings_encryption_key', '', raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            with caplog.at_level('WARNING'):
                seed_settings_from_env(session)

            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.smtp_host == 'mail.example.com'
            assert row.smtp_password == ''
            assert row.env_bootstrap_complete is False
            assert 'SETTINGS_ENCRYPTION_KEY' in caplog.text

    def test_lifespan_bot_check_uses_decrypted_settings_db(self, monkeypatch):
        from backend_core import database
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.secrets import encrypt_secret

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        engine, _schema = _make_postgres_engine('settings')

        with Session(engine) as session:
            row = AppSettings(
                id=1,
                telegram_bot_enabled=True,
                telegram_bot_token=encrypt_secret('bot:tok'),
            )
            session.add(row)
            session.commit()

        monkeypatch.setattr(database, 'settings_engine', engine, raising=False)

        from backend_core.settings_store import get_resolved_telegram_settings

        resolved = get_resolved_telegram_settings()
        assert resolved['enabled'] is True
        assert resolved['token'] == 'bot:tok'

    def test_update_settings_disables_future_env_bootstrap(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_schemas import SettingsUpdate
        from backend_core.settings_store import seed_settings_from_env, update_settings

        monkeypatch.setattr(app_settings, 'smtp_port', 465, raising=False)
        monkeypatch.setattr(app_settings, 'telegram_bot_enabled', True, raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            update_settings(
                session,
                SettingsUpdate(
                    smtp_port=587,
                    telegram_bot_enabled=False,
                ),
            )
            seed_settings_from_env(session)

            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.smtp_port == 587
            assert row.telegram_bot_enabled is False
            assert row.env_bootstrap_complete is True


class TestSettingsRuntimeReads:
    def _make_engine(self):
        engine, _schema = _make_postgres_engine('settings')
        return engine

    def test_secret_derivation_cache_tracks_key_material_changes(self, monkeypatch) -> None:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'first-key')
        first = encrypt_secret('alpha')

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'second-key')
        second = encrypt_secret('beta')

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'first-key')
        assert decrypt_secret(first) == 'alpha'

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'second-key')
        assert decrypt_secret(second) == 'beta'

    def test_get_settings_engine_is_lazy(self, monkeypatch, tmp_path) -> None:
        from backend_core import database

        monkeypatch.setattr(database, 'settings_engine', None, raising=False)
        monkeypatch.setattr(
            'backend_core.config.settings.database_url',
            __import__('os').environ['TEST_POSTGRES_URL'],
        )

        first = database.get_settings_engine()
        second = database.get_settings_engine()

        assert first is second
        assert database.settings_engine is first
        assert first.url.drivername.startswith('postgresql')
        first.dispose()

    def test_resolved_settings_reflect_external_database_update(self, monkeypatch) -> None:
        from backend_core import settings_store
        from backend_core.database import (
            clear_settings_engine_override,
            set_settings_engine_override,
        )
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_schemas import SettingsUpdate
        from backend_core.settings_store import get_resolved_smtp

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        notifications: list[dict[str, object]] = []
        monkeypatch.setattr(
            settings_store,
            '_notify_settings_changed',
            lambda _session: notifications.append({'kind': 'settings_changed'}),
        )
        engine = self._make_engine()
        set_settings_engine_override(engine)

        try:
            with Session(engine) as session:
                settings_store.update_settings(
                    session,
                    SettingsUpdate(
                        smtp_host='smtp.one.test',
                        smtp_port=587,
                        smtp_user='first',
                        smtp_password='pw-one',
                    ),
                )

            assert notifications == [{'kind': 'settings_changed'}]

            assert get_resolved_smtp() == {
                'host': 'smtp.one.test',
                'port': 587,
                'user': 'first',
                'password': 'pw-one',
            }

            # Simulate another API child committing a settings change.
            with engine.begin() as connection:
                connection.execute(
                    cast(Any, AppSettings).__table__.update().where(AppSettings.id == 1).values(smtp_host='smtp.two.test', smtp_port=465, smtp_user='second')
                )

            assert get_resolved_smtp() == {
                'host': 'smtp.two.test',
                'port': 465,
                'user': 'second',
                'password': 'pw-one',
            }
        finally:
            clear_settings_engine_override()

    def test_settings_save_and_bootstrap_do_not_write_tenant_outbox(self, monkeypatch) -> None:
        import psycopg
        from sqlalchemy import MetaData

        from backend_core.config import settings as app_settings
        from backend_core.database import clear_settings_engine_override, set_settings_engine_override
        from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_schemas import SettingsUpdate
        from backend_core.settings_store import seed_settings_from_env, update_settings

        settings_schema = f'public_settings_{uuid.uuid4().hex}'
        tenant_schema = f'tenant_settings_{uuid.uuid4().hex}'
        database_url = __import__('os').environ['TEST_POSTGRES_URL']
        admin_engine = create_engine(database_url)
        engine = create_engine(
            database_url,
            connect_args={'options': f'-c search_path={settings_schema}'},
        )
        listener = None

        try:
            with admin_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{settings_schema}"'))
                connection.execute(text(f'CREATE SCHEMA "{tenant_schema}"'))
            tenant_outbox = cast(Any, RuntimeOutboxEvent).__table__.to_metadata(MetaData(), schema=tenant_schema)
            with engine.begin() as connection:
                cast(Any, AppSettings).__table__.create(connection)
                tenant_outbox.create(connection)
            listener = psycopg.connect(
                database_url.replace('postgresql+psycopg://', 'postgresql://'),
                autocommit=True,
            )
            listener.execute('LISTEN runtime_events')

            monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
            monkeypatch.setattr(app_settings, 'smtp_host', 'bootstrap.test', raising=False)
            set_settings_engine_override(engine)

            with Session(engine) as session:
                seed_settings_from_env(session)
            with Session(engine) as session:
                update_settings(session, SettingsUpdate(smtp_host='saved.test'))
            notifications = [message.payload for message in listener.notifies(timeout=1, stop_after=100)]
            assert notifications.count('{"kind":"settings_changed"}') == 2

            with engine.connect() as connection:
                assert connection.execute(text("SELECT to_regclass('runtime_outbox_events')")).scalar_one() is None
                assert (
                    connection.execute(
                        text('SELECT to_regclass(:table_name)'),
                        {'table_name': f'{tenant_schema}.runtime_outbox_events'},
                    ).scalar_one()
                    is not None
                )
        finally:
            clear_settings_engine_override()
            if listener is not None:
                listener.close()
            engine.dispose()
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{settings_schema}" CASCADE'))
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_schema}" CASCADE'))
            admin_engine.dispose()

    def test_resolved_settings_reflect_bootstrap(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.database import (
            clear_settings_engine_override,
            set_settings_engine_override,
        )
        from backend_core.settings_store import (
            get_resolved_default_model,
            get_resolved_openrouter_key,
            seed_settings_from_env,
        )

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr(app_settings, 'settings_encryption_key', 'test-key', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'openrouter-seeded', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_default_model', 'seeded-model', raising=False)
        engine = self._make_engine()
        set_settings_engine_override(engine)

        try:
            assert get_resolved_openrouter_key() == ''
            assert get_resolved_default_model() == ''

            with Session(engine) as session:
                seed_settings_from_env(session)

            assert get_resolved_openrouter_key() == 'openrouter-seeded'
            assert get_resolved_default_model() == 'seeded-model'
        finally:
            clear_settings_engine_override()

    def test_resolved_openrouter_key_uses_deployment_key_when_saved_key_is_empty(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.database import clear_settings_engine_override, set_settings_engine_override
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.settings_store import get_resolved_openrouter_key

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr(app_settings, 'settings_encryption_key', 'test-key', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'sk-or-env', raising=False)
        engine = self._make_engine()
        set_settings_engine_override(engine)
        try:
            with Session(engine) as session:
                session.add(AppSettings(id=1, openrouter_api_key='', env_bootstrap_complete=True))
                session.commit()
            assert get_resolved_openrouter_key() == 'sk-or-env'
            with Session(engine) as session:
                row = session.get(AppSettings, 1)
                assert row is not None
                assert row.openrouter_api_key.startswith('enc:v1:')
                assert decrypt_secret(row.openrouter_api_key) == 'sk-or-env'
        finally:
            clear_settings_engine_override()

    def test_resolved_openrouter_key_prefers_saved_key(self, monkeypatch) -> None:
        from backend_core.config import settings as app_settings
        from backend_core.database import clear_settings_engine_override, set_settings_engine_override
        from backend_core.persistence.settings.models import AppSettings
        from backend_core.secrets import encrypt_secret
        from backend_core.settings_store import get_resolved_openrouter_key

        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
        monkeypatch.setattr(app_settings, 'settings_encryption_key', 'test-key', raising=False)
        monkeypatch.setattr(app_settings, 'openrouter_api_key', 'sk-or-env', raising=False)
        engine = self._make_engine()
        set_settings_engine_override(engine)
        try:
            with Session(engine) as session:
                session.add(
                    AppSettings(
                        id=1,
                        openrouter_api_key=encrypt_secret('sk-or-db'),
                        env_bootstrap_complete=True,
                    )
                )
                session.commit()
            assert get_resolved_openrouter_key() == 'sk-or-db'
        finally:
            clear_settings_engine_override()
