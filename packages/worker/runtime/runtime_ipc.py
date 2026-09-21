from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import psycopg
from psycopg import Notify

from runtime.config import settings

logger = logging.getLogger(__name__)

_CHANNEL = "runtime_events"


def _conninfo() -> str:
    database_url = settings.database_url
    if not database_url:
        raise RuntimeError("Runtime IPC database URL is not configured")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def start_runtime_listener() -> psycopg.Connection:
    connection = psycopg.connect(_conninfo(), autocommit=True)
    connection.execute(f"LISTEN {_CHANNEL}")
    return connection


def stop_runtime_listener(connection: psycopg.Connection | None) -> None:
    if connection is not None and not connection.closed:
        connection.close()


def _connection_socket(connection: psycopg.Connection) -> int:
    fileno = getattr(connection, "fileno", None)
    if callable(fileno):
        socket_fd = fileno()
        if isinstance(socket_fd, int) and socket_fd >= 0:
            return socket_fd
    pgconn = getattr(connection, "pgconn", None)
    socket_fd = getattr(pgconn, "socket", None)
    if isinstance(socket_fd, int) and socket_fd >= 0:
        return socket_fd
    raise RuntimeError("Unable to determine Postgres runtime IPC socket")


async def _wait_for_socket(connection: psycopg.Connection, stop_event: asyncio.Event) -> bool:
    loop = asyncio.get_running_loop()
    ready = asyncio.Event()
    socket_fd = _connection_socket(connection)

    def mark_ready() -> None:
        ready.set()

    loop.add_reader(socket_fd, mark_ready)
    ready_task = asyncio.create_task(ready.wait())
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, pending = await asyncio.wait({ready_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return ready_task in done
    finally:
        loop.remove_reader(socket_fd)


async def serve_runtime_notifications(
    connection: psycopg.Connection,
    stop_event: asyncio.Event,
    handler: Callable[[dict[str, object]], Awaitable[None]],
) -> None:
    while not stop_event.is_set():
        try:
            if not await _wait_for_socket(connection, stop_event):
                return
            notifications = list(connection.notifies(timeout=0, stop_after=100))
        except asyncio.CancelledError:
            raise
        except psycopg.Error as exc:
            logger.warning("Worker runtime notification listener stopped: %s", exc)
            return
        for notification in notifications:
            try:
                payload = json.loads(_notification_payload(notification))
            except json.JSONDecodeError as exc:
                logger.debug("Ignoring malformed worker runtime notification: %s", exc)
                continue
            if isinstance(payload, dict):
                await handler(payload)


def _notification_payload(notification: Notify) -> str:
    return notification.payload
