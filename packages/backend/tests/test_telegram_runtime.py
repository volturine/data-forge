import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlmodel import Session

from backend_core.persistence.runtime_events.models import RuntimeCoordinatorState
from backend_core.persistence.telegram.models import TelegramDetectionRequest, TelegramPollOffset
from backend_core.secrets import decrypt_secret
from modules.telegram import runtime, store
from modules.telegram.domain import TelegramDetectionClaim, TelegramSettings


@pytest.fixture
def telegram_db(test_engine):
    with test_engine.begin() as connection:
        for model in (RuntimeCoordinatorState, TelegramPollOffset, TelegramDetectionRequest):
            model.__table__.create(connection, checkfirst=False)
    with Session(test_engine) as session:
        session.add(RuntimeCoordinatorState(singleton_id=1, generation=7))
        session.commit()
        yield session


def test_offset_is_durable_monotonic_and_fenced(telegram_db) -> None:
    fingerprint = store.token_fingerprint('secret-token')
    store.advance_update_id(telegram_db, fingerprint=fingerprint, next_update_id=12, generation=7, chats=[])
    store.advance_update_id(telegram_db, fingerprint=fingerprint, next_update_id=10, generation=7, chats=[])
    assert store.get_next_update_id(telegram_db, fingerprint) == 12
    assert telegram_db.get(TelegramPollOffset, 'secret-token') is None
    with pytest.raises(store.TelegramOwnerFenced):
        store.advance_update_id(telegram_db, fingerprint=fingerprint, next_update_id=13, generation=6, chats=[])


def test_stale_owner_cannot_mutate_subscriber(telegram_db) -> None:
    from modules.telegram.bot import _add_subscriber

    with pytest.raises(store.TelegramOwnerFenced):
        _add_subscriber(telegram_db, '42', 'Test', 'secret-token', 6)


def test_detection_recovers_after_epoch_change_and_scrubs_token(telegram_db) -> None:
    request_id = store.enqueue_detection(telegram_db, token='secret-token', request_user_id='user-1', namespace='tenant-a')
    row = telegram_db.get(TelegramDetectionRequest, request_id)
    assert row is not None
    assert decrypt_secret(row.token_encrypted) == 'secret-token'
    assert row.token_encrypted != 'secret-token'
    first = store.claim_detection(telegram_db, generation=7)
    assert first is not None
    assert store.get_detection_result(telegram_db, request_id=request_id, request_user_id='user-2') is None
    state = telegram_db.get(RuntimeCoordinatorState, 1)
    assert state is not None
    state.generation = 8
    telegram_db.add(state)
    telegram_db.commit()
    store.recover_detection_requests(telegram_db, generation=8)
    second = store.claim_detection(telegram_db, generation=8)
    assert second is not None and second.request_id == first.request_id
    with pytest.raises(store.TelegramOwnerFenced):
        store.complete_detection(telegram_db, claim=first, result={'success': True})
    assert store.complete_detection(telegram_db, claim=second, result={'success': True, 'message': 'Found 0 chat(s)', 'chats': []})
    telegram_db.refresh(row)
    assert row.token_encrypted == ''
    assert row.status == 'completed'


def test_detection_overload_and_expiration_are_bounded(telegram_db, monkeypatch) -> None:
    monkeypatch.setattr(store, 'MAX_PENDING_DETECTIONS', 1)
    request_id = store.enqueue_detection(telegram_db, token='secret-token', request_user_id='user-1', namespace='tenant-a')
    with pytest.raises(store.DetectionQueueFull):
        store.enqueue_detection(telegram_db, token='other-token', request_user_id='user-2', namespace='tenant-b')
    row = telegram_db.get(TelegramDetectionRequest, request_id)
    assert row is not None
    row.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    telegram_db.add(row)
    telegram_db.commit()
    store.recover_detection_requests(telegram_db, generation=7)
    telegram_db.refresh(row)
    assert row.status == 'timed_out'
    assert row.token_encrypted == ''


@pytest.mark.asyncio
async def test_settings_wake_cancels_inflight_native_poll() -> None:
    started = asyncio.Event()
    canceled = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params['timeout'] == '5'
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()
        return httpx.Response(200, json={'result': []})

    actor = runtime.TelegramIntegrationRuntime(7)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        task = asyncio.create_task(actor._get_updates_or_wake(client, asyncio.Event(), 0, token='secret', offset=12, poll_timeout=5))
        await asyncio.wait_for(started.wait(), timeout=1)
        actor.wake()
        response, _version = await asyncio.wait_for(task, timeout=1)
    assert response is None
    assert canceled.is_set()


@pytest.mark.asyncio
async def test_failed_update_does_not_advance_offset(monkeypatch) -> None:
    actor = runtime.TelegramIntegrationRuntime(7)
    advances: list[int] = []

    async def database(function, *args, **kwargs):
        if function is store.get_next_update_id:
            return 0
        if function is store.advance_update_id:
            advances.append(kwargs['next_update_id'])

    monkeypatch.setattr(actor, '_database', database)
    monkeypatch.setattr(runtime.bot, 'handle_update', AsyncMock(side_effect=httpx.ConnectError('provider unavailable')))
    response = httpx.Response(200, json={'result': [{'update_id': 2, 'message': {'text': '/start', 'chat': {'id': 42}}}]})
    async with httpx.AsyncClient() as client:
        await actor._process_poll_response(client, TelegramSettings(enabled=True, token='secret'), 'fingerprint', response)
    assert advances == []


@pytest.mark.asyncio
async def test_detection_and_main_poll_never_overlap(monkeypatch) -> None:
    stop = asyncio.Event()
    poll_started = asyncio.Event()
    actor = runtime.TelegramIntegrationRuntime(7)
    active = 0
    maximum = 0
    requested = False
    completed: list[dict[str, object]] = []
    claim = TelegramDetectionClaim('request-1', 'secret', store.token_fingerprint('secret'), 'user-1', 'tenant-a', 7, datetime.now(UTC) + timedelta(seconds=20))

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            if request.url.params['timeout'] == '5':
                poll_started.set()
                await asyncio.Event().wait()
            return httpx.Response(200, json={'result': [{'message': {'chat': {'id': 42, 'first_name': 'Test'}}}]})
        finally:
            active -= 1

    async def database(function, *args, **kwargs):
        nonlocal requested
        if function is store.claim_detection:
            if poll_started.is_set() and not requested:
                requested = True
                return claim
            return None
        if function is store.read_settings:
            return TelegramSettings(enabled=True, token='secret')
        if function is store.get_next_update_id:
            return 0
        if function is store.observed_chats:
            return []
        if function is store.complete_detection:
            completed.append(kwargs['result'])
            stop.set()
            return True
        return None

    original_client = httpx.AsyncClient
    monkeypatch.setattr(runtime.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(actor, '_database', database)
    task = asyncio.create_task(actor.run(stop))
    await asyncio.wait_for(poll_started.wait(), timeout=1)
    actor.wake()
    await asyncio.wait_for(task, timeout=1)
    assert maximum == 1
    assert completed[0]['chats'] == [{'chat_id': '42', 'title': 'Test'}]
