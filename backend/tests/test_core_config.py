import os
import tempfile
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import Settings


def _set_isolated_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data_dir: Path | None = None) -> Path:
    env_file = tmp_path / '.env'
    env_file.write_text('', encoding='utf-8')
    resolved_data_dir = data_dir or (tmp_path / 'data')
    monkeypatch.setenv('DATA_DIR', str(resolved_data_dir))
    monkeypatch.setenv('ENV_FILE', str(env_file))
    return resolved_data_dir


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
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('PUBLIC_IDB_DEBUG', 'false')

        settings = Settings()

        assert settings.debug is False
        assert settings.database_url == f'sqlite:///{settings.data_dir / "app.db"}'
        assert settings.data_dir.exists()
        assert settings.upload_chunk_size == 5 * 1024 * 1024
        assert settings.job_timeout == 300
        assert settings.engine_idle_timeout == 60
        assert settings.engine_pooling_interval == 30
        assert settings.lock_ttl_seconds == 30
        assert settings.lock_heartbeat_interval_seconds == 10
        assert settings.public_idb_debug is False
        assert settings.auth_required is False
        assert settings.prod_mode_enabled is False

    def test_custom_settings_from_env(self, monkeypatch, tmp_path):
        data_dir = tmp_path / 'data'
        _set_isolated_settings_env(monkeypatch, tmp_path, data_dir)
        monkeypatch.setenv('DEBUG', 'true')
        monkeypatch.setenv('PORT', '8123')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///./test.db')
        monkeypatch.setenv('DATA_DIR', str(data_dir))
        monkeypatch.setenv('DEFAULT_NAMESPACE', 'acme')
        monkeypatch.setenv('UPLOAD_CHUNK_SIZE', '2000000')
        monkeypatch.setenv('JOB_TIMEOUT', '3600')
        monkeypatch.setenv('PUBLIC_IDB_DEBUG', 'true')

        settings = Settings()

        assert settings.debug is True
        assert settings.port == 8123
        # database_url is always derived from data_dir, ignoring the env var
        assert settings.database_url == f'sqlite:///{data_dir / "app.db"}'
        assert settings.data_dir == data_dir
        assert settings.default_namespace == 'acme'
        assert settings.upload_chunk_size == 2000000
        assert settings.job_timeout == 3600
        assert settings.public_idb_debug is True

    def test_polars_settings(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('POLARS_MAX_THREADS', '8')
        monkeypatch.setenv('POLARS_STREAMING_CHUNK_SIZE', '100000')

        settings = Settings()

        assert settings.polars_max_threads == 8
        assert settings.polars_streaming_chunk_size == 100000

    def test_cors_settings(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173')

        settings = Settings()

        assert settings.cors_origins == 'http://localhost:3000,http://localhost:5173'
        assert 'http://localhost:3000' in settings.cors_origins_list
        assert 'http://localhost:5173' in settings.cors_origins_list

    def test_cors_default(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        settings = Settings()

        assert settings.cors_origins is not None
        assert len(settings.cors_origins_list) > 0

    def test_database_url_always_derived_from_data_dir(self, monkeypatch, tmp_path):
        """database_url is always derived from data_dir regardless of DATABASE_URL env var."""
        data_dir = tmp_path / 'data'
        _set_isolated_settings_env(monkeypatch, tmp_path, data_dir)
        monkeypatch.setenv('DATABASE_URL', 'invalid-url')
        monkeypatch.setenv('DATA_DIR', str(data_dir))
        settings = Settings()
        assert settings.database_url == f'sqlite:///{data_dir / "app.db"}'

    def test_negative_timeout_values(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
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

    def test_port_must_be_in_valid_range(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('PORT', '0')

        with pytest.raises(ValidationError, match='port must be >= 1'):
            Settings()

        monkeypatch.setenv('PORT', '65536')

        with pytest.raises(ValidationError, match='port must be <= 65535'):
            Settings()

    def test_directory_paths_are_path_objects(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        settings = Settings()

        assert isinstance(settings.data_dir, Path)

    def test_empty_env_file_uses_stable_default_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv('DATA_DIR', raising=False)
        empty_env = tmp_path / '.env'
        empty_env.write_text('', encoding='utf-8')
        monkeypatch.setenv('ENV_FILE', str(empty_env))
        monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))

        first = Settings()
        second = Settings()

        assert first.data_dir == tmp_path / 'data-forge'
        assert first.data_dir == second.data_dir
        assert first.data_dir.exists()
        assert second.database_url == f'sqlite:///{second.data_dir / "app.db"}'

    def test_logging_level(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('LOG_LEVEL', 'DEBUG')

        settings = Settings()

        assert settings.log_level == 'debug'

    def test_default_logging_level(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        settings = Settings()

        assert settings.log_level == 'info'

    def test_default_log_sqlite_paths(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        settings = Settings()

        assert 'logs' in str(settings.log_sqlite_path)

    def test_worker_settings(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('WORKERS', '4')

        settings = Settings()

        assert settings.workers == 4

    def test_settings_validation(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        settings = Settings()

        assert settings.app_name == 'Data-Forge Analysis Platform'
        assert settings.app_version == '1.0.0'

    def test_warns_when_auth_required_without_encryption_key(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('AUTH_REQUIRED', 'true')
        monkeypatch.delenv('SETTINGS_ENCRYPTION_KEY', raising=False)

        with pytest.warns(UserWarning, match='SETTINGS_ENCRYPTION_KEY is empty while AUTH_REQUIRED=True'):
            Settings()

    def test_no_warning_when_auth_disabled_without_encryption_key(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('AUTH_REQUIRED', 'false')
        monkeypatch.delenv('SETTINGS_ENCRYPTION_KEY', raising=False)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            settings = Settings()

        assert settings.auth_required is False
        assert not caught

    def test_rejects_lock_heartbeat_not_less_than_ttl(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('LOCK_TTL_SECONDS', '10')
        monkeypatch.setenv('LOCK_HEARTBEAT_INTERVAL_SECONDS', '10')

        with pytest.raises(ValidationError, match='lock_heartbeat_interval_seconds must be < lock_ttl_seconds'):
            Settings()
