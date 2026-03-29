import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import Settings


class TestSettings:
    def test_default_settings(self, monkeypatch, tmp_path):
        keys = list(os.environ.keys())
        for key in keys:
            if key.startswith('POLARS_') or key in [
                'DEBUG',
                'DATABASE_URL',
                'DATA_DIR',
                'DEFAULT_NAMESPACE',
                'UPLOAD_CHUNK_SIZE',
                'ENGINE_IDLE_TIMEOUT',
                'ENGINE_POOLING_INTERVAL',
                'JOB_TIMEOUT',
                'LOG_LEVEL',
                'LOG_ICEBERG_PATH',
                'PUBLIC_IDB_DEBUG',
                'WORKERS',
            ]:
                monkeypatch.delenv(key, raising=False)
        # Point ENV_FILE to a non-existent path so .env is not loaded
        monkeypatch.setenv('ENV_FILE', str(tmp_path / 'nonexistent.env'))
        monkeypatch.setenv('PUBLIC_IDB_DEBUG', 'false')

        settings = Settings()

        assert settings.debug is False
        assert settings.database_url == f'sqlite:///{settings.data_dir / "app.db"}'
        assert settings.data_dir.exists()
        assert settings.upload_chunk_size == 5 * 1024 * 1024
        assert settings.job_timeout == 300
        assert settings.engine_idle_timeout == 300
        assert settings.engine_pooling_interval == 30
        assert settings.public_idb_debug is False

    def test_custom_settings_from_env(self, monkeypatch, tmp_path):
        data_dir = tmp_path / 'data'
        monkeypatch.setenv('DEBUG', 'true')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///./test.db')
        monkeypatch.setenv('DATA_DIR', str(data_dir))
        monkeypatch.setenv('DEFAULT_NAMESPACE', 'acme')
        monkeypatch.setenv('UPLOAD_CHUNK_SIZE', '2000000')
        monkeypatch.setenv('JOB_TIMEOUT', '3600')
        monkeypatch.setenv('PUBLIC_IDB_DEBUG', 'true')

        settings = Settings()

        assert settings.debug is True
        # database_url is always derived from data_dir, ignoring the env var
        assert settings.database_url == f'sqlite:///{data_dir / "app.db"}'
        assert settings.data_dir == data_dir
        assert settings.default_namespace == 'acme'
        assert settings.upload_chunk_size == 2000000
        assert settings.job_timeout == 3600
        assert settings.public_idb_debug is True

    def test_polars_settings(self, monkeypatch):
        monkeypatch.setenv('POLARS_MAX_THREADS', '8')
        monkeypatch.setenv('POLARS_STREAMING_CHUNK_SIZE', '100000')

        settings = Settings()

        assert settings.polars_max_threads == 8
        assert settings.polars_streaming_chunk_size == 100000

    def test_cors_settings(self, monkeypatch):
        monkeypatch.setenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173')

        settings = Settings()

        assert settings.cors_origins == 'http://localhost:3000,http://localhost:5173'
        assert 'http://localhost:3000' in settings.cors_origins_list
        assert 'http://localhost:5173' in settings.cors_origins_list

    def test_cors_default(self):
        settings = Settings()

        assert settings.cors_origins is not None
        assert len(settings.cors_origins_list) > 0

    def test_database_url_always_derived_from_data_dir(self, monkeypatch, tmp_path):
        """database_url is always derived from data_dir regardless of DATABASE_URL env var."""
        data_dir = tmp_path / 'data'
        monkeypatch.setenv('DATABASE_URL', 'invalid-url')
        monkeypatch.setenv('DATA_DIR', str(data_dir))
        settings = Settings()
        assert settings.database_url == f'sqlite:///{data_dir / "app.db"}'

    def test_negative_timeout_values(self, monkeypatch):
        monkeypatch.setenv('ENGINE_IDLE_TIMEOUT', '-100')

        with pytest.raises(ValidationError, match='engine_idle_timeout must be >= 1'):
            Settings()

        monkeypatch.setenv('ENGINE_IDLE_TIMEOUT', '300')
        monkeypatch.setenv('JOB_TIMEOUT', '-50')

        with pytest.raises(ValidationError, match='job_timeout must be >= 1'):
            Settings()

        monkeypatch.setenv('JOB_TIMEOUT', '300')
        monkeypatch.setenv('ENGINE_POOLING_INTERVAL', '0')

        with pytest.raises(ValidationError, match='engine_pooling_interval must be >= 1'):
            Settings()

    def test_directory_paths_are_path_objects(self):
        settings = Settings()

        assert isinstance(settings.data_dir, Path)

    def test_empty_env_file_uses_stable_default_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv('DATA_DIR', raising=False)
        empty_env = tmp_path / '.env'
        empty_env.write_text('', encoding='utf-8')
        monkeypatch.setenv('ENV_FILE', str(empty_env))

        first = Settings()
        second = Settings()

        assert first.data_dir == second.data_dir
        assert first.data_dir.exists()
        assert second.database_url == f'sqlite:///{second.data_dir / "app.db"}'

    def test_logging_level(self, monkeypatch):
        monkeypatch.setenv('LOG_LEVEL', 'DEBUG')

        settings = Settings()

        assert settings.log_level == 'debug'

    def test_default_logging_level(self):
        settings = Settings()

        assert settings.log_level == 'info'

    def test_default_log_sqlite_paths(self):
        settings = Settings()

        assert 'logs' in str(settings.log_sqlite_path)

    def test_worker_settings(self, monkeypatch):
        monkeypatch.setenv('WORKERS', '4')

        settings = Settings()

        assert settings.workers == 4

    def test_settings_validation(self):
        settings = Settings()

        assert settings.app_name == 'Data-Forge Analysis Platform'
        assert settings.app_version == '1.0.0'
