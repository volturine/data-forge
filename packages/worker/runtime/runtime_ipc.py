from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable

import psycopg
from psycopg import AsyncConnection, Notify

from runtime.config import settings

logger = logging.getLogger(__name__)

_CHANNEL = "runtime_events"


class RuntimeNotificationListener:
    """Own the worker LISTEN socket and replace it after a DB disconnect."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection: AsyncConnection | None = connection

    def connection(self) -> AsyncConnection | None:
        return self._connection

    async def replace(self, connection: AsyncConnection | None) -> None:
        previous = self._connection
        self._connection = connection
        if previous is not None and previous is not connection:
            with contextlib.suppress(Exception):
                await previous.close()

    async def close(self) -> None:
        await self.replace(None)


def _conninfo() -> str:
    database_url = settings.database_url
    if not database_url:
        raise RuntimeError("Runtime IPC database URL is not configured")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


async def _open_runtime_listener() -> AsyncConnection:
    connection = await AsyncConnection.connect(_conninfo(), autocommit=True)
    try:
        await connection.execute(f"LISTEN {_CHANNEL}")
    except BaseException:
        with contextlib.suppress(Exception):
            await connection.close()
        raise
    return connection


async def start_runtime_listener() -> RuntimeNotificationListener:
    return RuntimeNotificationListener(await _open_runtime_listener())


async def stop_runtime_listener(connection: RuntimeNotificationListener | None) -> None:
    if connection is not None:
        await connection.close()


async def _wait_for_reconnect(stop_event: asyncio.Event, delay_seconds: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay_seconds)
    except TimeoutError:
        return False
    return True


async def serve_runtime_notifications(
    listener: RuntimeNotificationListener,
    stop_event: asyncio.Event,
    handler: Callable[[dict[str, object]], Awaitable[None]],
) -> None:
    reconnect_delay = 0.25
    while not stop_event.is_set():
        connection = listener.connection()
        if connection is None:
            if await _wait_for_reconnect(stop_event, reconnect_delay):
                return
            try:
                connection = await _open_runtime_listener()
                await listener.replace(connection)
                reconnect_delay = 0.25
                logger.info("Worker runtime notification listener reconnected")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Worker runtime notification listener reconnect failed", exc_info=True)
                reconnect_delay = min(reconnect_delay * 2, 5.0)
                continue
        try:
            notifications_since_yield = 0
            async for notification in connection.notifies(timeout=0.5, stop_after=100):
                notifications_since_yield += 1
                try:
                    payload = json.loads(_notification_payload(notification))
                except json.JSONDecodeError as exc:
                    logger.debug("Ignoring malformed worker runtime notification: %s", exc)
                else:
                    if isinstance(payload, dict):
                        try:
                            await handler(payload)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception("Worker runtime notification handler failed kind=%s", payload.get("kind", "-"))
                if stop_event.is_set():
                    return
                if notifications_since_yield == 64:
                    notifications_since_yield = 0
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except OSError, psycopg.Error:
            logger.warning("Worker runtime notification listener lost its connection; reconnecting", exc_info=True)
            await listener.replace(None)
            reconnect_delay = min(reconnect_delay * 2, 5.0)
            continue


def _notification_payload(notification: Notify) -> str:
    return notification.payload
