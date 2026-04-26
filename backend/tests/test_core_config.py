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
        assert settings.lock_ttl_seconds == 30
        assert settings.lock_heartbeat_interval_seconds == 10
        assert settings.public_idb_debug is False
        assert settings.auth_required is False
        assert settings.verify_email_address is True
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
        assert settings.database_url == 'sqlite:///./test.db'
        assert settings.data_dir == data_dir
        assert settings.default_namespace == 'acme'
        assert settings.upload_chunk_size == 2000000
        assert settings.job_timeout == 3600
        assert settings.public_idb_debug is True

    def test_verify_email_address_from_env(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('VERIFY_EMAIL_ADDRESS', 'false')

        settings = Settings()

        assert settings.verify_email_address is False

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

    def test_database_url_defaults_from_data_dir_when_empty(self, monkeypatch, tmp_path):
        data_dir = tmp_path / 'data'
        _set_isolated_settings_env(monkeypatch, tmp_path, data_dir)
        monkeypatch.delenv('DATABASE_URL', raising=False)
        monkeypatch.setenv('DATA_DIR', str(data_dir))

        settings = Settings()

        assert settings.database_url == f'sqlite:///{data_dir / "app.db"}'

    def test_database_url_uses_explicit_env_value(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:pass@host:5432/db')

        settings = Settings()

        assert settings.database_url == 'postgresql+psycopg://user:pass@host:5432/db'
        assert settings.is_postgres is True

    def test_distributed_runtime_defaults_disabled(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)

        settings = Settings()

        assert settings.distributed_runtime_enabled is False

    def test_distributed_runtime_and_pool_settings_from_env(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:pass@host:5432/db')
        monkeypatch.setenv('DISTRIBUTED_RUNTIME_ENABLED', 'true')
        monkeypatch.setenv('DATABASE_POOL_SIZE', '15')
        monkeypatch.setenv('DATABASE_MAX_OVERFLOW', '7')
        monkeypatch.setenv('DATABASE_POOL_TIMEOUT', '12')

        settings = Settings()

        assert settings.distributed_runtime_enabled is True
        assert settings.database_pool_size == 15
        assert settings.database_max_overflow == 7
        assert settings.database_pool_timeout == 12

    def test_distributed_runtime_requires_postgres(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('DISTRIBUTED_RUNTIME_ENABLED', 'true')

        with pytest.raises(ValidationError, match='DISTRIBUTED_RUNTIME_ENABLED requires a PostgreSQL DATABASE_URL'):
            Settings()

    def test_distributed_runtime_rejects_embedded_build_worker(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:pass@host:5432/db')
        monkeypatch.setenv('DISTRIBUTED_RUNTIME_ENABLED', 'true')
        monkeypatch.setenv('EMBEDDED_BUILD_WORKER_ENABLED', 'true')

        with pytest.raises(ValidationError, match='EMBEDDED_BUILD_WORKER_ENABLED cannot be enabled'):
            Settings()

    def test_build_worker_process_range_rejects_min_above_max(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('BUILD_WORKER_MIN_PROCESSES', '2')
        monkeypatch.setenv('BUILD_WORKER_MAX_PROCESSES', '1')

        with pytest.raises(ValidationError, match='BUILD_WORKER_MIN_PROCESSES must be <= BUILD_WORKER_MAX_PROCESSES'):
            Settings()

    def test_build_worker_process_range_rejects_max_above_engine_limit(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('MAX_CONCURRENT_ENGINES', '2')
        monkeypatch.setenv('BUILD_WORKER_MAX_PROCESSES', '3')

        with pytest.raises(ValidationError, match='BUILD_WORKER_MAX_PROCESSES must be <= MAX_CONCURRENT_ENGINES'):
            Settings()

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

    def test_rejects_production_auth_without_encryption_key(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('PROD_MODE_ENABLED', 'true')
        monkeypatch.setenv('AUTH_REQUIRED', 'true')
        monkeypatch.delenv('SETTINGS_ENCRYPTION_KEY', raising=False)

        with pytest.raises(ValidationError, match='SETTINGS_ENCRYPTION_KEY must be set'):
            Settings()

    def test_rejects_production_placeholder_default_password(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('PROD_MODE_ENABLED', 'true')
        monkeypatch.setenv('AUTH_REQUIRED', 'true')
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'prod-key')
        monkeypatch.setenv('DEFAULT_USER_PASSWORD', 'ChangeMe123!')

        with pytest.raises(ValidationError, match='DEFAULT_USER_PASSWORD must be changed'):
            Settings()

    def test_trusted_proxy_hops_must_be_non_negative(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('TRUSTED_PROXY_HOPS', '-1')

        with pytest.raises(ValidationError, match='TRUSTED_PROXY_HOPS must be >= 0'):
            Settings()

    def test_rejects_lock_heartbeat_not_less_than_ttl(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('LOCK_TTL_SECONDS', '10')
        monkeypatch.setenv('LOCK_HEARTBEAT_INTERVAL_SECONDS', '10')

        with pytest.raises(ValidationError, match='lock_heartbeat_interval_seconds must be < lock_ttl_seconds'):
            Settings()
