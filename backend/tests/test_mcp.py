"""Tests for MCP tool listing and preview/confirm flow."""

from fastapi.testclient import TestClient

from modules.mcp.registry import _build_tool, _openapi_to_json_schema


class TestMCPToolListing:
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
        post_tool = next((t for t in tools if t['method'] == 'POST'), None)
        assert post_tool is not None

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
        response = client.get('/api/v1/mcp/tools')
        tools = response.json()
        post_tool = next((t for t in tools if t['method'] == 'POST'), None)
        assert post_tool is not None

        call_resp = client.post('/api/v1/mcp/call', json={'tool_id': post_tool['id'], 'args': {}})
        token = call_resp.json()['token']

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
        post_tool = next((t for t in tools if t['method'] == 'POST'), None)
        assert post_tool is not None

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
            return
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
            return
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
            return
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

    def test_format_uri_valid(self) -> None:
        from modules.mcp.validation import validate_args

        schema = {'type': 'object', 'properties': {'url': {'type': 'string', 'format': 'uri'}}}
        valid, errors, _ = validate_args(schema, {'url': 'https://example.com'})
        assert valid is True

    def test_format_uri_invalid(self) -> None:
        import pytest
        from jsonschema import FormatChecker

        if 'uri' not in FormatChecker().checkers:
            pytest.skip('uri format checker not available (requires rfc3986 extra)')
        from modules.mcp.validation import validate_args

        schema = {'type': 'object', 'properties': {'url': {'type': 'string', 'format': 'uri'}}}
        valid, errors, _ = validate_args(schema, {'url': 'not a uri'})
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
                }
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
                }
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
        from fastapi import FastAPI
        from fastapi.routing import APIRoute

        from modules.mcp import registry as reg
        from modules.mcp.decorators import deterministic_tool

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
                                }
                            ],
                        }
                    }
                },
                'components': {},
            }

        @deterministic_tool
        def fake_endpoint() -> None:
            pass

        app = FastAPI()
        app.routes.append(APIRoute('/api/v1/fake/endpoint', fake_endpoint, methods=['GET']))
        monkeypatch.setattr(app, 'openapi', fake_openapi)

        with pytest.raises(ValueError, match='fake_endpoint'):
            reg.build_tool_registry(app)

    def test_undecorated_route_excluded(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from fastapi import FastAPI
        from fastapi.routing import APIRoute

        from modules.mcp import registry as reg

        def fake_openapi() -> dict:
            return {
                'paths': {
                    '/api/v1/undecorated/endpoint': {
                        'get': {
                            'summary': 'Undecorated',
                            'parameters': [],
                        }
                    }
                },
                'components': {},
            }

        def undecorated_endpoint() -> None:
            pass

        app = FastAPI()
        app.routes.append(APIRoute('/api/v1/undecorated/endpoint', undecorated_endpoint, methods=['GET']))
        monkeypatch.setattr(app, 'openapi', fake_openapi)

        tools = reg.build_tool_registry(app)
        assert tools == []


class TestStartupEnforcement:
    def test_startup_raises_on_unsupported_schema(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        import pytest
        from fastapi import FastAPI
        from fastapi.routing import APIRoute

        from modules.mcp.decorators import deterministic_tool
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
                                }
                            ],
                        }
                    }
                },
                'components': {},
            }

        @deterministic_tool
        def startup_check() -> None:
            pass

        app = FastAPI()
        app.routes.append(APIRoute('/api/v1/startup/check', startup_check, methods=['GET']))
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
