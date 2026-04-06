"""Tests for MCP tool listing and preview/confirm flow."""

import re

import pytest
from fastapi.testclient import TestClient

from modules.mcp.decorators import MCP_TOOL_MARKER, deterministic_tool, get_mcp_tool_meta
from modules.mcp.registry import _build_tool, _openapi_to_json_schema
from modules.mcp.router import MCP_ROUTE_META, MCPRouter, get_mcp_route_meta


class TestMCPToolListing:
    def test_routes_require_auth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from main import app
        from modules.auth.dependencies import get_current_user

        monkeypatch.setattr('core.config.settings.auth_required', True)
        app.dependency_overrides.pop(get_current_user, None)
        response = client.get('/api/v1/mcp/tools')
        assert response.status_code == 401

    def test_list_tools_returns_list(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        assert response.status_code == 200
        tools = response.json()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tools_have_required_fields(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        for tool in tools:
            assert 'id' in tool
            assert 'method' in tool
            assert 'path' in tool
            assert 'description' in tool
            assert 'safety' in tool
            assert 'input_schema' in tool
            assert 'confirm_required' in tool
            assert 'output_schema' in tool

    def test_get_tools_are_safe(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        get_tools = [t for t in tools if t['method'] == 'GET']
        for tool in get_tools:
            assert tool['safety'] == 'safe'

    def test_delete_tools_are_mutating(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        delete_tools = [t for t in tools if t['method'] == 'DELETE']
        for tool in delete_tools:
            assert tool['safety'] == 'mutating'

    def test_mcp_tools_not_in_registry(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        paths = [t['path'] for t in tools]
        for p in paths:
            assert '/mcp/' not in p

    def test_datasource_delete_requires_confirm(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        ds_delete = [t for t in tools if t['method'] == 'DELETE' and '/datasource/' in t['path']]
        assert len(ds_delete) > 0
        for tool in ds_delete:
            assert tool['confirm_required'] is True

    def test_analysis_delete_requires_confirm(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        analysis_delete = [t for t in tools if t['method'] == 'DELETE' and '/analysis/' in t['path']]
        assert len(analysis_delete) > 0
        for tool in analysis_delete:
            assert tool['confirm_required'] is True


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
        post_tool = next((t for t in tools if t['method'] == 'POST' and not t['input_schema'].get('required')), None)
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
    def test_confirm_executes_pending_action(self, client: TestClient) -> None:
        from modules.mcp.pending import pending_store

        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next((t for t in tools if t['method'] == 'POST' and not t['input_schema'].get('required')), None)
        if post_tool is None:
            pytest.skip('No POST tool without required args available')

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {}})
        token = call_resp.json()['token']
        pending = pending_store.get(token)
        assert pending is not None
        assert pending.context['headers']['X-Namespace'] == 'default'

        confirm_resp = client.post('/api/v1/mcp/confirm', json={'token': token})
        assert confirm_resp.status_code == 200
        data = confirm_resp.json()
        assert data['status'] == 'executed'
        assert 'result' in data

    def test_confirm_expired_token_returns_404(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/confirm', json={'token': 'invalid-token-xyz'})
        assert resp.status_code == 404

    def test_token_consumed_after_confirm(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next((t for t in tools if t['method'] == 'POST' and not t['input_schema'].get('required')), None)
        if post_tool is None:
            pytest.skip('No POST tool without required args available')

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {}})
        token = call_resp.json()['token']

        client.post('/api/v1/mcp/confirm', json={'token': token})
        second = client.post('/api/v1/mcp/confirm', json={'token': token})
        assert second.status_code == 404


class TestMCPValidate:
    def test_validate_returns_errors_for_missing_required_args(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next((t for t in tools if t['method'] == 'POST' and t['input_schema'].get('required')), None)
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
        post_tool = next((t for t in tools if t['method'] == 'POST' and t['input_schema'].get('required')), None)
        if post_tool is None:
            pytest.skip('No POST tool with required args available')
        resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {'__invalid__': 1}})
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'validation_error'
        assert data['valid'] is False
        assert isinstance(data['errors'], list)

    def test_call_does_not_create_pending_for_invalid_args(self, client: TestClient) -> None:
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next((t for t in tools if t['method'] == 'POST' and t['input_schema'].get('required')), None)
        if post_tool is None:
            pytest.skip('No POST tool with required args available')
        resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {'__invalid__': 1}})
        data = resp.json()
        assert data['status'] == 'validation_error'
        assert 'token' not in data


class TestValidationFormatAndDefaults:
    def test_format_email_valid(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {'type': 'object', 'properties': {'email': {'type': 'string', 'format': 'email'}}}
        valid, errors, _ = validate_args(schema, {'email': 'user@example.com'})
        assert valid is True
        assert errors == []

    def test_format_email_invalid(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {'type': 'object', 'properties': {'email': {'type': 'string', 'format': 'email'}}}
        valid, errors, _ = validate_args(schema, {'email': 'not-an-email'})
        assert valid is False
        assert len(errors) == 1
        assert 'email' in errors[0]['path'] or errors[0]['path'] == 'email'

    def test_format_date_valid(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {'type': 'object', 'properties': {'d': {'type': 'string', 'format': 'date'}}}
        valid, errors, _ = validate_args(schema, {'d': '2024-01-15'})
        assert valid is True

    def test_format_date_invalid(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {'type': 'object', 'properties': {'d': {'type': 'string', 'format': 'date'}}}
        valid, errors, _ = validate_args(schema, {'d': 'not-a-date'})
        assert valid is False

    def test_const_applied_when_missing(self) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {'type': 'object', 'properties': {'mode': {'const': 'fixed'}}}
        result = apply_defaults(schema, {})
        assert result['mode'] == 'fixed'

    def test_const_not_overwritten_when_present(self) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {'type': 'object', 'properties': {'mode': {'const': 'fixed'}}}
        result = apply_defaults(schema, {'mode': 'other'})
        assert result['mode'] == 'other'

    def test_default_applied_when_missing(self) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {'type': 'object', 'properties': {'limit': {'type': 'integer', 'default': 10}}}
        result = apply_defaults(schema, {})
        assert result['limit'] == 10

    def test_default_not_overwritten_when_present(self) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {'type': 'object', 'properties': {'limit': {'type': 'integer', 'default': 10}}}
        result = apply_defaults(schema, {'limit': 5})
        assert result['limit'] == 5

    def test_nested_defaults_applied(self) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {
            'type': 'object',
            'properties': {
                'opts': {
                    'type': 'object',
                    'properties': {'verbose': {'type': 'boolean', 'default': False}},
                },
            },
        }
        result = apply_defaults(schema, {'opts': {}})
        assert result['opts']['verbose'] is False

    def test_nested_object_created_when_missing(self) -> None:
        from modules.mcp.validation import apply_defaults

        schema = {
            'type': 'object',
            'properties': {
                'opts': {
                    'type': 'object',
                    'properties': {'verbose': {'type': 'boolean', 'default': True}},
                },
            },
        }
        result = apply_defaults(schema, {})
        assert result['opts']['verbose'] is True

    def test_validate_returns_normalized_with_defaults(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'limit': {'type': 'integer', 'default': 20},
            },
            'required': ['name'],
        }
        valid, errors, normalized = validate_args(schema, {'name': 'test'})
        assert valid is True
        assert normalized['limit'] == 20

    def test_validate_returns_normalized_with_const(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'version': {'const': 'v1'},
            },
            'required': ['name'],
        }
        valid, errors, normalized = validate_args(schema, {'name': 'test'})
        assert valid is True
        assert normalized['version'] == 'v1'

    def test_validate_reports_actionable_required_error(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {
            'type': 'object',
            'properties': {'name': {'type': 'string'}},
            'required': ['name'],
        }
        valid, errors, _ = validate_args(schema, {})
        assert valid is False
        assert len(errors) == 1
        assert errors[0]['validator'] == 'required'
        assert 'Provide all required fields' in errors[0]['message']

    def test_validate_reports_actionable_additional_properties_error(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {
            'type': 'object',
            'properties': {'name': {'type': 'string'}},
            'additionalProperties': False,
        }
        valid, errors, _ = validate_args(schema, {'extra': 1})
        assert valid is False
        assert len(errors) == 1
        assert errors[0]['validator'] == 'additionalProperties'
        assert 'Remove unknown fields' in errors[0]['message']

    def test_validate_reports_actionable_enum_error(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {
            'type': 'object',
            'properties': {'mode': {'type': 'string', 'enum': ['a', 'b']}},
            'required': ['mode'],
        }
        valid, errors, _ = validate_args(schema, {'mode': 'c'})
        assert valid is False
        assert len(errors) == 1
        assert errors[0]['validator'] == 'enum'
        assert 'Use one of the documented enum values' in errors[0]['message']

    def test_validate_reports_actionable_type_error(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {
            'type': 'object',
            'properties': {'limit': {'type': 'integer'}},
            'required': ['limit'],
        }
        valid, errors, _ = validate_args(schema, {'limit': 'ten'})
        assert valid is False
        assert len(errors) == 1
        assert errors[0]['validator'] == 'type'
        assert 'Use the documented JSON type' in errors[0]['message']


class TestOpenAPIToJsonSchema:
    def test_bool_true_passthrough(self) -> None:
        result = _openapi_to_json_schema(True, {})
        assert result is True

    def test_bool_false_passthrough(self) -> None:
        result = _openapi_to_json_schema(False, {})
        assert result is False

    def test_none_passthrough(self) -> None:
        result = _openapi_to_json_schema(None, {})
        assert result is None

    def test_dict_passthrough(self) -> None:
        result = _openapi_to_json_schema({'type': 'string'}, {})
        assert result == {'type': 'string'}

    def test_additional_properties_true(self) -> None:
        schema = {'type': 'object', 'additionalProperties': True}
        result = _openapi_to_json_schema(schema, {})
        assert result == {'type': 'object', 'additionalProperties': True}

    def test_additional_properties_false(self) -> None:
        schema = {'type': 'object', 'additionalProperties': False}
        result = _openapi_to_json_schema(schema, {})
        assert result == {'type': 'object', 'additionalProperties': False}

    def test_additional_properties_dict(self) -> None:
        schema = {'type': 'object', 'additionalProperties': {'type': 'string'}}
        result = _openapi_to_json_schema(schema, {})
        assert result == {'type': 'object', 'additionalProperties': {'type': 'string'}}

    def test_additional_properties_ref_schema(self) -> None:
        components = {
            'schemas': {
                'ExtraValue': {
                    'type': 'object',
                    'properties': {'name': {'type': 'string'}},
                    'required': ['name'],
                    'additionalProperties': False,
                },
            },
        }
        schema = {'type': 'object', 'additionalProperties': {'$ref': '#/components/schemas/ExtraValue'}}
        result = _openapi_to_json_schema(schema, components)
        assert result == {
            'type': 'object',
            'additionalProperties': {
                'type': 'object',
                'properties': {'name': {'type': 'string'}},
                'required': ['name'],
                'additionalProperties': False,
            },
        }

    def test_items_bool(self) -> None:
        schema = {'type': 'array', 'items': True}
        result = _openapi_to_json_schema(schema, {})
        assert result == {'type': 'array', 'items': True}

    def test_items_dict(self) -> None:
        schema = {'type': 'array', 'items': {'type': 'integer'}}
        result = _openapi_to_json_schema(schema, {})
        assert result == {'type': 'array', 'items': {'type': 'integer'}}

    def test_ref_resolution(self) -> None:
        components = {'schemas': {'Foo': {'type': 'string'}}}
        schema = {'$ref': '#/components/schemas/Foo'}
        result = _openapi_to_json_schema(schema, components)
        assert result == {'type': 'string'}

    def test_title_stripped(self) -> None:
        schema = {'type': 'string', 'title': 'My Field'}
        result = _openapi_to_json_schema(schema, {})
        assert 'title' not in result

    def test_build_tool_additional_properties_true(self) -> None:
        op = {
            'summary': 'Test',
            'requestBody': {'content': {'application/json': {'schema': {'type': 'object', 'additionalProperties': True}}}},
        }
        tool = _build_tool({'method': 'POST', 'path': '/api/v1/test', 'operation': op}, {})
        payload = tool['input_schema']['properties']['payload']
        assert payload == {'type': 'object', 'additionalProperties': True}

    def test_build_tool_additional_properties_false(self) -> None:
        op = {
            'summary': 'Test',
            'requestBody': {'content': {'application/json': {'schema': {'type': 'object', 'additionalProperties': False}}}},
        }
        tool = _build_tool({'method': 'POST', 'path': '/api/v1/test', 'operation': op}, {})
        payload = tool['input_schema']['properties']['payload']
        assert payload == {'type': 'object', 'additionalProperties': False}

    def test_build_tool_sets_top_level_additional_properties_false(self) -> None:
        op = {'summary': 'Test', 'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}]}
        tool = _build_tool({'method': 'GET', 'path': '/api/v1/test/{id}', 'operation': op}, {})
        assert tool['input_schema']['additionalProperties'] is False

    def test_build_tool_includes_arg_metadata(self) -> None:
        op = {
            'summary': 'Test',
            'parameters': [
                {'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}, 'description': 'Resource ID'},
                {'name': 'limit', 'in': 'query', 'required': False, 'schema': {'type': 'integer', 'default': 10}},
            ],
            'requestBody': {
                'required': True,
                'description': 'Body payload',
                'content': {'application/json': {'schema': {'type': 'object', 'properties': {'x': {'type': 'string'}}}}},
            },
        }
        tool = _build_tool({'method': 'POST', 'path': '/api/v1/test/{id}', 'operation': op}, {})
        meta = tool['arg_metadata']
        assert meta['path'][0]['name'] == 'id'
        assert meta['query'][0]['name'] == 'limit'
        assert meta['payload']['required'] is True
        assert meta['payload']['content_type'] == 'application/json'
        assert 'payload' in tool['input_schema']['required']

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
        output = tool['output_schema']
        assert output is not None
        assert output['status_code'] == '200'
        assert output['content_type'] == 'application/json'
        assert output['schema'] == {
            'type': 'object',
            'properties': {'ok': {'type': 'boolean'}},
            'required': ['ok'],
        }
        assert output['response_model'] == 'TestResponse'

    def test_build_tool_output_schema_is_none_when_success_schema_missing(self) -> None:
        op = {
            'summary': 'Test',
            'responses': {
                '204': {'description': 'No content'},
                '400': {'description': 'Bad request'},
            },
        }
        tool = _build_tool({'method': 'GET', 'path': '/api/v1/test', 'operation': op}, {})
        assert tool['output_schema'] is None


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
            {
                'id': 'broken_mutating_tool',
                'method': 'POST',
                'path': '/api/v1/test/{item_id}',
                'description': 'Broken for confirm test',
                'safety': 'mutating',
                'confirm_required': False,
                'input_schema': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
                'arg_metadata': {'path': [], 'query': [], 'payload': None},
                'tags': [],
            },
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


class TestDeterministicToolMetadata:
    def test_decorator_preserves_marker_truthiness(self) -> None:
        @deterministic_tool
        def endpoint() -> None:
            pass

        assert bool(getattr(endpoint, MCP_TOOL_MARKER)) is True

    def test_decorator_attaches_structured_metadata(self) -> None:
        @deterministic_tool(confirm_required=True)
        def endpoint(name: str, limit: int = 10) -> None:
            """Demo endpoint."""

        meta = get_mcp_tool_meta(endpoint)
        assert isinstance(meta, dict)
        assert meta['name'] == 'endpoint'
        assert meta['docstring'] == 'Demo endpoint.'
        assert meta['confirm_required'] is True
        assert isinstance(meta['inputs'], list)
        assert meta['inputs'][0]['name'] == 'name'
        assert meta['inputs'][0]['required'] is True
        assert meta['inputs'][1]['name'] == 'limit'
        assert meta['inputs'][1]['required'] is False

    def test_metadata_lookup_is_wrapper_aware(self) -> None:
        from functools import wraps

        def wrap(fn):
            @wraps(fn)
            def inner(*args, **kwargs):
                return fn(*args, **kwargs)

            return inner

        @wrap
        @deterministic_tool
        def endpoint(value: str) -> None:
            """Wrapped endpoint."""

        meta = get_mcp_tool_meta(endpoint)
        assert isinstance(meta, dict)
        assert meta['name'] == 'endpoint'
        assert meta['docstring'] == 'Wrapped endpoint.'
        assert meta['inputs'][0]['name'] == 'value'


class TestRouterDecoratorOnboarding:
    def test_mcp_defaults_to_off(self) -> None:
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        leaf = MCPRouter(prefix='/demo', tags=['demo'])

        @leaf.delete('/item/{item_id}')
        def endpoint(item_id: str) -> dict[str, str]:
            """Delete item endpoint."""
            return {'id': item_id}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        tools = reg.build_tool_registry(app)
        assert tools == []

    def test_mcp_true_onboards_route(self) -> None:
        from fastapi import APIRouter, FastAPI

        from modules.mcp import registry as reg

        leaf = MCPRouter(prefix='/demo', tags=['demo'])

        @leaf.delete('/item/{item_id}', mcp=True)
        def endpoint(item_id: str) -> dict[str, str]:
            """Delete item endpoint."""
            return {'id': item_id}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0]['id'] == 'endpoint'

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
        assert tools[0]['confirm_required'] is False

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
        assert tools[0]['id'] == 'stable_custom_tool'

    def test_description_prefers_docstring_when_operation_text_missing(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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
        assert tools[0]['description'] == 'Docstring text for MCP description.'


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
        from fastapi.routing import APIRoute

        leaf = MCPRouter(prefix='/leaf', tags=['leaf'])

        @leaf.get('/value', mcp=True)
        def value() -> dict[str, str]:
            return {'ok': 'yes'}

        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)

        route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == '/api/v1/leaf/value')
        meta = get_mcp_route_meta(route)
        assert isinstance(meta, dict)
        assert meta['name'] == 'value'

    def test_registry_prefers_route_registered_metadata(self) -> None:
        from fastapi import APIRouter, FastAPI
        from fastapi.routing import APIRoute

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

        app_route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == '/api/v1/demo/item/{item_id}')
        app_meta = dict(get_mcp_route_meta(app_route) or {})
        app_meta['confirm_required'] = False
        app_meta['name'] = 'stable_override_name'
        setattr(app_route, MCP_ROUTE_META, app_meta)

        tools = reg.build_tool_registry(app)
        assert len(tools) == 1
        assert tools[0]['id'] == 'stable_override_name'
        assert tools[0]['confirm_required'] is False

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
        ids = {tool['id'] for tool in tools}
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
            {
                'id': 'broken_tool',
                'method': 'GET',
                'path': '/api/v1/test/{item_id}',
                'description': 'Broken for test',
                'safety': 'safe',
                'confirm_required': False,
                'input_schema': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
                'arg_metadata': {'path': [], 'query': [], 'payload': None},
                'tags': [],
            },
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
            return {'session_token': x_session_token, 'namespace': x_namespace or 'default'}

        context = build_tool_context({'X-Session-Token': 'session-1', 'X-Namespace': 'alpha'})
        result = await call_tool(app, 'GET', '/api/v1/test/context', {}, context)
        assert result['ok'] is True
        assert result['body'] == {'session_token': 'session-1', 'namespace': 'alpha'}


class TestCheckSchemaSupported:
    def test_valid_schema_returns_empty(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}
        assert check_schema_supported(schema) == []

    def test_unknown_top_level_keyword(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'object', 'x-custom-extension': 'foo'}
        issues = check_schema_supported(schema)
        assert any('x-custom-extension' in i for i in issues)

    def test_unsupported_type_flagged(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'custom-unknown-type'}
        issues = check_schema_supported(schema)
        assert any('custom-unknown-type' in i for i in issues)

    def test_nested_unknown_keyword_in_property(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'object', 'properties': {'x': {'type': 'string', 'x-secret': True}}}
        issues = check_schema_supported(schema)
        assert any('x-secret' in i for i in issues)

    def test_anyof_with_unknown_keyword(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'anyOf': [{'type': 'string', 'x-unknown': 1}]}
        issues = check_schema_supported(schema)
        assert any('x-unknown' in i for i in issues)

    def test_items_schema_valid(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'array', 'items': {'type': 'string'}}
        assert check_schema_supported(schema) == []

    def test_items_schema_with_enum(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'array', 'items': {'type': 'string', 'enum': ['a', 'b']}}
        assert check_schema_supported(schema) == []

    def test_items_array_of_schemas(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'array', 'items': [{'type': 'string'}, {'type': 'integer'}]}
        assert check_schema_supported(schema) == []

    def test_if_then_else_valid(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'if': {'type': 'string'}, 'then': {'minLength': 1}, 'else': {'type': 'integer'}}
        assert check_schema_supported(schema) == []

    def test_not_valid(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'not': {'type': 'string'}}
        assert check_schema_supported(schema) == []

    def test_pattern_properties_valid(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'object', 'patternProperties': {'^x_': {'type': 'string'}}}
        assert check_schema_supported(schema) == []

    def test_additional_properties_schema_valid(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'object', 'additionalProperties': {'type': 'integer'}}
        assert check_schema_supported(schema) == []

    def test_validate_route_returns_invalid_for_unsupported_schema(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'object', 'x-unsupported': True}
        issues = check_schema_supported(schema)
        assert len(issues) > 0
        assert any('x-unsupported' in i for i in issues)


class TestMCPCapabilities:
    def test_capabilities_all_tools_returns_list(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/capabilities', json={})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_capabilities_entries_have_required_fields(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/capabilities', json={})
        data = resp.json()
        for entry in data:
            assert 'tool_id' in entry
            assert 'supported' in entry
            assert 'issues' in entry
            assert isinstance(entry['supported'], bool)
            assert isinstance(entry['issues'], list)

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

    def test_capabilities_empty_tool_ids_returns_all(self, client: TestClient) -> None:
        tools_resp = client.get('/api/v1/mcp/tools')
        all_count = len(tools_resp.json())

        resp = client.post('/api/v1/mcp/capabilities', json={'tool_ids': []})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == all_count

    def test_capabilities_supported_tools_have_empty_issues(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/capabilities', json={})
        data = resp.json()
        for entry in data:
            if entry['supported']:
                assert entry['issues'] == []

    def test_capabilities_unsupported_tool_has_issues(self) -> None:
        from modules.mcp.validation import check_schema_supported

        schema = {'type': 'object', 'x-unsupported': True}
        issues = check_schema_supported(schema)
        assert len(issues) > 0
        assert any('x-unsupported' in i for i in issues)

    def test_capabilities_unknown_tool_id_excluded(self, client: TestClient) -> None:
        resp = client.post('/api/v1/mcp/capabilities', json={'tool_ids': ['nonexistent_tool_xyz']})
        assert resp.status_code == 200
        data = resp.json()
        assert data == []


class TestBuildRegistryFailFast:
    def test_raises_on_unsupported_schema(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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

    def test_undecorated_route_excluded(self) -> None:
        from fastapi import FastAPI

        from modules.mcp import registry as reg

        router = MCPRouter(prefix='/api/v1/undecorated', tags=['undecorated'])

        @router.get('/endpoint')
        def undecorated_endpoint() -> dict[str, str]:
            return {'ok': 'no'}

        app = FastAPI()
        app.include_router(router)

        tools = reg.build_tool_registry(app)
        assert tools == []

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
        assert tools[0]['id'] == 'decorated_endpoint'
        assert tools[0]['path'] == '/api/v1/mixed/decorated'


class TestStartupEnforcement:
    def test_startup_raises_on_unsupported_schema(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import pytest
        from fastapi import APIRouter, FastAPI

        from modules.mcp.routes import get_registry

        def fake_openapi() -> dict:
            return {
                'paths': {
                    '/api/v1/startup/check': {
                        'get': {
                            'summary': 'StartupCheck',
                            'parameters': [
                                {
                                    'name': 'p',
                                    'in': 'query',
                                    'schema': {'type': 'string', 'x-bad-ext': True},
                                },
                            ],
                        },
                    },
                },
                'components': {},
            }

        def startup_check() -> None:
            pass

        leaf = MCPRouter(prefix='/startup', tags=['startup'])
        leaf.add_api_route('/check', startup_check, methods=['GET'], mcp=True)
        v1 = APIRouter(prefix='/api/v1')
        v1.include_router(leaf)
        app = FastAPI()
        app.include_router(v1)
        monkeypatch.setattr(app, 'openapi', fake_openapi)

        with pytest.raises(ValueError, match='startup_check'):
            get_registry(app)

    def test_startup_populates_cache_so_no_double_build(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from fastapi import FastAPI

        import modules.mcp.routes as routes_mod
        from modules.mcp.routes import get_registry

        build_calls: list[int] = []
        original_build = routes_mod.build_tool_registry

        def counting_build(a: FastAPI) -> list[dict]:
            build_calls.append(1)
            return original_build(a)

        monkeypatch.setattr(routes_mod, 'build_tool_registry', counting_build)

        app = FastAPI()

        get_registry(app)
        get_registry(app)
        assert len(build_calls) == 1
