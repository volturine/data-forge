from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import uuid
from collections.abc import Awaitable, Callable

import psycopg
from psycopg import Notify
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from backend_core.api_execution_budget import run_api_blocking
from backend_core.domain.enums import DataForgeStrEnum
from backend_core.domain.runtime.events import RuntimePayloadKind

logger = logging.getLogger(__name__)
# Identifies this API process in the notifications it publishes so it can skip
# its own echoes. A PID is not enough: containerized replicas usually all run
# their single API process as PID 1.
API_PROCESS_ID = uuid.uuid4().hex

_CHANNEL = 'runtime_events'
_database_url_provider: Callable[[], str] | None = None
type RuntimePayloadHandler = Callable[[dict[str, object]], Awaitable[None]]
type RuntimeRecovery = Callable[[], Awaitable[None]]


class RuntimeListenerKind(DataForgeStrEnum):
    API = 'api'
    JOB = 'job'


ListenerKind = RuntimeListenerKind | str
_notify_connection_state: tuple[psycopg.Connection, str] | None = None
_notify_connection_lock = threading.Lock()
_notify_connection_io_lock = threading.Lock()


class RuntimeNotificationListener:
    """Own a dedicated async LISTEN connection and consume without prefetching.

    One continuous generator applies transport backpressure while a handler
    awaits. There is no application queue or callback per notification. Lost
    connections request durable recovery through one coalesced event.
    """

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._connection: psycopg.AsyncConnection | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._serving_task: asyncio.Task[None] | None = None
        self._recovery_requested = asyncio.Event()

    async def start(self) -> None:
        if self._loop is not None:
            raise RuntimeError('PostgreSQL runtime notification listener is already started')
        self._loop = asyncio.get_running_loop()
        async with asyncio.timeout(10.0):
            await self._connect()

    async def _connect(self) -> None:
        connection = await psycopg.AsyncConnection.connect(self._conninfo, autocommit=True, connect_timeout=5)
        try:
            await connection.execute(f'LISTEN {_CHANNEL}')
        except BaseException:
            await connection.close()
            raise
        self._connection = connection
        self._recovery_requested.set()
        logger.info('Runtime notification listener connected')

    async def _listen(self, handler: RuntimePayloadHandler) -> None:
        reconnect_delay = 0.25
        while True:
            try:
                if self._connection is None:
                    await self._connect()
                connection = self._connection
                assert connection is not None
                reconnect_delay = 0.25
                # Keep the generator open even while awaiting a slow handler.
                # psycopg disables its notification backlog for this lifetime.
                async with contextlib.aclosing(connection.notifies()) as notifications:
                    delivered = 0
                    async for notify in notifications:
                        try:
                            payload = json.loads(_notify_payload(notify))
                        except json.JSONDecodeError as exc:
                            logger.debug('Ignoring malformed Postgres runtime notification: %s', exc)
                            self._recovery_requested.set()
                            continue
                        if isinstance(payload, dict):
                            try:
                                await handler(payload)
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                logger.exception('Runtime notification handler failed kind=%s', payload.get('kind', '-'))
                                self._recovery_requested.set()
                        delivered += 1
                        if delivered % 100 == 0:
                            await asyncio.sleep(0)
                raise psycopg.OperationalError('PostgreSQL runtime notification generator exited unexpectedly')
            except psycopg.Error, OSError:
                logger.warning('Runtime notification listener lost its connection; reconnecting', exc_info=True)
                self._recovery_requested.set()
                await self._close_connection()
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 5.0)

    async def _recover(self, recover: RuntimeRecovery) -> None:
        while True:
            await self._recovery_requested.wait()
            self._recovery_requested.clear()
            try:
                await recover()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning('Runtime notification recovery failed; retrying', exc_info=True)
                self._recovery_requested.set()
                await asyncio.sleep(1.0)

    async def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            await connection.close()

    def _require_owner_loop(self) -> None:
        if self._loop is not asyncio.get_running_loop():
            raise RuntimeError('PostgreSQL runtime notification listener must be used on its owning event loop')

    async def close(self) -> None:
        self._require_owner_loop()
        task = self._serving_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._close_connection()


def _psycopg_conninfo() -> str:
    database_url = _database_url_provider() if _database_url_provider is not None else os.environ.get('DATABASE_URL', '')
    if not database_url:
        raise RuntimeError('Runtime IPC database URL is not configured')
    return database_url.replace('postgresql+psycopg://', 'postgresql://', 1)


def configure_database_url_provider(provider: Callable[[], str] | None) -> None:
    _close_notify_connection(provider, replace_provider=True)


async def start_api_server(listener: ListenerKind = RuntimeListenerKind.API) -> RuntimeNotificationListener:
    del listener
    server = RuntimeNotificationListener(_psycopg_conninfo())
    try:
        await server.start()
    except BaseException:
        await server.close()
        raise
    return server


async def serve_api_notifications(
    listener: RuntimeNotificationListener,
    stop_event: asyncio.Event,
    handler: RuntimePayloadHandler,
    *,
    recover: RuntimeRecovery,
) -> None:
    listener._require_owner_loop()
    if listener._connection is None:
        raise RuntimeError('PostgreSQL runtime notification listener has not started')
    if listener._serving_task is not None:
        raise RuntimeError('PostgreSQL runtime notification listener is already serving')
    if stop_event.is_set():
        return
    listener._serving_task = asyncio.current_task()
    consume_task = asyncio.create_task(listener._listen(handler), name='runtime-notification-receive')
    recovery_task = asyncio.create_task(listener._recover(recover), name='runtime-notification-recovery')
    stop_task = asyncio.create_task(stop_event.wait(), name='runtime-notification-stop')
    tasks = (consume_task, recovery_task, stop_task)
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            return
        for task in (consume_task, recovery_task):
            if task in done:
                task.result()
                raise RuntimeError(f'Runtime notification task {task.get_name()} exited unexpectedly')
    finally:
        for pending_task in tasks:
            pending_task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        listener._serving_task = None


def _notify_payload(notify: Notify) -> str:
    return notify.payload


async def stop_api_server(
    server: RuntimeNotificationListener | None,
    *,
    listener: ListenerKind = RuntimeListenerKind.API,
) -> None:
    del listener
    try:
        if server is not None:
            await server.close()
    finally:
        await run_api_blocking(_close_notify_connection)


def notify_api_build(namespace: str, build_id: str, latest_sequence: int) -> None:
    _send_api_message(
        {'kind': RuntimePayloadKind.BUILD.value, 'namespace': namespace, 'build_id': build_id, 'latest_sequence': latest_sequence},
        listener=RuntimeListenerKind.API,
    )


def notify_api_engine(namespace: str) -> None:
    _send_api_message({'kind': RuntimePayloadKind.ENGINE.value, 'namespace': namespace}, listener=RuntimeListenerKind.API)


def notify_build_job(namespace: str | None = None) -> None:
    payload: dict[str, object] = {'kind': RuntimePayloadKind.JOB.value}
    if namespace is not None:
        payload['namespace'] = namespace
    _send_api_message(payload, listener=RuntimeListenerKind.JOB)


def notify_compute_request_on_commit(session: Session, *, request_id: str, namespace: str, compute_kind: int) -> None:
    notify_runtime_payload_on_commit(
        session,
        {
            'kind': RuntimePayloadKind.COMPUTE_REQUEST.value,
            'request_id': request_id,
            'namespace': namespace,
            'compute_kind': compute_kind,
        },
    )


def notify_compute_response_on_commit(session: Session, *, request_id: str, namespace: str) -> None:
    notify_runtime_payload_on_commit(
        session,
        {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request_id, 'namespace': namespace},
    )


def notify_runtime_payload_on_commit(session: Session, payload: dict[str, object]) -> None:
    """Queue a small notification in the caller's transaction.

    PostgreSQL delivers it only after commit, so a durable state change and its
    wake become visible atomically without opening a second connection.
    """
    if RuntimePayloadKind.from_payload(payload) is None:
        raise ValueError(f'Unsupported runtime notification payload kind: {payload.get("kind")!r}')
    bind = session.get_bind()
    if getattr(getattr(bind, 'dialect', None), 'name', None) != 'postgresql':
        return
    session.execute(
        text('SELECT pg_notify(:channel, :payload)'),
        {'channel': _CHANNEL, 'payload': json.dumps(payload, separators=(',', ':'))},
    )


def notify_api_lock(
    namespace: str,
    resource_type: str,
    resource_id: str,
    status_payload: dict[str, object] | BaseModel,
) -> None:
    if isinstance(status_payload, BaseModel):
        status_payload = status_payload.model_dump(mode='json')
    _send_api_message(
        {
            'kind': 'lock',
            'namespace': namespace,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'status': status_payload,
            'source_process': API_PROCESS_ID,
        },
        listener=RuntimeListenerKind.API,
    )


def notify_runtime_payload(payload: dict[str, object]) -> None:
    kind = RuntimePayloadKind.from_payload(payload)
    if kind is None:
        raise ValueError(f'Unsupported runtime notification payload kind: {payload.get("kind")!r}')
    api_payload_kinds = {
        RuntimePayloadKind.BUILD,
        RuntimePayloadKind.ENGINE,
        RuntimePayloadKind.COMPUTE_RESPONSE,
    }
    listener = RuntimeListenerKind.API if kind in api_payload_kinds else RuntimeListenerKind.JOB
    _send_api_message(payload, listener=listener)


def _send_api_message(payload: dict[str, object], *, listener: ListenerKind) -> None:
    del listener
    _send_postgres_message(payload)


def _get_notify_connection() -> psycopg.Connection:
    global _notify_connection_state
    conninfo = _psycopg_conninfo()
    with _notify_connection_lock:
        if _notify_connection_state is not None:
            connection, cached_conninfo = _notify_connection_state
            if not connection.closed and cached_conninfo == conninfo:
                return connection
            if not connection.closed:
                connection.close()
        connection = psycopg.connect(conninfo, autocommit=True)
        _notify_connection_state = (connection, conninfo)
        return connection


def _reset_notify_connection() -> None:
    global _notify_connection_state
    with _notify_connection_lock:
        if _notify_connection_state is not None:
            connection, _conninfo = _notify_connection_state
            connection.close()
        _notify_connection_state = None


def _close_notify_connection(
    provider: Callable[[], str] | None = None,
    *,
    replace_provider: bool = False,
) -> None:
    """Serialize publisher shutdown/configuration against in-flight sends."""
    global _database_url_provider
    with _notify_connection_io_lock:
        if replace_provider:
            _database_url_provider = provider
        _reset_notify_connection()


def _send_postgres_message(payload: dict[str, object]) -> None:
    data = json.dumps(payload)
    # The cached psycopg connection is shared by all synchronous publishers in
    # one process. Serialise the execute/reconnect pair as well as connection
    # creation; protecting only _get_notify_connection still lets concurrent
    # lock/build notifications use one connection at the same time.
    with _notify_connection_io_lock:
        try:
            connection = _get_notify_connection()
            connection.execute('SELECT pg_notify(%s, %s)', (_CHANNEL, data))
        except psycopg.Error:
            _reset_notify_connection()
            connection = _get_notify_connection()
            connection.execute('SELECT pg_notify(%s, %s)', (_CHANNEL, data))
