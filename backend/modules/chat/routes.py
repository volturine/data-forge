"""Chat API routes — session management, message sending, SSE streaming, apply."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.error_handlers import handle_errors
from core.namespace import get_namespace
from modules.ai.service import get_ai_client
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.chat.openrouter import OpenRouterError, chat_with_tools, list_models
from modules.chat.sessions import LiveSession, session_store
from modules.chat.tool_contract import format_output_hint
from modules.mcp.executor import build_tool_context, call_tool
from modules.mcp.validation import validate_args

router = APIRouter(prefix='/ai/chat', tags=['ai-chat'])

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15


class CreateSessionRequest(BaseModel):
    """Request body to create a chat session."""

    provider: str = 'openrouter'
    model: str
    api_key: str = ''
    system_prompt: str = ''


class UpdateSessionRequest(BaseModel):
    """Request body to update session settings."""

    provider: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    api_key: str | None = None


class MessageRequest(BaseModel):
    """Request body to send a message."""

    session_id: str
    content: str
    tool_ids: list[str] = []


class ChatModelsRequest(BaseModel):
    """Request body to list chat models."""

    provider: str = 'openrouter'
    api_key: str = ''
    endpoint_url: str | None = None
    organization_id: str | None = None


def _resolve_api_key(provider: str, session_key: str) -> str:
    """Return session key if set, otherwise fall back to provider defaults."""
    if session_key:
        return session_key
    normalized = provider.strip().lower()
    if normalized == 'openrouter':
        from modules.settings.service import get_resolved_openrouter_key

        return get_resolved_openrouter_key()
    if normalized == 'openai':
        from modules.settings.service import get_resolved_openai_settings

        return get_resolved_openai_settings()['api_key']
    if normalized in {'huggingface', 'huggingface-api'}:
        from modules.settings.service import get_resolved_huggingface_settings

        return get_resolved_huggingface_settings()['api_token']
    return ''


def _infer_patch(tool_id: str, method: str, path: str, result: dict) -> dict | None:
    """Infer a ui_patch event from tool method/path and response body."""
    if not result.get('ok'):
        return None
    # Path is /api/v1/{resource}/... — resource is always parts[2]
    parts = [p for p in path.split('/') if p]
    resource = parts[2] if len(parts) > 2 else 'unknown'
    action_map = {'GET': 'refresh', 'POST': 'created', 'PUT': 'updated', 'PATCH': 'updated', 'DELETE': 'deleted'}
    action = action_map.get(method, 'refresh')
    body = result.get('body')
    record_id = None
    if isinstance(body, dict):
        record_id = body.get('id')
    return {'resource': resource, 'action': action, 'id': record_id, 'data': body}


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


def _build_tool_system_message(tools: list[dict]) -> str:
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
                _format_param_details('payload', payload_schema, bool(payload_meta.get('required', False)), 'body', payload_desc),
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


def _push_tool_error(
    session: LiveSession,
    tc: dict,
    tool_id: str,
    method: str,
    path: str,
    args: dict,
    message: str,
) -> None:
    """Push tool_error event and append tool-role message for the LLM context."""
    session.push_event(
        {
            'type': 'tool_error',
            'tool_id': tool_id,
            'method': method,
            'path': path,
            'args': args,
            'errors': [{'path': '$', 'message': message}],
        },
    )
    session.append_message(
        {
            'role': 'tool',
            'tool_call_id': tc.get('id', tool_id),
            'content': json.dumps({'status': 'error', 'message': message}),
        },
    )


def _try_parse_json(text: str) -> list[dict] | None:
    """Try to parse JSON, progressively trimming trailing garbage on failure."""
    for end in range(len(text), 0, -1):
        candidate = text[:end]
        if not candidate.rstrip().endswith((']', '}')):
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return [data]
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            continue
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


async def _run_agent_turn(
    session: LiveSession,
    app: Any,
    user_content: str,
    tool_ids: list[str] | None = None,
    tool_context: dict[str, Any] | None = None,
) -> None:
    """Run one agent turn: send message, handle tool calls, push SSE events."""
    from modules.mcp.routes import get_registry

    provider_name = session.provider.strip().lower()
    api_key = _resolve_api_key(provider_name, session.api_key)
    if provider_name in {'openrouter', 'huggingface', 'huggingface-api'} and not api_key:
        session.push_event({'type': 'error', 'content': 'No API key configured'})
        session.push_event({'type': 'done'})
        await session.set_busy(False)
        session_store.flush(session.id)
        return

    turn_start = time.monotonic()
    tool_count = 0
    turn_usage: dict[str, int] = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    logger.info('chat turn start session=%s user_len=%d', session.id, len(user_content))

    session.add_message('user', user_content)
    session.push_event({'type': 'message', 'role': 'user', 'content': user_content})

    try:
        if provider_name != 'openrouter':
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
            client = get_ai_client(provider_name, api_key=api_key)
            assistant_content = await asyncio.to_thread(
                client.generate,
                prompt,
                model=session.model,
                options=None,
            )
            session.append_message({'role': 'assistant', 'content': assistant_content})
            session.push_event({'type': 'message', 'role': 'assistant', 'content': assistant_content})
            return

        registry = get_registry(app)
        if tool_ids:
            id_set = set(tool_ids)
            registry = [t for t in registry if t['id'] in id_set]
        safe_tools = [t for t in registry if t['safety'] == 'safe']
        mutating_tools = [t for t in registry if t['safety'] == 'mutating']
        all_tools = safe_tools + mutating_tools

        tool_system_msg = {'role': 'system', 'content': _build_tool_system_message(all_tools)} if all_tools else None
        use_text_format = True  # becomes False once native function calling is confirmed

        turn = 0
        while True:
            turn += 1
            session.push_event({'type': 'turn_start', 'turn': turn})
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
            elif assistant_content:
                cleaned, parsed = _parse_text_tool_calls(assistant_content)
                if parsed:
                    tool_calls = parsed
                    assistant_content = cleaned
                    finish = 'tool_calls'

            msg: dict = {'role': 'assistant', 'content': assistant_content}
            if tool_calls:
                msg['tool_calls'] = tool_calls
            session.append_message(msg)

            if assistant_content:
                session.push_event({'type': 'message', 'role': 'assistant', 'content': assistant_content})

            if not tool_calls or finish not in ('tool_calls', 'stop', None, ''):
                break

            for tc in tool_calls:
                fn = tc.get('function', {})
                tool_id = fn.get('name', '')
                raw_args = fn.get('arguments', '{}')

                tool = next((t for t in all_tools if t['id'] == tool_id), None)
                if tool is None:
                    logger.warning('Unknown tool_id session=%s tool=%s', session.id, tool_id)
                    _push_tool_error(session, tc, tool_id, '', '', {}, f"Unknown tool '{tool_id}'")
                    continue

                method = tool['method']
                path = tool['path']

                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError as exc:
                    logger.warning('Malformed tool args session=%s tool=%s: %s', session.id, tool_id, exc)
                    _push_tool_error(session, tc, tool_id, method, path, {}, f'Malformed arguments: {exc}')
                    continue
                tool_count += 1

                session.push_event({'type': 'tool_call', 'tool_id': tool_id, 'method': method, 'path': path, 'args': args})

                valid, errors, normalized = validate_args(tool['input_schema'], args)
                if not valid:
                    session.push_event(
                        {'type': 'tool_error', 'tool_id': tool_id, 'method': method, 'path': path, 'args': args, 'errors': errors},
                    )
                    session.append_message(
                        {
                            'role': 'tool',
                            'tool_call_id': tc.get('id', tool_id),
                            'content': json.dumps({'status': 'validation_error', 'errors': errors}),
                        },
                    )
                    continue

                if tool.get('confirm_required'):
                    session.push_event(
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
                        _push_tool_error(session, tc, tool_id, method, path, normalized, 'User denied tool execution')
                        continue

                session.push_event({'type': 'tool_start', 'tool_id': tool_id, 'method': method, 'path': path})
                t0 = time.monotonic()
                try:
                    result = await call_tool(app, method, path, normalized, tool_context)
                except ValueError as exc:
                    _push_tool_error(session, tc, tool_id, method, path, normalized, str(exc))
                    continue
                duration_ms = round((time.monotonic() - t0) * 1000)
                patch = _infer_patch(tool_id, method, path, result)

                session.push_event({'type': 'tool_result', 'tool_id': tool_id, 'result': result, 'duration_ms': duration_ms})
                if patch:
                    session.push_event({'type': 'ui_patch', **patch})

                tool_result_str = json.dumps(result.get('body', ''))
                session.append_message(
                    {
                        'role': 'tool',
                        'tool_call_id': tc.get('id', tool_id),
                        'content': tool_result_str,
                    },
                )

        session.push_event({'type': 'usage', **turn_usage})
    except OpenRouterError as exc:
        logger.error('OpenRouter error session=%s: %s', session.id, exc)
        session.push_event({'type': 'error', 'content': f'AI provider error: {exc}'})
    except asyncio.CancelledError:
        logger.info('Agent turn cancelled session=%s', session.id)
        session.push_event({'type': 'error', 'content': 'Generation stopped'})
    except httpx.TimeoutException as exc:
        logger.error('Timeout session=%s: %s', session.id, exc)
        session.push_event({'type': 'error', 'content': 'Request timed out'})
    except Exception as exc:
        logger.exception('Unexpected error session=%s', session.id)
        session.push_event({'type': 'error', 'content': f'Internal error: {type(exc).__name__}'})
    finally:
        elapsed = time.monotonic() - turn_start
        logger.info('chat turn end session=%s elapsed=%.2fs tools=%d', session.id, elapsed, tool_count)
        session.push_event({'type': 'done'})
        await session.set_busy(False)
        session_store.flush(session.id)


@router.get('/sessions')
@handle_errors('list chat sessions')
def list_sessions(user: User = Depends(get_current_user)) -> list[dict]:
    """List all active chat sessions with preview info."""
    del user
    return session_store.list_sessions()


@router.post('/sessions')
@handle_errors('create chat session')
def create_session(body: CreateSessionRequest, user: User = Depends(get_current_user)) -> dict:
    """Create a new chat session with the given provider/model/key."""
    del user
    session = session_store.create(body.provider, body.model, body.api_key, body.system_prompt)
    return {'session_id': session.id, 'model': session.model, 'provider': session.provider}


@router.patch('/sessions/{session_id}')
@handle_errors('update chat session')
def update_session(session_id: str, body: UpdateSessionRequest, user: User = Depends(get_current_user)) -> dict:
    """Update model, system prompt, or API key on a live session."""
    del user
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    if body.provider is not None:
        session.provider = body.provider
    if body.model is not None:
        session.model = body.model
    if body.api_key is not None:
        session.api_key = body.api_key
    if body.system_prompt is not None:
        session.system_prompt = body.system_prompt
        # Update system message in conversation history
        if session.messages and session.messages[0].get('role') == 'system':
            session.messages[0]['content'] = body.system_prompt
        elif body.system_prompt:
            session.messages.insert(0, {'role': 'system', 'content': body.system_prompt})
    session_store.flush(session_id)
    return {'session_id': session_id, 'model': session.model, 'provider': session.provider}


@router.post('/message')
@handle_errors('send chat message')
async def send_message(request: Request, body: MessageRequest, user: User = Depends(get_current_user)) -> dict:
    """Send a user message; agent processing is kicked off asynchronously."""
    del user
    session = session_store.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')

    acquired = await session.acquire_turn()
    if not acquired:
        session.push_event({'type': 'error', 'content': 'Agent is busy — wait for the current turn to finish'})
        raise HTTPException(status_code=409, detail='Agent busy')
    context = build_tool_context(
        {
            'X-Session-Token': request.headers.get('X-Session-Token') or request.cookies.get('session_token') or '',
            'X-Namespace': request.headers.get('X-Namespace') or get_namespace(),
        },
    )
    task = asyncio.create_task(_run_agent_turn(session, request.app, body.content, body.tool_ids or None, context))
    session.set_task(task)
    return {'status': 'processing', 'session_id': body.session_id}


@router.post('/sessions/{session_id}/stop')
@handle_errors('stop chat generation')
async def stop_generation(session_id: str, user: User = Depends(get_current_user)) -> dict:
    """Cancel the running agent turn for a session."""
    del user
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    session.cancel_task()
    await session.set_busy(False)
    return {'status': 'stopped', 'session_id': session_id}


class ConfirmRequest(BaseModel):
    """Request body for tool confirmation."""

    approved: bool


@router.post('/sessions/{session_id}/confirm')
@handle_errors('confirm chat tool')
def confirm_tool(session_id: str, body: ConfirmRequest, user: User = Depends(get_current_user)) -> dict:
    """Confirm or deny a pending tool execution."""
    del user
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    session.resolve_confirm(body.approved)
    return {'status': 'resolved', 'approved': body.approved}


@router.get('/history/{session_id}')
@handle_errors('get chat history')
def get_history(session_id: str, user: User = Depends(get_current_user)) -> dict:
    """Return the full event history for a session."""
    del user
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'session_id': session_id, 'history': session.get_history()}


@router.get('/stream/{session_id}')
@handle_errors('stream chat events')
async def stream(session_id: str, user: User = Depends(get_current_user)) -> StreamingResponse:
    """SSE stream of chat events for a session with heartbeat."""
    del user
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')

    session.reopen_stream()

    async def generate() -> AsyncIterator[bytes]:
        queue = session._queue
        heartbeat_task: asyncio.Task[None] | None = None

        async def _heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if not session._closed:
                    queue.put_nowait({'_heartbeat': True})

        try:
            heartbeat_task = asyncio.create_task(_heartbeat_loop())
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL * 3)
                except TimeoutError:
                    yield b': heartbeat\n\n'
                    continue
                if event is None:
                    break
                if event.get('_heartbeat'):
                    yield b': heartbeat\n\n'
                    continue
                yield f'data: {json.dumps(event)}\n\n'.encode()
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task

    return StreamingResponse(generate(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@router.delete('/sessions/{session_id}')
@handle_errors('delete chat session')
def delete_session(session_id: str, user: User = Depends(get_current_user)) -> dict:
    """Close and delete a chat session."""
    del user
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'status': 'closed', 'session_id': session_id}


@router.post('/models')
@handle_errors('list chat models')
async def get_models(body: ChatModelsRequest, user: User = Depends(get_current_user)) -> list[dict]:
    """List models available for a chat provider."""
    del user
    key = _resolve_api_key(body.provider, body.api_key)
    try:
        if body.provider == 'openrouter':
            if not key:
                raise HTTPException(status_code=400, detail='No API key configured')
            return await list_models(key)
        client = get_ai_client(
            body.provider,
            endpoint_url=body.endpoint_url,
            api_key=key or None,
            organization_id=body.organization_id,
        )
        return await asyncio.to_thread(client.list_models)
    except (OpenRouterError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
