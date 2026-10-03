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

    def deliver(_payload: dict[str, object], _event_id: str, _progress: object) -> None:
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

    def deliver(_payload: dict[str, object], _event_id: str, _progress: object) -> None:
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
async def test_canceled_claim_joins_and_logs_its_started_database_operation(caplog: pytest.LogCaptureFixture) -> None:
    claim_started = threading.Event()
    release_claim = threading.Event()
    claim_finished = threading.Event()

    def claim(_namespace: str, _limit: int) -> list[OutboxClaim]:
        claim_started.set()
        if not release_claim.wait(timeout=3):
            raise TimeoutError('test DB claim was not released')
        claim_finished.set()
        raise RuntimeError('late claim failure')

    dispatcher = IntegrationDeliveryDispatcher(
        kind=EMAIL_DELIVERY_KIND,
        claim_delivery=claim,
    )
    task = asyncio.create_task(dispatcher.dispatch_namespace('default'))
    try:
        assert await asyncio.to_thread(claim_started.wait, 1)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
        assert not claim_finished.is_set()

        release_claim.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert claim_finished.is_set()
        assert 'Integration delivery operation failed after its caller was cancelled' in caplog.text
        assert 'RuntimeError' in caplog.text
        assert 'late claim failure' in caplog.text
    finally:
        release_claim.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_delivery_is_finalized_for_durable_retry() -> None:
    finalized: list[str | None] = []

    def deliver(_payload: dict[str, object], _event_id: str, _progress: object) -> None:
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
