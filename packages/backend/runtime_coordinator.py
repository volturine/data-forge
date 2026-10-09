from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import signal
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from functools import partial
from typing import Any

import psycopg
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from backend_core import runtime_ipc
from backend_core.config import settings
from backend_core.coordinator_health import CoordinatorHealth
from backend_core.database import (
    active_runtime_coordinator_generation,
    configure_runtime_critical_database_budget,
    init_db,
    set_active_runtime_coordinator_generation,
)
from backend_core.logging import configure_logging_off_loop
from backend_core.public_schema import ensure_backend_public_tables
from backend_core.runtime_integration_delivery import NotificationDeliveryDispatcher
from backend_core.runtime_ipc import RuntimeListenerKind
from backend_core.runtime_outbox_dispatcher import OUTBOX_WAKE_HUB, RuntimeOutboxDispatcher
from backend_core.runtime_outbox_service import OUTBOX_WAKE_KIND
from backend_grpc.server import start_runtime_grpc_server
from modules.chat.consumer import ChatTurnConsumer
from modules.chat.store import CHAT_TURN_WAKE_KIND
from modules.telegram.runtime import TelegramIntegrationRuntime

logger = logging.getLogger(__name__)

_COORDINATOR_LOCK_KEY = int.from_bytes(hashlib.sha256(b'dataforge:runtime-coordinator').digest()[:8], 'big', signed=True)
_LEASE_CHECK_SECONDS = 1.0
_LEASE_CHECK_FRESHNESS_SECONDS = 0.25
_LEASE_RETRY_SECONDS = 1.0
# The advisory lock lives on this session. A coordinator whose machine vanishes
# never closes the connection, so PostgreSQL must notice the dead peer itself:
# probe after 5s idle, every 2s, three misses, instead of the OS default of
# two hours. Only then can a standby on another machine take over.
_LEASE_SESSION_OPTIONS = '-c statement_timeout=3000 -c lock_timeout=1000 -c tcp_keepalives_idle=5 -c tcp_keepalives_interval=2 -c tcp_keepalives_count=3'
_ACTOR_SHUTDOWN_GRACE_SECONDS = 15.0
_CHAT_DATABASE_RETRY_MIN_SECONDS = 0.25
_CHAT_DATABASE_RETRY_MAX_SECONDS = 5.0


def _database_conninfo() -> str:
    if not settings.database_url:
        raise RuntimeError('DATABASE_URL must be configured for the runtime coordinator')
    return settings.database_url.replace('postgresql+psycopg://', 'postgresql://', 1)


class RuntimeCoordinatorLease:
    """Hold the singleton control-plane lease on one PostgreSQL session.

    The advisory lock is session-owned. If this process or its database
    connection disappears, PostgreSQL releases the lock and a replacement
    coordinator can start. No API child can accidentally become a second
    runtime gRPC owner because it never acquires this lease or binds the
    coordinator port. Request-path checks may reuse a very recent successful
    session ping. The lease monitor always forces a new ping; neither path
    reads ``pg_locks`` or the fencing row because the dedicated live session
    owns the advisory lock.
    """

    def __init__(self, *, connection_factory=psycopg.connect) -> None:
        self._connection_factory = connection_factory
        self._connection: psycopg.Connection | None = None
        self._generation: int | None = None
        self._owns_lock = False
        self._connection_lock = threading.Lock()
        self._check_lock = threading.Lock()
        self._check_inflight: Future[None] | None = None
        self._check_valid_until = 0.0
        self._check_epoch = 0
        self._last_ping_timeout_log = 0.0

    @property
    def generation(self) -> int:
        if self._generation is None:
            raise RuntimeError('Runtime coordinator fencing generation is not active')
        return self._generation

    def acquire(self) -> bool:
        with self._connection_lock:
            self._invalidate_check_cache()
            if self._owns_lock:
                raise RuntimeError('Runtime coordinator lease is already held')
            if self._connection is None or self._connection.closed:
                self._connection = self._connection_factory(
                    _database_conninfo(),
                    autocommit=True,
                    connect_timeout=5,
                    keepalives_idle=2,
                    keepalives_interval=1,
                    keepalives_count=3,
                    options=_LEASE_SESSION_OPTIONS,
                )
            try:
                result = self._connection.execute(
                    'SELECT pg_try_advisory_lock(%s)',
                    (_COORDINATOR_LOCK_KEY,),
                ).fetchone()
                self._owns_lock = bool(result and result[0])
                if not self._owns_lock:
                    return False
            except BaseException:
                if not self._connection.closed:
                    self._connection.close()
                self._connection = None
                self._owns_lock = False
                raise
            return self._owns_lock

    def activate_generation(self) -> int:
        with self._connection_lock:
            connection = self._connection
            if connection is None or connection.closed or not self._owns_lock:
                raise RuntimeError('Runtime coordinator lease must be held before activating its generation')
            if self._generation is not None:
                raise RuntimeError('Runtime coordinator generation is already active')
            row = connection.execute(
                """
                UPDATE public.runtime_coordinator_state
                SET generation = generation + 1
                WHERE singleton_id = 1
                RETURNING generation
                """
            ).fetchone()
            if row is None:
                raise RuntimeError('Runtime coordinator fencing state is missing; database migrations did not run')
            self._generation = int(row[0])
            return self._generation

    def check(self, *, force: bool = False) -> None:
        with self._check_lock:
            check = self._check_inflight
            if check is None and not force and time.monotonic() < self._check_valid_until:
                return
            is_owner = check is None
            check_epoch = self._check_epoch
            if check is None:
                check = Future()
                self._check_inflight = check
        if not is_owner:
            check.result()
            return

        try:
            confirmed = self._check_owner_session()
        except BaseException as exc:
            self._invalidate_check_cache()
            check.set_exception(exc)
            raise
        else:
            with self._check_lock:
                if check_epoch == self._check_epoch:
                    self._check_valid_until = time.monotonic() + _LEASE_CHECK_FRESHNESS_SECONDS if confirmed else 0.0
            check.set_result(None)
        finally:
            with self._check_lock:
                if self._check_inflight is check:
                    self._check_inflight = None

    def _check_owner_session(self) -> bool:
        with self._connection_lock:
            connection = self._connection
            if connection is None or connection.closed:
                raise RuntimeError('Runtime coordinator PostgreSQL lease connection is closed')
            if not self._owns_lock:
                raise RuntimeError('Runtime coordinator advisory lease is not held')
            # This connection is dedicated to the session-level advisory
            # lock. PostgreSQL keeps that lock until this session explicitly
            # unlocks or disconnects; only release() can unlock it, under the
            # same connection lock. A successful round-trip here therefore
            # proves the lock-owning session is still alive without scanning
            # pg_locks or the fencing table for every lifecycle RPC.
            try:
                connection.execute('SELECT 1')
            except psycopg.errors.QueryCanceled:
                # PostgreSQL responded, so the session and its advisory lock
                # are still alive. This probe did not complete, however, so
                # it must not refresh the successful-check cache.
                now = time.monotonic()
                if now - self._last_ping_timeout_log >= 30.0:
                    logger.warning('Runtime coordinator owner-session lease ping timed out; retaining the live session lock and retrying')
                    self._last_ping_timeout_log = now
                return False
            except psycopg.Error as exc:
                raise RuntimeError('Runtime coordinator advisory lease connection is unavailable') from exc
            return True

    def _invalidate_check_cache(self) -> None:
        with self._check_lock:
            self._check_epoch += 1
            self._check_valid_until = 0.0

    def release(self) -> None:
        with self._connection_lock:
            connection = self._connection
            self._connection = None
            self._generation = None
            owns_lock = self._owns_lock
            self._owns_lock = False
            self._invalidate_check_cache()
            if connection is None:
                return
            if owns_lock:
                with contextlib.suppress(psycopg.Error):
                    connection.execute('SELECT pg_advisory_unlock(%s)', (_COORDINATOR_LOCK_KEY,))
            connection.close()


async def _handle_coordinator_notification(
    payload: dict[str, object],
    *,
    chat_wake: Callable[[], None],
    telegram_wake: Callable[[], None],
) -> None:
    kind = payload.get('kind')
    if kind == OUTBOX_WAKE_KIND:
        namespace = payload.get('namespace')
        OUTBOX_WAKE_HUB.publish(namespace if isinstance(namespace, str) and namespace else None)
        return
    if kind == CHAT_TURN_WAKE_KIND:
        chat_wake()
        return
    if kind in {'settings_changed', 'telegram_detection'}:
        telegram_wake()


async def _recover_coordinator_notifications(*, chat_wake: Callable[[], None], telegram_wake: Callable[[], None]) -> None:
    """Wake durable consumers after initial LISTEN readiness or a reconnect."""
    OUTBOX_WAKE_HUB.publish(None)
    chat_wake()
    telegram_wake()


async def _supervise_epoch(tasks: list[asyncio.Task[None]], process_stop: asyncio.Task[bool], owner_stop: asyncio.Task[bool]) -> None:
    done, _pending = await asyncio.wait({process_stop, owner_stop, *tasks}, return_when=asyncio.FIRST_COMPLETED)
    if process_stop in done or owner_stop in done:
        return
    for task in done:
        if task.cancelled():
            raise RuntimeError(f'Coordinator actor {task.get_name()} was unexpectedly canceled')
        error = task.exception()
        if error is not None:
            raise RuntimeError(f'Coordinator actor {task.get_name()} failed') from error
        raise RuntimeError(f'Coordinator actor {task.get_name()} exited unexpectedly')


def _install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def stop() -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop)


async def _lease_monitor(
    process_stop_event: asyncio.Event,
    owner_stop_event: asyncio.Event,
    lease: RuntimeCoordinatorLease,
) -> None:
    while not process_stop_event.is_set() and not owner_stop_event.is_set():
        try:
            await asyncio.wait_for(process_stop_event.wait(), timeout=_LEASE_CHECK_SECONDS)
            return
        except TimeoutError:
            pass
        try:
            await asyncio.to_thread(lease.check, force=True)
        except Exception:
            logger.critical('Runtime coordinator lease was lost; stopping this coordinator', exc_info=True)
            owner_stop_event.set()
            return


async def _run_chat_turn_consumer(
    run: Callable[[asyncio.Event], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    """Reconnect the durable chat consumer without taking down runtime RPCs."""
    delay = _CHAT_DATABASE_RETRY_MIN_SECONDS
    while not stop_event.is_set():
        try:
            await run(stop_event)
            if stop_event.is_set():
                return
            raise RuntimeError('Chat turn consumer exited unexpectedly')
        except asyncio.CancelledError:
            raise
        except SQLAlchemyOperationalError, psycopg.OperationalError:
            if stop_event.is_set():
                return
            logger.warning(
                'Chat turn consumer database connection failed; retrying in %.2fs',
                delay,
                exc_info=True,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
                return
            except TimeoutError:
                delay = min(delay * 2, _CHAT_DATABASE_RETRY_MAX_SECONDS)


async def _wait_for_lease(stop_event: asyncio.Event, lease: RuntimeCoordinatorLease) -> bool:
    """Keep a standby alive until it can safely become the sole coordinator."""
    next_log = 0.0
    while not stop_event.is_set():
        acquire_task = asyncio.create_task(asyncio.to_thread(lease.acquire))
        try:
            acquired = await asyncio.shield(acquire_task)
            if acquired:
                if stop_event.is_set():
                    await asyncio.to_thread(lease.release)
                    return False
                return True
            now = asyncio.get_running_loop().time()
            if now >= next_log:
                logger.info('Runtime coordinator standby waiting for the active owner to release its lease')
                next_log = now + 30.0
        except asyncio.CancelledError:
            # Cancelling asyncio.to_thread does not stop the blocking DB call.
            # Join it before releasing the connection so a late advisory-lock
            # acquisition cannot outlive this standby task.
            with contextlib.suppress(Exception):
                acquired = await asyncio.shield(acquire_task)
                if acquired:
                    await asyncio.to_thread(lease.release)
            raise
        except Exception:
            logger.warning('Runtime coordinator standby could not check the lease; retrying', exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_LEASE_RETRY_SECONDS)
        except TimeoutError:
            continue
    return False


async def _cancel_and_join_actors(tasks: list[asyncio.Task[None]]) -> None:
    """Request actor shutdown, then join every task before relinquishing ownership."""
    if not tasks:
        return
    _done, pending = await asyncio.wait(tasks, timeout=_ACTOR_SHUTDOWN_GRACE_SECONDS)
    for task in pending:
        task.cancel()
    if pending:
        # Actors may be inside bounded synchronous DB/provider operations.
        # Their cancellation handlers join those exact operations. There is
        # deliberately no second timeout here: releasing the epoch while any
        # actor can still publish would permit overlapping coordinator work.
        await asyncio.gather(*pending, return_exceptions=True)
    for task in tasks:
        if task.done() and not task.cancelled():
            task.exception()


async def _finish_actor_shutdown(tasks: list[asyncio.Task[None]]) -> bool:
    """Make actor join a teardown barrier even if the epoch is cancelled again.

    Returns whether another cancellation arrived while the barrier was being
    completed. The caller can propagate it after clearing the generation and
    releasing the lease, which is safe only after all actor tasks have settled.
    """
    shutdown = asyncio.create_task(_cancel_and_join_actors(tasks), name='coordinator-actor-shutdown')
    interrupted = False
    current = asyncio.current_task()
    while not shutdown.done():
        try:
            await asyncio.shield(shutdown)
        except asyncio.CancelledError:
            interrupted = True
            if current is not None:
                current.uncancel()
    shutdown.result()
    return interrupted


async def _settle_epoch_ownership(tasks: list[asyncio.Task[None]], lease: RuntimeCoordinatorLease) -> bool:
    """Clear local fencing and release the DB lease only after all actors settle."""
    interrupted = await _finish_actor_shutdown(tasks)
    set_active_runtime_coordinator_generation(None)
    await asyncio.to_thread(lease.release)
    return interrupted


async def _stop_endpoints_and_settle_epoch(
    owner_stop_event: asyncio.Event,
    control_tasks: tuple[asyncio.Task[bool], asyncio.Task[bool]],
    grpc_server: Any | None,
    listener: Any,
    tasks: list[asyncio.Task[None]],
    lease: RuntimeCoordinatorLease,
) -> bool:
    """Attempt endpoint shutdowns but make actor settlement unconditional."""
    shutdown_errors: list[BaseException] = []
    owner_stop_event.set()
    for task in control_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*control_tasks, return_exceptions=True)
    try:
        if grpc_server is not None:
            await grpc_server.stop(grace=0.5)
    except BaseException as exc:
        shutdown_errors.append(exc)
        logger.error('Runtime coordinator gRPC shutdown failed', exc_info=(type(exc), exc, exc.__traceback__))
    try:
        await runtime_ipc.stop_api_server(listener, listener=RuntimeListenerKind.JOB)
    except BaseException as exc:
        shutdown_errors.append(exc)
        logger.error('Runtime coordinator listener shutdown failed', exc_info=(type(exc), exc, exc.__traceback__))
    if shutdown_errors:
        # An endpoint that failed to stop may still admit work. Join actors,
        # but retain the fencing generation and advisory lease so a standby
        # cannot overlap this possibly-live endpoint.
        await _finish_actor_shutdown(tasks)
        raise RuntimeError('Runtime coordinator endpoint shutdown failed; retaining its lease') from shutdown_errors[0]
    interrupted = await _settle_epoch_ownership(tasks, lease)
    return interrupted


async def _finish_epoch_shutdown(
    owner_stop_event: asyncio.Event,
    control_tasks: tuple[asyncio.Task[bool], asyncio.Task[bool]],
    grpc_server: Any | None,
    listener: Any,
    tasks: list[asyncio.Task[None]],
    lease: RuntimeCoordinatorLease,
) -> bool:
    """Run the entire teardown barrier to completion despite further cancellation."""
    shutdown = asyncio.create_task(
        _stop_endpoints_and_settle_epoch(owner_stop_event, control_tasks, grpc_server, listener, tasks, lease),
        name='coordinator-epoch-shutdown',
    )
    interrupted = False
    current = asyncio.current_task()
    while not shutdown.done():
        try:
            await asyncio.shield(shutdown)
        except asyncio.CancelledError:
            interrupted = True
            if current is not None:
                current.uncancel()
    return interrupted or shutdown.result()


def _fail_stop_if_epoch_active() -> None:
    """Terminate the process if an epoch could still own live endpoints/work."""
    generation = active_runtime_coordinator_generation()
    if generation is not None:
        logger.critical(
            'Coordinator generation %s did not settle; terminating without releasing its PostgreSQL lease',
            generation,
        )
        os._exit(1)


async def _release_coordinator_lease(lease: RuntimeCoordinatorLease) -> None:
    """Release only a settled epoch; otherwise terminate without unlocking it."""
    _fail_stop_if_epoch_active()
    await asyncio.to_thread(lease.release)


async def _run_owned_epoch(process_stop_event: asyncio.Event, lease: RuntimeCoordinatorLease, *, health: CoordinatorHealth | None = None) -> None:
    owner_stop_event = asyncio.Event()
    process_stop_task = asyncio.create_task(process_stop_event.wait(), name='runtime-process-stop')
    owner_stop_task = asyncio.create_task(owner_stop_event.wait(), name='runtime-owner-stop')
    grpc_server = None
    listener = None
    tasks: list[asyncio.Task[None]] = []
    coordinator_generation: int | None = None
    try:
        if process_stop_event.is_set():
            return
        from main import app

        tasks.append(asyncio.create_task(_lease_monitor(process_stop_event, owner_stop_event, lease), name='coordinator-lease'))
        await init_db()
        if process_stop_event.is_set() or owner_stop_event.is_set():
            raise RuntimeError('Runtime coordinator lease was lost during database startup')
        coordinator_generation = await asyncio.to_thread(lease.activate_generation)
        set_active_runtime_coordinator_generation(coordinator_generation)
        await asyncio.to_thread(ensure_backend_public_tables)
        grpc_server = await start_runtime_grpc_server(coordinator_guard=lease.check)
        if process_stop_event.is_set() or owner_stop_event.is_set():
            raise RuntimeError('Runtime coordinator lease was lost during gRPC startup')
        listener = await runtime_ipc.start_api_server(listener=RuntimeListenerKind.JOB)
        if health is not None:
            health.active(coordinator_generation)
        chat_consumer = await asyncio.to_thread(ChatTurnConsumer, app, coordinator_generation)
        telegram_runtime = TelegramIntegrationRuntime(coordinator_generation)
        handler = partial(_handle_coordinator_notification, chat_wake=chat_consumer.wake, telegram_wake=telegram_runtime.wake)
        recover = partial(_recover_coordinator_notifications, chat_wake=chat_consumer.wake, telegram_wake=telegram_runtime.wake)
        tasks.extend(
            [
                asyncio.create_task(
                    runtime_ipc.serve_api_notifications(listener, owner_stop_event, handler, recover=recover), name='coordinator-notifications'
                ),
                asyncio.create_task(RuntimeOutboxDispatcher().run(owner_stop_event), name='runtime-outbox'),
                asyncio.create_task(NotificationDeliveryDispatcher().run(owner_stop_event), name='notification-delivery'),
                asyncio.create_task(_run_chat_turn_consumer(chat_consumer.run, owner_stop_event), name='chat-turn-consumer'),
                asyncio.create_task(telegram_runtime.run(owner_stop_event), name='telegram-integration'),
            ]
        )
        logger.info(
            'Runtime coordinator started pid=%s grpc=%s:%s coordinator_generation=%s lease=postgres-advisory-lock engine-owner=worker-service',
            os.getpid(),
            settings.internal_grpc_host,
            settings.internal_grpc_port,
            coordinator_generation,
        )
        await _supervise_epoch(tasks, process_stop_task, owner_stop_task)
    finally:
        # Run endpoint shutdown and the actor/lease barrier in a separate
        # cancellation-resistant task. No endpoint-stop error or cancellation
        # may bypass settlement and let main() release a live epoch.
        try:
            interrupted_shutdown = await _finish_epoch_shutdown(
                owner_stop_event,
                (process_stop_task, owner_stop_task),
                grpc_server,
                listener,
                tasks,
                lease,
            )
        except RuntimeError:
            process_stop_event.set()
            raise
        if health is not None:
            health.standby()
        logger.info('Runtime coordinator stopped generation=%s', coordinator_generation)
        if interrupted_shutdown:
            raise asyncio.CancelledError


async def main() -> None:
    configure_runtime_critical_database_budget()
    await configure_logging_off_loop()
    if not settings.distributed_runtime_enabled:
        raise RuntimeError('The runtime coordinator requires DISTRIBUTED_RUNTIME_ENABLED=true')

    lease = RuntimeCoordinatorLease()
    process_stop_event = asyncio.Event()
    _install_stop_handlers(process_stop_event)
    retry_seconds = _LEASE_RETRY_SECONDS
    health = CoordinatorHealth()
    try:
        async with health.serve():
            await _run_coordinator_roles(process_stop_event, lease, health, retry_seconds)
    finally:
        await _release_coordinator_lease(lease)


async def _run_coordinator_roles(
    process_stop_event: asyncio.Event,
    lease: RuntimeCoordinatorLease,
    health: CoordinatorHealth,
    retry_seconds: float,
) -> None:
    """Alternate between standby and owner until the process is asked to stop."""
    while not process_stop_event.is_set():
        health.standby()
        if not await _wait_for_lease(process_stop_event, lease):
            return
        try:
            await _run_owned_epoch(process_stop_event, lease, health=health)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Runtime coordinator owner epoch failed; returning to standby')
            _fail_stop_if_epoch_active()
        else:
            retry_seconds = _LEASE_RETRY_SECONDS
        if process_stop_event.is_set():
            return
        try:
            await asyncio.wait_for(process_stop_event.wait(), timeout=retry_seconds)
        except TimeoutError:
            retry_seconds = min(retry_seconds * 2, 30.0)
        else:
            return


if __name__ == '__main__':
    asyncio.run(main())
