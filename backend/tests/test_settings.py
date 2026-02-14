"""Tests for the settings module — GET/PUT settings, test SMTP/Telegram."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestGetSettings:
    """GET /v1/settings — returns singleton settings row."""

    def test_returns_defaults_when_no_row(self) -> None:
        resp = client.get('/api/v1/settings')
        assert resp.status_code == 200
        data = resp.json()
        assert 'smtp_host' in data
        assert 'smtp_port' in data
        assert 'telegram_bot_token' in data
        assert 'public_idb_debug' in data

    def test_returns_saved_values(self) -> None:
        # First save some values
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'mail.example.com',
                'smtp_port': 465,
                'smtp_user': 'user@example.com',
                'smtp_password': 'secret',
                'telegram_bot_token': 'bot123:abc',
                'public_idb_debug': True,
            },
        )
        resp = client.get('/api/v1/settings')
        assert resp.status_code == 200
        data = resp.json()
        assert data['smtp_host'] == 'mail.example.com'
        assert data['smtp_port'] == 465
        assert data['smtp_user'] == 'user@example.com'
        assert data['smtp_password'] == 'secret'
        assert data['telegram_bot_token'] == 'bot123:abc'
        assert data['public_idb_debug'] is True


class TestUpdateSettings:
    """PUT /v1/settings — upserts the singleton row."""

    def test_update_smtp(self) -> None:
        resp = client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_user': 'test@test.com',
                'smtp_password': 'pw',
                'telegram_bot_token': '',
                'public_idb_debug': False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['smtp_host'] == 'smtp.test.com'
        assert data['smtp_user'] == 'test@test.com'

    def test_update_telegram(self) -> None:
        resp = client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot999:xyz',
                'public_idb_debug': False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()['telegram_bot_token'] == 'bot999:xyz'

    def test_update_idb_debug(self) -> None:
        resp = client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'public_idb_debug': True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()['public_idb_debug'] is True


class TestTestSmtp:
    """POST /v1/settings/test-smtp — test email sending."""

    def test_not_configured(self) -> None:
        # Ensure SMTP is cleared
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/test-smtp', json={'to': 'test@test.com'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'not configured' in data['message'].lower()

    @patch('modules.settings.routes.smtplib.SMTP')
    def test_success(self, mock_smtp_cls: MagicMock) -> None:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        # Configure SMTP first
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_user': 'user@test.com',
                'smtp_password': 'pw',
                'telegram_bot_token': '',
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-smtp', json={'to': 'recipient@test.com'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True

    @patch('modules.settings.routes.smtplib.SMTP')
    def test_failure(self, mock_smtp_cls: MagicMock) -> None:
        mock_smtp_cls.side_effect = ConnectionRefusedError('Connection refused')

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'bad-host',
                'smtp_port': 587,
                'smtp_user': 'user@test.com',
                'smtp_password': '',
                'telegram_bot_token': '',
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-smtp', json={'to': 'test@test.com'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'refused' in data['message'].lower()


class TestTestTelegram:
    """POST /v1/settings/test-telegram — test Telegram sending."""

    def test_not_configured(self) -> None:
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/test-telegram', json={'chat_id': '123'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'not configured' in data['message'].lower()

    @patch('modules.settings.routes.httpx.post')
    def test_success(self, mock_post: MagicMock) -> None:
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
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-telegram', json={'chat_id': '456'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True

    @patch('modules.settings.routes.httpx.post')
    def test_api_error(self, mock_post: MagicMock) -> None:
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
                'public_idb_debug': False,
            },
        )

        resp = client.post('/api/v1/settings/test-telegram', json={'chat_id': 'bad'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'chat not found' in data['message'].lower()


class TestConfigEndpointWithDbSettings:
    """GET /v1/config — should reflect DB settings for smtp/telegram enabled."""

    def test_config_reflects_db_settings(self) -> None:
        # Save SMTP settings
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': 'mail.example.com',
                'smtp_port': 587,
                'smtp_user': 'user@example.com',
                'smtp_password': 'pw',
                'telegram_bot_token': 'botXYZ',
                'public_idb_debug': True,
            },
        )

        resp = client.get('/api/v1/config')
        assert resp.status_code == 200
        data = resp.json()
        assert data['smtp_enabled'] is True
        assert data['telegram_enabled'] is True
        assert data['public_idb_debug'] is True

    def test_config_reflects_empty_settings(self) -> None:
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'public_idb_debug': False,
            },
        )

        resp = client.get('/api/v1/config')
        assert resp.status_code == 200
        data = resp.json()
        assert data['smtp_enabled'] is False
        assert data['telegram_enabled'] is False
        assert data['public_idb_debug'] is False


class TestDetectTelegramChat:
    """POST /v1/settings/detect-telegram-chat — detect chat IDs via getUpdates."""

    def test_not_configured(self) -> None:
        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': '',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/detect-telegram-chat')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'not configured' in data['message'].lower()
        assert data['chats'] == []

    @patch('modules.settings.routes.httpx.get')
    def test_success_with_chats(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'ok': True,
            'result': [
                {
                    'update_id': 1,
                    'message': {
                        'chat': {'id': 123, 'first_name': 'Test User', 'type': 'private'},
                        'text': 'hello',
                    },
                },
                {
                    'update_id': 2,
                    'message': {
                        'chat': {'id': 456, 'title': 'Test Group', 'type': 'group'},
                        'text': 'hi',
                    },
                },
            ],
        }
        mock_get.return_value = mock_resp

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot123:abc',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/detect-telegram-chat')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert len(data['chats']) == 2
        ids = {c['chat_id'] for c in data['chats']}
        assert ids == {'123', '456'}

    @patch('modules.settings.routes.httpx.get')
    def test_no_updates(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'ok': True, 'result': []}
        mock_get.return_value = mock_resp

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot123:abc',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/detect-telegram-chat')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert len(data['chats']) == 0

    @patch('modules.settings.routes.httpx.get')
    def test_deduplicates_chats(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'ok': True,
            'result': [
                {
                    'update_id': 1,
                    'message': {
                        'chat': {'id': 123, 'first_name': 'User', 'type': 'private'},
                        'text': 'msg1',
                    },
                },
                {
                    'update_id': 2,
                    'message': {
                        'chat': {'id': 123, 'first_name': 'User', 'type': 'private'},
                        'text': 'msg2',
                    },
                },
            ],
        }
        mock_get.return_value = mock_resp

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot123:abc',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/detect-telegram-chat')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert len(data['chats']) == 1
        assert data['chats'][0]['chat_id'] == '123'

    @patch('modules.settings.routes.httpx.get')
    def test_channel_post(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'ok': True,
            'result': [
                {
                    'update_id': 1,
                    'channel_post': {
                        'chat': {'id': -100123, 'title': 'My Channel', 'type': 'channel'},
                        'text': 'post',
                    },
                },
            ],
        }
        mock_get.return_value = mock_resp

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bot123:abc',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/detect-telegram-chat')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert len(data['chats']) == 1
        assert data['chats'][0]['title'] == 'My Channel'

    @patch('modules.settings.routes.httpx.get')
    def test_api_error(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = 'Unauthorized'
        mock_get.return_value = mock_resp

        client.put(
            '/api/v1/settings',
            json={
                'smtp_host': '',
                'smtp_port': 587,
                'smtp_user': '',
                'smtp_password': '',
                'telegram_bot_token': 'bad-token',
                'public_idb_debug': False,
            },
        )
        resp = client.post('/api/v1/settings/detect-telegram-chat')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'error' in data['message'].lower()
        assert data['chats'] == []
