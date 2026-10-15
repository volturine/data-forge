"""MCP executor — invokes API routes in-process via httpx AsyncClient."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI

from backend_core.api_execution_budget import run_api_blocking
from backend_core.websocket import serialize_json
from modules.mcp.models import MCPHttpMethod
from modules.mcp.tool_output import redact_secrets


def build_tool_context(headers: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    return {'headers': {k: v for k, v in (headers or {}).items() if v}}


def _interpolate_path(path: str, args: dict) -> tuple[str, dict]:
    """Replace {param} placeholders in path, return (url, remaining_args)."""
    params = re.findall(r'\{(\w+)\}', path)
    remaining = dict(args)
    missing: list[str] = []
    for p in params:
        if p not in remaining:
            missing.append(p)
            continue
        value = remaining.pop(p)
        if value is None:
            missing.append(p)
            continue
        path = path.replace(f'{{{p}}}', quote(str(value), safe=''))
    if missing:
        miss = ', '.join(sorted(missing))
        raise ValueError(f'Missing required path parameter(s): {miss}')
    if re.search(r'\{\w+\}', path):
        raise ValueError(f'Unresolved path template remains: {path}')
    return path, remaining


async def call_tool(
    app: FastAPI,
    method: str | MCPHttpMethod,
    path: str,
    args: dict,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a tool call by invoking the app's route in-process."""
    url, remaining = _interpolate_path(path, {k: v for k, v in args.items() if k != 'payload'})
    method_name = method.value if isinstance(method, MCPHttpMethod) else method

    headers = {'Content-Type': 'application/json'}
    forwarded = (context or {}).get('headers', {})
    if isinstance(forwarded, dict):
        headers.update({str(key): str(value) for key, value in forwarded.items() if value})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        if method_name in ('POST', 'PUT', 'PATCH'):
            payload = args.get('payload')
            content = await serialize_json(payload) if payload is not None else b''
            resp = await client.request(method_name, url, content=content, headers=headers, params=remaining)
        else:
            resp = await client.request(method_name, url, params=remaining, headers=headers)

    def decode_response() -> dict[str, Any]:
        status = resp.status_code
        body: Any = None
        content_type = resp.headers.get('content-type', '')
        if 'application/json' in content_type:
            body = resp.json()
        elif resp.content:
            body = resp.text
        return {'status': status, 'body': redact_secrets(body), 'ok': 200 <= status < 300}

    return await run_api_blocking(decode_response)
