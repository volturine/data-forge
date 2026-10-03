import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest

from modules.compute import routes


@pytest.mark.asyncio
async def test_build_event_protobuf_conversion_runs_off_api_event_loop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    row = SimpleNamespace(sequence=1)
    sent_payloads: list[dict[str, object]] = []
    database_threads: list[int] = []

    def fake_run_db(function, *args, **kwargs):
        database_threads.append(threading.get_ident())
        return function(SimpleNamespace(), *args, **kwargs)

    def serialize_event(_row) -> dict[str, object]:
        return {'serializer_thread': threading.get_ident()}

    async def send_json(_websocket, payload: dict[str, object]) -> bool:
        sent_payloads.append(payload)
        return True

    monkeypatch.setattr(routes, 'run_db', fake_run_db)

    def list_events(_session, *_args):
        assert threading.get_ident() != loop_thread
        return [row]

    monkeypatch.setattr(routes.build_run_service, 'list_build_events_after', list_events)
    monkeypatch.setattr(routes.build_run_service, 'serialize_event_row', serialize_event)
    monkeypatch.setattr(routes, 'safe_send_json', send_json)

    assert await routes._replay_build_events(cast(Any, object()), 'build-1', 0) == 1
    assert len(sent_payloads) == 1
    assert database_threads and database_threads[0] != loop_thread
    assert sent_payloads[0]['serializer_thread'] != loop_thread
