import os
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend_core.config import Settings


def _set_isolated_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data_dir: Path | None = None) -> Path:
    env_file = tmp_path / '.env'
    env_file.write_text('', encoding='utf-8')
    resolved_data_dir = data_dir or (tmp_path / 'data')
    monkeypatch.setenv('DATA_DIR', str(resolved_data_dir))
    monkeypatch.setenv('ENV_FILE', str(env_file))
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:pass@host:5432/db')
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
                'UPLOAD_MAX_FILE_SIZE_BYTES',
                'LOG_LEVEL',
                'LOG_ICEBERG_PATH',
                'PUBLIC_IDB_DEBUG',
                'WORKERS',
                'COMPUTE_WORKERS',
            ]:
                monkeypatch.delenv(key, raising=False)
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('PUBLIC_IDB_DEBUG', 'false')

        settings = Settings()

        assert settings.debug is False
        assert settings.database_url == 'postgresql+psycopg://user:pass@host:5432/db'
        assert settings.data_dir.exists()
        assert settings.upload_max_file_size_bytes == 2 * 1024 * 1024 * 1024
        assert settings.lock_ttl_seconds == 30
        assert settings.lock_heartbeat_interval_seconds == 10
        assert settings.public_idb_debug is False
        assert settings.sql_echo is False
        assert settings.prod_mode_enabled is False
        assert settings.compute_workers == 14
        assert settings.distributed_runtime_enabled is False
        assert settings.log_level == 'info'
        assert settings.log_flush_interval_seconds == 5
        assert settings.cors_origins is not None
        assert len(settings.cors_origins_list) > 0
        assert settings.app_name == 'Data-Forge Analysis Platform'
        assert settings.app_version == '1.0.0'

    @pytest.mark.parametrize(
        ('env', 'expected'),
        [
            pytest.param({'COMPUTE_WORKERS': '32'}, {'compute_workers': 32}, id='compute-workers'),
            pytest.param({'SQL_ECHO': 'true'}, {'sql_echo': True}, id='sql-echo'),
            # App config names must not collide with Polars' native env.
            pytest.param(
                {'POLARS_CORES_AVAILABLE': '8', 'POLARS_STREAMING_CHUNK_SIZE': '100000'},
                {'polars_cores_available': 8, 'polars_streaming_chunk_size': 100000},
                id='polars',
            ),
            pytest.param({'POLARS_CORES_AVAILABLE': '0'}, {'polars_cores_available': 0}, id='polars-cores-all-host-cores'),
            pytest.param({'PERSIST_PREVIEW_RUNS': 'false'}, {'persist_preview_runs': False}, id='preview-run-persistence'),
            pytest.param({'LOG_LEVEL': 'DEBUG'}, {'log_level': 'debug'}, id='logging-level'),
            pytest.param({'WORKERS': '4'}, {'workers': 4}, id='workers'),
            pytest.param(
                {'DISTRIBUTED_RUNTIME_ENABLED': 'true', 'DATABASE_POOL_SIZE': '100', 'DATABASE_MAX_OVERFLOW': '7', 'DATABASE_POOL_TIMEOUT': '12'},
                {'distributed_runtime_enabled': True, 'database_pool_size': 100, 'database_max_overflow': 7, 'database_pool_timeout': 12},
                id='distributed-runtime-and-pool',
            ),
        ],
    )
    def test_env_var_sets_field(self, monkeypatch, tmp_path, env, expected):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        for name, value in env.items():
            monkeypatch.setenv(name, value)

        settings = Settings()

        assert {field: getattr(settings, field) for field in expected} == expected

    @pytest.mark.parametrize(
        ('value', 'message'),
        [('0', 'COMPUTE_WORKERS\n  Input should be greater than or equal to 1'), ('101', 'COMPUTE_WORKERS\n  Input should be less than or equal to 100')],
    )
    def test_compute_workers_must_be_between_one_and_one_hundred(self, monkeypatch, tmp_path, value, message):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('COMPUTE_WORKERS', value)

        with pytest.raises(ValidationError, match=message):
            Settings()

    def test_custom_settings_from_env(self, monkeypatch, tmp_path):
        data_dir = tmp_path / 'data'
        _set_isolated_settings_env(monkeypatch, tmp_path, data_dir)
        monkeypatch.setenv('DEBUG', 'true')
        monkeypatch.setenv('PORT', '8123')
        monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:pass@host:5433/test')
        monkeypatch.setenv('DATA_DIR', str(data_dir))
        monkeypatch.setenv('DEFAULT_NAMESPACE', 'acme')
        monkeypatch.setenv('PUBLIC_IDB_DEBUG', 'true')

        settings = Settings()

        assert settings.debug is True
        assert settings.port == 8123
        assert settings.database_url == 'postgresql+psycopg://user:pass@host:5433/test'
        assert settings.data_dir == data_dir
        assert settings.default_namespace == 'acme'
        assert settings.public_idb_debug is True

    def test_cors_settings(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173')

        settings = Settings()

        assert settings.cors_origins == 'http://localhost:3000,http://localhost:5173'
        assert 'http://localhost:3000' in settings.cors_origins_list
        assert 'http://localhost:5173' in settings.cors_origins_list

    def test_database_url_must_be_explicit_postgres(self, monkeypatch, tmp_path):
        data_dir = tmp_path / 'data'
        _set_isolated_settings_env(monkeypatch, tmp_path, data_dir)
        monkeypatch.delenv('DATABASE_URL', raising=False)
        monkeypatch.setenv('DATA_DIR', str(data_dir))

        with pytest.raises(ValidationError, match='DATABASE_URL must be set to a PostgreSQL connection string'):
            Settings()

    def test_database_url_rejects_non_postgres_values(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('DATABASE_URL', 'mysql://user:pass@host/db')

        with pytest.raises(ValidationError, match='DATABASE_URL must be a PostgreSQL connection string'):
            Settings()

    def test_negative_scheduler_interval_rejected(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('SCHEDULER_CHECK_INTERVAL', '-100')

        with pytest.raises(ValidationError, match='SCHEDULER_CHECK_INTERVAL\n  Input should be greater than or equal to 1'):
            Settings()

    def test_port_must_be_in_valid_range(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('PORT', '0')

        with pytest.raises(ValidationError, match='PORT\n  Input should be greater than or equal to 1'):
            Settings()

        monkeypatch.setenv('PORT', '65536')

        with pytest.raises(ValidationError, match='PORT\n  Input should be less than or equal to 65535'):
            Settings()

    def test_upload_max_file_size_matches_data_plane_ceiling(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('UPLOAD_MAX_FILE_SIZE_BYTES', str(2 * 1024 * 1024 * 1024))

        settings = Settings()
        assert settings.upload_max_file_size_bytes == 2 * 1024 * 1024 * 1024

        monkeypatch.setenv('UPLOAD_MAX_FILE_SIZE_BYTES', str(2 * 1024 * 1024 * 1024 + 1))
        with pytest.raises(ValidationError, match='UPLOAD_MAX_FILE_SIZE_BYTES\n  Input should be less than or equal to 2147483648'):
            Settings()

        monkeypatch.setenv('UPLOAD_MAX_FILE_SIZE_BYTES', '0')
        settings = Settings()
        assert settings.upload_max_file_size_bytes == 0

    def test_empty_env_file_uses_stable_default_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv('DATA_DIR', raising=False)
        monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://dataforge:dataforge@127.0.0.1:5432/dataforge')
        empty_env = tmp_path / '.env'
        empty_env.write_text('', encoding='utf-8')
        monkeypatch.setenv('ENV_FILE', str(empty_env))
        monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))

        first = Settings()
        second = Settings()

        assert first.data_dir == tmp_path / 'data-forge'
        assert first.data_dir == second.data_dir
        assert first.data_dir.exists()
        assert second.database_url == 'postgresql+psycopg://dataforge:dataforge@127.0.0.1:5432/dataforge'

    def test_trusted_proxy_hops_must_be_non_negative(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('TRUSTED_PROXY_HOPS', '-1')

        with pytest.raises(ValidationError, match='TRUSTED_PROXY_HOPS\n  Input should be greater than or equal to 0'):
            Settings()

    def test_rejects_lock_heartbeat_not_less_than_ttl(self, monkeypatch, tmp_path):
        _set_isolated_settings_env(monkeypatch, tmp_path)
        monkeypatch.setenv('LOCK_TTL_SECONDS', '10')
        monkeypatch.setenv('LOCK_HEARTBEAT_INTERVAL_SECONDS', '10')

        with pytest.raises(ValidationError, match='lock_heartbeat_interval_seconds must be < lock_ttl_seconds'):
            Settings()
