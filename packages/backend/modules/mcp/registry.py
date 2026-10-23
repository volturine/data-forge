"""MCP tool registry built from MCP-onboarded FastAPI routes."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from modules.mcp.models import MCPHttpMethod, MCPToolDefinition
from modules.mcp.router import get_mcp_route_meta
from modules.mcp.tool_output import format_output_hint, top_level_output_fields


def _route_openapi_operation(route: APIRoute, schema: dict[str, Any], path: str) -> tuple[str, dict[str, Any]] | None:
    path_item = schema.get('paths', {}).get(path)
    if not isinstance(path_item, dict):
        return None
    allowed_methods = route.methods or set()
    for method, op in path_item.items():
        if method.upper() in allowed_methods and isinstance(op, dict):
            return method.upper(), op
    return None


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
    success = sorted(
        [(code, r) for code, r in responses.items() if isinstance(code, str) and code.startswith('2') and code != 'default' and isinstance(r, dict)],
        key=lambda pair: int(pair[0]) if pair[0].isdigit() else 999,
    )
    for code, response in success:
        content = response.get('content')
        if not isinstance(content, dict):
            continue
        if isinstance(content.get('application/json'), dict):
            mime: str | None = 'application/json'
        else:
            mime = next((m for m, item in content.items() if isinstance(m, str) and isinstance(item, dict)), None)
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


def _build_tool(route_data: dict, components: dict) -> MCPToolDefinition:
    method = MCPHttpMethod.from_route_method(route_data['method'])
    if method is None:
        raise ValueError(f'Unsupported MCP route method: {route_data["method"]!r}')
    path = route_data['path']
    op = route_data['operation']
    onboard = route_data.get('meta', {})
    route = route_data.get('route')

    text = op.get('description') or op.get('summary') or onboard.get('docstring')
    description = text if isinstance(text, str) and text.strip() else f'{method} {path}'
    # Destructive routes opt in with `mcp_confirm_required=True` on the route itself.
    confirm_required = onboard.get('confirm_required') is True

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
        item = {
            'name': name,
            'required': is_required,
            'description': param.get('description', ''),
            'schema': schema,
        }
        (path_params if p_in == 'path' else query_params).append(item)

    request_body = op.get('requestBody', {})
    body_content = request_body.get('content', {})
    body_mime = next((mime for mime in ('application/json', 'multipart/form-data', 'application/x-www-form-urlencoded') if mime in body_content), None)
    body_schema = _openapi_to_json_schema(body_content[body_mime].get('schema', {}), components) if body_mime is not None else None
    body_required = bool(request_body.get('required', False))
    if body_schema:
        properties['payload'] = body_schema
        if body_required and 'payload' not in required:
            required.append('payload')

    tool_schema: dict[str, Any] = {
        'type': 'object',
        'properties': properties,
        'additionalProperties': False,
    }
    if required:
        tool_schema['required'] = required

    tool_id = route_data.get('name') or f'{method.value.lower()}_{path.replace("/", "_").replace("{", "").replace("}", "").strip("_")}'

    return MCPToolDefinition(
        id=tool_id,
        method=method,
        path=path,
        description=description,
        confirm_required=confirm_required,
        input_schema=tool_schema,
        arg_metadata={
            'path': path_params,
            'query': query_params,
            'payload': {
                'required': body_required,
                'content_type': body_mime,
                'description': request_body.get('description', ''),
            }
            if body_schema is not None
            else None,
        },
        output_schema=_output_schema(op, onboard, components),
        tags=_tag_list(route, op) if isinstance(route, APIRoute) else op.get('tags', []),
    )


def build_tool_registry(app: FastAPI) -> list[MCPToolDefinition]:
    """Extract MCPRouter mcp=True onboarded routes as MCP tool definitions."""
    schema = app.openapi()
    components = schema.get('components', {})
    tools: list[MCPToolDefinition] = []
    for route_context in iter_route_contexts(list(app.routes)):
        route = route_context.original_route
        if not isinstance(route, APIRoute):
            continue
        meta = get_mcp_route_meta(route)
        # Routes in this codebase are single-method; MCP exposes one tool per route.
        if meta is None or not any(MCPHttpMethod.from_route_method(raw) is not None for raw in route.methods or set()):
            continue
        path = route_context.path or route.path
        operation = _route_openapi_operation(route, schema, path)
        if operation is None:
            continue
        method, op = operation
        tool = _build_tool(
            {
                'method': method,
                'path': path,
                'operation': op,
                'name': meta.get('name') or getattr(route.endpoint, '__name__', route.name),
                'meta': dict(meta),
                'route': route,
            },
            components,
        )
        issues = tool.schema_support_issues()
        if issues:
            raise ValueError(f'Tool {tool.id!r} has unsupported schema: {", ".join(issues)}')
        tools.append(tool)
    return tools
