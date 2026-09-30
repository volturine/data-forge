from __future__ import annotations

import asyncio
import contextvars
import logging
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TypeVar

from backend_core import notification_delivery, runtime_outbox_service
from backend_core.database import run_db, run_settings_db
from backend_core.live_hubs import VersionHub
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.notification_delivery import EMAIL_DELIVERY_KIND, TELEGRAM_DELIVERY_KIND
from backend_core.runtime_outbox_dispatcher import OUTBOX_WAKE_HUB
from backend_core.runtime_outbox_service import OutboxClaim

logger = logging.getLogger(__name__)

_DEFAULT_RECOVERY_SECONDS = 5.0
_DELIVERY_EXECUTORS = {
    EMAIL_DELIVERY_KIND: ThreadPoolExecutor(max_workers=1, thread_name_prefix='email-delivery'),
    TELEGRAM_DELIVERY_KIND: ThreadPoolExecutor(max_workers=1, thread_name_prefix='telegram-delivery'),
}
T = TypeVar('T')

ClaimDelivery = Callable[[str, int], list[OutboxClaim]]
FinalizeDelivery = Callable[[str, OutboxClaim, str | None], bool]
Deliver = Callable[[dict[str, object], str], None]


def wake(namespace: str) -> None:
    """Wake the external delivery lanes for one namespace."""
    OUTBOX_WAKE_HUB.publish(namespace)


async def run(stop_event: asyncio.Event) -> None:
    """Exported lifecycle hook for all isolated external provider lanes."""
    await NotificationDeliveryDispatcher().run(stop_event)


class NotificationDeliveryDispatcher:
    """Supervise independent email and Telegram durable delivery lanes."""

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run both provider lanes under one cancellable lifecycle."""
        async with asyncio.TaskGroup() as group:
            for kind in (EMAIL_DELIVERY_KIND, TELEGRAM_DELIVERY_KIND):
                group.create_task(IntegrationDeliveryDispatcher(kind=kind).run(stop_event), name=f'{kind}-dispatcher')


class IntegrationDeliveryDispatcher:
    """Consume one provider kind on its own bounded executor and durable claims."""

    def __init__(
        self,
        *,
        kind: str,
        poll_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        namespace_refresh_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        batch_size: int = 1,
        list_namespaces: Callable[[], list[str]] | None = None,
        claim_delivery: ClaimDelivery | None = None,
        finalize_delivery: FinalizeDelivery | None = None,
        deliver: Deliver | None = None,
        wake_hub: VersionHub = OUTBOX_WAKE_HUB,
    ) -> None:
        if kind not in _DELIVERY_EXECUTORS:
            raise ValueError(f'Unsupported external delivery kind: {kind!r}')
        self._kind = kind
        self._executor = _DELIVERY_EXECUTORS[kind]
        self._poll_seconds = max(float(poll_seconds), 0.1)
        self._namespace_refresh_seconds = max(float(namespace_refresh_seconds), 1.0)
        self._batch_size = max(int(batch_size), 1)
        self._list_namespaces = list_namespaces or (lambda: run_settings_db(runtime_outbox_service.list_pending_outbox_namespaces))
        self._claim_delivery = claim_delivery or self._claim_delivery_in_database
        self._finalize_delivery = finalize_delivery or self._finalize_delivery_in_database
        self._deliver = deliver or self._deliver_notification
        self._wake_hub = wake_hub
        self._namespaces: list[str] = []
        self._next_refresh = 0.0
        self._pending_namespaces: deque[str] = deque()
        self._pending_namespace_set: set[str] = set()

    async def run(self, stop_event: asyncio.Event) -> None:
        wake_version = self._wake_hub.version()
        while not stop_event.is_set():
            try:
                current_version = self._wake_hub.version()
                self._enqueue_wake_namespaces(wake_version)
                wake_version = current_version
                namespace = await self._next_namespace()
                if namespace is None:
                    wake_version = await self._wait_for_wakeup_or_stop(stop_event, wake_version)
                    continue
                delivered = await self.dispatch_namespace(namespace)
                if delivered:
                    self._enqueue_namespace(namespace)
                if self._pending_namespaces:
                    continue
                last_seen = wake_version
                wake_version = await self._wait_for_wakeup_or_stop(stop_event, last_seen)
                self._enqueue_wake_namespaces(last_seen)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning('Integration delivery pass failed kind=%s', self._kind, exc_info=True)
                last_seen = wake_version
                wake_version = await self._wait_for_wakeup_or_stop(stop_event, last_seen, retry_seconds=1.0)
                self._enqueue_wake_namespaces(last_seen)

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
            try:
                await self._run_blocking(self._deliver, {**claim.payload, 'event_id': claim.event_id}, claim.event_id)
            except Exception as exc:  # noqa: BLE001 - persist provider failures for retry/backoff.
                error = str(exc)
        finalized = await self._run_blocking(self._finalize_delivery, namespace, claim, error)
        return int(finalized and error is None)

    def _enqueue_wake_namespaces(self, last_seen: int) -> None:
        for namespace in self._wake_hub.payloads_since(last_seen):
            if isinstance(namespace, str):
                self._enqueue_namespace(namespace)

    def _enqueue_namespace(self, namespace: str) -> None:
        if not namespace or namespace in self._pending_namespace_set:
            return
        self._pending_namespaces.append(namespace)
        self._pending_namespace_set.add(namespace)

    async def _next_namespace(self) -> str | None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now >= self._next_refresh:
            try:
                names = await self._run_blocking(self._list_namespaces)
            except Exception:
                if not self._namespaces:
                    raise
                logger.warning('Integration namespace refresh failed; retrying last snapshot kind=%s', self._kind, exc_info=True)
                names = self._namespaces
                self._next_refresh = loop.time() + min(self._namespace_refresh_seconds, 1.0)
            else:
                self._namespaces = list(dict.fromkeys(name for name in names if name))
                self._next_refresh = loop.time() + self._namespace_refresh_seconds
            for namespace in names:
                self._enqueue_namespace(namespace)
        if not self._pending_namespaces:
            return None
        namespace = self._pending_namespaces.popleft()
        self._pending_namespace_set.discard(namespace)
        return namespace

    async def _run_blocking(self, function: Callable[..., T], *args: object) -> T:
        loop = asyncio.get_running_loop()
        context = contextvars.copy_context()
        return await loop.run_in_executor(self._executor, context.run, partial(function, *args))

    def _claim_delivery_in_database(self, namespace: str, limit: int) -> list[OutboxClaim]:
        token = set_namespace_context(namespace)
        try:
            return run_db(lambda session: runtime_outbox_service.claim_external_deliveries(session, kind=self._kind, limit=limit))
        finally:
            reset_namespace(token)

    def _finalize_delivery_in_database(self, namespace: str, claim: OutboxClaim, error: str | None) -> bool:
        token = set_namespace_context(namespace)
        try:
            return run_db(lambda session: runtime_outbox_service.finalize_external_delivery(session, claim, error=error))
        finally:
            reset_namespace(token)

    @staticmethod
    def _deliver_notification(payload: dict[str, object], event_id: str) -> None:
        notification_delivery.deliver(payload, event_id=event_id)

    async def _wait_for_wakeup_or_stop(
        self,
        stop_event: asyncio.Event,
        wake_version: int,
        *,
        retry_seconds: float | None = None,
    ) -> int:
        wake_task = asyncio.create_task(self._wake_hub.wait(last_seen=wake_version))
        stop_task = asyncio.create_task(stop_event.wait())
        timer_task = asyncio.create_task(asyncio.sleep(self._poll_seconds if retry_seconds is None else retry_seconds))
        done, pending = await asyncio.wait({wake_task, stop_task, timer_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if stop_task in done:
            return self._wake_hub.version()
        if wake_task in done:
            return wake_task.result()
        return self._wake_hub.version()
