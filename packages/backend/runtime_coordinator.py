from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import signal
import threading
from collections.abc import Callable

import psycopg

from backend_core import runtime_ipc
from backend_core.config import settings
from backend_core.database import init_db, set_active_runtime_coordinator_generation
from backend_core.logging import configure_logging_off_loop
from backend_core.public_schema import ensure_backend_public_tables
from backend_core.runtime_ipc import RuntimeListenerKind
from backend_core.runtime_outbox_dispatcher import OUTBOX_WAKE_HUB, RuntimeOutboxDispatcher
from backend_core.runtime_outbox_service import OUTBOX_WAKE_KIND
from backend_grpc.server import start_runtime_grpc_server

logger = logging.getLogger(__name__)

_COORDINATOR_LOCK_KEY = int.from_bytes(hashlib.sha256(b'dataforge:runtime-coordinator').digest()[:8], 'big', signed=True)
_LEASE_CHECK_SECONDS = 1.0
_LEASE_RETRY_SECONDS = 1.0


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
    coordinator port.
    """

    def __init__(self, *, connection_factory=psycopg.connect) -> None:
        self._connection_factory = connection_factory
        self._connection: psycopg.Connection | None = None
        self._generation: int | None = None
        self._owns_lock = False
        self._connection_lock = threading.Lock()

    @property
    def generation(self) -> int:
        if self._generation is None:
            raise RuntimeError('Runtime coordinator fencing generation is not active')
        return self._generation

    def acquire(self) -> bool:
        with self._connection_lock:
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
                    options='-c statement_timeout=3000 -c lock_timeout=1000',
                )
            try:
                result = self._connection.execute(
                    'SELECT pg_try_advisory_lock(%s)',
                    (_COORDINATOR_LOCK_KEY,),
                ).fetchone()
            except BaseException:
                if not self._connection.closed:
                    self._connection.close()
                self._connection = None
                raise
            self._owns_lock = bool(result and result[0])
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

    def check(self) -> None:
        with self._connection_lock:
            connection = self._connection
            if connection is None or connection.closed:
                raise RuntimeError('Runtime coordinator PostgreSQL lease connection is closed')
            if not self._owns_lock:
                raise RuntimeError('Runtime coordinator advisory lease is not held')
            if self._generation is None:
                connection.execute('SELECT 1')
            else:
                generation = self._generation
                row = connection.execute(
                    """
                    SELECT EXISTS (
                               SELECT 1
                               FROM pg_locks
                               WHERE locktype = 'advisory'
                                 AND pid = pg_backend_pid()
                                 AND classid = %s::oid
                                 AND objid = %s::oid
                                 AND objsubid = 1
                           ),
                           generation
                    FROM public.runtime_coordinator_state
                    WHERE singleton_id = 1
                    """,
                    (
                        ((_COORDINATOR_LOCK_KEY & 0xFFFFFFFFFFFFFFFF) >> 32),
                        (_COORDINATOR_LOCK_KEY & 0xFFFFFFFF),
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeError('Runtime coordinator fencing state is missing')
                if not row[0]:
                    raise RuntimeError('Runtime coordinator advisory lease was lost')
                if int(row[1]) != generation:
                    raise RuntimeError('Runtime coordinator fencing generation was superseded')

    def release(self) -> None:
        with self._connection_lock:
            connection = self._connection
            self._connection = None
            self._generation = None
            owns_lock = self._owns_lock
            self._owns_lock = False
            if connection is None:
                return
            if owns_lock:
                with contextlib.suppress(psycopg.Error):
                    connection.execute('SELECT pg_advisory_unlock(%s)', (_COORDINATOR_LOCK_KEY,))
            connection.close()


async def _handle_coordinator_notification(payload: dict[str, object]) -> None:
    """Wake the one outbox dispatcher without owning UI/runtime projections."""
    if payload.get('kind') != OUTBOX_WAKE_KIND:
        return
    namespace = payload.get('namespace')
    OUTBOX_WAKE_HUB.publish(namespace if isinstance(namespace, str) and namespace else None)


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
            await asyncio.to_thread(lease.check)
        except Exception:
            logger.critical('Runtime coordinator lease was lost; stopping this coordinator', exc_info=True)
            owner_stop_event.set()
            return


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


async def _run_worker_runtime(
    stop_event: asyncio.Event,
    *,
    coordinator_generation: int,
    coordinator_guard: Callable[[], None],
) -> None:
    """Run engine ownership in this process, beside the backend gRPC server."""
    try:
        from runtime.coordinator import run_runtime_coordinator  # type: ignore[import-untyped]  # Worker runtime is a separate package in this image.
    except ModuleNotFoundError as exc:
        raise RuntimeError('The runtime coordinator image must include the worker runtime package') from exc
    previous_generation = os.environ.get('RUNTIME_COORDINATOR_GENERATION')
    try:
        await run_runtime_coordinator(
            stop_event=stop_event,
            coordinator_generation=coordinator_generation,
            coordinator_guard=coordinator_guard,
        )
    finally:
        if previous_generation is None:
            os.environ.pop('RUNTIME_COORDINATOR_GENERATION', None)
        else:
            os.environ['RUNTIME_COORDINATOR_GENERATION'] = previous_generation


async def _run_owned_epoch(process_stop_event: asyncio.Event, lease: RuntimeCoordinatorLease) -> None:
    owner_stop_event = asyncio.Event()
    process_stop_task = asyncio.create_task(process_stop_event.wait(), name='runtime-process-stop')
    owner_stop_task = asyncio.create_task(owner_stop_event.wait(), name='runtime-owner-stop')
    grpc_server = None
    listener = None
    listener_task: asyncio.Task[None] | None = None
    dispatcher_task: asyncio.Task[None] | None = None
    lease_task: asyncio.Task[None] | None = None
    engine_task: asyncio.Task[None] | None = None
    coordinator_generation: int | None = None
    try:
        if process_stop_event.is_set():
            return
        lease_task = asyncio.create_task(_lease_monitor(process_stop_event, owner_stop_event, lease))
        await init_db()
        if process_stop_event.is_set() or owner_stop_event.is_set():
            raise RuntimeError('Runtime coordinator lease was lost during database startup')
        coordinator_generation = await asyncio.to_thread(lease.activate_generation)
        set_active_runtime_coordinator_generation(coordinator_generation)
        await asyncio.to_thread(ensure_backend_public_tables)
        grpc_server = await start_runtime_grpc_server()
        if process_stop_event.is_set() or owner_stop_event.is_set():
            raise RuntimeError('Runtime coordinator lease was lost during gRPC startup')
        engine_task = asyncio.create_task(
            _run_worker_runtime(
                owner_stop_event,
                coordinator_generation=coordinator_generation,
                coordinator_guard=lease.check,
            ),
            name='runtime-engine-coordinator',
        )
        listener = await runtime_ipc.start_api_server(listener=RuntimeListenerKind.JOB)
        listener_task = asyncio.create_task(runtime_ipc.serve_api_notifications(listener, owner_stop_event, _handle_coordinator_notification))
        dispatcher_task = asyncio.create_task(RuntimeOutboxDispatcher().run(owner_stop_event))
        logger.info(
            'Runtime coordinator started pid=%s grpc=%s:%s coordinator_generation=%s lease=postgres-advisory-lock engine-owner=coordinator',
            os.getpid(),
            settings.internal_grpc_host,
            settings.internal_grpc_port,
            coordinator_generation,
        )
        done, _pending = await asyncio.wait(
            {process_stop_task, owner_stop_task, engine_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if engine_task in done:
            await engine_task
        elif process_stop_task in done:
            owner_stop_event.set()
    finally:
        owner_stop_event.set()
        for task in (process_stop_task, owner_stop_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(process_stop_task, owner_stop_task, return_exceptions=True)
        # Withdraw the control-plane endpoint before stopping engines. An old
        # owner must not accept new lifecycle/claim RPCs while a replacement
        # is taking its fencing epoch.
        if grpc_server is not None:
            await grpc_server.stop(grace=0.5)
            grpc_server = None
        await runtime_ipc.stop_api_server(listener, listener=RuntimeListenerKind.JOB)
        tasks = [task for task in (listener_task, dispatcher_task, lease_task, engine_task) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        set_active_runtime_coordinator_generation(None)
        await asyncio.to_thread(lease.release)
        logger.info('Runtime coordinator stopped generation=%s', coordinator_generation)


async def main() -> None:
    await configure_logging_off_loop()
    if not settings.distributed_runtime_enabled:
        raise RuntimeError('The runtime coordinator requires DISTRIBUTED_RUNTIME_ENABLED=true')

    lease = RuntimeCoordinatorLease()
    process_stop_event = asyncio.Event()
    _install_stop_handlers(process_stop_event)
    retry_seconds = _LEASE_RETRY_SECONDS
    try:
        while not process_stop_event.is_set():
            if not await _wait_for_lease(process_stop_event, lease):
                return
            try:
                await _run_owned_epoch(process_stop_event, lease)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Runtime coordinator owner epoch failed; returning to standby')
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
    finally:
        await asyncio.to_thread(lease.release)


if __name__ == '__main__':
    asyncio.run(main())
