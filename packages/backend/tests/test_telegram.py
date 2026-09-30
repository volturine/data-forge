"""Tests for the Telegram subscriber/listener module."""

import uuid

import httpx
import pytest
from sqlmodel import Session

from backend_core.persistence.telegram.models import TelegramSubscriber
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
from tests.http_client import TestClient

# ---------------------------------------------------------------------------
# Service tests (direct DB calls)
# ---------------------------------------------------------------------------


class TestAddSubscriber:
    def test_creates_new(self, test_db_session: Session) -> None:
        result = add_subscriber(test_db_session, '111', 'Alice', 'tok-A')
        assert result.chat_id == '111'
        assert result.title == 'Alice'
        assert result.is_active is True

    def test_reactivates_existing(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '222', 'Bob', 'tok-A')
        deactivate_subscriber(test_db_session, sub.id)
        reactivated = add_subscriber(test_db_session, '222', 'Bob Updated', 'tok-A')
        assert reactivated.id == sub.id
        assert reactivated.is_active is True
        assert reactivated.title == 'Bob Updated'


class TestGetSubscriberByChat:
    def test_found(self, test_db_session: Session) -> None:
        add_subscriber(test_db_session, '333', 'Carol', 'tok-B')
        found = get_subscriber_by_chat(test_db_session, '333', 'tok-B')
        assert found is not None
        assert found.chat_id == '333'

    def test_not_found(self, test_db_session: Session) -> None:
        assert get_subscriber_by_chat(test_db_session, '999', 'tok-X') is None


class TestListSubscribers:
    def test_all(self, test_db_session: Session) -> None:
        add_subscriber(test_db_session, '1', 'A', 'tok-1')
        add_subscriber(test_db_session, '2', 'B', 'tok-2')
        subs = list_subscribers(test_db_session)
        assert len(subs) == 2

    def test_filter_by_token(self, test_db_session: Session) -> None:
        add_subscriber(test_db_session, '1', 'A', 'tok-1')
        add_subscriber(test_db_session, '2', 'B', 'tok-2')
        subs = list_subscribers(test_db_session, bot_token='tok-1')
        assert len(subs) == 1
        assert subs[0].chat_id == '1'


class TestDeactivateSubscriber:
    def test_deactivates(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '444', 'Dave', 'tok-C')
        deactivate_subscriber(test_db_session, sub.id)
        refreshed = test_db_session.get(TelegramSubscriber, sub.id)
        assert refreshed is not None
        assert refreshed.is_active is False

    def test_missing_id_no_error(self, test_db_session: Session) -> None:
        deactivate_subscriber(test_db_session, 99999)  # should not raise


class TestDeleteSubscriber:
    def test_deletes_with_listeners(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '555', 'Eve', 'tok-D')
        add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-1'))
        delete_subscriber(test_db_session, sub.id)
        assert test_db_session.get(TelegramSubscriber, sub.id) is None
        assert list_listeners(test_db_session, subscriber_id=sub.id) == []

    def test_missing_id_no_error(self, test_db_session: Session) -> None:
        delete_subscriber(test_db_session, 99999)  # should not raise


class TestListeners:
    def test_add_and_list(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '10', 'X', 'tok')
        listener = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-A'))
        assert listener.datasource_id == 'ds-A'
        found = list_listeners(test_db_session, subscriber_id=sub.id)
        assert len(found) == 1

    def test_idempotent(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '11', 'Y', 'tok')
        first = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-B'))
        second = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-B'))
        assert first.id == second.id

    def test_filter_by_datasource(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '12', 'Z', 'tok')
        add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-C'))
        add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-D'))
        found = list_listeners(test_db_session, datasource_id='ds-C')
        assert len(found) == 1

    def test_remove(self, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '13', 'W', 'tok')
        listener = add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-E'))
        remove_listener(test_db_session, listener.id)
        assert list_listeners(test_db_session, subscriber_id=sub.id) == []

    def test_remove_missing_no_error(self, test_db_session: Session) -> None:
        remove_listener(test_db_session, 99999)  # should not raise


class TestAutoPopulateListeners:
    def test_creates_for_active_subscribers(self, test_db_session: Session) -> None:
        s1 = add_subscriber(test_db_session, '20', 'A', 'tok')
        s2 = add_subscriber(test_db_session, '21', 'B', 'tok')
        deactivate_subscriber(test_db_session, s2.id)
        results = auto_populate_listeners(test_db_session, 'ds-auto')
        assert len(results) == 1
        assert results[0].subscriber_id == s1.id


class TestGetNotificationChatIds:
    def test_returns_active_only(self, test_db_session: Session) -> None:
        s1 = add_subscriber(test_db_session, '30', 'A', 'tok')
        s2 = add_subscriber(test_db_session, '31', 'B', 'tok')
        add_listener(test_db_session, ListenerCreate(subscriber_id=s1.id, datasource_id='ds-X'))
        add_listener(test_db_session, ListenerCreate(subscriber_id=s2.id, datasource_id='ds-X'))
        deactivate_subscriber(test_db_session, s2.id)
        ids = get_notification_chat_ids(test_db_session, 'ds-X')
        assert ids == [('30', 'tok')]

    def test_empty_when_no_listeners(self, test_db_session: Session) -> None:
        assert get_notification_chat_ids(test_db_session, 'ds-none') == []


# ---------------------------------------------------------------------------
# API route tests (via TestClient)
# ---------------------------------------------------------------------------


class TestBotStatusEndpoint:
    def test_status(self, client: TestClient) -> None:
        resp = client.get('/api/v1/telegram/status')
        assert resp.status_code == 200
        data = resp.json()
        assert 'running' in data
        assert 'token_configured' in data
        assert 'subscriber_count' in data


class TestSubscriberEndpoints:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get('/api/v1/telegram/subscribers')
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_nonexistent(self, client: TestClient) -> None:
        resp = client.delete('/api/v1/telegram/subscribers/99999')
        assert resp.status_code == 204

    def test_delete_existing(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '100', 'Test', 'tok')
        resp = client.delete(f'/api/v1/telegram/subscribers/{sub.id}')
        assert resp.status_code == 204
        assert test_db_session.get(TelegramSubscriber, sub.id) is None


class TestListenerEndpoints:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get('/api/v1/telegram/listeners')
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_list(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '200', 'L', 'tok')
        resp = client.post(
            '/api/v1/telegram/listeners',
            json={'subscriber_id': sub.id, 'datasource_id': 'ds-api'},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['datasource_id'] == 'ds-api'

        resp = client.get('/api/v1/telegram/listeners', params={'subscriber_id': sub.id})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_delete(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '201', 'M', 'tok')
        listener = add_listener(
            test_db_session,
            ListenerCreate(subscriber_id=sub.id, datasource_id='ds-del'),
        )
        resp = client.delete(f'/api/v1/telegram/listeners/{listener.id}')
        assert resp.status_code == 204

    def test_filter_by_datasource(self, client: TestClient, test_db_session: Session) -> None:
        sub = add_subscriber(test_db_session, '202', 'N', 'tok')
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
        resp = client.get('/api/v1/telegram/listeners', params={'datasource_id': datasource_id})
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# Stateless command handling runs only within the coordinator owner.


class TestTelegramUpdateHandling:
    @pytest.mark.asyncio
    async def test_subscribe_replay_is_idempotent(self, test_db_session: Session, monkeypatch) -> None:
        from modules.telegram.bot import handle_update

        monkeypatch.setattr('modules.telegram.bot.require_generation', lambda _session, _generation: None)
        messages: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            messages.append(request)
            return httpx.Response(200, json={'ok': True})

        update: dict[str, object] = {'message': {'text': '/subscribe', 'chat': {'id': 42, 'first_name': 'Test'}}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await handle_update(client, token='tok-test', update=update, generation=7)
            first = get_subscriber_by_chat(test_db_session, '42', 'tok-test')
            assert first is not None
            first_id = first.id
            await handle_update(client, token='tok-test', update=update, generation=7)
        test_db_session.expire_all()
        subscribers = list_subscribers(test_db_session, 'tok-test')
        assert len(subscribers) == 1
        assert subscribers[0].id == first_id
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_failed_reply_propagates_for_offset_retry(self) -> None:
        from modules.telegram.bot import handle_update

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(503))) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await handle_update(client, token='tok-test', update={'message': {'text': '/start', 'chat': {'id': 42}}}, generation=7)
