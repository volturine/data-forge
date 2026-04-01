"""Tests for health check endpoints."""

from core.config import settings


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health_check(self, client):
        """Test basic health check endpoint."""
        response = client.get('/api/v1/health/')

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert 'version' in data

    def test_health_liveness(self, client):
        """Test Kubernetes liveness probe."""
        response = client.get('/health/ready')

        assert response.status_code == 200
        data = response.json()
        assert 'status' in data

    def test_health_readiness(self, client):
        """Test Kubernetes readiness probe."""
        response = client.get('/health/ready')

        assert response.status_code == 200

    def test_health_startup(self, client):
        """Test Kubernetes startup probe."""
        response = client.get('/health/startup')

        assert response.status_code == 200
        data = response.json()
        assert 'status' in data

    def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = client.get('/')

        assert response.status_code == 200
        data = response.json()
        assert 'message' in data or 'version' in data or 'status' in data

    def test_health_check_response_time(self, client):
        """Test that health check responds quickly."""
        import time

        start = time.time()
        response = client.get('/api/v1/health/')
        duration = time.time() - start

        assert response.status_code == 200
        assert duration < 1.0

    def test_multiple_health_checks(self, client):
        """Test multiple consecutive health checks."""
        for _ in range(5):
            response = client.get('/api/v1/health/')
            assert response.status_code == 200

    def test_health_check_headers(self, client):
        """Test health check response headers."""
        response = client.get('/api/v1/health/')

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
