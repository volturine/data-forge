from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import queue
import threading
from collections.abc import Awaitable, Callable

import psycopg
from psycopg import Notify
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from backend_core.domain.enums import DataForgeStrEnum
from backend_core.domain.runtime.events import RuntimePayloadKind

logger = logging.getLogger(__name__)

_CHANNEL = 'runtime_events'
_database_url_provider: Callable[[], str] | None = None


class RuntimeListenerKind(DataForgeStrEnum):
    API = 'api'
    JOB = 'job'


ListenerKind = RuntimeListenerKind | str
_notify_connection_state: tuple[psycopg.Connection, str] | None = None
_notify_connection_lock = threading.Lock()
_notify_connection_io_lock = threading.Lock()


class RuntimeNotificationListener:
    """Own a reconnectable PostgreSQL LISTEN connection on a dedicated thread.

    LISTEN/NOTIFY is an acceleration path only; the outbox and response
    recovery tasks are durable backstops. psycopg drains notifications in
    synchronous libpq code, so polling never runs on an API/coordinator event
    loop. Notifications are handed back to that loop for async fan-out.
    """

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._messages: queue.SimpleQueue[dict[str, object]] = queue.SimpleQueue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._startup_error: Exception | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._thread = threading.Thread(target=self._listen, name='runtime-notifications', daemon=True)
        self._thread.start()

    def wait_ready(self) -> None:
        if not self._ready.wait(timeout=10):
            raise TimeoutError('PostgreSQL runtime notification listener did not connect within 10 seconds')
        if self._startup_error is not None:
            raise RuntimeError('PostgreSQL runtime notification listener failed to start') from self._startup_error

    def _publish(self, payload: dict[str, object]) -> None:
        self._messages.put(payload)
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(wake.set)

    def _listen(self) -> None:
        reconnect_delay = 0.25
        first_connection = True
        while not self._stop.is_set():
            connection: psycopg.Connection | None = None
            try:
                connection = psycopg.connect(self._conninfo, autocommit=True, connect_timeout=5)
                connection.execute(f'LISTEN {_CHANNEL}')
                if first_connection:
                    first_connection = False
                    self._ready.set()
                reconnect_delay = 0.25
                logger.info('Runtime notification listener connected')
                while not self._stop.is_set():
                    for notify in connection.notifies(timeout=0.5, stop_after=100):
                        try:
                            payload = json.loads(_notify_payload(notify))
                        except json.JSONDecodeError as exc:
                            logger.debug('Ignoring malformed Postgres runtime notification: %s', exc)
                            continue
                        if isinstance(payload, dict):
                            self._publish(payload)
            except Exception as exc:
                if first_connection:
                    self._startup_error = exc
                    self._ready.set()
                elif not self._stop.is_set():
                    logger.warning('Runtime notification listener lost its connection; reconnecting', exc_info=True)
                if self._stop.wait(reconnect_delay):
                    break
                reconnect_delay = min(reconnect_delay * 2, 5.0)
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        connection.close()

    async def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            await asyncio.to_thread(thread.join, 6.0)
            if thread.is_alive():
                logger.error('PostgreSQL runtime notification listener did not stop within 6 seconds')


def _psycopg_conninfo() -> str:
    database_url = _database_url_provider() if _database_url_provider is not None else os.environ.get('DATABASE_URL', '')
    if not database_url:
        raise RuntimeError('Runtime IPC database URL is not configured')
    return database_url.replace('postgresql+psycopg://', 'postgresql://', 1)


def configure_database_url_provider(provider: Callable[[], str] | None) -> None:
    global _database_url_provider
    _database_url_provider = provider
    _reset_notify_connection()


async def start_api_server(listener: ListenerKind = RuntimeListenerKind.API) -> RuntimeNotificationListener:
    del listener
    server = RuntimeNotificationListener(_psycopg_conninfo())
    server.start()
    try:
        await asyncio.to_thread(server.wait_ready)
    except BaseException:
        await server.close()
        raise
    return server


async def serve_api_notifications(
    listener: RuntimeNotificationListener,
    stop_event,
    handler: Callable[[dict[str, object]], Awaitable[None]],
) -> None:
    await _serve_postgres_notifications(listener, stop_event, handler)


async def _serve_postgres_notifications(
    listener: RuntimeNotificationListener,
    stop_event,
    handler: Callable[[dict[str, object]], Awaitable[None]],
) -> None:
    wake = listener._wake
    if wake is None:
        raise RuntimeError('PostgreSQL runtime notification listener has not started')
    stop_task = asyncio.create_task(stop_event.wait())
    wake_task: asyncio.Task[bool] | None = None
    try:
        while not stop_event.is_set():
            wake.clear()
            if listener._messages.empty():
                if not listener._messages.empty():
                    continue
                wake_task = asyncio.create_task(wake.wait())
                done, _pending = await asyncio.wait({stop_task, wake_task}, return_when=asyncio.FIRST_COMPLETED)
                if stop_task in done:
                    return
                wake_task = None

            for _ in range(100):
                try:
                    payload = listener._messages.get_nowait()
                except queue.Empty:
                    break
                try:
                    await handler(payload)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception('Runtime notification handler failed kind=%s', payload.get('kind', '-'))
            if not listener._messages.empty():
                await asyncio.sleep(0)
                wake.set()
    finally:
        stop_task.cancel()
        pending_tasks = [stop_task]
        if wake_task is not None and not wake_task.done():
            wake_task.cancel()
            pending_tasks.append(wake_task)
        await asyncio.gather(*pending_tasks, return_exceptions=True)


def _notify_payload(notify: Notify) -> str:
    return notify.payload


async def stop_api_server(
    server: RuntimeNotificationListener | None,
    *,
    listener: ListenerKind = RuntimeListenerKind.API,
) -> None:
    del listener
    if server is None:
        return
    await server.close()


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
            'source_pid': os.getpid(),
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
