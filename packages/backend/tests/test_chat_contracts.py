"""Preserved chat provider, MCP, parsing, and authorization safety contracts."""

import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlmodel import Session

from backend_core.database import get_settings_engine
from backend_core.secrets import encrypt_secret
from modules.chat.models import ChatSession
from tests.http_client import TestClient


class TestModelsRoute:
    def test_models_with_provided_key(self, client: TestClient) -> None:
        mock_models = [{'id': 'openai/gpt-4o', 'name': 'GPT-4o'}]
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)):
            resp = client.post(
                '/api/v1/ai/chat/models',
                json={'provider': 'openrouter', 'api_key': 'sk-test'},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]['id'] == 'openai/gpt-4o'
        assert data[0]['name'] == 'GPT-4o'

    def test_models_requires_provider(self, client: TestClient) -> None:
        resp = client.post('/api/v1/ai/chat/models', json={'api_key': 'sk-test'})
        assert resp.status_code == 422

    def test_models_returns_400_when_no_key(self, client: TestClient) -> None:
        with patch('modules.chat.routes.get_resolved_openrouter_key', return_value=''):
            resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter'})
        assert resp.status_code == 400
        assert 'API key is required' in resp.json()['detail']

    def test_models_uses_resolved_key_when_request_key_is_empty(self, client: TestClient) -> None:
        mock_models = [{'id': 'z-ai/glm-5.3-flash', 'name': 'GLM'}]
        with (
            patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)) as mock_list,
            patch('modules.chat.routes.get_resolved_openrouter_key', return_value='sk-deploy'),
        ):
            resp = client.post('/api/v1/ai/chat/models', json={'provider': 'openrouter', 'api_key': ''})
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with('sk-deploy')

    def test_models_returns_empty_list(self, client: TestClient) -> None:
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=[])):
            resp = client.post(
                '/api/v1/ai/chat/models',
                json={'provider': 'openrouter', 'api_key': 'sk-test'},
            )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_models_uses_provided_key(self, client: TestClient) -> None:
        mock_models = [{'id': 'model/a', 'name': 'A'}]
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)) as mock_list:
            resp = client.post(
                '/api/v1/ai/chat/models',
                json={'provider': 'openrouter', 'api_key': 'sk-session'},
            )
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with('sk-session')

    def test_models_route_requires_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from main import app
        from modules.auth.dependencies import get_current_user

        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        app.dependency_overrides.pop(get_current_user, None)
        resp = client.post(
            '/api/v1/ai/chat/models',
            json={'provider': 'openrouter', 'api_key': 'sk-test'},
        )
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
        'input_schema': {
            'type': 'object',
            'properties': {},
            'additionalProperties': False,
        },
    },
    {
        'id': 'get_datasources',
        'method': 'GET',
        'path': '/api/v1/datasource',
        'safety': 'safe',
        'tags': ['datasource'],
        'input_schema': {
            'type': 'object',
            'properties': {},
            'additionalProperties': False,
        },
    },
    {
        'id': 'post_datasource',
        'method': 'POST',
        'path': '/api/v1/datasource',
        'safety': 'mutating',
        'tags': ['datasource'],
        'input_schema': {
            'type': 'object',
            'properties': {'payload': {'type': 'object'}},
            'additionalProperties': False,
        },
    },
]

STOP_RESPONSE = {
    'choices': [{'message': {'content': 'Done', 'tool_calls': None}, 'finish_reason': 'stop'}],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}


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
                        'mode': {
                            'type': 'string',
                            'enum': ['full', 'summary'],
                            'default': 'summary',
                        },
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
                            'schema': {
                                'type': 'string',
                                'enum': ['full', 'summary'],
                                'default': 'summary',
                            },
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
                    'payload': {
                        'required': True,
                        'content_type': 'application/json',
                        'description': 'Create payload',
                    },
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
                        'q': {
                            'type': 'string',
                            'description': 'Query text',
                            'default': 'x',
                        },
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
                'input_schema': {
                    'type': 'object',
                    'properties': {},
                    'additionalProperties': False,
                },
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

        payload_tool = next(
            (t for t in tools if t.get('arg_metadata', {}).get('payload') is not None),
            None,
        )
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
        from modules.chat.chat_http import _mcp_tool_to_openai

        tool = {
            'id': 'get_item',
            'description': 'Fetch item',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
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
        from modules.chat.chat_http import _mcp_tool_to_openai

        tool = {
            'id': 'get_item',
            'description': 'Fetch item',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
            'output_schema': None,
        }

        mapped = _mcp_tool_to_openai(tool)
        assert mapped['function']['description'] == 'Fetch item'


class TestToolContractFormatting:
    def test_format_output_hint_matches_expected_shape(self) -> None:
        from modules.mcp.tool_output import format_output_hint, top_level_output_fields

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
                'tool_calls': [
                    {
                        'id': 'tc1',
                        'function': {
                            'name': 'safe_tool',
                            'arguments': '{not valid json}',
                        },
                    }
                ],
            },
            'finish_reason': 'tool_calls',
        },
    ],
    'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
}


class TestInferPatch:
    """Test _infer_patch extracts the correct resource name from API paths."""

    def test_simple_resource_path(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch(
            'post_analysis',
            'POST',
            '/api/v1/analysis',
            {'ok': True, 'body': {'id': '123'}},
        )
        assert patch is not None
        assert patch['resource'] == 'analysis'
        assert patch['action'] == 'created'
        assert patch['id'] == '123'

    def test_resource_with_id(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch(
            'get_analysis',
            'GET',
            '/api/v1/analysis/abc-123',
            {'ok': True, 'body': {'id': 'abc-123'}},
        )
        assert patch is not None
        assert patch['resource'] == 'analysis'
        assert patch['action'] == 'refresh'

    def test_nested_resource_path(self) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch(
            'post_step',
            'POST',
            '/api/v1/analysis/abc/tabs/t1/steps',
            {'ok': True, 'body': {'id': 's1'}},
        )
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


class TestProviderResponseValidation:
    @pytest.mark.asyncio
    async def test_chat_with_tools_rejects_non_object_provider_json(self) -> None:
        """OpenRouter chat completions must return a JSON object."""
        from modules.chat.chat_http import ChatHttpError, chat_with_tools

        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=[]))
        async with httpx.AsyncClient(transport=transport) as async_client:
            with patch('modules.chat.chat_http.http_client.get_async_client', return_value=async_client):
                with pytest.raises(ChatHttpError, match='non-object JSON response'):
                    await chat_with_tools('sk-test', 'gpt-test', [{'role': 'user', 'content': 'hello'}], [])

    @pytest.mark.asyncio
    async def test_chat_with_tools_returns_provider_json_object(self) -> None:
        """OpenRouter chat completions preserve valid provider response objects."""
        from modules.chat.chat_http import chat_with_tools

        payload = {'id': 'completion-1', 'choices': [{'message': {'content': 'hello'}}]}
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as async_client:
            with patch('modules.chat.chat_http.http_client.get_async_client', return_value=async_client):
                result = await chat_with_tools('sk-test', 'gpt-test', [{'role': 'user', 'content': 'hello'}], [])

        assert result == payload


class TestSessionOwnership:
    """Per-user chat session isolation."""

    def _create_session(self, client: TestClient) -> str:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'test-key',
            },
        )
        assert resp.status_code == 200
        return resp.json()['session_id']

    def _insert_session_row(self, session_id: str, user_id: str | None) -> None:
        with Session(get_settings_engine()) as db:
            db.add(
                ChatSession(
                    id=session_id,
                    user_id=user_id,
                    provider='openrouter',
                    model='gpt-4o-mini',
                    api_key=encrypt_secret('key'),
                ),
            )
            db.commit()

    def test_create_stamps_current_user_id(self, client: TestClient, test_user) -> None:
        sid = self._create_session(client)
        with Session(get_settings_engine()) as db:
            row = db.get(ChatSession, sid)
            assert row is not None
            assert row.user_id == test_user.id

    def test_owner_can_read_own_session(self, client: TestClient) -> None:
        sid = self._create_session(client)
        resp = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert resp.status_code == 200

    def test_foreign_session_history_returns_404(self, client: TestClient) -> None:
        self._insert_session_row('foreign-sid', 'another-user')
        resp = client.get('/api/v1/ai/chat/history/foreign-sid')
        assert resp.status_code == 404

    def test_foreign_session_update_returns_404(self, client: TestClient) -> None:
        self._insert_session_row('foreign-sid', 'another-user')
        resp = client.patch('/api/v1/ai/chat/sessions/foreign-sid', json={'model': 'new-model'})
        assert resp.status_code == 404

    def test_foreign_session_delete_returns_404(self, client: TestClient) -> None:
        self._insert_session_row('foreign-sid', 'another-user')
        resp = client.delete('/api/v1/ai/chat/sessions/foreign-sid')
        assert resp.status_code == 404
        with Session(get_settings_engine()) as db:
            assert db.get(ChatSession, 'foreign-sid') is not None

    def test_foreign_session_message_returns_404(self, client: TestClient) -> None:
        self._insert_session_row('foreign-sid', 'another-user')
        resp = client.post('/api/v1/ai/chat/message', json={'session_id': 'foreign-sid', 'content': 'hi'})
        assert resp.status_code == 404

    def test_foreign_session_stop_returns_404(self, client: TestClient) -> None:
        self._insert_session_row('foreign-sid', 'another-user')
        resp = client.post('/api/v1/ai/chat/sessions/foreign-sid/stop')
        assert resp.status_code == 404

    def test_list_sessions_scoped_to_owner(self, client: TestClient, test_user) -> None:
        own_sid = self._create_session(client)
        self._insert_session_row('foreign-sid', 'another-user')
        resp = client.get('/api/v1/ai/chat/sessions')
        assert resp.status_code == 200
        ids = {item['id'] for item in resp.json()}
        assert own_sid in ids
        assert 'foreign-sid' not in ids

    def test_legacy_null_owner_session_inaccessible(self, client: TestClient) -> None:
        """Rows predating ownership (user_id NULL) are not exposed to any user."""
        self._insert_session_row('legacy-sid', None)
        resp = client.get('/api/v1/ai/chat/history/legacy-sid')
        assert resp.status_code == 404
        listing = client.get('/api/v1/ai/chat/sessions')
        assert 'legacy-sid' not in {item['id'] for item in listing.json()}

    def test_legacy_null_owner_backfills_to_default_user(self) -> None:
        """Backfilled legacy rows resolve ownership to the default user."""
        from sqlalchemy import text

        from modules.auth.service import get_default_user_id
        from modules.chat.sessions import SessionStore

        with Session(get_settings_engine()) as db:
            db.add(
                ChatSession(
                    id='legacy-sid',
                    user_id=None,
                    provider='openrouter',
                    model='gpt-4o-mini',
                    api_key=encrypt_secret('key'),
                ),
            )
            db.commit()
            db.execute(text('UPDATE chat_sessions SET user_id = :uid WHERE user_id IS NULL'), {'uid': get_default_user_id()})
            db.commit()

        live = SessionStore().get('legacy-sid')
        assert live is not None
        assert live.user_id == get_default_user_id()


class TestSessionEndpoints:
    def test_chat_routes_require_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from main import app
        from modules.auth.dependencies import get_current_user

        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        app.dependency_overrides.pop(get_current_user, None)
        resp = client.get('/api/v1/ai/chat/sessions')
        assert resp.status_code == 401

    def test_create_session(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'test-key',
            },
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
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'key',
                'system_prompt': 'Be brief.',
            },
        )
        assert resp.status_code == 200
        sid = resp.json()['session_id']
        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.system_prompt == 'Be brief.'
        assert session_store.messages(sid)[0] == {'role': 'system', 'content': 'Be brief.'}

    def test_create_session_rejects_unknown_provider(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={
                'provider': 'anthropic',
                'model': 'claude',
                'api_key': 'key',
            },
        )
        assert resp.status_code == 400
        assert 'Unknown AI provider' in resp.json()['detail']

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
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'key',
                'system_prompt': 'Original.',
            },
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
        assert session_store.messages(sid)[0] == {'role': 'system', 'content': 'Original.'}

    def test_update_session_not_found(self, client: TestClient) -> None:
        resp = client.patch(
            '/api/v1/ai/chat/sessions/nonexistent',
            json={'model': 'new-model'},
        )
        assert resp.status_code == 404

    def test_history_empty_for_new_session(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'test-key',
            },
        )
        sid = resp.json()['session_id']
        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 200
        data = hist.json()
        assert data['session_id'] == sid
        assert data['history'] == []

    def test_list_sessions_returns_epoch_milliseconds(self, client: TestClient) -> None:
        resp = client.post(
            '/api/v1/ai/chat/sessions',
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'test-key',
            },
        )
        sid = resp.json()['session_id']

        sessions_resp = client.get('/api/v1/ai/chat/sessions')
        assert sessions_resp.status_code == 200
        session = next(item for item in sessions_resp.json() if item['id'] == sid)
        assert isinstance(session['created_at'], int)
        assert session['created_at'] > 10_000_000_000

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
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'test-key',
            },
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
            json={
                'provider': 'openrouter',
                'model': 'gpt-4o-mini',
                'api_key': 'test-key',
            },
        )
        sid = resp.json()['session_id']
        client.delete(f'/api/v1/ai/chat/sessions/{sid}')
        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 404

    def test_delete_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.delete('/api/v1/ai/chat/sessions/nonexistent')
        assert resp.status_code == 404
