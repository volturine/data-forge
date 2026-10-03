"""Regression tests for durable chat turns, control, and event replay."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlmodel import Session

from backend_core.ai_clients import AIError
from backend_core.database import get_settings_engine
from backend_core.sqlmodel_typing import col
from modules.chat.chat_http import ChatHttpError
from modules.chat.consumer import ChatTurnConsumer, TurnRuntime
from modules.chat.models import ChatEvent, ChatMessage, ChatTurn
from modules.chat.sessions import session_store
from modules.chat.store import ChatTurnStore
from modules.mcp.models import MCPHttpMethod, MCPToolDefinition
from tests.http_client import TestClient


def _create_session(client: TestClient) -> str:
    response = client.post(
        '/api/v1/ai/chat/sessions',
        json={'provider': 'openrouter', 'model': 'test-model', 'api_key': 'test-key', 'system_prompt': 'Be concise.'},
    )
    assert response.status_code == 200
    return str(response.json()['session_id'])


def _enqueue(store: ChatTurnStore, session_id: str, content: str) -> str:
    session = session_store.get(session_id)
    assert session is not None and session.user_id is not None
    return store.enqueue(
        session_id=session_id,
        user_id=session.user_id,
        content=content,
        tool_ids=['datasource_list'],
        namespace='public',
        session_token='opaque-session-token',
    )


def test_chat_session_has_no_process_local_owner_cache() -> None:
    assert not hasattr(session_store, '_live')


def test_post_message_keeps_existing_response_shape_and_busy_is_database_claim(client: TestClient) -> None:
    session_id = _create_session(client)
    first = client.post('/api/v1/ai/chat/message', json={'session_id': session_id, 'content': 'first'})
    second = client.post('/api/v1/ai/chat/message', json={'session_id': session_id, 'content': 'second'})

    assert first.status_code == 200
    assert first.json() == {'status': 'processing', 'session_id': session_id}
    assert second.status_code == 409
    history = client.get(f'/api/v1/ai/chat/history/{session_id}')
    assert history.status_code == 200
    assert history.json()['history'][0]['content'] == 'first'
    assert isinstance(history.json()['last_event_id'], int)


def test_enqueue_flushes_turn_before_persisting_dependent_rows(client: TestClient) -> None:
    session_id = _create_session(client)
    store = ChatTurnStore()

    turn_id = _enqueue(store, session_id, 'persist in order')

    with Session(get_settings_engine()) as db:
        turn = db.get(ChatTurn, turn_id)
        message = db.execute(select(ChatMessage).where(col(ChatMessage.session_id) == session_id, col(ChatMessage.turn_id) == turn_id)).scalar_one()
        event = db.execute(select(ChatEvent).where(col(ChatEvent.session_id) == session_id, col(ChatEvent.turn_id) == turn_id)).scalar_one()

    assert turn is not None and turn.status == 'queued'
    assert message.message == {'role': 'user', 'content': 'persist in order'}
    assert event.payload['type'] == 'message'
    assert event.payload['role'] == 'user'
    assert event.payload['content'] == 'persist in order'
    assert isinstance(event.payload['ts'], int)


def test_concurrent_api_store_instances_claim_one_turn(client: TestClient) -> None:
    session_id = _create_session(client)
    first_store = ChatTurnStore()
    second_store = ChatTurnStore()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: _attempt_enqueue(*args),
                [(first_store, session_id, 'one'), (second_store, session_id, 'two')],
            )
        )

    assert sum(result != 'busy' for result in results) == 1
    assert sum(result == 'busy' for result in results) == 1
    history, _cursor, _gap = session_store.history(session_id)
    assert sum(event.get('type') == 'message' and event.get('role') == 'user' for event in history) == 1


def _attempt_enqueue(store: ChatTurnStore, session_id: str, content: str) -> str:
    try:
        return _enqueue(store, session_id, content)
    except RuntimeError as exc:
        if str(exc) == 'Agent busy':
            return 'busy'
        raise


def test_stop_and_confirmation_are_visible_across_store_instances(client: TestClient) -> None:
    session_id = _create_session(client)
    owner = ChatTurnStore()
    api_child = ChatTurnStore()
    turn_id = _enqueue(owner, session_id, 'confirm me')
    claim = owner.claim_batch(generation=3, limit=1)[0]
    owner.set_checkpoint(
        turn_id=turn_id,
        claim_token=claim.claim_token,
        generation=3,
        checkpoint={'phase': 'awaiting_confirmation', 'tool_call': {'tool_id': 'datasource_delete'}},
        status='awaiting_confirmation',
    )

    assert api_child.confirm(session_id=session_id, user_id=claim.user_id, approved=True) is True
    assert owner.control_state(turn_id=turn_id, claim_token=claim.claim_token, generation=3) == (False, True)
    assert api_child.request_stop(session_id=session_id, user_id=claim.user_id) is True
    assert owner.control_state(turn_id=turn_id, claim_token=claim.claim_token, generation=3) == (True, True)


def test_owner_recovery_interrupts_uncertain_work_and_reclaims_confirmation(client: TestClient) -> None:
    interrupted_session = _create_session(client)
    waiting_session = _create_session(client)
    store = ChatTurnStore()
    interrupted_id = _enqueue(store, interrupted_session, 'provider request')
    waiting_id = _enqueue(store, waiting_session, 'await confirmation')
    first_claims = store.claim_batch(generation=4, limit=2)
    claims = {claim.id: claim for claim in first_claims}
    store.set_checkpoint(
        turn_id=interrupted_id,
        claim_token=claims[interrupted_id].claim_token,
        generation=4,
        checkpoint={'phase': 'provider_request'},
    )
    store.set_checkpoint(
        turn_id=waiting_id,
        claim_token=claims[waiting_id].claim_token,
        generation=4,
        checkpoint={'phase': 'awaiting_confirmation', 'tool_call': {'tool_id': 'datasource_delete'}},
        status='awaiting_confirmation',
    )

    assert store.recover(generation=5) == 2
    events, _latest, _oldest = store.read_events(session_id=interrupted_session, after=0)
    assert [event.payload.get('type') for event in events][-2:] == ['error', 'done']
    from backend_core.database import get_settings_engine

    with Session(get_settings_engine()) as db:
        interrupted = db.execute(select(ChatTurn).where(col(ChatTurn.id) == interrupted_id)).scalar_one()
        assert interrupted.status == 'interrupted'
    assert store.claim_batch(generation=5, limit=1) == []
    assert store.confirm(session_id=waiting_session, user_id=claims[waiting_id].user_id, approved=True)
    resumed = store.claim_batch(generation=5, limit=1)
    assert len(resumed) == 1
    assert resumed[0].id == waiting_id
    assert resumed[0].checkpoint['phase'] == 'awaiting_confirmation'


def test_event_replay_is_independent_for_each_reader(client: TestClient) -> None:
    session_id = _create_session(client)
    store = ChatTurnStore()
    turn_id = _enqueue(store, session_id, 'replay')
    claim = store.claim_batch(generation=6, limit=1)[0]
    sequence = store.append_event(
        turn_id=turn_id,
        claim_token=claim.claim_token,
        generation=6,
        payload={'type': 'message', 'role': 'assistant', 'content': 'persisted'},
    )

    first, _latest, _oldest = store.read_events(session_id=session_id, after=sequence - 1)
    second, _latest, _oldest = store.read_events(session_id=session_id, after=sequence - 1)
    assert [event.payload for event in first] == [event.payload for event in second]
    assert first[0].sequence == sequence


def test_credentials_are_encrypted_and_event_time_is_normalized(client: TestClient) -> None:
    from backend_core.secrets import decrypt_secret
    from modules.chat.models import ChatSession

    session_id = _create_session(client)
    store = ChatTurnStore()
    turn_id = _enqueue(store, session_id, 'encrypted')
    claim = store.claim_batch(generation=7, limit=1)[0]
    store.append_event(turn_id=turn_id, claim_token=claim.claim_token, generation=7, payload={'type': 'message', 'content': 'time', 'ts': 1779554733866.484})
    with Session(get_settings_engine()) as db:
        session = db.get(ChatSession, session_id)
        turn = db.get(ChatTurn, turn_id)
        assert session is not None and turn is not None
        assert session.api_key != 'test-key' and decrypt_secret(session.api_key) == 'test-key'
        assert turn.session_token_encrypted != 'opaque-session-token'
        assert decrypt_secret(turn.session_token_encrypted) == 'opaque-session-token'
    events, _latest, _oldest = store.read_events(session_id=session_id, after=1)
    assert events[0].payload['ts'] == 1779554733866


def _tool(tool_id: str, *, confirm: bool = False) -> MCPToolDefinition:
    return MCPToolDefinition(
        id=tool_id,
        method=MCPHttpMethod.POST,
        path=f'/api/v1/{tool_id}',
        description=tool_id,
        confirm_required=confirm,
        input_schema={'type': 'object', 'properties': {}, 'additionalProperties': False},
    )


def _call(tool_id: str, call_id: str) -> dict:
    return {'id': call_id, 'type': 'function', 'function': {'name': tool_id, 'arguments': '{}'}}


def _completion(*, content: str = 'Done', calls: list[dict] | None = None, finish: str = 'stop') -> dict:
    return {'choices': [{'message': {'content': content, 'tool_calls': calls}, 'finish_reason': finish}]}


def _runtime(client: TestClient, generation: int = 10) -> TurnRuntime:
    session_id = _create_session(client)
    store = ChatTurnStore()
    _enqueue(store, session_id, 'run')
    claim = store.claim_batch(generation=generation, limit=1)[0]
    return TurnRuntime(claim, FastAPI(), (), session_store.messages(session_id))


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [ChatHttpError('bad gateway'), AIError('provider failed'), httpx.ReadTimeout('slow'), RuntimeError('unexpected')])
async def test_provider_failure_persists_error_and_terminal_state(client: TestClient, error: Exception) -> None:
    from modules.chat.routes import _run_agent_turn

    runtime = _runtime(client)
    with patch('modules.chat.routes.chat_with_tools', new=AsyncMock(side_effect=error)):
        await _run_agent_turn(runtime, runtime.app, 'run')
    history, _cursor, _gap = session_store.history(runtime.id)
    assert history[-1]['type'] == 'done'
    assert any(event['type'] == 'error' for event in history)
    with Session(get_settings_engine()) as db:
        turn = db.get(ChatTurn, runtime.turn_id)
        assert turn is not None and turn.status == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', ['broken json', '{"unknown":1}'])
async def test_invalid_tool_arguments_never_execute(client: TestClient, arguments: str) -> None:
    from modules.chat.routes import _run_agent_turn

    runtime = _runtime(client)
    call = _call('tool', 'invalid')
    call['function']['arguments'] = arguments
    provider = AsyncMock(side_effect=[_completion(content='', calls=[call]), _completion()])
    executor = AsyncMock()
    with patch('modules.chat.routes.chat_with_tools', new=provider), patch('modules.chat.routes.call_tool', new=executor):
        await _run_agent_turn(runtime, runtime.app, 'run', registry=(_tool('tool'),))
    executor.assert_not_awaited()
    assert any(event['type'] == 'tool_error' for event in session_store.history(runtime.id)[0])


@pytest.mark.asyncio
async def test_provider_refusal_drops_unanswered_tool_calls(client: TestClient) -> None:
    from modules.chat.routes import _run_agent_turn

    runtime = _runtime(client)
    provider = AsyncMock(return_value=_completion(content='', calls=[_call('tool', 'refused')], finish='length'))
    executor = AsyncMock()
    with patch('modules.chat.routes.chat_with_tools', new=provider), patch('modules.chat.routes.call_tool', new=executor):
        await _run_agent_turn(runtime, runtime.app, 'run', registry=(_tool('tool'),))
    executor.assert_not_awaited()
    assert all('tool_calls' not in message for message in session_store.messages(runtime.id))


@pytest.mark.asyncio
async def test_captured_tool_allowlist_excludes_provider_selected_tool(client: TestClient) -> None:
    from modules.chat.routes import _run_agent_turn

    runtime = _runtime(client)
    provider = AsyncMock(side_effect=[_completion(content='', calls=[_call('excluded', 'call-1')]), _completion()])
    executor = AsyncMock()
    with patch('modules.chat.routes.chat_with_tools', new=provider), patch('modules.chat.routes.call_tool', new=executor):
        await _run_agent_turn(runtime, runtime.app, 'run', tool_ids=['allowed'], registry=(_tool('allowed'), _tool('excluded')))
    executor.assert_not_awaited()
    assert any(event['type'] == 'tool_error' for event in session_store.history(runtime.id)[0])


@pytest.mark.asyncio
async def test_agent_tool_turn_limit_is_preserved(client: TestClient) -> None:
    from modules.chat.routes import _run_agent_turn

    runtime = _runtime(client)
    provider = AsyncMock(return_value=_completion(content='', calls=[_call('tool', 'loop')]))
    executor = AsyncMock(return_value={'ok': True, 'status': 200, 'body': {}})
    with patch('modules.chat.routes.chat_with_tools', new=provider), patch('modules.chat.routes.call_tool', new=executor):
        await _run_agent_turn(runtime, runtime.app, 'run', registry=(_tool('tool'),))
    assert provider.await_count == 16
    assert executor.await_count == 15
    assert 'tool-turn limit' in session_store.history(runtime.id)[0][-3]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('approved', [True, False])
async def test_confirmation_restart_preserves_decision_and_remaining_calls(client: TestClient, approved: bool) -> None:
    from modules.chat.routes import _run_agent_turn

    runtime = _runtime(client, generation=11)
    store = ChatTurnStore()
    calls = [_call('first', 'call-1'), _call('second', 'call-2')]
    await runtime.append_message({'role': 'assistant', 'content': '', 'tool_calls': calls})
    await runtime.set_checkpoint(
        {
            'phase': 'awaiting_confirmation',
            'tool_call': {'id': 'call-1', 'tool_id': 'first', 'method': 'POST', 'path': '/api/v1/first', 'args': {}},
            'remaining_calls': calls[1:],
        },
        status='awaiting_confirmation',
    )
    assert store.confirm(session_id=runtime.id, user_id=runtime.user_id, approved=approved)
    store.recover(generation=12)
    claim = store.claim_batch(generation=12, limit=1)[0]
    resumed = TurnRuntime(claim, runtime.app, (), session_store.messages(runtime.id))
    tool_executor = AsyncMock(return_value={'ok': True, 'status': 200, 'body': {'saved': True}})
    provider = AsyncMock(return_value=_completion())
    with patch('modules.chat.routes.call_tool', new=tool_executor), patch('modules.chat.routes.chat_with_tools', new=provider):
        await _run_agent_turn(resumed, resumed.app, 'run', registry=(_tool('first', confirm=True), _tool('second')))

    assert [call.args[2] for call in tool_executor.await_args_list] == (['/api/v1/first', '/api/v1/second'] if approved else ['/api/v1/second'])
    assert provider.await_args is not None
    transcript = provider.await_args.args[2]
    assert [message['tool_call_id'] for message in transcript if message['role'] == 'tool'] == ['call-1', 'call-2']
    assert session_store.history(runtime.id)[0][-1]['type'] == 'done'


def test_old_claim_cannot_append_after_confirmation_takeover(client: TestClient) -> None:
    runtime_session = _create_session(client)
    store = ChatTurnStore()
    _enqueue(store, runtime_session, 'takeover')
    old = store.claim_batch(generation=13, limit=1)[0]
    store.set_checkpoint(
        turn_id=old.id, claim_token=old.claim_token, generation=13, checkpoint={'phase': 'awaiting_confirmation'}, status='awaiting_confirmation'
    )
    store.recover(generation=14)
    assert store.confirm(session_id=runtime_session, user_id=old.user_id, approved=True)
    new = store.claim_batch(generation=14, limit=1)[0]
    assert new.claim_token != old.claim_token
    with pytest.raises(RuntimeError, match='fenced'):
        store.append_event(turn_id=old.id, claim_token=old.claim_token, generation=13, payload={'type': 'error', 'content': 'stale'})
    assert all(event.get('content') != 'stale' for event in session_store.history(runtime_session)[0])


@pytest.mark.asyncio
async def test_queued_stop_never_enters_provider_lane(client: TestClient) -> None:
    runtime = _runtime(client, generation=15)
    ChatTurnStore().request_stop(session_id=runtime.id, user_id=runtime.user_id)
    consumer = ChatTurnConsumer(runtime.app, 15)
    provider = AsyncMock(return_value=_completion())
    with patch('modules.chat.routes.chat_with_tools', new=provider):
        await consumer._run_claim(runtime.claim)
    provider.assert_not_awaited()
    assert session_store.history(runtime.id)[0][-1]['type'] == 'done'


@pytest.mark.asyncio
async def test_sync_provider_stop_is_durable_while_lane_waits_for_io_exit(client: TestClient) -> None:
    from modules.chat.routes import _run_agent_turn

    runtime = _runtime(client, generation=18)
    runtime.provider = 'ollama'
    started = Event()
    release = Event()

    def generate(*_args, **_kwargs) -> str:
        started.set()
        release.wait(5)
        return 'late result'

    with patch('modules.chat.routes.get_ai_client', return_value=SimpleNamespace(generate=generate)):
        task = asyncio.create_task(_run_agent_turn(runtime, runtime.app, 'run'))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            runtime.stop_requested = True
            task.cancel()
            for _attempt in range(200):
                if runtime.finished:
                    break
                await asyncio.sleep(0.01)
            assert runtime.finished and not task.done()
            assert session_store.history(runtime.id)[0][-1]['type'] == 'done'
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    history = session_store.history(runtime.id)[0]
    assert sum(event['type'] == 'done' for event in history) == 1
    assert all(event.get('content') != 'late result' for event in history)


@pytest.mark.asyncio
async def test_two_sse_subscribers_receive_identical_persisted_replay(client: TestClient, test_user) -> None:
    from modules.chat.routes import stream

    runtime = _runtime(client, generation=16)
    await runtime.push_event({'type': 'message', 'role': 'assistant', 'content': 'broadcast'})
    request = Request({'type': 'http', 'headers': [], 'path': '/stream', 'method': 'GET'})
    first = await stream(runtime.id, request, after=0, user=test_user)
    second = await stream(runtime.id, request, after=0, user=test_user)
    first_events = [await anext(first.body_iterator), await anext(first.body_iterator)]
    second_events = [await anext(second.body_iterator), await anext(second.body_iterator)]
    assert first_events == second_events
    assert first_events[0].startswith(b'id: 1\n')
    await first.body_iterator.aclose()
    await second.body_iterator.aclose()


@pytest.mark.asyncio
async def test_sse_retention_gap_is_explicit(client: TestClient, test_user) -> None:
    from modules.chat.routes import stream

    runtime = _runtime(client, generation=17)
    with Session(get_settings_engine()) as db:
        db.add_all([ChatEvent(session_id=runtime.id, sequence=sequence, payload={'type': 'done'}) for sequence in range(2, 506)])
        db.commit()
    await runtime.push_event({'type': 'done'})
    request = Request({'type': 'http', 'headers': [(b'last-event-id', b'1')], 'path': '/stream', 'method': 'GET'})
    response = await stream(runtime.id, request, user=test_user)
    event = await anext(response.body_iterator)
    assert b'"type":"history_gap"' in event
    assert session_store.history(runtime.id)[2] is True
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_shared_stream_recovery_batches_duplicate_session_subscribers(monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.chat.store import ChatStreamRecovery

    recovery = ChatStreamRecovery()
    stop = asyncio.Event()
    queries: list[list[str]] = []

    def latest(keys: list[str]) -> dict[str, int]:
        queries.append(keys)
        return {'one': 4}

    monkeypatch.setattr('modules.chat.store._latest_session_events', latest)
    recovery.subscribe('one')
    recovery.subscribe('one')
    first = asyncio.create_task(recovery.wait('one', 0))
    second = asyncio.create_task(recovery.wait('one', 0))
    task = asyncio.create_task(recovery.run(stop))
    assert await asyncio.wait_for(first, 2) == await asyncio.wait_for(second, 2)
    assert queries == [['one']]
    recovery.unsubscribe('one')
    recovery.unsubscribe('one')
    stop.set()
    await task
