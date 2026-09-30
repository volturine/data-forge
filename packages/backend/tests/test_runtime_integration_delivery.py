import asyncio
import threading

import pytest

from backend_core.notification_delivery import EMAIL_DELIVERY_KIND
from backend_core.runtime_integration_delivery import IntegrationDeliveryDispatcher, wake
from backend_core.runtime_outbox_dispatcher import RuntimeOutboxDispatcher
from backend_core.runtime_outbox_service import OutboxClaim


def _claim() -> OutboxClaim:
    return OutboxClaim(
        event_id='event-1',
        claim_token='claim-1',
        lease_generation=1,
        event_kind=EMAIL_DELIVERY_KIND,
        payload={'kind': EMAIL_DELIVERY_KIND, 'to': 'test@example.com'},
    )


@pytest.mark.asyncio
async def test_blocked_external_provider_does_not_block_runtime_wake_lane() -> None:
    delivery_started = threading.Event()
    release_delivery = threading.Event()
    runtime_wakes: list[str] = []

    def deliver(_payload: dict[str, object], _event_id: str) -> None:
        delivery_started.set()
        assert release_delivery.wait(timeout=2)

    def dispatch_wake(namespace: str, _limit: int) -> int:
        runtime_wakes.append(namespace)
        return 1

    delivery = IntegrationDeliveryDispatcher(
        kind=EMAIL_DELIVERY_KIND,
        claim_delivery=lambda _namespace, _limit: [_claim()],
        finalize_delivery=lambda _namespace, _claim, error: error is None,
        deliver=deliver,
    )
    runtime = RuntimeOutboxDispatcher(
        dispatch_namespace=dispatch_wake,
        list_namespaces=lambda: [],
    )

    delivery_task = asyncio.create_task(delivery.dispatch_namespace('default'))
    try:
        assert await asyncio.to_thread(delivery_started.wait, 1)
        await asyncio.wait_for(runtime._run_blocking(runtime._dispatch_namespace, 'default', 1), timeout=1)
        assert runtime_wakes == ['default']
    finally:
        release_delivery.set()
        assert await delivery_task == 1


@pytest.mark.asyncio
async def test_canceled_delivery_finishes_claim_finalization_before_stopping() -> None:
    delivery_started = threading.Event()
    release_delivery = threading.Event()
    finalized: list[str | None] = []

    def deliver(_payload: dict[str, object], _event_id: str) -> None:
        delivery_started.set()
        assert release_delivery.wait(timeout=2)

    def finalize(_namespace: str, _claim: OutboxClaim, error: str | None) -> bool:
        finalized.append(error)
        return True

    dispatcher = IntegrationDeliveryDispatcher(
        kind=EMAIL_DELIVERY_KIND,
        claim_delivery=lambda _namespace, _limit: [_claim()],
        finalize_delivery=finalize,
        deliver=deliver,
    )
    task = asyncio.create_task(dispatcher.dispatch_namespace('default'))
    assert await asyncio.to_thread(delivery_started.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release_delivery.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert finalized == [None]


@pytest.mark.asyncio
async def test_failed_delivery_is_finalized_for_durable_retry() -> None:
    finalized: list[str | None] = []

    def deliver(_payload: dict[str, object], _event_id: str) -> None:
        raise RuntimeError('provider unavailable')

    def finalize(_namespace: str, _claim: OutboxClaim, error: str | None) -> bool:
        finalized.append(error)
        return True

    dispatcher = IntegrationDeliveryDispatcher(
        kind=EMAIL_DELIVERY_KIND,
        claim_delivery=lambda _namespace, _limit: [_claim()],
        finalize_delivery=finalize,
        deliver=deliver,
    )

    assert await dispatcher.dispatch_namespace('default') == 0
    assert finalized == ['provider unavailable']


def test_wake_interface_publishes_namespace_to_delivery_lanes() -> None:
    from backend_core.runtime_outbox_dispatcher import OUTBOX_WAKE_HUB

    last_seen = OUTBOX_WAKE_HUB.version()
    wake('wake-test')

    assert OUTBOX_WAKE_HUB.payloads_since(last_seen) == ['wake-test']
