import threading

import pytest

from backend_core import websocket
from modules.locks import schemas, watchers


@pytest.mark.asyncio
async def test_notify_watchers_serializes_once_for_fifty_sockets(monkeypatch) -> None:
    sockets = [object() for _ in range(50)]
    payload = schemas.LockWebsocketStatusMessage(
        resource_type='analysis',
        resource_id='analysis-1',
        lock=None,
    )
    serialize_calls = []
    send_calls = []

    async def get_sockets(namespace, resource_type, resource_id):
        assert (namespace, resource_type, resource_id) == ('default', 'analysis', 'analysis-1')
        return sockets

    async def serialize(value):
        serialize_calls.append(value)
        return '{"type":"status","resource_type":"analysis","resource_id":"analysis-1","lock":null}'

    async def send_serialized_json(websocket, serialized):
        send_calls.append((websocket, serialized))
        return True

    monkeypatch.setattr(watchers.registry, 'sockets', get_sockets)
    monkeypatch.setattr(watchers, 'serialize_json', serialize)
    monkeypatch.setattr(watchers, 'safe_send_serialized_json', send_serialized_json)

    await watchers.notify_watchers('default', 'analysis', 'analysis-1', payload)

    assert serialize_calls == [payload]
    assert len(send_calls) == len(sockets)
    assert [websocket for websocket, _ in send_calls] == sockets
    assert {serialized for _, serialized in send_calls} == {'{"type":"status","resource_type":"analysis","resource_id":"analysis-1","lock":null}'}


@pytest.mark.asyncio
async def test_serialize_json_does_not_run_on_event_loop(monkeypatch) -> None:
    loop_thread_id = threading.get_ident()
    serializer_thread_ids = []

    def serialize(payload):
        serializer_thread_ids.append(threading.get_ident())
        return '{"ok":true}'

    monkeypatch.setattr(websocket, '_serialize_json', serialize)

    result = await websocket.serialize_json({'ok': True})

    assert result == '{"ok":true}'
    assert len(serializer_thread_ids) == 1
    assert serializer_thread_ids[0] != loop_thread_id
