from __future__ import annotations

import asyncio
import threading

import pytest

from backend_core.live_hubs import VersionHub
from backend_core.runtime_outbox_dispatcher import RuntimeOutboxDispatcher


@pytest.mark.asyncio
async def test_dispatcher_consumes_one_pending_snapshot_without_rescanning() -> None:
    wake_hub = VersionHub()
    calls: list[tuple[str, int]] = []
    list_calls: list[int] = []
    dispatch_threads: list[str] = []
    list_threads: list[str] = []
    calls_changed = threading.Event()

    def dispatch(namespace: str, limit: int) -> int:
        calls.append((namespace, limit))
        dispatch_threads.append(threading.current_thread().name)
        calls_changed.set()
        return 0

    def list_namespaces() -> list[str]:
        list_calls.append(1)
        list_threads.append(threading.current_thread().name)
        return ['alpha', 'beta']

    dispatcher = RuntimeOutboxDispatcher(
        poll_seconds=30,
        namespace_refresh_seconds=30,
        batch_size=8,
        list_namespaces=list_namespaces,
        dispatch_namespace=dispatch,
        wake_hub=wake_hub,
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(dispatcher.run(stop_event))
    try:
        assert await asyncio.to_thread(calls_changed.wait, 1)
        await asyncio.sleep(0.05)
        assert calls == [('alpha', 8), ('beta', 8)]
        assert dispatch_threads == ['runtime-outbox_0', 'runtime-outbox_0']
        assert list_threads == ['runtime-outbox_0']
        assert list_calls == [1]

        calls_changed.clear()
        wake_hub.publish('alpha')
        assert await asyncio.to_thread(calls_changed.wait, 1)
        assert calls == [('alpha', 8), ('beta', 8), ('alpha', 8)]
        assert list_calls == [1]
    finally:
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_dispatcher_prioritizes_a_woken_namespace() -> None:
    wake_hub = VersionHub()
    calls: list[str] = []
    calls_changed = threading.Event()

    def dispatch(namespace: str, _limit: int) -> int:
        calls.append(namespace)
        calls_changed.set()
        return 0

    dispatcher = RuntimeOutboxDispatcher(
        poll_seconds=30,
        namespace_refresh_seconds=30,
        list_namespaces=lambda: ['alpha'],
        dispatch_namespace=dispatch,
        wake_hub=wake_hub,
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(dispatcher.run(stop_event))
    try:
        assert await asyncio.to_thread(calls_changed.wait, 1)
        assert calls == ['alpha']

        calls_changed.clear()
        wake_hub.publish('beta')
        assert await asyncio.to_thread(calls_changed.wait, 1)
        assert calls == ['alpha', 'beta']
        assert dispatcher._namespaces == ['alpha']
    finally:
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_dispatcher_requeues_nonempty_batches_fairly() -> None:
    wake_hub = VersionHub()
    calls: list[str] = []
    second_alpha_batch = threading.Event()

    def dispatch(namespace: str, _limit: int) -> int:
        calls.append(namespace)
        if namespace == 'alpha' and calls.count('alpha') == 2:
            second_alpha_batch.set()
            return 0
        return 1 if namespace == 'alpha' else 0

    dispatcher = RuntimeOutboxDispatcher(
        poll_seconds=30,
        namespace_refresh_seconds=30,
        batch_size=8,
        list_namespaces=lambda: ['alpha', 'beta'],
        dispatch_namespace=dispatch,
        wake_hub=wake_hub,
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(dispatcher.run(stop_event))
    try:
        assert await asyncio.to_thread(second_alpha_batch.wait, 1)
        assert calls[:3] == ['alpha', 'beta', 'alpha']
    finally:
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_dispatcher_uses_cached_namespaces_when_refresh_fails() -> None:
    refresh_calls = 0

    def list_namespaces() -> list[str]:
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls == 1:
            return ['alpha']
        raise RuntimeError('settings database unavailable')

    dispatcher = RuntimeOutboxDispatcher(
        list_namespaces=list_namespaces,
        dispatch_namespace=lambda _namespace, _limit: 0,
    )
    assert await dispatcher._next_namespace() == 'alpha'
    dispatcher._next_refresh = 0

    assert await dispatcher._next_namespace() == 'alpha'
