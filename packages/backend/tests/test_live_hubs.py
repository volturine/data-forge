import asyncio

import pytest

from backend_core.live_hubs import DEFAULT_MAX_WAITERS, KeyedVersionHub, VersionHub


async def _drain() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def test_publish_resolves_all_waiters_fan_out() -> None:
    hub = VersionHub()
    tasks = [asyncio.create_task(hub.wait()) for _ in range(5)]
    await _drain()
    assert len(hub._waiters) == 5

    hub.publish()

    assert await asyncio.gather(*tasks) == [1] * 5
    assert hub._waiters == []


async def test_wait_returns_immediately_when_version_advanced() -> None:
    hub = VersionHub()
    hub.publish()
    assert await hub.wait(0) == 1
    assert hub.version() == 1
    assert hub._waiters == []


async def test_cancelled_waiter_is_discarded() -> None:
    hub = VersionHub()
    task = asyncio.create_task(hub.wait())
    await _drain()
    assert len(hub._waiters) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _drain()

    assert hub._waiters == []


async def test_done_waiters_are_pruned_on_next_wait() -> None:
    hub = VersionHub()
    stale = asyncio.create_task(hub.wait())
    await _drain()
    stale.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stale

    # The discard of the cancelled waiter only happens when its coroutine finalizes;
    # force it to be finalized before adding the next waiter.
    await asyncio.sleep(0)

    keeper = asyncio.create_task(hub.wait())
    await _drain()

    live_entries = [entry for entry in hub._waiters if not entry[1].done()]
    assert len(live_entries) == 1
    assert len(hub._waiters) == 1

    hub.publish()
    assert await keeper == 1
    assert hub._waiters == []


async def test_version_hub_evicts_oldest_waiter_when_cap_exceeded() -> None:
    hub = VersionHub(max_waiters=3)
    oldest_tasks = [asyncio.create_task(hub.wait()) for _ in range(3)]
    await _drain()
    newest = asyncio.create_task(hub.wait())
    await _drain()

    assert len(hub._waiters) == 3

    hub.publish()
    results = await asyncio.gather(*oldest_tasks, return_exceptions=True)
    cancelled = [result for result in results if isinstance(result, asyncio.CancelledError)]
    resolved = [result for result in results if not isinstance(result, BaseException)]
    assert len(cancelled) == 1
    assert resolved == [1, 1]
    assert await newest == 1
    assert hub._waiters == []


async def test_version_hub_default_cap_is_bounded() -> None:
    hub = VersionHub()
    assert hub._max_waiters == DEFAULT_MAX_WAITERS


async def test_keyed_hub_publish_resolves_only_matching_key() -> None:
    hub = KeyedVersionHub()
    a = asyncio.create_task(hub.wait('a'))
    b = asyncio.create_task(hub.wait('b'))
    await _drain()

    hub.publish('a')

    assert await a == 1
    assert not b.done()
    hub.publish('b')
    assert await b == 1
    assert hub._waiters == {}


async def test_keyed_hub_prunes_done_waiters_per_key() -> None:
    hub = KeyedVersionHub()
    stale = asyncio.create_task(hub.wait('a'))
    await _drain()
    stale.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stale

    keeper = asyncio.create_task(hub.wait('a'))
    await _drain()

    live_entries = [entry for entry in hub._waiters.get('a', []) if not entry[1].done()]
    assert len(live_entries) == 1

    hub.publish('a')
    assert await keeper == 1
    assert 'a' not in hub._waiters


async def test_keyed_hub_total_cap_spans_keys_oldest_first() -> None:
    hub = KeyedVersionHub(max_waiters=4)
    first = asyncio.create_task(hub.wait('k0'))
    await _drain()
    later_tasks = []
    for index in range(4):
        later_tasks.append(asyncio.create_task(hub.wait(f'k{index % 2}')))
        await _drain()

    assert hub.waiter_count() <= 4
    with pytest.raises(asyncio.CancelledError):
        await first

    for task in later_tasks:
        task.cancel()
    await asyncio.gather(*later_tasks, return_exceptions=True)


async def test_keyed_hub_clear_cancels_waiters() -> None:
    hub = KeyedVersionHub()
    task = asyncio.create_task(hub.wait('a'))
    await _drain()
    await hub.clear()
    with pytest.raises(asyncio.CancelledError):
        await task
