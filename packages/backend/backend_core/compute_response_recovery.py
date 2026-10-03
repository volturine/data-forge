from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from backend_core import compute_requests_service
from backend_core.database import run_db
from backend_core.namespace import reset_namespace, set_namespace_context

logger = logging.getLogger(__name__)

_DEFAULT_POLL_SECONDS = 5.0
_MAX_REQUESTS_PER_NAMESPACE_POLL = 256
_POLL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='compute-response-recovery')


@dataclass(slots=True)
class _PendingComputeResponse:
    namespace: str
    registered_at: float
    waiter_count: int = 1
    wake_version: int = 0
    terminal: compute_requests_service.TerminalComputeRequest | None = None
    wake_event: asyncio.Event = field(default_factory=asyncio.Event)


def _poll_namespace(namespace: str, request_ids: Collection[str]) -> list[compute_requests_service.TerminalComputeRequest]:
    token = set_namespace_context(namespace)
    try:
        return run_db(compute_requests_service.list_terminal_requests, request_ids)
    finally:
        reset_namespace(token)


def _poll_with_timing(
    poll_namespace: Callable[[str, Collection[str]], list[compute_requests_service.TerminalComputeRequest]],
    namespace: str,
    request_ids: Collection[str],
    queued_at: float,
) -> tuple[list[compute_requests_service.TerminalComputeRequest], float, float]:
    poll_started = time.monotonic()
    terminal_ids = poll_namespace(namespace, request_ids)
    return terminal_ids, (poll_started - queued_at) * 1000, (time.monotonic() - poll_started) * 1000


class ComputeResponseRecovery:
    """Own local response waiters and recover lost completion notifications.

    Notifications and the recovery poller wake the same per-request state.
    Terminal results remain cached until every local HTTP follower unregisters,
    so a wake cannot be evicted between recovery and a delayed waiter.
    """

    def __init__(
        self,
        *,
        poll_seconds: float = _DEFAULT_POLL_SECONDS,
        poll_namespace: Callable[[str, Collection[str]], list[compute_requests_service.TerminalComputeRequest]] | None = None,
    ) -> None:
        self._poll_seconds = max(float(poll_seconds), 0.1)
        self._poll_namespace = poll_namespace or _poll_namespace
        # One state object owns the local single-flight reference count, wake,
        # and terminal cache until the last HTTP follower unregisters.
        self._pending: dict[str, _PendingComputeResponse] = {}
        self._lock = asyncio.Lock()
        self._poll_requested: asyncio.Event | None = None

    async def register(self, request_id: str, namespace: str) -> None:
        async with self._lock:
            current = self._pending.get(request_id)
            if current is None:
                self._pending[request_id] = _PendingComputeResponse(namespace=namespace, registered_at=time.monotonic())
            elif current.namespace == namespace:
                current.waiter_count += 1
            else:
                raise ValueError(f'Request {request_id} is already registered for namespace {current.namespace!r}')

    async def unregister(self, request_id: str) -> None:
        async with self._lock:
            current = self._pending.get(request_id)
            if current is None:
                return
            if current.waiter_count <= 1:
                self._pending.pop(request_id, None)
            else:
                current.waiter_count -= 1

    async def terminal_request(self, request_id: str) -> compute_requests_service.TerminalComputeRequest | None:
        async with self._lock:
            pending = self._pending.get(request_id)
            return pending.terminal if pending is not None else None

    async def wake_version(self, request_id: str) -> int:
        async with self._lock:
            pending = self._pending.get(request_id)
            return pending.wake_version if pending is not None else 0

    async def wait_for_wake(self, request_id: str, last_seen: int) -> int:
        wait_started = time.monotonic()
        wake_version = last_seen
        state_id = event_id = loop_id = 0
        event_was_set = False
        while True:
            async with self._lock:
                pending = self._pending.get(request_id)
                if pending is None:
                    return last_seen
                state_id = id(pending)
                event_id = id(pending.wake_event)
                loop_id = id(asyncio.get_running_loop())
                event_was_set = pending.wake_event.is_set()
                if pending.wake_version != last_seen:
                    wake_version = pending.wake_version
                    break
                event = pending.wake_event
                event.clear()
            await event.wait()
        wait_ms = (time.monotonic() - wait_started) * 1000
        if wait_ms >= 5_000:
            logger.warning(
                'Slow compute response signal wait request_id=%s process_id=%s state_id=%s event_id=%s '
                'loop_id=%s wake_version=%s event_was_set=%s wait_ms=%.1f',
                request_id,
                os.getpid(),
                state_id,
                event_id,
                loop_id,
                wake_version,
                event_was_set,
                wait_ms,
            )
        return wake_version

    async def notify(self, request_id: str) -> None:
        """Wake local followers after the durable terminal commit notification."""
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return
            pending.wake_version += 1
            pending.wake_event.set()

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._pending)

    async def clear(self) -> None:
        async with self._lock:
            self._pending.clear()

    def request_poll(self) -> None:
        """Coalesce requests on the API loop; the initial scan covers pre-start hints."""
        if self._poll_requested is not None:
            self._poll_requested.set()

    async def run(self, stop_event: asyncio.Event) -> None:
        if self._poll_requested is not None:
            raise RuntimeError('Compute response recovery is already running')
        # Allocate once per lifespan, never replace an active waiter's event.
        wake = asyncio.Event()
        self._poll_requested = wake
        try:
            while not stop_event.is_set():
                wake.clear()
                await self._poll_once()
                await self._wait_for_next_poll(stop_event, wake)
        finally:
            self._poll_requested = None

    async def _poll_once(self) -> None:
        async with self._lock:
            pending = {request_id: (state.namespace, state.registered_at) for request_id, state in self._pending.items() if state.terminal is None}
        grouped: dict[str, list[str]] = defaultdict(list)
        for request_id, (namespace, _registered_at) in pending.items():
            grouped[namespace].append(request_id)

        for namespace, request_ids in grouped.items():
            for offset in range(0, len(request_ids), _MAX_REQUESTS_PER_NAMESPACE_POLL):
                batch = request_ids[offset : offset + _MAX_REQUESTS_PER_NAMESPACE_POLL]
                queued_at = time.monotonic()

                try:
                    terminal_requests, executor_queue_ms, database_poll_ms = await asyncio.get_running_loop().run_in_executor(
                        _POLL_EXECUTOR,
                        _poll_with_timing,
                        self._poll_namespace,
                        namespace,
                        batch,
                        queued_at,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        'Compute response recovery poll failed process_id=%s namespace=%s request_count=%s',
                        os.getpid(),
                        namespace,
                        len(batch),
                        exc_info=True,
                    )
                    continue

                poll_duration_ms = (time.monotonic() - queued_at) * 1000
                if poll_duration_ms >= 1_000:
                    logger.warning(
                        'Slow compute response recovery poll namespace=%s request_count=%s terminal_count=%s '
                        'process_id=%s duration_ms=%.1f executor_queue_ms=%.1f database_poll_ms=%.1f',
                        namespace,
                        len(batch),
                        len(terminal_requests),
                        os.getpid(),
                        poll_duration_ms,
                        executor_queue_ms,
                        database_poll_ms,
                    )

                recovered_waits_ms: list[float] = []
                recovered_request_ids: list[str] = []
                recovered_wake_states: list[str] = []
                for terminal_request in terminal_requests:
                    request_id = terminal_request.id
                    async with self._lock:
                        current = self._pending.get(request_id)
                        if current is None or current.namespace != namespace:
                            continue
                        recovered_waits_ms.append((time.monotonic() - current.registered_at) * 1000)
                        recovered_request_ids.append(request_id)
                        current.terminal = terminal_request
                        current.wake_version += 1
                        current.wake_event.set()
                        recovered_wake_states.append(
                            f'{request_id}:{id(current)}:{id(current.wake_event)}:{current.wake_version}:{id(asyncio.get_running_loop())}'
                        )
                    logger.debug(
                        'Recovered terminal compute response request_id=%s namespace=%s process_id=%s',
                        request_id,
                        namespace,
                        os.getpid(),
                    )
                if recovered_waits_ms and max(recovered_waits_ms) >= 10_000:
                    logger.warning(
                        'Recovered compute responses from durable state namespace=%s request_count=%s request_ids=%s '
                        'process_id=%s max_wait_ms=%.1f poll_duration_ms=%.1f wake_states=%s',
                        namespace,
                        len(recovered_waits_ms),
                        ','.join(recovered_request_ids[:10]),
                        os.getpid(),
                        max(recovered_waits_ms),
                        poll_duration_ms,
                        ','.join(recovered_wake_states[:10]),
                    )

    async def _wait_for_next_poll(self, stop_event: asyncio.Event, wake: asyncio.Event) -> None:
        stop_task = asyncio.create_task(stop_event.wait())
        wake_task = asyncio.create_task(wake.wait())
        tasks = (stop_task, wake_task)
        try:
            await asyncio.wait(tasks, timeout=self._poll_seconds, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


response_recovery = ComputeResponseRecovery()
