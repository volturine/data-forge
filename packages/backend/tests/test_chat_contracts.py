"""Preserved chat provider, MCP, parsing, and authorization safety contracts."""

import re
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlmodel import Session

from backend_core.database import get_settings_engine
from backend_core.secrets import encrypt_secret
from modules.chat.models import ChatSession
from modules.mcp.models import MCPHttpMethod, MCPToolDefinition
from tests.http_client import TestClient


def _mcp_tool(
    tool_id: str,
    method: MCPHttpMethod,
    path: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    arg_metadata: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> MCPToolDefinition:
    return MCPToolDefinition(
        id=tool_id,
        method=method,
        path=path,
        description=description,
        input_schema=input_schema,
        arg_metadata=arg_metadata or {},
        output_schema=output_schema,
    )


def _create_session(client: TestClient, **fields: str) -> str:
    response = client.post(
        '/api/v1/ai/chat/sessions',
        json={'provider': 'openrouter', 'model': 'gpt-4o-mini', 'api_key': 'test-key', **fields},
    )
    assert response.status_code == 200
    return response.json()['session_id']


class TestModelsRoute:
    def test_models_with_provided_key(self, client: TestClient) -> None:
        mock_models = [{'id': 'openai/gpt-4o', 'name': 'GPT-4o'}]
        with patch('modules.chat.routes.list_models', new=AsyncMock(return_value=mock_models)) as mock_list:
            resp = client.post(
                '/api/v1/ai/chat/models',
                json={'provider': 'openrouter', 'api_key': 'sk-test'},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]['id'] == 'openai/gpt-4o'
        assert data[0]['name'] == 'GPT-4o'
        mock_list.assert_awaited_once_with('sk-test')

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

    def test_models_route_requires_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend_core.application import app
        from modules.auth.dependencies import get_current_user

        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        app.dependency_overrides.pop(get_current_user, None)
        resp = client.post(
            '/api/v1/ai/chat/models',
            json={'provider': 'openrouter', 'api_key': 'sk-test'},
        )
        assert resp.status_code == 401


class TestTextToolCallParsing:
    """Tests for _parse_text_tool_calls handling malformed model output."""

    @pytest.mark.parametrize(
        ('content', 'expected_cleaned', 'expected_names'),
        [
            pytest.param('TOOLCALL>[{"name": "get_config", "arguments": {}}]', '', ['get_config'], id='well-formed-array'),
            pytest.param('Some text TOOLCALL>{"name": "get_config", "arguments": {"id": "abc"}}', 'Some text', ['get_config'], id='single-object'),
            pytest.param('TOOLCALL>[{"name": "my_tool", "arguments": {"x": 1}}]CALL>extra garbage', '', ['my_tool'], id='trailing-garbage'),
            pytest.param('TOOLCALL>[not valid json at all', 'TOOLCALL>[not valid json at all', [], id='completely-malformed'),
            pytest.param('Just a normal message', 'Just a normal message', [], id='no-tool-call'),
            pytest.param(
                'I will call the tool now.\nTOOLCALL>[{"name": "test", "arguments": {}}]',
                'I will call the tool now.',
                ['test'],
                id='text-before-tool-call',
            ),
        ],
    )
    def test_parses_text_tool_calls(self, content: str, expected_cleaned: str, expected_names: list[str]) -> None:
        from modules.chat.routes import _parse_text_tool_calls

        cleaned, calls = _parse_text_tool_calls(content)
        assert cleaned == expected_cleaned
        assert [call['function']['name'] for call in calls] == expected_names


class TestToolSystemMessage:
    def test_tool_system_message_includes_argument_guidance_and_metadata(self) -> None:
        from modules.chat.routes import _build_tool_system_message

        tools = [
            _mcp_tool(
                'get_item',
                MCPHttpMethod.GET,
                '/api/v1/items/{item_id}',
                'Fetch item',
                {
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
                arg_metadata={
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
            ),
            _mcp_tool(
                'post_item',
                MCPHttpMethod.POST,
                '/api/v1/items',
                'Create item',
                {
                    'type': 'object',
                    'properties': {'payload': {'type': 'object'}},
                    'required': ['payload'],
                    'additionalProperties': False,
                },
                arg_metadata={
                    'path': [],
                    'query': [],
                    'payload': {
                        'required': True,
                        'content_type': 'application/json',
                        'description': 'Create payload',
                    },
                },
            ),
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
            _mcp_tool(
                'fallback_tool',
                MCPHttpMethod.GET,
                '/api/v1/fallback',
                'Fallback metadata test',
                {
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
            ),
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
            _mcp_tool(
                'get_item',
                MCPHttpMethod.GET,
                '/api/v1/items/{item_id}',
                'Fetch item',
                {
                    'type': 'object',
                    'properties': {},
                    'additionalProperties': False,
                },
                arg_metadata={'path': [], 'query': [], 'payload': None},
                output_schema={
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
            ),
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
            assert f'- {tool.id} [{tool.method.value}]:' in msg

        headers = re.findall(r'^- .+ \[[A-Z]+\]:', msg, flags=re.MULTILINE)
        assert len(headers) == len(tools)

        path_tool = next((t for t in tools if (t.arg_metadata.get('path') or [])), None)
        assert path_tool is not None
        first_path = path_tool.arg_metadata['path'][0]
        assert f'- {path_tool.id} [{path_tool.method.value}]' in msg
        assert f'- {first_path["name"]} (path,' in msg

        query_tool = next((t for t in tools if (t.arg_metadata.get('query') or [])), None)
        if query_tool is not None:
            first_query = query_tool.arg_metadata['query'][0]
            assert f'- {query_tool.id} [{query_tool.method.value}]' in msg
            assert f'- {first_query["name"]} (query,' in msg

        payload_tool = next(
            (t for t in tools if t.arg_metadata.get('payload') is not None),
            None,
        )
        assert payload_tool is not None
        content_type = payload_tool.arg_metadata['payload']['content_type']
        assert f'- {payload_tool.id} [{payload_tool.method.value}]' in msg
        assert '- payload (body,' in msg
        assert f'content_type: {content_type}' in msg


class TestOpenRouterToolMapping:
    def test_mcp_tool_to_openai_appends_expected_output_hint(self) -> None:

        tool = _mcp_tool(
            'get_item',
            MCPHttpMethod.GET,
            '/api/v1/items',
            'Fetch item',
            {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
            output_schema={
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
        )

        mapped = tool.openai_tool()
        desc = mapped['function']['description']
        assert 'Fetch item' in desc
        assert 'Expected output:' in desc
        assert 'status 200' in desc
        assert 'application/json' in desc
        assert 'model ItemResponse' in desc
        assert 'fields: id, name, created_at' in desc

    def test_mcp_tool_to_openai_keeps_description_when_no_output_schema(self) -> None:

        tool = _mcp_tool(
            'get_item',
            MCPHttpMethod.GET,
            '/api/v1/items',
            'Fetch item',
            {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
        )

        mapped = tool.openai_tool()
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


class TestInferPatch:
    """Test _infer_patch extracts the correct resource name from API paths."""

    @pytest.mark.parametrize(
        ('method', 'path', 'body', 'expected'),
        [
            pytest.param('POST', '/api/v1/analysis', {'id': '123'}, {'resource': 'analysis', 'action': 'created', 'id': '123'}, id='create-root-resource'),
            pytest.param('GET', '/api/v1/analysis/abc-123', {'id': 'abc-123'}, {'resource': 'analysis', 'action': 'refresh'}, id='refresh-resource-with-id'),
            pytest.param(
                'POST', '/api/v1/analysis/abc/tabs/t1/steps', {'id': 's1'}, {'resource': 'analysis', 'action': 'created'}, id='create-nested-resource'
            ),
            pytest.param('DELETE', '/api/v1/datasource/xyz', None, {'resource': 'datasource', 'action': 'deleted'}, id='delete-datasource'),
        ],
    )
    def test_infers_resource_and_action(self, method: str, path: str, body: dict | None, expected: dict) -> None:
        from modules.chat.routes import _infer_patch

        patch = _infer_patch(method, path, {'ok': True, 'body': body})
        assert patch is not None
        for key, value in expected.items():
            assert patch[key] == value

    def test_failed_result_returns_none(self) -> None:
        from modules.chat.routes import _infer_patch

        assert _infer_patch('POST', '/api/v1/analysis', {'ok': False, 'status': 422}) is None


class TestProviderResponseValidation:
    @pytest.mark.asyncio
    async def test_chat_with_tools_rejects_non_object_provider_json(self) -> None:
        """OpenRouter chat completions must return a JSON object."""
        from modules.chat.chat_http import ChatHttpError, chat_with_tools

        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=[]))
        async with httpx.AsyncClient(transport=transport) as async_client:
            with (
                patch('modules.chat.chat_http.http_client.get_async_client', return_value=async_client),
                pytest.raises(ChatHttpError, match='non-object JSON response'),
            ):
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
        sid = _create_session(client)
        with Session(get_settings_engine()) as db:
            row = db.get(ChatSession, sid)
            assert row is not None
            assert row.user_id == test_user.id

    @pytest.mark.parametrize(
        ('method', 'url', 'body'),
        [
            pytest.param('GET', '/api/v1/ai/chat/history/foreign-sid', None, id='history'),
            pytest.param('PATCH', '/api/v1/ai/chat/sessions/foreign-sid', {'model': 'new-model'}, id='update'),
            pytest.param('DELETE', '/api/v1/ai/chat/sessions/foreign-sid', None, id='delete'),
            pytest.param('POST', '/api/v1/ai/chat/message', {'session_id': 'foreign-sid', 'content': 'hi'}, id='message'),
            pytest.param('POST', '/api/v1/ai/chat/sessions/foreign-sid/stop', None, id='stop'),
        ],
    )
    def test_foreign_session_returns_404_and_is_not_removed(self, client: TestClient, method: str, url: str, body: dict | None) -> None:
        self._insert_session_row('foreign-sid', 'another-user')
        resp = client.request(method, url, json=body)
        assert resp.status_code == 404
        with Session(get_settings_engine()) as db:
            assert db.get(ChatSession, 'foreign-sid') is not None

    def test_list_sessions_scoped_to_owner(self, client: TestClient, test_user) -> None:
        own_sid = _create_session(client)
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

        self._insert_session_row('legacy-sid', None)
        with Session(get_settings_engine()) as db:
            db.execute(text('UPDATE chat_sessions SET user_id = :uid WHERE user_id IS NULL'), {'uid': get_default_user_id()})
            db.commit()

        live = SessionStore().get('legacy-sid')
        assert live is not None
        assert live.user_id == get_default_user_id()


class TestSessionEndpoints:
    def test_chat_routes_require_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend_core.application import app
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
        sid = _create_session(client)
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
        sid = _create_session(client, system_prompt='Original.')
        client.patch(
            f'/api/v1/ai/chat/sessions/{sid}',
            json={'system_prompt': 'Updated prompt.'},
        )
        from modules.chat.sessions import session_store

        live = session_store.get(sid)
        assert live is not None
        assert live.system_prompt == 'Updated prompt.'
        assert session_store.messages(sid)[0] == {'role': 'system', 'content': 'Original.'}

    def test_history_empty_for_new_session(self, client: TestClient) -> None:
        sid = _create_session(client)
        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 200
        data = hist.json()
        assert data['session_id'] == sid
        assert data['history'] == []

    def test_list_sessions_returns_epoch_milliseconds(self, client: TestClient) -> None:
        sid = _create_session(client)

        sessions_resp = client.get('/api/v1/ai/chat/sessions')
        assert sessions_resp.status_code == 200
        session = next(item for item in sessions_resp.json() if item['id'] == sid)
        assert isinstance(session['created_at'], int)
        assert session['created_at'] > 10_000_000_000

    @pytest.mark.parametrize(
        ('method', 'url', 'body'),
        [
            pytest.param('GET', '/api/v1/ai/chat/history/nonexistent', None, id='history'),
            pytest.param('POST', '/api/v1/ai/chat/message', {'session_id': 'nonexistent', 'content': 'hello'}, id='message'),
            pytest.param('GET', '/api/v1/ai/chat/stream/nonexistent', None, id='stream'),
            pytest.param('PATCH', '/api/v1/ai/chat/sessions/nonexistent', {'model': 'new-model'}, id='update'),
            pytest.param('DELETE', '/api/v1/ai/chat/sessions/nonexistent', None, id='delete'),
        ],
    )
    def test_unknown_session_returns_404(self, client: TestClient, method: str, url: str, body: dict | None) -> None:
        resp = client.request(method, url, json=body)
        assert resp.status_code == 404

    def test_delete_session_closes_and_removes_from_store(self, client: TestClient) -> None:
        sid = _create_session(client)
        del_resp = client.delete(f'/api/v1/ai/chat/sessions/{sid}')
        assert del_resp.status_code == 200
        data = del_resp.json()
        assert data['status'] == 'closed'
        assert data['session_id'] == sid
        hist = client.get(f'/api/v1/ai/chat/history/{sid}')
        assert hist.status_code == 404
