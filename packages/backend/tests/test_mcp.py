"""Tests for MCP tool listing and preview/confirm flow."""

import re

import pytest

from backend_core.secrets import MASKED_SECRET
from modules.mcp.models import MCPHttpMethod, MCPToolDefinition, MCPToolSafety
from modules.mcp.registry import _build_tool, _openapi_to_json_schema
from modules.mcp.router import MCP_ROUTE_META, MCPRouter, get_mcp_route_meta
from tests.http_client import TestClient


class TestMCPToolDefinition:
    def test_tool_definition_owns_validation_and_response_payloads(self) -> None:
        tool = MCPToolDefinition(
            id='create_item',
            method=MCPHttpMethod.POST,
            path='/api/v1/items',
            description='Create item',
            confirm_required=True,
            input_schema={
                'type': 'object',
                'properties': {'payload': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}},
                'required': ['payload'],
                'additionalProperties': False,
            },
            arg_metadata={'path': [], 'query': [], 'payload': {'required': True, 'content_type': 'application/json', 'description': ''}},
            output_schema={'status_code': '200', 'content_type': 'application/json', 'schema': {'type': 'object'}, 'fields': []},
        )

        valid, errors, normalized = tool.validate_arguments({})

        assert valid is False
        assert errors
        assert tool.safety == MCPToolSafety.MUTATING
        assert tool.pending_response('token-1', {'payload': {'name': 'demo'}})['confirm_required'] is True
        assert tool.executed_response({'status': 200}) == {'status': 'executed', 'result': {'status': 200}}
        assert tool.validation_error_response(errors, {})['status'] == 'validation_error'
        assert tool.capability_report()['supported'] is True
        assert normalized == {}


class TestMCPToolListing:
    def test_compute_worker_lifecycle_tools_use_compute_worker_paths_and_names(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        by_id = {tool['id']: tool for tool in tools}

        expected_suffixes = {
            'spawn_analysis_compute_worker': '/compute/compute-worker/spawn/analysis/{analysis_id}',
            'spawn_datasource_preview_compute_worker': '/compute/compute-worker/spawn/datasource-preview/{datasource_id}',
            'configure_analysis_compute_worker': '/compute/compute-worker/configure/analysis/{analysis_id}',
            'configure_datasource_preview_compute_worker': '/compute/compute-worker/configure/datasource-preview/{datasource_id}',
            'shutdown_analysis_compute_worker': '/compute/compute-worker/analysis/{analysis_id}',
            'shutdown_datasource_preview_compute_worker': '/compute/compute-worker/datasource-preview/{datasource_id}',
            'shutdown_build_compute_worker': '/compute/compute-worker/build/{build_id}',
        }
        for tool_id, path_suffix in expected_suffixes.items():
            assert tool_id in by_id
            assert by_id[tool_id]['path'].endswith(path_suffix)

        assert not any(tool_id.endswith('_engine') for tool_id in by_id)

    def test_routes_require_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend_core.application import app
        from modules.auth.dependencies import get_current_user

        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        app.dependency_overrides.pop(get_current_user, None)
        response = client.get('/api/v1/mcp/tools')
        assert response.status_code == 401

    def test_tools_listing_contract(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        assert response.status_code == 200
        tools = response.json()
        assert isinstance(tools, list)
        assert len(tools) > 0
        for tool in tools:
            assert 'id' in tool
            assert 'method' in tool
            assert 'path' in tool
            assert 'description' in tool
            assert 'safety' in tool
            assert 'input_schema' in tool
            assert 'confirm_required' in tool
            assert 'output_schema' in tool

        paths = [tool['path'] for tool in tools]
        assert any(path.endswith('/compute-worker-runs') for path in paths)
        assert any(path.endswith('/compute-worker-runs/stats') for path in paths)
        assert not any('/engine-runs' in path for path in paths)
        assert not any('/mcp/' in path for path in paths)

        for tool in [t for t in tools if t['method'] == 'GET']:
            assert tool['safety'] == MCPToolSafety.SAFE.value
        for tool in [t for t in tools if t['method'] == 'DELETE']:
            assert tool['safety'] == MCPToolSafety.MUTATING.value

        # Deleting datasources, analyses (and their versions/steps), schedules and
        # health checks from chat always needs the user's confirmation.
        for prefix in ('/datasource/', '/analysis/', '/schedules/', '/healthchecks/'):
            deletes = [t for t in tools if t['method'] == 'DELETE' and f'/api/v1{prefix}' in t['path']]
            assert deletes, prefix
            assert all(tool['confirm_required'] is True for tool in deletes), prefix


class TestMCPCallPreview:
    def test_call_get_tool_executes_directly(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        get_tool = next((t for t in tools if t['method'] == 'GET'), None)
        assert get_tool is not None

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': get_tool['id'], 'args': {}})
        assert call_resp.status_code == 200
        data = call_resp.json()
        assert data['status'] == 'executed'
        assert 'result' in data

    def test_call_mutating_tool_returns_pending(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next(
            (t for t in tools if t['method'] == 'POST' and not t['input_schema'].get('required')),
            None,
        )
        if post_tool is None:
            pytest.skip('No POST tool without required args available')

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {}})
        assert call_resp.status_code == 200
        data = call_resp.json()
        assert data['status'] == 'pending'
        assert 'token' in data
        assert data['token'] != ''

    def test_call_unknown_tool_returns_404(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/call', json={'tool_id': 'nonexistent_tool', 'args': {}})
        assert resp.status_code == 404


class TestMCPConfirm:
    def test_pending_action_is_encrypted_and_consumed_once_across_store_instances(self, client: TestClient, test_user) -> None:
        from concurrent.futures import ThreadPoolExecutor
        from hashlib import sha256

        from backend_core.database import run_settings_db
        from backend_core.persistence.mcp_pending.models import McpPendingAction
        from modules.mcp.models import MCPHttpMethod
        from modules.mcp.pending import PendingStore

        args = {'password': 'sensitive-test-value'}
        token = PendingStore().create(
            'test_tool',
            MCPHttpMethod.POST,
            '/api/v1/test',
            args,
            namespace='default',
            owner_id=test_user.id,
        )
        action = run_settings_db(lambda session: session.get(McpPendingAction, sha256(token.encode()).hexdigest()))

        assert action is not None
        assert action.token_hash != token
        assert 'sensitive-test-value' not in action.args_encrypted

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: PendingStore().pop(token, owner_id=test_user.id), range(2)))

        consumed = [entry for entry in results if entry is not None]
        assert len(consumed) == 1
        assert consumed[0].args == args

    def test_confirm_executes_pending_action(self, client: TestClient, test_user) -> None:
        from hashlib import sha256

        from backend_core.database import run_settings_db
        from backend_core.persistence.mcp_pending.models import McpPendingAction

        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next(
            (t for t in tools if t['method'] == 'POST' and not t['input_schema'].get('required')),
            None,
        )
        if post_tool is None:
            pytest.skip('No POST tool without required args available')

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {}})
        token = call_resp.json()['token']
        pending = run_settings_db(lambda session: session.get(McpPendingAction, sha256(token.encode()).hexdigest()))
        assert pending is not None
        assert pending.owner_id == test_user.id
        assert pending.namespace == 'default'

        confirm_resp = client.post('/api/v1/mcp/confirm', json={'token': token})
        assert confirm_resp.status_code == 200
        data = confirm_resp.json()
        assert data['status'] == 'executed'
        assert 'result' in data
        replay = client.post('/api/v1/mcp/confirm', json={'token': token})
        assert replay.status_code == 404

    def test_confirm_expired_token_returns_404(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/confirm', json={'token': 'invalid-token-xyz'})
        assert resp.status_code == 404

    @staticmethod
    def _post_tool_without_required_args(client: TestClient) -> dict | None:
        tools = client.get('/api/v1/mcp/tools').json()
        return next((t for t in tools if t['method'] == 'POST' and not t['input_schema'].get('required')), None)

    def test_confirm_rejects_token_presented_by_other_user(self, client: TestClient, test_user) -> None:
        import uuid
        from datetime import UTC, datetime

        from fastapi import FastAPI

        from modules.auth.dependencies import get_current_user
        from modules.auth.models import User, UserStatus

        app = client.app
        assert isinstance(app, FastAPI)

        post_tool = self._post_tool_without_required_args(client)
        if post_tool is None:
            pytest.skip('No POST tool without required args available')

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {}})
        token = call_resp.json()['token']

        now = datetime.now(UTC)
        other_user = User(
            id=uuid.uuid4().hex,
            email='other@example.com',
            display_name='Other User',
            status=UserStatus.ACTIVE,
            email_verified=True,
            has_password=True,
            preferences={},
            created_at=now,
            updated_at=now,
        )
        previous_override = app.dependency_overrides[get_current_user]
        app.dependency_overrides[get_current_user] = lambda: other_user
        denied = client.post('/api/v1/mcp/confirm', json={'token': token})
        assert denied.status_code == 404

        app.dependency_overrides[get_current_user] = previous_override
        allowed = client.post('/api/v1/mcp/confirm', json={'token': token})
        assert allowed.status_code == 200
        assert allowed.json()['status'] == 'executed'


class TestMCPValidate:
    def test_validate_returns_errors_for_missing_required_args(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next(
            (t for t in tools if t['method'] == 'POST' and t['input_schema'].get('required')),
            None,
        )
        if post_tool is None:
            pytest.skip('No POST tool with required args available')
        resp = client.post('/api/v1/mcp/validate', json={'tool_id': post_tool['id'], 'args': {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data['valid'] is False
        assert isinstance(data['errors'], list)
        assert len(data['errors']) > 0

    def test_validate_returns_valid_for_correct_args(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        get_tool = next((t for t in tools if t['method'] == 'GET'), None)
        assert get_tool is not None
        resp = client.post('/api/v1/mcp/validate', json={'tool_id': get_tool['id'], 'args': {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data['valid'] is True
        assert data['errors'] == []

    def test_validate_unknown_tool_returns_404(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/validate', json={'tool_id': 'nonexistent_tool', 'args': {}})
        assert resp.status_code == 404


class TestMCPCallValidation:
    def test_call_returns_validation_error_for_invalid_args(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next(
            (t for t in tools if t['method'] == 'POST' and t['input_schema'].get('required')),
            None,
        )
        if post_tool is None:
            pytest.skip('No POST tool with required args available')
        resp = client.post(
            '/api/v1/mcp/call',
            json={'tool_id': post_tool['id'], 'args': {'__invalid__': 1}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'validation_error'
        assert data['valid'] is False
        assert isinstance(data['errors'], list)
        assert 'token' not in data


class TestValidationFormatAndDefaults:
    @pytest.mark.parametrize(
        ('value_format', 'value', 'expected_valid'),
        [
            pytest.param('email', 'user@example.com', True, id='email-valid'),
            pytest.param('email', 'not-an-email', False, id='email-invalid'),
            pytest.param('date', '2024-01-15', True, id='date-valid'),
            pytest.param('date', 'not-a-date', False, id='date-invalid'),
        ],
    )
    def test_string_format_is_enforced(self, value_format: str, value: str, expected_valid: bool) -> None:
        from modules.mcp.validation import validate_args

        schema = {'type': 'object', 'properties': {'value': {'type': 'string', 'format': value_format}}}
        valid, errors, _ = validate_args(schema, {'value': value})
        assert valid is expected_valid
        assert len(errors) == (0 if expected_valid else 1)
        assert all(error['path'] == 'value' for error in errors)

    @pytest.mark.parametrize(
        ('prop_schema', 'args', 'expected'),
        [
            pytest.param({'const': 'fixed'}, {}, 'fixed', id='const-filled-when-missing'),
            pytest.param({'const': 'fixed'}, {'value': 'other'}, 'other', id='const-kept-when-present'),
            pytest.param({'type': 'integer', 'default': 10}, {}, 10, id='default-filled-when-missing'),
            pytest.param({'type': 'integer', 'default': 10}, {'value': 5}, 5, id='default-kept-when-present'),
        ],
    )
    def test_apply_defaults_fills_only_missing_values(self, prop_schema: dict, args: dict, expected: object) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {'type': 'object', 'properties': {'value': prop_schema}}
        assert apply_defaults(schema, args)['value'] == expected

    @pytest.mark.parametrize(
        ('verbose_default', 'args'),
        [
            pytest.param(False, {'opts': {}}, id='existing-object-gets-default'),
            pytest.param(True, {}, id='missing-object-is-created'),
        ],
    )
    def test_apply_defaults_recurses_into_nested_objects(self, verbose_default: bool, args: dict) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {
            'type': 'object',
            'properties': {
                'opts': {
                    'type': 'object',
                    'properties': {'verbose': {'type': 'boolean', 'default': verbose_default}},
                },
            },
        }
        assert apply_defaults(schema, args)['opts']['verbose'] is verbose_default

    @pytest.mark.parametrize(
        ('prop_name', 'prop_schema', 'expected'),
        [
            pytest.param('limit', {'type': 'integer', 'default': 20}, 20, id='default'),
            pytest.param('version', {'const': 'v1'}, 'v1', id='const'),
        ],
    )
    def test_validate_args_returns_normalized_defaults_and_consts(self, prop_name: str, prop_schema: dict, expected: object) -> None:
        from modules.mcp.validation import validate_args

        schema = {
            'type': 'object',
            'properties': {'name': {'type': 'string'}, prop_name: prop_schema},
            'required': ['name'],
        }
        valid, errors, normalized = validate_args(schema, {'name': 'test'})
        assert valid is True
        assert normalized[prop_name] == expected

    @pytest.mark.parametrize(
        ('schema', 'args', 'validator', 'message'),
        [
            pytest.param(
                {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
                {},
                'required',
                'Provide all required fields',
                id='required',
            ),
            pytest.param(
                {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'additionalProperties': False},
                {'extra': 1},
                'additionalProperties',
                'Remove unknown fields',
                id='additional-properties',
            ),
            pytest.param(
                {'type': 'object', 'properties': {'mode': {'type': 'string', 'enum': ['a', 'b']}}, 'required': ['mode']},
                {'mode': 'c'},
                'enum',
                'Use one of the documented enum values',
                id='enum',
            ),
            pytest.param(
                {'type': 'object', 'properties': {'limit': {'type': 'integer'}}, 'required': ['limit']},
                {'limit': 'ten'},
                'type',
                'Use the documented JSON type',
                id='type',
            ),
        ],
    )
    def test_validate_args_reports_actionable_error(self, schema: dict, args: dict, validator: str, message: str) -> None:
        from modules.mcp.validation import validate_args

        valid, errors, _ = validate_args(schema, args)
        assert valid is False
        assert len(errors) == 1
        assert errors[0]['validator'] == validator
        assert message in errors[0]['message']


class TestOpenAPIToJsonSchema:
    @pytest.mark.parametrize(
        'value',
        [
            pytest.param(True, id='bool-true'),
            pytest.param(False, id='bool-false'),
            pytest.param(None, id='none'),
            pytest.param({'type': 'string'}, id='dict'),
        ],
    )
    def test_non_ref_values_pass_through_unchanged(self, value: object) -> None:
        result = _openapi_to_json_schema(value, {})
        assert result == value
        assert type(result) is type(value)

    @pytest.mark.parametrize(
        'schema',
        [
            pytest.param({'type': 'object', 'additionalProperties': True}, id='additional-properties-true'),
            pytest.param({'type': 'object', 'additionalProperties': False}, id='additional-properties-false'),
            pytest.param({'type': 'object', 'additionalProperties': {'type': 'string'}}, id='additional-properties-schema'),
            pytest.param({'type': 'array', 'items': True}, id='items-bool'),
            pytest.param({'type': 'array', 'items': {'type': 'integer'}}, id='items-schema'),
        ],
    )
    def test_subschema_keywords_are_preserved(self, schema: dict) -> None:
        assert _openapi_to_json_schema(schema, {}) == schema

    @pytest.mark.parametrize(
        ('schema', 'components', 'expected'),
        [
            pytest.param(
                {'$ref': '#/components/schemas/Foo'},
                {'schemas': {'Foo': {'type': 'string'}}},
                {'type': 'string'},
                id='top-level-ref',
            ),
            pytest.param(
                {'type': 'object', 'additionalProperties': {'$ref': '#/components/schemas/ExtraValue'}},
                {
                    'schemas': {
                        'ExtraValue': {
                            'type': 'object',
                            'properties': {'name': {'type': 'string'}},
                            'required': ['name'],
                            'additionalProperties': False,
                        },
                    },
                },
                {
                    'type': 'object',
                    'additionalProperties': {
                        'type': 'object',
                        'properties': {'name': {'type': 'string'}},
                        'required': ['name'],
                        'additionalProperties': False,
                    },
                },
                id='additional-properties-ref',
            ),
            pytest.param({'type': 'string', 'title': 'My Field'}, {}, {'type': 'string'}, id='title-stripped'),
        ],
    )
    def test_refs_resolve_and_titles_are_stripped(self, schema: dict, components: dict, expected: dict) -> None:
        assert _openapi_to_json_schema(schema, components) == expected

    @pytest.mark.parametrize('additional_properties', [True, False], ids=['additional-properties-true', 'additional-properties-false'])
    def test_build_tool_payload_keeps_additional_properties(self, additional_properties: bool) -> None:
        op = {
            'summary': 'Test',
            'requestBody': {'content': {'application/json': {'schema': {'type': 'object', 'additionalProperties': additional_properties}}}},
        }
        tool = _build_tool({'method': 'POST', 'path': '/api/v1/test', 'operation': op}, {})
        payload = tool.input_schema['properties']['payload']
        assert payload == {'type': 'object', 'additionalProperties': additional_properties}

    def test_build_tool_sets_top_level_additional_properties_false(self) -> None:
        op = {
            'summary': 'Test',
            'parameters': [
                {
                    'name': 'id',
                    'in': 'path',
                    'required': True,
                    'schema': {'type': 'string'},
                }
            ],
        }
        tool = _build_tool({'method': 'GET', 'path': '/api/v1/test/{id}', 'operation': op}, {})
        assert tool.input_schema['additionalProperties'] is False

    def test_build_tool_includes_arg_metadata(self) -> None:
        op = {
            'summary': 'Test',
            'parameters': [
                {
                    'name': 'id',
                    'in': 'path',
                    'required': True,
                    'schema': {'type': 'string'},
                    'description': 'Resource ID',
                },
                {
                    'name': 'limit',
                    'in': 'query',
                    'required': False,
                    'schema': {'type': 'integer', 'default': 10},
                },
            ],
            'requestBody': {
                'required': True,
                'description': 'Body payload',
                'content': {
                    'application/json': {
                        'schema': {
                            'type': 'object',
                            'properties': {'x': {'type': 'string'}},
                        }
                    }
                },
            },
        }
        tool = _build_tool({'method': 'POST', 'path': '/api/v1/test/{id}', 'operation': op}, {})
        meta = tool.arg_metadata
        assert meta['path'][0]['name'] == 'id'
        assert meta['query'][0]['name'] == 'limit'
        assert meta['payload']['required'] is True
        assert meta['payload']['content_type'] == 'application/json'
        assert 'payload' in tool.input_schema['required']

    def test_build_tool_includes_output_schema_for_json_success_response(self) -> None:
        op = {
            'summary': 'Test',
            'responses': {
                '200': {
                    'description': 'Success',
                    'content': {
                        'application/json': {
                            'schema': {
                                'type': 'object',
                                'properties': {'ok': {'type': 'boolean'}},
                                'required': ['ok'],
                            },
                        },
                    },
                },
            },
        }
        tool = _build_tool(
            {
                'method': 'GET',
                'path': '/api/v1/test',
                'operation': op,
                'meta': {'response_model': 'TestResponse'},
            },
            {},
        )
        output = tool.output_schema
        assert output is not None
        assert output['status_code'] == '200'
        assert output['content_type'] == 'application/json'
        assert output['schema'] == {
            'type': 'object',
            'properties': {'ok': {'type': 'boolean'}},
            'required': ['ok'],
        }
        assert output['response_model'] == 'TestResponse'
        assert output['fields'] == ['ok']
        assert output['hint'] == 'Expected output: status 200; application/json; model TestResponse; fields: ok'

    def test_build_tool_output_schema_is_none_when_success_schema_missing(self) -> None:
        op = {
            'summary': 'Test',
            'responses': {
                '204': {'description': 'No content'},
                '400': {'description': 'Bad request'},
            },
        }
        tool = _build_tool({'method': 'GET', 'path': '/api/v1/test', 'operation': op}, {})
        assert tool.output_schema is None


class TestMCPContractGuardrails:
    @staticmethod
    def _path_names(path: str) -> set[str]:
        return set(re.findall(r'\{(\w+)\}', path))

    def test_registry_schemas_are_closed_at_top_level(self, client: TestClient) -> None:
        tools = client.get('/api/v1/mcp/tools').json()
        assert len(tools) > 0
        for tool in tools:
            assert tool['input_schema'].get('additionalProperties') is False

    def test_path_parameter_contract_is_consistent(self, client: TestClient) -> None:
        tools = client.get('/api/v1/mcp/tools').json()
        for tool in tools:
            path_names = self._path_names(tool['path'])
            path_meta = tool.get('arg_metadata', {}).get('path') or []
            meta_names = {item['name'] for item in path_meta}
            required = set(tool['input_schema'].get('required', []))
            assert meta_names == path_names
            for item in path_meta:
                assert item.get('required') is True
            for name in path_names:
                assert name in required

    def test_payload_contract_is_consistent(self, client: TestClient) -> None:
        tools = client.get('/api/v1/mcp/tools').json()
        payload_tools = [t for t in tools if t.get('arg_metadata', {}).get('payload') is not None]
        assert len(payload_tools) > 0
        for tool in payload_tools:
            meta = tool['arg_metadata']['payload']
            schema = tool['input_schema']
            props = schema.get('properties', {})
            required = set(schema.get('required', []))
            assert 'payload' in props
            assert meta.get('content_type') in {
                'application/json',
                'multipart/form-data',
                'application/x-www-form-urlencoded',
            }
            if meta.get('required'):
                assert 'payload' in required

    def test_confirm_returns_structured_validation_error_for_missing_path_param(self, client: TestClient) -> None:
        from fastapi import FastAPI

        app = client.app
        assert isinstance(app, FastAPI)
        app.state.mcp_registry = [
            MCPToolDefinition(
                id='broken_mutating_tool',
                method=MCPHttpMethod.POST,
                path='/api/v1/test/{item_id}',
                description='Broken for confirm test',
                confirm_required=False,
                input_schema={
                    'type': 'object',
                    'properties': {},
                    'required': [],
                    'additionalProperties': False,
                },
                arg_metadata={'path': [], 'query': [], 'payload': None},
            ),
        ]

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': 'broken_mutating_tool', 'args': {}})
        assert call_resp.status_code == 200
        assert call_resp.json()['status'] == 'pending'
        token = call_resp.json()['token']

        confirm_resp = client.post('/api/v1/mcp/confirm', json={'token': token})
        assert confirm_resp.status_code == 200
        data = confirm_resp.json()
        assert data['status'] == 'validation_error'
        assert data['valid'] is False
        assert data['tool_id'] == 'broken_mutating_tool'
        assert isinstance(data['errors'], list)
        assert data['errors'][0]['validator'] == 'path_params'
        assert 'Missing required path parameter' in data['errors'][0]['message']


class TestRouterOnboarding:
    def test_mcp_route_onboards_with_docstring(self) -> None:
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        leaf = MCPRouter(prefix='/demo', tags=['demo'])

        @leaf.get('/decorated', mcp=True)
        def endpoint() -> dict[str, str]:
            """Decorated endpoint."""
            return {'ok': 'yes'}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0].id == 'endpoint'
        assert tools[0].description == 'Decorated endpoint.'

    def test_confirm_required_override_from_router_decorator(self) -> None:
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        leaf = MCPRouter(prefix='/datasource', tags=['demo'])

        @leaf.delete('/item/{item_id}', mcp=True, mcp_confirm_required=False)
        def endpoint(item_id: str) -> dict[str, str]:
            """Delete item endpoint."""
            return {'id': item_id}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0].confirm_required is False

    def test_tool_id_override_from_router_decorator(self) -> None:
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        leaf = MCPRouter(prefix='/demo', tags=['demo'])

        @leaf.get('/custom', mcp=True, mcp_tool_id='stable_custom_tool')
        def endpoint() -> dict[str, str]:
            return {'ok': 'yes'}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0].id == 'stable_custom_tool'

    def test_description_prefers_docstring_when_operation_text_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import FastAPI

        from modules.mcp import registry as reg

        def fake_openapi() -> dict:
            return {
                'paths': {'/api/v1/demo/doc': {'get': {'parameters': []}}},
                'components': {},
            }

        def endpoint() -> None:
            """Docstring text for MCP description."""

        router = MCPRouter(prefix='/api/v1/demo', tags=['demo'])
        router.add_api_route('/doc', endpoint, methods=['GET'], mcp=True)
        app = FastAPI()
        app.include_router(router)
        monkeypatch.setattr(app, 'openapi', fake_openapi)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0].description == 'Docstring text for MCP description.'


class TestRouterRegistrationOnboarding:
    def test_mcp_router_attaches_metadata_on_registered_route(self) -> None:
        from fastapi.routing import APIRoute
        from pydantic import BaseModel

        class DemoResponse(BaseModel):
            ok: bool

        router = MCPRouter(prefix='/demo', tags=['demo'])

        @router.get('/item', response_model=DemoResponse, mcp=True, mcp_confirm_required=True)
        def item(item_id: str) -> DemoResponse:
            return DemoResponse(ok=bool(item_id))

        route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path == '/demo/item')
        meta = get_mcp_route_meta(route)
        assert isinstance(meta, dict)
        assert getattr(route, MCP_ROUTE_META) == meta
        assert meta['name'] == 'item'
        assert meta['confirm_required'] is True
        assert meta['response_model'] == 'DemoResponse'

    def test_router_metadata_survives_nested_include_router(self) -> None:
        from fastapi import APIRouter, FastAPI
        from fastapi.routing import APIRoute, iter_route_contexts

        leaf = MCPRouter(prefix='/leaf', tags=['leaf'])

        @leaf.get('/value', mcp=True)
        def value() -> dict[str, str]:
            return {'ok': 'yes'}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        route_context = next(
            context
            for context in iter_route_contexts(list(app.routes))
            if isinstance(context.original_route, APIRoute) and context.original_route.path == '/leaf/value'
        )
        route = route_context.original_route
        assert isinstance(route, APIRoute)
        assert route_context.path == '/api/v1/leaf/value'
        meta = get_mcp_route_meta(route)
        assert isinstance(meta, dict)
        assert meta['name'] == 'value'

    def test_registry_prefers_route_registered_metadata(self) -> None:
        from fastapi import APIRouter, FastAPI
        from fastapi.routing import APIRoute, iter_route_contexts

        from modules.mcp import registry as reg

        leaf = MCPRouter(prefix='/demo', tags=['demo'])

        @leaf.delete('/item/{item_id}', mcp=True, mcp_confirm_required=True)
        def remove(item_id: str) -> None:
            del item_id

        route = next(r for r in leaf.routes if isinstance(r, APIRoute) and r.path == '/demo/item/{item_id}')
        meta = dict(get_mcp_route_meta(route) or {})
        meta['confirm_required'] = False
        meta['name'] = 'stable_override_name'
        setattr(route, MCP_ROUTE_META, meta)

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        route_context = next(
            context
            for context in iter_route_contexts(list(app.routes))
            if isinstance(context.original_route, APIRoute) and context.original_route.path == '/demo/item/{item_id}'
        )
        app_route = route_context.original_route
        assert isinstance(app_route, APIRoute)
        assert route_context.path == '/api/v1/demo/item/{item_id}'
        app_meta = dict(get_mcp_route_meta(app_route) or {})
        app_meta['confirm_required'] = False
        app_meta['name'] = 'stable_override_name'
        setattr(app_route, MCP_ROUTE_META, app_meta)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0].id == 'stable_override_name'
        assert tools[0].confirm_required is False

    def test_plain_apirouter_route_not_onboarded(self) -> None:
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        plain = APIRouter(prefix='/api/v1/plain', tags=['plain'])

        @plain.get('/decorated')
        def plain_decorated() -> dict[str, str]:
            return {'ok': 'yes'}

        app = FastAPI()
        app.include_router(plain)

        tools = reg.build_tool_registry(app)
        assert tools == []

    def test_raw_api_route_not_onboarded(self) -> None:
        from fastapi import FastAPI
        from fastapi.routing import APIRoute

        from modules.mcp import registry as reg

        def raw_decorated() -> None:
            return None

        app = FastAPI()
        app.routes.append(APIRoute('/api/v1/raw/decorated', raw_decorated, methods=['GET']))

        tools = reg.build_tool_registry(app)
        assert tools == []

    def test_registry_tool_ids_stay_endpoint_stable(self) -> None:
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        leaf = MCPRouter(prefix='/stable', tags=['stable'])

        @leaf.get('/a', mcp=True)
        def alpha() -> dict[str, str]:
            return {'ok': 'a'}

        @leaf.post('/b', mcp=True)
        def beta() -> dict[str, str]:
            return {'ok': 'b'}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        tools = reg.build_tool_registry(app)
        ids = {tool.id for tool in tools}
        assert ids == {'alpha', 'beta'}


class TestPathParameterReliability:
    async def test_call_tool_raises_on_missing_path_param(self) -> None:
        import pytest
        from fastapi import FastAPI

        from modules.mcp.executor import call_tool

        app = FastAPI()
        with pytest.raises(ValueError, match='Missing required path parameter'):
            await call_tool(app, 'GET', '/api/v1/test/{item_id}', {})

    def test_call_route_returns_validation_error_for_missing_path_param_at_execution(self, client: TestClient) -> None:
        from fastapi import FastAPI

        app = client.app
        assert isinstance(app, FastAPI)
        app.state.mcp_registry = [
            MCPToolDefinition(
                id='broken_tool',
                method=MCPHttpMethod.GET,
                path='/api/v1/test/{item_id}',
                description='Broken for test',
                confirm_required=False,
                input_schema={
                    'type': 'object',
                    'properties': {},
                    'required': [],
                    'additionalProperties': False,
                },
                arg_metadata={'path': [], 'query': [], 'payload': None},
            ),
        ]
        resp = client.post('/api/v1/mcp/call', json={'tool_id': 'broken_tool', 'args': {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'validation_error'
        assert data['errors'][0]['validator'] == 'path_params'
        assert data['tool_id'] == 'broken_tool'
        assert 'Missing required path parameter' in data['errors'][0]['message']

    async def test_call_tool_url_encodes_path_param(self) -> None:
        from fastapi import FastAPI

        from modules.mcp.executor import call_tool

        app = FastAPI()

        @app.get('/api/v1/test/{name}')
        async def get_name(name: str) -> dict[str, str]:
            return {'name': name}

        result = await call_tool(app, 'GET', '/api/v1/test/{name}', {'name': 'a b'})
        assert result['ok'] is True
        assert result['status'] == 200
        assert result['body']['name'] == 'a b'

    async def test_call_tool_forwards_context_headers(self) -> None:
        from fastapi import FastAPI, Header

        from modules.mcp.executor import build_tool_context, call_tool

        app = FastAPI()

        @app.get('/api/v1/test/context')
        async def get_context(
            x_session_token: str | None = Header(default=None),
            x_namespace: str | None = Header(default=None),
        ) -> dict[str, str | None]:
            return {
                'session_token': x_session_token,
                'namespace': x_namespace or 'default',
            }

        context = build_tool_context({'X-Session-Token': 'session-1', 'X-Namespace': 'alpha'})
        result = await call_tool(app, 'GET', '/api/v1/test/context', {}, context)
        assert result['ok'] is True
        assert result['status'] == 200
        assert result['body'] == {'session_token': 'session-1', 'namespace': 'alpha'}


class TestSecretRedaction:
    def test_redact_secrets_masks_sensitive_fields(self) -> None:
        from modules.mcp.tool_output import redact_secrets

        result = redact_secrets(
            {
                'connection_string': 'postgres://user:pass@host/db',
                'api_key': 'sk-secret',
                'bot_token': '123:abc',
                'name': 'keep-me',
            }
        )
        assert result == {'connection_string': MASKED_SECRET, 'api_key': MASKED_SECRET, 'bot_token': MASKED_SECRET, 'name': 'keep-me'}

    def test_redact_secrets_walks_nested_structures(self) -> None:
        from modules.mcp.tool_output import redact_secrets

        result = redact_secrets(
            {
                'items': [{'config': {'connection_string': 'postgres://h/db'}}, {'safe': 1}],
                'empty_secret': '',
            }
        )
        assert result['items'][0]['config']['connection_string'] == MASKED_SECRET
        assert result['items'][1] == {'safe': 1}
        assert result['empty_secret'] == ''

    async def test_call_tool_redacts_secrets_in_response_body(self) -> None:
        from fastapi import FastAPI

        from modules.mcp.executor import call_tool

        app = FastAPI()

        @app.get('/api/v1/datasource/{item_id}')
        async def get_item(item_id: str) -> dict[str, str]:
            return {
                'id': item_id,
                'connection_string': 'postgres://user:pass@host/db',
                'api_key': 'sk-secret',
                'bot_token': '123:abc',
            }

        result = await call_tool(app, 'GET', '/api/v1/datasource/{item_id}', {'item_id': 'ds-1'})
        assert result['ok'] is True
        assert result['body'] == {
            'id': 'ds-1',
            'connection_string': MASKED_SECRET,
            'api_key': MASKED_SECRET,
            'bot_token': MASKED_SECRET,
        }


class TestCheckSchemaSupported:
    @pytest.mark.parametrize(
        'schema',
        [
            pytest.param({'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}, id='object-with-properties'),
            pytest.param({'type': 'array', 'items': {'type': 'string'}}, id='items-schema'),
            pytest.param({'type': 'array', 'items': {'type': 'string', 'enum': ['a', 'b']}}, id='items-with-enum'),
            pytest.param({'type': 'array', 'items': [{'type': 'string'}, {'type': 'integer'}]}, id='items-tuple'),
            pytest.param({'if': {'type': 'string'}, 'then': {'minLength': 1}, 'else': {'type': 'integer'}}, id='if-then-else'),
            pytest.param({'not': {'type': 'string'}}, id='not'),
            pytest.param({'type': 'object', 'patternProperties': {'^x_': {'type': 'string'}}}, id='pattern-properties'),
            pytest.param({'type': 'object', 'additionalProperties': {'type': 'integer'}}, id='additional-properties-schema'),
        ],
    )
    def test_supported_schema_has_no_issues(self, schema: dict) -> None:
        from modules.mcp.validation import check_schema_supported

        assert check_schema_supported(schema) == []

    @pytest.mark.parametrize(
        ('schema', 'marker'),
        [
            pytest.param({'type': 'object', 'x-custom-extension': 'foo'}, 'x-custom-extension', id='unknown-top-level-keyword'),
            pytest.param({'type': 'custom-unknown-type'}, 'custom-unknown-type', id='unsupported-type'),
            pytest.param({'type': 'object', 'properties': {'x': {'type': 'string', 'x-secret': True}}}, 'x-secret', id='nested-unknown-keyword'),
            pytest.param({'anyOf': [{'type': 'string', 'x-unknown': 1}]}, 'x-unknown', id='anyof-unknown-keyword'),
        ],
    )
    def test_unsupported_schema_reports_issue(self, schema: dict, marker: str) -> None:
        from modules.mcp.validation import check_schema_supported

        issues = check_schema_supported(schema)
        assert any(marker in i for i in issues)


class TestMCPCapabilities:
    @pytest.mark.parametrize('body', [pytest.param({}, id='default-body'), pytest.param({'tool_ids': []}, id='empty-tool-ids')])
    def test_capabilities_without_filter_reports_every_tool(self, client: TestClient, body: dict) -> None:
        all_count = len(client.get('/api/v1/mcp/tools').json())
        resp = client.post('/api/v1/mcp/capabilities', json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert all_count > 0
        assert len(data) == all_count
        for entry in data:
            assert 'tool_id' in entry
            assert 'supported' in entry
            assert 'issues' in entry
            assert isinstance(entry['supported'], bool)
            assert isinstance(entry['issues'], list)
            assert entry['supported'] is (entry['issues'] == [])

    def test_capabilities_filters_by_tool_ids(self, client: TestClient) -> None:
        tools_resp = client.get('/api/v1/mcp/tools')
        tools = tools_resp.json()
        subset = [tools[0]['id'], tools[1]['id']] if len(tools) >= 2 else [tools[0]['id']]

        resp = client.post('/api/v1/mcp/capabilities', json={'tool_ids': subset})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(subset)
        returned_ids = [e['tool_id'] for e in data]
        for tid in subset:
            assert tid in returned_ids

    def test_capabilities_unknown_tool_id_excluded(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/capabilities', json={'tool_ids': ['nonexistent_tool_xyz']})
        assert resp.status_code == 200
        data = resp.json()
        assert data == []


class TestBuildRegistryFailFast:
    def test_raises_on_unsupported_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pytest
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        def fake_openapi() -> dict:
            return {
                'paths': {
                    '/api/v1/fake/endpoint': {
                        'get': {
                            'summary': 'Fake',
                            'parameters': [
                                {
                                    'name': 'q',
                                    'in': 'query',
                                    'schema': {'type': 'string', 'x-vendor-ext': 'bad'},
                                },
                            ],
                        },
                    },
                },
                'components': {},
            }

        def fake_endpoint() -> None:
            pass

        leaf = MCPRouter(prefix='/fake', tags=['fake'])
        leaf.add_api_route('/endpoint', fake_endpoint, methods=['GET'], mcp=True)
        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)
        monkeypatch.setattr(app, 'openapi', fake_openapi)

        with pytest.raises(ValueError, match='fake_endpoint'):
            reg.build_tool_registry(app)

    def test_mixed_routes_include_only_decorated(self) -> None:
        from fastapi import FastAPI

        from modules.mcp import registry as reg

        router = MCPRouter(prefix='/api/v1/mixed', tags=['mixed'])

        @router.get('/decorated', mcp=True)
        def decorated_endpoint() -> dict[str, str]:
            return {'type': 'decorated'}

        @router.get('/undecorated')
        def undecorated_endpoint() -> dict[str, str]:
            return {'type': 'undecorated'}

        app = FastAPI()
        app.include_router(router)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0].id == 'decorated_endpoint'
        assert tools[0].path == '/api/v1/mixed/decorated'


class TestStartupEnforcement:
    def test_startup_populates_cache_so_no_double_build(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import FastAPI

        import modules.mcp.routes as routes_mod
        from modules.mcp.routes import get_registry

        build_calls: list[int] = []
        original_build = routes_mod.build_tool_registry

        def counting_build(a: FastAPI) -> list[MCPToolDefinition]:
            build_calls.append(1)
            return original_build(a)

        monkeypatch.setattr(routes_mod, 'build_tool_registry', counting_build)

        app = FastAPI()

        first = get_registry(app)
        second = get_registry(app)
        assert len(build_calls) == 1
        assert second is first
