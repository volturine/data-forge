from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

import httpx

_SYNC_CLIENT: httpx.Client | None = None
_SYNC_CLIENT_LOCK = Lock()

_ASYNC_CLIENTS: dict[int, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}
_ASYNC_CLIENTS_LOCK = Lock()


def get_client() -> httpx.Client:
    global _SYNC_CLIENT
    with _SYNC_CLIENT_LOCK:
        if _SYNC_CLIENT is None or _SYNC_CLIENT.is_closed:
            _SYNC_CLIENT = httpx.Client()
        return _SYNC_CLIENT


def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    return get_client().request(method, url, **kwargs)


def get(url: str, **kwargs: Any) -> httpx.Response:
    return get_client().get(url, **kwargs)


def post(url: str, **kwargs: Any) -> httpx.Response:
    return get_client().post(url, **kwargs)


def get_async_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    with _ASYNC_CLIENTS_LOCK:
        existing = _ASYNC_CLIENTS.get(loop_id)
        if existing is not None:
            existing_loop, client = existing
            if existing_loop is loop and not client.is_closed:
                return client
        client = httpx.AsyncClient()
        _ASYNC_CLIENTS[loop_id] = (loop, client)
        return client


async def close_clients() -> None:
    global _SYNC_CLIENT

    with _SYNC_CLIENT_LOCK:
        sync_client = _SYNC_CLIENT
        _SYNC_CLIENT = None

    with _ASYNC_CLIENTS_LOCK:
        async_clients = list(_ASYNC_CLIENTS.values())
        _ASYNC_CLIENTS.clear()

    if sync_client is not None and not sync_client.is_closed:
        sync_client.close()

    for _, client in async_clients:
        if client.is_closed:
            continue
        await client.aclose()
