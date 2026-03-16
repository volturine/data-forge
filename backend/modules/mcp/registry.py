"""MCP tool registry — discovers /api/v1 routes and exposes them as tools."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

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
    for key in ('properties', 'additionalProperties'):
        if isinstance(result.get(key), dict):
            result[key] = {k: _openapi_to_json_schema(v, components) for k, v in result[key].items()}
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


def _build_tool(route_data: dict, components: dict) -> dict:
    method = route_data['method']
    path = route_data['path']
    op = route_data['operation']

    description = op.get('description') or op.get('summary') or f'{method} {path}'

    properties: dict[str, Any] = {}
    required: list[str] = []

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
        if param.get('required', p_in == 'path'):
            required.append(name)

    body_content = op.get('requestBody', {}).get('content', {})
    body_schema: dict | None = None
    for mime in ('application/json', 'multipart/form-data', 'application/x-www-form-urlencoded'):
        if mime in body_content:
            raw = body_content[mime].get('schema', {})
            body_schema = _openapi_to_json_schema(raw, components)
            break
    if body_schema:
        properties['payload'] = body_schema

    tool_schema: dict[str, Any] = {'type': 'object', 'properties': properties}
    if required:
        tool_schema['required'] = required

    tool_id = route_data.get('name') or f'{method.lower()}_{path.replace("/", "_").replace("{", "").replace("}", "").strip("_")}'

    return {
        'id': tool_id,
        'method': method,
        'path': path,
        'description': description,
        'safety': 'safe' if method in SAFE_METHODS else 'mutating',
        'confirm_required': _requires_confirm(method, path),
        'input_schema': tool_schema,
        'tags': op.get('tags', []),
    }


def _marked_routes(app: FastAPI) -> dict[tuple[str, str], str]:
    """Return mapping of (METHOD, path) -> endpoint function name for marked routes."""
    marked: dict[tuple[str, str], str] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not getattr(route.endpoint, '__mcp_tool__', False):
            continue
        name = route.endpoint.__name__
        for method in route.methods or []:
            marked[(method.upper(), route.path)] = name
    return marked


def build_tool_registry(app: FastAPI) -> list[dict]:
    """Extract marked /api/v1 routes from the app's OpenAPI schema and return tool defs."""
    allowed = _marked_routes(app)
    schema = app.openapi()
    components = schema.get('components', {})
    paths = schema.get('paths', {})
    tools = []
    for path, path_item in paths.items():
        if not path.startswith('/api/v1/'):
            continue
        if '/mcp/' in path or '/ai/chat' in path:
            continue
        for method, op in path_item.items():
            if method.upper() not in {*SAFE_METHODS, *MUTATING_METHODS}:
                continue
            if not isinstance(op, dict):
                continue
            if (method.upper(), path) not in allowed:
                continue
            tool_name = allowed[(method.upper(), path)]
            tool = _build_tool({'method': method.upper(), 'path': path, 'operation': op, 'name': tool_name}, components)
            issues = check_schema_supported(tool['input_schema'])
            if issues:
                raise ValueError(f'Tool {tool["id"]!r} has unsupported schema: {", ".join(issues)}')
            tools.append(tool)
    return tools
