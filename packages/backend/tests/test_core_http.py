import asyncio

from backend_core import http


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


def test_callers_can_override_timeout_per_request():
    client = http.get_client()
    try:
        request = client.build_request('GET', 'https://example.com', timeout=5.0)
        assert request.extensions['timeout'] == {'connect': 5.0, 'pool': 5.0, 'read': 5.0, 'write': 5.0}
    finally:
        asyncio.run(http.close_clients())
