"""Chat API routes — session management, message sending, SSE streaming, apply."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from modules.chat.openrouter import chat_with_tools, list_models
from modules.chat.sessions import LiveSession, session_store
from modules.mcp.executor import call_tool
from modules.mcp.pending import pending_store
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


class MessageRequest(BaseModel):
    """Request body to send a message."""

    session_id: str
    content: str
    tool_ids: list[str] = []


class ApplyRequest(BaseModel):
    """Request body to apply a pending tool action."""

    session_id: str
    token: str


def _resolve_api_key(session_key: str) -> str:
    """Return session key if set, otherwise fall back to global settings key."""
    if session_key:
        return session_key
    from modules.settings.service import get_resolved_openrouter_key

    return get_resolved_openrouter_key()


def _infer_patch(tool_id: str, method: str, path: str, result: dict) -> dict | None:
    """Infer a ui_patch event from tool method/path and response body."""
    if not result.get('ok'):
        return None
    parts = [p for p in path.split('/') if p]
    resource = parts[3] if len(parts) > 3 else (parts[2] if len(parts) > 2 else 'unknown')
    action_map = {'GET': 'refresh', 'POST': 'created', 'PUT': 'updated', 'PATCH': 'updated', 'DELETE': 'deleted'}
    action = action_map.get(method, 'refresh')
    body = result.get('body')
    record_id = None
    if isinstance(body, dict):
        record_id = body.get('id')
    return {'resource': resource, 'action': action, 'id': record_id, 'data': body}


async def _run_agent_turn(session: LiveSession, app: Any, user_content: str, tool_ids: list[str] | None = None) -> None:
    """Run one agent turn: send message, handle tool calls, push SSE events."""
    from modules.mcp.routes import get_registry

    api_key = _resolve_api_key(session.api_key)
    if not api_key:
        session.push_event({'type': 'error', 'content': 'No API key configured'})
        session.push_event({'type': 'done'})
        session.set_busy(False)
        session_store.flush(session.id)
        return

    turn_start = time.monotonic()
    tool_count = 0
    turn_usage: dict[str, int] = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    logger.info('chat turn start session=%s user_len=%d', session.id, len(user_content))

    session.add_message('user', user_content)
    session.push_event({'type': 'message', 'role': 'user', 'content': user_content})

    registry = get_registry(app)
    if tool_ids:
        id_set = set(tool_ids)
        registry = [t for t in registry if t['id'] in id_set]
    safe_tools = [t for t in registry if t['safety'] == 'safe']
    mutating_tools = [t for t in registry if t['safety'] == 'mutating']
    all_tools = safe_tools + mutating_tools

    max_turns = 5
    for _ in range(max_turns):
        response = await chat_with_tools(
            api_key,
            session.model,
            session.messages,
            all_tools,
        )
        choice = response.get('choices', [{}])[0]
        msg = choice.get('message', {})
        finish = choice.get('finish_reason', '')

        usage = response.get('usage', {})
        turn_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
        turn_usage['completion_tokens'] += usage.get('completion_tokens', 0)
        turn_usage['total_tokens'] += usage.get('total_tokens', 0)

        assistant_content = msg.get('content') or ''
        tool_calls = msg.get('tool_calls') or []

        session.messages.append({'role': 'assistant', 'content': assistant_content, 'tool_calls': tool_calls or None})

        if assistant_content:
            session.push_event({'type': 'message', 'role': 'assistant', 'content': assistant_content})

        if not tool_calls or finish not in ('tool_calls', 'stop', None, ''):
            break

        for tc in tool_calls:
            fn = tc.get('function', {})
            tool_id = fn.get('name', '')
            raw_args = fn.get('arguments', '{}')
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

            tool = next((t for t in all_tools if t['id'] == tool_id), None)
            if tool is None:
                continue

            method = tool['method']
            path = tool['path']
            tool_count += 1

            session.push_event({'type': 'tool_call', 'tool_id': tool_id, 'method': method, 'path': path, 'args': args})

            valid, errors, normalized = validate_args(tool.get('input_schema', {'type': 'object'}), args)
            if not valid:
                session.push_event(
                    {'type': 'tool_error', 'tool_id': tool_id, 'method': method, 'path': path, 'args': args, 'errors': errors}
                )
                tool_result_str = json.dumps({'status': 'validation_error', 'errors': errors})
                session.messages.append(
                    {
                        'role': 'tool',
                        'tool_call_id': tc.get('id', tool_id),
                        'content': tool_result_str,
                    }
                )
                continue

            token = pending_store.create(tool_id, method, path, normalized)
            event: dict[str, Any] = {
                'type': 'pending',
                'token': token,
                'tool_id': tool_id,
                'method': method,
                'path': path,
                'args': normalized,
                'confirm_required': tool.get('confirm_required', False),
            }
            session.push_event(event)
            tool_result_str = json.dumps({'status': 'pending', 'token': token})

            session.messages.append(
                {
                    'role': 'tool',
                    'tool_call_id': tc.get('id', tool_id),
                    'content': tool_result_str,
                }
            )

        if finish not in ('tool_calls',):
            break

    elapsed = time.monotonic() - turn_start
    logger.info('chat turn end session=%s elapsed=%.2fs tools=%d', session.id, elapsed, tool_count)

    session.push_event({'type': 'usage', **turn_usage})
    session.push_event({'type': 'done'})
    session.set_busy(False)
    session_store.flush(session.id)


@router.post('/sessions')
def create_session(body: CreateSessionRequest) -> dict:
    """Create a new chat session with the given provider/model/key."""
    session = session_store.create(body.provider, body.model, body.api_key, body.system_prompt)
    return {'session_id': session.id, 'model': session.model, 'provider': session.provider}


@router.post('/message')
async def send_message(request: Request, body: MessageRequest) -> dict:
    """Send a user message; agent processing is kicked off asynchronously."""
    session = session_store.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')

    if session.busy:
        session.push_event({'type': 'error', 'content': 'Agent is busy — wait for the current turn to finish'})
        raise HTTPException(status_code=409, detail='Agent busy')

    session.set_busy(True)
    asyncio.create_task(_run_agent_turn(session, request.app, body.content, body.tool_ids or None))
    return {'status': 'processing', 'session_id': body.session_id}


@router.get('/history/{session_id}')
def get_history(session_id: str) -> dict:
    """Return the full event history for a session."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'session_id': session_id, 'history': session.get_history()}


@router.get('/stream/{session_id}')
async def stream(session_id: str) -> StreamingResponse:
    """SSE stream of chat events for a session with heartbeat."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')

    session.reopen_stream()

    async def generate() -> AsyncIterator[bytes]:
        queue = session._queue

        async def _heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if not session._closed:
                    queue.put_nowait({'_heartbeat': True})

        heartbeat_task = asyncio.create_task(_heartbeat_loop())

        while True:
            event = await queue.get()
            if event is None:
                break
            if event.get('_heartbeat'):
                yield b': heartbeat\n\n'
                continue
            yield f'data: {json.dumps(event)}\n\n'.encode()

        heartbeat_task.cancel()

    return StreamingResponse(generate(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@router.delete('/sessions/{session_id}')
def delete_session(session_id: str) -> dict:
    """Close and delete a chat session."""
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'status': 'closed', 'session_id': session_id}


@router.post('/apply')
async def apply(request: Request, body: ApplyRequest) -> dict:
    """Apply a pending tool action by token."""
    session = session_store.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')

    entry = pending_store.pop(body.token)
    if entry is None:
        raise HTTPException(status_code=404, detail='Token not found or expired')

    result = await call_tool(request.app, entry['method'], entry['path'], entry['args'])
    patch = _infer_patch(entry['tool_id'], entry['method'], entry['path'], result)

    session.messages.append({'role': 'tool', 'tool_call_id': entry['tool_id'], 'content': json.dumps(result.get('body', ''))})

    event: dict[str, Any] = {'type': 'tool_result', 'tool_id': entry['tool_id'], 'result': result}
    session.push_event(event)
    if patch:
        session.push_event({'type': 'ui_patch', **patch})

    session_store.flush(body.session_id)
    return {'status': 'executed', 'result': result, 'patch': patch}


@router.get('/models')
async def get_models(api_key: str = '') -> list[dict]:
    """List models available from OpenRouter. Uses provided key or falls back to global."""
    from modules.settings.service import get_resolved_openrouter_key

    key = api_key or get_resolved_openrouter_key()
    if not key:
        raise HTTPException(status_code=400, detail='No API key configured')
    return await list_models(key)
