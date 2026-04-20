"""MCP tool registry built from MCP-onboarded FastAPI routes."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from modules.mcp.router import get_mcp_route_meta
from modules.mcp.tool_output import format_output_hint, top_level_output_fields
from modules.mcp.validation import check_schema_supported

SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})
MUTATING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

CONFIRM_REQUIRED_PATTERNS: list[tuple[str, str]] = [
    ('DELETE', r'^/api/v1/datasource/'),
    ('DELETE', r'^/api/v1/scheduler/'),
    ('DELETE', r'^/api/v1/healthchecks/'),
    ('DELETE', r'^/api/v1/analysis/'),
]


def _requires_confirm(method: str, path: str) -> bool:
    return any(method == m and re.match(pattern, path) for m, pattern in CONFIRM_REQUIRED_PATTERNS)


def _route_openapi_operation(route: APIRoute, schema: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    path_item = schema.get('paths', {}).get(route.path)
    if not isinstance(path_item, dict):
        return None
    allowed_methods = route.methods or set()
    for method in path_item:
        method_upper = method.upper()
        if method_upper not in allowed_methods:
            continue
        op = path_item.get(method)
        if not isinstance(op, dict):
            continue
        return method_upper, op
    return None


def _description(op: dict[str, Any], meta: dict[str, Any], method: str, path: str) -> str:
    text = op.get('description') or op.get('summary') or meta.get('docstring')
    if isinstance(text, str) and text.strip():
        return text
    return f'{method} {path}'


def _confirm_required(method: str, path: str, meta: dict[str, Any]) -> bool:
    value = meta.get('confirm_required')
    if isinstance(value, bool):
        return value
    return _requires_confirm(method, path)


def _tag_list(route: APIRoute, op: dict[str, Any]) -> list[str]:
    tags = op.get('tags')
    if isinstance(tags, list):
        return [t for t in tags if isinstance(t, str)]
    route_tags = route.tags or []
    return [t for t in route_tags if isinstance(t, str)]


def _openapi_to_json_schema(schema_ref: Any, components: dict) -> Any:
    """Resolve a single OpenAPI schema (possibly $ref) to a plain JSON Schema dict."""
    if not isinstance(schema_ref, dict):
        return schema_ref
    if '$ref' in schema_ref:
        ref_path = schema_ref['$ref'].lstrip('#/').split('/')
        resolved: Any = components
        for part in ref_path[1:]:
            resolved = resolved.get(part, {})
        return _openapi_to_json_schema(resolved, components)
    result = dict(schema_ref)
    for k in ('title', 'x-orderIndex'):
        result.pop(k, None)
    if isinstance(result.get('properties'), dict):
        result['properties'] = {k: _openapi_to_json_schema(v, components) for k, v in result['properties'].items()}
    if isinstance(result.get('additionalProperties'), dict):
        result['additionalProperties'] = _openapi_to_json_schema(result['additionalProperties'], components)
    if 'items' in result:
        result['items'] = _openapi_to_json_schema(result['items'], components)
    if 'allOf' in result:
        parts = [_openapi_to_json_schema(p, components) for p in result['allOf']]
        if len(parts) == 1:
            return parts[0]
        result['allOf'] = parts
    if 'anyOf' in result:
        result['anyOf'] = [_openapi_to_json_schema(p, components) for p in result['anyOf']]
    return result


def _output_schema(op: dict[str, Any], meta: dict[str, Any], components: dict) -> dict[str, Any] | None:
    responses = op.get('responses')
    if not isinstance(responses, dict):
        return None

    def pick_mime(content: dict) -> str | None:
        if isinstance(content.get('application/json'), dict):
            return 'application/json'
        return next((m for m, item in content.items() if isinstance(m, str) and isinstance(item, dict)), None)

    success = sorted(
        [
            (code, r)
            for code, r in responses.items()
            if isinstance(code, str) and code.startswith('2') and code != 'default' and isinstance(r, dict)
        ],
        key=lambda pair: int(pair[0]) if pair[0].isdigit() else 999,
    )
    for code, response in success:
        content = response.get('content')
        if not isinstance(content, dict):
            continue
        mime = pick_mime(content)
        if mime is None:
            continue
        schema = _openapi_to_json_schema(content[mime].get('schema'), components)
        if schema is None:
            continue
        output = {
            'status_code': code,
            'content_type': mime,
            'schema': schema,
            'response_model': meta.get('response_model'),
            'fields': top_level_output_fields(schema),
        }
        output['hint'] = format_output_hint(output)
        return output
    return None


def _build_tool(route_data: dict, components: dict) -> dict:
    method = route_data['method']
    path = route_data['path']
    op = route_data['operation']
    onboard = route_data.get('meta', {})
    route = route_data.get('route')

    description = _description(op, onboard, method, path)

    properties: dict[str, Any] = {}
    required: list[str] = []
    path_params: list[dict[str, Any]] = []
    query_params: list[dict[str, Any]] = []

    for param in op.get('parameters', []):
        p_in = param.get('in', '')
        if p_in not in ('path', 'query'):
            continue
        name = param['name']
        raw_schema = _openapi_to_json_schema(param.get('schema', {'type': 'string'}), components)
        schema: dict[str, Any] = raw_schema if isinstance(raw_schema, dict) else {}
        if param.get('description'):
            schema['description'] = param['description']
        properties[name] = schema
        is_required = bool(param.get('required', p_in == 'path'))
        if is_required and name not in required:
            required.append(name)
        item = {'name': name, 'required': is_required, 'description': param.get('description', ''), 'schema': schema}
        if p_in == 'path':
            path_params.append(item)
        if p_in == 'query':
            query_params.append(item)

    body_content = op.get('requestBody', {}).get('content', {})
    body_schema: dict | None = None
    body_mime: str | None = None
    for mime in ('application/json', 'multipart/form-data', 'application/x-www-form-urlencoded'):
        if mime in body_content:
            raw = body_content[mime].get('schema', {})
            body_schema = _openapi_to_json_schema(raw, components)
            body_mime = mime
            break
    body_required = bool(op.get('requestBody', {}).get('required', False))
    if body_schema:
        properties['payload'] = body_schema
        if body_required and 'payload' not in required:
            required.append('payload')

    tool_schema: dict[str, Any] = {'type': 'object', 'properties': properties, 'additionalProperties': False}
    if required:
        tool_schema['required'] = required

    tool_id = route_data.get('name') or f'{method.lower()}_{path.replace("/", "_").replace("{", "").replace("}", "").strip("_")}'

    tags = op.get('tags', [])
    if isinstance(route, APIRoute):
        tags = _tag_list(route, op)
    output_schema = _output_schema(op, onboard, components)

    return {
        'id': tool_id,
        'method': method,
        'path': path,
        'description': description,
        'safety': 'safe' if method in SAFE_METHODS else 'mutating',
        'confirm_required': _confirm_required(method, path, onboard),
        'input_schema': tool_schema,
        'arg_metadata': {
            'path': path_params,
            'query': query_params,
            'payload': {
                'required': body_required,
                'content_type': body_mime,
                'description': op.get('requestBody', {}).get('description', ''),
            }
            if body_schema is not None
            else None,
        },
        'output_schema': output_schema,
        'tags': tags,
    }


def _marked_routes(app: FastAPI) -> list[dict[str, Any]]:
    """Return metadata for routes onboarded via MCP route registration."""
    allowed_methods = SAFE_METHODS | MUTATING_METHODS
    marked: list[dict[str, Any]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        route_meta = get_mcp_route_meta(route)
        if not isinstance(route_meta, dict):
            continue
        meta = dict(route_meta)
        if not route.path.startswith('/api/v1/'):
            continue
        # Routes in this codebase are single-method; MCP exposes one tool per route.
        method = next((m.upper() for m in (route.methods or set()) if m.upper() in allowed_methods), None)
        if method is None:
            continue
        endpoint = route.endpoint
        fallback = endpoint.__name__ if hasattr(endpoint, '__name__') else route.name
        name = meta.get('name') or fallback
        marked.append({'route': route, 'method': method, 'name': name, 'meta': meta})
    return marked


def build_tool_registry(app: FastAPI) -> list[dict]:
    """Extract MCPRouter mcp=True onboarded routes as MCP tool definitions."""
    marked = _marked_routes(app)
    schema = app.openapi()
    components = schema.get('components', {})
    tools: list[dict[str, Any]] = []
    for item in marked:
        route = item['route']
        op_item = _route_openapi_operation(route, schema)
        if op_item is None:
            continue
        method, op = op_item
        tool = _build_tool(
            {
                'method': method,
                'path': route.path,
                'operation': op,
                'name': item['name'],
                'meta': item['meta'],
                'route': route,
            },
            components,
        )
        issues = check_schema_supported(tool['input_schema'])
        if issues:
            raise ValueError(f'Tool {tool["id"]!r} has unsupported schema: {", ".join(issues)}')
        tools.append(tool)
    return tools
