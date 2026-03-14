"""Tests for chat module: sessions, routes, history, streaming."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from modules.chat.sessions import ChatSession, LiveSession, SessionStore


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

    def test_busy_guard(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        assert s.busy is False
        s.set_busy(True)
        assert s.busy is True
        s.set_busy(False)
        assert s.busy is False

    def test_bounded_messages(self) -> None:
        row = ChatSession(id='sid', provider='openrouter', model='gpt-4o-mini', api_key='key')
        s = LiveSession(row)
        for i in range(120):
            s.add_message('user', f'msg-{i}')
        assert len(s.messages) == 100
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

    def test_get_expired_returns_none(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        s.created_at -= SessionStore.TTL + 1
        assert store.get(s.id) is None

    def test_sweep_removes_expired(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        s.created_at -= SessionStore.TTL + 1
        store.sweep()
        assert s.id not in store._live

    def test_delete_removes_session_and_closes_stream(self) -> None:
        store = SessionStore()
        s = store.create('openrouter', 'gpt-4o-mini', 'key')
        result = store.delete(s.id)
        assert result is True
        assert store.get(s.id) is None
        assert s._closed is True

    def test_delete_unknown_returns_false(self) -> None:
        store = SessionStore()
        assert store.delete('nonexistent') is False

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


class TestChatRoutes:
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

    def test_create_session_defaults_provider(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        assert resp.status_code == 200
        assert resp.json()['provider'] == 'openrouter'

    def test_create_session_without_api_key(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'model': 'gpt-4o-mini'},
        )
        assert resp.status_code == 200
        assert 'session_id' in resp.json()

    def test_create_session_with_system_prompt(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'model': 'gpt-4o-mini', 'api_key': 'key', 'system_prompt': 'Be brief.'},
        )
        assert resp.status_code == 200
        sid = resp.json()['session_id']
        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.system_prompt == 'Be brief.'
        assert live.messages[0] == {'role': 'system', 'content': 'Be brief.'}

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

    def test_apply_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/apply',
            json={'session_id': 'nonexistent', 'token': 'tok'},
        )
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
                }
            ]
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            send_resp = client.post(
                '/api/v1/ai/chat/message',
                json={'session_id': sid, 'content': 'hi'},
            )
        assert send_resp.status_code == 200
        assert send_resp.json()['status'] == 'processing'

    def test_send_message_busy_returns_409(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key'},
        )
        sid = resp.json()['session_id']

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        live.set_busy(True)

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
                }
            ]
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hi'})
            await asyncio.sleep(0.05)

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
                }
            ]
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'first'})
            await asyncio.sleep(0.05)
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'second'})
            await asyncio.sleep(0.05)

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
                }
            ],
            'usage': {
                'prompt_tokens': 10,
                'completion_tokens': 5,
                'total_tokens': 15,
            },
        }

        with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(return_value=mock_response)):
            client.post('/api/v1/ai/chat/message', json={'session_id': sid, 'content': 'hello'})
            await asyncio.sleep(0.05)

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
            resp = client.get('/api/v1/ai/chat/models', params={'api_key': 'sk-test'})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]['id'] == 'openai/gpt-4o'
        assert data[0]['name'] == 'GPT-4o'

    def test_models_falls_back_to_global_key(self, client: TestClient) -> None:
        mock_models = [{'id': 'anthropic/claude-3', 'name': 'Claude 3'}]
        with (
            patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)) as mock_list,
            patch('modules.settings.service.get_resolved_openrouter_key', return_value='sk-global'),
        ):
            resp = client.get('/api/v1/ai/chat/models')
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with('sk-global')

    def test_models_returns_400_when_no_key(self, client: TestClient) -> None:
        with patch('modules.settings.service.get_resolved_openrouter_key', return_value=''):
            resp = client.get('/api/v1/ai/chat/models')
        assert resp.status_code == 400
        assert 'No API key' in resp.json()['detail']

    def test_models_returns_empty_list(self, client: TestClient) -> None:
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=[])):
            resp = client.get('/api/v1/ai/chat/models', params={'api_key': 'sk-test'})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_models_prefers_provided_key_over_global(self, client: TestClient) -> None:
        mock_models = [{'id': 'model/a', 'name': 'A'}]
        with (
            patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)) as mock_list,
            patch('modules.settings.service.get_resolved_openrouter_key', return_value='sk-global'),
        ):
            resp = client.get('/api/v1/ai/chat/models', params={'api_key': 'sk-session'})
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with('sk-session')


SAMPLE_REGISTRY = [
    {'id': 'get_config', 'method': 'GET', 'path': '/api/v1/config', 'safety': 'safe', 'tags': ['config']},
    {'id': 'get_datasources', 'method': 'GET', 'path': '/api/v1/datasource', 'safety': 'safe', 'tags': ['datasource']},
    {'id': 'post_datasource', 'method': 'POST', 'path': '/api/v1/datasource', 'safety': 'mutating', 'tags': ['datasource']},
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
            import time

            time.sleep(0.1)

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
            import time

            time.sleep(0.1)

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
            import time

            time.sleep(0.1)

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
            import time

            time.sleep(0.1)

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
        }
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
        }
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
            await asyncio.sleep(0.15)

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
            await asyncio.sleep(0.15)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        pending_events = [e for e in history if e.get('type') == 'pending']
        assert len(pending_events) == 0

    async def test_valid_safe_tool_emits_pending_event(self, client: TestClient) -> None:
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
            await asyncio.sleep(0.15)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        pending_events = [e for e in history if e.get('type') == 'pending']
        assert len(pending_events) == 1
        assert pending_events[0]['tool_id'] == 'safe_tool'

    async def test_valid_safe_tool_does_not_auto_execute(self, client: TestClient) -> None:
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
            await asyncio.sleep(0.15)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        result_events = [e for e in history if e.get('type') == 'tool_result']
        assert len(result_events) == 0


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
        }
    ],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}


class TestUnsupportedSchemaInChat:
    async def test_unsupported_schema_emits_tool_error(self, client: TestClient) -> None:
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
            await asyncio.sleep(0.15)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        error_events = [e for e in history if e.get('type') == 'tool_error']
        assert len(error_events) == 1
        assert error_events[0]['tool_id'] == 'tool_with_bad_schema'
        assert any(e['message'] == 'unsupported schema' for e in error_events[0]['errors'])

    async def test_unsupported_schema_does_not_create_pending(self, client: TestClient) -> None:
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
            await asyncio.sleep(0.15)

        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        history = live.get_history()
        pending_events = [e for e in history if e.get('type') == 'pending']
        assert len(pending_events) == 0
