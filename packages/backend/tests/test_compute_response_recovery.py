from __future__ import annotations

import asyncio
import threading

import pytest

from backend_core import compute_requests_service
from backend_core.compute_response_recovery import ComputeResponseRecovery
from dataforge_protocol import enums_pb2


def _terminal_request(request_id: str) -> compute_requests_service.TerminalComputeRequest:
    return compute_requests_service.TerminalComputeRequest(
        id=request_id,
        kind=int(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW),
        status=int(enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED),
        response_envelope=b'completed-response',
        error_message=None,
        artifact_path=None,
        artifact_name=None,
        artifact_content_type=None,
    )


def test_recovery_can_run_on_successive_lifespan_loops() -> None:
    recovery = ComputeResponseRecovery(poll_seconds=3_600)

    async def lifespan() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(recovery.run(stop))
        for _ in range(3):
            await asyncio.sleep(0)
        recovery.request_poll()
        for _ in range(3):
            await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(lifespan())
    asyncio.run(lifespan())


@pytest.mark.asyncio
async def test_pre_start_recovery_requests_are_covered_by_one_immediate_initial_poll() -> None:
    terminal = _terminal_request('before-start')
    calls = 0

    def poll(_namespace, _request_ids) -> list[compute_requests_service.TerminalComputeRequest]:
        nonlocal calls
        calls += 1
        return [terminal]

    recovery = ComputeResponseRecovery(poll_seconds=3_600, poll_namespace=poll)
    await recovery.register(terminal.id, 'default')
    for _ in range(50_000):
        recovery.request_poll()
    stop = asyncio.Event()
    task = asyncio.create_task(recovery.run(stop))
    try:
        assert await asyncio.wait_for(recovery.wait_for_wake(terminal.id, 0), timeout=1) == 1
        assert calls == 1
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        await recovery.unregister(terminal.id)


@pytest.mark.asyncio
async def test_concurrent_run_is_rejected_without_replacing_the_active_waiter_event() -> None:
    terminal = _terminal_request('active-owner')
    first_polled = threading.Event()
    calls = 0

    def poll(_namespace, _request_ids) -> list[compute_requests_service.TerminalComputeRequest]:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_polled.set()
            return []
        return [terminal]

    recovery = ComputeResponseRecovery(poll_seconds=3_600, poll_namespace=poll)
    await recovery.register(terminal.id, 'default')
    stop = asyncio.Event()
    task = asyncio.create_task(recovery.run(stop))
    try:
        assert await asyncio.to_thread(first_polled.wait, 1)
        with pytest.raises(RuntimeError, match='already running'):
            await recovery.run(asyncio.Event())
        recovery.request_poll()
        assert await asyncio.wait_for(recovery.wait_for_wake(terminal.id, 0), timeout=1) == 1
        assert calls == 2
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        await recovery.unregister(terminal.id)


@pytest.mark.asyncio
async def test_recovery_batches_pending_requests_by_namespace() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def poll(
        namespace: str,
        request_ids,
    ) -> list[compute_requests_service.TerminalComputeRequest]:
        ids = tuple(request_ids)
        calls.append((namespace, ids))
        return [_terminal_request(request_id) for request_id in ids]

    recovery = ComputeResponseRecovery(poll_namespace=poll)
    await recovery.register('alpha-1', 'alpha')
    await recovery.register('alpha-2', 'alpha')
    await recovery.register('beta-1', 'beta')

    await recovery._poll_once()

    assert calls == [
        ('alpha', ('alpha-1', 'alpha-2')),
        ('beta', ('beta-1',)),
    ]
    assert await recovery.pending_count() == 3
    assert await recovery.wait_for_wake('alpha-1', last_seen=0) == 1
    assert await recovery.wait_for_wake('alpha-2', last_seen=0) == 1
    assert await recovery.wait_for_wake('beta-1', last_seen=0) == 1
    assert await recovery.terminal_request('alpha-1') == _terminal_request('alpha-1')

    for request_id in ('alpha-1', 'alpha-2', 'beta-1'):
        await recovery.unregister(request_id)
    assert await recovery.pending_count() == 0


@pytest.mark.asyncio
async def test_recovery_keeps_requests_pending_when_database_poll_fails() -> None:
    def poll(_namespace: str, _request_ids) -> list[compute_requests_service.TerminalComputeRequest]:
        raise RuntimeError('database unavailable')

    recovery = ComputeResponseRecovery(poll_namespace=poll)
    await recovery.register('request-1', 'default')

    await recovery._poll_once()

    assert await recovery.pending_count() == 1


@pytest.mark.asyncio
async def test_recovery_keeps_shared_request_until_all_waiters_unregister() -> None:
    terminal = _terminal_request('shared-request')
    recovery = ComputeResponseRecovery(poll_namespace=lambda _namespace, _request_ids: [terminal])
    await recovery.register('shared-request', 'default')
    await recovery.register('shared-request', 'default')
    await recovery._poll_once()

    await recovery.unregister('shared-request')

    assert await recovery.pending_count() == 1
    assert await recovery.terminal_request('shared-request') is terminal

    await recovery.unregister('shared-request')

    assert await recovery.pending_count() == 0
    assert await recovery.terminal_request('shared-request') is None


@pytest.mark.asyncio
async def test_recovery_does_not_poll_cached_terminal_request_again() -> None:
    calls: list[tuple[str, ...]] = []
    terminal = _terminal_request('terminal-once')

    def poll(_namespace: str, request_ids) -> list[compute_requests_service.TerminalComputeRequest]:
        calls.append(tuple(request_ids))
        return [terminal]

    recovery = ComputeResponseRecovery(poll_namespace=poll)
    await recovery.register(terminal.id, 'default')

    await recovery._poll_once()
    await recovery._poll_once()

    assert calls == [(terminal.id,)]
    assert await recovery.terminal_request(terminal.id) is terminal
    await recovery.unregister(terminal.id)


@pytest.mark.asyncio
async def test_recovery_wake_is_retained_when_waiter_starts_after_terminal_publication() -> None:
    terminal = _terminal_request('late-waiter')
    recovery = ComputeResponseRecovery(poll_namespace=lambda _namespace, _request_ids: [terminal])
    await recovery.register(terminal.id, 'default')
    version_before_poll = await recovery.wake_version(terminal.id)

    await recovery._poll_once()
    for _ in range(4_100):
        await recovery.notify(terminal.id)

    assert await recovery.wait_for_wake(terminal.id, version_before_poll) == 4_101
    assert await recovery.terminal_request(terminal.id) is terminal
    await recovery.unregister(terminal.id)


@pytest.mark.asyncio
async def test_recovery_poll_wakes_an_already_waiting_http_follower() -> None:
    terminal = _terminal_request('active-waiter')
    recovery = ComputeResponseRecovery(poll_namespace=lambda _namespace, _request_ids: [terminal])
    await recovery.register(terminal.id, 'default')
    wake_version = await recovery.wake_version(terminal.id)
    waiter = asyncio.create_task(recovery.wait_for_wake(terminal.id, wake_version))
    await asyncio.sleep(0)

    await recovery._poll_once()

    assert await asyncio.wait_for(waiter, timeout=0.1) == wake_version + 1
    assert await recovery.terminal_request(terminal.id) is terminal
    await recovery.unregister(terminal.id)


@pytest.mark.asyncio
async def test_listener_recovery_wakes_terminal_poll_without_waiting_for_periodic_timer() -> None:
    terminal = _terminal_request('lost-notify')
    first_polled = threading.Event()
    completed = False
    calls = 0

    def poll(_namespace, _request_ids) -> list[compute_requests_service.TerminalComputeRequest]:
        nonlocal calls
        calls += 1
        first_polled.set()
        if calls == 1:
            return []
        return [terminal] if completed else []

    recovery = ComputeResponseRecovery(poll_seconds=3_600, poll_namespace=poll)
    await recovery.register(terminal.id, 'default')
    stop = asyncio.Event()
    task = asyncio.create_task(recovery.run(stop))
    try:
        assert await asyncio.to_thread(first_polled.wait, 1)
        completed = True
        for _ in range(50_000):
            recovery.request_poll()
        assert await asyncio.wait_for(recovery.wait_for_wake(terminal.id, 0), timeout=1) == 1
        assert await recovery.terminal_request(terminal.id) is terminal
        assert calls == 2
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        await recovery.unregister(terminal.id)


@pytest.mark.asyncio
async def test_listener_recovery_requested_during_database_poll_is_not_lost() -> None:
    terminal = _terminal_request('poll-race')
    first_polled = threading.Event()
    release = threading.Event()
    calls = 0

    def poll(_namespace, _request_ids) -> list[compute_requests_service.TerminalComputeRequest]:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_polled.set()
            if not release.wait(2):
                raise TimeoutError('Test did not release the initial database poll')
            return []
        return [terminal]

    recovery = ComputeResponseRecovery(poll_seconds=3_600, poll_namespace=poll)
    await recovery.register(terminal.id, 'default')
    stop = asyncio.Event()
    task = asyncio.create_task(recovery.run(stop))
    try:
        assert await asyncio.to_thread(first_polled.wait, 1)
        recovery.request_poll()
        release.set()
        assert await asyncio.wait_for(recovery.wait_for_wake(terminal.id, 0), timeout=1) == 1
        assert calls == 2
    finally:
        release.set()
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        await recovery.unregister(terminal.id)
