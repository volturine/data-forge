"""Tests for process health and readiness endpoints."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend_core.config import settings


class TestHealthEndpoints:
    def test_health_liveness(self, client):
        response = client.get('/health')

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert data['version'] == settings.app_version
        assert data['service'] == settings.app_name

    def test_health_readiness(self, client):
        response = client.get('/health/ready')

        assert response.status_code == 200
        data = response.json()
        assert 'status' in data

    def test_health_startup(self, client):
        response = client.get('/health/startup')

        assert response.status_code == 200
        data = response.json()
        assert 'status' in data

    def test_root_endpoint(self, client):
        response = client.get('/')

        assert response.status_code == 200
        data = response.json()
        assert data['message'] == settings.app_name
        assert data['version'] == settings.app_version

    def test_health_check_response_time(self, client):
        import time

        start = time.time()
        response = client.get('/health')
        duration = time.time() - start

        assert response.status_code == 200
        assert duration < 1.0

    def test_multiple_health_checks(self, client):
        for _ in range(5):
            response = client.get('/health')
            assert response.status_code == 200

    def test_health_check_headers(self, client):
        response = client.get('/health')

        assert response.status_code == 200
        assert 'content-type' in response.headers
        assert 'application/json' in response.headers['content-type']
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['x-xss-protection'] == '0'
        assert response.headers['referrer-policy'] == 'strict-origin-when-cross-origin'
        assert response.headers['permissions-policy'] == 'camera=(), microphone=(), geolocation=()'
        assert response.headers['strict-transport-security'] == 'max-age=63072000; includeSubDomains'

    def test_security_headers_skip_hsts_in_debug(self, client, monkeypatch):
        monkeypatch.setattr(settings, 'debug', True, raising=False)

        response = client.get('/health/startup')

        assert response.status_code == 200
        assert 'strict-transport-security' not in response.headers


def test_readiness_object_store_failure_does_not_expose_exception_detail(monkeypatch) -> None:
    import backend_core.object_store_probe as object_store_probe
    from main import _readiness_checks

    def fail(*, namespace: str | None = None) -> str:
        raise RuntimeError('endpoint http://internal-s3:9000 bucket secret-bucket')

    monkeypatch.setattr(object_store_probe, 'probe_object_store', fail)

    checks, is_ready = _readiness_checks()

    assert is_ready is False
    assert checks['object_store'] == 'error'
    assert 'secret-bucket' not in str(checks)


@pytest.mark.asyncio
async def test_readiness_probe_coalesces_callers_and_survives_one_cancellation() -> None:
    from main import ReadinessProbe

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='readiness-coalescing-test')
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def check() -> tuple[dict[str, str], bool]:
        nonlocal calls
        calls += 1
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError('readiness test was not released')
        return {'database': 'ok'}, True

    probe = ReadinessProbe(executor, check)
    try:
        canceled_waiter = asyncio.create_task(probe.run())
        assert await asyncio.to_thread(started.wait, 1)
        surviving_waiter = asyncio.create_task(probe.run())
        canceled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await canceled_waiter
        release.set()

        assert await surviving_waiter == ({'database': 'ok'}, True)
        assert calls == 1
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)
