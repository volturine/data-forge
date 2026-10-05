"""Chat API routes — session management, message sending, SSE streaming, apply."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

from backend_core.ai_clients import AIError, ai_provider_name, get_ai_client, resolve_ai_provider
from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import RuntimeCoordinatorFenced
from backend_core.error_handlers import handle_errors
from backend_core.namespace import get_namespace
from backend_core.websocket import serialize_json
from dataforge_protocol import enums_pb2
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.chat.chat_http import ChatHttpError, chat_with_tools, list_models
from modules.chat.models import ChatSession
from modules.chat.sessions import ChatSessionBusy, normalize_epoch_milliseconds, session_store
from modules.chat.store import ChatClaimRevoked, ConfirmationPending, chat_stream_recovery, chat_turn_store
from modules.mcp.executor import call_tool
from modules.mcp.models import MCPToolDefinition, MCPToolSafety
from modules.mcp.tool_output import format_output_hint

if TYPE_CHECKING:
    from modules.chat.consumer import TurnRuntime

router = APIRouter(prefix='/ai/chat', tags=['ai-chat'])

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15


def _require_owned_session(session_id: str, user: User) -> ChatSession:
    """Return persisted session configuration, or 404 for an unowned session."""
    session = session_store.get(session_id, user_id=user.id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    return session


async def _require_owned_session_async(session_id: str, user: User) -> ChatSession:
    """Load a chat session without running its synchronous DB fallback on the loop."""
    return await _run_chat_db(_require_owned_session, session_id, user)


async def _run_chat_db[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    return await run_api_blocking(function, *args, **kwargs)


@dataclass(frozen=True, slots=True)
class ChatProviderDefinition:
    provider: enums_pb2.AIProvider
    requires_session_api_key: bool = False
    requires_model_list_api_key: bool = False
    supports_mcp_tool_calls: bool = False

    @classmethod
    def require(cls, provider: str | enums_pb2.AIProvider) -> ChatProviderDefinition:
        normalized = resolve_ai_provider(provider)
        return CHAT_PROVIDER_DEFINITIONS[normalized]

    async def list_models(self, body: ChatModelsRequest) -> list[dict]:
        if self.provider == enums_pb2.AI_PROVIDER_OPENROUTER:
            if not body.api_key:
                raise HTTPException(status_code=400, detail='API key is required')
            return await list_models(body.api_key)
        client = get_ai_client(
            self.provider,
            endpoint_url=body.endpoint_url,
            api_key=body.api_key or None,
            organization_id=body.organization_id,
        )
        return await run_api_blocking(client.list_models)


CHAT_PROVIDER_DEFINITIONS: dict[enums_pb2.AIProvider, ChatProviderDefinition] = {
    enums_pb2.AI_PROVIDER_OPENROUTER: ChatProviderDefinition(
        provider=enums_pb2.AI_PROVIDER_OPENROUTER,
        requires_session_api_key=True,
        requires_model_list_api_key=True,
        supports_mcp_tool_calls=True,
    ),
    enums_pb2.AI_PROVIDER_OPENAI: ChatProviderDefinition(provider=enums_pb2.AI_PROVIDER_OPENAI),
    enums_pb2.AI_PROVIDER_OLLAMA: ChatProviderDefinition(provider=enums_pb2.AI_PROVIDER_OLLAMA),
}


class CreateSessionRequest(BaseModel):
    """Request body to create a chat session."""

    model_config = ConfigDict(extra='forbid')

    provider: str
    model: str
    api_key: str | None = None
    system_prompt: str | None = None


class UpdateSessionRequest(BaseModel):
    """Request body to update session settings."""

    model_config = ConfigDict(extra='forbid')

    provider: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    api_key: str | None = None


class MessageRequest(BaseModel):
    """Request body to send a message."""

    model_config = ConfigDict(extra='forbid')

    session_id: str
    content: str
    tool_ids: list[str] = []


class ChatModelsRequest(BaseModel):
    """Request body to list chat models."""

    model_config = ConfigDict(extra='forbid')

    provider: str
    api_key: str | None = None
    endpoint_url: str | None = None
    organization_id: str | None = None


def _infer_patch(tool_id: str, method: str, path: str, result: dict) -> dict | None:
    """Infer a ui_patch event from tool method/path and response body."""
    if not result.get('ok'):
        return None
    # Path is /api/v1/{resource}/... — resource is always parts[2]
    parts = [p for p in path.split('/') if p]
    resource = parts[2] if len(parts) > 2 else 'unknown'
    action_map = {
        'GET': 'refresh',
        'POST': 'created',
        'PUT': 'updated',
        'PATCH': 'updated',
        'DELETE': 'deleted',
    }
    action = action_map.get(method, 'refresh')
    body = result.get('body')
    record_id = None
    if isinstance(body, dict):
        record_id = body.get('id')
    return {'resource': resource, 'action': action, 'id': record_id, 'data': body}


async def _resume_checkpointed_tool(
    session: TurnRuntime,
    app: FastAPI,
    registry: Sequence[MCPToolDefinition],
    tool_context: dict[str, Any] | None,
) -> None:
    checkpoint = session.checkpoint
    call = checkpoint.get('tool_call')
    if not isinstance(call, dict):
        raise RuntimeError('Checkpointed chat tool call is malformed')
    tool_id = str(call.get('tool_id', ''))
    tool = next((item for item in registry if item.id == tool_id), None)
    if tool is None:
        raise RuntimeError(f'Checkpointed chat tool {tool_id!r} is no longer registered')
    method = str(call.get('method', tool.method.value))
    path = str(call.get('path', tool.path))
    args = call.get('args')
    if not isinstance(args, dict):
        raise RuntimeError('Checkpointed chat tool arguments are malformed')
    tc = {'id': call.get('id', tool_id)}
    remaining_calls = checkpoint.get('remaining_calls', [])
    if not isinstance(remaining_calls, list):
        raise RuntimeError('Checkpointed chat continuation is malformed')
    if method != tool.method.value or path != tool.path:
        raise RuntimeError('Checkpointed chat tool definition changed')

    if checkpoint.get('phase') == 'awaiting_confirmation' and not await session.wait_for_confirm():
        await _push_tool_error(session, tc, tool_id, method, path, args, 'User denied tool execution')
        await session.set_checkpoint({'phase': 'provider_request'})
        await _execute_tool_calls(session, app, registry, remaining_calls, tool_context)
        return

    await session.set_checkpoint({'phase': 'tool_running', 'tool_call': call})
    await session.push_event({'type': 'tool_start', 'tool_id': tool_id, 'method': method, 'path': path})
    try:
        result = await call_tool(app, method, path, args, tool_context)
    except ValueError as exc:
        await _push_tool_error(session, tc, tool_id, method, path, args, str(exc))
        await session.set_checkpoint({'phase': 'provider_request'})
        await _execute_tool_calls(session, app, registry, remaining_calls, tool_context)
        return
    patch = _infer_patch(tool_id, method, path, result)
    await session.push_event({'type': 'tool_result', 'tool_id': tool_id, 'result': result})
    if patch:
        await session.push_event({'type': 'ui_patch', **patch})
    await session.append_message(
        {
            'role': 'tool',
            'tool_call_id': call.get('id', tool_id),
            'content': await serialize_json(result.get('body', '')),
        }
    )
    await session.set_checkpoint({'phase': 'provider_request'})
    await _execute_tool_calls(session, app, registry, remaining_calls, tool_context)


_TOOL_CALL_RE = re.compile(r'TOOLCALL>\s*(\[.*\])', re.DOTALL)
_TOOL_CALL_OBJ_RE = re.compile(r'TOOLCALL>\s*(\{.*\})', re.DOTALL)


def _format_param_details(name: str, schema: dict, required: bool, location: str, description: str = '') -> str:
    type_name = schema.get('type', 'any')
    req = 'required' if required else 'optional'
    parts = [f'    - {name} ({location}, {type_name}, {req})']
    if description:
        parts.append(f'      description: {description}')
    if 'enum' in schema and isinstance(schema['enum'], list):
        enum_values = ', '.join(json.dumps(v) for v in schema['enum'])
        parts.append(f'      enum: [{enum_values}]')
    if 'default' in schema:
        parts.append(f'      default: {json.dumps(schema["default"])}')
    if 'examples' in schema and isinstance(schema['examples'], list) and schema['examples']:
        parts.append(f'      examples: {json.dumps(schema["examples"][:2])}')
    elif 'example' in schema:
        parts.append(f'      example: {json.dumps(schema["example"])}')
    return '\n'.join(parts)


def _format_fallback_param_details(schema: dict) -> list[str]:
    props = schema.get('properties', {})
    required = set(schema.get('required', []))
    return [_format_param_details(name, prop, name in required, 'arg', prop.get('description', '')) for name, prop in props.items()]


def _build_tool_system_message(tools: Sequence[MCPToolDefinition | dict[str, Any]]) -> str:
    """Build a system message describing available tools and how to call them."""
    lines = [
        'You have access to the following tools. To call a tool, output EXACTLY this format on its own line:',
        'TOOLCALL>[{"name": "tool_name", "arguments": {"arg1": "value1"}}]',
        '',
        'CRITICAL RULES:',
        '- NEVER fabricate or guess tool results. After outputting a TOOLCALL, STOP and wait.',
        '- The system will execute the tool and provide the result in the next message.',
        '- Only then should you continue your response based on the actual result.',
        '- You may call multiple tools in one TOOLCALL by passing an array.',
        '- Always use generate_uuid to get UUIDs — never invent them.',
        '- Path parameters: provide them as top-level arguments by exact name; they are inserted into URL templates.',
        '- Query parameters: provide as top-level arguments that are not path params and not payload.',
        '- Request body: always pass JSON body as `payload`.',
        '- Never send unknown arguments; only use documented parameters.',
        '',
        'Available tools:',
    ]
    for t in tools:
        desc = t.get('description', '')
        schema = t['input_schema']
        meta = t.get('arg_metadata', {}) or {}
        path_meta = meta.get('path') or []
        query_meta = meta.get('query') or []
        payload_meta = meta.get('payload')

        param_parts: list[str] = []
        for item in path_meta:
            param_parts.append(
                _format_param_details(
                    item.get('name', ''),
                    item.get('schema', {}),
                    bool(item.get('required', True)),
                    'path',
                    item.get('description', ''),
                ),
            )
        for item in query_meta:
            param_parts.append(
                _format_param_details(
                    item.get('name', ''),
                    item.get('schema', {}),
                    bool(item.get('required', False)),
                    'query',
                    item.get('description', ''),
                ),
            )
        if payload_meta is not None:
            payload_schema = schema.get('properties', {}).get('payload', {})
            payload_desc = payload_meta.get('description', '')
            param_parts.append(
                _format_param_details(
                    'payload',
                    payload_schema,
                    bool(payload_meta.get('required', False)),
                    'body',
                    payload_desc,
                ),
            )
            if payload_meta.get('content_type'):
                param_parts.append(f'      content_type: {payload_meta["content_type"]}')

        if not param_parts:
            param_parts = _format_fallback_param_details(schema)

        params_str = '\n'.join(param_parts) if param_parts else '    (no parameters)'
        lines.append(f'- {t["id"]} [{t["method"]}]: {desc}')
        lines.append(f'  Parameters:\n{params_str}')
        hint = format_output_hint(t.get('output_schema'))
        if hint:
            lines.append(f'  {hint}')
    return '\n'.join(lines)


async def _push_tool_error(
    session: TurnRuntime,
    tc: dict,
    tool_id: str,
    method: str,
    path: str,
    args: dict,
    message: str,
) -> None:
    """Push tool_error event and append tool-role message for the LLM context."""
    await session.push_event(
        {
            'type': 'tool_error',
            'tool_id': tool_id,
            'method': method,
            'path': path,
            'args': args,
            'errors': [{'path': '$', 'message': message}],
        },
    )
    await session.append_message(
        {
            'role': 'tool',
            'tool_call_id': tc.get('id', tool_id),
            'content': json.dumps({'status': 'error', 'message': message}),
        },
    )


def _try_parse_json(text: str) -> list[dict] | None:
    """Parse one leading JSON value, ignoring any trailing model chatter."""
    start = len(text) - len(text.lstrip())
    try:
        data, _end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    return None


def _parse_text_tool_calls(content: str) -> tuple[str, list[dict]]:
    """Extract tool calls dumped as text by models that don't support function calling.

    Returns (cleaned_content, tool_calls) where tool_calls is in OpenAI format.
    """
    match = _TOOL_CALL_RE.search(content) or _TOOL_CALL_OBJ_RE.search(content)
    if not match:
        return content, []
    calls_data = _try_parse_json(match.group(1))
    if calls_data is None:
        return content, []
    tool_calls = []
    for i, call in enumerate(calls_data):
        if not isinstance(call, dict) or 'name' not in call:
            continue
        tool_calls.append(
            {
                'id': f'text_call_{i}',
                'type': 'function',
                'function': {
                    'name': call['name'],
                    'arguments': json.dumps(call.get('arguments', {})),
                },
            },
        )
    cleaned = re.sub(r'TOOLCALL>.*', '', content, flags=re.DOTALL).strip()
    return cleaned, tool_calls


async def _execute_tool_calls(
    session: TurnRuntime,
    app: FastAPI,
    all_tools: Sequence[MCPToolDefinition],
    tool_calls: list[dict[str, Any]],
    tool_context: dict[str, Any] | None,
) -> None:
    for call_index, tc in enumerate(tool_calls):
        remaining_calls = tool_calls[call_index + 1 :]
        fn = tc.get('function', {})
        tool_id = fn.get('name', '')
        raw_args = fn.get('arguments', '{}')

        tool = next((t for t in all_tools if t.id == tool_id), None)
        if tool is None:
            logger.warning('Unknown tool_id session=%s tool=%s', session.id, tool_id)
            await _push_tool_error(session, tc, tool_id, '', '', {}, f"Unknown tool '{tool_id}'")
            continue

        method = tool.method.value
        path = tool.path

        try:
            args = await run_api_blocking(json.loads, raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError as exc:
            logger.warning(
                'Malformed tool args session=%s tool=%s: %s',
                session.id,
                tool_id,
                exc,
            )
            await _push_tool_error(
                session,
                tc,
                tool_id,
                method,
                path,
                {},
                f'Malformed arguments: {exc}',
            )
            continue

        await session.push_event(
            {
                'type': 'tool_call',
                'tool_id': tool_id,
                'method': method,
                'path': path,
                'args': args,
            }
        )

        valid, errors, normalized = await run_api_blocking(tool.validate_arguments, args)
        if not valid:
            await session.push_event(
                {
                    'type': 'tool_error',
                    'tool_id': tool_id,
                    'method': method,
                    'path': path,
                    'args': args,
                    'errors': errors,
                },
            )
            await session.append_message(
                {
                    'role': 'tool',
                    'tool_call_id': tc.get('id', tool_id),
                    'content': json.dumps({'status': 'validation_error', 'errors': errors}),
                },
            )
            continue

        if tool.confirm_required:
            pending_call = {
                'id': tc.get('id', tool_id),
                'tool_id': tool_id,
                'method': method,
                'path': path,
                'args': normalized,
            }
            await session.set_checkpoint(
                {'phase': 'awaiting_confirmation', 'tool_call': pending_call, 'remaining_calls': remaining_calls},
                status='awaiting_confirmation',
            )
            await session.push_event(
                {
                    'type': 'tool_confirm',
                    'tool_id': tool_id,
                    'method': method,
                    'path': path,
                    'args': normalized,
                },
            )
            approved = await session.wait_for_confirm()
            if not approved:
                await _push_tool_error(
                    session,
                    tc,
                    tool_id,
                    method,
                    path,
                    normalized,
                    'User denied tool execution',
                )
                await session.set_checkpoint({'phase': 'provider_request'})
                continue

        await session.set_checkpoint(
            {
                'phase': 'tool_running',
                'remaining_calls': remaining_calls,
                'tool_call': {
                    'id': tc.get('id', tool_id),
                    'tool_id': tool_id,
                    'method': method,
                    'path': path,
                    'args': normalized,
                },
            }
        )
        await session.push_event(
            {
                'type': 'tool_start',
                'tool_id': tool_id,
                'method': method,
                'path': path,
            }
        )
        t0 = time.monotonic()
        try:
            result = await call_tool(app, method, path, normalized, tool_context)
        except ValueError as exc:
            await _push_tool_error(session, tc, tool_id, method, path, normalized, str(exc))
            await session.set_checkpoint({'phase': 'provider_request'})
            continue
        duration_ms = round((time.monotonic() - t0) * 1000)
        patch = _infer_patch(tool_id, method, path, result)

        await session.push_event(
            {
                'type': 'tool_result',
                'tool_id': tool_id,
                'result': result,
                'duration_ms': duration_ms,
            }
        )
        if patch:
            await session.push_event({'type': 'ui_patch', **patch})

        tool_result_str = await serialize_json(result.get('body', ''))
        await session.append_message(
            {
                'role': 'tool',
                'tool_call_id': tc.get('id', tool_id),
                'content': tool_result_str,
            },
        )
        await session.set_checkpoint({'phase': 'provider_request'})


async def _run_agent_turn(
    session: TurnRuntime,
    app: FastAPI,
    user_content: str,
    tool_ids: list[str] | None = None,
    tool_context: dict[str, Any] | None = None,
    registry: Sequence[MCPToolDefinition] = (),
) -> None:
    """Run one agent turn: send message, handle tool calls, push SSE events."""
    provider = ChatProviderDefinition.require(session.provider)
    api_key = session.api_key
    if provider.requires_session_api_key and not api_key:
        await session.push_event({'type': 'error', 'content': 'No API key configured'})
        await session.finish('failed')
        return

    turn_start = time.monotonic()
    tool_count = 0
    MAX_AGENT_TOOL_TURNS = 16
    turn_usage = session.turn_usage
    logger.info('chat turn start session=%s user_len=%d', session.id, len(user_content))

    try:
        registry = [MCPToolDefinition.coerce(item) for item in registry]
        if tool_ids:
            id_set = set(tool_ids)
            registry = [tool for tool in registry if tool.id in id_set]
        if session.checkpoint.get('phase') in {'awaiting_confirmation', 'tool_ready'}:
            await _resume_checkpointed_tool(session, app, registry, tool_context)

        if not provider.supports_mcp_tool_calls:
            prompt_lines: list[str] = []
            for history_msg in session.messages:
                role = str(history_msg.get('role', 'user')).lower()
                if role not in {'system', 'user', 'assistant'}:
                    continue
                content = str(history_msg.get('content') or '')
                if not content:
                    continue
                prompt_lines.append(f'{role}: {content}')
            prompt_lines.append('assistant:')
            prompt = '\n'.join(prompt_lines)
            client = get_ai_client(provider.provider, api_key=api_key or None)
            await session.set_checkpoint({'phase': 'provider_request'})
            assistant_content = await session.run_sync_provider(
                client.generate,
                prompt,
                model=session.model,
                options=None,
            )
            await session.append_message({'role': 'assistant', 'content': assistant_content})
            await session.push_event({'type': 'message', 'role': 'assistant', 'content': assistant_content})
            await session.finish('completed')
            return

        safe_tools = [t for t in registry if t.safety == MCPToolSafety.SAFE]
        mutating_tools = [t for t in registry if t.safety == MCPToolSafety.MUTATING]
        all_tools = safe_tools + mutating_tools

        tool_system_msg = {'role': 'system', 'content': _build_tool_system_message(all_tools)} if all_tools else None
        use_text_format = session.use_text_format

        turn = session.provider_turn
        while True:
            turn += 1
            session.provider_turn = turn
            await session.set_checkpoint({'phase': 'provider_request'})
            await session.push_event({'type': 'turn_start', 'turn': turn})
            api_messages = list(session.messages)
            if tool_system_msg and use_text_format:
                insert_idx = 1 if api_messages and api_messages[0].get('role') == 'system' else 0
                api_messages.insert(insert_idx, tool_system_msg)

            response = await chat_with_tools(
                api_key,
                session.model,
                api_messages,
                all_tools,
            )
            choice = response.get('choices', [{}])[0]
            raw = choice.get('message', {})
            finish = choice.get('finish_reason', '')

            usage = response.get('usage', {})
            turn_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
            turn_usage['completion_tokens'] += usage.get('completion_tokens', 0)
            turn_usage['total_tokens'] += usage.get('total_tokens', 0)

            assistant_content = raw.get('content') or ''
            tool_calls = list(raw.get('tool_calls') or [])

            if tool_calls:
                use_text_format = False  # model uses native calling; drop text instructions hereafter
                session.use_text_format = False
            elif assistant_content:
                cleaned, parsed = await run_api_blocking(_parse_text_tool_calls, assistant_content)
                if parsed:
                    tool_calls = parsed
                    assistant_content = cleaned
                    finish = 'tool_calls'

            msg: dict = {'role': 'assistant', 'content': assistant_content}
            if tool_calls:
                msg['tool_calls'] = tool_calls

            # A provider refusing mid-tool-call (length/content_filter/...) would
            # leave unanswered tool_calls in the history, which providers reject
            # on the next request — drop them and end the turn instead.
            disallowed_finish = finish not in ('tool_calls', 'stop', None, '')
            if tool_calls and disallowed_finish:
                msg = {'role': 'assistant', 'content': assistant_content or f'Stopped after {turn} turns ({finish}).'}
                await session.append_message(msg)
                await session.push_event({'type': 'message', 'role': 'assistant', 'content': msg['content']})
                break

            if tool_calls and turn >= MAX_AGENT_TOOL_TURNS:
                note = f'Stopped: reached the {MAX_AGENT_TOOL_TURNS} tool-turn limit.'
                await session.append_message({'role': 'assistant', 'content': assistant_content or note})
                await session.push_event({'type': 'message', 'role': 'assistant', 'content': assistant_content or note})
                break

            await session.append_message(msg)

            if assistant_content:
                await session.push_event(
                    {
                        'type': 'message',
                        'role': 'assistant',
                        'content': assistant_content,
                    }
                )

            if not tool_calls:
                break

            tool_count += len(tool_calls)
            await _execute_tool_calls(session, app, all_tools, tool_calls, tool_context)

        await session.push_event({'type': 'usage', **turn_usage})
    except ConfirmationPending:
        return
    except ChatClaimRevoked, RuntimeCoordinatorFenced, SQLAlchemyError:
        raise
    except ChatHttpError as exc:
        logger.error('Chat HTTP error session=%s: %s', session.id, exc)
        session.failed = True
        await session.push_event({'type': 'error', 'content': f'AI provider error: {exc}'})
    except AIError as exc:
        logger.error('AI client error session=%s: %s', session.id, exc)
        session.failed = True
        await session.push_event({'type': 'error', 'content': f'AI provider error: {exc}'})
    except asyncio.CancelledError:
        logger.info('Agent turn cancelled session=%s', session.id)
        if session.finished:
            pass
        elif session.owner_stopping:
            session.failed = True
            await session.push_event({'type': 'error', 'content': 'Generation interrupted by coordinator restart'})
        else:
            session.stop_requested = True
            await session.push_event({'type': 'error', 'content': 'Generation stopped'})
    except httpx.TimeoutException as exc:
        logger.error('Timeout session=%s: %s', session.id, exc)
        session.failed = True
        await session.push_event({'type': 'error', 'content': 'Request timed out'})
    except ValueError as exc:
        logger.info('Chat configuration error session=%s: %s', session.id, exc)
        session.failed = True
        await session.push_event({'type': 'error', 'content': str(exc)})
    except Exception:
        logger.exception('Unexpected error session=%s', session.id)
        session.failed = True
        await session.push_event({'type': 'error', 'content': 'Internal error'})
    finally:
        elapsed = time.monotonic() - turn_start
        logger.info(
            'chat turn end session=%s elapsed=%.2fs tools=%d',
            session.id,
            elapsed,
            tool_count,
        )
    status = 'interrupted' if session.owner_stopping else 'failed' if session.failed or session.stop_requested else 'completed'
    await session.finish(status)


@router.get('/sessions')
@handle_errors('list chat sessions')
def list_sessions(user: User = Depends(get_current_user)) -> list[dict]:
    """List all active chat sessions with preview info."""
    return session_store.list_sessions(user_id=user.id)


@router.post('/sessions')
@handle_errors('create chat session')
def create_session(body: CreateSessionRequest, user: User = Depends(get_current_user)) -> dict:
    """Create a new chat session with the given provider/model/key."""
    provider = ChatProviderDefinition.require(body.provider).provider
    session = session_store.create(
        ai_provider_name(provider),
        body.model,
        body.api_key or '',
        body.system_prompt or '',
        user_id=user.id,
    )
    return {
        'session_id': session.id,
        'model': session.model,
        'provider': session.provider,
    }


@router.patch('/sessions/{session_id}')
@handle_errors('update chat session')
def update_session(session_id: str, body: UpdateSessionRequest, user: User = Depends(get_current_user)) -> dict:
    """Update model, system prompt, or API key on a live session."""
    _require_owned_session(session_id, user)
    provider = ai_provider_name(ChatProviderDefinition.require(body.provider).provider) if body.provider is not None else None
    session = session_store.update(
        session_id,
        user_id=user.id,
        provider=provider,
        model=body.model,
        api_key=body.api_key,
        system_prompt=body.system_prompt,
    )
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    return {
        'session_id': session_id,
        'model': session.model,
        'provider': session.provider,
    }


@router.post('/message')
@handle_errors('send chat message')
async def send_message(request: Request, body: MessageRequest, user: User = Depends(get_current_user)) -> dict:
    """Send a user message; agent processing is kicked off asynchronously."""
    await _require_owned_session_async(body.session_id, user)
    session_token = request.headers.get('X-Session-Token') or request.cookies.get('session_token') or ''
    try:
        await _run_chat_db(
            chat_turn_store.enqueue,
            session_id=body.session_id,
            user_id=user.id,
            content=body.content,
            tool_ids=body.tool_ids,
            namespace=get_namespace(),
            session_token=session_token,
        )
    except RuntimeError as exc:
        if str(exc) != 'Agent busy':
            raise
        raise HTTPException(status_code=409, detail='Agent busy') from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail='Session not found') from exc
    return {'status': 'processing', 'session_id': body.session_id}


@router.post('/sessions/{session_id}/stop')
@handle_errors('stop chat generation')
async def stop_generation(session_id: str, user: User = Depends(get_current_user)) -> dict:
    """Cancel the running agent turn for a session."""
    await _require_owned_session_async(session_id, user)
    await _run_chat_db(chat_turn_store.request_stop, session_id=session_id, user_id=user.id)
    return {'status': 'stopped', 'session_id': session_id}


class ConfirmRequest(BaseModel):
    """Request body for tool confirmation."""

    approved: bool


@router.post('/sessions/{session_id}/confirm')
@handle_errors('confirm chat tool')
async def confirm_tool(session_id: str, body: ConfirmRequest, user: User = Depends(get_current_user)) -> dict:
    """Confirm or deny a pending tool execution."""
    await _require_owned_session_async(session_id, user)
    await _run_chat_db(chat_turn_store.confirm, session_id=session_id, user_id=user.id, approved=body.approved)
    return {'status': 'resolved', 'approved': body.approved}


@router.get('/history/{session_id}')
@handle_errors('get chat history')
async def get_history(session_id: str, user: User = Depends(get_current_user)) -> dict:
    """Return the full event history for a session."""
    await _require_owned_session_async(session_id, user)
    history, cursor, gap = await _run_chat_db(session_store.history, session_id)
    return {'session_id': session_id, 'history': history, 'last_event_id': cursor, 'history_gap': gap}


@router.get('/stream/{session_id}')
@handle_errors('stream chat events')
async def stream(
    session_id: str,
    request: Request,
    after: int = 0,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE stream of chat events for a session with heartbeat."""
    await _require_owned_session_async(session_id, user)
    header_cursor = request.headers.get('Last-Event-ID')
    if header_cursor is not None:
        try:
            after = max(int(header_cursor), 0)
        except ValueError:
            after = 0
    after = max(after, 0)

    async def generate() -> AsyncIterator[bytes]:
        cursor = after
        chat_stream_recovery.subscribe(session_id)
        try:
            while True:
                version = chat_stream_recovery.version(session_id)
                rows, latest, oldest = await _run_chat_db(
                    chat_turn_store.read_events,
                    session_id=session_id,
                    after=cursor,
                    limit=100,
                )
                if cursor > latest:
                    cursor = 0
                    continue
                if oldest is not None and cursor < oldest - 1:
                    gap_event = {'type': 'history_gap', 'oldest_event_id': oldest}
                    yield f'id: {oldest - 1}\ndata: {await serialize_json(gap_event)}\n\n'.encode()
                    cursor = oldest - 1
                    continue
                if rows:
                    for row in rows:
                        cursor = int(row.sequence)
                        event = {**row.payload, 'ts': normalize_epoch_milliseconds(row.payload.get('ts')) or int(row.created_at.timestamp() * 1000)}
                        yield f'id: {cursor}\ndata: {await serialize_json(event)}\n\n'.encode()
                    continue
                try:
                    await asyncio.wait_for(chat_stream_recovery.wait(session_id, version), timeout=HEARTBEAT_INTERVAL)
                except TimeoutError:
                    yield b': heartbeat\n\n'
        finally:
            chat_stream_recovery.unsubscribe(session_id)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.delete('/sessions/{session_id}')
@handle_errors('delete chat session')
def delete_session(session_id: str, user: User = Depends(get_current_user)) -> dict:
    """Close and delete a chat session."""
    try:
        deleted = session_store.delete(session_id, user_id=user.id)
    except ChatSessionBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'status': 'closed', 'session_id': session_id}


@router.post('/models')
@handle_errors('list chat models')
async def get_models(body: ChatModelsRequest, user: User = Depends(get_current_user)) -> list[dict]:
    """List models available for a chat provider."""
    del user
    provider = ChatProviderDefinition.require(body.provider)
    if provider.requires_model_list_api_key and not body.api_key:
        raise HTTPException(status_code=400, detail='API key is required')
    try:
        return await provider.list_models(body)
    except (ChatHttpError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
