"""Turn lifecycle regressions that do not require running services."""

import asyncio
from collections.abc import Callable, Generator
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

import modules.chat.consumer as consumer_module
import modules.chat.routes as routes_module
from backend_core import database
from backend_core.ai_clients import AIClient
from backend_core.config import settings
from backend_core.database import RuntimeCoordinatorFenced
from modules.auth.models import User
from modules.chat.consumer import ChatTurnConsumer, TurnRuntime
from modules.chat.models import ChatSession, ChatTurn
from modules.chat.sessions import session_store
from modules.chat.store import ChatClaimRevoked, ChatTurnStore, TurnClaim, _verify_claim
from modules.mcp.models import MCPHttpMethod, MCPToolDefinition
from runtime_coordinator import _supervise_epoch


def _claim_batches_then_idle(*batches: list[TurnClaim]) -> Callable[..., list[TurnClaim]]:
    remaining = iter(batches)
    return lambda *_args, **_kwargs: next(remaining, [])


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # This module tests lifecycle boundaries without the shared Docker fixtures.
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    monkeypatch.setattr(settings, 'settings_encryption_key', 'test-key')


@pytest.fixture(autouse=True)
def isolate_settings_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine]:
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    ChatSession.metadata.create_all(
        engine, tables=[ChatSession.metadata.tables[name] for name in ('chat_sessions', 'chat_turns', 'chat_messages', 'chat_events')]
    )
    monkeypatch.setattr(database, 'settings_engine', engine)
    monkeypatch.setattr(database, '_settings_engine_override', None)
    try:
        yield engine
    finally:
        engine.dispose()


def _claim(turn_id: str = 'removed') -> TurnClaim:
    return TurnClaim(
        id=turn_id,
        session_id=f'session-{turn_id}',
        user_id='user',
        content='run',
        tool_ids=(),
        namespace='default',
        session_token='token',
        provider='openrouter',
        model='test',
        api_key='key',
        system_prompt='',
        checkpoint={},
        claim_token='claim',
        coordinator_generation=1,
        confirmation_decision=None,
    )


@pytest.mark.parametrize('status', ['queued', 'running', 'awaiting_confirmation'])
def test_delete_conflicts_with_active_turn(status: str) -> None:
    session = session_store.create('openrouter', 'test', 'key', user_id='user')
    store = ChatTurnStore()
    turn_id = store.enqueue(session_id=session.id, user_id='user', content='run', tool_ids=[], namespace='default', session_token='token')
    if status != 'queued':
        claim = store.claim_batch(generation=1, limit=1)[0]
        store.set_checkpoint(turn_id=turn_id, claim_token=claim.claim_token, generation=1, checkpoint={}, status=status)

    with pytest.raises(HTTPException) as result:
        routes_module.delete_session(session.id, User(id='user'))

    assert result.value.status_code == 409
    assert session_store.get(session.id) is not None
    with Session(database.get_settings_engine()) as db:
        turn = db.get(ChatTurn, turn_id)
        assert turn is not None and turn.status == status


def test_idle_delete_keeps_closed_response_and_owned_404() -> None:
    session = session_store.create('openrouter', 'test', 'key', user_id='user')
    with pytest.raises(HTTPException) as foreign:
        routes_module.delete_session(session.id, User(id='foreign'))
    assert foreign.value.status_code == 404
    assert routes_module.delete_session(session.id, User(id='user')) == {'status': 'closed', 'session_id': session.id}
    with pytest.raises(HTTPException) as missing:
        routes_module.delete_session(session.id, User(id='user'))
    assert missing.value.status_code == 404


@pytest.mark.parametrize('state', ['missing', 'revoked', 'finished', 'unassigned', 'new_epoch'])
def test_claim_loss_distinguishes_turn_lifecycle_from_epoch_fencing(state: str) -> None:
    session = session_store.create('openrouter', 'test', 'key', user_id='user')
    store = ChatTurnStore()
    turn_id = store.enqueue(session_id=session.id, user_id='user', content='run', tool_ids=[], namespace='default', session_token='token')
    claim = store.claim_batch(generation=1, limit=1)[0]
    with Session(database.get_settings_engine()) as db:
        turn = db.get(ChatTurn, turn_id)
        assert turn is not None
        if state == 'missing':
            db.delete(turn)
        if state == 'revoked':
            turn.claim_token = 'other-claim'
        if state == 'finished':
            turn.status = 'completed'
            turn.claim_token = None
            turn.coordinator_generation = None
        if state == 'new_epoch':
            turn.coordinator_generation = 2
        if state == 'unassigned':
            turn.coordinator_generation = None
        db.commit()
        error = RuntimeCoordinatorFenced if state == 'new_epoch' else ChatClaimRevoked
        with pytest.raises(error):
            _verify_claim(db, turn_id, claim.claim_token, 1)


@pytest.mark.parametrize('global_generation', [1, 2])
def test_global_epoch_check_precedes_missing_turn_classification(monkeypatch: pytest.MonkeyPatch, global_generation: int) -> None:
    monkeypatch.setattr(database, '_ACTIVE_RUNTIME_COORDINATOR_GENERATION', 1)
    connection = create_autospec(Connection, instance=True)
    connection.dialect = create_autospec(PGDialect_psycopg, instance=True)
    connection.dialect.name = 'postgresql'
    connection.execute.return_value.scalar_one_or_none.return_value = global_generation
    db = create_autospec(Session, instance=True)
    missing = db.execute.return_value
    missing.scalar_one_or_none.return_value = None

    def execute(_statement: object) -> object:
        database._fence_runtime_transaction(db, None, connection)
        return missing

    db.execute.side_effect = execute
    error = ChatClaimRevoked if global_generation == 1 else RuntimeCoordinatorFenced
    with pytest.raises(error):
        _verify_claim(db, 'removed', 'claim', 1)
    connection.execute.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['plain_provider', 'confirmation', 'queued_stop', 'missing_key'])
async def test_agent_early_returns_preserve_durable_terminal_or_confirmation_state(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    session = session_store.create('openrouter', 'test', 'key', user_id='user')
    store = ChatTurnStore()
    store.enqueue(session_id=session.id, user_id='user', content='run', tool_ids=[], namespace='default', session_token='token')
    claim = store.claim_batch(generation=1, limit=1)[0]
    runtime = TurnRuntime(claim, FastAPI(), (), [])
    provider = AsyncMock(return_value={'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]})
    tool_executor = AsyncMock()
    monkeypatch.setattr(routes_module, 'chat_with_tools', provider)
    monkeypatch.setattr(routes_module, 'call_tool', tool_executor)
    if path == 'plain_provider':
        runtime.provider = 'ollama'
        client = create_autospec(AIClient, instance=True)
        client.generate.return_value = 'answer'
        monkeypatch.setattr(routes_module, 'get_ai_client', lambda *_args, **_kwargs: client)
        await routes_module._run_agent_turn(runtime, runtime.app, 'run')
        client.generate.assert_called_once()
    elif path == 'confirmation':
        tool = MCPToolDefinition(
            id='mutate', method=MCPHttpMethod.POST, path='/api/v1/mutate', description='mutate', confirm_required=True, input_schema={'type': 'object'}
        )
        provider.return_value = {
            'choices': [{'message': {'tool_calls': [{'id': 'call', 'function': {'name': 'mutate', 'arguments': '{}'}}]}, 'finish_reason': 'tool_calls'}]
        }
        await routes_module._run_agent_turn(runtime, runtime.app, 'run', registry=(tool,))
    elif path == 'queued_stop':
        store.request_stop(session_id=session.id, user_id='user')
        await ChatTurnConsumer(runtime.app, 1)._run_claim(claim)
    else:
        runtime.api_key = ''
        await routes_module._run_agent_turn(runtime, runtime.app, 'run')

    with Session(database.get_settings_engine()) as db:
        turn = db.get(ChatTurn, claim.id)
        assert turn is not None
        assert turn.status == ('awaiting_confirmation' if path == 'confirmation' else 'completed' if path == 'plain_provider' else 'failed')
        assert turn.claim_token is None
    history = session_store.history(session.id)[0]
    assert sum(item['type'] == 'done' for item in history) == (0 if path == 'confirmation' else 1)
    tool_executor.assert_not_awaited()
    if path != 'confirmation':
        provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('removed', [True, False])
async def test_consumer_handles_actual_removed_or_revoked_store_row(monkeypatch: pytest.MonkeyPatch, removed: bool) -> None:
    session = session_store.create('openrouter', 'test', 'key', user_id='user')
    store = ChatTurnStore()
    store.enqueue(session_id=session.id, user_id='user', content='run', tool_ids=[], namespace='default', session_token='token')
    claim = store.claim_batch(generation=1, limit=1)[0]
    with Session(database.get_settings_engine()) as db:
        turn = db.get(ChatTurn, claim.id)
        assert turn is not None
        if removed:
            db.delete(turn)
        else:
            turn.claim_token = 'revoked'
        db.commit()

    provider = AsyncMock()
    monkeypatch.setattr(routes_module, 'chat_with_tools', provider)
    await ChatTurnConsumer(FastAPI(), 1)._run_claim(claim)
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['control_state', 'set_checkpoint', 'append_event', 'finish', 'watcher'])
async def test_revoked_turn_does_not_stop_later_turn_or_grpc_actor(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    store = create_autospec(ChatTurnStore, instance=True)
    store.recover.return_value = 0
    store.claim_batch.side_effect = _claim_batches_then_idle([_claim()], [_claim('later')], [])
    store.control_state.return_value = (False, None)
    store.append_event.return_value = 1
    loop = asyncio.get_running_loop()
    later_finished = asyncio.Event()
    stop = asyncio.Event()
    grpc_exited = asyncio.Event()
    control_reads = 0

    def fail_removed(*_args: object, **kwargs: object) -> object:
        nonlocal control_reads
        if kwargs['turn_id'] == 'removed':
            control_reads += 1
            if operation != 'watcher' or control_reads > 1:
                raise ChatClaimRevoked('Removed or revoked turn')
        if operation in ('control_state', 'watcher'):
            return False, None
        return 1 if operation == 'append_event' else None

    def finish(*_args: object, **kwargs: object) -> None:
        if kwargs['turn_id'] == 'removed' and operation == 'finish':
            raise ChatClaimRevoked('Removed or revoked turn')
        if kwargs['turn_id'] == 'later':
            loop.call_soon_threadsafe(later_finished.set)

    methods = {'control_state': store.control_state, 'set_checkpoint': store.set_checkpoint, 'append_event': store.append_event}
    if operation == 'watcher':
        store.control_state.side_effect = fail_removed
    if operation in methods:
        methods[operation].side_effect = fail_removed
    store.finish.side_effect = finish

    async def load_turn(claim: TurnClaim, app: FastAPI, registry: tuple) -> TurnRuntime:
        return TurnRuntime(claim, app, registry, [])

    async def grpc_actor() -> None:
        try:
            await stop.wait()
        finally:
            grpc_exited.set()

    monkeypatch.setattr(consumer_module, 'chat_turn_store', store)
    monkeypatch.setattr(consumer_module, '_load_turn', load_turn)
    monkeypatch.setattr(routes_module, 'chat_with_tools', AsyncMock(return_value={'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}))
    consumer = ChatTurnConsumer(FastAPI(), 1)
    consumer_task = asyncio.create_task(consumer.run(stop), name='chat-turn-consumer')
    grpc_task = asyncio.create_task(grpc_actor(), name='runtime-grpc')
    process_stop = asyncio.create_task(stop.wait())
    owner_stop = asyncio.create_task(stop.wait())
    supervisor = asyncio.create_task(_supervise_epoch([consumer_task, grpc_task], process_stop, owner_stop))
    try:
        await asyncio.wait_for(later_finished.wait(), 3)
        assert not consumer_task.done()
        assert not supervisor.done()
        assert not grpc_exited.is_set()
        assert store.claim_batch.call_count >= 2
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(consumer_task, grpc_task, supervisor, process_stop, owner_stop), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['load', 'agent', 'watcher'])
@pytest.mark.parametrize('error', [OperationalError('SELECT', {}, RuntimeError('database unavailable')), RuntimeCoordinatorFenced('Epoch superseded')])
async def test_infrastructure_failures_still_fail_closed(monkeypatch: pytest.MonkeyPatch, phase: str, error: Exception) -> None:
    store = create_autospec(ChatTurnStore, instance=True)
    store.recover.return_value = 0
    store.claim_batch.side_effect = _claim_batches_then_idle([_claim()], [])
    store.control_state.return_value = (False, None)
    store.append_event.return_value = 1
    if phase == 'agent':
        store.set_checkpoint.side_effect = error
    if phase == 'watcher':
        initial_control_state_pending = True

        def control_state_side_effect(*_args: object, **_kwargs: object) -> tuple[bool, None]:
            nonlocal initial_control_state_pending
            if initial_control_state_pending:
                initial_control_state_pending = False
                return False, None
            raise error

        store.control_state.side_effect = control_state_side_effect

    async def load_turn(claim: TurnClaim, app: FastAPI, registry: tuple) -> TurnRuntime:
        if phase == 'load':
            raise error
        return TurnRuntime(claim, app, registry, [])

    async def wait_for_watcher(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(consumer_module, 'chat_turn_store', store)
    monkeypatch.setattr(consumer_module, '_load_turn', load_turn)
    monkeypatch.setattr(routes_module, 'chat_with_tools', AsyncMock(side_effect=wait_for_watcher))
    stop = asyncio.Event()
    consumer_task = asyncio.create_task(ChatTurnConsumer(FastAPI(), 1).run(stop), name='chat-turn-consumer')
    process_stop = asyncio.create_task(stop.wait())
    owner_stop = asyncio.create_task(stop.wait())
    try:
        with pytest.raises(RuntimeError, match='chat-turn-consumer failed') as failure:
            await asyncio.wait_for(_supervise_epoch([consumer_task], process_stop, owner_stop), 3)
        assert failure.value.__cause__ is error
        assert consumer_task.exception() is error
        if phase == 'agent':
            store.append_event.assert_not_called()
            store.finish.assert_not_called()
    finally:
        stop.set()
        await asyncio.gather(consumer_task, process_stop, owner_stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_revocation_during_sync_provider_io_keeps_admission_until_thread_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    store = create_autospec(ChatTurnStore, instance=True)
    store.append_event.side_effect = ChatClaimRevoked('Turn was removed')
    monkeypatch.setattr(consumer_module, 'chat_turn_store', store)
    runtime = TurnRuntime(replace(_claim(), provider='ollama'), FastAPI(), (), [])
    started = Event()
    release = Event()

    def generate() -> str:
        started.set()
        assert release.wait(3)
        return 'late result'

    task = asyncio.create_task(runtime.run_sync_provider(generate))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        while not store.append_event.called:
            await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(ChatClaimRevoked):
            await asyncio.wait_for(task, 2)
        store.finish.assert_not_called()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
