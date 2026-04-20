"""Tests for chat module: sessions, routes, history, streaming."""

import asyncio
import json
import re
import time
from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from modules.chat.sessions import ChatSession, LiveSession, SessionStore


def _session_history(session_id: str) -> list[dict]:
    from modules.chat.sessions import session_store

    live = session_store.get(session_id)
    assert live is not None
    return live.get_history()


def _done_count(history: list[dict]) -> int:
    return sum(event.get('type') == 'done' for event in history)


def _wait_for_history(session_id: str, predicate: Callable[[list[dict]], bool], *, timeout: float = 0.5) -> list[dict]:
    deadline = time.monotonic() + timeout
    while True:
        history = _session_history(session_id)
        if predicate(history):
            return history
        if time.monotonic() >= deadline:
            raise AssertionError(f'Timed out waiting for history condition for session {session_id}')
        time.sleep(0.005)


async def _wait_for_history_async(
    session_id: str,
    predicate: Callable[[list[dict]], bool],
    *,
    timeout: float = 0.5,
) -> list[dict]:
    deadline = time.monotonic() + timeout
    while True:
        history = _session_history(session_id)
        if predicate(history):
            return history
        if time.monotonic() >= deadline:
            raise AssertionError(f'Timed out waiting for history condition for session {session_id}')
        await asyncio.sleep(0.005)


class TestLiveSession:
    def test_add_message_appends_to_messages(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.add_message('user', 'hello')
        assert s.messages == [{'role': 'user', 'content': 'hello'}]

    def test_push_event_stores_in_history(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.push_event({'type': 'message', 'role': 'user', 'content': 'hi'})
        assert len(s.get_history()) == 1
        assert s.get_history()[0]['type'] == 'message'

    def test_get_history_returns_copy(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.push_event({'type': 'done'})
        history = s.get_history()
        history.clear()
        assert len(s.get_history()) == 1

    def test_push_event_queues_when_not_closed(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.push_event({'type': 'done'})
        assert s._queue.qsize() == 1

    def test_push_event_skips_queue_when_closed(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.close_stream()
        s.push_event({'type': 'done'})
        assert s._queue.qsize() == 1

    def test_multiple_turns_accumulate_history(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.push_event({'type': 'message', 'role': 'user', 'content': 'hi'})
        s.push_event({'type': 'message', 'role': 'assistant', 'content': 'hello'})
        s.push_event({'type': 'done'})
        s.push_event({'type': 'message', 'role': 'user', 'content': 'again'})
        s.push_event({'type': 'done'})
        assert len(s.get_history()) == 5

    async def test_busy_guard(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        assert s.busy is False
        await s.set_busy(True)
        assert s.busy is True
        await s.set_busy(False)
        assert s.busy is False

    def test_bounded_messages(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        for i in range(120):
            s.add_message('user', f'msg-{i}')
        assert len(s.messages) == 100
        # No system messages, so oldest non-system kept is msg-20
        assert s.messages[0]['content'] == 'msg-20'

    def test_bounded_history(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.close_stream()
        for i in range(520):
            s.push_event({'type': 'message', 'content': f'evt-{i}'})
        assert len(s.get_history()) == 500

    def test_reopen_stream(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        s.close_stream()
        assert s._closed is True
        s.reopen_stream()
        assert s._closed is False
        s.push_event({'type': 'done'})
        assert s._queue.qsize() == 1


class TestSessionStore:
    def test_create_returns_session(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        assert s.id
        assert s.model == 'gpt-4o-mini'

    def test_create_with_system_prompt_prepends_system_message(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key', system_prompt='Be concise.')
        assert s.system_prompt == 'Be concise.'
        assert s.messages == [{'role': 'system', 'content': 'Be concise.'}]

    def test_create_without_system_prompt_has_empty_messages(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        assert s.system_prompt == ''
        assert s.messages == []

    def test_get_returns_session(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        assert store.get(s.id) is s

    def test_get_unknown_returns_none(self) -> None:
        store = SessionStore()
        assert store.get('nonexistent') is None

    def test_get_old_session_still_returns(self) -> None:
        """Sessions persist in DB regardless of age — only memory cache is evicted."""
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        s.created_at -= SessionStore.MEMORY_TTL + 1
        assert store.get(s.id) is not None

    def test_sweep_evicts_memory_preserves_db(self) -> None:
        """Sweep removes in-memory wrappers but DB rows survive."""
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        sid = s.id
        s.created_at -= SessionStore.MEMORY_TTL + 1
        s.last_activity -= SessionStore.MEMORY_TTL + 1
        store.sweep()
        assert sid not in store._live
        # But DB row still exists — get() reloads it
        reloaded = store.get(sid)
        assert reloaded is not None

    def test_delete_removes_session_and_closes_stream(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        result = store.delete(s.id)
        assert result is True
        assert store.get(s.id) is None
        assert s._closed is True

    def test_delete_unknown_returns_false(self) -> None:
        store = SessionStore()
        result = store.delete('nonexistent')
        assert result is False

    def test_db_persistence_survives_eviction(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        sid = s.id
        s.add_message('user', 'hello')
        s.push_event({'type': 'message', 'role': 'user', 'content': 'hello'})
        store.flush(sid)
        del store._live[sid]
        restored = store.get(sid)
        assert restored is not None
        assert restored.messages == [{'role': 'user', 'content': 'hello'}]
        assert len(restored.get_history()) == 1

    def test_flush_persists_state(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        s.add_message('user', 'hi')
        store.flush(s.id)
        store2 = SessionStore()
        restored = store2.get(s.id)
        assert restored is not None
        assert restored.messages == [{'role': 'user', 'content': 'hi'}]

    def test_api_key_is_encrypted_at_rest(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        with store._db() as db:
            row = db.get(ChatSession, s.id)
            assert row is not None
            assert row.api_key != 'key'
            assert row.api_key.startswith('enc:v1:')

    def test_legacy_api_key_migrates_on_load(self) -> None:
        store = SessionStore()
        with store._db() as db:
            row = ChatSession(id='legacy', provider='openrouter', model='gpt-4o-mini', api_key='legacy-key')
            db.add(row)
            db.commit()
        live = store.get('legacy')
        assert live is not None
        assert live.api_key == 'legacy-key'
        with store._db() as db:
            stored = db.get(ChatSession, 'legacy')
            assert stored is not None
            assert stored.api_key != 'legacy-key'
            assert stored.api_key.startswith('enc:v1:')


class TestChatRoutes:
    def test_chat_routes_require_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from main import app
        from modules.auth.dependencies import get_current_user

        monkeypatch.setattr('core.config.settings.auth_required', True)
        app.dependency_overrides.pop(get_current_user, None)
        resp = client.get('/api/v1/ai/chat/sessions')
        assert resp.status_code == 401

    def test_create_session(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert 'session_id' in data
        assert data['model'] == 'gpt-4o-mini'
        assert data['provider'] == 'openrouter'

    def test_create_session_requires_provider(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        assert resp.status_code == 422

    def test_create_session_without_api_key(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini'},
        )
        assert resp.status_code == 200
        assert 'session_id' in resp.json()

    def test_create_session_with_system_prompt(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'key', 'system_prompt': 'Be brief.'},
        )
        assert resp.status_code == 200
        sid = resp.json()['session_id']
        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.system_prompt == 'Be brief.'
        assert live.messages[0] == {'role': 'system', 'content': 'Be brief.'}

    def test_update_session_model(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'key'},
        )
        sid = resp.json()['session_id']
        patch_resp = client.patch(
            f'/api/v1/ai/chat/sessions/{sid}',
            json={'model': 'anthropic/claude-3.5-sonnet'},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()['model'] == 'anthropic/claude-3.5-sonnet'
        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.model == 'anthropic/claude-3.5-sonnet'

    def test_update_session_system_prompt(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'key', 'system_prompt': 'Original.'},
        )
        sid = resp.json()['session_id']
        client.patch(
            f'/api/v1/ai/chat/sessions/{sid}',
            json={'system_prompt': 'Updated prompt.'},
        )
        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.system_prompt == 'Updated prompt.'
        assert live.messages[0] == {'role': 'system', 'content': 'Updated prompt.'}

    def test_update_session_not_found(self, client: TestClient) -> None:
        resp = client.patch(
            '/api/v1/ai/chat/sessions/nonexistent',
            json={'model': 'new-model'},
        )
        assert resp.status_code == 404

    def test_history_empty_for_new_session(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']
        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 200
        data = hist.json()
        assert data['session_id'] == sid
        assert data['history'] == []

    def test_history_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.get('/api/v1/ai/chat/history/nonexistent')
        assert resp.status_code == 404

    def test_send_message_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/message',
            json={'session_id': 'nonexistent', 'content': 'hello'},
        )
        assert resp.status_code == 404

    def test_stream_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.get('/api/v1/ai/chat/stream/nonexistent')
        assert resp.status_code == 404

    def test_delete_session_returns_closed(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']
        del_resp = client.delete(f'/api/v1/ai/chat/sessions/{sid}')
        assert del_resp.status_code == 200
        data = del_resp.json()
        assert data['status'] == 'closed'
        assert data['session_id'] == sid

    def test_delete_session_removes_from_store(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']
        client.delete(f'/api/v1/ai/chat/sessions/{sid}')
        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 404

    def test_delete_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.delete('/api/v1/ai/chat/sessions/nonexistent')
        assert resp.status_code == 404

    def test_send_message_triggers_agent_task(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        mock_response = {
            'choices': [
                {
                    'message': {'content': 'Hello!', 'tool_calls': None},
                    'finish_reason': 'stop',
                },
            ],
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            send_resp = client.post(
                '/api/v1/ai/chat/message',
                json={'session_id': sid, 'content': 'hi'},
            )
        assert send_resp.status_code == 200
        assert send_resp.json()['status'] == 'processing'

    async def test_send_message_busy_returns_409(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        await live.set_busy(True)

        send_resp = client.post(
            '/api/v1/ai/chat/message',
            json={'session_id': sid, 'content': 'hi'},
        )
        assert send_resp.status_code == 409

    async def test_history_contains_events_after_turn(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        mock_response = {
            'choices': [
                {
                    'message': {'content': 'Hello!', 'tool_calls': None},
                    'finish_reason': 'stop',
                },
            ],
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hi'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 200
        events = hist.json()['history']
        user_events = [e for e in events if e.get('role') == 'user']
        assert len(user_events) >= 1

    async def test_history_persists_across_multiple_turns(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        mock_response = {
            'choices': [
                {
                    'message': {'content': 'Reply', 'tool_calls': None},
                    'finish_reason': 'stop',
                },
            ],
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'first'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'second'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 2)

        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        events = hist.json()['history']
        user_events = [e for e in events if e.get('role') == 'user']
        assert len(user_events) >= 2

    async def test_history_contains_usage_event(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        mock_response = {
            'choices': [
                {
                    'message': {'content': 'Hi!', 'tool_calls': None},
                    'finish_reason': 'stop',
                },
            ],
            'usage': {
                'prompt_tokens': 10,
                'completion_tokens': 5,
                'total_tokens': 15,
            },
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hello'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 200
        events = hist.json()['history']
        usage_events = [e for e in events if e.get('type') == 'usage']
        assert len(usage_events) == 1
        assert usage_events[0]['prompt_tokens'] == 10
        assert usage_events[0]['completion_tokens'] == 5
        assert usage_events[0]['total_tokens'] == 15


class TestModelsRoute:
    def test_models_with_provided_key(self, client: TestClient) -> None:
        mock_models = [{'id': 'openai/gpt-4o', 'name': 'GPT-4o'}]
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)):
            resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter', 'api_key': 'sk-test'})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]['id'] == 'openai/gpt-4o'
        assert data[0]['name'] == 'GPT-4o'

    def test_models_requires_provider(self, client: TestClient) -> None:
        resp = client.post('/api/v1/ai/chat/models', json={'api_key': 'sk-test'})
        assert resp.status_code == 422

    def test_models_returns_400_when_no_key(self, client: TestClient) -> None:
        resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter'})
        assert resp.status_code == 400
        assert 'API key is required' in resp.json()['detail']

    def test_models_returns_empty_list(self, client: TestClient) -> None:
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=[])):
            resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter', 'api_key': 'sk-test'})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_models_uses_provided_key(self, client: TestClient) -> None:
        mock_models = [{'id': 'model/a', 'name': 'A'}]
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)) as mock_list:
            resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter', 'api_key': 'sk-session'})
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with('sk-session')

    def test_models_route_requires_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from main import app
        from modules.auth.dependencies import get_current_user

        monkeypatch.setattr('core.config.settings.auth_required', True)
        app.dependency_overrides.pop(get_current_user, None)
        resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter', 'api_key': 'sk-test'})
        assert resp.status_code == 401


class TestToolContextForwarding:
    @pytest.mark.asyncio
    async def test_call_tool_forwards_session_and_namespace_headers(self) -> None:
        from fastapi import FastAPI, Header

        from modules.mcp.executor import build_tool_context, call_tool

        app = FastAPI()

        @app.get('/api/v1/test/auth')
        async def auth_headers(
            x_session_token: str | None = Header(default=None),
            x_namespace: str | None = Header(default=None),
        ) -> dict[str, str | None]:
            return {'token': x_session_token, 'namespace': x_namespace or 'default'}

        context = build_tool_context({'X-Session-Token': 'sess-123', 'X-Namespace': 'team-a'})
        result = await call_tool(app, 'GET', '/api/v1/test/auth', {}, context)
        assert result['status'] == 200
        assert result['body'] == {'token': 'sess-123', 'namespace': 'team-a'}


SAMPLE_REGISTRY = [
    {
        'id': 'get_config',
        'method': 'GET',
        'path': '/api/v1/config',
        'safety': 'safe',
        'tags': ['config'],
        'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'id': 'get_datasources',
        'method': 'GET',
        'path': '/api/v1/datasource',
        'safety': 'safe',
        'tags': ['datasource'],
        'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'id': 'post_datasource',
        'method': 'POST',
        'path': '/api/v1/datasource',
        'safety': 'mutating',
        'tags': ['datasource'],
        'input_schema': {'type': 'object', 'properties': {'payload': {'type': 'object'}}, 'additionalProperties': False},
    },
]

STOP_RESPONSE = {
    'choices': [{'message': {'content': 'Done', 'tool_calls': None}, 'finish_reason': 'stop'}],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}


class TestToolIdFiltering:
    def test_send_message_passes_tool_ids_to_agent(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        captured_tools: list[list[dict]] = []
        original_mock = AsyncMock(return_value=STOP_RESPONSE)

        async def capture_tools(api_key, model, messages, tools):
            captured_tools.append(tools)
            return await original_mock(api_key, model, messages, tools)

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=capture_tools),
            patch('modules.mcp.routes.get_registry', return_value=SAMPLE_REGISTRY),
        ):
            send_resp = client.post(
                '/api/v1/ai/chat/message',
                json={'session_id': sid, 'content': 'hi', 'tool_ids': ['get_config']},
            )
            _wait_for_history(sid, lambda history: _done_count(history) >= 1)

        assert send_resp.status_code == 200
        assert len(captured_tools) == 1
        tool_ids_passed = [t['id'] for t in captured_tools[0]]
        assert tool_ids_passed == ['get_config']

    def test_send_message_without_tool_ids_sends_all(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        captured_tools: list[list[dict]] = []
        original_mock = AsyncMock(return_value=STOP_RESPONSE)

        async def capture_tools(api_key, model, messages, tools):
            captured_tools.append(tools)
            return await original_mock(api_key, model, messages, tools)

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=capture_tools),
            patch('modules.mcp.routes.get_registry', return_value=SAMPLE_REGISTRY),
        ):
            send_resp = client.post(
                '/api/v1/ai/chat/message',
                json={'session_id': sid, 'content': 'hi'},
            )
            _wait_for_history(sid, lambda history: _done_count(history) >= 1)

        assert send_resp.status_code == 200
        assert len(captured_tools) == 1
        tool_ids_passed = {t['id'] for t in captured_tools[0]}
        assert tool_ids_passed == {'get_config', 'get_datasources', 'post_datasource'}

    def test_send_message_with_empty_tool_ids_sends_all(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        captured_tools: list[list[dict]] = []
        original_mock = AsyncMock(return_value=STOP_RESPONSE)

        async def capture_tools(api_key, model, messages, tools):
            captured_tools.append(tools)
            return await original_mock(api_key, model, messages, tools)

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=capture_tools),
            patch('modules.mcp.routes.get_registry', return_value=SAMPLE_REGISTRY),
        ):
            send_resp = client.post(
                '/api/v1/ai/chat/message',
                json={'session_id': sid, 'content': 'hi', 'tool_ids': []},
            )
            _wait_for_history(sid, lambda history: _done_count(history) >= 1)

        assert send_resp.status_code == 200
        assert len(captured_tools) == 1
        tool_ids_passed = {t['id'] for t in captured_tools[0]}
        assert tool_ids_passed == {'get_config', 'get_datasources', 'post_datasource'}

    def test_send_message_filters_multiple_tool_ids(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        captured_tools: list[list[dict]] = []
        original_mock = AsyncMock(return_value=STOP_RESPONSE)

        async def capture_tools(api_key, model, messages, tools):
            captured_tools.append(tools)
            return await original_mock(api_key, model, messages, tools)

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=capture_tools),
            patch('modules.mcp.routes.get_registry', return_value=SAMPLE_REGISTRY),
        ):
            send_resp = client.post(
                '/api/v1/ai/chat/message',
                json={'session_id': sid, 'content': 'hi', 'tool_ids': ['get_config', 'post_datasource']},
            )
            _wait_for_history(sid, lambda history: _done_count(history) >= 1)

        assert send_resp.status_code == 200
        assert len(captured_tools) == 1
        tool_ids_passed = {t['id'] for t in captured_tools[0]}
        assert tool_ids_passed == {'get_config', 'post_datasource'}


VALIDATION_REGISTRY = [
    {
        'id': 'safe_tool',
        'method': 'GET',
        'path': '/api/v1/config',
        'safety': 'safe',
        'tags': ['config'],
        'confirm_required': False,
        'input_schema': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'id': 'mutating_tool_with_required',
        'method': 'POST',
        'path': '/api/v1/datasource',
        'safety': 'mutating',
        'tags': ['datasource'],
        'confirm_required': False,
        'input_schema': {
            'type': 'object',
            'properties': {'payload': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}},
            'required': ['payload'],
        },
    },
]

TOOL_CALL_RESPONSE_INVALID = {
    'choices': [
        {
            'message': {
                'content': None,
                'tool_calls': [{'id': 'tc1', 'function': {'name': 'mutating_tool_with_required', 'arguments': json.dumps({})}}],
            },
            'finish_reason': 'tool_calls',
        },
    ],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}

TOOL_CALL_RESPONSE_VALID = {
    'choices': [
        {
            'message': {
                'content': None,
                'tool_calls': [{'id': 'tc2', 'function': {'name': 'safe_tool', 'arguments': json.dumps({})}}],
            },
            'finish_reason': 'tool_calls',
        },
    ],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}


class TestToolValidationInChat:
    async def test_invalid_tool_call_emits_tool_error_event(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return TOOL_CALL_RESPONSE_INVALID
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=VALIDATION_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        error_events = [e for e in history if e.get('type') == 'tool_error']
        assert len(error_events) == 1
        assert error_events[0]['tool_id'] == 'mutating_tool_with_required'

    async def test_invalid_tool_call_does_not_create_pending(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return TOOL_CALL_RESPONSE_INVALID
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=VALIDATION_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        pending_events = [e for e in history if e.get('type') == 'pending']
        assert len(pending_events) == 0

    async def test_valid_safe_tool_auto_executes(self, client: TestClient) -> None:
        """Tools are auto-executed during the agent turn and emit tool_result events."""
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return TOOL_CALL_RESPONSE_VALID
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=VALIDATION_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        result_events = [e for e in history if e.get('type') == 'tool_result']
        assert len(result_events) == 1
        assert result_events[0]['tool_id'] == 'safe_tool'


UNSUPPORTED_SCHEMA_REGISTRY = [
    {
        'id': 'tool_with_bad_schema',
        'method': 'POST',
        'path': '/api/v1/datasource',
        'safety': 'mutating',
        'tags': ['datasource'],
        'confirm_required': False,
        'input_schema': {'type': 'object', 'x-unsupported-extension': True},
    },
]

TOOL_CALL_UNSUPPORTED = {
    'choices': [
        {
            'message': {
                'content': None,
                'tool_calls': [{'id': 'tc3', 'function': {'name': 'tool_with_bad_schema', 'arguments': json.dumps({})}}],
            },
            'finish_reason': 'tool_calls',
        },
    ],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}


class TestUnsupportedSchemaInChat:
    async def test_unsupported_schema_auto_executes(self, client: TestClient) -> None:
        """Unsupported schema extensions are ignored by validate_args, so tools
        with extra schema keywords pass validation and are auto-executed.
        """
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return TOOL_CALL_UNSUPPORTED
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=UNSUPPORTED_SCHEMA_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        result_events = [e for e in history if e.get('type') == 'tool_result']
        assert len(result_events) == 1
        assert result_events[0]['tool_id'] == 'tool_with_bad_schema'

    async def test_unsupported_schema_does_not_emit_tool_error(self, client: TestClient) -> None:
        """Unsupported schema extensions don't trigger validation errors."""
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return TOOL_CALL_UNSUPPORTED
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=UNSUPPORTED_SCHEMA_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        error_events = [e for e in history if e.get('type') == 'tool_error']
        assert len(error_events) == 0


class TestProductionHardening:
    """Tests for the 7 production-hardening fixes."""

    def test_truncation_preserves_system_message(self) -> None:
        """System message at index 0 survives truncation."""
        row = ChatSession(id='sid', provider='openrouter', model='m', api_key='k')
        s = LiveSession(row)
        s.add_message('system', 'You are helpful.')
        for i in range(120):
            s.add_message('user', f'msg-{i}')
        assert len(s.messages) == 100
        assert s.messages[0] == {'role': 'system', 'content': 'You are helpful.'}
        assert s.messages[1]['role'] == 'user'

    async def test_acquire_turn_is_atomic(self) -> None:
        """Two concurrent acquire_turn calls — exactly one wins."""
        row = ChatSession(id='sid', provider='openrouter', model='m', api_key='k')
        s = LiveSession(row)
        results = await asyncio.gather(s.acquire_turn(), s.acquire_turn())
        assert sorted(results) == [False, True]
        assert s.busy is True

    async def test_openrouter_error_pushes_error_event(self, client: TestClient) -> None:
        """OpenRouterError during agent turn emits error+done events and clears busy."""
        from modules.chat.openrouter import OpenRouterError

        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        async def mock_chat(*_args, **_kwargs):
            raise OpenRouterError('rate limited')

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=SAMPLE_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hi'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.busy is False
        history = live.get_history()
        error_events = [e for e in history if e.get('type') == 'error']
        assert any('AI provider error' in e.get('content', '') for e in error_events)
        done_events = [e for e in history if e.get('type') == 'done']
        assert len(done_events) >= 1

    async def test_timeout_pushes_error_event(self, client: TestClient) -> None:
        """httpx.ReadTimeout during agent turn emits error+done events."""
        import httpx

        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        async def mock_chat(*_args, **_kwargs):
            raise httpx.ReadTimeout('timed out')

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=SAMPLE_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hi'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.busy is False
        history = live.get_history()
        error_events = [e for e in history if e.get('type') == 'error']
        assert any('timed out' in e.get('content', '') for e in error_events)

    async def test_unexpected_error_pushes_error_event(self, client: TestClient) -> None:
        """Unexpected RuntimeError during agent turn emits error+done events."""
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        async def mock_chat(*_args, **_kwargs):
            raise RuntimeError('kaboom')

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=SAMPLE_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hi'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.busy is False
        history = live.get_history()
        error_events = [e for e in history if e.get('type') == 'error']
        assert any('RuntimeError' in e.get('content', '') for e in error_events)

    def test_models_raises_on_api_error(self, client: TestClient) -> None:
        """list_models raising OpenRouterError returns 502."""
        from modules.chat.openrouter import OpenRouterError

        with patch('modules.chat.routes.list_models', new=AsyncMock(side_effect=OpenRouterError('bad gateway'))):
            resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter', 'api_key': 'sk-test'})
        assert resp.status_code == 502
        assert 'bad gateway' in resp.json()['detail']

    def test_reopen_stream_preserves_queued_events(self) -> None:
        """Events queued before reopen_stream are not lost."""
        row = ChatSession(id='sid', provider='openrouter', model='m', api_key='k')
        s = LiveSession(row)
        s.push_event({'type': 'message', 'content': 'preserved'})
        s.reopen_stream()
        assert not s._queue.empty()
        event = s._queue.get_nowait()
        assert event is not None
        assert event['content'] == 'preserved'


class TestTextToolCallParsing:
    """Tests for _parse_text_tool_calls handling malformed model output."""

    def test_parses_well_formed_array(self) -> None:
        from modules.chat.routes import _parse_text_tool_calls

        content = 'TOOLCALL>[{"name": "get_config", "arguments": {}}]'
        cleaned, calls = _parse_text_tool_calls(content)
        assert cleaned == ''
        assert len(calls) == 1


class TestToolSystemMessage:
    def test_tool_system_message_includes_argument_guidance_and_metadata(self) -> None:
        from modules.chat.routes import _build_tool_system_message

        tools = [
            {
                'id': 'get_item',
                'method': 'GET',
                'path': '/api/v1/items/{item_id}',
                'description': 'Fetch item',
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'item_id': {'type': 'string', 'description': 'Item id'},
                        'mode': {'type': 'string', 'enum': ['full', 'summary'], 'default': 'summary'},
                    },
                    'required': ['item_id'],
                    'additionalProperties': False,
                },
                'arg_metadata': {
                    'path': [
                        {
                            'name': 'item_id',
                            'required': True,
                            'description': 'Path id',
                            'schema': {'type': 'string'},
                        },
                    ],
                    'query': [
                        {
                            'name': 'mode',
                            'required': False,
                            'description': 'Response mode',
                            'schema': {'type': 'string', 'enum': ['full', 'summary'], 'default': 'summary'},
                        },
                    ],
                    'payload': None,
                },
            },
            {
                'id': 'post_item',
                'method': 'POST',
                'path': '/api/v1/items',
                'description': 'Create item',
                'input_schema': {
                    'type': 'object',
                    'properties': {'payload': {'type': 'object'}},
                    'required': ['payload'],
                    'additionalProperties': False,
                },
                'arg_metadata': {
                    'path': [],
                    'query': [],
                    'payload': {'required': True, 'content_type': 'application/json', 'description': 'Create payload'},
                },
            },
        ]

        msg = _build_tool_system_message(tools)
        assert 'Path parameters: provide them as top-level arguments by exact name' in msg
        assert 'Query parameters: provide as top-level arguments' in msg
        assert 'Request body: always pass JSON body as `payload`' in msg
        assert 'Never send unknown arguments' in msg
        assert '- item_id (path, string, required)' in msg
        assert '- mode (query, string, optional)' in msg
        assert 'enum: ["full", "summary"]' in msg
        assert 'default: "summary"' in msg
        assert '- payload (body, object, required)' in msg
        assert 'content_type: application/json' in msg

    def test_tool_system_message_falls_back_when_arg_metadata_missing(self) -> None:
        from modules.chat.routes import _build_tool_system_message

        tools = [
            {
                'id': 'fallback_tool',
                'method': 'GET',
                'path': '/api/v1/fallback',
                'description': 'Fallback metadata test',
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'q': {'type': 'string', 'description': 'Query text', 'default': 'x'},
                        'mode': {'type': 'string', 'enum': ['a', 'b']},
                    },
                    'required': ['q'],
                    'additionalProperties': False,
                },
                'arg_metadata': None,
            },
        ]

        msg = _build_tool_system_message(tools)
        assert '- q (arg, string, required)' in msg
        assert '- mode (arg, string, optional)' in msg
        assert 'description: Query text' in msg
        assert 'default: "x"' in msg
        assert 'enum: ["a", "b"]' in msg

    def test_tool_system_message_includes_expected_output_summary(self) -> None:
        from modules.chat.routes import _build_tool_system_message

        tools = [
            {
                'id': 'get_item',
                'method': 'GET',
                'path': '/api/v1/items/{item_id}',
                'description': 'Fetch item',
                'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                'arg_metadata': {'path': [], 'query': [], 'payload': None},
                'output_schema': {
                    'status_code': '200',
                    'content_type': 'application/json',
                    'response_model': 'ItemResponse',
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'string'},
                            'name': {'type': 'string'},
                            'created_at': {'type': 'string'},
                        },
                    },
                },
            },
        ]

        msg = _build_tool_system_message(tools)
        assert 'Expected output:' in msg
        assert 'status 200' in msg
        assert 'application/json' in msg
        assert 'model ItemResponse' in msg
        assert 'fields: id, name, created_at' in msg

    def test_tool_system_message_is_coherent_with_real_registry(self, client: TestClient) -> None:
        from fastapi import FastAPI

        from modules.chat.routes import _build_tool_system_message
        from modules.mcp.routes import get_registry

        assert isinstance(client.app, FastAPI)
        tools = get_registry(client.app)
        assert len(tools) > 0
        msg = _build_tool_system_message(tools)

        assert 'CRITICAL RULES:' in msg
        assert 'NEVER fabricate or guess tool results' in msg
        assert 'Path parameters: provide them as top-level arguments by exact name' in msg
        assert 'Query parameters: provide as top-level arguments' in msg
        assert 'Request body: always pass JSON body as `payload`' in msg
        assert 'Never send unknown arguments; only use documented parameters.' in msg

        for tool in tools:
            assert f'- {tool["id"]} [{tool["method"]}]:' in msg

        headers = re.findall(r'^- .+ \[[A-Z]+\]:', msg, flags=re.MULTILINE)
        assert len(headers) == len(tools)

        path_tool = next((t for t in tools if (t.get('arg_metadata', {}).get('path') or [])), None)
        assert path_tool is not None
        first_path = path_tool['arg_metadata']['path'][0]
        assert f'- {path_tool["id"]} [{path_tool["method"]}]' in msg
        assert f'- {first_path["name"]} (path,' in msg

        query_tool = next((t for t in tools if (t.get('arg_metadata', {}).get('query') or [])), None)
        if query_tool is not None:
            first_query = query_tool['arg_metadata']['query'][0]
            assert f'- {query_tool["id"]} [{query_tool["method"]}]' in msg
            assert f'- {first_query["name"]} (query,' in msg

        payload_tool = next((t for t in tools if t.get('arg_metadata', {}).get('payload') is not None), None)
        assert payload_tool is not None
        content_type = payload_tool['arg_metadata']['payload']['content_type']
        assert f'- {payload_tool["id"]} [{payload_tool["method"]}]' in msg
        assert '- payload (body,' in msg
        assert f'content_type: {content_type}' in msg

    def test_parses_single_object(self) -> None:
        from modules.chat.routes import _parse_text_tool_calls

        content = 'Some text TOOLCALL>{"name": "get_config", "arguments": {"id": "abc"}}'
        cleaned, calls = _parse_text_tool_calls(content)
        assert 'TOOLCALL' not in cleaned
        assert len(calls) == 1
        assert calls[0]['function']['name'] == 'get_config'

    def test_handles_trailing_garbage(self) -> None:
        from modules.chat.routes import _parse_text_tool_calls

        content = 'TOOLCALL>[{"name": "my_tool", "arguments": {"x": 1}}]CALL>extra garbage'
        cleaned, calls = _parse_text_tool_calls(content)
        assert len(calls) == 1
        assert calls[0]['function']['name'] == 'my_tool'

    def test_handles_completely_malformed(self) -> None:
        from modules.chat.routes import _parse_text_tool_calls

        content = 'TOOLCALL>[not valid json at all'
        cleaned, calls = _parse_text_tool_calls(content)
        assert calls == []

    def test_no_toolcall_returns_original(self) -> None:
        from modules.chat.routes import _parse_text_tool_calls

        content = 'Just a normal message'
        cleaned, calls = _parse_text_tool_calls(content)
        assert cleaned == content
        assert calls == []

    def test_preserves_text_before_toolcall(self) -> None:
        from modules.chat.routes import _parse_text_tool_calls

        content = 'I will call the tool now.\nTOOLCALL>[{"name": "test", "arguments": {}}]'
        cleaned, calls = _parse_text_tool_calls(content)
        assert cleaned == 'I will call the tool now.'
        assert len(calls) == 1


class TestOpenRouterToolMapping:
    def test_mcp_tool_to_openai_appends_expected_output_hint(self) -> None:
        from modules.chat.openrouter import _mcp_tool_to_openai

        tool = {
            'id': 'get_item',
            'description': 'Fetch item',
            'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            'output_schema': {
                'status_code': '200',
                'content_type': 'application/json',
                'response_model': 'ItemResponse',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'string'},
                        'name': {'type': 'string'},
                        'created_at': {'type': 'string'},
                    },
                },
            },
        }

        mapped = _mcp_tool_to_openai(tool)
        desc = mapped['function']['description']
        assert 'Fetch item' in desc
        assert 'Expected output:' in desc
        assert 'status 200' in desc
        assert 'application/json' in desc
        assert 'model ItemResponse' in desc
        assert 'fields: id, name, created_at' in desc

    def test_mcp_tool_to_openai_keeps_description_when_no_output_schema(self) -> None:
        from modules.chat.openrouter import _mcp_tool_to_openai

        tool = {
            'id': 'get_item',
            'description': 'Fetch item',
            'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            'output_schema': None,
        }

        mapped = _mcp_tool_to_openai(tool)
        assert mapped['function']['description'] == 'Fetch item'


class TestToolContractFormatting:
    def test_format_output_hint_matches_expected_shape(self) -> None:
        from modules.chat.tool_contract import format_output_hint, top_level_output_fields

        schema = {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'}},
            },
        }
        output = {
            'status_code': '200',
            'content_type': 'application/json',
            'response_model': 'ItemsResponse',
            'schema': schema,
        }

        assert top_level_output_fields(schema) == ['id', 'name']
        assert format_output_hint(output) == 'Expected output: status 200; application/json; model ItemsResponse; fields: id, name'


MALFORMED_ARGS_REGISTRY = [
    {
        'id': 'safe_tool',
        'method': 'GET',
        'path': '/api/v1/config',
        'safety': 'safe',
        'tags': ['config'],
        'confirm_required': False,
        'input_schema': {'type': 'object', 'properties': {}, 'required': []},
    },
]

MALFORMED_ARGS_RESPONSE = {
    'choices': [
        {
            'message': {
                'content': None,
                'tool_calls': [{'id': 'tc1', 'function': {'name': 'safe_tool', 'arguments': '{not valid json}'}}],
            },
            'finish_reason': 'tool_calls',
        },
    ],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}


class TestMalformedToolArgs:
    """Tests that malformed tool call arguments are handled deterministically."""

    async def test_malformed_args_emits_tool_error(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MALFORMED_ARGS_RESPONSE
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=MALFORMED_ARGS_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        error_events = [e for e in history if e.get('type') == 'tool_error']
        assert len(error_events) == 1
        assert error_events[0]['tool_id'] == 'safe_tool'
        assert any('Malformed' in err.get('message', '') for err in error_events[0].get('errors', []))

    async def test_malformed_args_skips_tool_execution(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MALFORMED_ARGS_RESPONSE
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=MALFORMED_ARGS_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        result_events = [e for e in history if e.get('type') == 'tool_result']
        assert len(result_events) == 0

    async def test_events_have_ts_field(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        with (
            patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=STOP_RESPONSE)),
            patch('modules.mcp.routes.get_registry', return_value=MALFORMED_ARGS_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hi'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        assert len(history) > 0
        for event in history:
            assert 'ts' in event, f'Event missing ts: {event}'
            assert isinstance(event['ts'], float)
            assert event['ts'] > 0


class TestBugFixes:
    """Tests for the 8 production bug fixes."""

    def test_append_message_enforces_truncation(self) -> None:
        """append_message helper respects MAX_MESSAGES and preserves system message."""
        row = ChatSession(id='sid', provider='openrouter', model='m', api_key='k')
        s = LiveSession(row)
        s.append_message({'role': 'system', 'content': 'system'})
        for i in range(120):
            s.append_message({'role': 'user', 'content': f'msg-{i}'})
        assert len(s.messages) == 100
        assert s.messages[0] == {'role': 'system', 'content': 'system'}

    def test_assistant_message_omits_tool_calls_key_when_empty(self) -> None:
        """Assistant messages without tool_calls must not include the key."""
        row = ChatSession(id='sid', provider='openrouter', model='m', api_key='k')
        s = LiveSession(row)
        msg: dict = {'role': 'assistant', 'content': 'hello'}
        s.append_message(msg)
        stored = s.messages[-1]
        assert 'tool_calls' not in stored

    async def test_agent_loop_continues_when_finish_stop_but_has_tool_calls(self, client: TestClient) -> None:
        """Agent loop must not break when finish_reason='stop' if tool_calls were present."""
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        call_count = 0

        async def mock_chat(api_key, model, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    'choices': [
                        {
                            'message': {
                                'content': None,
                                'tool_calls': [{'id': 'tc1', 'function': {'name': 'safe_tool', 'arguments': '{}'}}],
                            },
                            'finish_reason': 'stop',
                        },
                    ],
                    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
                }
            return STOP_RESPONSE

        with (
            patch('modules.chat.routes.chat_with_tools', side_effect=mock_chat),
            patch('modules.mcp.routes.get_registry', return_value=VALIDATION_REGISTRY),
        ):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'go'})
            await _wait_for_history_async(sid, lambda history: _done_count(history) >= 1)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        result_events = [e for e in history if e.get('type') == 'tool_result']
        assert len(result_events) >= 1
        assert call_count == 2


class TestInferPatch:
    """Test _infer_patch extracts the correct resource name from API paths."""

    def test_simple_resource_path(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch('post_analysis', 'POST', '/api/v1/analysis', {'ok': True, 'body': {'id': '123'}})
        assert patch is not None
        assert patch['resource'] == 'analysis'
        assert patch['action'] == 'created'
        assert patch['id'] == '123'

    def test_resource_with_id(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch('get_analysis', 'GET', '/api/v1/analysis/abc-123', {'ok': True, 'body': {'id': 'abc-123'}})
        assert patch is not None
        assert patch['resource'] == 'analysis'
        assert patch['action'] == 'refresh'

    def test_nested_resource_path(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch('post_step', 'POST', '/api/v1/analysis/abc/tabs/t1/steps', {'ok': True, 'body': {'id': 's1'}})
        assert patch is not None
        assert patch['resource'] == 'analysis'
        assert patch['action'] == 'created'

    def test_failed_result_returns_none(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch('post_analysis', 'POST', '/api/v1/analysis', {'ok': False, 'status': 422})
        assert patch is None

    def test_datasource_path(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch('delete_ds', 'DELETE', '/api/v1/datasource/xyz', {'ok': True, 'body': None})
        assert patch is not None
        assert patch['resource'] == 'datasource'
        assert patch['action'] == 'deleted'
