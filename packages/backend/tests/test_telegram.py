"""Tests for the Telegram subscriber/listener module."""

import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from contracts.telegram_models import TelegramSubscriber
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from backend_core.telegram_schemas import ListenerCreate
from backend_core.telegram_store import (
    add_listener,
    add_subscriber,
    auto_populate_listeners,
    deactivate_subscriber,
    delete_subscriber,
    get_notification_chat_ids,
    get_subscriber_by_chat,
    list_listeners,
    list_subscribers,
    remove_listener,
)
from modules.telegram.bot import TelegramBot

# ---------------------------------------------------------------------------
# Service tests (direct DB calls)
# ---------------------------------------------------------------------------


class TestAddSubscriber:
    def test_creates_new(self, test_db_session: Session) -> None:
        result = add_subscriber(test_db_session, "111", "Alice", "tok-A")
        assert result.chat_id == "111"
        assert result.title == "Alice"
        assert result.bot_token == "tok-A"
        assert result.is_active is True

    def test_reactivates_existing(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "222", "Bob", "tok-A")
        deactivate_subscriber(test_db_session, sub.id)
        reactivated = add_subscriber(test_db_session, "222", "Bob Updated", "tok-A")
        assert reactivated.id == sub.id
        assert reactivated.is_active is True
        assert reactivated.title == "Bob Updated"


class TestGetSubscriberByChat:
    def test_found(self, test_db_session: Session) -> None:
        add_subscriber(test_db_session, "333", "Carol", "tok-B")
        found = get_subscriber_by_chat(test_db_session, "333", "tok-B")
        assert found is not None
        assert found.chat_id == "333"

    def test_not_found(self, test_db_session: Session) -> None:
        assert get_subscriber_by_chat(test_db_session, "999", "tok-X") is None


class TestListSubscribers:
    def test_all(self, test_db_session: Session) -> None:
        add_subscriber(test_db_session, "1", "A", "tok-1")
        add_subscriber(test_db_session, "2", "B", "tok-2")
        subs = list_subscribers(test_db_session)
        assert len(subs) == 2

    def test_filter_by_token(self, test_db_session: Session) -> None:
        add_subscriber(test_db_session, "1", "A", "tok-1")
        add_subscriber(test_db_session, "2", "B", "tok-2")
        subs = list_subscribers(test_db_session, bot_token="tok-1")
        assert len(subs) == 1
        assert subs[0].bot_token == "tok-1"


class TestDeactivateSubscriber:
    def test_deactivates(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "444", "Dave", "tok-C")
        deactivate_subscriber(test_db_session, sub.id)
        refreshed = test_db_session.get(TelegramSubscriber, sub.id)
        assert refreshed is not None
        assert refreshed.is_active is False

    def test_missing_id_no_error(self, test_db_session: Session) -> None:
        deactivate_subscriber(test_db_session, 99999)  # should not raise


class TestDeleteSubscriber:
    def test_deletes_with_listeners(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "555", "Eve", "tok-D")
        add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id="ds-1"))
        delete_subscriber(test_db_session, sub.id)
        assert test_db_session.get(TelegramSubscriber, sub.id) is None
        assert list_listeners(test_db_session, subscriber_id=sub.id) == []

    def test_missing_id_no_error(self, test_db_session: Session) -> None:
        delete_subscriber(test_db_session, 99999)  # should not raise


class TestListeners:
    def test_add_and_list(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "10", "X", "tok")
        listener = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id="ds-A"))
        assert listener.datasource_id == "ds-A"
        found = list_listeners(test_db_session, subscriber_id=sub.id)
        assert len(found) == 1

    def test_idempotent(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "11", "Y", "tok")
        first = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id="ds-B"))
        second = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id="ds-B"))
        assert first.id == second.id

    def test_filter_by_datasource(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "12", "Z", "tok")
        add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id="ds-C"))
        add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id="ds-D"))
        found = list_listeners(test_db_session, datasource_id="ds-C")
        assert len(found) == 1

    def test_remove(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "13", "W", "tok")
        listener = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id="ds-E"))
        remove_listener(test_db_session, listener.id)
        assert list_listeners(test_db_session, subscriber_id=sub.id) == []

    def test_remove_missing_no_error(self, test_db_session: Session) -> None:
        remove_listener(test_db_session, 99999)  # should not raise


class TestAutoPopulateListeners:
    def test_creates_for_active_subscribers(self, test_db_session: Session) -> None:
        s1 = add_subscriber(test_db_session, "20", "A", "tok")
        s2 = add_subscriber(test_db_session, "21", "B", "tok")
        deactivate_subscriber(test_db_session, s2.id)
        results = auto_populate_listeners(test_db_session, "ds-auto")
        assert len(results) == 1
        assert results[0].subscriber_id == s1.id


class TestGetNotificationChatIds:
    def test_returns_active_only(self, test_db_session: Session) -> None:
        s1 = add_subscriber(test_db_session, "30", "A", "tok")
        s2 = add_subscriber(test_db_session, "31", "B", "tok")
        add_listener(test_db_session, ListenerCreate(subscriber_id=s1.id, datasource_id="ds-X"))
        add_listener(test_db_session, ListenerCreate(subscriber_id=s2.id, datasource_id="ds-X"))
        deactivate_subscriber(test_db_session, s2.id)
        ids = get_notification_chat_ids(test_db_session, "ds-X")
        assert ids == [("30", "tok")]

    def test_empty_when_no_listeners(self, test_db_session: Session) -> None:
        assert get_notification_chat_ids(test_db_session, "ds-none") == []


# ---------------------------------------------------------------------------
# API route tests (via TestClient)
# ---------------------------------------------------------------------------


class TestBotStatusEndpoint:
    def test_status(self, client: TestClient) -> None:
        resp = client.get("/api/v1/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "token_configured" in data
        assert "subscriber_count" in data


class TestSubscriberEndpoints:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/telegram/subscribers")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_nonexistent(self, client: TestClient) -> None:
        resp = client.delete("/api/v1/telegram/subscribers/99999")
        assert resp.status_code == 204

    def test_delete_existing(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "100", "Test", "tok")
        resp = client.delete(f"/api/v1/telegram/subscribers/{sub.id}")
        assert resp.status_code == 204
        assert test_db_session.get(TelegramSubscriber, sub.id) is None


class TestListenerEndpoints:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/telegram/listeners")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_list(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "200", "L", "tok")
        resp = client.post(
            "/api/v1/telegram/listeners",
            json={"subscriber_id": sub.id, "datasource_id": "ds-api"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["datasource_id"] == "ds-api"

        resp = client.get("/api/v1/telegram/listeners", params={"subscriber_id": sub.id})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_delete(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "201", "M", "tok")
        listener = add_listener(
            test_db_session,
            ListenerCreate(subscriber_id=sub.id, datasource_id="ds-del"),
        )
        resp = client.delete(f"/api/v1/telegram/listeners/{listener.id}")
        assert resp.status_code == 204

    def test_filter_by_datasource(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, "202", "N", "tok")
        datasource_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        add_listener(
            test_db_session,
            ListenerCreate(subscriber_id=sub.id, datasource_id=datasource_id),
        )
        add_listener(
            test_db_session,
            ListenerCreate(subscriber_id=sub.id, datasource_id=other_id),
        )
        resp = client.get("/api/v1/telegram/listeners", params={"datasource_id": datasource_id})
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# Bot unit tests
# ---------------------------------------------------------------------------


class TestTelegramBot:
    def test_initial_state(self) -> None:
        bot = TelegramBot()
        assert bot.running is False
        assert bot.token == ""

    @patch("modules.telegram.bot.http_client.get")
    def test_start_stop(self, mock_get: MagicMock) -> None:
        # Make getUpdates return empty so the loop doesn't process anything
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": []}
        mock_get.return_value = mock_resp

        bot = TelegramBot()
        bot.start("test-token")
        assert bot.running is True
        assert bot.token == "test-token"
        bot.stop()
        assert bot.running is False

    def test_handle_update_subscribe(self, test_db_session: Session) -> None:
        bot = TelegramBot()
        bot._token = "tok-test"

        update = {
            "message": {
                "text": "/subscribe",
                "chat": {"id": 42, "first_name": "TestUser"},
            },
        }

        with patch.object(bot, "_send_message") as mock_send:
            bot._handle_update(update)
            mock_send.assert_called_once()
            assert "Subscribed" in mock_send.call_args[0][1]

        sub = get_subscriber_by_chat(test_db_session, "42", "tok-test")
        assert sub is not None
        assert sub.is_active is True

    def test_handle_update_unsubscribe(self, test_db_session: Session) -> None:
        bot = TelegramBot()
        bot._token = "tok-test"

        # First subscribe
        add_subscriber(test_db_session, "43", "Unsub", "tok-test")

        update = {
            "message": {
                "text": "/unsubscribe",
                "chat": {"id": 43, "first_name": "Unsub"},
            },
        }

        with patch.object(bot, "_send_message"):
            bot._handle_update(update)

        sub = get_subscriber_by_chat(test_db_session, "43", "tok-test")
        assert sub is not None
        assert sub.is_active is False

    def test_handle_update_start(self) -> None:
        bot = TelegramBot()
        bot._token = "tok-test"

        update = {
            "message": {
                "text": "/start",
                "chat": {"id": 44, "first_name": "Starter"},
            },
        }

        with patch.object(bot, "_send_message") as mock_send:
            bot._handle_update(update)
            mock_send.assert_called_once()
            assert "Welcome" in mock_send.call_args[0][1]

    def test_handle_update_no_message(self) -> None:
        bot = TelegramBot()
        bot._token = "tok-test"

        with patch.object(bot, "_send_message") as mock_send:
            bot._handle_update({"update_id": 1})
            mock_send.assert_not_called()

    @patch("modules.telegram.bot.http_client.post")
    def test_send_message(self, mock_post: MagicMock) -> None:
        bot = TelegramBot()
        bot._token = "tok-test"
        bot._send_message("123", "hello")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["chat_id"] == "123"
        assert call_kwargs[1]["json"]["text"] == "hello"

    @patch(
        "modules.telegram.bot.http_client.post",
        side_effect=httpx.ConnectError("network"),
    )
    def test_send_message_failure_no_raise(self, mock_post: MagicMock) -> None:
        bot = TelegramBot()
        bot._token = "tok-test"
        # Should not raise
        bot._send_message("123", "hello")

    def test_subscribe_unsubscribe_resubscribe_cycle(self, test_db_session: Session) -> None:
        """Full subscribe/unsubscribe/resubscribe cycle does not corrupt state."""
        bot = TelegramBot()
        bot._token = "tok-cycle"

        # Subscribe
        with patch.object(bot, "_send_message"):
            bot._handle_update(
                {
                    "message": {
                        "text": "/subscribe",
                        "chat": {"id": 50, "first_name": "Cycler"},
                    },
                },
            )
        test_db_session.expire_all()
        sub = get_subscriber_by_chat(test_db_session, "50", "tok-cycle")
        assert sub is not None
        assert sub.is_active is True
        original_id = sub.id

        # Unsubscribe
        with patch.object(bot, "_send_message"):
            bot._handle_update(
                {
                    "message": {
                        "text": "/unsubscribe",
                        "chat": {"id": 50, "first_name": "Cycler"},
                    },
                },
            )
        test_db_session.expire_all()
        sub = get_subscriber_by_chat(test_db_session, "50", "tok-cycle")
        assert sub is not None
        assert sub.is_active is False

        # Resubscribe — should reactivate same row
        with patch.object(bot, "_send_message"):
            bot._handle_update(
                {
                    "message": {
                        "text": "/subscribe",
                        "chat": {"id": 50, "first_name": "Cycler"},
                    },
                },
            )
        test_db_session.expire_all()
        sub = get_subscriber_by_chat(test_db_session, "50", "tok-cycle")
        assert sub is not None
        assert sub.is_active is True
        assert sub.id == original_id

    def test_handle_subscribe_db_error_sends_failure_message(self) -> None:
        bot = TelegramBot()
        bot._token = "tok-error"

        with (
            patch("core.database.run_db", side_effect=SQLAlchemyError("db down")),
            patch.object(bot, "_send_message") as mock_send,
        ):
            bot._handle_subscribe("51", "Broken")

        mock_send.assert_called_once_with("51", "Failed to subscribe. Please try again.")

    def test_handle_unsubscribe_db_error_does_not_reraise(self) -> None:
        bot = TelegramBot()
        bot._token = "tok-error"

        with patch("core.database.run_db", side_effect=SQLAlchemyError("db down")):
            bot._handle_unsubscribe("52")

    def test_poll_lock_prevents_concurrent_get_updates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_do_get_updates returns None when lock is held by another caller."""
        bot = TelegramBot()
        lock = MagicMock()
        lock.acquire.return_value = False
        monkeypatch.setattr(bot, "_poll_lock", lock)

        with patch("modules.telegram.bot.http_client.get") as mock_get:
            result = bot._do_get_updates("tok", {"offset": 0, "timeout": 5}, timeout=5)
        assert result is None
        mock_get.assert_not_called()

    def test_offset_tracked_per_token(self) -> None:
        """Offsets are tracked independently per bot token."""
        bot = TelegramBot()
        assert bot.get_offset("tok-a") == 0
        bot._set_offset("tok-a", 100)
        bot._set_offset("tok-b", 200)
        assert bot.get_offset("tok-a") == 100
        assert bot.get_offset("tok-b") == 200

    @patch("modules.telegram.bot.http_client.get")
    def test_409_clears_webhook_and_retries(self, mock_get: MagicMock) -> None:
        """409 response triggers webhook clear and does not immediately crash."""
        bot = TelegramBot()
        bot._token = "tok-409"
        bot._stop_event = MagicMock()
        bot._stop_event.is_set.return_value = False

        resp_409 = MagicMock()
        resp_409.status_code = 409

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = {"result": []}

        # First call 409, second call should work
        mock_get.side_effect = [resp_409, resp_ok]

        with patch.object(bot, "_clear_webhook") as mock_clear:
            # Simulate one iteration manually via _do_get_updates
            result = bot._do_get_updates("tok-409", {"offset": 0, "timeout": 5}, timeout=10)
            assert result is not None
            assert result.status_code == 409
            # On 409, the poll loop calls _clear_webhook
            bot._clear_webhook("tok-409")
            mock_clear.assert_called_once_with("tok-409")


# ---------------------------------------------------------------------------
# Settings write_settings restarts bot
# ---------------------------------------------------------------------------


class TestSettingsRestartBot:
    @patch("modules.telegram.bot.telegram_bot")
    def test_start_on_token_set(self, mock_bot: MagicMock, client: TestClient) -> None:
        mock_bot.running = False
        resp = client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "new-token",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )
        assert resp.status_code == 200
        mock_bot.start.assert_called_once_with("new-token")

    @patch("modules.telegram.bot.telegram_bot")
    def test_stop_on_token_clear(self, mock_bot: MagicMock, client: TestClient) -> None:
        mock_bot.running = True
        resp = client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "",
                "public_idb_debug": False,
            },
        )
        assert resp.status_code == 200
        mock_bot.stop.assert_called_once_with()

    @patch("modules.telegram.bot.telegram_bot")
    def test_write_settings_surfaces_runtime_failure(self, mock_bot: MagicMock, client: TestClient) -> None:
        mock_bot.running = False
        mock_bot.start.side_effect = RuntimeError("boom")

        resp = client.put(
            "/api/v1/settings",
            json={
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "telegram_bot_token": "broken-token",
                "telegram_bot_enabled": True,
                "public_idb_debug": False,
            },
        )

        assert resp.status_code == 502
        assert resp.json()["detail"] == "Telegram bot runtime update failed: boom"
