from __future__ import annotations

import asyncio
import contextvars
import logging
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TypeVar

from backend_core import runtime_outbox_service
from backend_core.database import run_db, run_settings_db
from backend_core.live_hubs import VersionHub
from backend_core.namespace import reset_namespace, set_namespace_context

logger = logging.getLogger(__name__)

OUTBOX_WAKE_HUB = VersionHub()
_DEFAULT_BATCH_SIZE = 8
_DEFAULT_RECOVERY_SECONDS = 5.0
_OUTBOX_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='runtime-outbox')
T = TypeVar('T')


class RuntimeOutboxDispatcher:
    """Deliver durable runtime events with one bounded recovery cursor.

    A request path may dispatch the event it just created, but terminal worker
    events are produced by another process. This task handles those events
    without one RPC per request: PostgreSQL NOTIFY wakes it immediately after
    commit, while a five-second indexed pending-work query is the
    lost-notification backstop. Claims remain row-locked and directed to one
    namespace at a time.
    """

    def __init__(
        self,
        *,
        poll_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        namespace_refresh_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        list_namespaces: Callable[[], list[str]] | None = None,
        dispatch_namespace: Callable[[str, int], int] | None = None,
        wake_hub: VersionHub = OUTBOX_WAKE_HUB,
    ) -> None:
        self._poll_seconds = max(float(poll_seconds), 0.1)
        self._namespace_refresh_seconds = max(float(namespace_refresh_seconds), 1.0)
        self._batch_size = max(int(batch_size), 1)
        self._list_namespaces = list_namespaces or (lambda: run_settings_db(runtime_outbox_service.list_pending_outbox_namespaces))
        self._dispatch_namespace = dispatch_namespace or self._dispatch_namespace_in_database
        self._wake_hub = wake_hub
        self._namespaces: list[str] = []
        self._next_refresh = 0.0
        self._pending_namespaces: deque[str] = deque()
        self._pending_namespace_set: set[str] = set()

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run until API shutdown, never blocking the event loop on delivery."""
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
                dispatched = await self._run_blocking(self._dispatch_namespace, namespace, self._batch_size)
                if dispatched:
                    # A successful delivery may leave more ready events even
                    # when some claims in the batch failed and backed off.
                    # Requeue at the tail so every tenant gets a turn before
                    # this namespace drains its backlog.
                    self._enqueue_namespace(namespace)
                if self._pending_namespaces:
                    continue
                last_seen = wake_version
                wake_version = await self._wait_for_wakeup_or_stop(stop_event, last_seen)
                self._enqueue_wake_namespaces(last_seen)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning('Runtime outbox dispatcher pass failed', exc_info=True)
                last_seen = wake_version
                wake_version = await self._wait_for_wakeup_or_stop(stop_event, last_seen, retry_seconds=1.0)
                self._enqueue_wake_namespaces(last_seen)

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
                logger.warning('Outbox namespace refresh failed; retrying from the last durable snapshot', exc_info=True)
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
        return await loop.run_in_executor(_OUTBOX_EXECUTOR, context.run, partial(function, *args))

    def _dispatch_namespace_in_database(self, namespace: str, limit: int) -> int:
        token = set_namespace_context(namespace)
        try:
            return run_db(lambda session: runtime_outbox_service.dispatch_pending_events(session, limit=limit))
        finally:
            reset_namespace(token)

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
