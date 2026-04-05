"""OpenRouter client — OpenAI-compatible provider for chat with tool calls."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from core import http as http_client
from modules.chat.tool_contract import format_output_hint

logger = logging.getLogger(__name__)

_OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
_TIMEOUT = httpx.Timeout(connect=10, read=120, write=10, pool=10)


class OpenRouterError(Exception):
    """Raised on OpenRouter API failures."""


def _headers(api_key: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://data-forge.local',
    }


def _mcp_tool_to_openai(tool: dict) -> dict:
    desc = tool['description']
    hint = format_output_hint(tool.get('output_schema'))
    if hint:
        desc = f'{desc}\n{hint}'
    return {
        'type': 'function',
        'function': {
            'name': tool['id'],
            'description': desc,
            'parameters': tool['input_schema'],
        },
    }


async def chat_with_tools(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict],
) -> dict[str, Any]:
    """Send a chat completion request with tool definitions."""
    logger.debug('chat_with_tools model=%s messages=%d tools=%d', model, len(messages), len(tools))
    payload: dict[str, Any] = {
        'model': model,
        'messages': messages,
    }
    if tools:
        payload['tools'] = [_mcp_tool_to_openai(t) for t in tools]
        payload['tool_choice'] = 'auto'

    client = http_client.get_async_client()
    resp = await client.post(
        f'{_OPENROUTER_BASE}/chat/completions',
        headers=_headers(api_key),
        content=json.dumps(payload),
        timeout=_TIMEOUT,
    )
    if not resp.is_success:
        raise OpenRouterError(f'OpenRouter returned {resp.status_code}: {resp.text[:500]}')
    return resp.json()  # type: ignore[no-any-return]


async def list_models(api_key: str) -> list[dict]:
    """List models available on OpenRouter."""
    client = http_client.get_async_client()
    resp = await client.get(f'{_OPENROUTER_BASE}/models', headers=_headers(api_key), timeout=_TIMEOUT)
    if not resp.is_success:
        logger.error('list_models failed: %d %s', resp.status_code, resp.text[:500])
        raise OpenRouterError(f'OpenRouter returned {resp.status_code}: {resp.text[:500]}')
    data = resp.json()
    return [
        {'id': m.get('id', ''), 'name': m.get('name', m.get('id', '')), 'context_length': m.get('context_length', 0)}
        for m in data.get('data', [])
    ]
