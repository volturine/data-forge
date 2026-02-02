"""Tests for core configuration module."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import Settings


class TestSettings:
    """Test configuration settings."""

    def test_default_settings(self, monkeypatch):
        """Test default configuration values."""
        for key in os.environ:
            if key.startswith('POLARS_') or key in [
                'DEBUG',
                'DATABASE_URL',
                'UPLOAD_DIR',
                'MAX_UPLOAD_SIZE',
                'ENGINE_IDLE_TIMEOUT',
                'ENGINE_POOLING_INTERVAL',
                'JOB_TIMEOUT',
                'LOG_LEVEL',
                'WORKERS',
            ]:
                monkeypatch.delenv(key, raising=False)

        settings = Settings()

        assert settings.debug is False
        assert settings.database_url == 'sqlite+aiosqlite:///./database/app.db'
        assert 'uploads' in str(settings.upload_dir)
        assert settings.max_upload_size == 10 * 1024 * 1024 * 1024
        assert settings.job_timeout == 300
        assert settings.engine_idle_timeout == 300
        assert settings.engine_pooling_interval == 5

    def test_custom_settings_from_env(self, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv('DEBUG', 'true')
        monkeypatch.setenv('DATABASE_URL', 'sqlite+aiosqlite:///./test.db')
        monkeypatch.setenv('UPLOAD_DIR', '/tmp/uploads')
        monkeypatch.setenv('MAX_UPLOAD_SIZE', '50000000')
        monkeypatch.setenv('JOB_TIMEOUT', '3600')

        settings = Settings()

        assert settings.debug is True
        assert settings.database_url == 'sqlite+aiosqlite:///./test.db'
        assert settings.upload_dir == Path('/tmp/uploads')
        assert settings.max_upload_size == 50000000
        assert settings.job_timeout == 3600

    def test_polars_settings(self, monkeypatch):
        """Test Polars-specific configuration."""
        monkeypatch.setenv('POLARS_MAX_THREADS', '8')
        monkeypatch.setenv('POLARS_STREAMING_CHUNK_SIZE', '100000')

        settings = Settings()

        assert settings.polars_max_threads == 8
        assert settings.polars_streaming_chunk_size == 100000

    def test_cors_settings(self, monkeypatch):
        """Test CORS configuration."""
        monkeypatch.setenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173')

        settings = Settings()

        assert settings.cors_origins == 'http://localhost:3000,http://localhost:5173'
        assert 'http://localhost:3000' in settings.cors_origins_list
        assert 'http://localhost:5173' in settings.cors_origins_list

    def test_cors_default(self):
        """Test default CORS configuration."""
        settings = Settings()

        assert settings.cors_origins is not None
        assert len(settings.cors_origins_list) > 0

    def test_invalid_database_url(self, monkeypatch):
        """Test validation of invalid database URL."""
        monkeypatch.setenv('DATABASE_URL', 'invalid-url')

        settings = Settings()
        assert settings.database_url == 'invalid-url'

    def test_negative_timeout_values(self, monkeypatch):
        """Test that negative timeout values are rejected."""
        monkeypatch.setenv('ENGINE_IDLE_TIMEOUT', '-100')

        with pytest.raises(ValidationError, match='engine_idle_timeout must be positive'):
            Settings()

        monkeypatch.setenv('ENGINE_IDLE_TIMEOUT', '300')
        monkeypatch.setenv('JOB_TIMEOUT', '-50')

        with pytest.raises(ValidationError, match='job_timeout must be positive'):
            Settings()

        monkeypatch.setenv('JOB_TIMEOUT', '300')
        monkeypatch.setenv('ENGINE_POOLING_INTERVAL', '0')

        with pytest.raises(ValidationError, match='engine_pooling_interval must be positive'):
            Settings()

    def test_directory_paths_are_path_objects(self):
        """Test that directory settings are Path objects."""
        settings = Settings()

        assert isinstance(settings.upload_dir, Path)
        assert isinstance(settings.exports_dir, Path)

    def test_logging_level(self, monkeypatch):
        """Test logging level configuration."""
        monkeypatch.setenv('LOG_LEVEL', 'DEBUG')

        settings = Settings()

        assert settings.log_level == 'debug'

    def test_default_logging_level(self):
        """Test default logging level."""
        settings = Settings()

        assert settings.log_level == 'info'

    def test_worker_settings(self, monkeypatch):
        """Test worker configuration."""
        monkeypatch.setenv('WORKERS', '4')

        settings = Settings()

        assert settings.workers == 4

    def test_settings_validation(self):
        """Test that settings validate correctly."""
        settings = Settings()

        assert settings.app_name == 'Polars-FastAPI-Svelte Analysis Platform'
        assert settings.app_version == '1.0.0'
