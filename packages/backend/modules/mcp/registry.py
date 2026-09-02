"""MCP tool registry built from MCP-onboarded FastAPI routes."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from modules.mcp.models import MCPHttpMethod, MCPToolDefinition
from modules.mcp.router import get_mcp_route_meta
from modules.mcp.tool_output import format_output_hint, top_level_output_fields


def _route_openapi_operation(route: APIRoute, schema: dict[str, Any], effective_path: str | None = None) -> tuple[str, dict[str, Any]] | None:
    lookup_path = effective_path or route.path
    path_item = schema.get('paths', {}).get(lookup_path)
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


def _description(op: dict[str, Any], meta: dict[str, Any], method: MCPHttpMethod, path: str) -> str:
    text = op.get('description') or op.get('summary') or meta.get('docstring')
    if isinstance(text, str) and text.strip():
        return text
    return f'{method} {path}'


def _confirm_required(method: MCPHttpMethod, path: str, meta: dict[str, Any]) -> bool:
    value = meta.get('confirm_required')
    if isinstance(value, bool):
        return value
    return method.requires_confirmation_for_path(path)


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
        return next(
            (m for m, item in content.items() if isinstance(m, str) and isinstance(item, dict)),
            None,
        )

    success = sorted(
        [(code, r) for code, r in responses.items() if isinstance(code, str) and code.startswith('2') and code != 'default' and isinstance(r, dict)],
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


def _build_tool(route_data: dict, components: dict) -> MCPToolDefinition:
    method = MCPHttpMethod.from_route_method(route_data['method'])
    if method is None:
        raise ValueError(f'Unsupported MCP route method: {route_data["method"]!r}')
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
        item = {
            'name': name,
            'required': is_required,
            'description': param.get('description', ''),
            'schema': schema,
        }
        if p_in == 'path':
            path_params.append(item)
        if p_in == 'query':
            query_params.append(item)

    body_content = op.get('requestBody', {}).get('content', {})
    body_schema: dict | None = None
    body_mime: str | None = None
    for mime in (
        'application/json',
        'multipart/form-data',
        'application/x-www-form-urlencoded',
    ):
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

    tool_schema: dict[str, Any] = {
        'type': 'object',
        'properties': properties,
        'additionalProperties': False,
    }
    if required:
        tool_schema['required'] = required

    tool_id = route_data.get('name') or f'{method.value.lower()}_{path.replace("/", "_").replace("{", "").replace("}", "").strip("_")}'

    tags = op.get('tags', [])
    if isinstance(route, APIRoute):
        tags = _tag_list(route, op)
    output_schema = _output_schema(op, onboard, components)

    return MCPToolDefinition(
        id=tool_id,
        method=method,
        path=path,
        description=description,
        confirm_required=_confirm_required(method, path, onboard),
        input_schema=tool_schema,
        arg_metadata={
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
        output_schema=output_schema,
        tags=tags,
    )


def _collect_api_routes(routes: list[Any]) -> list[tuple[APIRoute, str]]:
    """Recursively collect (APIRoute, effective_path) pairs, unwrapping _IncludedRouter wrappers.

    FastAPI ≥0.137 stores sub-routers as ``_IncludedRouter`` nodes instead of
    flattening them into ``app.routes``.  Each ``_IncludedRouter`` lazily
    resolves its children via ``effective_candidates()`` which may yield more
    ``_IncludedRouter`` instances or ``_EffectiveRouteContext`` wrappers around
    the original ``APIRoute``.

    Returns ``(route, effective_path)`` where *effective_path* includes any
    prefix applied by ``include_router`` (e.g. ``/api/v1/analysis``).
    """
    collected: list[tuple[APIRoute, str]] = []
    for route in routes:
        if isinstance(route, APIRoute):
            collected.append((route, route.path))
            continue
        # FastAPI ≥0.137 _IncludedRouter – unwrap via effective_candidates()
        if hasattr(route, 'effective_candidates'):
            for candidate in route.effective_candidates():
                if isinstance(candidate, APIRoute):
                    collected.append((candidate, candidate.path))
                elif hasattr(candidate, 'effective_candidates'):
                    collected.extend(_collect_api_routes([candidate]))
                elif hasattr(candidate, 'original_route'):
                    original = candidate.original_route
                    if isinstance(original, APIRoute):
                        # _EffectiveRouteContext stores the prefixed path
                        effective_path = getattr(candidate, 'path', original.path)
                        collected.append((original, effective_path))
    return collected


def _marked_routes(app: FastAPI) -> list[dict[str, Any]]:
    """Return metadata for routes onboarded via MCP route registration."""
    marked: list[dict[str, Any]] = []
    for route, effective_path in _collect_api_routes(list(app.routes)):
        route_meta = get_mcp_route_meta(route)
        if not isinstance(route_meta, dict):
            continue
        meta = dict(route_meta)
        # Routes in this codebase are single-method; MCP exposes one tool per route.
        method = next(
            (candidate for raw in (route.methods or set()) if (candidate := MCPHttpMethod.from_route_method(raw)) is not None),
            None,
        )
        if method is None:
            continue
        endpoint = route.endpoint
        fallback = endpoint.__name__ if hasattr(endpoint, '__name__') else route.name
        name = meta.get('name') or fallback
        marked.append({'route': route, 'method': method.value, 'name': name, 'meta': meta, 'effective_path': effective_path})
    return marked


def build_tool_registry(app: FastAPI) -> list[MCPToolDefinition]:
    """Extract MCPRouter mcp=True onboarded routes as MCP tool definitions."""
    marked = _marked_routes(app)
    schema = app.openapi()
    components = schema.get('components', {})
    tools: list[MCPToolDefinition] = []
    for item in marked:
        route = item['route']
        effective_path = item.get('effective_path', route.path)
        op_item = _route_openapi_operation(route, schema, effective_path)
        if op_item is None:
            continue
        method, op = op_item
        tool = _build_tool(
            {
                'method': method,
                'path': effective_path,
                'operation': op,
                'name': item['name'],
                'meta': item['meta'],
                'route': route,
            },
            components,
        )
        issues = tool.schema_support_issues()
        if issues:
            raise ValueError(f'Tool {tool.id!r} has unsupported schema: {", ".join(issues)}')
        tools.append(tool)
    return tools
