import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack

import httpx
import pytest

from backend_core import http
from backend_core.api_execution_budget import run_api_blocking


def test_sync_client_has_default_timeout():
    client = http.get_client()
    try:
        assert client.timeout.connect == http.DEFAULT_TIMEOUT.connect
        assert client.timeout.read == http.DEFAULT_TIMEOUT.read
        assert http.DEFAULT_TIMEOUT.read == 30.0
    finally:
        asyncio.run(http.close_clients())


def test_async_client_has_default_timeout():
    async def _get():
        return http.get_async_client()

    client = asyncio.run(_get())
    try:
        assert client.timeout.connect == http.DEFAULT_TIMEOUT.connect
        assert client.timeout.read == http.DEFAULT_TIMEOUT.read
    finally:
        asyncio.run(http.close_clients())


def test_async_client_is_prewarmed_off_loop_and_reused_on_owner_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    original_async_client = httpx.AsyncClient
    constructed_thread_ids: list[int] = []
    constructor_timeouts: list[httpx.Timeout] = []
    request_thread_ids: list[int] = []

    def handle_request(_request: httpx.Request) -> httpx.Response:
        request_thread_ids.append(threading.get_ident())
        return httpx.Response(200, json={'ok': True})

    def create_async_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
        constructed_thread_ids.append(threading.get_ident())
        constructor_timeouts.append(timeout)
        return original_async_client(transport=httpx.MockTransport(handle_request), timeout=timeout)

    monkeypatch.setattr(httpx, 'AsyncClient', create_async_client)

    async def _exercise() -> None:
        loop = asyncio.get_running_loop()
        loop_thread_id = threading.get_ident()
        client: httpx.AsyncClient | None = None
        try:
            await run_api_blocking(http.prewarm_async_client, loop)
            client = http.get_async_client()
            response = await client.get('https://example.test/warmup')

            assert response.json() == {'ok': True}
            assert len(constructed_thread_ids) == 1
            assert constructed_thread_ids[0] != loop_thread_id
            assert constructor_timeouts == [http.DEFAULT_TIMEOUT]
            assert request_thread_ids == [loop_thread_id]
            assert http.get_async_client() is client
        finally:
            await http.close_clients()

        assert client is not None and client.is_closed

    asyncio.run(_exercise())


def test_cancelled_async_client_prewarm_drains_before_client_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend_core import application
    from backend_core.api_execution_budget import ApiDatabaseBudget

    original_async_client = httpx.AsyncClient
    constructor_started = threading.Event()
    release_constructor = threading.Event()
    clients: list[httpx.AsyncClient] = []

    def create_async_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
        constructor_started.set()
        if not release_constructor.wait(timeout=5):
            raise TimeoutError('cancelled HTTP client prewarm was not released')
        client = original_async_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
            timeout=timeout,
        )
        clients.append(client)
        return client

    async def skip_executor_prewarm(_executor: ThreadPoolExecutor, _workers: int) -> None:
        return None

    monkeypatch.setattr(httpx, 'AsyncClient', create_async_client)
    monkeypatch.setattr(application, '_api_thread_budget', lambda: ApiDatabaseBudget(3, 1, 1, 1))
    monkeypatch.setattr(application, '_configure_sync_thread_capacity', lambda: 1)
    monkeypatch.setattr(application, '_guard_runtime_workers', lambda _workers: None)
    monkeypatch.setattr(application, '_prewarm_executor', skip_executor_prewarm)
    monkeypatch.setattr(application, '_resolve_uvicorn_workers', lambda: 1)

    async def _exercise() -> None:
        loop = asyncio.get_running_loop()
        try:
            async with AsyncExitStack() as cleanup:
                startup = asyncio.create_task(application._start_api_lifespan(application.app, cleanup))
                release_scheduled = False
                try:
                    deadline = loop.time() + 2
                    while not constructor_started.is_set():
                        if startup.done():
                            await startup
                        if loop.time() >= deadline:
                            raise AssertionError('HTTP client constructor did not start during lifespan startup')
                        await asyncio.sleep(0.01)

                    startup.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await startup
                    loop.call_later(0.05, release_constructor.set)
                    release_scheduled = True
                finally:
                    if not startup.done():
                        startup.cancel()
                        await asyncio.gather(startup, return_exceptions=True)
                    if not release_scheduled:
                        release_constructor.set()

            assert len(clients) == 1
            assert clients[0].is_closed
        finally:
            await http.close_clients()

    asyncio.run(_exercise())
