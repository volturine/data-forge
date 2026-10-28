from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from backend_core import notification_delivery, runtime_outbox_service
from backend_core.live_hubs import VersionHub
from backend_core.notification_delivery import DeliveryKind, DeliveryProgress
from backend_core.runtime_outbox_dispatcher import OUTBOX_WAKE_HUB, NamespaceWakeDispatcher, run_namespace_db
from backend_core.runtime_outbox_service import OutboxClaim

_DEFAULT_RECOVERY_SECONDS = 5.0
_DELIVERY_EXECUTORS = {
    DeliveryKind.EMAIL: ThreadPoolExecutor(max_workers=1, thread_name_prefix='email-delivery'),
    DeliveryKind.TELEGRAM: ThreadPoolExecutor(max_workers=1, thread_name_prefix='telegram-delivery'),
}

ClaimDelivery = Callable[[str, int], list[OutboxClaim]]
FinalizeDelivery = Callable[[str, OutboxClaim, str | None], bool]
Deliver = Callable[[dict[str, object], str, DeliveryProgress], None]


async def run_notification_delivery(stop_event: asyncio.Event) -> None:
    """Supervise independent email and Telegram durable delivery lanes under one cancellable lifecycle."""
    async with asyncio.TaskGroup() as group:
        for kind in DeliveryKind:
            group.create_task(IntegrationDeliveryDispatcher(kind=kind).run(stop_event), name=f'{kind}-dispatcher')


class IntegrationDeliveryDispatcher(NamespaceWakeDispatcher):
    """Consume one provider kind on its own bounded executor and durable claims."""

    def __init__(
        self,
        *,
        kind: DeliveryKind,
        poll_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        namespace_refresh_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        batch_size: int = 1,
        list_namespaces: Callable[[], list[str]] | None = None,
        claim_delivery: ClaimDelivery | None = None,
        finalize_delivery: FinalizeDelivery | None = None,
        deliver: Deliver | None = None,
        wake_hub: VersionHub = OUTBOX_WAKE_HUB,
    ) -> None:
        super().__init__(
            executor=_DELIVERY_EXECUTORS[kind],
            log_name='Integration delivery',
            log_detail=f' kind={kind}',
            poll_seconds=poll_seconds,
            namespace_refresh_seconds=namespace_refresh_seconds,
            batch_size=batch_size,
            list_namespaces=list_namespaces,
            wake_hub=wake_hub,
        )
        self._kind = kind
        self._claim_delivery = claim_delivery or self._claim_delivery_in_database
        self._finalize_delivery = finalize_delivery or self._finalize_delivery_in_database
        self._deliver = deliver or self._deliver_notification

    async def dispatch_namespace(self, namespace: str) -> int:
        claims = await self._run_blocking(self._claim_delivery, namespace, self._batch_size)
        delivered = 0
        for claim in claims:
            operation = asyncio.create_task(self._deliver_and_finalize(namespace, claim))
            try:
                delivered += await asyncio.shield(operation)
            except asyncio.CancelledError:
                # The provider call runs in a thread and cannot be interrupted.
                # Finish its fenced result commit before propagating shutdown.
                await asyncio.shield(operation)
                raise
        return delivered

    async def _deliver_and_finalize(self, namespace: str, claim: OutboxClaim) -> int:
        error: str | None = None
        if not claim.already_delivered:
            progress = DeliveryProgress(
                completed_parts=claim.completed_parts,
                record_completed_part=partial(self._record_delivery_part, namespace, claim),
            )
            try:
                await self._run_blocking(self._deliver, {**claim.payload, 'event_id': claim.event_id}, claim.event_id, progress)
            except Exception as exc:  # noqa: BLE001 - persist provider failures for retry/backoff.
                error = str(exc)
        finalized = await self._run_blocking(self._finalize_delivery, namespace, claim, error)
        return int(finalized and error is None)

    def _claim_delivery_in_database(self, namespace: str, limit: int) -> list[OutboxClaim]:
        return run_namespace_db(namespace, lambda session: runtime_outbox_service.claim_external_deliveries(session, kind=self._kind, limit=limit))

    @staticmethod
    def _finalize_delivery_in_database(namespace: str, claim: OutboxClaim, error: str | None) -> bool:
        return run_namespace_db(namespace, lambda session: runtime_outbox_service.finalize_external_delivery(session, claim, error=error))

    @staticmethod
    def _record_delivery_part(namespace: str, claim: OutboxClaim, part_key: str) -> bool:
        return run_namespace_db(namespace, lambda session: runtime_outbox_service.record_external_delivery_part(session, claim, part_key=part_key))

    @staticmethod
    def _deliver_notification(payload: dict[str, object], event_id: str, progress: DeliveryProgress) -> None:
        notification_delivery.deliver(payload, event_id=event_id, progress=progress)
