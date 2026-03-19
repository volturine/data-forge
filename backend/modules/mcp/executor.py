"""MCP executor — invokes API routes in-process via httpx AsyncClient."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi import FastAPI


def _interpolate_path(path: str, args: dict) -> tuple[str, dict]:
    """Replace {param} placeholders in path, return (url, remaining_args)."""
    params = re.findall(r'\{(\w+)\}', path)
    remaining = dict(args)
    for p in params:
        if p in remaining:
            path = path.replace(f'{{{p}}}', str(remaining.pop(p)))
    return path, remaining


async def call_tool(app: FastAPI, method: str, path: str, args: dict) -> dict[str, Any]:
    """Execute a tool call by invoking the app's route in-process."""
    url, remaining = _interpolate_path(path, {k: v for k, v in args.items() if k != 'payload'})

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
        payload = args.get('payload')
        headers = {'Content-Type': 'application/json'}

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
            resp = await client.request(method, url, params=query_params)
        else:
            resp = await client.request(method, url, params=query_params)

    status = resp.status_code
    body: Any = None
    content_type = resp.headers.get('content-type', '')
    if 'application/json' in content_type:
        body = resp.json()
    elif resp.content:
        body = resp.text

    return {'status': status, 'body': body, 'ok': 200 <= status < 300}
