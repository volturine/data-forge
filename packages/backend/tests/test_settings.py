"""Tests for the settings module — GET/PUT settings, test SMTP/Telegram."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import httpx
import pytest
from core.secrets import MASKED_SECRET, decrypt_secret, encrypt_secret
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, create_engine


def _make_postgres_engine(prefix: str = "settings"):
    from sqlmodel import SQLModel

    url = __import__("os").environ["TEST_POSTGRES_URL"]
    schema = f"{prefix}_{uuid.uuid4().hex}"
    engine = create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={schema},public"},
    )

    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        SQLModel.metadata.create_all(connection)
    return engine, schema


@pytest.fixture(autouse=True)
def stub_telegram_bot_lifecycle():
    with (
        patch("modules.telegram.bot.telegram_bot.start"),
        patch("modules.telegram.bot.telegram_bot.stop"),
    ):
        yield


class TestGetSettings:
    """GET /v1/settings — returns singleton settings row."""

    def test_returns_defaults_when_no_row(self, client: TestClient) -> None:
        resp = client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "smtp_host" in data
        assert "smtp_port" in data
        assert "telegram_bot_token" in data
        assert "public_idb_debug" in data

    def test_returns_saved_values(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        # First save some values
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "mail.example.com",
                "smtp_port": 465,
                "smtp_user": "user@example.com",
                "smtp_password": "secret",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": True,
            },
        )
        resp = client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["smtp_host"] == "mail.example.com"
        assert data["smtp_port"] == 465
        assert data["smtp_user"] == "user@example.com"
        assert data["smtp_password"] == MASKED_SECRET
        assert data["telegram_bot_token"] == MASKED_SECRET
        assert data["public_idb_debug"] is True


class TestConfigRoute:
    def test_config_endpoint_returns_cached_frontend_config(self, client: TestClient) -> None:
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "default_namespace" in data
        assert "auth_required" in data


class TestNamespaceDatabaseConcurrency:
    def test_run_db_is_safe_across_concurrent_threads(self) -> None:
        from core.database import run_db
        from core.namespace import reset_namespace, set_namespace_context

        def call() -> int:
            token = set_namespace_context("alpha")
            try:
                return run_db(lambda session: 1)
            finally:
                reset_namespace(token)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: call(), range(8)))

        assert results == [1] * 8


class TestUpdateSettings:
    """PUT /v1/settings — upserts the singleton row."""

    def test_update_smtp(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        resp = client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "smtp_user": "test@test.com",
                "smtp_password": "pw",
                "telegram_bot_token": "",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["smtp_host"] == "smtp.test.com"
        assert data["smtp_user"] == "test@test.com"
        assert data["smtp_password"] == MASKED_SECRET

    def test_update_telegram(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        resp = client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot999:xyz",
                "telegram_bot_enabled": False,
                "public_idb_debug": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["telegram_bot_token"] == MASKED_SECRET

    def test_update_idb_debug(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        resp = client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "",
                "telegram_bot_enabled": False,
                "public_idb_debug": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["public_idb_debug"] is True

    def test_preserves_masked_secrets_on_partial_update(self, client: TestClient, monkeypatch) -> None:
        from backend_core.settings_store import (
            get_resolved_openrouter_key,
            get_resolved_smtp,
            get_resolved_telegram_token,
        )

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "smtp_user": "test@test.com",
                "smtp_password": "pw",
                "telegram_bot_token": "bot999:xyz",
                "telegram_bot_enabled": True,
                "openrouter_api_key": "sk-live",
                "public_idb_debug": False,
            },
        )

        resp = client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "smtp.changed.com",
                "smtp_password": MASKED_SECRET,
                "telegram_bot_token": "********",
                "openrouter_api_key": MASKED_SECRET,
            },
        )
        assert resp.status_code == 200
        assert get_resolved_smtp()["password"] == "pw"
        assert get_resolved_telegram_token() == "bot999:xyz"
        assert get_resolved_openrouter_key() == "sk-live"

    def test_encrypts_settings_secrets_at_rest(self, client: TestClient, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.database import run_settings_db

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "smtp_user": "test@test.com",
                "smtp_password": "pw",
                "telegram_bot_token": "bot999:xyz",
                "telegram_bot_enabled": True,
                "openrouter_api_key": "sk-live",
                "public_idb_debug": False,
            },
        )

        def _read(session: Session) -> AppSettings | None:
            return session.get(AppSettings, 1)

        row = run_settings_db(_read)
        assert row is not None
        assert row.smtp_password != "pw"
        assert row.telegram_bot_token != "bot999:xyz"
        assert row.openrouter_api_key != "sk-live"
        assert row.smtp_password.startswith("enc:v1:")
        assert row.telegram_bot_token.startswith("enc:v1:")
        assert row.openrouter_api_key.startswith("enc:v1:")

    def test_get_rejects_unsupported_secret_storage_format(self, client: TestClient, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.database import run_settings_db

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")

        def _seed(session: Session) -> None:
            row = session.get(AppSettings, 1)
            assert row is not None
            row.smtp_password = "enc:07001001000d"
            session.commit()

        run_settings_db(_seed)

        resp = client.get("/api/v1/settings")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Stored secret is not encrypted with the supported format"


class TestTestSmtp:
    """POST /v1/settings/test-smtp — test email sending."""

    def test_not_configured(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        # Ensure SMTP is cleared
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "",
                "telegram_bot_enabled": False,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/test-smtp", json={"to": "test@test.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "not configured" in data["message"].lower()

    @patch("modules.settings.routes.send_smtp_message")
    def test_success(self, mock_send_smtp: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")

        # Configure SMTP first
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "smtp_user": "user@test.com",
                "smtp_password": "pw",
                "telegram_bot_token": "",
                "telegram_bot_enabled": False,
                "public_idb_debug": False,
            },
        )

        resp = client.post("/api/v1/settings/test-smtp", json={"to": "recipient@test.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_send_smtp.assert_called_once()

    @patch("modules.settings.routes.send_smtp_message")
    def test_failure(self, mock_send_smtp: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_send_smtp.side_effect = ConnectionRefusedError("Connection refused")

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "bad-host",
                "smtp_port": 587,
                "smtp_user": "user@test.com",
                "smtp_password": "",
                "telegram_bot_token": "",
                "telegram_bot_enabled": False,
                "public_idb_debug": False,
            },
        )

        resp = client.post("/api/v1/settings/test-smtp", json={"to": "test@test.com"})
        assert resp.status_code == 502
        data = resp.json()
        assert "refused" in data["detail"].lower()


class TestTestTelegram:
    """POST /v1/settings/test-telegram — test Telegram sending."""

    def test_not_configured(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "",
                "telegram_bot_enabled": False,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/test-telegram", json={"chat_id": "123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "not configured" in data["message"].lower()

    @patch("modules.settings.routes.http_client.post")
    def test_success(self, mock_post: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )

        resp = client.post("/api/v1/settings/test-telegram", json={"chat_id": "456"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @patch("modules.settings.routes.http_client.post")
    def test_api_error(self, mock_post: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"description": "Bad Request: chat not found"}
        mock_post.return_value = mock_resp

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )

        resp = client.post("/api/v1/settings/test-telegram", json={"chat_id": "bad"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "chat not found" in data["message"].lower()

    @patch("modules.settings.routes.http_client.post")
    def test_transport_failure(self, mock_post: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )

        resp = client.post("/api/v1/settings/test-telegram", json={"chat_id": "123"})
        assert resp.status_code == 502
        data = resp.json()
        assert "refused" in data["detail"].lower()


class TestConfigEndpointWithDbSettings:
    """GET /v1/config — should reflect DB settings for smtp/telegram enabled."""

    def test_config_reflects_db_settings(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        monkeypatch.setattr("backend_core.auth_config.settings.auth_required", True)
        # Save SMTP settings
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "mail.example.com",
                "smtp_port": 587,
                "smtp_user": "user@example.com",
                "smtp_password": "pw",
                "telegram_bot_token": "botXYZ",
                "telegram_bot_enabled": False,
                "public_idb_debug": True,
            },
        )

        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_required"] is True
        assert data["verify_email_address"] is True
        assert data["smtp_enabled"] is True
        assert data["telegram_enabled"] is False
        assert data["public_idb_debug"] is True

    def test_config_reflects_empty_settings(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        monkeypatch.setattr("backend_core.auth_config.settings.auth_required", False)
        monkeypatch.setattr("backend_core.auth_config.settings.verify_email_address", False)
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "",
                "telegram_bot_enabled": False,
                "public_idb_debug": False,
            },
        )

        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_required"] is False
        assert data["verify_email_address"] is False
        assert data["smtp_enabled"] is False
        assert data["telegram_enabled"] is False
        assert data["public_idb_debug"] is False


class TestGenerateUuid:
    """GET /v1/config/uuid — generate UUID v4 values."""

    def test_generates_single_uuid(self, client: TestClient) -> None:
        resp = client.get("/api/v1/config/uuid")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["uuids"]) == 1
        import uuid

        uuid.UUID(data["uuids"][0], version=4)

    def test_generates_multiple_uuids(self, client: TestClient) -> None:
        resp = client.get("/api/v1/config/uuid?count=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["uuids"]) == 5
        assert len(set(data["uuids"])) == 5  # all unique

    def test_rejects_invalid_count(self, client: TestClient) -> None:
        resp = client.get("/api/v1/config/uuid?count=0")
        assert resp.status_code == 422
        resp = client.get("/api/v1/config/uuid?count=21")
        assert resp.status_code == 422


class TestDetectTelegramChat:
    """POST /v1/settings/detect-telegram-chat — detect chat IDs via getUpdates."""

    def test_not_configured(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "",
                "telegram_bot_enabled": False,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/detect-telegram-chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "not configured" in data["message"].lower()
        assert data["chats"] == []

    @patch("modules.telegram.bot.http_client.get")
    def test_success_with_chats(self, mock_get: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 1,
                    "message": {
                        "chat": {
                            "id": 123,
                            "first_name": "Test User",
                            "type": "private",
                        },
                        "text": "hello",
                    },
                },
                {
                    "update_id": 2,
                    "message": {
                        "chat": {"id": 456, "title": "Test Group", "type": "group"},
                        "text": "hi",
                    },
                },
            ],
        }
        mock_get.return_value = mock_resp

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/detect-telegram-chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["chats"]) == 2
        ids = {c["chat_id"] for c in data["chats"]}
        assert ids == {"123", "456"}

    @patch("modules.telegram.bot.http_client.get")
    def test_no_updates(self, mock_get: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": []}
        mock_get.return_value = mock_resp

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/detect-telegram-chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["chats"]) == 0

    @patch("modules.telegram.bot.http_client.get")
    def test_deduplicates_chats(self, mock_get: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 1,
                    "message": {
                        "chat": {"id": 123, "first_name": "User", "type": "private"},
                        "text": "msg1",
                    },
                },
                {
                    "update_id": 2,
                    "message": {
                        "chat": {"id": 123, "first_name": "User", "type": "private"},
                        "text": "msg2",
                    },
                },
            ],
        }
        mock_get.return_value = mock_resp

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/detect-telegram-chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["chats"]) == 1
        assert data["chats"][0]["chat_id"] == "123"

    @patch("modules.telegram.bot.http_client.get")
    def test_channel_post(self, mock_get: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 1,
                    "channel_post": {
                        "chat": {
                            "id": -100123,
                            "title": "My Channel",
                            "type": "channel",
                        },
                        "text": "post",
                    },
                },
            ],
        }
        mock_get.return_value = mock_resp

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/detect-telegram-chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["chats"]) == 1
        assert data["chats"][0]["title"] == "My Channel"

    @patch("modules.telegram.bot.http_client.get")
    def test_api_error(self, mock_get: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_get.return_value = mock_resp

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bad-token",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )
        resp = client.post("/api/v1/settings/detect-telegram-chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "error" in data["message"].lower()
        assert data["chats"] == []

    @patch("modules.telegram.bot.http_client.get")
    def test_transport_failure(self, mock_get: MagicMock, client: TestClient, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "bot123:abc",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )

        resp = client.post("/api/v1/settings/detect-telegram-chat")
        assert resp.status_code == 502
        data = resp.json()
        assert "refused" in data["detail"].lower()


class TestSeedSettingsFromEnv:
    """seed_settings_from_env() writes ENV values to an empty DB row."""

    def _make_engine(self):
        engine, _schema = _make_postgres_engine("settings")
        return engine

    def test_seeds_all_fields_when_db_is_empty(self, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.config import settings as app_settings

        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        monkeypatch.setattr(app_settings, "settings_encryption_key", "test-key", raising=False)
        monkeypatch.setattr(app_settings, "smtp_host", "mail.example.com", raising=False)
        monkeypatch.setattr(app_settings, "smtp_port", 465, raising=False)
        monkeypatch.setattr(app_settings, "smtp_user", "user@example.com", raising=False)
        monkeypatch.setattr(app_settings, "telegram_bot_token", "bot123:abc", raising=False)
        monkeypatch.setattr(app_settings, "telegram_bot_enabled", True, raising=False)
        monkeypatch.setattr(app_settings, "openrouter_api_key", "sk-or-test", raising=False)
        monkeypatch.setattr(app_settings, "openrouter_default_model", "openai/gpt-4o", raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            seed_settings_from_env(session)
            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.smtp_host == "mail.example.com"
            assert row.smtp_port == 465
            assert row.smtp_user == "user@example.com"
            assert row.telegram_bot_token.startswith("enc:v1:")
            assert row.telegram_bot_enabled is True
            assert row.openrouter_api_key.startswith("enc:v1:")
            assert row.openrouter_default_model == "openai/gpt-4o"
            assert row.env_bootstrap_complete is True

    def test_does_not_overwrite_existing_db_values(self, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.config import settings as app_settings

        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(app_settings, "smtp_host", "env.example.com", raising=False)
        monkeypatch.setattr(app_settings, "openrouter_api_key", "sk-or-env", raising=False)
        monkeypatch.setattr(app_settings, "openrouter_default_model", "env/model", raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            # Pre-populate DB with user-set values
            row = AppSettings(
                id=1,
                smtp_host="db.example.com",
                openrouter_api_key="sk-or-db",
                openrouter_default_model="db/model",
                env_bootstrap_complete=True,
            )
            session.add(row)
            session.commit()

            seed_settings_from_env(session)
            session.refresh(row)

            # DB values must not be overwritten
            assert row.smtp_host == "db.example.com"
            assert row.openrouter_api_key == "sk-or-db"
            assert row.openrouter_default_model == "db/model"

    def test_seeds_openrouter_default_model_field(self, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.config import settings as app_settings

        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(
            app_settings,
            "openrouter_default_model",
            "anthropic/claude-3-5-sonnet",
            raising=False,
        )

        engine = self._make_engine()
        with Session(engine) as session:
            seed_settings_from_env(session)
            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.openrouter_default_model == "anthropic/claude-3-5-sonnet"

    def test_seed_is_idempotent(self, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.config import settings as app_settings

        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        monkeypatch.setattr(app_settings, "settings_encryption_key", "test-key", raising=False)
        monkeypatch.setattr(app_settings, "smtp_host", "mail.example.com", raising=False)
        monkeypatch.setattr(app_settings, "openrouter_api_key", "sk-or-test", raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            seed_settings_from_env(session)
            seed_settings_from_env(session)  # second call must be a no-op
            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.smtp_host == "mail.example.com"
            assert row.openrouter_api_key.startswith("enc:v1:")
            assert row.env_bootstrap_complete is True

    def test_existing_row_preserves_explicit_default_values(self, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.config import settings as app_settings

        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(app_settings, "smtp_port", 465, raising=False)
        monkeypatch.setattr(app_settings, "telegram_bot_enabled", True, raising=False)

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
        from contracts.settings_models import AppSettings
        from core.config import settings as app_settings

        from backend_core.settings_store import seed_settings_from_env

        monkeypatch.setattr(app_settings, "smtp_host", "mail.example.com", raising=False)
        monkeypatch.setattr(app_settings, "smtp_password", "secret", raising=False)
        monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
        monkeypatch.setattr(app_settings, "settings_encryption_key", "", raising=False)

        engine = self._make_engine()
        with Session(engine) as session:
            with caplog.at_level("WARNING"):
                seed_settings_from_env(session)

            row = session.get(AppSettings, 1)
            assert row is not None
            assert row.smtp_host == "mail.example.com"
            assert row.smtp_password == ""
            assert row.env_bootstrap_complete is False
            assert "SETTINGS_ENCRYPTION_KEY" in caplog.text

    def test_lifespan_bot_check_uses_decrypted_settings_db(self, monkeypatch):
        from contracts.settings_models import AppSettings
        from core import database
        from core.secrets import encrypt_secret

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        engine, _schema = _make_postgres_engine("settings")

        with Session(engine) as session:
            row = AppSettings(
                id=1,
                telegram_bot_enabled=True,
                telegram_bot_token=encrypt_secret("bot:tok"),
            )
            session.add(row)
            session.commit()

        monkeypatch.setattr(database, "settings_engine", engine, raising=False)

        from backend_core.settings_store import get_resolved_telegram_settings

        resolved = get_resolved_telegram_settings()
        assert resolved["enabled"] is True
        assert resolved["token"] == "bot:tok"

    def test_update_settings_disables_future_env_bootstrap(self, monkeypatch) -> None:
        from contracts.settings_models import AppSettings
        from core.config import settings as app_settings

        from backend_core.settings_schemas import SettingsUpdate
        from backend_core.settings_store import seed_settings_from_env, update_settings

        monkeypatch.setattr(app_settings, "smtp_port", 465, raising=False)
        monkeypatch.setattr(app_settings, "telegram_bot_enabled", True, raising=False)

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


class TestSettingsRuntimeCaches:
    def _make_engine(self):
        engine, _schema = _make_postgres_engine("settings")
        return engine

    def test_secret_derivation_cache_tracks_key_material_changes(self, monkeypatch) -> None:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "first-key")
        first = encrypt_secret("alpha")

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "second-key")
        second = encrypt_secret("beta")

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "first-key")
        assert decrypt_secret(first) == "alpha"

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "second-key")
        assert decrypt_secret(second) == "beta"

    def test_get_settings_engine_is_lazy(self, monkeypatch, tmp_path) -> None:
        from core import database

        monkeypatch.setattr(database, "settings_engine", None, raising=False)
        monkeypatch.setattr(
            "core.config.settings.database_url",
            __import__("os").environ["TEST_POSTGRES_URL"],
        )

        first = database.get_settings_engine()
        second = database.get_settings_engine()

        assert first is second
        assert database.settings_engine is first
        assert first.url.drivername.startswith("postgresql")
        first.dispose()

    def test_resolved_settings_cache_invalidates_after_update(self, monkeypatch) -> None:
        from core.database import (
            clear_settings_engine_override,
            set_settings_engine_override,
        )

        from backend_core.settings_schemas import SettingsUpdate
        from backend_core.settings_store import get_resolved_smtp, update_settings

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        engine = self._make_engine()
        set_settings_engine_override(engine)

        try:
            with Session(engine) as session:
                update_settings(
                    session,
                    SettingsUpdate(
                        smtp_host="smtp.one.test",
                        smtp_port=587,
                        smtp_user="first",
                        smtp_password="pw-one",
                    ),
                )

            assert get_resolved_smtp() == {
                "host": "smtp.one.test",
                "port": 587,
                "user": "first",
                "password": "pw-one",
            }

            with Session(engine) as session:
                update_settings(
                    session,
                    SettingsUpdate(
                        smtp_host="smtp.two.test",
                        smtp_port=465,
                        smtp_user="second",
                        smtp_password="pw-two",
                    ),
                )

            assert get_resolved_smtp() == {
                "host": "smtp.two.test",
                "port": 465,
                "user": "second",
                "password": "pw-two",
            }
        finally:
            clear_settings_engine_override()

    def test_resolved_settings_cache_invalidates_after_bootstrap(self, monkeypatch) -> None:
        from core.config import settings as app_settings
        from core.database import (
            clear_settings_engine_override,
            set_settings_engine_override,
        )

        from backend_core.settings_store import (
            get_resolved_default_model,
            get_resolved_openrouter_key,
            seed_settings_from_env,
        )

        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "test-key")
        monkeypatch.setattr(app_settings, "settings_encryption_key", "test-key", raising=False)
        monkeypatch.setattr(app_settings, "openrouter_api_key", "openrouter-seeded", raising=False)
        monkeypatch.setattr(app_settings, "openrouter_default_model", "seeded-model", raising=False)
        engine = self._make_engine()
        set_settings_engine_override(engine)

        try:
            assert get_resolved_openrouter_key() == ""
            assert get_resolved_default_model() == ""

            with Session(engine) as session:
                seed_settings_from_env(session)

            assert get_resolved_openrouter_key() == "openrouter-seeded"
            assert get_resolved_default_model() == "seeded-model"
        finally:
            clear_settings_engine_override()
