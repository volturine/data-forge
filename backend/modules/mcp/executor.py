"""MCP executor — invokes API routes in-process via httpx AsyncClient."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI


def build_tool_context(headers: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    context_headers = {k: v for k, v in (headers or {}).items() if v}
    return {'headers': context_headers}


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


async def call_tool(app: FastAPI, method: str, path: str, args: dict, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a tool call by invoking the app's route in-process."""
    url, remaining = _interpolate_path(path, {k: v for k, v in args.items() if k != 'payload'})

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
        payload = args.get('payload')
        headers = {'Content-Type': 'application/json'}
        forwarded = (context or {}).get('headers', {})
        if isinstance(forwarded, dict):
            for key, value in forwarded.items():
                if not value:
                    continue
                headers[str(key)] = str(value)

        query_params = {k: v for k, v in remaining.items() if k != 'payload'}

        if method in ('POST', 'PUT', 'PATCH'):
            resp = await client.request(
                method,
                url,
                content=json.dumps(payload) if payload is not None else b'',
                headers=headers,
                params=query_params,
            )
        elif method == 'DELETE':
            resp = await client.request(method, url, params=query_params, headers=headers)
        else:
            resp = await client.request(method, url, params=query_params, headers=headers)

    status = resp.status_code
    body: Any = None
    content_type = resp.headers.get('content-type', '')
    if 'application/json' in content_type:
        body = resp.json()
    elif resp.content:
        body = resp.text

    return {'status': status, 'body': body, 'ok': 200 <= status < 300}
