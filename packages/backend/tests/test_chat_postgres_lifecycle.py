"""Chat deletion and claim revocation using the normal backend PostgreSQL fixtures."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import pytest
from fastapi import FastAPI
from sqlalchemy import Connection, Engine, event, select, text
from sqlmodel import Session

import modules.chat.routes as routes_module
from backend_core.database import get_settings_engine
from backend_core.sqlmodel_typing import col
from modules.auth.models import User
from modules.chat.consumer import ChatTurnConsumer
from modules.chat.models import ChatEvent, ChatSession, ChatTurn
from modules.chat.sessions import ChatSessionBusy, session_store
from modules.chat.store import ChatTurnStore
from modules.mcp.models import MCPToolDefinition
from runtime_coordinator import _supervise_epoch
from tests.http_client import TestClient


def _create_session(client: TestClient) -> str:
    response = client.post('/api/v1/ai/chat/sessions', json={'provider': 'openrouter', 'model': 'test', 'api_key': 'key'})
    assert response.status_code == 200
    return str(response.json()['session_id'])


def _enqueue(session_id: str, user_id: str, content: str) -> str:
    return ChatTurnStore().enqueue(session_id=session_id, user_id=user_id, content=content, tool_ids=[], namespace='default', session_token='token')


def test_claim_batch_fails_only_turn_with_undecryptable_credentials(test_user: User) -> None:
    engine = get_settings_engine()
    assert engine.dialect.name == 'postgresql'
    poisoned_session = session_store.create('openrouter', 'test', 'poisoned-api-key', user_id=test_user.id)
    valid_session = session_store.create('openrouter', 'test', 'valid-api-key', user_id=test_user.id)
    poisoned_turn_id = _enqueue(poisoned_session.id, test_user.id, 'poisoned turn')
    valid_turn_id = _enqueue(valid_session.id, test_user.id, 'valid turn')

    with Session(engine) as db:
        session = db.get(ChatSession, poisoned_session.id)
        assert session is not None
        session.api_key = 'enc:v1:corrupt'
        db.add(session)
        db.commit()

    claims = ChatTurnStore().claim_batch(generation=9, limit=2)

    assert len(claims) == 1
    assert claims[0].id == valid_turn_id
    assert claims[0].api_key == 'valid-api-key'
    with Session(engine) as db:
        poisoned = db.get(ChatTurn, poisoned_turn_id)
        assert poisoned is not None
        assert poisoned.status == 'failed'
        assert poisoned.claim_token is None
        assert poisoned.coordinator_generation is None
        events = db.execute(select(ChatEvent).where(col(ChatEvent.turn_id) == poisoned_turn_id).order_by(col(ChatEvent.sequence))).scalars().all()
        payloads = [event.payload for event in events]
    errors = [payload['content'] for payload in payloads if payload.get('type') == 'error']
    assert errors == ['Chat credentials could not be decrypted; update the session credentials and try again.']
    assert not any('poisoned-api-key' in message for message in errors)
    assert any(payload.get('type') == 'done' for payload in payloads)


@pytest.mark.parametrize('status', ['queued', 'running', 'awaiting_confirmation'])
def test_active_session_delete_returns_conflict_and_preserves_turn(client: TestClient, test_user: User, status: str) -> None:
    session_id = _create_session(client)
    store = ChatTurnStore()
    turn_id = _enqueue(session_id, test_user.id, 'keep the durable owner')
    if status != 'queued':
        claim = store.claim_batch(generation=1, limit=1)[0]
        if status == 'awaiting_confirmation':
            store.set_checkpoint(turn_id=turn_id, claim_token=claim.claim_token, generation=1, checkpoint={}, status=status)

    response = client.delete(f'/api/v1/ai/chat/sessions/{session_id}')

    assert response.status_code == 409
    assert session_store.get(session_id) is not None
    with Session(get_settings_engine()) as db:
        turn = db.get(ChatTurn, turn_id)
        assert turn is not None and turn.status == status


@pytest.mark.parametrize('first_operation', ['enqueue', 'delete'])
def test_session_delete_and_enqueue_serialize_on_postgres_session_lock(client: TestClient, test_user: User, first_operation: str) -> None:
    session_id = _create_session(client)
    engine = get_settings_engine()
    assert engine.dialect.name == 'postgresql'
    winner_locked = Event()
    release_winner = Event()
    loser_started = Event()
    winner_threads: list[int] = []
    loser_pids: list[int] = []

    def before_execute(connection: Connection, _cursor: object, statement: str, _parameters: object, _context: object, _executemany: bool) -> None:
        if 'chat_sessions' in statement and 'FOR UPDATE' in statement and get_ident() != winner_threads[0]:
            loser_pids.append(int(connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one()))
            loser_started.set()

    def after_execute(_connection: Connection, _cursor: object, statement: str, _parameters: object, _context: object, _executemany: bool) -> None:
        if 'chat_sessions' in statement and 'FOR UPDATE' in statement and get_ident() == winner_threads[0] and not winner_locked.is_set():
            winner_locked.set()
            assert release_winner.wait(10), 'Test did not release the session row lock'

    def operate(operation: str, *, winner: bool = False) -> str | bool:
        if winner:
            winner_threads.append(get_ident())
        if operation == 'delete':
            return session_store.delete(session_id, user_id=test_user.id)
        return _enqueue(session_id, test_user.id, 'accepted')

    event.listen(engine, 'before_cursor_execute', before_execute)
    event.listen(engine, 'after_cursor_execute', after_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            winner = executor.submit(operate, first_operation, winner=True)
            try:
                assert winner_locked.wait(3)
                loser = executor.submit(operate, 'delete' if first_operation == 'enqueue' else 'enqueue')
                assert loser_started.wait(3)
                deadline = time.monotonic() + 3
                with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as observer:
                    while observer.execute(text('SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid'), {'pid': loser_pids[0]}).scalar() != 'Lock':
                        assert time.monotonic() < deadline, 'The competing operation did not wait on the session row lock'
                        time.sleep(0.01)
            finally:
                release_winner.set()
            result = winner.result(timeout=3)
            if first_operation == 'enqueue':
                with pytest.raises(ChatSessionBusy):
                    loser.result(timeout=3)
                with Session(engine) as db:
                    assert db.get(ChatTurn, result) is not None
                assert session_store.get(session_id) is not None
            else:
                assert result is True
                with pytest.raises(LookupError, match='Session not found'):
                    loser.result(timeout=3)
                assert session_store.get(session_id) is None
    finally:
        event.remove(engine, 'before_cursor_execute', before_execute)
        event.remove(engine, 'after_cursor_execute', after_execute)


@pytest.mark.asyncio
@pytest.mark.parametrize('removed', [True, False])
async def test_postgres_claim_revocation_preserves_later_chat_and_other_actor(
    isolate_settings_engine: Engine, test_user: User, monkeypatch: pytest.MonkeyPatch, removed: bool
) -> None:
    engine = isolate_settings_engine
    assert engine.dialect.name == 'postgresql'
    first = await asyncio.to_thread(session_store.create, 'openrouter', 'test', 'key', user_id=test_user.id)
    first_turn = await asyncio.to_thread(_enqueue, first.id, test_user.id, 'first')
    provider_started = asyncio.Event()
    release_provider = asyncio.Event()
    stop = asyncio.Event()
    grpc_exited = asyncio.Event()

    async def provider(_api_key: str, _model: str, messages: list[dict], _tools: list[MCPToolDefinition]) -> dict:
        if any(message.get('content') == 'first' for message in messages):
            provider_started.set()
            await release_provider.wait()
        return {'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}

    def revoke() -> None:
        with Session(engine) as db:
            turn = db.get(ChatTurn, first_turn)
            assert turn is not None and turn.status == 'running'
            if removed:
                db.delete(turn)
            else:
                turn.claim_token = 'revoked'
            db.commit()

    def completed(turn_id: str) -> bool:
        with Session(engine) as db:
            turn = db.get(ChatTurn, turn_id)
            return turn is not None and turn.status == 'completed'

    async def grpc_actor() -> None:
        try:
            await stop.wait()
        finally:
            grpc_exited.set()

    monkeypatch.setattr(routes_module, 'chat_with_tools', provider)
    consumer = ChatTurnConsumer(FastAPI(), 1)
    consumer_task = asyncio.create_task(consumer.run(stop), name='chat-turn-consumer')
    grpc_task = asyncio.create_task(grpc_actor(), name='runtime-grpc')
    process_stop = asyncio.create_task(stop.wait())
    owner_stop = asyncio.create_task(stop.wait())
    supervisor = asyncio.create_task(_supervise_epoch([consumer_task, grpc_task], process_stop, owner_stop))
    try:
        await asyncio.wait_for(provider_started.wait(), 5)
        await asyncio.to_thread(revoke)
        release_provider.set()
        later = await asyncio.to_thread(session_store.create, 'openrouter', 'test', 'key', user_id=test_user.id)
        later_turn = await asyncio.to_thread(_enqueue, later.id, test_user.id, 'later')
        consumer.wake()
        deadline = time.monotonic() + 5
        while not await asyncio.to_thread(completed, later_turn):
            assert time.monotonic() < deadline, 'The later chat turn did not complete'
            assert not supervisor.done(), 'Claim revocation escaped into coordinator supervision'
            await asyncio.sleep(0.01)
        assert not consumer_task.done()
        assert not supervisor.done()
        assert not grpc_exited.is_set()
    finally:
        release_provider.set()
        stop.set()
        await asyncio.wait_for(asyncio.gather(consumer_task, grpc_task, supervisor, process_stop, owner_stop), 5)
